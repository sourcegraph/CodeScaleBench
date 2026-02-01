/*
 * =============================================================================
 * LexiLearn MVC Orchestrator – Training Stage Interface
 * -----------------------------------------------------------------------------
 * File:    lexilearn_orchestrator/src/controller/pipeline/training_stage.h
 * Author:  LexiLearn Engineering <engineering@lexilearn.ai>
 *
 * Description:
 *      Public interface for authoring plug-and-play pipeline stages within the
 *      Controller layer of the LexiLearn MVC Orchestrator.  A “training stage”
 *      is a composable unit of work—data preprocessing, feature engineering,
 *      model training, evaluation, etc.—that can be orchestrated through the
 *      Pipeline Pattern.  Each stage exposes a life-cycle contract comprising
 *      init(), execute(), and destroy() callbacks, receives a shared
 *      LLTrainingContext, and reports status via strongly-typed error codes.
 *
 * Usage:
 *      1.  Implement callbacks that satisfy LLStageInitFn, LLStageExecuteFn,
 *          and LLStageDestroyFn signatures.  Allocate stage-specific state in
 *          init(), perform work in execute(), and clean up in destroy().
 *      2.  Populate an LLTrainingStage descriptor and register it with the
 *          Pipeline (see training_pipeline.h) or use LL_STAGE_DEFINE().
 *
 *      Example:
 *
 *          static int preprocessing_execute(LLTrainingContext *ctx, void *st);
 *
 *          LL_STAGE_DEFINE(
 *              PREPROCESSING,
 *              LL_STAGE_DATA_PREPROCESS,
 *              NULL,                      // optional init
 *              preprocessing_execute,
 *              NULL                       // optional destroy
 *          );
 *
 * License: Proprietary & Confidential – © 2024 LexiLearn, Inc.
 * =============================================================================
 */

#ifndef LEXILEARN_TRAINING_STAGE_H
#define LEXILEARN_TRAINING_STAGE_H

/* ------------------------------------------------------------------------- */
/*  Standard Library Dependencies                                            */
/* ------------------------------------------------------------------------- */
#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint64_t */
#include <stdbool.h>    /* bool   */
#include <stdio.h>      /* fprintf */
#include <stdlib.h>     /* malloc/free */

/* ------------------------------------------------------------------------- */
/*  C / C++ Compatibility                                                    */
/* ------------------------------------------------------------------------- */
#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 *  Error-handling helpers
 * ========================================================================= */
#define LL_OK                       (0)
#define LL_ERR_INVALID_ARG          (-1)
#define LL_ERR_MEMORY               (-2)
#define LL_ERR_INIT_STAGE           (-3)
#define LL_ERR_STAGE_EXECUTION      (-4)
#define LL_ERR_INTERNAL             (-5)

/* =========================================================================
 *  Enumerations
 * ========================================================================= */

/*
 * LLTrainingStageKind
 * --------------------------------------------------------------------------
 * Enumerates canonical stages of an ML/NLP experiment life-cycle. Custom
 * stages may declare LL_STAGE_CUSTOM_BASE + N to avoid collision.
 */
typedef enum
{
    LL_STAGE_UNINITIALIZED      = 0,
    LL_STAGE_DATA_PREPROCESS    = 1,
    LL_STAGE_FEATURE_ENGINEER   = 2,
    LL_STAGE_HYPERPARAM_TUNE    = 3,
    LL_STAGE_MODEL_TRAIN        = 4,
    LL_STAGE_EVALUATE           = 5,
    LL_STAGE_REGISTER_MODEL     = 6,
    LL_STAGE_MONITOR            = 7,
    LL_STAGE_CLEANUP            = 8,

    /* Reserve values >= 1024 for project-specific custom stages */
    LL_STAGE_CUSTOM_BASE        = 1024
} LLTrainingStageKind;

/* =========================================================================
 *  Forward declarations – opaque handles owned by other subsystems
 * ========================================================================= */
struct LLConfig;
struct LLLogger;
struct LLModelRegistry;
struct LLObserverBus;

/* =========================================================================
 *  Context object passed to every stage
 * ========================================================================= */
typedef struct
{
    /*
     * Unique identifier for the experiment run (e.g., UUIDv4 string).  Allows
     * stages to correlate metrics and artifacts across the pipeline.
     */
    char            run_id[64];

    /* Timestamp (ms since Unix epoch) when the pipeline execution started. */
    uint64_t        start_ts_epoch_ms;

    /* Pointers to shared infrastructure components.  Ownership is external. */
    struct LLConfig         *config;        /* Global experiment configuration   */
    struct LLLogger         *logger;        /* Application-wide structured logger*/
    struct LLModelRegistry  *registry;      /* Model registry / experiment store */
    struct LLObserverBus    *bus;           /* Event bus for Observer pattern    */

    /*
     * Optional user data blob that orchestrator users may pass through the
     * pipeline.  Ownership semantics: if non-NULL, caller is responsible for
     * freeing this pointer after pipeline completion.
     */
    void            *user_data;

} LLTrainingContext;

/* =========================================================================
 *  Function pointer typedefs – stage life-cycle
 * ========================================================================= */

