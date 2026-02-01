```c
/**
 * HoloCanvas Wallet-Proxy Service
 *
 * File:    services/wallet_proxy/src/proxy_server.c
 * Author:  HoloCanvas Core Team
 *
 * Description
 * -----------
 * An HTTP/JSON-based façade that shields end-user wallets from the
 * internal blockchain topology.  It provides:
 *
 *   • Wallet creation (Ed25519)
 *   • Balance look-ups (delegated to LedgerCore over gRPC)
 *   • Transaction signing
 *   • Transaction broadcast forwarding
 *
 * The service is intentionally stateless with the exception of an
 * in-memory, thread-safe key store that is meant only for demonstration
 * purposes.  Production deployments SHOULD replace the keystore with a
 * secure HSM or enclave-backed store.
 *
 * Build
 * -----
 * gcc -O2 -Wall -Wextra -pedantic -pthread \
 *     proxy_server.c -o wallet_proxy \
 *     -levent -lcjson -lsodium
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <signal.h>
#include <time.h>
#include <pthread.h>

#include <event2/event.h>
#include <event2/http.h>
#include <event2/buffer.h>
#include <event2/keyvalq_struct.h>

#include <sodium.h>
#include "uthash.h"          /* Header-only hash map: https://troydhanson.github.io/uthash/ */
#include "cjson/cJSON.h"     /* Assumed to be available on include path */

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

#define LISTEN_ADDRESS      "0.0.0.0"
#define LISTEN_PORT         8082
#define SERVICE_VERSION     "1.3.0"

#define JSON_CONTENT_TYPE   "application/json; charset=utf-8"
#define MAX_JSON_BODY       (64 * 1024)   /* 64 KiB */

/* -------------------------------------------------------------------------- */
/*                               Logging Macros                               */
/* -------------------------------------------------------------------------- */

#define LOG_LEVEL_INFO  1
#define LOG_LEVEL_WARN  2
#define LOG_LEVEL_ERR   3

#ifndef LOG_LEVEL
#   define LOG_LEVEL LOG_LEVEL_INFO
#endif

#define LOG_PRINTF(level, fmt, ...)                                      \
    do {                                                                 \
        if ((level) >= LOG_LEVEL) {                                      \
            const char *_l = (level) == LOG_LEVEL_INFO ? "INFO" :        \
                             (level) == LOG_LEVEL_WARN ? "WARN" : "ERROR";\
            fprintf(stderr, "[%s][%s:%d] " fmt "\n", _l,                 \
                    __FILE__, __LINE__, ##__VA_ARGS__);                  \
        }                                                                \
    } while (0)

#define LOG_INFO(fmt, ...)  LOG_PRINTF(LOG_LEVEL_INFO, fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  LOG_PRINTF(LOG_LEVEL_WARN, fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...)   LOG_PRINTF(LOG_LEVEL_ERR,  fmt, ##__VA_ARGS__)

/* -------------------------------------------------------------------------- */
/*                                 Utilities                                  */
/* -------------------------------------------------------------------------- */

/* Hex-encoding helpers ----------------------------------------------------- */
static void
bytes_to_hex(const uint8_t *bytes, size_t len, char *hex_out)
{
    static const char lut[] = "0123456789abcdef";
    for (size_t i = 0; i < len; ++i) {
        hex_out[i * 2]     = lut[(bytes[i] >> 4) & 0x0F];
        hex_out[i * 2 + 1] = lut[ bytes[i]       & 0x0F];
    }
    hex_out[len * 2] = '\0';
}

static int
hex_to_bytes(const char *hex, uint8_t *bytes_out, size_t max_len)
{
    size_t hex_len = strlen(hex);
    if (hex_len % 2 != 0 || hex_len / 2 > max_len)
        return -1;

    for (size_t i = 0; i < hex_len / 2; ++i) {
        unsigned int byte;
        if (sscanf(&hex[i * 2], "%2x", &byte) != 1)
            return -1;
        bytes_out[i] = (uint8_t)byte;
    }
    return (int)(hex_len / 2);
}

/* HTTP parameter convenience ---------------------------------------------- */
static char *
get_query_param(struct evkeyvalq *params, const char *key)
{
    return (char *)evhttp_find_header(params, key);
}

/* Reads the body of an evhttp_request into a null-terminated buffer.
 * The returned pointer must be freed by the caller. */
static char *
read_request_body(struct evhttp_request *req)
{
    struct evbuffer *buf = evhttp_request_get_input_buffer(req);
    size_t len           = evbuffer_get_length(buf);
    if (len == 0 || len > MAX_JSON_BODY) {
        return NULL;
    }

    char *data = calloc(1, len + 1);
    if (!data)
        return NULL;

    evbuffer_copyout(buf, data, len);
    return data;
}

/* -------------------------------------------------------------------------- */
/*                                Key-Store                                  */
/* -------------------------------------------------------------------------- */

/*
 * The keystore is a simple in-memory, thread-safe map:
 *      address (hex-encoded pubkey)  ->  wallet_entry_t
 *
 * WARNING: This is for demonstration only.  Never store private keys
 *          like this in production.
 */

typedef struct wallet_entry {
    uint8_t  pubkey[crypto_sign_PUBLICKEYBYTES];
    uint8_t  seckey[crypto_sign_SECRETKEYBYTES];
    char     address[crypto_sign_PUBLICKEYBYTES * 2 + 1]; /* hex-encoded */
    UT_hash_handle hh; /* makes this structure hashable */
} wallet_entry_t;

static wallet_entry_t *g_keystore = NULL;
static pthread_mutex_t g_keystore_lock = PTHREAD_MUTEX_INITIALIZER;

static wallet_entry_t *
keystore_lookup(const char *address)
{
    wallet_entry_t *entry = NULL;
    pthread_mutex_lock(&g_keystore_lock);
    HASH_FIND_STR(g_keystore, address, entry);
    pthread_mutex_unlock(&g_keystore_lock);
    return entry;
}

static int
keystore_insert(const uint8_t pubkey[crypto_sign_PUBLICKEYBYTES],
                const uint8_t seckey[crypto_sign_SECRETKEYBYTES],
                char **address_out)
{
    wallet_entry_t *entry = malloc(sizeof *entry);
    if (!entry)
        return -1;

    memcpy(entry->pubkey, pubkey, crypto_sign_PUBLICKEYBYTES);
    memcpy(entry->seckey, seckey, crypto_sign_SECRETKEYBYTES);

    bytes_to_hex(pubkey, crypto_sign_PUBLICKEYBYTES, entry->address);

    pthread_mutex_lock(&g_keystore_lock);
    HASH_ADD_STR(g_keystore, address, entry);
    pthread_mutex_unlock(&g_keystore_lock);

    if (address_out)
        *address_out = strdup(entry->address);

    return 0;
}

/* -------------------------------------------------------------------------- */
/*                           gRPC Stubbed Adapters                           */
/* -------------------------------------------------------------------------- */

/* In production, the following functions would marshal protobuf messages
 * and call LedgerCore over the network.  Here, we stub them for brevity. */

static int
ledger_get_balance(const char *address, uint64_t *balance_out)
{
    /* Random balance for demonstration */
    *balance_out = (uint64_t) (rand() % 10'000) * 100'0000ULL;
    LOG_INFO("ledger_get_balance(%s) -> %" PRIu64, address, *balance_out);
    return 0;
}

static int
ledger_broadcast_transaction(const char *signed_tx_hex)
{
    LOG_INFO("ledger_broadcast_transaction(len=%zu)", strlen(signed_tx_hex));
    /* pretend success */
    return 0;
}

/* -------------------------------------------------------------------------- */
/*                               HTTP Handlers                               */
/* -------------------------------------------------------------------------- */

/* Helper: send JSON response and free the cJSON object. */
static void
send_json_reply(struct evhttp_request *req, int code, cJSON *json)
{
    char *rendered = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);

    struct evbuffer *buf = evbuffer_new();
    evbuffer_add_printf(buf, "%s", rendered);
    free(rendered);

    evhttp_add_header(evhttp_request_get_output_headers(req),
                      "Content-Type", JSON_CONTENT_TYPE);
    evhttp_send_reply(req, code, "OK", buf);

    evbuffer_free(buf);
}

/* Handler: GET /v1/health ----------------------------------------------- */
static void
handle_health(struct evhttp_request *req, void *arg)
{
    (void)arg;
    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "service", "wallet-proxy");
    cJSON_AddStringToObject(json, "version", SERVICE_VERSION);
    cJSON_AddStringToObject(json, "status",  "OK");
    send_json_reply(req, HTTP_OK, json);
}

/* Handler: POST /v1/wallet/create --------------------------------------- */
static void
handle_wallet_create(struct evhttp_request *req, void *arg)
{
    (void)arg;
    if (req->type != EVHTTP_REQ_POST) {
        evhttp_send_reply(req, HTTP_BADMETHOD, "Method Not Allowed", NULL);
        return;
    }

    uint8_t pubkey[crypto_sign_PUBLICKEYBYTES];
    uint8_t seckey[crypto_sign_SECRETKEYBYTES];

    if (crypto_sign_keypair(pubkey, seckey) != 0) {
        LOG_ERR("crypto_sign_keypair() failed");
        evhttp_send_reply(req, HTTP_INTERNAL, "Crypto Error", NULL);
        return;
    }

    char *address = NULL;
    if (keystore_insert(pubkey, seckey, &address) != 0) {
        evhttp_send_reply(req, HTTP_INTERNAL, "Keystore Error", NULL);
        return;
    }

    char pub_hex[crypto_sign_PUBLICKEYBYTES * 2 + 1];
    bytes_to_hex(pubkey, crypto_sign_PUBLICKEYBYTES, pub_hex);

    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "address", address);
    cJSON_AddStringToObject(json, "public_key", pub_hex);

    send_json_reply(req, HTTP_OK, json);
    free(address);
}

/* Handler: GET /v1/wallet/<addr>/balance ------------------------------- */
static void
handle_wallet_balance(struct evhttp_request *req, void *arg)
{
    (void)arg;
    if (req->type != EVHTTP_REQ_GET) {
        evhttp_send_reply(req, HTTP_BADMETHOD, "Method Not Allowed", NULL);
        return;
    }

    const char *uri  = evhttp_request_get_uri(req);
    struct evhttp_uri *decoded = evhttp_uri_parse(uri);
    if (!decoded) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Bad URI", NULL);
        return;
    }

    const char *path = evhttp_uri_get_path(decoded);
    /* Path format: /v1/wallet/<address>/balance */
    char address[crypto_sign_PUBLICKEYBYTES * 2 + 1] = {0};
    if (sscanf(path, "/v1/wallet/%64[a-f0-9]/balance", address) != 1) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Bad Address", NULL);
        evhttp_uri_free(decoded);
        return;
    }
    evhttp_uri_free(decoded);

    uint64_t balance = 0;
    if (ledger_get_balance(address, &balance) != 0) {
        evhttp_send_reply(req, HTTP_INTERNAL, "Ledger Error", NULL);
        return;
    }

    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "address", address);
    cJSON_AddNumberToObject(json, "balance", (double)balance);
    send_json_reply(req, HTTP_OK, json);
}

/* Handler: POST /v1/wallet/sign ----------------------------------------- */
static void
handle_wallet_sign(struct evhttp_request *req, void *arg)
{
    (void)arg;
    if (req->type != EVHTTP_REQ_POST) {
        evhttp_send_reply(req, HTTP_BADMETHOD, "Method Not Allowed", NULL);
        return;
    }

    char *body = read_request_body(req);
    if (!body) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Empty Body", NULL);
        return;
    }

    cJSON *json = cJSON_Parse(body);
    free(body);
    if (!json) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Invalid JSON", NULL);
        return;
    }

    cJSON *j_addr = cJSON_GetObjectItemCaseSensitive(json, "address");
    cJSON *j_payload = cJSON_GetObjectItemCaseSensitive(json, "payload");

    if (!cJSON_IsString(j_addr) || !cJSON_IsString(j_payload)) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_BADREQUEST, "Missing Fields", NULL);
        return;
    }

    const char *address = j_addr->valuestring;
    const char *payload_hex = j_payload->valuestring;

    wallet_entry_t *entry = keystore_lookup(address);
    if (!entry) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_NOTFOUND, "Wallet Not Found", NULL);
        return;
    }

    uint8_t payload_bin[1024];
    int payload_len = hex_to_bytes(payload_hex, payload_bin, sizeof payload_bin);
    if (payload_len < 0) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_BADREQUEST, "Bad Payload Hex", NULL);
        return;
    }

    uint8_t signed_msg[1024 + crypto_sign_BYTES];
    unsigned long long signed_len = 0;
    if (crypto_sign(signed_msg, &signed_len, payload_bin, (unsigned long long)payload_len,
                    entry->seckey) != 0) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_INTERNAL, "Crypto Error", NULL);
        return;
    }

    char *sig_hex = malloc(signed_len * 2 + 1);
    bytes_to_hex(signed_msg, signed_len, sig_hex);

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "address", address);
    cJSON_AddStringToObject(resp, "signature", sig_hex);

    send_json_reply(req, HTTP_OK, resp);
    free(sig_hex);
    cJSON_Delete(json);
}

/* Handler: POST /v1/tx/broadcast ---------------------------------------- */
static void
handle_tx_broadcast(struct evhttp_request *req, void *arg)
{
    (void)arg;
    if (req->type != EVHTTP_REQ_POST) {
        evhttp_send_reply(req, HTTP_BADMETHOD, "Method Not Allowed", NULL);
        return;
    }

    char *body = read_request_body(req);
    if (!body) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Empty Body", NULL);
        return;
    }

    cJSON *json = cJSON_Parse(body);
    free(body);
    if (!json) {
        evhttp_send_reply(req, HTTP_BADREQUEST, "Invalid JSON", NULL);
        return;
    }

    cJSON *j_tx = cJSON_GetObjectItemCaseSensitive(json, "signed_tx");
    if (!cJSON_IsString(j_tx)) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_BADREQUEST, "Missing signed_tx", NULL);
        return;
    }

    const char *tx_hex = j_tx->valuestring;
    if (ledger_broadcast_transaction(tx_hex) != 0) {
        cJSON_Delete(json);
        evhttp_send_reply(req, HTTP_INTERNAL, "Ledger Error", NULL);
        return;
    }

    cJSON *resp = cJSON_CreateObject();
    cJSON_AddStringToObject(resp, "status", "submitted");
    send_json_reply(req, HTTP_OK, resp);
    cJSON_Delete(json);
}

/* -------------------------------------------------------------------------- */
/*                              Server Bootstrap                              */
/* -------------------------------------------------------------------------- */

typedef struct server_context {
    struct event_base *evbase;
    struct evhttp     *httpd;
} server_context_t;

static server_context_t g_srv_ctx;

static void
signal_handler(evutil_socket_t sig, short events, void *user_data)
{
    (void)events; (void)user_data;
    LOG_INFO("Signal %d received.  Shutting down...", sig);
    event_base_loopexit(g_srv_ctx.evbase, NULL);
}

static int
init_signal_handlers(struct event_base *base)
{
    struct event *sigint  = evsignal_new(base, SIGINT,  signal_handler, NULL);
    struct event *sigterm = evsignal_new(base, SIGTERM, signal_handler, NULL);
    if (!sigint || !sigterm)
        return -1;

    event_add(sigint,  NULL);
    event_add(sigterm, NULL);
    return 0;
}

static int
start_http_server(struct event_base *base)
{
    struct evhttp *httpd = evhttp_new(base);
    if (!httpd)
        return -1;

    /* ROUTES ----------------------------------------------------------------*/
    evhttp_set_gencb (httpd, NULL, NULL); /* 404 handler */
    evhttp_set_cb   (httpd, "/v1/health",        handle_health,        NULL);
    evhttp_set_cb   (httpd, "/v1/wallet/create", handle_wallet_create, NULL);
    evhttp_set_cb   (httpd, "/v1/wallet/sign",   handle_wallet_sign,   NULL);
    evhttp_set_cb   (httpd, "/v1/tx/broadcast",  handle_tx_broadcast,  NULL);
    /* For balance, we use a generic callback because of dynamic path. */
    evhttp_set_cb   (httpd, "/v1/wallet/",       handle_wallet_balance, NULL);

    if (evhttp_bind_socket(httpd, LISTEN_ADDRESS, LISTEN_PORT) != 0)
        return -1;

    g_srv_ctx.httpd = httpd;
    return 0;
}

/* -------------------------------------------------------------------------- */
/*                                    main                                   */
/* -------------------------------------------------------------------------- */

int
main(void)
{
    srand((unsigned)time(NULL));

    if (sodium_init() < 0) {
        LOG_ERR("sodium_init() failed");
        return EXIT_FAILURE;
    }

    struct event_base *base = event_base_new();
    if (!base) {
        LOG_ERR("event_base_new() failed");
        return EXIT_FAILURE;
    }
    g_srv_ctx.evbase = base;

    if (init_signal_handlers(base) != 0) {
        LOG_ERR("init_signal_handlers() failed");
        return EXIT_FAILURE;
    }

    if (start_http_server(base) != 0) {
        LOG_ERR("Failed to start HTTP server on %s:%d", LISTEN_ADDRESS, LISTEN_PORT);
        return EXIT_FAILURE;
    }

    LOG_INFO("Wallet-Proxy listening on http://%s:%d", LISTEN_ADDRESS, LISTEN_PORT);
    event_base_dispatch(base);

    /* Cleanup ----------------------------------------------------------------*/
    evhttp_free(g_srv_ctx.httpd);
    event_base_free(base);

    /* Free keystore */
    wallet_entry_t *e, *tmp;
    HASH_ITER(hh, g_keystore, e, tmp) {
        HASH_DEL(g_keystore, e);
        free(e);
    }

    LOG_INFO("Shutdown complete.");
    return EXIT_SUCCESS;
}
```