/*
 *  LexiLearn Orchestrator: Model Strategy Interface
 *  File: lexilearn_orchestrator/src/model/ml_models/model_strategy.h
 *
 *  Description:
 *      This header formalises the Strategy Pattern contract for the Model layer.
 *      Concrete strategies (e.g. transformer_summarizer.c, ngram_tagger.c, or
 *      hybrid_meta_learner.c) must expose a constructor that returns an
 *      instance whose vptr satisfies the model_strategy_vtable_t defined here.
 *
 *      At runtime, the Controller layer requests a strategy by name.  A small
 *      registry implemented in model_strategy.c maps names to constructors,
 *      allowing educators and researchers to swap algorithms without touching
 *      Controller code or recompiling the full orchestrator.
 *
 *  Notes:
 *      • All functions return lexi_status_t for uniform error handling.
 *      • The interface is intentionally agnostic to the underlying ML
 *        framework (ONNX, TorchScript, custom C kernels, etc.).
 *      • This file is pure C and therefore includes an extern "C" guard so
 *        that strategies may be implemented in C++ when convenient.
 *
 *  Author:  LexiLearn Engineering
 *  License: Apache-2.0
 */

#ifndef LEXILEARN_MODEL_STRATEGY_H
#define LEXILEARN_MODEL_STRATEGY_H

#include <stddef.h>   /* size_t */
#include <stdint.h>   /* int64_t */
#include <stdbool.h>  /* bool */

#ifdef __cplusplus
extern "C" {
#endif

/*---------------------------------------------------------------------------
 * Global status / error-code enumeration
 *--------------------------------------------------------------------------*/
typedef enum
{
    LEXI_OK                    =  0,
    LEXI_ERR_INVALID_ARGUMENT  = -1,
    LEXI_ERR_NO_MEMORY         = -2,
    LEXI_ERR_IO                = -3,
    LEXI_ERR_NOT_IMPLEMENTED   = -4,
    LEXI_ERR_INTERNAL          = -5
} lexi_status_t;

/*---------------------------------------------------------------------------
 * Task types supported by LexiLearn.  Used for routing to the right model.
 *--------------------------------------------------------------------------*/
typedef enum
{
    TASK_SUMMARIZATION = 0,
    TASK_GRAMMAR_CORRECTION,
    TASK_PROFICIENCY_SCORING,
    TASK_KEYWORD_EXTRACTION,
    TASK_CUSTOM
} lexi_task_t;

/*---------------------------------------------------------------------------
 * Generic hyper-parameter container
 *--------------------------------------------------------------------------*/
typedef enum
{
    HP_TYPE_INT,
    HP_TYPE_DOUBLE,
    HP_TYPE_BOOL,
    HP_TYPE_STRING
} hp_type_t;

typedef struct
{
    const char *key;    /* e.g. "learning_rate" */
    hp_type_t   type;
    union
    {
        int64_t     i;
        double      d;
        bool        b;
        const char *s;
    } value;
} hyperparam_t;

/*---------------------------------------------------------------------------
 * Forward declarations of opaque resource types used across the system
 *--------------------------------------------------------------------------*/
typedef struct ll_dataset_t        ll_dataset_t;        /* defined in dataset.h */
typedef struct ll_feature_store_t  ll_feature_store_t;  /* defined in feature_store.h */
typedef struct ll_model_artifact_t ll_model_artifact_t; /* defined in registry.h */

/*---------------------------------------------------------------------------
 * Strategy object & vtable
 *--------------------------------------------------------------------------*/
struct model_strategy_vtable; /* fwd */

typedef struct model_strategy
{
    const char *name;                           /* strategy identifier */
    const struct model_strategy_vtable *vptr;   /* method table        */
    void *impl;                                 /* strategy-specific data */
} model_strategy_t;

/*
 *  Virtual table defining the lifecycle of a model strategy.
 *
 *  Implementations MUST fill in all mandatory function pointers.  Optional
 *  operations (e.g. load/save) may return LEXI_ERR_NOT_IMPLEMENTED when
 *  unsupported.
 */
typedef struct model_strategy_vtable
{
    /*
     *  configure():
     *      Apply a list of hyper-parameters prior to training.
     *
     *  Return:
     *      LEXI_OK on success, or appropriate error code.
     */
    lexi_status_t (*configure)(model_strategy_t      *self,
                               const hyperparam_t    *params,
                               size_t                 param_count);

    /*
     *  train():
     *      Fit the model to the given datasets.  The model artefact emitted
     *      here is registered with the Model Registry by the Controller.
     */
    lexi_status_t (*train)(model_strategy_t      *self,
                           const ll_dataset_t    *training_data,
                           const ll_dataset_t    *validation_data,
                           ll_model_artifact_t  **out_model);

    /*
     *  predict():
     *      Run inference using the current state of the model.
     *      Predictions are returned as a dataset so that downstream pipeline
     *      stages can treat them uniformly.
     */
    lexi_status_t (*predict)(model_strategy_t   *self,
                             const ll_dataset_t *input_data,
                             ll_dataset_t      **out_predictions);

    /*
     *  evaluate():
     *      Compute an evaluation metric (e.g. BLEU, ROUGE-L, accuracy).
     *      Metric choice is strategy-specific.
     */
    lexi_status_t (*evaluate)(model_strategy_t   *self,
                              const ll_dataset_t *test_data,
                              double             *out_score);

    /*
     *  save() / load():
     *      Persist or restore the model.  Implementation may stream to/from
     *      cloud object storage, local disk, or a database URI.
     */
    lexi_status_t (*save)(model_strategy_t *self,
                          const char       *artifact_uri);

    lexi_status_t (*load)(model_strategy_t *self,
                          const char       *artifact_uri);

    /*
     *  destroy():
     *      Finaliser invoked by the orchestrator when the strategy is no
     *      longer needed.  Must free all memory and release GPU/CPU handles.
     */
    void (*destroy)(model_strategy_t *self);

} model_strategy_vtable_t;

/*---------------------------------------------------------------------------
 * Registry API
 *  – Facilitates dynamic discovery and instantiation of strategies
 *---------------------------------------------------------------------------*/

/* Prototype that concrete strategies must expose */
typedef model_strategy_t *(*strategy_ctor_fn)(void);

/*
 *  ll_strategy_register():
 *      Register a constructor under a unique, case-insensitive name.
 *
 *  Typical usage (inside transformer_summarizer.c):
 *      static model_strategy_t *transformer_ctor(void) { … }
 *      __attribute__((constructor))
 *      static void _init(void)
 *      {
 *          ll_strategy_register("transformer_summarizer", transformer_ctor);
 *      }
 */
lexi_status_t ll_strategy_register(const char      *name,
                                   strategy_ctor_fn ctor);

/*
 *  ll_strategy_create():
 *      Instantiate a strategy by name.  Caller owns the returned pointer and
 *      must eventually invoke ->vptr->destroy().
 */
model_strategy_t *ll_strategy_create(const char *name);

/*
 *  ll_strategy_list():
 *      Enumerate all names currently registered.  The returned array is
 *      heap-allocated and must be freed via ll_strategy_free_name_list().
 */
void ll_strategy_list(char ***out_names, size_t *out_count);

/* Release memory allocated by ll_strategy_list(). */
void ll_strategy_free_name_list(char **names, size_t count);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_STRATEGY_H */
