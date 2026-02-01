/*=====================================================================================
 *  LexiLearn Orchestrator – Common Public Header
 *
 *  File:    ll_common.h
 *  Desc:    Public-facing utilities shared across the entire LexiLearn MVC
 *           Orchestrator stack (Controller, Model, View).  This header exposes
 *           the project-wide error-handling contract, logging facilities, build
 *           configuration macros, and small cross-platform helpers.
 *
 *  Copyright © 2023-2024  LexiLearn Contributors
 *  SPDX-License-Identifier: MIT
 *====================================================================================*/
#ifndef LEXILEARN_LL_COMMON_H
#define LEXILEARN_LL_COMMON_H

/*------------------------------------------------------------------------------------
 *  Standard Library
 *-----------------------------------------------------------------------------------*/
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*------------------------------------------------------------------------------------
 *  C++ Compatibility
 *-----------------------------------------------------------------------------------*/
#ifdef __cplusplus
#   define LL_EXTERN_C extern "C"
#else
#   define LL_EXTERN_C
#endif

/*------------------------------------------------------------------------------------
 *  Compiler Feature Detection
 *-----------------------------------------------------------------------------------*/
#if defined(__GNUC__) || defined(__clang__)
#   define LL_ATTR_NONNULL(...) __attribute__((nonnull(__VA_ARGS__)))
#   define LL_ATTR_FORMAT(archetype, idx, first) __attribute__((format(archetype, idx, first)))
#   define LL_ATTR_UNUSED __attribute__((unused))
#else
#   define LL_ATTR_NONNULL(...)
#   define LL_ATTR_FORMAT(archetype, idx, first)
#   define LL_ATTR_UNUSED
#endif

#if defined(_WIN32) && defined(LL_SHARED)
#   ifdef LL_BUILD_DLL
#       define LL_API LL_EXTERN_C __declspec(dllexport)
#   else
#       define LL_API LL_EXTERN_C __declspec(dllimport)
#   endif
#else
#   define LL_API LL_EXTERN_C __attribute__((visibility("default")))
#endif

/*------------------------------------------------------------------------------------
 *  Versioning
 *-----------------------------------------------------------------------------------*/
#define LL_VERSION_MAJOR   0
#define LL_VERSION_MINOR   9
#define LL_VERSION_PATCH   3

#define LL_VERSION_STRING  "0.9.3"

/*------------------------------------------------------------------------------------
 *  Likely / Unlikely branch prediction hints
 *-----------------------------------------------------------------------------------*/
#if defined(__GNUC__) || defined(__clang__)
#   define LL_LIKELY(x)   __builtin_expect(!!(x), 1)
#   define LL_UNLIKELY(x) __builtin_expect(!!(x), 0)
#else
#   define LL_LIKELY(x)   (x)
#   define LL_UNLIKELY(x) (x)
#endif

/*------------------------------------------------------------------------------------
 *  Error / Status Codes
 *-----------------------------------------------------------------------------------*/
typedef enum
{
    LL_STATUS_OK = 0,
    LL_STATUS_ERR_ALLOC,            /* Out-of-memory                           */
    LL_STATUS_ERR_IO,               /* I/O error – failed to read / write      */
    LL_STATUS_ERR_INVALID_ARG,      /* Invalid function argument               */
    LL_STATUS_ERR_STATE,            /* Invalid program state                   */
    LL_STATUS_ERR_TIMEOUT,          /* Operation timed-out                     */
    LL_STATUS_ERR_NOT_IMPLEMENTED,  /* Placeholder                             */
    LL_STATUS_ERR_PERMISSION,       /* Permission denied (file/network)        */
    LL_STATUS_ERR_MODEL_DRIFT,      /* Model drift detected                    */
    LL_STATUS_ERR_UNKNOWN           /* Unknown / unspecified error             */
} ll_status_t;

/* Return a human-readable string describing a status code. */
LL_API const char *ll_status_to_string(ll_status_t status);

/*------------------------------------------------------------------------------------
 *  Logging
 *-----------------------------------------------------------------------------------*/
typedef enum
{
    LL_LOG_FATAL = 0,
    LL_LOG_ERROR,
    LL_LOG_WARN,
    LL_LOG_INFO,
    LL_LOG_DEBUG,
    LL_LOG_TRACE
} ll_log_level_t;

