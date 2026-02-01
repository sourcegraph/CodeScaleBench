/*
 * SynestheticCanvas API Gateway – Authentication Middleware
 * --------------------------------------------------------
 *
 *  File:        middleware/auth.h
 *  License:     MIT (see root LICENSE file)
 *
 *  Description:
 *      Public interface for SynestheticCanvas’ authentication middleware.
 *      The middleware is responsible for extracting and validating
 *      Authorization headers (currently Bearer/JWT & Basic), enforcing
 *      role/permission scopes, and providing caller-friendly abstractions
 *      around token claims.
 *
 *      The implementation lives in middleware/auth.c – only high-level,
 *      zero-dependency* declarations remain here so that every other
 *      component (GraphQL resolvers, REST handlers, CLI tools, etc.)
 *      can consume the API without pulling the entire JWT stack.
 *
 *      *A tiny <stdarg.h>-based logger callback is optional.
 */

#ifndef SC_API_GATEWAY_MIDDLEWARE_AUTH_H
#define SC_API_GATEWAY_MIDDLEWARE_AUTH_H

/* ------------------------------------------------------------------------- */
/*  Standard C Library Headers                                               */
/* ------------------------------------------------------------------------- */
#include <stddef.h>     /* size_t               */
#include <stdint.h>     /* uint64_t             */
#include <stdbool.h>    /* bool                 */

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*  Compile-time Configuration                                               */
/* ------------------------------------------------------------------------- */

/* Maximum lengths that affect static/stack allocations only; overriding
 * these does NOT impact the on-wire format or token semantics.              */
#ifndef SC_AUTH_MAX_TOKEN_SIZE
#   define SC_AUTH_MAX_TOKEN_SIZE     4096    /* bytes (incl. terminating NUL) */
#endif

#ifndef SC_AUTH_MAX_SUBJECT_SIZE
#   define SC_AUTH_MAX_SUBJECT_SIZE    256    /* bytes (incl. terminating NUL) */
#endif

/* When defined, additional debug information such as the failing line number
 * is included in status strings (at the cost of flash/ELF size).            */
/* #define SC_AUTH_VERBOSE_DIAGNOSTICS */

/* ------------------------------------------------------------------------- */
/*  Status & Error Codes                                                     */
/* ------------------------------------------------------------------------- */

/**
 * sc_auth_status_t – Result/diagnostic codes returned by almost all API calls.
 *
 * Values below zero (-1 ..) are reserved for future use (e.g. POSIX errno
 * passthrough). 0 denotes success. All positive numbers are middleware-specific
 * failures.
 */
typedef enum
{
    SC_AUTH_OK = 0,                  /* Success                                       */
    SC_AUTH_ERR_INVALID_ARGUMENT,    /* NULL/0 argument or otherwise nonsensical call */
    SC_AUTH_ERR_MISSING_HEADER,      /* No Authorization header present               */
    SC_AUTH_ERR_MALFORMED_HEADER,    /* Header present but malformed                  */
    SC_AUTH_ERR_UNSUPPORTED_SCHEME,  /* e.g. Digest yet we only handle Bearer/Basic   */
    SC_AUTH_ERR_TOKEN_EXPIRED,       /* `exp` claim in the past                       */
    SC_AUTH_ERR_TOKEN_REVOKED,       /* Token present on deny-list/CRL                */
    SC_AUTH_ERR_INVALID_SIGNATURE,   /* JWT signature mismatch                        */
    SC_AUTH_ERR_INSUFFICIENT_SCOPE,  /* Required permission(s) missing                */
    SC_AUTH_ERR_INTERNAL             /* Out-of-memory, RNG failed, etc.               */
} sc_auth_status_t;

/* ------------------------------------------------------------------------- */
/*  Authentication Schemes                                                   */
/* ------------------------------------------------------------------------- */

/** Enumeration of currently supported Authorization schemes. */
typedef enum
{
    SC_AUTH_SCHEME_NONE   = 0,
    SC_AUTH_SCHEME_BEARER = 1,  /* RFC 6750 (OAuth 2.0 Bearer Token Usage)  */
    SC_AUTH_SCHEME_BASIC  = 2   /* RFC 7617 (HTTP Basic Authentication)     */
} sc_auth_scheme_t;

/* ------------------------------------------------------------------------- */
/*  Scope / Permission Model                                                 */
/* ------------------------------------------------------------------------- */

/**
 * SynestheticCanvas uses a 64-bit bitfield for scopes so that new permissions
 * can be rolled out without DB schema changes. Keep related flags adjacent
 * so higher-level systems can mask entire “families” with a single shift.    *
 *
 * NOTE: These constants represent capabilities exposed through the gateway
 * and thus evolve with the public API. Do NOT change existing numeric values
 * after they have been shipped – add only new, previously unused bits!       */
typedef uint64_t sc_auth_scope_t;

#define SC_SCOPE_READ_PALETTE       UINT64_C(1)         /* 0x0000000000000001 */
#define SC_SCOPE_WRITE_PALETTE      UINT64_C(1) << 1    /* 0x0000000000000002 */
#define SC_SCOPE_READ_TEXTURE       UINT64_C(1) << 2    /* 0x0000000000000004 */
#define SC_SCOPE_WRITE_TEXTURE      UINT64_C(1) << 3    /* 0x0000000000000008 */
#define SC_SCOPE_AUDIO_REACTIVE     UINT64_C(1) << 4    /* 0x0000000000000010 */
#define SC_SCOPE_NARRATIVE_BRANCH   UINT64_C(1) << 5    /* 0x0000000000000020 */
#define SC_SCOPE_ADMIN              UINT64_C(1) << 60   /* 0x1000000000000000 */

