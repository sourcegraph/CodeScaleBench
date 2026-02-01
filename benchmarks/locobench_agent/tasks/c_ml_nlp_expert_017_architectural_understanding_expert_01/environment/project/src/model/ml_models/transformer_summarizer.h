/**
 * transformer_summarizer.h
 *
 * LexiLearn MVC Orchestrator ― Model Layer
 * ----------------------------------------
 * A pragmatic, production-grade C interface for a transformer-based text
 * summarizer.  The API is purposely abstracted so that the underlying runtime
 * (ONNX Runtime, TensorRT, custom CUDA kernels, etc.) can be swapped out at
 * compile-time while the Controller and View layers remain untouched.
 *
 * Patterns / Practices employed:
 *   • Strategy Pattern – interchangeable summarizers share a common interface.
 *   • Observer Pattern – optional callback hooks for model-monitoring.
 *   • MLOps-ready – explicit configuration, version tagging, and metrics.
 *
 * This header is self-contained: define TRANSFORMER_SUMMARIZER_IMPLEMENTATION
 * in exactly one translation unit to emit the function bodies.
 *
 * Copyright (c) 2024  LexiLearn
 */

#ifndef LEXILEARN_TRANSFORMER_SUMMARIZER_H
#define LEXILEARN_TRANSFORMER_SUMMARIZER_H

/*───────────────────────────────────────────────────────────────────────────*/
/*  Standard & system includes                                              */
/*───────────────────────────────────────────────────────────────────────────*/
#include <stddef.h>     /* size_t  */
#include <stdint.h>     /* uint32_t*/
#include <stdbool.h>    /* bool    */
#include <stdio.h>      /* FILE, fprintf, stderr */
#include <stdlib.h>     /* malloc, free, getenv */
#include <string.h>     /* memcpy, memset, strchr */

/*───────────────────────────────────────────────────────────────────────────*/
/*  Public constants & macros                                               */
/*───────────────────────────────────────────────────────────────────────────*/
#define TSUM_VERSION "1.4.2"      /* SemVer for model registry      */
#define TSUM_MAX_ERROR_MSG 256    /* Fixed-length error buffer      */

/* clang-tidy & MISRA friendly nullability                              */
#ifndef TSUM_NONNULL
#   if defined(__clang__) || defined(__GNUC__)
#       define TSUM_NONNULL(...) __attribute__((nonnull(__VA_ARGS__)))
#   else
#       define TSUM_NONNULL(...)
#   endif
#endif /* TSUM_NONNULL */

/*───────────────────────────────────────────────────────────────────────────*/
/*  Enumerations                                                            */
/*───────────────────────────────────────────────────────────────────────────*/

/* Return codes for every public API call. 0 == success.                    */
typedef enum {
    TSUM_OK                           = 0,
    TSUM_ERR_INVALID_ARGUMENT         = 1,
    TSUM_ERR_RUNTIME_INIT             = 2,
    TSUM_ERR_MODEL_LOAD               = 3,
    TSUM_ERR_INFERENCE                = 4,
    TSUM_ERR_MEMORY                   = 5,
    TSUM_ERR_INTERNAL                 = 6
} tsum_status_e;

/* Possible execution backends. Extend as needed.                           */
typedef enum {
    TSUM_DEVICE_CPU = 0,
    TSUM_DEVICE_GPU = 1
} tsum_device_e;

/* Observer hooks for model-monitoring / drift detection.                   */
typedef void (*tsum_metrics_cb)(
        const char *metric_key,
        double      metric_value,
        void       *user_data);

/*───────────────────────────────────────────────────────────────────────────*/
/*  Configuration & opaque handle                                           */
/*───────────────────────────────────────────────────────────────────────────*/

/* User-supplied hyper-parameters and runtime options.                      */
typedef struct {
    const char  *model_path;          /* Path to .onnx / .pt / .bin file */
    const char  *model_version_tag;   /* e.g. "electra-base-summarizer"   */
    uint32_t     max_input_tokens;    /* Truncation length               */
    uint32_t     max_output_tokens;   /* e.g. 128                        */
    float        temperature;         /* For sampling-based decoding     */
    uint32_t     top_k;               /* For nucleus / top-k sampling    */
    tsum_device_e device;             /* Runtime backend (CPU/GPU)       */
    bool         enable_fp16;         /* Mixed precision inference       */
} tsum_config_t;

/* Forward declaration of the opaque context.                               */
typedef struct tsum_ctx tsum_ctx_t;

