/*
 * ----------------------------------------------------------------------------
 *  lexilearn_orchestrator/src/model/ml_models/hybrid_model.c
 *
 *  HybridModel – Combines transformer-based embeddings with a classical
 *  logistic-regression classifier.  Implements the Model Strategy interface
 *  used by LexiLearn’s MVC Orchestrator.  The implementation purposefully
 *  keeps the math lightweight while demonstrating production-grade structure,
 *  logging, error handling, and MLOps hooks (model registry, observer events).
 *
 *  NOTE:  This file purposefully avoids external heavyweight ML dependencies
 *  (e.g., ONNX Runtime, LAPACK).  A pluggable transformer embedding stub is
 *  provided.  Swap it with a genuine embedding backend by implementing
 *  `transformer_embed()` for your platform (e.g., C++ wrapper, micro-service,
 *  or GPU kernel).
 * ----------------------------------------------------------------------------
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <time.h>
#include <errno.h>

/* ---- Project-local headers ------------------------------------------------ */
#include "hybrid_model.h"          /* Corresponding header (public interface) */
#include "model_registry.h"        /* Global Model Registry  (MLOps)          */
#include "feature_store.h"         /* Shared feature store   (offline FE)     */
#include "observer.h"              /* Observer Pattern hooks (monitoring)    "
#include "logger.h"                /* Project-wide structured logger          */

/* ---- Compile-time configuration ------------------------------------------ */
#ifndef HM_DEFAULT_LR
#define HM_DEFAULT_LR          0.005     /* Default learning rate            */
#endif

#define HM_MAX_MODEL_ID_LEN        64
#define HM_EMBED_DIM             768     /* Must match transformer backend   */
#define HM_EARLY_STOP_PATIENCE     10     /* #valid epochs without improvement*/

/* ---- Simple error-handling helpers --------------------------------------- */
#define HM_SUCCESS                 0
#define HM_FAIL                    1

#define HM_CHECK(cond, msg, ret)                   \
    do {                                           \
        if (!(cond)) {                             \
            log_error("[HybridModel] %s", msg);    \
            errno = (ret);                         \
            return (ret);                          \
        }                                          \
    } while (0)

/* ---- Forward declarations for internal helpers --------------------------- */
static int  transformer_embed(const char *text,
                              double      *out_vec,
                              size_t       embed_dim);

static void shuffle_indices(size_t *idx, size_t n);
static double sigmoid(double z);

/* ---- Data structures ------------------------------------------------------ */
/* Minimalist variants are defined here to break include-dependency cycles.   */

typedef struct
{
    const char *text;      /* Raw sample text (UTF-8)                         */
    double     *feats;     /* Classical engineered features                   */
    size_t      feat_dim;  /* Number of classical features                    */
} sample_t;

typedef struct
{
    sample_t   *samples;   /* Pointer to array length = num_samples           */
    uint8_t    *labels;    /* Ground-truth labels 0/1                         */
    size_t      num_samples;
} dataset_t;

typedef struct
{
    double accuracy;
    double loss;
    double auc;
} metrics_t;

typedef struct hybrid_model_ctx_s
{
    char        model_id[HM_MAX_MODEL_ID_LEN];

    /* Hyper-parameters ------------------------------------------------------ */
    size_t      embed_dim;           /* Dimension of transformer embedding    */
    double      learning_rate;       /* Updatable during tuning               */
    size_t      epochs;
    size_t      batch_size;
    double      l2_reg;

    /* Model weights --------------------------------------------------------- */
    size_t      input_dim;           /* total_dim = feat_dim + embed_dim      */
    double     *weights;             /* [input_dim]                           */
    double      bias;

    /* Training state -------------------------------------------------------- */
    size_t      step;
    metrics_t   current_metrics;

    /* MLOps / monitoring ---------------------------------------------------- */
    observer_t *observer;            /* Optional; can be NULL                 */
    int         needs_persist;       /* Dirty flag for lazy checkpointing     */
} hybrid_model_ctx_t;

/* ---- Local prototypes exposed via Strategy interface --------------------- */
static void  *hybrid_model_init   (const char              *model_id,
                                   const hyperparams_t     *hp);

static int    hybrid_model_train  (void                    *ctx,
                                   const dataset_t         *train,
                                   const dataset_t         *valid);

static int    hybrid_model_predict(void                    *ctx,
                                   const sample_t          *sample,
                                   double                  *out_prob);

static int    hybrid_model_save   (void                    *ctx,
                                   const char              *artifact_path);

