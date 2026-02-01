/*
 * sc_errors.h
 *
 * Centralised error-handling utilities for the SynestheticCanvas micro-service
 * constellation.  All public functions are re-entrant, thread-safe and can be
 * used from C as well as C++ translation units.
 *
 * To provide the function *definitions* in a single translation unit, define
 *
 *      #define SC_ERRORS_IMPL
 *
 * **once** before including this header.  All other units should include the
 * header without defining the macro, giving them static prototypes only.
 *
 * Example:
 *      #define SC_ERRORS_IMPL
 *      #include "sc_errors.h"
 *
 *      int main(void) {
 *          ...
 *      }
 *
 * Copyright (c) 2024
 * SynestheticCanvas – All rights reserved.
 */

#ifndef SC_ERRORS_H
#define SC_ERRORS_H

/* ---------------------------------------------------------------------------
 * Public Includes
 * -------------------------------------------------------------------------*/
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h> /* asprintf, malloc/free */
#include <string.h>

#if defined(__GNUC__) || defined(__clang__)
#   define SC_ATTR_FORMAT(archetype, string_index, first_to_check) \
        __attribute__((format(archetype, string_index, first_to_check)))
#else
#   define SC_ATTR_FORMAT(archetype, string_index, first_to_check)
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------------
 * Error enumeration
 * -------------------------------------------------------------------------*/
typedef enum {
    SC_OK = 0,                /* Generic success */

    SC_ERR_UNKNOWN              = -1,

    /* 1xxx – Parameter & validation errors */
    SC_ERR_INVALID_ARGUMENT     = -1000,
    SC_ERR_OUT_OF_RANGE,
    SC_ERR_NULL_POINTER,
    SC_ERR_UNSUPPORTED,

    /* 2xxx – I/O & resource errors */
    SC_ERR_IO                   = -2000,
    SC_ERR_EOF,
    SC_ERR_TIMEOUT,
    SC_ERR_FILE_NOT_FOUND,

    /* 3xxx – Network / protocol errors */
    SC_ERR_NET                  = -3000,
    SC_ERR_DISCONNECTED,
    SC_ERR_PROTOCOL,
    SC_ERR_BAD_SCHEMA,
    SC_ERR_HTTP_STATUS,            /* HTTP status stored in `.sys_err` */

    /* 4xxx – Authentication / authorisation / rate limiting */
    SC_ERR_UNAUTHENTICATED      = -4000,
    SC_ERR_UNAUTHORIZED,
    SC_ERR_RATE_LIMITED,

    /* 5xxx – Repository / persistence */
    SC_ERR_DATA_INTEGRITY       = -5000,
    SC_ERR_DATA_NOT_FOUND,
    SC_ERR_CONFLICT,

    /* 6xxx – GraphQL specifics */
    SC_ERR_GQL_PARSE            = -6000,
    SC_ERR_GQL_VALIDATE,
    SC_ERR_GQL_EXECUTE,

    /* 7xxx – System */
    SC_ERR_NO_MEMORY            = -7000,
    SC_ERR_NOT_IMPLEMENTED

} sc_err_e;

/* ---------------------------------------------------------------------------
 * Structured error object
 * -------------------------------------------------------------------------*/
typedef struct sc_error {
    sc_err_e     code;     /* High level code                            */
    int          sys_err;  /* Underlying errno / subsystem code          */
    const char  *msg;      /* Dynamically allocated, human-readable text */
    const char  *file;     /* Source file where error was raised         */
    int          line;     /* Line in source file                        */
} sc_error_t;

#define SC_ERROR_INIT { .code = SC_OK, .sys_err = 0, .msg = NULL, .file = NULL, .line = 0 }

/* ---------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------*/

/* Return a short, constant, english string describing the error code.        */
const char *sc_err_str(sc_err_e code);

/* Populate a provided sc_error_t instance                                    */
void sc_error_set(sc_error_t *dst,
                  sc_err_e     code,
                  int          sys_err,
                  const char  *msg,
                  const char  *file,
                  int          line);

/* Convenience helper: prints a diagnostic representation to FILE*            */
void sc_error_print(const sc_error_t *err,
                    const char       *prefix,
                    FILE             *stream);

/* Map internal error codes to outbound HTTP status codes.                    */
int  sc_err_to_http(sc_err_e code);

/* ---------------------------------------------------------------------------
 * Helper macros
 * -------------------------------------------------------------------------*/

/*
 * SC_RAISE
 * Populate an sc_error_t with contextual information.  The format specifier
 * and following variadic arguments are *optional*.  If no format string is
 * required, pass NULL.
 */
