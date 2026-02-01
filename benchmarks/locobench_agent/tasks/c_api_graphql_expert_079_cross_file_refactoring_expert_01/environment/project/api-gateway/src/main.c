/*
 * SynestheticCanvas API Gateway - Main Entry Point
 * ------------------------------------------------
 *
 *  This file boots the API gateway responsible for exposing a unified
 *  REST + GraphQL surface on top of the creative micro-service constellation.
 *  The gateway is intentionally thin: it deals with concerns that belong at
 *  the edge (transport, auth, rate-limiting, validation, metrics, …) and
 *  forwards enriched domain requests to the correct downstream service.
 *
 *  Author: SynestheticCanvas Core Team
 *  License: MIT
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <signal.h>
#include <errno.h>
#include <pthread.h>
#include <unistd.h>
#include <sys/stat.h>

#include <microhttpd.h>          /* libmicrohttpd ‑ HTTP server                       */
#include <cjson/cJSON.h>         /* Open-source, lightweight JSON parser              */

/* ============================================================================
 *  INTERNAL HEADERS
 * ========================================================================== */
#include "version.h"             /* Auto-generated from CI/CD – git SHA, build time  */
#include "rate_limiter.h"        /* Token bucket implementation                      */
#include "validators.h"          /* OpenAPI & GraphQL schema validation helpers      */
#include "router.h"              /* URL to handler dispatch table                    */
#include "metrics.h"             /* Prometheus-compatible counters / histograms      */
#include "repository.h"          /* Service discovery / adapter layer                */

/* --------------------------------------------------------------------------
 *  Fallback single-file logger (used only when sc_logger is not provided)
 * ------------------------------------------------------------------------ */
#ifndef HAVE_SC_LOGGER
    typedef enum { LOG_DEBUG, LOG_INFO, LOG_WARN, LOG_ERROR } log_level_t;

    static const char *_level_to_str(log_level_t lvl)
    {
        switch (lvl)
        {
            case LOG_DEBUG: return "DEBUG";
            case LOG_INFO:  return "INFO";
            case LOG_WARN:  return "WARN";
            case LOG_ERROR: return "ERROR";
            default:        return "UNK";
        }
    }

    static void _log_impl(log_level_t lvl, const char *file, int line,
                          const char *fmt, ...) __attribute__((format(printf, 4, 5)));

    static void _log_impl(log_level_t lvl, const char *file, int line,
                          const char *fmt, ...)
    {
        const char *lvl_str = _level_to_str(lvl);

        /* Timestamp */
        char ts_buf[32];
        time_t now = time(NULL);
        strftime(ts_buf, sizeof(ts_buf), "%Y-%m-%dT%H:%M:%SZ", gmtime(&now));

        /* Actual message */
        va_list ap;
        va_start(ap, fmt);
        fprintf(stderr, "%s [%s] (%s:%d): ", ts_buf, lvl_str, file, line);
        vfprintf(stderr, fmt, ap);
        fprintf(stderr, "\n");
        va_end(ap);
    }

    #define SC_LOGD(...) _log_impl(LOG_DEBUG, __FILE__, __LINE__, __VA_ARGS__)
    #define SC_LOGI(...) _log_impl(LOG_INFO,  __FILE__, __LINE__, __VA_ARGS__)
    #define SC_LOGW(...) _log_impl(LOG_WARN,  __FILE__, __LINE__, __VA_ARGS__)
    #define SC_LOGE(...) _log_impl(LOG_ERROR, __FILE__, __LINE__, __VA_ARGS__)

#else
    #include <sc_logger.h>
    #define SC_LOGD sc_logger_debug
    #define SC_LOGI sc_logger_info
    #define SC_LOGW sc_logger_warn
    #define SC_LOGE sc_logger_error
#endif /* HAVE_SC_LOGGER */

/* ============================================================================
 *  CONFIGURATION
 * ========================================================================== */