/* Scope utility – returns true if `have` satisfies ALL `required` bits.      */
static inline bool
sc_auth_scope_has(sc_auth_scope_t have, sc_auth_scope_t required)
{
    return (have & required) == required;
}

/* ------------------------------------------------------------------------- */
/*  Token Claims                                                             */
/* ------------------------------------------------------------------------- */

/** Parsed/validated JWT claims that other modules might be interested in. */
typedef struct sc_auth_claims
{
    char             subject[SC_AUTH_MAX_SUBJECT_SIZE]; /* “sub”             */
    sc_auth_scope_t  scope;                             /* bitfield          */
    uint64_t         issued_at;                         /* “iat” Unix epoch  */
    uint64_t         expires_at;                        /* “exp” Unix epoch  */
    uint64_t         not_before;                        /* “nbf” Unix epoch  */
} sc_auth_claims_t;

/* ------------------------------------------------------------------------- */
/*  Opaque Context Forward Declarations                                      */
/* ------------------------------------------------------------------------- */

/** Opaque struct holding JWK sets, caches, and configuration. */
typedef struct sc_auth_ctx sc_auth_ctx_t;

/* ------------------------------------------------------------------------- */
/*  Callback/Hook Types                                                      */
/* ------------------------------------------------------------------------- */

/**
 * sc_auth_key_resolver_cb – User-supplied callback to resolve signing keys.
 *
 * Parameters:
 *  kid          – ‘Key ID’ header field extracted from JWT; may be NULL for
 *                 single-tenant deployments.
 *  out_key      – Buffer where the raw key (DER, PEM, or vendor-specific)
 *                 should be copied to.
 *  inout_len    – In:  size of out_key buffer.
 *                 Out: actual bytes written on success OR required size
 *                      on SC_AUTH_ERR_INVALID_ARGUMENT.
 *  user_ctx     – Opaque user data passed to sc_auth_create().
 *
 * Returns:
 *  SC_AUTH_OK on success or one of the SC_AUTH_ERR_* codes on failure.
 */
typedef sc_auth_status_t (*sc_auth_key_resolver_cb)(
        const char *kid,
        uint8_t    *out_key,
        size_t     *inout_len,
        void       *user_ctx);

/* ------------------------------------------------------------------------- */
/*  Initialization / Teardown                                                */
/* ------------------------------------------------------------------------- */

/**
 * sc_auth_options_t – Configuration blob consumed by sc_auth_create().
 *
 * Fields:
 *  issuer       – Required `iss` claim every JWT must contain (NULL to ignore).
 *  audience     – Required `aud` claim (NULL/empty to ignore).
 *  key_resolver – Callback used to fetch/rotate signing keys at runtime.
 *  key_resolver_user_ctx
 *               – Opaque pointer forwarded to key_resolver.
 *  logger       – Optional printf-like logger. Pass NULL to disable.
 */
typedef struct sc_auth_options
{
    const char                 *issuer;
    const char                 *audience;
    sc_auth_key_resolver_cb     key_resolver;
    void                       *key_resolver_user_ctx;
    void                      (*logger)(const char *fmt, ...);
} sc_auth_options_t;

/**
 * sc_auth_create – Allocate and configure a new authentication context.
 *
 * The returned pointer must eventually be released via sc_auth_destroy().
 *
 * Returns:
 *  Valid pointer on success, NULL on error (errno will be set).
 */
sc_auth_ctx_t *
sc_auth_create(const sc_auth_options_t *options);

/**
 * sc_auth_destroy – Release all resources associated with the context.
 */
void
sc_auth_destroy(sc_auth_ctx_t *ctx);

/* ------------------------------------------------------------------------- */
/*  Validation / Runtime Checks                                              */
/* ------------------------------------------------------------------------- */

/**
 * sc_auth_validate – Validate an Authorization header and extract claims.
 *
 * Parameters:
 *  ctx          – Auth context previously obtained via sc_auth_create().
 *  header_value – The raw value of the HTTP “Authorization” header
 *                 (e.g., “Bearer eyJhbGciOi…”). Must be NULL-terminated.
 *  out_claims   – Optional pointer that receives parsed claims on success.
 *                 Pass NULL if the caller is interested in the status only.
 *  out_scheme   – Optional pointer that receives the detected auth scheme.
 *
 * Returns:
 *  SC_AUTH_OK on success or one of the SC_AUTH_ERR_* codes on failure.
 */
sc_auth_status_t
sc_auth_validate(sc_auth_ctx_t        *ctx,
                 const char           *header_value,
                 sc_auth_claims_t     *out_claims,
                 sc_auth_scheme_t     *out_scheme);

/* ------------------------------------------------------------------------- */
/*  Convenience / Debug Helpers                                              */
/* ------------------------------------------------------------------------- */

/**
 * sc_auth_status_str – Convert a status code into a human-readable string.
 *
 * The returned string is a static const pointer – no need to free().
 */
const char *
sc_auth_status_str(sc_auth_status_t status);

/**
 * sc_auth_scope_to_string – Pretty-print a scope bitfield into a comma-separated
 * list of symbolic names. The caller MUST free() the returned buffer.
 *
 * Useful for tracing/logging purposes, NOT for access control checks.
 */
char *
sc_auth_scope_to_string(sc_auth_scope_t scope);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SC_API_GATEWAY_MIDDLEWARE_AUTH_H */
