```c
/**
 * HoloCanvas – Oracle-Bridge Microservice
 * File: services/oracle_bridge/src/feed_manager.c
 *
 * Description
 * ------------
 *  The Feed-Manager is responsible for:
 *   • Registering off-chain oracle feeds (HTTP / WebSocket / gRPC, etc.).
 *   • Polling / subscribing to those endpoints.
 *   • Verifying the authenticity of data (basic SHA-256 HMAC).
 *   • Publishing normalised updates onto the internal Event Mesh (Kafka).
 *
 *  NOTE:  Only the HTTP-pull strategy is implemented below for brevity,
 *         but the architecture leaves room for additional transport
 *         strategies (WebSocket, ZeroMQ-push, gRPC-stream, …).
 *
 * Build Dependencies
 * -------------------
 *   – OpenSSL (libcrypto)              :  signature / digest
 *   – libcurl                          :  HTTP transport
 *   – librdkafka                       :  Kafka client
 *   – POSIX Threads                    :  feed workers
 *
 * Copyright
 * ----------
 *   © 2023-24 HoloCanvas Contributors.  All rights reserved.
 */

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <curl/curl.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <rdkafka/rdkafka.h>

#include "feed_manager.h"
#include "logger.h"
#include "config.h"

/*-------------------------------------------------------------*
 *                         CONSTANTS                           *
 *-------------------------------------------------------------*/

#define HC_FM_MAX_FEED_ID        64
#define HC_FM_MAX_ENDPOINT_LEN   256
#define HC_FM_MAX_TOPIC_LEN      128
#define HC_FM_DEFAULT_INTERVAL_S 30u
#define HC_FM_HMAC_KEY_BYTES     32u    /* 256-bit key */

/*-------------------------------------------------------------*
 *                          DATA TYPES                         *
 *-------------------------------------------------------------*/

/**
 * oracle_feed_t:
 *  Runtime description of a single external oracle feed.
 */
typedef struct {
    char      id[HC_FM_MAX_FEED_ID];
    char      endpoint[HC_FM_MAX_ENDPOINT_LEN];
    char      topic[HC_FM_MAX_TOPIC_LEN];
    uint32_t  interval_s;                 /* polling interval in seconds */
    time_t    last_polled;                /* for adaptive back-off */
    pthread_t worker;
} oracle_feed_t;

/**
 * feed_manager_t:
 *  Global (singleton) manager context.
 */
struct feed_manager {
    oracle_feed_t *feeds;
    size_t         feed_count;

    rd_kafka_t    *kafka;
    uint8_t        hmac_key[HC_FM_HMAC_KEY_BYTES];

    volatile bool  running;
    pthread_mutex_t lock;
};

static feed_manager_t g_mgr = {
    .feeds      = NULL,
    .feed_count = 0,
    .kafka      = NULL,
    .hmac_key   = {0},
    .running    = false,
    .lock       = PTHREAD_MUTEX_INITIALIZER,
};

/*-------------------------------------------------------------*
 *                      FORWARD DECLARATIONS                   *
 *-------------------------------------------------------------*/

static size_t http_write_cb(char *ptr, size_t size, size_t nmemb, void *userdata);
static void  *feed_worker_routine(void *arg);
static bool   fm_publish_kafka(oracle_feed_t *feed,
                               const char    *payload,
                               const char    *sig_hex);

/*-------------------------------------------------------------*
 *                    UTILITY IMPLEMENTATIONS                  *
 *-------------------------------------------------------------*/

/**
 * bin_to_hex:
 *  Converts binary data into a lower-case hex string.
 */
static void bin_to_hex(const uint8_t *bin, size_t len, char *hex_out)
{
    static const char lut[] = "0123456789abcdef";
    for (size_t i = 0; i < len; ++i) {
        hex_out[i * 2]     = lut[(bin[i] >> 4) & 0xF];
        hex_out[i * 2 + 1] = lut[bin[i] & 0xF];
    }
    hex_out[len * 2] = '\0';
}

/**
 * sign_payload:
 *  Computes SHA-256 HMAC of the payload and converts to hex.
 */
static void sign_payload(const uint8_t *key, size_t key_len,
                         const char *msg, char *sig_hex_out)
{
    unsigned int dgst_len = EVP_MAX_MD_SIZE;
    uint8_t dgst[EVP_MAX_MD_SIZE];

    HMAC(EVP_sha256(), key, (int)key_len,
         (const unsigned char *)msg, strlen(msg),
         dgst, &dgst_len);

    bin_to_hex(dgst, dgst_len, sig_hex_out);
}

/*-------------------------------------------------------------*
 *                      HTTP HELPERS (libcurl)                 *
 *-------------------------------------------------------------*/

/**
 * http_write_cb:
 *  Accumulates HTTP response into a growable string buffer.
 */
typedef struct {
    char  *data;
    size_t len;
} buf_t;

static size_t http_write_cb(char *ptr, size_t size, size_t nmemb, void *userdata)
{
    size_t real_size = size * nmemb;
    buf_t *buf = (buf_t *)userdata;

    char *new_mem = realloc(buf->data, buf->len + real_size + 1);
    if (!new_mem)
        return 0; /* curl will abort the transfer */

    buf->data = new_mem;
    memcpy(&(buf->data[buf->len]), ptr, real_size);
    buf->len += real_size;
    buf->data[buf->len] = '\0';

    return real_size;
}

/*-------------------------------------------------------------*
 *                 KAFKA PUBLISH IMPLEMENTATION                *
 *-------------------------------------------------------------*/

static bool fm_publish_kafka(oracle_feed_t *feed,
                             const char    *payload,
                             const char    *sig_hex)
{
    rd_kafka_resp_err_t err;
    rd_kafka_topic_t *topic_obj = rd_kafka_topic_new(g_mgr.kafka,
                                                     feed->topic, NULL);
    if (!topic_obj) {
        HC_LOG_ERROR("Kafka: failed to create topic object '%s': %s",
                     feed->topic, rd_kafka_err2str(rd_kafka_last_error()));
        return false;
    }

    /* Construct a composite message: JSON {payload, signature} */
    char *msg;
    int   n = asprintf(&msg, "{\"feed_id\":\"%s\","
                             "\"payload\":%s,"
                             "\"signature\":\"%s\","
                             "\"ts\":%ld}",
                             feed->id,
                             payload,
                             sig_hex,
                             time(NULL));
    if (n == -1) {
        rd_kafka_topic_destroy(topic_obj);
        return false;
    }

    err = rd_kafka_produce(
        topic_obj,
        RD_KAFKA_PARTITION_UA,
        RD_KAFKA_MSG_F_COPY,
        msg, n,
        NULL, 0,
        NULL);

    rd_kafka_topic_destroy(topic_obj);
    free(msg);

    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        HC_LOG_ERROR("Kafka: failed to publish to '%s': %s",
                     feed->topic, rd_kafka_err2str(err));
        return false;
    }
    return true;
}

/*-------------------------------------------------------------*
 *                 FEED WORKER THREAD ROUTINE                  *
 *-------------------------------------------------------------*/

static void *feed_worker_routine(void *arg)
{
    oracle_feed_t *feed = (oracle_feed_t *)arg;
    CURL *curl = curl_easy_init();

    if (!curl) {
        HC_LOG_ERROR("Feed[%s]: failed to init curl", feed->id);
        return NULL;
    }

    buf_t resp = {.data = NULL, .len = 0};
    CURLcode cc;

    while (g_mgr.running) {

        /* ---------- Poll ---------- */
        resp.len = 0;
        free(resp.data);
        resp.data = NULL;

        curl_easy_setopt(curl, CURLOPT_URL, feed->endpoint);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, http_write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 8L);            /* seconds */
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

        cc = curl_easy_perform(curl);
        if (cc != CURLE_OK) {
            HC_LOG_WARN("Feed[%s]: HTTP error: %s",
                        feed->id, curl_easy_strerror(cc));
            /* Apply exponential back-off (max 5x interval) */
            sleep(feed->interval_s * 2);
            continue;
        }

        /* ---------- Sign & Publish ---------- */
        char sig_hex[EVP_MAX_MD_SIZE * 2 + 1];
        sign_payload(g_mgr.hmac_key, sizeof(g_mgr.hmac_key),
                     resp.data ? resp.data : "", sig_hex);

        if (!fm_publish_kafka(feed, resp.data ? resp.data : "null", sig_hex)) {
            HC_LOG_WARN("Feed[%s]: failed to publish Kafka message", feed->id);
        } else {
            HC_LOG_INFO("Feed[%s]: update forwarded (payload %zu bytes)",
                        feed->id, resp.len);
        }

        /* ---------- Sleep until next tick ---------- */
        for (uint32_t i = 0; g_mgr.running && i < feed->interval_s; ++i)
            sleep(1);
    }

    free(resp.data);
    curl_easy_cleanup(curl);
    return NULL;
}

/*-------------------------------------------------------------*
 *              PUBLIC API – FEED MANAGER INTERFACE            *
 *-------------------------------------------------------------*/

bool fm_init(const fm_config_t *cfg)
{
    if (g_mgr.running) {
        HC_LOG_ERROR("FeedManager already running");
        return false;
    }

    /* ---------- Init libcurl ---------- */
    if (curl_global_init(CURL_GLOBAL_ALL) != 0) {
        HC_LOG_ERROR("curl_global_init failed");
        return false;
    }

    /* ---------- Copy HMAC key ---------- */
    if (cfg->hmac_key_len != HC_FM_HMAC_KEY_BYTES) {
        HC_LOG_ERROR("HMAC key must be %u bytes", HC_FM_HMAC_KEY_BYTES);
        return false;
    }
    memcpy(g_mgr.hmac_key, cfg->hmac_key, HC_FM_HMAC_KEY_BYTES);

    /* ---------- Init Kafka ---------- */
    char errstr[512];
    rd_kafka_conf_t *kconf = rd_kafka_conf_new();
    rd_kafka_conf_set(kconf, "bootstrap.servers",
                      cfg->kafka_bootstrap, errstr, sizeof(errstr));
    rd_kafka_conf_set(kconf, "compression.type", "zstd",
                      errstr, sizeof(errstr));

    g_mgr.kafka = rd_kafka_new(RD_KAFKA_PRODUCER, kconf,
                               errstr, sizeof(errstr));
    if (!g_mgr.kafka) {
        HC_LOG_ERROR("Kafka init failed: %s", errstr);
        curl_global_cleanup();
        return false;
    }

    g_mgr.running = true;
    HC_LOG_INFO("FeedManager initialised");
    return true;
}

bool fm_shutdown(void)
{
    if (!g_mgr.running)
        return true;

    g_mgr.running = false;

    /* ---------- Join worker threads ---------- */
    for (size_t i = 0; i < g_mgr.feed_count; ++i)
        pthread_join(g_mgr.feeds[i].worker, NULL);

    /* ---------- Cleanup ---------- */
    rd_kafka_flush(g_mgr.kafka, 3000);
    rd_kafka_destroy(g_mgr.kafka);
    curl_global_cleanup();
    free(g_mgr.feeds);
    memset(&g_mgr, 0, sizeof(g_mgr)); /* zero entire struct */

    HC_LOG_INFO("FeedManager shut down");
    return true;
}

bool fm_register_feed(const char *feed_id,
                      const char *endpoint,
                      const char *topic,
                      uint32_t    interval_s)
{
    if (!feed_id || !endpoint || !topic || strlen(feed_id) == 0)
        return false;

    pthread_mutex_lock(&g_mgr.lock);

    /* ---------- Grow feed array ---------- */
    oracle_feed_t *new_arr = realloc(g_mgr.feeds,
                                     (g_mgr.feed_count + 1) *
                                     sizeof(oracle_feed_t));
    if (!new_arr) {
        pthread_mutex_unlock(&g_mgr.lock);
        HC_LOG_ERROR("Memory allocation failed while registering feed");
        return false;
    }
    g_mgr.feeds = new_arr;

    /* ---------- Populate entry ---------- */
    oracle_feed_t *feed = &g_mgr.feeds[g_mgr.feed_count];
    memset(feed, 0, sizeof(*feed));
    strncpy(feed->id,       feed_id,  sizeof(feed->id) - 1);
    strncpy(feed->endpoint, endpoint, sizeof(feed->endpoint) - 1);
    strncpy(feed->topic,    topic,    sizeof(feed->topic) - 1);
    feed->interval_s = interval_s ? interval_s : HC_FM_DEFAULT_INTERVAL_S;

    /* ---------- Launch worker ---------- */
    if (pthread_create(&feed->worker, NULL,
                       feed_worker_routine, feed) != 0) {
        HC_LOG_ERROR("Failed to spawn thread for feed '%s'", feed->id);
        pthread_mutex_unlock(&g_mgr.lock);
        return false;
    }

    g_mgr.feed_count++;
    pthread_mutex_unlock(&g_mgr.lock);

    HC_LOG_INFO("Feed[%s] registered (interval %u s)",
                feed->id, feed->interval_s);
    return true;
}

/*-------------------------------------------------------------*
 *                      SIGNAL HANDLING (POSIX)                *
 *-------------------------------------------------------------*/

static void fm_sig_handler(int signo)
{
    (void)signo;
    fm_shutdown();
}

__attribute__((constructor))
static void fm_auto_init(void)
{
    /* Install signal handlers for graceful shutdown */
    signal(SIGINT,  fm_sig_handler);
    signal(SIGTERM, fm_sig_handler);
}

/*-------------------------------------------------------------*
 *                       TEST HARNESS (Optional)               *
 *-------------------------------------------------------------*/
#ifdef HC_FEED_MANAGER_STANDALONE

static void load_cfg(fm_config_t *cfg)
{
    /* Example configuration loader */
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->kafka_bootstrap,
            getenv("KAFKA_BOOTSTRAP") ? getenv("KAFKA_BOOTSTRAP") :
            "localhost:9092",
            sizeof(cfg->kafka_bootstrap) - 1);

    /* In production the key would come from Vault / KMS */
    for (size_t i = 0; i < HC_FM_HMAC_KEY_BYTES; ++i)
        cfg->hmac_key[i] = (uint8_t)i;
    cfg->hmac_key_len = HC_FM_HMAC_KEY_BYTES;
}

int main(void)
{
    fm_config_t cfg;
    load_cfg(&cfg);

    if (!fm_init(&cfg))
        return EXIT_FAILURE;

    fm_register_feed("coingecko_btc_usd",
                     "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                     "oracle.btcusd",
                     15);

    /* Block main thread until manager stops */
    while (g_mgr.running)
        pause();

    return EXIT_SUCCESS;
}
#endif /* HC_FEED_MANAGER_STANDALONE */
```