/*
 * ll_error.c
 *
 * Centralised error-handling utilities for the LexiLearn MVC Orchestrator.
 *
 * The module provides:
 *   • A lightweight, thread-local error context
 *   • Human-readable translation of ll_err_code values
 *   • Safe creation / propagation of formatted error messages
 *   • Optional syslog / stderr logging with run-time configuration
 *
 * All public symbols are declared in ll_error.h.
 *
 * Author: LexiLearn Engineering
 * License: MIT
 */

#include "ll_error.h"

#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>

/*----------------------------------------------------------------------------
 * Compile-time configuration
 *---------------------------------------------------------------------------*/
#ifndef LL_ERR_MAX_MSG
#define LL_ERR_MAX_MSG 1024
#endif

#ifndef LL_ERR_MAX_IDENT
#define LL_ERR_MAX_IDENT 64
#endif

/*----------------------------------------------------------------------------
 * Static helpers / data
 *---------------------------------------------------------------------------*/
static pthread_once_t g_log_init_once = PTHREAD_ONCE_INIT;
static int            g_log_to_syslog = 1;
static char           g_ident[LL_ERR_MAX_IDENT] = "LexiLearnOrchestrator";

/* Thread-local storage for the current error context */
static _Thread_local ll_error_t g_tls_error = {
    .code    = LL_E_OK,
    .message = {0},
    .file    = {0},
    .func    = {0},
    .line    = 0,
    .ts      = {0},
};

/*-----------------------------------------------------------------------------
 * Human-readable string for each ll_err_code.
 *-----------------------------------------------------------------------------*/
static const char *const g_code_map[LL_E_MAX] = {
    [LL_E_OK]           = "No error",
    [LL_E_MEM]          = "Memory allocation failed",
    [LL_E_IO]           = "I/O error",
    [LL_E_INVALID_ARG]  = "Invalid argument",
    [LL_E_NOT_FOUND]    = "Entity not found",
    [LL_E_CONFIG]       = "Configuration error",
    [LL_E_MODEL]        = "Model failure",
    [LL_E_PIPELINE]     = "Pipeline failure",
    [LL_E_THREAD]       = "Threading error",
    [LL_E_OS]           = "Operating-system error",
    [LL_E_INTERNAL]     = "Internal error",
};

/*-----------------------------------------------------------------------------
 * Logging helpers
 *-----------------------------------------------------------------------------*/
static void prv_open_log(void)
{
    if (g_log_to_syslog) {
        openlog(g_ident, LOG_PID | LOG_NDELAY, LOG_USER);
    }
}

static void prv_log(ll_log_level level, const char *fmt, ...)
{
    static const int syslog_lvl_map[] = {
        [LL_LOG_DEBUG] = LOG_DEBUG,
        [LL_LOG_INFO]  = LOG_INFO,
        [LL_LOG_WARN]  = LOG_WARNING,
        [LL_LOG_ERROR] = LOG_ERR,
        [LL_LOG_FATAL] = LOG_CRIT,
    };

    pthread_once(&g_log_init_once, prv_open_log);

    char buf[LL_ERR_MAX_MSG];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    if (g_log_to_syslog) {
        syslog(syslog_lvl_map[level], "%s", buf);
    } else {
        const char *lvl =
            level == LL_LOG_DEBUG ? "DEBUG"
          : level == LL_LOG_INFO  ? "INFO "
          : level == LL_LOG_WARN  ? "WARN "
          : level == LL_LOG_ERROR ? "ERROR"
                                  : "FATAL";
        time_t now = time(NULL);
        struct tm tm_now;
        localtime_r(&now, &tm_now);

        fprintf(stderr,
                "%04d-%02d-%02d %02d:%02d:%02d [%s] %s\n",
                tm_now.tm_year + 1900,
                tm_now.tm_mon + 1,
                tm_now.tm_mday,
                tm_now.tm_hour,
                tm_now.tm_min,
                tm_now.tm_sec,
                lvl,
                buf);
    }
}

/*----------------------------------------------------------------------------
 * Public API implementation
 *---------------------------------------------------------------------------*/
void ll_err_logger_setup(const char *ident, int use_syslog)
{
    if (ident && *ident) {
        strncpy(g_ident, ident, sizeof(g_ident) - 1);
        g_ident[sizeof(g_ident) - 1] = '\0';
    }
    g_log_to_syslog = use_syslog ? 1 : 0;
    /* Ensure we (re)initialise connection with new settings */
    if (g_log_to_syslog) {
        pthread_once(&g_log_init_once, prv_open_log);
    } else {
        /* No need to closelog()—program may still call syslog from elsewhere */
    }
}

const char *ll_err_code_str(ll_err_code code)
{
    if (code >= 0 && code < LL_E_MAX && g_code_map[code])
        return g_code_map[code];
    return "Unknown error code";
}

ll_error_t ll_err_last(void)
{
    return g_tls_error;
}

void ll_err_clear(void)
{
    g_tls_error.code = LL_E_OK;
    g_tls_error.message[0] = '\0';
    g_tls_error.file[0] = '\0';
    g_tls_error.func[0] = '\0';
    g_tls_error.line = 0;
    g_tls_error.ts.tv_sec = g_tls_error.ts.tv_nsec = 0L;
}