/*───────────────────────────────────────────────────────────────────────────*/
/*  Public API                                                              */
/*───────────────────────────────────────────────────────────────────────────*/

/**
 * Create a new summarizer context from the supplied configuration.
 * ctx_out is set to a valid handle on success.
 */
tsum_status_e
tsum_create(const tsum_config_t *cfg,
            tsum_ctx_t         **ctx_out,
            char                 err_msg[TSUM_MAX_ERROR_MSG]) TSUM_NONNULL(1,2,3);

/**
 * Produce a summary for the given UTF-8 encoded input text.
 * The returned char* is heap-allocated; caller must free() it.
 */
tsum_status_e
tsum_summarize(tsum_ctx_t    *ctx,
               const char    *input_text,
               char         **summary_out,
               char           err_msg[TSUM_MAX_ERROR_MSG]) TSUM_NONNULL(1,2,3,4);

/**
 * Dynamically update sampling hyper-parameters without re-loading the model.
 */
tsum_status_e
tsum_update_sampling(tsum_ctx_t *ctx,
                     float       temperature,
                     uint32_t    top_k,
                     char        err_msg[TSUM_MAX_ERROR_MSG]) TSUM_NONNULL(1,4);

/**
 * Register (or replace) a metrics callback for model-monitoring.
 * Pass NULL to disable callbacks.
 */
void
tsum_set_metrics_callback(tsum_ctx_t       *ctx,
                          tsum_metrics_cb   callback,
                          void             *user_data) TSUM_NONNULL(1);

/**
 * Destroy and free all resources tied to the context.
 * After this call the ctx pointer is no longer valid.
 */
void
tsum_destroy(tsum_ctx_t *ctx);

/*───────────────────────────────────────────────────────────────────────────*/
/*  Inline helpers                                                          */
/*───────────────────────────────────────────────────────────────────────────*/

/* Convert a status code to a human-readable string.                        */
static inline const char *tsum_status_str(const tsum_status_e s)
{
    switch (s) {
        case TSUM_OK:                     return "ok";
        case TSUM_ERR_INVALID_ARGUMENT:   return "invalid argument";
        case TSUM_ERR_RUNTIME_INIT:       return "runtime init failed";
        case TSUM_ERR_MODEL_LOAD:         return "model load failed";
        case TSUM_ERR_INFERENCE:          return "inference error";
        case TSUM_ERR_MEMORY:             return "memory allocation failed";
        case TSUM_ERR_INTERNAL:           return "internal error";
        default:                          return "unknown";
    }
}

/*───────────────────────────────────────────────────────────────────────────*/
/*  Implementation (define once)                                            */
/*───────────────────────────────────────────────────────────────────────────*/
#ifdef TRANSFORMER_SUMMARIZER_IMPLEMENTATION

/* Private context definition.                                              */
struct tsum_ctx {
    tsum_config_t   cfg;             /* User configuration (copied)      */
    tsum_metrics_cb metrics_cb;      /* Optional observer callback       */
    void           *metrics_ud;      /* User data forwarded to callback  */

    /* The ML runtime handle(s) would live here. For a real implementation
       hook into ONNX Runtime, TensorRT, etc. For portability we keep them
       as opaque void* pointers.                                            */
    void           *runtime_session;

    bool            initialized;     /* Sanity check flag                */
};

