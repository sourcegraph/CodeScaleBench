/*=============================================================================
 *  File:    ngram_analyzer.h
 *  Project: LexiLearn MVC Orchestrator — Model Layer
 *
 *  Description:
 *  ----------
 *  Public API for a classical statistical N-gram language-model strategy.
 *  The N-gram analyzer implements MLE/discounted probability estimation,
 *  model (de)serialization, online monitoring for model drift, and hooks
 *  for automated retraining—features that align with the platform’s MLOps
 *  requirements (hyper-parameter tuning, model versioning, etc.).
 *
 *  Usage Notes:
 *  -----------
 *  The API is pure C and compatible with C++ via extern "C".
 *  All heap allocations are performed through the portable LLNG_*
 *  allocator macros, which forward to malloc/realloc/free by default and
 *  can be globally overridden for custom memory-tracking if desired.
 *
 *  Thread Safety:
 *  -------------
 *  Training and mutation are NOT thread-safe.  Inference is read-only and
 *  can be called concurrently once training/fitting is complete.  Users
 *  must provide their own synchronization when mixing reads and writes.
 *
 *  Copyright:
 *  ---------
 *  (c) 2024 LexiLearn Research Labs.  All rights reserved.
 *===========================================================================*/

#ifndef LEXILEARN_ML_MODELS_NGRAM_ANALYZER_H_
#define LEXILEARN_ML_MODELS_NGRAM_ANALYZER_H_

