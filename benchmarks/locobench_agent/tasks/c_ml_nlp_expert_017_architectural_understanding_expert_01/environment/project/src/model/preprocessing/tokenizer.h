```c
/**
 * @file tokenizer.h
 * @author
 * @brief Tokenization strategy interface for the LexiLearn MVC Orchestrator.
 *
 * This header exposes an extensible, Strategy-Pattern-based tokenizer API that
 * can be swapped at runtime (e.g., whitespace, BPE, WordPiece, SentencePiece).
 * The interface is used by the Model-layer preprocessing pipeline as well as
 * by online inference services.  Implementation units must live in
 * src/model/preprocessing/tokenizer_<backend>.c and register themselves via
 * tokenizer_register_backend().
 *
 * Design goals:
 *   - Implementation agnostic: callers interact only with the opaque handle.
 *   - High performance: zero-copy slices where possible, SIMD-ready APIs.
 *   - Thread safety: immutable vocab + stateless tokenize(); only encode()
 *     relies on shared, read-only data.
 *   - MLOps ready: versioned vocabulary snapshots, checksum validation.
 *
 * Typical usage:
 *   tokenizer_t *tok = tokenizer_create("wordpiece",
 *                                       tokenizer_config_default());
 *   lexv_vector_t *ids = tokenizer_encode(tok, "Hello, world!", &status);
 *   tokenizer_destroy(tok);
 */

#ifndef LEXILEARN_MODEL_PREPROCESSING_TOKENIZER_H
#define LEXILEARN_MODEL_PREPROCESSING_TOKENIZER_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint32_t */
#include <stdbool.h>    /* bool   */
#include <stdio.h>      /* FILE   */

#include "lexilearn_common/lexv_vector.h"  /* Project-wide small-vector util. */
#include "lexilearn_common/status.h"       /* Centralized error code enum.    */
#include "lexilearn_common/sha256.h"       /* For vocab checksum validation.  */

/* --------------------------------------------------------------------------
 * Macros & constants
 * --------------------------------------------------------------------------*/

#define TOKENIZER_MAX_BACKEND_NAME 32
#define TOKENIZER_VERSION          "2.3.0"

/* --------------------------------------------------------------------------
 * Enumerations
 * --------------------------------------------------------------------------*/

/**
 * @brief Supported tokenizer back-ends.
 * Note: Actual availability depends on compile-time flags (see CMake options).
 */
typedef enum {
    TOKENIZER_BACKEND_WHITESPACE,
    TOKENIZER_BACKEND_WORDPIECE,
    TOKENIZER_BACKEND_BPE,
    TOKENIZER_BACKEND_SENTENCE_PIECE,
    TOKENIZER_BACKEND_CUSTOM /* User-provided via plug-in mechanism */
} tokenizer_backend_e;

/**
 * @brief Post-processing modes after initial token split.
 */
typedef enum {
    TOKENIZER_POST_NONE          = 0x00,
    TOKENIZER_POST_LOWER_CASE    = 0x01,
    TOKENIZER_POST_STRIP_PUNCT   = 0x02,
    TOKENIZER_POST_NORMALIZE_UNICODE = 0x04
} tokenizer_post_mode_e;

/* --------------------------------------------------------------------------
 * Configuration structure
 * --------------------------------------------------------------------------*/

/**
 * @struct tokenizer_config_t
 * @brief Configuration used during tokenizer creation.
 *
 * Configuration is treated as immutable after tokenizer_create(); callers
 * should allocate it on the stack or on the heap and pass a *copy* to
 * tokenizer_create() because implementations may retain a reference.
 */
typedef struct {
    size_t                vocab_size;        /**< For new training.             */
    tokenizer_post_mode_e post_processing;   /**< Lower-casing, punctuation…    */
    bool                  enable_cache;      /**< LRU cache for encode() calls. */
    size_t                cache_capacity;    /**< #entries in the LRU cache.    */
    uint32_t              random_seed;       /**< For stochastic models.        */
    char                  vocab_path[512];   /**< File path to serialized vocab */
} tokenizer_config_t;

/**
 * @brief Returns a sane default configuration.
 */
static inline tokenizer_config_t tokenizer_config_default(void)
{
    tokenizer_config_t cfg = {
        .vocab_size      = 30522,       /* BERT-base default                 */
        .post_processing = TOKENIZER_POST_NORMALIZE_UNICODE |
                           TOKENIZER_POST_STRIP_PUNCT,
        .enable_cache    = true,
        .cache_capacity  = 1024,
        .random_seed     = 42u,
        .vocab_path      = {0}
    };
    return cfg;
}

/* --------------------------------------------------------------------------
 * Opaque handle & forward declarations
 * --------------------------------------------------------------------------*/

/* Forward declaration of implementation detail. */
typedef struct tokenizer tokenizer_t;

/* Function-pointer table each backend must populate. */
typedef struct tokenizer_vtable {
    lexv_vector_t *(*tokenize)   (tokenizer_t *tok,
                                  const char  *input,
                                  ll_status_e *status);

    lexv_vector_t *(*encode)     (tokenizer_t *tok,
                                  const char  *input,
                                  ll_status_e *status);

    char          *(*detokenize) (tokenizer_t      *tok,
                                  const uint32_t  *ids,
                                  size_t           n_ids,
                                  ll_status_e     *status);

    void (*destroy)(tokenizer_t *tok);
} tokenizer_vtable_t;

/* --------------------------------------------------------------------------
 * Public API
 * --------------------------------------------------------------------------*/

/**
 * @brief Create a tokenizer instance.
 *
 * @param backend_name  String identifier (e.g., "wordpiece").  If NULL, falls
 *                      back to default backend configured at build time.
 * @param cfg           Pointer to configuration struct (may be NULL for
 *                      defaults).
 * @param status        Optional pointer to status enum; may be NULL.
 *
 * @return Pointer to tokenizer handle, or NULL on error.
 */
tokenizer_t *tokenizer_create(const char            *backend_name,
                              const tokenizer_config_t *cfg,
                              ll_status_e            *status);

/**
 * @brief Destroy tokenizer and free all associated resources.
 */
void tokenizer_destroy(tokenizer_t *tok);

/**
 * @brief Tokenize a UTF-8 string and return a vector of substrings.
 *
 * @note The returned lexv_vector_t contains char* entries.  Caller owns both
 *       the vector and the duplicated strings inside it.
 */
static inline
lexv_vector_t *tokenizer_tokenize(tokenizer_t *tok,
                                  const char  *input,
                                  ll_status_e *status)
{
    return (tok && tok->vtbl && tok->vtbl->tokenize)
           ? tok->vtbl->tokenize(tok, input, status)
           : NULL;
}

/**
 * @brief Encode a UTF-8 string into integer token IDs.
 *
 * @note Returned vector contains uint32_t values.
 */
static inline
lexv_vector_t *tokenizer_encode(tokenizer_t *tok,
                                const char  *input,
                                ll_status_e *status)
{
    return (tok && tok->vtbl && tok->vtbl->encode)
           ? tok->vtbl->encode(tok, input, status)
           : NULL;
}

/**
 * @brief Convert token IDs back into a UTF-8 string.
 *
 * Caller must free() the returned string.
 */
static inline
char *tokenizer_detokenize(tokenizer_t     *tok,
                           const uint32_t *ids,
                           size_t          n_ids,
                           ll_status_e    *status)
{
    return (tok && tok->vtbl && tok->vtbl->detokenize)
           ? tok->vtbl->detokenize(tok, ids, n_ids, status)
           : NULL;
}

/* --------------------------------------------------------------------------
 * Backend registration (internal; exposed for plug-ins)
 * --------------------------------------------------------------------------*/

/**
 * @brief Register a new tokenizer backend at runtime.
 *
 * Usually invoked from the backend’s init function, marked with
 * __attribute__((constructor)).
 *
 * @param name          Null-terminated name (max 31 chars).
 * @param vtbl          Virtual table with mandatory functions.
 *
 * @return LL_STATUS_OK on success, error code otherwise.
 */
ll_status_e tokenizer_register_backend(const char        *name,
                                       const tokenizer_vtable_t *vtbl);

/**
 * @brief Helper that loads and validates a vocabulary file.
 *
 * The function computes a SHA-256 checksum to verify integrity and optionally
 * checks version metadata embedded in the vocab header.
 *
 * @param path          Path to the vocab file.
 * @param out_tokens    Output pointer to an array of char* (token strings).
 * @param out_size      Output pointer to number of tokens.
 * @param status        Optional status return.
 */
void tokenizer_load_vocab(const char  *path,
                          char      ***out_tokens,
                          size_t       *out_size,
                          ll_status_e  *status);

/* --------------------------------------------------------------------------
 * Diagnostics
 * --------------------------------------------------------------------------*/

/**
 * @brief Print implementation info to the given FILE* stream.
 *
 * Example output:
 *   Backend       : WordPiece
 *   Version       : 1.2.0
 *   Vocab size    : 30522
 *   Post-process  : LOWER_CASE | STRIP_PUNCT
 */
void tokenizer_dump_info(const tokenizer_t *tok, FILE *stream);

/* --------------------------------------------------------------------------
 * Inline helpers
 * --------------------------------------------------------------------------*/

/**
 * @brief Convenience macro for resource-safe encode-and-free.
 *
 * Example:
 *   uint32_t *ids = NULL;
 *   size_t    n   = 0;
 *   TOKENIZER_ENCODE_STACK(my_tok, "hello", ids, n, status);
 *   // use ids…
 */
#define TOKENIZER_ENCODE_STACK(tok, str, out_ids, out_len, stat)       \
    lexv_vector_t *_tmp_vec = tokenizer_encode((tok), (str), (stat));  \
    (out_len) = _tmp_vec ? _tmp_vec->size : 0;                         \
    (out_ids) = _tmp_vec ? (uint32_t*)_tmp_vec->data : NULL;           \
    if (_tmp_vec) lexv_vector_move_to_stack(_tmp_vec) /* frees header */

/* --------------------------------------------------------------------------*/

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_PREPROCESSING_TOKENIZER_H */
```