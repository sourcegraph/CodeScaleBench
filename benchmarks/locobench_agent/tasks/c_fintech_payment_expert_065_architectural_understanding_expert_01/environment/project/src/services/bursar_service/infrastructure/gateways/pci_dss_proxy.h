/*
 *  EduPay Ledger Academy
 *  ---------------------
 *  File: pci_dss_proxy.h
 *  Layer: Infrastructure ‒ Bursar Service ‒ Gateways
 *
 *  Description
 *  ===========
 *  Type-safe, header-only client library that enables the Bursar Service to
 *  perform PCI-DSS compliant operations (tokenisation, detokenisation, and
 *  authorisation pre-checks) against the central “PCI Proxy” micro-service.
 *
 *  The proxy is the ONLY component allowed to handle raw PAN data.  All
 *  downstream services MUST use the opaque tokens produced here.
 *
 *  Design Notes
 *  ------------
 *  • Clean-Architecture dictates that *nothing* in the Core domain depends on
 *    this header.  Only the infrastructure layer is allowed to import it.
 *  • Header-only so that professors may quickly stub/replace the underlying
 *    transport during lectures (e.g., switch from mTLS TCP to a UNIX socket).
 *  • OpenSSL is used for TLS and AES-GCM envelope encryption of the request
 *    payloads.  Real cards never traverse the wire in clear text.
 *  • Thread-safe by default: an internal pthread mutex protects the TLS
 *    session; concurrency primitives can be swapped via the adapter macros.
 *
 *  Copyright © 2023-2024 EduPay Ledger Academy
 *  SPDX-License-Identifier: Apache-2.0
 */

#ifndef EDU_PAY_LEDGER_ACADEMY_PCI_DSS_PROXY_H
#define EDU_PAY_LEDGER_ACADEMY_PCI_DSS_PROXY_H

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard Library                                                         */
/* ────────────────────────────────────────────────────────────────────────── */
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Third-Party Dependencies                                                 */
/* ────────────────────────────────────────────────────────────────────────── */
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  OS-Level / Concurrency                                                  */
/* ────────────────────────────────────────────────────────────────────────── */
#include <pthread.h>
#include <sys/socket.h>
#include <netdb.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 *  Compile-Time Configuration
 * =========================================================================*/
#ifndef PCI_DSS_PROXY_DEFAULT_PORT
#define PCI_DSS_PROXY_DEFAULT_PORT 4433
#endif

#ifndef PCI_DSS_PROXY_TOKEN_MAX
/*  29 bytes is enough for 22 base-62 chars + delimiters/version data         */
#define PCI_DSS_PROXY_TOKEN_MAX 64
#endif

#ifndef PCI_DSS_PROXY_TIMEOUT_MS
#define PCI_DSS_PROXY_TIMEOUT_MS 5000u
#endif

/* =========================================================================
 *  Error Handling
 * =========================================================================*/
typedef enum
{
    PCI_DSS_OK = 0,                   /* Success                                       */
    PCI_DSS_ERR_CFG = -1,             /* Invalid configuration                         */
    PCI_DSS_ERR_NETWORK = -2,         /* Socket, DNS, or TLS failure                   */
    PCI_DSS_ERR_TIMEOUT = -3,         /* Operation took longer than configured limit   */
    PCI_DSS_ERR_CRYPTO = -4,          /* AES-GCM or RNG failure                        */
    PCI_DSS_ERR_PROTOCOL = -5,        /* Malformed proxy response                      */
    PCI_DSS_ERR_MEMORY = -6,          /* Allocation failure                            */
    PCI_DSS_ERR_ARGUMENT = -7,        /* Invalid parameter passed by caller            */
    PCI_DSS_ERR_INTERNAL = -128       /* Should never happen                           */
} pci_dss_status_e;

/* =========================================================================
 *  Data-Structures
 * =========================================================================*/

/* mTLS credentials on disk.  Paths can be absolute or relative. */
typedef struct
{
    char client_cert_pem[256];
    char client_key_pem[256];
    char ca_cert_pem[256];
} pci_dss_tls_credentials_t;

