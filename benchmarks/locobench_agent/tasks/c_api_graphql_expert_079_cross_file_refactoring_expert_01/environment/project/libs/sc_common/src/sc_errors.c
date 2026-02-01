/**
 * sc_errors.c
 *
 * SynestheticCanvas Common Library
 * --------------------------------
 * Centralised error-handling implementation shared by all micro-services that
 * make up the SynestheticCanvas constellation.  This compilation unit
 * provides:
 *
 *  • A stable enumeration of error codes (mirrored in sc_errors.h).
 *  • Human-readable translations for each code (thread-safe, async-signal-safe).
 *  • Helper routines / macros for propagating and logging failures.
 *  • A lightweight, per-thread error context similar to errno, but extensible
 *    and service-aware.
 *
 * Copyright 2024
 * SPDX-License-Identifier: MIT
 */

#include "sc_errors.h"        /* public interface */
#include "sc_log.h"           /* internal logging facade */
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

/* ============================================================================
 * Private constants / tables
 * ========================================================================== */

/*
 * IMPORTANT: Keep the order in sync with enum sc_error_code in sc_errors.h.
 *
 * DO NOT insert values in the middle – always append, otherwise previously
 * serialized error codes will be reinterpreted.  Mark deprecated entries but
 * keep them in place.
 */
static const char *const g_sc_error_lut[] = {
    /* 0  */ "Success",
    /* 1  */ "Unknown failure",
    /* 2  */ "Out of memory",
    /* 3  */ "Null pointer dereference",
    /* 4  */ "Invalid argument",
    /* 5  */ "Index out of range",
    /* 6  */ "Resource not found",
    /* 7  */ "Permission denied",
    /* 8  */ "Operation timed out",
    /* 9  */ "Connection failed",
    /* 10 */ "Protocol violation",
    /* 11 */ "Data corruption detected",
    /* 12 */ "Unimplemented feature",
    /* 13 */ "Unsupported media type",
    /* 14 */ "Configuration error",
    /* 15 */ "I/O failure",
    /* 16 */ "Filesystem full",
    /* 17 */ "GraphQL validation error",
    /* 18 */ "GraphQL execution error",
    /* 19 */ "REST validation error",
    /* 20 */ "Rate limit exceeded",
    /* 21 */ "Service unavailable",
    /* 22 */ "Schema version mismatch",
    /* 23 */ "Database query failed",
    /* 24 */ "Transaction aborted",
    /* 25 */ "Threading error",
    /* 26 */ "Serialization error",
    /* 27 */ "Deserialization error",
    /* 28 */ "Crypto / TLS error",
    /* 29 */ "Cancellation requested"
};

_Static_assert(SC_ERR__MAX == (sizeof g_sc_error_lut / sizeof g_sc_error_lut[0]),
               "g_sc_error_lut size must match sc_error_code enum");

/* ============================================================================
 * Per-thread errno implementation
 * ========================================================================== */

/*
 * We keep the last error in a thread-local variable to avoid function signatures
 * exploding with additional parameters.  This should NOT be used for control
 * flow.  Instead, each function should return an explicit sc_error_code and let
 * callers inspect that directly.  The TLS value is useful as a “last resort”
 * when integrating with foreign code (e.g., gRPC, pthreads) that predates our
 * conventions.
 */
static _Thread_local sc_error_code tl_last_error = SC_OK;

/* -------------------------------------------------------------------------- */
void sc_set_error(sc_error_code code)
{
    tl_last_error = code;
}
/* -------------------------------------------------------------------------- */
sc_error_code sc_get_error(void)
{
    return tl_last_error;
}
/* ============================================================================
 * Public translation helpers
 * ========================================================================== */

const char *sc_error_to_cstr(sc_error_code code)
{
    if (code < 0 || code >= SC_ERR__MAX) {
        return "Invalid error code"; /* Should never happen */
    }
    return g_sc_error_lut[code];
}

