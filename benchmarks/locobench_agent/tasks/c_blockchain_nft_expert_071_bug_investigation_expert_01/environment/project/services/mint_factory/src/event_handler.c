/*
 * HoloCanvas – Mint-Factory
 * File: event_handler.c
 *
 * Description:
 *   Event ingestion and dispatch layer for the Mint-Factory micro-service.
 *   Consumes domain events from the HoloCanvas Kafka mesh, parses the
 *   payloads (JSON/Protobuf), and routes them to the appropriate
 *   sub-systems (minting engine, bid processor, governance module, etc.).
 *
 *   This is intentionally self-contained so that unit-tests can stub
 *   external dependencies.  The production build links against
 *   -lrdkafka –ljansson –lpthread.
 *
 * Author: HoloCanvas Core Team
 * SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <inttypes.h>
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
#include <pthread.h>

#include <rdkafka/rdkafka.h>

#include "event_handler.h"  /* Local header (exports init/run/shutdown)    */
#include "metrics.h"        /* Prometheus-style exporter (not in this file)*/
#include "mint_engine.h"    /* Business logic for NFT minting             */
#include "logger.h"         /* Syslog-style async logger                   */


/* ────────────────────────────────────────────────────────────────────────── *
 * Compile-Time Configuration
 * ────────────────────────────────────────────────────────────────────────── */

#ifndef KAFKA_BROKERS
#define KAFKA_BROKERS       "localhost:9092"
#endif

#ifndef KAFKA_GROUP_ID
#define KAFKA_GROUP_ID      "mint_factory_consumer"
#endif

#ifndef KAFKA_TOPICS
#define KAFKA_TOPICS        "mint-factory.events"
#endif

#define KAFKA_CONSUMER_POLL_TIMEOUT_MS  250
#define MAX_EVENT_ID_LEN                64
#define ISO_TS_BUF_SZ                   32

/* ────────────────────────────────────────────────────────────────────────── *
 * Local Data Structures
 * ────────────────────────────────────────────────────────────────────────── */

/* Enumeration of canonical event types emitted onto the bus. */
typedef enum {
    EVT_UNKNOWN = 0,
    EVT_MINT_REQUEST,
    EVT_BID,
    EVT_GOVERNANCE_VOTE,
    EVT_ORACLE_FEED
} event_type_t;

/* Generic event container. Additional type-specific fields live in
 * sub-structures that mint_engine.c and friends know how to decode. */
typedef struct {
    event_type_t  type;
    char          id[MAX_EVENT_ID_LEN];
    uint64_t      ts_epoch_ms;
    char         *raw_payload;   /* Original JSON string; ownership retained. */
} event_t;

/* ────────────────────────────────────────────────────────────────────────── *
 * Module State
 * ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    rd_kafka_t      *rk;          /* Kafka handle */
    rd_kafka_conf_t *conf;        /* Kafka configuration */
    bool             running;
    pthread_t        thread;
} evh_context_t;

static evh_context_t g_ctx = {0};

/* Metrics */
static struct {
    uint64_t processed;
    uint64_t parse_errors;
    uint64_t dispatch_errors;
} g_metrics = {0};

/* Forward declarations */
static void *run_loop(void *arg);
static bool parse_event(const char *json_str, size_t len, event_t *out_evt);
static void free_event(event_t *evt);
static int  dispatch_event(const event_t *evt);
static char *iso_timestamp(uint64_t epoch_ms, char *buf, size_t buf_sz);

/* ────────────────────────────────────────────────────────────────────────── *
 * Public API
 * ────────────────────────────────────────────────────────────────────────── */

/*
 * evh_init – Initialise the event handler module and spawn the consumer
 *            thread.  Returns 0 on success, <0 on fatal error.
 */
