```markdown
<!---
#############################################################################
#  LexiLearn MVC Orchestrator – Public C API Reference
#  ─────────────────────────────────────────────────────────────────────────
#  This document is generated as part of the official distribution of the
#  LexiLearn Machine-Learning/NLP orchestration framework (project “ml_nlp”).
#  It specifies the public interface for third–party developers as well as
#  internal teams integrating custom components or building client bindings.
#
#  Copyright © 2023-2024 EduCog Systems, Inc.
#  SPDX-License-Identifier: Apache-2.0
#############################################################################
-->

# LexiLearn C API Reference
The LexiLearn Orchestrator is a modular C library that enables ingestion,
pre-processing, model building, evaluation, monitoring, and versioning of
language-learning ML pipelines at scale.  It is built around the MVC pattern
with additional MLOps-specific components.  This document details the public
headers, types, functions, and conventions available to native extensions and
embedders.

> NOTE  
> All symbols are **prefixed with `lexi_`** to prevent namespace clashes.
> Only the headers listed in this document are considered stable.

---

## Table of Contents
1. [Compilation & Linking](#compilation--linking)  
2. [Thread-Safety & Memory](#thread-safety--memory)  
3. [Error-Handling](#error-handling)  
4. [Module Overview](#module-overview)  
   4.1 [`lexi_ingest.h`](#lexi_ingesth—data-ingestion-api)  
   4.2 [`lexi_feature_store.h`](#lexi_feature_storeh—feature-store-api)  
   4.3 [`lexi_experiment.h`](#lexi_experimenth—experiment-tracking-api)  
   4.4 [`lexi_training.h`](#lexi_trainingh—training-pipeline-api)  
   4.5 [`lexi_registry.h`](#lexi_registryh—model-registry-api)  
   4.6 [`lexi_monitor.h`](#lexi_monitorh—model-monitoring-api)  
5. [Versioning](#versioning)  
6. [Changelog](#changelog)  

---

## Compilation & Linking
```bash
# POSIX example linking with the shared library
cc -std=c17 -O2 -Wall -Wextra -pedantic \
   compute_features.c -o compute_features \
   -I/usr/local/include/lexilearn \
   -L/usr/local/lib -llexilearn
```
On Windows, the import library is `lexilearn.lib` and the dynamic link library
is `lexilearn.dll`.

Use `pkg-config` when available:
```bash
cc $(pkg-config --cflags lexilearn) my_app.c \
   $(pkg-config --libs   lexilearn)
```

---

## Thread-Safety & Memory
All public functions are *re-entrant* and *thread-safe* **unless stated
otherwise**.  Functions returning heap-allocated objects transfer ownership to
the caller; deallocate with the matching `lexi_*_destroy()` routine.

The library uses the [jemalloc] allocator by default; you may override by
defining `LEXI_MALLOC`, `LEXI_REALLOC`, and `LEXI_FREE` macros **before**
including any LexiLearn header.

---

## Error Handling
The API follows a Unix-style *status-code* convention and surfaces rich error
objects when available.

```c
typedef enum {
    LEXI_OK = 0,
    LEXI_EINVAL,      /* Invalid argument              */
    LEXI_ENOMEM,      /* Allocation failure            */
    LEXI_EIO,         /* I/O or network failure        */
    LEXI_ESTATE,      /* Invalid object state          */
    LEXI_ETRANSIENT,  /* Retryable transient error     */
    LEXI_EINTERNAL,   /* Internal bug (please report)  */
    /* ... reserved for future codes … */
} lexi_status_t;
```
Unless otherwise documented, a non-zero `lexi_status_t` return indicates
failure.  Use `lexi_error_str(status)` to obtain a human-readable description.

---

## Module Overview
Each header presents a cohesive set of responsibilities:

| Header                  | Responsibility                       | Patterns Used       |
|-------------------------|--------------------------------------|---------------------|
| `lexi_ingest.h`         | Classroom & LMS data ingestion       | Pipeline Pattern    |
| `lexi_feature_store.h`  | Shared feature engineering registry   | Factory, Strategy   |
| `lexi_experiment.h`     | Hyper-parameter sweeps & tracking     | Observer            |
| `lexi_training.h`       | Model training & evaluation           | Strategy, Pipeline  |
| `lexi_registry.h`       | Model registry & versioning           | Model Registry      |
| `lexi_monitor.h`        | Drift detection & automated retrain   | Observer           |

---

### `lexi_ingest.h` — Data Ingestion API
```c
#ifndef LEXI_INGEST_H
#define LEXI_INGEST_H

