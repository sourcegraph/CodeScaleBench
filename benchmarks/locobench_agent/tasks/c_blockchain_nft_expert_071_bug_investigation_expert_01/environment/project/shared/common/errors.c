/*
 * HoloCanvas – shared/common/errors.c
 *
 * A small but fully-featured error-handling facility used by every
 * HoloCanvas micro-service.  The module offers:
 *
 *   • Enumerated error codes with string lookup
 *   • Formatted “raise / propagate” helpers
 *   • Thread-local last-error + bounded stack for rudimentary back-tracing
 *   • Optional logging hook (falls back to stderr if <logging.h> is absent)
 *
 * The accompanying public header is “errors.h”.  To raise an error:
 *
 *      if (!ptr) {
 *          HC_RAISE(HC_ERR_NOMEM, "failed to allocate foo (size=%zu)", sz);
 *          return false;
 *      }
 *
 * Callers can inspect hc_error_last() or pop the stack for details.
 */

#include "errors.h"            /* public interface – see header for details */
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#ifdef _WIN32
#   include <windows.h>        /* for GetLastError() (if ever needed) */
#endif

/* ------------------------------------------------------------------------- */
/*  Optional external logger                                                 */
/* ------------------------------------------------------------------------- */
#ifdef HAVE_LOGGING_H
#   include "logging.h"        /* presumed to expose LOG_ERROR / LOG_WARN…  */
#else
/* Fallback – emit to stderr with a simple timestamp */
#   define LOG_ERROR(fmt, ...) hc__stderr_log("ERROR", __FILE__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_WARN(fmt,  ...) hc__stderr_log("WARN ", __FILE__, __LINE__, fmt, ##__VA_ARGS__)
#   define LOG_INFO(fmt,  ...) hc__stderr_log("INFO ", __FILE__, __LINE__, fmt, ##__VA_ARGS__)

static void hc__stderr_log(const char *level,
                           const char *file,
                           int         line,
                           const char *fmt, ...)
{
    char   buf[512];
    time_t now = time(NULL);
    struct tm tm_now;

#if defined(_WIN32)
    localtime_s(&tm_now, &now);
#else
    localtime_r(&now, &tm_now);
#endif

    int n = strftime(buf, sizeof buf, "%Y-%m-%d %H:%M:%S", &tm_now);
    if (n < 0) n = 0;

    int off = snprintf(buf + n, sizeof buf - (size_t)n, " [%s] %s:%d: ", level, file, line);
    if (off < 0) off = 0;

    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + n + (size_t)off, sizeof buf - (size_t)n - (size_t)off, fmt, ap);
    va_end(ap);

    fputs(buf, stderr);
    fputc('\n', stderr);
    fflush(stderr);
}
#endif /* HAVE_LOGGING_H */

/* ------------------------------------------------------------------------- */
/*  Compile-time constants, helpers                                          */
/* ------------------------------------------------------------------------- */

/* Sanity defaults in case the public header forgot to define them */
#ifndef HC_ERROR_MSG_MAX
#   define HC_ERROR_MSG_MAX      256
#endif

#ifndef HC_ERROR_FILE_MAX
#   define HC_ERROR_FILE_MAX      96
#endif

#ifndef HC_ERROR_FUNC_MAX
#   define HC_ERROR_FUNC_MAX      64
#endif

#ifndef HC_ERROR_STACK_DEPTH
#   define HC_ERROR_STACK_DEPTH   16
#endif

/* ------------------------------------------------------------------------- */
/*  Error-code ⇄ string lookup table                                         */
/* ------------------------------------------------------------------------- */
typedef struct {
    hc_err_code   code;
    const char   *name;
    const char   *desc;
} hc_err_entry_t;

/* Keep this table in ascending order of enum values for binary search
 * if desired – for now linear scan is fast enough (few dozens of codes). */
