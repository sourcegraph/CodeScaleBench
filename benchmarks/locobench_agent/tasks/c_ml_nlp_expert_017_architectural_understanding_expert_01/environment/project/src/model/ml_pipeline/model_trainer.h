/**
 *  LexiLearn MVC Orchestrator – Model Trainer (Header)
 *  ---------------------------------------------------
 *  File:    model_trainer.h
 *  Author:  LexiLearn Engineering Team
 *  License: Apache-2.0
 *
 *  Description
 *  ===========
 *  Public interface for the Model-Trainer component, responsible for:
 *    • Coordinating data-pre-processing & feature engineering
 *    • Performing hyper-parameter tuning (grid, random, Bayesian, etc.)
 *    • Fitting candidate models and selecting the champion
 *    • Persisting artifacts to the shared Model Registry
 *    • Emitting Observer hooks for real-time monitoring / drift detection
 *
 *  The implementation (model_trainer.c) hides its internal state behind an
 *  opaque pointer to preserve ABI compatibility and allow incremental
 *  refactors without breaking dependent code.
 */

#ifndef LEXILEARN_MODEL_TRAINER_H_
#define LEXILEARN_MODEL_TRAINER_H_

/* ────────────── Standard Library ────────────── */
#include <stddef.h>   /* size_t  */
#include <stdint.h>   /* uint32_t, int64_t */
#include <stdbool.h>  /* bool    */

/* ────────────── LexiLearn Core  ─────────────── */
#include "ml_error.h"         /* Unified error codes across Model layer       */
#include "feature_store.h"    /* Shared feature ledger                         */
#include "model_registry.h"   /* Artifact persistence & version control        */
#include "dataset.h"          /* Canonical dataset representation              */
#include "metrics.h"          /* Evaluation metrics abstraction                */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────────
 * Enumerations & Constants
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * ll_trainer_status_t
 * Descriptive status codes specific to the trainer.
 * Always map to / extend the global ml_err_t set.
 */
typedef enum
{
    LL_TRAINER_OK            =  ML_OK,        /* Success                           */
    LL_TRAINER_INTERRUPTED   =  ML_EINTR,     /* Training job was interrupted      */
    LL_TRAINER_BAD_ARGUMENT  =  ML_EINVAL,    /* Invalid input parameter           */
    LL_TRAINER_OUT_OF_MEMORY =  ML_ENOMEM,    /* Allocation failure                */
    LL_TRAINER_IO_ERROR      =  ML_EIO,       /* I/O error (feature store, FS)     */
    LL_TRAINER_INTERNAL      =  ML_EINTERNAL  /* Generic internal failure          */
} ll_trainer_status_t;

/**
 * ll_tuning_strategy_t
 * Strategy pattern for hyper-parameter search.
 */
typedef enum
{
    LL_TUNING_GRID_SEARCH = 0,
    LL_TUNING_RANDOM_SEARCH,
    LL_TUNING_BAYES_OPT,
    LL_TUNING_NONE  /* Skip tuning, use default parameters */
} ll_tuning_strategy_t;


/* ────────────────────────────────────────────────────────────────────────────
 * Forward declarations & opaque handles
 * ────────────────────────────────────────────────────────────────────────── */

/* Opaque handle – actual definition lives in model_trainer.c */
typedef struct ll_model_trainer       ll_model_trainer_t;

/* Handle for final training results (metrics, artifact paths, etc.) */
typedef struct ll_training_result     ll_training_result_t;

/* ────────────────────────────────────────────────────────────────────────────
 * Data-Structures
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * ll_hparam_space_t
 * Describe a hyper-parameter search space.  The trainer copies the
 * definition internally; caller may free the struct after create().
 */
typedef struct
{
    const char *json_schema;  /* JSON-schema-encoded search space definition */
    size_t      schema_len;   /* Size in bytes ( json_schema is *not*
                                 required to be NUL-terminated )            */
} ll_hparam_space_t;


/**
 * ll_trainer_config_t
 * Aggregate configuration for a training job.
 */
