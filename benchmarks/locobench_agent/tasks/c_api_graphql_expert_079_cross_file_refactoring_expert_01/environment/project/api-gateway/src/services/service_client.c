/*
 * SynestheticCanvas - API Gateway
 * --------------------------------
 * service_client.c
 *
 * A production-grade, thread-safe service client wrapper around libcurl that is
 * responsible for communicating with downstream creative micro-services
 * (palette, texture, audio, narrative).  The client provides:
 *
 *  • Configurable per-service base URLs loaded from environment variables
 *  • Automatic request instrumentation (request / failure counters)
 *  • Exponential-back-off retries with jitter
 *  • JSON parsing (cJSON) and basic validation
 *  • Centralised structured logging
 *
 * Author  : SynestheticCanvas Core Team
 * License : MIT
 */

#include "service_client.h"

#include <curl/curl.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* -------------------------------------------------------------------------
 * Local Macros & Helpers
 * ------------------------------------------------------------------------- */
#define SC_DEFAULT_TIMEOUT_MS 5000
#define SC_DEFAULT_RETRIES        3
#define SC_DEFAULT_BACKOFF_MS   250
#define SC_BACKOFF_FACTOR       2.0

#define SC_ENV_PALETTE_URL   "SC_PALETTE_SERVICE_URL"
#define SC_ENV_TEXTURE_URL   "SC_TEXTURE_SERVICE_URL"
#define SC_ENV_AUDIO_URL     "SC_AUDIO_SERVICE_URL"
#define SC_ENV_NARRATIVE_URL "SC_NARRATIVE_SERVICE_URL"

/* Simple timestamped log macros */
#define LOG_FMT(ts, lvl, fmt) "[%s] [%s] " fmt "\n", ts, lvl
#define LOG_INF(fmt, ...) log_write("INFO",  fmt, ##__VA_ARGS__)
#define LOG_WRN(fmt, ...) log_write("WARN",  fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...) log_write("ERROR", fmt, ##__VA_ARGS__)

/* -------------------------------------------------------------------------
 * Data Structures
 * ------------------------------------------------------------------------- */
typedef struct
{
    char    *mem;
    size_t   len;
} response_buf_t;

struct sc_service_client
{
    /* Service base URLs */
    char *palette_url;
    char *texture_url;
    char *audio_url;
    char *narrative_url;

    /* Request configuration */
    long  timeout_ms;
    int   max_retries;
    long  backoff_initial_ms;
    double backoff_factor;

    /* Metrics */
    atomic_ullong requests_total;
    atomic_ullong failures_total;

    /* libcurl shared handle */
    CURL *curl_handle;
    pthread_mutex_t curl_mtx;
};

/* -------------------------------------------------------------------------
 * Forward Declarations
 * ------------------------------------------------------------------------- */
static void        log_write(const char *level, const char *fmt, ...);
static size_t      curl_write_cb(void *contents, size_t size, size_t nmemb, void *userp);
static int         perform_request(sc_service_client_t     *client,
                                   const char              *url,
                                   const char              *method,
                                   const char              *json_body,
                                   long                    *http_status,
                                   cJSON                  **out_body);

static char       *build_full_url(sc_service_endp_t ep, sc_service_client_t *client, const char *path);

/* -------------------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------------------- */

