/*
 *  SynestheticCanvas/api-gateway/src/middleware/caching.c
 *
 *  ---------------------------------------------------------------------------
 *  Copyright (c) 2024
 *  SynestheticCanvas Contributors.  All rights reserved.
 *
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions are met:
 *  ...
 *  (BSD-2-Clause license text elided for brevity)
 *  ---------------------------------------------------------------------------
 *
 *  Description:
 *      In-memory, thread-safe LRU cache middleware for the SynestheticCanvas
 *      API Gateway.  Designed to accelerate REST and GraphQL GET requests by
 *      short-circuiting the downstream service pipeline when a fresh copy of
 *      the response is already present in memory.
 *
 *      • Pluggable: enable/disable or swap implementation without touching
 *        unrelated modules.
 *      • Thread-safe: global mutex protects critical regions.
 *      • Bounded: configurable entry count + per-item TTL.  LRU eviction.
 *      • Vary-On: option to include the Authorization header as part of the
 *        cache key (useful for private resources).
 *
 *  Usage from the gateway pipeline:
 *
 *      caching_middleware_init(NULL);             // at startup
 *
 *      sg_pipeline_add(caching_middleware_process);
 *
 *      ...
 *
 *      caching_middleware_shutdown();             // on graceful shutdown
 */

#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "uthash.h"                /* External dependency: https://troydhanson.github.io/uthash/ */

/* ---------------------------------------------------------------------------
 *  Gateway-wide forward declarations (opaque for the cache).
 *  These types originate from the gateway core and are intentionally minimal
 *  here to avoid a hard compile-time dependency.
 * ------------------------------------------------------------------------- */
typedef struct sg_request   sg_request_t;
typedef struct sg_response  sg_response_t;

/* sg_next_middleware_fn:
 *      Signature all middlewares conform to.  Provided by the pipeline.
 *      The caching middleware must call this if it cannot serve from cache.
 */
typedef int (*sg_next_middleware_fn)(sg_request_t *req,
                                     sg_response_t **res /* out */);

/* ---------------------------------------------------------------------------
 *  Internal logging helpers
 * ------------------------------------------------------------------------- */

