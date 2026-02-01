/**
 * EduPay Ledger Academy
 * -------------------------------------
 * Bursar Service : PCI-DSS Gateway Proxy
 *
 * File:    pci_dss_proxy.c
 * Project: EduPay Ledger Academy (fintech_payment)
 * Layer:   Infrastructure / Gateways
 *
 * Overview
 * --------
 * The PCI-DSS proxy is the single integration point between the
 * Bursar service and an external PCI-DSS-compliant payment processor.
 * All cardholder-data (CHD) enters and leaves the system exclusively
 * through this component.  By centralising the interaction we:
 *
 *   1. Contain the PCI scope to a well-defined boundary.
 *   2. Facilitate mock/stub replacement for classroom exercises.
 *   3. Enforce security controls (tokenisation, encryption at rest,
 *      memory scrubbing, and request-level auditing).
 *
 * The implementation chooses libcurl for HTTPS transport, cJSON for
 * lightweight JSON handling, and libsodium for symmetric encryption
 * of transient card data.  Compile-time feature flags allow the
 * instructor to strip external dependencies (e.g. during unit tests)
 * while keeping the public interface unchanged.
 *
 * Build flags
 * -----------
 *   -DHAVE_LIBCURL   : enable real HTTP calls via libcurl
 *   -DHAVE_CJSON     : enable JSON serialisation with cJSON
 *   -DHAVE_SODIUM    : enable encryption with libsodium
 *
 * Author:  EduPay Ledger Academy Core Team
 * License: Apache-2.0
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include <time.h>

#include <pthread.h>

#ifdef HAVE_LIBCURL
#  include <curl/curl.h>
#endif

#ifdef HAVE_CJSON
#  include <cjson/cJSON.h>
#endif

#ifdef HAVE_SODIUM
#  include <sodium.h>
#endif

#include "pci_dss_proxy.h"     /* Public interface for the proxy          */
#include "audit_trail.h"       /* Domain-level audit logging               */
#include "secure_string.h"     /* memzero_explicit() / secure_strcmp()     */
#include "configuration.h"     /* runtime_config_get() utility             */

/* ------------------------------------------------------------------------- */
/* Constants & Macros                                                        */
/* ------------------------------------------------------------------------- */

#define PCI_DSS_PROXY_VERSION       "2.4.0"
#define HTTP_STATUS_OK              200
#define HTTP_STATUS_ACCEPTED        202
#define DEFAULT_HTTPS_TIMEOUT_SEC   30
#define TRACE_ID_HEADER             "X-Trace-Id"

/* ------------------------------------------------------------------------- */
/* Internal data structures                                                  */
/* ------------------------------------------------------------------------- */

/* Gateway configuration pulled from configuration service or env-vars */
typedef struct {
    char  gateway_url[256];
    char  api_key[128];
    char  api_secret[128];   /* Only used if HAVE_SODIUM assumed */
    long  timeout_seconds;
} pci_dss_gateway_cfg_t;

/* Runtime context shared by proxy (singleton in process) */
typedef struct {
    pci_dss_gateway_cfg_t cfg;
    bool                  is_initialised;
    pthread_mutex_t       lock;
#ifdef HAVE_LIBCURL
    CURL                 *curl;
#endif
} pci_dss_ctx_t;

/* ------------------------------------------------------------------------- */
/* Static globals (file scope)                                               */
/* ------------------------------------------------------------------------- */

static pci_dss_ctx_t g_ctx = {
    .is_initialised = false,
    .lock           = PTHREAD_MUTEX_INITIALIZER,
#ifdef HAVE_LIBCURL
    .curl           = NULL
#endif
};

/* ------------------------------------------------------------------------- */
/* Utilities                                                                 */
/* ------------------------------------------------------------------------- */

