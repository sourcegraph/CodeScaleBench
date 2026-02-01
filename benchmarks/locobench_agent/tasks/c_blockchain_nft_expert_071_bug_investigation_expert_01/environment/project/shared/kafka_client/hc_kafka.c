/*
 *  HoloCanvas -- Kafka Client Abstraction Layer
 *
 *  File:    HoloCanvas/shared/kafka_client/hc_kafka.c
 *  Project: HoloCanvas – A Micro-Gallery Blockchain for Generative Artifacts
 *
 *  Description:
 *      Thin(ish) wrapper around librdkafka that provides the HoloCanvas
 *      micro-services with a sane, opinionated interface for publishing and
 *      consuming protobuf / JSON events on the project-wide Event Bus.
 *
 *  Design notes:
 *      • One producer instance and one consumer instance are multiplexed out of
 *        a single rd_kafka_t handle to conserve file descriptors.
 *      • Thread-safety is provided by an internal mutex guarding the producer’s
 *        shared queue; the consumer runs in the caller’s thread.
 *      • Delivery reports are routed to a ring-buffer so that infrequent callers
 *        can inspect them without registering a full callback.
 *      • All public API symbols are prefixed with “hc_kafka_”.
 *
 *  Build:
 *      gcc -Wall -Wextra -pedantic -std=c11 \
 *          -I/path/to/librdkafka/include -L/path/to/librdkafka/lib \
 *          -lrdkafka -pthread -o hc_kafka.o -c hc_kafka.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <signal.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>

#include <librdkafka/rdkafka.h>

#include "hc_kafka.h"   /* Public header exported to the rest of the project    */

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Compile-time Defaults                           */

#ifndef HC_KAFKA_LOG_PREFIX
#   define HC_KAFKA_LOG_PREFIX  "[hc_kafka] "
#endif

#ifndef HC_KAFKA_MAX_DELIVERY_RING
#   define HC_KAFKA_MAX_DELIVERY_RING  1024  /* Power-of-two strongly advised */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*                                 Logging                                   */

static void hc_kafka_vlog(enum hc_kafka_log_level lvl,
                          const char *fmt, va_list ap)
{
    const char *pfx = HC_KAFKA_LOG_PREFIX;
    FILE *stream   = (lvl >= HC_KAFKA_LOG_ERROR) ? stderr : stdout;

    flockfile(stream);
    fprintf(stream, "%s", pfx);
    vfprintf(stream, fmt, ap);
    fprintf(stream, "\n");
    funlockfile(stream);
}

static void hc_kafka_log(enum hc_kafka_log_level lvl, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    hc_kafka_vlog(lvl, fmt, ap);
    va_end(ap);
}

/* -------------------------------------------------------------------------- */
/*                        Ring-buffer for delivery reports                    */

typedef struct {
    hc_kafka_delivery_t buf[HC_KAFKA_MAX_DELIVERY_RING];
    size_t              head;
    size_t              tail;
    pthread_mutex_t     mutex;
} delivery_ring_t;

static void ring_init(delivery_ring_t *r)
{
    memset(r, 0, sizeof(*r));
    pthread_mutex_init(&r->mutex, NULL);
}

static void ring_push(delivery_ring_t *r, const hc_kafka_delivery_t *item)
{
    pthread_mutex_lock(&r->mutex);
    r->buf[r->head] = *item;
    r->head = (r->head + 1) % HC_KAFKA_MAX_DELIVERY_RING;
    if (r->head == r->tail) {          /* overwrite oldest */
        r->tail = (r->tail + 1) % HC_KAFKA_MAX_DELIVERY_RING;
    }
    pthread_mutex_unlock(&r->mutex);
}

