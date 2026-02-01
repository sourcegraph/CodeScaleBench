/**
 * SynestheticCanvas/api-gateway/graphql/resolvers.c
 *
 * Production-grade GraphQL resolver implementations for the SynestheticCanvas
 * API-Gateway.  These resolvers act as a thin facade that translates GraphQL
 * requests into downstream REST/JSON calls, enriches them with observability
 * metadata, performs pagination bookkeeping, and returns the materialized
 * JSON back to the GraphQL runtime.
 *
 * © 2024 SynestheticCanvas Contributors
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <curl/curl.h>
#include <jansson.h>

#include "graphql.h"        /* Project-internal GraphQL runtime abstractions */
#include "logging.h"        /* Structured logger (spdlog-like facade)        */
#include "metrics.h"        /* Prometheus metrics facade                     */
#include "rate_limit.h"     /* Leaky-bucket rate limiter                     */
#include "resolvers.h"      /* Header for this implementation                */

/* -------------------------------------------------------------------------- */
/*                          Compile-time configuration                        */
/* -------------------------------------------------------------------------- */

#ifndef PALETTE_SERVICE_BASE_URL
#define PALETTE_SERVICE_BASE_URL "http://palette-service.internal:8080/v1"
#endif

#ifndef HTTP_TIMEOUT_SECS
#define HTTP_TIMEOUT_SECS 3L
#endif

/* -------------------------------------------------------------------------- */
/*                              Local structures                              */
/* -------------------------------------------------------------------------- */

/* GraphQL resolver context – passed as `void *user_data` by the runtime.     */
typedef struct gql_context {
    logger_t      *log;
    metrics_t     *metrics;
    rate_limiter_t *limiter;
} gql_context_t;


/* libcurl response aggregator */
typedef struct curl_buffer {
    char *data;
    size_t size;
} curl_buffer_t;


/* -------------------------------------------------------------------------- */
/*                       HTTP/REST helper implementation                      */
/* -------------------------------------------------------------------------- */

static size_t curl_buffer_write(void *contents, size_t size, size_t nmemb, void *userp)
{
    size_t realsize    = size * nmemb;
    curl_buffer_t *mem = (curl_buffer_t *)userp;

    char *ptr = realloc(mem->data, mem->size + realsize + 1);
    if (!ptr) {
        /* Out of memory – abort transfer */
        return 0;
    }

    mem->data = ptr;
    memcpy(&(mem->data[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->data[mem->size] = '\0';

    return realsize;
}

/* Perform an HTTP GET and parse the JSON payload. */
static json_t *http_json_get(const char *url, logger_t *log, GQLError **gql_err)
{
    CURL *curl = curl_easy_init();
    if (!curl) {
        LOG_ERROR(log, "curl_easy_init() failed");
        *gql_err = gql_error_new(GQL_ERR_INTERNAL, "Internal HTTP init error");
        return NULL;
    }

    curl_buffer_t chunk = {.data = NULL, .size = 0};

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_buffer_write);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, HTTP_TIMEOUT_SECS);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "SynestheticCanvas-Gateway/1.0");

    CURLcode res = curl_easy_perform(curl);
    long http_status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_status);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        LOG_ERROR(log, "curl_easy_perform() failed: %s", curl_easy_strerror(res));
        free(chunk.data);
        *gql_err = gql_error_new(GQL_ERR_NETWORK, "Upstream network error");
        return NULL;
    }

    if (http_status >= 400) {
        LOG_WARN(log, "Upstream error %ld for GET %s", http_status, url);
        free(chunk.data);

        if (http_status == 404) {
            *gql_err = gql_error_new(GQL_ERR_NOT_FOUND, "Resource not found");
        } else {
            *gql_err = gql_error_new(GQL_ERR_UPSTREAM, "Upstream service error");
        }
        return NULL;
    }

    /* Parse JSON payload */
    json_error_t json_err;
    json_t *json = json_loads(chunk.data, 0, &json_err);
    free(chunk.data);

    if (!json) {
        LOG_ERROR(log, "JSON parse error on line %d: %s", json_err.line, json_err.text);
        *gql_err = gql_error_new(GQL_ERR_INTERNAL, "Invalid upstream JSON");
        return NULL;
    }

    return json;
}

