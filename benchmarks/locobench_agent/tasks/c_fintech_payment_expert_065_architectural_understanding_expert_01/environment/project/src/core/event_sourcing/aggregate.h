/**
 * =============================================================================
 *  EduPay Ledger Academy – Core / Event Sourcing
 * -----------------------------------------------------------------------------
 *  File:    aggregate.h
 *  Language: C (C99)
 *  Purpose: Primitive building–blocks for the Event-Sourced Aggregate-Root used
 *           across bounded contexts (Admissions, Bursar, Financial-Aid, etc.).
 *
 *  This header contains both declarations and header-inline implementations.
 *  Doing so keeps the Aggregate primitive completely framework-free and enables
 *  professors to copy a single file into assignments without chasing link-time
 *  dependencies.  The code is carefully written to compile cleanly with
 *  -Wall -Wextra -Werror on modern GCC/Clang.
 *
 *  NOTE: All symbols are prefixed with “epa_” (EduPay Aggregate) to minimise
 *  risk of collision when educators intentionally create conflicting libraries
 *  during labs on symbol-resolution and package-management.
 * =============================================================================
 */

#ifndef EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_AGGREGATE_H
#define EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_AGGREGATE_H

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard Library                                                          */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Configuration                                                             */

/* Maximum length for human-readable identifiers (UUID v4 fits comfortably). */
#ifndef EPA_AGGREGATE_ID_MAX
#   define EPA_AGGREGATE_ID_MAX  48u
#endif

/* Initial capacity for the uncommitted event buffer.  Doubles on demand.   */
#ifndef EPA_AGGREGATE_EVENT_BUF_INIT
#   define EPA_AGGREGATE_EVENT_BUF_INIT  4u
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Return Codes                                                              */

/* Success / generic errors (non-exhaustive).  Non-zero indicates failure.  */
typedef enum
{
    EPA_OK                     = 0,
    EPA_ERR_NULLPTR            = 1,
    EPA_ERR_OOM                = 2,
    EPA_ERR_ID_TOO_LONG        = 3,
    EPA_ERR_EVENT_OVERFLOW     = 4,
    EPA_ERR_VERSION_CONFLICT   = 5,
    EPA_ERR_INVALID_ARGUMENT   = 6
} epa_rc_e;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Event Envelope Structure                                                  */

/**
 * Event envelopes wrap a raw event payload with the metadata required to
 * guarantee ordering, idempotency, and traceability across micro-services.
 *
 * The payload is intentionally opaque to keep the aggregate pure.  Domain
 * modules define their own immutable event DTOs and pass them as the
 * “payload” pointer.
 */
typedef struct
{
    char            type[32];          /* ASCII event name, e.g. "PaymentDebited"      */
    uint64_t        version;           /* Version after the event is applied           */
    struct timespec timestamp;         /* High-resolution wall-clock time              */
    void           *payload;           /* Domain-specific immutable event object       */
    size_t          payload_sz;        /* Size (bytes) of the payload object           */
} epa_event_envelope_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Forward Declarations                                                      */

/* Aggregate root opaque state is domain-specific (void*).                   */
struct epa_aggregate_s;

/* Event-handler signature: mutates `state` in place. */
typedef epa_rc_e (*epa_apply_event_fn)(
        void                    *state,
        const epa_event_envelope_t *event);

/* Command-handler signature: converts command+state into new events.        */
typedef epa_rc_e (*epa_handle_cmd_fn)(
        struct epa_aggregate_s  *agg,
        const void              *command /* Domain-specific immutable DTO    */);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Aggregate Root Structure                                                  */

/**
 * The in-memory representation of an aggregate root.  Only the functions in
 * this header manipulate the internals; callers interact through the public
 * API to enforce invariants (e.g. versioning, event immutability).
 */
typedef struct epa_aggregate_s
{
    /* Identity & Versioning */
    char        id[EPA_AGGREGATE_ID_MAX]; /* Business key / UUID */
    uint64_t    version;                  /* Last committed version */

    /* Mutable State */
    void       *state;        /* Domain-specific mutable state blob        */
    size_t      state_sz;     /* Size of the state blob                    */

    /* Behaviour (Domain injects strategy functions) */
    epa_apply_event_fn  apply_event;
    epa_handle_cmd_fn   handle_command;

    /* Outbox of uncommitted events (guaranteed contiguous) */
    epa_event_envelope_t *uncommitted;      /* Dynamic array buffer   */
    size_t                uncommitted_len;  /* Number of items stored */
    size_t                uncommitted_cap;  /* Alloc ‑ may grow       */
} epa_aggregate_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public API                                                                */

/**
 * Initialise an aggregate in freshly-allocated memory.
 *
 * Domain code supplies:
 *   - id:             unique identifier (NULL-terminated ASCII)
 *   - initial_state:  pointer to caller-owned state to copy
 *   - apply_fn:       pure function that mutates state given an event
 *   - command_fn:     pure function that converts a command into events
 */
static inline
epa_rc_e epa_aggregate_init(
        epa_aggregate_t     *agg,
        const char          *id,
        const void          *initial_state,
        size_t               state_sz,
        epa_apply_event_fn   apply_fn,
        epa_handle_cmd_fn    command_fn)
{
    if (!agg || !id || !initial_state || !apply_fn)
        return EPA_ERR_NULLPTR;

    if (strlen(id) >= EPA_AGGREGATE_ID_MAX)
        return EPA_ERR_ID_TOO_LONG;

    memset(agg, 0, sizeof(*agg));
    strncpy(agg->id, id, EPA_AGGREGATE_ID_MAX - 1u);
    agg->version           = 0u;
    agg->apply_event       = apply_fn;
    agg->handle_command    = command_fn;
    agg->state_sz          = state_sz;

    /* Deep-copy initial state to ensure immutability of caller buffer. */
    agg->state = malloc(state_sz);
    if (!agg->state)
        return EPA_ERR_OOM;
    memcpy(agg->state, initial_state, state_sz);

    /* Allocate initial event buffer. */
    agg->uncommitted_cap = EPA_AGGREGATE_EVENT_BUF_INIT;
    agg->uncommitted = calloc(agg->uncommitted_cap, sizeof(epa_event_envelope_t));
    if (!agg->uncommitted)
    {
        free(agg->state);
        return EPA_ERR_OOM;
    }
    return EPA_OK;
}

