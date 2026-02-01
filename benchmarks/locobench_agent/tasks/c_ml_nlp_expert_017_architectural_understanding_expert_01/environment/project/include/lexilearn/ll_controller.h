#ifndef LEXILEARN_LL_CONTROLLER_H
#define LEXILEARN_LL_CONTROLLER_H
/**
 *  @file ll_controller.h
 *  @brief Public interface for the LexiLearn Controller layer.
 *
 *  The Controller orchestrates all data- and model-centric workflows:
 *      •   Ingests data from Learning-Management Systems (LMS)
 *      •   Triggers factory-generated training / inference jobs
 *      •   Logs experiments to the Model Registry
 *      •   Monitors model-performance drift and schedules automatic retraining
 *
 *  This header purposely exposes only the high-level API needed by View/Model
 *  layers as well as external orchestration tools (e.g., Airflow, Kubeflow).
 *
 *  Copyright (c) 2024, LexiLearn
 *  SPDX-License-Identifier: MIT
 */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard-Library Dependencies                                           */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stddef.h>     /* size_t  */
#include <stdint.h>     /* uint64_t, int32_t */
#include <stdbool.h>    /* bool    */
#include <time.h>       /* time_t  */

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public Constants & Macros                                               */
/* ────────────────────────────────────────────────────────────────────────── */
/**
 *  @def LL_CONTROLLER_VERSION
 *  Semantic version of the Controller API.
 */
#define LL_CONTROLLER_VERSION "1.2.0"

/**
 *  @def LL_MAX_RESOURCE_URI
 *  Maximum length (including NUL terminator) for URIs passed to the Controller.
 */
#define LL_MAX_RESOURCE_URI 256U

/**
 *  @def LL_MAX_TAG_SIZE
 *  Maximum length for user-supplied experiment/model tags.
 */
#define LL_MAX_TAG_SIZE      48U

/**
 *  @macro LL_DEPRECATED
 *  Marks API symbols as deprecated when compiled with supported toolchains.
 */
#if defined(__GNUC__) || defined(__clang__)
#   define LL_DEPRECATED __attribute__((deprecated))
#else
#   define LL_DEPRECATED
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Status / Error Codes                                                    */
/* ────────────────────────────────────────────────────────────────────────── */
/**
 *  @enum ll_status_t
 *  @brief Return codes for all Controller APIs.
 */
typedef enum
{
    LL_STATUS_OK                 = 0,  /* Operation succeeded                    */
    LL_STATUS_INVALID_ARGUMENT   = 1,  /* One or more arguments are invalid      */
    LL_STATUS_IO_ERROR           = 2,  /* File/Network I/O error                 */
    LL_STATUS_NOT_FOUND          = 3,  /* Requested resource does not exist      */
    LL_STATUS_PERM_DENIED        = 4,  /* Permission denied (filesystem, etc.)   */
    LL_STATUS_CONFLICT           = 5,  /* Resource conflict (already exists, …)  */
    LL_STATUS_TIMED_OUT          = 6,  /* Operation took longer than expected    */
    LL_STATUS_BACKEND_FAILURE    = 7,  /* Underlying Model Registry / DB failed  */
    LL_STATUS_UNIMPLEMENTED      = 8,  /* Feature not yet implemented            */
    LL_STATUS_CANCELLED          = 9,  /* User or system requested cancellation  */
    LL_STATUS_INTERNAL_ERROR     = 10  /* Unexpected internal failure            */
} ll_status_t;


/* ────────────────────────────────────────────────────────────────────────── */
/*  Forward Declarations / Opaque Types                                      */
/* ────────────────────────────────────────────────────────────────────────── */
/** Opaque handle to a running Controller instance. */
typedef struct ll_controller      ll_controller_t;

/** Opaque handle representing a scheduled retraining job. */
typedef struct ll_retrain_job     ll_retrain_job_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Enumerations                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
/**
 *  @enum ll_event_t
 *  Events emitted by the Controller for Observer callbacks.
 */
typedef enum
{
    LL_EVENT_NONE                   = 0,
    LL_EVENT_DATA_INGEST_STARTED    = 1,
    LL_EVENT_DATA_INGEST_COMPLETED  = 2,
    LL_EVENT_TRAINING_STARTED       = 3,
    LL_EVENT_TRAINING_COMPLETED     = 4,
    LL_EVENT_MODEL_REGISTERED       = 5,
    LL_EVENT_MODEL_DRIFT_DETECTED   = 6,
    LL_EVENT_RETRAINING_SCHEDULED   = 7,
    LL_EVENT_RETRAINING_EXECUTED    = 8,
    LL_EVENT_SHUTDOWN               = 9
} ll_event_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Configuration Structures                                                */
/* ────────────────────────────────────────────────────────────────────────── */
/**
 *  @struct ll_controller_cfg_t
 *  Runtime configuration for a Controller instance.
 */
typedef struct
{
    /* Root directory for persistent assets (feature store, checkpoints, …) */
    char        asset_root[LL_MAX_RESOURCE_URI];

    /* URI for the Model Registry (e.g., mlflow://tracking-svc:5000)        */
    char        registry_uri[LL_MAX_RESOURCE_URI];

    /* Maximum number of concurrent training jobs permitted.                */
    uint32_t    max_concurrency;

    /* Polling interval, in seconds, for drift-detection hooks.             */
    uint32_t    drift_poll_interval_sec;

    /* Flag enabling verbose logging from the Controller.                   */
    bool        verbose;

    /* Reserved for future use; must be NULL to preserve ABI                */
    void       *reserved;
} ll_controller_cfg_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Callback Types                                                           */
/* ────────────────────────────────────────────────────────────────────────── */
/**
 *  @typedef ll_observer_cb
 *  Observer callback invoked synchronously when an event occurs.
 *
 *  @param[in] ctrl       Pointer to the emitting Controller instance
 *  @param[in] event      Event type
 *  @param[in] timestamp  Wall-clock time of the event
 *  @param[in] usr_ctx    User-supplied context pointer provided during
 *                        registration
 */
