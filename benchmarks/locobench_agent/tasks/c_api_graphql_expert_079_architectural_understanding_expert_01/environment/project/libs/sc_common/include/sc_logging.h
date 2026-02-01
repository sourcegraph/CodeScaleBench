#ifndef SC_LOGGING_H
#define SC_LOGGING_H
/*
 *  SynestheticCanvas – Common Logging Facility
 *  -------------------------------------------
 *  File        : sc_logging.h
 *  License     : MIT
 *
 *  The SynestheticCanvas micro-service constellation relies on this tiny yet
 *  powerful logging facility to deliver color-coded, high-performance, and
 *  optionally thread-safe diagnostics across every component, from palette
 *  managers to GraphQL gateways.
 *
 *  Usage (header-only):
 *      #define SC_LOGGING_IMPLEMENTATION
 *      #include "sc_logging.h"
 *
 *      int main(void) {
 *          sc_log_conf_t conf = {
 *              .level     = SC_LOG_DEBUG,
 *              .sink      = stderr,
 *              .flags     = SC_LOG_F_COLOR | SC_LOG_F_UTC
 *          };
 *          sc_log_configure(&conf);
 *
 *          SC_LOG_INFO("Server started on port %d", 8080);
 *      }
 *
 *  Thread-safety:
 *      Define SC_LOG_THREAD_SAFE to enable a pthread mutex protecting writes.
 *
 *  Compile-time disabling:
 *      Define SC_DISABLE_LOGGING to strip all logging calls from the build.
 */

#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <time.h>

#if defined(SC_LOG_THREAD_SAFE)
#   include <pthread.h>
#endif

/* ---------------------------------------------------------------------------
 *  Versioning
 * -------------------------------------------------------------------------*/
#define SC_LOGGING_VERSION_MAJOR 1
#define SC_LOGGING_VERSION_MINOR 0
#define SC_LOGGING_VERSION_PATCH 0

/* ---------------------------------------------------------------------------
 *  Attributes & Helper Macros
 * -------------------------------------------------------------------------*/
#if defined(__GNUC__) || defined(__clang__)
#   define SC_ATTR_FMT(archetype_idx, first_idx) \
        __attribute__((format(printf, archetype_idx, first_idx)))
#else
#   define SC_ATTR_FMT(archetype_idx, first_idx)
#endif

#define SC_UNUSED(x) (void)(x)

/* ---------------------------------------------------------------------------
 *  Log levels
 * -------------------------------------------------------------------------*/
typedef enum {
    SC_LOG_TRACE = 0,
    SC_LOG_DEBUG,
    SC_LOG_INFO,
    SC_LOG_WARN,
    SC_LOG_ERROR,
    SC_LOG_FATAL,
    SC_LOG_LEVEL_COUNT
} sc_log_level_t;

/* Human-readable string representations (same order as enum) */
static const char *const sc_log_level_str[SC_LOG_LEVEL_COUNT] = {
    "TRACE","DEBUG","INFO ","WARN ","ERROR","FATAL"
};

/* ---------------------------------------------------------------------------
 *  ANSI color palette
 * -------------------------------------------------------------------------*/
#define SC_ANSI_RESET   "\x1b[0m"
#define SC_ANSI_GRAY    "\x1b[90m"
#define SC_ANSI_GREEN   "\x1b[32m"
#define SC_ANSI_CYAN    "\x1b[36m"
#define SC_ANSI_YELLOW  "\x1b[33m"
#define SC_ANSI_RED     "\x1b[31m"
#define SC_ANSI_MAGENTA "\x1b[35m"

static const char *const sc_log_level_color[SC_LOG_LEVEL_COUNT] = {
    SC_ANSI_GRAY,   /* TRACE */
    SC_ANSI_CYAN,   /* DEBUG */
    SC_ANSI_GREEN,  /* INFO  */
    SC_ANSI_YELLOW, /* WARN  */
    SC_ANSI_RED,    /* ERROR */
    SC_ANSI_MAGENTA /* FATAL */
};

/* ---------------------------------------------------------------------------
 *  Configuration Flags
 * -------------------------------------------------------------------------*/