#define SC_RAISE(err_ptr, sc_code, sys, fmt, ...)                                 \
    do {                                                                          \
        if ((err_ptr) != NULL) {                                                  \
            char *_sc_msg_buf = NULL;                                             \
            if ((fmt) != NULL) {                                                  \
                /* GNU asprintf allocates; caller must free() later              */\
                (void)asprintf(&_sc_msg_buf, fmt, ##__VA_ARGS__);                 \
            }                                                                     \
            sc_error_set((err_ptr), (sc_code), (sys),                             \
                         _sc_msg_buf, __FILE__, __LINE__);                        \
        }                                                                         \
    } while (0)

/*
 * SC_TRY
 * Execute a function returning sc_err_e, propagate on failure while populating
 * the error object with contextual meta-information.
 */
#define SC_TRY(call, err_ptr)                         \
    do {                                              \
        sc_err_e _sc_rc = (call);                     \
        if (_sc_rc != SC_OK) {                        \
            SC_RAISE(err_ptr, _sc_rc, 0, NULL);       \
            return _sc_rc;                            \
        }                                             \
    } while (0)

/*
 * Convenience shortcut: Free the message buffer contained in an sc_error_t,
 * if present, and reset the struct to SC_ERROR_INIT.
 */
static inline void sc_error_reset(sc_error_t *e)
{
    if (e == NULL) {
        return;
    }
    if (e->msg != NULL) {
        free((void *)e->msg);
    }
    *e = (sc_error_t)SC_ERROR_INIT;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ---------------------------------------------------------------------------
 * Implementation
 * -------------------------------------------------------------------------*/
#ifdef SC_ERRORS_IMPL

static const struct {
    sc_err_e     code;
    const char  *str;
} _sc_err_lut[] = {
    { SC_OK,                   "success" },
    { SC_ERR_UNKNOWN,          "unknown error" },

    { SC_ERR_INVALID_ARGUMENT, "invalid argument" },
    { SC_ERR_OUT_OF_RANGE,     "value out of range" },
    { SC_ERR_NULL_POINTER,     "null pointer dereference" },
    { SC_ERR_UNSUPPORTED,      "operation unsupported" },

    { SC_ERR_IO,              "I/O error" },
    { SC_ERR_EOF,             "end of file" },
    { SC_ERR_TIMEOUT,         "operation timed out" },
    { SC_ERR_FILE_NOT_FOUND,  "file not found" },

    { SC_ERR_NET,             "network error" },
    { SC_ERR_DISCONNECTED,    "remote disconnected" },
    { SC_ERR_PROTOCOL,        "protocol violation" },
    { SC_ERR_BAD_SCHEMA,      "schema mismatch" },
    { SC_ERR_HTTP_STATUS,     "HTTP error status" },

    { SC_ERR_UNAUTHENTICATED, "unauthenticated" },
    { SC_ERR_UNAUTHORIZED,    "unauthorized" },
    { SC_ERR_RATE_LIMITED,    "rate limited" },

    { SC_ERR_DATA_INTEGRITY,  "data integrity error" },
    { SC_ERR_DATA_NOT_FOUND,  "data not found" },
    { SC_ERR_CONFLICT,        "conflict" },

    { SC_ERR_GQL_PARSE,       "GraphQL parse error" },
    { SC_ERR_GQL_VALIDATE,    "GraphQL validation error" },
    { SC_ERR_GQL_EXECUTE,     "GraphQL execution error" },

    { SC_ERR_NO_MEMORY,       "out of memory" },
    { SC_ERR_NOT_IMPLEMENTED, "not implemented" }
};

const char *sc_err_str(sc_err_e code)
{
    size_t lut_len = sizeof(_sc_err_lut) / sizeof(_sc_err_lut[0]);
    for (size_t i = 0; i < lut_len; ++i) {
        if (_sc_err_lut[i].code == code) {
            return _sc_err_lut[i].str;
        }
    }
    return "unrecognised error";
}

void sc_error_set(sc_error_t *dst,
                  sc_err_e     code,
                  int          sys_err,
                  const char  *msg,
                  const char  *file,
                  int          line)
{
    if (dst == NULL) {
        return;
    }

    /* Free existing message buffer if necessary */
    if (dst->msg != NULL && dst->msg != msg) {
        free((void *)dst->msg);
    }

    dst->code    = code;
    dst->sys_err = sys_err;
    dst->msg     = msg;
    dst->file    = file;
    dst->line    = line;
}

void sc_error_print(const sc_error_t *err,
                    const char       *prefix,
                    FILE             *stream)
{
    if (err == NULL) {
        return;
    }

    if (stream == NULL) {
        stream = stderr;
    }

    if (prefix != NULL) {
        fprintf(stream, "%s: ", prefix);
    }

    const char *code_str = sc_err_str(err->code);
    fprintf(stream, "%s", code_str);

    if (err->msg != NULL) {
        fprintf(stream, ": %s", err->msg);
    }

    if (err->sys_err != 0) {
        fprintf(stream, " (sys=%d:%s)", err->sys_err, strerror(err->sys_err));
    }

    if (err->file != NULL) {
        fprintf(stream, " [%s:%d]", err->file, err->line);
    }

    fputc('\n', stream);
}

int sc_err_to_http(sc_err_e code)
{
    switch (code) {
        case SC_OK:                       return 200;

        /* client errors (4xx) */
        case SC_ERR_INVALID_ARGUMENT:
        case SC_ERR_OUT_OF_RANGE:
        case SC_ERR_NULL_POINTER:
        case SC_ERR_UNSUPPORTED:
        case SC_ERR_BAD_SCHEMA:
        case SC_ERR_GQL_PARSE:
        case SC_ERR_GQL_VALIDATE:
            return 400;  /* Bad Request */

        case SC_ERR_UNAUTHENTICATED:      return 401;  /* Unauthorized */
        case SC_ERR_UNAUTHORIZED:         return 403;  /* Forbidden */
        case SC_ERR_DATA_NOT_FOUND:
        case SC_ERR_FILE_NOT_FOUND:       return 404;  /* Not Found */
        case SC_ERR_RATE_LIMITED:         return 429;  /* Too Many Requests */

        /* conflict */
        case SC_ERR_CONFLICT:             return 409;  /* Conflict */

        /* Server errors (5xx) */
        case SC_ERR_IO:
        case SC_ERR_EOF:
        case SC_ERR_TIMEOUT:
        case SC_ERR_NET:
        case SC_ERR_DISCONNECTED:
        case SC_ERR_PROTOCOL:
        case SC_ERR_DATA_INTEGRITY:
        case SC_ERR_GQL_EXECUTE:
        case SC_ERR_NO_MEMORY:
        case SC_ERR_NOT_IMPLEMENTED:
        case SC_ERR_UNKNOWN:
        default:
            return 500;  /* Internal Server Error */
    }
}

#endif /* SC_ERRORS_IMPL */
#endif /* SC_ERRORS_H */
