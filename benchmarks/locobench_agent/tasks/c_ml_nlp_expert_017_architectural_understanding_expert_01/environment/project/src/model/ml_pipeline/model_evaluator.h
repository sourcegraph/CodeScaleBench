```c
/**
 * ============================================================================
 *  LexiLearn Orchestrator – Model Evaluator Public Interface
 *  File:    model_evaluator.h
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Author:  LexiLearn Core Team
 *  License: MIT
 *  ----------------------------------------------------------------------------
 *  Description:
 *      This header exposes a production-grade, pluggable evaluation framework
 *      for NLP / ML models inside the LexiLearn platform.  The evaluator
 *      supports classical classification/regression metrics as well as
 *      sequence-to-sequence metrics (BLEU, ROUGE, perplexity).  Developers may
 *      register custom metrics at run-time, integrate with the Model Registry
 *      for lineage tracking, and hook observer callbacks to enable automated
 *      retraining when performance degradation (model drift) is detected.
 *
 *      The interface is written in pure C but is C++ compatible and is safe
 *      for use in multi-threaded contexts (internal state is thread-local or
 *      user-managed).  All API calls return detailed error codes; a
 *      thread-local error buffer is available for human-readable diagnostics.
 * ============================================================================
 */

#ifndef LEXILEARN_MODEL_EVALUATOR_H
#define LEXILEARN_MODEL_EVALUATOR_H

/* ---------------------------------------------------------------------------
 *  Standard Library Dependencies
 * ---------------------------------------------------------------------------*/
#include <stddef.h>      /* size_t */
#include <stdint.h>      /* uint8_t, uint16_t, etc. */
#include <stdbool.h>     /* bool   */
#include <time.h>        /* time_t */
#include <stdio.h>       /* FILE   */

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------------
 *  Versioning Macros (Semantic Versioning)
 * ---------------------------------------------------------------------------*/
#define LEXILEARN_ME_VERSION_MAJOR  1
#define LEXILEARN_ME_VERSION_MINOR  2
#define LEXILEARN_ME_VERSION_PATCH  0

#define LEXILEARN_ME_MAKE_VERSION(maj, min, pat) (((maj) << 16) | ((min) << 8) | (pat))
#define LEXILEARN_ME_VERSION \
        LEXILEARN_ME_MAKE_VERSION(LEXILEARN_ME_VERSION_MAJOR, \
                                  LEXILEARN_ME_VERSION_MINOR, \
                                  LEXILEARN_ME_VERSION_PATCH)

/* ---------------------------------------------------------------------------
 *  API Export / Import Macros
 * ---------------------------------------------------------------------------*/
#if defined(_WIN32) || defined(__CYGWIN__)
  #ifdef LEXILEARN_ME_BUILD_DLL
    #define LEXILEARN_ME_API __declspec(dllexport)
  #else
    #define LEXILEARN_ME_API __declspec(dllimport)
  #endif
#else
  #define LEXILEARN_ME_API __attribute__((visibility("default")))
#endif

/* ---------------------------------------------------------------------------
 *  Error Handling
 * ---------------------------------------------------------------------------*/
typedef enum {
    LEXILEARN_ME_OK = 0,
    LEXILEARN_ME_ERR_ALLOC,          /* Memory allocation failed                     */
    LEXILEARN_ME_ERR_BAD_ARG,        /* Invalid function argument                    */
    LEXILEARN_ME_ERR_IO,             /* I/O error (e.g., metric file serialization)  */
    LEXILEARN_ME_ERR_NOT_FOUND,      /* Requested resource not found                 */
    LEXILEARN_ME_ERR_METRIC_EXISTS,  /* Custom metric name already registered        */
    LEXILEARN_ME_ERR_METRIC_INVALID, /* Metric computation failed / returned NAN     */
    LEXILEARN_ME_ERR_INTERNAL,       /* Internal logic error                         */
    LEXILEARN_ME_ERR_UNSUPPORTED,    /* Feature not compiled in                      */
    LEXILEARN_ME_ERR_THREADING,      /* Threading / synchronization error            */
    LEXILEARN_ME_ERR_LIMIT_REACHED   /* Allocation or usage limit reached            */
} lexilearn_me_err_t;

/**
 * Retrieve a human-readable string for the last error on the calling thread.
 * The returned pointer is valid until the next API call on the same thread.
 */
LEXILEARN_ME_API const char *lexilearn_me_last_error(void);

/* ---------------------------------------------------------------------------
 *  Metric Type System
 * ---------------------------------------------------------------------------*/
typedef enum {
    LEXILEARN_ME_METRIC_ACCURACY,
    LEXILEARN_ME_METRIC_PRECISION,
    LEXILEARN_ME_METRIC_RECALL,
    LEXILEARN_ME_METRIC_F1,
    LEXILEARN_ME_METRIC_ROC_AUC,
    LEXILEARN_ME_METRIC_MAE,
    LEXILEARN_ME_METRIC_MSE,
    LEXILEARN_ME_METRIC_BLEU,
    LEXILEARN_ME_METRIC_ROUGE_L,
    LEXILEARN_ME_METRIC_PERPLEXITY,
    /* Custom metrics start at 1024 to avoid clashing with built-ins */
    LEXILEARN_ME_METRIC_CUSTOM_BASE = 1024
} lexilearn_me_metric_id_t;

/* Forward-declaration of opaque evaluator context */
typedef struct lexilearn_me_context_s lexilearn_me_context_t;

/* ---------------------------------------------------------------------------
 *  Confusion Matrix Representation
 * ---------------------------------------------------------------------------*/
typedef struct {
    size_t  num_labels;
    /* Row major matrix of size num_labels x num_labels */
    uint64_t *cells;
} lexilearn_me_confmat_t;

/* ---------------------------------------------------------------------------
 *  Metric Result Variant
 * ---------------------------------------------------------------------------*/
typedef struct {
    lexilearn_me_metric_id_t metric_id;
    union {
        double          scalar;   /* For single-value metrics (accuracy, etc.)   */
        lexilearn_me_confmat_t cm;/* For confusion matrix–producing metrics      */
        /* Future: Add distribution, histogram, etc.                             */
    } value;
} lexilearn_me_metric_result_t;

/* ---------------------------------------------------------------------------
 *  Dataset Abstraction
 * ---------------------------------------------------------------------------*/
typedef struct {
    const void *inputs;           /* User-allocated input buffer                  */
    const void *targets;          /* Ground-truth labels / sequences              */
    size_t      count;            /* Number of samples                            */
    void       *reserved;         /* Reserved for future metadata                 */
} lexilearn_me_dataset_t;

/* ---------------------------------------------------------------------------
 *  Custom Metric Callback Signature
 * ---------------------------------------------------------------------------*/
/**
 * Custom metric callback.
 *
 * @param  predictions     Pointer to model predictions  (implementation defined)
 * @param  targets         Pointer to ground-truth labels/values
 * @param  sample_count    Number of samples in predictions/targets
 * @param  user_ctx        Opaque pointer supplied during registration
 * @param  out_result      Output pointer to store metric result
 *
 * @return LEXILEARN_ME_OK on success or appropriate error code.
 */
typedef lexilearn_me_err_t (*lexilearn_me_custom_metric_fn)(
        const void *predictions,
        const void *targets,
        size_t      sample_count,
        void       *user_ctx,
        lexilearn_me_metric_result_t *out_result);

/* ---------------------------------------------------------------------------
 *  Observer Pattern: Drift Callback
 * ---------------------------------------------------------------------------*/
/**
 * Performance drift callback invoked when monitored metric crosses a threshold.
 * All callbacks execute on the evaluation thread—implementations must return
 * quickly or hand off work to another thread.
 */
typedef void (*lexilearn_me_drift_callback_fn)(
        const lexilearn_me_metric_result_t *metric,
        void                               *user_ctx);

/* ---------------------------------------------------------------------------
 *  Evaluator Configuration & Lifecycle
 * ---------------------------------------------------------------------------*/
typedef struct {
    size_t                          num_threads;  /* 0 = auto */
    bool                            enable_cache; /* memoize metric results */
    bool                            keep_confmat; /* store confusion matrix  */
} lexilearn_me_config_t;

/**
 * Create a new evaluator context.
 *
 * @param  cfg       Optional configuration (NULL = defaults)
 * @param  out_ctx   Returns newly allocated context pointer
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_create(const lexilearn_me_config_t *cfg,
                    lexilearn_me_context_t     **out_ctx);

/**
 * Destroy an evaluator context and release all associated resources.
 * Safe to pass NULL.
 */
LEXILEARN_ME_API void
lexilearn_me_destroy(lexilearn_me_context_t *ctx);

/* ---------------------------------------------------------------------------
 *  Custom Metric Registration
 * ---------------------------------------------------------------------------*/
/**
 * Register a custom metric at run-time.
 *
 * @param ctx            Evaluator context
 * @param name           Null-terminated unique metric name
 * @param callback       Pointer to metric implementation
 * @param user_ctx       User data passed back to callback
 * @param out_metric_id  Returns assigned metric identifier
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_register_custom_metric(lexilearn_me_context_t    *ctx,
                                    const char                *name,
                                    lexilearn_me_custom_metric_fn callback,
                                    void                      *user_ctx,
                                    lexilearn_me_metric_id_t  *out_metric_id);

/* ---------------------------------------------------------------------------
 *  Metric Evaluation
 * ---------------------------------------------------------------------------*/
/**
 * Evaluate a batch of predictions against ground-truth targets.
 *
 * @param ctx           Evaluator context
 * @param dataset       Pointer to dataset struct describing targets
 * @param predictions   Pointer to model predictions buffer
 * @param metrics       Array of metric IDs to compute
 * @param metric_count  Length of metrics array
 * @param out_results   Caller-allocated array of results (metric_count length)
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_evaluate_batch(lexilearn_me_context_t          *ctx,
                            const lexilearn_me_dataset_t    *dataset,
                            const void                      *predictions,
                            const lexilearn_me_metric_id_t  *metrics,
                            size_t                           metric_count,
                            lexilearn_me_metric_result_t    *out_results);

/**
 * Stream-oriented evaluation API for large datasets.  Must call begin, then
 * feed multiple chunks, and finally end.  Enables bounded memory usage.
 */
typedef struct lexilearn_me_stream_s lexilearn_me_stream_t;

/* Begin streaming session */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_stream_begin(lexilearn_me_context_t         *ctx,
                          const lexilearn_me_metric_id_t *metrics,
                          size_t                          metric_count,
                          lexilearn_me_stream_t         **out_stream);

/* Feed next chunk */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_stream_feed(lexilearn_me_stream_t *stream,
                         const void            *pred_chunk,
                         const void            *target_chunk,
                         size_t                 chunk_size);

/* End streaming session and obtain results */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_stream_end(lexilearn_me_stream_t     *stream,
                        lexilearn_me_metric_result_t *out_results /* metric_count */);

/* Abort streaming without producing results */
LEXILEARN_ME_API void
lexilearn_me_stream_abort(lexilearn_me_stream_t *stream);

/* ---------------------------------------------------------------------------
 *  Drift Monitoring
 * ---------------------------------------------------------------------------*/
/**
 * Attach a drift callback to a metric.  When the absolute difference between
 * the latest value and the reference exceeds 'threshold', the callback fires.
 *
 * @param ctx            Evaluator context
 * @param metric_id      Metric to monitor (must have been computed previously)
 * @param reference      Baseline/reference value
 * @param threshold      Threshold that triggers drift notification
 * @param callback       User-supplied callback
 * @param user_ctx       User data passed to callback
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_monitor_drift(lexilearn_me_context_t       *ctx,
                           lexilearn_me_metric_id_t      metric_id,
                           double                        reference,
                           double                        threshold,
                           lexilearn_me_drift_callback_fn callback,
                           void                         *user_ctx);

/* ---------------------------------------------------------------------------
 *  Serialization Helpers (Model Registry Integration)
 * ---------------------------------------------------------------------------*/
/**
 * Serialize metric results to disk in a stable, deterministic binary format
 * understood by the LexiLearn Model Registry.
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_save_results(const lexilearn_me_metric_result_t *results,
                          size_t                              result_count,
                          const char                         *filepath,
                          bool                                compress);

/**
 * Load metric results from disk (inverse of save).
 * Memory for results is allocated by the function and must be freed with
 * lexilearn_me_free_results().
 */
LEXILEARN_ME_API lexilearn_me_err_t
lexilearn_me_load_results(const char                    *filepath,
                          lexilearn_me_metric_result_t **out_results,
                          size_t                        *out_count);

/* Free results loaded by lexilearn_me_load_results */
LEXILEARN_ME_API void
lexilearn_me_free_results(lexilearn_me_metric_result_t *results,
                          size_t                        result_count);

/* ---------------------------------------------------------------------------
 *  Utility: Pretty-print results for debugging / CLI tooling
 * ---------------------------------------------------------------------------*/
LEXILEARN_ME_API void
lexilearn_me_print_results(const lexilearn_me_metric_result_t *results,
                           size_t                              count,
                           FILE                               *stream);

/* ---------------------------------------------------------------------------
 *  Inline Helpers
 * ---------------------------------------------------------------------------*/
static inline const char *lexilearn_me_metric_name(lexilearn_me_metric_id_t id)
{
    switch (id) {
        case LEXILEARN_ME_METRIC_ACCURACY:   return "accuracy";
        case LEXILEARN_ME_METRIC_PRECISION:  return "precision";
        case LEXILEARN_ME_METRIC_RECALL:     return "recall";
        case LEXILEARN_ME_METRIC_F1:         return "f1";
        case LEXILEARN_ME_METRIC_ROC_AUC:    return "roc_auc";
        case LEXILEARN_ME_METRIC_MAE:        return "mae";
        case LEXILEARN_ME_METRIC_MSE:        return "mse";
        case LEXILEARN_ME_METRIC_BLEU:       return "bleu";
        case LEXILEARN_ME_METRIC_ROUGE_L:    return "rouge_l";
        case LEXILEARN_ME_METRIC_PERPLEXITY: return "perplexity";
        default:                             return "custom_metric";
    }
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_EVALUATOR_H */
```