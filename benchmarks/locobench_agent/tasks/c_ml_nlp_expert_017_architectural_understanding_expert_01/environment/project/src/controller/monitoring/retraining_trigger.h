/*
 *  LexiLearn MVC Orchestrator – Retraining Trigger Monitor
 *  -------------------------------------------------------
 *  File: retraining_trigger.h
 *  Desc: Observer-Pattern component that passively collects model-level
 *        performance metrics and proactively triggers automated retraining
 *        jobs when statistically significant model drift is detected.
 *
 *  Usage:
 *      #define LEXILEARN_RETRAINING_TRIGGER_IMPLEMENTATION
 *      #include "retraining_trigger.h"
 *
 *  The first translation unit that defines
 *      LEXILEARN_RETRAINING_TRIGGER_IMPLEMENTATION
 *  gets the function definitions; every other TU only sees the declarations.
 *
 *  Thread-safety:  All public APIs are thread-safe and can be called from the
 *                  metrics-logging hot-path as well as from the scheduler.
 *
 *  Copyright (c) 2024  LexiLearn
 */

#ifndef LEXILEARN_RETRAINING_TRIGGER_H
#define LEXILEARN_RETRAINING_TRIGGER_H

/* -------------------------------------------------------------------------
 *  Public Dependencies
 * -------------------------------------------------------------------------*/
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 *  Compile-time Configuration
 * -------------------------------------------------------------------------*/
#ifndef RT_MAX_MODELS
#define RT_MAX_MODELS          64      /* maximum number of concurrently-tracked models */
#endif

#ifndef RT_MAX_SAMPLES
#define RT_MAX_SAMPLES         32      /* sliding window size per model */
#endif

#ifndef RT_BASELINE_WINDOW
#define RT_BASELINE_WINDOW      5      /* number of initial samples to establish baseline */
#endif

#ifndef RT_MODEL_ID_MAX
#define RT_MODEL_ID_MAX        64      /* bytes incl.\ null-terminator */
#endif

/* -------------------------------------------------------------------------
 *  Status / Error Codes
 * -------------------------------------------------------------------------*/
typedef enum
{
    RT_OK = 0,
    RT_ERR_FULL,            /* registry full – no free slots              */
    RT_ERR_NOT_FOUND,       /* model not registered                        */
    RT_ERR_ALREADY_EXISTS,  /* model already registered                    */
    RT_ERR_BAD_PARAM,       /* null ptr / invalid argument                 */
    RT_ERR_INTERNAL         /* unexpected internal failure                 */
} rt_status_t;

/* -------------------------------------------------------------------------
 *  Metric Descriptor
 * -------------------------------------------------------------------------*/
typedef enum
{
    RT_METRIC_ACCURACY,
    RT_METRIC_LOSS,
    RT_METRIC_ROUGE,
    RT_METRIC_F1,
    RT_METRIC_CUSTOM
} rt_metric_t;

/* -------------------------------------------------------------------------
 *  Callback Signature
 * -------------------------------------------------------------------------*/
/*
 *  The orchestrator registers exactly one callback that gets invoked
 *  whenever drift is detected for a given model.  The callback must return
 *  true on success so that the trigger can reset its “retraining pending”
 *  flag; returning false keeps the flag set and the trigger will retry once
 *  per check-interval (the orchestrator may choose to back-off).
 */
typedef bool (*rt_retrain_callback_t)(const char *model_id);

/* -------------------------------------------------------------------------
 *  Public API
 * -------------------------------------------------------------------------*/

/* Initialization / shutdown */
rt_status_t rt_trigger_init(rt_retrain_callback_t cb);
void        rt_trigger_shutdown(void);

/* Model-level registry management */
rt_status_t rt_register_model(const char *model_id,
                              rt_metric_t metric,
                              double drift_threshold_pct);  /* e.g. 5.0 for 5 % */

rt_status_t rt_unregister_model(const char *model_id);

/* Metric ingestion (hot-path) */
rt_status_t rt_record_metric(const char *model_id,
                             double      value,             /* raw metric value */
                             uint64_t    timestamp_ms);     /* epoch millis     */

/* Synchronous check – can be called by cron-like job every N minutes */
void rt_check_and_schedule(void);

/* Poll whether the last check flagged a model for retraining. Mainly for unit-tests. */
bool rt_has_pending_retraining(const char *model_id);

#ifdef __cplusplus
}
#endif

/* -------------------------------------------------------------------------*/
/* -------------------------------------------------------------------------*/
/* -------------------------------------------------------------------------*/
/*              Implementation – only if requested by compile unit          */
/* -------------------------------------------------------------------------*/
/* -------------------------------------------------------------------------*/
/* -------------------------------------------------------------------------*/
#ifdef LEXILEARN_RETRAINING_TRIGGER_IMPLEMENTATION