/*───────────────────────────────────────────────────────────────────────────*/
/*  Utility: safe malloc wrapper                                            */
/*───────────────────────────────────────────────────────────────────────────*/
static void *tsum_xmalloc(size_t n, char err_msg[TSUM_MAX_ERROR_MSG])
{
    void *p = malloc(n);
    if (!p) {
        if (err_msg) {
            snprintf(err_msg, TSUM_MAX_ERROR_MSG, "malloc(%zu) failed", n);
        }
    }
    return p;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*  Stub runtime init & shutdown                                            */
/*───────────────────────────────────────────────────────────────────────────*/
static tsum_status_e
tsum_runtime_start(tsum_ctx_t *ctx, char err_msg[TSUM_MAX_ERROR_MSG])
{
    /* For illustration we “fake” initialization. Replace with real code. */
    (void)ctx;
    (void)err_msg;
    return TSUM_OK;
}

static void
tsum_runtime_stop(tsum_ctx_t *ctx)
{
    (void)ctx;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*  Public function bodies                                                  */
/*───────────────────────────────────────────────────────────────────────────*/
tsum_status_e
tsum_create(const tsum_config_t *cfg,
            tsum_ctx_t         **ctx_out,
            char                 err_msg[TSUM_MAX_ERROR_MSG])
{
    if (!cfg || !ctx_out) { return TSUM_ERR_INVALID_ARGUMENT; }

    tsum_ctx_t *ctx = (tsum_ctx_t *)tsum_xmalloc(sizeof(*ctx), err_msg);
    if (!ctx) { return TSUM_ERR_MEMORY; }

    memset(ctx, 0, sizeof(*ctx));
    ctx->cfg = *cfg; /* Flat copy is fine: all members are POD/const char* */

    tsum_status_e st = tsum_runtime_start(ctx, err_msg);
    if (st != TSUM_OK) {
        free(ctx);
        return st;
    }

    ctx->initialized = true;
    *ctx_out = ctx;
    return TSUM_OK;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*  Naïve sentence-extractive summarizer                                    */
/*───────────────────────────────────────────────────────────────────────────*/
static char *extractive_summary(const char *text,
                                uint32_t    max_sentences,
                                char       *err_msg)
{
    if (!text) { return NULL; }

    /* Reserve rough memory: length of original + 1 for \0 (upper bound).   */
    size_t len = strlen(text) + 1;
    char *summary = (char *)tsum_xmalloc(len, err_msg);
    if (!summary) { return NULL; }

    size_t si = 0;
    uint32_t sentences = 0;

    for (size_t i = 0; text[i] != '\0' && sentences < max_sentences; ++i) {
        summary[si++] = text[i];

        if (text[i] == '.' || text[i] == '?' || text[i] == '!') {
            /* Skip consecutive punctuation / spaces                        */
            while (text[i + 1] == ' ' || text[i + 1] == '\n') {
                summary[si++] = text[++i];
            }
            ++sentences;
        }
    }

    summary[si] = '\0';
    return summary;
}

/*───────────────────────────────────────────────────────────────────────────*/
tsum_status_e
tsum_summarize(tsum_ctx_t    *ctx,
               const char    *input_text,
               char         **summary_out,
               char           err_msg[TSUM_MAX_ERROR_MSG])
{
    if (!ctx || !input_text || !summary_out) {
        return TSUM_ERR_INVALID_ARGUMENT;
    }
    if (!ctx->initialized) { return TSUM_ERR_INTERNAL; }

    /* Metrics: token length of the request                                 */
    if (ctx->metrics_cb) {
        ctx->metrics_cb("input_chars", (double)strlen(input_text),
                        ctx->metrics_ud);
    }

    /* Fake inference for demonstration: use first N sentences              */
    char *summary = extractive_summary(
        input_text,
        ctx->cfg.max_output_tokens > 0 ? ctx->cfg.max_output_tokens : 3,
        err_msg);

    if (!summary) { return TSUM_ERR_MEMORY; }

    /* Emit a dummy “rouge-1” score metric                                  */
    if (ctx->metrics_cb) {
        ctx->metrics_cb("rouge1", 0.42, ctx->metrics_ud);
    }

    *summary_out = summary;
    return TSUM_OK;
}

/*───────────────────────────────────────────────────────────────────────────*/
tsum_status_e
tsum_update_sampling(tsum_ctx_t *ctx,
                     float       temperature,
                     uint32_t    top_k,
                     char        err_msg[TSUM_MAX_ERROR_MSG])
{
    if (!ctx) { return TSUM_ERR_INVALID_ARGUMENT; }
    (void)err_msg;

    ctx->cfg.temperature = temperature;
    ctx->cfg.top_k       = top_k;
    return TSUM_OK;
}

/*───────────────────────────────────────────────────────────────────────────*/
void
tsum_set_metrics_callback(tsum_ctx_t       *ctx,
                          tsum_metrics_cb   callback,
                          void             *user_data)
{
    if (!ctx) { return; }
    ctx->metrics_cb = callback;
    ctx->metrics_ud = user_data;
}

/*───────────────────────────────────────────────────────────────────────────*/
void
tsum_destroy(tsum_ctx_t *ctx)
{
    if (!ctx) { return; }

    tsum_runtime_stop(ctx);
    memset(ctx, 0, sizeof(*ctx));
    free(ctx);
}

#endif /* TRANSFORMER_SUMMARIZER_IMPLEMENTATION */

#endif /* LEXILEARN_TRANSFORMER_SUMMARIZER_H */
