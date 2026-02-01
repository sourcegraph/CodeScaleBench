/*
 *  fallback_handlers.c
 *
 *  SynestheticCanvas – API Gateway
 *  ------------------------------------------------------------
 *  REST fallback handlers used when:
 *      1. A legacy REST endpoint is requested.
 *      2. A GraphQL resolver or downstream micro-service is
 *         temporarily unavailable.
 *      3. An unsupported HTTP method or resource is addressed.
 *
 *  The gateway tries to keep the public contract stable, even if
 *  individual services are rebooted or upgraded.  The handlers in
 *  this compilation unit wrap transient errors in a deterministic,
 *  well-structured JSON envelope so that consumer applications
 *  (e.g., WebGL visualisations, Max/MSP patches, Unity shaders)
 *  can degrade gracefully instead of crashing.
 *
 *  ------------------------------------------------------------------
 *  Author  : SynestheticCanvas Core Team
 *  License : MIT
 */

#include "fallback_handlers.h"

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cjson/cJSON.h"          /* Third-party lightweight JSON library */
#include "core/logger.h"          /* Project-wide structured logger        */
#include "core/mime_types.h"      /* Utility for Content-Type resolution   */
#include "core/version.h"         /* Semantic version of the gateway       */

/* ------------------------------------------------------------------ */
/* Static helpers                                                     */
/* ------------------------------------------------------------------ */

