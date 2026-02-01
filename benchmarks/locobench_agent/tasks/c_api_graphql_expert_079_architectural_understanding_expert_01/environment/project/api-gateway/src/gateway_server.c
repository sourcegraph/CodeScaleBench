```c
/**
 * SynestheticCanvas – API Gateway
 * ---------------------------------
 * gateway_server.c
 *
 * Central entry-point for the SynestheticCanvas micro-service constellation.
 * Provides:
 *   • HTTP listener (REST + GraphQL)
 *   • Basic request validation
 *   • IP based token-bucket rate limiting
 *   • Up-stream proxying  (service fan-out)
 *   • Health/Liveness endpoints
 *
 * Compile (example):
 *   cc -Wall -Wextra -pedantic -O2 \
 *      gateway_server.c -o gateway_server \
 *      -lmicrohttpd -lcurl -lcjson -lpthread
 *
 * Runtime:
 *   PORT=8080 CONF=./gateway.conf ./gateway_server
 *
 * External deps:
 *   – libmicrohttpd   : GNU HTTP server library
 *   – libcurl         : Up-stream HTTP client
 *   – cJSON           : Configuration / payload parsing
 *
 * Author: SynestheticCanvas Core Team
 */

#define _GNU_SOURCE
#include <microhttpd.h>
#include <curl/curl.h>
#include <cjson/cJSON.h>

#include <syslog.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* ------------------------------------------------------------------------- */
/* Constants & Tunables                                                      */
/* ------------------------------------------------------------------------- */
#define DEFAULT_PORT          8080
#define MAX_BODY_SIZE         (1024 * 1024) /* 1 MiB  */
#define TOKEN_BUCKET_RATE     20            /* req / sec  */
#define TOKEN_BUCKET_CAP      60            /* burst     */
#define HTTP_THREAD_POOL      8

/* ------------------------------------------------------------------------- */
/* Utilities                                                                 */
/* ------------------------------------------------------------------------- */
static uint64_t
now_millis(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t) ts.tv_sec * 1000ULL + ts.tv_nsec / 1000000ULL;
}

/* ------------------------------------------------------------------------- */
/* Configuration                                                             */
/* ------------------------------------------------------------------------- */
typedef struct {
    uint16_t port;
    char    *graphql_upstream;      /* e.g. http://graphql-engine:4000/graphql */
    char    *rest_upstream_prefix;  /* e.g. http://rest-router:7000 */
} gateway_conf_t;

static void
conf_free(gateway_conf_t *conf)
{
    if (!conf) return;
    free(conf->graphql_upstream);
    free(conf->rest_upstream_prefix);
    free(conf);
}

static gateway_conf_t *
conf_load(const char *path)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        syslog(LOG_ERR, "cannot open config '%s': %s", path, strerror(errno));
        return NULL;
    }

    fseek(fp, 0, SEEK_END);
    long len = ftell(fp);
    rewind(fp);

    char *buf = malloc(len + 1);
    fread(buf, 1, len, fp);
    buf[len] = '\0';
    fclose(fp);

    cJSON *json = cJSON_Parse(buf);
    free(buf);
    if (!json) {
        syslog(LOG_ERR, "invalid JSON in config file");
        return NULL;
    }

    gateway_conf_t *cfg = calloc(1, sizeof(*cfg));
    cfg->port               = (uint16_t) cJSON_GetObjectItemCaseSensitive(json, "port")->valueint ?: DEFAULT_PORT;
    cfg->graphql_upstream   = strdup(cJSON_GetObjectItemCaseSensitive(json, "graphql_upstream")->valuestring);
    cfg->rest_upstream_prefix =
        strdup(cJSON_GetObjectItemCaseSensitive(json, "rest_upstream_prefix")->valuestring);

    cJSON_Delete(json);
    return cfg;
}

/* ------------------------------------------------------------------------- */
/* Token Bucket Rate-Limiting                                                */
/* ------------------------------------------------------------------------- */
typedef struct {
    uint64_t last_refill_ms;
    int64_t  tokens;
    pthread_mutex_t mtx;
} bucket_t;

static bucket_t *
bucket_create(void)
{
    bucket_t *b = calloc(1, sizeof(*b));
    b->last_refill_ms = now_millis();
    b->tokens         = TOKEN_BUCKET_CAP;
    pthread_mutex_init(&b->mtx, NULL);
    return b;
}

static bool
bucket_take(bucket_t *b)
{
    bool allowed = false;
    pthread_mutex_lock(&b->mtx);

    uint64_t now = now_millis();
    uint64_t elapsed = now - b->last_refill_ms;

    if (elapsed >= 1000) {
        int64_t refill = (elapsed / 1000) * TOKEN_BUCKET_RATE;
        if (refill > 0) {
            b->tokens = (b->tokens + refill > TOKEN_BUCKET_CAP)
                      ? TOKEN_BUCKET_CAP
                      : b->tokens + refill;
            b->last_refill_ms = now;
        }
    }

    if (b->tokens > 0) {
        b->tokens--;
        allowed = true;
    }

    pthread_mutex_unlock(&b->mtx);
    return allowed;
}

/* Very thin IP→bucket map (open addressing). Not built for huge cardinality,
 * but sufficient for small public endpoints. */
#define BUCKET_MAP_SZ  1024
typedef struct {
    char     *ip;
    bucket_t *bucket;
} bucket_map_slot_t;

static bucket_map_slot_t bucket_map[BUCKET_MAP_SZ];
static pthread_mutex_t   bucket_map_mtx = PTHREAD_MUTEX_INITIALIZER;

static bucket_t *
rate_limit_get_bucket(const char *ip)
{
    uint32_t h = 0;
    for (const char *p = ip; *p; ++p)
        h = (h * 33u) ^ (unsigned)(*p);
    uint32_t idx = h % BUCKET_MAP_SZ;

    pthread_mutex_lock(&bucket_map_mtx);
    for (uint32_t i = 0; i < BUCKET_MAP_SZ; ++i) {
        uint32_t probe = (idx + i) % BUCKET_MAP_SZ;

        if (bucket_map[probe].ip == NULL) {
            /* create slot */
            bucket_map[probe].ip     = strdup(ip);
            bucket_map[probe].bucket = bucket_create();
            pthread_mutex_unlock(&bucket_map_mtx);
            return bucket_map[probe].bucket;
        }

        if (strcmp(bucket_map[probe].ip, ip) == 0) {
            pthread_mutex_unlock(&bucket_map_mtx);
            return bucket_map[probe].bucket;
        }
    }
    /* Fallback (evict) */
    pthread_mutex_unlock(&bucket_map_mtx);
    return bucket_create();
}

/* ------------------------------------------------------------------------- */
/* Up-stream Proxy Helpers (libcurl)                                         */
/* ------------------------------------------------------------------------- */
typedef struct {
    char *ptr;
    size_t len;
} dynbuf_t;

static size_t
curl_write_cb(char *data, size_t size, size_t nmemb, void *userdata)
{
    size_t real = size * nmemb;
    dynbuf_t *db = userdata;

    char *tmp = realloc(db->ptr, db->len + real + 1);
    if (!tmp) return 0;

    memcpy(tmp + db->len, data, real);
    db->ptr = tmp;
    db->len += real;
    db->ptr[db->len] = '\0';
    return real;
}

static int
proxy_post(const char *url, const char *body, struct MHD_Response **resp, unsigned int *status)
{
    CURL *curl = curl_easy_init();
    if (!curl) return -1;

    dynbuf_t db = { .ptr = NULL, .len = 0 };
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &db);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);

    CURLcode ret = curl_easy_perform(curl);
    long http_code = 502;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);

    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);

    if (ret != CURLE_OK) {
        syslog(LOG_ERR, "curl failed: %s", curl_easy_strerror(ret));
        return -1;
    }

    *status = (unsigned int)http_code;
    *resp   = MHD_create_response_from_buffer(db.len, db.ptr, MHD_RESPMEM_MUST_FREE);
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Request Context for libmicrohttpd                                         */
/* ------------------------------------------------------------------------- */
typedef struct {
    char   *body;
    size_t  body_size;
} request_ctx_t;

/* ------------------------------------------------------------------------- */
/* Handler Implementations                                                   */
/* ------------------------------------------------------------------------- */
static int
reply_json(struct MHD_Connection *conn, unsigned int status,
           const char *json)
{
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(json),
                                        (void *)json,
                                        MHD_RESPMEM_PERSISTENT);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int
handle_healthz(struct MHD_Connection *conn)
{
    return reply_json(conn, MHD_HTTP_OK, "{\"status\":\"ok\"}");
}

static int
handle_graphql(struct MHD_Connection *conn,
               request_ctx_t *rctx,
               const gateway_conf_t *cfg)
{
    if (!rctx->body) {
        return reply_json(conn, MHD_HTTP_BAD_REQUEST,
                          "{\"error\":\"empty body\"}");
    }

    cJSON *json = cJSON_ParseWithLength(rctx->body, rctx->body_size);
    if (!json) {
        return reply_json(conn, MHD_HTTP_BAD_REQUEST,
                          "{\"error\":\"invalid json\"}");
    }

    cJSON *query = cJSON_GetObjectItemCaseSensitive(json, "query");
    if (!cJSON_IsString(query) || query->valuestring[0] == '\0') {
        cJSON_Delete(json);
        return reply_json(conn, MHD_HTTP_BAD_REQUEST,
                          "{\"error\":\"'query' must be non-empty\"}");
    }
    cJSON_Delete(json);

    /* Proxy to upstream */
    struct MHD_Response *resp;
    unsigned int status;
    if (proxy_post(cfg->graphql_upstream, rctx->body, &resp, &status) != 0) {
        return reply_json(conn, MHD_HTTP_BAD_GATEWAY,
                          "{\"error\":\"upstream failure\"}");
    }

    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int
handle_rest(struct MHD_Connection *conn,
            const char           *url,
            const char           *method,
            request_ctx_t        *rctx,
            const gateway_conf_t *cfg)
{
    /* Compose upstream URL. Simple concatenation. */
    char *full;
    if (asprintf(&full, "%s%s", cfg->rest_upstream_prefix, url) == -1)
        return reply_json(conn, MHD_HTTP_INTERNAL_SERVER_ERROR,
                          "{\"error\":\"oom\"}");

    struct MHD_Response *resp = NULL;
    unsigned int status = 0;

    if (strcasecmp(method, "GET") == 0) {
        /* For brevity, reuse POST path with empty body for GET. */
        if (proxy_post(full, "", &resp, &status) != 0) {
            free(full);
            return reply_json(conn, MHD_HTTP_BAD_GATEWAY,
                              "{\"error\":\"upstream failure\"}");
        }
    } else if (strcasecmp(method, "POST") == 0
               || strcasecmp(method, "PUT") == 0
               || strcasecmp(method, "PATCH") == 0
               || strcasecmp(method, "DELETE") == 0) {
        if (!rctx->body) {
            free(full);
            return reply_json(conn, MHD_HTTP_BAD_REQUEST,
                              "{\"error\":\"empty body\"}");
        }
        if (proxy_post(full, rctx->body, &resp, &status) != 0) {
            free(full);
            return reply_json(conn, MHD_HTTP_BAD_GATEWAY,
                              "{\"error\":\"upstream failure\"}");
        }
    } else {
        free(full);
        return reply_json(conn, MHD_HTTP_METHOD_NOT_ALLOWED,
                          "{\"error\":\"method not allowed\"}");
    }

    free(full);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* ------------------------------------------------------------------------- */
/* Dispatcher                                                                */
/* ------------------------------------------------------------------------- */
static int
access_handler_cb(void *cls,
                  struct MHD_Connection *conn,
                  const char *url,
                  const char *method,
                  const char *version,
                  const char *upload_data,
                  size_t      *upload_data_size,
                  void       **con_cls)
{
    (void)version; /* unused */

    gateway_conf_t *cfg = cls;
    request_ctx_t *rctx = *con_cls;

    /* 1st call -> create per-request ctx */
    if (!rctx) {
        rctx = calloc(1, sizeof(*rctx));
        *con_cls = rctx;
        return MHD_YES;
    }

    /* Collect body (potentially chunked) */
    if (*upload_data_size > 0) {
        size_t new_size = rctx->body_size + *upload_data_size;
        if (new_size > MAX_BODY_SIZE) {
            return reply_json(conn, MHD_HTTP_REQUEST_ENTITY_TOO_LARGE,
                              "{\"error\":\"payload too large\"}");
        }
        char *tmp = realloc(rctx->body, new_size + 1);
        if (!tmp) {
            return reply_json(conn, MHD_HTTP_INTERNAL_SERVER_ERROR,
                              "{\"error\":\"oom\"}");
        }
        memcpy(tmp + rctx->body_size, upload_data, *upload_data_size);
        rctx->body = tmp;
        rctx->body_size = new_size;
        rctx->body[rctx->body_size] = '\0';

        *upload_data_size = 0; /* signal libmicrohttpd to continue */
        return MHD_YES;
    }

    /* Rate-limit */
    const char *ip = MHD_get_connection_info(conn, MHD_CONNECTION_INFO_CLIENT_ADDRESS)
                     ->client_addr->sa_family == AF_INET ?
                     inet_ntoa(((struct sockaddr_in*)
                                MHD_get_connection_info(conn,
                                  MHD_CONNECTION_INFO_CLIENT_ADDRESS)
                                   ->client_addr)->sin_addr) :
                     "unknown";

    bucket_t *bucket = rate_limit_get_bucket(ip);
    if (!bucket_take(bucket)) {
        return reply_json(conn, MHD_HTTP_TOO_MANY_REQUESTS,
                          "{\"error\":\"rate limit exceeded\"}");
    }

    /* Dispatch by path */
    int ret;
    if (strcmp(url, "/healthz") == 0) {
        ret = handle_healthz(conn);
    } else if (strcmp(url, "/graphql") == 0) {
        ret = handle_graphql(conn, rctx, cfg);
    } else if (strncmp(url, "/api/", 5) == 0) {
        ret = handle_rest(conn, url, method, rctx, cfg);
    } else {
        ret = reply_json(conn, MHD_HTTP_NOT_FOUND,
                         "{\"error\":\"not found\"}");
    }

    /* Clean ctx */
    if (rctx) {
        free(rctx->body);
        free(rctx);
        *con_cls = NULL;
    }
    return ret;
}

/* ------------------------------------------------------------------------- */
/* Shutdown handling                                                         */
/* ------------------------------------------------------------------------- */
static volatile sig_atomic_t g_running = 1;

static void
sigint_handler(int sig)
{
    (void)sig;
    g_running = 0;
}

/* ------------------------------------------------------------------------- */
/* Main                                                                      */
/* ------------------------------------------------------------------------- */
int
main(int argc, char **argv)
{
    (void)argc; (void)argv;

    openlog("syn_canvas_gateway", LOG_PID | LOG_CONS, LOG_DAEMON);

    const char *conf_path = getenv("CONF");
    if (!conf_path) conf_path = "./gateway.conf";

    gateway_conf_t *cfg = conf_load(conf_path);
    if (!cfg) {
        syslog(LOG_ERR, "failed to load configuration; exiting");
        return EXIT_FAILURE;
    }

    curl_global_init(CURL_GLOBAL_DEFAULT);

    struct MHD_Daemon *d = MHD_start_daemon(
                                MHD_USE_THREAD_POOL | MHD_USE_TCP_FASTOPEN,
                                cfg->port,
                                NULL, NULL,
                                &access_handler_cb, cfg,
                                MHD_OPTION_THREAD_POOL_SIZE, HTTP_THREAD_POOL,
                                MHD_OPTION_END);
    if (!d) {
        syslog(LOG_ERR, "failed to start HTTP daemon on port %u", cfg->port);
        conf_free(cfg);
        return EXIT_FAILURE;
    }

    syslog(LOG_INFO, "gateway started on port %u", cfg->port);

    signal(SIGINT, sigint_handler);
    signal(SIGTERM, sigint_handler);

    while (g_running) {
        pause();
    }

    syslog(LOG_INFO, "shutting down");
    MHD_stop_daemon(d);
    curl_global_cleanup();
    conf_free(cfg);
    closelog();
    return EXIT_SUCCESS;
}
```