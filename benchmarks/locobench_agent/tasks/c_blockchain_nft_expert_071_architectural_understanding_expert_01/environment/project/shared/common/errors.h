```c
/**
 * errors.h
 * HoloCanvas – Common error definitions and helpers
 *
 * This header is consumed by every micro-service that makes up the HoloCanvas
 * blockchain NFT platform.  It provides:
 *
 *   • A strictly-typed, 32-bit error code layout that unifies error handling
 *     across service boundaries.
 *   • Sub-system identifiers (Cryptograph, LedgerCore, etc.) so that any error
 *     can be traced back to its originating bounded context.
 *   • Severity levels that allow transport-agnostic log routing (stderr,
 *     syslog, Kafka topic, OpenTelemetry, …).
 *   • Convenience macros for building, de-constructing and propagating errors
 *     with zero boilerplate.
 *
 * Copyright (c) 2023-2024 The HoloCanvas contributors
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef HOLOCANVAS_SHARED_COMMON_ERRORS_H
#define HOLOCANVAS_SHARED_COMMON_ERRORS_H

/*───────────────────────────────────────────────────────────────────────────*/
#include <stdint.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif
/*───────────────────────────────────────────────────────────────────────────*/

/**
 * 32-bit error code layout
 *
 *   31 ── 24 │ Sub-system  (8 bits)
 *   23 ── 20 │ Severity    (4 bits)
 *   19 ── 16 │ Reserved    (4 bits)
 *   15 ──  0 │ Detail      (16 bits)
 */
typedef uint32_t hc_error_t;

/*===========================================================================*/
/* Sub-system identifiers (8 bits)                                           */
/*===========================================================================*/
typedef enum {
    HC_SUBSYS_UNDEFINED     = 0x00,
    HC_SUBSYS_CRYPTOGRAPH   = 0x01,
    HC_SUBSYS_LEDGER_CORE   = 0x02,
    HC_SUBSYS_MINT_FACTORY  = 0x03,
    HC_SUBSYS_GALLERY_GATE  = 0x04,
    HC_SUBSYS_DEFI_GARDEN   = 0x05,
    HC_SUBSYS_ORACLE_BRIDGE = 0x06,
    HC_SUBSYS_WALLET_PROXY  = 0x07,
    HC_SUBSYS_GOVERNANCE    = 0x08,
    HC_SUBSYS_COMMON        = 0xFE,   /* Utility & shared libs  */
    HC_SUBSYS_UNKNOWN       = 0xFF
} hc_subsys_t;

/*===========================================================================*/
/* Severity levels (4 bits)                                                  */
/*===========================================================================*/
typedef enum {
    HC_SEV_SUCCESS  = 0x0,   /* Non-error, success                      */
    HC_SEV_INFO     = 0x1,   /* Informative message, no action required */
    HC_SEV_WARNING  = 0x2,   /* Recoverable error                       */
    HC_SEV_ERROR    = 0x3,   /* Non-fatal error                         */
    HC_SEV_FATAL    = 0x4    /* Unrecoverable, must abort               */
} hc_sev_t;

/*===========================================================================*/
/* Macro helpers                                                             */
/*===========================================================================*/
#define HC_ERROR_PACK(subsys, sev, detail) \
    ((((uint32_t)(subsys)  & 0xFFu) << 24) | \
     (((uint32_t)(sev)     & 0x0Fu) << 20) | \
     (((uint32_t)(detail)  & 0xFFFFu)))

#define HC_ERROR_SUBSYS(code)   ((hc_subsys_t)(((code) >> 24) & 0xFFu))
#define HC_ERROR_SEVERITY(code) ((hc_sev_t)   (((code) >> 20) & 0x0Fu))
#define HC_ERROR_DETAIL(code)   ((uint16_t)   ((code) & 0xFFFFu))

#define HC_OK  ((hc_error_t)0)  /* Convenience alias for success */

/*===========================================================================*/
/* Common detail codes (16 bits)                                             */
/* Service-specific headers should extend their own detail ranges starting   */
/* at 0x0100 to avoid overlap with these commons.                            */
/*===========================================================================*/
typedef enum {
    HC_EC_SUCCESS             = 0x0000,
    HC_EC_INVALID_ARGUMENT    = 0x0001,
    HC_EC_OUT_OF_MEMORY       = 0x0002,
    HC_EC_IO_ERROR            = 0x0003,
    HC_EC_TIMEOUT             = 0x0004,
    HC_EC_NOT_IMPLEMENTED     = 0x0005,
    HC_EC_DATA_CORRUPT        = 0x0006,
    HC_EC_PERMISSION_DENIED   = 0x0007,
    HC_EC_STATE_VIOLATION     = 0x0008,
    HC_EC_DEPENDENCY_FAILURE  = 0x0009,
    HC_EC_NETWORK_UNREACHABLE = 0x000A,
    HC_EC_ASSERTION_FAILED    = 0x000B,
    HC_EC_UNKNOWN             = 0xFFFF
} hc_ec_t;

/*===========================================================================*/
/* Public API                                                                */
/*===========================================================================*/

/**
 * Convert an error code into a human-readable, short message.
 *
 * Implemented inline for header-only availability, but backed by an internal
 * constant table to keep it lightweight.  The resulting pointer is to a
 * read-only static string—do NOT free it.
 */
static inline const char *
hc_error_str(hc_error_t code)
{
    switch (HC_ERROR_DETAIL(code)) {
        case HC_EC_SUCCESS:             return "Success";
        case HC_EC_INVALID_ARGUMENT:    return "Invalid argument";
        case HC_EC_OUT_OF_MEMORY:       return "Out of memory";
        case HC_EC_IO_ERROR:            return "I/O error";
        case HC_EC_TIMEOUT:             return "Operation timed out";
        case HC_EC_NOT_IMPLEMENTED:     return "Not implemented";
        case HC_EC_DATA_CORRUPT:        return "Data corrupt";
        case HC_EC_PERMISSION_DENIED:   return "Permission denied";
        case HC_EC_STATE_VIOLATION:     return "Invalid state for operation";
        case HC_EC_DEPENDENCY_FAILURE:  return "Dependency failure";
        case HC_EC_NETWORK_UNREACHABLE: return "Network unreachable";
        case HC_EC_ASSERTION_FAILED:    return "Assertion failed";
        case HC_EC_UNKNOWN:             /* fallthrough */
        default:                        return "Unknown error";
    }
}

/**
 * Print a formatted error to the provided FILE* stream.
 *
 * Example:
 *   hc_error_t err = some_function();
 *   if (err != HC_OK) hc_error_fprint(stderr, err, __FILE__, __LINE__, "while opening wallet");
 */
static inline void
hc_error_fprint(FILE *stream, hc_error_t code,
                const char *file, int line, const char *context)
{
    fprintf(stream,
            "[%s] %s (subsys=%02X sev=%u detail=%04X) at %s:%d\n",
            context ? context : "context-none",
            hc_error_str(code),
            HC_ERROR_SUBSYS(code),
            HC_ERROR_SEVERITY(code),
            HC_ERROR_DETAIL(code),
            file, line);
}

/*===========================================================================*/
/* Convenience macros for ergonomic error handling                           */
/*===========================================================================*/

/* Wrap a call that returns hc_error_t; if it is not HC_OK, propagate upward */
#define HC_TRY(call)                           \
    do {                                       \
        hc_error_t _e = (call);                \
        if (_e != HC_OK) {                     \
            return _e;                         \
        }                                      \
    } while (0)

/*
 * Similar to HC_TRY, but logs the error with the current location before
 * bubbling it up.
 */
#ifndef HC_ERRLOG_STREAM
#  define HC_ERRLOG_STREAM stderr
#endif

#define HC_TRY_LOG(call, ctx)                                  \
    do {                                                       \
        hc_error_t _e = (call);                                \
        if (_e != HC_OK) {                                     \
            hc_error_fprint(HC_ERRLOG_STREAM, _e,              \
                            __FILE__, __LINE__, (ctx));        \
            return _e;                                         \
        }                                                      \
    } while (0)

/*
 * Assert-like helper that returns HC_ASSERTION_FAILED on failure rather than
 * aborting the process, allowing higher layers to decide how to handle it.
 */
#define HC_ENSURE(expr)                                                    \
    do {                                                                   \
        if (!(expr)) {                                                     \
            hc_error_t _e = HC_ERROR_PACK(HC_SUBSYS_COMMON,                \
                                          HC_SEV_FATAL,                    \
                                          HC_EC_ASSERTION_FAILED);         \
            hc_error_fprint(HC_ERRLOG_STREAM, _e,                          \
                            __FILE__, __LINE__, "HC_ENSURE");              \
            return _e;                                                     \
        }                                                                  \
    } while (0)

/*===========================================================================*/
#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* HOLOCANVAS_SHARED_COMMON_ERRORS_H */
```