/*
 *  drift_detector.c
 *  LexiLearn Orchestrator – Controller / Monitoring Component
 *
 *  Description:
 *      Implements real-time model-drift detection using a Page-Hinkley Test for
 *      each registered model instance.  The detector is designed as an Observer
 *      that publishes drift events back to the Controller’s event-bus so that
 *      automated retraining jobs can be triggered without human intervention.
 *
 *  Design highlights:
 *      • One drift state per model, stored in an in-memory hash map (uthash).
 *      • Thread-safe; synchronizes access with a POSIX mutex.
 *      • Supports multiple user-supplied callbacks (observers) to decouple the
 *        detector from concrete retraining, alerting, or logging logic.
 *
 *  Compile flags:
 *      gcc -Wall -Wextra -pedantic -std=c11 -pthread -o drift_detector.o -c drift_detector.c
 *
 *  External dependencies:
 *      • uthash.h         – single-header hash-table implementation (MIT License)
 *      • pthread (glibc)  – for synchronization
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>

#include "uthash.h"            /* Hash-table for mapping model_id → drift state */
#include "drift_detector.h"    /* Public header for this implementation          */


/* ============================================================================
 *  Type definitions
 * ========================================================================== */

/* Internal representation of the Page-Hinkley drift state for a model. */
typedef struct {
    char            model_id[64];      /* unique identifier (hash-key)          */
    double          x_mean;            /* running mean of the monitored metric  */
    double          cumulative_sum;    /* Page-Hinkley cumulative difference    */
    double          min_cumulative_sum;/* Minimum cumulative sum seen so far    */
    size_t          sample_count;      /* N                                    */
    double          delta;             /* Small magnitude to ignore             */
    double          lambda;            /* Drift threshold                       */
    UT_hash_handle  hh;                /* uthash handle                         */
} model_drift_state_t;


/* Linked list node for callback registry. */
typedef struct callback_node {
    drift_callback_t        fn;
    void                   *user_data;
    struct callback_node   *next;
} callback_node_t;


/* ============================================================================
 *  Module-level globals   (protected by g_lock)
 * ========================================================================== */

static model_drift_state_t *g_model_states = NULL;  /* uthash head              */
static callback_node_t     *g_callbacks    = NULL;  /* observer registry list   */
static pthread_mutex_t      g_lock         = PTHREAD_MUTEX_INITIALIZER;
static int                  g_initialized  = 0;


/* ============================================================================
 *  Helper / Internal functions
 * ========================================================================== */

/* Publish a drift event to all registered observers. */
static void
publish_drift_event(const char *model_id, const char *reason)
{
    callback_node_t *node = g_callbacks;

    while (node) {
        node->fn(model_id, reason, node->user_data);
        node = node->next;
    }
}


/* Ensure the library has been initialized once. */
static int
ensure_initialized(void)
{
    if (__builtin_expect(g_initialized, 1))
        return 0;

    int rc = pthread_mutex_lock(&g_lock);
    if (rc != 0) return rc;

    if (!g_initialized) {
        /* Potential future initialization: connect to central event bus, etc. */
        g_initialized = 1;
    }

    return pthread_mutex_unlock(&g_lock);
}


/* ============================================================================
 *  Public API – see header for documentation
 * ========================================================================== */

int
drift_detector_register_model(const char *model_id,
                              double       delta,
                              double       lambda)
{
    if (!model_id || delta <= 0.0 || lambda <= 0.0)
        return EINVAL;

    int rc = ensure_initialized();
    if (rc != 0) return rc;

    rc = pthread_mutex_lock(&g_lock);
    if (rc != 0) return rc;

    /* Check if model already exists. */
    model_drift_state_t *state = NULL;
    HASH_FIND_STR(g_model_states, model_id, state);
    if (state) {
        pthread_mutex_unlock(&g_lock);
        return EEXIST;
    }

    /* Create new drift state. */
    state = calloc(1, sizeof(model_drift_state_t));
    if (!state) {
        pthread_mutex_unlock(&g_lock);
        return ENOMEM;
    }

    strncpy(state->model_id, model_id, sizeof(state->model_id) - 1);
    state->delta                = delta;
    state->lambda               = lambda;
    state->x_mean               = 0.0;
    state->cumulative_sum       = 0.0;
    state->min_cumulative_sum   = 0.0;
    state->sample_count         = 0;

    HASH_ADD_STR(g_model_states, model_id, state);

    pthread_mutex_unlock(&g_lock);
    return 0;
}