/* -------------------------------------------------------------------------- */
/*
 * A tiny, header-only logging wrapper could just format the message and forward
 * to sc_log_write().  Here we provide a convenience implementation so callers
 * can do:
 *
 *     if ((rc = sc_foo()) != SC_OK) {
 *         return sc_perror(rc, "foo failed");
 *     }
 */
sc_error_code sc_perror(sc_error_code code, const char *context)
{
    const char *msg = sc_error_to_cstr(code);

    if (context && *context) {
        sc_log_write(SC_LOG_ERROR, "[%s] %s", context, msg);
    } else {
        sc_log_write(SC_LOG_ERROR, "%s", msg);
    }

    /* stash; do this after logging—handlers may consult sc_get_error() */
    sc_set_error(code);

    return code;
}

/* ============================================================================
 * Extensibility: custom translators
 * ========================================================================== */

/*
 * Some services may want to register a domain-specific mapping (e.g., map DB
 * vendor error codes into sc_error_code + additional diagnostics).  We expose a
 * simple listener pattern: interested parties register a callback that gets
 * invoked on every sc_set_error() and can perform their own side effects
 * (telemetry, tracing, etc.).
 */

#define MAX_LISTENERS 8

typedef void (*sc_error_listener_fn)(sc_error_code code);

static sc_error_listener_fn g_listeners[MAX_LISTENERS];
static atomic_uint g_listener_count = 0;

/* -------------------------------------------------------------------------- */
bool sc_error_add_listener(sc_error_listener_fn fn)
{
    if (!fn)
        return false;

    unsigned idx = atomic_load_explicit(&g_listener_count, memory_order_relaxed);

    if (idx >= MAX_LISTENERS)
        return false;

    g_listeners[idx] = fn;
    atomic_fetch_add_explicit(&g_listener_count, 1, memory_order_release);
    return true;
}

/* -------------------------------------------------------------------------- */
void sc_error_notify(sc_error_code code)
{
    unsigned count = atomic_load_explicit(&g_listener_count, memory_order_acquire);

    for (unsigned i = 0; i < count; ++i) {
        if (g_listeners[i]) {
            g_listeners[i](code);
        }
    }
}

/* -------------------------------------------------------------------------- */
/* Override default setter to broadcast events */
void sc_set_error_broadcast(sc_error_code code)
{
    sc_set_error(code);        /* local TLS copy */
    sc_error_notify(code);     /* fan out to listeners */
}

/* ============================================================================
 * Debug utilities
 * ========================================================================== */

#ifdef SC_BUILD_DEBUG

#include <inttypes.h>
#include <stdlib.h>

void sc_error_dump(FILE *fp)
{
    if (!fp) fp = stderr;

    sc_error_code last = sc_get_error();
    fprintf(fp, "[dbg] last error = %d (%s)\n",
            last, sc_error_to_cstr(last));
}

/*
 * Compile-time check that enum and LUT stay in sync,
 *   *and* catch duplicate values.
 */
static void sc_error_compile_asserts(void)
{
    for (int i = 0; i < SC_ERR__MAX; ++i) {
        /* This branchless trick will abort at run-time if duplicates detected.
         * Not perfect, but still helps to catch copy-paste mistakes.
         */
        for (int j = i + 1; j < SC_ERR__MAX; ++j) {
            if (strcmp(g_sc_error_lut[i], g_sc_error_lut[j]) == 0) {
                fprintf(stderr,
                        "sc_errors: duplicate error string \"%s\" @ %d and %d\n",
                        g_sc_error_lut[i], i, j);
                abort();
            }
        }
    }
}
/* Run once at startup */
__attribute__((constructor))
static void sc_error_init_ctor(void)
{
    sc_error_compile_asserts();
}

#endif /* SC_BUILD_DEBUG */

/* ============================================================================
 * End of file
 * ========================================================================== */
