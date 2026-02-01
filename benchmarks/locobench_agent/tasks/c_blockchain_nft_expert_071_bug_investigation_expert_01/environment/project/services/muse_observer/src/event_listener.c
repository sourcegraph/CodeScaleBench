```c
/**
 * HoloCanvas – Muse Observer
 * File: services/muse_observer/src/event_listener.c
 *
 * Description:
 *   Kafka-backed event listener that consumes on-chain / off-chain “artistic
 *   triggers”, deserialises the JSON payload, and dispatches the resulting
 *   event to a dynamically-loaded MuseActionStrategy plug-in.
 *
 *   Build requirements:
 *     - librdkafka (https://github.com/edenhill/librdkafka)
 *     - jansson   (https://github.com/akheron/jansson)
 *
 *   The code purposefully contains few compile-time dependencies on other
 *   HoloCanvas units; it exposes a narrow callback interface so that Muse
 *   strategies can be hot-swapped without having to relink this module.
 *
 *   Author: HoloCanvas Core Team
 *   SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <jansson.h>
#include <librdkafka/rdkafka.h>

/* ----  Plugin interface -------------------------------------------------- */

#include "muse_strategy.h" /* expected to provide MuseActionStrategy         */

/* ----  Logging helpers --------------------------------------------------- */

#define LOG_BUF_SZ 512

static inline void log_timestamp(char *buf, size_t sz) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%S", &tm);
}

static void log_print(const char *level, const char *fmt, ...) {
    char ts[32];
    log_timestamp(ts, sizeof(ts));

    char msg[LOG_BUF_SZ];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    fprintf(stderr, "[%s] [%s] %s\n", ts, level, msg);
}

#define LOG_INFO(...)  log_print("INFO",  __VA_ARGS__)
#define LOG_WARN(...)  log_print("WARN",  __VA_ARGS__)
#define LOG_ERROR(...) log_print("ERROR", __VA_ARGS__)
#define LOG_DEBUG(...)                                                         \
    do {                                                                       \
        if (getenv("MUSE_OBSERVER_DEBUG"))                                     \
            log_print("DEBUG", __VA_ARGS__);                                   \
    } while (0)

/* ----  Configuration / Data structures ----------------------------------- */

typedef struct {
    char *brokers;          /* comma-separated list of <host:port>            */
    char *topic;            /* topic to subscribe to                          */
    char *group_id;         /* consumer group                                 */
    int   commit_interval;  /* auto-commit (ms)                               */
} EventListenerConfig;

typedef struct {
    rd_kafka_t                     *rk;
    rd_kafka_topic_partition_list_t *topics;
    pthread_t                       thr;
    bool                            running;
    MuseActionStrategy             *strategy;
} EventListener;

/* ----  Forward declarations ---------------------------------------------- */

static void *listener_thread(void *arg);
static int   dispatch_event(EventListener *listener,
                            const char *payload, size_t len);
static void  on_error(const rd_kafka_error_t *error);

/* ----  Signal handling ---------------------------------------------------- */

static volatile bool g_shutdown = false;

static void sig_handler(int sig) {
    (void)sig;
    g_shutdown = true;
}

/* ----  librdkafka callbacks ---------------------------------------------- */

static void rebalance_cb(rd_kafka_t *rk,
                         rd_kafka_resp_err_t err,
                         rd_kafka_topic_partition_list_t *partitions,
                         void *opaque) {
    (void)rk;
    EventListener *listener = opaque;

    switch (err) {
    case RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS:
        LOG_INFO("Assigned %d partitions", partitions->cnt);
        rd_kafka_assign(rk, partitions);
        break;
    case RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS:
        LOG_INFO("Revoked %d partitions", partitions->cnt);
        rd_kafka_assign(rk, NULL);
        break;
    default:
        LOG_ERROR("Rebalance error: %s", rd_kafka_err2str(err));
        rd_kafka_assign(rk, NULL);
        break;
    }
    (void)listener;
}

static void error_cb(rd_kafka_t *rk, int err, const char *reason, void *opaque) {
    (void)rk;
    (void)opaque;
    LOG_ERROR("Kafka error (%d): %s", err, reason);
}

static void log_cb(const rd_kafka_t *rk, int level,
                   const char *fac, const char *buf) {
    (void)rk;
    if (level <= LOG_DEBUG) {
        LOG_DEBUG("rdkafka[%s] %s", fac, buf);
    }
}

/* ----  Public API --------------------------------------------------------- */

EventListener *event_listener_create(const EventListenerConfig *cfg,
                                     MuseActionStrategy       *strategy) {
    rd_kafka_conf_t *kconf = rd_kafka_conf_new();
    if (!kconf) {
        LOG_ERROR("Unable to allocate rd_kafka_conf");
        return NULL;
    }

    /* copy config into librdkafka */
    rd_kafka_conf_set_log_cb(kconf, log_cb);
    rd_kafka_conf_set_error_cb(kconf, error_cb);
    rd_kafka_conf_set_rebalance_cb(kconf, rebalance_cb);
    rd_kafka_conf_set_opaque(kconf, NULL); /* will set later */

    if (rd_kafka_conf_set(kconf, "bootstrap.servers",
                          cfg->brokers, NULL, 0) != RD_KAFKA_CONF_OK) {
        LOG_ERROR("Invalid 'bootstrap.servers' value: %s", cfg->brokers);
        rd_kafka_conf_destroy(kconf);
        return NULL;
    }

    char commit_str[32];
    snprintf(commit_str, sizeof(commit_str), "%d", cfg->commit_interval);
    rd_kafka_conf_set(kconf, "auto.commit.interval.ms", commit_str, NULL, 0);
    rd_kafka_conf_set(kconf, "enable.auto.commit", "true", NULL, 0);
    rd_kafka_conf_set(kconf, "group.id", cfg->group_id, NULL, 0);

    rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_CONSUMER, kconf,
                                  NULL, 0);
    if (!rk) {
        LOG_ERROR("Failed to create rd_kafka handle");
        rd_kafka_conf_destroy(kconf);
        return NULL;
    }

    rd_kafka_poll_set_consumer(rk);

    rd_kafka_topic_partition_list_t *topics =
        rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, cfg->topic, RD_KAFKA_PARTITION_UA);

    EventListener *listener = calloc(1, sizeof(*listener));
    if (!listener) {
        LOG_ERROR("Out of memory");
        rd_kafka_destroy(rk);
        rd_kafka_topic_partition_list_destroy(topics);
        return NULL;
    }

    listener->rk       = rk;
    listener->topics   = topics;
    listener->strategy = strategy;
    listener->running  = false;

    /* pass self pointer through opaque for callbacks */
    rd_kafka_conf_set_opaque(kconf, listener);

    return listener;
}

int event_listener_start(EventListener *listener) {
    if (listener->running) {
        LOG_WARN("EventListener already running");
        return 0;
    }

    if (!listener->strategy || !listener->strategy->on_event) {
        LOG_ERROR("No valid strategy attached to EventListener");
        return -1;
    }

    rd_kafka_resp_err_t err =
        rd_kafka_subscribe(listener->rk, listener->topics);
    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        LOG_ERROR("Failed to subscribe to topic: %s",
                  rd_kafka_err2str(err));
        return -1;
    }

    listener->running = true;
    int rc = pthread_create(&listener->thr, NULL, listener_thread, listener);
    if (rc != 0) {
        LOG_ERROR("Failed to spawn listener thread: %s", strerror(rc));
        listener->running = false;
        return -1;
    }

    LOG_INFO("EventListener started for topic '%s'", listener->topics->elems[0].topic);
    return 0;
}

void event_listener_stop(EventListener *listener) {
    if (!listener || !listener->running)
        return;

    listener->running = false;
    pthread_join(listener->thr, NULL);

    LOG_INFO("EventListener stopped");
}

void event_listener_destroy(EventListener *listener) {
    if (!listener)
        return;

    if (listener->running)
        event_listener_stop(listener);

    rd_kafka_unsubscribe(listener->rk);
    rd_kafka_destroy(listener->rk);
    rd_kafka_topic_partition_list_destroy(listener->topics);

    free(listener);
}

/* ----  Thread routine ---------------------------------------------------- */

static void *listener_thread(void *arg) {
    EventListener *listener = arg;
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    while (listener->running && !g_shutdown) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(listener->rk, 100 /* ms */);

        if (!rkmsg)
            continue; /* timeout – poll again */

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                LOG_DEBUG("Reached end of partition %"PRId32
                          " at offset %"PRId64,
                          rkmsg->partition, rkmsg->offset);
            } else {
                LOG_WARN("Consume error: %s",
                         rd_kafka_message_errstr(rkmsg));
            }
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Dispatch user payload */
        if (dispatch_event(listener,
                           (const char *)rkmsg->payload,
                           rkmsg->len) != 0) {
            LOG_WARN("Failed to dispatch event (offset %"PRId64")",
                     rkmsg->offset);
        }

        rd_kafka_message_destroy(rkmsg);
    }

    rd_kafka_consumer_close(listener->rk);
    return NULL;
}

/* ----  Event dispatch ---------------------------------------------------- */

static int dispatch_event(EventListener *listener,
                          const char *payload, size_t len) {
    json_error_t jerr;
    json_t *root = json_loadb(payload, len, 0, &jerr);
    if (!root) {
        LOG_WARN("JSON parse failed: %s (line %d)", jerr.text, jerr.line);
        return -1;
    }

    json_t *type = json_object_get(root, "type");
    if (!json_is_string(type)) {
        LOG_WARN("Event missing string 'type' field");
        json_decref(root);
        return -1;
    }

    const char *etype = json_string_value(type);
    LOG_INFO("Received event: %s", etype);

    /* Build a thin wrapper for plug-in */
    MuseEvent evt = {
        .raw_json = root,
        .type     = etype,
    };

    int rc = listener->strategy->on_event(listener->strategy, &evt);
    if (rc != 0)
        LOG_WARN("Strategy returned non-zero (%d) for event %s", rc, etype);

    json_decref(root);
    return rc;
}
```
