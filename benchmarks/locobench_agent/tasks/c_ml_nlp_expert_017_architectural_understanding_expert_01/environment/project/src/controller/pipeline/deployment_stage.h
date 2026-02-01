/*
 * LexiLearn MVC Orchestrator
 * -------------------------------------------------------------
 * File        : deployment_stage.h
 * Author      : LexiLearn Engineering <eng@lexilearn.ai>
 * Description : Header-only implementation of the “Deployment Stage”
 *               in the Controller-Pipeline Pattern.  The stage
 *               encapsulates the logic required to:
 *                   1. Package model artifacts
 *                   2. Push them to the model registry
 *                   3. Schedule a rollout to the target environment
 *                   4. Notify interested observers of progress/events
 *
 *               The code is implemented as a header so that small CLI
 *               utilities and unit-tests can simply #include the file
 *               without needing a separate linkage step.
 *
 *               NOTE: The functions rely on POSIX commands (tar, curl)
 *               to keep the sample concise; in production, replace them
 *               with proper library calls (e.g., libarchive, libcurl).
 * -------------------------------------------------------------
 */

#ifndef LEXILEARN_CONTROLLER_PIPELINE_DEPLOYMENT_STAGE_H
#define LEXILEARN_CONTROLLER_PIPELINE_DEPLOYMENT_STAGE_H

/*---------------------------  Dependencies  ---------------------------*/
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
/* For POSIX system() */
#include <unistd.h>

/*---------------------------  Compile Flags  --------------------------*/
#if defined(__STDC_VERSION__) && __STDC_VERSION__ < 201112L
#   error "C11 or newer is required"
#endif

/*---------------------------  Constants  ------------------------------*/
#define DEPLOY_MAX_PATH          256
#define DEPLOY_MAX_NAME           64
#define DEPLOY_MAX_VERSION        16
#define DEPLOY_TARBALL_SUFFIX    ".tgz"
#define DEPLOY_LOG_TIMEFMT   "%Y-%m-%d %H:%M:%S"
#define DEPLOY_POLL_INTERVAL_MS 500  /* Used by active wait loops       */
#define DEPLOY_CMD_BUF          512

/*---------------------------  Logging Macro  --------------------------*/
#ifndef DEPLOY_LOG_LEVEL
#   define DEPLOY_LOG_LEVEL 3 /* 0 = silent, 1 = error, 2 = warn, 3 = info, 4 = debug */
#endif

#define _DEPLOY_TIMESTAMP_BUF 32
#define _DEPLOY_PRINT(level, fmt, ...)                                       \
    do {                                                                     \
        if ((level) <= DEPLOY_LOG_LEVEL) {                                   \
            char _tsbuf[_DEPLOY_TIMESTAMP_BUF];                              \
            time_t _now = time(NULL);                                        \
            strftime(_tsbuf, sizeof(_tsbuf), DEPLOY_LOG_TIMEFMT,             \
                     localtime(&_now));                                      \
            fprintf((level) == 1 ? stderr : stdout,                          \
                    "[%s] [DEPLOY:%s] " fmt "\n",                            \
                    _tsbuf,                                                  \
                    (level) == 1 ? "ERROR" :                                 \
                    (level) == 2 ? "WARN"  :                                 \
                    (level) == 3 ? "INFO"  : "DEBUG",                        \
                    ##__VA_ARGS__);                                          \
        }                                                                    \
    } while (0)

#define DEPLOY_LOG_ERR(fmt, ...)   _DEPLOY_PRINT(1, fmt, ##__VA_ARGS__)
#define DEPLOY_LOG_WARN(fmt, ...)  _DEPLOY_PRINT(2, fmt, ##__VA_ARGS__)
#define DEPLOY_LOG_INFO(fmt, ...)  _DEPLOY_PRINT(3, fmt, ##__VA_ARGS__)
#define DEPLOY_LOG_DBG(fmt, ...)   _DEPLOY_PRINT(4, fmt, ##__VA_ARGS__)

/*---------------------------  Enumerations  ---------------------------*/
typedef enum {
    DEPLOY_TARGET_DEV,
    DEPLOY_TARGET_STAGING,
    DEPLOY_TARGET_PROD
} deploy_target_t;

typedef enum {
    DEPLOY_STATUS_INIT        = 0,
    DEPLOY_STATUS_PACKAGING   = 1,
    DEPLOY_STATUS_PUSHING     = 2,
    DEPLOY_STATUS_SCHEDULING  = 3,
    DEPLOY_STATUS_COMPLETED   = 4,
    DEPLOY_STATUS_FAILED      = 5
} deploy_status_t;

/*---------------------------  Observer Hook  --------------------------*/
/*
 * Observer callback signature.  Users can register one callback per
 * deployment stage to receive asynchronous status updates.
 *
 * @param status   Current status/state transition.
 * @param message  Human-readable message describing the event.
 * @param ctx      User-supplied context pointer.
 */
typedef void (*deploy_observer_fn)(deploy_status_t status,
                                   const char     *message,
                                   void           *ctx);

/*---------------------------  Structures  -----------------------------*/
typedef struct {
    deploy_target_t target;
    char            model_name[DEPLOY_MAX_NAME];
    char            model_version[DEPLOY_MAX_VERSION];
    char            artifact_path[DEPLOY_MAX_PATH]; /* Directory of artifacts */
    char            registry_uri[DEPLOY_MAX_PATH];
    int             rollout_percent;   /* Canary rollout percentage      */
    bool            enable_monitoring; /* Real-time metrics hook         */
} deployment_config_t;

typedef struct {
    deployment_config_t cfg;
    deploy_status_t     status;
    uint64_t            t_start_ms;
    char                tarball_path[DEPLOY_MAX_PATH]; /* Filled during packaging */

    /* Observer pattern */
    deploy_observer_fn  observer;
    void               *observer_ctx;
} deployment_stage_t;

/*---------------------------  Helper Utils  ---------------------------*/
static inline uint64_t _deploy_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)((ts.tv_sec * 1000ULL) + (ts.tv_nsec / 1e6));
}