#include <stddef.h>
#include <stdint.h>
#include "lexi_core.h"   /* common types & status codes */

#ifdef __cplusplus
extern "C" {
#endif

/* Forward declaration */
typedef struct lexi_ingest_session_s lexi_ingest_session_t;

typedef enum {
    LEXI_SOURCE_LMS      = 0,
    LEXI_SOURCE_VOICE    = 1,
    LEXI_SOURCE_ESSAY    = 2,
    LEXI_SOURCE_QUIZ     = 3
} lexi_source_t;

/* Optional structured metadata attached to each record */
typedef struct {
    const char *student_id;   /* UTF-8, NUL-terminated */
    const char *course_id;    /* may be NULL */
    int64_t     timestamp_ms; /* epoch milliseconds */
} lexi_metadata_t;

/*
 * Creates an ingestion session.
 * Sessions are lightweight and may be created per thread.
 */
lexi_ingest_session_t *
lexi_ingest_session_create(const char      *tenant_name,
                           lexi_status_t   *out_status);

/*
 * Pushes a single record into the pipeline.  The buffer is copied
 * internally; the caller retains ownership of `payload`.
 */
lexi_status_t
lexi_ingest_push_record(lexi_ingest_session_t *session,
                        lexi_source_t          source,
                        const void            *payload,
                        size_t                 payload_sz,
                        const lexi_metadata_t *meta /* nullable */);

/* Flushes all buffered records and closes the session. */
lexi_status_t
lexi_ingest_session_close(lexi_ingest_session_t *session);

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* LEXI_INGEST_H */
```

#### Usage Example
```c
#include <lexilearn/lexi_ingest.h>
#include <stdio.h>

int main(void)
{
    lexi_status_t st;
    lexi_ingest_session_t *sess =
        lexi_ingest_session_create("district-42", &st);
    if (!sess) {
        fprintf(stderr, "Failed to create session: %s\n",
                lexi_error_str(st));
        return 1;
    }

    const char *essay = "To be, or not to be…";
    lexi_metadata_t meta = {
        .student_id = "stu_99123",
        .course_id  = "eng-101",
        .timestamp_ms = 1701012345123
    };

    st = lexi_ingest_push_record(sess,
                                 LEXI_SOURCE_ESSAY,
                                 essay, strlen(essay),
                                 &meta);
    if (st != LEXI_OK)
        fprintf(stderr, "push_record: %s\n", lexi_error_str(st));

    lexi_ingest_session_close(sess);
    return (st == LEXI_OK) ? 0 : 1;
}
```

---

### `lexi_feature_store.h` — Feature Store API
```c
#ifndef LEXI_FEATURE_STORE_H
#define LEXI_FEATURE_STORE_H

#include <stddef.h>
#include <stdint.h>
#include "lexi_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lexi_feature_store_s lexi_feature_store_t;
typedef struct lexi_feature_view_s  lexi_feature_view_t;

typedef enum {
    LEXI_FEAT_VEC_F32,  /* 32-bit float vector */
    LEXI_FEAT_VEC_I8,   /* int8 quantized      */
    LEXI_FEAT_TEXT_BPE, /* Byte-Pair Encoded   */
} lexi_feat_kind_t;

typedef struct {
    const char       *name;     /* e.g., "tfidf_bi_gram"      */
    lexi_feat_kind_t  kind;
    size_t            dim;      /* vector dimension if any   */
} lexi_feat_schema_t;

/* Opens or creates a feature store for the given tenant. */
lexi_feature_store_t *
lexi_feature_store_open(const char    *tenant_name,
                        lexi_status_t *out_status);

/* Registers a new feature schema (idempotent). */
lexi_status_t
lexi_feature_store_register(lexi_feature_store_t  *store,
                            const lexi_feat_schema_t *schema);

/* 
 * Retrieves a feature view for batch operations.  The view must be destroyed
 * when no longer needed.
 */
lexi_feature_view_t *
lexi_feature_view_open(lexi_feature_store_t *store,
                       const char           *feature_name,
                       lexi_status_t        *out_status);

/* Persists a dense float vector feature. */
lexi_status_t
lexi_feature_view_put_vec_f32(lexi_feature_view_t *view,
                              const char *entity_id,        /* student_id */
                              const float *vec,
                              size_t dim);

/* Frees all resources held by the feature view. */
void lexi_feature_view_destroy(lexi_feature_view_t *view);

/* Closes the store handle. */
void lexi_feature_store_close(lexi_feature_store_t *store);

#ifdef __cplusplus
}
#endif
#endif /* LEXI_FEATURE_STORE_H */
```

#### Example: Writing Custom Features
```c
#include <lexilearn/lexi_feature_store.h>
#include <math.h>  /* hypothetical feature calc */
#include <stdio.h>