/* Generates a cryptographically random trace id for cross-system debugging */
static void create_trace_id(char out[37]) /* UUID v4 format */
{
#ifdef HAVE_SODIUM
    randombytes_buf(out, 16);
#else
    /* Fallback: use rand(); not cryptographically strong, but only for demo */
    for (int i = 0; i < 16; ++i) {
        out[i] = (char)(rand() % 256);
    }
#endif
    /* Convert raw bytes to UUID string (simple version) */
    static const char *hex = "0123456789abcdef";
    int idx = 0;
    for (int i = 0; i < 16; ++i) {
        out[idx++] = hex[(out[i] >> 4) & 0xF];
        out[idx++] = hex[out[i] & 0xF];
        if (i == 3 || i == 5 || i == 7 || i == 9) {
            out[idx++] = '-';
        }
    }
    out[36] = '\0';
}

/* Securely wipe and free heap memory containing sensitive data */
static void secure_free(void *ptr, size_t sz)
{
    if (!ptr) return;
    memzero_explicit(ptr, sz);
    free(ptr);
}

/* Convert JSON into cstring, auditing memory usage.  Caller must free().    */
#ifdef HAVE_CJSON
static char *json_to_string(const cJSON *object)
{
    char *raw = cJSON_PrintUnformatted(object);
    if (!raw) return NULL;

    size_t len = strlen(raw);
    audit_trail_metric("pci_dss.json.bytes", (int)len);
    return raw;
}
#endif

/* ------------------------------------------------------------------------- */
/* Gateway initialisation & teardown                                         */
/* ------------------------------------------------------------------------- */

/**
 * pci_dss_proxy_init
 * Initialise the singleton proxy context.  Safe for repeated calls.
 */