static inline void _deploy_notify(deployment_stage_t *stage,
                                  deploy_status_t     status,
                                  const char         *fmt, ...)
{
    char msg[256] = {0};

    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    /* Log internally */
    switch (status) {
        case DEPLOY_STATUS_FAILED:     DEPLOY_LOG_ERR ("%s", msg); break;
        case DEPLOY_STATUS_PACKAGING:
        case DEPLOY_STATUS_PUSHING:
        case DEPLOY_STATUS_SCHEDULING: DEPLOY_LOG_INFO("%s", msg); break;
        case DEPLOY_STATUS_COMPLETED:  DEPLOY_LOG_INFO("%s", msg); break;
        default:                       DEPLOY_LOG_DBG ("%s", msg); break;
    }

    /* Fire external observer */
    if (stage && stage->observer) {
        stage->observer(status, msg, stage->observer_ctx);
    }
}

/*---------------------------  Internal Steps  -------------------------*/
/* 1. Package artifacts into a compressed tarball */
static bool _deploy_package_artifacts(deployment_stage_t *stage)
{
    assert(stage);

    stage->status = DEPLOY_STATUS_PACKAGING;
    _deploy_notify(stage, stage->status,
                   "Packaging artifacts for model %s:%s",
                   stage->cfg.model_name, stage->cfg.model_version);

    /* Build tarball path: <artifact_path>/<model_name>_<version>.tgz */
    int n = snprintf(stage->tarball_path, sizeof(stage->tarball_path),
                     "%s/%s_%s%s",
                     stage->cfg.artifact_path,
                     stage->cfg.model_name,
                     stage->cfg.model_version,
                     DEPLOY_TARBALL_SUFFIX);
    if (n <= 0 || (size_t)n >= sizeof(stage->tarball_path)) {
        _deploy_notify(stage, DEPLOY_STATUS_FAILED,
                       "Tarball path overflow for '%s'",
                       stage->cfg.artifact_path);
        return false;
    }

    /* Create tarball via system() call */
    char cmd[DEPLOY_CMD_BUF];
    n = snprintf(cmd, sizeof(cmd),
                 "tar -czf \"%s\" -C \"%s\" . > /dev/null 2>&1",
                 stage->tarball_path, stage->cfg.artifact_path);
    if (n <= 0 || (size_t)n >= sizeof(cmd)) {
        _deploy_notify(stage, DEPLOY_STATUS_FAILED,
                       "Command buffer overflow while packaging");
        return false;
    }

    DEPLOY_LOG_DBG("Executing: %s", cmd);
    int rc = system(cmd);
    if (rc != 0) {
        _deploy_notify(stage, DEPLOY_STATUS_FAILED,
                       "Packaging command failed with rc=%d", rc);
        return false;
    }

    DEPLOY_LOG_INFO("Created tarball: %s", stage->tarball_path);
    return true;
}