/* -------------------------------------------------------------------------
 *  Private Includes
 * -------------------------------------------------------------------------*/
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* -------------------------------------------------------------------------
 *  Private Helper Macros
 * -------------------------------------------------------------------------*/
#define RT_MIN(a,b) ((a) < (b) ? (a) : (b))
#define RT_MAX(a,b) ((a) > (b) ? (a) : (b))

/* Return current time in milliseconds since epoch – for internal bookkeeping
 * when caller passes 0 for timestamp_ms.
 */
static uint64_t _rt_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ((uint64_t) ts.tv_sec) * 1000ULL + (uint64_t) (ts.tv_nsec / 1000000ULL);
}

/* Metric ring-buffer element */
typedef struct
{
    double   value;
    uint64_t ts_ms;
} rt_sample_t;

/* Model registry entry */
typedef struct
{
    bool             in_use;
    char             model_id[RT_MODEL_ID_MAX];

    /* configuration */
    rt_metric_t      metric_type;
    double           drift_threshold_pct;   /* % drop/increase vs baseline */

    /* runtime state */
    rt_sample_t      samples[RT_MAX_SAMPLES];
    size_t           head;                  /* next insertion point */
    size_t           count;                 /* current number of samples */
    bool             retrain_pending;       /* drift detected, waiting for handler */
} rt_model_entry_t;

/* Global registry */
static struct
{
    pthread_mutex_t      mtx;
    rt_model_entry_t     entries[RT_MAX_MODELS];
    rt_retrain_callback_t callback;
    bool                 initialized;
} _rt_state = {
    .mtx          = PTHREAD_MUTEX_INITIALIZER,
    .entries      = { {0} },
    .callback     = NULL,
    .initialized  = false
};

/* -------------------------------------------------------------------------
 *  Internal Functions
 * -------------------------------------------------------------------------*/

/* Thread-safe lookup (caller must hold lock) */
static rt_model_entry_t *_rt_find_entry(const char *model_id)
{
    for (size_t i = 0; i < RT_MAX_MODELS; ++i)
    {
        if (_rt_state.entries[i].in_use &&
            strncmp(_rt_state.entries[i].model_id, model_id, RT_MODEL_ID_MAX) == 0)
        {
            return &_rt_state.entries[i];
        }
    }
    return NULL;
}

/* Compute average of N most recent samples from ring buffer */
static double _rt_avg_last_n(const rt_model_entry_t *ent, size_t n)
{
    if (ent->count == 0) { return 0.0; }
    n = RT_MIN(n, ent->count);
    double sum = 0.0;
    for (size_t i = 0; i < n; ++i)
    {
        size_t idx = (ent->head + RT_MAX_SAMPLES - 1 - i) % RT_MAX_SAMPLES;
        sum += ent->samples[idx].value;
    }
    return sum / (double) n;
}

/* Compute baseline average consisting of the oldest N samples */
static double _rt_avg_first_n(const rt_model_entry_t *ent, size_t n)
{
    if (ent->count == 0) { return 0.0; }
    n = RT_MIN(n, ent->count);
    double sum = 0.0;
    size_t start = (ent->head + RT_MAX_SAMPLES - ent->count) % RT_MAX_SAMPLES;
    for (size_t i = 0; i < n; ++i)
    {
        size_t idx = (start + i) % RT_MAX_SAMPLES;
        sum += ent->samples[idx].value;
    }
    return sum / (double) n;
}

/* -------------------------------------------------------------------------
 *  Public API – Implementation
 * -------------------------------------------------------------------------*/
rt_status_t rt_trigger_init(rt_retrain_callback_t cb)
{
    if (cb == NULL) { return RT_ERR_BAD_PARAM; }

    pthread_mutex_lock(&_rt_state.mtx);
    _rt_state.callback    = cb;
    _rt_state.initialized = true;
    pthread_mutex_unlock(&_rt_state.mtx);

    return RT_OK;
}

void rt_trigger_shutdown(void)
{
    pthread_mutex_lock(&_rt_state.mtx);
    memset(_rt_state.entries, 0, sizeof(_rt_state.entries));
    _rt_state.callback    = NULL;
    _rt_state.initialized = false;
    pthread_mutex_unlock(&_rt_state.mtx);
}

