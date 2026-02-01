/**
 *  lexilearn_orchestrator/src/controller/job_factory/job_factory.h
 *
 *  Copyright (c) 2024
 *  LexiLearn MVC Orchestrator (ml_nlp)
 *
 *  MIT License
 *
 *  A production-quality Factory interface for allocating, configuring, and
 *  destroying asynchronous controller–pipeline jobs.  The interface is used
 *  by the Pipeline Scheduler and the Drift-Observer hooks to decouple job
 *  creation logic from the execution engine.  Each job encapsulates the
 *  metadata necessary to reproduce an experiment in a fully–traceable,
 *  MLOps-compliant manner (e.g., run_id, git SHA, data snapshot id, hyper-
 *  parameter grid, etc.).
 *
 *  The Job abstraction is intentionally generic; concrete sub-jobs are
 *  expressed via the enum `ll_job_kind_e` and the opaque payload pointer
 *  `void *payload`.  The implementation (.c) file is responsible for casting
 *  this payload into the appropriate structure based on `kind`.
 */

#ifndef LEXILEARN_ORCHESTRATOR_JOB_FACTORY_H
#define LEXILEARN_ORCHESTRATOR_JOB_FACTORY_H

/*───────────────────────────  System Includes  ────────────────────────────*/
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <time.h>

/*───────────────────────────  Public Constants  ───────────────────────────*/
/* Maximum length for id-strings (run id, model id, etc.) */
#define LL_JOB_MAX_ID          64
#define LL_JOB_MAX_TAGS        16   /* Maximum number of arbitrary tags */
#define LL_JOB_MAX_TAG_LENGTH  32

/*──────────────────────────   Error Codes   ───────────────────────────────*/
typedef enum {
    LL_JOB_OK = 0,
    LL_JOB_EINVAL,        /* Invalid argument supplied */
    LL_JOB_ENOMEM,        /* Memory allocation failed  */
    LL_JOB_EUNKNOWN       /* Unknown/unspecified error */
} ll_job_status_e;

/*───────────────────────────  Job Kind Enum  ──────────────────────────────*/
typedef enum {
    LL_JOB_TRAIN_MODEL = 0,       /* First-time supervised training                */
    LL_JOB_HYPERPARAM_TUNE,       /* Hyper-parameter grid / Bayesian optimisation  */
    LL_JOB_RETRAIN_MODEL,         /* Triggered by concept drift                    */
    LL_JOB_DATA_PREPROCESS,       /* Batch or incremental ETL                      */
    LL_JOB_MODEL_MONITOR,         /* Metrics/alert job                             */
    LL_JOB_MODEL_VERSION_ROLLOUT, /* Canary or blue-green deployment               */
    LL_JOB_KIND_COUNT             /* Sentinel, keep last                           */
} ll_job_kind_e;

/*────────────────────────────  Forward Decls  ─────────────────────────────*/
/* Concrete payload structures live in the .c implementation. */
struct ll_train_payload;
struct ll_tune_payload;
struct ll_retrain_payload;
struct ll_preproc_payload;
struct ll_monitor_payload;
struct ll_version_payload;

/*───────────────────────────  Job Structure   ─────────────────────────────*/
typedef struct ll_job {
    /* Unique identifier (monotonically-increasing or UUID) */
    char        job_id[LL_JOB_MAX_ID];

    /* The fully-qualified user who submitted the job
       (supports audit-trail requirements). */
    char        submitted_by[LL_JOB_MAX_ID];

    /* Unix epoch (UTC) – creation time. */
    time_t      created_at;

    /* The specific job flavour. */
    ll_job_kind_e kind;

    /* Zero or more arbitrary string tags (null-terminated). */
    char        tags[LL_JOB_MAX_TAGS][LL_JOB_MAX_TAG_LENGTH];
    size_t      tag_count;

    /* Opaque pointer to kind-specific payload.  Ownership is transferred to
       the job object; free via job_factory_destroy(). */
    void       *payload;

    /* Free-form pointer reserved for orchestration engine (e.g., future
       cancellation tokens or tracing spans).  Not touched by the factory. */
    void       *extension;
} ll_job_t;

/*───────────────────────────  Factory API  ────────────────────────────────*/
/**
 *  @brief Allocate and initialise a new job.
 *
 *  The caller provides the job kind and a fully-populated payload struct
 *  (specific to that kind).  The factory deep-copies the payload to decouple
 *  ownership.  Use job_factory_destroy() to free.
 *
 *  @param kind          The job type (training, tuning, etc.).
 *  @param payload_src   Pointer to the concrete payload struct.
 *  @param[out] job_out  On success, *job_out contains a valid job pointer.
 *
 *  @return ll_job_status_e
 */
ll_job_status_e
job_factory_create(ll_job_kind_e   kind,
                   const void     *payload_src,
                   ll_job_t      **job_out);

/**
 *  @brief Destroy a job and all of its internally-allocated resources.
 *
 *  The pointer is set to NULL on return.
 */
void
job_factory_destroy(ll_job_t **job);

/**
 *  @brief Serialise a job into canonical JSON (RFC 8259) for inter-process
 *         transmission or audit storage.
 *
 *  The buffer is heap-allocated; caller must free().
 *
 *  @param job        Job to serialise.
 *  @param[out] json  On success, *json points to a null-terminated buffer.
 *
 *  @return ll_job_status_e
 */
ll_job_status_e
job_factory_to_json(const ll_job_t *job, char **json);

/**
 *  @brief Parse a job from canonical JSON.
 *
 *  @param json          Null-terminated JSON string.
 *  @param[out] job_out  New job instance (must be destroyed by caller).
 *
 *  @return ll_job_status_e
 */
ll_job_status_e
job_factory_from_json(const char *json, ll_job_t **job_out);

/**
 *  @brief Human-readable string for job kind (owned by library, do not free).
 */
const char *
job_factory_kind_str(ll_job_kind_e kind);

/*────────────────────────────  Utilities  ─────────────────────────────────*/
/**
 *  @brief Generate a cryptographically secure random job id.
 *
 *  Implementation uses OS-specific secure RNG (/dev/urandom, getrandom(),
 *  or BCryptGenRandom() on Windows).
 *
 *  @param[out] id_str  Buffer of at least LL_JOB_MAX_ID bytes.
 *
 *  @return ll_job_status_e
 */
ll_job_status_e
job_factory_generate_id(char id_str[LL_JOB_MAX_ID]);

/*────────────────────────────  Versioning  ────────────────────────────────*/
#define LL_JOB_FACTORY_VERSION_MAJOR   1
#define LL_JOB_FACTORY_VERSION_MINOR   0
#define LL_JOB_FACTORY_VERSION_PATCH   0

static inline unsigned
job_factory_version(void)
{
    return (LL_JOB_FACTORY_VERSION_MAJOR << 16) |
           (LL_JOB_FACTORY_VERSION_MINOR <<  8) |
           (LL_JOB_FACTORY_VERSION_PATCH);
}

#endif /* LEXILEARN_ORCHESTRATOR_JOB_FACTORY_H */