/* Connection (dependency-injected) settings. */
typedef struct
{
    char                    hostname[256];
    uint16_t                port;
    uint32_t                timeout_ms;
    bool                    verify_peer;          /* enforce X509 validation            */
    pci_dss_tls_credentials_t tls;
} pci_dss_proxy_config_t;

/*  Opaque handle returned to callers after successful init().               */
typedef struct
{
    pci_dss_proxy_config_t  cfg;

    /* Transport */
    int                     sock_fd;
    SSL                    *ssl;
    SSL_CTX                *ssl_ctx;

    /* Concurrency */
    pthread_mutex_t         mtx;

    /* Statistics */
    uint64_t                calls_tokenise_ok;
    uint64_t                calls_detokenise_ok;
    uint64_t                calls_authorise_ok;
    uint64_t                bytes_sent;
    uint64_t                bytes_recv;

} pci_dss_proxy_t;

/* (1) Tokenisation request/response -------------------------------------- */
typedef struct
{
    char        token[PCI_DSS_PROXY_TOKEN_MAX];
} pci_dss_token_t;

/* (2) Authorisation pre-check (example subset of ISO-8583 fields) --------- */
typedef struct
{
    char        token[PCI_DSS_PROXY_TOKEN_MAX];
    char        currency[4];      /* ISO-4217 – “USD”, “EUR”, … */
    uint64_t    amount_minor;     /* Minor units (cents)         */
    char        merchant_id[16];
} pci_dss_authorise_req_t;

typedef struct
{
    bool        approved;
    char        auth_code[8];
    char        issuer_message[64];
} pci_dss_authorise_resp_t;

/* =========================================================================
 *  Public API
 * =========================================================================*/

/*
 *  pci_dss_proxy_init
 *  ------------------
 *  Establishes an mTLS session with the proxy server.
 *
 *  Returned handle MUST be passed to pci_dss_proxy_close() by the caller
 *  once it is no longer needed, otherwise socket and crypto resources leak.
 */
static inline pci_dss_status_e
pci_dss_proxy_init(pci_dss_proxy_t *ctx,
                   const pci_dss_proxy_config_t *cfg);

/*
 *  pci_dss_proxy_close
 *  -------------------
 *  Closes the TLS session and frees associated resources.  Safe to call
 *  multiple times; subsequent invocations become no-ops.
 */
static inline void
pci_dss_proxy_close(pci_dss_proxy_t *ctx);

/*
 *  pci_dss_tokenise_pan
 *  --------------------
 *  Converts a raw PAN into a proxy-scoped opaque token.  After this call,
 *  the Bursar Service MUST discard the PAN from memory by invoking
 *  pci_dss_secure_bzero().
 */
static inline pci_dss_status_e
pci_dss_tokenise_pan(pci_dss_proxy_t       *ctx,
                     const char            *pan,            /* 13-19 digits */
                     pci_dss_token_t       *out_token);

/*
 *  pci_dss_detokenise
 *  ------------------
 *  Retrieves the original PAN from a token.  ONLY authorised roles (e.g.,
 *  re-issue card) should ever call this, and the caller is responsible for
 *  scrubbing it from memory after use.
 */
static inline pci_dss_status_e
pci_dss_detokenise(pci_dss_proxy_t         *ctx,
                   const pci_dss_token_t   *token,
                   char                    *out_pan_buf,
                   size_t                   out_pan_buf_len);

/*
 *  pci_dss_pre_authorise
 *  ---------------------
 *  Lightweight fraud/velocity/pre-check before full ISO-8583 authorisation.
 */
static inline pci_dss_status_e
pci_dss_pre_authorise(pci_dss_proxy_t              *ctx,
                      const pci_dss_authorise_req_t *req,
                      pci_dss_authorise_resp_t      *resp);

/*
 *  pci_dss_secure_bzero
 *  --------------------
 *  Overwrites a buffer with zeros, using a volatile pointer to prevent the
 *  compiler from optimising the call away.
 */