sc_service_client_t *sc_service_client_new(void)
{
    sc_service_client_t *cli = calloc(1, sizeof(*cli));
    if (!cli)
    {
        LOG_ERR("Out of memory while allocating service client");
        return NULL;
    }

    cli->palette_url   = getenv(SC_ENV_PALETTE_URL)   ? strdup(getenv(SC_ENV_PALETTE_URL))   : NULL;
    cli->texture_url   = getenv(SC_ENV_TEXTURE_URL)   ? strdup(getenv(SC_ENV_TEXTURE_URL))   : NULL;
    cli->audio_url     = getenv(SC_ENV_AUDIO_URL)     ? strdup(getenv(SC_ENV_AUDIO_URL))     : NULL;
    cli->narrative_url = getenv(SC_ENV_NARRATIVE_URL) ? strdup(getenv(SC_ENV_NARRATIVE_URL)) : NULL;

    cli->timeout_ms        = SC_DEFAULT_TIMEOUT_MS;
    cli->max_retries       = SC_DEFAULT_RETRIES;
    cli->backoff_initial_ms = SC_DEFAULT_BACKOFF_MS;
    cli->backoff_factor     = SC_BACKOFF_FACTOR;

    atomic_init(&cli->requests_total, 0);
    atomic_init(&cli->failures_total, 0);

    if (pthread_mutex_init(&cli->curl_mtx, NULL) != 0)
    {
        LOG_ERR("Failed to init mutex: %s", strerror(errno));
        free(cli);
        return NULL;
    }

    if (curl_global_init(CURL_GLOBAL_ALL) != CURLE_OK)
    {
        LOG_ERR("Failed to init libcurl");
        pthread_mutex_destroy(&cli->curl_mtx);
        free(cli);
        return NULL;
    }

    cli->curl_handle = curl_easy_init();
    if (!cli->curl_handle)
    {
        LOG_ERR("curl_easy_init() failed");
        curl_global_cleanup();
        pthread_mutex_destroy(&cli->curl_mtx);
        free(cli);
        return NULL;
    }

    /* Use connection pooling */
    curl_easy_setopt(cli->curl_handle, CURLOPT_DNS_CACHE_TIMEOUT, 60L);

    LOG_INF("Service client initialised");
    return cli;
}

void sc_service_client_free(sc_service_client_t *cli)
{
    if (!cli) return;

    LOG_INF("Releasing service client (totalRequests=%" PRIu64 ", failures=%" PRIu64 ")",
            atomic_load(&cli->requests_total), atomic_load(&cli->failures_total));

    free(cli->palette_url);
    free(cli->texture_url);
    free(cli->audio_url);
    free(cli->narrative_url);

    if (cli->curl_handle) curl_easy_cleanup(cli->curl_handle);
    curl_global_cleanup();
    pthread_mutex_destroy(&cli->curl_mtx);
    free(cli);
}

int sc_service_client_call(sc_service_client_t *cli,
                           sc_service_endp_t    endpoint,
                           const char          *method,
                           const char          *path,
                           const char          *request_json,
                           cJSON              **response_json,
                           long                *http_status)
{
    if (!cli || !method || !path || !http_status)
        return SC_EINVAL;

    char *full_url = build_full_url(endpoint, cli, path);
    if (!full_url)
        return SC_EINVAL;

    atomic_fetch_add_explicit(&cli->requests_total, 1, memory_order_relaxed);

    int rc = perform_request(cli, full_url, method, request_json, http_status, response_json);
    free(full_url);

    if (rc != SC_OK)
        atomic_fetch_add_explicit(&cli->failures_total, 1, memory_order_relaxed);

    return rc;
}

/* -------------------------------------------------------------------------
 * Private Implementation
 * ------------------------------------------------------------------------- */

static char *build_full_url(sc_service_endp_t ep, sc_service_client_t *client, const char *path)
{
    const char *base = NULL;
    switch (ep)
    {
        case SC_EP_PALETTE:   base = client->palette_url;   break;
        case SC_EP_TEXTURE:   base = client->texture_url;   break;
        case SC_EP_AUDIO:     base = client->audio_url;     break;
        case SC_EP_NARRATIVE: base = client->narrative_url; break;
        default: return NULL;
    }

    if (!base)
    {
        LOG_ERR("Endpoint base URL not configured");
        return NULL;
    }

    size_t needed = strlen(base) + strlen(path) + 2; /* '/' + '\0' */
    char *url = malloc(needed);
    if (!url) return NULL;

    snprintf(url, needed, "%s%s%s", base, (path[0] == '/' ? "" : "/"), path);
    return url;
}

