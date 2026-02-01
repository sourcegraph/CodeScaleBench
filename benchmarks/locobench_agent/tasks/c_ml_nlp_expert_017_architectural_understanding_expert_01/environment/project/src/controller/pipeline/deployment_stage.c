```c
/**
 *  File:    deployment_stage.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Author:  LexiLearn DevOps Team
 *
 *  Description:
 *      This compilation unit implements the Deployment Stage of the
 *      Controller-layer Pipeline Pattern.  After a model has passed
 *      evaluation and been “approved-for-production” in the Model
 *      Registry, this stage
 *
 *          1. Retrieves the latest approved model artifact/version
 *          2. Builds a container image that bundles the artifact with
 *             its inference server
 *          3. Pushes the image to the container registry
 *          4. Applies the Kubernetes manifest for blue/green rollout
 *          5. Emits rich logging/metrics for MLOps auditability
 *
 *      The code purposefully depends only on stable POSIX & libc APIs,
 *      plus project-local headers.  External integrations (e.g. docker,
 *      kubectl, Model Registry gRPC) are shell-wrapped here for
 *      portability; in production, these calls are swapped for lib-
 *      specific clients at link-time.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/wait.h>
#include <unistd.h>

#include "deployment_stage.h"   /* Public interface to this module    */
#include "ll_logger.h"          /* Project-wide async logger          */
#include "ll_metrics.h"         /* Prometheus/OpenTelemetry exporter  */
#include "model_registry.h"     /* gRPC client for model registry     */
#include "orchestrator_config.h"

/* ---------- Compile-time Tunables --------------------------------------- */

#define MAX_VERSION_LEN          64
#define MAX_IMG_TAG_LEN         128
#define LOCK_DIR               "/var/lock/lexilearn"
#define DOCKER_BIN             "/usr/bin/docker"
#define KUBECTL_BIN            "/usr/bin/kubectl"

/* ---------- Type Definitions ------------------------------------------- */

/* Opaque to calling modules—defined in header only as forward struct */
struct DeploymentStageCtx
{
    char        model_name[MODEL_NAME_MAX];
    char        target_environment[ENV_NAME_MAX];
    char        approved_version[MAX_VERSION_LEN];
    char        image_tag[MAX_IMG_TAG_LEN];
    int         lock_fd;                /* File-lock to guard duplicate deployments */
    time_t      start_ts;
};

/* ---------- Static Helpers --------------------------------------------- */

/**
 * safe_system
 *      Thin wrapper around system(3) that forwards stdout/stderr to the
 *      Orchestrator logger and returns an exit code in a uniform way.
 */
static int
safe_system(const char *cmd)
{
    ll_logger_info("[deployment] Executing shell command: %s", cmd);

    int rc = system(cmd);
    if (rc == -1)
    {
        ll_logger_error("[deployment] system() failed: %s", strerror(errno));
        return -1;
    }

    if (WIFEXITED(rc))
    {
        int status = WEXITSTATUS(rc);
        if (status != 0)
            ll_logger_error("[deployment] Command exited with status %d", status);

        return status;
    }
    else if (WIFSIGNALED(rc))
    {
        ll_logger_error("[deployment] Command killed by signal %d", WTERMSIG(rc));
        return -1;
    }

    ll_logger_error("[deployment] Unknown process termination");
    return -1;
}

/**
 * acquire_lock
 *      Avoids two orchestrators deploying the same model concurrently.
 */
static int
acquire_lock(struct DeploymentStageCtx *ctx)
{
    char lock_path[PATH_MAX];
    snprintf(lock_path, sizeof(lock_path), "%s/%s.deploy.lck", LOCK_DIR, ctx->model_name);

    ctx->lock_fd = open(lock_path, O_CREAT | O_RDWR, 0644);
    if (ctx->lock_fd == -1)
    {
        ll_logger_error("[deployment] Unable to open lock file %s: %s",
                        lock_path, strerror(errno));
        return -1;
    }

    if (flock(ctx->lock_fd, LOCK_EX | LOCK_NB) == -1)
    {
        ll_logger_warn("[deployment] Another deployment in progress for %s", ctx->model_name);
        close(ctx->lock_fd);
        ctx->lock_fd = -1;
        return -1;
    }
    return 0;
}

/**
 * release_lock
 */
static void
release_lock(struct DeploymentStageCtx *ctx)
{
    if (ctx->lock_fd >= 0)
    {
        flock(ctx->lock_fd, LOCK_UN);
        close(ctx->lock_fd);
        ctx->lock_fd = -1;
    }
}

/**
 * build_image
 *      Constructs a docker image tag and builds the image using `docker build`.
 */
static int
build_image(struct DeploymentStageCtx *ctx)
{
    /* Tag schema: <registry>/<model>:<version>-<timestamp> */
    time_t now = time(NULL);
    struct tm tm_now;
    gmtime_r(&now, &tm_now);

    char tsbuf[32];
    strftime(tsbuf, sizeof(tsbuf), "%Y%m%d%H%M%S", &tm_now);

    snprintf(ctx->image_tag, sizeof(ctx->image_tag),
             "%s/%s:%s-%s",
             orchestrator_cfg()->container_registry,
             ctx->model_name,
             ctx->approved_version,
             tsbuf);

    char cmd[512];
    snprintf(cmd, sizeof(cmd),
             "%s build --quiet -t %s -f %s/Dockerfile %s",
             DOCKER_BIN,
             ctx->image_tag,
             orchestrator_cfg()->dockerfiles_dir,
             orchestrator_cfg()->model_artifact_dir);

    return safe_system(cmd);
}

/**
 * push_image
 */
static int
push_image(const struct DeploymentStageCtx *ctx)
{
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "%s push %s", DOCKER_BIN, ctx->image_tag);
    return safe_system(cmd);
}

/**
 * rollout_kubernetes
 */
static int
rollout_kubernetes(const struct DeploymentStageCtx *ctx)
{
    char manifest_path[PATH_MAX];
    snprintf(manifest_path, sizeof(manifest_path),
             "%s/%s/%s-manifest.yaml",
             orchestrator_cfg()->k8s_manifest_dir,
             ctx->target_environment,
             ctx->model_name);

    char cmd[512];
    snprintf(cmd, sizeof(cmd),
             "%s --namespace=%s apply -f %s",
             KUBECTL_BIN,
             ctx->target_environment,
             manifest_path);

    return safe_system(cmd);
}

/**
 * record_metrics
 */
static void
record_metrics(struct DeploymentStageCtx *ctx, int success)
{
    double duration = difftime(time(NULL), ctx->start_ts);
    ll_metrics_observe_histogram("deployment_duration_seconds",
                                 duration,
                                 "model", ctx->model_name,
                                 "environment", ctx->target_environment,
                                 NULL);
    ll_metrics_inc_counter("deployment_total",
                           "model", ctx->model_name,
                           "environment", ctx->target_environment,
                           "status", success ? "success" : "failure",
                           NULL);
}

/* ---------- Public API -------------------------------------------------- */

DeploymentStageCtx *
deployment_stage_init(const char *model_name, const char *environment)
{
    if (!model_name || !environment)
        return NULL;

    struct DeploymentStageCtx *ctx = calloc(1, sizeof(struct DeploymentStageCtx));
    if (!ctx)
        return NULL;

    strlcpy(ctx->model_name, model_name, sizeof(ctx->model_name));
    strlcpy(ctx->target_environment, environment, sizeof(ctx->target_environment));
    ctx->lock_fd = -1;
    ctx->start_ts = time(NULL);

    ll_logger_info("[deployment] Initializing deployment for model=%s env=%s",
                   ctx->model_name, ctx->target_environment);

    return ctx;
}

int
deployment_stage_execute(DeploymentStageCtx *ctx)
{
    if (!ctx)
        return -1;

    /* Step 0: Concurrency guard */
    if (acquire_lock(ctx) != 0)
        return -1;

    /* Step 1: Retrieve approved model version from registry */
    if (model_registry_get_latest_approved_version(ctx->model_name,
                                                   ctx->approved_version,
                                                   sizeof(ctx->approved_version)) != 0)
    {
        ll_logger_error("[deployment] No approved version found for %s", ctx->model_name);
        release_lock(ctx);
        return -1;
    }

    ll_logger_info("[deployment] Latest approved version: %s", ctx->approved_version);

    /* Step 2: Build container image */
    if (build_image(ctx) != 0)
    {
        release_lock(ctx);
        record_metrics(ctx, 0);
        return -1;
    }

    /* Step 3: Push image to registry */
    if (push_image(ctx) != 0)
    {
        release_lock(ctx);
        record_metrics(ctx, 0);
        return -1;
    }

    /* Step 4: Kubernetes rollout */
    if (rollout_kubernetes(ctx) != 0)
    {
        release_lock(ctx);
        record_metrics(ctx, 0);
        return -1;
    }

    ll_logger_info("[deployment] Successfully deployed %s:%s to %s",
                   ctx->model_name, ctx->approved_version, ctx->target_environment);

    release_lock(ctx);
    record_metrics(ctx, 1);

    return 0;
}

void
deployment_stage_cleanup(DeploymentStageCtx *ctx)
{
    if (!ctx)
        return;

    release_lock(ctx);
    free(ctx);
}

/* ---------- End of file ------------------------------------------------- */
```