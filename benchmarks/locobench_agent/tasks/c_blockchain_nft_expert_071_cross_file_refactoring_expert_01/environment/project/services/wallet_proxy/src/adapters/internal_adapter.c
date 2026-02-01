/**
 * HoloCanvas: Wallet-Proxy – Internal Adapter
 *
 * File: services/wallet_proxy/src/adapters/internal_adapter.c
 *
 * Description:
 *   “internal_adapter” is an in-process façade that hides the transport
 *   details (Kafka RPC over gRPC-bridge) from higher-level wallet logic.
 *   It sends request-reply messages to the Ledger-Core micro-service to
 *   fetch balances, broadcast signed transactions, and query chain state.
 *
 *   The adapter uses librdkafka for Event-Driven messaging and relies on
 *   uuid(3) for correlation-IDs.  All calls are synchronous with bounded
 *   latency; production code SHOULD provide an async variant, but that
 *   remains out-of-scope for this sample.
 *
 * Build:
 *   gcc -std=c11 -Wall -Wextra -pedantic -pthread \
 *       internal_adapter.c -lrdkafka -luuid -o internal_adapter
 *
 * Copyright:
 *   MIT-licensed – (c) 2023-2024 The HoloCanvas Contributors
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <signal.h>
#include <uuid/uuid.h>
#include <syslog.h>

/* External dependency: librdkafka */
#include <rdkafka/rdkafka.h>

/* -------------------------------------------------------------------------- */
/*                               Configuration                                */
/* -------------------------------------------------------------------------- */

/* Default topic names – may be overridden at run-time                      */
#define DEFAULT_REQ_TOPIC  "walletproxy.ledger.req"
#define DEFAULT_RES_TOPIC  "walletproxy.ledger.res"

/* Time (in ms) to block while waiting for a reply from Ledger-Core         */
#define REPLY_TIMEOUT_MS   (5 * 1000)

/* Maximum accepted message size (sanity guard)                             */
#define MAX_PAYLOAD_SIZE   (64 * 1024)  /* 64 KiB */

/* -------------------------------------------------------------------------- */
/*                              Local Structures                              */
/* -------------------------------------------------------------------------- */

typedef struct {
    rd_kafka_t        *rk;            /* Kafka client handle                */
    rd_kafka_topic_t  *req_t;         /* Request topic handle               */
    rd_kafka_topic_t  *res_t;         /* Response topic handle              */
    char               client_id[64]; /* Wallet-Proxy instance ID           */
    char               req_topic[128];
    char               res_topic[128];
    pthread_mutex_t    produce_mtx;   /* Serialize produce calls            */
} adapter_ctx_t;

/* Singleton context – wallet-proxy is a tiny daemon, so a single instance  */
static adapter_ctx_t g_ctx = { 0 };

/* -------------------------------------------------------------------------- */
/*                          Forward Declarations                              */
/* -------------------------------------------------------------------------- */

static int  kafka_init(const char *brokers,
                       const char *req_topic,
                       const char *res_topic);

static void kafka_teardown(void);
static int  send_request_wait_reply(const char *corr_id,
                                    const void *payload,
                                    size_t      payload_len,
                                    char      **reply_out,
                                    size_t     *reply_len);

static int  parse_balance_json(const char *json,
                               uint64_t   *balance_out);

static int  parse_generic_ok_json(const char *json);

/* -------------------------------------------------------------------------- */
/*                             Public Interface                               */
/* -------------------------------------------------------------------------- */

/**
 * internal_adapter_init –
 *     Bootstraps the adapter; MUST be called before any other function.
 *
 * @param broker_list   – comma-separated list of Kafka broker endpoints
 * @param req_topic     – topic for request messages  (NULL → default)
 * @param res_topic     – topic for response messages (NULL → default)
 *
 * Returns 0 on success or ‑1 on failure (check errno, and syslog).
 */
