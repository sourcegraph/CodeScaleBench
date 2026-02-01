/**
 *  File:    pipeline_manager.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Author:  LexiLearn Engineering
 *
 *  Description:
 *  ------------
 *  Pipeline Manager orchestrates the end-to-end NLP/ML pipeline:
 *      1.   Ingest LMS events via DataIngestor (Factory-generated)
 *      2.   Persist raw artifacts to the Feature Store
 *      3.   Kick off training jobs through TrainingJobFactory
 *      4.   Register experiments with the Model Registry
 *      5.   Monitor model-quality metrics & trigger retraining
 *      6.   Emit rich controller-level logs/telemetry
 *
 *  Concurrency model:
 *  ------------------
 *  • A dedicated ingestion thread continuously pulls data from the LMS.
 *  • A monitor thread subscribes to Observer events (e.g., drift detected).
 *  • Mutex-protected state keeps the pipeline life-cycle thread-safe.
 *
 *  License:
 *  --------
 *  Proprietary — LexiLearn, Inc.  All rights reserved.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <errno.h>

#include "pipeline_manager.h"
#include "lms/data_ingestor.h"
#include "model/training_job_factory.h"
#include "model/model_registry.h"
#include "monitor/drift_detector.h"
#include "util/logger.h"
#include "util/xmalloc.h"   /* Safe malloc/calloc wrappers */

/* ------------------------------------------------------------------------- *
 *                             Internal constants                            *
 * ------------------------------------------------------------------------- */

#define INGESTION_POLL_SEC            15     /* How often to ping LMS        */
#define RETRAINING_BACKOFF_SEC       900     /* Cool-down after retraining   */
#define PIPELINE_VERSION             "2.1.0" /* Semantic versioning          */
#define MAX_PIPELINE_NAME_LEN         64

/* ------------------------------------------------------------------------- *
 *                        Opaque data structure definition                    *
 * ------------------------------------------------------------------------- */

struct pipeline_manager {
    char                    name[MAX_PIPELINE_NAME_LEN];
    volatile bool           running;        /* Gate for background threads      */
    pthread_t               ingestion_thr;  /* Background ingestion thread      */
    pthread_t               monitor_thr;    /* Background drift-monitor thread  */
    pthread_mutex_t         state_mtx;      /* Protects critical sections       */

    data_ingestor_t        *ingestor;       /* Factory-built LMS connector      */
    training_job_factory_t *job_factory;    /* Generates Training Jobs          */
    model_registry_t       *registry;       /* Component for Model Registry     */
    drift_detector_t       *drift_detector; /* Observer Pattern subject         */
};

/* ------------------------------------------------------------------------- *
 *                       Forward-declarations (static)                        *
 * ------------------------------------------------------------------------- */
static void    *ingestion_loop (void *arg);
static void    *monitor_loop   (void *arg);

static bool     trigger_training_locked (pipeline_manager_t *pmgr,
                                         const char         *reason);

static void     safe_sleep_sec (unsigned seconds);

/* ------------------------------------------------------------------------- *
 *                      Public API — constructor/destructor                   *
 * ------------------------------------------------------------------------- */

pipeline_manager_t *
pipeline_manager_create(const char *pipeline_name,
                        data_ingestor_config_t  ingestor_cfg,
                        training_job_factory_t *job_factory,
                        model_registry_t       *registry,
                        drift_detector_t       *drift_detector)
{
    if (!pipeline_name || strlen(pipeline_name) >= MAX_PIPELINE_NAME_LEN) {
        LOG_ERROR("pipeline_manager_create: invalid pipeline name argument");
        return NULL;
    }
    if (!job_factory || !registry || !drift_detector) {
        LOG_ERROR("pipeline_manager_create: mandatory argument is NULL");
        return NULL;
    }

    pipeline_manager_t *pmgr = xcalloc(1, sizeof(*pmgr));
    strncpy(pmgr->name, pipeline_name, sizeof(pmgr->name) - 1);

    /* Initialize sub-components ------------------------------------------------ */
    pmgr->ingestor = data_ingestor_factory_create(ingestor_cfg);
    if (!pmgr->ingestor) {
        LOG_ERROR("Failed to instantiate DataIngestor");
        free(pmgr);
        return NULL;
    }

    pmgr->job_factory    = job_factory;
    pmgr->registry       = registry;
    pmgr->drift_detector = drift_detector;

    pthread_mutex_init(&pmgr->state_mtx, NULL);

    LOG_INFO("PipelineManager '%s' (v%s) created", pmgr->name, PIPELINE_VERSION);
    return pmgr;
}

