/**
 *  LexiLearn Orchestrator – Job Factory
 *  -----------------------------------
 *  File:    job_factory.c
 *  Author:  LexiLearn Engineering
 *  License: MIT
 *
 *  Description:
 *      Implements the Factory pattern for the Controller-layer pipeline.
 *      The job factory turns high-level orchestration requests (typically
 *      emitted by the event bus or RESTful API gateway) into concrete,
 *      executable Job instances.  Each Job encapsulates a single unit of
 *      work―data-preprocessing, hyper-parameter tuning, model training,
 *      etc.―and exposes a uniform interface that the Pipeline Scheduler
 *      can consume.
 *
 *      The implementation purposefully avoids leaking heavy ML/NLP
 *      semantics into the Controller.  Instead, the factory focuses on
 *      validating inputs, allocating resources, and wiring callbacks
 *      (Strategy pattern) that defer to Model-layer code *at run-time*.
 *
 *  Build:
 *      gcc -Wall -Wextra -pedantic -std=c11 -I../../include -c job_factory.c
 */

#include "job_factory.h"         /* Public API */
#include "controller_logger.h"   /* Thin wrapper around syslog / spdlog     */
#include "event_bus.h"           /* Domain-level message/event bus          */

#include <errno.h>
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__linux__)
    #include <uuid/uuid.h>       /* libuuid is available on all major distros */
#endif

/* ------------------------------------------------------------------------- *
 *  Internal constants & macros
 * ------------------------------------------------------------------------- */

#define JOB_ID_MAX_LEN     37          /* 36 chars + '\0' for canonical UUID */
#define JOB_DESCRIPTION_MAX 256

#define VALIDATE_ARG(cond, err_code, err_label) \
    do {                                        \
        if (!(cond)) {                          \
            *err = err_code;                    \
            goto err_label;                     \
        }                                       \
    } while (0)

/* ------------------------------------------------------------------------- *
 *  Forward declarations of Job-specific execution callbacks
 * ------------------------------------------------------------------------- */

static int execute_data_preprocessing(Job *self);
static int execute_hyperparameter_tuning(Job *self);
static int execute_training(Job *self);
static int execute_model_monitoring(Job *self);
static int execute_automated_retraining(Job *self);

/* ------------------------------------------------------------------------- *
 *  Atomic counter for monotonically increasing Job numbers (fallback)
 * ------------------------------------------------------------------------- */

static atomic_uint_fast64_t g_job_sequence = 0;

/* ------------------------------------------------------------------------- *
 *  Helper: UUID generation with graceful fallback
 * ------------------------------------------------------------------------- */

static void
generate_job_id(char buffer[JOB_ID_MAX_LEN])
{
#if defined(__linux__)
    uuid_t uuid;
    uuid_generate(uuid);
    uuid_unparse_lower(uuid, buffer);
#else
    /* Portable pseudo-UUID fallback (timestamp + atomic counter) */
    uint64_t ts_ms = (uint64_t)time(NULL) * 1000ULL;
    uint64_t seq   = atomic_fetch_add_explicit(&g_job_sequence, 1,
                                               memory_order_relaxed);

    /* Ensures at most 24 hex chars; remaining filled with '0' */
    snprintf(buffer, JOB_ID_MAX_LEN, "%08" PRIx64 "-%012" PRIx64, ts_ms, seq);
#endif
}

/* ------------------------------------------------------------------------- *
 *  Helper: Safe allocation with logging
 * ------------------------------------------------------------------------- */

static void *
xzmalloc(size_t size)
{
    void *ptr = calloc(1, size);
    if (!ptr) {
        controller_log(LOG_ERR,
                       "job_factory: Memory allocation failure (%zu bytes)",
                       size);
    }
    return ptr;
}

/* ------------------------------------------------------------------------- *
 *  Factory entry-point
 * ------------------------------------------------------------------------- */

