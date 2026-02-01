/*
 *  LexiLearn MVC Orchestrator – Model-Monitoring Component
 *  -------------------------------------------------------
 *  File:    lexilearn_orchestrator/src/controller/monitoring/retraining_trigger.c
 *  Author:  LexiLearn Core Team
 *
 *  Description:
 *      Production-grade implementation of the Controller-layer “Retraining Trigger”.
 *      The module listens to drift-metric events emitted by the Observer Pattern hooks
 *      in the Model layer.  When statistical drift exceeds configurable thresholds,
 *      it safely schedules an automated retraining job through an external scheduler
 *      (K8s-Job, Airflow DAG, or shell command), while guaranteeing thread-safety and
 *      idempotency.  Extensive logging is performed via syslog(3).
 *
 *  Build:
 *      cc -Wall -Wextra -pedantic -std=c11 -pthread -c retraining_trigger.c
 *
 *  External Deps:
 *      N/A – POSIX only.
 */

#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/*                        Publicly-Visible Type Definitions                   */
/* -------------------------------------------------------------------------- */

/* Payload produced by the Model-Monitoring observers. */
typedef struct
{
    const char *model_id;   /* Unique identifier of the model version         */
    double       accuracy;  /* Accuracy on hold-out                        [0,1] */
    double       f1_score;  /* F1 score on hold-out                        [0,1] */
    double       perplexity;/* Language-model perplexity                     >0  */
    uint64_t     timestamp_ms;
} ModelMetricsEvent;

/* Tuning knobs for drift detection and retraining policy. */
typedef struct
{
    size_t window;                   /* Sliding-window size (# events)        */
    double accuracy_drop_pct;        /* e.g. 0.05 for 5 % drop                */
    double f1_drop_pct;              /* idem                                  */
    double perplexity_increase_pct;  /* e.g. 0.10 for 10 % ↑                  */
    unsigned min_seconds_between_jobs; /* Cool-down period                    */
    char training_job_cmd[256];      /* Shell or CLI command to execute       */
} DriftMetricConfig;

/* Opaque handle exported to other Controller modules. */
typedef struct
{
    DriftMetricConfig cfg;

    /* Circular buffers for sliding-window stats. */
    double *accuracy_buf;
    double *f1_buf;
    double *perplexity_buf;
    size_t  buf_idx;
    size_t  buf_fill;

    /* Baseline metrics captured at time-of-deployment. */
    double baseline_accuracy;
    double baseline_f1;
    double baseline_perplexity;

    /* Synchronisation / re-entrancy guarantees. */
    pthread_mutex_t mtx;
    bool retraining_in_progress;
    time_t last_job_epoch_s;
} RetrainingTrigger;

/* -------------------------------------------------------------------------- */
/*                              Internal Helpers                              */
/* -------------------------------------------------------------------------- */

/* Allocate zeroed, exit-on-failure memory. */
static void *xcalloc(size_t n, size_t sz)
{
    void *p = calloc(n, sz);
    if (!p)
    {
        syslog(LOG_CRIT, "retraining_trigger: Out of memory (%zu bytes).", n * sz);
        exit(EXIT_FAILURE);
    }
    return p;
}

/* Insert value into circular buffer. */
static void buf_push(double *buf, size_t len, size_t *idx, size_t *fill, double val)
{
    buf[*idx] = val;
    *idx      = (*idx + 1) % len;
    if (*fill < len) (*fill)++;
}

/* Compute average of the circular buffer. */
static double buf_avg(const double *buf, size_t len, size_t fill)
{
    if (fill == 0) return 0.0;
    double sum = 0.0;
    for (size_t i = 0; i < fill; ++i) sum += buf[i];
    return sum / (double)fill;
}