static const hc_err_entry_t g_error_table[] = {
    { HC_ERR_OK,                 "HC_ERR_OK",
      "Operation successful" },
    { HC_ERR_UNKNOWN,            "HC_ERR_UNKNOWN",
      "Unknown / unspecified error" },
    { HC_ERR_NOMEM,              "HC_ERR_NOMEM",
      "Out of memory" },
    { HC_ERR_IO,                 "HC_ERR_IO",
      "I/O failure" },
    { HC_ERR_INVALID_ARG,        "HC_ERR_INVALID_ARG",
      "Invalid argument" },
    { HC_ERR_TIMEOUT,            "HC_ERR_TIMEOUT",
      "Operation timed out" },
    { HC_ERR_NETWORK,            "HC_ERR_NETWORK",
      "Network error" },
    { HC_ERR_CRYPTO,             "HC_ERR_CRYPTO",
      "Cryptographic failure" },
    { HC_ERR_DB,                 "HC_ERR_DB",
      "Database or storage failure" },
    { HC_ERR_CONTRACT,           "HC_ERR_CONTRACT",
      "Smart-contract related error" },
    { HC_ERR_CONSENSUS,          "HC_ERR_CONSENSUS",
      "Consensus engine failure" },
    { HC_ERR_STATE,              "HC_ERR_STATE",
      "Illegal object / FSM state" },
    { HC_ERR_PERM,               "HC_ERR_PERM",
      "Permission denied" },
    { HC_ERR_NOT_FOUND,          "HC_ERR_NOT_FOUND",
      "Entity not found" },
    { HC_ERR_AUTH,               "HC_ERR_AUTH",
      "Authentication failed" },
    { HC_ERR_OVERFLOW,           "HC_ERR_OVERFLOW",
      "Numeric overflow" },
    { HC_ERR_UNDERFLOW,          "HC_ERR_UNDERFLOW",
      "Numeric underflow" },
    { HC_ERR_FORMAT,             "HC_ERR_FORMAT",
      "Invalid or unsupported format" },
    { HC_ERR_ABORTED,            "HC_ERR_ABORTED",
      "Operation aborted" },
    { HC_ERR_CAPACITY,           "HC_ERR_CAPACITY",
      "Resource exhausted / capacity reached" },
};

static const size_t g_error_table_len = sizeof g_error_table / sizeof *g_error_table;

/* ------------------------------------------------------------------------- */
/*  Thread-local last error + stack                                          */
/* ------------------------------------------------------------------------- */

typedef struct {
    size_t      top;                      /* index of next free slot          */
    hc_error_t  stack[HC_ERROR_STACK_DEPTH];
} hc_error_stack_t;

static _Thread_local hc_error_t       tls_last_error = { .code = HC_ERR_OK };
static _Thread_local hc_error_stack_t tls_err_stack  = { .top  = 0 };

/* ------------------------------------------------------------------------- */
/*  Internal helpers                                                         */
/* ------------------------------------------------------------------------- */

static void
hc__error_copy(hc_error_t       *dst,
               hc_err_code       code,
               const char       *file,
               int               line,
               const char       *func,
               const char       *fmt,
               va_list           ap)
{
    dst->code = code;
    dst->line = line;

    /* Timestamp the error – nanosecond accuracy when available */
#if defined(CLOCK_REALTIME)
    clock_gettime(CLOCK_REALTIME, &dst->ts);
#else
    dst->ts.tv_sec  = time(NULL);
    dst->ts.tv_nsec = 0;
#endif

    /* Safely copy file / func strings */
    if (file) {
        strncpy(dst->file, file, HC_ERROR_FILE_MAX - 1U);
        dst->file[HC_ERROR_FILE_MAX - 1U] = '\0';
    } else {
        dst->file[0] = '\0';
    }

    if (func) {
        strncpy(dst->func, func, HC_ERROR_FUNC_MAX - 1U);
        dst->func[HC_ERROR_FUNC_MAX - 1U] = '\0';
    } else {
        dst->func[0] = '\0';
    }

    /* Compose user message */
    vsnprintf(dst->msg, HC_ERROR_MSG_MAX, fmt ? fmt : "", ap);
}

/* Push onto the per-thread stack (dropping the oldest on overflow) */
static void
hc__error_stack_push(const hc_error_t *err)
{
    hc_error_stack_t *st = &tls_err_stack;

    if (st->top >= HC_ERROR_STACK_DEPTH) {
        /* Shift everything left by 1 (O(N) but N is tiny) */
        memmove(&st->stack[0], &st->stack[1],
                sizeof(hc_error_t) * (HC_ERROR_STACK_DEPTH - 1U));
        st->top = HC_ERROR_STACK_DEPTH - 1U;
    }

    st->stack[st->top++] = *err;
}