#define SC_LOG_F_COLOR   (1u << 0)  /* Enable ANSI color codes             */
#define SC_LOG_F_UTC     (1u << 1)  /* Use UTC timestamps instead of local */
#define SC_LOG_F_MICROS  (1u << 2)  /* Print microsecond precision         */

typedef struct sc_log_conf {
    sc_log_level_t level;   /* Minimum level to emit                */
    FILE          *sink;    /* Output stream (stderr, logfile, …)   */
    uint32_t       flags;   /* SC_LOG_F_* bitmask                   */
} sc_log_conf_t;

/* ---------------------------------------------------------------------------
 *  Public API
 * -------------------------------------------------------------------------*/
#ifdef __cplusplus
extern "C" {
#endif

/* Update global configuration (deep copy) */
void sc_log_configure(const sc_log_conf_t *conf);

/* Runtime re-configuration helpers */
void sc_log_set_level(sc_log_level_t lvl);
void sc_log_set_output(FILE *stream);
void sc_log_set_flags(uint32_t flags);

/* Optional user-supplied hook executed right after message is formatted, but
 * just before it is written to the sink. Return non-zero to cancel default
 * write (useful for forwarding to syslog, journald, ELK, etc.). */
typedef int (*sc_log_hook_fn)(
        sc_log_level_t level,
        const char    *timestamp,
        const char    *file,
        int            line,
        const char    *func,
        const char    *message);

void sc_log_set_hook(sc_log_hook_fn hook);

/* Core logging routine (used by macros below) */
void sc_log_write(sc_log_level_t level,
                  const char    *file,
                  int            line,
                  const char    *func,
                  const char    *fmt, ...) SC_ATTR_FMT(5, 6);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ---------------------------------------------------------------------------
 *  Convenience Macros
 * -------------------------------------------------------------------------*/
#if defined(SC_DISABLE_LOGGING)

#define SC_LOG_TRACE(...) ((void)0)
#define SC_LOG_DEBUG(...) ((void)0)
#define SC_LOG_INFO(...)  ((void)0)
#define SC_LOG_WARN(...)  ((void)0)
#define SC_LOG_ERROR(...) ((void)0)
#define SC_LOG_FATAL(...) ((void)0)

#else /* !SC_DISABLE_LOGGING */

#define SC_LOG_TRACE(...) sc_log_write(SC_LOG_TRACE, __FILE__, __LINE__, __func__, __VA_ARGS__)
#define SC_LOG_DEBUG(...) sc_log_write(SC_LOG_DEBUG, __FILE__, __LINE__, __func__, __VA_ARGS__)
#define SC_LOG_INFO(...)  sc_log_write(SC_LOG_INFO,  __FILE__, __LINE__, __func__, __VA_ARGS__)
#define SC_LOG_WARN(...)  sc_log_write(SC_LOG_WARN,  __FILE__, __LINE__, __func__, __VA_ARGS__)
#define SC_LOG_ERROR(...) sc_log_write(SC_LOG_ERROR, __FILE__, __LINE__, __func__, __VA_ARGS__)
#define SC_LOG_FATAL(...) sc_log_write(SC_LOG_FATAL, __FILE__, __LINE__, __func__, __VA_ARGS__)

#endif /* SC_DISABLE_LOGGING */

/* ===========================================================================
 *  Implementation (define SC_LOGGING_IMPLEMENTATION once in a .c file)
 * =========================================================================*/
#ifdef SC_LOGGING_IMPLEMENTATION

/* -------------------------- Internal State --------------------------------*/
static sc_log_conf_t sc_log_g_conf = {
    .level = SC_LOG_INFO,
    .sink  = NULL,            /* auto-set to stderr in first call */
    .flags = SC_LOG_F_COLOR | SC_LOG_F_MICROS
};

static sc_log_hook_fn sc_log_g_hook = NULL;

#if defined(SC_LOG_THREAD_SAFE)
static pthread_mutex_t sc_log_g_mtx = PTHREAD_MUTEX_INITIALIZER;
#   define SC_LOCK()   pthread_mutex_lock(&sc_log_g_mtx)
#   define SC_UNLOCK() pthread_mutex_unlock(&sc_log_g_mtx)
#else
#   define SC_LOCK()   ((void)0)
#   define SC_UNLOCK() ((void)0)
#endif

/* ----------------------- Helper: formatted timestamp ----------------------*/
static void sc_log_timestamp(char *buf, size_t len, uint32_t flags)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);

    time_t          seconds = ts.tv_sec;
    struct tm       tm_info;

    if (flags & SC_LOG_F_UTC)
        gmtime_r(&seconds, &tm_info);
    else
        localtime_r(&seconds, &tm_info);

    size_t written = strftime(buf, len,
                              (flags & SC_LOG_F_MICROS)
                                  ? "%Y-%m-%dT%H:%M:%S"
                                  : "%Y-%m-%dT%H:%M:%S%z",
                              &tm_info);

    if ((flags & SC_LOG_F_MICROS) && written < len) {
        int micros = (int)(ts.tv_nsec / 1000);
        snprintf(buf + written, len - written, ".%06d%+03d%02d",
                 micros,
                 (int)(tm_info.tm_gmtoff / 3600),
                 (int)((abs((int)tm_info.tm_gmtoff) % 3600) / 60));
    }
}