static void  *hybrid_model_load   (const char              *artifact_path);

static void   hybrid_model_free   (void                    *ctx);

/* ---- Public registration ------------------------------------------------- */
static model_strategy_t HYBRID_MODEL_STRATEGY =
{
    .name            = "hybrid_model",
    .init            = hybrid_model_init,
    .train           = hybrid_model_train,
    .predict         = hybrid_model_predict,
    .save            = hybrid_model_save,
    .load            = hybrid_model_load,
    .destroy         = hybrid_model_free
};

__attribute__((constructor))
static void register_strategy(void)
{
    register_model_strategy(&HYBRID_MODEL_STRATEGY);
}

/* ===========================================================================
 *                           Implementation Details
 * ==========================================================================*/

/* Allocate and initialize a new HybridModel context */
static void *hybrid_model_init(const char *model_id, const hyperparams_t *hp)
{
    hybrid_model_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx)
    {
        log_error("[HybridModel] Failed to allocate context: %s", strerror(errno));
        return NULL;
    }

    snprintf(ctx->model_id, HM_MAX_MODEL_ID_LEN, "%s", model_id ? model_id : "hybrid");

    /* Resolve hyper-params (use defaults when NULL) */
    ctx->embed_dim     = (hp && hp->embed_dim) ? hp->embed_dim : HM_EMBED_DIM;
    ctx->learning_rate = (hp && hp->learning_rate) ?
                          hp->learning_rate : HM_DEFAULT_LR;
    ctx->epochs        = (hp && hp->epochs)      ? hp->epochs      : 50;
    ctx->batch_size    = (hp && hp->batch_size)  ? hp->batch_size  : 32;
    ctx->l2_reg        = (hp && hp->l2)          ? hp->l2          : 1e-4;

    /* input_dim must be determined later once we see first sample (lazy) */
    ctx->input_dim     = 0;
    ctx->weights       = NULL;
    ctx->bias          = 0.0;
    ctx->step          = 0;
    ctx->needs_persist = 0;

    /* Attach default observer (monitors drift & metrics) */
    ctx->observer = create_default_observer(ctx->model_id);

    log_info("[HybridModel] Initialized model '%s'", ctx->model_id);
    return ctx;
}

/* Initialize weights lazily once we know feature dimensions */
static int init_weights(hybrid_model_ctx_t *ctx, size_t total_dim)
{
    ctx->input_dim = total_dim;
    ctx->weights   = calloc(total_dim, sizeof(double));
    if (!ctx->weights)
    {
        log_error("[HybridModel] Weight allocation failed: %s", strerror(errno));
        return HM_FAIL;
    }

    /* Xavier init */
    double scale = 1.0 / sqrt((double)total_dim);
    for (size_t i = 0; i < total_dim; ++i)
        ctx->weights[i] = ((double)rand() / RAND_MAX - 0.5) * 2.0 * scale;

    ctx->bias = 0.0;
    return HM_SUCCESS;
}

/* Compute forward pass probability */
static double forward(const hybrid_model_ctx_t *ctx,
                      const double *x)  /* length = input_dim */
{
    double z = ctx->bias;
    for (size_t i = 0; i < ctx->input_dim; ++i)
        z += ctx->weights[i] * x[i];
    return sigmoid(z);
}

