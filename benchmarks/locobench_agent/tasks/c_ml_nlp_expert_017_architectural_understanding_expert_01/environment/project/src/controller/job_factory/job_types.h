/**
 * lexilearn_orchestrator/src/controller/job_factory/job_types.h
 *
 * Copyright (c) 2024
 * LexiLearn MVC Orchestrator — ml_nlp
 *
 * Description:
 *   Public type-definitions and helper utilities for representing
 *   controller-layer “jobs” that flow through the Pipeline Pattern
 *   orchestrator.  These definitions are shared between the job
 *   factory, scheduler, and runtime executor components.
 *
 *   The job layer is intentionally decoupled from any concrete model
 *   or data-processing implementation so that researchers can add new
 *   workflows (e.g., prompt-engineering, synthetic-data generation,
 *   LLM fine-tuning) without requiring changes to the core
 *   orchestration logic.
 *
 * Usage:
 *   #include "controller/job_factory/job_types.h"
 */

#ifndef LEXILEARN_CONTROLLER_JOB_TYPES_H
#define LEXILEARN_CONTROLLER_JOB_TYPES_H

/* ──────────────────────────────────────────────────────────────
 *  Standard Library Includes
 * ────────────────────────────────────────────────────────────── */
#include <stdint.h>     /* uint64_t, uint32_t */
#include <stdbool.h>    /* bool               */
#include <stddef.h>     /* size_t             >

/* ──────────────────────────────────────────────────────────────
 *  Export / Visibility Macros
 *  (build systems can override LEXILEARN_JOB_API to add
 *   compiler-specific visibility/export directives)
 * ────────────────────────────────────────────────────────────── */
#ifndef LEXILEARN_JOB_API
#   define LEXILEARN_JOB_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────
 *  Enumerations
 * ────────────────────────────────────────────────────────────── */

/**
 * job_type_e
 *
 * Enumerates the coarse-grained job categories supported by the
 * orchestrator.  Individual category parameters live in the union
 * `job_config_u` defined below.
 */
typedef enum
{
    JOB_TYPE_PREPROCESS = 0,       /* Data ingestion and cleansing */
    JOB_TYPE_FEATURE_ENGINEERING,  /* Transform raw data ➜ feature vectors */
    JOB_TYPE_TRAIN,                /* Initial training run          */
    JOB_TYPE_EVALUATE,             /* Model evaluation on hold-out  */
    JOB_TYPE_HPARAM_TUNE,          /* Hyper-parameter optimisation  */
    JOB_TYPE_MONITOR,              /* In-production model metrics   */
    JOB_TYPE_RETRAIN,              /* Automated retraining (drift)  */
    JOB_TYPE_EXPORT,               /* Push model artifact to store  */
    JOB_TYPE_CUSTOM,               /* Extension hook for plugins    */

    JOB_TYPE_MAX
} job_type_e;


/**
 * job_state_e
 *
 * Execution life-cycle of a job instance as viewed by the scheduler.
 */
typedef enum
{
    JOB_STATE_PENDING = 0,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCESS,
    JOB_STATE_FAILED,
    JOB_STATE_CANCELLED,
    JOB_STATE_MAX
} job_state_e;


/* ──────────────────────────────────────────────────────────────
 *  Primitive Type Aliases
 * ────────────────────────────────────────────────────────────── */

typedef uint64_t job_id_t;     /* Globally unique, monotonic */
typedef uint64_t epoch_ms_t;   /* UNIX epoch in milliseconds */


/* ──────────────────────────────────────────────────────────────
 *  Job-Specific Parameter Structures
 * ────────────────────────────────────────────────────────────── */

typedef struct
{
    /* Input artifact locations (e.g., S3, NFS, remote dataset registry) */
    char        dataset_uri[256];

    /* Text-specific preprocessing flags */
    bool        normalize_utf8;
    bool        remove_stopwords;
    bool        expand_contractions;

    /* Output dataset tag */
    char        output_alias[64];
} preprocess_params_t;


typedef struct
{
    /* Human-readable experiment label */
    char        experiment_name[128];

    /* Path to feature set if pre-computed */
    char        feature_set_uri[256];

    /* Model hyper-parameters (basic subset; full tuning lives elsewhere) */
    uint32_t    epochs;
    uint32_t    batch_size;
    float       learning_rate;

    /* Where to store resulting model artefact */
    char        output_model_uri[256];
} train_params_t;


