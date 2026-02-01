/*
 * SynestheticCanvas API Gateway
 * ---------------------------------
 * Middleware: auth.c
 *
 * Centralised authentication / authorisation middleware layer.
 * Verifies JWT bearer tokens, rejects unauthenticated calls, and
 * injects the verified user context into the request structure
 * so that downstream handlers can rely on `req->principal`.
 *
 * Dependencies:
 *   - OpenSSL (libcrypto) for HMAC-SHA256
 *   - Jansson (libjansson) for JSON parsing
 *
 * This module purposefully uses *only* stable C11 and battle-tested
 * third-party libraries that are ubiquitous on modern Linux distros.
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include <ctype.h>
#include <errno.h>
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <jansson.h>

#include "auth.h"       /* Interface of this middleware            */
#include "config.h"     /* Global gateway configuration            */
#include "http.h"       /* Request / response abstraction          */
#include "logger.h"     /* syslog-style logging wrapper            */

/* ---------------------------------------------------------------------
 * Internal helpers – minimal string / memory utilities
 * ------------------------------------------------------------------ */

static char *str_dup_range(const char *start, const char *end)
{
    const size_t len = (size_t)(end - start);
    char *out       = (char *)malloc(len + 1);
    if (!out) return NULL;

    memcpy(out, start, len);
    out[len] = '\0';
    return out;
}

/* We need a base64url decoding routine because OpenSSL only deals with
 * RFC 4648 §4 (standard base64) by default. This helper converts the
 * URL-safe alphabet in-place and adds padding back before delegating to
 * OpenSSL. */
static unsigned char *base64url_decode(const char *in, size_t *out_len)
{
    if (!in) return NULL;

    const size_t in_len = strlen(in);
    /* Prepare scratch buffer with room for padding */
    char *tmp      = (char *)malloc(in_len + 4);
    if (!tmp) return NULL;

    /* Copy while converting URL-safe chars */
    size_t i, j = 0;
    for (i = 0; i < in_len; ++i) {
        if (in[i] == '-') tmp[j++] = '+';
        else if (in[i] == '_') tmp[j++] = '/';
        else if (in[i] == '\n' || in[i] == '\r') continue;
        else tmp[j++] = in[i];
    }

    /* Add required padding */
    const size_t mod = j % 4;
    if (mod) {
        const size_t pad = 4 - mod;
        for (i = 0; i < pad; ++i) tmp[j++] = '=';
    }
    tmp[j] = '\0';

    BIO *b64 = BIO_new(BIO_f_base64());
    BIO *bio = BIO_new_mem_buf(tmp, (int)j);
    if (!b64 || !bio) {
        free(tmp);
        if (b64) BIO_free(b64);
        if (bio) BIO_free(bio);
        return NULL;
    }
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    bio = BIO_push(b64, bio);

    unsigned char *buffer = (unsigned char *)malloc(j); /* upper bound */
    if (!buffer) {
        BIO_free_all(bio);
        free(tmp);
        return NULL;
    }

    const int decoded_size = BIO_read(bio, buffer, (int)j);
    if (decoded_size <= 0) {
        free(buffer);
        buffer = NULL;
    } else {
        *out_len = (size_t)decoded_size;
    }

    BIO_free_all(bio);
    free(tmp);

    return buffer;
}

/* Constant-time string comparison to mitigate timing attacks */
static int secure_equals(const unsigned char *a, const unsigned char *b,
                         size_t len)
{
    unsigned char diff = 0;
    for (size_t i = 0; i < len; ++i) diff |= a[i] ^ b[i];
    return diff == 0;
}

/* ---------------------------------------------------------------------
 * JWT verification
 * ------------------------------------------------------------------ */

typedef struct
{
    char *sub;     /* User / service identity                */
    char *scope;   /* Authorisation scope, e.g. "read:media" */
    time_t exp;    /* Expiration epoch seconds               */
} jwt_claims_t;

static void jwt_claims_destroy(jwt_claims_t *c)
{
    if (!c) return;
    free(c->sub);
    free(c->scope);
    free(c);
}

