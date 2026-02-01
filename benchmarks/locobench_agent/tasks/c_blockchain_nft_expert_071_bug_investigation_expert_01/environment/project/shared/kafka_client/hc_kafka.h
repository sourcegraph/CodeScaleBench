/**
 * hc_kafka.h
 *
 * HoloCanvas – Event-Driven Kafka Client Helper
 * --------------------------------------------
 * A minimalist, production-grade wrapper around librdkafka that provides the
 * micro-services within HoloCanvas a uniform, opinionated API for publishing
 * and consuming protobuf / JSON events.  The wrapper adds:
 *
 *  • Sensible default configuration tuned for low-latency micro-services
 *  • Thread-safe producer / consumer handles
 *  • Centralised error handling & structured logging
 *  • Graceful shutdown hooks
 *
 * The file is implemented header-only to avoid the boiler-plate of a separate
 * compilation unit; simply include it wherever Kafka access is required.
 *
 * NOTE: link with -lrdkafka (and -lpthread on most platforms)
 */
#ifndef HC_KAFKA_H
#define HC_KAFKA_H

/* ────────────────────────────────────────────────────────────────────────── */
/* System headers                                                            */
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

/* ────────────────────────────────────────────────────────────────────────── */
/* Third-party headers                                                       */
#include <rdkafka/rdkafka.h> /* librdkafka – https://github.com/confluentinc/librdkafka */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Versioning                                                                */
#define HC_KAFKA_VERSION_MAJOR 1
#define HC_KAFKA_VERSION_MINOR 0
#define HC_KAFKA_VERSION_PATCH 0

/* ────────────────────────────────────────────────────────────────────────── */
/* Logging                                                                   */
#ifndef HC_KAFKA_LOG_LEVEL
#define HC_KAFKA_LOG_LEVEL LOG_INFO
#endif

#ifndef HC_KAFKA_LOG_TAG
#define HC_KAFKA_LOG_TAG "hc_kafka"
#endif

typedef enum
{
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR,
    LOG_FATAL
} hc_log_level_e;

/* Simple stdio logger; applications may override by defining
 * HC_KAFKA_LOG_FN(level, fmt, ...) prior to including this header. */
#ifndef HC_KAFKA_LOG_FN
#define HC_KAFKA_LOG_FN hc_kafka_default_log
static inline void hc_kafka_default_log(hc_log_level_e level,
                                        const char *file,
                                        int line,
                                        const char *func,
                                        const char *fmt, ...)
{
    if (level < HC_KAFKA_LOG_LEVEL)
        return;

    static const char *LEVEL_STR[] = {"DEBUG", "INFO", "WARN", "ERROR", "FATAL"};

    char timebuf[64];
    struct tm tm_now;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    localtime_r(&ts.tv_sec, &tm_now);
    strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", &tm_now);

    fprintf((level >= LOG_ERROR) ? stderr : stdout,
            "%s.%03ld [%s] %s:%d %s() : ",
            timebuf,
            ts.tv_nsec / 1000000,
            LEVEL_STR[level],
            file,
            line,
            func);

    va_list ap;
    va_start(ap, fmt);
    vfprintf((level >= LOG_ERROR) ? stderr : stdout, fmt, ap);
    va_end(ap);

    fputc('\n', (level >= LOG_ERROR) ? stderr : stdout);

    if (level == LOG_FATAL)
        abort();
}
#endif /* HC_KAFKA_LOG_FN */

#define HC_LOG(lvl, ...) HC_KAFKA_LOG_FN((lvl), __FILE__, __LINE__, __func__, __VA_ARGS__)

/* ────────────────────────────────────────────────────────────────────────── */
/* Error handling                                                            */

typedef enum
{
    HC_OK = 0,
    HC_ERR = -1,
    HC_ERR_TIMEOUT = -2,
    HC_ERR_EOF = -3
} hc_err_e;

#define HC_KAFKA_MAX_ERR_STR 512

