```c
/**
 * @file pipeline_manager.h
 * @author
 * @brief  Public interface for the LexiLearn Pipeline Manager.
 *
 * The Pipeline Manager orchestrates the end-to-end machine-learning/NLP
 * workflow for LexiLearn’s Controller layer.  It implements a Pipeline
 * Pattern that:
 *   • Ingests classroom data from external LMS APIs
 *   • Spawns Strategy-pattern-driven training/evaluation jobs
 *   • Registers artifacts in the centralized Model Registry
 *   • Emits model-monitoring metrics and schedules automated retraining
 *   • Publishes life-cycle events to Observer Pattern subscribers
 *
 * All functions are thread-safe unless otherwise noted.
 */

#ifndef LEXILEARN_ORCHESTRATOR_SRC_CONTROLLER_PIPELINE_PIPELINE_MANAGER_H
#define LEXILEARN_ORCHESTRATOR_SRC_CONTROLLER_PIPELINE_PIPELINE_MANAGER_H

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard headers                                                         */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Forward declarations & opaque handles                                    */
/* ────────────────────────────────────────────────────────────────────────── */
typedef struct ll_pipeline_manager      ll_pipeline_manager_t; /* Opaque      */
typedef void*                           ll_observer_ctx_t;     /* User ctx    */

/* ────────────────────────────────────────────────────────────────────────── */
/*  Enumerations                                                             */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @enum ll_pipeline_state_t
 * Describes the high-level life-cycle state of the pipeline.
 */
typedef enum
{
    LL_PIPELINE_STATE_UNINITIALIZED = 0,
    LL_PIPELINE_STATE_INITIALIZING,
    LL_PIPELINE_STATE_IDLE,
    LL_PIPELINE_STATE_INGESTING,
    LL_PIPELINE_STATE_TRAINING,
    LL_PIPELINE_STATE_EVALUATING,
    LL_PIPELINE_STATE_DEPLOYING,
    LL_PIPELINE_STATE_MONITORING,
    LL_PIPELINE_STATE_PAUSED,
    LL_PIPELINE_STATE_SHUTTING_DOWN,
    LL_PIPELINE_STATE_TERMINATED,
    LL_PIPELINE_STATE_ERROR
} ll_pipeline_state_t;

/**
 * @enum ll_controller_error_t
 * Canonical error codes returned by Controller-layer APIs.
 */
typedef enum
{
    LL_CONTROLLER_SUCCESS  = 0,
    LL_CONTROLLER_EINVAL   = 1,   /* Invalid parameter                        */
    LL_CONTROLLER_ENOENT   = 2,   /* Required resource not found              */
    LL_CONTROLLER_EBUSY    = 3,   /* Operation cannot proceed (busy)          */
    LL_CONTROLLER_EPERM    = 4,   /* Operation not permitted                  */
    LL_CONTROLLER_EALREADY = 5,   /* Requested state already achieved         */
    LL_CONTROLLER_EIO      = 6,   /* I/O failure (e.g., disk, network)        */
    LL_CONTROLLER_ETMO     = 7,   /* Timeout                                  */
    LL_CONTROLLER_EUNKNOWN = 255  /* Unclassified / unexpected failure        */
} ll_controller_error_t;

/**
 * @enum ll_pipeline_event_t
 * Event types broadcast to observers registered via the Observer Pattern.
 */
typedef enum
{
    LL_PIPELINE_EVENT_NONE = 0,
    LL_PIPELINE_EVENT_DATA_INGESTED,
    LL_PIPELINE_EVENT_TRAINING_STARTED,
    LL_PIPELINE_EVENT_TRAINING_COMPLETED,
    LL_PIPELINE_EVENT_EVALUATION_COMPLETED,
    LL_PIPELINE_EVENT_MODEL_VERSIONED,
    LL_PIPELINE_EVENT_DRIFT_DETECTED,
    LL_PIPELINE_EVENT_RETRAINING_SCHEDULED,
    LL_PIPELINE_EVENT_PIPELINE_ERROR,
    LL_PIPELINE_EVENT_TERMINATED
} ll_pipeline_event_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Observer Pattern types                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @typedef ll_pipeline_event_cb
 * Callback invoked when an event occurs within the pipeline.
 *
 * @param event         Type of event.
 * @param event_payload Optional JSON payload (UTF-8, NUL-terminated if size
 *                      permits). May be NULL.
 * @param payload_size  Length in bytes of the payload (0 if none).
 * @param user_ctx      User-supplied pointer passed during registration.
 */
typedef void (*ll_pipeline_event_cb)(
    ll_pipeline_event_t  event,
    const char          *event_payload,
    size_t               payload_size,
    ll_observer_ctx_t    user_ctx);

/**
 * @struct ll_observer_handle_t
 * Token that represents a subscription.  Must be opaque to the caller.
 */
typedef struct ll_observer_handle
{
    uint64_t _token; /* Internal identifier – do not access directly. */
} ll_observer_handle_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Configuration                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @struct ll_pipeline_manager_cfg_t
 * Immutable configuration passed to ll_pipeline_manager_create().
 */
typedef struct ll_pipeline_manager_cfg
{
    const char *log_dir;                /* Directory for pipeline-level logs  */
    const char *experiment_name;        /* MLflow/Model Registry experiment   */
    uint32_t    max_concurrency;        /* Max concurrent training jobs       */
    uint32_t    training_timeout_s;     /* Hard timeout per training job      */
    bool        autoretrain_on_drift;   /* Auto-schedule retraining if drift  */
    uint32_t    drift_monitor_freq_min; /* Drift check cadence (minutes)      */
    uint32_t    _reserved;              /* Align to 8-byte boundary           */
} ll_pipeline_manager_cfg_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public API                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @brief  Instantiate a Pipeline Manager.
 *
 * @param[in]  cfg      Pointer to caller-owned configuration.
 * @param[out] mgr_out  Location where the newly created handle is stored.
 *
 * @retval LL_CONTROLLER_SUCCESS   On success.
 * @retval LL_CONTROLLER_EINVAL    cfg == NULL || mgr_out == NULL.
 * @retval LL_CONTROLLER_EIO       Persistent storage/log dir is not writable.
 */
int ll_pipeline_manager_create(
        const ll_pipeline_manager_cfg_t  *cfg,
        ll_pipeline_manager_t           **mgr_out);

/**
 * @brief Destroy a Pipeline Manager and free its resources.
 *
 * Safe to call with NULL; a no-op is performed in that case.
 */
int ll_pipeline_manager_destroy(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Start the orchestrated ML pipeline.
 *
 * Initializes worker threads, verifies dependencies (feature store,
 * model registry, etc.), and transitions the state to IDLE.
 */
int ll_pipeline_manager_start(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Pause execution without terminating workers.
 */
int ll_pipeline_manager_pause(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Resume a paused pipeline.
 */
int ll_pipeline_manager_resume(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Stop the pipeline and perform an orderly shutdown.
 *
 * Waits for in-flight jobs to finish or be cancelled and releases all
 * system resources (threads, file descriptors, sockets, etc.).
 */
int ll_pipeline_manager_stop(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Manually trigger a retraining cycle.
 *
 * This call is asynchronous; progress is communicated via events.
 */
int ll_pipeline_manager_trigger_retrain(
        ll_pipeline_manager_t *mgr);

/**
 * @brief Get the current life-cycle state.
 */
ll_pipeline_state_t
ll_pipeline_manager_get_state(
        const ll_pipeline_manager_t *mgr);

/**
 * @brief Retrieve the last error code.
 */
ll_controller_error_t
ll_pipeline_manager_last_error(
        const ll_pipeline_manager_t *mgr);

/**
 * @brief Register for pipeline events.
 *
 * @param mgr     Pipeline manager instance.
 * @param cb      Callback invoked on event; must not be NULL.
 * @param ctx     User context forwarded to the callback.
 * @param handle  Output token for later unregistration.
 */
int ll_pipeline_manager_register_observer(
        ll_pipeline_manager_t   *mgr,
        ll_pipeline_event_cb     cb,
        ll_observer_ctx_t        ctx,
        ll_observer_handle_t    *handle);

/**
 * @brief Unregister a previously registered observer.
 */
int ll_pipeline_manager_unregister_observer(
        ll_pipeline_manager_t *mgr,
        ll_observer_handle_t   handle);

/**
 * @brief Block until all queued events have been dispatched to observers.
 *
 * Useful for deterministic unit tests or controlled shutdown sequences.
 */
int ll_pipeline_manager_flush(
        ll_pipeline_manager_t *mgr);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_ORCHESTRATOR_SRC_CONTROLLER_PIPELINE_PIPELINE_MANAGER_H */
```