/**
 * @file ll_error.h
 * @brief Centralised error/status handling for the LexiLearn MVC Orchestrator.
 *
 * All public functions in the project should:
 *   1. Return an `ll_status_t` indicating success or the type of failure.
 *   2. NEVER expose raw `errno` or implementation-specific details to callers.
 *   3. Use the LL_* macros in this header to propagate failures with minimal
 *      boilerplate while retaining file/line context for debugging.
 *
 * This header is intentionally dependency-light so that it can be included
 * from anywhere in the code-base (Model, View, Controller, feature-store
 * utilities, etc.) without causing circular-include issues.
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#ifndef LEXILEARN_ORCHESTRATOR_COMMON_LL_ERROR_H
#define LEXILEARN_ORCHESTRATOR_COMMON_LL_ERROR_H

/* ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* ────────────────────────────────────────────────────────────────────────── */
/* Versioning (semantic version of the error module itself) */
#define LL_ERROR_MAJOR   1
#define LL_ERROR_MINOR   0
#define LL_ERROR_PATCH   0
#define LL_ERROR_VERSION_STRING  "1.0.0"

/* ────────────────────────────────────────────────────────────────────────── */
/* Compile-time configuration flags                                           *
 * Enable fine-grained debugging/tracing without recompiling the entire app. */
#ifndef LL_ENABLE_DEBUG
#   define LL_ENABLE_DEBUG 0   /* Set to 1 for verbose error diagnostics.   */
#endif

#ifndef LL_ENABLE_BACKTRACE
#   define LL_ENABLE_BACKTRACE 0 /* Requires execinfo.h on *nix platforms   */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Enumerated status / error codes.                                           *
 * NOTE: Keep the numeric ordering stable; never remove existing items after *
 * they have been released. Append new codes to preserve ABI compatibility.  */