static void
compute_demo_feature(const char *essay, float *out_vec, size_t dim)
{
    for (size_t i = 0; i < dim; ++i)
        out_vec[i] = sinf((float)i) * 0.01f; /* stub */
}

int main(void)
{
    lexi_status_t st;
    lexi_feature_store_t *store =
        lexi_feature_store_open("district-42", &st);
    if (!store) return 1;

    lexi_feat_schema_t sch = {
        .name = "demo_f32_feature",
        .kind = LEXI_FEAT_VEC_F32,
        .dim  = 128
    };
    lexi_feature_store_register(store, &sch);

    lexi_feature_view_t *view =
        lexi_feature_view_open(store, sch.name, &st);

    float vec[128];
    compute_demo_feature("dummy", vec, 128);

    lexi_feature_view_put_vec_f32(view, "stu_99123", vec, 128);

    lexi_feature_view_destroy(view);
    lexi_feature_store_close(store);
    return 0;
}
```

---

### `lexi_experiment.h` — Experiment Tracking API
```c
#ifndef LEXI_EXPERIMENT_H
#define LEXI_EXPERIMENT_H

#include <stdint.h>
#include "lexi_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lexi_exp_run_s    lexi_exp_run_t;
typedef struct lexi_exp_param_s  lexi_exp_param_t;
typedef struct lexi_exp_metric_s lexi_exp_metric_t;

lexi_exp_run_t *
lexi_exp_run_start(const char    *project_name,
                   const char    *run_name,
                   lexi_status_t *out_status);

lexi_status_t
lexi_exp_log_param(lexi_exp_run_t *run,
                   const char     *key,
                   const char     *value);

lexi_status_t
lexi_exp_log_metric(lexi_exp_run_t *run,
                    const char     *name,
                    double          value,
                    int64_t         ts_ms); /* 0 = now */

lexi_status_t
lexi_exp_run_end(lexi_exp_run_t *run, lexi_status_t final_status);

#ifdef __cplusplus
}
#endif
#endif /* LEXI_EXPERIMENT_H */
```

---

### `lexi_training.h` — Training Pipeline API
```c
#ifndef LEXI_TRAINING_H
#define LEXI_TRAINING_H

#include "lexi_core.h"
#include "lexi_feature_store.h"
#include "lexi_experiment.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Abstract model handle */
typedef struct lexi_model_s lexi_model_t;

/* Training-time configuration */
typedef struct {
    const char *model_name;     /* user-friendly */
    const char *strategy;       /* e.g., "transformer-v2" */
    uint32_t    seed;           /* RNG seed     */
    uint32_t    epochs;
    double      learning_rate;
    /* future fields … */
} lexi_train_cfg_t;

/* Callback invoked for progress & early stopping */
typedef int (*lexi_train_progress_cb)(const lexi_model_t *model,
                                      uint32_t epoch,
                                      double loss,
                                      void *user_ctx);

/*
 * Trains a model; returns a fully-initialized handle on success.
 * The returned object must be released with `lexi_model_destroy()`.
 */
lexi_model_t *
lexi_model_train(const lexi_train_cfg_t     *cfg,
                 lexi_train_progress_cb      cb /* nullable */,
                 void                       *cb_ctx,
                 lexi_status_t              *out_status);

/* Evaluates on the held-out test set defined by `tenant_name`. */
lexi_status_t
lexi_model_evaluate(const lexi_model_t *model,
                    const char         *tenant_name,
                    double             *out_accuracy,
                    double             *out_loss);

/* Serializes and registers the model in the Model Registry. */
lexi_status_t
lexi_model_register(lexi_model_t *model,
                    const char   *registry_ns);

