/*
 *  SynestheticCanvas – Common Type Definitions
 *
 *  Copyright (c) 2024
 *  SynestheticCanvas Authors. All rights reserved.
 *
 *  SPDX-License-Identifier: MIT
 *
 *  This header centralises the primitive and high-level data types that are
 *  shared across the SynestheticCanvas micro-service constellation.  Keeping
 *  these definitions in a single translation unit eliminates subtle ABI
 *  mismatches and ensures that every service speaks the same binary dialect.
 *
 *  NOTE:
 *      This header is intentionally dependency-light and does not pull in any
 *      project-specific symbols beyond <stdint.h> and friends.  Treat it as the
 *      “System V ABI” of the SynestheticCanvas ecosystem.
 */

#ifndef SC_TYPES_H_
#define SC_TYPES_H_

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────  Imports  ── */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>

/* ───────────────────────────────────────────────────────  Compiler Tweaks ── */
#if defined(_MSC_VER)
#  define SC_INLINE __inline
#else
#  define SC_INLINE inline
#endif

/* Export symbols when building shared objects on supported platforms. */
#if defined(_WIN32)
#  ifdef SC_EXPORTS
#    define SC_API __declspec(dllexport)
#  else
#    define SC_API __declspec(dllimport)
#  endif
#elif defined(__GNUC__) && __GNUC__ >= 4
#  define SC_API __attribute__((visibility("default")))
#else
#  define SC_API /* nothing */
#endif

/* “Always inline” helper – falls back to a regular inline if unavailable. */
#if defined(__GNUC__) || defined(__clang__)
#  define SC_FORCE_INLINE static __inline__ __attribute__((always_inline))
#elif defined(_MSC_VER)
#  define SC_FORCE_INLINE static __forceinline
#else
#  define SC_FORCE_INLINE static inline
#endif

/* Branch prediction hints – compile to a no-op on unknown toolchains. */
#if defined(__GNUC__) || defined(__clang__)
#  define SC_LIKELY(x)   __builtin_expect(!!(x), 1)
#  define SC_UNLIKELY(x) __builtin_expect(!!(x), 0)
#else
#  define SC_LIKELY(x)   (x)
#  define SC_UNLIKELY(x) (x)
#endif

/* ────────────────────────────────────────────────────────  Versioning  ──── */
#define SC_TYPES_VERSION_MAJOR  1
#define SC_TYPES_VERSION_MINOR  0
#define SC_TYPES_VERSION_PATCH  0

/* Combine into a single integer for easy range checks: Mmmpp (e.g. 10000) */
#define SC_TYPES_VERSION_CODE \
    ((SC_TYPES_VERSION_MAJOR * 10000) + (SC_TYPES_VERSION_MINOR * 100) + \
     SC_TYPES_VERSION_PATCH)

/* ─────────────────────────────────────────────────────────  Status Codes ── */
/*
 *  We use a single set of error codes across all layers (network, storage,
 *  GraphQL resolver, etc.) to simplify inter-service translation.  Values are
 *  grouped in ranges for quick categorisation without bit masking.
 *
 *      0                 Success
 *      1–99              Generic errors
 *      100–199           I/O subsystem
 *      200–299           Network stack
 *      300–399           Validation / decoding
 *      400–499           Service-level runtime errors
 */
typedef enum sc_status_e {
    /* Success */
    SC_STATUS_OK = 0,

    /* Generic errors (1–99) */
    SC_STATUS_ERR_UNKNOWN              = 1,
    SC_STATUS_ERR_INVALID_ARGUMENT     = 2,
    SC_STATUS_ERR_OUT_OF_RANGE         = 3,
    SC_STATUS_ERR_NULL_POINTER         = 4,
    SC_STATUS_ERR_ALLOCATION_FAILED    = 5,
    SC_STATUS_ERR_NOT_IMPLEMENTED      = 6,
    SC_STATUS_ERR_TIMEOUT              = 7,
    SC_STATUS_ERR_CANCELLED            = 8,

    /* I/O errors (100–199) */
    SC_STATUS_ERR_IO                   = 100,
    SC_STATUS_ERR_IO_EOF               = 101,
    SC_STATUS_ERR_IO_NOT_FOUND         = 102,
    SC_STATUS_ERR_IO_PERMISSION        = 103,

    /* Network errors (200–299) */
    SC_STATUS_ERR_NET                  = 200,
    SC_STATUS_ERR_NET_UNREACHABLE      = 201,
    SC_STATUS_ERR_NET_CONNECTION_RESET = 202,
    SC_STATUS_ERR_NET_DNS              = 203,

    /* Validation errors (300–399) */
    SC_STATUS_ERR_VALIDATION           = 300,
    SC_STATUS_ERR_VALIDATION_SCHEMA    = 301,
    SC_STATUS_ERR_VALIDATION_FORMAT    = 302,

    /* Service runtime errors (400–499) */
    SC_STATUS_ERR_SERVICE_UNAVAILABLE  = 400,
    SC_STATUS_ERR_SERVICE_OVERLOADED   = 401,
    SC_STATUS_ERR_SERVICE_RATE_LIMIT   = 402
} sc_status_t;