int evh_init(void)
{
    char errstr[512];

    g_ctx.conf = rd_kafka_conf_new();
    if (!g_ctx.conf)
        return -ENOMEM;

    /* Basic configuration */
    if (rd_kafka_conf_set(g_ctx.conf, "bootstrap.servers",
                          KAFKA_BROKERS, errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        log_error("Kafka conf error: %s", errstr);
        return -EINVAL;
    }

    if (rd_kafka_conf_set(g_ctx.conf, "group.id",
                          KAFKA_GROUP_ID, errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        log_error("Kafka conf error: %s", errstr);
        return -EINVAL;
    }

    /* Handle rebalance callbacks if necessary
     * rd_kafka_conf_set_rebalance_cb(g_ctx.conf, rebalance_cb); */

    /* Create consumer instance */
    g_ctx.rk = rd_kafka_new(RD_KAFKA_CONSUMER, g_ctx.conf, errstr, sizeof(errstr));
    if (!g_ctx.rk) {
        log_error("Failed to create Kafka consumer: %s", errstr);
        return -ECANCELED;
    }

    /* Redirect Kafka logs to our logger */
    rd_kafka_set_log_level(g_ctx.rk, LOG_INFO);

    /* Subscribe to topics */
    rd_kafka_topic_partition_list_t *topics = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, KAFKA_TOPICS, RD_KAFKA_PARTITION_UA);

    if (rd_kafka_subscribe(g_ctx.rk, topics) != RD_KAFKA_RESP_ERR_NO_ERROR) {
        log_error("Kafka subscription failed");
        rd_kafka_topic_partition_list_destroy(topics);
        return -EIO;
    }
    rd_kafka_topic_partition_list_destroy(topics);

    /* Spawn consume loop */
    g_ctx.running = true;
    if (pthread_create(&g_ctx.thread, NULL, run_loop, NULL) != 0) {
        log_error("Failed to create consumer thread");
        return -errno;
    }

    log_info("event_handler initialised (brokers=%s, group=%s, topics=%s)",
             KAFKA_BROKERS, KAFKA_GROUP_ID, KAFKA_TOPICS);
    return 0;
}

/*
 * evh_shutdown – Graceful shutdown; joins the consumer thread and
 *                cleans up resources.
 */
void evh_shutdown(void)
{
    if (!g_ctx.running)
        return;

    g_ctx.running = false;
    pthread_join(g_ctx.thread, NULL);

    rd_kafka_consumer_close(g_ctx.rk);
    rd_kafka_destroy(g_ctx.rk);

    log_info("event_handler shutdown complete "
             "(processed=%" PRIu64 ", parse_errors=%" PRIu64 ", dispatch_errors=%" PRIu64 ")",
             g_metrics.processed, g_metrics.parse_errors, g_metrics.dispatch_errors);
}

/* ────────────────────────────────────────────────────────────────────────── *
 * Internal Helpers
 * ────────────────────────────────────────────────────────────────────────── */

/* Thread entry point */
static void *run_loop(void *arg)
{
    (void)arg;
    while (g_ctx.running) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(g_ctx.rk, KAFKA_CONSUMER_POLL_TIMEOUT_MS);

        if (!rkmsg)
            continue; /* Poll timeout */

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                /* Log at debug level; nothing to do */
                rd_kafka_message_destroy(rkmsg);
                continue;
            }
            log_warn("Kafka error: %s", rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Parse and dispatch */
        event_t evt = {0};
        if (!parse_event((char *)rkmsg->payload, rkmsg->len, &evt)) {
            g_metrics.parse_errors++;
            log_warn("Failed to parse event (topic=%s, offset=%ld)",
                     rd_kafka_topic_name(rkmsg->rkt), rkmsg->offset);
            /* Commit offset despite bad message to avoid poison-pill loops */
            rd_kafka_commit_message(g_ctx.rk, rkmsg, 0);
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        if (dispatch_event(&evt) != 0) {
            g_metrics.dispatch_errors++;
            log_warn("Dispatch error for event ID %s (type=%d)", evt.id, evt.type);
            /* Optionally implement retry or DLQ */
        } else {
            g_metrics.processed++;
            metrics_inc_counter("evh_processed_total"); /* external metrics API */
        }

        free_event(&evt);
        rd_kafka_commit_message(g_ctx.rk, rkmsg, 0);
        rd_kafka_message_destroy(rkmsg);
    }

    return NULL;
}

/*
 * parse_event – Validate and normalise JSON message into event_t.
 *
 * Expected payload example:
 * {
 *   "id": "e7b84e46-8bc1-4ed4-ab04-7574c01234d2",
 *   "type": "MINT_REQUEST",
 *   "ts": 1695150687123,
 *   "payload": { ... }
 * }
 */
static bool parse_event(const char *json_str, size_t len, event_t *out_evt)
{
    bool ok = false;
    json_error_t jerr;
    json_t *root = json_loadb(json_str, len, 0, &jerr);
    if (!root) {
        log_debug("JSON parse error: %s (at line %d col %d)", jerr.text, jerr.line, jerr.column);
        return false;
    }

    /* id */
    const char *id = json_string_value(json_object_get(root, "id"));
    if (!id || strlen(id) >= MAX_EVENT_ID_LEN) {
        log_debug("Invalid or missing event id");
        goto cleanup;
    }
    strncpy(out_evt->id, id, MAX_EVENT_ID_LEN);

    /* type */
    const char *type_str = json_string_value(json_object_get(root, "type"));
    if (!type_str) {
        log_debug("Event.type missing");
        goto cleanup;
    }

    if      (strcmp(type_str, "MINT_REQUEST")     == 0) out_evt->type = EVT_MINT_REQUEST;
    else if (strcmp(type_str, "BID")              == 0) out_evt->type = EVT_BID;
    else if (strcmp(type_str, "GOVERNANCE_VOTE")  == 0) out_evt->type = EVT_GOVERNANCE_VOTE;
    else if (strcmp(type_str, "ORACLE_FEED")      == 0) out_evt->type = EVT_ORACLE_FEED;
    else out_evt->type = EVT_UNKNOWN;

    /* timestamp */
    json_t *ts_node = json_object_get(root, "ts");
    if (!json_is_integer(ts_node)) {
        log_debug("Event.ts missing or not integer");
        goto cleanup;
    }
    out_evt->ts_epoch_ms = (uint64_t)json_integer_value(ts_node);

    /* payload (keep raw to avoid extra serialise-deserialise cycles) */
    json_t *payload_node = json_object_get(root, "payload");
    if (!payload_node) {
        log_debug("Event.payload missing");
        goto cleanup;
    }
    /* Dump just the payload subtree for downstream modules */
    out_evt->raw_payload = json_dumps(payload_node, JSON_COMPACT | JSON_ENSURE_ASCII);
    if (!out_evt->raw_payload) {
        log_debug("Failed to serialise payload subtree");
        goto cleanup;
    }

    ok = true;

cleanup:
    json_decref(root);
    return ok;
}

static void free_event(event_t *evt)
{
    if (evt->raw_payload)
        free(evt->raw_payload);
    memset(evt, 0, sizeof(*evt));
}

/*
 * dispatch_event – Call the appropriate domain handler.  Returns 0 on success.
 */
static int dispatch_event(const event_t *evt)
{
    int rc = 0;
    char tsbuf[ISO_TS_BUF_SZ];
    iso_timestamp(evt->ts_epoch_ms, tsbuf, sizeof(tsbuf));

    switch (evt->type) {
    case EVT_MINT_REQUEST:
        log_info("Dispatching MINT_REQUEST id=%s ts=%s", evt->id, tsbuf);
        rc = mint_engine_handle_request(evt->raw_payload);
        break;

    case EVT_BID:
        log_info("Dispatching BID id=%s ts=%s", evt->id, tsbuf);
        rc = mint_engine_handle_bid(evt->raw_payload);
        break;

    case EVT_GOVERNANCE_VOTE:
        log_info("Dispatching GOVERNANCE_VOTE id=%s ts=%s", evt->id, tsbuf);
        rc = mint_engine_handle_governance_vote(evt->raw_payload);
        break;

    case EVT_ORACLE_FEED:
        log_info("Dispatching ORACLE_FEED id=%s ts=%s", evt->id, tsbuf);
        rc = mint_engine_handle_oracle_feed(evt->raw_payload);
        break;

    default:
        log_warn("Unknown event type (%d) id=%s", evt->type, evt->id);
        rc = -EINVAL;
        break;
    }

    return rc;
}

/*
 * iso_timestamp – Convert epoch_ms to ISO-8601 UTC string.
 */
static char *iso_timestamp(uint64_t epoch_ms, char *buf, size_t buf_sz)
{
    time_t sec = (time_t)(epoch_ms / 1000ULL);
    struct tm tm;
    gmtime_r(&sec, &tm);
    size_t n = strftime(buf, buf_sz, "%Y-%m-%dT%H:%M:%S", &tm);
    snprintf(buf + n, buf_sz - n, ".%03" PRIu64 "Z", epoch_ms % 1000ULL);
    return buf;
}

/* ────────────────────────────────────────────────────────────────────────── *
 * Signal Handling Convenience
 * ────────────────────────────────────────────────────────────────────────── */

static void sig_handler(int sig)
{
    (void)sig;
    log_info("Received termination signal, shutting down");
    evh_shutdown();
    /* Exit entire process once clean-up completes */
    _exit(EXIT_SUCCESS);
}

/*
 * evh_install_signal_handlers – Utility function that applications may call.
 */
void evh_install_signal_handlers(void)
{
    struct sigaction sa = {
        .sa_handler = sig_handler,
        .sa_flags   = 0
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/* ────────────────────────────────────────────────────────────────────────── *
 * Unit-Test Hooks (weak linkage, allow overrides)
 * ────────────────────────────────────────────────────────────────────────── */

__attribute__((weak))
int mint_engine_handle_request(const char *payload_json) {
    (void)payload_json; return 0;
}

__attribute__((weak))
int mint_engine_handle_bid(const char *payload_json) {
    (void)payload_json; return 0;
}

__attribute__((weak))
int mint_engine_handle_governance_vote(const char *payload_json) {
    (void)payload_json; return 0;
}

__attribute__((weak))
int mint_engine_handle_oracle_feed(const char *payload_json) {
    (void)payload_json; return 0;
}

/* End of file */