rt_status_t rt_register_model(const char *model_id,
                              rt_metric_t metric,
                              double drift_threshold_pct)
{
    if (!model_id || drift_threshold_pct <= 0.0) { return RT_ERR_BAD_PARAM; }

    rt_status_t status = RT_ERR_FULL;
    pthread_mutex_lock(&_rt_state.mtx);

    /* duplicate? */
    if (_rt_find_entry(model_id) != NULL)
    {
        status = RT_ERR_ALREADY_EXISTS;
        goto out;
    }

    /* locate free slot */
    for (size_t i = 0; i < RT_MAX_MODELS; ++i)
    {
        if (!_rt_state.entries[i].in_use)
        {
            rt_model_entry_t *ent = &_rt_state.entries[i];
            memset(ent, 0, sizeof(*ent));
            ent->in_use              = true;
            ent->metric_type         = metric;
            ent->drift_threshold_pct = drift_threshold_pct;
            strncpy(ent->model_id, model_id, RT_MODEL_ID_MAX - 1);
            status = RT_OK;
            goto out;
        }
    }

out:
    pthread_mutex_unlock(&_rt_state.mtx);
    return status;
}

rt_status_t rt_unregister_model(const char *model_id)
{
    if (!model_id) { return RT_ERR_BAD_PARAM; }

    pthread_mutex_lock(&_rt_state.mtx);
    rt_model_entry_t *ent = _rt_find_entry(model_id);
    if (ent)
    {
        memset(ent, 0, sizeof(*ent));
        pthread_mutex_unlock(&_rt_state.mtx);
        return RT_OK;
    }
    pthread_mutex_unlock(&_rt_state.mtx);
    return RT_ERR_NOT_FOUND;
}

rt_status_t rt_record_metric(const char *model_id,
                             double      value,
                             uint64_t    timestamp_ms)
{
    if (!model_id) { return RT_ERR_BAD_PARAM; }
    if (timestamp_ms == 0) { timestamp_ms = _rt_now_ms(); }

    pthread_mutex_lock(&_rt_state.mtx);
    rt_model_entry_t *ent = _rt_find_entry(model_id);
    if (!ent)
    {
        pthread_mutex_unlock(&_rt_state.mtx);
        return RT_ERR_NOT_FOUND;
    }

    /* insert into ring buffer */
    ent->samples[ent->head].value  = value;
    ent->samples[ent->head].ts_ms  = timestamp_ms;
    ent->head   = (ent->head + 1) % RT_MAX_SAMPLES;
    ent->count  = RT_MIN(ent->count + 1, RT_MAX_SAMPLES);

    pthread_mutex_unlock(&_rt_state.mtx);
    return RT_OK;
}

/* Determine drift for a single entry (lock must be held) */
static bool _rt_drift_detected(rt_model_entry_t *ent)
{
    if (ent->count < RT_BASELINE_WINDOW * 2) { return false; }

    double baseline = _rt_avg_first_n(ent, RT_BASELINE_WINDOW);
    double current  = _rt_avg_last_n(ent,  RT_BASELINE_WINDOW);

    if (baseline == 0.0) { return false; } /* avoid div-by-zero */

    double delta_pct;
    if (ent->metric_type == RT_METRIC_LOSS)
    {
        /* increase in loss indicates drift */
        delta_pct = ((current - baseline) / baseline) * 100.0;
        return delta_pct >= ent->drift_threshold_pct;
    }
    else
    {
        /* decrease in metric (accuracy, F1, etc.) indicates drift */
        delta_pct = ((baseline - current) / baseline) * 100.0;
        return delta_pct >= ent->drift_threshold_pct;
    }
}

void rt_check_and_schedule(void)
{
    if (!_rt_state.initialized || !_rt_state.callback) { return; }

    pthread_mutex_lock(&_rt_state.mtx);

    /* scan registry */
    for (size_t i = 0; i < RT_MAX_MODELS; ++i)
    {
        rt_model_entry_t *ent = &_rt_state.entries[i];
        if (!ent->in_use || ent->retrain_pending) { continue; }

        if (_rt_drift_detected(ent))
        {
            ent->retrain_pending = true;
            /* Unlock during callback to avoid deadlocks */
            pthread_mutex_unlock(&_rt_state.mtx);
            bool ok = _rt_state.callback(ent->model_id);
            pthread_mutex_lock(&_rt_state.mtx);

            if (ok)
            {
                /* Callback accepted the scheduling – reset samples to establish new baseline */
                ent->count            = 0;
                ent->head             = 0;
                ent->retrain_pending  = false;
            }
            /* else: keep pending flag set for future retries */
        }
    }

    pthread_mutex_unlock(&_rt_state.mtx);
}

bool rt_has_pending_retraining(const char *model_id)
{
    if (!model_id) { return false; }
    bool pending = false;
    pthread_mutex_lock(&_rt_state.mtx);
    rt_model_entry_t *ent = _rt_find_entry(model_id);
    if (ent) { pending = ent->retrain_pending; }
    pthread_mutex_unlock(&_rt_state.mtx);
    return pending;
}

#endif /* LEXILEARN_RETRAINING_TRIGGER_IMPLEMENTATION */
#endif /* LEXILEARN_RETRAINING_TRIGGER_H */