/* -------------------------------------------------------------------------- */
/*                       Small helper to stringify codes.                     */
/* -------------------------------------------------------------------------- */
SC_FORCE_INLINE const char *sc_status_to_string(sc_status_t status)
{
    switch (status) {
    case SC_STATUS_OK:                         return "OK";
    case SC_STATUS_ERR_UNKNOWN:                return "Unknown error";
    case SC_STATUS_ERR_INVALID_ARGUMENT:       return "Invalid argument";
    case SC_STATUS_ERR_OUT_OF_RANGE:           return "Out of range";
    case SC_STATUS_ERR_NULL_POINTER:           return "Null pointer";
    case SC_STATUS_ERR_ALLOCATION_FAILED:      return "Allocation failed";
    case SC_STATUS_ERR_NOT_IMPLEMENTED:        return "Not implemented";
    case SC_STATUS_ERR_TIMEOUT:                return "Timeout";
    case SC_STATUS_ERR_CANCELLED:              return "Cancelled";

    case SC_STATUS_ERR_IO:                     return "I/O error";
    case SC_STATUS_ERR_IO_EOF:                 return "End of file";
    case SC_STATUS_ERR_IO_NOT_FOUND:           return "File not found";
    case SC_STATUS_ERR_IO_PERMISSION:          return "Permission denied";

    case SC_STATUS_ERR_NET:                    return "Network error";
    case SC_STATUS_ERR_NET_UNREACHABLE:        return "Network unreachable";
    case SC_STATUS_ERR_NET_CONNECTION_RESET:   return "Connection reset";
    case SC_STATUS_ERR_NET_DNS:                return "DNS error";

    case SC_STATUS_ERR_VALIDATION:             return "Validation error";
    case SC_STATUS_ERR_VALIDATION_SCHEMA:      return "Schema validation error";
    case SC_STATUS_ERR_VALIDATION_FORMAT:      return "Format validation error";

    case SC_STATUS_ERR_SERVICE_UNAVAILABLE:    return "Service unavailable";
    case SC_STATUS_ERR_SERVICE_OVERLOADED:     return "Service overloaded";
    case SC_STATUS_ERR_SERVICE_RATE_LIMIT:     return "Rate limit exceeded";

    default:                                   return "Unrecognised status code";
    }
}

/* Convenience macros to streamline defensive programming patterns. */
#define SC_RETURN_IF_ERROR(expr)                    \
    do {                                            \
        sc_status_t _sc_ret = (expr);               \
        if (SC_UNLIKELY(_sc_ret != SC_STATUS_OK)) { \
            return _sc_ret;                         \
        }                                           \
    } while (0)

#define SC_RETURN_IF_NULL(ptr)                      \
    do {                                            \
        if (SC_UNLIKELY((ptr) == NULL)) {           \
            return SC_STATUS_ERR_NULL_POINTER;      \
        }                                           \
    } while (0)

/* ───────────────────────────────────────────────────────────────  Strings ── */
/*
 *  Immutable, non-owning slice of a C-string.  Used throughout the codebase to
 *  avoid accidental copies and to cleanly transport UTF-8 payloads.
 */
typedef struct sc_str_view_s {
    const char *data;
    size_t      len;
} sc_str_view_t;

/* Quickly construct from a C string literal (compile-time length deduction). */
#define SC_STR_LIT(lit) ((sc_str_view_t){ (lit), sizeof(lit) - 1 })

/* ───────────────────────────────────────────────────────────────  UUIDs ──── */
typedef struct sc_uuid_s {
    uint8_t bytes[16];   /* RFC 4122 layout */
} sc_uuid_t;

/* Public UUID helpers (implemented in sc_types.c) */
SC_API sc_uuid_t     sc_uuid_generate(void);                    /* v4 random */
SC_API bool          sc_uuid_equal(const sc_uuid_t *a,
                                   const sc_uuid_t *b);
SC_API sc_str_view_t sc_uuid_to_str(const sc_uuid_t *uuid,
                                    char              out[37]);
/*
 *  Why 37?  UUID string form is 36 characters plus a null terminator:
 *      "123e4567-e89b-12d3-a456-426614174000"
 */

/* ───────────────────────────────────────────────────────────  Timestamps ─── */
typedef struct sc_timestamp_s {
    time_t   seconds;   /* Seconds since the Unix epoch (UTC). */
    uint32_t nanos;     /* 0-999 999 999 – extra precision.   */
} sc_timestamp_t;

SC_API sc_timestamp_t sc_timestamp_now(void);
SC_API sc_status_t    sc_timestamp_from_iso8601(sc_str_view_t iso,
                                                sc_timestamp_t *out_ts);
SC_API sc_str_view_t  sc_timestamp_to_iso8601(const sc_timestamp_t *ts,
                                              char out[32]);
/*
 *  The ISO-8601 helper produces a string in the form
 *      YYYY-MM-DDThh:mm:ss.nnnnnnnnnZ
 *  which is at most 30 bytes + terminator => buffer[32] is safe.
 */

/* ──────────────────────────────────────────────────────  Byte-order glue ── */
#if defined(__APPLE__)
#  include <libkern/OSByteOrder.h>
#  define sc_htonll(x) OSSwapHostToBigInt64(x)
#  define sc_ntohll(x) OSSwapBigToHostInt64(x)
#elif defined(_WIN32)
#  include <winsock2.h>
#  define sc_htonll(x) htonll(x)
#  define sc_ntohll(x) ntohll(x)
#else
#  include <arpa/inet.h>
SC_FORCE_INLINE uint64_t sc_htonll(uint64_t v)
{
#  if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    return ((uint64_t)htonl((uint32_t)(v >> 32))) |
           ((uint64_t)htonl((uint32_t) v        ) << 32);
#  else
    return v;
#  endif
}
SC_FORCE_INLINE uint64_t sc_ntohll(uint64_t v)
{
#  if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    return ((uint64_t)ntohl((uint32_t)(v >> 32))) |
           ((uint64_t)ntohl((uint32_t) v        ) << 32);
#  else
    return v;
#  endif
}
#endif /* Byte-order helpers */

/* ─────────────────────────────────────────────────────────  Miscellanea ── */
#ifndef SC_SIZE_MAX
#  define SC_SIZE_MAX ((size_t)-1)
#endif

/* ───────────────────────────────────────────────────────────────  Footer ── */
#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* SC_TYPES_H_ */
