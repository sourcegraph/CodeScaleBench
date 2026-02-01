/**
 * HoloCanvas Oracle-Bridge — Event Producer
 * -----------------------------------------
 * Produces canonical JSON-encoded oracle events to the HoloCanvas
 * event mesh (Kafka).  This component is embedded in the Oracle-Bridge
 * micro-service and is responsible for
 *
 *  • Marshaling Oracle observations into JSON
 *  • Buffering messages in an in-memory queue to avoid blocking the
 *    hot-path ingest loop
 *  • Publishing messages to Kafka with exactly-once producer semantics
 *  • Reporting delivery status and statistics
 *
 * The module is intentionally self-contained so that it can be used by
 * both the core Oracle-Bridge and unit-tests without dragging in the
 * rest of the micro-service.
 *
 * Build Dependencies
 * ------------------
 *   • librdkafka          (https://github.com/edenhill/librdkafka)
 *   • cJSON               (https://github.com/DaveGamble/cJSON)
 *
 * Example
 * -------
 *      ob_event_producer_t producer;
 *
 *      if (ob_event_producer_init(&producer,
 *                                 "kafka-broker-1:9092,kafka-broker-2:9092",
 *                                 "hc.oracle.events") != 0) {
 *          fprintf(stderr, "Could not start producer\n");
 *          exit(EXIT_FAILURE);
 *      }
 *
 *      cJSON *payload = cJSON_CreateObject();
 *      cJSON_AddStringToObject(payload, "symbol", "ETH/USD");
 *      cJSON_AddNumberToObject(payload, "price", 3621.42);
 *
 *      char *json = cJSON_PrintUnformatted(payload);
 *      ob_event_producer_enqueue(&producer, "ethusd", json);
 *      cJSON_free(json);
 *      cJSON_Delete(payload);
 *
 *      ob_event_producer_shutdown(&producer);
 *
 * Author:   github.com/holocanvas
 * License:  MIT
 */

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <librdkafka/rdkafka.h>
#include <cjson/cJSON.h>

#include "event_producer.h"     /* public API */

/* -------------------------------------------------------------------------- */
/* Configuration defaults                                                     */
/* -------------------------------------------------------------------------- */

#define OB_MAX_INFLIGHT                16384
#define OB_QUEUE_CAPACITY              4096
#define OB_DELIVERY_FLUSH_TIMEOUT_MS   10 * 1000

/* -------------------------------------------------------------------------- */
/* Logging helpers                                                            */
/* -------------------------------------------------------------------------- */

#ifndef OB_LOG_TAG
#define OB_LOG_TAG "oracle-bridge:event-producer"
#endif

#define OB_LOG_ERR(fmt, ...)  fprintf(stderr, "[%s] ERROR: " fmt "\n", OB_LOG_TAG, ##__VA_ARGS__)
#define OB_LOG_WARN(fmt, ...) fprintf(stderr, "[%s] WARN : " fmt "\n", OB_LOG_TAG, ##__VA_ARGS__)
#define OB_LOG_INFO(fmt, ...) fprintf(stdout, "[%s] INFO : " fmt "\n", OB_LOG_TAG, ##__VA_ARGS__)

/* -------------------------------------------------------------------------- */
/* Internal types                                                             */
/* -------------------------------------------------------------------------- */

typedef struct ob_event_item_s {
    char   *key;           /* partition key — UTF-8 string */
    char   *payload;       /* JSON payload */
    size_t  payload_len;
    struct ob_event_item_s *next;
} ob_event_item_t;

typedef struct {
    ob_event_item_t *head;
    ob_event_item_t *tail;
    size_t           size;
    pthread_mutex_t  mutex;
    pthread_cond_t   cv_nonempty;
    pthread_cond_t   cv_nonfull;
} ob_event_queue_t;

/* -------------------------------------------------------------------------- */
/* Forward declarations                                                       */
/* -------------------------------------------------------------------------- */

static int  queue_init(ob_event_queue_t *q);
static void queue_destroy(ob_event_queue_t *q);
static int  queue_push(ob_event_queue_t *q, const char *key,
                       const char *payload, size_t plen, size_t capacity);
static int  queue_pop(ob_event_queue_t *q, ob_event_item_t **out);
static void queue_item_destroy(ob_event_item_t *item);

static void *producer_thread(void *arg);
static void  handle_delivery_report(rd_kafka_t *rk, const rd_kafka_message_t *rkmsg, void *opaque);

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