typedef enum
{
    LL_OK = 0,                      /* Success */
    LL_ERR_UNKNOWN = 1,             /* Unknown/unspecified failure */
    LL_ERR_INVALID_ARGUMENT,        /* Invalid function parameter(s) */
    LL_ERR_OUT_OF_MEMORY,           /* Memory allocation failed */
    LL_ERR_IO,                      /* Persistent or transient I/O error */
    LL_ERR_NOT_FOUND,               /* Requested entity does not exist */
    LL_ERR_ALREADY_EXISTS,          /* Uniqueness violation */
    LL_ERR_PERMISSION_DENIED,       /* Security/ACL failure */
    LL_ERR_TIMEOUT,                 /* Operation timed out */
    LL_ERR_MODEL_DRIFT,             /* Deviation in model performance */
    LL_ERR_DATA_VALIDATION,         /* Data integrity/validation failure */
    LL_ERR_PIPELINE_STAGE_FAILED,   /* Any stage in the pipeline crashed */
    LL_ERR_JSON_PARSE,              /* JSON parsing/serialization failure */
    LL_ERR_PROTOBUF,                /* (De)serialization using protobuf */
    LL_ERR_DB,                      /* Database/storage subsystem failure */
    LL_ERR_SHUTTING_DOWN,           /* Service is shutting down */
    LL_ERR_NOT_IMPLEMENTED,         /* Feature stubbed/not available */
    LL_ERR_CONCURRENCY,             /* Concurrency primitive failure */
    LL_ERR_RESOURCE_EXHAUSTED,      /* GPU/CPU/file-descriptor exhaustion */
    LL_ERR_VERSION_MISMATCH,        /* ABI/protocol version mismatch */
    /* ---- Add new codes here ---- */
    LL_ERR__COUNT                    /* Keep as last to determine size */
} ll_status_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Human-readable status strings. Could be localised in the future.          */
static inline const char *ll_status_str(ll_status_t status)
{
    switch (status)
    {
        case LL_OK:                        return "OK";
        case LL_ERR_UNKNOWN:               return "Unknown error";
        case LL_ERR_INVALID_ARGUMENT:      return "Invalid argument";
        case LL_ERR_OUT_OF_MEMORY:         return "Out of memory";
        case LL_ERR_IO:                    return "I/O error";
        case LL_ERR_NOT_FOUND:             return "Not found";
        case LL_ERR_ALREADY_EXISTS:        return "Already exists";
        case LL_ERR_PERMISSION_DENIED:     return "Permission denied";
        case LL_ERR_TIMEOUT:               return "Timeout";
        case LL_ERR_MODEL_DRIFT:           return "Model drift detected";
        case LL_ERR_DATA_VALIDATION:       return "Data validation failed";
        case LL_ERR_PIPELINE_STAGE_FAILED: return "Pipeline stage failed";
        case LL_ERR_JSON_PARSE:            return "JSON parse error";
        case LL_ERR_PROTOBUF:              return "Protobuf error";
        case LL_ERR_DB:                    return "Database error";
        case LL_ERR_SHUTTING_DOWN:         return "Shutting down";
        case LL_ERR_NOT_IMPLEMENTED:       return "Not implemented";
        case LL_ERR_CONCURRENCY:           return "Concurrency error";
        case LL_ERR_RESOURCE_EXHAUSTED:    return "Resource exhausted";
        case LL_ERR_VERSION_MISMATCH:      return "Version mismatch";
        default:                           return "Unrecognised status code";
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Error handling hooks.                                                      *
 * The orchestrator allows the embedding application to plug in its own      *
 * logging or telemetry system without hard-wiring e.g. syslog, spdlog, etc. */
typedef void (*ll_error_handler_t)(
    ll_status_t  status,
    const char  *msg,        /* Formatted message (may be NULL) */
    const char  *file,       /* __FILE__                          */
    int          line,       /* __LINE__                          */
    const char  *function    /* __func__                          */
);

/* Register a custom handler. Passing NULL reverts to default stderr logger. */
void ll_error_set_handler(ll_error_handler_t handler);

/* Retrieve current callback (may be NULL). */
ll_error_handler_t ll_error_get_handler(void);

/* Internal default handler (exposed for unit test injection). */
void ll_error_default_handler(
    ll_status_t status,
    const char *msg,
    const char *file,
    int         line,
    const char *function
);

/* ────────────────────────────────────────────────────────────────────────── */
/* Convenience macros.                                                        *
 * Why macros? We want file/line/function baked in at the call site to avoid  *
 * double-evaluation issues prevalent with inline functions.                  */

/* Format spec helper for snprintf-style messages, compiled away if NULL. */
#if __STDC_VERSION__ >= 199901L
#   include <stdarg.h>
static inline void
ll__invoke_handler(ll_status_t status,
                   const char *file,
                   int line,
                   const char *function,
                   const char *fmt, ...)
{
    /* Fetch active handler; fall back to default implementation. */
    ll_error_handler_t cb = ll_error_get_handler();
    if (!cb) cb = ll_error_default_handler;

    char buf[512] = {0};

    if (fmt)
    {
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
    }

    cb(status, (fmt ? buf : NULL), file, line, function);
}
#else
/* Pre-C99 fallback (less informative, avoids variadics) */
#   define ll__invoke_handler(status,file,line,func,fmt,...) \
        do {                                                  \
            (void)(fmt);                                      \
            ll_error_handler_t cb = ll_error_get_handler();   \
            if (!cb) cb = ll_error_default_handler;           \
            cb(status, NULL, file, line, func);               \
        } while (0)
#endif

/* Raise an error and return it. */
#define LL_RAISE(status, fmt, ...)                                   \
    do {                                                             \
        ll__invoke_handler((status), __FILE__, __LINE__, __func__,   \
                           (fmt), ##__VA_ARGS__);                    \
        return (status);                                             \
    } while (0)

/* Propagate error from callee — similar to TRY/CATCH but lightweight. */
#define LL_CHECK(expr)                                   \
    do {                                                 \
        ll_status_t _st = (expr);                        \
        if (LL_OK != _st)                                \
        {                                                \
            /* Bubble up with context but keep original status. */ \
            ll__invoke_handler(_st, __FILE__, __LINE__, __func__, \
                               "Propagating failure: %s", \
                               ll_status_str(_st));      \
            return _st;                                  \
        }                                                \
    } while (0)

/* Assert-like helper that *terminates* the process (irrecoverable error). */
#define LL_ABORT_IF(cond, fmt, ...)                                      \
    do {                                                                 \
        if (cond)                                                        \
        {                                                                \
            ll__invoke_handler(LL_ERR_UNKNOWN, __FILE__, __LINE__,       \
                               __func__, (fmt), ##__VA_ARGS__);          \
            abort();                                                     \
        }                                                                \
    } while (0)

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation section (inline + header-only)                             */

#if LL_ENABLE_BACKTRACE
#   include <execinfo.h>
static inline void ll__print_backtrace(void)
{
    void *buffer[32];
    int n = backtrace(buffer, (int)(sizeof(buffer) / sizeof(buffer[0])));
    backtrace_symbols_fd(buffer, n, fileno(stderr));
}
#else
#   define ll__print_backtrace() ((void)0)
#endif

/* Default stderr-based logger. */
static inline void
ll_error_default_handler(
    ll_status_t status,
    const char *msg,
    const char *file,
    int         line,
    const char *function)
{
#if LL_ENABLE_DEBUG
    fprintf(stderr,
            "[LexiLearn] ERROR %-3d (%s) @ %s:%d %s(): %s\n",
            status,
            ll_status_str(status),
            file,
            line,
            function,
            msg ? msg : "-");
#else
    /* Minimal log for production builds */
    fprintf(stderr, "LexiLearn error (%d): %s\n",
            status, ll_status_str(status));
    (void)file; (void)line; (void)function; (void)msg;
#endif
    if (status == LL_ERR_OUT_OF_MEMORY || status == LL_ERR_RESOURCE_EXHAUSTED)
    {
        /* These failures are often fatal; dump backtrace if enabled. */
        ll__print_backtrace();
    }
}

/* Global pointer guarded by atomic/volatile for thread safety. */
#include <stdatomic.h>
static _Atomic(ll_error_handler_t) g_ll_error_handler = ATOMIC_VAR_INIT(NULL);

static inline void ll_error_set_handler(ll_error_handler_t handler)
{
    atomic_store_explicit(&g_ll_error_handler, handler, memory_order_release);
}

static inline ll_error_handler_t ll_error_get_handler(void)
{
    return atomic_load_explicit(&g_ll_error_handler, memory_order_acquire);
}

/* ────────────────────────────────────────────────────────────────────────── */
#endif /* LEXILEARN_ORCHESTRATOR_COMMON_LL_ERROR_H */
