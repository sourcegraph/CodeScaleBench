```c
/**
 * @file orchestrator.h
 * @author
 *      LexiLearn Core Team <core@lexilearn.ai>
 *
 * @brief Public interface for the LexiLearn MVC Orchestrator.
 *
 * The Orchestrator coordinates the Controller-layer Pipeline Pattern, wiring
 * Data Ingestion → Model Training → Model Registry → Monitoring/Drift-Detection
 * into a cohesive workflow that can be started, stopped, and dynamically
 * reconfigured at runtime.
 *
 * This header exposes a C-friendly API that allows external components (CLI,
 * HTTP server, unit tests, etc.) to interact with the Orchestrator without
 * leaking internal implementation details.  Thread-safety is guaranteed for
 * all public functions unless otherwise noted.
 *
 * ---------------------------------------------------------------------------
 *  Copyright (c) 2024
 *  LexiLearn, Inc.  All rights reserved.
 *  Licensed under the Apache License, Version 2.0 (the "License");
 * ---------------------------------------------------------------------------
 */

#ifndef LEXILEARN_ORCHESTRATOR_H
#define LEXILEARN_ORCHESTRATOR_H

/* ────────────────────────────────────────────────────────────────────────── */
/* System Headers                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>            /* bool, true, false                        */
#include <stddef.h>             /* size_t                                   */
#include <stdint.h>             /* uint32_t, etc.                           */
#include <time.h>               /* time_t                                   */

/* ────────────────────────────────────────────────────────────────────────── */
/* Compile-time Versioning                                                  */
/* ────────────────────────────────────────────────────────────────────────── */
#define LEXILEARN_ORCH_VERSION_MAJOR   1
#define LEXILEARN_ORCH_VERSION_MINOR   3
#define LEXILEARN_ORCH_VERSION_PATCH   0

#define LEXILEARN_ORCH_VERSION_STR  "1.3.0"

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward Declarations (opaque structs)                                     */
/* ────────────────────────────────────────────────────────────────────────── */
typedef struct ll_orchestrator      ll_orchestrator_t;
typedef struct ll_context           ll_context_t;    /* JSON-like runtime ctx */
typedef struct ll_training_job      ll_training_job_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Enumerations                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @enum ll_status_t
 * @brief Unified return codes produced by public Orchestrator APIs.
 */
typedef enum
{
    LL_STATUS_OK                = 0,  /* Success */
    LL_STATUS_EINVAL            = 1,  /* Invalid argument                  */
    LL_STATUS_ENOMEM            = 2,  /* Memory allocation failure         */
    LL_STATUS_ESTATE            = 3,  /* Invalid Orchestrator state        */
    LL_STATUS_EINTERNAL         = 4,  /* Unexpected internal error         */
    LL_STATUS_ETIMEOUT          = 5,  /* Blocking call timed out           */
    LL_STATUS_ENOTFOUND         = 6,  /* Resource not found                */
    LL_STATUS_EALREADY          = 7,  /* Operation already in progress     */
    LL_STATUS_EIO               = 8,  /* I/O failure                       */
} ll_status_t;


/**
 * @enum ll_log_level_t
 * @brief Verbosity level for callback-driven logging.
 */
typedef enum
{
    LL_LOG_TRACE = 0,
    LL_LOG_DEBUG,
    LL_LOG_INFO,
    LL_LOG_WARN,
    LL_LOG_ERROR,
    LL_LOG_FATAL
} ll_log_level_t;


/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration Structures                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * @struct ll_orchestrator_cfg_t
 * @brief User-supplied runtime configuration for the Orchestrator.
 *
 * All string pointers must remain valid for the lifetime of the Orchestrator.
 */
typedef struct
{
    /* Human-readable identifier shown in logs/metrics */
    const char        *instance_name;

    /* Max number of in-flight training jobs allowed */
    uint32_t           max_concurrent_jobs;

    /* URI of Feature Store, Model Registry, and Metrics back-ends */
    const char        *feature_store_uri;
    const char        *model_registry_uri;
    const char        *metrics_uri;

    /* Polling interval (in seconds) for drift-detection scans */
    uint32_t           drift_scan_interval_sec;

    /* Log level threshold delivered to registered logger callbacks */
    ll_log_level_t     log_level;

    /* Optional opaque pointer forwarded to all user-installed callbacks */
    void              *user_ctx;

} ll_orchestrator_cfg_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Callback Type Definitions                                                */
/* ────────────────────────────────────────────────────────────────────────── */

/* User-provided, thread-safe logging function. */
typedef void (*ll_logger_fn)(
        ll_log_level_t level,
        const char    *component,
        const char    *fmt,
        ...);

/**
 * @brief Ingestion callback triggered periodically by the Orchestrator.
 *
 * The callback must allocate a ll_context_t describing the newly ingested
 * dataset (e.g., JSON metadata, on-disk file locations).  Ownership of the
 * returned pointer is transferred to the Orchestrator.
 *
 * @param user_ctx   User context passed from ll_orchestrator_cfg_t::user_ctx
 * @param out_ctx    (OUT) Newly allocated ingestion context
 * @return           LL_STATUS_OK on success, else error code
 */
typedef ll_status_t (*ll_ingest_cb)(
        void            *user_ctx,
        ll_context_t   **out_ctx);

/**
 * @brief Factory callback that creates a training job for a given dataset.
 *
 * The factory can inspect `ingest_ctx` to decide which Strategy implementation
 * (BERT Summarizer, n-gram analyzer, etc.) should be constructed.
 *
 * @param user_ctx      Same pointer provided in ll_orchestrator_cfg_t::user_ctx
 * @param ingest_ctx    Immutable context belonging to the ingestion batch
 * @param out_job       (OUT) Newly created training job handle
 * @return              status code
 */
typedef ll_status_t (*ll_training_job_factory_cb)(
        void                   *user_ctx,
        const ll_context_t     *ingest_ctx,
        ll_training_job_t     **out_job);

/**
 * @brief Observer invoked when statistical drift is detected.
 *
 * @param user_ctx       Passed through from cfg
 * @param model_version  Version string of the affected model
 * @param drift_score    Magnitude of detected drift (0 = no drift)
 * @param timestamp      Wall-clock time of detection
 */
typedef void (*ll_drift_observer_cb)(
        void            *user_ctx,
        const char      *model_version,
        double           drift_score,
        time_t           timestamp);

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

/*----------------------------- Lifecycle ----------------------------------*/

/**
 * @brief Allocate and initialize an Orchestrator instance.
 *
 * @param cfg           Immutable configuration structure
 * @param logger_cb     Optional logger; may be NULL for silent operation
 * @param out_handle    (OUT) Newly created orchestrator
 * @return              status code
 */
ll_status_t
ll_orchestrator_create(
        const ll_orchestrator_cfg_t *cfg,
        ll_logger_fn                 logger_cb,
        ll_orchestrator_t          **out_handle);

/**
 * @brief Start all background worker threads.
 *
 * Safe to call from multiple threads; subsequent calls are ignored.
 */
ll_status_t
ll_orchestrator_start(
        ll_orchestrator_t *handle);

/**
 * @brief Signal the orchestrator to shut down and flush state.
 *
 * This call blocks until all in-flight jobs complete or the timeout expires.
 *
 * @param handle        Valid orchestrator
 * @param timeout_ms    0 = infinite
 */
ll_status_t
ll_orchestrator_stop(
        ll_orchestrator_t *handle,
        uint32_t           timeout_ms);

/**
 * @brief Release all resources associated with the orchestrator.
 *
 * You must call ll_orchestrator_stop() before destroy.
 */
void
ll_orchestrator_destroy(
        ll_orchestrator_t *handle);

/*-------------------------- Registration APIs -----------------------------*/

/**
 * @brief Register a data-ingestion source.
 *
 * The orchestrator will invoke the callback at a cadence determined by
 * internal heuristics (e.g., LMS event rate).  Multiple sources may be
 * registered; each runs independently.
 *
 * @return LL_STATUS_EALREADY if the same callback is registered twice.
 */
ll_status_t
ll_orchestrator_register_ingestion_source(
        ll_orchestrator_t *handle,
        ll_ingest_cb       ingest_fn);

/**
 * @brief Register a factory that generates training jobs.
 *
 * Exactly one factory must be registered before starting the orchestrator.
 */
ll_status_t
ll_orchestrator_register_training_factory(
        ll_orchestrator_t           *handle,
        ll_training_job_factory_cb   factory_fn);

/**
 * @brief Register an observer for model-drift events.
 *
 * Observers may be added/removed at runtime; they are executed on a
 * dedicated internal thread to avoid blocking the main pipeline.
 */
ll_status_t
ll_orchestrator_register_drift_observer(
        ll_orchestrator_t    *handle,
        ll_drift_observer_cb  observer_fn);

/*-------------------------- Manual Operations -----------------------------*/

/**
 * @brief Manually inject a dataset for immediate training.
 *
 * This is useful for A/B tests or urgent re-training outside scheduled
 * pipelines.  Ownership of `ingest_ctx` moves to the Orchestrator.
 */
ll_status_t
ll_orchestrator_submit_manual_training(
        ll_orchestrator_t *handle,
        ll_context_t      *ingest_ctx);

/**
 * @brief Return last error stored in thread-local errno-style slot.
 *
 * Intended for logging after a function returns LL_STATUS_EINTERNAL.
 */
const char *
ll_orchestrator_last_error(void);

/* ------------------------------------------------------------------------- */
/*             Utility helpers exposed for advanced integrations             */
/* ------------------------------------------------------------------------- */

/**
 * @brief Convert status code to human-readable string.
 */
static inline const char *
ll_status_to_str(ll_status_t st)
{
    switch (st) {
        case LL_STATUS_OK:         return "OK";
        case LL_STATUS_EINVAL:     return "Invalid argument";
        case LL_STATUS_ENOMEM:     return "Out of memory";
        case LL_STATUS_ESTATE:     return "Invalid state";
        case LL_STATUS_EINTERNAL:  return "Internal error";
        case LL_STATUS_ETIMEOUT:   return "Timeout";
        case LL_STATUS_ENOTFOUND:  return "Not found";
        case LL_STATUS_EALREADY:   return "Already exists / in progress";
        case LL_STATUS_EIO:        return "I/O error";
        default:                   return "Unknown status";
    }
}

#endif /* LEXILEARN_ORCHESTRATOR_H */
```