#define DEFAULT_CONFIG_PATH "/etc/synesthetic_canvas/api-gateway.json"
#define DEFAULT_HTTP_PORT   8080
#define MAX_BODY_SIZE       (64 * 1024)  /* 64 KiB – we do pagination anyway   */

typedef struct sc_gateway_cfg_t
{
    uint16_t    http_port;
    uint32_t    max_body_size;
    char       *log_level;
    char       *repository_uri;
    int         enable_metrics;
    int         enable_rate_limit;
} sc_gateway_cfg_t;

/* Parsed, immutable application-wide configuration */
static sc_gateway_cfg_t g_cfg = { 0 };

/* ============================================================================
 *  GLOBALS
 * ========================================================================== */

static struct MHD_Daemon *g_httpd = NULL;
static volatile sig_atomic_t g_shutdown_requested = 0;

/* ============================================================================
 *  UTILITIES
 * ========================================================================== */

/* Return malloc'ed file content, caller must free(). NULL on error. */
static char *load_file_to_mem(const char *path, size_t *o_size)
{
    struct stat st;
    if (stat(path, &st) < 0)
    {
        SC_LOGE("Unable to stat '%s': %s", path, strerror(errno));
        return NULL;
    }

    FILE *fp = fopen(path, "rb");
    if (!fp)
    {
        SC_LOGE("Unable to open '%s': %s", path, strerror(errno));
        return NULL;
    }

    char *buf = (char *)malloc(st.st_size + 1);
    if (!buf)
    {
        SC_LOGE("Out of memory while reading '%s'", path);
        fclose(fp);
        return NULL;
    }

    size_t read_sz = fread(buf, 1, st.st_size, fp);
    fclose(fp);

    if (read_sz != (size_t)st.st_size)
    {
        SC_LOGE("Short read on '%s' – expected %zu, got %zu",
                path, (size_t)st.st_size, read_sz);
        free(buf);
        return NULL;
    }

    buf[read_sz] = '\0'; /* Null-terminate for JSON parser convenience */
    if (o_size) *o_size = read_sz;
    return buf;
}

/* Parse the JSON configuration file into g_cfg */
static int parse_config(const char *json, size_t len)
{
    (void)len; /* not used */

    cJSON *root = cJSON_Parse(json);
    if (!root)
    {
        SC_LOGE("Config parse error before: %.32s", cJSON_GetErrorPtr());
        return -1;
    }

    const cJSON *item = NULL;

    item = cJSON_GetObjectItemCaseSensitive(root, "http_port");
    g_cfg.http_port = item && cJSON_IsNumber(item) ? (uint16_t)item->valueint
                                                   : DEFAULT_HTTP_PORT;

    item = cJSON_GetObjectItemCaseSensitive(root, "max_body_size");
    g_cfg.max_body_size = item && cJSON_IsNumber(item) ? (uint32_t)item->valueint
                                                       : MAX_BODY_SIZE;

    item = cJSON_GetObjectItemCaseSensitive(root, "log_level");
    g_cfg.log_level = item && cJSON_IsString(item) && item->valuestring
                        ? strdup(item->valuestring) : strdup("INFO");

    item = cJSON_GetObjectItemCaseSensitive(root, "repository_uri");
    g_cfg.repository_uri = item && cJSON_IsString(item) && item->valuestring
                            ? strdup(item->valuestring) : strdup("localhost:5239");

    item = cJSON_GetObjectItemCaseSensitive(root, "enable_metrics");
    g_cfg.enable_metrics = item && cJSON_IsBool(item) ? cJSON_IsTrue(item) : 1;

    item = cJSON_GetObjectItemCaseSensitive(root, "enable_rate_limit");
    g_cfg.enable_rate_limit = item && cJSON_IsBool(item) ? cJSON_IsTrue(item) : 0;

    cJSON_Delete(root);
    return 0;
}

/* ============================================================================
 *  SIGNAL HANDLING
 * ========================================================================== */

static void handle_sigterm(int signum)
{
    (void)signum;
    g_shutdown_requested = 1;
}

