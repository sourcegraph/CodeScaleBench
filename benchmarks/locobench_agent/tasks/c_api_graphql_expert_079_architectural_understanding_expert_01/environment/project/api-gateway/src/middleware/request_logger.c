/*
 *  SynestheticCanvas – API Gateway
 *  middleware/request_logger.c
 *
 *  Production-grade request/response logger middleware.
 *  Responsible for:
 *      • Correlation-ID generation / propagation
 *      • High-resolution latency measurement
 *      • Colorized console output (optional)
 *      • Rotating JSON-Lines log files
 *
 *  Author: SynestheticCanvas Core Team
 *  SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "middleware.h"        /* generic middleware interface            */
#include "request_logger.h"    /* public header for this module           */
#include "http_request.h"      /* request_context_t, etc.                 */
#include "uuid.h"              /* tiny uuid helper – creates v4 uuids     */


/* ---------- Compile-time configuration ---------------------------------- */

#define RL_DEFAULT_MAX_FILE_SIZE_MB  100U          /* rotate after 100 MiB    */
#define RL_TIMESTAMP_FMT             "%Y-%m-%dT%H:%M:%S"
#define RL_LOG_FILE_PREFIX           "sc_gateway"
#define RL_FILE_MODE                 0640

/* Console ANSI colors */
#define ANSI_CLR_RESET   "\x1b[0m"
#define ANSI_CLR_METHOD  "\x1b[38;5;39m"
#define ANSI_CLR_URL     "\x1b[38;5;45m"
#define ANSI_CLR_STATUS  "\x1b[38;5;208m"
#define ANSI_CLR_ERROR   "\x1b[31m"

/* ---------- Private types & globals ------------------------------------- */

typedef struct
{
    char             directory[PATH_MAX];
    size_t           max_file_size;     /* bytes                                  */
    bool             colorize;
} rl_config_t;

/* The active configuration (immutable after init) */
static rl_config_t          g_cfg;
static FILE                *g_fp           = NULL;
static size_t               g_fp_size      = 0;
static pthread_mutex_t      g_lock         = PTHREAD_MUTEX_INITIALIZER;
static char                 g_path[PATH_MAX];

/* ---------- Forward declarations ---------------------------------------- */

static void        rl_rotate_if_needed_locked(void);
static FILE       *rl_open_new_file_locked(void);
static void        rl_write_locked(const char *json_line, size_t len);
static void        rl_console_print(const request_context_t *ctx,
                                    const response_meta_t  *rsp_meta);

/* ---------- Helper: get utc timestamp ----------------------------------- */

static inline void
rl_get_utc_timestamp(char *buf, size_t len)
{
    struct timespec ts;
    struct tm       tm;

    clock_gettime(CLOCK_REALTIME, &ts);
    gmtime_r(&ts.tv_sec, &tm);
    strftime(buf, len, RL_TIMESTAMP_FMT, &tm);
    size_t used = strlen(buf);
    snprintf(buf + used, len - used, ".%03ldZ", ts.tv_nsec / 1000000L);
}

/* ---------- Initialisation / shutdown ----------------------------------- */

int
request_logger_init(const request_logger_cfg_t *cfg)
{
    if (!cfg || !cfg->log_directory)
        return -EINVAL;

    size_t dir_len = strnlen(cfg->log_directory, sizeof(g_cfg.directory) - 1);
    if (dir_len == 0 || dir_len >= sizeof(g_cfg.directory))
        return -ENAMETOOLONG;

    strncpy(g_cfg.directory, cfg->log_directory, sizeof(g_cfg.directory));
    g_cfg.max_file_size = (cfg->max_file_size_mb ?
                          cfg->max_file_size_mb :
                          RL_DEFAULT_MAX_FILE_SIZE_MB) * 1024U * 1024U;
    g_cfg.colorize      = cfg->use_console_colors;

    /* ensure directory exists */
    if (mkdir(g_cfg.directory, 0755) && errno != EEXIST)
        return -errno;

    pthread_mutex_lock(&g_lock);
    g_fp = rl_open_new_file_locked();
    pthread_mutex_unlock(&g_lock);

    return g_fp ? 0 : -EIO;
}

void
request_logger_shutdown(void)
{
    pthread_mutex_lock(&g_lock);
    if (g_fp)
        fclose(g_fp);
    g_fp = NULL;
    pthread_mutex_unlock(&g_lock);
}

/* ---------- Middleware hook: before request ----------------------------- */

middleware_status_t
request_logger_on_request(request_context_t *ctx)
{
    if (!ctx)
        return MIDDLEWARE_ABORT;

    /* attach correlation uuid if missing */
    char uuid_str[UUID_STR_LEN];
    if (!request_header_get(ctx, "X-Request-ID", uuid_str, sizeof uuid_str))
    {
        uuid_v4(uuid_str);
        request_header_set(ctx, "X-Request-ID", uuid_str);
    }

    /* store start-time for latency measurement */
    clock_gettime(CLOCK_MONOTONIC, &ctx->meta.start_ts);
    strncpy(ctx->meta.correlation_id, uuid_str, sizeof ctx->meta.correlation_id);

    return MIDDLEWARE_CONTINUE;
}

