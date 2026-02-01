```c
/**
 *  lexilearn_orchestrator/src/controller/monitoring/model_monitor.h
 *
 *  Copyright (c) 2024 LexiLearn
 *
 *  Production-grade interface for Controller-level Model Monitoring.
 *  -----------------------------------------------------------------
 *  The Model Monitor is responsible for:
 *    • Persistently tracking model-level metrics (latency, accuracy, drift, etc.)
 *    • Emitting Observer-pattern events to trigger automated retraining
 *    • Acting as an abstraction layer so that multiple drift-detection
 *      strategies can be swapped in without touching higher-level code
 *    • Interfacing with the Model Registry to tag / version promoted models
 *
 *  This header intentionally contains no implementation logic—only the public
 *  contracts meant to be consumed by the Controller’s Pipeline components
 *  and, where relevant, by View-layer dashboards.
 */

#ifndef LEXILEARN_CONTROLLER_MONITORING_MODEL_MONITOR_H
#define LEXILEARN_CONTROLLER_MONITORING_MODEL_MONITOR_H

/* --- Standard Library ---------------------------------------------------- */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*                               Versioning                                  */
/* ------------------------------------------------------------------------- */

#define MODEL_MONITOR_VERSION_MAJOR  1
#define MODEL_MONITOR_VERSION_MINOR  0
#define MODEL_MONITOR_VERSION_PATCH  0

/* ------------------------------------------------------------------------- */
/*                               Error Codes                                 */
/* ------------------------------------------------------------------------- */

typedef enum {
    MM_OK = 0,                  /* Success */
    MM_ERR_INVALID_ARG = -1,    /* Invalid function argument */
    MM_ERR_MEM_ALLOC   = -2,    /* Memory allocation failure */
    MM_ERR_IO          = -3,    /* Persistent-store I/O failure */
    MM_ERR_STATE       = -4,    /* Monitor is in invalid state */
    MM_ERR_INTERNAL    = -5,    /* Catch-all for unexpected errors */
} mm_status_t;

/* ------------------------------------------------------------------------- */
/*                           Model Metrics & Tags                            */
/* ------------------------------------------------------------------------- */

/* High-level KPI buckets. Extend as needed. */
typedef struct {
    double accuracy;              /* Macro accuracy or other figure of merit */
    double f1_score;              /* Weighted F1 */
    double precision;
    double recall;

    double latency_ms;            /* Avg/95th-percentile inference latency */
    double throughput_qps;        /* Queries per second */

    double data_drift;            /* e.g., Population-stability index (PSI) */
    double concept_drift;         /* e.g., Sudden change detection score */

    time_t snapshot_time_utc;     /* When metrics were observed */
} mm_metrics_t;

/* Opaque handle to a registered model instance */
typedef struct mm_model_handle_s mm_model_handle_t;

/* Enum of Observer events emitted by the monitor */
typedef enum {
    MM_EVENT_METRIC_UPDATE,       /* Triggered whenever metrics are updated */
    MM_EVENT_DRIFT_DETECTED,      /* Data or concept drift threshold crossed */
    MM_EVENT_RETRAIN_TRIGGERED,   /* Automated retrain job has been scheduled */
    MM_EVENT_ERROR                /* A non-recoverable error has occurred */
} mm_event_type_t;

typedef struct {
    mm_event_type_t type;
    mm_status_t     status;       /* Relevant for MM_EVENT_ERROR */
    mm_metrics_t    latest_metrics;
    const char     *msg;          /* Human-readable, may be NULL */
} mm_event_t;

/* Observer callback signature */
typedef void (*mm_observer_fn)(const mm_event_t *event, void *user_data);

/* ------------------------------------------------------------------------- */
/*                       Strategy: Drift-Detector API                        */
/* ------------------------------------------------------------------------- */

/*
 * Implementations must adhere to this interface and register themselves
 * via mm_register_drift_detector(). See docs/DriftDetectorPlugin.md
 */

typedef struct {
    /* Initialize detector for a specific model and baseline metrics. */
    mm_status_t (*init)(mm_model_handle_t   *model,
                        const mm_metrics_t  *baseline);

    /* Feed real-time metrics into the detector. */
    mm_status_t (*update)(const mm_metrics_t *current_metrics,
                          bool               *drift_detected);

    /* Optional: return a human-readable diagnostic message. */
    const char *(*diagnostics)(void);

    /* Clean up any resources. */
    void (*destroy)(void);
} mm_drift_detector_vtbl_t;

/* ------------------------------------------------------------------------- */
/*                              Public  API                                  */
/* ------------------------------------------------------------------------- */

/**
 * mm_init()
 * ----------------------------------------------------------------------
 * Global initialization that must be invoked once during Controller start-up.
 * @return MM_OK or error code
 */
mm_status_t mm_init(void);

/**
 * mm_shutdown()
 * ----------------------------------------------------------------------
 * Flush all outstanding metrics, close persistent stores, and free memory.
 */
void mm_shutdown(void);

/**
 * mm_model_register()
 * ----------------------------------------------------------------------
 * Register a model instance with the monitor. A handle is returned on
 * success and must be released with mm_model_unregister().
 *
 * @param model_id        Unique identifier from Model Registry, NUL-terminated
 * @param baseline        Baseline metrics collected during validation
 * @param handle_out      Output: opaque model handle
 * @return                MM_OK or error code
 */
mm_status_t mm_model_register(const char        *model_id,
                              const mm_metrics_t *baseline,
                              mm_model_handle_t **handle_out);

/**
 * mm_model_unregister()
 * ----------------------------------------------------------------------
 * Releases internal resources associated with a model handle.
 */
mm_status_t mm_model_unregister(mm_model_handle_t *handle);

/**
 * mm_submit_metrics()
 * ----------------------------------------------------------------------
 * Ingest runtime metrics for a given model. May be invoked from multiple
 * threads (internally synchronized).
 *
 * @param handle          Model handle obtained from mm_model_register()
 * @param metrics         Metrics snapshot
 * @return                MM_OK or error code
 */
mm_status_t mm_submit_metrics(mm_model_handle_t *handle,
                              const mm_metrics_t *metrics);

/**
 * mm_add_observer()
 * ----------------------------------------------------------------------
 * Register an observer that listens for MM_EVENT_* events. Thread-safe.
 *
 * @param handle          Model handle (or NULL to subscribe globally)
 * @param fn              Callback function
 * @param user_data       Opaque pointer passed back to observer
 * @return                MM_OK or error code
 */
mm_status_t mm_add_observer(mm_model_handle_t *handle,
                            mm_observer_fn     fn,
                            void              *user_data);

/**
 * mm_remove_observer()
 *
 * Removes a previously registered observer. Safe to call from within the
 * callback itself (will take effect after callback returns).
 */
mm_status_t mm_remove_observer(mm_model_handle_t *handle,
                               mm_observer_fn     fn,
                               void              *user_data);

/**
 * mm_register_drift_detector()
 * ----------------------------------------------------------------------
 * Plug-in a new drift detection strategy. The detector becomes available
 * system-wide; individual models can opt in via configuration.
 *
 * @param name            Unique plugin name (e.g., "PSI", "KS-Test")
 * @param vtbl            Function table implementing the detector
 * @return                MM_OK or error code
 */
mm_status_t mm_register_drift_detector(const char               *name,
                                       const mm_drift_detector_vtbl_t *vtbl);

/**
 * mm_force_retrain()
 * ----------------------------------------------------------------------
 * Imperative API to bypass thresholds and force a retrain cycle.
 * Mainly useful for A/B testing or hot-fix releases.
 */
mm_status_t mm_force_retrain(mm_model_handle_t *handle,
                             const char        *reason);

/* ------------------------------------------------------------------------- */
/*                               Utilities                                   */
/* ------------------------------------------------------------------------- */

/* Convenience macro to embed current source location in diagnostic logs. */
#define MM_SRC_LOC  __FILE__, __LINE__, __func__

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_CONTROLLER_MONITORING_MODEL_MONITOR_H */
```