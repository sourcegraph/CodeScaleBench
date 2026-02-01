/**
 *  LexiLearn MVC Orchestrator
 *  -----------------------------------------
 *  File:    lexilearn_orchestrator/src/controller/pipeline/training_stage.c
 *  Author:  LexiLearn Engineering Team
 *
 *  Description:
 *      Implementation of the TrainingStage component in the Controller
 *      layer.  The TrainingStage orchestrates the life-cycle of a single
 *      model-training run: registering an experiment with the Model
 *      Registry, building a TrainingJob via the Factory Pattern,
 *      executing the job (including optional hyper-parameter tuning),
 *      and finally emitting Observer events so that other subsystems
 *      (e.g., automated retraining scheduler, drift monitor) can react.
 *
 *      This module deliberately hides its internal state and exposes a
 *      clean API suitable for consumption by the pipeline engine.
 *
 *  Note:
 *      All external dependencies are thin interfaces; the concrete
 *      implementations live in their respective modules.
 */

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "controller/pipeline/training_stage.h"
#include "core/logging.h"
#include "model_registry/model_registry_client.h"
#include "model_registry/registry_errors.h"
#include "observer/observer.h"
#include "pipeline/pipeline_events.h"
#include "training/training_job.h"
#include "training/training_job_factory.h"

/* -------------------------------------------------------------------------- */
/*                              Private Constants                             */
/* -------------------------------------------------------------------------- */

#define ERR_BUF_SZ          256
#define EXP_ID_BUF_SZ       64
#define ISO_TIME_BUF_SZ     32

/* -------------------------------------------------------------------------- */
/*                              Private Helpers                               */
/* -------------------------------------------------------------------------- */

/**
 * iso_8601_now
 * ----------------------------------------------------------------------------
 * Return the current timestamp in fairly strict ISO-8601 format
 * (YYYY-MM-DDThh:mm:ssZ).  The buffer must be at least ISO_TIME_BUF_SZ bytes.
 */
static void
iso_8601_now(char *buf, size_t len)
{
    time_t     now     = time(NULL);
    struct tm  gm_now;

    gmtime_r(&now, &gm_now);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &gm_now);
}

/**
 * gen_experiment_id
 * ----------------------------------------------------------------------------
 * Generate a reasonably-unique experiment identifier: <epoch>_<rand32bit>.
 */
static void
gen_experiment_id(char *out, size_t len)
{
    uint32_t rnd = (uint32_t)random();
    snprintf(out, len, "%llu_%08x",
             (unsigned long long)time(NULL),
             rnd);
}

/* -------------------------------------------------------------------------- */
/*                              Type Definitions                              */
/* -------------------------------------------------------------------------- */

struct TrainingStage
{
    ModelRegistryClient  *registry;
    TrainingJobFactory   *factory;
    Observer             *observer;

    pthread_mutex_t       mtx;
    int                   initialized;
    char                  last_error[ERR_BUF_SZ];
};

/* -------------------------------------------------------------------------- */
/*                           Forward Declarations                             */
/* -------------------------------------------------------------------------- */

static int _registry_start_experiment(TrainingStage            *stage,
                                      const TrainingStageCfg   *cfg,
                                      char                     *out_experiment_id,
                                      size_t                    id_len);

static void _registry_finish_experiment(TrainingStage  *stage,
                                        const char     *experiment_id,
                                        int             status);

static void _notify_observers(TrainingStage   *stage,
                              PipelineEvent    type,
                              const char      *experiment_id,
                              int              status);

/* -------------------------------------------------------------------------- */
/*                           Public API Implementation                        */
/* -------------------------------------------------------------------------- */

TrainingStage *
training_stage_create(ModelRegistryClient  *registry,
                      TrainingJobFactory   *factory,
                      Observer             *observer)
{
    if (!registry || !factory || !observer)
    {
        LLEXI_LOG_ERROR("training_stage_create: invalid dependency.");
        return NULL;
    }

    TrainingStage *ts = calloc(1, sizeof(TrainingStage));
    if (!ts)
    {
        LLEXI_LOG_ERROR("training_stage_create: %s", strerror(errno));
        return NULL;
    }

    ts->registry     = registry;
    ts->factory      = factory;
    ts->observer     = observer;
    ts->initialized  = 0;
    ts->last_error[0] = '\0';

    pthread_mutex_init(&ts->mtx, NULL);
    return ts;
}

void
training_stage_destroy(TrainingStage *stage)
{
    if (!stage) return;

    pthread_mutex_destroy(&stage->mtx);
    free(stage);
}