int internal_adapter_init(const char *broker_list,
                          const char *req_topic,
                          const char *res_topic)
{
    if (!broker_list) {
        errno = EINVAL;
        return -1;
    }

    openlog("wallet_proxy", LOG_PID | LOG_CONS, LOG_USER);

    if (kafka_init(broker_list,
                   req_topic ?: DEFAULT_REQ_TOPIC,
                   res_topic ?: DEFAULT_RES_TOPIC) < 0)
    {
        syslog(LOG_ERR, "internal_adapter_init: kafka_init failed");
        return -1;
    }

    syslog(LOG_INFO,
           "wallet_proxy: internal_adapter ready (broker=%s, req=%s, res=%s)",
           broker_list, g_ctx.req_topic, g_ctx.res_topic);
    return 0;
}

/**
 * internal_adapter_shutdown –
 *     Idempotent cleanup routine; safe to call multiple times.
 */
void internal_adapter_shutdown(void)
{
    kafka_teardown();
    syslog(LOG_INFO, "wallet_proxy: internal_adapter shutdown complete");
    closelog();
}

/**
 * internal_adapter_get_balance –
 *     Blocking call that fetches the on-chain balance (in Wei) for @address.
 *
 * @param address     – hex-encoded account address (0x…)
 * @param balance_out – populated on success
 *
 * Returns 0 on success, ‑1 on error.
 */
int internal_adapter_get_balance(const char *address,
                                 uint64_t   *balance_out)
{
    if (!address || !balance_out) {
        errno = EINVAL;
        return -1;
    }

    /* Compose a minimalistic JSON request */
    char payload[256];
    int n = snprintf(payload, sizeof payload,
                     "{ \"op\": \"get_balance\", \"address\": \"%s\" }",
                     address);
    if (n <= 0 || (size_t)n >= sizeof payload) {
        errno = ENOMEM;
        return -1;
    }

    /* Correlation-ID used for request-reply matching */
    char corr_id[37];
    uuid_t bin_uuid;
    uuid_generate(bin_uuid);
    uuid_unparse_lower(bin_uuid, corr_id);

    char  *reply     = NULL;
    size_t reply_len = 0;

    if (send_request_wait_reply(corr_id,
                                payload,
                                (size_t)n,
                                &reply,
                                &reply_len) < 0)
    {
        /* errno set by helper */
        return -1;
    }

    int rc = parse_balance_json(reply, balance_out);
    free(reply);

    return rc;
}

/**
 * internal_adapter_send_signed_tx –
 *     Broadcasts a pre-signed raw transaction to Ledger-Core.
 *
 * @param tx_hex      – hex-encoded serialized transaction
 * @param hash_out    – buffer to receive the resulting tx-hash (optional)
 * @param hash_len    – size of @hash_out; recommended ≥ 67 bytes
 *
 * Returns 0 on success (transaction accepted), ‑1 on error.
 */
int internal_adapter_send_signed_tx(const char *tx_hex,
                                    char       *hash_out,
                                    size_t      hash_len)
{
    if (!tx_hex) {
        errno = EINVAL;
        return -1;
    }

    /* Compose JSON request */
    size_t max_len = strlen(tx_hex) + 128;
    if (max_len > MAX_PAYLOAD_SIZE) {
        errno = EMSGSIZE;
        return -1;
    }

    char *payload = calloc(1, max_len);
    if (!payload) {
        errno = ENOMEM;
        return -1;
    }

    int n = snprintf(payload, max_len,
                     "{ \"op\": \"send_tx\", \"raw\": \"%s\" }",
                     tx_hex);
    if (n <= 0 || (size_t)n >= max_len) {
        free(payload);
        errno = ENOMEM;
        return -1;
    }

    char corr_id[37];
    uuid_t uuid;
    uuid_generate(uuid);
    uuid_unparse_lower(uuid, corr_id);

    char  *reply     = NULL;
    size_t reply_len = 0;

    int rc = send_request_wait_reply(corr_id,
                                     payload,
                                     (size_t)n,
                                     &reply,
                                     &reply_len);
    free(payload);
    if (rc < 0)
        return -1;

    /* Parse tx-hash on success */
    if (hash_out && hash_len > 0) {
        const char *tag = "\"tx_hash\": \"";
        char *p = strstr(reply, tag);
        if (p) {
            p += strlen(tag);
            char *end = strchr(p, '"');
            if (end && (size_t)(end - p) < hash_len) {
                memcpy(hash_out, p, (size_t)(end - p));
                hash_out[end - p] = '\0';
            }
        }
    }

    rc = parse_generic_ok_json(reply);
    free(reply);
    return rc;
}