/* ------------------------------ Training ---------------------------------- */
static int hybrid_model_train(void *vctx,
                              const dataset_t *train,
                              const dataset_t *valid)
{
    hybrid_model_ctx_t *ctx = (hybrid_model_ctx_t*)vctx;
    HM_CHECK(ctx && train, "Invalid arguments to train()", HM_FAIL);

    /* Determine dimensionalities from first sample */
    size_t total_dim = train->samples[0].feat_dim + ctx->embed_dim;
    if (ctx->input_dim == 0)
        HM_CHECK(init_weights(ctx, total_dim) == HM_SUCCESS,
                 "Weight initialization failed", HM_FAIL);

    size_t N  = train->num_samples;
    size_t bs = ctx->batch_size;

    /* For shuffling */
    size_t *idx = malloc(N * sizeof(size_t));
    HM_CHECK(idx, "shuffle allocation failed", HM_FAIL);
    for (size_t i = 0; i < N; ++i) idx[i] = i;

    double *x_buf = calloc(total_dim * bs, sizeof(double));
    HM_CHECK(x_buf, "mini-batch buffer alloc failed", HM_FAIL);

    log_info("[HybridModel] Starting training for %zu epochs (%zu samples)",
             ctx->epochs, N);

    double best_valid_loss = HUGE_VAL;
    size_t patience = 0;

    for (size_t epoch = 0; epoch < ctx->epochs; ++epoch)
    {
        shuffle_indices(idx, N);
        size_t processed = 0;

        while (processed < N)
        {
            size_t cur_bs = (processed + bs <= N) ? bs : (N - processed);
            /* Build input matrix ------------------------------------------------*/
            for (size_t b = 0; b < cur_bs; ++b)
            {
                size_t s_idx  = idx[processed + b];
                sample_t *sp  = &train->samples[s_idx];
                double  *dest = &x_buf[b * total_dim];

                /* Copy classical features */
                memcpy(dest, sp->feats, sp->feat_dim * sizeof(double));

                /* Compute embedding */
                transformer_embed(sp->text,
                                  dest + sp->feat_dim,
                                  ctx->embed_dim);

                /* (Optional) FeatureStore augmentation can be inserted here */
            }

            /* Forward + Backward for batch --------------------------------------*/
            double grad_b = 0.0;                 /* bias gradient accumulator   */
            for (size_t d = 0; d < ctx->input_dim; ++d)
                ctx->weights[d] *= (1.0 - ctx->learning_rate * ctx->l2_reg); /* L2 */

            for (size_t b = 0; b < cur_bs; ++b)
            {
                const double *xb = &x_buf[b * total_dim];
                double y_hat     = forward(ctx, xb);
                uint8_t y_true   = train->labels[idx[processed + b]];
                double  err      = y_hat - (double)y_true; /* derivative of BCE */

                /* Gradient step */
                for (size_t d = 0; d < ctx->input_dim; ++d)
                    ctx->weights[d] -= ctx->learning_rate * err * xb[d];

                grad_b += err;
            }
            ctx->bias -= ctx->learning_rate * (grad_b / cur_bs);

            processed += cur_bs;
            ctx->step++;
        }

        /* Validate -------------------------------------------------------------*/
        double val_loss = 0.0;
        size_t correct  = 0;
        for (size_t i = 0; i < valid->num_samples; ++i)
        {
            double prob;
            hybrid_model_predict(ctx, &valid->samples[i], &prob);
            uint8_t pred = prob >= 0.5;
            uint8_t y    = valid->labels[i];
            correct     += (pred == y);

            /* Binary cross-entropy */
            double eps  = 1e-9;
            val_loss   += - ( y *  log(prob + eps) +
                             (1 - y)*log(1.0 - prob + eps));
        }
        val_loss /= valid->num_samples;
        double acc = (double)correct / valid->num_samples;

        ctx->current_metrics.loss     = val_loss;
        ctx->current_metrics.accuracy = acc;
        ctx->needs_persist            = 1;  /* mark as dirty */

        log_info("[HybridModel][Epoch %zu] val_loss=%.4f accuracy=%.3f",
                 epoch+1, val_loss, acc);

        /* Observer notification (model drift / monitoring) */
        if (ctx->observer)
            observer_on_epoch_end(ctx->observer, epoch, &ctx->current_metrics);

        /* Early stopping */
        if (val_loss < best_valid_loss)
        {
            best_valid_loss = val_loss;
            patience = 0;
            /* Save checkpoint to registry */
            char uri[256];
            snprintf(uri, sizeof(uri),
                     "registry://%s/checkpoints/best.ckpt", ctx->model_id);
            hybrid_model_save(ctx, uri);
        }
        else if (++patience >= HM_EARLY_STOP_PATIENCE)
        {
            log_warn("[HybridModel] Early stopping after %zu epochs", epoch+1);
            break;
        }
    }

    free(idx);
    free(x_buf);
    return HM_SUCCESS;
}

/* ------------------------------ Predict ----------------------------------- */
static int hybrid_model_predict(void *vctx, const sample_t *sample, double *out_prob)
{
    hybrid_model_ctx_t *ctx = (hybrid_model_ctx_t*)vctx;
    HM_CHECK(ctx && sample && out_prob, "predict() bad args", HM_FAIL);

    if (ctx->input_dim == 0)
    {
        log_error("[HybridModel] predict() before training!");
        return HM_FAIL;
    }

    /* Build full feature vector on the stack */
    double *x = alloca(ctx->input_dim * sizeof(double));

    /* Copy classical features */
    memcpy(x, sample->feats, sample->feat_dim * sizeof(double));

    /* Embed text */
    transformer_embed(sample->text,
                      x + sample->feat_dim,
                      ctx->embed_dim);

    *out_prob = forward(ctx, x);
    return HM_SUCCESS;
}

