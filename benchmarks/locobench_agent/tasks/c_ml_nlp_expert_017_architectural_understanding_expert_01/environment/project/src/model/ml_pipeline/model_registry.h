/**
 *  LexiLearn MVC Orchestrator – Model Registry Public Interface
 *  -------------------------------------------------------------
 *  File:    model_registry.h
 *  Project: LexiLearn NLP / ML Pipeline
 *
 *  Author:  LexiLearn Core Team
 *  License: Apache 2.0
 *
 *  Description:
 *      Production-grade, thread-safe C API for LexiLearn’s on-disk /
 *      remote (future) Model Registry.  The registry tracks the full
 *      life-cycle of ML models—versioning, stage promotion, metadata,
 *      and lineage—for reproducible research and robust MLOps.
 *
 *  Usage:
 *      #include "model_registry.h"
 *
 *      if (ml_registry_init("/var/lib/lexilearn/registry") != ML_OK)
 *          die(ml_registry_last_error());
 *
 *      char model_id[ML_MODEL_ID_MAX] = {0};
 *      ml_registry_register_model("hybrid-summarizer",
 *                                 "v1.3.4",
 *                                 "/models/hybrid-summarizer_v1.3.4.bin",
 *                                 "{\"lr\":0.0001, \"epochs\":12}",
 *                                 "{\"val_bleu\":0.87}",
 *                                 "b01cbe6",
 *                                 model_id,
 *                                 sizeof(model_id));
 *
 *      ml_registry_shutdown();
 */

#ifndef LEXILEARN_MODEL_REGISTRY_H
#define LEXILEARN_MODEL_REGISTRY_H

/* ────────────────────────────────────────────────────────────────────────── */
/*  System Headers                                                           */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stddef.h>     /* size_t      */
#include <stdint.h>     /* uint64_t    */
#include <time.h>       /* time_t      */
#include <stdio.h>      /* FILE        */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Feature Flags / Config                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

#ifndef ML_REGISTRY_THREAD_SAFE
#define ML_REGISTRY_THREAD_SAFE 1
#endif

/* Maximum byte length for a model identifier (“{strategy}:{hash}”)          */
#define ML_MODEL_ID_MAX          128

/* JSON blobs are stored in TEXT columns – reasonable upper bound            */
#define ML_JSON_MAX              8192

/* Strategy name ≤ 64 chars; version tag ≤ 32 chars                          */
#define ML_STRATEGY_MAX          64
#define ML_VERSION_TAG_MAX       32

/* Internal filesystem limits                                               */
#define ML_PATH_MAX              4096

/* ────────────────────────────────────────────────────────────────────────── */
/*  Error Handling                                                           */
/* ────────────────────────────────────────────────────────────────────────── */

typedef enum
{
    ML_OK = 0,
    ML_ERR_INIT          = -1,
    ML_ERR_SHUTDOWN      = -2,
    ML_ERR_IO            = -3,
    ML_ERR_MEMORY        = -4,
    ML_ERR_INVALID_ARG   = -5,
    ML_ERR_NOT_FOUND     = -6,
    ML_ERR_CONFLICT      = -7,
    ML_ERR_SERIALIZATION = -8,
    ML_ERR_UNKNOWN       = -100
} ml_error_t;

/**
 * Returns a thread-local, NULL-terminated string describing the last error.
 * The pointer is owned by the registry and MUST NOT be freed by the caller.
 */
const char *ml_registry_last_error(void);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Model Metadata Structures                                                */
/* ────────────────────────────────────────────────────────────────────────── */

/* Model stage / life-cycle gates                                            */
typedef enum
{
    ML_STAGE_EXPERIMENT = 0,  /* Default after registration                 */
    ML_STAGE_STAGING    = 1,  /* Candidate awaiting production sign-off     */
    ML_STAGE_PRODUCTION = 2,  /* Actively serving recommendations           */
    ML_STAGE_ARCHIVED   = 3   /* Frozen for audit or rollback               */
} ml_model_stage_t;

/* Primary key is a deterministic string: <strategy>::<git-sha>              */
typedef struct
{
    char             model_id[ML_MODEL_ID_MAX];   /* PK                     */
    char             strategy[ML_STRATEGY_MAX];   /* Strategy pattern key   */
    char             version_tag[ML_VERSION_TAG_MAX]; /* “v1.2.3”           */
    char             artifact_path[ML_PATH_MAX];  /* Path to binary / pkl   */

    /* JSON blobs: hyper-parameters, metrics, & additional metadata          */
    char             hyperparams_json[ML_JSON_MAX];
    char             metrics_json[ML_JSON_MAX];

    char             git_commit_sha[16];          /* short SHA (7–15 chars) */
    ml_model_stage_t stage;                       /* Current stage          */

    time_t           created_at;                  /* Registration timestamp */
    time_t           last_updated;                /* Stage promotion, etc.  */

} ml_model_record_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Registry Lifecycle                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Initializes / opens the registry at the given root directory.
 * This call is idempotent.  Multiple opens simply bump an internal ref-count.
 *
 * Parameters:
 *   registry_root – absolute path to directory containing registry.db & blobs
 *
 * Returns:
 *   ML_OK on success, negative error code otherwise.
 */
