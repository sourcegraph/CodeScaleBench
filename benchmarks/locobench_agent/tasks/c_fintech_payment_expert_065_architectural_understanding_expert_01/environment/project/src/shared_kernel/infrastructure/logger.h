/*
 * EduPay Ledger Academy – Shared Kernel Logger
 *
 * File:    logger.h
 * Project: EduPay Ledger Academy (fintech_payment)
 * License: MIT
 *
 * A small, header-only, production-grade logger that complies with
 * Security-by-Design requirements while remaining framework-agnostic so it can
 * be swapped out during coursework.  The interface is intentionally minimal
 * (init / write / shutdown) to keep the core domain free from I/O concerns,
 * yet the implementation demonstrates best practices such as:
 *
 *   • Thread-safety (POSIX & Win32)
 *   • Compile-time log elimination (EDUPAY_DISABLE_LOGGING)
 *   • Microsecond precision timestamps (ISO-8601 / UTC)
 *   • Log-level filtering
 *   • Correlation IDs for distributed tracing (thread-local)
 *
 * Usage
 * -----
 *      #include "logger.h"
 *
 *      int main(void)
 *      {
 *          if (edupay_logger_init("ledger.log", LOG_LEVEL_DEBUG) != 0) {
 *              fprintf(stderr, "Failed to init logger\n");
 *              return EXIT_FAILURE;
 *          }
 *
 *          edupay_logger_set_correlation("ENR-TXN-493");
 *          LOG_INFO("Student %s paid tuition: %.2f USD", "s00012345", 3049.99);
 *
 *          edupay_logger_shutdown();
 *          return 0;
 *      }
 */

#ifndef EDUPAY_SHARED_KERNEL_LOGGER_H
#define EDUPAY_SHARED_KERNEL_LOGGER_H

/* ===== STD LIB ===== */
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ===== THREADING ===== */
#if defined(_WIN32) || defined(_WIN64)
#   define NOMINMAX
#   include <windows.h>
    typedef CRITICAL_SECTION edupay_mutex_t;
#   define EDUPAY_MUTEX_INIT(m)    InitializeCriticalSection(&(m))
#   define EDUPAY_MUTEX_LOCK(m)    EnterCriticalSection(&(m))
#   define EDUPAY_MUTEX_UNLOCK(m)  LeaveCriticalSection(&(m))
#   define EDUPAY_MUTEX_DESTROY(m) DeleteCriticalSection(&(m))
#   define EDUPAY_THREAD_LOCAL __declspec(thread)
#else /* POSIX */
#   include <pthread.h>
    typedef pthread_mutex_t edupay_mutex_t;
#   define EDUPAY_MUTEX_INIT(m)    pthread_mutex_init(&(m), NULL)
#   define EDUPAY_MUTEX_LOCK(m)    pthread_mutex_lock(&(m))
#   define EDUPAY_MUTEX_UNLOCK(m)  pthread_mutex_unlock(&(m))
#   define EDUPAY_MUTEX_DESTROY(m) pthread_mutex_destroy(&(m))
#   define EDUPAY_THREAD_LOCAL __thread
#endif

/* ===== PUBLIC ENUMS & TYPES ===== */

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    LOG_LEVEL_TRACE = 0,
    LOG_LEVEL_DEBUG = 1,
    LOG_LEVEL_INFO  = 2,
    LOG_LEVEL_WARN  = 3,
    LOG_LEVEL_ERROR = 4,
    LOG_LEVEL_FATAL = 5,
    LOG_LEVEL_OFF   = 6
} edupay_log_level_t;

/* ===== PUBLIC API ===== */

/*
 * Initializes the logger.
 *
 * log_path  – File system path to append logs to.  If NULL, stdout is used.
 * level     – Initial log level.
 *
 * Returns 0 on success, −1 on failure (errno is set).
 */
int  edupay_logger_init(const char *log_path, edupay_log_level_t level);

/*
 * Changes the active log level at runtime.
 * Example: edupay_logger_set_level(LOG_LEVEL_WARN);
 */
void edupay_logger_set_level(edupay_log_level_t level);

