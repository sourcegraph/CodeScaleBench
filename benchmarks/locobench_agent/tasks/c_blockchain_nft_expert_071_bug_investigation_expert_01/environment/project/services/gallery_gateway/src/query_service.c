/*
 *  HoloCanvas: Gallery Gateway - Query Service
 *  File: query_service.c
 *
 *  Description:
 *      The Query-Service is responsible for answering read-only requests
 *      for NFT artifacts, gallery collections, and related metadata.  It
 *      federates information from LedgerCore, Mint-Factory, and
 *      Governance-Hall micro-services, while maintaining an in-process
 *      LRU cache to alleviate hot-path latency.
 *
 *      This module purposefully contains _no_ outbound state-mutating
 *      calls.  All updates are performed elsewhere in the platform.  The
 *      service may be linked into a gRPC/REST transport layer (not
 *      provided here) or embedded directly into another C component.
 *
 *  Build Dependencies:
 *      - libcurl       (HTTP/gRPC over HTTP2 transport)
 *      - cJSON         (Light-weight JSON DOM)
 *      - uthash        (Single-header hash-table – https://troydhanson.github.io/uthash/)
 *      - pthreads
 *
 *  Copyright:
 *      MIT License – HoloCanvas Authors
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <curl/curl.h>
#include <errno.h>

/* External single-header libraries */
#include "cJSON.h"
#include "uthash.h"

/* =========================================================================
 *  Configuration
 * =========================================================================
 */
#define ENV_LEDGERCORE_ENDPOINT   "LEDGERCORE_ENDPOINT"
#define ENV_FACTORY_ENDPOINT      "MINT_FACTORY_ENDPOINT"
#define ENV_GOVERNANCE_ENDPOINT   "GOVERNANCE_HALL_ENDPOINT"

#define DEFAULT_LEDGERCORE_ENDPOINT   "http://ledgercore:8080"
#define DEFAULT_FACTORY_ENDPOINT      "http://mint-factory:8090"
#define DEFAULT_GOVERNANCE_ENDPOINT   "http://governance-hall:8070"

#define DEFAULT_CACHE_CAPACITY        1024          /* # of entries  */
#define DEFAULT_CACHE_TTL_SEC         (60 * 5)      /* 5 min TTL     */

/* =========================================================================
 *  Logging helpers
 * =========================================================================
 */