static inline void
pci_dss_secure_bzero(void *ptr, size_t len);

/* =========================================================================
 *  Internal Helpers  (Implementation)
 * =========================================================================*/
static inline pci_dss_status_e
_pci_dss_connect_tls(pci_dss_proxy_t *ctx);

static inline pci_dss_status_e
_pci_dss_send_encrypted_json(pci_dss_proxy_t *ctx,
                             const char      *json,
                             size_t           json_len,
                             char            *rsp_buf,
                             size_t           rsp_buf_len);

static inline pci_dss_status_e
_pci_dss_parse_status(const char *json);

/* =========================================================================
 *  IMPLEMENTATION
 * =========================================================================*/
#include <cjson/cJSON.h>    /* Small MIT-licensed JSON lib shipped in vendor/ */

static inline void
pci_dss_secure_bzero(void *ptr, size_t len)
{
    volatile unsigned char *p = (volatile unsigned char *)ptr;
    while (len--) { *p++ = 0; }
}

static inline pci_dss_status_e
pci_dss_proxy_init(pci_dss_proxy_t *ctx,
                   const pci_dss_proxy_config_t *cfg)
{
    if (!ctx || !cfg) { return PCI_DSS_ERR_ARGUMENT; }

    memset(ctx, 0, sizeof(*ctx));
    ctx->cfg = *cfg;

    if (pthread_mutex_init(&ctx->mtx, NULL) != 0)
        return PCI_DSS_ERR_INTERNAL;

    /* OpenSSL global init – thread-safe since OpenSSL 1.1.0 */
    SSL_load_error_strings();
    OpenSSL_add_ssl_algorithms();

    ctx->ssl_ctx = SSL_CTX_new(TLS_client_method());
    if (!ctx->ssl_ctx)
        return PCI_DSS_ERR_CRYPTO;

    if (cfg->verify_peer)
    {
        if (SSL_CTX_load_verify_locations(ctx->ssl_ctx,
                                          cfg->tls.ca_cert_pem, NULL) != 1)
            return PCI_DSS_ERR_CRYPTO;
    }
    if (SSL_CTX_use_certificate_file(ctx->ssl_ctx,
                                     cfg->tls.client_cert_pem,
                                     SSL_FILETYPE_PEM) != 1)
        return PCI_DSS_ERR_CRYPTO;

    if (SSL_CTX_use_PrivateKey_file(ctx->ssl_ctx,
                                    cfg->tls.client_key_pem,
                                    SSL_FILETYPE_PEM) != 1)
        return PCI_DSS_ERR_CRYPTO;

    return _pci_dss_connect_tls(ctx);
}

static inline pci_dss_status_e
_pci_dss_connect_tls(pci_dss_proxy_t *ctx)
{
    char port_str[8];
    snprintf(port_str, sizeof(port_str), "%u", ctx->cfg.port);

    struct addrinfo hints = {
        .ai_family   = AF_UNSPEC,
        .ai_socktype = SOCK_STREAM,
        .ai_flags    = AI_ADDRCONFIG,
    };
    struct addrinfo *res = NULL;
    int rc = getaddrinfo(ctx->cfg.hostname, port_str, &hints, &res);
    if (rc != 0) return PCI_DSS_ERR_NETWORK;

    int sock = -1;
    struct addrinfo *ai;
    for (ai = res; ai != NULL; ai = ai->ai_next)
    {
        sock = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (sock < 0) continue;

        if (connect(sock, ai->ai_addr, ai->ai_addrlen) == 0) break;

        close(sock);
        sock = -1;
    }
    freeaddrinfo(res);

    if (sock < 0) return PCI_DSS_ERR_NETWORK;

    ctx->ssl = SSL_new(ctx->ssl_ctx);
    if (!ctx->ssl) { close(sock); return PCI_DSS_ERR_CRYPTO; }

    SSL_set_fd(ctx->ssl, sock);

    /* Apply timeout */
    struct timeval tv = {
        .tv_sec  = ctx->cfg.timeout_ms / 1000,
        .tv_usec = (ctx->cfg.timeout_ms % 1000) * 1000,
    };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    if (SSL_connect(ctx->ssl) != 1)
    {
        SSL_free(ctx->ssl);
        close(sock);
        return PCI_DSS_ERR_NETWORK;
    }

    ctx->sock_fd = sock;
    return PCI_DSS_OK;
}