/* -------------------------------------------------------------------------- */
/*                                Validators                                  */
/* -------------------------------------------------------------------------- */

/* Validate a UUID argument (simple length/format check). */
static int validate_uuid_arg(const char *uuid, GQLError **gql_err)
{
    /* Very permissive validation; can be swapped for libcork or libuuid */
    if (!uuid || strlen(uuid) != 36) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "Invalid UUID");
        return -1;
    }
    return 0;
}

/* Extract and validate pagination arguments. */
static int extract_pagination(const json_t *args,
                              size_t *out_first,
                              const char **out_after,
                              GQLError **gql_err)
{
    json_t *first_json = json_object_get(args, "first");
    json_t *after_json = json_object_get(args, "after");

    if (first_json && !json_is_integer(first_json)) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "`first` must be an integer");
        return -1;
    }

    if (after_json && !json_is_string(after_json)) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "`after` must be a string cursor");
        return -1;
    }

    if (first_json) *out_first = (size_t)json_integer_value(first_json);
    if (after_json) *out_after = json_string_value(after_json);

    return 0;
}

/* -------------------------------------------------------------------------- */
/*                          Resolver implementations                          */
/* -------------------------------------------------------------------------- */

/**
 * palette(id: ID!): Palette!
 */
static json_t *resolve_palette(const json_t *args, void *user_data, GQLError **gql_err)
{
    gql_context_t *ctx = (gql_context_t *)user_data;

    const char *id = json_string_value(json_object_get(args, "id"));
    if (validate_uuid_arg(id, gql_err) < 0) {
        return NULL;
    }

    /* Throttle upstream calls */
    if (rate_limiter_acquire(ctx->limiter) != 0) {
        *gql_err = gql_error_new(GQL_ERR_RATE_LIMIT, "Too many requests");
        return NULL;
    }

    char url[512];
    snprintf(url, sizeof(url), "%s/palettes/%s", PALETTE_SERVICE_BASE_URL, id);

    LOG_INFO(ctx->log, "GET %s", url);
    json_t *payload = http_json_get(url, ctx->log, gql_err);
    if (!payload) {
        return NULL;
    }

    METRIC_INC(ctx->metrics, "palette_resolver_success");
    return payload; /* Ownership transferred to GraphQL runtime */
}

/**
 * palettes(first: Int, after: String): PaletteConnection!
 */
static json_t *resolve_palettes(const json_t *args, void *user_data, GQLError **gql_err)
{
    gql_context_t *ctx = (gql_context_t *)user_data;

    size_t first       = 25; /* default page size */
    const char *after  = NULL;

    if (extract_pagination(args, &first, &after, gql_err) < 0) {
        return NULL;
    }

    if (first == 0 || first > 100) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "`first` must be between 1 and 100");
        return NULL;
    }

    /* Construct query string */
    char url[512];
    if (after) {
        snprintf(url, sizeof(url),
                 "%s/palettes?limit=%zu&cursor=%s", PALETTE_SERVICE_BASE_URL, first, after);
    } else {
        snprintf(url, sizeof(url),
                 "%s/palettes?limit=%zu", PALETTE_SERVICE_BASE_URL, first);
    }

    LOG_INFO(ctx->log, "GET %s", url);
    json_t *payload = http_json_get(url, ctx->log, gql_err);
    if (!payload) {
        return NULL;
    }

    METRIC_INC(ctx->metrics, "palettes_resolver_success");
    return payload;
}

/**
 * createPalette(input: CreatePaletteInput!): Palette!
 *
 * For simplicity, we forward the entire JSON payload to the palette service.
 */