/* Releases all resources.  Idempotent. */
void lexi_model_destroy(lexi_model_t *model);

#ifdef __cplusplus
}
#endif
#endif /* LEXI_TRAINING_H */
```

---

### `lexi_registry.h` — Model Registry API
```c
#ifndef LEXI_REGISTRY_H
#define LEXI_REGISTRY_H

#include "lexi_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lexi_registry_s lexi_registry_t;
typedef struct lexi_registry_iter_s lexi_registry_iter_t;

lexi_registry_t *
lexi_registry_open(const char *namespace,
                   lexi_status_t *out_status);

lexi_registry_iter_t *
lexi_registry_list(lexi_registry_t *reg,
                   const char      *filter_expr /* may be NULL */);

const char *
lexi_registry_iter_next(lexi_registry_iter_t *iter);

void lexi_registry_iter_destroy(lexi_registry_iter_t *iter);

void lexi_registry_close(lexi_registry_t *reg);

#ifdef __cplusplus
}
#endif
#endif /* LEXI_REGISTRY_H */
```

---

### `lexi_monitor.h` — Model Monitoring API
```c
#ifndef LEXI_MONITOR_H
#define LEXI_MONITOR_H

#include <stdint.h>
#include "lexi_core.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lexi_monitor_s lexi_monitor_t;

typedef enum {
    LEXI_DRIFT_NONE  = 0,
    LEXI_DRIFT_MINOR = 1,
    LEXI_DRIFT_MAJOR = 2
} lexi_drift_level_t;

typedef void (*lexi_drift_cb)(lexi_drift_level_t level,
                              const char        *metric_name,
                              double             p_value,
                              void              *user_ctx);

/* Creates a monitor for the given model_id. */
lexi_monitor_t *
lexi_monitor_create(const char    *model_id,
                    lexi_drift_cb  cb,
                    void          *cb_ctx,
                    lexi_status_t *out_status);

/* Records a new prediction/label pair for online drift detection. */
lexi_status_t
lexi_monitor_observe(lexi_monitor_t *mon,
                     double          prediction,
                     double          label);

/* Destroys the monitor. */
void lexi_monitor_destroy(lexi_monitor_t *mon);

#ifdef __cplusplus
}
#endif
#endif /* LEXI_MONITOR_H */
```

#### Example: Automated Retraining Trigger
```c
#include <lexilearn/lexi_monitor.h>
#include <lexilearn/lexi_training.h>

static void
on_drift(lexi_drift_level_t level,
         const char *metric,
         double p_value,
         void *ctx)
{
    (void)metric; (void)p_value;
    if (level == LEXI_DRIFT_MAJOR) {
        const lexi_train_cfg_t cfg = {
            .model_name = "Retrain-on-Drift",
            .strategy   = "transformer-v3",
            .seed       = 42,
            .epochs     = 5,
            .learning_rate = 1e-4
        };
        lexi_status_t st;
        lexi_model_t *m = lexi_model_train(&cfg, NULL, NULL, &st);
        if (st == LEXI_OK) {
            lexi_model_register(m, "production");
            lexi_model_destroy(m);
        }
    }
}

int main(void)
{
    lexi_status_t st;
    lexi_monitor_t *mon =
        lexi_monitor_create("prod-model-123",
                            on_drift,
                            NULL,
                            &st);
    if (!mon) return 1;
    /* Observe data stream (omitted) */
    lexi_monitor_destroy(mon);
    return 0;
}
```

---

## Versioning
The header `lexi_core.h` exposes semantic version macros:

```c
#define LEXI_VERSION_MAJOR 1
#define LEXI_VERSION_MINOR 4
#define LEXI_VERSION_PATCH 0
#define LEXI_VERSION_STR   "1.4.0"
```

Use `lexi_version()` at runtime:

```c
#include <lexilearn/lexi_core.h>
printf("Linked against LexiLearn v%s\n", lexi_version());
```

---

## Changelog
### 1.4.0 (2024-06-19)
* Added `lexi_monitor_observe()` for continuous drift detection.
* `lexi_feature_store_register()` now idempotent.
* Deprecated: `lexi_training_run()` → superseded by `lexi_model_train()`.

### 1.3.0 (2024-01-05)
* Introduced Model Registry API.

*(full changelog available in `CHANGELOG.md`)*

---

[jemalloc]: https://jemalloc.net/
```