/* Default compile-time log level (overridden by CMake or -DLL_LOG_LEVEL). */
#ifndef LL_LOG_LEVEL
#   ifdef NDEBUG
#       define LL_LOG_LEVEL LL_LOG_INFO
#   else
#       define LL_LOG_LEVEL LL_LOG_DEBUG
#   endif
#endif

/* Terminal colour escape codes (POSIX). */
#define LL_CLR_RESET   "\x1b[0m"
#define LL_CLR_FATAL   "\x1b[1;35m"
#define LL_CLR_ERROR   "\x1b[1;31m"
#define LL_CLR_WARN    "\x1b[1;33m"
#define LL_CLR_INFO    "\x1b[1;32m"
#define LL_CLR_DEBUG   "\x1b[1;36m"
#define LL_CLR_TRACE   "\x1b[0;37m"

/* Internal log helper (should not be called directly; use macros). */
LL_API void ll_log_internal(ll_log_level_t level,
                            const char     *file,
                            int             line,
                            const char     *fmt, ...)
                            LL_ATTR_FORMAT(printf, 4, 5);

/* Convenience macros (guarded by compile-time log level). */
#define LL_LOG(level, fmt, ...) \
    do { if ((level) <= LL_LOG_LEVEL) \
            ll_log_internal((level), __FILE__, __LINE__, (fmt), ##__VA_ARGS__); } while(0)

#define LL_FATAL(fmt, ...) LL_LOG(LL_LOG_FATAL, fmt, ##__VA_ARGS__)
#define LL_ERROR(fmt, ...) LL_LOG(LL_LOG_ERROR, fmt, ##__VA_ARGS__)
#define LL_WARN(fmt,  ...) LL_LOG(LL_LOG_WARN,  fmt, ##__VA_ARGS__)
#define LL_INFO(fmt,  ...) LL_LOG(LL_LOG_INFO,  fmt, ##__VA_ARGS__)
#define LL_DEBUG(fmt, ...) LL_LOG(LL_LOG_DEBUG, fmt, ##__VA_ARGS__)
#define LL_TRACE(fmt, ...) LL_LOG(LL_LOG_TRACE, fmt, ##__VA_ARGS__)

/*------------------------------------------------------------------------------------
 *  Memory Utilities
 *-----------------------------------------------------------------------------------*/
#define LL_SAFE_FREE(ptr)  \
    do {                   \
        free(ptr);         \
        (ptr) = NULL;      \
    } while (0)

/**
 *  Allocate zero-initialised memory with error propagation.
 *
 *  @param count   Number of elements
 *  @param size    Size of each element
 *  @param status  Out-parameter for failure reason (may be NULL)
 *
 *  @return        Pointer on success, NULL on failure
 */
static inline void *
ll_calloc(size_t count, size_t size, ll_status_t *status)
{
    void *mem = calloc(count, size);
    if (LL_UNLIKELY(!mem))
    {
        if (status) *status = LL_STATUS_ERR_ALLOC;
        LL_ERROR("Out-of-memory: calloc(%zu, %zu)", count, size);
    }
    else if (status)
    {
        *status = LL_STATUS_OK;
    }
    return mem;
}

/*------------------------------------------------------------------------------------
 *  String Utilities
 *-----------------------------------------------------------------------------------*/
/* Cross-platform strdup (C11 does not include it in <string.h>). */
static inline char *
ll_strdup(const char *src) LL_ATTR_NONNULL(1)
{
#if defined(_MSC_VER)
    return _strdup(src);
#else
    size_t len  = strlen(src) + 1U;
    char  *copy = (char *)malloc(len);
    if (!copy)
    {
        LL_ERROR("Out-of-memory while duplicating string");
        return NULL;
    }
    return (char *)memcpy(copy, src, len);
#endif
}

/*------------------------------------------------------------------------------------
 *  Build-time Feature Flags
 *-----------------------------------------------------------------------------------*/
#define LL_FEATURE_HYPERPARAM_TUNING   (1 << 0)
#define LL_FEATURE_DATA_PREPROCESSING  (1 << 1)
#define LL_FEATURE_MODEL_MONITORING    (1 << 2)
#define LL_FEATURE_MODEL_VERSIONING    (1 << 3)
#define LL_FEATURE_AUTOMATED_RETRAIN   (1 << 4)

static inline uint32_t ll_enabled_features(void)
{
    uint32_t flags = 0;
#ifdef LL_ENABLE_HYPERPARAM_TUNING
    flags |= LL_FEATURE_HYPERPARAM_TUNING;
#endif
#ifdef LL_ENABLE_DATA_PREPROCESSING
    flags |= LL_FEATURE_DATA_PREPROCESSING;
#endif
#ifdef LL_ENABLE_MODEL_MONITORING
    flags |= LL_FEATURE_MODEL_MONITORING;
#endif
#ifdef LL_ENABLE_MODEL_VERSIONING
    flags |= LL_FEATURE_MODEL_VERSIONING;
#endif
#ifdef LL_ENABLE_AUTOMATED_RETRAIN
    flags |= LL_FEATURE_AUTOMATED_RETRAIN;
#endif
    return flags;
}

/*------------------------------------------------------------------------------------
 *  Runtime Checks (Assertions that cannot be compiled-out)
 *-----------------------------------------------------------------------------------*/
#define LL_CHECK(cond, status_code)                                    \
    do {                                                               \
        if (LL_UNLIKELY(!(cond))) {                                    \
            LL_FATAL("Critical check failed: (%s)", #cond);            \
            return (status_code);                                      \
        }                                                              \
    } while (0)

/*------------------------------------------------------------------------------------
 *  Fwd Decls for Frequently Used Core Types
 *-----------------------------------------------------------------------------------*/
typedef struct ll_context_s  ll_context_t;   /* Core orchestration context      */
typedef struct ll_model_s    ll_model_t;     /* Abstract model interface        */
typedef struct ll_dataset_s  ll_dataset_t;   /* Dataset wrapper                 */

/*------------------------------------------------------------------------------------
 *  Implementation – Inline Only (Small Footprint)
 *-----------------------------------------------------------------------------------*/
#ifdef LL_COMMON_IMPL
/* Convert status to string (header-only for small enum). */
LL_API
const char *ll_status_to_string(ll_status_t status)
{
    switch (status)
    {
        case LL_STATUS_OK:                return "OK";
        case LL_STATUS_ERR_ALLOC:         return "Allocation failed";
        case LL_STATUS_ERR_IO:            return "I/O error";
        case LL_STATUS_ERR_INVALID_ARG:   return "Invalid argument";
        case LL_STATUS_ERR_STATE:         return "Invalid program state";
        case LL_STATUS_ERR_TIMEOUT:       return "Timeout";
        case LL_STATUS_ERR_NOT_IMPLEMENTED:return "Not implemented";
        case LL_STATUS_ERR_PERMISSION:    return "Permission denied";
        case LL_STATUS_ERR_MODEL_DRIFT:   return "Model drift";
        default:                          return "Unknown error";
    }
}

/* Colour mapping for log levels. */
static inline const char *ll_color_for_level(ll_log_level_t lvl)
{
    switch (lvl)
    {
        case LL_LOG_FATAL: return LL_CLR_FATAL;
        case LL_LOG_ERROR: return LL_CLR_ERROR;
        case LL_LOG_WARN:  return LL_CLR_WARN;
        case LL_LOG_INFO:  return LL_CLR_INFO;
        case LL_LOG_DEBUG: return LL_CLR_DEBUG;
        case LL_LOG_TRACE: return LL_CLR_TRACE;
        default:           return LL_CLR_RESET;
    }
}

/* Central logging implementation. */
LL_API
void ll_log_internal(ll_log_level_t level,
                     const char     *file,
                     int             line,
                     const char     *fmt, ...)
{
    static const char *level_names[] =
    {
        "FATAL", "ERROR", "WARN ", "INFO ", "DEBUG", "TRACE"
    };

    /* Timestamp (UTC) */
    char timebuf[32];
    {
        time_t t      = time(NULL);
        struct tm tm_ = {0};
#if defined(_WIN32)
        gmtime_s(&tm_, &t);
#else
        gmtime_r(&t, &tm_);
#endif
        strftime(timebuf, sizeof timebuf, "%Y-%m-%dT%H:%M:%SZ", &tm_);
    }

    /* Build the preamble */
    fprintf(stderr,
            "%s[%s][%s][%s:%d] ",
            ll_color_for_level(level),
            timebuf,
            level_names[level],
            file,
            line);

    /* Variadic payload */
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);

    /* Reset colour + newline */
    fprintf(stderr, "%s\n", LL_CLR_RESET);

    /* Fatal => abort */
    if (level == LL_LOG_FATAL)
    {
        abort();
    }
}

#endif /* LL_COMMON_IMPL */

#endif /* LEXILEARN_LL_COMMON_H */
