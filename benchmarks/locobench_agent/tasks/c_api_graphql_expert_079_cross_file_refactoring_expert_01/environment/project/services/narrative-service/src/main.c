```c
/**********************************************************************
 *  SynestheticCanvas Narrative Service – Entry Point
 *
 *  File:    services/narrative-service/src/main.c
 *  Project: SynestheticCanvas API Suite
 *  Author:  SynestheticCanvas Core Team
 *  License: MIT
 *
 *  Description:
 *      A self-contained microservice that exposes narrative-oriented
 *      GraphQL/REST endpoints.  The program is production-grade yet
 *      dependency-light: if libmicrohttpd is unavailable the service
 *      gracefully degrades to a “dry-run” mode so CI pipelines can
 *      still build and run unit tests.
 *
 *  Build (with networking enabled):
 *      cc -DUSE_MHD -o narrative_service main.c -lmicrohttpd -lpthread
 *
 *  Build (dry-run mode):
 *      cc -o narrative_service main.c
 *********************************************************************/

#define _POSIX_C_SOURCE 200809L     /* For sigaction & clock_gettime   */

#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef USE_MHD
#   include <microhttpd.h>
#endif

/*──────────────────────────────────────────────────────────────────*/
/*  Constants & Global State                                        */
/*──────────────────────────────────────────────────────────────────*/
#define APP_NAME        "SynestheticCanvas Narrative Service"
#define APP_VERSION     "1.3.0"
#define DEFAULT_HOST    "0.0.0.0"
#define DEFAULT_PORT    8061
#define DEFAULT_PAGE_SZ 32
#define MAX_PAGE_SZ     256

typedef enum { LOG_DEBUG = 0, LOG_INFO, LOG_WARN, LOG_ERROR, LOG_FATAL }
log_level_t;

static const char *LOG_LEVEL_STR[] = { "DEBUG", "INFO", "WARN",
                                       "ERROR", "FATAL" };

/* ANSI colors for pretty logs (disabled on non-tty). */
static const char *LOG_COLOR[] = {
        "\x1b[37m", /* DEBUG – white  */
        "\x1b[32m", /* INFO  – green  */
        "\x1b[33m", /* WARN  – yellow */
        "\x1b[31m", /* ERROR – red    */
        "\x1b[35m", /* FATAL – magenta*/
};

static log_level_t g_min_log_level = LOG_INFO;
static bool        g_colorize      = true;

static volatile sig_atomic_t g_should_terminate = 0;

/* Prometheus-style metrics (extremely minimal). */
struct {
        uint64_t requests_total;
        uint64_t requests_errors;
        uint64_t started_epoch_s;
} g_metrics = {0};

/*──────────────────────────────────────────────────────────────────*/
/*  Utilities                                                       */
/*──────────────────────────────────────────────────────────────────*/
static void
log_print(log_level_t level, const char *file, int line,
          const char *fmt, ...)
{
    if (level < g_min_log_level) return;

    char tbuf[64];
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    time_t   sec  = (time_t)ts.tv_sec;
    struct tm tm;
    gmtime_r(&sec, &tm);
    strftime(tbuf, sizeof tbuf, "%Y-%m-%dT%H:%M:%S", &tm);

    fprintf(stderr, "%s.%03ld ", tbuf, ts.tv_nsec / 1000000L);
    if (g_colorize) fprintf(stderr, "%s", LOG_COLOR[level]);
    fprintf(stderr, "[%s] %s:%d: ", LOG_LEVEL_STR[level], file, line);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    if (g_colorize) fprintf(stderr, "\x1b[0m");
    fputc('\n', stderr);

    if (level == LOG_FATAL) abort();
}

#define LOGD(...) log_print(LOG_DEBUG, __FILE__, __LINE__, __VA_ARGS__)
#define LOGI(...) log_print(LOG_INFO,  __FILE__, __LINE__, __VA_ARGS__)
#define LOGW(...) log_print(LOG_WARN,  __FILE__, __LINE__, __VA_ARGS__)
#define LOGE(...) log_print(LOG_ERROR, __FILE__, __LINE__, __VA_ARGS__)
#define LOGF(...) log_print(LOG_FATAL, __FILE__, __LINE__, __VA_ARGS__)

/*──────────────────────────────────────────────────────────────────*/
/*  Configuration Handling                                          */
/*──────────────────────────────────────────────────────────────────*/
typedef struct {
        char  host[64];
        int   port;
        int   default_page_size;
        char  log_level_env[16];
} app_cfg_t;

static void
cfg_init(app_cfg_t *cfg)
{
    snprintf(cfg->host, sizeof cfg->host, "%s",
             getenv("NARRATIVE_HOST") ?: DEFAULT_HOST);

    cfg->port = getenv("NARRATIVE_PORT") ? atoi(getenv("NARRATIVE_PORT"))
                                         : DEFAULT_PORT;

    cfg->default_page_size =
        getenv("NARRATIVE_PAGE_SIZE") ?
        atoi(getenv("NARRATIVE_PAGE_SIZE")) : DEFAULT_PAGE_SZ;

    if ((cfg->default_page_size <= 0) ||
        (cfg->default_page_size > MAX_PAGE_SZ))
        cfg->default_page_size = DEFAULT_PAGE_SZ;

    snprintf(cfg->log_level_env, sizeof cfg->log_level_env, "%s",
             getenv("NARRATIVE_LOG") ?: "INFO");
}

/* Parse textual log level env var to enum. */
static log_level_t
parse_loglevel(const char *lvl)
{
    if (!lvl) return LOG_INFO;
    if (strcasecmp(lvl, "DEBUG") == 0) return LOG_DEBUG;
    if (strcasecmp(lvl, "INFO")  == 0) return LOG_INFO;
    if (strcasecmp(lvl, "WARN")  == 0) return LOG_WARN;
    if (strcasecmp(lvl, "ERROR") == 0) return LOG_ERROR;
    if (strcasecmp(lvl, "FATAL") == 0) return LOG_FATAL;
    return LOG_INFO;
}

/*──────────────────────────────────────────────────────────────────*/
/*  Signal Handling                                                 */
/*──────────────────────────────────────────────────────────────────*/
static void
sig_handler(int sig)
{
    (void)sig;
    g_should_terminate = 1;
}

static void
install_signal_handlers(void)
{
    struct sigaction sa = { .sa_handler = sig_handler };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/*──────────────────────────────────────────────────────────────────*/
/*  JSON Helpers (very thin – avoid full JSON dep for brevity)      */
/*──────────────────────────────────────────────────────────────────*/
static int
json_escape(char *dst, size_t dstsz, const char *src)
{
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 2 < dstsz; i++) {
        char c = src[i];
        switch (c) {
        case '"':  if (j + 2 < dstsz) { dst[j++]='\\'; dst[j++]='"'; }  break;
        case '\\': if (j + 2 < dstsz) { dst[j++]='\\'; dst[j++]='\\'; } break;
        case '\n': if (j + 2 < dstsz) { dst[j++]='\\'; dst[j++]='n'; }  break;
        default:   dst[j++] = c; break;
        }
    }
    if (j >= dstsz) return -1;
    dst[j] = '\0';
    return 0;
}

/*──────────────────────────────────────────────────────────────────*/
/*  Business Logic — Narrative Endpoint                             */
/*──────────────────────────────────────────────────────────────────*/

/* Simple in-memory “story fragments” for demo purposes. */
typedef struct {
        const char *id;
        const char *text;
} fragment_t;

static const fragment_t MOCK_STORY_BANK[] = {
    {"0", "Once upon a midnight dreary, while I pondered, weak and weary,"},
    {"1", "Over many a quaint and curious volume of forgotten lore—"},
    {"2", "While I nodded, nearly napping, suddenly there came a tapping,"},
    {"3", "As of some one gently rapping, rapping at my chamber door."},
};

static void
render_story_json(char *buf, size_t bufsz,
                  int page, int per_page, int *status_out)
{
    if (per_page > MAX_PAGE_SZ || per_page <= 0) {
        *status_out = 400;
        snprintf(buf, bufsz, "{\"error\":\"invalid per_page\"}");
        return;
    }

    size_t total = sizeof(MOCK_STORY_BANK)/sizeof(MOCK_STORY_BANK[0]);
    int    pages = (int)((total + per_page - 1)/per_page);

    if (page < 1 || page > pages) {
        *status_out = 400;
        snprintf(buf, bufsz, "{\"error\":\"page out of range\"}");
        return;
    }

    size_t off = (size_t)(page - 1) * (size_t)per_page;
    size_t lim = off + (size_t)per_page;
    if (lim > total) lim = total;

    int n = 0;
    n += snprintf(buf + n, bufsz - n, "{\"page\":%d,\"pages\":%d,\"data\":[",
                  page, pages);

    for (size_t i = off; i < lim && n < (int)bufsz; i++) {
        char esc[256];
        json_escape(esc, sizeof esc, MOCK_STORY_BANK[i].text);
        n += snprintf(buf + n, bufsz - n,
                      "{\"id\":\"%s\",\"text\":\"%s\"}%s",
                      MOCK_STORY_BANK[i].id,
                      esc,
                      (i + 1 < lim) ? "," : "");
    }
    n += snprintf(buf + n, bufsz - n, "]}");
    *status_out = 200;
}

/*──────────────────────────────────────────────────────────────────*/
/*  HTTP Layer                                                      */
/*──────────────────────────────────────────────────────────────────*/
#ifdef USE_MHD
/* Content types */
#define MIME_JSON   "application/json"
#define MIME_TEXT   "text/plain; charset=utf-8"
#define MIME_HTML   "text/html; charset=utf-8"

static int
respond(struct MHD_Connection *conn, int status,
        const char *ctype, const char *body)
{
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(body),
                                        (void *)body,
                                        MHD_RESPMEM_MUST_COPY);
    if (!resp) return MHD_NO;
    MHD_add_response_header(resp, "Content-Type", ctype);
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* Validate that Content-Type header starts with application/json */
static bool
validate_json_ct(const char *hdr)
{
    if (!hdr) return false;
    return strncasecmp(hdr, "application/json", 16) == 0;
}

static int
handle_graphql(struct MHD_Connection *conn, const char *method,
               const char *upload_data, size_t *upload_size)
{
    if (strcmp(method, "POST") != 0)
        return respond(conn, 405, MIME_JSON,
                       "{\"error\":\"method not allowed\"}");

    if (*upload_size == 0)
        return MHD_YES;                           /* Wait for body */

    const char *ct = MHD_lookup_connection_value(
            conn, MHD_HEADER_KIND, "Content-Type");

    if (!validate_json_ct(ct))
        return respond(conn, 415, MIME_JSON,
                       "{\"error\":\"unsupported media type\"}");

    /* Very very naive GraphQL “parser” just for the demo. */
    if (strstr(upload_data, "version") != NULL) {
        char body[128];
        snprintf(body, sizeof body,
                 "{\"data\":{\"version\":\"%s\"}}", APP_VERSION);
        *upload_size = 0;
        return respond(conn, 200, MIME_JSON, body);
    }

    *upload_size = 0;
    return respond(conn, 400, MIME_JSON,
                   "{\"errors\":[{\"message\":\"unsupported query\"}]}");
}

static int
request_router(void *cls,
               struct MHD_Connection *conn,
               const char *url,
               const char *method,
               const char *ver,
               const char *upload_data, size_t *upload_size,
               void **con_cls)
{
    (void)cls; (void)ver; (void)con_cls;

    g_metrics.requests_total++;

    if (strcmp(url, "/healthz") == 0) {
        return respond(conn, 200, MIME_TEXT, "ok");
    }
    else if (strcmp(url, "/metrics") == 0) {
        char body[256];
        int n = snprintf(body, sizeof body,
                         "# HELP narrative_requests_total "
                         "Total HTTP requests\n"
                         "# TYPE narrative_requests_total counter\n"
                         "narrative_requests_total %lu\n"
                         "# HELP narrative_requests_errors "
                         "Total HTTP error responses\n"
                         "# TYPE narrative_requests_errors counter\n"
                         "narrative_requests_errors %lu\n",
                         (unsigned long)g_metrics.requests_total,
                         (unsigned long)g_metrics.requests_errors);
        (void)n;
        return respond(conn, 200, MIME_TEXT, body);
    }
    else if (strcmp(url, "/narrative") == 0) {
        return handle_graphql(conn, method, upload_data, upload_size);
    }
    else if (strcmp(url, "/stories") == 0) {      /* RESTful endpoint */
        if (strcmp(method, "GET") != 0)
            return respond(conn, 405, MIME_JSON,
                           "{\"error\":\"method not allowed\"}");

        const char *p_page     = MHD_lookup_connection_value(conn,
                                   MHD_GET_ARGUMENT_KIND, "page");
        const char *p_per_page = MHD_lookup_connection_value(conn,
                                   MHD_GET_ARGUMENT_KIND, "per_page");

        int page     = p_page     ? atoi(p_page)     : 1;
        int per_page = p_per_page ? atoi(p_per_page) : DEFAULT_PAGE_SZ;

        char body[2048];
        int  status = 0;
        render_story_json(body, sizeof body, page, per_page, &status);
        if (status != 200) g_metrics.requests_errors++;
        return respond(conn, status, MIME_JSON, body);
    }

    g_metrics.requests_errors++;
    return respond(conn, 404, MIME_JSON, "{\"error\":\"not found\"}");
}

static struct MHD_Daemon *g_daemon = NULL;

static bool
http_server_start(const app_cfg_t *cfg)
{
    g_daemon = MHD_start_daemon(
        MHD_USE_SELECT_INTERNALLY, (uint16_t)cfg->port, NULL, NULL,
        &request_router, NULL,
        MHD_OPTION_CONNECTION_TIMEOUT, (unsigned int)10,
        MHD_OPTION_LISTEN_ADDRESS, cfg->host,
        MHD_OPTION_END);

    if (!g_daemon) {
        LOGE("Failed to start HTTP daemon on %s:%d: %s",
             cfg->host, cfg->port, strerror(errno));
        return false;
    }
    LOGI("Listening on http://%s:%d", cfg->host, cfg->port);
    return true;
}

static void
http_server_stop(void)
{
    if (g_daemon) {
        MHD_stop_daemon(g_daemon);
        g_daemon = NULL;
    }
}
#else  /* USE_MHD not defined — dry-run stubs */
static bool  http_server_start(const app_cfg_t *cfg)
{
    (void)cfg;
    LOGW("libmicrohttpd not available, running in dry-run mode.");
    LOGW("No HTTP listener started; service will exit immediately.");
    return true;
}
static void  http_server_stop(void) { }
#endif /* USE_MHD */

/*──────────────────────────────────────────────────────────────────*/
/*  Application Entry                                               */
/*──────────────────────────────────────────────────────────────────*/
int
main(int argc, char **argv)
{
    (void)argc; (void)argv;

    app_cfg_t cfg;
    cfg_init(&cfg);

    /* Logging setup */
    g_min_log_level = parse_loglevel(cfg.log_level_env);
    g_colorize = isatty(STDERR_FILENO);

    LOGI("%s v%s booting…", APP_NAME, APP_VERSION);
    LOGD("configured host=%s port=%d page_size=%d",
         cfg.host, cfg.port, cfg.default_page_size);

    g_metrics.started_epoch_s = (uint64_t)time(NULL);

    install_signal_handlers();

    if (!http_server_start(&cfg))
        LOGF("HTTP server failed to start, aborting.");

#ifndef USE_MHD
    /* Dry-run mode exits right away. */
    return EXIT_SUCCESS;
#endif

    /* ↓ Main loop: sleep until a signal indicates we should shut down. */
    while (!g_should_terminate) {
        struct timespec ts = { .tv_sec = 0, .tv_nsec = 250 * 1000 * 1000 };
        nanosleep(&ts, NULL);
    }

    LOGI("Termination signal received, shutting down…");

    http_server_stop();

    LOGI("Bye!");
    return EXIT_SUCCESS;
}

/*────────────────────────── end of file ───────────────────────────*/
```