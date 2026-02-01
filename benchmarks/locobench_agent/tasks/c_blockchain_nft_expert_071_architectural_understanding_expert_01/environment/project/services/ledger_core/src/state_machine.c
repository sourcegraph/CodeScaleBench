/*
 * HoloCanvas – LedgerCore – State Machine
 * ---------------------------------------
 * Production–quality C implementation of the Artifact life-cycle finite-state
 * machine used by the LedgerCore micro-service.
 *
 * This file is intentionally self-contained; public types may be extracted
 * into a dedicated header if required by other translation units.
 *
 * (c) 2024 HoloCanvas Contributors – MIT License
 */

#define _POSIX_C_SOURCE 200809L /* for clock_gettime */
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>

/* -------------------------------------------------------------------------- */
/*                            Public-facing API                               */
/* -------------------------------------------------------------------------- */

/* Error codes returned by the state-machine public functions. */
typedef enum {
    SM_OK = 0,
    SM_ERR_INVALID_ARG      = -1,
    SM_ERR_INVALID_STATE    = -2,
    SM_ERR_INVALID_TRANS    = -3,
    SM_ERR_LOCK_FAILED      = -4,
    SM_ERR_OUT_OF_MEMORY    = -5,
    SM_ERR_INTERNAL         = -6
} sm_error_t;

/* The canonical Artifact life-cycle states. */
typedef enum {
    ART_STATE_DRAFT = 0,
    ART_STATE_CURATED,
    ART_STATE_AUCTION,
    ART_STATE_FRACTIONALIZED,
    ART_STATE_STAKED,
    ART_STATE_RETIRED,

    ART_STATE_MAX
} art_state_t;

/* Forward declaration so that clients can maintain opaque handles. */
typedef struct artifact_sm artifact_sm_t;

/* Create / Destroy */
sm_error_t sm_create(uint64_t artifact_id,
                     art_state_t initial_state,
                     artifact_sm_t **out_handle);
void       sm_destroy(artifact_sm_t *handle);

/* Query & Mutation */
sm_error_t sm_get_state(artifact_sm_t *handle, art_state_t *out_state);
sm_error_t sm_transition(artifact_sm_t *handle,
                         art_state_t    target_state,
                         const char    *actor /* e.g. wallet addr */);

/* Introspection helpers */
const char *sm_state_to_str(art_state_t state);

/* -------------------------------------------------------------------------- */
/*                          Private implementation                            */
/* -------------------------------------------------------------------------- */

/* Utility: timespec (nanoseconds since boot) */
static inline uint64_t
epoch_millis(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + (ts.tv_nsec / 1000000ULL);
}

/* Transition table: allowed[next][current] = true if current -> next */
static const bool g_allowed_transitions[ART_STATE_MAX][ART_STATE_MAX] = {
    /*                 FROM ➜   DRAFT CURATED AUCTION FRACT  STAKED RETIRED */
    /* TO = DRAFT */        {  true,  false,  false,  false, false, false },
    /* CURATED */           {  true,  true,   false,  false, false, false },
    /* AUCTION */           { false,  true,   true,   false, false, false },
    /* FRACTIONALIZED */    { false, false,   true,   true,  true,  false },
    /* STAKED */            { false, false,  false,   true,  true,  false },
    /* RETIRED */           {  true,  true,   true,   true,  true,  true  }
};

struct artifact_sm {
    uint64_t     id;
    art_state_t  state;
    uint64_t     last_updated_ms;
    pthread_mutex_t mtx;
};

/* ----------------------------- Logging helpers --------------------------- */

static void
log_event(int priority, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsyslog(priority, fmt, ap);
    va_end(ap);
}

/* Stub out actual event-bus publication with a log for now. */
static void
publish_state_change(uint64_t    artifact_id,
                     art_state_t from,
                     art_state_t to,
                     const char *actor)
{
    log_event(LOG_INFO,
              "[SM] Artifact %" PRIu64 " %s -> %s by %s",
              artifact_id,
              sm_state_to_str(from),
              sm_state_to_str(to),
              actor ? actor : "system");
}

/* ------------------------------- API ------------------------------------- */