int
training_stage_init(TrainingStage *stage, const TrainingStageCfg *cfg)
{
    if (!stage || !cfg)
        return TRAINING_STAGE_EINVAL;

    pthread_mutex_lock(&stage->mtx);
    if (stage->initialized)
    {
        pthread_mutex_unlock(&stage->mtx);
        return TRAINING_STAGE_EALREADY;
    }

    /* Perform any additional validation here if needed */
    stage->initialized = 1;
    pthread_mutex_unlock(&stage->mtx);

    LLEXI_LOG_INFO("TrainingStage initialized: strategy=%s, tune=%s",
                   cfg->strategy_name,
                   cfg->enable_hyper_tuning ? "yes" : "no");

    return TRAINING_STAGE_OK;
}

int
training_stage_execute(TrainingStage *stage,
                       const TrainingStageCfg *cfg,
                       const DataSplit *data,
                       TrainingMetrics *out_metrics)
{
    if (!stage || !cfg || !data || !out_metrics)
        return TRAINING_STAGE_EINVAL;

    if (!stage->initialized)
        return TRAINING_STAGE_ENOINIT;

    int        rc             = TRAINING_STAGE_OK;
    char       experiment_id[EXP_ID_BUF_SZ] = {0};
    TrainingJob *job          = NULL;

    /* 1. Register experiment creation in Model Registry */
    if (_registry_start_experiment(stage, cfg,
                                   experiment_id,
                                   sizeof(experiment_id)) != 0)
    {
        rc = TRAINING_STAGE_EREGISTRY;
        goto done;
    }

    /* 2. Use Factory Pattern to obtain a concrete TrainingJob */
    job = training_job_factory_create(stage->factory, cfg, data);
    if (!job)
    {
        snprintf(stage->last_error, ERR_BUF_SZ,
                 "training_job_factory_create failed.");
        rc = TRAINING_STAGE_EFACTORY;
        goto finish_exp;
    }

    /* 3. Execute TrainingJob (includes optional hyper-parameter tuning) */
    rc = training_job_run(job, out_metrics);

    training_job_destroy(job);
    job = NULL;

finish_exp:
    /* 4. Finish experiment in Model Registry */
    _registry_finish_experiment(stage,
                                experiment_id,
                                rc == TRAINING_STAGE_OK ? 0 : -1);

    /* 5. Send Observer event for downstream automation */
    _notify_observers(stage,
                      PIPELINE_EVENT_TRAINING_COMPLETE,
                      experiment_id,
                      rc == TRAINING_STAGE_OK ? 0 : -1);

done:
    return rc;
}

const char *
training_stage_last_error(const TrainingStage *stage)
{
    return stage ? stage->last_error : "NULL stage";
}

/* -------------------------------------------------------------------------- */
/*                             Private Functions                              */
/* -------------------------------------------------------------------------- */

/**
 *  _registry_start_experiment
 *  --------------------------------------------------------------------------
 *  Insert a new experiment entry in the Model Registry and return its ID.
 */
static int
_registry_start_experiment(TrainingStage            *stage,
                           const TrainingStageCfg   *cfg,
                           char                     *out_experiment_id,
                           size_t                    id_len)
{
    char iso_time[ISO_TIME_BUF_SZ];
    gen_experiment_id(out_experiment_id, id_len);
    iso_8601_now(iso_time, sizeof(iso_time));

    RegistryExperiment exp = {
        .id               = out_experiment_id,
        .strategy_name    = cfg->strategy_name,
        .created_at       = iso_time,
        .hyper_tuning     = cfg->enable_hyper_tuning,
        .status           = REGISTRY_EXPERIMENT_RUNNING
    };

    int rc = model_registry_create_experiment(stage->registry, &exp);
    if (rc != REGISTRY_OK)
    {
        snprintf(stage->last_error, ERR_BUF_SZ,
                 "Registry error (%d): %s", rc,
                 model_registry_strerror(rc));
        return -1;
    }
    return 0;
}

/**
 *  _registry_finish_experiment
 *  --------------------------------------------------------------------------
 *  Update experiment status in the Model Registry.
 */
static void
_registry_finish_experiment(TrainingStage  *stage,
                            const char     *experiment_id,
                            int             status)
{
    int rc = model_registry_update_status(stage->registry,
                                          experiment_id,
                                          status == 0
                                              ? REGISTRY_EXPERIMENT_SUCCEEDED
                                              : REGISTRY_EXPERIMENT_FAILED);
    if (rc != REGISTRY_OK)
    {
        LLEXI_LOG_WARN("Failed to update experiment status: %s",
                       model_registry_strerror(rc));
    }
}

/**
 *  _notify_observers
 *  --------------------------------------------------------------------------
 *  Emit pipeline events via Observer Pattern.
 */
static void
_notify_observers(TrainingStage   *stage,
                  PipelineEvent    type,
                  const char      *experiment_id,
                  int              status)
{
    PipelineEventData d = {
        .event_type    = type,
        .experiment_id = experiment_id,
        .status        = status
    };

    observer_notify(stage->observer, &d);
}

/* -------------------------------------------------------------------------- */
/*                                End of File                                 */
/* -------------------------------------------------------------------------- */
