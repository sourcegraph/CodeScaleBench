```c
/*
 *  SynestheticCanvas – REST Router
 *
 *  File:    api-gateway/include/rest/router.h
 *  Author:  SynestheticCanvas Core Team
 *  License: MIT
 *
 *  Description:
 *      Header-only (optional) REST router for the SynestheticCanvas API-Gateway.
 *      Exposes an ergonomic API to register routes, middlewares, and validators
 *      that map HTTP requests to C handlers.  Designed for low-latency,
 *      high-throughput micro-service environments with first-class support for
 *      versioning, rate-limiting, and structured observability.
 *
 *  Usage:
 *      #define SC_REST_ROUTER_IMPLEMENTATION
 *      #include "rest/router.h"
 *
 *      // See bottom of file for example.
 */

#ifndef SC_REST_ROUTER_H
#define SC_REST_ROUTER_H

/* -------------------------------------------------------------------------
 *  Standard & third-party dependencies
 * ------------------------------------------------------------------------- */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 *  Compiler annotations
 * ------------------------------------------------------------------------- */
#if defined(__GNUC__) || defined(__clang__)
#   define SC_NONNULL(...)   __attribute__((nonnull(__VA_ARGS__)))
#   define SC_PRINTF(a, b)   __attribute__((format(printf, a, b)))
#   define SC_NORETURN       __attribute__((noreturn))
#else
#   define SC_NONNULL(...)
#   define SC_PRINTF(a, b)
#   define SC_NORETURN
#endif

/* -------------------------------------------------------------------------
 *  Constants & Limits
 * ------------------------------------------------------------------------- */
#ifndef SC_REST_MAX_PATH_LEN
#   define SC_REST_MAX_PATH_LEN      512
#endif

#ifndef SC_REST_MAX_METHOD_LEN
#   define SC_REST_MAX_METHOD_LEN     16
#endif

#ifndef SC_REST_MAX_ROUTE_SEGMENTS
#   define SC_REST_MAX_ROUTE_SEGMENTS 32
#endif

#ifndef SC_REST_DEFAULT_CAPACITY
#   define SC_REST_DEFAULT_CAPACITY   64
#endif

/* -------------------------------------------------------------------------
 *  Logging helpers (delegate to user’s logging facility)
 * ------------------------------------------------------------------------- */
#ifndef SC_LOG_INFO
#   include <stdio.h>
#   define SC_LOG_INFO(fmt, ...)   fprintf(stderr, "[INFO] " fmt "\n", ##__VA_ARGS__)
#   define SC_LOG_WARN(fmt, ...)   fprintf(stderr, "[WARN] " fmt "\n", ##__VA_ARGS__)
#   define SC_LOG_ERROR(fmt, ...)  fprintf(stderr, "[ERR ] " fmt "\n", ##__VA_ARGS__)
#endif

/* -------------------------------------------------------------------------
 *  HTTP primitives
 * ------------------------------------------------------------------------- */
typedef enum {
    SC_HTTP_UNKNOWN = 0,
    SC_HTTP_GET,
    SC_HTTP_POST,
    SC_HTTP_PUT,
    SC_HTTP_PATCH,
    SC_HTTP_DELETE,
    SC_HTTP_HEAD,
    SC_HTTP_OPTIONS,
    SC_HTTP_TRACE,
    SC_HTTP_CONNECT
} sc_http_method_t;

/* Mask for quick method checks */
typedef uint16_t sc_http_method_mask_t;
#define SC_HTTP_METHOD_BIT(m)   (1u << (m))

/* -------------------------------------------------------------------------
 *  Versioning
 * ------------------------------------------------------------------------- */
typedef struct {
    uint16_t    major;
    uint16_t    minor;
} sc_api_version_t;

/* -------------------------------------------------------------------------
 *  Forward declarations
 * ------------------------------------------------------------------------- */
struct sc_rest_request;
struct sc_rest_response;
struct sc_rest_router;
struct sc_rest_route;
struct sc_rate_limiter;

/* -------------------------------------------------------------------------
 *  Error codes
 * ------------------------------------------------------------------------- */
typedef enum {
    SC_ROUTER_OK = 0,
    SC_ROUTER_ENOMEM,
    SC_ROUTER_EINVAL,
    SC_ROUTER_ENOTFOUND,
    SC_ROUTER_EOVERFLOW,
    SC_ROUTER_ERATELIMIT,
} sc_router_err_t;

/* -------------------------------------------------------------------------
 *  REST request / response abstraction
 * ------------------------------------------------------------------------- */
typedef struct sc_key_value {
    const char *key;
    const char *value;
} sc_key_value_t;

typedef struct sc_rest_request {
    sc_http_method_t  method;
    const char       *raw_path;       /* Full path incl. query string           */
    const char       *path;           /* Sanitised path without query           */
    const char       *query;          /* Query string (may be NULL)             */
    const uint8_t    *body;           /* Optional payload                       */
    size_t            body_len;
    const sc_key_value_t *headers;    /* Read-only header‐array                 */
    size_t            header_count;
    void             *user_data;      /* Framework-level opaque pointer         */
} sc_rest_request_t;

typedef struct sc_rest_response {
    uint16_t          status;         /* HTTP status code                       */
    sc_key_value_t   *headers;        /* Mutable header collection              */
    size_t            header_count;
    uint8_t          *body;           /* Mutable response body                  */
    size_t            body_len;
    /* Custom allocator hooks for body/header growth can be installed if req.  */
} sc_rest_response_t;

/* -------------------------------------------------------------------------
 *  Handler & middleware signatures
 * ------------------------------------------------------------------------- */
typedef int (*sc_rest_handler_fn)(const sc_rest_request_t  *req,
                                  sc_rest_response_t       *res,
                                  void                     *ctx);

typedef int (*sc_rest_middleware_fn)(const sc_rest_request_t  *req,
                                     sc_rest_response_t       *res,
                                     void                     *ctx,
                                     sc_rest_handler_fn        next);

/* -------------------------------------------------------------------------
 *  Route definition
 * ------------------------------------------------------------------------- */
typedef struct sc_route_spec {
    const char            *pattern;      /* e.g. "/v{version}/palette/{id}"     */
    sc_http_method_mask_t  methods;      /* Allowed methods bitmask             */
    sc_rest_handler_fn     handler;      /* Final handler                       */
    sc_rest_middleware_fn  validator;    /* Optional request validator          */
    sc_rate_limiter       *rlimit;       /* Optional rate limiter               */
    sc_api_version_t       min_version;  /* Inclusive minimum supported ver.    */
    sc_api_version_t       max_version;  /* Inclusive maximum supported ver.    */
    void                  *user_ctx;     /* Injected as last arg to handler     */
} sc_route_spec_t;

typedef struct sc_rest_route {
    char                  *pattern;
    size_t                 segment_count;
    char                 **segments;     /* Tokenised pattern segments          */
    sc_http_method_mask_t  methods;
    sc_rest_handler_fn     handler;
    sc_rest_middleware_fn  validator;
    sc_rate_limiter       *rlimit;
    sc_api_version_t       min_version;
    sc_api_version_t       max_version;
    void                  *user_ctx;
} sc_rest_route_t;

/* -------------------------------------------------------------------------
 *  Router container
 * ------------------------------------------------------------------------- */
typedef struct sc_rest_router {
    sc_rest_route_t  *routes;
    size_t            route_count;
    size_t            capacity;
    sc_rest_middleware_fn *global_middleware;
    size_t            global_mw_count;
} sc_rest_router_t;

/* -------------------------------------------------------------------------
 *  Public API
 * ------------------------------------------------------------------------- */

/* Initialise / destroy router */
sc_router_err_t
sc_rest_router_init(sc_rest_router_t *router,
                    size_t            initial_capacity);

void
sc_rest_router_cleanup(sc_rest_router_t *router);

/* Register a route. Returns index >=0 on success. */
int
sc_rest_router_add(sc_rest_router_t   *router,
                   const sc_route_spec_t *spec) SC_NONNULL(1,2);

/* Register a global middleware (executed for every request before route-level
 * middleware). They are executed in the order they were added.
 */
sc_router_err_t
sc_rest_router_use(sc_rest_router_t      *router,
                   sc_rest_middleware_fn  mw) SC_NONNULL(1,2);

/* Dispatch a request. Returns 0 on success, negative error code otherwise.
 * The function will invoke middlewares, rate limiters, version checks, etc.
 */
int
sc_rest_router_dispatch(sc_rest_router_t          *router,
                        const sc_rest_request_t   *req,
                        sc_rest_response_t        *res) SC_NONNULL(1,2,3);

/* Utility: Convert HTTP method string to enum */
sc_http_method_t
sc_http_method_from_str(const char *method) SC_NONNULL(1);

/* Utility: Bitmask for a HTTP method */
static inline sc_http_method_mask_t
sc_http_method_mask(sc_http_method_t m) { return SC_HTTP_METHOD_BIT(m); }

/* -------------------------------------------------------------------------
 *  Built-in simple token-bucket rate limiter (optional)
 * ------------------------------------------------------------------------- */
typedef struct sc_rate_limiter {
    uint32_t        capacity;   /* Max tokens                   */
    uint32_t        tokens;     /* Current tokens               */
    double          refill_rate;/* Tokens per second            */
    struct timespec last_check; /* Last time tokens were added  */
} sc_rate_limiter_t;

/* Initialize rate limiter */
void
sc_rate_limiter_init(sc_rate_limiter_t *rlim,
                     uint32_t           capacity,
                     double             refill_rate) SC_NONNULL(1);

/* Consume 1 token, returns true if allowed */
bool
sc_rate_limiter_allow(sc_rate_limiter_t *rlim) SC_NONNULL(1);

/* -------------------------------------------------------------------------
 *  Header-only implementation
 * ------------------------------------------------------------------------- */
#ifdef SC_REST_ROUTER_IMPLEMENTATION
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>

/* ------------------------------------------------- Internal helpers ------- */
static inline size_t
sc_strnlen_s(const char *s, size_t maxlen)
{
    size_t len = 0;
    if (!s) return 0;
    while (len < maxlen && *s++) ++len;
    return len;
}

static char *
sc_strdup_n(const char *src, size_t n)
{
    char *dup = (char *) malloc(n + 1);
    if (!dup) return NULL;
    memcpy(dup, src, n);
    dup[n] = '\0';
    return dup;
}

/* Tokenise path pattern into segments separated by '/' */
static int
sc_route_tokenise(sc_rest_route_t *route, const char *pattern)
{
    char *copy, *tok, *ctx = NULL;
    size_t count = 0;

    copy = strdup(pattern);
    if (!copy) return -1;

    /* First pass: count segments */
    tok = strtok_r(copy, "/", &ctx);
    while (tok && count < SC_REST_MAX_ROUTE_SEGMENTS) {
        ++count;
        tok = strtok_r(NULL, "/", &ctx);
    }
    free(copy);

    if (count >= SC_REST_MAX_ROUTE_SEGMENTS)
        return -1;

    route->segment_count = count;
    route->segments = (char **) calloc(count, sizeof(char *));
    if (!route->segments) return -1;

    copy = strdup(pattern);
    if (!copy) return -1;

    tok = strtok_r(copy, "/", &ctx);
    for (size_t i = 0; i < count && tok; ++i) {
        route->segments[i] = strdup(tok);
        if (!route->segments[i]) goto oom;
        tok = strtok_r(NULL, "/", &ctx);
    }
    free(copy);
    return 0;
oom:
    free(copy);
    for (size_t i = 0; i < count; ++i) free(route->segments[i]);
    free(route->segments);
    return -1;
}

/* Compare request path with route segments (simple literal & '{param}' subs) */
static bool
sc_route_match(const sc_rest_route_t *route,
               const char            *path,
               sc_api_version_t       version)
{
    char *copy = NULL, *tok, *ctx = NULL;
    size_t seg_idx = 0;

    /* Version gate */
    if (version.major < route->min_version.major ||
        version.major > route->max_version.major)
        return false;

    copy = strdup(path);
    if (!copy) return false;

    tok = strtok_r(copy, "/", &ctx);
    while (tok && seg_idx < route->segment_count) {
        const char *seg = route->segments[seg_idx];

        if (seg[0] == '{' && seg[strlen(seg)-1] == '}') {
            /* Wildcard segment – always matches */
        } else if (strcmp(seg, tok) != 0) {
            free(copy);
            return false; /* Literal mismatch */
        }
        ++seg_idx;
        tok = strtok_r(NULL, "/", &ctx);
    }
    free(copy);
    return (seg_idx == route->segment_count && !tok);
}

/* ------------------------------------------------ Router implementation --- */
sc_router_err_t
sc_rest_router_init(sc_rest_router_t *router,
                    size_t            initial_capacity)
{
    if (!router) return SC_ROUTER_EINVAL;
    if (initial_capacity == 0)
        initial_capacity = SC_REST_DEFAULT_CAPACITY;

    router->routes  = (sc_rest_route_t *) calloc(initial_capacity,
                                                 sizeof(sc_rest_route_t));
    router->route_count = 0;
    router->capacity = initial_capacity;
    router->global_middleware = NULL;
    router->global_mw_count = 0;

    return router->routes ? SC_ROUTER_OK : SC_ROUTER_ENOMEM;
}

void
sc_rest_router_cleanup(sc_rest_router_t *router)
{
    if (!router) return;
    for (size_t i = 0; i < router->route_count; ++i) {
        sc_rest_route_t *r = &router->routes[i];
        free(r->pattern);
        for (size_t j = 0; j < r->segment_count; ++j)
            free(r->segments[j]);
        free(r->segments);
    }
    free(router->routes);
    free(router->global_middleware);
    memset(router, 0, sizeof(*router));
}

int
sc_rest_router_add(sc_rest_router_t   *router,
                   const sc_route_spec_t *spec)
{
    if (!router || !spec || !spec->pattern || !spec->handler)
        return -SC_ROUTER_EINVAL;

    if (router->route_count == router->capacity) {
        size_t new_cap = router->capacity * 2;
        sc_rest_route_t *tmp = (sc_rest_route_t *) realloc(
                router->routes, new_cap * sizeof(sc_rest_route_t));
        if (!tmp) return -SC_ROUTER_ENOMEM;
        router->routes = tmp;
        router->capacity = new_cap;
    }

    sc_rest_route_t *route = &router->routes[router->route_count];
    memset(route, 0, sizeof(*route));

    route->pattern = strdup(spec->pattern);
    if (!route->pattern) return -SC_ROUTER_ENOMEM;

    if (sc_route_tokenise(route, spec->pattern) != 0) {
        free(route->pattern);
        return -SC_ROUTER_EOVERFLOW;
    }

    route->methods      = spec->methods;
    route->handler      = spec->handler;
    route->validator    = spec->validator;
    route->rlimit       = spec->rlimit;
    route->min_version  = spec->min_version;
    route->max_version  = spec->max_version;
    route->user_ctx     = spec->user_ctx;

    return (int) router->route_count++;
}

sc_router_err_t
sc_rest_router_use(sc_rest_router_t      *router,
                   sc_rest_middleware_fn  mw)
{
    if (!router || !mw) return SC_ROUTER_EINVAL;

    sc_rest_middleware_fn *tmp = (sc_rest_middleware_fn *) realloc(
            router->global_middleware,
            (router->global_mw_count + 1) * sizeof(*tmp));
    if (!tmp) return SC_ROUTER_ENOMEM;

    router->global_middleware = tmp;
    router->global_middleware[router->global_mw_count++] = mw;
    return SC_ROUTER_OK;
}

/* Forward declaration for recursive mw chain */
static int
sc_dispatch_chain(const sc_rest_request_t *req,
                  sc_rest_response_t      *res,
                  sc_rest_handler_fn       final_handler,
                  void                    *user_ctx,
                  sc_rest_middleware_fn   *mw_arr,
                  size_t                   mw_count,
                  size_t                   idx);

/* Wrapper that calls the next middleware */
static int
sc_mw_next_wrapper(const sc_rest_request_t *req,
                   sc_rest_response_t      *res,
                   void                    *ctx)
{
    struct {
        sc_rest_handler_fn      final_handler;
        void                   *user_ctx;
        sc_rest_middleware_fn  *mw_arr;
        size_t                  mw_count;
        size_t                  idx;
    } *data = ctx;

    return sc_dispatch_chain(req, res,
                             data->final_handler,
                             data->user_ctx,
                             data->mw_arr, data->mw_count,
                             data->idx + 1);
}

static int
sc_dispatch_chain(const sc_rest_request_t *req,
                  sc_rest_response_t      *res,
                  sc_rest_handler_fn       final_handler,
                  void                    *user_ctx,
                  sc_rest_middleware_fn   *mw_arr,
                  size_t                   mw_count,
                  size_t                   idx)
{
    if (idx < mw_count) {
        /* Build context wrapper */
        struct {
            sc_rest_handler_fn      final_handler;
            void                   *user_ctx;
            sc_rest_middleware_fn  *mw_arr;
            size_t                  mw_count;
            size_t                  idx;
        } ctx = { final_handler, user_ctx, mw_arr, mw_count, idx };

        return mw_arr[idx](req, res, user_ctx, sc_mw_next_wrapper);
    }
    /* End of chain -> call final handler */
    return final_handler(req, res, user_ctx);
}

int
sc_rest_router_dispatch(sc_rest_router_t          *router,
                        const sc_rest_request_t   *req,
                        sc_rest_response_t        *res)
{
    if (!router || !req || !res) return -SC_ROUTER_EINVAL;

    sc_http_method_mask_t method_bit = SC_HTTP_METHOD_BIT(req->method);
    sc_api_version_t version = { .major = 1, .minor = 0 }; /* TODO: extract */

    for (size_t i = 0; i < router->route_count; ++i) {
        sc_rest_route_t *route = &router->routes[i];

        if (!(route->methods & method_bit))
            continue;

        if (!sc_route_match(route, req->path, version))
            continue;

        /* Rate limiting */
        if (route->rlimit && !sc_rate_limiter_allow(route->rlimit)) {
            res->status = 429; /* Too Many Requests */
            return -SC_ROUTER_ERATELIMIT;
        }

        /* Build middleware chain: [global …] + [validator?] */
        size_t mw_count = router->global_mw_count +
                          (route->validator ? 1 : 0);
        sc_rest_middleware_fn *mw_arr =
                (sc_rest_middleware_fn *) alloca(mw_count *
                                                  sizeof(*mw_arr));
        size_t idx = 0;
        for (; idx < router->global_mw_count; ++idx)
            mw_arr[idx] = router->global_middleware[idx];
        if (route->validator)
            mw_arr[idx++] = route->validator;

        /* Execute chain → final route handler */
        int rc = sc_dispatch_chain(req, res,
                                   route->handler,
                                   route->user_ctx,
                                   mw_arr, mw_count, 0);
        return rc;
    }

    /* Not found */
    res->status = 404;
    return -SC_ROUTER_ENOTFOUND;
}

/* ----------------------------------------- HTTP helpers ------------------ */
sc_http_method_t
sc_http_method_from_str(const char *method)
{
    if (!method) return SC_HTTP_UNKNOWN;
#define CMP(m) if (strcasecmp(method, #m) == 0) return SC_HTTP_##m
    CMP(GET);    CMP(POST);  CMP(PUT);  CMP(PATCH); CMP(DELETE);
    CMP(HEAD);   CMP(OPTIONS); CMP(TRACE); CMP(CONNECT);
#undef CMP
    return SC_HTTP_UNKNOWN;
}

/* ----------------------------------------- Rate limiter ------------------ */
static inline double
sc_timespec_to_sec(const struct timespec *ts)
{
    return ts->tv_sec + ts->tv_nsec / 1e9;
}

void
sc_rate_limiter_init(sc_rate_limiter_t *rlim,
                     uint32_t           capacity,
                     double             refill_rate)
{
    rlim->capacity   = capacity;
    rlim->tokens     = capacity;
    rlim->refill_rate= refill_rate;
    clock_gettime(CLOCK_MONOTONIC, &rlim->last_check);
}

bool
sc_rate_limiter_allow(sc_rate_limiter_t *rlim)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);

    double elapsed = sc_timespec_to_sec(&now) -
                     sc_timespec_to_sec(&rlim->last_check);
    uint32_t refill = (uint32_t)(elapsed * rlim->refill_rate);

    if (refill) {
        rlim->tokens = (rlim->tokens + refill > rlim->capacity)
                       ? rlim->capacity : rlim->tokens + refill;
        rlim->last_check = now;
    }

    if (rlim->tokens == 0)
        return false;

    --rlim->tokens;
    return true;
}

#endif /* SC_REST_ROUTER_IMPLEMENTATION */

/* -------------------------------------------------------------------------
 *  Example
 * -------------------------------------------------------------------------
 *
 *  #define SC_REST_ROUTER_IMPLEMENTATION
 *  #include "rest/router.h"
 *
 *  static int hello_handler(const sc_rest_request_t *req,
 *                           sc_rest_response_t      *res,
 *                           void                    *ctx)
 *  {
 *      (void) ctx;
 *      res->status = 200;
 *      res->body   = (uint8_t *) strdup("Hello, Synesthetic World!");
 *      res->body_len = strlen((char *) res->body);
 *      return 0;
 *  }
 *
 *  int main(void)
 *  {
 *      sc_rest_router_t router;
 *      sc_rest_router_init(&router, 4);
 *
 *      sc_route_spec_t spec = {
 *          .pattern = "/hello",
 *          .methods = SC_HTTP_METHOD_BIT(SC_HTTP_GET),
 *          .handler = hello_handler,
 *          .min_version = {1,0},
 *          .max_version = {1,0}
 *      };
 *      sc_rest_router_add(&router, &spec);
 *
 *      // Build request
 *      sc_rest_request_t req = { .method = SC_HTTP_GET,
 *                                .path   = "/hello" };
 *      sc_rest_response_t res = {0};
 *
 *      sc_rest_router_dispatch(&router, &req, &res);
 *      printf("Status: %d, Body: %.*s\n",
 *              res.status, (int)res.body_len, res.body);
 *
 *      free(res.body);
 *      sc_rest_router_cleanup(&router);
 *      return 0;
 *  }
 */

#ifdef __cplusplus
}
#endif
#endif /* SC_REST_ROUTER_H */
```