/* Spawn a child process that executes the configured training job. */
static int spawn_training_job_async(const char *cmd)
{
    pid_t pid = fork();
    if (pid < 0)
    {
        syslog(LOG_ERR, "retraining_trigger: fork() failed: %s", strerror(errno));
        return -1;
    }
    if (pid == 0)
    {
        /* Child ‑ use /bin/sh to interpret command string. */
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        /* If execl() returns, an error occurred. */
        syslog(LOG_ERR, "retraining_trigger: execl() failed: %s", strerror(errno));
        _exit(EXIT_FAILURE);
    }
    /* Parent – detach from child, no wait (fire-and-forget). */
    return 0;
}

/* -------------------------------------------------------------------------- */
/*                              Public API Functions                          */
/* -------------------------------------------------------------------------- */

int retraining_trigger_init(RetrainingTrigger *rt,
                            const DriftMetricConfig *cfg,
                            double baseline_accuracy,
                            double baseline_f1,
                            double baseline_perplexity)
{
    if (!rt || !cfg) return -1;

    memset(rt, 0, sizeof *rt);
    rt->cfg               = *cfg;
    rt->accuracy_buf      = xcalloc(cfg->window, sizeof(double));
    rt->f1_buf            = xcalloc(cfg->window, sizeof(double));
    rt->perplexity_buf    = xcalloc(cfg->window, sizeof(double));
    rt->baseline_accuracy = baseline_accuracy;
    rt->baseline_f1       = baseline_f1;
    rt->baseline_perplexity = baseline_perplexity;
    pthread_mutex_init(&rt->mtx, NULL);
    rt->last_job_epoch_s = 0;

    openlog("lexilearn_retraining", LOG_CONS | LOG_PID, LOG_USER);
    syslog(LOG_INFO, "retraining_trigger: initialized (window=%zu, cmd=%s)",
           cfg->window, cfg->training_job_cmd);

    return 0;
}

void retraining_trigger_destroy(RetrainingTrigger *rt)
{
    if (!rt) return;

    free(rt->accuracy_buf);
    free(rt->f1_buf);
    free(rt->perplexity_buf);
    pthread_mutex_destroy(&rt->mtx);
    closelog();
    memset(rt, 0, sizeof *rt);
}

/* Ingest a single metrics event; may be invoked concurrently. */
void retraining_trigger_ingest(RetrainingTrigger *rt, const ModelMetricsEvent *ev)
{
    if (!rt || !ev) return;

    pthread_mutex_lock(&rt->mtx);

    /* Push values into circular buffers. */
    buf_push(rt->accuracy_buf,     rt->cfg.window, &rt->buf_idx, &rt->buf_fill, ev->accuracy);
    buf_push(rt->f1_buf,           rt->cfg.window, &rt->buf_idx, &rt->buf_fill, ev->f1_score);
    buf_push(rt->perplexity_buf,   rt->cfg.window, &rt->buf_idx, &rt->buf_fill, ev->perplexity);

    /* Drift evaluation only after buffer warmed up. */
    if (rt->buf_fill == rt->cfg.window && !rt->retraining_in_progress)
    {
        double avg_acc = buf_avg(rt->accuracy_buf,   rt->cfg.window, rt->buf_fill);
        double avg_f1  = buf_avg(rt->f1_buf,         rt->cfg.window, rt->buf_fill);
        double avg_px  = buf_avg(rt->perplexity_buf, rt->cfg.window, rt->buf_fill);

        bool acc_drift = (rt->baseline_accuracy > 0.0) &&
                         ((rt->baseline_accuracy - avg_acc) / rt->baseline_accuracy >= rt->cfg.accuracy_drop_pct);

        bool f1_drift  = (rt->baseline_f1 > 0.0) &&
                         ((rt->baseline_f1 - avg_f1) / rt->baseline_f1 >= rt->cfg.f1_drop_pct);

        bool px_drift  = (avg_px - rt->baseline_perplexity) / rt->baseline_perplexity
                         >= rt->cfg.perplexity_increase_pct;

        if (acc_drift || f1_drift || px_drift)
        {
            time_t now = time(NULL);
            if (difftime(now, rt->last_job_epoch_s) >= rt->cfg.min_seconds_between_jobs)
            {
                syslog(LOG_WARNING,
                       "retraining_trigger: Drift detected – scheduling retraining "
                       "(acc=%.4f, f1=%.4f, px=%.2f, model=%s)",
                       avg_acc, avg_f1, avg_px, ev->model_id ? ev->model_id : "unknown");

                if (spawn_training_job_async(rt->cfg.training_job_cmd) == 0)
                {
                    rt->retraining_in_progress = true;
                    rt->last_job_epoch_s       = now;
                }
            }
            else
            {
                syslog(LOG_INFO,
                       "retraining_trigger: Drift detected but cool-down active "
                       "(%lds remaining).",
                       (long)(rt->cfg.min_seconds_between_jobs -
                              difftime(now, rt->last_job_epoch_s)));
            }
        }
    }

    pthread_mutex_unlock(&rt->mtx);
}

