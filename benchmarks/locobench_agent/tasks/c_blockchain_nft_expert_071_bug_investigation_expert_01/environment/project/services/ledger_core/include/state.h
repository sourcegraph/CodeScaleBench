/*
 * HoloCanvas – LedgerCore
 * state.h
 *
 * A small, yet production-grade state-machine implementation that drives an
 * Artifact’s life-cycle inside LedgerCore.  The module is self-contained: simply
 * include this header in exactly ONE compilation unit with
 *
 *      #define HOLOCANVAS_STATE_IMPLEMENTATION
 *      #include "state.h"
 *
 * to emit the implementation, or just `#include "state.h"` to consume the API.
 *
 * Thread-safety: all mutating operations are guarded by a pthread read/write
 * lock, making the state-machine safe for concurrent reads and single-writer
 * updates.
 */

#ifndef HOLOCANVAS_LEDGERCORE_STATE_H
#define HOLOCANVAS_LEDGERCORE_STATE_H

/* ────────────────────────────────────────────────────────────────────────── */
/* Standard deps                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants / Types                                                        */
/* ────────────────────────────────────────────────────────────────────────── */

/* Possible phases in an artwork’s life-cycle */
typedef enum {
    ARTIFACT_STATE_DRAFT = 0,
    ARTIFACT_STATE_CURATED,
    ARTIFACT_STATE_AUCTION,
    ARTIFACT_STATE_FRACTIONALIZED,
    ARTIFACT_STATE_STAKED,
    ARTIFACT_STATE_RETIRED,
    ARTIFACT_STATE__COUNT      /* Keep last – number of valid states */
} artifact_state_t;

/* Micro-events that can drive transitions (for observability only) */
typedef enum {
    STATE_EVT_BID = 0,
    STATE_EVT_GOVERNANCE_VOTE,
    STATE_EVT_ORACLE_FEED,
    STATE_EVT_TIMEOUT,
    STATE_EVT_MANUAL,
    STATE_EVT__COUNT
} state_event_t;

/* Error codes returned by the public API */
typedef enum {
    STATE_OK = 0,
    STATE_ERR_INVALID_ARG         = -1,
    STATE_ERR_INVALID_TRANSITION  = -2,
    STATE_ERR_GUARD_REJECTED      = -3,
    STATE_ERR_LOCK                = -4,
    STATE_ERR_CAPACITY            = -5
} state_rc_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Transition context                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * Opaque metadata accompanying a transition attempt.  The pointer-based payload
 * is owned by the caller and must outlive the transition call.
 */
typedef struct {
    uint64_t       artifact_id;     /* Unique on-chain id */
    state_event_t  event;           /* What triggered the attempt?          */
    const void    *payload;         /* Optional – may be NULL               */
    size_t         payload_len;     /* Zero if no payload                   */
    uint64_t       ts_unix_ms;      /* Millisecond precision timestamp      */
} state_transition_ctx_t;

/* Guard callback – return true to allow the transition, false to veto */
typedef bool (*state_guard_fn)(const state_transition_ctx_t *ctx);

/* Observer callback – notified after a successful state transition          */
typedef void (*state_listener_fn)(artifact_state_t from,
                                  artifact_state_t to,
                                  const state_transition_ctx_t *ctx,
                                  void *user_data);

/* ────────────────────────────────────────────────────────────────────────── */
/* Transition & machine struct                                              */
/* ────────────────────────────────────────────────────────────────────────── */
typedef struct {
    artifact_state_t from;
    artifact_state_t to;
    state_guard_fn   guard;   /* Optional – may be NULL (always allowed)    */
} state_transition_t;

#define STATE_MAX_LISTENERS  8   /* Tunable – enough for most use-cases     */

/*
 * The state-machine itself.  Treat as opaque and only interact through the API
 */
typedef struct {
    artifact_state_t  current;
    const state_transition_t *transitions;
    size_t            transition_count;

    /* Listener registry */
    struct {
        state_listener_fn cb;
        void             *userdata;
    } listeners[STATE_MAX_LISTENERS];
    size_t listener_count;

    /* Concurrency control */
    pthread_rwlock_t lock;
} state_machine_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * Initialise a state-machine instance.
 *
 * transitions/transition_count define the legal edges of the graph.
 */
state_rc_t
state_machine_init(state_machine_t             *sm,
                   artifact_state_t             initial,
                   const state_transition_t    *transitions,
                   size_t                       transition_count);

/* Free resources – must be called exactly once per initialized machine */
void
state_machine_destroy(state_machine_t *sm);

/* Query the current state (thread-safe, lockless for readers)             */
artifact_state_t
state_machine_get(const state_machine_t *sm);

/*
 * Attempt a transition to `desired`.  Returns STATE_OK iff successful.
 * On success, registered listeners are notified (synchronously, under lock).
 */
state_rc_t
state_machine_transition(state_machine_t          *sm,
                         artifact_state_t          desired,
                         const state_transition_ctx_t *ctx);

/* Listener management */
state_rc_t
state_machine_add_listener(state_machine_t *sm,
                           state_listener_fn cb,
                           void *userdata);

state_rc_t
state_machine_remove_listener(state_machine_t *sm,
                              state_listener_fn cb,
                              void *userdata);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
#ifdef HOLOCANVAS_STATE_IMPLEMENTATION
#include <string.h> /* memset */

static inline state_rc_t
state__rwlock_init(pthread_rwlock_t *rw)
{
    if (pthread_rwlock_init(rw, NULL) != 0) {
        return STATE_ERR_LOCK;
    }
    return STATE_OK;
}