/*
 * LLStageInitFn
 * --------------------------------------------------------------------------
 * Allocate and initialize per-stage state.
 *
 * Parameters:
 *      ctx         Shared training context.
 *      out_state   [out] Address of void* to receive stage-specific state.
 *
 * Returns:
 *      LL_OK on success, otherwise an LL_ERR_* code.
 */
typedef int (*LLStageInitFn)(LLTrainingContext *ctx, void **out_state);

/*
 * LLStageExecuteFn
 * --------------------------------------------------------------------------
 * Perform the primary work of the stage.
 *
 * Parameters:
 *      ctx         Shared training context.
 *      state       Pointer previously returned by init().  May be NULL if
 *                  stage does not allocate per-stage data.
 *
 * Returns:
 *      LL_OK on success, otherwise an LL_ERR_* code.
 */
typedef int (*LLStageExecuteFn)(LLTrainingContext *ctx, void *state);

/*
 * LLStageDestroyFn
 * --------------------------------------------------------------------------
 * Release any resources allocated in init().
 *
 * Parameters:
 *      ctx         Shared training context (read-only).
 *      state       Per-stage state pointer.  Must be freed by the function if
 *                  it was allocated by init().  May be NULL.
 */
typedef void (*LLStageDestroyFn)(LLTrainingContext *ctx, void *state);

/* =========================================================================
 *  Training stage descriptor
 * ========================================================================= */
typedef struct
{
    LLTrainingStageKind  kind;       /* Categorical identifier               */
    const char          *name;       /* Human-readable stage name            */

    LLStageInitFn        init;       /* Optional (may be NULL)               */
    LLStageExecuteFn     execute;    /* Mandatory                            */
    LLStageDestroyFn     destroy;    /* Optional (may be NULL)               */
} LLTrainingStage;

/* =========================================================================
 *  Helper macros
 * ========================================================================= */

/*
 * LL_STAGE_DEFINE
 * --------------------------------------------------------------------------
 * Convenience macro for static stage descriptors.  Example:
 *
 *      LL_STAGE_DEFINE(MY_STAGE, LL_STAGE_MODEL_TRAIN,
 *                      my_init, my_execute, my_destroy);
 */
#define LL_STAGE_DEFINE(ident, _kind, _init, _exec, _destroy)           \
    static const LLTrainingStage ident = {                              \
        .kind    = (_kind),                                             \
        .name    = #ident,                                              \
        .init    = (_init),                                             \
        .execute = (_exec),                                             \
        .destroy = (_destroy)                                           \
    }

/*
 * LL_SAFE_FREE
 * --------------------------------------------------------------------------
 * Safe wrapper for free().  Sets the pointer to NULL after deallocation.
 */
#define LL_SAFE_FREE(ptr)   \
    do {                    \
        if ((ptr) != NULL)  \
        {                   \
            free(ptr);      \
            (ptr) = NULL;   \
        }                   \
    } while (false)

/* =========================================================================
 *  Inline helpers
 * ========================================================================= */

/*
 * ll_training_stage_run
 * --------------------------------------------------------------------------
 * Execute a single LLTrainingStage.  The utility handles optional init and
 * destroy calls as well as basic error propagation.
 *
 * Parameters:
 *      stage   Stage descriptor (must not be NULL).
 *      ctx     Shared training context (must not be NULL).
 *
 * Returns:
 *      LL_OK on success, otherwise LL_ERR_*
 *
 * Notes:
 *      – Stage implementers are encouraged to log verbose diagnostic info via
 *        ctx->logger rather than printing directly to stdout/stderr.
 *      – In production, you may wish to replace fprintf() with the project’s
 *        centralized logger to enforce structured logging.
 */
static inline int
ll_training_stage_run(const LLTrainingStage *stage, LLTrainingContext *ctx)
{
    if (stage == NULL || ctx == NULL || stage->execute == NULL)
        return LL_ERR_INVALID_ARG;

    void *state = NULL;
    int rc = LL_OK;

    /* --------------- init() --------------- */
    if (stage->init != NULL)
    {
        rc = stage->init(ctx, &state);
        if (rc != LL_OK)
        {
            if (ctx->logger == NULL)
                fprintf(stderr,
                        "[ERROR] Stage '%s' init failed with code %d\n",
                        stage->name, rc);
            goto cleanup;  /* Destroy not called if init failed */
        }
    }

    /* ------------- execute() -------------- */
    rc = stage->execute(ctx, state);
    if (rc != LL_OK)
    {
        if (ctx->logger == NULL)
            fprintf(stderr,
                    "[ERROR] Stage '%s' execute failed with code %d\n",
                    stage->name, rc);
        /* Fall through to destroy() regardless of execution result */
    }

cleanup:
    /* ------------- destroy() -------------- */
    if (stage->destroy != NULL)
        stage->destroy(ctx, state);

    return rc;
}

/* =========================================================================
 *  Compile-time sanity checks (C11 _Static_assert)
 * ========================================================================= */
#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(sizeof(LLTrainingStageKind) == sizeof(int),
               "LLTrainingStageKind must be int-sized for ABI stability");
#endif

/* ------------------------------------------------------------------------- */
/*  C / C++ Compatibility Footer                                             */
/* ------------------------------------------------------------------------- */
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_TRAINING_STAGE_H */
/* ===============================[ EOF ]==================================== */