/* Extract header.payload.signature parts of the JWT. Caller frees. */
static int jwt_split(const char *jwt,
                     char **header_b64, char **payload_b64, char **signature_b64)
{
    const char *dot1 = strchr(jwt, '.');
    if (!dot1) return -1;
    const char *dot2 = strchr(dot1 + 1, '.');
    if (!dot2) return -1;

    *header_b64    = str_dup_range(jwt, dot1);
    *payload_b64   = str_dup_range(dot1 + 1, dot2);
    *signature_b64 = strdup(dot2 + 1);

    return (*header_b64 && *payload_b64 && *signature_b64) ? 0 : -1;
}

static jwt_claims_t *jwt_parse_and_verify(const char *jwt, const char *shared_key,
                                          char **err_msg_out)
{
    char *hdr_b64 = NULL;
    char *pld_b64 = NULL;
    char *sig_b64 = NULL;

    if (jwt_split(jwt, &hdr_b64, &pld_b64, &sig_b64) != 0) {
        if (err_msg_out) *err_msg_out = strdup("Invalid token format");
        goto fail;
    }

    /* Decode and parse header */
    size_t hdr_len = 0;
    unsigned char *hdr_raw = base64url_decode(hdr_b64, &hdr_len);
    if (!hdr_raw) {
        if (err_msg_out) *err_msg_out = strdup("Unable to decode header");
        goto fail;
    }
    json_error_t jerr;
    json_t *hdr_json = json_loadb((const char *)hdr_raw, hdr_len, 0, &jerr);
    free(hdr_raw);
    if (!hdr_json) {
        if (err_msg_out) *err_msg_out = strdup("Corrupted JWT header");
        goto fail;
    }
    const char *alg = json_string_value(json_object_get(hdr_json, "alg"));
    if (!alg || strcmp(alg, "HS256") != 0) {
        if (err_msg_out) *err_msg_out =
            strdup("Unsupported or missing alg (expecting HS256)");
        json_decref(hdr_json);
        goto fail;
    }
    json_decref(hdr_json);

    /* Validate signature -------------------------------------------- */
    /* Compute HMAC of "<header_b64>.<payload_b64>"                    */
    size_t message_len = strlen(hdr_b64) + 1 + strlen(pld_b64);
    char *message      = (char *)malloc(message_len + 1);
    if (!message) {
        if (err_msg_out) *err_msg_out = strdup("Out-of-memory");
        goto fail;
    }
    sprintf(message, "%s.%s", hdr_b64, pld_b64);

    unsigned char mac[EVP_MAX_MD_SIZE];
    unsigned int mac_len = 0;
    HMAC(EVP_sha256(), shared_key, (int)strlen(shared_key),
         (unsigned char *)message, (int)message_len,
         mac, &mac_len);

    size_t sig_bin_len = 0;
    unsigned char *sig_bin = base64url_decode(sig_b64, &sig_bin_len);
    if (!sig_bin) {
        if (err_msg_out) *err_msg_out = strdup("Bad signature encoding");
        free(message);
        goto fail;
    }

    const int sig_ok = (mac_len == sig_bin_len) &&
                       secure_equals(mac, sig_bin, mac_len);

    free(message);
    free(sig_bin);

    if (!sig_ok) {
        if (err_msg_out) *err_msg_out = strdup("Signature mismatch");
        goto fail;
    }

    /* Decode claims (payload) -------------------------------------- */
    size_t pld_len = 0;
    unsigned char *pld_raw = base64url_decode(pld_b64, &pld_len);
    if (!pld_raw) {
        if (err_msg_out) *err_msg_out = strdup("Unable to decode payload");
        goto fail;
    }

    json_t *pld_json = json_loadb((const char *)pld_raw, pld_len, 0, &jerr);
    free(pld_raw);
    if (!pld_json) {
        if (err_msg_out) *err_msg_out = strdup("Corrupted JWT payload");
        goto fail;
    }

    jwt_claims_t *claims = calloc(1, sizeof(jwt_claims_t));
    if (!claims) {
        json_decref(pld_json);
        if (err_msg_out) *err_msg_out = strdup("Out-of-memory");
        goto fail;
    }

    /* Required claims */
    json_t *sub_j = json_object_get(pld_json, "sub");
    json_t *exp_j = json_object_get(pld_json, "exp");
    if (!json_is_string(sub_j) || !json_is_integer(exp_j)) {
        if (err_msg_out) *err_msg_out = strdup("Missing required claims");
        json_decref(pld_json);
        jwt_claims_destroy(claims);
        goto fail;
    }

    claims->sub = strdup(json_string_value(sub_j));
    claims->exp = (time_t)json_integer_value(exp_j);

    /* Optional scope */
    json_t *scp_j = json_object_get(pld_json, "scope");
    if (json_is_string(scp_j)) claims->scope = strdup(json_string_value(scp_j));

    json_decref(pld_json);

    /* Expiration check */
    const time_t now = time(NULL);
    if (claims->exp < now) {
        if (err_msg_out) *err_msg_out = strdup("Token has expired");
        jwt_claims_destroy(claims);
        goto fail;
    }

    free(hdr_b64);
    free(pld_b64);
    free(sig_b64);

    return claims;

fail:
    free(hdr_b64);
    free(pld_b64);
    free(sig_b64);
    return NULL;
}