/*
 * Returns the current global log level.
 */
edupay_log_level_t edupay_logger_get_level(void);

/*
 * Thread-local correlation identifiers let callers tag all subsequent log
 * messages (on the same thread) with a unique value, for example the Saga ID
 * during a distributed tuition-payment workflow.
 *
 * Passing NULL clears the current correlation ID.
 * The string is copied internally (max 63 bytes).
 */
void edupay_logger_set_correlation(const char *correlation_id);

/*
 * Retrieves the current thread’s correlation ID or "" if none is set
 * (never returns NULL).
 */
const char *edupay_logger_get_correlation(void);

/*
 * Gracefully flushes and closes the log. Idempotent; safe to call multiple
 * times and also in atexit(3) handlers.
 */
void edupay_logger_shutdown(void);

/* ===== IMPLEMENTATION DETAILS (Header-only) ===== */
#ifndef EDUPAY_DISABLE_LOGGING
/* We ship a small but capable implementation in the header to avoid linking
 * requirements in student exercises.  Production deployments tend to isolate
 * loggers in shared libraries, but keeping things header-only eases grading. */
static FILE            *s_log_fp        = NULL;
static edupay_mutex_t   s_log_mutex;
static volatile bool    s_logger_ready  = false;
static edupay_log_level_t s_current_lvl = LOG_LEVEL_INFO;
static char             s_log_path[FILENAME_MAX] = {0};

/* Thread-local correlation ID (64 bytes incl. NUL) */
static EDUPAY_THREAD_LOCAL char s_correlation[64] = {0};

static inline const char *edupay_level_to_str(edupay_log_level_t lvl)
{
    static const char *map[] = {
        "TRACE", "DEBUG", "INFO ",
        "WARN ", "ERROR", "FATAL", "OFF  "
    };
    return map[(int)lvl];
}

static inline void edupay_get_timestamp(char *buf, size_t len)
{
    struct timespec ts;
#if defined(_WIN32) || defined(_WIN64)
    timespec_get(&ts, TIME_UTC);
#else
    clock_gettime(CLOCK_REALTIME, &ts);
#endif
    struct tm tm_utc;
#if defined(_WIN32) || defined(_WIN64)
    gmtime_s(&tm_utc, &ts.tv_sec);
#else
    gmtime_r(&ts.tv_sec, &tm_utc);
#endif
    int written = (int)strftime(buf, len, "%Y-%m-%dT%H:%M:%S", &tm_utc);
    if (written > 0 && (size_t)written < len) {
        snprintf(buf + written, len - (size_t)written,
                 ".%06ldZ", (long)ts.tv_nsec / 1000);
    }
}

/*
 * Core write helper – assumes mutex is locked and level check already passed.
 */
static void edupay_logger_vwrite(edupay_log_level_t lvl,
                                 const char        *file,
                                 const char        *func,
                                 int                line,
                                 const char        *fmt,
                                 va_list            ap)
{
    if (!s_logger_ready) { return; }

    char ts[32];
    edupay_get_timestamp(ts, sizeof(ts));

    fprintf(s_log_fp, "[%s] %-5s [%s] [%s:%d,%s] ",
            ts, edupay_level_to_str(lvl),
            (s_correlation[0] ? s_correlation : "-"),
            file, line, func);

    vfprintf(s_log_fp, fmt, ap);
    fputc('\n', s_log_fp);
    fflush(s_log_fp);
}

/*
 * Public, variadic entry point
 */
void edupay_log_write(edupay_log_level_t lvl,
                      const char        *file,
                      const char        *func,
                      int                line,
                      const char        *fmt, ...)
{
    if (!s_logger_ready || lvl < s_current_lvl || lvl == LOG_LEVEL_OFF) {
        return; /* Fast path: disabled */
    }

    EDUPAY_MUTEX_LOCK(s_log_mutex);

    va_list ap;
    va_start(ap, fmt);
    edupay_logger_vwrite(lvl, file, func, line, fmt, ap);
    va_end(ap);

    EDUPAY_MUTEX_UNLOCK(s_log_mutex);
}

/* Implementation of public API */