int pci_dss_proxy_init(void)
{
    pthread_mutex_lock(&g_ctx.lock);

    if (g_ctx.is_initialised) {
        pthread_mutex_unlock(&g_ctx.lock);
        return PCI_DSS_OK;
    }

    /* Load configuration */
    const char *url     = runtime_config_get("PCI_GATEWAY_URL");
    const char *api_key = runtime_config_get("PCI_GATEWAY_API_KEY");
    const char *secret  = runtime_config_get("PCI_GATEWAY_API_SECRET");

    if (!url || !api_key) {
        pthread_mutex_unlock(&g_ctx.lock);
        return PCI_DSS_ERR_CONFIG;
    }

    snprintf(g_ctx.cfg.gateway_url, sizeof g_ctx.cfg.gateway_url, "%s", url);
    snprintf(g_ctx.cfg.api_key, sizeof g_ctx.cfg.api_key, "%s", api_key);
    snprintf(g_ctx.cfg.api_secret, sizeof g_ctx.cfg.api_secret, "%s",
             secret ? secret : "");
    g_ctx.cfg.timeout_seconds = DEFAULT_HTTPS_TIMEOUT_SEC;

#ifdef HAVE_SODIUM
    if (sodium_init() == -1) {
        pthread_mutex_unlock(&g_ctx.lock);
        return PCI_DSS_ERR_CRYPTO;
    }
#endif

#ifdef HAVE_LIBCURL
    g_ctx.curl = curl_easy_init();
    if (!g_ctx.curl) {
        pthread_mutex_unlock(&g_ctx.lock);
        return PCI_DSS_ERR_NETWORK;
    }
    curl_easy_setopt(g_ctx.curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(g_ctx.curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(g_ctx.curl, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(g_ctx.curl, CURLOPT_TIMEOUT, g_ctx.cfg.timeout_seconds);
#endif

    g_ctx.is_initialised = true;
    pthread_mutex_unlock(&g_ctx.lock);

    audit_trail_info("PCI-DSS proxy initialised (version %s)",
                     PCI_DSS_PROXY_VERSION);

    return PCI_DSS_OK;
}

/**
 * pci_dss_proxy_shutdown
 * Cleans up global resources.  Idempotent.
 */
void pci_dss_proxy_shutdown(void)
{
    pthread_mutex_lock(&g_ctx.lock);

    if (!g_ctx.is_initialised) {
        pthread_mutex_unlock(&g_ctx.lock);
        return;
    }

#ifdef HAVE_LIBCURL
    if (g_ctx.curl) {
        curl_easy_cleanup(g_ctx.curl);
        g_ctx.curl = NULL;
    }
#endif

    memzero_explicit(&g_ctx.cfg, sizeof g_ctx.cfg);
    g_ctx.is_initialised = false;

    pthread_mutex_unlock(&g_ctx.lock);

    audit_trail_info("PCI-DSS proxy shutdown complete");
}

/* ------------------------------------------------------------------------- */
/* Encryption helpers (libsodium)                                            */
/* ------------------------------------------------------------------------- */

#ifdef HAVE_SODIUM
/* Using secretbox for symmetric encryption of short strings */
static int encrypt_blob(const char *plain,
                        unsigned char **out_cipher,
                        unsigned long long *out_len)
{
    if (!plain || !out_cipher || !out_len) return -1;

    const unsigned char *key = (const unsigned char *) g_ctx.cfg.api_secret;
    if (strlen((const char *)key) < crypto_secretbox_KEYBYTES) {
        return -2;
    }

    const size_t mlen = strlen(plain);
    unsigned char *cipher = calloc(1,
        crypto_secretbox_NONCEBYTES + mlen + crypto_secretbox_MACBYTES);
    if (!cipher) return -3;

    unsigned char *nonce = cipher;
    randombytes_buf(nonce, crypto_secretbox_NONCEBYTES);

    if (crypto_secretbox_easy(cipher + crypto_secretbox_NONCEBYTES,
                              (const unsigned char *)plain, mlen,
                              nonce, key) != 0) {
        secure_free(cipher, crypto_secretbox_NONCEBYTES + mlen +
                             crypto_secretbox_MACBYTES);
        return -4; /* encryption failed */
    }

    *out_cipher = cipher;
    *out_len    = crypto_secretbox_NONCEBYTES + mlen +
                  crypto_secretbox_MACBYTES;
    return 0;
}
#endif /* HAVE_SODIUM */

/* ------------------------------------------------------------------------- */
/* HTTP helper (libcurl)                                                     */
/* ------------------------------------------------------------------------- */

#ifdef HAVE_LIBCURL

/* Buffer for curl write callback */
typedef struct {
    char  *data;
    size_t size;
} curl_response_buf_t;

static size_t curl_write_cb(void *contents, size_t size,
                            size_t nmemb, void *userp)
{
    const size_t realsize = size * nmemb;
    curl_response_buf_t *mem = (curl_response_buf_t *) userp;

    char *ptr = realloc(mem->data, mem->size + realsize + 1);
    if (!ptr) {
        /* out of memory! */
        audit_trail_error("curl_write_cb: out of memory");
        return 0;
    }

    mem->data = ptr;
    memcpy(&(mem->data[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->data[mem->size] = '\0';

    return realsize;
}

/**
 * perform_http_post
 * Execute HTTPS POST request and return HTTP status code along with body.
 * Caller must free() response_body if not NULL.
 */
static int perform_http_post(const char *endpoint_path,
                             const char *json_payload,
                             char **response_body)
{
    if (!g_ctx.is_initialised || !endpoint_path || !json_payload) {
        return PCI_DSS_ERR_PRECONDITION;
    }

    char url[512];
    snprintf(url, sizeof url, "%s%s", g_ctx.cfg.gateway_url, endpoint_path);

    struct curl_slist *headers = NULL;
    char trace_id[37];
    create_trace_id(trace_id);

    char api_key_header[160];
    snprintf(api_key_header, sizeof api_key_header,
             "Authorization: Bearer %s", g_ctx.cfg.api_key);

    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, api_key_header);
    char trace_header_buf[64];
    snprintf(trace_header_buf, sizeof trace_header_buf,
             TRACE_ID_HEADER ": %s", trace_id);
    headers = curl_slist_append(headers, trace_header_buf);

    curl_response_buf_t resp = { .data = NULL, .size = 0 };

    curl_easy_setopt(g_ctx.curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(g_ctx.curl, CURLOPT_URL, url);
    curl_easy_setopt(g_ctx.curl, CURLOPT_POSTFIELDS, json_payload);
    curl_easy_setopt(g_ctx.curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(g_ctx.curl, CURLOPT_WRITEDATA, (void *)&resp);

    CURLcode res = curl_easy_perform(g_ctx.curl);

    long http_status = 0;
    curl_easy_getinfo(g_ctx.curl, CURLINFO_RESPONSE_CODE, &http_status);

    curl_slist_free_all(headers);
    curl_easy_reset(g_ctx.curl); /* reset options for next call */

    if (res != CURLE_OK) {
        audit_trail_error("curl_easy_perform error: %s",
                          curl_easy_strerror(res));
        if (resp.data) free(resp.data);
        return PCI_DSS_ERR_NETWORK;
    }

    if (response_body) {
        *response_body = resp.data; /* caller file free() */
    } else if (resp.data) {
        free(resp.data);
    }

    return (int)http_status;
}
#endif /* HAVE_LIBCURL */

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

int pci_dss_tokenize_card(const card_data_plain_t *card,
                          tokenized_card_t        *out_token)
{
    if (!g_ctx.is_initialised || !card || !out_token) {
        return PCI_DSS_ERR_PRECONDITION;
    }

    int retval = PCI_DSS_OK;
    char *payload = NULL;
    char *resp_body = NULL;

#ifdef HAVE_CJSON
    /* Build JSON payload */
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return PCI_DSS_ERR_ALLOC;
    }

    cJSON_AddStringToObject(root, "card_number",  card->card_number);
    cJSON_AddStringToObject(root, "expiry_month", card->expiry_month);
    cJSON_AddStringToObject(root, "expiry_year",  card->expiry_year);
    cJSON_AddStringToObject(root, "cardholder",   card->cardholder_name);
    cJSON_AddStringToObject(root, "cvv",          card->cvv);

    payload = json_to_string(root);
    cJSON_Delete(root);

    if (!payload) {
        return PCI_DSS_ERR_SERIALISE;
    }
#else
    /* Fallback naive payload */
    payload = strdup("{\"dummy\":\"no_json_lib\"}");
    if (!payload) return PCI_DSS_ERR_ALLOC;
#endif

#ifdef HAVE_LIBCURL
    int http_status = perform_http_post("/tokenize", payload, &resp_body);
#else
    int http_status = HTTP_STATUS_ACCEPTED; /* stub */
    resp_body = strdup("{\"token\":\"stub-token-123\"}");
#endif

    /* Payload contains sensitive data; wipe immediately */
    secure_free(payload, strlen(payload));

    if (http_status != HTTP_STATUS_OK) {
        audit_trail_warn("Tokenisation failed, HTTP %d", http_status);
        secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
        return PCI_DSS_ERR_GATEWAY;
    }

#ifdef HAVE_CJSON
    cJSON *resp_json = cJSON_Parse(resp_body);
    if (!resp_json) {
        secure_free(resp_body, strlen(resp_body));
        return PCI_DSS_ERR_SERIALISE;
    }

    const cJSON *token = cJSON_GetObjectItemCaseSensitive(resp_json, "token");
    const cJSON *network = cJSON_GetObjectItemCaseSensitive(resp_json,
                                                            "card_network");

    if (!cJSON_IsString(token) || !token->valuestring) {
        retval = PCI_DSS_ERR_GATEWAY;
    } else {
        snprintf(out_token->token, sizeof out_token->token, "%s",
                 token->valuestring);
        snprintf(out_token->card_network, sizeof out_token->card_network, "%s",
                 cJSON_IsString(network) ? network->valuestring : "UNKNOWN");
        out_token->created_epoch_sec = time(NULL);
    }

    cJSON_Delete(resp_json);
#else
    snprintf(out_token->token, sizeof out_token->token, "stub-token-123");
    snprintf(out_token->card_network, sizeof out_token->card_network, "STUB");
    out_token->created_epoch_sec = time(NULL);
#endif

    secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
    return retval;
}

int pci_dss_authorize(const tokenized_card_t *tokenised_card,
                      const money_amount_t   *amount,
                      char                    out_auth_id[PCI_DSS_AUTH_ID_LEN])
{
    if (!g_ctx.is_initialised || !tokenised_card || !amount || !out_auth_id) {
        return PCI_DSS_ERR_PRECONDITION;
    }

    int retval = PCI_DSS_OK;
    char *payload = NULL;
    char *resp_body = NULL;

#ifdef HAVE_CJSON
    cJSON *root = cJSON_CreateObject();
    if (!root) return PCI_DSS_ERR_ALLOC;

    cJSON_AddStringToObject(root, "token", tokenised_card->token);
    cJSON_AddNumberToObject(root, "amount_minor", amount->amount_minor);
    cJSON_AddStringToObject(root, "currency", amount->currency_iso);

    payload = json_to_string(root);
    cJSON_Delete(root);
#else
    payload = strdup("{\"dummy\":\"no_json_lib\"}");
#endif

    if (!payload) return PCI_DSS_ERR_SERIALISE;

#ifdef HAVE_LIBCURL
    int http_status = perform_http_post("/authorize", payload, &resp_body);
#else
    int http_status = HTTP_STATUS_OK;
    resp_body = strdup("{\"auth_id\":\"stub-auth-890\"}");
#endif

    secure_free(payload, strlen(payload));

    if (http_status != HTTP_STATUS_OK) {
        secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
        return PCI_DSS_ERR_GATEWAY;
    }

#ifdef HAVE_CJSON
    cJSON *resp_json = cJSON_Parse(resp_body);
    if (!resp_json) {
        secure_free(resp_body, strlen(resp_body));
        return PCI_DSS_ERR_SERIALISE;
    }

    const cJSON *auth_id = cJSON_GetObjectItemCaseSensitive(resp_json,
                                                            "auth_id");
    if (!cJSON_IsString(auth_id) || !auth_id->valuestring) {
        retval = PCI_DSS_ERR_GATEWAY;
    } else {
        snprintf(out_auth_id, PCI_DSS_AUTH_ID_LEN, "%s",
                 auth_id->valuestring);
    }
    cJSON_Delete(resp_json);
#else
    snprintf(out_auth_id, PCI_DSS_AUTH_ID_LEN, "stub-auth-890");
#endif

    secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
    return retval;
}

int pci_dss_capture(const char auth_id[PCI_DSS_AUTH_ID_LEN],
                    const money_amount_t *amount,
                    char  out_txn_id[PCI_DSS_TXN_ID_LEN])
{
    if (!g_ctx.is_initialised || !auth_id || !amount || !out_txn_id) {
        return PCI_DSS_ERR_PRECONDITION;
    }

    int retval = PCI_DSS_OK;
    char *payload = NULL;
    char *resp_body = NULL;

#ifdef HAVE_CJSON
    cJSON *root = cJSON_CreateObject();
    if (!root) return PCI_DSS_ERR_ALLOC;

    cJSON_AddStringToObject(root, "auth_id", auth_id);
    cJSON_AddNumberToObject(root, "amount_minor", amount->amount_minor);
    cJSON_AddStringToObject(root, "currency", amount->currency_iso);

    payload = json_to_string(root);
    cJSON_Delete(root);
#else
    payload = strdup("{\"dummy\":\"no_json_lib\"}");
#endif

    if (!payload) return PCI_DSS_ERR_SERIALISE;

#ifdef HAVE_LIBCURL
    int http_status = perform_http_post("/capture", payload, &resp_body);
#else
    int http_status = HTTP_STATUS_OK;
    resp_body = strdup("{\"txn_id\":\"stub-txn-456\"}");
#endif

    secure_free(payload, strlen(payload));

    if (http_status != HTTP_STATUS_OK) {
        secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
        return PCI_DSS_ERR_GATEWAY;
    }

#ifdef HAVE_CJSON
    cJSON *resp_json = cJSON_Parse(resp_body);
    if (!resp_json) {
        secure_free(resp_body, strlen(resp_body));
        return PCI_DSS_ERR_SERIALISE;
    }

    const cJSON *txn_id = cJSON_GetObjectItemCaseSensitive(resp_json,
                                                           "txn_id");
    if (!cJSON_IsString(txn_id) || !txn_id->valuestring) {
        retval = PCI_DSS_ERR_GATEWAY;
    } else {
        snprintf(out_txn_id, PCI_DSS_TXN_ID_LEN, "%s", txn_id->valuestring);
    }
    cJSON_Delete(resp_json);
#else
    snprintf(out_txn_id, PCI_DSS_TXN_ID_LEN, "stub-txn-456");
#endif

    secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
    return retval;
}

int pci_dss_refund(const char txn_id[PCI_DSS_TXN_ID_LEN],
                   const money_amount_t *amount,
                   char  out_refund_id[PCI_DSS_REFUND_ID_LEN])
{
    if (!g_ctx.is_initialised || !txn_id || !amount || !out_refund_id) {
        return PCI_DSS_ERR_PRECONDITION;
    }

    int retval = PCI_DSS_OK;
    char *payload = NULL;
    char *resp_body = NULL;

#ifdef HAVE_CJSON
    cJSON *root = cJSON_CreateObject();
    if (!root) return PCI_DSS_ERR_ALLOC;

    cJSON_AddStringToObject(root, "txn_id", txn_id);
    cJSON_AddNumberToObject(root, "amount_minor", amount->amount_minor);
    cJSON_AddStringToObject(root, "currency", amount->currency_iso);

    payload = json_to_string(root);
    cJSON_Delete(root);
#else
    payload = strdup("{\"dummy\":\"no_json_lib\"}");
#endif

    if (!payload) return PCI_DSS_ERR_SERIALISE;

#ifdef HAVE_LIBCURL
    int http_status = perform_http_post("/refund", payload, &resp_body);
#else
    int http_status = HTTP_STATUS_OK;
    resp_body = strdup("{\"refund_id\":\"stub-refund-222\"}");
#endif

    secure_free(payload, strlen(payload));

    if (http_status != HTTP_STATUS_OK) {
        secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
        return PCI_DSS_ERR_GATEWAY;
    }

#ifdef HAVE_CJSON
    cJSON *resp_json = cJSON_Parse(resp_body);
    if (!resp_json) {
        secure_free(resp_body, strlen(resp_body));
        return PCI_DSS_ERR_SERIALISE;
    }

    const cJSON *refund_id = cJSON_GetObjectItemCaseSensitive(resp_json,
                                                              "refund_id");
    if (!cJSON_IsString(refund_id) || !refund_id->valuestring) {
        retval = PCI_DSS_ERR_GATEWAY;
    } else {
        snprintf(out_refund_id, PCI_DSS_REFUND_ID_LEN, "%s",
                 refund_id->valuestring);
    }
    cJSON_Delete(resp_json);
#else
    snprintf(out_refund_id, PCI_DSS_REFUND_ID_LEN, "stub-refund-222");
#endif

    secure_free(resp_body, resp_body ? strlen(resp_body) : 0);
    return retval;
}

/* ------------------------------------------------------------------------- */
/* Memory hygiene: destructor attribute (GCC/Clang)                          */
/* ------------------------------------------------------------------------- */

#ifdef __GNUC__
static void __attribute__((destructor)) pci_dss_proxy_auto_shutdown(void)
{
    pci_dss_proxy_shutdown();
}
#endif