/* ------------------------- Public API bodies -----------------------------*/
void sc_log_configure(const sc_log_conf_t *conf)
{
    if (!conf) return;
    SC_LOCK();
    sc_log_g_conf = *conf;
    if (!sc_log_g_conf.sink)
        sc_log_g_conf.sink = stderr;
    SC_UNLOCK();
}

void sc_log_set_level(sc_log_level_t lvl)
{
    SC_LOCK();
    sc_log_g_conf.level = lvl;
    SC_UNLOCK();
}

void sc_log_set_output(FILE *stream)
{
    if (!stream) return;
    SC_LOCK();
    sc_log_g_conf.sink = stream;
    SC_UNLOCK();
}

void sc_log_set_flags(uint32_t flags)
{
    SC_LOCK();
    sc_log_g_conf.flags = flags;
    SC_UNLOCK();
}

void sc_log_set_hook(sc_log_hook_fn hook)
{
    SC_LOCK();
    sc_log_g_hook = hook;
    SC_UNLOCK();
}

/* ----------------------------- Core Writer --------------------------------*/
void sc_log_write(sc_log_level_t level,
                  const char    *file,
                  int            line,
                  const char    *func,
                  const char    *fmt, ...)
{
    if (level < sc_log_g_conf.level)
        return;

    if (!sc_log_g_conf.sink)
        sc_log_g_conf.sink = stderr;

    char   timestamp[64];
    char   message[1024];
    size_t msg_len;

    /* ----------- Format user payload -----------*/
    va_list args;
    va_start(args, fmt);
    msg_len = (size_t)vsnprintf(message, sizeof(message), fmt, args);
    va_end(args);

    /* Guard against truncation */
    if (msg_len >= sizeof(message))
        msg_len = sizeof(message) - 1;

    /* ----------- Timestamp -----------*/
    sc_log_timestamp(timestamp, sizeof(timestamp), sc_log_g_conf.flags);

    /* ----------- Hook? -----------*/
    if (sc_log_g_hook && sc_log_g_hook(level, timestamp, file, line, func, message))
        return; /* Hook consumed the message */

    /* ----------- Compose final line -----------*/
    SC_LOCK();

    const char *color = (sc_log_g_conf.flags & SC_LOG_F_COLOR)
                            ? sc_log_level_color[level]
                            : "";

    const char *reset = (sc_log_g_conf.flags & SC_LOG_F_COLOR)
                            ? SC_ANSI_RESET
                            : "";

    fprintf(sc_log_g_conf.sink,
            "%s%s %-5s %s %s:%d %s()%s %s\n",
            color,
            timestamp,
            sc_log_level_str[level],
            reset,
            file,
            line,
            func,
            (sc_log_g_conf.flags & SC_LOG_F_COLOR) ? color : "",
            message);

    fflush(sc_log_g_conf.sink);

    SC_UNLOCK();

    if (level == SC_LOG_FATAL) {
        /* Ensure fatal messages reach console/logs before aborting */
        fflush(sc_log_g_conf.sink);
        abort();
    }
}

#endif /* SC_LOGGING_IMPLEMENTATION */
#endif /* SC_LOGGING_H */