int
drift_detector_unregister_model(const char *model_id)
{
    if (!model_id) return EINVAL;

    int rc = pthread_mutex_lock(&g_lock);
    if (rc != 0) return rc;

    model_drift_state_t *state = NULL;
    HASH_FIND_STR(g_model_states, model_id, state);
    if (!state) {
        pthread_mutex_unlock(&g_lock);
        return ENOENT;
    }

    HASH_DEL(g_model_states, state);
    free(state);

    pthread_mutex_unlock(&g_lock);
    return 0;
}


int
drift_detector_update_metric(const char *model_id, double metric_value)
{
    if (!model_id) return EINVAL;

    int rc = ensure_initialized();
    if (rc != 0) return rc;

    rc = pthread_mutex_lock(&g_lock);
    if (rc != 0) return rc;

    model_drift_state_t *state = NULL;
    HASH_FIND_STR(g_model_states, model_id, state);
    if (!state) {
        pthread_mutex_unlock(&g_lock);
        return ENOENT;
    }

    /* Update running mean incrementally. */
    state->sample_count += 1;
    double prev_mean = state->x_mean;
    state->x_mean += (metric_value - prev_mean) / (double)state->sample_count;

    /* Page-Hinkley test g_t = Σ (x_t – mean_t – δ) */
    state->cumulative_sum += (metric_value - state->x_mean - state->delta);
    if (state->cumulative_sum < state->min_cumulative_sum)
        state->min_cumulative_sum = state->cumulative_sum;

    double ph_statistic = state->cumulative_sum - state->min_cumulative_sum;

    /* Drift detected? */
    if (ph_statistic > state->lambda) {
        char reason[128];
        snprintf(reason, sizeof(reason),
                 "Drift detected (PH=%.4f > λ=%.4f) after %zu samples",
                 ph_statistic, state->lambda, state->sample_count);

        /* Provide callback outside of locked section to avoid deadlocks. */
        callback_node_t *tmp_callbacks = g_callbacks;
        pthread_mutex_unlock(&g_lock);

        /* Notify observers */
        while (tmp_callbacks) {
            tmp_callbacks->fn(model_id, reason, tmp_callbacks->user_data);
            tmp_callbacks = tmp_callbacks->next;
        }

        /* Reacquire lock to reset state. */
        pthread_mutex_lock(&g_lock);

        /* Reset cumulative statistics for next monitoring cycle. */
        state->cumulative_sum     = 0.0;
        state->min_cumulative_sum = 0.0;
        state->sample_count       = 0;
    }

    pthread_mutex_unlock(&g_lock);
    return 0;
}


int
drift_detector_add_callback(drift_callback_t cb, void *user_data)
{
    if (!cb) return EINVAL;

    int rc = ensure_initialized();
    if (rc != 0) return rc;

    rc = pthread_mutex_lock(&g_lock);
    if (rc != 0) return rc;

    callback_node_t *node = calloc(1, sizeof(callback_node_t));
    if (!node) {
        pthread_mutex_unlock(&g_lock);
        return ENOMEM;
    }

    node->fn        = cb;
    node->user_data = user_data;
    node->next      = g_callbacks;
    g_callbacks     = node;

    pthread_mutex_unlock(&g_lock);
    return 0;
}


void
drift_detector_cleanup(void)
{
    pthread_mutex_lock(&g_lock);

    /* Free model state hash table. */
    model_drift_state_t *cur, *tmp;
    HASH_ITER(hh, g_model_states, cur, tmp) {
        HASH_DEL(g_model_states, cur);
        free(cur);
    }
    g_model_states = NULL;

    /* Free callback list. */
    callback_node_t *cnode = g_callbacks;
    while (cnode) {
        callback_node_t *next = cnode->next;
        free(cnode);
        cnode = next;
    }
    g_callbacks = NULL;

    pthread_mutex_unlock(&g_lock);
}


/* ============================================================================
 *  Example default callback (optional)
 * ========================================================================== */

static void
default_log_callback(const char *model_id, const char *reason, void *ud)
{
    (void)ud; /* unused */
    fprintf(stderr, "[DRIFT] Model=%s  %s\n", model_id, reason);
}


/* ============================================================================
 *  Module initializer – register default logging callback
 * ========================================================================== */

__attribute__((constructor))
static void
drift_detector_constructor(void)
{
    drift_detector_add_callback(default_log_callback, NULL);
}

__attribute__((destructor))
static void
drift_detector_destructor(void)
{
    drift_detector_cleanup();
}