ml_error_t ml_registry_init(const char *registry_root);

/**
 * Flushes pending IO and releases resources.  Balanced with ml_registry_init().
 * The registry may remain open if other references are active.
 */
ml_error_t ml_registry_shutdown(void);

/* ────────────────────────────────────────────────────────────────────────── */
/*  CRUD – Create                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Registers a new model artifact & metadata into the registry.  Function is
 * atomic; either all metadata are flushed to disk or an error is returned.
 *
 * Parameters:
 *   strategy_name     – logical family (e.g., “transformer-summarizer”)
 *   version_tag       – human-readable tag (“v2.1-alpha”)
 *   artifact_path     – absolute / relative path to binary artifact
 *   hyperparams_json  – serialized hyperparameters (may be NULL / "")
 *   metrics_json      – serialized evaluation metrics (may be NULL / "")
 *   git_commit_sha    – optional SCM commit for code–model lineage
 *   out_model_id      – buffer where unique model_id will be written
 *   out_model_id_len  – size of the above buffer
 *
 * Returns:
 *   ML_OK on success, error code otherwise.
 */
ml_error_t ml_registry_register_model(const char *strategy_name,
                                      const char *version_tag,
                                      const char *artifact_path,
                                      const char *hyperparams_json,
                                      const char *metrics_json,
                                      const char *git_commit_sha,
                                      char       *out_model_id,
                                      size_t      out_model_id_len);

/* ────────────────────────────────────────────────────────────────────────── */
/*  CRUD – Read                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Retrieves a model record by ID.
 *
 * Parameters:
 *   model_id   – composite key returned by ml_registry_register_model
 *   out_record – caller-allocated pointer; filled on success
 *
 * Returns:
 *   ML_OK or ML_ERR_NOT_FOUND.
 */
ml_error_t ml_registry_get_model(const char *model_id,
                                 ml_model_record_t *out_record);

/**
 * Returns the latest (by created_at) model for a given strategy & stage.
 * Useful when Controllers need “latest stable” automatically.
 *
 * Parameters:
 *   strategy_name – e.g., “n_gram_analyzer”
 *   desired_stage – ML_STAGE_STAGING / ML_STAGE_PRODUCTION, etc.
 *   out_model_id  – buffer to receive the model_id
 *   len           – bytes available in buffer
 */
ml_error_t ml_registry_get_latest_model(const char    *strategy_name,
                                        ml_model_stage_t desired_stage,
                                        char           *out_model_id,
                                        size_t          len);

/**
 * Lists all models for a given strategy.  The registry allocates an array that
 * the caller MUST free via ml_registry_free_model_list().
 *
 * Parameters:
 *   strategy_name – filter; NULL for all strategies
 *   out_list      – on success, *out_list points to malloc-ed array
 *   out_count     – number of elements in array
 */
ml_error_t ml_registry_list_models(const char  *strategy_name,
                                   ml_model_record_t **out_list,
                                   size_t *out_count);

/**
 * Releases memory returned by ml_registry_list_models().
 */
void ml_registry_free_model_list(ml_model_record_t *list);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Update                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Promotes / demotes a model to a new stage (e.g., STAGING → PRODUCTION).
 * Audit information is automatically appended in an internal changelog.
 */
ml_error_t ml_registry_set_stage(const char *model_id, ml_model_stage_t new_stage);

/**
 * Adds / overwrites metrics for an existing model, used by continuous eval.
 */
ml_error_t ml_registry_update_metrics(const char *model_id,
                                      const char *metrics_json);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Delete / Garbage Collection                                              */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Archives a model and optionally removes its artifact from disk to reclaim
 * storage.  For compliance, metadata are retained unless hard_delete is true.
 */
ml_error_t ml_registry_archive_model(const char *model_id, int hard_delete);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Observability                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Exports a read-only FILE* handle to the registry’s change-feed, suitable for
 * tail-f style monitoring or integration with Observer Pattern hooks that
 * trigger automated retraining.
 *
 * Note: Returned FILE* is shared; do NOT fclose().  Call ml_registry_unwatch().
 */
FILE *ml_registry_watch(void);

/* Balances ml_registry_watch(); flushes & detaches the stream. */
void ml_registry_unwatch(FILE *stream);

/* ────────────────────────────────────────────────────────────────────────── */
/*  Thread-Safety Internals (opaque to API consumers)                        */
/* ────────────────────────────────────────────────────────────────────────── */

#if ML_REGISTRY_THREAD_SAFE
#include <pthread.h>
typedef pthread_mutex_t ml_mutex_t;
#else
typedef int ml_mutex_t;  /* Dummy placeholder for single-thread builds */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Inline Convenience Helpers                                               */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Returns non-zero if the stage is production-ready (STAGING or PRODUCTION).
 */
static inline int ml_stage_is_stable(ml_model_stage_t stage)
{
    return stage == ML_STAGE_STAGING || stage == ML_STAGE_PRODUCTION;
}

/* ────────────────────────────────────────────────────────────────────────── */

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_REGISTRY_H */