#define LOG(level, fmt, ...) \
    fprintf(stderr, "[%s] (%s:%d) " fmt "\n", level, __FILE__, __LINE__, \
            ##__VA_ARGS__)

#define LOG_INFO(...)    LOG("INFO",  __VA_ARGS__)
#define LOG_WARN(...)    LOG("WARN",  __VA_ARGS__)
#define LOG_ERROR(...)   LOG("ERROR", __VA_ARGS__)

/* ---------------------------------------------------------------------------
 *  Configuration
 * ------------------------------------------------------------------------- */
typedef struct {
    size_t   max_entries;        /* Hard cap on cache entries     */
    uint32_t default_ttl_secs;   /* Default Time-To-Live (seconds)*/
    bool     vary_on_auth;       /* Whether to include auth header*/
} caching_config_t;

/* Defaults can be overridden by environment variables. */
static const caching_config_t k_default_cfg = {
    .max_entries       = 2048,
    .default_ttl_secs  = 30,
    .vary_on_auth      = true,
};

/* ---------------------------------------------------------------------------
 *  Data structures: doubly-linked LRU list + hash table.
 * ------------------------------------------------------------------------- */
typedef struct cache_entry {
    char               *key;          /* Unique key (malloc'd)           */
    uint8_t            *payload;      /* Cached response body            */
    size_t              payload_len;
    time_t              expiry;       /* Epoch time when entry expires   */

    /* LRU bookkeeping */
    struct cache_entry *prev;
    struct cache_entry *next;

    /* uthash handle */
    UT_hash_handle hh;
} cache_entry_t;

/* ---------------------------------------------------------------------------
 *  Global state (singleton)
 * ------------------------------------------------------------------------- */
static struct {
    caching_config_t   cfg;
    cache_entry_t     *table;      /* Hash table                       */
    cache_entry_t     *lru_head;   /* MRU                              */
    cache_entry_t     *lru_tail;   /* LRU                              */
    size_t             entry_count;
    pthread_mutex_t    mtx;
    bool               initialized;
} g_cache = {
    .table        = NULL,
    .lru_head     = NULL,
    .lru_tail     = NULL,
    .entry_count  = 0,
    .mtx          = PTHREAD_MUTEX_INITIALIZER,
    .initialized  = false,
};

/* ---------------------------------------------------------------------------
 *  Helpers
 * ------------------------------------------------------------------------- */

/* lock/unlock wrappers */
static inline void cache_lock(void)   { pthread_mutex_lock(&g_cache.mtx); }
static inline void cache_unlock(void) { pthread_mutex_unlock(&g_cache.mtx); }

/* Move entry to the front (MRU) */
static void touch_entry(cache_entry_t *e)
{
    if (e == g_cache.lru_head) return;

    /* Unlink */
    if (e->prev) e->prev->next = e->next;
    if (e->next) e->next->prev = e->prev;

    if (e == g_cache.lru_tail)
        g_cache.lru_tail = e->prev;

    /* Insert at head */
    e->prev = NULL;
    e->next = g_cache.lru_head;

    if (g_cache.lru_head)
        g_cache.lru_head->prev = e;

    g_cache.lru_head = e;

    if (!g_cache.lru_tail)
        g_cache.lru_tail = e;
}

/* Allocate and duplicate memory safely (aborts on OOM). */
static void *xmemdup(const void *src, size_t len)
{
    void *dst = malloc(len);
    if (!dst) {
        LOG_ERROR("Out of memory (allocating %zu bytes)", len);
        abort();
    }
    memcpy(dst, src, len);
    return dst;
}

static void free_entry(cache_entry_t *e)
{
    if (!e) return;

    free(e->key);
    free(e->payload);
    free(e);
}

/* Delete the LRU tail until the cache is within max_entries. */
static void enforce_size_limit(void)
{
    while (g_cache.entry_count > g_cache.cfg.max_entries &&
           g_cache.lru_tail) {
        cache_entry_t *victim = g_cache.lru_tail;

        /* Unlink from list */
        g_cache.lru_tail = victim->prev;
        if (g_cache.lru_tail)
            g_cache.lru_tail->next = NULL;
        else
            g_cache.lru_head = NULL;

        /* Remove from hash */
        HASH_DEL(g_cache.table, victim);

        g_cache.entry_count--;

        LOG_INFO("Evicted cache entry (key=%s)", victim->key);
        free_entry(victim);
    }
}

/* ---------------------------------------------------------------------------
 *  Public API
 * ------------------------------------------------------------------------- */

/*  caching_middleware_init:
 *      Must be called once during gateway start-up.
 *      cfg == NULL → use defaults (possibly overridden by env vars).
 */
int caching_middleware_init(const caching_config_t *cfg)
{
    if (g_cache.initialized)
        return 0;

    g_cache.cfg = k_default_cfg;
    if (cfg) {
        g_cache.cfg = *cfg;
    }

    /* Allow environment variable overrides. */
    const char *env;
    if ((env = getenv("SC_CACHE_MAX_ENTRIES")))
        g_cache.cfg.max_entries = strtoul(env, NULL, 10);
    if ((env = getenv("SC_CACHE_DEFAULT_TTL")))
        g_cache.cfg.default_ttl_secs = strtoul(env, NULL, 10);
    if ((env = getenv("SC_CACHE_VARY_ON_AUTH")))
        g_cache.cfg.vary_on_auth = (strcmp(env, "0") != 0);

    LOG_INFO("Cache middleware initialized (max=%zu, ttl=%us, vary_on_auth=%s)",
             g_cache.cfg.max_entries,
             g_cache.cfg.default_ttl_secs,
             g_cache.cfg.vary_on_auth ? "yes" : "no");

    g_cache.initialized = true;
    return 0;
}

/*  caching_middleware_shutdown:
 *      Free all resources and reset state.
 */
void caching_middleware_shutdown(void)
{
    if (!g_cache.initialized)
        return;

    cache_lock();

    cache_entry_t *cur, *tmp;
    HASH_ITER(hh, g_cache.table, cur, tmp) {
        HASH_DEL(g_cache.table, cur);
        free_entry(cur);
    }

    g_cache.table        = NULL;
    g_cache.lru_head     = NULL;
    g_cache.lru_tail     = NULL;
    g_cache.entry_count  = 0;

    cache_unlock();

    pthread_mutex_destroy(&g_cache.mtx);
    g_cache.initialized = false;

    LOG_INFO("Cache middleware shut down");
}

/*  cache_make_key:
 *      Compose a unique key from method, path, query string, optional auth.
 *      Caller must free 'out'.
 */
static char *cache_make_key(const sg_request_t *req, bool vary_on_auth);

/*  cache_get / cache_put:
 *      Internal helpers to interact with the LRU cache itself.
 */

/* Return 1 if hit (and payload copied out), 0 = miss.  */
static int cache_get(const char *key,
                     uint8_t **payload_out,
                     size_t  *len_out)
{
    time_t now = time(NULL);
    cache_lock();

    cache_entry_t *e;
    HASH_FIND_STR(g_cache.table, key, e);

    if (!e) {
        cache_unlock();
        return 0;
    }

    if (now >= e->expiry) {
        /* Stale ‑ remove. */
        LOG_INFO("Cache stale (key=%s)", key);
        touch_entry(e); /* move to head anyway (avoids thrash) */

        HASH_DEL(g_cache.table, e);
        g_cache.entry_count--;
        /* Unlink from list */
        if (e->prev) e->prev->next = e->next;
        if (e->next) e->next->prev = e->prev;
        if (e == g_cache.lru_head) g_cache.lru_head = e->next;
        if (e == g_cache.lru_tail) g_cache.lru_tail = e->prev;

        free_entry(e);
        cache_unlock();
        return 0;
    }

    /* Hit */
    touch_entry(e);
    *payload_out = xmemdup(e->payload, e->payload_len);
    *len_out     = e->payload_len;

    cache_unlock();
    return 1;
}

static void cache_put(const char *key,
                      const void *payload,
                      size_t len,
                      uint32_t ttl)
{
    time_t now = time(NULL);
    cache_lock();

    cache_entry_t *e;
    HASH_FIND_STR(g_cache.table, key, e);

    if (e) {
        /* Replace existing */
        free(e->payload);
        e->payload     = xmemdup(payload, len);
        e->payload_len = len;
        e->expiry      = now + ttl;
        touch_entry(e);

        cache_unlock();
        return;
    }

    /* Create new */
    e = calloc(1, sizeof(*e));
    if (!e) {
        LOG_ERROR("Out of memory (creating cache entry)");
        cache_unlock();
        return;
    }

    e->key         = strdup(key);
    e->payload     = xmemdup(payload, len);
    e->payload_len = len;
    e->expiry      = now + ttl;

    /* Insert to hash + LRU head */
    HASH_ADD_KEYPTR(hh, g_cache.table, e->key, strlen(e->key), e);
    e->prev        = NULL;
    e->next        = g_cache.lru_head;
    if (g_cache.lru_head)
        g_cache.lru_head->prev = e;
    g_cache.lru_head = e;
    if (!g_cache.lru_tail)
        g_cache.lru_tail = e;

    g_cache.entry_count++;

    enforce_size_limit();
    cache_unlock();
}

/* ---------------------------------------------------------------------------
 *  Middleware processing
 * ------------------------------------------------------------------------- */

/*  caching_middleware_process:
 *      Entry point registered in the pipeline.
 *
 *      Decision tree:
 *          - Only cache idempotent requests (GET and HEAD).
 *          - Build composite key (method + URL + optionally auth).
 *          - If present & fresh → build response object from cached bytes.
 *          - On miss → delegate to next() and, if 200 OK, store in cache.
 *
 *      Returns:
 *          0 on success, non-zero to indicate an internal error (gateway will
 *          transform into 500).
 */
int caching_middleware_process(sg_request_t        *req,
                               sg_response_t      **res_out,
                               sg_next_middleware_fn next)
{
    assert(g_cache.initialized && "caching_middleware_init not called");

    /* ---- (1) We only cache GET/HEAD ------------------------------ */
    /* The following helper functions are assumed to exist in the
       gateway core.  Their prototypes are omitted for brevity.        */
    extern const char *sg_request_method(const sg_request_t *);
    extern bool        sg_request_is_secure(const sg_request_t *);
    extern const char *sg_request_path(const sg_request_t *);
    extern const char *sg_request_query(const sg_request_t *);
    extern const char *sg_request_header(const sg_request_t *, const char *name);

    const char *method = sg_request_method(req);
    if (!method || (strcmp(method, "GET") && strcmp(method, "HEAD"))) {
        /* Delegate immediately */
        return next(req, res_out);
    }

    /* ---- (2) Key construction ------------------------------------ */
    char *key = cache_make_key(req, g_cache.cfg.vary_on_auth);

    /* ---- (3) Lookup ---------------------------------------------- */
    uint8_t *cached_payload = NULL;
    size_t   cached_len     = 0;

    if (cache_get(key, &cached_payload, &cached_len)) {
        /* Hit!  Fabricate sg_response_t from serialized bytes. */
        extern sg_response_t *sg_response_from_bytes(const uint8_t *, size_t);

        *res_out = sg_response_from_bytes(cached_payload, cached_len);
        free(cached_payload);
        free(key);

        if (!*res_out) {
            LOG_ERROR("Failed to deserialize cached response");
            return -1; /* treat as error so gateway can handle */
        }

        LOG_INFO("Cache HIT");
        /* Response served; do not call next() */
        return 0;
    }

    /* ---- (4) Miss → delegate ------------------------------------- */
    int rc = next(req, res_out);
    if (rc != 0 || !*res_out) {
        free(key);
        return rc; /* propagate error */
    }

    /* Decide if we should store the response (e.g., only 200 OK). */
    extern int   sg_response_status(const sg_response_t *);
    extern void  sg_response_serialize(const sg_response_t *,
                                       uint8_t **out, size_t *len);

    if (sg_response_status(*res_out) == 200) {
        uint8_t *bytes = NULL;
        size_t   len   = 0;
        sg_response_serialize(*res_out, &bytes, &len);
        if (bytes && len > 0) {
            cache_put(key, bytes, len, g_cache.cfg.default_ttl_secs);
        }
        free(bytes);
    }

    free(key);
    return rc;
}

/* ---------------------------------------------------------------------------
 *  Key construction implementation
 * ------------------------------------------------------------------------- */
static char *cache_make_key(const sg_request_t *req, bool vary_on_auth)
{
    /* We'll build: METHOD|SCHEME|HOST|PATH?QUERY[#F]|AUTH(optional)
       For simplicity, we assume helper functions exist:              */
    extern const char *sg_request_method(const sg_request_t *);
    extern const char *sg_request_scheme(const sg_request_t *);
    extern const char *sg_request_host(const sg_request_t *);
    extern const char *sg_request_path(const sg_request_t *);
    extern const char *sg_request_query(const sg_request_t *);
    extern const char *sg_request_header(const sg_request_t *, const char *);

    const char *method = sg_request_method(req);
    const char *scheme = sg_request_scheme(req);  /* http / https */
    const char *host   = sg_request_host(req);
    const char *path   = sg_request_path(req);
    const char *query  = sg_request_query(req);   /* May be NULL */

    const char *auth   = NULL;
    if (vary_on_auth)
        auth = sg_request_header(req, "Authorization");

    /* Pre-compute required length */
    size_t len = strlen(method) + strlen(scheme) + strlen(host) +
                 strlen(path) + 5;   /* separators & NUL */
    if (query) len += strlen(query) + 1;  /* '?' */
    if (auth)  len += strlen(auth)  + 1;  /* '|' */

    char *key = malloc(len);
    if (!key) {
        LOG_ERROR("Out of memory (allocating cache key)");
        abort();
    }

    /* Build string */
    if (query && *query) {
        snprintf(key, len, "%s|%s|%s|%s?%s", method, scheme, host, path, query);
    } else {
        snprintf(key, len, "%s|%s|%s|%s", method, scheme, host, path);
    }

    if (auth && *auth) {
        size_t cur = strlen(key);
        snprintf(key + cur, len - cur, "|%s", auth);
    }

    return key;
}

/* ---------------------------------------------------------------------------
 *  Unit-test hook (compile with -DTEST_CACHE to run)
 * ------------------------------------------------------------------------- */
#ifdef TEST_CACHE
/* Minimal stubs to test the cache module without linking the full gateway.  */
struct sg_request  { const char *method, *scheme, *host, *path, *query, *auth; };
struct sg_response { int status; uint8_t *body; size_t len; };

static const char *sg_request_method(const sg_request_t *r) { return r->method; }
static const char *sg_request_scheme(const sg_request_t *r) { return r->scheme; }
static const char *sg_request_host  (const sg_request_t *r) { return r->host;   }
static const char *sg_request_path  (const sg_request_t *r) { return r->path;   }
static const char *sg_request_query (const sg_request_t *r) { return r->query;  }
static const char *sg_request_header(const sg_request_t *r, const char *name) {
    return (strcmp(name,"Authorization")==0)? r->auth : NULL;
}

static sg_response_t *sg_response_from_bytes(const uint8_t *b, size_t l) {
    sg_response_t *r = calloc(1, sizeof(*r));
    r->status = 200;
    r->body   = xmemdup(b, l);
    r->len    = l;
    return r;
}
static int sg_response_status(const sg_response_t *r) { return r->status; }
static void sg_response_serialize(const sg_response_t *r,
                                  uint8_t **out, size_t *len) {
    *out = xmemdup(r->body, r->len);
    *len = r->len;
}
static int mock_next(sg_request_t *req, sg_response_t **out) {
    const char *payload = "Hello World!";
    sg_response_t *r = calloc(1, sizeof(*r));
    r->status = 200;
    r->body   = xmemdup(payload, strlen(payload));
    r->len    = strlen(payload);
    *out = r;
    return 0;
}

int main(void)
{
    caching_middleware_init(NULL);

    sg_request_t req = {
        .method="GET", .scheme="https", .host="example.com",
        .path="/foo", .query="", .auth=""
    };
    sg_response_t *res = NULL;

    caching_middleware_process(&req, &res, mock_next);
    printf("First status=%d (expect 200)\n", res->status);
    free(res);

    res = NULL;
    caching_middleware_process(&req, &res, mock_next); /* Should hit cache */
    printf("Second status=%d (cached)\n", res->status);
    free(res);

    caching_middleware_shutdown();
    return 0;
}
#endif /* TEST_CACHE */

/* ---------------------------------------------------------------------------
 *  End of file
 * ------------------------------------------------------------------------- */