#ifdef __cplusplus
extern "C" {
#endif

/* ======= Standard Library ======= */
#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uintXX_t */
#include <stdbool.h>  /* bool     */

/*-----------------------------------------------------------------------------
 *  Versioning
 *---------------------------------------------------------------------------*/
#define NGRAM_ANALYZER_VERSION      "1.2.0"
#define NGRAM_ANALYZER_MAGIC        0x4E474D30u  /* "NGM0" – little-endian */

/*-----------------------------------------------------------------------------
 *  Memory Abstraction (override for custom allocators)
 *---------------------------------------------------------------------------*/
#ifndef LLNG_MALLOC
  #include <stdlib.h>
  #define LLNG_MALLOC(sz)           malloc(sz)
  #define LLNG_CALLOC(n, sz)        calloc((n), (sz))
  #define LLNG_REALLOC(ptr, sz)     realloc((ptr), (sz))
  #define LLNG_FREE(ptr)            free(ptr)
#endif

/*-----------------------------------------------------------------------------
 *  Error Codes
 *---------------------------------------------------------------------------*/
typedef enum
{
    NGRAM_OK = 0,
    NGRAM_ERR_INVALID_ARG,
    NGRAM_ERR_OOM,
    NGRAM_ERR_IO,
    NGRAM_ERR_CORRUPT,
    NGRAM_ERR_UNSUPPORTED,
    NGRAM_ERR_INTERNAL
} ngram_status_t;

/*-----------------------------------------------------------------------------
 *  Smoothing / Discounting Strategy
 *---------------------------------------------------------------------------*/
typedef enum
{
    NGRAM_SMOOTH_NONE = 0,          /* Maximum-Likelihood Estimates          */
    NGRAM_SMOOTH_ADD_K,             /* Add-k / Laplace                       */
    NGRAM_SMOOTH_KNESER_NEY         /* Absolute-discount + continuation prob */
} ngram_smoothing_t;

/*-----------------------------------------------------------------------------
 *  Configuration Object
 *---------------------------------------------------------------------------*/
typedef struct
{
    uint8_t             n_order;           /* N in N-gram (e.g., 3 = trigram) */
    ngram_smoothing_t   smoothing;         /* Smoothing/discount algorithm     */
    double              k;                 /* 'k' for Add-k smoothing          */
    double              discount;          /* D for Absolute Discounting       */
    size_t              vocab_capacity;    /* Initial vocab table capacity     */
    size_t              hash_size;         /* Prime size for hash tables       */
    bool                enable_model_drift_monitoring; /* Observer Pattern    */
} ngram_config_t;

/*-----------------------------------------------------------------------------
 *  Forward Declarations
 *---------------------------------------------------------------------------*/
typedef struct ngram_model      ngram_model_t;
typedef struct ngram_drift_ctx  ngram_drift_ctx_t;

/*-----------------------------------------------------------------------------
 *  Logging Callbacks (Strategy Pattern: user-supplied)
 *---------------------------------------------------------------------------*/
typedef void (*ngram_log_cb)(const char *msg, void *user);

/*-----------------------------------------------------------------------------
 *  Drift Callback (Observer Pattern)
 *---------------------------------------------------------------------------*/
typedef void (*ngram_drift_cb)(ngram_model_t *model,
                               const ngram_drift_ctx_t *ctx,
                               void *user);

/*-----------------------------------------------------------------------------
 *  Public API
 *---------------------------------------------------------------------------*/

/*
 * ngram_model_create
 * ------------------
 * Construct and allocate a new N-gram model.  All fields in `cfg` must be
 * initialized; zero-init is acceptable for optional fields.
 *
 * Returns a valid pointer on success, or NULL if allocation fails or
 * parameters are invalid (checked in debug builds).
 */
ngram_model_t *
ngram_model_create(const ngram_config_t *cfg,
                   ngram_log_cb           logger,
                   void                  *logger_ud);

/*
 * ngram_model_free
 * ----------------
 * Destroys the model and releases all resources.  Safe to call with NULL.
 */
void
ngram_model_free(ngram_model_t *model);

/*
 * ngram_model_train
 * -----------------
 * Fit the language model on an array of UTF-8 documents.  Tokenization is
 * performed internally; the caller need only pass raw text.
 *
 * doc_ary:     Pointer to an array of NUL-terminated strings.
 * doc_count:   Number of documents in the array.
 *
 * Returns NGRAM_OK on success; otherwise an error code.
 */
ngram_status_t
ngram_model_train(ngram_model_t      *model,
                  const char * const *doc_ary,
                  size_t              doc_count);

/*
 * ngram_model_score_sequence
 * --------------------------
 * Compute log-probability (base-e) of a token-id sequence.  A negative
 * infinity (-INFINITY) indicates zero probability under the model.
 */
double
ngram_model_score_sequence(const ngram_model_t *model,
                           const uint32_t      *token_ids,
                           size_t               len);

/*
 * ngram_model_predict_next_token
 * ------------------------------
 * Given a context of up to (n-1) tokens, predict the most-likely next
 * token.  On success, returns NGRAM_OK and writes to out_token_id/out_prob.
 * On failure, returns an error code and leaves outputs untouched.
 */
ngram_status_t
ngram_model_predict_next_token(const ngram_model_t *model,
                               const uint32_t      *context_ids,
                               size_t               context_len,
                               uint32_t            *out_token_id,
                               double              *out_prob);

/*
 * ngram_model_perplexity
 * ----------------------
 * Evaluate model perplexity over a held-out set of documents.  A lower
 * value indicates better fit.  Returns +INFINITY if evaluation fails.
 */
double
ngram_model_perplexity(const ngram_model_t *model,
                       const char * const  *doc_ary,
                       size_t               doc_count);

/*
 * ngram_model_save / ngram_model_load
 * -----------------------------------
 * Portable binary (de)serialization with versioning and endianness
 * headers.  Suitable for checkpointing to a model registry.
 */
ngram_status_t
ngram_model_save(const ngram_model_t *model,
                 const char          *filepath);

ngram_model_t *
ngram_model_load(const char    *filepath,
                 ngram_log_cb   logger,
                 void          *logger_ud,
                 ngram_status_t *out_status /* optional */);

/*
 * ngram_model_register_drift_hook
 * -------------------------------
 * Attach a callback that is invoked when the streaming perplexity crosses
 * a configurable threshold (configured via `ngram_model_set_drift_threshold`).
 * Only one hook may be active at a time; registering NULL removes it.
 */
void
ngram_model_register_drift_hook(ngram_model_t *model,
                                ngram_drift_cb cb,
                                void          *user);

/*
 * ngram_model_set_drift_threshold
 * -------------------------------
 * Set threshold for triggering the drift hook.
 * new_threshold: Multiplicative factor w.r.t baseline perplexity.
 *                Example: 1.25 = 25% degradation allowed before trigger.
 */
void
ngram_model_set_drift_threshold(ngram_model_t *model,
                                double         new_threshold);

/*
 * ngram_model_enable_auto_retrain
 * -------------------------------
 * Enable/disable automatic retraining when drift is detected.  The caller
 * must still provide a valid training set via `ngram_model_train_async`.
 */
void
ngram_model_enable_auto_retrain(ngram_model_t *model,
                                bool           enable);

/*-----------------------------------------------------------------------------
 *  Optional:  Asynchronous Training (Factory-generated Jobs)
 *---------------------------------------------------------------------------*/
typedef void (*ngram_train_done_cb)(ngram_model_t *updated_model,
                                    ngram_status_t status,
                                    void          *user);

/*
 * ngram_model_train_async
 * -----------------------
 * Non-blocking training; spawns worker thread(s) via the controller’s job
 * factory.  Returns immediately with NGRAM_OK if job was queued.
 */
ngram_status_t
ngram_model_train_async(ngram_model_t       *model,
                        const char * const  *doc_ary,
                        size_t               doc_count,
                        ngram_train_done_cb  done_cb,
                        void               *user);

/*-----------------------------------------------------------------------------
 *  Diagnostics & Introspection
 *---------------------------------------------------------------------------*/

/*  Retrieve current vocabulary size. */
size_t
ngram_model_get_vocab_size(const ngram_model_t *model);

/*  Retrieve n-order (unigram, bigram, …). */
uint8_t
ngram_model_get_order(const ngram_model_t *model);

/*  Return pointer to opaque config (read-only). */
const ngram_config_t *
ngram_model_get_config(const ngram_model_t *model);

/*-----------------------------------------------------------------------------
 *  Inline Helpers
 *---------------------------------------------------------------------------*/
static inline bool
ngram_status_success(ngram_status_t st)
{
    return (st == NGRAM_OK);
}

/*-----------------------------------------------------------------------------
 *  Implementation Details
 *---------------------------------------------------------------------------*/
/*  Opaque struct definitions are intentionally hidden from users. */
struct ngram_model      { unsigned char _private[1]; };
struct ngram_drift_ctx  { unsigned char _private[1]; };

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* LEXILEARN_ML_MODELS_NGRAM_ANALYZER_H_ */
