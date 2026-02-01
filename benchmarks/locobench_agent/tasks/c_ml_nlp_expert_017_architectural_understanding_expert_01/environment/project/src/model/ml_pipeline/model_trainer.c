```c
/**
 *  lexilearn_orchestrator/src/model/ml_pipeline/model_trainer.c
 *
 *  Production–quality implementation of a light-weight ML training
 *  service that demonstrates:
 *      • Data loading & preprocessing
 *      • Mini-batch gradient–descent training
 *      • Hyper-parameter tuning (threaded grid search)
 *      • Model evaluation & registry logging
 *      • Observer notification hooks (model drift / training events)
 *
 *  NOTE:  This single file is    self-contained and can be compiled with
 *      $ gcc -std=c11 -pthread -Wall -Wextra -o model_trainer model_trainer.c
 *
 *  In the full LexiLearn repository the forward-declared headers would be
 *  supplied by shared libraries.  Here we provide minimal stub versions
 *  so the code remains functional and unit-testable in isolation.
 */

#define _POSIX_C_SOURCE 200809L   /* For clock_gettime / getline */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <time.h>

/*───────────────────────────────────────────────────────────────────────────*/
/*                   Stub-only public dependency headers                     */
/*───────────────────────────────────────────────────────────────────────────*/
#ifndef LEXILEARN_FEATURE_STORE_H
#define LEXILEARN_FEATURE_STORE_H
typedef struct {
        /* Placeholder; real impl. backed by Redis / parquet cache */
        int stub;
} FeatureStore;
#endif /* LEXILEARN_FEATURE_STORE_H */

#ifndef LEXILEARN_REGISTRY_CLIENT_H
#define LEXILEARN_REGISTRY_CLIENT_H
static inline void registry_log_metric(const char *run_id,
                                       const char *metric_key,
                                       double      metric_val,
                                       size_t      step)
{
        (void)run_id; (void)metric_key; (void)metric_val; (void)step;
        /* Real implementation would call REST/gRPC endpoint. */
}
static inline void registry_log_artifact(const char *run_id,
                                         const char *artifact_path)
{
        (void)run_id; (void)artifact_path;
}
static inline void registry_set_tag(const char *run_id,
                                    const char *tag,
                                    const char *value)
{
        (void)run_id; (void)tag; (void)value;
}
#endif /* LEXILEARN_REGISTRY_CLIENT_H */

#ifndef LEXILEARN_OBSERVER_H
#define LEXILEARN_OBSERVER_H
static inline void observer_emit(const char *event_key,
                                 const char *payload)
{
        (void)event_key; (void)payload;
}
#endif /* LEXILEARN_OBSERVER_H */

/*───────────────────────────────────────────────────────────────────────────*/
/*                           Type Declarations                               */
/*───────────────────────────────────────────────────────────────────────────*/

/* Training return status enumeration */
typedef enum {
        TRAINER_OK = 0,
        TRAINER_ERR_IO,
        TRAINER_ERR_MEM,
        TRAINER_ERR_INVAL,
        TRAINER_ERR_TRAINING,
        TRAINER_ERR_THREAD
} trainer_status_t;

/* Hyper-parameter specification */
typedef struct {
        double  learning_rate;
        size_t  epochs;
        size_t  batch_size;
        double  l2_lambda;
} hyperparams_t;

/* Logistic regression model */
typedef struct {
        double *weights;   /* [n_features] */
        size_t  n_features;
} lr_model_t;

/* Encapsulates a training session */
typedef struct {
        FeatureStore     *fs;                 /* External dependency (stub) */
        char              run_id[64];         /* Experiment / registry id  */
        lr_model_t        model;              /* In-memory weights          */
        hyperparams_t     hp;                 /* Chosen hyper-params        */
        size_t            n_samples;          /* # of training samples      */
        size_t            n_features;         /* Feature dimensionality     */
        double           *X;                  /* Flattened row-major data   */
        double           *y;                  /* Labels (0/1)               */
} trainer_ctx_t;

/* Forward-declared helper functions */
static trainer_status_t  load_csv_dataset(const char *path,
                                          double    **out_X,
                                          double    **out_y,
                                          size_t     *out_rows,
                                          size_t     *out_cols);

static trainer_status_t  preprocess_standardize(double *X,
                                                size_t  rows,
                                                size_t  cols);

static trainer_status_t  lr_train(trainer_ctx_t *ctx);
static double            lr_eval(const trainer_ctx_t *ctx,
                                 const double         *X_val,
                                 const double         *y_val,
                                 size_t                rows);

/*───────────────────────────────────────────────────────────────────────────*/
/*                       Utility / Timing Helpers                            */
/*───────────────────────────────────────────────────────────────────────────*/

/* Monotonic clock for micro-benchmarking */
static inline double wall_time_sec(void)
{
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        return ts.tv_sec + ts.tv_nsec / 1e9;
}

/* Random double in [0,1) – thread-safe local state */
static inline double rand_uniform01(unsigned int *seed)
{
        return rand_r(seed) / (double)RAND_MAX;
}

/* Xavier/Glorot uniform init helper */
static void xavier_init(double *arr, size_t len, unsigned int *seed)
{
        const double limit = sqrt(6.0) / sqrt((double)len);
        for (size_t i = 0; i < len; ++i)
                arr[i] = (rand_uniform01(seed) * 2.0 * limit) - limit;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*                  Core logistic regression implementation                  */
/*───────────────────────────────────────────────────────────────────────────*/

/* Sigmoid with numeric stability */
static inline double sigmoid(double z)
{
        if (z >= 0) {
                double exp_neg = exp(-z);
                return 1.0 / (1.0 + exp_neg);
        } else {
                double exp_pos = exp(z);
                return exp_pos / (1.0 + exp_pos);
        }
}

/* One training epoch – mini-batch gradient descent */
static void lr_epoch_step(trainer_ctx_t *ctx,
                          size_t         start_idx,
                          size_t         batch_count,
                          double        *grad_out)   /* [n_features] */
{
        const size_t nf   = ctx->n_features;
        const size_t bs   = batch_count;
        const double lr   = ctx->hp.learning_rate;
        const double l2   = ctx->hp.l2_lambda;

        memset(grad_out, 0, sizeof(*grad_out) * nf);

        /* Compute gradient over batch */
        for (size_t i = 0; i < bs; ++i) {
                const size_t row = start_idx + i;
                const double *x  = ctx->X + row * nf;
                const double  y  = ctx->y[row];

                /* Dot product w^T x */
                double z = 0.0;
                for (size_t j = 0; j < nf; ++j)
                        z += ctx->model.weights[j] * x[j];

                double pred = sigmoid(z);
                double diff = pred - y;

                for (size_t j = 0; j < nf; ++j)
                        grad_out[j] += diff * x[j];
        }

        /* Apply updates */
        for (size_t j = 0; j < nf; ++j) {
                grad_out[j] = (grad_out[j] / bs) + (l2 * ctx->model.weights[j]);
                ctx->model.weights[j] -= lr * grad_out[j];
        }
}

/* Overall training loop */
static trainer_status_t lr_train(trainer_ctx_t *ctx)
{
        if (!ctx || !ctx->X || !ctx->y || !ctx->model.weights)
                return TRAINER_ERR_INVAL;

        const size_t nf       = ctx->n_features;
        const size_t ns       = ctx->n_samples;
        const size_t epochs   = ctx->hp.epochs;
        const size_t batch_sz = ctx->hp.batch_size;
        unsigned int seed     = (unsigned int)time(NULL);

        double *grad = calloc(nf, sizeof(*grad));
        if (!grad) return TRAINER_ERR_MEM;

        registry_set_tag(ctx->run_id, "algorithm", "logistic_regression");

        for (size_t epoch = 0; epoch < epochs; ++epoch) {
                /* Shuffle indices using Fisher-Yates */
                for (size_t i = ns - 1; i > 0; --i) {
                        size_t j = rand_r(&seed) % (i + 1);
                        if (j != i) {
                                /* Swap rows i and j in X and y */
                                for (size_t k = 0; k < nf; ++k) {
                                        double tmp                = ctx->X[i * nf + k];
                                        ctx->X[i * nf + k]        = ctx->X[j * nf + k];
                                        ctx->X[j * nf + k]        = tmp;
                                }
                                double tmpy = ctx->y[i];
                                ctx->y[i]    = ctx->y[j];
                                ctx->y[j]    = tmpy;
                        }
                }

                /* Mini-batch loop */
                for (size_t offset = 0; offset < ns; offset += batch_sz) {
                        size_t bs = ((ns - offset) < batch_sz)
                                    ? (ns - offset)
                                    : batch_sz;
                        lr_epoch_step(ctx, offset, bs, grad);
                }

                /* Simple metric: log-loss (cross entropy) */
                double loss = 0.0;
                for (size_t i = 0; i < ns; ++i) {
                        const double *x = ctx->X + i * nf;
                        double z = 0.0;
                        for (size_t j = 0; j < nf; ++j)
                                z += ctx->model.weights[j] * x[j];
                        double p = sigmoid(z);
                        double y = ctx->y[i];
                        /* clip p to avoid log(0) */
                        p = fmin(fmax(p, 1e-15), 1.0 - 1e-15);
                        loss += -(y * log(p) + (1.0 - y) * log(1.0 - p));
                }
                loss /= ns;

                registry_log_metric(ctx->run_id, "train_loss", loss, epoch);
        }

        free(grad);
        return TRAINER_OK;
}

/* Evaluate classification accuracy */
static double lr_eval(const trainer_ctx_t *ctx,
                      const double        *X_val,
                      const double        *y_val,
                      size_t               rows)
{
        size_t correct = 0;
        const size_t nf = ctx->n_features;

        for (size_t i = 0; i < rows; ++i) {
                const double *x = X_val + i * nf;
                double z = 0.0;
                for (size_t j = 0; j < nf; ++j)
                        z += ctx->model.weights[j] * x[j];
                double p = sigmoid(z);
                int    pred = (p >= 0.5);
                if (pred == (int)y_val[i])
                        ++correct;
        }
        return correct / (double)rows;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*                     Dataset loading & preprocessing                       */
/*───────────────────────────────────────────────────────────────────────────*/

/**
 * Read CSV with numeric features and final binary label column.
 * CPU-bound parsing; optimised for clarity over performance.
 */
static trainer_status_t load_csv_dataset(const char *path,
                                         double    **out_X,
                                         double    **out_y,
                                         size_t     *out_rows,
                                         size_t     *out_cols)
{
        if (!path || !out_X || !out_y || !out_rows || !out_cols)
                return TRAINER_ERR_INVAL;

        FILE *fp = fopen(path, "r");
        if (!fp) return TRAINER_ERR_IO;

        char   *line   = NULL;
        size_t  len    = 0;
        size_t  rows   = 0;
        size_t  cols   = 0;
        double *X      = NULL;
        double *y      = NULL;

        /* First pass: count rows & columns */
        while (getline(&line, &len, fp) != -1) {
                if (rows == 0) {
                        /* Count commas to infer column count */
                        cols = 1;
                        for (char *c = line; *c; ++c)
                                if (*c == ',') ++cols;
                        /* Last column is label */
                        if (cols == 0) { fclose(fp); free(line); return TRAINER_ERR_IO; }
                        --cols;
                }
                ++rows;
        }
        if (rows == 0 || cols == 0) {
                fclose(fp); free(line); return TRAINER_ERR_IO;
        }

        /* Allocate contiguous buffers */
        X = malloc(sizeof(*X) * rows * cols);
        y = malloc(sizeof(*y) * rows);
        if (!X || !y) {
                fclose(fp); free(line); free(X); free(y);
                return TRAINER_ERR_MEM;
        }

        /* Second pass: actually parse */
        rewind(fp);
        size_t r = 0;
        while (getline(&line, &len, fp) != -1) {
                char *saveptr = NULL;
                char *tok     = strtok_r(line, ",", &saveptr);
                size_t c      = 0;
                for (; c < cols && tok; ++c) {
                        X[r * cols + c] = atof(tok);
                        tok = strtok_r(NULL, ",", &saveptr);
                }
                if (!tok) { fclose(fp); free(line); free(X); free(y); return TRAINER_ERR_IO; }
                y[r] = atof(tok);
                ++r;
        }

        fclose(fp);
        free(line);

        *out_X    = X;
        *out_y    = y;
        *out_rows = rows;
        *out_cols = cols;
        return TRAINER_OK;
}

/* Simple z-score standardization per column */
static trainer_status_t preprocess_standardize(double *X,
                                               size_t  rows,
                                               size_t  cols)
{
        if (!X) return TRAINER_ERR_INVAL;

        double *mean = calloc(cols, sizeof(*mean));
        double *std  = calloc(cols, sizeof(*std));
        if (!mean || !std) { free(mean); free(std); return TRAINER_ERR_MEM; }

        /* Compute column means */
        for (size_t c = 0; c < cols; ++c) {
                double acc = 0.0;
                for (size_t r = 0; r < rows; ++r)
                        acc += X[r * cols + c];
                mean[c] = acc / rows;
        }

        /* Compute std deviation */
        for (size_t c = 0; c < cols; ++c) {
                double var = 0.0;
                for (size_t r = 0; r < rows; ++r) {
                        double diff = X[r * cols + c] - mean[c];
                        var += diff * diff;
                }
                std[c] = sqrt(var / rows);
                if (std[c] < 1e-12) std[c] = 1.0; /* Avoid divide-by-zero */
        }

        /* Normalize */
        for (size_t r = 0; r < rows; ++r)
                for (size_t c = 0; c < cols; ++c)
                        X[r * cols + c] = (X[r * cols + c] - mean[c]) / std[c];

        free(mean); free(std);
        return TRAINER_OK;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*                   Hyper-parameter tuning – grid search                    */
/*───────────────────────────────────────────────────────────────────────────*/

typedef struct {
        trainer_ctx_t base;      /* Copy of context prototype  */
        const char   *val_path;  /* Validation set path        */
        double        best_score;
} tune_worker_arg_t;

static void *tune_worker(void *arg)
{
        tune_worker_arg_t *tw = arg;
        trainer_ctx_t     *ctx = &tw->base;

        /* Load validation data */
        double *X_val = NULL, *y_val = NULL;
        size_t  rows  = 0, cols = 0;
        if (load_csv_dataset(tw->val_path, &X_val, &y_val, &rows, &cols) != TRAINER_OK) {
                fprintf(stderr, "[Tune] failed to load validation data\n");
                pthread_exit((void *) (intptr_t) TRAINER_ERR_IO);
        }
        preprocess_standardize(X_val, rows, cols);

        /* (Re)initialize model parameters */
        unsigned int seed = (unsigned int)time(NULL) ^ (uintptr_t)pthread_self();
        xavier_init(ctx->model.weights, ctx->n_features, &seed);

        /* Train */
        double train_start = wall_time_sec();
        trainer_status_t st = lr_train(ctx);
        if (st != TRAINER_OK) {
                fprintf(stderr, "[Tune] training error (%d)\n", st);
                free(X_val); free(y_val);
                pthread_exit((void *) (intptr_t) st);
        }

        /* Evaluate */
        double acc = lr_eval(ctx, X_val, y_val, rows);
        double train_dur = wall_time_sec() - train_start;

        tw->best_score = acc;

        registry_log_metric(ctx->run_id, "val_accuracy", acc, 0);
        registry_log_metric(ctx->run_id, "train_duration_sec", train_dur, 0);

        /* Notify observers */
        char buf[128];
        snprintf(buf, sizeof(buf), "{\"run_id\":\"%s\",\"accuracy\":%.4f}",
                 ctx->run_id, acc);
        observer_emit("MODEL_TRAINED", buf);

        free(X_val); free(y_val);
        pthread_exit((void *) (intptr_t) st);
}

/* Public API – hyper-parameter grid search (simplified) */
static trainer_status_t tune_hyperparameters(trainer_ctx_t *proto_ctx,
                                             const char    *val_csv_path,
                                             const hyperparams_t grid[],
                                             size_t         grid_len,
                                             trainer_ctx_t **best_ctx_out)
{
        if (!proto_ctx || !grid || grid_len == 0 || !best_ctx_out)
                return TRAINER_ERR_INVAL;

        pthread_t           *threads = calloc(grid_len, sizeof(*threads));
        tune_worker_arg_t   *args    = calloc(grid_len, sizeof(*args));
        if (!threads || !args) { free(threads); free(args); return TRAINER_ERR_MEM; }

        /* Launch one worker per grid candidate */
        for (size_t i = 0; i < grid_len; ++i) {
                args[i].base            = *proto_ctx; /* shallow copy */
                args[i].base.hp         = grid[i];
                args[i].val_path        = val_csv_path;
                args[i].base.model.weights =
                        malloc(sizeof(double) * proto_ctx->n_features);
                if (!args[i].base.model.weights) return TRAINER_ERR_MEM;

                snprintf(args[i].base.run_id, sizeof(args[i].base.run_id),
                         "run_%zu_%ld", i, time(NULL));

                if (pthread_create(&threads[i], NULL, tune_worker, &args[i]) != 0)
                        return TRAINER_ERR_THREAD;
        }

        trainer_status_t final_status = TRAINER_OK;
        double best_score = -1.0;
        size_t best_idx   = 0;

        /* Join threads & find best model */
        for (size_t i = 0; i < grid_len; ++i) {
                void *retval;
                pthread_join(threads[i], &retval);
                trainer_status_t st = (trainer_status_t)(intptr_t)retval;
                if (st != TRAINER_OK) final_status = st;

                if (args[i].best_score > best_score) {
                        best_score = args[i].best_score;
                        best_idx   = i;
                }
        }

        if (final_status == TRAINER_OK) {
                /* Return deep copy of best context */
                trainer_ctx_t *best = malloc(sizeof(*best));
                if (!best) return TRAINER_ERR_MEM;
                *best = args[best_idx].base;
                *best_ctx_out = best;

                /* Transfer ownership of weights to caller; avoid double-free */
                for (size_t i = 0; i < grid_len; ++i)
                        if (i != best_idx) free(args[i].base.model.weights);
        } else {
                for (size_t i = 0; i < grid_len; ++i)
                        free(args[i].base.model.weights);
        }

        free(threads); free(args);
        return final_status;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*                        Public Trainer API (Facade)                        */
/*───────────────────────────────────────────────────────────────────────────*/

trainer_status_t model_trainer_run(const char    *train_csv_path,
                                   const char    *val_csv_path,
                                   const char    *model_output_path)
{
        if (!train_csv_path || !val_csv_path || !model_output_path)
                return TRAINER_ERR_INVAL;

        /* 1. Load training dataset */
        double *X = NULL, *y = NULL;
        size_t  rows = 0, cols = 0;
        trainer_status_t st = load_csv_dataset(train_csv_path, &X, &y, &rows, &cols);
        if (st != TRAINER_OK) return st;

        /* 2. Preprocess */
        st = preprocess_standardize(X, rows, cols);
        if (st != TRAINER_OK) { free(X); free(y); return st; }

        /* 3. Proto context */
        trainer_ctx_t proto = {
                .fs          = NULL,
                .run_id      = "proto_run",
                .n_samples   = rows,
                .n_features  = cols,
                .X           = X,
                .y           = y,
                .model       = {.weights = NULL, .n_features = cols},
        };
        proto.model.weights = calloc(cols, sizeof(double));
        if (!proto.model.weights) { free(X); free(y); return TRAINER_ERR_MEM; }

        /* 4. Hyper-parameter grid */
        hyperparams_t grid[] = {
                {.learning_rate = 0.01, .epochs = 50,  .batch_size = 32, .l2_lambda = 0.0},
                {.learning_rate = 0.05, .epochs = 50,  .batch_size = 32, .l2_lambda = 0.0},
                {.learning_rate = 0.01, .epochs = 100, .batch_size = 64, .l2_lambda = 1e-4},
                {.learning_rate = 0.05, .epochs = 100, .batch_size = 64, .l2_lambda = 1e-4},
        };

        trainer_ctx_t *best_ctx = NULL;
        st = tune_hyperparameters(&proto,
                                  val_csv_path,
                                  grid,
                                  sizeof(grid)/sizeof(grid[0]),
                                  &best_ctx);
        if (st != TRAINER_OK) { free(X); free(y); free(proto.model.weights); return st; }

        /* 5. Persist best model */
        FILE *fp = fopen(model_output_path, "wb");
        if (!fp) {
                st = TRAINER_ERR_IO;
        } else {
                fwrite(best_ctx->model.weights,
                       sizeof(double),
                       best_ctx->n_features,
                       fp);
                fclose(fp);
                registry_log_artifact(best_ctx->run_id, model_output_path);
        }

        /* 6. Cleanup */
        free(X); free(y); free(proto.model.weights);
        free(best_ctx->model.weights);
        free(best_ctx);

        return st;
}

/*───────────────────────────────────────────────────────────────────────────*/
/*                              Unit test main                               */
/*───────────────────────────────────────────────────────────────────────────*/
#ifdef MODEL_TRAINER_TEST_MAIN
int main(void)
{
        trainer_status_t st = model_trainer_run("train.csv",
                                                "val.csv",
                                                "model.bin");
        if (st != TRAINER_OK)
                fprintf(stderr, "Training failed: %d\n", st);
        else
                printf("Training complete – model saved as model.bin\n");
        return (st == TRAINER_OK) ? EXIT_SUCCESS : EXIT_FAILURE;
}
#endif
```