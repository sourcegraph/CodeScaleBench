/*
 *  SynestheticCanvas API Suite - API Gateway
 *  =========================================
 *  File:    gateway_server.h
 *  Author:  SynestheticCanvas Core Team
 *
 *  Description:
 *      Public interface for the API-Gateway server.  The gateway is responsible
 *      for brokering HTTP/2 REST endpoints, multiplexing GraphQL requests, and
 *      enforcing cross-cutting concerns such as authentication, rate-limiting,
 *      structured logging, and schema version negotiation.
 *
 *      This header intentionally exposes *only* the high-level orchestration
 *      API—internals such as the concrete HTTP stack (libmicrohttpd, nghttp2,
 *      or bespoke epoll loops) remain private so that the surrounding micro-
 *      service constellation can be refactored without breaking dependants.
 *
 *  Usage:
 *      #include <gateway_server.h>
 *
 *      gateway_cfg_t cfg = GATEWAY_CFG_INIT;
 *      cfg.http_port  = 8080;
 *      cfg.graphql_ws = true;
 *
 *      gateway_server_t *srv = gateway_server_create(&cfg, NULL);
 *      if (!srv) {
 *          fprintf(stderr, "Failed to bootstrap API-Gateway\n");
 *          return EXIT_FAILURE;
 *      }
 *
 *      if (gateway_server_start(srv) != GATEWAY_OK) {
 *          gateway_server_destroy(srv);
 *          return EXIT_FAILURE;
 *      }
 *
 *      gateway_server_block(srv); // run until signalled
 *      gateway_server_destroy(srv);
 *
 *  Copyright:
 *      MIT License
 */

#ifndef SYNESTHETICCANVAS_GATEWAY_SERVER_H
#define SYNESTHETICCANVAS_GATEWAY_SERVER_H

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <time.h>

/* Forward declarations to decouple from heavy third-party headers */
struct json_object;        /* opaque json-c object                         */
struct http_request;       /* transport-layer request abstraction          */
struct http_response;      /* transport-layer response abstraction         */
struct gql_doc;            /* parsed GraphQL document                      */
struct gql_schema;         /* loaded GraphQL schema                        */
struct prometheus_ctx;     /* monitoring handle                            */

/* ------------------------------------------------------------------------- */
/* Error handling                                                            */
/* ------------------------------------------------------------------------- */

typedef enum gateway_err_e
{
    GATEWAY_OK = 0,
    GATEWAY_ERR_INVALID_ARG,
    GATEWAY_ERR_OOM,
    GATEWAY_ERR_SOCKET,
    GATEWAY_ERR_TLS,
    GATEWAY_ERR_ROUTING,
    GATEWAY_ERR_SCHEMA,
    GATEWAY_ERR_IO,
    GATEWAY_ERR_INTERNAL
} gateway_err_t;

/* Helper macro to stringify error codes */
const char *gateway_error_str(gateway_err_t code);

/* ------------------------------------------------------------------------- */
/* Logging                                                                   */
/* ------------------------------------------------------------------------- */

typedef enum gateway_log_level_e
{
    GATEWAY_LOG_TRACE = 0,
    GATEWAY_LOG_DEBUG,
    GATEWAY_LOG_INFO,
    GATEWAY_LOG_WARN,
    GATEWAY_LOG_ERROR,
    GATEWAY_LOG_FATAL
} gateway_log_level_t;

/* Callback signature for user-supplied log sinks */
typedef void (*gateway_log_sink_fn)(
    gateway_log_level_t level,
    const char         *component,
    const char         *fmt,
    va_list             args);

/* Registers a custom, thread-safe logging sink; pass NULL to restore default */
void gateway_log_set_sink(gateway_log_sink_fn sink);

/* Runtime log level (affects all components) */
void gateway_log_set_level(gateway_log_level_t new_level);

/* ------------------------------------------------------------------------- */
/* Rate Limiter                                                              */
/* ------------------------------------------------------------------------- */

typedef struct gateway_rate_limiter_s
{
    uint32_t    max_tokens;     /* Burst capacity                           */
    uint32_t    refill_rate;    /* Tokens added per second                  */
    uint32_t    tokens;         /* Current token count (atomic)             */
    time_t      last_refill;    /* For leaky-bucket algorithm               */
} gateway_rate_limiter_t;

/* Thread-safe token acquisition; returns true if request may proceed       */
bool gateway_rate_limiter_consume(gateway_rate_limiter_t *rl, uint32_t cost);

/* ------------------------------------------------------------------------- */
/* Server Configuration                                                      */
/* ------------------------------------------------------------------------- */

#define GATEWAY_MAX_ROOT_DIR  256
#define GATEWAY_MAX_CERT_FILE 256
#define GATEWAY_MAX_KEY_FILE  256

typedef struct gateway_cfg_s
{
    /* Listener configuration */
    uint16_t    http_port;                     /* 0 → disable               */
    uint16_t    https_port;                    /* 0 → disable               */
    bool        http2;                         /* Enable HTTP/2 on TLs      */

    /* TLS details */
    char        tls_cert_file[GATEWAY_MAX_CERT_FILE];
    char        tls_key_file[GATEWAY_MAX_KEY_FILE];

    /* GraphQL specifics */
    bool        graphql_ws;                    /* GraphQL-WS subscriptions  */
    size_t      max_query_depth;               /* 防止 DoS                  */
    size_t      max_query_cost;

    /* REST specifics */
    char        static_root[GATEWAY_MAX_ROOT_DIR];
    bool        enable_static_files;

    /* Rate limiting */
    gateway_rate_limiter_t global_rl;

    /* Monitoring / metrics */
    bool        enable_metrics;
    char        *metrics_namespace;

    /* Reserved for future fields; zero-init with GATEWAY_CFG_INIT           */
    void       *user_data;
} gateway_cfg_t;

