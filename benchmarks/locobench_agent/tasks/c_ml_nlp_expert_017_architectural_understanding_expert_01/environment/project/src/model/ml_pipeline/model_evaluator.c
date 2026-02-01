/*
 *  File: model_evaluator.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *
 *  Description:
 *      Production-quality implementation of model-evaluation utilities used by
 *      the LexiLearn Model-layer pipeline.  The evaluator computes task-specific
 *      performance metrics (classification / regression) and persists results
 *      to the central Model Registry in JSON format.  Thread-safety,
 *      defensive-programming practices, and meaningful error codes are
 *      implemented to satisfy the platform’s MLOps requirements.
 *
 *  Copyright:
 *      © 2024 LexiLearn Research Group – All rights reserved.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#include <time.h>
#include <sys/stat.h>      /* mkdir, stat  */
#include <sys/types.h>
#include <pthread.h>

#include "cJSON.h"                     /* Third-party lightweight JSON lib   */
#include "model_evaluator.h"           /* Public API for this compilation unit */
#include "logger.h"                    /* Project-wide logging abstraction   */

/* ------------------------------------------------------------------------- */
/*                          Configuration / Constants                        */
/* ------------------------------------------------------------------------- */

#ifndef MODEL_REGISTRY_BASE_DIR
#define MODEL_REGISTRY_BASE_DIR  "model_registry/evaluations"
#endif

#define SAFE_DIV(num, den)  ((den) == 0.0 ? 0.0 : ((num) / (den)))

/* ------------------------------------------------------------------------- */
/*                               Error Codes                                 */
/* ------------------------------------------------------------------------- */

typedef enum {
    EVAL_OK                     = 0,
    EVAL_ERR_INVALID_ARGUMENT   = 1,
    EVAL_ERR_ALLOCATION         = 2,
    EVAL_ERR_FS_IO              = 3,
    EVAL_ERR_REGISTRY_PERSIST   = 4
} eval_status_t;

/* ------------------------------------------------------------------------- */
/*                               Data Models                                 */
/* ------------------------------------------------------------------------- */

typedef struct {
    double accuracy;
    double precision;
    double recall;
    double f1_score;
} classification_metrics_t;

typedef struct {
    double mae;
    double mse;
    double r2;
} regression_metrics_t;

/* ------------------------------------------------------------------------- */
/*                             Static Utilities                              */
/* ------------------------------------------------------------------------- */

static pthread_mutex_t _registry_mutex = PTHREAD_MUTEX_INITIALIZER;

/*
 * Ensures that MODEL_REGISTRY_BASE_DIR exists on disk.  This function is
 * idempotent and safe to call concurrently.
 */
static int
ensure_registry_dir(void)
{
    struct stat st = {0};

    if (stat(MODEL_REGISTRY_BASE_DIR, &st) == -1) {
        if (mkdir(MODEL_REGISTRY_BASE_DIR, 0755) != 0) {
            LOG_ERROR("Failed to create registry dir '%s' (%s)",
                      MODEL_REGISTRY_BASE_DIR, strerror(errno));
            return -1;
        }
    } else if (!S_ISDIR(st.st_mode)) {
        LOG_ERROR("Registry path '%s' exists but is not a directory",
                  MODEL_REGISTRY_BASE_DIR);
        return -1;
    }
    return 0;
}

/*
 * Persists a JSON blob to the model registry, using the convention:
 *     <MODEL_REGISTRY_BASE_DIR>/<model_id>_<model_version>_eval.json
 *
 * Thread-safe (file writes are guarded by a mutex).
 */
static int
persist_metrics_to_registry(const char *model_id,
                            const char *model_version,
                            const char *json_blob)
{
    if (!model_id || !model_version || !json_blob) {
        return EVAL_ERR_INVALID_ARGUMENT;
    }

    if (ensure_registry_dir() != 0) {
        return EVAL_ERR_FS_IO;
    }

    char filepath[512];
    if (snprintf(filepath, sizeof(filepath), "%s/%s_%s_eval.json",
                 MODEL_REGISTRY_BASE_DIR, model_id, model_version) >=
        (int)sizeof(filepath))
    {
        LOG_ERROR("Registry path exceeded maximum length");
        return EVAL_ERR_FS_IO;
    }

    pthread_mutex_lock(&_registry_mutex);

    FILE *fp = fopen(filepath, "w");
    if (!fp) {
        pthread_mutex_unlock(&_registry_mutex);
        LOG_ERROR("Unable to open registry file '%s' for writing: %s",
                  filepath, strerror(errno));
        return EVAL_ERR_FS_IO;
    }

    if (fwrite(json_blob, 1, strlen(json_blob), fp) != strlen(json_blob)) {
        fclose(fp);
        pthread_mutex_unlock(&_registry_mutex);
        LOG_ERROR("Failed to write metrics to '%s': %s",
                  filepath, strerror(errno));
        return EVAL_ERR_FS_IO;
    }

    fclose(fp);
    pthread_mutex_unlock(&_registry_mutex);

    LOG_INFO("Metrics persisted to Model Registry: %s", filepath);
    return EVAL_OK;
}

/* ------------------------------------------------------------------------- */
/*                       Metric-Computation Helpers                          */
/* ------------------------------------------------------------------------- */

