```c
/**
 * LexiLearn Orchestrator
 * File: lexilearn_orchestrator/src/controller/orchestrator.c
 *
 * The Orchestrator coordinates the entire MLOps pipeline for the
 * LexiLearn platform.  Responsibilities include:
 *
 *  • Periodic ingestion of LMS data
 *  • Pre-processing & feature engineering via the shared pipeline
 *  • Hyper-parameter tuning and model training through the factory API
 *  • Model registration / versioning in the central registry
 *  • Scheduling automated retraining when model drift is detected
 *  • Broadcasting Observer events to interested components
 *
 *  Build-flags: ‑pthread
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <signal.h>
#include <errno.h>

/* ───────────── Project-Level Headers (Forward Declarations) ───────────── */
#include "config.h"            /* Global configuration object              */
#include "lms_api.h"           /* Data ingestion – LMS REST/gRPC clients    */
#include "pipeline.h"          /* ETL / feature engineering pipeline        */
#include "trainer_factory.h"   /* Factory Pattern for model trainer objects */
#include "registry.h"          /* Model Registry (versioning, metadata)     */
#include "observer.h"          /* Observer Pattern hooks for drift alerts   */
#include "scheduler.h"         /* Cron-like scheduler for automated tasks   */
#include "logger.h"            /* Thread-safe logging abstraction           */

/* ───────────── Local Definitions ───────────── */

#define ORCHESTRATOR_TAG      "ORCHESTRATOR"
#define DEFAULT_RETRAIN_HRS   24    /* Fallback retraining interval in hours */

typedef struct
{
    int              initialized;
    int              running;
    OrchestratorCfg  cfg;

    pthread_t        scheduler_thread;
    pthread_mutex_t  state_mtx;
} orchestrator_t;

/* Singleton instance */
static orchestrator_t g_orch = {
    .initialized = 0,
    .running     = 0,
    .state_mtx   = PTHREAD_MUTEX_INITIALIZER
};

/* ───────────── Static Helpers ───────────── */

static int start_training_pipeline(void);
static void *scheduler_mainloop(void *arg);
static void  handle_sigterm(int signum);

/* ───────────── Public API ───────────── */

int orchestrator_init(const OrchestratorCfg *cfg)
{
    if (!cfg)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "NULL cfg passed to orchestrator_init()");
        return -1;
    }

    pthread_mutex_lock(&g_orch.state_mtx);

    if (g_orch.initialized)
    {
        LL_LOG_WARN(ORCHESTRATOR_TAG, "Orchestrator already initialized.");
        pthread_mutex_unlock(&g_orch.state_mtx);
        return 0;
    }

    memset(&g_orch.cfg, 0, sizeof(g_orch.cfg));
    memcpy(&g_orch.cfg, cfg, sizeof(*cfg));

    g_orch.initialized = 1;
    pthread_mutex_unlock(&g_orch.state_mtx);

    /* Register signal handlers for graceful shutdown */
    struct sigaction sa = {
        .sa_handler = handle_sigterm,
        .sa_flags   = 0
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LL_LOG_INFO(ORCHESTRATOR_TAG, "Initialized (retrain_interval=%dh, hparam_tuning=%s)",
                g_orch.cfg.retrain_interval_hours,
                g_orch.cfg.enable_hparam_tuning ? "ON" : "OFF");

    return 0;
}

int orchestrator_start(void)
{
    if (!g_orch.initialized)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Cannot start before initialization.");
        return -1;
    }

    pthread_mutex_lock(&g_orch.state_mtx);
    if (g_orch.running)
    {
        LL_LOG_WARN(ORCHESTRATOR_TAG, "Orchestrator already running.");
        pthread_mutex_unlock(&g_orch.state_mtx);
        return 0;
    }
    g_orch.running = 1;
    pthread_mutex_unlock(&g_orch.state_mtx);

    /* Kick-off the first training iteration synchronously */
    if (start_training_pipeline() != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Initial training pipeline failed. Aborting startup.");
        return -1;
    }

    /* Spawn the retraining scheduler */
    int rc = pthread_create(&g_orch.scheduler_thread, NULL, scheduler_mainloop, NULL);
    if (rc != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Failed to start scheduler thread (%s).", strerror(rc));
        g_orch.running = 0;
        return -1;
    }

    LL_LOG_INFO(ORCHESTRATOR_TAG, "Orchestrator started.");
    return 0;
}

void orchestrator_stop(void)
{
    pthread_mutex_lock(&g_orch.state_mtx);
    if (!g_orch.running)
    {
        pthread_mutex_unlock(&g_orch.state_mtx);
        return;
    }
    g_orch.running = 0;
    pthread_mutex_unlock(&g_orch.state_mtx);

    /* Wake the scheduler so it can exit */
    scheduler_cancel_wait();

    pthread_join(g_orch.scheduler_thread, NULL);
    LL_LOG_INFO(ORCHESTRATOR_TAG, "Orchestrator stopped.");
}

/* ───────────── Implementation Details ───────────── */

/**
 * start_training_pipeline()
 * ----------------------------------------------------
 * Executes a full training cycle: ingestion, preprocessing,
 * hyper-parameter tuning, model training, and registration.
 */
static int start_training_pipeline(void)
{
    char tmp_data_dir[PATH_MAX]        = {0};
    char preproc_output[PATH_MAX]      = {0};
    char best_params_file[PATH_MAX]    = {0};
    model_info_t model_info            = {0};

    LL_LOG_INFO(ORCHESTRATOR_TAG, "Starting training pipeline…");

    /* 1. Ingest latest data */
    if (lms_fetch_latest_data(g_orch.cfg.lms_endpoint,
                              g_orch.cfg.project_root,
                              tmp_data_dir,
                              sizeof(tmp_data_dir)) != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Data ingestion failed.");
        return -1;
    }

    /* 2. Pre-processing & feature engineering */
    if (pipeline_run(tmp_data_dir,
                     preproc_output,
                     sizeof(preproc_output)) != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Pre-processing failed.");
        return -1;
    }

    /* 3. Hyper-parameter tuning (optional) */
    trainer_params_t params = {0};
    if (g_orch.cfg.enable_hparam_tuning)
    {
        if (tuner_run(preproc_output,
                      best_params_file,
                      sizeof(best_params_file)) != 0)
        {
            LL_LOG_ERROR(ORCHESTRATOR_TAG, "Hyper-parameter tuning failed.");
            return -1;
        }

        if (params_load_from_file(best_params_file, &params) != 0)
        {
            LL_LOG_ERROR(ORCHESTRATOR_TAG, "Failed to parse best params file.");
            return -1;
        }
    }
    else
    {
        params = trainer_default_params();
    }

    /* 4. Model training via Factory Pattern */
    trainer_t *trainer = trainer_factory_create(g_orch.cfg.model_strategy);
    if (!trainer)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Trainer creation failed (strategy=%s).",
                     g_orch.cfg.model_strategy);
        return -1;
    }

    if (trainer->train(trainer, preproc_output, &params, &model_info) != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Model training failed.");
        trainer->destroy(trainer);
        return -1;
    }
    trainer->destroy(trainer);

    /* 5. Register model in the central registry */
    if (registry_register_model(&model_info) != 0)
    {
        LL_LOG_ERROR(ORCHESTRATOR_TAG, "Model registration failed.");
        return -1;
    }

    /* 6. Notify Observers for model lifecycle event */
    observer_event_t ev = {
        .type      = OBSERVER_EVT_MODEL_VERSIONED,
        .timestamp = time(NULL),
        .payload   = &model_info
    };
    observer_broadcast(&ev);

    LL_LOG_INFO(ORCHESTRATOR_TAG, "Training pipeline completed (model_id=%s).",
                model_info.model_id);

    return 0;
}

/**
 * scheduler_mainloop()
 * ----------------------------------------------------
 * Background thread that waits until the configured retrain
 * interval (or an external drift alert) elapses, then triggers
 * start_training_pipeline().
 */
static void *scheduler_mainloop(void *arg)
{
    (void)arg; /* Unused */

    const int interval_hours = g_orch.cfg.retrain_interval_hours > 0 ?
                               g_orch.cfg.retrain_interval_hours :
                               DEFAULT_RETRAIN_HRS;

    LL_LOG_INFO(ORCHESTRATOR_TAG,
                "Scheduler thread started (interval=%dh).", interval_hours);

    while (1)
    {
        pthread_mutex_lock(&g_orch.state_mtx);
        int keep_running = g_orch.running;
        pthread_mutex_unlock(&g_orch.state_mtx);

        if (!keep_running)
            break;

        /* Wait for either drift alert or time-based trigger */
        scheduler_wait_or_timeout(interval_hours * 3600);

        /* Consume any pending drift events */
        if (observer_drift_detected())
        {
            LL_LOG_INFO(ORCHESTRATOR_TAG,
                        "Model drift detected – initiating immediate retraining.");
        }

        if (!keep_running)
            break;

        if (start_training_pipeline() != 0)
        {
            LL_LOG_ERROR(ORCHESTRATOR_TAG, "Scheduled training failed; will retry later.");
        }
    }

    LL_LOG_INFO(ORCHESTRATOR_TAG, "Scheduler thread exiting.");
    return NULL;
}

/**
 * handle_sigterm()
 * ----------------------------------------------------
 * Graceful shutdown handler for SIGINT/SIGTERM.
 */
static void handle_sigterm(int signum)
{
    (void)signum; /* Unused */
    LL_LOG_INFO(ORCHESTRATOR_TAG, "Received termination signal. Shutting down…");
    orchestrator_stop();
}
```