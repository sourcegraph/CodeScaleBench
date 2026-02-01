/*
 * HoloCanvas – Wallet Proxy
 * File: services/wallet_proxy/src/adapters/eip1193_adapter.c
 *
 * Description:
 *   Production-quality EIP-1193 adapter used by the Wallet-Proxy micro-service
 *   to interact with browser / mobile wallets (e.g. MetaMask) through the
 *   standard JSON-RPC interface.  The adapter hides transport details,
 *   provides request-ID management, thread-safety, error handling, and
 *   convenience wrappers around common wallet methods (eth_chainId,
 *   eth_accounts, eth_sendTransaction, personal_sign, etc.).
 *
 * Build deps (pkg-config):
 *   libcurl >= 7.29        – network transport
 *   libcjson >= 1.7        – JSON parsing / serialisation
 *
 * Author: HoloCanvas Core Team
 * SPDX-License-Identifier: MIT
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <inttypes.h>

#include <curl/curl.h>
#include <cjson/cJSON.h>

/* ------------------------------------------------------------------------- */
/* Constants & Macros                                                        */
/* ------------------------------------------------------------------------- */

#define EIP1193_DEFAULT_ENDPOINT   "http://127.0.0.1:8545"
#define EIP1193_DEFAULT_TIMEOUT_MS 8000L

/* Helper macro for checked free */
#define SAFE_FREE(p)      \
    do {                  \
        if ((p) != NULL){ \
            free(p);      \
            (p) = NULL;   \
        }                 \
    } while (0)

/* ------------------------------------------------------------------------- */
/* Logging – can be wired into service-wide logger later                     */
/* ------------------------------------------------------------------------- */

static void log_err(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);

    fprintf(stderr, "[EIP-1193][ERR] ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");

    va_end(ap);
}

static void log_dbg(const char *fmt, ...)
{
#ifndef NDEBUG
    va_list ap;
    va_start(ap, fmt);

    fprintf(stdout, "[EIP-1193][DBG] ");
    vfprintf(stdout, fmt, ap);
    fprintf(stdout, "\n");

    va_end(ap);
#else
    (void)fmt;
#endif
}

/* ------------------------------------------------------------------------- */
/* Error codes                                                               */
/* ------------------------------------------------------------------------- */

typedef enum {
    EIP1193_OK = 0,
    EIP1193_ERR_INVALID_ARG    = 1,
    EIP1193_ERR_CURL           = 2,
    EIP1193_ERR_JSON           = 3,
    EIP1193_ERR_RPC            = 4,
    EIP1193_ERR_ALLOC          = 5,
} eip1193_err_t;

/* ------------------------------------------------------------------------- */
/* Internal types                                                            */
/* ------------------------------------------------------------------------- */

typedef struct {
    char            *provider_url;   /* wallet endpoint                       */
    long             timeout_ms;     /* request timeout                       */
    pthread_mutex_t  lock;           /* protects next_request_id              */
    uint64_t         next_request_id;
} eip1193_adapter_t;

typedef struct {
    char *data;
    size_t size;
} mem_buf_t;

/* ------------------------------------------------------------------------- */
/* Static helpers                                                            */
/* ------------------------------------------------------------------------- */