/* ============================================================================
 *  HTTP HANDLERS
 * ========================================================================== */

typedef struct http_req_ctx_t
{
    struct MHD_PostProcessor *pp;
    char                     *body;
    size_t                    body_size;
    size_t                    body_alloc;
} http_req_ctx_t;

/* GraphQL processing stub – would call the actual query engine */
static int process_graphql(const char *query,
                           struct MHD_Connection *connection)
{
    /* Validate syntax early (a real implementation would be more sophisticated) */
    if (!validators_is_valid_graphql(query))
        return router_send_error(connection, MHD_HTTP_BAD_REQUEST,
                                 "Malformed GraphQL query");

    /* Rate limiting (if configured) */
    if (g_cfg.enable_rate_limit && !rate_limiter_allow(connection))
        return router_send_error(connection, MHD_HTTP_TOO_MANY_REQUESTS,
                                 "Rate limit exceeded");

    /* Transform to downstream service request via repository pattern */
    char *json_payload = repository_dispatch_graphql(query);
    if (!json_payload)
        return router_send_error(connection, MHD_HTTP_BAD_GATEWAY,
                                 "Upstream processing error");

    /* Success – stream back the payload */
    int ret = router_send_json(connection, MHD_HTTP_OK, json_payload);
    free(json_payload);
    return ret;
}

static int generic_request_handler(void *cls,
                                   struct MHD_Connection *connection,
                                   const char *url,
                                   const char *method,
                                   const char *version,
                                   const char *upload_data,
                                   size_t      *upload_data_size,
                                   void       **con_cls)
{
    (void)cls;
    (void)version;

    http_req_ctx_t *ctx = *con_cls;

    /* 1st call – allocate per-connection context */
    if (!ctx)
    {
        ctx = calloc(1, sizeof(*ctx));
        if (!ctx)
            return MHD_NO;
        ctx->body_alloc = g_cfg.max_body_size;
        ctx->body = malloc(ctx->body_alloc);
        if (!ctx->body)
        {
            free(ctx);
            return MHD_NO;
        }
        ctx->pp = NULL; /* We handle body manually, simpler */

        *con_cls = ctx;
        return MHD_YES;
    }

    /* Collect request body if present */
    if (*upload_data_size)
    {
        size_t copy_sz = *upload_data_size;
        if (ctx->body_size + copy_sz > ctx->body_alloc)
        {
            SC_LOGW("Request body truncated (exceeds %zu bytes)",
                    ctx->body_alloc);
            copy_sz = ctx->body_alloc - ctx->body_size;
        }
        memcpy(ctx->body + ctx->body_size, upload_data, copy_sz);
        ctx->body_size += copy_sz;
        *upload_data_size = 0;
        return MHD_YES; /* Continue receiving */
    }

    /* Handle after fully received (when *upload_data_size == 0) */
    int ret = MHD_NO;

    /* Log the request */
    SC_LOGI("%s %s (%zu bytes)", method, url, ctx->body_size);

    /* Dispatch based on URL */
    if (strcmp(url, "/graphql") == 0 && strcmp(method, "POST") == 0)
    {
        /* Null-terminate query to be safe */
        ctx->body[ctx->body_size] = '\0';
        ret = process_graphql(ctx->body, connection);
    }
    else if (strcmp(url, "/healthz") == 0 && strcmp(method, "GET") == 0)
    {
        ret = router_send_text(connection, MHD_HTTP_OK,
                               "OK – SynestheticCanvas API Gateway alive\n");
    }
    else if (strcmp(url, "/metrics") == 0 && strcmp(method, "GET") == 0
             && g_cfg.enable_metrics)
    {
        char *metrics_dump = metrics_serialize_prometheus();
        ret = router_send_text(connection, MHD_HTTP_OK, metrics_dump);
        free(metrics_dump);
    }
    else
    {
        ret = router_send_error(connection, MHD_HTTP_NOT_FOUND,
                                "Endpoint not found");
    }

    /* Cleanup */
    free(ctx->body);
    free(ctx);
    *con_cls = NULL;

    return ret;
}