/* ---------- Middleware hook: after response ----------------------------- */

middleware_status_t
request_logger_on_response(request_context_t *ctx,
                           const response_meta_t *rsp_meta)
{
    if (!ctx || !rsp_meta)
        return MIDDLEWARE_ABORT;

    struct timespec end_ts;
    clock_gettime(CLOCK_MONOTONIC, &end_ts);

    /* latency in microseconds */
    uint64_t dur_us = (end_ts.tv_sec  - ctx->meta.start_ts.tv_sec) * 1e6
                    + (end_ts.tv_nsec - ctx->meta.start_ts.tv_nsec) / 1000;

    /* Compose JSON line */
    char ts_buf[32];
    rl_get_utc_timestamp(ts_buf, sizeof ts_buf);

    /* Truncate long URLs for log readability */
    char safe_url[512];
    strncpy(safe_url, ctx->req_path, sizeof safe_url - 1);
    safe_url[sizeof safe_url - 1] = '\0';

    char json[2048];
    int written = snprintf(json, sizeof json,
        "{"
        "\"ts\":\"%s\","
        "\"id\":\"%s\","
        "\"client_ip\":\"%s\","
        "\"method\":\"%s\","
        "\"url\":\"%s\","
        "\"status\":%d,"
        "\"content_length\":%" PRIu64 ","
        "\"duration_us\":%" PRIu64
        "}\n",
        ts_buf,
        ctx->meta.correlation_id,
        ctx->remote_addr,
        ctx->http_method,
        safe_url,
        rsp_meta->http_status,
        (uint64_t)rsp_meta->content_length,
        dur_us);

    if (written <= 0)
        return MIDDLEWARE_CONTINUE; /* nothing we can do */

    /* Write to file */
    pthread_mutex_lock(&g_lock);
    rl_rotate_if_needed_locked();
    rl_write_locked(json, (size_t)written);
    pthread_mutex_unlock(&g_lock);

    /* Optional console output */
    if (g_cfg.colorize)
        rl_console_print(ctx, rsp_meta);

    return MIDDLEWARE_CONTINUE;
}

/* ---------- File rotation helpers -------------------------------------- */

static void
rl_rotate_if_needed_locked(void)
{
    if (!g_fp)
        return;

    if (g_fp_size < g_cfg.max_file_size)
        return;

    fclose(g_fp);
    g_fp       = rl_open_new_file_locked();
    g_fp_size  = 0;
}

static FILE *
rl_open_new_file_locked(void)
{
    char ts[32];
    rl_get_utc_timestamp(ts, sizeof ts);

    snprintf(g_path, sizeof g_path, "%s/%s_%s.log",
             g_cfg.directory, RL_LOG_FILE_PREFIX, ts);

    FILE *fp = fopen(g_path, "a");
    if (!fp)
    {
        fprintf(stderr, ANSI_CLR_ERROR "[RequestLogger] Failed to open log file '%s': %s\n"
                ANSI_CLR_RESET, g_path, strerror(errno));
        return NULL;
    }

    fchmod(fileno(fp), RL_FILE_MODE);
    setvbuf(fp, NULL, _IOLBF, 0);  /* line buffered */
    return fp;
}

static void
rl_write_locked(const char *json_line, size_t len)
{
    if (!g_fp)
        return;

    if (fwrite(json_line, 1, len, g_fp) != len)
    {
        fprintf(stderr, ANSI_CLR_ERROR "[RequestLogger] Write failed: %s\n"
                ANSI_CLR_RESET, strerror(errno));
        return;
    }
    g_fp_size += len;
}

/* ---------- Console pretty printer -------------------------------------- */

static void
rl_console_print(const request_context_t *ctx,
                 const response_meta_t  *rsp_meta)
{
    const char *color_status = ANSI_CLR_STATUS;
    if (rsp_meta->http_status >= 500)
        color_status = ANSI_CLR_ERROR;

    fprintf(stdout,
            "[" ANSI_CLR_METHOD "%s" ANSI_CLR_RESET "] "
            ANSI_CLR_URL "%s" ANSI_CLR_RESET
            " → %s%d%s (%" PRIu64 "µs)\n",
            ctx->http_method,
            ctx->req_path,
            color_status, rsp_meta->http_status, ANSI_CLR_RESET,
            (uint64_t)rsp_meta->duration_us);
}

/* ---------- Utility. (Could be moved elsewhere) ------------------------- */

/* Safe free wrapper */
#define SAFE_FREE(p) do { if ((p)) { free(p); (p) = NULL; } } while (0)

/* ---------- End of file ------------------------------------------------- */
