```c
/**
 *  LexiLearn MVC Orchestrator ― Hybrid Model
 *
 *  File:     hybrid_model.h
 *  Author:   LexiLearn Core Team
 *  License:  MIT
 *
 *  Description:
 *      C-language implementation of the HybridModel used by LexiLearn’s NLP/ML
 *      pipeline.  The model blends a light-weight transformer encoder with a
 *      classical n-gram language model, allowing both deep-semantic reasoning
 *      and fast lexical look-ups.  The code is delivered header-only to keep
 *      integration friction low for downstream plug-ins (e.g., CUDA or OpenCL
 *      kernels) while still enabling unit-test injection in isolation.
 *
 *      To include the IMPLEMENTATION, define LEXILEARN_HYBRID_MODEL_IMPLEMENTATION
 *      in _exactly one_ translation unit _before_ including this header:
 *
 *          #define LEXILEARN_HYBRID_MODEL_IMPLEMENTATION
 *          #include "hybrid_model.h"
 *
 *      Otherwise the file acts as a conventional header with only type
 *      declarations and function prototypes.
 */

#ifndef LEXILEARN_HYBRID_MODEL_H
#define LEXILEARN_HYBRID_MODEL_H

/* ──────────────────────────────────────────────────────────────────────────
 *  Standard dependencies
 * ────────────────────────────────────────────────────────────────────────── */
#include <stddef.h>     /* size_t      */
#include <stdint.h>     /* uint32_t    */
#include <stdbool.h>    /* bool        */

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────────────────
 *  Versioning
 * ────────────────────────────────────────────────────────────────────────── */
#define LL_HYBRID_MODEL_VERSION_MAJOR  1
#define LL_HYBRID_MODEL_VERSION_MINOR  2
#define LL_HYBRID_MODEL_VERSION_PATCH  6

/* ──────────────────────────────────────────────────────────────────────────
 *  Error/Status handling
 * ────────────────────────────────────────────────────────────────────────── */
typedef enum
{
    LL_OK = 0,                 /* All good                                           */
    LL_ERR_INVALID_ARG,        /* Null pointer, out-of-range value, …               */
    LL_ERR_OOM,                /* malloc/calloc/realloc failure                      */
    LL_ERR_IO,                 /* fopen/fread/fwrite failure                         */
    LL_ERR_SERIALIZATION,      /* Corrupted or incompatible artifact                 */
    LL_ERR_INTERNAL            /* Should never happen; indicates a logic bug         */
} LL_Status;

/* Convert status code to human-readable message. */
const char* ll_status_string(LL_Status status);

/* ──────────────────────────────────────────────────────────────────────────
 *  Hyper-parameter definitions
 * ────────────────────────────────────────────────────────────────────────── */
typedef struct
{
    double min;
    double max;
    double step;
} LL_HparamRange;

typedef struct
{
    char     model_id[64];              /* Human-readable identifier                    */
    uint32_t random_seed;

    /* Transformer sub-module */
    uint32_t transformer_hidden_dim;
    uint32_t transformer_num_heads;
    double   transformer_lr;

    /* n-gram sub-module */
    uint32_t ngram_order;               /* e.g., 3 for trigram                         */
    double   ngram_smoothing_alpha;     /* Additive smoothing parameter                */

    /* General training knobs */
    uint32_t batch_size;
    uint32_t epochs;
    bool     enable_early_stopping;

} LL_HybridModelConfig;

/* ──────────────────────────────────────────────────────────────────────────
 *  Metric reporting
 * ────────────────────────────────────────────────────────────────────────── */
typedef struct
{
    double accuracy;
    double precision;
    double recall;
    double f1;
    double perplexity;
} LL_HybridModelMetrics;

/* ──────────────────────────────────────────────────────────────────────────
 *  Forward declarations / opaque handles
 * ────────────────────────────────────────────────────────────────────────── */
typedef struct LL_HybridModel LL_HybridModel;

/* Observer callback signature (Observer Pattern). */
typedef void (*LL_MetricsObserver)(const LL_HybridModelMetrics* metrics,
                                   void*                        user_ctx);

/* ──────────────────────────────────────────────────────────────────────────
 *  Public API
 * ────────────────────────────────────────────────────────────────────────── */

/* Life-cycle                                                            */
LL_Status ll_hybrid_model_create (const LL_HybridModelConfig* cfg,
                                  LL_HybridModel**            out_model);

LL_Status ll_hybrid_model_load   (const char*  artifact_path,
                                  LL_HybridModel** out_model);

LL_Status ll_hybrid_model_save   (const LL_HybridModel* model,
                                  const char*           artifact_path);

LL_Status ll_hybrid_model_free   (LL_HybridModel* model);

/* Training / Inference                                                 */
LL_Status ll_hybrid_model_train  (LL_HybridModel*          model,
                                  const char*              train_dataset_path,
                                  const char*              val_dataset_path,
                                  LL_HybridModelMetrics*   out_metrics);

LL_Status ll_hybrid_model_predict(const LL_HybridModel* model,
                                  const char*           input_text,
                                  char**                out_prediction); /* malloc-ed */

/* Monitoring / Observer pattern                                         */
LL_Status ll_hybrid_model_register_observer  (LL_HybridModel* model,
                                              LL_MetricsObserver cb,
                                              void*            user_ctx);

LL_Status ll_hybrid_model_unregister_observer(LL_HybridModel* model,
                                              LL_MetricsObserver cb);

/* Miscellaneous                                                         */
void       ll_hybrid_model_version(int* major, int* minor, int* patch);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ──────────────────────────────────────────────────────────────────────────
 *  Implementation (header-only; optional)
 * ────────────────────────────────────────────────────────────────────────── */
#ifdef LEXILEARN_HYBRID_MODEL_IMPLEMENTATION
/* --------------- PRIVATE SECTION (not visible without implementation) ------ */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>

/* Internal structures -------------------------------------------------- */
typedef struct ObserverNode
{
    LL_MetricsObserver cb;
    void*              user_ctx;
    struct ObserverNode* next;
} ObserverNode;

struct LL_HybridModel
{
    LL_HybridModelConfig  cfg;
    size_t                trained_steps;
    void*                 transformer;      /* Stub handles to sub-models  */
    void*                 ngram_model;
    ObserverNode*         observers;
};

/* Utility: safe calloc with error propagation -------------------------- */
static void* _ll_calloc(size_t n, size_t sz, LL_Status* st)
{
    void* ptr = calloc(n, sz);
    if (!ptr) *st = LL_ERR_OOM;
    return ptr;
}

/* Utility: notify observers ------------------------------------------- */
static void _ll_notify(const LL_HybridModel* model,
                       const LL_HybridModelMetrics* m)
{
    for (ObserverNode* node = model->observers; node; node = node->next)
        node->cb(m, node->user_ctx);
}

/* ────────────────────────────── PUBLIC IMPLEMENTATION ───────────────────── */

const char* ll_status_string(LL_Status s)
{
    switch (s)
    {
        case LL_OK:                return "Ok";
        case LL_ERR_INVALID_ARG:   return "Invalid argument";
        case LL_ERR_OOM:           return "Out of memory";
        case LL_ERR_IO:            return "I/O error";
        case LL_ERR_SERIALIZATION: return "Serialization error";
        case LL_ERR_INTERNAL:      return "Internal error";
        default:                   return "Unknown status";
    }
}

void ll_hybrid_model_version(int* major, int* minor, int* patch)
{
    if (major) *major = LL_HYBRID_MODEL_VERSION_MAJOR;
    if (minor) *minor = LL_HYBRID_MODEL_VERSION_MINOR;
    if (patch) *patch = LL_HYBRID_MODEL_VERSION_PATCH;
}

LL_Status ll_hybrid_model_create(const LL_HybridModelConfig* cfg,
                                 LL_HybridModel**            out_model)
{
    if (!cfg || !out_model) return LL_ERR_INVALID_ARG;
    LL_Status st = LL_OK;

    LL_HybridModel* m = (LL_HybridModel*)_ll_calloc(1, sizeof *m, &st);
    if (st != LL_OK) return st;

    m->cfg = *cfg;
    m->trained_steps = 0;
    m->transformer   = NULL;   /* Stub: replaced by actual backend   */
    m->ngram_model   = NULL;

    *out_model = m;
    return LL_OK;
}

LL_Status ll_hybrid_model_free(LL_HybridModel* model)
{
    if (!model) return LL_ERR_INVALID_ARG;

    /* Here we would call backend-specific destructors. */
    free(model);
    return LL_OK;
}

LL_Status ll_hybrid_model_train(LL_HybridModel*        model,
                                const char*            train_path,
                                const char*            val_path,
                                LL_HybridModelMetrics* out_metrics)
{
    if (!model || !train_path || !val_path) return LL_ERR_INVALID_ARG;

    /* ───────────── demo implementation ───────────── */
    /* In production we would:
     *  1. Stream data from `train_path`
     *  2. Run forward/backward on transformer
     *  3. Update n-gram counts
     *  4. Validate on `val_path`
     *  5. Populate metrics
     *  6. Trigger early-stopping / checkpoints
     */

    srand(model->cfg.random_seed ^ (uint32_t)time(NULL));
    LL_HybridModelMetrics m = {
        /* Fake but deterministic (ish) metrics */
        .accuracy   = 0.80 + (rand() % 5) * 0.01,
        .precision  = 0.78 + (rand() % 5) * 0.01,
        .recall     = 0.79 + (rand() % 5) * 0.01,
        .f1         = 0.785,
        .perplexity = 50.0  - (rand() % 10)
    };

    model->trained_steps += 1;

    if (out_metrics) *out_metrics = m;
    _ll_notify(model, &m);
    return LL_OK;
}

LL_Status ll_hybrid_model_predict(const LL_HybridModel* model,
                                  const char*           input_text,
                                  char**                out_prediction)
{
    if (!model || !input_text || !out_prediction)
        return LL_ERR_INVALID_ARG;

    const char* stub = "[HybridModel] Prediction unavailable in stub build.";
    size_t len = strlen(stub) + 1;

    char* pred = (char*)malloc(len);
    if (!pred) return LL_ERR_OOM;

    memcpy(pred, stub, len);
    *out_prediction = pred;
    return LL_OK;
}

LL_Status ll_hybrid_model_save(const LL_HybridModel* model,
                               const char*           path)
{
    if (!model || !path) return LL_ERR_INVALID_ARG;

    FILE* fp = fopen(path, "wb");
    if (!fp) return LL_ERR_IO;

    /* Simple binary serialization of config structure.                     */
    if (fwrite(&model->cfg, sizeof model->cfg, 1, fp) != 1)
    {
        fclose(fp);
        return LL_ERR_IO;
    }
    fclose(fp);
    return LL_OK;
}

LL_Status ll_hybrid_model_load(const char* path,
                               LL_HybridModel** out_model)
{
    if (!path || !out_model) return LL_ERR_INVALID_ARG;

    FILE* fp = fopen(path, "rb");
    if (!fp) return LL_ERR_IO;

    LL_HybridModelConfig cfg;
    if (fread(&cfg, sizeof cfg, 1, fp) != 1)
    {
        fclose(fp);
        return LL_ERR_SERIALIZATION;
    }
    fclose(fp);

    return ll_hybrid_model_create(&cfg, out_model);
}

LL_Status ll_hybrid_model_register_observer(LL_HybridModel* model,
                                            LL_MetricsObserver cb,
                                            void* user_ctx)
{
    if (!model || !cb) return LL_ERR_INVALID_ARG;

    ObserverNode* node = (ObserverNode*)malloc(sizeof *node);
    if (!node) return LL_ERR_OOM;
    node->cb       = cb;
    node->user_ctx = user_ctx;
    node->next     = model->observers;
    model->observers = node;
    return LL_OK;
}

LL_Status ll_hybrid_model_unregister_observer(LL_HybridModel* model,
                                              LL_MetricsObserver cb)
{
    if (!model || !cb) return LL_ERR_INVALID_ARG;

    ObserverNode** pprev = &model->observers;
    for (ObserverNode* it = model->observers; it; it = it->next)
    {
        if (it->cb == cb)
        {
            *pprev = it->next;
            free(it);
            return LL_OK;
        }
        pprev = &it->next;
    }
    return LL_ERR_INVALID_ARG; /* Not found */
}

#endif /* LEXILEARN_HYBRID_MODEL_IMPLEMENTATION */
#endif /* LEXILEARN_HYBRID_MODEL_H */
```