typedef struct
{
    const char           *experiment_name; /* Name that appears in registry          */
    uint32_t              random_seed;     /* RNG seed for reproducibility           */
    ll_tuning_strategy_t  tuning_strategy; /* Hyper-parameter search algorithm       */
    uint32_t              max_trials;      /* # of tuning trials (if applicable)     */
    uint32_t              max_epochs;      /* Safety cap for training loops          */
    double                early_stop_delta;/* Min. improvement to avoid early stop   */

    /* Optional components (may be NULL) */
    ll_feature_store_t   *feature_store;   /* Pre-computed feature ledger            */
    ll_model_registry_t  *model_registry;  /* Artifact registry (versioning)         */

} ll_trainer_config_t;


/* ────────────────────────────────────────────────────────────────────────────
 * API
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * ll_model_trainer_create
 * -----------------------
 * Allocate and initialize a trainer instance.
 *
 * Parameters
 *   cfg          – Configuration parameters (deep-copied by the trainer)
 *   hparam_space – Hyper-parameter search space definition (nullable)
 *   out_handle   – Returns the created trainer pointer on success
 *
 * Returns
 *   LL_TRAINER_OK on success, otherwise an ll_trainer_status_t error code.
 */
ll_trainer_status_t
ll_model_trainer_create(const ll_trainer_config_t  *cfg,
                        const ll_hparam_space_t    *hparam_space,
                        ll_model_trainer_t        **out_handle);


/**
 * ll_model_trainer_destroy
 * ------------------------
 * Destroy the trainer and free all allocated resources.
 *
 * Safe to call with NULL.
 */
void
ll_model_trainer_destroy(ll_model_trainer_t *trainer);


/**
 * ll_model_trainer_set_dataset
 * ----------------------------
 * Provide the dataset used for training/validation.
 *
 * The trainer will retain a *reference* to the dataset; callers must
 * ensure that `dataset` remains valid until destroy() or replace.
 */
ll_trainer_status_t
ll_model_trainer_set_dataset(ll_model_trainer_t *trainer,
                             const ll_dataset_t *dataset);


/**
 * ll_model_trainer_register_observer
 * ----------------------------------
 * Register an external callback that is invoked whenever a new metric or
 * artifact becomes available (Observer Pattern).
 *
 * Parameters
 *   trainer     – Trainer instance
 *   ctx         – Arbitrary user context forwarded to the callback
 *   on_update   – Callback fired on metric update / drift detection
 *
 * Returns
 *   Status code.
 */
typedef void (*ll_trainer_observer_cb)(void *ctx,
                                       const ll_metric_snapshot_t *metrics);

ll_trainer_status_t
ll_model_trainer_register_observer(ll_model_trainer_t   *trainer,
                                   void                 *ctx,
                                   ll_trainer_observer_cb on_update);


/**
 * ll_model_trainer_start
 * ----------------------
 * Launch the training job synchronously.
 *
 * Parameters
 *   trainer      – Trainer instance
 *   out_result   – Populated with final metrics & artifact locations
 *                  (caller must free via ll_model_trainer_free_result()).
 *
 * Thread-Safety
 *   Non-blocking; internally spawns worker threads so the caller remains
 *   responsive to cancellation via stop().
 */
ll_trainer_status_t
ll_model_trainer_start(ll_model_trainer_t     *trainer,
                       ll_training_result_t  **out_result);


/**
 * ll_model_trainer_stop
 * ---------------------
 * Request graceful cancellation.  May block until workers exit.
 *
 * Returns
 *   LL_TRAINER_OK               – Cancellation succeeded
 *   LL_TRAINER_INTERRUPTED      – Training already interrupted
 *   LL_TRAINER_BAD_ARGUMENT     – Invalid trainer handle
 */
ll_trainer_status_t
ll_model_trainer_stop(ll_model_trainer_t *trainer);


/**
 * ll_model_trainer_progress
 * -------------------------
 * Query the job’s progress.
 *
 * Parameters
 *   trainer     – Trainer instance
 *   out_percent – Completion percentage in range [0.0, 100.0]
 */
ll_trainer_status_t
ll_model_trainer_progress(const ll_model_trainer_t *trainer,
                          double                   *out_percent);


/**
 * ll_model_trainer_free_result
 * ----------------------------
 * Free resources associated with a training result.
 */
void
ll_model_trainer_free_result(ll_training_result_t *result);


/* ────────────────────────────────────────────────────────────────────────────
 * Convenience Helpers
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * ll_trainer_status_str
 * ---------------------
 * Translate a status code to human-readable text.
 */
const char *
ll_trainer_status_str(ll_trainer_status_t status);


#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_TRAINER_H_ */