/* CURL write callback to accumulate response body */
static size_t curl_write_cb(void *contents, size_t size, size_t nmemb, void *userp)
{
    size_t realsize = size * nmemb;
    mem_buf_t *mem  = (mem_buf_t *)userp;

    char *ptr = realloc(mem->data, mem->size + realsize + 1);
    if (ptr == NULL)
        return 0; /* will trigger CURLE_WRITE_ERROR */

    mem->data = ptr;
    memcpy(&(mem->data[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->data[mem->size] = '\0';

    return realsize;
}

/* Generates monotonically increasing request-IDs (thread-safe) */
static uint64_t next_request_id(eip1193_adapter_t *adp)
{
    uint64_t id;
    pthread_mutex_lock(&adp->lock);
    id = ++adp->next_request_id;
    pthread_mutex_unlock(&adp->lock);
    return id;
}

/* Serialises a JSON-RPC request and returns heap-allocated char* */
static char *build_rpc_payload(uint64_t id, const char *method, cJSON *params)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;

    cJSON_AddStringToObject(root, "jsonrpc", "2.0");
    cJSON_AddStringToObject(root, "method", method);
    cJSON_AddItemReferenceToObject(root, "params", params ? params : cJSON_CreateArray());
    cJSON_AddNumberToObject(root, "id", (double)id);

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return payload;
}

/* Extracts `"result"` or `"error"` from response JSON */
static eip1193_err_t extract_rpc_result(const char *json_str,
                                        cJSON **result_out,
                                        char **err_msg_out)
{
    cJSON *root = cJSON_Parse(json_str);
    if (!root)
        return EIP1193_ERR_JSON;

    cJSON *err = cJSON_GetObjectItem(root, "error");
    if (err && cJSON_IsObject(err))
    {
        cJSON *msg = cJSON_GetObjectItem(err, "message");
        if (msg && cJSON_IsString(msg))
            *err_msg_out = strdup(msg->valuestring);
        else
            *err_msg_out = strdup("RPC Error (no message)");

        cJSON_Delete(root);
        return EIP1193_ERR_RPC;
    }

    cJSON *res = cJSON_GetObjectItem(root, "result");
    if (!res)
    {
        cJSON_Delete(root);
        return EIP1193_ERR_JSON;
    }

    *result_out = cJSON_Duplicate(res, 1); /* deep copy for caller */
    cJSON_Delete(root);
    return (*result_out) ? EIP1193_OK : EIP1193_ERR_ALLOC;
}

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

/* Creates and initialises an adapter instance */
eip1193_adapter_t *eip1193_adapter_create(const char *provider_url, long timeout_ms)
{
    if (!provider_url)
        provider_url = EIP1193_DEFAULT_ENDPOINT;

    eip1193_adapter_t *adp = calloc(1, sizeof(*adp));
    if (!adp)
        return NULL;

    adp->provider_url = strdup(provider_url);
    if (!adp->provider_url)
    {
        free(adp);
        return NULL;
    }

    adp->timeout_ms      = (timeout_ms <= 0) ? EIP1193_DEFAULT_TIMEOUT_MS : timeout_ms;
    adp->next_request_id = 0;
    pthread_mutex_init(&adp->lock, NULL);

    /* Global initialisation of libcurl – safe to call multiple times */
    curl_global_init(CURL_GLOBAL_DEFAULT);

    log_dbg("Adapter created for %s (timeout = %ld ms)", adp->provider_url, adp->timeout_ms);
    return adp;
}

/* Destroys adapter and releases resources */
void eip1193_adapter_destroy(eip1193_adapter_t *adp)
{
    if (!adp) return;

    SAFE_FREE(adp->provider_url);
    pthread_mutex_destroy(&adp->lock);
    SAFE_FREE(adp);

    curl_global_cleanup();
}

/*
 * Core request method.
 *   params      – borrowed reference; you may pass NULL (will send empty array)
 *   result_out  – deep-copied cJSON* on success (caller frees using cJSON_Delete)
 */
eip1193_err_t eip1193_adapter_request(eip1193_adapter_t *adp,
                                      const char *method,
                                      cJSON *params,
                                      cJSON **result_out)
{
    if (!adp || !method || !result_out)
        return EIP1193_ERR_INVALID_ARG;

    *result_out = NULL;
    eip1193_err_t status  = EIP1193_OK;
    char         *payload = NULL;
    CURL         *curl    = NULL;
    struct curl_slist *headers = NULL;
    mem_buf_t      resp_buf    = {0};

    uint64_t id = next_request_id(adp);
    payload = build_rpc_payload(id, method, params);
    if (!payload)
        return EIP1193_ERR_ALLOC;

    curl = curl_easy_init();
    if (!curl)
    {
        status = EIP1193_ERR_CURL;
        goto cleanup;
    }

    /* Prepare headers */
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, adp->provider_url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(payload));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, adp->timeout_ms);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp_buf);

    CURLcode rc = curl_easy_perform(curl);
    if (rc != CURLE_OK)
    {
        log_err("CURL failed: %s", curl_easy_strerror(rc));
        status = EIP1193_ERR_CURL;
        goto cleanup;
    }

    char *rpc_err_msg = NULL;
    status = extract_rpc_result(resp_buf.data, result_out, &rpc_err_msg);
    if (status != EIP1193_OK)
    {
        if (rpc_err_msg)
        {
            log_err("RPC Error: %s", rpc_err_msg);
            free(rpc_err_msg);
        }
        else if (status == EIP1193_ERR_JSON)
        {
            log_err("Invalid JSON in RPC response");
        }
    }

cleanup:
    if (headers)      curl_slist_free_all(headers);
    if (curl)         curl_easy_cleanup(curl);
    SAFE_FREE(payload);
    SAFE_FREE(resp_buf.data);
    return status;
}

/* Convenience wrappers ---------------------------------------------------- */

