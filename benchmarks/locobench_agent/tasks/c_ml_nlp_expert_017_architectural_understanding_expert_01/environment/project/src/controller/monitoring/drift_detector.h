/*
 * =============================================================================
 *  LexiLearn MVC Orchestrator (ml_nlp)
 *  ------------------------------------------------------------
 *  File        : drift_detector.h
 *  Author      : LexiLearn Core Team
 *  Description : Runtime model–data drift monitoring component used by the
 *                Controller layer to decide when automated retraining or
 *                rollback should be triggered.
 *
 *  NOTE: This header is self-contained (“header-only”) to simplify integration
 *  into embedded targets where dynamic linking is unavailable.  Simply include
 *  this file in a single translation unit with
 *      #define LEXILEARN_DRIFT_DETECTOR_IMPLEMENTATION
 *  before the include directive to generate the implementation.
 *
 *  The API is thread-safe and uses an Observer pattern so that external
 *  subsystems (e.g., the Retraining Scheduler) can subscribe to drift events.
 * =============================================================================
 */

#ifndef LEXILEARN_DRIFT_DETECTOR_H
#define LEXILEARN_DRIFT_DETECTOR_H

#ifdef __cplusplus
extern "C" {
#endif

/* ====  Standard Library Dependencies  ===================================== */
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>

/* ====  Versioning  ========================================================= */
#define LEXILEARN_DRIFT_DETECTOR_VERSION_MAJOR 1
#define LEXILEARN_DRIFT_DETECTOR_VERSION_MINOR 0
#define LEXILEARN_DRIFT_DETECTOR_VERSION_PATCH 0

/* ====  Compile-time Configuration  ======================================== */
#ifndef LEXI_MAX_BINS
#   define LEXI_MAX_BINS 32          /* Upper bound on histogram bins */
#endif

#ifndef LEXI_MAX_LISTENERS
#   define LEXI_MAX_LISTENERS 16     /* Max Observer callbacks per detector */
#endif

#ifndef LEXI_MODEL_ID_LEN
#   define LEXI_MODEL_ID_LEN 64      /* Length of model identifier string */
#endif

/* ====  Error Codes  ======================================================== */
typedef enum
{
    LEXI_OK                = 0,
    LEXI_EINVAL            = 1,  /* Invalid argument                     */
    LEXI_EOOR              = 2,  /* Out of range                         */
    LEXI_ENOMEM            = 3,  /* Allocation failure                   */
    LEXI_ETHREAD           = 4,  /* Threading / lock failure             */
    LEXI_ELISTENER_FULL    = 5,  /* Listener array is already saturated  */
    LEXI_EUNKNOWN          = 255 /* Unknown / unspecified error          */
} lexi_error_t;

/* ====  Public API Types  =================================================== */

/*  Drift score computation strategy.  */
typedef enum
{
    LEXI_DRIFT_PSI      = 0,    /* Population Stability Index           */
    LEXI_DRIFT_KL       = 1,    /* Kullback-Leibler divergence          */
    LEXI_DRIFT_WASSER   = 2,    /* 1-Wasserstein (a.k.a Earth-Mover)    */
} lexi_drift_metric_t;

/*  Event payload describing a drift occurrence.  */
typedef struct
{
    char      model_id[LEXI_MODEL_ID_LEN];
    double    score;           /* Calculated drift metric score          */
    double    threshold;       /* User-defined threshold that was crossed */
    time_t    timestamp;       /* UTC epoch-seconds of detection          */
} lexi_drift_event_t;

/*  Function signature for Observer callback.  */
typedef void (*lexi_drift_listener_t)(const lexi_drift_event_t* event,
                                      void*                     user_ctx);

/*  Opaque drift detector handle.  */
typedef struct lexi_drift_detector lexi_drift_detector_t;

/*  Configuration object supplied at construction time.  */
typedef struct
{
    char                 model_id[LEXI_MODEL_ID_LEN];
    size_t               num_bins;           /* Must be ≤ LEXI_MAX_BINS     */
    double               threshold;          /* Trigger threshold           */
    lexi_drift_metric_t  metric;             /* Drift metric strategy       */
    size_t               window;             /* Sliding window (samples)    */
} lexi_drift_cfg_t;

/* ====  Public API Functions  ============================================== */

/*
 *  Create a new drift detector instance.
 *
 *  Parameters
 *  ----------
 *      cfg   : User-provided configuration object.
 *      err   : Optional pointer to receive an error code.
 *
 *  Returns
 *  -------
 *      Non-NULL pointer on success; NULL on failure.
 */
lexi_drift_detector_t*
lexi_drift_create(const lexi_drift_cfg_t* cfg, lexi_error_t* err);

/*
 *  Destroy a detector and free all associated resources.
 */
void
lexi_drift_destroy(lexi_drift_detector_t* detector);

/*
 *  Feed a batch of observed probabilities into the detector.
 *
 *  Arguments
 *  ---------
 *      detector : Handle previously obtained from lexi_drift_create.
 *      probs    : Array of probabilities corresponding to histogram bins.
 *                 Length must equal cfg->num_bins provided at construction.
 *      err      : Optional out-parameter for error status.
 *
 *  Notes
 *  -----
 *      Users are expected to pre-bucketize raw feature values into the same
 *      bin boundaries as the reference distribution used during model
 *      training.  All values in `probs` must be non-negative and sum to 1.0.
 */
void
lexi_drift_update(lexi_drift_detector_t* detector,
                  const double*          probs,
                  lexi_error_t*          err);

/*
 *  Query whether drift has already been observed (non-destructive).
 *
 *  Returns
 *  -------
 *      true  : Drift condition currently active.
 *      false : No drift identified.
 */
bool
lexi_drift_is_drifting(const lexi_drift_detector_t* detector,
                       double*                      out_score /* optional */);

/*
 *  Attach an Observer callback.
 *
 *  The callback is invoked asynchronously *within the context of
 *  lexi_drift_update()* immediately after drift is detected. To prevent
 *  deadlocks, callbacks must not call back into the detector API.
 */
lexi_error_t
lexi_drift_add_listener(lexi_drift_detector_t* detector,
                        lexi_drift_listener_t  fn,
                        void*                  user_ctx);

/*
 *  Remove an Observer callback.  All instances of `fn` with the same
 *  `user_ctx` will be removed.
 */
lexi_error_t
lexi_drift_remove_listener(lexi_drift_detector_t* detector,
                           lexi_drift_listener_t  fn,
                           void*                  user_ctx);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ====  Implementation  ===================================================== */
#ifdef LEXILEARN_DRIFT_DETECTOR_IMPLEMENTATION
/*  Internal helper macros  */
#define LEXI_MIN(a,b) ((a) < (b) ? (a) : (b))
#define LEXI_MAX(a,b) ((a) > (b) ? (a) : (b))

struct lexi_drift_detector
{
    lexi_drift_cfg_t    cfg;
    size_t              sample_count;                  /* # observations      */
    double              reference[LEXI_MAX_BINS];      /* Training dist.      */
    double              rolling_actual[LEXI_MAX_BINS]; /* Sliding window dist */
    double              last_score;
    bool                drifting;

    /* Observer Pattern */
    lexi_drift_listener_t listeners[LEXI_MAX_LISTENERS];
    void*                 listener_ctx[LEXI_MAX_LISTENERS];
    size_t                listener_cnt;

    /* Thread-safety */
    pthread_mutex_t      mtx;
};

/* ====  Utility: Safe allocation wrapper  ================================== */
static inline void* lexi_xcalloc(size_t n, size_t sz)
{
    void* p = calloc(n, sz);
    return p;
}

/* ====  Metric Implementations  =========================================== */
static double
lexi_compute_psi(const double* ref, const double* act, size_t k)
{
    double psi = 0.0;
    for (size_t i = 0; i < k; ++i)
    {
        const double e = ref[i] <= 0.0 ? 1e-12 : ref[i];
        const double a = act[i] <= 0.0 ? 1e-12 : act[i];
        psi += (a - e) * log(a / e);
    }
    return psi;
}

static double
lexi_compute_kl(const double* ref, const double* act, size_t k)
{
    double kl = 0.0;
    for (size_t i = 0; i < k; ++i)
    {
        double a = act[i] <= 0.0 ? 1e-12 : act[i];
        double r = ref[i] <= 0.0 ? 1e-12 : ref[i];
        kl += a * log(a / r);
    }
    return kl;
}

static double
lexi_compute_wasserstein(const double* ref, const double* act, size_t k)
{
    /* 1-dimensional 1-Wasserstein distance for histograms */
    double cum_ref = 0.0, cum_act = 0.0, wass = 0.0;
    for (size_t i = 0; i < k; ++i)
    {
        cum_ref += ref[i];
        cum_act += act[i];
        wass += fabs(cum_ref - cum_act);
    }
    return wass;
}

/* ====  Private helper: notify listeners  ================================== */
static void
lexi_notify(const lexi_drift_detector_t* det)
{
    lexi_drift_event_t evt;
    strncpy(evt.model_id, det->cfg.model_id, LEXI_MODEL_ID_LEN);
    evt.score     = det->last_score;
    evt.threshold = det->cfg.threshold;
    evt.timestamp = time(NULL);

    for (size_t i = 0; i < det->listener_cnt; ++i)
    {
        det->listeners[i](&evt, det->listener_ctx[i]);
    }
}

/* ====  Public API: Create  ================================================= */
lexi_drift_detector_t*
lexi_drift_create(const lexi_drift_cfg_t* cfg, lexi_error_t* err)
{
    if (!cfg || cfg->num_bins == 0 || cfg->num_bins > LEXI_MAX_BINS)
    {
        if (err) *err = LEXI_EINVAL;
        return NULL;
    }

    lexi_drift_detector_t* det = (lexi_drift_detector_t*)lexi_xcalloc(1, sizeof(*det));
    if (!det)
    {
        if (err) *err = LEXI_ENOMEM;
        return NULL;
    }

    det->cfg = *cfg;
    /* Initialize reference distribution to uniform until calibrated */
    for (size_t i = 0; i < cfg->num_bins; ++i)
        det->reference[i] = 1.0 / (double)cfg->num_bins;

    if (pthread_mutex_init(&det->mtx, NULL) != 0)
    {
        free(det);
        if (err) *err = LEXI_ETHREAD;
        return NULL;
    }
    if (err) *err = LEXI_OK;
    return det;
}

/* ====  Public API: Destroy  ============================================== */
void
lexi_drift_destroy(lexi_drift_detector_t* det)
{
    if (!det) return;
    pthread_mutex_destroy(&det->mtx);
    free(det);
}

/* ====  Public API: Update  =============================================== */
void
lexi_drift_update(lexi_drift_detector_t* det,
                  const double*          probs,
                  lexi_error_t*          err)
{
    if (!det || !probs)
    {
        if (err) *err = LEXI_EINVAL;
        return;
    }

    pthread_mutex_lock(&det->mtx);
    const size_t k = det->cfg.num_bins;

    /* Exponential moving average for rolling distribution */
    const double alpha = 1.0 / (double)LEXI_MAX(1, det->cfg.window);
    for (size_t i = 0; i < k; ++i)
    {
        double p = probs[i];
        if (p < 0.0)
        {
            pthread_mutex_unlock(&det->mtx);
            if (err) *err = LEXI_EINVAL;
            return;
        }
        det->rolling_actual[i] =
            (1.0 - alpha) * det->rolling_actual[i] + alpha * p;
    }

    /* Compute drift metric */
    switch (det->cfg.metric)
    {
        case LEXI_DRIFT_PSI:
            det->last_score = lexi_compute_psi(det->reference,
                                               det->rolling_actual, k);
            break;
        case LEXI_DRIFT_KL:
            det->last_score = lexi_compute_kl(det->reference,
                                              det->rolling_actual, k);
            break;
        case LEXI_DRIFT_WASSER:
            det->last_score = lexi_compute_wasserstein(det->reference,
                                                       det->rolling_actual, k);
            break;
        default:
            det->last_score = 0.0;
            break;
    }

    bool drift_now = det->last_score >= det->cfg.threshold;
    if (drift_now && !det->drifting)
    {
        det->drifting = true;
        lexi_notify(det); /* fire Observer callbacks */
    }
    else if (!drift_now && det->drifting)
    {
        det->drifting = false; /* reset flag */
    }

    det->sample_count++;
    pthread_mutex_unlock(&det->mtx);

    if (err) *err = LEXI_OK;
}

/* ====  Public API: is_drifting  ========================================== */
bool
lexi_drift_is_drifting(const lexi_drift_detector_t* det, double* out_score)
{
    if (!det) return false;
    if (out_score) *out_score = det->last_score;
    return det->drifting;
}

/* ====  Public API: add/remove listener  =================================== */
lexi_error_t
lexi_drift_add_listener(lexi_drift_detector_t* det,
                        lexi_drift_listener_t  fn,
                        void*                  ctx)
{
    if (!det || !fn) return LEXI_EINVAL;
    pthread_mutex_lock(&det->mtx);

    if (det->listener_cnt >= LEXI_MAX_LISTENERS)
    {
        pthread_mutex_unlock(&det->mtx);
        return LEXI_ELISTENER_FULL;
    }
    det->listeners[det->listener_cnt]     = fn;
    det->listener_ctx[det->listener_cnt]  = ctx;
    det->listener_cnt++;

    pthread_mutex_unlock(&det->mtx);
    return LEXI_OK;
}

lexi_error_t
lexi_drift_remove_listener(lexi_drift_detector_t* det,
                           lexi_drift_listener_t  fn,
                           void*                  ctx)
{
    if (!det || !fn) return LEXI_EINVAL;

    pthread_mutex_lock(&det->mtx);
    size_t i = 0;
    while (i < det->listener_cnt)
    {
        if (det->listeners[i] == fn && det->listener_ctx[i] == ctx)
        {
            /* shift elements */
            for (size_t j = i + 1; j < det->listener_cnt; ++j)
            {
                det->listeners[j - 1]    = det->listeners[j];
                det->listener_ctx[j - 1] = det->listener_ctx[j];
            }
            det->listener_cnt--;
            /* do not increment i to catch duplicate matches */
        }
        else
        {
            ++i;
        }
    }
    pthread_mutex_unlock(&det->mtx);
    return LEXI_OK;
}

#endif /* LEXILEARN_DRIFT_DETECTOR_IMPLEMENTATION */
#endif /* LEXILEARN_DRIFT_DETECTOR_H */