/* Convenience initializer */
#define GATEWAY_CFG_INIT                         \
    {                                            \
        .http_port            = 80,              \
        .https_port           = 443,             \
        .http2                = true,            \
        .graphql_ws           = true,            \
        .max_query_depth      = 15,              \
        .max_query_cost       = 5000,            \
        .static_root          = "./public",      \
        .enable_static_files  = true,            \
        .global_rl            = {                \
            .max_tokens  = 1024,                 \
            .refill_rate = 256,                  \
            .tokens      = 1024,                 \
            .last_refill = 0                     \
        },                                       \
        .enable_metrics       = true,            \
        .metrics_namespace    = "syn_canvas",    \
        .user_data            = NULL             \
    }

/* ------------------------------------------------------------------------- */
/* Opaque handle                                                             */
/* ------------------------------------------------------------------------- */

typedef struct gateway_server_s gateway_server_t;

/* ------------------------------------------------------------------------- */
/* Callback Types                                                            */
/* ------------------------------------------------------------------------- */

/* REST handler: populate `rsp` on success; return appropriate status code   */
typedef gateway_err_t (*gateway_rest_handler_fn)(
    const struct http_request  *req,
    struct http_response       *rsp,
    void                       *user_ctx);

/* GraphQL resolver for a specific field or type                             */
typedef gateway_err_t (*gateway_gql_resolver_fn)(
    const struct gql_doc  *document,
    struct json_object    *variables,
    struct json_object   **out_value,
    void                  *user_ctx);

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

/*
 * gateway_server_create:
 *     Allocates and configures a new server instance.  Ownership of `cfg` is
 *     not transferred—the caller may free it immediately after the call returns.
 *
 *     On success, returns a valid pointer; on failure, returns NULL and sets
 *     `*out_err` (if non-NULL).
 */
gateway_server_t *
gateway_server_create(const gateway_cfg_t *cfg,
                      gateway_err_t       *out_err);

/*
 * gateway_server_destroy:
 *     Gracefully shuts down (if running) and releases all resources.  The call
 *     blocks until all background threads have terminated.
 */
void
gateway_server_destroy(gateway_server_t *srv);

/*
 * gateway_server_start:
 *     Begins listening on the configured interfaces.  Non-blocking; returns once
 *     sockets are bound and worker threads launched.
 */
gateway_err_t
gateway_server_start(gateway_server_t *srv);

/*
 * gateway_server_block:
 *     Enters an indefinite loop processing requests until the server receives
 *     SIGINT, SIGTERM, or an equivalent stop signal from `gateway_server_stop`.
 *
 *     Intended for simple deployments; sophisticated runners may prefer to
 *     integrate the gateway into an existing event loop instead.
 */
gateway_err_t
gateway_server_block(gateway_server_t *srv);

/*
 * gateway_server_stop:
 *     Initiates a graceful shutdown; active requests are given up to
 *     `timeout_ms` to complete before force-termination.
 */
gateway_err_t
gateway_server_stop(gateway_server_t *srv, uint32_t timeout_ms);

/*
 * gateway_server_register_route:
 *     Register a REST endpoint.  `method` must be uppercase (“GET”, “POST”…).
 *     The framework copies `path` internally.
 *
 *     Returns GATEWAY_ERR_ROUTING if the path clashes with an existing route.
 */
gateway_err_t
gateway_server_register_route(gateway_server_t          *srv,
                              const char                *method,
                              const char                *path,
                              gateway_rest_handler_fn    handler,
                              void                      *user_ctx);

/*
 * gateway_server_register_gql_resolver:
 *     Attach a field resolver to the active schema.  If `schema_name` is NULL,
 *     the resolver applies to the *current* default schema (across versions).
 */
gateway_err_t
gateway_server_register_gql_resolver(gateway_server_t         *srv,
                                     const char               *type_name,
                                     const char               *field_name,
                                     gateway_gql_resolver_fn   resolver,
                                     void                     *user_ctx,
                                     const char               *schema_name);

/*
 * gateway_server_reload_schema:
 *     Hot-swap the GraphQL schema from an SDL string or on-disk file.
 *     If `is_file` is true, `source` is treated as a file path.
 *
 *     The function validates the new schema and rejects it if breaking changes
 *     are detected according to SynestheticCanvas’s versioning policy.
 */
gateway_err_t
gateway_server_reload_schema(gateway_server_t *srv,
                             const char       *source,
                             bool              is_file);

/*
 * gateway_server_prometheus_handle:
 *     Expose the internal Prometheus context for advanced metrics consumers.
 *     May return NULL if metrics are disabled.
 */
struct prometheus_ctx *
gateway_server_prometheus_handle(gateway_server_t *srv);

/*
 * gateway_server_healthcheck:
 *     Lightweight probe to indicate whether the server is alive *and* accepting
 *     new requests (useful for Kubernetes style health probes).
 */
bool
gateway_server_healthcheck(const gateway_server_t *srv);

/* ------------------------------------------------------------------------- */
/* C++ friendly footer                                                       */
/* ------------------------------------------------------------------------- */
#ifdef __cplusplus
}
#endif

#endif /* SYNESTHETICCANVAS_GATEWAY_SERVER_H */