Job *
job_factory_create(JobType          type,
                   const char      *json_payload,   /* Optional opaque blob */
                   JobError        *err)
{
    if (err) { *err = JOB_ERR_NONE; }
    else      { /* Prevent deref null in macros */ JobError dummy; err = &dummy; }

    VALIDATE_ARG(json_payload != NULL, JOB_ERR_INVALID_ARGUMENT, on_error);

    /* ------------------------------------------------------------------ *
     * Allocate Job and populate metadata
     * ------------------------------------------------------------------ */
    Job *job = xzmalloc(sizeof *job);
    VALIDATE_ARG(job != NULL, JOB_ERR_OOM, on_error);

    job->type            = type;
    job->created_ts      = time(NULL);
    job->priority        = JOB_PRIORITY_NORMAL;  /* default */
    strncpy(job->payload, json_payload, JOB_PAYLOAD_MAX - 1);
    generate_job_id(job->id);

    /* ------------------------------------------------------------------ *
     * Bind strategy callback depending on JobType
     * ------------------------------------------------------------------ */
    switch (type) {
        case JOB_DATA_PREPROCESSING:
            job->execute_cb = execute_data_preprocessing;
            snprintf(job->description, JOB_DESCRIPTION_MAX,
                     "Data-preprocessing job");
            break;

        case JOB_HYPERPARAMETER_TUNING:
            job->execute_cb = execute_hyperparameter_tuning;
            snprintf(job->description, JOB_DESCRIPTION_MAX,
                     "Hyper-parameter tuning job");
            break;

        case JOB_TRAINING:
            job->execute_cb = execute_training;
            snprintf(job->description, JOB_DESCRIPTION_MAX,
                     "Model training job");
            break;

        case JOB_MODEL_MONITORING:
            job->execute_cb = execute_model_monitoring;
            snprintf(job->description, JOB_DESCRIPTION_MAX,
                     "Model monitoring job");
            break;

        case JOB_AUTOMATED_RETRAINING:
            job->execute_cb = execute_automated_retraining;
            snprintf(job->description, JOB_DESCRIPTION_MAX,
                     "Automated retraining job");
            break;

        default:
            controller_log(LOG_ERR,
                           "job_factory: Unknown JobType %d", (int)type);
            *err = JOB_ERR_UNKNOWN_TYPE;
            goto on_error;
    }

    controller_log(LOG_INFO,
                   "job_factory: Created job '%s' (%s)",
                   job->id, job->description);

    return job;

on_error:
    if (job) { free(job); }
    return NULL;
}

/* ------------------------------------------------------------------------- *
 *  Public API: destruction
 * ------------------------------------------------------------------------- */

void
job_factory_destroy(Job *job)
{
    if (!job) { return; }

    controller_log(LOG_DEBUG,
                   "job_factory: Destroying job '%s' (%s)",
                   job->id, job->description);
    free(job);
}

/* ------------------------------------------------------------------------- *
 *  Public API: convenience wrapper for immediate execution
 * ------------------------------------------------------------------------- */

int
job_factory_execute(Job *job)
{
    if (!job || !job->execute_cb) {
        controller_log(LOG_ERR,
                       "job_factory_execute: Invalid Job or callback");
        return -EINVAL;
    }

    controller_log(LOG_INFO,
                   "job_factory_execute: Starting job '%s' (%s)",
                   job->id, job->description);

    int rc = job->execute_cb(job);

    if (rc == 0) {
        controller_log(LOG_INFO,
                       "job_factory_execute: Completed job '%s' successfully",
                       job->id);
    } else {
        controller_log(LOG_ERR,
                       "job_factory_execute: Job '%s' failed (rc=%d)",
                       job->id, rc);
    }
    return rc;
}

/* ------------------------------------------------------------------------- *
 *  ------------  Job-specific callbacks (Strategy pattern)  -------------- *
 * ------------------------------------------------------------------------- */

static int
execute_data_preprocessing(Job *self)
{
    /* Pretend to delegate to Model-layer pre-processing pipeline */
    controller_log(LOG_DEBUG,
                   "[%s] Preprocessing payload: %s",
                   self->id, self->payload);

    /* TODO: call data_preprocessor_run(&ctx); */
    /* Simulate work */
    sleep(1);

    event_bus_publish(EVENT_JOB_COMPLETED, self->id);
    return 0;
}

static int
execute_hyperparameter_tuning(Job *self)
{
    controller_log(LOG_DEBUG,
                   "[%s] Hyperparameter tuning payload: %s",
                   self->id, self->payload);

    /* TODO: hook into Optuna / Ray Tune / custom tuner */

    sleep(2);
    event_bus_publish(EVENT_JOB_COMPLETED, self->id);
    return 0;
}

static int
execute_training(Job *self)
{
    controller_log(LOG_DEBUG,
                   "[%s] Training payload: %s",
                   self->id, self->payload);

    /* TODO: instantiate Strategy (transformer | n-gram | hybrid). */

    sleep(3);
    event_bus_publish(EVENT_JOB_COMPLETED, self->id);
    return 0;
}

static int
execute_model_monitoring(Job *self)
{
    controller_log(LOG_DEBUG,
                   "[%s] Model monitoring payload: %s",
                   self->id, self->payload);

    /* TODO: evaluate drift metrics and alert if thresholds exceeded */

    sleep(1);
    event_bus_publish(EVENT_JOB_COMPLETED, self->id);
    return 0;
}

static int
execute_automated_retraining(Job *self)
{
    controller_log(LOG_DEBUG,
                   "[%s] Automated retraining payload: %s",
                   self->id, self->payload);

    /* TODO: chain preprocess -> training -> registry update */

    sleep(4);
    event_bus_publish(EVENT_JOB_COMPLETED, self->id);
    return 0;
}

/* ------------------------------------------------------------------------- *
 *  End of file
 * ------------------------------------------------------------------------- */