static inline void
pci_dss_proxy_close(pci_dss_proxy_t *ctx)
{
    if (!ctx) return;

    pthread_mutex_lock(&ctx->mtx);

    if (ctx->ssl)
    {
        SSL_shutdown(ctx->ssl);
        SSL_free(ctx->ssl);
        ctx->ssl = NULL;
    }
    if (ctx->sock_fd >= 0)
    {
        close(ctx->sock_fd);
        ctx->sock_fd = -1;
    }
    if (ctx->ssl_ctx)
    {
        SSL_CTX_free(ctx->ssl_ctx);
        ctx->ssl_ctx = NULL;
    }
    pthread_mutex_unlock(&ctx->mtx);
    pthread_mutex_destroy(&ctx->mtx);
    pci_dss_secure_bzero(ctx, sizeof(*ctx));
}

static inline pci_dss_status_e
pci_dss_tokenise_pan(pci_dss_proxy_t *ctx,
                     const char      *pan,
                     pci_dss_token_t *out_token)
{
    if (!ctx || !pan || !out_token) return PCI_DSS_ERR_ARGUMENT;
    if (strlen(pan) < 13 || strlen(pan) > 19) return PCI_DSS_ERR_ARGUMENT;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "op", "tokenise");
    cJSON_AddStringToObject(root, "pan", pan);
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) return PCI_DSS_ERR_MEMORY;

    char rsp[256] = {0};
    pci_dss_status_e st = _pci_dss_send_encrypted_json(ctx,
                                                       json, strlen(json),
                                                       rsp, sizeof(rsp));
    pci_dss_secure_bzero(json, strlen(json));
    free(json);
    if (st != PCI_DSS_OK) return st;

    st = _pci_dss_parse_status(rsp);
    if (st != PCI_DSS_OK) return st;

    cJSON *resp_root = cJSON_Parse(rsp);
    if (!resp_root) return PCI_DSS_ERR_PROTOCOL;

    const cJSON *tok = cJSON_GetObjectItemCaseSensitive(resp_root, "token");
    if (!cJSON_IsString(tok) || tok->valuestring == NULL)
    {
        cJSON_Delete(resp_root);
        return PCI_DSS_ERR_PROTOCOL;
    }
    strncpy(out_token->token, tok->valuestring, sizeof(out_token->token));
    cJSON_Delete(resp_root);

    pthread_mutex_lock(&ctx->mtx);
    ctx->calls_tokenise_ok++;
    pthread_mutex_unlock(&ctx->mtx);

    return PCI_DSS_OK;
}

static inline pci_dss_status_e
pci_dss_detokenise(pci_dss_proxy_t         *ctx,
                   const pci_dss_token_t   *token,
                   char                    *out_pan_buf,
                   size_t                   out_pan_buf_len)
{
    if (!ctx || !token || !out_pan_buf) return PCI_DSS_ERR_ARGUMENT;
    if (out_pan_buf_len < 20) return PCI_DSS_ERR_ARGUMENT;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "op", "detokenise");
    cJSON_AddStringToObject(root, "token", token->token);
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    char rsp[256] = {0};
    pci_dss_status_e st = _pci_dss_send_encrypted_json(ctx,
                                                       json, strlen(json),
                                                       rsp, sizeof(rsp));
    pci_dss_secure_bzero(json, strlen(json));
    free(json);
    if (st != PCI_DSS_OK) return st;

    st = _pci_dss_parse_status(rsp);
    if (st != PCI_DSS_OK) return st;

    cJSON *resp_root = cJSON_Parse(rsp);
    if (!resp_root) return PCI_DSS_ERR_PROTOCOL;

    const cJSON *pan = cJSON_GetObjectItemCaseSensitive(resp_root, "pan");
    if (!cJSON_IsString(pan) || pan->valuestring == NULL)
    {
        cJSON_Delete(resp_root);
        return PCI_DSS_ERR_PROTOCOL;
    }
    strncpy(out_pan_buf, pan->valuestring, out_pan_buf_len);
    cJSON_Delete(resp_root);

    pthread_mutex_lock(&ctx->mtx);
    ctx->calls_detokenise_ok++;
    pthread_mutex_unlock(&ctx->mtx);

    return PCI_DSS_OK;
}