/* -------------------------------------------------------------------------- */
/*                           Kafka Helper Routines                            */
/* -------------------------------------------------------------------------- */

/* Flush outstanding messages and clean up */
static void kafka_teardown(void)
{
    if (!g_ctx.rk)
        return;

    /* Ensure everything is delivered */
    rd_kafka_flush(g_ctx.rk, 2 * 1000);

    if (g_ctx.req_t) rd_kafka_topic_destroy(g_ctx.req_t);
    if (g_ctx.res_t) rd_kafka_topic_destroy(g_ctx.res_t);
    rd_kafka_destroy(g_ctx.rk);

    g_ctx = (adapter_ctx_t){ 0 };
}

/* Delivery-report callback – invoked by librdkafka thread */
static void dr_msg_cb(rd_kafka_t *rk,
                      const rd_kafka_message_t *rkmessage, void *opaque)
{
    (void)rk;
    (void)opaque;
    if (rkmessage->err) {
        syslog(LOG_ERR,
               "wallet_proxy: failed to deliver message: %s",
               rd_kafka_err2str(rkmessage->err));
    }
}

/* Populate g_ctx with a fully-configured Kafka client */
static int kafka_init(const char *brokers,
                      const char *req_topic,
                      const char *res_topic)
{
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    if (!conf)
        return -1;

    rd_kafka_conf_set_dr_msg_cb(conf, dr_msg_cb);
    rd_kafka_conf_set(conf, "bootstrap.servers",
                      brokers, NULL, 0);

    /* Create client */
    rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf,
                                  NULL, 0);
    if (!rk) {
        syslog(LOG_ERR,
               "internal_adapter: rd_kafka_new failed");
        rd_kafka_conf_destroy(conf);
        return -1;
    }

    /* Duplicate string parameters into context */
    strncpy(g_ctx.req_topic, req_topic, sizeof g_ctx.req_topic - 1);
    strncpy(g_ctx.res_topic, res_topic, sizeof g_ctx.res_topic - 1);

    g_ctx.rk     = rk;
    g_ctx.req_t  = rd_kafka_topic_new(rk, g_ctx.req_topic, NULL);
    g_ctx.res_t  = rd_kafka_topic_new(rk, g_ctx.res_topic, NULL);
    pthread_mutex_init(&g_ctx.produce_mtx, NULL);

    if (!g_ctx.req_t || !g_ctx.res_t) {
        syslog(LOG_ERR, "internal_adapter: topic_new failed");
        kafka_teardown();
        return -1;
    }

    /* Attach a consumer to the same RD_KAFKA_PRODUCER handle via queues */
    return 0;
}