static json_t *resolve_create_palette(const json_t *args, void *user_data, GQLError **gql_err)
{
    gql_context_t *ctx = (gql_context_t *)user_data;

    /* Rate limiting */
    if (rate_limiter_acquire(ctx->limiter) != 0) {
        *gql_err = gql_error_new(GQL_ERR_RATE_LIMIT, "Too many requests");
        return NULL;
    }

    /* Validate mandatory fields */
    const json_t *input = json_object_get(args, "input");
    if (!input || !json_is_object(input)) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "`input` must be provided");
        return NULL;
    }

    const char *name = json_string_value(json_object_get(input, "name"));
    if (!name || strlen(name) == 0) {
        *gql_err = gql_error_new(GQL_ERR_VALIDATION, "`name` cannot be empty");
        return NULL;
    }

    /* Serialize input to JSON for POST body */
    char *body = json_dumps(input, JSON_COMPACT);
    if (!body) {
        *gql_err = gql_error_new(GQL_ERR_INTERNAL, "JSON serialization failed");
        return NULL;
    }

    /* Prepare CURL */
    CURL *curl = curl_easy_init();
    if (!curl) {
        free(body);
        *gql_err = gql_error_new(GQL_ERR_INTERNAL, "Internal HTTP init error");
        return NULL;
    }

    char url[512];
    snprintf(url, sizeof(url), "%s/palettes", PALETTE_SERVICE_BASE_URL);

    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_buffer_t chunk = {.data = NULL, .size = 0};

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_buffer_write);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, HTTP_TIMEOUT_SECS);

    LOG_INFO(ctx->log, "POST %s", url);
    CURLcode res = curl_easy_perform(curl);
    long http_status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_status);

    curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    free(body);

    if (res != CURLE_OK) {
        LOG_ERROR(ctx->log, "curl_easy_perform() failed: %s", curl_easy_strerror(res));
        free(chunk.data);
        *gql_err = gql_error_new(GQL_ERR_NETWORK, "Upstream network error");
        return NULL;
    }

    if (http_status >= 400) {
        LOG_WARN(ctx->log, "Upstream error %ld for POST %s", http_status, url);
        free(chunk.data);
        *gql_err = gql_error_new(GQL_ERR_UPSTREAM, "Upstream service error");
        return NULL;
    }

    json_error_t json_err;
    json_t *json = json_loads(chunk.data, 0, &json_err);
    free(chunk.data);

    if (!json) {
        LOG_ERROR(ctx->log, "JSON parse error at line %d: %s", json_err.line, json_err.text);
        *gql_err = gql_error_new(GQL_ERR_INTERNAL, "Invalid upstream JSON");
        return NULL;
    }

    METRIC_INC(ctx->metrics, "create_palette_resolver_success");
    return json;
}

/* -------------------------------------------------------------------------- */
/*                           Registration / bootstrap                         */
/* -------------------------------------------------------------------------- */

/**
 * gql_register_resolvers:
 *
 * Register all resolvers for the palette sub-graph with the GraphQL runtime.
 */
int gql_register_resolvers(GraphQLRuntime *runtime,
                           logger_t *log,
                           metrics_t *metrics,
                           rate_limiter_t *limiter)
{
    if (!runtime) return -EINVAL;

    gql_context_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) {
        LOG_ERROR(log, "Out of memory allocating gql_context_t");
        return -ENOMEM;
    }

    ctx->log     = log;
    ctx->metrics = metrics;
    ctx->limiter = limiter;

    int rc = 0;

    rc |= graphql_register_resolver(runtime, "Query",  "palette",
                                    resolve_palette,       ctx /*user_data*/);

    rc |= graphql_register_resolver(runtime, "Query",  "palettes",
                                    resolve_palettes,      ctx);

    rc |= graphql_register_resolver(runtime, "Mutation","createPalette",
                                    resolve_create_palette, ctx);

    if (rc != 0) {
        LOG_ERROR(log, "Failed to register one or more GraphQL resolvers");
        free(ctx);
        return -1;
    }

    LOG_INFO(log, "Palette resolvers registered successfully");
    return 0;
}

/* -------------------------------------------------------------------------- */
/*                           Graceful shutdown hook                           */
/* -------------------------------------------------------------------------- */

void gql_resolvers_shutdown(GraphQLRuntime *runtime)
{
    /* Currently nothing to free. Add schema-wide cleanup here if needed. */
    (void)runtime;
}

/* -------------------------------------------------------------------------- */
/*                                   EOF                                      */
/* -------------------------------------------------------------------------- */