eip1193_err_t eip1193_eth_chain_id(eip1193_adapter_t *adp, char **chain_id_out)
{
    if (!chain_id_out)
        return EIP1193_ERR_INVALID_ARG;

    *chain_id_out = NULL;
    cJSON *result = NULL;
    eip1193_err_t rc = eip1193_adapter_request(adp, "eth_chainId", NULL, &result);
    if (rc != EIP1193_OK)
        return rc;

    if (!cJSON_IsString(result))
    {
        cJSON_Delete(result);
        return EIP1193_ERR_JSON;
    }

    *chain_id_out = strdup(result->valuestring);
    cJSON_Delete(result);
    return (*chain_id_out) ? EIP1193_OK : EIP1193_ERR_ALLOC;
}

eip1193_err_t eip1193_eth_accounts(eip1193_adapter_t *adp, cJSON **accounts_out)
{
    return eip1193_adapter_request(adp, "eth_accounts", NULL, accounts_out);
}

eip1193_err_t eip1193_eth_send_transaction(eip1193_adapter_t *adp,
                                           cJSON *tx_obj,
                                           char **tx_hash_out)
{
    if (!tx_obj || !tx_hash_out)
        return EIP1193_ERR_INVALID_ARG;

    *tx_hash_out = NULL;

    cJSON *params = cJSON_CreateArray();
    if (!params)
        return EIP1193_ERR_ALLOC;

    cJSON_AddItemReferenceToArray(params, tx_obj);

    cJSON *result = NULL;
    eip1193_err_t rc = eip1193_adapter_request(adp, "eth_sendTransaction", params, &result);
    cJSON_Delete(params);

    if (rc != EIP1193_OK)
        return rc;

    if (!cJSON_IsString(result))
    {
        cJSON_Delete(result);
        return EIP1193_ERR_JSON;
    }

    *tx_hash_out = strdup(result->valuestring);
    cJSON_Delete(result);

    return (*tx_hash_out) ? EIP1193_OK : EIP1193_ERR_ALLOC;
}

eip1193_err_t eip1193_personal_sign(eip1193_adapter_t *adp,
                                    const char *message_hex,
                                    const char *account,
                                    char **signature_out)
{
    if (!message_hex || !account || !signature_out)
        return EIP1193_ERR_INVALID_ARG;

    *signature_out = NULL;

    cJSON *params = cJSON_CreateArray();
    if (!params) return EIP1193_ERR_ALLOC;

    cJSON_AddItemToArray(params, cJSON_CreateString(message_hex));
    cJSON_AddItemToArray(params, cJSON_CreateString(account));

    cJSON *result = NULL;
    eip1193_err_t rc = eip1193_adapter_request(adp, "personal_sign", params, &result);
    cJSON_Delete(params);

    if (rc != EIP1193_OK)
        return rc;

    if (!cJSON_IsString(result))
    {
        cJSON_Delete(result);
        return EIP1193_ERR_JSON;
    }

    *signature_out = strdup(result->valuestring);
    cJSON_Delete(result);

    return (*signature_out) ? EIP1193_OK : EIP1193_ERR_ALLOC;
}

/* ------------------------------------------------------------------------- */
/* Example usage (can be removed in production)                              */
/* ------------------------------------------------------------------------- */
#ifdef EIP1193_ADAPTER_TEST_MAIN
int main(void)
{
    eip1193_adapter_t *adp = eip1193_adapter_create(NULL, 5000);
    if (!adp)
    {
        fprintf(stderr, "Failed to create adapter\n");
        return EXIT_FAILURE;
    }

    char *chain_id = NULL;
    if (eip1193_eth_chain_id(adp, &chain_id) == EIP1193_OK)
    {
        printf("Chain ID: %s\n", chain_id);
        free(chain_id);
    }

    cJSON *accounts = NULL;
    if (eip1193_eth_accounts(adp, &accounts) == EIP1193_OK)
    {
        char *acc_str = cJSON_Print(accounts);
        printf("Accounts: %s\n", acc_str);
        free(acc_str);
        cJSON_Delete(accounts);
    }

    /* Send a dummy txn */
    cJSON *tx = cJSON_CreateObject();
    cJSON_AddStringToObject(tx, "from",  "0x0000000000000000000000000000000000000000");
    cJSON_AddStringToObject(tx, "to",    "0x0000000000000000000000000000000000000001");
    cJSON_AddStringToObject(tx, "value", "0x0");
    char *tx_hash = NULL;
    eip1193_err_t rc = eip1193_eth_send_transaction(adp, tx, &tx_hash);
    if (rc == EIP1193_OK)
    {
        printf("Tx Hash: %s\n", tx_hash);
        free(tx_hash);
    }
    else
    {
        printf("Tx failed (err=%d)\n", rc);
    }
    cJSON_Delete(tx);

    eip1193_adapter_destroy(adp);
    return 0;
}
#endif /* EIP1193_ADAPTER_TEST_MAIN */