static int ring_pop(delivery_ring_t *r, hc_kafka_delivery_t *out)
{
    int found = 0;
    pthread_mutex_lock(&r->mutex);
    if (r->tail != r->head) {
        *out = r->buf[r->tail];
        r->tail = (r->tail + 1) % HC_KAFKA_MAX_DELIVERY_RING;
        found = 1;
    }
    pthread_mutex_unlock(&r->mutex);
    return found;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                    Internal structure representing a client               */

struct hc_kafka_client {
    rd_kafka_t       *rk;             /* Unified handle (producer & consumer) */
    rd_kafka_conf_t  *conf;           /* Base configuration object           */
    rd_kafka_topic_partition_list_t *subscribed;
    pthread_mutex_t   producer_mutex; /* Guards produce() and queue length   */
    delivery_ring_t   d_ring;         /* Ring-buffer for delivery reports    */
    char             *brokers;
    char             *client_id;
    volatile int      run;
};

/* -------------------------------------------------------------------------- */
/*                        librdkafka Callback Shims                           */

static void rebalance_cb(rd_kafka_t *rk,
                         rd_kafka_resp_err_t err,
                         rd_kafka_topic_partition_list_t *partitions,
                         void *opaque)
{
    hc_kafka_client_t *cli = (hc_kafka_client_t *)opaque;
    switch (err) {
        case RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS:
            hc_kafka_log(HC_KAFKA_LOG_INFO,
                         "Assigned %d partition(s) to consumer",
                         partitions->cnt);
            rd_kafka_assign(rk, partitions);
            break;
        case RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS:
            hc_kafka_log(HC_KAFKA_LOG_INFO,
                         "Partitions revoked");
            rd_kafka_assign(rk, NULL);
            break;
        default:
            rd_kafka_assign(rk, NULL);
            break;
    }
    (void)cli;
}

static void logger_cb(const rd_kafka_t *rk, int level,
                      const char *fac, const char *buf)
{
    (void)rk; (void)fac;
    enum hc_kafka_log_level lvl;

    /* Map librdkafka logs to our own */
    if (level >= 6)
        lvl = HC_KAFKA_LOG_DEBUG;
    else if (level >= 4)
        lvl = HC_KAFKA_LOG_INFO;
    else
        lvl = HC_KAFKA_LOG_WARN;

    hc_kafka_log(lvl, "rdkafka: %s", buf);
}

static void dr_msg_cb(rd_kafka_t *rk,
                      const rd_kafka_message_t *m,
                      void *opaque)
{
    hc_kafka_client_t *cli = (hc_kafka_client_t *)opaque;
    hc_kafka_delivery_t d  = {
        .topic      = m->rkt ? rd_kafka_topic_name(m->rkt) : NULL,
        .partition  = m->partition,
        .offset     = m->offset,
        .err        = m->err,
        .opaque     = m->_private
    };

    ring_push(&cli->d_ring, &d);

    if (m->err) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR,
                     "Delivery failed: %s",
                     rd_kafka_err2str(m->err));
    } else {
        hc_kafka_log(HC_KAFKA_LOG_DEBUG,
                     "Delivered message to %s [%d] @ %" PRId64,
                     d.topic, d.partition, d.offset);
    }
    (void)rk;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Public  API                                  */

hc_kafka_client_t *hc_kafka_client_new(const hc_kafka_conf_t *user_conf)
{
    hc_kafka_client_t *cli = calloc(1, sizeof(*cli));
    if (!cli) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR, "OOM creating hc_kafka_client");
        return NULL;
    }

    cli->conf = rd_kafka_conf_new();

    rd_kafka_conf_set_log_cb(cli->conf, logger_cb);
    rd_kafka_conf_set_dr_msg_cb(cli->conf, dr_msg_cb);
    rd_kafka_conf_set_rebalance_cb(cli->conf, rebalance_cb);
    rd_kafka_conf_set_opaque(cli->conf, cli);

    /* Apply caller-provided overrides */
    if (user_conf->bootstrap_servers)
        rd_kafka_conf_set(cli->conf, "bootstrap.servers",
                          user_conf->bootstrap_servers, NULL, 0);

    if (user_conf->client_id)
        rd_kafka_conf_set(cli->conf, "client.id",
                          user_conf->client_id, NULL, 0);

    if (user_conf->group_id)
        rd_kafka_conf_set(cli->conf, "group.id",
                          user_conf->group_id, NULL, 0);

    /* Enable idempotent producer for exactly-once semantics */
    rd_kafka_conf_set(cli->conf, "enable.idempotence", "true", NULL, 0);

    /* Max in-flight requests set to 5 to prevent re-ordering */
    rd_kafka_conf_set(cli->conf, "max.in.flight.requests.per.connection",
                      "5", NULL, 0);

    char errstr[512];
    cli->rk = rd_kafka_new(RD_KAFKA_PRODUCER, cli->conf,
                           errstr, sizeof(errstr));
    if (!cli->rk) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR,
                     "Failed to create Kafka handle: %s", errstr);
        rd_kafka_conf_destroy(cli->conf);
        free(cli);
        return NULL;
    }

    pthread_mutex_init(&cli->producer_mutex, NULL);
    ring_init(&cli->d_ring);

    cli->brokers   = strdup(user_conf->bootstrap_servers ?: "");
    cli->client_id = strdup(user_conf->client_id ?: "");

    cli->run = 1;

    hc_kafka_log(HC_KAFKA_LOG_INFO,
                 "Kafka client created (id=%s, brokers=%s)",
                 cli->client_id, cli->brokers);

    return cli;
}