static inline const char *hc_strerror(hc_err_e err)
{
    switch (err)
    {
    case HC_OK:
        return "OK";
    case HC_ERR:
        return "Generic error";
    case HC_ERR_TIMEOUT:
        return "Timeout";
    case HC_ERR_EOF:
        return "End of partition";
    default:
        return "Unknown error";
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Configuration                                                             */

/* The main configuration object that can be shared across producer/consumer. */
typedef struct
{
    char *bootstrap_servers; /* Comma separated list of brokers */
    char *client_id;         /* Custom client id (optional)     */
} hc_kafka_conf_t;

/* Forward declarations */
typedef struct hc_kafka_producer_s hc_kafka_producer_t;
typedef struct hc_kafka_consumer_s hc_kafka_consumer_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Global state                                                              */

static pthread_once_t g_kafka_global_init_once = PTHREAD_ONCE_INIT;

/* Called once per process */
static void hc_kafka__rdk_init_once(void)
{
    rd_kafka_configure_events(); /* noop stub if disabled in librdkafka build */
    /* Nothing else for now */
}

/* Ensure global initialization of librdkafka – must be called before any API. */
static inline void hc_kafka_global_init(void)
{
    (void)pthread_once(&g_kafka_global_init_once, hc_kafka__rdk_init_once);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Producer                                                                  */

struct hc_kafka_producer_s
{
    rd_kafka_t *rk;
    rd_kafka_conf_t *conf;
    char errstr[HC_KAFKA_MAX_ERR_STR];
    pthread_mutex_t lock;
};

static inline hc_kafka_producer_t *
hc_kafka_producer_new(const hc_kafka_conf_t *cfg)
{
    hc_kafka_global_init();

    hc_kafka_producer_t *self = calloc(1, sizeof(*self));
    if (!self)
    {
        HC_LOG(LOG_FATAL, "Out of memory creating producer");
        return NULL;
    }

    self->conf = rd_kafka_conf_new();
    rd_kafka_conf_set_log_cb(self->conf, NULL); /* Use default internal logging */

    if (rd_kafka_conf_set(self->conf, "bootstrap.servers", cfg->bootstrap_servers,
                          self->errstr, sizeof(self->errstr)) != RD_KAFKA_CONF_OK)
    {
        HC_LOG(LOG_ERROR, "Kafka conf error: %s", self->errstr);
        goto fail;
    }

    if (cfg->client_id &&
        rd_kafka_conf_set(self->conf, "client.id", cfg->client_id,
                          self->errstr, sizeof(self->errstr)) != RD_KAFKA_CONF_OK)
    {
        HC_LOG(LOG_WARN, "Kafka conf client.id: %s", self->errstr);
    }

    /* Improve latency for micro-services */
    rd_kafka_conf_set(self->conf, "queue.buffering.max.ms", "5", NULL, 0);
    rd_kafka_conf_set(self->conf, "linger.ms", "0", NULL, 0);
    rd_kafka_conf_set(self->conf, "acks", "all", NULL, 0);

    self->rk = rd_kafka_new(RD_KAFKA_PRODUCER, self->conf,
                            self->errstr, sizeof(self->errstr));
    if (!self->rk)
    {
        HC_LOG(LOG_ERROR, "Kafka producer init: %s", self->errstr);
        goto fail;
    }

    pthread_mutex_init(&self->lock, NULL);
    HC_LOG(LOG_INFO, "Kafka producer created (client.id=%s)",
           cfg->client_id ? cfg->client_id : "N/A");
    return self;

fail:
    if (self->conf)
        rd_kafka_conf_destroy(self->conf);
    free(self);
    return NULL;
}

/*
 * Non-blocking send – copies payload, returns immediately.
 * On success returns HC_OK.  In case of queue‐full backpressure, waits
 * (block_ms) milliseconds before giving up with HC_ERR_TIMEOUT.
 */
static inline hc_err_e
hc_kafka_producer_send(hc_kafka_producer_t *self,
                       const char *topic,
                       const void *payload,
                       size_t len,
                       int32_t partition, /* RD_KAFKA_PARTITION_UA for any */
                       int block_ms)
{
    if (!self || !topic)
        return HC_ERR;

    rd_kafka_resp_err_t err;
    int remaining_wait = block_ms;

    pthread_mutex_lock(&self->lock);

retry:
    err = rd_kafka_producev(
        self->rk,
        RD_KAFKA_V_TOPIC(topic),
        RD_KAFKA_V_PARTITION(partition),
        RD_KAFKA_V_MSGFLAGS(RD_KAFKA_MSG_F_COPY),
        RD_KAFKA_V_VALUE(payload, len),
        RD_KAFKA_V_END);

    if (!err)
    {
        pthread_mutex_unlock(&self->lock);
        return HC_OK; /* queued successfully */
    }

    if (err == RD_KAFKA_RESP_ERR__QUEUE_FULL && remaining_wait > 0)
    {
        rd_kafka_poll(self->rk, 0);  /* serve delivery reports */
        const int backoff = 50;      /* ms */
        struct timespec ts = {.tv_sec = 0, .tv_nsec = backoff * 1000000};
        nanosleep(&ts, NULL);
        remaining_wait -= backoff;
        goto retry;
    }

    HC_LOG(LOG_ERROR, "Produce failed: %s", rd_kafka_err2str(err));
    pthread_mutex_unlock(&self->lock);
    return HC_ERR;
}

/* Poll delivery callbacks.  Return number of events served. */
static inline int
hc_kafka_producer_poll(hc_kafka_producer_t *self, int timeout_ms)
{
    return rd_kafka_poll(self->rk, timeout_ms);
}

/* Flush outstanding messages; timeout_ms < 0 waits indefinitely. */
static inline hc_err_e
hc_kafka_producer_flush(hc_kafka_producer_t *self, int timeout_ms)
{
    int ret = rd_kafka_flush(self->rk, timeout_ms < 0 ? INT_MAX : timeout_ms);
    return (ret == RD_KAFKA_RESP_ERR_NO_ERROR) ? HC_OK : HC_ERR_TIMEOUT;
}

static inline void
hc_kafka_producer_destroy(hc_kafka_producer_t *self)
{
    if (!self)
        return;

    hc_kafka_producer_flush(self, 10 * 1000);
    rd_kafka_destroy(self->rk);
    pthread_mutex_destroy(&self->lock);
    free(self);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Consumer                                                                  */

typedef void (*hc_kafka_msg_cb)(const rd_kafka_message_t *rkmsg, void *opaque);

struct hc_kafka_consumer_s
{
    rd_kafka_t *rk;
    rd_kafka_conf_t *conf;
    rd_kafka_topic_partition_list_t *subscribed;
    hc_kafka_msg_cb on_msg;
    void *opaque;
    char errstr[HC_KAFKA_MAX_ERR_STR];
};

static inline hc_kafka_consumer_t *
hc_kafka_consumer_new(const hc_kafka_conf_t *cfg,
                      const char *group_id,
                      hc_kafka_msg_cb on_msg,
                      void *opaque)
{
    hc_kafka_global_init();

    hc_kafka_consumer_t *self = calloc(1, sizeof(*self));
    if (!self)
        return NULL;

    self->conf = rd_kafka_conf_new();
    rd_kafka_conf_set(self->conf, "bootstrap.servers", cfg->bootstrap_servers, NULL, 0);
    rd_kafka_conf_set(self->conf, "group.id", group_id, NULL, 0);
    rd_kafka_conf_set(self->conf, "auto.offset.reset", "earliest", NULL, 0);
    rd_kafka_conf_set(self->conf, "enable.auto.commit", "false", NULL, 0);
    rd_kafka_conf_set(self->conf, "enable.partition.eof", "true", NULL, 0);

    if (cfg->client_id)
        rd_kafka_conf_set(self->conf, "client.id", cfg->client_id, NULL, 0);

    self->rk = rd_kafka_new(RD_KAFKA_CONSUMER, self->conf,
                            self->errstr, sizeof(self->errstr));
    if (!self->rk)
    {
        HC_LOG(LOG_ERROR, "Kafka consumer new: %s", self->errstr);
        goto fail;
    }

    rd_kafka_poll_set_consumer(self->rk); /* Redirect rd_kafka_poll() to consumer_poll */

    self->on_msg = on_msg;
    self->opaque = opaque;

    HC_LOG(LOG_INFO, "Kafka consumer created (group=%s)", group_id);
    return self;

fail:
    if (self->conf)
        rd_kafka_conf_destroy(self->conf);
    free(self);
    return NULL;
}

static inline hc_err_e
hc_kafka_consumer_subscribe(hc_kafka_consumer_t *self,
                            const char *const *topics,
                            size_t topic_cnt)
{
    if (!self || topic_cnt == 0)
        return HC_ERR;

    self->subscribed = rd_kafka_topic_partition_list_new((int)topic_cnt);
    for (size_t i = 0; i < topic_cnt; ++i)
        rd_kafka_topic_partition_list_add(self->subscribed, topics[i], RD_KAFKA_PARTITION_UA);

    rd_kafka_resp_err_t err = rd_kafka_subscribe(self->rk, self->subscribed);
    if (err)
    {
        HC_LOG(LOG_ERROR, "Failed to subscribe: %s", rd_kafka_err2str(err));
        rd_kafka_topic_partition_list_destroy(self->subscribed);
        self->subscribed = NULL;
        return HC_ERR;
    }
    return HC_OK;
}

/* Blocking poll loop helper; returns HC_ERR on fatal error or when stop flag set */
static inline hc_err_e
hc_kafka_consumer_poll_loop(hc_kafka_consumer_t *self,
                            int timeout_ms,
                            volatile sig_atomic_t *stop_flag)
{
    while (!(*stop_flag))
    {
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(self->rk, timeout_ms);
        if (!rkmsg)
            continue;

        if (rkmsg->err)
        {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF)
            {
                /* Silently ignore EOFs to avoid log spam */
                rd_kafka_message_destroy(rkmsg);
                continue;
            }
            HC_LOG(LOG_WARN, "Consumer error: %s", rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Dispatch to user callback */
        if (self->on_msg)
            self->on_msg(rkmsg, self->opaque);

        rd_kafka_message_destroy(rkmsg);
    }

    return HC_OK;
}

static inline hc_err_e
hc_kafka_consumer_commit(hc_kafka_consumer_t *self)
{
    rd_kafka_resp_err_t err = rd_kafka_commit(self->rk, NULL, false);
    if (err)
    {
        HC_LOG(LOG_ERROR, "Commit failed: %s", rd_kafka_err2str(err));
        return HC_ERR;
    }
    return HC_OK;
}

static inline void
hc_kafka_consumer_destroy(hc_kafka_consumer_t *self)
{
    if (!self)
        return;

    rd_kafka_consumer_close(self->rk);
    rd_kafka_topic_partition_list_destroy(self->subscribed);
    rd_kafka_destroy(self->rk);
    free(self);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Utilities                                                                 */

/* Convert timeval to milliseconds since epoch */
static inline int64_t hc_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HC_KAFKA_H */