static void prv_set_ctx(ll_err_code code,
                        const char *file,
                        const char *func,
                        int         line,
                        const char *fmt,
                        va_list     ap)
{
    g_tls_error.code = code;

    /* Timestamp */
    clock_gettime(CLOCK_REALTIME, &g_tls_error.ts);

    /* File / function / line */
    strncpy(g_tls_error.file, file ? file : "?", sizeof(g_tls_error.file) - 1);
    strncpy(g_tls_error.func, func ? func : "?", sizeof(g_tls_error.func) - 1);
    g_tls_error.line = line;

    /* User-supplied message */
    if (fmt && *fmt) {
        vsnprintf(g_tls_error.message,
                  sizeof(g_tls_error.message),
                  fmt,
                  ap);
    } else {
        strncpy(g_tls_error.message,
                ll_err_code_str(code),
                sizeof(g_tls_error.message) - 1);
    }
}

void ll_err_pushv(ll_err_code   code,
                  const char   *file,
                  const char   *func,
                  int           line,
                  const char   *fmt,
                  va_list       ap)
{
    prv_set_ctx(code, file, func, line, fmt, ap);

    /* Emit log line */
    prv_log(
        code == LL_E_OK   ? LL_LOG_DEBUG
      : code == LL_E_WARN ? LL_LOG_WARN
                          : LL_LOG_ERROR,
        "[%s:%d] %s: %s",
        g_tls_error.file,
        g_tls_error.line,
        g_tls_error.func,
        g_tls_error.message);
}

void ll_err_push(ll_err_code   code,
                 const char   *file,
                 const char   *func,
                 int           line,
                 const char   *fmt,
                 ...)
{
    va_list ap;
    va_start(ap, fmt);
    ll_err_pushv(code, file, func, line, fmt, ap);
    va_end(ap);
}

void ll_err_from_errno(int errnum,
                       const char *file,
                       const char *func,
                       int line,
                       const char *msg_fmt,
                       ...)
{
    ll_err_code code = LL_E_OS;

    char os_msg[LL_ERR_MAX_MSG] = {0};
#if defined(_GNU_SOURCE)
    /* GNU specific reentrant strerror_r returns char* */
    char *tmp = strerror_r(errnum, os_msg, sizeof(os_msg));
    if (tmp != os_msg)
        strncpy(os_msg, tmp, sizeof(os_msg) - 1);
#else
    strerror_r(errnum, os_msg, sizeof(os_msg));
#endif

    /* Compose composite message: user msg + ": " + os_msg */
    char user_msg[LL_ERR_MAX_MSG] = {0};
    if (msg_fmt && *msg_fmt) {
        va_list ap;
        va_start(ap, msg_fmt);
        vsnprintf(user_msg, sizeof(user_msg), msg_fmt, ap);
        va_end(ap);
    }

    char full_msg[LL_ERR_MAX_MSG] = {0};
    if (user_msg[0])
        snprintf(full_msg,
                 sizeof(full_msg),
                 "%s: %s (errno=%d)",
                 user_msg,
                 os_msg,
                 errnum);
    else
        snprintf(full_msg,
                 sizeof(full_msg),
                 "%s (errno=%d)",
                 os_msg,
                 errnum);

    /* Pass down to generic push */
    ll_err_push(code, file, func, line, "%s", full_msg);
}

/*----------------------------------------------------------------------------
 * Utility helpers
 *---------------------------------------------------------------------------*/
int ll_err_is_ok(void)
{
    return g_tls_error.code == LL_E_OK;
}

const char *ll_err_last_msg(void)
{
    return g_tls_error.message[0] ? g_tls_error.message : NULL;
}

void ll_err_die_if(ll_err_code expect_failure_code)
{
    if (g_tls_error.code == expect_failure_code && expect_failure_code != LL_E_OK) {
        prv_log(LL_LOG_FATAL,
                "Fatal error (%s) @ %s:%d: %s",
                ll_err_code_str(g_tls_error.code),
                g_tls_error.file,
                g_tls_error.line,
                g_tls_error.message);
        abort();
    }
}

/*----------------------------------------------------------------------------
 * Convenience function to dump current error context (for debugging)
 *---------------------------------------------------------------------------*/
void ll_err_dump(FILE *out)
{
    if (!out) out = stderr;

    fprintf(out,
            "---- LexiLearn Error Context (thread %lu) ----\n"
            "Time:  %ld.%09ld\n"
            "Code:  %d (%s)\n"
            "Where: %s:%d (%s)\n"
            "Msg:   %s\n"
            "---------------------------------------------\n",
            (unsigned long)pthread_self(),
            g_tls_error.ts.tv_sec,
            g_tls_error.ts.tv_nsec,
            g_tls_error.code,
            ll_err_code_str(g_tls_error.code),
            g_tls_error.file,
            g_tls_error.line,
            g_tls_error.func,
            g_tls_error.message[0] ? g_tls_error.message : "<none>");
}

/*----------------------------------------------------------------------------
 * Module unit test (compile with -DLL_ERROR_TEST to exercise)
 *---------------------------------------------------------------------------*/
#ifdef LL_ERROR_TEST
#include <assert.h>

static void *thread_fn(void *_) {
    ll_err_push(LL_E_INVALID_ARG, __FILE__, __func__, __LINE__,
                "Thread test message");
    ll_error_t ctx = ll_err_last();
    assert(ctx.code == LL_E_INVALID_ARG);
    printf("Thread %lu OK\n", (unsigned long)pthread_self());
    return NULL;
}

int main(void)
{
    ll_err_logger_setup("ll_error_test", 0);

    ll_err_push(LL_E_MEM, __FILE__, __func__, __LINE__,
                "Unable to allocate %zu bytes", (size_t)1024);
    ll_err_dump(stdout);
    assert(ll_err_last().code == LL_E_MEM);

    pthread_t th;
    pthread_create(&th, NULL, thread_fn, NULL);
    pthread_join(th, NULL);

    printf("All tests passed\n");
    return 0;
}
#endif /* LL_ERROR_TEST */