#define LOG_FMT(level, fmt, ...) \
        fprintf(stderr, "[%s] (%s:%d) " fmt "\n", level, __FILE__, __LINE__, \
                ##__VA_ARGS__)

#define LOG_INFO(fmt, ...)    LOG_FMT("INFO",    fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)    LOG_FMT("WARN",    fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...)     LOG_FMT("ERROR",   fmt, ##__VA_ARGS__)

/* =========================================================================
 *  Query Service Public API
 * =========================================================================
 */
typedef enum {
    QRY_OK = 0,
    QRY_ERR_NETWORK      = -1,
    QRY_ERR_JSON_PARSE   = -2,
    QRY_ERR_NOT_FOUND    = -3,
    QRY_ERR_INTERNAL     = -4,
} qry_status_t;

typedef struct {
    char *json_payload;     /* NULL-terminated JSON string (caller must free) */
    size_t len;             /* length of json_payload                        */
    long   http_code;       /* underlying HTTP status code                   */
} qry_response_t;

/*
 *  Initialize global resources (curl, cache, etc.).
 *  Returns 0 on success or negative error code.
 */
int gallery_query_init(void);

/*
 *  Shutdown global resources and free memory.
 */
void gallery_query_shutdown(void);

/*
 *  Retrieve lifecycle + metadata for a single artifact.
 *  Caller takes ownership of the response and must free it via free().
 */
qry_status_t gallery_query_get_artifact(const char *token_id,
                                        qry_response_t *out);

/*
 *  List every artifact token belonging to a gallery/collection.
 */
qry_status_t gallery_query_list_artifacts(const char *gallery_id,
                                          qry_response_t *out);

/* =========================================================================
 *  Internal implementation details
 * =========================================================================
 */

typedef struct cache_entry_s {
    char *key;              /* UTF-8 string key (token_id / gallery_id) */
    char *value;            /* JSON blob                                */
    size_t value_len;
    time_t created_at;      /* For TTL eviction                         */

    struct cache_entry_s *prev, *next;  /* intrusive LRU list          */
    UT_hash_handle hh;                   /* uthash handle               */
} cache_entry_t;

typedef struct {
    size_t capacity;
    size_t size;
    cache_entry_t *entries;     /* hash table root               */
    cache_entry_s *head;        /* Most-recently-used            */
    cache_entry_s *tail;        /* Least-recently-used           */
    pthread_mutex_t mtx;        /* protect all members           */
} lru_cache_t;

/* Global singleton state */
static struct {
    lru_cache_t   cache;
    char          ledgercore_ep[256];
    char          factory_ep[256];
    char          governance_ep[256];
} g_srv;

/* -------------------------------------------------------------------------
 *  LRU Cache helpers
 * -------------------------------------------------------------------------
 */
static int lru_cache_init(lru_cache_t *c, size_t capacity)
{
    if (!c || capacity == 0)
        return -1;
    c->capacity = capacity;
    c->size     = 0;
    c->entries  = NULL;
    c->head     = c->tail = NULL;
    if (pthread_mutex_init(&c->mtx, NULL) != 0) {
        LOG_ERR("pthread_mutex_init failed: %s", strerror(errno));
        return -1;
    }
    return 0;
}

static void lru_cache_evict(lru_cache_t *c)
{
    /* Remove oldest (tail) entry if above capacity or TTL expired */
    cache_entry_t *entry = c->tail;
    time_t now = time(NULL);

    while (entry &&
          (c->size > c->capacity ||
           (now - entry->created_at) > DEFAULT_CACHE_TTL_SEC)) {

        /* Detach from linked list */
        if (entry->prev)
            entry->prev->next = NULL;
        c->tail = entry->prev;
        if (c->head == entry)
            c->head = NULL;

        /* Remove from hash table */
        HASH_DEL(c->entries, entry);

        /* Free entry */
        free(entry->key);
        free(entry->value);
        cache_entry_t *old = entry;
        entry = entry->prev;
        free(old);
        c->size--;
    }
}

static void lru_cache_promote(lru_cache_t *c, cache_entry_t *entry)
{
    /* Move entry to head of LRU list */
    if (entry == c->head)
        return; /* already MRU */

    /* Detach */
    if (entry->prev)
        entry->prev->next = entry->next;
    if (entry->next)
        entry->next->prev = entry->prev;
    if (c->tail == entry)
        c->tail = entry->prev;

    /* Insert at head */
    entry->prev = NULL;
    entry->next = c->head;
    if (c->head)
        c->head->prev = entry;
    c->head = entry;
    if (c->tail == NULL)
        c->tail = entry;
}

static char *lru_cache_get(lru_cache_t *c,
                           const char *key,
                           size_t *value_len_out)
{
    pthread_mutex_lock(&c->mtx);
    cache_entry_t *entry = NULL;
    HASH_FIND_STR(c->entries, key, entry);

    if (!entry) {
        pthread_mutex_unlock(&c->mtx);
        return NULL;
    }

    /* Refresh LRU position and check TTL */
    time_t now = time(NULL);
    if ((now - entry->created_at) > DEFAULT_CACHE_TTL_SEC) {
        /* Stale – treat as miss */
        LOG_INFO("Cache expired for key=%s", key);
        HASH_DEL(c->entries, entry);

        if (entry->prev)
            entry->prev->next = entry->next;
        if (entry->next)
            entry->next->prev = entry->prev;
        if (c->head == entry)
            c->head = entry->next;
        if (c->tail == entry)
            c->tail = entry->prev;

        free(entry->key);
        free(entry->value);
        free(entry);
        c->size--;
        pthread_mutex_unlock(&c->mtx);
        return NULL;
    }

    lru_cache_promote(c, entry);

    char *dup = strndup(entry->value, entry->value_len);
    if (value_len_out)
        *value_len_out = entry->value_len;

    pthread_mutex_unlock(&c->mtx);
    return dup;
}

static void lru_cache_put(lru_cache_t *c,
                          const char *key,
                          const char *value,
                          size_t value_len)
{
    pthread_mutex_lock(&c->mtx);

    cache_entry_t *entry = NULL;
    HASH_FIND_STR(c->entries, key, entry);
    if (entry) {
        /* Update existing */
        free(entry->value);
        entry->value = strndup(value, value_len);
        entry->value_len = value_len;
        entry->created_at = time(NULL);
        lru_cache_promote(c, entry);
    } else {
        /* New entry */
        entry = calloc(1, sizeof(*entry));
        entry->key   = strdup(key);
        entry->value = strndup(value, value_len);
        entry->value_len = value_len;
        entry->created_at = time(NULL);

        /* Insert into hash & LRU list */
        HASH_ADD_KEYPTR(hh, c->entries, entry->key, strlen(entry->key), entry);
        entry->prev = NULL;
        entry->next = c->head;
        if (c->head)
            c->head->prev = entry;
        c->head = entry;
        if (c->tail == NULL)
            c->tail = entry;

        c->size++;
    }

    lru_cache_evict(c); /* Ensure capacity */
    pthread_mutex_unlock(&c->mtx);
}

static void lru_cache_deinit(lru_cache_t *c)
{
    pthread_mutex_lock(&c->mtx);
    cache_entry_t *cur, *tmp;
    HASH_ITER(hh, c->entries, cur, tmp) {
        HASH_DEL(c->entries, cur);
        free(cur->key);
        free(cur->value);
        free(cur);
    }
    c->head = c->tail = NULL;
    c->size = c->capacity = 0;
    pthread_mutex_unlock(&c->mtx);
    pthread_mutex_destroy(&c->mtx);
}

/* -------------------------------------------------------------------------
 *  CURL helpers
 * -------------------------------------------------------------------------
 */
typedef struct {
    char  *mem;
    size_t size;
} curl_resp_buf_t;

static size_t curl_write_cb(void *contents, size_t size, size_t nmemb,
                            void *userp)
{
    size_t realsize = size * nmemb;
    curl_resp_buf_t *buf = (curl_resp_buf_t *)userp;

    char *ptr = realloc(buf->mem, buf->size + realsize + 1);
    if (!ptr) {
        LOG_ERR("Not enough memory (realloc returned NULL)");
        return 0; /* abort */
    }
    buf->mem = ptr;
    memcpy(&(buf->mem[buf->size]), contents, realsize);
    buf->size += realsize;
    buf->mem[buf->size] = 0;
    return realsize;
}

static qry_status_t http_get_json(const char *url,
                                  char **out_payload,
                                  size_t *out_len,
                                  long *out_http_code)
{
    CURL *curl = curl_easy_init();
    if (!curl) {
        LOG_ERR("curl_easy_init failed");
        return QRY_ERR_INTERNAL;
    }

    curl_resp_buf_t chunk = { .mem = malloc(1), .size = 0 };
    struct curl_slist *hdrs = NULL;

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_HTTPGET, 1L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    /* Accept JSON */
    hdrs = curl_slist_append(hdrs, "Accept: application/json");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        LOG_ERR("curl_easy_perform() failed: %s", curl_easy_strerror(res));
        curl_slist_free_all(hdrs);
        curl_easy_cleanup(curl);
        free(chunk.mem);
        return QRY_ERR_NETWORK;
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    if (out_http_code)
        *out_http_code = http_code;

    *out_payload = chunk.mem;
    *out_len     = chunk.size;

    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    return QRY_OK;
}

/* -------------------------------------------------------------------------
 *  Private utility helpers
 * -------------------------------------------------------------------------
 */
static void populate_endpoints(void)
{
    const char *env;

    env = getenv(ENV_LEDGERCORE_ENDPOINT);
    snprintf(g_srv.ledgercore_ep, sizeof(g_srv.ledgercore_ep), "%s",
             env ? env : DEFAULT_LEDGERCORE_ENDPOINT);

    env = getenv(ENV_FACTORY_ENDPOINT);
    snprintf(g_srv.factory_ep, sizeof(g_srv.factory_ep), "%s",
             env ? env : DEFAULT_FACTORY_ENDPOINT);

    env = getenv(ENV_GOVERNANCE_ENDPOINT);
    snprintf(g_srv.governance_ep, sizeof(g_srv.governance_ep), "%s",
             env ? env : DEFAULT_GOVERNANCE_ENDPOINT);

    LOG_INFO("LedgerCore endpoint: %s",      g_srv.ledgercore_ep);
    LOG_INFO("Mint-Factory endpoint: %s",    g_srv.factory_ep);
    LOG_INFO("Governance-Hall endpoint: %s", g_srv.governance_ep);
}

/* =========================================================================
 *  Public API Implementation
 * =========================================================================
 */
int gallery_query_init(void)
{
    memset(&g_srv, 0, sizeof(g_srv));

    if (curl_global_init(CURL_GLOBAL_ALL) != 0) {
        LOG_ERR("curl_global_init failed");
        return -1;
    }

    if (lru_cache_init(&g_srv.cache, DEFAULT_CACHE_CAPACITY) != 0) {
        curl_global_cleanup();
        return -1;
    }

    populate_endpoints();
    return 0;
}

void gallery_query_shutdown(void)
{
    lru_cache_deinit(&g_srv.cache);
    curl_global_cleanup();
}

/* --
 *  compose_url():
 *      Build a URL string using the supplied pattern:
 *          base + "/" + segment + "/" + id
 *
 *      Returns a malloc()'d string that the caller must free.
 * -- */
static char *compose_url(const char *base,
                         const char *segment,
                         const char *id)
{
    size_t len = strlen(base) + strlen(segment) + strlen(id) + 3;
    char *url = malloc(len);
    snprintf(url, len, "%s/%s/%s", base, segment, id);
    return url;
}

qry_status_t gallery_query_get_artifact(const char *token_id,
                                        qry_response_t *out)
{
    if (!token_id || !out)
        return QRY_ERR_INTERNAL;

    /* Step 1 – Check in-process cache */
    size_t cached_len = 0;
    char *cached = lru_cache_get(&g_srv.cache, token_id, &cached_len);
    if (cached) {
        out->json_payload = cached;
        out->len          = cached_len;
        out->http_code    = 200;
        return QRY_OK;
    }

    /* Step 2 – Query LedgerCore for on-chain state */
    char *url = compose_url(g_srv.ledgercore_ep,
                            "artifact",
                            token_id);

    char *payload = NULL;
    size_t len = 0;
    long http_code = 0;
    qry_status_t st = http_get_json(url, &payload, &len, &http_code);
    free(url);

    if (st != QRY_OK)
        return st;

    if (http_code == 404) {
        free(payload);
        return QRY_ERR_NOT_FOUND;
    }

    /* Step 3 – Validate JSON (lightweight sanity check) */
    cJSON *root = cJSON_ParseWithLength(payload, (int)len);
    if (!root) {
        LOG_ERR("Malformed JSON received for token_id=%s", token_id);
        free(payload);
        return QRY_ERR_JSON_PARSE;
    }
    cJSON_Delete(root);

    /* Step 4 – Insert into cache on success */
    lru_cache_put(&g_srv.cache, token_id, payload, len);

    out->json_payload = payload;
    out->len          = len;
    out->http_code    = http_code;
    return QRY_OK;
}

qry_status_t gallery_query_list_artifacts(const char *gallery_id,
                                          qry_response_t *out)
{
    if (!gallery_id || !out)
        return QRY_ERR_INTERNAL;

    size_t cached_len = 0;
    char *cached = lru_cache_get(&g_srv.cache, gallery_id, &cached_len);
    if (cached) {
        out->json_payload = cached;
        out->len          = cached_len;
        out->http_code    = 200;
        return QRY_OK;
    }

    /* Compose URL – gallery listing lives behind the Factory service */
    char *url = compose_url(g_srv.factory_ep,
                            "gallery",
                            gallery_id);

    char *payload = NULL;
    size_t len = 0;
    long http_code = 0;
    qry_status_t st = http_get_json(url, &payload, &len, &http_code);
    free(url);

    if (st != QRY_OK)
        return st;

    if (http_code == 404) {
        free(payload);
        return QRY_ERR_NOT_FOUND;
    }

    cJSON *root = cJSON_ParseWithLength(payload, (int)len);
    if (!root) {
        LOG_ERR("Malformed JSON received for gallery_id=%s", gallery_id);
        free(payload);
        return QRY_ERR_JSON_PARSE;
    }
    cJSON_Delete(root);

    lru_cache_put(&g_srv.cache, gallery_id, payload, len);

    out->json_payload = payload;
    out->len          = len;
    out->http_code    = http_code;
    return QRY_OK;
}

/* =========================================================================
 *  Self-Test (Compile-time gated)
 * =========================================================================
 *  To run: gcc -DTEST_QUERY_SERVICE query_service.c -lcurl -lpthread -lcjson
 * ------------------------------------------------------------------------- */
#ifdef TEST_QUERY_SERVICE
int main(int argc, char **argv)
{
    if (gallery_query_init() != 0)
        return EXIT_FAILURE;

    qry_response_t resp = {0};
    if (gallery_query_get_artifact("demo-token-1", &resp) == QRY_OK) {
        printf("Artifact JSON: %.*s\n", (int)resp.len, resp.json_payload);
        free(resp.json_payload);
    } else {
        LOG_ERR("Failed to fetch demo-token-1");
    }

    if (gallery_query_list_artifacts("demo-gallery", &resp) == QRY_OK) {
        printf("Gallery JSON: %.*s\n", (int)resp.len, resp.json_payload);
        free(resp.json_payload);
    } else {
        LOG_ERR("Failed to fetch demo-gallery");
    }

    gallery_query_shutdown();
    return EXIT_SUCCESS;
}
#endif /* TEST_QUERY_SERVICE */