/* Allow external components to inform that retraining finished successfully. */
void retraining_trigger_on_job_complete(RetrainingTrigger *rt,
                                        double new_baseline_acc,
                                        double new_baseline_f1,
                                        double new_baseline_px)
{
    if (!rt) return;

    pthread_mutex_lock(&rt->mtx);

    rt->baseline_accuracy    = new_baseline_acc;
    rt->baseline_f1          = new_baseline_f1;
    rt->baseline_perplexity  = new_baseline_px;
    rt->retraining_in_progress = false;

    /* Reset buffers so that new window collects post-deployment stats. */
    rt->buf_idx = rt->buf_fill = 0;

    syslog(LOG_INFO,
           "retraining_trigger: Retraining completed – baselines updated "
           "(acc=%.4f, f1=%.4f, px=%.2f).",
           new_baseline_acc, new_baseline_f1, new_baseline_px);

    pthread_mutex_unlock(&rt->mtx);
}

/* Utility to query whether a retraining job is currently running. */
bool retraining_trigger_is_busy(RetrainingTrigger *rt)
{
    if (!rt) return false;
    pthread_mutex_lock(&rt->mtx);
    bool busy = rt->retraining_in_progress;
    pthread_mutex_unlock(&rt->mtx);
    return busy;
}

/* -------------------------------------------------------------------------- */
/*                         Example Usage (for test only)                      */
/* -------------------------------------------------------------------------- */
#ifdef RETRAINING_TRIGGER_SELFTEST
#include <signal.h>

/* Dummy stream of events to stress-test logic. */
static void *producer_thread(void *arg)
{
    RetrainingTrigger *rt = arg;
    ModelMetricsEvent  ev = {.model_id = "v1"};

    for (int i = 0; i < 1000; ++i)
    {
        ev.accuracy   = 0.90 - 0.0005 * i;       /* Gradual decay. */
        ev.f1_score   = 0.88  - 0.0006 * i;
        ev.perplexity = 30.0  + 0.05   * i;
        ev.timestamp_ms = (uint64_t)time(NULL) * 1000;

        retraining_trigger_ingest(rt, &ev);
        usleep(100 * 1000); /* 100 ms */
    }
    return NULL;
}

int main(void)
{
    DriftMetricConfig cfg = {
        .window                   = 20,
        .accuracy_drop_pct        = 0.05,
        .f1_drop_pct              = 0.05,
        .perplexity_increase_pct  = 0.10,
        .min_seconds_between_jobs = 30,
        .training_job_cmd         = "echo 'Starting retraining job...'"
    };

    RetrainingTrigger rt;
    retraining_trigger_init(&rt, &cfg, 0.90, 0.88, 30.0);

    pthread_t th;
    pthread_create(&th, NULL, producer_thread, &rt);

    /* Run for ~2 minutes then exit. */
    sleep(120);

    retraining_trigger_destroy(&rt);
    return 0;
}
#endif /* RETRAINING_TRIGGER_SELFTEST */