/**
 * Destroy an aggregate and free heap allocations.  Safe to pass NULL.
 * NOTE: Does NOT free memory pointed to by event payloads; that responsibility
 *       belongs to the domain layer which created those DTOs.
 */
static inline
void epa_aggregate_destroy(epa_aggregate_t *agg)
{
    if (!agg) return;

    free(agg->state);
    free(agg->uncommitted);
    memset(agg, 0, sizeof(*agg));
}

/**
 * Append an event to the aggregate’s uncommitted outbox AND apply it to the
 * in-memory state.  The version will automatically increment and be reflected
 * in both the aggregate and the event envelope.
 *
 * The event payload is *deep-copied* so that callers may free their buffer
 * immediately after this function returns.
 */
static inline
epa_rc_e epa_aggregate_record_event(
        epa_aggregate_t         *agg,
        const char              *type,
        const void              *payload,
        size_t                   payload_sz)
{
    if (!agg || !type || !payload || payload_sz == 0u)
        return EPA_ERR_NULLPTR;

    /* Allocate room if necessary (simple doubling strategy). */
    if (agg->uncommitted_len == agg->uncommitted_cap)
    {
        size_t new_cap = agg->uncommitted_cap * 2u;
        if (new_cap < agg->uncommitted_cap) /* overflow check */
            return EPA_ERR_EVENT_OVERFLOW;

        epa_event_envelope_t *tmp = realloc(
            agg->uncommitted, new_cap * sizeof(epa_event_envelope_t));
        if (!tmp)
            return EPA_ERR_OOM;

        agg->uncommitted       = tmp;
        agg->uncommitted_cap   = new_cap;
    }

    /* Deep-copy the payload so that it remains immutable. */
    void *payload_copy = malloc(payload_sz);
    if (!payload_copy)
        return EPA_ERR_OOM;
    memcpy(payload_copy, payload, payload_sz);

    /* Populate envelope */
    epa_event_envelope_t *env = &agg->uncommitted[agg->uncommitted_len];
    memset(env, 0, sizeof(*env));
    strncpy(env->type, type, sizeof(env->type) - 1u);
    clock_gettime(CLOCK_REALTIME, &env->timestamp);
    env->payload     = payload_copy;
    env->payload_sz  = payload_sz;
    env->version     = ++agg->version; /* increment first */

    /* Apply to current state */
    epa_rc_e rc = agg->apply_event(agg->state, env);
    if (rc != EPA_OK)
    {
        /* Rollback the version increment and free allocations. */
        agg->version--;
        free(payload_copy);
        memset(env, 0, sizeof(*env));
        return rc;
    }

    agg->uncommitted_len++;
    return EPA_OK;
}

/**
 * Handle a domain command (e.g. “DebitStudentAccount”).  The command handler
 * is expected to populate the aggregate’s uncommitted buffer via
 * epa_aggregate_record_event() calls.
 *
 * Teachers often stub this out in unit tests by injecting a lambda that
 * deterministically emits events given known commands.
 */
static inline
epa_rc_e epa_aggregate_handle_command(
        epa_aggregate_t   *agg,
        const void        *command)
{
    if (!agg || !agg->handle_command)
        return EPA_ERR_NULLPTR;

    return agg->handle_command(agg, command);
}

/**
 * Commit all uncommitted events.  In a real system this would persist events
 * to an append-only store and publish them to brokers.  For the purposes of
 * the pure core domain we simply clear the buffer so subsequent calls to
 * `epa_aggregate_get_uncommitted()` return an empty vector.
 *
 * The caller MAY inspect the events before committing (for example to pipe
 * them into a test harness).  After commit the ownership of the event payload
 * is transferred to the caller; this function will NOT free the payloads.
 */
static inline
epa_rc_e epa_aggregate_commit(epa_aggregate_t *agg)
{
    if (!agg)
        return EPA_ERR_NULLPTR;

    /* Free envelopes but leave payload ownership to caller. */
    for (size_t i = 0u; i < agg->uncommitted_len; ++i)
        memset(&agg->uncommitted[i], 0, sizeof(epa_event_envelope_t));

    agg->uncommitted_len = 0u;
    return EPA_OK;
}

/**
 * Return a read-only pointer to uncommitted event buffer and its length.
 * Useful for projections or test assertions.  Callers must NOT mutate.
 */
static inline
const epa_event_envelope_t *epa_aggregate_get_uncommitted(
        const epa_aggregate_t *agg,
        size_t               *out_len)
{
    if (!agg) return NULL;
    if (out_len) *out_len = agg->uncommitted_len;
    return agg->uncommitted;
}

/* ----------------------------------------------------------------------------
 *  Utility: Clone aggregate state (used by CQRS read-models or snapshotting)
 * ------------------------------------------------------------------------- */
static inline
epa_rc_e epa_aggregate_clone_state(
        const epa_aggregate_t *src,
        void                  *dst,
        size_t                 dst_sz)
{
    if (!src || !dst || dst_sz != src->state_sz)
        return EPA_ERR_INVALID_ARGUMENT;

    memcpy(dst, src->state, src->state_sz);
    return EPA_OK;
}

#endif /* EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_AGGREGATE_H */