/* ISO-8601 timestamp generator (UTC, to the second) */
static void
iso8601_now(char buffer[static 32])
{
    time_t     t  = time(NULL);
    struct tm  tm;
    gmtime_r(&t, &tm);
    strftime(buffer, 32, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

/* Build a standardised error JSON envelope:
 * {
 *   "error": {
 *       "code"     : 404,
 *       "type"     : "NOT_FOUND",
 *       "message"  : "Resource '/v1/foobar' does not exist.",
 *       "timestamp": "2023-11-18T14:27:08Z",
 *       "gateway"  : "v3.2.0"
 *   }
 * }
 */
static char *
build_error_payload(int             code,
                    const char     *type,
                    const char     *message_fmt,
                    ...)
{
    char                iso[32];
    iso8601_now(iso);

    /* Compose `message` (variadic) */
    va_list ap;
    va_start(ap, message_fmt);
    char message[256];
    vsnprintf(message, sizeof(message), message_fmt, ap);
    va_end(ap);

    cJSON *root  = cJSON_CreateObject();
    cJSON *error = cJSON_AddObjectToObject(root, "error");

    cJSON_AddNumberToObject(error, "code", code);
    cJSON_AddStringToObject(error, "type", type);
    cJSON_AddStringToObject(error, "message", message);
    cJSON_AddStringToObject(error, "timestamp", iso);
    cJSON_AddStringToObject(error, "gateway", SC_GATEWAY_VERSION);

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json; /* caller must free() */
}

/* ------------------------------------------------------------------ */
/* Introspection cache: used when the GraphQL engine is offline       */
/* ------------------------------------------------------------------ */

#define INTROSPECTION_CACHE_TTL  30 /* seconds */

typedef struct
{
    char   *body;
    size_t  len;
    time_t  stored_at;
} CachedIntrospection;

static pthread_rwlock_t    g_introspect_lock = PTHREAD_RWLOCK_INITIALIZER;
static CachedIntrospection g_introspect      = { .body = NULL, .len = 0, .stored_at = 0 };

static const char *
read_fallback_introspection(size_t *out_len)
{
    /* Quick path: Is the current cache still fresh? */
    time_t now = time(NULL);

    pthread_rwlock_rdlock(&g_introspect_lock);
    if (g_introspect.body && (now - g_introspect.stored_at) < INTROSPECTION_CACHE_TTL)
    {
        *out_len = g_introspect.len;
        const char *ret = g_introspect.body;
        pthread_rwlock_unlock(&g_introspect_lock);
        return ret;
    }
    pthread_rwlock_unlock(&g_introspect_lock);

    /* Slow path: (Re)load from disk */
    FILE *fp = fopen("/var/lib/synesthetic/introspection_fallback.json", "rb");
    if (!fp)
    {
        LOG_WARN("Failed to open cached introspection file: %s", strerror(errno));
        return NULL;
    }

    if (fseek(fp, 0, SEEK_END) != 0)
    {
        fclose(fp);
        return NULL;
    }

    long len = ftell(fp);
    if (len <= 0 || fseek(fp, 0, SEEK_SET) != 0)
    {
        fclose(fp);
        return NULL;
    }

    char *buf = calloc((size_t)len + 1, 1);
    if (fread(buf, 1, (size_t)len, fp) != (size_t)len)
    {
        LOG_WARN("Incomplete read of introspection fallback.");
        fclose(fp);
        free(buf);
        return NULL;
    }
    fclose(fp);

    pthread_rwlock_wrlock(&g_introspect_lock);

    /* Clear existing cache */
    free(g_introspect.body);
    g_introspect.body      = buf;
    g_introspect.len       = (size_t)len;
    g_introspect.stored_at = now;

    *out_len = g_introspect.len;

    pthread_rwlock_unlock(&g_introspect_lock);
    return buf;
}

/* ------------------------------------------------------------------ */
/* Public handler implementations                                     */
/* ------------------------------------------------------------------ */

RestResponse
rest_fallback_not_found(const RestRequest *req)
{
    LOG_DEBUG("[REST] Not-Found handler for URI '%s'", req->uri);

    char *payload = build_error_payload(
        404,
        "NOT_FOUND",
        "Resource '%s' does not exist.", req->uri);

    RestResponse res = {
        .status_code  = 404,
        .content_type = MIME_APP_JSON,
        .body         = payload,
        .body_len     = strlen(payload),
        .must_free    = true
    };
    return res;
}

RestResponse
rest_fallback_method_not_allowed(const RestRequest *req,
                                 HttpMethod         allowed)
{
    LOG_DEBUG("[REST] Method-Not-Allowed handler for URI '%s'", req->uri);

    const char *method_name = http_method_to_str(req->method);
    const char *allowed_str = http_method_to_str(allowed);

    char *payload = build_error_payload(
        405,
        "METHOD_NOT_ALLOWED",
        "Method %s is not allowed on '%s'. Allowed: %s.",
        method_name,
        req->uri,
        allowed_str);

    RestResponse res = {
        .status_code  = 405,
        .content_type = MIME_APP_JSON,
        .body         = payload,
        .body_len     = strlen(payload),
        .must_free    = true
    };

    /* Add mandatory 'Allow' header (RFC 7231 §6.5.5) */
    res.headers_len = snprintf(res.headers, sizeof res.headers,
                               "Allow: %s\r\n", allowed_str);

    return res;
}

RestResponse
rest_fallback_service_unavailable(const RestRequest *req,
                                  const char        *service_name,
                                  unsigned           retry_after_sec)
{
    LOG_WARN("[REST] Service '%s' unavailable ‑ Fallback triggered for URI '%s'",
             service_name, req->uri);

    char *payload = build_error_payload(
        503,
        "SERVICE_UNAVAILABLE",
        "The %s service is temporarily unavailable. Please retry later.",
        service_name);

    RestResponse res = {
        .status_code  = 503,
        .content_type = MIME_APP_JSON,
        .body         = payload,
        .body_len     = strlen(payload),
        .must_free    = true
    };

    if (retry_after_sec > 0)
    {
        res.headers_len = snprintf(res.headers, sizeof res.headers,
                                   "Retry-After: %u\r\n", retry_after_sec);
    }

    return res;
}

/* Legacy palette endpoint redirect/fallback
 * Historically, users called:
 *      GET /v1/palette/<palette-id>
 * The new canonical route is:
 *      GET /v3/palette?id=<palette-id>
 *
 * We keep the old endpoint alive but mark it as deprecated.
 */
RestResponse
rest_fallback_legacy_palette(const RestRequest *req,
                             const char        *palette_id)
{
    (void)req; /* Not used beyond log. */
    LOG_INFO("[REST] Legacy palette endpoint accessed: id='%s'", palette_id);

    /* Build JSON informing of deprecation */
    cJSON *root  = cJSON_CreateObject();
    cJSON *meta  = cJSON_AddObjectToObject(root, "meta");
    cJSON *data  = cJSON_AddObjectToObject(root, "data");

    cJSON_AddStringToObject(meta, "status",  "DEPRECATED");
    cJSON_AddStringToObject(meta, "target",  "/v3/palette");
    cJSON_AddStringToObject(meta, "message", "This endpoint will be removed in v4.0.0");

    cJSON_AddStringToObject(data, "paletteId", palette_id);
    cJSON_AddStringToObject(data, "redirect", "/v3/palette?id=<paletteId>");

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    RestResponse res = {
        .status_code  = 200,
        .content_type = MIME_APP_JSON,
        .body         = json,
        .body_len     = strlen(json),
        .must_free    = true
    };
    return res;
}

/* Return an introspection JSON snapshot when the GraphQL engine
 * (powered by libgraphqlparser & LLVM JIT) is unreachable.
 */
RestResponse
rest_fallback_graphql_introspection(const RestRequest *req)
{
    (void)req;
    size_t len   = 0;
    const char *body = read_fallback_introspection(&len);

    if (!body)
    {
        /* Last-ditch effort: give a 503 instead of crashing */
        return rest_fallback_service_unavailable(
            req, "GraphQL", /* retry_after = */ 5);
    }

    RestResponse res = {
        .status_code  = 200,
        .content_type = MIME_APP_JSON,
        .body         = (char *)body, /* NOTE: cached pointer, do NOT free. */
        .body_len     = len,
        .must_free    = false
    };
    return res;
}

/* ------------------------------------------------------------------ */
/* Destructor to clean up cache at program termination                */
/* ------------------------------------------------------------------ */

__attribute__((destructor))
static void
cleanup_introspection_cache(void)
{
    pthread_rwlock_wrlock(&g_introspect_lock);
    free(g_introspect.body);
    g_introspect.body = NULL;
    g_introspect.len  = 0;
    pthread_rwlock_unlock(&g_introspect_lock);
}