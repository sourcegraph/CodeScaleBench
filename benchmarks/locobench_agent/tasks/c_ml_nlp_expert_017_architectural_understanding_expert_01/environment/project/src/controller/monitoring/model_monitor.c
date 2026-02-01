```c
/**
 *  File: model_monitor.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Description:
 *      Implements run–time model-performance surveillance for the Controller
 *      layer.  The monitor periodically polls the metrics exporter that is
 *      side-car’d with every deployed model instance, validates statistical
 *      drift, and notifies registered observers (e.g., the automated
 *      retraining scheduler) when thresholds are exceeded.
 *
 *      Architectural ties:
 *          • Pipeline Pattern – the monitor is a stage in the inference/
 *            retraining pipeline.
 *          • Observer Pattern – downstream components register callbacks
 *            to be invoked on drift events.
 *          • Model Registry – used to pull the reference (baseline) metrics
 *            against which live metrics are compared.
 *
 *  Build:
 *      Requires the cJSON library (https://github.com/DaveGamble/cJSON)
 *
 *      gcc -std=c11 -Wall -Wextra -pthread -lcjson -o model_monitor model_monitor.c
 */
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <cjson/cJSON.h>          /* External dependency – JSON parsing */

#include "logger.h"               /* Project-local, thread-safe logger */
#include "model_monitor.h"        /* Public API for the monitor module */
#include "network/http_client.h"  /* Thin wrapper over libcurl          */
#include "registry/registry.h"    /* Interface to Model Registry        */

/* -------------------------------------------------------------------------- */
/*                               Local typedefs                               */
/* -------------------------------------------------------------------------- */

typedef struct _ll_observer_node {
    ll_drift_callback          cb;
    void                      *user_data;
    struct _ll_observer_node  *next;
} ll_observer_node;

/* Main monitor object – opaque outside this compilation unit */
struct ll_model_monitor {
    char                 model_id[LL_MODEL_ID_MAX];
    ll_monitor_cfg       cfg;
    volatile bool        running;
    pthread_t            thread;
    ll_observer_node    *observers;
    pthread_mutex_t      lock;          /* protects observers list       */

    /* Cached baseline metrics */
    double               baseline_accuracy;
    double               baseline_loss;
};

/* -------------------------------------------------------------------------- */
/*                        Forward-declaration of helpers                      */
/* -------------------------------------------------------------------------- */
static void       *monitor_loop          (void *arg);
static bool        acquire_live_metrics  (const ll_model_monitor *mon,
                                          double                *acc_out,
                                          double                *loss_out,
                                          long                  *ts_out);
static bool        refresh_baseline      (ll_model_monitor *mon);
static bool        drift_detected        (const ll_model_monitor *mon,
                                          double                  live_acc,
                                          double                  live_loss);
static void        notify_observers      (ll_model_monitor *mon,
                                          const ll_drift_event  *event);
static void        free_observer_list    (ll_model_monitor *mon);

/* -------------------------------------------------------------------------- */
/*                             Public API implementation                      */
/* -------------------------------------------------------------------------- */
ll_model_monitor *ll_monitor_create(const char        *model_id,
                                    const ll_monitor_cfg *cfg)
{
    if (!model_id || !cfg) {
        ll_log_error("ll_monitor_create: invalid arguments");
        return NULL;
    }

    ll_model_monitor *mon = calloc(1, sizeof(*mon));
    if (!mon) {
        ll_log_errno("calloc");
        return NULL;
    }

    strlcpy(mon->model_id, model_id, sizeof(mon->model_id));
    memcpy(&mon->cfg, cfg, sizeof(*cfg));

    if (pthread_mutex_init(&mon->lock, NULL) != 0) {
        ll_log_errno("pthread_mutex_init");
        free(mon);
        return NULL;
    }

    if (!refresh_baseline(mon)) {
        ll_log_error("Failed to fetch baseline metrics – aborting monitor creation");
        pthread_mutex_destroy(&mon->lock);
        free(mon);
        return NULL;
    }

    return mon;
}

int ll_monitor_start(ll_model_monitor *mon)
{
    if (!mon) return -EINVAL;
    if (mon->running) return 0;   /* already running */

    mon->running = true;
    int rc = pthread_create(&mon->thread, NULL, monitor_loop, mon);
    if (rc != 0) {
        mon->running = false;
        ll_log_errno("pthread_create");
        return rc;
    }

    ll_log_info("[Monitor:%s] started (poll=%us, acc_tol=%.3f)",
                mon->model_id,
                mon->cfg.poll_interval_sec,
                mon->cfg.accuracy_tolerance);

    return 0;
}

void ll_monitor_stop(ll_model_monitor *mon)
{
    if (!mon) return;
    if (!mon->running) return;

    mon->running = false;
    pthread_kill(mon->thread, SIGUSR1); /* Interrupt sleep (see monitor_loop) */
    pthread_join(mon->thread, NULL);

    free_observer_list(mon);
    pthread_mutex_destroy(&mon->lock);

    ll_log_info("[Monitor:%s] stopped", mon->model_id);
    free(mon);
}

int ll_monitor_register_observer(ll_model_monitor *mon,
                                 ll_drift_callback cb,
                                 void             *user_data)
{
    if (!mon || !cb) return -EINVAL;

    ll_observer_node *node = calloc(1, sizeof(*node));
    if (!node) {
        ll_log_errno("calloc");
        return -ENOMEM;
    }
    node->cb        = cb;
    node->user_data = user_data;

    pthread_mutex_lock(&mon->lock);
    node->next       = mon->observers;
    mon->observers   = node;
    pthread_mutex_unlock(&mon->lock);

    return 0;
}

/* -------------------------------------------------------------------------- */
/*                             Background thread                              */
/* -------------------------------------------------------------------------- */

/* pthread sleep helper that can be interrupted with SIGUSR1 */
static int sleep_interrupible(unsigned seconds)
{
    struct timespec ts = {
        .tv_sec  = seconds,
        .tv_nsec = 0
    };
    return nanosleep(&ts, NULL);
}

static void *monitor_loop(void *arg)
{
    ll_model_monitor *mon = arg;

    /* Install signal handler so that pthread_kill wakes nanosleep */
    struct sigaction sa = { .sa_handler = SIG_IGN };
    sigaction(SIGUSR1, &sa, NULL);

    while (mon->running) {
        double live_acc = 0.0, live_loss = 0.0;
        long   ts       = 0L;

        if (!acquire_live_metrics(mon, &live_acc, &live_loss, &ts)) {
            ll_log_warn("[Monitor:%s] failed to read live metrics", mon->model_id);
            goto sleep_and_continue;
        }

        if (drift_detected(mon, live_acc, live_loss)) {
            ll_drift_event ev = {
                .model_id         = mon->model_id,
                .live_accuracy    = live_acc,
                .live_loss        = live_loss,
                .baseline_accuracy= mon->baseline_accuracy,
                .baseline_loss    = mon->baseline_loss,
                .timestamp        = ts
            };

            ll_log_warn("[Monitor:%s] DRIFT detected (live_acc=%.4f, baseline=%.4f)",
                        mon->model_id, live_acc, mon->baseline_accuracy);

            notify_observers(mon, &ev);

            /* Optionally fetch a new baseline after retraining or flagging */
            if (mon->cfg.auto_refresh_baseline)
                refresh_baseline(mon);
        }

sleep_and_continue:
        if (!mon->running) break;
        sleep_interrupible(mon->cfg.poll_interval_sec);
    }
    return NULL;
}

/* -------------------------------------------------------------------------- */
/*                               Helper functions                             */
/* -------------------------------------------------------------------------- */

static bool fetch_metrics_json(const char *url, char **json_buf, size_t *len)
{
    struct http_response resp = {0};
    if (http_get(url, &resp) != 0) {
        ll_log_error("HTTP GET failed for %s", url);
        return false;
    }
    *json_buf = resp.body;
    *len      = resp.body_len;
    return true;
}

static bool acquire_live_metrics(const ll_model_monitor *mon,
                                 double *acc_out,
                                 double *loss_out,
                                 long   *ts_out)
{
    char *json   = NULL;
    size_t len   = 0;
    bool ok      = false;

    if (!fetch_metrics_json(mon->cfg.metrics_endpoint, &json, &len))
        goto cleanup;

    cJSON *root = cJSON_ParseWithLength(json, len);
    if (!root) {
        ll_log_error("Invalid JSON from metrics endpoint");
        goto cleanup;
    }

    cJSON *acc  = cJSON_GetObjectItemCaseSensitive(root, "accuracy");
    cJSON *loss = cJSON_GetObjectItemCaseSensitive(root, "loss");
    cJSON *ts   = cJSON_GetObjectItemCaseSensitive(root, "timestamp");

    if (!cJSON_IsNumber(acc) || !cJSON_IsNumber(loss) || !cJSON_IsNumber(ts)) {
        ll_log_error("Metrics JSON missing required numeric fields");
        goto cleanup_json;
    }

    *acc_out = acc->valuedouble;
    *loss_out= loss->valuedouble;
    *ts_out  = (long)ts->valuedouble;
    ok = true;

cleanup_json:
    cJSON_Delete(root);
cleanup:
    free(json);
    return ok;
}

static bool refresh_baseline(ll_model_monitor *mon)
{
    struct registry_metrics bm = {0};

    if (registry_fetch_baseline(mon->model_id, &bm) != 0) {
        ll_log_error("Unable to fetch baseline metrics for model '%s'",
                     mon->model_id);
        return false;
    }

    mon->baseline_accuracy = bm.accuracy;
    mon->baseline_loss     = bm.loss;

    ll_log_info("[Monitor:%s] baseline refreshed (acc=%.4f, loss=%.4f)",
                mon->model_id, bm.accuracy, bm.loss);
    return true;
}

static bool drift_detected(const ll_model_monitor *mon,
                           double live_acc,
                           double live_loss)
{
    /* Primary rule: accuracy drop beyond tolerance           */
    double acc_drop = mon->baseline_accuracy - live_acc;
    if (acc_drop > mon->cfg.accuracy_tolerance) return true;

    /* Secondary rule: loss rise by % threshold (if provided) */
    if (mon->cfg.loss_tolerance > 0.0) {
        double loss_increase = live_loss - mon->baseline_loss;
        if (loss_increase > mon->cfg.loss_tolerance) return true;
    }

    return false;
}

static void notify_observers(ll_model_monitor *mon,
                             const ll_drift_event *event)
{
    pthread_mutex_lock(&mon->lock);
    for (ll_observer_node *n = mon->observers; n; n = n->next) {
        /* observers are trusted not to block for long – they may spawn their
           own threads if heavy work is required (e.g., retraining)          */
        n->cb(event, n->user_data);
    }
    pthread_mutex_unlock(&mon->lock);
}

static void free_observer_list(ll_model_monitor *mon)
{
    pthread_mutex_lock(&mon->lock);
    ll_observer_node *n = mon->observers;
    while (n) {
        ll_observer_node *next = n->next;
        free(n);
        n = next;
    }
    mon->observers = NULL;
    pthread_mutex_unlock(&mon->lock);
}

/* -------------------------------------------------------------------------- */
/*                              Public API helpers                            */
/* -------------------------------------------------------------------------- */

/* Convenience factory for common config defaults */
ll_monitor_cfg ll_monitor_default_cfg(void)
{
    return (ll_monitor_cfg) {
        .metrics_endpoint       = "http://localhost:9000/metrics",
        .poll_interval_sec      = 60,
        .accuracy_tolerance     = 0.02,   /* 2% absolute accuracy drop     */
        .loss_tolerance         = 0.05,   /* 5% absolute loss increase     */
        .auto_refresh_baseline  = true
    };
}
```