const char *
sm_state_to_str(art_state_t state)
{
    static const char *kNames[ART_STATE_MAX] = {
        [ART_STATE_DRAFT]         = "DRAFT",
        [ART_STATE_CURATED]       = "CURATED",
        [ART_STATE_AUCTION]       = "AUCTION",
        [ART_STATE_FRACTIONALIZED]= "FRACTIONALIZED",
        [ART_STATE_STAKED]        = "STAKED",
        [ART_STATE_RETIRED]       = "RETIRED"
    };
    if (state >= ART_STATE_MAX) { return "UNKNOWN"; }
    return kNames[state];
}

sm_error_t
sm_create(uint64_t artifact_id,
          art_state_t initial_state,
          artifact_sm_t **out_handle)
{
    if (!out_handle) { return SM_ERR_INVALID_ARG; }
    if (initial_state >= ART_STATE_MAX) { return SM_ERR_INVALID_STATE; }

    artifact_sm_t *sm = calloc(1, sizeof(*sm));
    if (!sm) { return SM_ERR_OUT_OF_MEMORY; }

    sm->id              = artifact_id;
    sm->state           = initial_state;
    sm->last_updated_ms = epoch_millis();

    if (pthread_mutex_init(&sm->mtx, NULL) != 0) {
        free(sm);
        return SM_ERR_INTERNAL;
    }

    *out_handle = sm;
    log_event(LOG_INFO,
              "[SM] Created state-machine for Artifact %" PRIu64 " (%s)",
              artifact_id, sm_state_to_str(initial_state));
    return SM_OK;
}

void
sm_destroy(artifact_sm_t *handle)
{
    if (!handle) { return; }
    pthread_mutex_destroy(&handle->mtx);
    memset(handle, 0, sizeof(*handle));
    free(handle);
}

sm_error_t
sm_get_state(artifact_sm_t *handle, art_state_t *out_state)
{
    if (!handle || !out_state) { return SM_ERR_INVALID_ARG; }
    if (pthread_mutex_lock(&handle->mtx) != 0) { return SM_ERR_LOCK_FAILED; }
    *out_state = handle->state;
    pthread_mutex_unlock(&handle->mtx);
    return SM_OK;
}

sm_error_t
sm_transition(artifact_sm_t *handle,
              art_state_t    target_state,
              const char    *actor)
{
    if (!handle) { return SM_ERR_INVALID_ARG; }
    if (target_state >= ART_STATE_MAX) { return SM_ERR_INVALID_STATE; }

    if (pthread_mutex_lock(&handle->mtx) != 0) { return SM_ERR_LOCK_FAILED; }

    art_state_t current = handle->state;

    /* Validate transition */
    if (!g_allowed_transitions[target_state][current]) {
        pthread_mutex_unlock(&handle->mtx);
        log_event(LOG_WARNING,
                  "[SM] Invalid transition: %s -> %s (Artifact %" PRIu64 ")",
                  sm_state_to_str(current),
                  sm_state_to_str(target_state),
                  handle->id);
        return SM_ERR_INVALID_TRANS;
    }

    /* Apply transition */
    handle->state           = target_state;
    handle->last_updated_ms = epoch_millis();

    pthread_mutex_unlock(&handle->mtx);

    /* Notify observers / event bus */
    publish_state_change(handle->id, current, target_state, actor);

    return SM_OK;
}

/* -------------------------------------------------------------------------- */
/*                           Unit-Test (optional)                             */
/* -------------------------------------------------------------------------- */
#ifdef STATE_MACHINE_TEST
static void
expect(int line, sm_error_t rc, sm_error_t want)
{
    if (rc != want) {
        fprintf(stderr, "Line %d: expected %d got %d\n", line, want, rc);
        exit(1);
    }
}

int main(void)
{
    openlog("ledger_core_state_machine", LOG_PID | LOG_CONS, LOG_USER);

    artifact_sm_t *sm;
    expect(__LINE__, sm_create(42, ART_STATE_DRAFT, &sm), SM_OK);

    expect(__LINE__, sm_transition(sm, ART_STATE_CURATED, "tester"), SM_OK);
    expect(__LINE__, sm_transition(sm, ART_STATE_AUCTION, "tester"), SM_OK);

    /* Invalid direct jump */
    expect(__LINE__, sm_transition(sm, ART_STATE_DRAFT, "tester"), SM_ERR_INVALID_TRANS);

    sm_destroy(sm);
    closelog();
    puts("All tests passed");
    return 0;
}
#endif /* STATE_MACHINE_TEST */

/* end of file */