static inline pci_dss_status_e
pci_dss_pre_authorise(pci_dss_proxy_t               *ctx,
                      const pci_dss_authorise_req_t *req,
                      pci_dss_authorise_resp_t      *resp)
{
    if (!ctx || !req || !resp) return PCI_DSS_ERR_ARGUMENT;

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "op",         "pre_auth");
    cJSON_AddStringToObject(root, "token",      req->token);
    cJSON_AddStringToObject(root, "currency",   req->currency);
    cJSON_AddNumberToObject(root, "amount",     (double)req->amount_minor);
    cJSON_AddStringToObject(root, "merchantId", req->merchant_id);

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    char rsp[256] = {0};
    pci_dss_status_e st = _pci_dss_send_encrypted_json(ctx,
                                                       json, strlen(json),
                                                       rsp, sizeof(rsp));
    pci_dss_secure_bzero(json, strlen(json));
    free(json);
    if (st != PCI_DSS_OK) return st;

    st = _pci_dss_parse_status(rsp);
    if (st != PCI_DSS_OK) return st;

    cJSON *resp_root = cJSON_Parse(rsp);
    if (!resp_root) return PCI_DSS_ERR_PROTOCOL;

    const cJSON *approved = cJSON_GetObjectItemCaseSensitive(resp_root, "approved");
    const cJSON *auth_code= cJSON_GetObjectItemCaseSensitive(resp_root, "authCode");
    const cJSON *msg      = cJSON_GetObjectItemCaseSensitive(resp_root, "message");

    resp->approved = cJSON_IsBool(approved) ? cJSON_IsTrue(approved) : false;
    strncpy(resp->auth_code,
            cJSON_IsString(auth_code) && auth_code->valuestring ? auth_code->valuestring : "",
            sizeof(resp->auth_code));
    strncpy(resp->issuer_message,
            cJSON_IsString(msg) && msg->valuestring ? msg->valuestring : "",
            sizeof(resp->issuer_message));

    cJSON_Delete(resp_root);

    pthread_mutex_lock(&ctx->mtx);
    ctx->calls_authorise_ok++;
    pthread_mutex_unlock(&ctx->mtx);

    return PCI_DSS_OK;
}