void pipeline_manager_destroy(pipeline_manager_t *pmgr)
{
    if (!pmgr) return;

    pipeline_manager_stop(pmgr);

    pthread_mutex_destroy(&pmgr->state_mtx);

    if (pmgr->ingestor)
        data_ingestor_destroy(pmgr->ingestor);

    /* The factory, registry and detector are owned by caller (DI container) */
    free(pmgr);
    LOG_INFO("PipelineManager destroyed");
}

/* ------------------------------------------------------------------------- *
 *                      Public API — execution lifecycle                      *
 * ------------------------------------------------------------------------- */

bool pipeline_manager_start(pipeline_manager_t *pmgr)
{
    if (!pmgr) return false;

    pthread_mutex_lock(&pmgr->state_mtx);
    if (pmgr->running) {
        pthread_mutex_unlock(&pmgr->state_mtx);
        LOG_WARN("PipelineManager already running");
        return true;
    }
    pmgr->running = true;
    pthread_mutex_unlock(&pmgr->state_mtx);

    /* Spawn background threads -------------------------------------------------- */
    if (pthread_create(&pmgr->ingestion_thr, NULL, ingestion_loop, pmgr) != 0) {
        LOG_ERROR("Failed to spawn ingestion thread: %s", strerror(errno));
        pmgr->running = false;
        return false;
    }

    if (pthread_create(&pmgr->monitor_thr, NULL, monitor_loop, pmgr) != 0) {
        LOG_ERROR("Failed to spawn drift monitor thread: %s", strerror(errno));
        pmgr->running = false;
        pthread_cancel(pmgr->ingestion_thr);
        return false;
    }

    LOG_INFO("PipelineManager '%s' started", pmgr->name);
    return true;
}

void pipeline_manager_stop(pipeline_manager_t *pmgr)
{
    if (!pmgr) return;

    pthread_mutex_lock(&pmgr->state_mtx);
    bool was_running = pmgr->running;
    pmgr->running = false;
    pthread_mutex_unlock(&pmgr->state_mtx);

    if (!was_running)
        return;

    /* Wait for threads to finish ------------------------------------------------ */
    pthread_join(pmgr->ingestion_thr, NULL);
    pthread_join(pmgr->monitor_thr,  NULL);

    LOG_INFO("PipelineManager '%s' gracefully stopped", pmgr->name);
}

/* ------------------------------------------------------------------------- *
 *                      Public API — imperative operations                    *
 * ------------------------------------------------------------------------- */

bool pipeline_manager_trigger_training(pipeline_manager_t *pmgr,
                                       const char         *reason)
{
    if (!pmgr) return false;

    pthread_mutex_lock(&pmgr->state_mtx);
    bool ok = trigger_training_locked(pmgr, reason);
    pthread_mutex_unlock(&pmgr->state_mtx);
    return ok;
}

/* ------------------------------------------------------------------------- *
 *                         Internal helper implementations                    *
 * ------------------------------------------------------------------------- */

/**
 * ingestion_loop
 * --------------
 * Background thread that pulls LMS data at a constant cadence and stores the
 * results in the shared Feature Store.  If the DataIngestor detects anomalies
 * in the incoming stream, it automatically logs metrics to Prometheus via
 * util/logger.  Any ingestion error toggles a soft failure state; after three
 * consecutive failures, the pipeline issues an ALERT severity log entry.
 */
static void *ingestion_loop(void *arg)
{
    pipeline_manager_t *pmgr = (pipeline_manager_t *)arg;
    unsigned consecutive_failures = 0;

    LOG_DEBUG("Ingestion thread started");
    while (pmgr->running) {

        if (data_ingestor_ingest(pmgr->ingestor) == 0) {
            /* Success case ----------------------------------------------------- */
            consecutive_failures = 0;
            LOG_INFO("Ingestion successful");
        } else {
            /* Failure handling -------------------------------------------------- */
            consecutive_failures++;
            LOG_ERROR("Ingestion failed (attempt #%u)", consecutive_failures);
            if (consecutive_failures >= 3)
                LOG_ALERT("Consecutive ingestion failures >= 3 — check LMS connectivity");
        }

        /* Re-schedule --------------------------------------------------------- */
        safe_sleep_sec(INGESTION_POLL_SEC);
    }
    LOG_DEBUG("Ingestion thread exiting");
    return NULL;
}