static size_t curl_write_cb(void *contents, size_t size, size_t nmemb, void *userp)
{
    size_t realsize = size * nmemb;
    response_buf_t *mem = (response_buf_t *)userp;

    char *ptr = realloc(mem->mem, mem->len + realsize + 1);
    if (!ptr)
        return 0; /* will cause CURLE_WRITE_ERROR */

    mem->mem = ptr;
    memcpy(&(mem->mem[mem->len]), contents, realsize);
    mem->len += realsize;
    mem->mem[mem->len] = 0;

    return realsize;
}

static int perform_request(sc_service_client_t *client,
                           const char          *url,
                           const char          *method,
                           const char          *json_body,
                           long                *http_status,
                           cJSON              **out_body)
{
    int      attempt = 0;
    CURLcode res     = CURLE_OK;
    long     status  = 0;
    struct timespec ts_sleep = {0};
    double   backoff_ms = client->backoff_initial_ms;

    do
    {
        response_buf_t resp;
        resp.mem = malloc(1);
        resp.len = 0;
        if (!resp.mem)
            return SC_ENOMEM;

        pthread_mutex_lock(&client->curl_mtx);

        CURL *h = client->curl_handle;
        curl_easy_reset(h);

        struct curl_slist *hdrs = NULL;
        hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
        hdrs = curl_slist_append(hdrs, "Accept: application/json");

        curl_easy_setopt(h, CURLOPT_URL, url);
        curl_easy_setopt(h, CURLOPT_HTTPHEADER, hdrs);
        curl_easy_setopt(h, CURLOPT_TIMEOUT_MS, client->timeout_ms);
        curl_easy_setopt(h, CURLOPT_WRITEFUNCTION, curl_write_cb);
        curl_easy_setopt(h, CURLOPT_WRITEDATA, (void *)&resp);
        curl_easy_setopt(h, CURLOPT_CUSTOMREQUEST, method);

        if (json_body && (strcmp(method, "POST") == 0 || strcmp(method, "PUT") == 0 || strcmp(method, "PATCH") == 0))
            curl_easy_setopt(h, CURLOPT_POSTFIELDS, json_body);

        res = curl_easy_perform(h);
        if (res == CURLE_OK)
            curl_easy_getinfo(h, CURLINFO_RESPONSE_CODE, &status);

        pthread_mutex_unlock(&client->curl_mtx);
        curl_slist_free_all(hdrs);

        if (res == CURLE_OK && status >= 200 && status < 500)
        {
            *http_status = status;

            if (out_body)
            {
                *out_body = cJSON_Parse(resp.mem);
                if (!*out_body)
                {
                    LOG_ERR("JSON parse error: %s", cJSON_GetErrorPtr());
                    free(resp.mem);
                    return SC_EBADJSON;
                }
            }

            free(resp.mem);
            return SC_OK;
        }

        /* transient network/server errors (5xx) are retried */
        LOG_WRN("Request attempt %d failed (curlCode=%d, http=%ld) - retrying...", attempt, res, status);

        free(resp.mem);

        /* Exponential backoff with +-10% jitter */
        long jitter = (rand() % (int)(backoff_ms / 10.0 + 1));
        ts_sleep.tv_sec  = (long)((backoff_ms + jitter) / 1000);
        ts_sleep.tv_nsec = ((long)(backoff_ms + jitter) % 1000) * 1000000L;
        nanosleep(&ts_sleep, NULL);
        backoff_ms *= client->backoff_factor;
    }
    while (++attempt <= client->max_retries);

    *http_status = status;
    LOG_ERR("Request permanently failed after %d attempts", attempt);
    return SC_EREQFAIL;
}

/* -------------------------------------------------------------------------
 * Logging
 * ------------------------------------------------------------------------- */
#include <stdarg.h>

static void log_write(const char *level, const char *fmt, ...)
{
    time_t     now = time(NULL);
    struct tm  tm_now;
    char       ts[32];

    localtime_r(&now, &tm_now);
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S%z", &tm_now);

    fprintf(stderr, "[%s] [%s] ", ts, level);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);

    fputc('\n', stderr);
}

/* -------------------------------------------------------------------------
 * End-of-file
 * ------------------------------------------------------------------------- */