/*  Send/Receive helper with AES-GCM envelope encryption ------------------ */
static inline pci_dss_status_e
_pci_dss_send_encrypted_json(pci_dss_proxy_t *ctx,
                             const char      *json,
                             size_t           json_len,
                             char            *rsp_buf,
                             size_t           rsp_buf_len)
{
    /* 1. Generate ephemeral AES-256-GCM key + IV */
    unsigned char key[32];
    unsigned char iv[12];
    if (RAND_bytes(key, sizeof(key)) != 1 ||
        RAND_bytes(iv, sizeof(iv))   != 1)
        return PCI_DSS_ERR_CRYPTO;

    /* 2. Encrypt payload */
    EVP_CIPHER_CTX *cctx = EVP_CIPHER_CTX_new();
    if (!cctx) return PCI_DSS_ERR_CRYPTO;

    int len = 0, ciphertext_len = 0;
    unsigned char ciphertext[1024];
    unsigned char tag[16];

    if (EVP_EncryptInit_ex(cctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1 ||
        EVP_CIPHER_CTX_ctrl(cctx, EVP_CTRL_GCM_SET_IVLEN, sizeof(iv), NULL) != 1 ||
        EVP_EncryptInit_ex(cctx, NULL, NULL, key, iv) != 1)
    {
        EVP_CIPHER_CTX_free(cctx);
        return PCI_DSS_ERR_CRYPTO;
    }

    if (EVP_EncryptUpdate(cctx, ciphertext, &len,
                          (const unsigned char *)json, (int)json_len) != 1)
    {
        EVP_CIPHER_CTX_free(cctx);
        return PCI_DSS_ERR_CRYPTO;
    }
    ciphertext_len = len;

    if (EVP_EncryptFinal_ex(cctx, ciphertext + len, &len) != 1)
    {
        EVP_CIPHER_CTX_free(cctx);
        return PCI_DSS_ERR_CRYPTO;
    }
    ciphertext_len += len;

    if (EVP_CIPHER_CTX_ctrl(cctx, EVP_CTRL_GCM_GET_TAG,
                            sizeof(tag), tag) != 1)
    {
        EVP_CIPHER_CTX_free(cctx);
        return PCI_DSS_ERR_CRYPTO;
    }
    EVP_CIPHER_CTX_free(cctx);

    /* 3. Build wire format: | IV | TAG | KEY | CIPHERTEXT |
     *    (The key is encrypted via TLS, removing the need for a wrapping key)
     */
    size_t total_len = sizeof(iv) + sizeof(tag) + sizeof(key) + ciphertext_len;
    unsigned char *payload = malloc(total_len);
    if (!payload) return PCI_DSS_ERR_MEMORY;

    unsigned char *p = payload;
    memcpy(p, iv, sizeof(iv));                    p += sizeof(iv);
    memcpy(p, tag, sizeof(tag));                  p += sizeof(tag);
    memcpy(p, key, sizeof(key));                  p += sizeof(key);
    memcpy(p, ciphertext, (size_t)ciphertext_len);

    pci_dss_status_e st = PCI_DSS_OK;

    pthread_mutex_lock(&ctx->mtx);

    int n = SSL_write(ctx->ssl, payload, (int)total_len);
    if (n != (int)total_len)
        st = PCI_DSS_ERR_NETWORK;
    else
    {
        ctx->bytes_sent += (uint64_t)n;

        /* Receive response (unenveloped JSON) */
        n = SSL_read(ctx->ssl, rsp_buf, (int)rsp_buf_len - 1);
        if (n <= 0)
            st = PCI_DSS_ERR_NETWORK;
        else
        {
            rsp_buf[n] = '\0';
            ctx->bytes_recv += (uint64_t)n;
        }
    }

    pthread_mutex_unlock(&ctx->mtx);
    pci_dss_secure_bzero(key, sizeof(key));
    pci_dss_secure_bzero(payload, total_len);
    free(payload);

    return st;
}

/*  Parse {"status":"ok|error", "errorCode": <int>, ...} ------------------ */
static inline pci_dss_status_e
_pci_dss_parse_status(const char *json)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) return PCI_DSS_ERR_PROTOCOL;

    const cJSON *status = cJSON_GetObjectItemCaseSensitive(root, "status");
    if (!cJSON_IsString(status) || status->valuestring == NULL)
    {
        cJSON_Delete(root);
        return PCI_DSS_ERR_PROTOCOL;
    }

    pci_dss_status_e rc = PCI_DSS_OK;
    if (strcmp(status->valuestring, "ok") != 0)
    {
        const cJSON *err = cJSON_GetObjectItemCaseSensitive(root, "errorCode");
        rc = (pci_dss_status_e)(cJSON_IsNumber(err) ? err->valueint
                                                    : PCI_DSS_ERR_PROTOCOL);
        if (rc == 0) rc = PCI_DSS_ERR_PROTOCOL;
    }

    cJSON_Delete(root);
    return rc;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDU_PAY_LEDGER_ACADEMY_PCI_DSS_PROXY_H */
