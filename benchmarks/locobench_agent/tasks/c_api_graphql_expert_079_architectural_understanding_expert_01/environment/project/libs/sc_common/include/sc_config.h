#ifndef SC_CONFIG_H
#define SC_CONFIG_H
/*
 * sc_config.h
 * SynestheticCanvas Common Configuration Header
 *
 * This header centralises compile-time configuration toggles, version
 * information, attribute/visibility helpers and a thin shim that allows
 * the rest of the code-base to query runtime parameters (usually sourced
 * from environment variables) without dragging in the heavyweight service
 * layer.
 *
 *  Copyright (c) 2024
 *  SynestheticCanvas Contributors <opensource@synestheticcanvas.io>
 *
 *  SPDX-License-Identifier: MIT
 */

#ifdef __cplusplus
extern "C" {
#endif

/*==========================================================================*/
/*  Standard Library Includes                                               */
/*==========================================================================*/
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
#   include <stdalign.h>
#   define SC_HAS_C11 1
#else
#   define SC_HAS_C11 0
#endif

/*==========================================================================*/
/*  Versioning                                                              */
/*==========================================================================*/
#define SC_VERSION_MAJOR    1
#define SC_VERSION_MINOR    4
#define SC_VERSION_PATCH    2

#define SC_VERSION_STR_HELPER(x) #x
#define SC_VERSION_STR(maj, min, pat)  \
        SC_VERSION_STR_HELPER(maj) "." \
        SC_VERSION_STR_HELPER(min) "." \
        SC_VERSION_STR_HELPER(pat)

#define SC_VERSION  SC_VERSION_STR(SC_VERSION_MAJOR, SC_VERSION_MINOR, SC_VERSION_PATCH)

/*==========================================================================*/
/*  Platform / Compiler Detection                                           */
/*==========================================================================*/
#if defined(_WIN32) || defined(_WIN64)
#   define SC_PLATFORM_WINDOWS 1
#else
#   define SC_PLATFORM_WINDOWS 0
#endif

#if defined(__linux__)
#   define SC_PLATFORM_LINUX 1
#else
#   define SC_PLATFORM_LINUX 0
#endif

#if defined(__APPLE__)
#   define SC_PLATFORM_APPLE 1
#else
#   define SC_PLATFORM_APPLE 0
#endif

#if defined(__GNUC__)
#   define SC_COMPILER_GCC 1
#else
#   define SC_COMPILER_GCC 0
#endif

#if defined(_MSC_VER)
#   define SC_COMPILER_MSVC 1
#else
#   define SC_COMPILER_MSVC 0
#endif

/*==========================================================================*/
/*  Dynamic Library Export / Import Helpers                                 */
/*==========================================================================*/
#if SC_PLATFORM_WINDOWS
#   ifdef SC_EXPORT_SYMBOLS
#       define SC_PUBLIC __declspec(dllexport)
#   else
#       define SC_PUBLIC __declspec(dllimport)
#   endif
#   define SC_PRIVATE
#else
#   if SC_COMPILER_GCC
#       define SC_PUBLIC  __attribute__((visibility("default")))
#       define SC_PRIVATE __attribute__((visibility("hidden")))
#   else
#       define SC_PUBLIC
#       define SC_PRIVATE
#   endif
#endif

/*==========================================================================*/
/*  Static / Compile-time Assertions                                        */
/*==========================================================================*/
#if SC_HAS_C11
#   define SC_STATIC_ASSERT(cond, msg) _Static_assert(cond, msg)
#else
    /* Fallback that creates an invalid typedef if the condition is false */
#   define SC_STATIC_ASSERT(cond, msg) typedef char static_assertion_##msg[(cond) ? 1 : -1]
#endif

/* Validate fundamental assumptions early */
SC_STATIC_ASSERT(sizeof(void*) == 4 || sizeof(void*) == 8, pointer_size_must_be_32_or_64_bits);

/*==========================================================================*/
/*  Feature Flags (Override at compile-time with -Dflag=0|1)                */
/*==========================================================================*/

#ifndef SC_FEATURE_GRAPHQL
#   define SC_FEATURE_GRAPHQL      1
#endif

#ifndef SC_FEATURE_REST
#   define SC_FEATURE_REST         1
#endif

#ifndef SC_FEATURE_VALIDATION
#   define SC_FEATURE_VALIDATION   1
#endif

#ifndef SC_FEATURE_MONITORING
#   define SC_FEATURE_MONITORING   1
#endif

#ifndef SC_FEATURE_LOGGING
#   define SC_FEATURE_LOGGING      1
#endif

/*==========================================================================*/
/*  Default Limits (Adjust per deployment)                                  */
/*==========================================================================*/
#ifndef SC_MAX_HTTP_HEADER_SIZE
#   define SC_MAX_HTTP_HEADER_SIZE     (16 * 1024)   /* 16 KiB */
#endif

#ifndef SC_MAX_PAYLOAD_SIZE
#   define SC_MAX_PAYLOAD_SIZE         (10 * 1024 * 1024) /* 10 MiB */
#endif

#ifndef SC_DEFAULT_PAGE_SIZE
#   define SC_DEFAULT_PAGE_SIZE        50
#endif

/*==========================================================================*/
/*  Logging                                                                 */
/*==========================================================================*/
typedef enum sc_log_level {
    SC_LOG_TRACE = 0,
    SC_LOG_DEBUG,
    SC_LOG_INFO,
    SC_LOG_WARN,
    SC_LOG_ERROR,
    SC_LOG_FATAL
} sc_log_level_t;

/* Compile-time default, can be overridden via -DSC_LOG_LEVEL */
#ifndef SC_LOG_LEVEL
#   ifdef NDEBUG
#       define SC_LOG_LEVEL SC_LOG_INFO
#   else
#       define SC_LOG_LEVEL SC_LOG_DEBUG
#   endif
#endif

/*==========================================================================*/
/*  Runtime Configuration Structure                                         */
/*==========================================================================*/
typedef struct sc_runtime_config {
    const char      *environment;       /* "development", "staging", "production"      */
    const char      *service_name;      /* e.g., "palette-service"                     */
    uint16_t         service_port;      /* default 0 means "use environment variable"   */

    /* feature toggles */
    bool             enable_monitoring;
    bool             enable_validation;
    bool             enable_request_tracing;

    /* runtime knobs */
    sc_log_level_t   log_level;
    uint32_t         max_payload_size;
    uint16_t         default_page_size;
} sc_runtime_config_t;

/*==========================================================================*/
/*  Inline Helpers                                                          */
/*==========================================================================*/
#include <stdlib.h>
#include <string.h>

SC_PUBLIC
static inline uint16_t sc_u16_from_env(const char *name, uint16_t fallback)
{
    const char *val = getenv(name);
    if (!val || !*val) return fallback;

    char *endptr = NULL;
    unsigned long parsed = strtoul(val, &endptr, 10);
    if (endptr == val || *endptr != '\0' || parsed > 0xFFFFUL)
        return fallback;

    return (uint16_t)parsed;
}

SC_PUBLIC
static inline bool sc_bool_from_env(const char *name, bool fallback)
{
    const char *val = getenv(name);
    if (!val || !*val) return fallback;

    if (!strcasecmp(val, "1") ||
        !strcasecmp(val, "true") ||
        !strcasecmp(val, "yes") ||
        !strcasecmp(val, "on"))
        return true;

    if (!strcasecmp(val, "0") ||
        !strcasecmp(val, "false") ||
        !strcasecmp(val, "no") ||
        !strcasecmp(val, "off"))
        return false;

    return fallback;
}

SC_PUBLIC
static inline sc_log_level_t sc_log_level_from_env(const char *name, sc_log_level_t fallback)
{
    const char *val = getenv(name);
    if (!val) return fallback;

    if (!strcasecmp(val, "trace")) return SC_LOG_TRACE;
    if (!strcasecmp(val, "debug")) return SC_LOG_DEBUG;
    if (!strcasecmp(val, "info"))  return SC_LOG_INFO;
    if (!strcasecmp(val, "warn"))  return SC_LOG_WARN;
    if (!strcasecmp(val, "error")) return SC_LOG_ERROR;
    if (!strcasecmp(val, "fatal")) return SC_LOG_FATAL;

    return fallback;
}

/*-------------------------------------------------------------------------
 * sc_config_load_default
 *
 * Populate config with sane defaults, reading from well-known environment
 * variables when present. Does not allocate memory – string pointers point
 * directly to getenv-backed storage, the caller must copy if longer
 * lifetimes are required.
 *------------------------------------------------------------------------*/
SC_PUBLIC
static inline void sc_config_load_default(sc_runtime_config_t *cfg,
                                          const char *service_name,
                                          uint16_t default_port)
{
    if (!cfg) return;

    cfg->environment           = getenv("SC_ENVIRONMENT") ? getenv("SC_ENVIRONMENT") : "development";
    cfg->service_name          = service_name;
    cfg->service_port          = sc_u16_from_env("SC_SERVICE_PORT", default_port);

    cfg->enable_monitoring     = sc_bool_from_env("SC_ENABLE_MONITORING", SC_FEATURE_MONITORING);
    cfg->enable_validation     = sc_bool_from_env("SC_ENABLE_VALIDATION", SC_FEATURE_VALIDATION);
    cfg->enable_request_tracing= sc_bool_from_env("SC_ENABLE_TRACING",    false);

    cfg->log_level             = sc_log_level_from_env("SC_LOG_LEVEL", (sc_log_level_t)SC_LOG_LEVEL);
    cfg->max_payload_size      = (uint32_t)strtoul(getenv("SC_MAX_PAYLOAD") ?: "", NULL, 10);
    if (cfg->max_payload_size == 0 || cfg->max_payload_size > SC_MAX_PAYLOAD_SIZE)
        cfg->max_payload_size = SC_MAX_PAYLOAD_SIZE;

    cfg->default_page_size     = (uint16_t)strtoul(getenv("SC_DEFAULT_PAGE_SIZE") ?: "", NULL, 10);
    if (cfg->default_page_size == 0 || cfg->default_page_size > 1000)
        cfg->default_page_size = SC_DEFAULT_PAGE_SIZE;
}

/*==========================================================================*/
/*  Deprecation / Unavailable                                               */
/*==========================================================================*/
#if SC_COMPILER_GCC || (__has_attribute(deprecated))
#   define SC_DEPRECATED(msg) __attribute__((deprecated(msg)))
#elif SC_COMPILER_MSVC
#   define SC_DEPRECATED(msg) __declspec(deprecated(msg))
#else
#   define SC_DEPRECATED(msg)
#endif

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SC_CONFIG_H */