typedef void (*ll_observer_cb)(const ll_controller_t *ctrl,
                               ll_event_t              event,
                               time_t                  timestamp,
                               void                   *usr_ctx);

/* ────────────────────────────────────────────────────────────────────────── */
/*  API Functions                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 *  ll_controller_create()
 *  Instantiate a new Controller.
 *
 *  Thread-safety: Safe to call from multiple threads provided separate
 *                 instances are created (one thread per instance).
 *
 *  @param[in]  cfg   Pointer to a configuration structure (MUST NOT be NULL)
 *  @param[out] out   Receives an opaque handle on success
 *
 *  @return LL_STATUS_OK on success; otherwise an error code.
 */
ll_status_t
ll_controller_create(const ll_controller_cfg_t *cfg,
                     ll_controller_t          **out);

/**
 *  ll_controller_start()
 *  Start orchestrating scheduled pipelines and begin emitting events.
 *
 *  This call is asynchronous: it returns once background worker threads and
 *  timers have been initialized.
 *
 *  @param[in] ctrl  Controller handle obtained from ll_controller_create()
 *
 *  @return LL_STATUS_OK on success; otherwise an error code.
 */
ll_status_t
ll_controller_start(ll_controller_t *ctrl);

/**
 *  ll_controller_stop()
 *  Gracefully flush outstanding tasks and shut down the Controller.
 *
 *  After this call returns, the Controller handle becomes invalid and must be
 *  destroyed via ll_controller_destroy().
 *
 *  @param[in] ctrl  Controller handle
 *
 *  @return LL_STATUS_OK on success.
 */
ll_status_t
ll_controller_stop(ll_controller_t *ctrl);

/**
 *  ll_controller_destroy()
 *  Release all resources associated with a Controller instance.
 *
 *  Safe to call with NULL (no-op).
 */
void
ll_controller_destroy(ll_controller_t *ctrl);

/**
 *  ll_controller_trigger_training()
 *  Manually trigger a training job outside the regular schedule.
 *
 *  @param[in]  ctrl         Controller handle
 *  @param[in]  dataset_uri  URI referencing the dataset to train on
 *  @param[in]  exp_tag      Optional user-defined tag for experiment tracking
 *
 *  @return LL_STATUS_OK on success.
 */
ll_status_t
ll_controller_trigger_training(ll_controller_t *ctrl,
                               const char      *dataset_uri,
                               const char      *exp_tag /* nullable */);

/**
 *  ll_controller_schedule_retraining()
 *  Schedule an automated retraining job after the specified delay.
 *
 *  If the system restarts before the delay elapses, the job is persisted and
 *  will be executed upon Controller start-up.
 *
 *  @param[in]  ctrl          Controller instance
 *  @param[in]  delay_seconds Delay (≥ 60) before retraining commences
 *  @param[out] job           Optional handle to the scheduled job
 *
 *  @return LL_STATUS_OK or LL_STATUS_INVALID_ARGUMENT.
 */
ll_status_t
ll_controller_schedule_retraining(ll_controller_t  *ctrl,
                                  uint32_t          delay_seconds,
                                  ll_retrain_job_t **job /* nullable */);

/**
 *  ll_controller_cancel_retraining()
 *  Attempts to cancel a previously scheduled retraining job.
 *
 *  @param[in] ctrl  Controller instance
 *  @param[in] job   Retraining job handle as returned by
 *                   ll_controller_schedule_retraining()
 *
 *  @return LL_STATUS_OK               on success
 *          LL_STATUS_NOT_FOUND        if the job is unknown
 *          LL_STATUS_CONFLICT         if the job is already running/completed
 */
ll_status_t
ll_controller_cancel_retraining(ll_controller_t   *ctrl,
                                ll_retrain_job_t  *job);

/**
 *  ll_controller_register_observer()
 *  Subscribe to runtime events. Observers execute on the Controller's internal
 *  event loop thread; keep callbacks lightweight to avoid blocking.
 *
 *  @param[in] ctrl     Controller instance
 *  @param[in] cb       Observer callback
 *  @param[in] usr_ctx  User context forwarded to the callback
 *
 *  @return LL_STATUS_OK on success.
 */
ll_status_t
ll_controller_register_observer(ll_controller_t *ctrl,
                                ll_observer_cb   cb,
                                void            *usr_ctx);

/**
 *  ll_controller_unregister_observer()
 *  Remove a previously registered observer.
 *
 *  @note Unregistration is idempotent; attempting to remove a non-existent
 *        observer returns LL_STATUS_NOT_FOUND.
 */
ll_status_t
ll_controller_unregister_observer(ll_controller_t *ctrl,
                                  ll_observer_cb   cb,
                                  void            *usr_ctx);

/**
 *  ll_controller_get_version()
 *  Retrieve the semantic version string for the Controller API.
 *
 *  The returned pointer is guaranteed to remain valid for the duration of the
 *  process and must NOT be freed by the caller.
 */
const char *
ll_controller_get_version(void);

/**
 *  ll_status_to_string()
 *  Convert an ll_status_t value to a human-readable string.
 *
 *  @return NUL-terminated string literal.
 */
const char *
ll_status_to_string(ll_status_t status) __attribute__((const));

#ifdef __cplusplus
}   /* extern "C" */
#endif
#endif /* LEXILEARN_LL_CONTROLLER_H */
