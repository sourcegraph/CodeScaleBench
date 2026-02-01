#ifndef LEXILEARN_LL_MODEL_H
#define LEXILEARN_LL_MODEL_H
/**
 * ll_model.h
 *
 * LexiLearn MVC Orchestrator – Model-layer public interface.
 *
 * This header exposes an abstract, strategy-pattern based API for any
 * NLP/ML model that wishes to participate in the LexiLearn pipeline.
 *
 *     ┌────────────────────────────────────────────────────────┐
 *     │                    Model Registry                     │
 *     ├────────────────────────────────────────────────────────┤
 *     │                ll_model_t  (this file)                │
 *     ├────────────────────────────────────────────────────────┤
 *     │   transformer.c   │   ngram.c   │   hybrid.c   …       │
 *     └────────────────────────────────────────────────────────┘
 *
 * Each concrete model implementation plugs into the orchestrator by
 * filling out a v-table defined below.  This enables the Controller
 * pipeline to hot-swap models at run-time without re-compilation.
 *
 * Copyright 2024
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>     /* FILE */
#include <stdint.h>    /* uint32_t, etc. */
#include <stddef.h>    /* size_t   */
#include <stdbool.h>   /* bool     */

#ifdef __cplusplus
extern "C" {
#endif

/*──────────────────────────────────────────────────────────────*/
/*                     Error and status codes                  */
/*──────────────────────────────────────────────────────────────*/

typedef enum {
    LL_STATUS_OK                          = 0,
    LL_STATUS_ERR_INVALID_ARGUMENT        = 1,
    LL_STATUS_ERR_IO                      = 2,
    LL_STATUS_ERR_OUT_OF_MEMORY           = 3,
    LL_STATUS_ERR_MODEL_NOT_TRAINED       = 4,
    LL_STATUS_ERR_SERIALIZATION           = 5,
    LL_STATUS_ERR_INTERNAL                = 255
} ll_status_t;

/**
 * Convert status code to a human-readable string.
 * This function is async-signal-safe and thread-safe.
 */
const char *ll_status_to_str(ll_status_t code);

/*──────────────────────────────────────────────────────────────*/
/*                  Forward type declarations                  */
/*──────────────────────────────────────────────────────────────*/

typedef struct ll_model        ll_model_t;        /* Opaque handle              */
typedef struct ll_dataset       ll_dataset_t;      /* Provided by data layer     */
typedef struct ll_tensor        ll_tensor_t;       /* Minimal ND tensor          */
typedef struct ll_metric_set    ll_metric_set_t;   /* Key-value metric map       */

/*──────────────────────────────────────────────────────────────*/
/*                    Observer-pattern hooks                   */
/*──────────────────────────────────────────────────────────────*/

/**
 * Notified whenever a monitored event occurs (e.g., drift detected).
 * See ll_model_register_observer().
 */
typedef void (*ll_observer_cb)(
        ll_model_t          *model,
        const char          *event_name,
        const ll_metric_set_t *metrics,
        void                *user_data); /* opaque pointer passed on register */

/*──────────────────────────────────────────────────────────────*/
/*                       Hyper-parameters                      */
/*──────────────────────────────────────────────────────────────*/

/* Model-agnostic hyper-parameter key/value pair representation. */
typedef struct {
    const char *key;          /* UTF-8 key (null-terminated)     */
    const char *value;        /* UTF-8 value (null-terminated)   */
} ll_hparam_kv_t;

/**
 * The hyper-parameter set is a dynamic array.  Memory for keys/values
 * is managed by the caller; the library does not copy strings.
 */
typedef struct {
    ll_hparam_kv_t *items;
    size_t          count;
} ll_hparam_set_t;

/*──────────────────────────────────────────────────────────────*/
/*                       Model descriptors                     */
/*──────────────────────────────────────────────────────────────*/

typedef enum {
    LL_MODEL_TRANSFORMER = 1,
    LL_MODEL_NGRAM_ANALYZER,
    LL_MODEL_HYBRID,
    LL_MODEL_CUSTOM  /* Reserved for user-defined plug-ins */
} ll_model_kind_t;

#define LL_MODEL_ID_MAX 64   /* Model IDs are short ASCII tokens */

/**
 * Immutable metadata describing a model instance at runtime.
 */
typedef struct {
    char             model_id[LL_MODEL_ID_MAX]; /* Unique within registry */
    ll_model_kind_t  kind;                      /* Strategy family        */
    const char      *version_tag;               /* SemVer/git-style tag   */
} ll_model_info_t;

/*──────────────────────────────────────────────────────────────*/
/*                     Strategy function table                 */
/*──────────────────────────────────────────────────────────────*/

/* Forward declare vtable */
typedef struct ll_model_vtable ll_model_vtable_t;

/**
 * The primary model handle.  Always allocated through
 * ll_model_create() and destroyed via ll_model_destroy().
 */
struct ll_model {
    const ll_model_vtable_t *vptr;   /* Strategy pattern         */
    ll_model_info_t          info;   /* Publicly visible metadata*/
    void                    *impl;   /* Private implementation   */
};

/*─────────────────────  V-table definition  ───────────────────*/

struct ll_model_vtable {
    ll_status_t (*train)(
        ll_model_t       *self,
        const ll_dataset_t *training_data,
        const ll_hparam_set_t *hparams);

    ll_status_t (*predict)(
        ll_model_t        *self,
        const ll_tensor_t *input,
        ll_tensor_t       **output);       /* allocates output tensor */

    ll_status_t (*evaluate)(
        ll_model_t              *self,
        const ll_dataset_t      *test_data,
        ll_metric_set_t        **out_metrics); /* allocates metrics map */

    ll_status_t (*save)(
        ll_model_t *self,
        FILE       *fp);                    /* binary or JSON encoding */

    ll_status_t (*load)(
        ll_model_t *self,
        FILE       *fp);                    /* counterpart to save()   */

    void (*destroy)(ll_model_t *self);
};

/*──────────────────────────────────────────────────────────────*/
/*                   Public constructor/destructor              */
/*──────────────────────────────────────────────────────────────*/

/**
 * Factory function that queries the Model Registry to construct the
 * requested model.  The registry is responsible for wiring the proper
 * v-table and allocating the concrete implementation.
 *
 * @param kind          Strategy family (transformer, ngram, …).
 * @param requested_id  Optional specific model ID, or NULL to let the
 *                      factory choose the latest prod-ready version.
 * @param out_model     Out-param that receives the allocated handle.
 * @return              Status code.
 */
ll_status_t ll_model_create(
        ll_model_kind_t   kind,
        const char       *requested_id,
        ll_model_t      **out_model);

/**
 * Destroys model instance and releases all resources.  The pointer
 * becomes invalid after this call; set it to NULL manually if needed.
 */
void ll_model_destroy(ll_model_t *model);

/*──────────────────────────────────────────────────────────────*/
/*                    Delegating convenience API               */
/*──────────────────────────────────────────────────────────────*/

static inline ll_status_t
ll_model_train(ll_model_t *m,
               const ll_dataset_t *d,
               const ll_hparam_set_t *hp)
{
    return (m && m->vptr && m->vptr->train)
           ? m->vptr->train(m, d, hp)
           : LL_STATUS_ERR_INVALID_ARGUMENT;
}

static inline ll_status_t
ll_model_predict(ll_model_t *m,
                 const ll_tensor_t *in,
                 ll_tensor_t **out)
{
    return (m && m->vptr && m->vptr->predict)
           ? m->vptr->predict(m, in, out)
           : LL_STATUS_ERR_INVALID_ARGUMENT;
}

static inline ll_status_t
ll_model_evaluate(ll_model_t *m,
                  const ll_dataset_t *d,
                  ll_metric_set_t **metrics)
{
    return (m && m->vptr && m->vptr->evaluate)
           ? m->vptr->evaluate(m, d, metrics)
           : LL_STATUS_ERR_INVALID_ARGUMENT;
}

static inline ll_status_t
ll_model_save(ll_model_t *m, FILE *fp)
{
    return (m && m->vptr && m->vptr->save)
           ? m->vptr->save(m, fp)
           : LL_STATUS_ERR_INVALID_ARGUMENT;
}

static inline ll_status_t
ll_model_load(ll_model_t *m, FILE *fp)
{
    return (m && m->vptr && m->vptr->load)
           ? m->vptr->load(m, fp)
           : LL_STATUS_ERR_INVALID_ARGUMENT;
}

/*──────────────────────────────────────────────────────────────*/
/*                        Model Monitoring                     */
/*──────────────────────────────────────────────────────────────*/

/**
 * Register an observer callback for model-level events.  Multiple
 * observers may be attached; they fire sequentially in the order of
 * registration.  Ownership of user_data remains with the caller.
 */
ll_status_t ll_model_register_observer(
        ll_model_t      *model,
        ll_observer_cb   cb,
        void            *user_data);

/**
 * Force-flush any pending telemetry samples to the monitoring
 * back-end (e.g., Prometheus, OpenTelemetry, custom).
 */
ll_status_t ll_model_flush_metrics(ll_model_t *model);

/*──────────────────────────────────────────────────────────────*/
/*                     Tensor helper utilities                 */
/*──────────────────────────────────────────────────────────────*/

/**
 * A minimal Nd-tensor container suitable for predictions/gradients.
 * For real-world projects, integrate with an existing tensor lib.
 */
struct ll_tensor {
    /* Row-major contiguous buffer.  Ownership is explicit. */
    void   *data;
    size_t  elem_size;   /* bytes per element */
    size_t *shape;       /* dim sizes array   */
    size_t  ndims;       /* rank              */
};

/* Allocate tensor.  Zeroes memory on success. */
ll_tensor_t *ll_tensor_alloc(size_t elem_size,
                             const size_t *shape,
                             size_t ndims);

/* Deep-copy tensor (data + shape). */
ll_tensor_t *ll_tensor_clone(const ll_tensor_t *src);

/* Free tensor and its internal buffers. */
void ll_tensor_free(ll_tensor_t *t);

/*──────────────────────────────────────────────────────────────*/
/*                       Metric utilities                      */
/*──────────────────────────────────────────────────────────────*/

/* Simple string->double map for metrics such as accuracy, F1, BLEU. */
struct ll_metric_set {
    char  **keys;     /* UTF-8 */
    double *values;
    size_t  count;
};

ll_metric_set_t *ll_metric_set_alloc(void);
void             ll_metric_set_put(ll_metric_set_t *set,
                                   const char *key,
                                   double value);
bool             ll_metric_set_get(const ll_metric_set_t *set,
                                   const char *key,
                                   double *out_value);
void             ll_metric_set_free(ll_metric_set_t *set);

/*──────────────────────────────────────────────────────────────*/
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_LL_MODEL_H */