/* ------------------------------ Serialization ----------------------------- */
static int hybrid_model_save(void *vctx, const char *artifact_path)
{
    hybrid_model_ctx_t *ctx = (hybrid_model_ctx_t*)vctx;
    HM_CHECK(ctx && artifact_path, "save() bad args", HM_FAIL);

    FILE *fp = fopen(artifact_path, "wb");
    HM_CHECK(fp, "Unable to open artifact for writing", HM_FAIL);

    /* Metadata header ------------------------------------------------------- */
    fwrite("LEXI_HM1", 1, 8, fp);  /* simple magic */
    fwrite(&ctx->input_dim,  sizeof(ctx->input_dim),  1, fp);
    fwrite(&ctx->embed_dim,  sizeof(ctx->embed_dim),  1, fp);
    fwrite(&ctx->bias,       sizeof(ctx->bias),       1, fp);
    fwrite(ctx->weights, sizeof(double), ctx->input_dim, fp);

    fclose(fp);
    log_info("[HybridModel] Saved model to %s", artifact_path);

    ctx->needs_persist = 0;
    return HM_SUCCESS;
}

static void *hybrid_model_load(const char *artifact_path)
{
    FILE *fp = fopen(artifact_path, "rb");
    if (!fp)
    {
        log_error("[HybridModel] Unable to load artifact %s: %s",
                  artifact_path, strerror(errno));
        return NULL;
    }

    char magic[9] = {0};
    fread(magic, 1, 8, fp);
    if (strcmp(magic, "LEXI_HM1") != 0)
    {
        log_error("[HybridModel] Invalid artifact magic");
        fclose(fp);
        return NULL;
    }

    hybrid_model_ctx_t *ctx = calloc(1, sizeof(*ctx));
    fread(&ctx->input_dim,  sizeof(ctx->input_dim), 1, fp);
    fread(&ctx->embed_dim,  sizeof(ctx->embed_dim), 1, fp);
    fread(&ctx->bias,       sizeof(ctx->bias),      1, fp);

    ctx->weights = malloc(ctx->input_dim * sizeof(double));
    fread(ctx->weights, sizeof(double), ctx->input_dim, fp);
    fclose(fp);

    snprintf(ctx->model_id, HM_MAX_MODEL_ID_LEN, "hybrid_loaded");
    ctx->learning_rate = HM_DEFAULT_LR; /* default unless overridden */
    ctx->observer      = create_default_observer(ctx->model_id);

    log_info("[HybridModel] Loaded model from %s (input_dim=%zu)",
             artifact_path, ctx->input_dim);

    return ctx;
}

/* ------------------------------ Free -------------------------------------- */
static void hybrid_model_free(void *vctx)
{
    hybrid_model_ctx_t *ctx = (hybrid_model_ctx_t*)vctx;
    if (!ctx) return;

    if (ctx->needs_persist)
    {
        char uri[256];
        snprintf(uri, sizeof(uri),
                 "registry://%s/checkpoints/autosave.ckpt", ctx->model_id);
        hybrid_model_save(ctx, uri);
    }

    free(ctx->weights);
    destroy_observer(ctx->observer);
    free(ctx);

    log_debug("[HybridModel] Freed context");
}

/* ===========================================================================
 *                           Helper Functions
 * ==========================================================================*/

/* Very naive transformer embedding stub.
 * REPLACE with your actual embedding system.
 */
static int transformer_embed(const char *text,
                             double *out_vec,
                             size_t embed_dim)
{
    if (!text || !out_vec) return HM_FAIL;

    /* Use deterministic pseudo-random values seeded by text hash */
    uint32_t hash = 2166136261u;
    for (const unsigned char *p = (const unsigned char*)text; *p; ++p)
        hash = (hash ^ *p) * 16777619u;

    srand(hash);
    for (size_t i = 0; i < embed_dim; ++i)
        out_vec[i] = (double)rand() / RAND_MAX;

    return HM_SUCCESS;
}

static void shuffle_indices(size_t *idx, size_t n)
{
    for (size_t i = n - 1; i > 0; --i)
    {
        size_t j = rand() % (i + 1);
        size_t tmp = idx[i];
        idx[i] = idx[j];
        idx[j] = tmp;
    }
}

static double sigmoid(double z)
{
    if (z >= 0)
    {
        double exp_neg = exp(-z);
        return 1.0 / (1.0 + exp_neg);
    }
    else
    {
        double exp_pos = exp(z);
        return exp_pos / (1.0 + exp_pos);
    }
}