/* Serialises a request and waits synchronously for a reply            */
static int send_request_wait_reply(const char *corr_id,
                                   const void *payload,
                                   size_t      payload_len,
                                   char      **reply_out,
                                   size_t     *reply_len)
{
    int rc = -1;
    rd_kafka_resp_err_t err;

    /* Produce message */
    pthread_mutex_lock(&g_ctx.produce_mtx);

    err = rd_kafka_produce(
        g_ctx.req_t,
        RD_KAFKA_PARTITION_UA,
        RD_KAFKA_MSG_F_COPY,
        (void *)payload, payload_len,
        corr_id, strlen(corr_id),   /* key = correlation ID        */
        NULL);
    pthread_mutex_unlock(&g_ctx.produce_mtx);

    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        syslog(LOG_ERR,
               "internal_adapter: produce failed: %s",
               rd_kafka_err2str(err));
        errno = ECOMM;
        return -1;
    }

    /* Poll until we receive matching correlation-ID on res topic */
    const int64_t timeout_ms = REPLY_TIMEOUT_MS;
    int64_t remaining        = timeout_ms;
    int64_t slice            = 250; /* 250 ms poll slices */

    rd_kafka_queue_t *queue = rd_kafka_queue_new(g_ctx.rk);
    rd_kafka_consume_start_queue(g_ctx.res_t,
                                 RD_KAFKA_PARTITION_UA,
                                 RD_KAFKA_OFFSET_END,
                                 queue);

    char *buffer   = NULL;
    size_t buf_len = 0;

    while (remaining > 0) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consume_queue(queue, slice);
        remaining -= slice;

        if (!rkmsg)
            continue;

        if (rkmsg->err) {
            /* Probably reached EOF on internal partition – ignore */
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Check correlation-ID match */
        if (rkmsg->key && rkmsg->key_len == strlen(corr_id) &&
            !memcmp(rkmsg->key, corr_id, rkmsg->key_len))
        {
            /* Guard against overly large payloads */
            if (rkmsg->len > MAX_PAYLOAD_SIZE) {
                rd_kafka_message_destroy(rkmsg);
                errno = EMSGSIZE;
                break;
            }

            buffer = malloc(rkmsg->len + 1);
            if (!buffer) {
                rd_kafka_message_destroy(rkmsg);
                errno = ENOMEM;
                break;
            }

            memcpy(buffer, rkmsg->payload, rkmsg->len);
            buffer[rkmsg->len] = '\0';
            buf_len = rkmsg->len;

            rd_kafka_message_destroy(rkmsg);
            rc = 0;
            break;
        }

        rd_kafka_message_destroy(rkmsg);
    }

    /* Cleanup consumer */
    rd_kafka_consume_stop(g_ctx.res_t, RD_KAFKA_PARTITION_UA);
    rd_kafka_queue_destroy(queue);

    if (rc == 0) {
        *reply_out  = buffer;
        *reply_len  = buf_len;
    } else {
        if (!errno)
            errno = ETIMEDOUT;
    }

    return rc;
}

/* -------------------------------------------------------------------------- */
/*                       Minimalistic JSON Parsers                            */
/* -------------------------------------------------------------------------- */

/* VERY crude JSON parser – production code should use RapidJSON/jansson     */
static int parse_balance_json(const char *json,
                              uint64_t   *balance_out)
{
    const char *tag = "\"balance\": \"";
    const char *p   = strstr(json, tag);
    if (!p) {
        errno = EBADMSG;
        return -1;
    }
    p += strlen(tag);
    char *end = strchr(p, '"');
    if (!end) {
        errno = EBADMSG;
        return -1;
    }

    char numbuf[32];
    size_t len = (size_t)(end - p);
    if (len >= sizeof numbuf) {
        errno = ERANGE;
        return -1;
    }

    memcpy(numbuf, p, len);
    numbuf[len] = '\0';

    char *ep = NULL;
    uint64_t bal = strtoull(numbuf, &ep, 10);
    if (!ep || *ep != '\0') {
        errno = EBADMSG;
        return -1;
    }

    *balance_out = bal;
    return 0;
}

static int parse_generic_ok_json(const char *json)
{
    const char *tag = "\"status\": \"ok\"";
    if (strstr(json, tag))
        return 0;

    errno = EBADMSG;
    return -1;
}

/* -------------------------------------------------------------------------- */
/*                             Graceful SIGINT                                */
/* -------------------------------------------------------------------------- */

static void handle_sigint(int sig)
{
    (void)sig;
    internal_adapter_shutdown();
    _exit(EXIT_SUCCESS);
}

/* Register signal handler at load-time                                       */
__attribute__((constructor))
static void setup_signal_handler(void)
{
    struct sigaction sa = {
        .sa_handler = handle_sigint,
        .sa_flags   = SA_RESTART
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/* -------------------------------------------------------------------------- */
/*                           End of File                                      */
/* -------------------------------------------------------------------------- */