/**
 * monitor_loop
 * ------------
 * Observer Pattern consumer that listens for drift_detector notifications.
 * When drift is detected, the loop triggers a retraining job via the Factory.
 */
static void *monitor_loop(void *arg)
{
    pipeline_manager_t *pmgr = (pipeline_manager_t *)arg;

    /* Subscribe to drift events ------------------------------------------------- */
    drift_event_handle_t handle =
        drift_detector_subscribe(pmgr->drift_detector);

    LOG_DEBUG("Drift-monitor thread started");
    while (pmgr->running) {

        drift_event_t event;
        if (drift_detector_await_event(handle, &event, 30 /* sec timeout */) < 0)
            continue; /* timeout or error */

        if (event.type == DRIFT_EVENT_TYPE_DRIFT_DETECTED) {
            LOG_WARN("Data or model drift detected => triggering retraining");
            pthread_mutex_lock(&pmgr->state_mtx);
            bool ok = trigger_training_locked(pmgr, "drift-detected");
            pthread_mutex_unlock(&pmgr->state_mtx);

            if (!ok)
                LOG_ERROR("Monitor loop retraining request failed");

            safe_sleep_sec(RETRAINING_BACKOFF_SEC);
        }
    }

    drift_detector_unsubscribe(handle);
    LOG_DEBUG("Drift-monitor thread exiting");
    return NULL;
}

/**
 * trigger_training_locked
 * -----------------------
 * Helper that assumes the caller already holds pmgr->state_mtx.  It builds
 * a TrainingJob via the factory, pushes metadata to the Model Registry, then
 * executes the job synchronously.  Production deployments might execute the
 * job asynchronously on a Kubernetes back-end; the synchronous approach is
 * used here for brevity.
 *
 * Return true on success, false otherwise.
 */
static bool trigger_training_locked(pipeline_manager_t *pmgr,
                                    const char         *reason)
{
    /* Build the Training Job -------------------------------------------------- */
    training_job_t *job =
        training_job_factory_create(pmgr->job_factory, reason);

    if (!job) {
        LOG_ERROR("training_job_factory_create failed");
        return false;
    }

    char exp_id[MODEL_REGISTRY_MAX_ID];
    if (model_registry_create_experiment(pmgr->registry,
                                         job,
                                         reason,
                                         exp_id,
                                         sizeof(exp_id)) < 0) {
        LOG_ERROR("Failed to log experiment into Model Registry");
        training_job_destroy(job);
        return false;
    }

    LOG_INFO("Experiment '%s' registered, launching training job", exp_id);

    /* Execute the training job ------------------------------------------------ */
    if (training_job_execute(job) != 0) {
        LOG_ERROR("Training job execution failed for experiment '%s'", exp_id);
        model_registry_update_status(pmgr->registry, exp_id, MODEL_STATUS_FAILED);
        training_job_destroy(job);
        return false;
    }

    /* Persist success status to registry ------------------------------------- */
    if (model_registry_update_status(pmgr->registry,
                                     exp_id,
                                     MODEL_STATUS_SUCCEEDED) != 0) {
        LOG_ERROR("Unable to update experiment '%s' status in registry", exp_id);
    }

    LOG_INFO("Training completed successfully for experiment '%s'", exp_id);
    training_job_destroy(job);
    return true;
}

/* ------------------------------------------------------------------------- *
 *                            Utility functions                               *
 * ------------------------------------------------------------------------- */

static void safe_sleep_sec(unsigned seconds)
{
    struct timespec req  = { .tv_sec  = seconds, .tv_nsec = 0 };
    while (nanosleep(&req, &req) == -1 && errno == EINTR)
        ; /* Restart if interrupted by signal */
}

/* ------------------------------------------------------------------------- *
 *                              Version info                                  *
 * ------------------------------------------------------------------------- */

const char *pipeline_manager_version(void)
{
    return PIPELINE_VERSION;
}