int ob_event_producer_init(ob_event_producer_t       *self,
                           const char                *brokers,
                           const char                *topic)
{
    if (!self || !brokers || !topic) {
        errno = EINVAL;
        return -1;
    }

    memset(self, 0, sizeof(*self));

    /* Create Kafka configuration */
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    if (!conf) {
        OB_LOG_ERR("librdkafka: cannot allocate configuration");
        return -1;
    }

    if (rd_kafka_conf_set(conf, "bootstrap.servers", brokers, 
                          NULL, 0) != RD_KAFKA_CONF_OK) {
        OB_LOG_ERR("Invalid broker list: %s", brokers);
        rd_kafka_conf_destroy(conf);
        return -1;
    }

    /* Enable idempotent producer for exactly-once semantics */
    rd_kafka_conf_set(conf, "enable.idempotence", "true", NULL, 0);
    rd_kafka_conf_set(conf, "compression.type",   "zstd", NULL, 0);
    rd_kafka_conf_set(conf, "socket.keepalive.enable", "true", NULL, 0);
    rd_kafka_conf_set(conf, "queue.buffering.max.messages",
                      "200000", NULL, 0);
    rd_kafka_conf_set(conf, "message.timeout.ms", "60000", NULL, 0);

    rd_kafka_conf_set_dr_msg_cb(conf, handle_delivery_report);

    char errstr[512];
    self->rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, errstr, sizeof(errstr));
    if (!self->rk) {
        OB_LOG_ERR("Failed to create producer: %s", errstr);
        rd_kafka_conf_destroy(conf);    /* conf is freed by rd_kafka_destroy, but only if we succeeded */
        return -1;
    }

    self->rkt = rd_kafka_topic_new(self->rk, topic, NULL);
    if (!self->rkt) {
        OB_LOG_ERR("Failed to create topic handle for %s: %s", topic,
                   rd_kafka_err2str(rd_kafka_last_error()));
        rd_kafka_destroy(self->rk);
        return -1;
    }

    /* Initialize internal queue */
    if (queue_init(&self->queue) != 0) {
        rd_kafka_topic_destroy(self->rkt);
        rd_kafka_destroy(self->rk);
        return -1;
    }

    self->queue_capacity = OB_QUEUE_CAPACITY;
    atomic_init(&self->running, true);

    /* Launch background producer thread */
    if (pthread_create(&self->thread, NULL, producer_thread, self) != 0) {
        OB_LOG_ERR("Could not create producer thread: %s", strerror(errno));
        queue_destroy(&self->queue);
        rd_kafka_topic_destroy(self->rkt);
        rd_kafka_destroy(self->rk);
        return -1;
    }

    OB_LOG_INFO("Event producer started (brokers=%s, topic=%s)", brokers, topic);
    return 0;
}

int ob_event_producer_enqueue(ob_event_producer_t *self,
                              const char          *key,
                              const char          *payload)
{
    if (!self || !payload) {
        errno = EINVAL;
        return -1;
    }
    size_t plen = strlen(payload);
    if (plen == 0) {
        errno = EINVAL;
        return -1;
    }

    return queue_push(&self->queue, key ? key : "", payload, plen,
                      self->queue_capacity);
}

void ob_event_producer_shutdown(ob_event_producer_t *self)
{
    if (!self) return;

    /* Signal background thread to exit */
    atomic_store(&self->running, false);

    pthread_mutex_lock(&self->queue.mutex);
    pthread_cond_signal(&self->queue.cv_nonempty);
    pthread_mutex_unlock(&self->queue.mutex);

    /* Wait until thread joins */
    pthread_join(self->thread, NULL);

    queue_destroy(&self->queue);

    /* Flush outstanding messages */
    OB_LOG_INFO("Flushing %d outstanding Kafka messages",
                rd_kafka_outq_len(self->rk));
    rd_kafka_flush(self->rk, OB_DELIVERY_FLUSH_TIMEOUT_MS);

    rd_kafka_topic_destroy(self->rkt);
    rd_kafka_destroy(self->rk);

    OB_LOG_INFO("Event producer shut down");
}

/* -------------------------------------------------------------------------- */
/* Internal: Bounded queue implementation                                     */
/* -------------------------------------------------------------------------- */

static int queue_init(ob_event_queue_t *q)
{
    memset(q, 0, sizeof(*q));
    if (pthread_mutex_init(&q->mutex, NULL) != 0)
        return -1;
    if (pthread_cond_init(&q->cv_nonempty, NULL) != 0) {
        pthread_mutex_destroy(&q->mutex);
        return -1;
    }
    if (pthread_cond_init(&q->cv_nonfull, NULL) != 0) {
        pthread_cond_destroy(&q->cv_nonempty);
        pthread_mutex_destroy(&q->mutex);
        return -1;
    }
    return 0;
}

static void queue_destroy(ob_event_queue_t *q)
{
    pthread_mutex_lock(&q->mutex);
    while (q->head) {
        ob_event_item_t *tmp = q->head;
        q->head = q->head->next;
        queue_item_destroy(tmp);
    }
    pthread_mutex_unlock(&q->mutex);

    pthread_cond_destroy(&q->cv_nonempty);
    pthread_cond_destroy(&q->cv_nonfull);
    pthread_mutex_destroy(&q->mutex);
}