/* 2. Push tarball to registry */
static bool _deploy_push_to_registry(deployment_stage_t *stage)
{
    assert(stage);

    stage->status = DEPLOY_STATUS_PUSHING;
    _deploy_notify(stage, stage->status,
                   "Pushing tarball to registry at %s",
                   stage->cfg.registry_uri);

    /* RESTful push via curl (simplified; replace with libcurl for prod) */
    char cmd[DEPLOY_CMD_BUF];
    int n = snprintf(cmd, sizeof(cmd),
                     "curl -sf -X POST \"%s/models/%s/versions/%s\" "
                     "-F \"artifact=@%s\" "
                     "-H \"Content-Type: multipart/form-data\"",
                     stage->cfg.registry_uri,
                     stage->cfg.model_name,
                     stage->cfg.model_version,
                     stage->tarball_path);
    if (n <= 0 || (size_t)n >= sizeof(cmd)) {
        _deploy_notify(stage, DEPLOY_STATUS_FAILED,
                       "Command buffer overflow while pushing");
        return false;
    }

    DEPLOY_LOG_DBG("Executing: %s", cmd);
    int rc = system(cmd);
    if (rc != 0) {
        _deploy_notify(stage, DEPLOY_STATUS_FAILED,
                       "Registry push failed with rc=%d", rc);
        return false;
    }

    DEPLOY_LOG_INFO("Successfully pushed model to registry");
    return true;
}

/* 3. Schedule rollout (stubbed via sleep/echo) */
static bool _deploy_schedule_rollout(deployment_stage_t *stage)
{
    assert(stage);

    stage->status = DEPLOY_STATUS_SCHEDULING;
    _deploy_notify(stage, stage->status,
                   "Scheduling rollout to %s environment (canary=%d%%)",
                   stage->cfg.target == DEPLOY_TARGET_DEV     ? "DEV"     :
                   stage->cfg.target == DEPLOY_TARGET_STAGING ? "STAGING" :
                                                                  "PROD",
                   stage->cfg.rollout_percent);

    /*
     * In production this would interact with a deployment controller
     * (e.g., Kubernetes API, AWS SageMaker Endpoint, etc.).  Here we
     * mimic latency via sleep().
     */
    sleep(1); /* simulate scheduler latency */

    /* Simulated success */
    DEPLOY_LOG_INFO("Rollout scheduled successfully");
    return true;
}

/*------------------------  Public API Functions  ----------------------*/
/*
 * Initialize a deployment stage with configuration + optional observer.
 */
static inline bool deployment_stage_init(deployment_stage_t          *stage,
                                         const deployment_config_t   *cfg,
                                         deploy_observer_fn           observer,
                                         void                        *observer_ctx)
{
    if (!stage || !cfg) {
        DEPLOY_LOG_ERR("NULL pointer passed to deployment_stage_init");
        return false;
    }

    memset(stage, 0, sizeof(*stage));
    stage->cfg          = *cfg; /* shallow copy OK (all POD) */
    stage->status       = DEPLOY_STATUS_INIT;
    stage->t_start_ms   = _deploy_now_ms();
    stage->observer     = observer;
    stage->observer_ctx = observer_ctx;

    DEPLOY_LOG_INFO("Deployment stage initialized for %s:%s",
                    cfg->model_name, cfg->model_version);
    return true;
}

/*
 * Execute the deployment pipeline (packaging -> push -> schedule).
 * Returns true on success, false on any failure.
 */
static inline bool deployment_stage_execute(deployment_stage_t *stage)
{
    if (!stage) {
        DEPLOY_LOG_ERR("deployment_stage_execute called with NULL stage");
        return false;
    }

    bool ok = false;

    do {
        if (!_deploy_package_artifacts(stage)) break;
        if (!_deploy_push_to_registry(stage))  break;
        if (!_deploy_schedule_rollout(stage))  break;

        stage->status = DEPLOY_STATUS_COMPLETED;
        _deploy_notify(stage, stage->status,
                       "Deployment pipeline completed in %.2f seconds",
                       (double)( _deploy_now_ms() - stage->t_start_ms ) / 1000.0);
        ok = true;
    } while (0);

    if (!ok) {
        stage->status = DEPLOY_STATUS_FAILED;
        _deploy_notify(stage, stage->status,
                       "Deployment pipeline failed after %.2f seconds",
                       (double)( _deploy_now_ms() - stage->t_start_ms ) / 1000.0);
    }

    return ok;
}

/*
 * Tear down resources (currently a no-op but provided for symmetry).
 */
static inline void deployment_stage_teardown(deployment_stage_t *stage)
{
    if (!stage) return;

    DEPLOY_LOG_INFO("Tearing down deployment stage for %s:%s",
                    stage->cfg.model_name, stage->cfg.model_version);

    /* Future improvements: secure-delete tarball, close sockets, etc. */
    if (access(stage->tarball_path, F_OK) == 0) {
        if (unlink(stage->tarball_path) == 0) {
            DEPLOY_LOG_DBG("Removed temporary tarball %s",
                           stage->tarball_path);
        }
    }

    memset(stage, 0, sizeof(*stage));
}

#endif /* LEXILEARN_CONTROLLER_PIPELINE_DEPLOYMENT_STAGE_H */