void hc_kafka_client_destroy(hc_kafka_client_t *cli)
{
    if (!cli) return;

    hc_kafka_log(HC_KAFKA_LOG_INFO, "Destroying Kafka client…");

    cli->run = 0;
    rd_kafka_flush(cli->rk, 10 * 1000);          /* wait up to 10s */

    rd_kafka_destroy(cli->rk);

    if (cli->subscribed)
        rd_kafka_topic_partition_list_destroy(cli->subscribed);

    pthread_mutex_destroy(&cli->producer_mutex);
    pthread_mutex_destroy(&cli->d_ring.mutex);
    free(cli->brokers);
    free(cli->client_id);
    free(cli);
}

int hc_kafka_client_subscribe(hc_kafka_client_t *cli,
                              const char *const *topics,
                              size_t topic_count)
{
    if (!cli || !topics || topic_count == 0)
        return -EINVAL;

    rd_kafka_conf_t *c_conf = rd_kafka_conf_dup(cli->conf);
    rd_kafka_conf_set(c_conf, "enable.auto.commit", "false", NULL, 0);

    char errstr[512];
    rd_kafka_t *c_consumer = rd_kafka_new(RD_KAFKA_CONSUMER, c_conf,
                                          errstr, sizeof(errstr));
    if (!c_consumer) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR,
                     "Failed to create consumer: %s", errstr);
        rd_kafka_conf_destroy(c_conf);
        return -1;
    }

    rd_kafka_poll_set_consumer(c_consumer);

    cli->subscribed = rd_kafka_topic_partition_list_new((int)topic_count);
    for (size_t i = 0; i < topic_count; ++i)
        rd_kafka_topic_partition_list_add(cli->subscribed, topics[i],
                                          RD_KAFKA_PARTITION_UA);

    rd_kafka_resp_err_t err =
        rd_kafka_subscribe(c_consumer, cli->subscribed);
    if (err) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR,
                     "Subscription failed: %s",
                     rd_kafka_err2str(err));
        rd_kafka_destroy(c_consumer);
        return -1;
    }

    /* Swap the consumer instance into the existing handle */
    cli->rk = c_consumer;
    hc_kafka_log(HC_KAFKA_LOG_INFO,
                 "Subscribed to %zu topic(s)", topic_count);

    return 0;
}

int hc_kafka_client_poll(hc_kafka_client_t *cli,
                         int timeout_ms,
                         hc_kafka_msg_cb on_msg,
                         void *opaque)
{
    if (!cli || !on_msg || timeout_ms < 0)
        return -EINVAL;

    rd_kafka_message_t *msg =
        rd_kafka_consumer_poll(cli->rk, timeout_ms);
    if (!msg) return 0; /* Timed out */

    if (msg->err) {
        if (msg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
            hc_kafka_log(HC_KAFKA_LOG_DEBUG,
                         "Reached end of %s [%d] @ %" PRId64,
                         rd_kafka_topic_name(msg->rkt),
                         msg->partition, msg->offset);
        } else {
            hc_kafka_log(HC_KAFKA_LOG_ERROR,
                         "Consume error: %s",
                         rd_kafka_message_errstr(msg));
        }
        rd_kafka_message_destroy(msg);
        return -1;
    }

    on_msg(msg, opaque);
    rd_kafka_message_destroy(msg);

    return 1;
}