/* ---------------------------------------------------------------------
 * Middleware public interface
 * ------------------------------------------------------------------ */

/* Public endpoints don't require authentication (health-checks etc.) */
static const char *PUBLIC_ENDPOINTS[] = {
    "/health",
    "/metrics",
    "/version",
    NULL
};

static int is_public_endpoint(const char *path)
{
    for (const char **p = PUBLIC_ENDPOINTS; *p; ++p) {
        if (strcmp(*p, path) == 0) return 1;
    }
    return 0;
}

/*
 * Entry point. Returns HTTP status code.
 * When verification succeeds, the request's `principal` pointer will
 * be populated with a freshly allocated `principal_t` structure.
 * Ownership of that pointer is transferred to the REQUEST object and
 * must be freed when the request completes (see http_request_destroy()).
 */
int auth_middleware_handle(http_request_t *req, http_response_t *res,
                           next_handler_fn next, void *user_data)
{
    if (!req || !res) return HTTP_INTERNAL_SERVER_ERROR;

    /* Skip auth for public resources */
    if (is_public_endpoint(req->path)) {
        return next(req, res, user_data);
    }

    const char *auth_hdr = http_request_header(req, "Authorization");
    if (!auth_hdr || strncmp(auth_hdr, "Bearer ", 7) != 0) {
        LOG_WARN("Unauthenticated request to %s (missing bearer token)",
                 req->path);
        http_response_set_status(res, HTTP_UNAUTHORIZED);
        http_response_set_header(res, "Content-Type", "application/json");
        http_response_write(res,
                            "{\"error\":\"Missing or invalid authorization "
                            "header\"}");
        return HTTP_UNAUTHORIZED;
    }

    const char *jwt_token = auth_hdr + 7;

    char *verify_err = NULL;
    jwt_claims_t *claims =
        jwt_parse_and_verify(jwt_token, config_get()->auth.shared_secret,
                             &verify_err);
    if (!claims) {
        LOG_WARN("JWT verification failed: %s", verify_err ? verify_err : "");
        http_response_set_status(res, HTTP_UNAUTHORIZED);
        http_response_set_header(res, "Content-Type", "application/json");
        http_response_write(res,
                            "{\"error\":\"Invalid or expired token\"}");
        free(verify_err);
        return HTTP_UNAUTHORIZED;
    }

    /* Populate principal ------------------------------------------- */
    principal_t *principal = principal_create(claims->sub, claims->scope);
    jwt_claims_destroy(claims);
    if (!principal) {
        http_response_set_status(res, HTTP_INTERNAL_SERVER_ERROR);
        return HTTP_INTERNAL_SERVER_ERROR;
    }
    req->principal = principal;

    /* Continue down the middleware chain */
    const int downstream_status = next(req, res, user_data);

    /* Cleanup (principal will be freed by request destructor after
     * the whole pipeline finishes). */
    return downstream_status;
}

/* ---------------------------------------------------------------------
 * Public helper to create an Authorization header from credentials
 * (Used by internal unit tests & client SDK generator)
 * ------------------------------------------------------------------ */
char *auth_build_bearer_header(const char *jwt_token)
{
    if (!jwt_token) return NULL;
    const size_t len = strlen(jwt_token) + 7 + 1;
    char *hdr          = (char *)malloc(len);
    if (!hdr) return NULL;
    sprintf(hdr, "Bearer %s", jwt_token);
    return hdr;
}