int edupay_logger_init(const char *log_path, edupay_log_level_t level)
{
    if (s_logger_ready) {
        errno = EALREADY;
        return -1;
    }

    if (EDUPAY_MUTEX_INIT(s_log_mutex) != 0) {
        /* errno set by pthread/Win32 TL */
        return -1;
    }

    if (log_path && *log_path) {
        s_log_fp = fopen(log_path, "a");
        if (!s_log_fp) {
            EDUPAY_MUTEX_DESTROY(s_log_mutex);
            return -1;
        }
        strncpy(s_log_path, log_path, sizeof(s_log_path) - 1);
    } else {
        s_log_fp = stdout;
    }

    s_current_lvl  = level;
    s_logger_ready = true;
    return 0;
}

void edupay_logger_shutdown(void)
{
    if (!s_logger_ready) { return; }

    EDUPAY_MUTEX_LOCK(s_log_mutex);
    s_logger_ready = false;

    if (s_log_fp && s_log_fp != stdout && s_log_fp != stderr) {
        fclose(s_log_fp);
        s_log_fp = NULL;
    }

    EDUPAY_MUTEX_UNLOCK(s_log_mutex);
    EDUPAY_MUTEX_DESTROY(s_log_mutex);
}

void edupay_logger_set_level(edupay_log_level_t level)
{
    s_current_lvl = level;
}

edupay_log_level_t edupay_logger_get_level(void)
{
    return s_current_lvl;
}

void edupay_logger_set_correlation(const char *correlation_id)
{
    if (!correlation_id) {
        s_correlation[0] = '\0';
    } else {
        strncpy(s_correlation, correlation_id, sizeof(s_correlation) - 1);
        s_correlation[sizeof(s_correlation) - 1] = '\0';
    }
}

const char *edupay_logger_get_correlation(void)
{
    return s_correlation;
}

#else /* EDUPAY_DISABLE_LOGGING ------------------------------------------------*/

static inline int  edupay_logger_init(const char *ignored, edupay_log_level_t l) { (void)ignored; (void)l; return 0; }
static inline void edupay_logger_shutdown(void)                                 { }
static inline void edupay_logger_set_level(edupay_log_level_t l)                { (void)l; }
static inline edupay_log_level_t edupay_logger_get_level(void)                  { return LOG_LEVEL_OFF; }
static inline void edupay_logger_set_correlation(const char *id)                { (void)id; }
static inline const char *edupay_logger_get_correlation(void)                   { return ""; }
static inline void edupay_log_write(edupay_log_level_t l,
                                    const char *f, const char *fu,
                                    int ln, const char *fmt, ...)               { (void)l;(void)f;(void)fu;(void)ln;(void)fmt; }

#endif /* EDUPAY_DISABLE_LOGGING */

/* ===== LOGGING MACROS ====================================================== */
#ifndef EDUPAY_DISABLE_LOGGING
#   define LOG_TRACE(fmt, ...) edupay_log_write(LOG_LEVEL_TRACE, __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_DEBUG(fmt, ...) edupay_log_write(LOG_LEVEL_DEBUG, __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_INFO(fmt,  ...) edupay_log_write(LOG_LEVEL_INFO,  __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_WARN(fmt,  ...) edupay_log_write(LOG_LEVEL_WARN,  __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_ERROR(fmt, ...) edupay_log_write(LOG_LEVEL_ERROR, __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_FATAL(fmt, ...) do { \
        edupay_log_write(LOG_LEVEL_FATAL, __FILE__, __func__, __LINE__, fmt, ##__VA_ARGS__); \
        edupay_logger_shutdown(); exit(EXIT_FAILURE); \
    } while (0)
#else
#   define LOG_TRACE(fmt, ...)
#   define LOG_DEBUG(fmt, ...)
#   define LOG_INFO(fmt,  ...)
#   define LOG_WARN(fmt,  ...)
#   define LOG_ERROR(fmt, ...)
#   define LOG_FATAL(fmt, ...) exit(EXIT_FAILURE)
#endif /* EDUPAY_DISABLE_LOGGING */

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDUPAY_SHARED_KERNEL_LOGGER_H */