int hc_kafka_client_commit(hc_kafka_client_t *cli)
{
    if (!cli) return -EINVAL;

    rd_kafka_resp_err_t err = rd_kafka_commit(cli->rk, NULL, 0);
    if (err) {
        hc_kafka_log(HC_KAFKA_LOG_WARN,
                     "Commit failed: %s", rd_kafka_err2str(err));
        return -1;
    }
    return 0;
}

int hc_kafka_client_publish(hc_kafka_client_t *cli,
                            const char *topic,
                            const char *key,
                            const void *payload,
                            size_t len,
                            int partition,
                            void *opaque)
{
    if (!cli || !topic || !payload)
        return -EINVAL;

    pthread_mutex_lock(&cli->producer_mutex);

    rd_kafka_resp_err_t err = rd_kafka_producev(
        cli->rk,
        RD_KAFKA_V_TOPIC(topic),
        RD_KAFKA_V_PARTITION(partition),
        RD_KAFKA_V_KEY((void *)key, key ? strlen(key) : 0),
        RD_KAFKA_V_VALUE((void *)payload, len),
        RD_KAFKA_V_OPAQUE(opaque),
        RD_KAFKA_V_END);

    if (err) {
        hc_kafka_log(HC_KAFKA_LOG_ERROR,
                     "Produce failed: %s", rd_kafka_err2str(err));
        pthread_mutex_unlock(&cli->producer_mutex);
        return -1;
    }

    /* Pump the internal producer queue */
    rd_kafka_poll(cli->rk, 0);
    pthread_mutex_unlock(&cli->producer_mutex);
    return 0;
}

size_t hc_kafka_client_drain_reports(hc_kafka_client_t *cli,
                                     hc_kafka_delivery_t *out,
                                     size_t max_count)
{
    if (!cli || !out || max_count == 0)
        return 0;

    size_t cnt = 0;
    while (cnt < max_count && ring_pop(&cli->d_ring, &out[cnt]))
        ++cnt;
    return cnt;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Signal Convenience                              */

static volatile int g_should_exit = 0;

static void sig_handler(int signo)
{
    (void)signo;
    g_should_exit = 1;
}

void hc_kafka_setup_signal_handlers(void)
{
    struct sigaction sa = {
        .sa_handler = sig_handler,
        .sa_flags   = 0
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Self-test Routine                            */

#ifdef HC_KAFKA_SELFTEST

/*
 *  Compile:
 *      gcc -DHC_KAFKA_SELFTEST hc_kafka.c -lrdkafka -pthread
 *
 *  Run:
 *      ./a.out
 */
int main(void)
{
    const char *brokers = "localhost:9092";
    const char *topic   = "hc_test_topic";

    hc_kafka_setup_signal_handlers();

    hc_kafka_conf_t conf = {
        .bootstrap_servers = brokers,
        .client_id         = "hc_kafka_selftest"
    };

    hc_kafka_client_t *cli = hc_kafka_client_new(&conf);
    if (!cli) return EXIT_FAILURE;

    /* Produce some messages */
    for (int i = 0; i < 5; ++i) {
        char buf[128];
        snprintf(buf, sizeof(buf), "Hello HoloCanvas %d", i);
        hc_kafka_client_publish(cli, topic, NULL,
                                buf, strlen(buf), RD_KAFKA_PARTITION_UA,
                                NULL);
    }

    hc_kafka_log(HC_KAFKA_LOG_INFO, "Waiting for delivery reports…");

    while (!g_should_exit) {
        hc_kafka_delivery_t reports[32];
        size_t n = hc_kafka_client_drain_reports(cli, reports, 32);
        for (size_t i = 0; i < n; ++i) {
            if (reports[i].err == RD_KAFKA_RESP_ERR_NO_ERROR)
                hc_kafka_log(HC_KAFKA_LOG_INFO,
                             "Delivered to %s[%d] offset=%" PRId64,
                             reports[i].topic,
                             reports[i].partition,
                             reports[i].offset);
        }
        if (n == 0) break;
    }

    hc_kafka_client_destroy(cli);
    return EXIT_SUCCESS;
}
#endif /* HC_KAFKA_SELFTEST */

/* end of file */