static int queue_push(ob_event_queue_t *q, const char *key,
                      const char *payload, size_t plen, size_t capacity)
{
    int rc = 0;
    ob_event_item_t *item = calloc(1, sizeof(*item));
    if (!item)
        return -1;

    item->key         = strdup(key);
    item->payload     = strndup(payload, plen);
    item->payload_len = plen;
    item->next        = NULL;

    pthread_mutex_lock(&q->mutex);

    while (q->size >= capacity) {
        /* Queue full: wait for space */
        pthread_cond_wait(&q->cv_nonfull, &q->mutex);
    }

    if (q->tail)
        q->tail->next = item;
    else
        q->head = item;

    q->tail = item;
    q->size++;

    pthread_cond_signal(&q->cv_nonempty);
    pthread_mutex_unlock(&q->mutex);

    return rc;
}

static int queue_pop(ob_event_queue_t *q, ob_event_item_t **out)
{
    pthread_mutex_lock(&q->mutex);

    while (q->size == 0) {
        pthread_cond_wait(&q->cv_nonempty, &q->mutex);
    }

    ob_event_item_t *item = q->head;
    if (!item) {
        pthread_mutex_unlock(&q->mutex);
        return -1; /* should not happen */
    }

    q->head = item->next;
    if (!q->head)
        q->tail = NULL;

    q->size--;
    pthread_cond_signal(&q->cv_nonfull);
    pthread_mutex_unlock(&q->mutex);

    *out = item;
    return 0;
}

static void queue_item_destroy(ob_event_item_t *item)
{
    if (!item) return;
    free(item->key);
    free(item->payload);
    free(item);
}

/* -------------------------------------------------------------------------- */
/* Internal: Kafka producer thread                                            */
/* -------------------------------------------------------------------------- */

static void *producer_thread(void *arg)
{
    ob_event_producer_t *self = (ob_event_producer_t *)arg;
    ob_event_item_t *item = NULL;

    while (atomic_load(&self->running) || self->queue.size > 0) {
        if (queue_pop(&self->queue, &item) != 0) {
            continue;
        }

        /* Produce the message */
        rd_kafka_resp_err_t err = rd_kafka_producev(
            self->rk,
            RD_KAFKA_V_TOPIC(rd_kafka_topic_name(self->rkt)),
            RD_KAFKA_V_KEY(item->key, strlen(item->key)),
            RD_KAFKA_V_VALUE(item->payload, item->payload_len),
            RD_KAFKA_V_MSGFLAGS(RD_KAFKA_MSG_F_COPY),
            RD_KAFKA_V_END);

        if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
            OB_LOG_ERR("Failed to produce message: %s",
                       rd_kafka_err2str(err));
        }

        queue_item_destroy(item);
        item = NULL;

        /* Poll for delivery reports */
        rd_kafka_poll(self->rk, 0);
    }

    /* Ensure all outstanding delivery reports are processed */
    while (rd_kafka_outq_len(self->rk) > 0) {
        rd_kafka_poll(self->rk, 100);
    }

    return NULL;
}

/* -------------------------------------------------------------------------- */
/* Internal: Delivery report callback                                         */
/* -------------------------------------------------------------------------- */

static void handle_delivery_report(rd_kafka_t *rk,
                                   const rd_kafka_message_t *rkmsg,
                                   void *opaque)
{
    (void)rk;
    (void)opaque;

    if (rkmsg->err) {
        OB_LOG_ERR("Delivery failed: %s", rd_kafka_err2str(rkmsg->err));
    } else {
        OB_LOG_INFO("Delivered message to %s [partition %d] @ offset %ld",
                    rd_kafka_topic_name(rkmsg->rkt),
                    rkmsg->partition,
                    rkmsg->offset);
    }
}

/* -------------------------------------------------------------------------- */
/* Utility helpers (optional)                                                 */
/* -------------------------------------------------------------------------- */

/**
 * ob_event_create_price_tick()
 * ----------------------------
 * Convenience wrapper for the most common oracle event: a price tick.
 *
 * Caller owns the returned string (must free with cJSON_free()).
 */
char *ob_event_create_price_tick(const char *symbol, double price)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;

    cJSON_AddStringToObject(root, "event_type", "PRICE_TICK");
    cJSON_AddStringToObject(root, "symbol",     symbol);
    cJSON_AddNumberToObject(root, "price",      price);

    /* Timestamp — ISO-8601 */
    time_t now = time(NULL);
    struct tm tm;
    gmtime_r(&now, &tm);
    char iso[32];
    strftime(iso, sizeof(iso), "%Y-%m-%dT%H:%M:%SZ", &tm);
    cJSON_AddStringToObject(root, "ts", iso);

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json;
}