/* ============================================================================
 *  INITIALIZATION / TEARDOWN
 * ========================================================================== */

static int http_server_start(void)
{
    g_httpd = MHD_start_daemon(
        MHD_USE_AUTO_INTERNAL_THREAD     |
        MHD_USE_DEBUG                    |
        MHD_USE_POLL,
        g_cfg.http_port,
        NULL, NULL,                              /* Accept policy callback */
        &generic_request_handler, NULL,          /* Default handler */
        MHD_OPTION_CONNECTION_LIMIT, (unsigned int)10240, /* Safety net   */
        MHD_OPTION_END);

    if (!g_httpd)
    {
        SC_LOGE("Unable to start HTTP server on port %u", g_cfg.http_port);
        return -1;
    }

    SC_LOGI("HTTP server started on port %u", g_cfg.http_port);
    return 0;
}

static void http_server_stop(void)
{
    if (g_httpd)
    {
        MHD_stop_daemon(g_httpd);
        g_httpd = NULL;
        SC_LOGI("HTTP server stopped");
    }
}

static int app_init(const char *config_path)
{
    /* 1. Parse JSON config */
    size_t cfg_sz = 0;
    char *cfg_json = load_file_to_mem(config_path, &cfg_sz);
    if (!cfg_json)
        return -1;

    if (parse_config(cfg_json, cfg_sz) < 0)
    {
        free(cfg_json);
        return -1;
    }
    free(cfg_json);

    /* 2. Initialize rate-limiter, repository, metrics, … */
    if (rate_limiter_init() < 0)        { SC_LOGE("rate_limiter_init failed"); return -1; }
    if (repository_connect(g_cfg.repository_uri) < 0)
    {
        SC_LOGE("Unable to connect to repository at '%s'", g_cfg.repository_uri);
        return -1;
    }
    if (g_cfg.enable_metrics && metrics_init() < 0)
    {
        SC_LOGE("metrics_init failed");
        return -1;
    }

    /* 3. Start HTTP server */
    if (http_server_start() < 0)
        return -1;

    return 0;
}

static void app_shutdown(void)
{
    http_server_stop();
    if (g_cfg.enable_metrics)  metrics_shutdown();
    repository_disconnect();
    rate_limiter_shutdown();

    free(g_cfg.log_level);
    free(g_cfg.repository_uri);
}

/* ============================================================================
 *  ENTRY POINT
 * ========================================================================== */

static void print_banner(void)
{
    fprintf(stdout,
            "SynestheticCanvas API Gateway %s (%s)\n"
            "Copyright (c) 2024 SynestheticCanvas\n\n",
            VERSION_GIT_SHA, VERSION_BUILD_DATE);
}

static void usage(const char *progname)
{
    fprintf(stderr,
            "Usage: %s [-c path/to/config.json]\n"
            "Options:\n"
            "  -c <file>   Override default config (" DEFAULT_CONFIG_PATH ")\n"
            "  -h          Show this help and exit\n",
            progname);
}

int main(int argc, char *argv[])
{
    const char *config_path = DEFAULT_CONFIG_PATH;

    int opt;
    while ((opt = getopt(argc, argv, "c:h")) != -1)
    {
        switch (opt)
        {
            case 'c':
                config_path = optarg;
                break;
            case 'h':
            default:
                usage(argv[0]);
                return (opt == 'h') ? EXIT_SUCCESS : EXIT_FAILURE;
        }
    }

    print_banner();

    /* Handle SIGINT / SIGTERM for graceful shutdown */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigterm;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    if (app_init(config_path) < 0)
    {
        SC_LOGE("Initialization failed – exiting");
        return EXIT_FAILURE;
    }

    /* Wait until a termination signal arrives */
    while (!g_shutdown_requested)
        sleep(1);

    SC_LOGI("Shutdown requested – cleaning up…");
    app_shutdown();
    SC_LOGI("Goodbye!");
    return EXIT_SUCCESS;
}