/* ------------------------------------------------------------------------- */
/*  Public API implementation                                                */
/* ------------------------------------------------------------------------- */

void
hc_error_raise(hc_err_code  code,
               const char  *file,
               int          line,
               const char  *func,
               const char  *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    hc__error_copy(&tls_last_error, code, file, line, func, fmt, ap);
    va_end(ap);

    hc__error_stack_push(&tls_last_error);

    /* Issue a log message immediately – helps with crash post-mortems */
    LOG_ERROR("[%s] %s", hc_err_code_name(code), tls_last_error.msg);
}

void
hc_error_propagate(const hc_error_t *err,
                   const char       *file,
                   int               line,
                   const char       *func)
{
    if (!err)
        return;

    /* Copy existing error, append propagation site to stack */
    tls_last_error = *err;
    hc__error_stack_push(&tls_last_error);

    LOG_WARN("Propagated error [%s] at %s:%d (%s)",
             hc_err_code_name(err->code), file, line, func);
}

void
hc_error_clear(void)
{
    tls_last_error.code = HC_ERR_OK;
    tls_last_error.msg[0] = '\0';
    tls_err_stack.top = 0;
}

const hc_error_t *
hc_error_last(void)
{
    return tls_last_error.code == HC_ERR_OK ? NULL : &tls_last_error;
}

bool
hc_error_stack_pop(hc_error_t *out_err)
{
    hc_error_stack_t *st = &tls_err_stack;

    if (st->top == 0)
        return false;

    *out_err = st->stack[--st->top];
    return true;
}

size_t
hc_error_stack_depth(void)
{
    return tls_err_stack.top;
}

const char *
hc_err_code_name(hc_err_code code)
{
    for (size_t i = 0; i < g_error_table_len; ++i) {
        if (g_error_table[i].code == code)
            return g_error_table[i].name;
    }
    return "HC_ERR_???";
}

const char *
hc_err_code_desc(hc_err_code code)
{
    for (size_t i = 0; i < g_error_table_len; ++i) {
        if (g_error_table[i].code == code)
            return g_error_table[i].desc;
    }
    return "Unknown error";
}

void
hc_error_print_stack(FILE *out)
{
    if (!out) out = stderr;

    hc_error_stack_t *st = &tls_err_stack;
    fprintf(out, "Error stack (depth=%zu):\n", st->top);

    for (size_t i = 0; i < st->top; ++i) {
        const hc_error_t *e = &st->stack[i];
        struct tm tm_ts;

#if defined(_WIN32)
        localtime_s(&tm_ts, &e->ts.tv_sec);
#else
        localtime_r(&e->ts.tv_sec, &tm_ts);
#endif
        char timebuf[32];
        strftime(timebuf, sizeof timebuf, "%Y-%m-%d %H:%M:%S", &tm_ts);

        fprintf(out,
                "  [%zu] %s.%03ld  %s (%s:%d %s)\n"
                "       %s\n",
                i,
                timebuf,
                e->ts.tv_nsec / 1000000L,
                hc_err_code_name(e->code),
                e->file,
                e->line,
                e->func,
                e->msg);
    }
}

/* Convenience wrapper mapping errno → hc_err_code + raise() */
void
hc_error_raise_errno(const char *file,
                     int         line,
                     const char *func,
                     const char *context)
{
    const int err = errno;

    hc_err_code code = HC_ERR_IO;
    if (err == ENOMEM)      code = HC_ERR_NOMEM;
    else if (err == EPERM ||
             err == EACCES) code = HC_ERR_PERM;
    else if (err == ETIMEDOUT)
                          code = HC_ERR_TIMEOUT;
    else if (err == ENOENT) code = HC_ERR_NOT_FOUND;
    /* Extend mapping as needed */

    hc_error_raise(code, file, line, func,
                   "%s failed: %s (errno=%d)",
                   context ? context : "System call",
                   strerror(err), err);
}

/* ------------------------------------------------------------------------- */
/*  End of file                                                              */
/* ------------------------------------------------------------------------- */