static inline void
state__rwlock_rdlock(const pthread_rwlock_t *rw)
{
    /* Ignore return value – not much we can do on failure except abort */
    (void)pthread_rwlock_rdlock((pthread_rwlock_t*)rw);
}

static inline void
state__rwlock_wrlock(const pthread_rwlock_t *rw)
{
    (void)pthread_rwlock_wrlock((pthread_rwlock_t*)rw);
}

static inline void
state__rwlock_unlock(const pthread_rwlock_t *rw)
{
    (void)pthread_rwlock_unlock((pthread_rwlock_t*)rw);
}

/* Find a matching edge in the transition table */
static const state_transition_t *
state__lookup_edge(const state_machine_t *sm,
                   artifact_state_t from,
                   artifact_state_t to)
{
    for (size_t i = 0; i < sm->transition_count; ++i) {
        if (sm->transitions[i].from == from &&
            sm->transitions[i].to   == to) {
            return &sm->transitions[i];
        }
    }
    return NULL;
}

/* ───────────────────────────── API functions ──────────────────────────── */

state_rc_t
state_machine_init(state_machine_t             *sm,
                   artifact_state_t             initial,
                   const state_transition_t    *transitions,
                   size_t                       transition_count)
{
    if (!sm || !transitions || transition_count == 0 ||
        initial >= ARTIFACT_STATE__COUNT) {
        return STATE_ERR_INVALID_ARG;
    }

    memset(sm, 0, sizeof(*sm));
    sm->current          = initial;
    sm->transitions      = transitions;
    sm->transition_count = transition_count;

    const state_rc_t rc = state__rwlock_init(&sm->lock);
    if (rc != STATE_OK) {
        return rc;
    }
    return STATE_OK;
}

void
state_machine_destroy(state_machine_t *sm)
{
    if (!sm) return;
    pthread_rwlock_destroy(&sm->lock);
    /* nothing else to free because we don’t own the transitions table */
}

artifact_state_t
state_machine_get(const state_machine_t *sm)
{
    if (!sm) return ARTIFACT_STATE__COUNT; /* invalid sentinel */
    state__rwlock_rdlock(&sm->lock);
    const artifact_state_t s = sm->current;
    state__rwlock_unlock(&sm->lock);
    return s;
}

state_rc_t
state_machine_transition(state_machine_t          *sm,
                         artifact_state_t          desired,
                         const state_transition_ctx_t *ctx)
{
    if (!sm || desired >= ARTIFACT_STATE__COUNT) {
        return STATE_ERR_INVALID_ARG;
    }

    state__rwlock_wrlock(&sm->lock);

    const artifact_state_t from = sm->current;
    if (from == desired) {
        state__rwlock_unlock(&sm->lock);
        return STATE_OK; /* idempotent */
    }

    const state_transition_t *edge = state__lookup_edge(sm, from, desired);
    if (!edge) {
        state__rwlock_unlock(&sm->lock);
        return STATE_ERR_INVALID_TRANSITION;
    }

    /* Check guard */
    if (edge->guard && !edge->guard(ctx)) {
        state__rwlock_unlock(&sm->lock);
        return STATE_ERR_GUARD_REJECTED;
    }

    /* Perform transition */
    sm->current = desired;

    /* Notify listeners (under lock to maintain ordering) */
    for (size_t i = 0; i < sm->listener_count; ++i) {
        const state_listener_fn cb = sm->listeners[i].cb;
        if (cb) {
            cb(from, desired, ctx, sm->listeners[i].userdata);
        }
    }

    state__rwlock_unlock(&sm->lock);
    return STATE_OK;
}

state_rc_t
state_machine_add_listener(state_machine_t *sm,
                           state_listener_fn cb,
                           void *userdata)
{
    if (!sm || !cb) {
        return STATE_ERR_INVALID_ARG;
    }

    state__rwlock_wrlock(&sm->lock);

    if (sm->listener_count >= STATE_MAX_LISTENERS) {
        state__rwlock_unlock(&sm->lock);
        return STATE_ERR_CAPACITY;
    }

    sm->listeners[sm->listener_count].cb       = cb;
    sm->listeners[sm->listener_count].userdata = userdata;
    sm->listener_count++;

    state__rwlock_unlock(&sm->lock);
    return STATE_OK;
}

state_rc_t
state_machine_remove_listener(state_machine_t *sm,
                              state_listener_fn cb,
                              void *userdata)
{
    if (!sm || !cb) return STATE_ERR_INVALID_ARG;

    state__rwlock_wrlock(&sm->lock);

    size_t idx = SIZE_MAX;
    for (size_t i = 0; i < sm->listener_count; ++i) {
        if (sm->listeners[i].cb == cb &&
            sm->listeners[i].userdata == userdata) {
            idx = i;
            break;
        }
    }
    if (idx == SIZE_MAX) {
        state__rwlock_unlock(&sm->lock);
        return STATE_ERR_INVALID_ARG;
    }

    /* Compact array */
    for (size_t i = idx; i < sm->listener_count - 1; ++i) {
        sm->listeners[i] = sm->listeners[i + 1];
    }
    --sm->listener_count;

    state__rwlock_unlock(&sm->lock);
    return STATE_OK;
}

#endif /* HOLOCANVAS_STATE_IMPLEMENTATION */
#endif /* HOLOCANVAS_LEDGERCORE_STATE_H */