/* Binary-classification metrics */
static void
compute_binary_classification_metrics(const double *y_true,
                                      const double *y_pred,
                                      size_t n,
                                      classification_metrics_t *out)
{
    /* Treat y_pred > 0.5 as positive class.  Caller guarantees non-NULL ptrs. */
    size_t tp = 0, fp = 0, fn = 0, tn = 0;

    for (size_t i = 0; i < n; ++i) {
        int actual = y_true[i] > 0.5;
        int pred   = y_pred[i] > 0.5;

        if (pred && actual)
            ++tp;
        else if (pred && !actual)
            ++fp;
        else if (!pred && actual)
            ++fn;
        else
            ++tn;
    }

    double acc  = SAFE_DIV((double)(tp + tn), (double)n);
    double prec = SAFE_DIV((double)tp, (double)(tp + fp));
    double rec  = SAFE_DIV((double)tp, (double)(tp + fn));
    double f1   = SAFE_DIV(2.0 * prec * rec, (prec + rec));

    out->accuracy  = acc;
    out->precision = prec;
    out->recall    = rec;
    out->f1_score  = f1;
}

/* Regression metrics */
static void
compute_regression_metrics(const double *y_true,
                           const double *y_pred,
                           size_t n,
                           regression_metrics_t *out)
{
    double sum_abs  = 0.0;
    double sum_sq   = 0.0;
    double sum_true = 0.0;
    double sum_true_sq = 0.0;

    for (size_t i = 0; i < n; ++i) {
        double err = y_true[i] - y_pred[i];
        sum_abs += fabs(err);
        sum_sq  += err * err;
        sum_true += y_true[i];
        sum_true_sq += y_true[i] * y_true[i];
    }

    double mae = SAFE_DIV(sum_abs, (double)n);
    double mse = SAFE_DIV(sum_sq,  (double)n);

    /* R2: 1 - (SS_res / SS_tot) */
    double mean_true = SAFE_DIV(sum_true, (double)n);
    double ss_tot = 0.0;

    for (size_t i = 0; i < n; ++i) {
        double diff = y_true[i] - mean_true;
        ss_tot += diff * diff;
    }

    double r2 = 1.0 - SAFE_DIV(sum_sq, ss_tot);

    out->mae = mae;
    out->mse = mse;
    out->r2  = r2;
}

/* ------------------------------------------------------------------------- */
/*                              Public  API                                  */
/* ------------------------------------------------------------------------- */

int
ll_evaluate_model(const ll_eval_config_t  *config,
                  const double            *y_true,
                  const double            *y_pred,
                  size_t                   n_samples)
{
    if (!config || !y_true || !y_pred || n_samples == 0) {
        LOG_ERROR("Invalid arguments passed to ll_evaluate_model");
        return EVAL_ERR_INVALID_ARGUMENT;
    }

    /* ------------------------------------------------------------------ */
    /*   Compute task-specific metrics                                     */
    /* ------------------------------------------------------------------ */
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        LOG_ERROR("Unable to allocate cJSON root object");
        return EVAL_ERR_ALLOCATION;
    }

    /* Populate metadata */
    cJSON_AddStringToObject(root, "model_id",      config->model_id);
    cJSON_AddStringToObject(root, "model_version", config->model_version);
    cJSON_AddStringToObject(root, "task_type",
                            config->task_type == LL_TASK_CLASSIFICATION ?
                            "classification" : "regression");

    time_t now = time(NULL);
    cJSON_AddNumberToObject(root, "timestamp", (double)now);

    if (config->task_type == LL_TASK_CLASSIFICATION) {
        classification_metrics_t m = {0};

        compute_binary_classification_metrics(y_true, y_pred,
                                              n_samples, &m);

        cJSON *mnode = cJSON_AddObjectToObject(root, "metrics");
        cJSON_AddNumberToObject(mnode, "accuracy",  m.accuracy);
        cJSON_AddNumberToObject(mnode, "precision", m.precision);
        cJSON_AddNumberToObject(mnode, "recall",    m.recall);
        cJSON_AddNumberToObject(mnode, "f1_score",  m.f1_score);

        LOG_INFO(
            "Eval metrics (Classification) – ID:%s V:%s | acc=%.4f prec=%.4f "
            "rec=%.4f f1=%.4f",
            config->model_id, config->model_version,
            m.accuracy, m.precision, m.recall, m.f1_score);

    } else { /* Regression */
        regression_metrics_t m = {0};

        compute_regression_metrics(y_true, y_pred, n_samples, &m);

        cJSON *mnode = cJSON_AddObjectToObject(root, "metrics");
        cJSON_AddNumberToObject(mnode, "mae", m.mae);
        cJSON_AddNumberToObject(mnode, "mse", m.mse);
        cJSON_AddNumberToObject(mnode, "r2",  m.r2);

        LOG_INFO(
            "Eval metrics (Regression) – ID:%s V:%s | mae=%.4f mse=%.4f r2=%.4f",
            config->model_id, config->model_version, m.mae, m.mse, m.r2);
    }

    /* ------------------------------------------------------------------ */
    /*   Persist results to Model Registry                                 */
    /* ------------------------------------------------------------------ */

    char *json_blob = cJSON_PrintUnformatted(root);
    if (!json_blob) {
        cJSON_Delete(root);
        LOG_ERROR("Failed to serialize evaluation metrics to JSON");
        return EVAL_ERR_ALLOCATION;
    }

    int status = persist_metrics_to_registry(config->model_id,
                                             config->model_version,
                                             json_blob);

    /* Clean-up */
    cJSON_Delete(root);
    free(json_blob);

    return status;
}

/* ------------------------------------------------------------------------- */
/*                                    EOF                                    */
/* ------------------------------------------------------------------------- */