typedef struct
{
    char        model_uri[256];
    char        testset_uri[256];

    /* Metrics of interest — comma separated string (e.g., "BLEU,ROUGE") */
    char        metrics[128];
} evaluate_params_t;


typedef struct
{
    /* Hyper-parameter search space file (YAML/JSON) */
    char        search_space_uri[256];

    /* Resource budget */
    uint32_t    max_trials;
    uint32_t    max_parallel_trials;

    /* Optional surrogate model checkpoint */
    char        warmstart_model_uri[256];
} hparam_tune_params_t;


typedef struct
{
    char        model_uri[256];

    /* Polling interval in seconds */
    uint32_t    interval_sec;

    /* Drift detection config */
    float       drift_threshold;
} monitor_params_t;


typedef struct
{
    /* Baseline model to compare against */
    char        baseline_model_uri[256];

    /* Training data where drift occurred */
    char        drifted_data_uri[256];

    /* Retrain hyper-parameters */
    uint32_t    epochs;
    uint32_t    batch_size;
} retrain_params_t;


/**
 * job_config_u
 *
 * Union of category-specific parameter payloads.
 */
typedef union
{
    preprocess_params_t     preprocess;
    train_params_t          train;
    evaluate_params_t       evaluate;
    hparam_tune_params_t    hparam_tune;
    monitor_params_t        monitor;
    retrain_params_t        retrain;

    /* Future extensions require only a new struct and a union field. */
} job_config_u;


/* ──────────────────────────────────────────────────────────────
 *  Job Metadata & Descriptor
 * ────────────────────────────────────────────────────────────── */

/**
 * job_metadata_t
 *
 * Lightweight struct capturing the run-time state of a job instance.
 */
typedef struct
{
    job_id_t        id;             /* Generated by scheduler */
    job_type_e      type;           /* Category               */
    job_state_e     state;          /* Current life-cycle      */

    /* Priority: 0 (lowest) ➜ 255 (highest) */
    uint8_t         priority;

    /* Audit fields — zero-terminated strings */
    char            created_by[64]; /* Username or service     */
    epoch_ms_t      created_ts;     /* Creation timestamp      */
    epoch_ms_t      updated_ts;     /* Last status update      */
} job_metadata_t;


/**
 * job_descriptor_t
 *
 * The canonical, scheduler-consumable definition of a job.  A
 * descriptor is immutable once submitted; create a new one for
 * each re-submission.
 */
typedef struct
{
    job_metadata_t  meta;
    job_config_u    config;
} job_descriptor_t;


/* ──────────────────────────────────────────────────────────────
 *  Helper Utilities
 * ────────────────────────────────────────────────────────────── */

/**
 * job_type_to_string
 *   Convert an enum tag into a static string literal.
 *
 * @param type (job_type_e)
 * @return      const char*      Pointer to read-only string.
 */
LEXILEARN_JOB_API
const char *
job_type_to_string(job_type_e type);


/**
 * job_state_to_string
 *   Convert a state enum into printable text.
 */
LEXILEARN_JOB_API
const char *
job_state_to_string(job_state_e state);


/**
 * job_descriptor_init
 *
 *   Convenience initializer ensuring that all fields are zeroed out
 *   and metadata is stamped with the caller-supplied parameters.
 *
 * @param out_desc      Destination descriptor (must be non-NULL)
 * @param type          Job category
 * @param creator       Name of requesting user/service
 * @return              0 on success, non-zero errno on failure
 */
LEXILEARN_JOB_API
int
job_descriptor_init(job_descriptor_t *out_desc,
                    job_type_e        type,
                    const char       *creator);


/**
 * job_generate_id
 *
 * Thread-safe, monotonic job ID generator.  The implementation is
 * provided by the scheduler’s persistence layer.  The header
 * merely exposes the symbol so that the factory can invoke it.
 *
 * @return  job_id_t    Unique identifier
 */
LEXILEARN_JOB_API
job_id_t
job_generate_id(void);


/* ──────────────────────────────────────────────────────────────
 *  Inlines
 * ────────────────────────────────────────────────────────────── */

static inline bool
job_is_terminal_state(job_state_e state)
{
    return state == JOB_STATE_SUCCESS ||
           state == JOB_STATE_FAILED  ||
           state == JOB_STATE_CANCELLED;
}


#ifdef __cplusplus
}   /* extern "C" */
#endif

#endif /* LEXILEARN_CONTROLLER_JOB_TYPES_H */
