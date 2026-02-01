/*
 * HoloCanvas – Mint-Factory Service (main.c)
 *
 * The Mint-Factory converts “creative recipes” arriving via Kafka into on-chain
 * minting transactions dispatched to LedgerCore through gRPC.  Every mint
 * request is a JSON blob describing modular shader/audio fragments.  The
 * service validates the request, assembles an immutable artifact manifest,
 * persists it locally (for provenance audit) and finally forwards the signed
 * transaction to the ledger.
 *
 * Build requirements (example):
 *   gcc -std=c11 -Wall -Wextra -pedantic -O2 \
 *       -o mint_factory \
 *       main.c -lpthread -lrdkafka -lcjson -lgrpc -lssl -lcrypto
 *
 * Note: External libraries (librdkafka, cJSON, gRPC-C) must be installed.
 *       Stub fall-backs are provided for unit testing without these libs
 *       (compile with -DHOLO_MINT_FACTORY_STUBS).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <signal.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>

#ifndef HOLO_MINT_FACTORY_STUBS
    #include <cjson/cJSON.h>
    #include <librdkafka/rdkafka.h>
    #include <grpc/grpc.h>
    #include <grpc/impl/codegen/status.h>
#else
    /* ---------- Minimal stubs for unit testing ---------- */
    typedef struct cJSON          { int dummy; } cJSON;
    static cJSON *cJSON_Parse(const char *s)                 { (void)s; return NULL; }
    static void   cJSON_Delete(cJSON *d)                     { (void)d; }
    static char  *cJSON_PrintUnformatted(const cJSON *d)     { (void)d; return strdup("{}"); }
    typedef struct rd_kafka_s     rd_kafka_t;
    typedef struct rd_kafka_conf_s rd_kafka_conf_t;
    typedef struct rd_kafka_message_s { char *payload; size_t len; } rd_kafka_message_t;
    #define RD_KAFKA_RESP_ERR_NO_ERROR 0
    typedef enum { RD_KAFKA_PARTITION_UA = 0 } rd_kafka_topic_partition_t;
    static rd_kafka_conf_t *rd_kafka_conf_new(void)          { return NULL; }
    static rd_kafka_t      *rd_kafka_new(int t, rd_kafka_conf_t *c,
                                         char *e, size_t s){ (void)t;(void)c;(void)e;(void)s; return NULL; }
    static int rd_kafka_subscribe(rd_kafka_t *k, void *l) { (void)k;(void)l; return 0; }
    static rd_kafka_message_t *rd_kafka_consumer_poll(rd_kafka_t *k,int tout){(void)k;(void)tout; return NULL;}
    static void rd_kafka_message_destroy(rd_kafka_message_t *m) { (void)m; }
    static void rd_kafka_destroy(rd_kafka_t *k){ (void)k; }
    #define rd_kafka_event_t int
    #define rd_kafka_queue_t int
    static void *grpc_channel;
#endif /* HOLO_MINT_FACTORY_STUBS */

/* ------------------------------------------------------------------------- */
/*                            Compile-time Config                            */
/* ------------------------------------------------------------------------- */

#define SERVICE_NAME            "Mint-Factory"
#define DEFAULT_KAFKA_BROKER    "localhost:9092"
#define DEFAULT_KAFKA_TOPIC     "holo.mint.requests"
#define DEFAULT_LEDGER_ENDPOINT "localhost:50051"
#define MAX_ARTIFACT_ID_LEN     64
#define MAX_QUEUE_DEPTH         512
#define MAX_WORKERS             4
#define VERSION_STRING          "0.9.3"

/* ------------------------------------------------------------------------- */
/*                                  Logging                                  */
/* ------------------------------------------------------------------------- */

static pthread_mutex_t log_mtx = PTHREAD_MUTEX_INITIALIZER;

static void log_time(char *buf, size_t sz)
{
    time_t now = time(NULL);
    struct tm tm;
    gmtime_r(&now, &tm);
    strftime(buf, sz, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

#define LOG(level, fmt, ...)                                                       \
    do {                                                                           \
        char _ts[32];                                                              \
        log_time(_ts, sizeof _ts);                                                 \
        pthread_mutex_lock(&log_mtx);                                              \
        fprintf(stderr, "[%s] [%s] [%s] " fmt "\n", _ts, level, SERVICE_NAME,      \
                ##__VA_ARGS__);                                                    \
        pthread_mutex_unlock(&log_mtx);                                            \
    } while (0)

#define LOG_INFO(fmt, ...)   LOG("INFO",  fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)   LOG("WARN",  fmt, ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...)  LOG("ERROR", fmt, ##__VA_ARGS__)

/* ------------------------------------------------------------------------- */
/*                                Data Models                                */
/* ------------------------------------------------------------------------- */

typedef enum {
    ARTIFACT_DRAFT,
    ARTIFACT_CURATED,
    ARTIFACT_AUCTION,
    ARTIFACT_FRACTIONALIZED,
    ARTIFACT_STAKED
} artifact_state_e;

static const char *state_str(artifact_state_e s)
{
    switch (s) {
        case ARTIFACT_DRAFT:          return "Draft";
        case ARTIFACT_CURATED:        return "Curated";
        case ARTIFACT_AUCTION:        return "Auction";
        case ARTIFACT_FRACTIONALIZED: return "Fractionalized";
        case ARTIFACT_STAKED:         return "Staked";
        default:                      return "Unknown";
    }
}

typedef struct {
    char            id[MAX_ARTIFACT_ID_LEN];
    artifact_state_e state;
    cJSON          *manifest;          /* Parsed recipe JSON            */
    char           *serialized;        /* Manifest string (immutable)    */
} artifact_t;

/* ------------------------------------------------------------------------- */
/*                               Globals & Flags                             */
/* ------------------------------------------------------------------------- */

static atomic_bool g_shutdown_flag = ATOMIC_VAR_INIT(false);

/* ------------------------------------------------------------------------- */
/*                           POSIX Queue (bounded)                           */
/* ------------------------------------------------------------------------- */

typedef struct {
    artifact_t     *buf[MAX_QUEUE_DEPTH];
    size_t          head;
    size_t          tail;
    size_t          count;
    pthread_mutex_t mtx;
    pthread_cond_t  not_empty;
    pthread_cond_t  not_full;
} bqueue_t;

static void bq_init(bqueue_t *q)
{
    memset(q, 0, sizeof *q);
    pthread_mutex_init(&q->mtx, NULL);
    pthread_cond_init(&q->not_empty, NULL);
    pthread_cond_init(&q->not_full, NULL);
}

static void bq_push(bqueue_t *q, artifact_t *item)
{
    pthread_mutex_lock(&q->mtx);
    while (q->count == MAX_QUEUE_DEPTH && !atomic_load(&g_shutdown_flag))
        pthread_cond_wait(&q->not_full, &q->mtx);

    if (atomic_load(&g_shutdown_flag)) { pthread_mutex_unlock(&q->mtx); return; }

    q->buf[q->tail] = item;
    q->tail = (q->tail + 1) % MAX_QUEUE_DEPTH;
    q->count++;
    pthread_cond_signal(&q->not_empty);
    pthread_mutex_unlock(&q->mtx);
}

static artifact_t *bq_pop(bqueue_t *q)
{
    pthread_mutex_lock(&q->mtx);
    while (q->count == 0 && !atomic_load(&g_shutdown_flag))
        pthread_cond_wait(&q->not_empty, &q->mtx);

    artifact_t *item = NULL;
    if (!atomic_load(&g_shutdown_flag) && q->count > 0) {
        item = q->buf[q->head];
        q->head = (q->head + 1) % MAX_QUEUE_DEPTH;
        q->count--;
        pthread_cond_signal(&q->not_full);
    }
    pthread_mutex_unlock(&q->mtx);
    return item;
}

/* ------------------------------------------------------------------------- */
/*                          Configuration Management                         */
/* ------------------------------------------------------------------------- */

typedef struct {
    char kafka_broker[256];
    char kafka_topic[128];
    char ledger_endpoint[256];
    int  workers;
} config_t;

static void load_config(config_t *cfg)
{
    const char *env;

    strncpy(cfg->kafka_broker,
            (env = getenv("HOLO_KAFKA_BROKER")) ? env : DEFAULT_KAFKA_BROKER,
            sizeof cfg->kafka_broker - 1);

    strncpy(cfg->kafka_topic,
            (env = getenv("HOLO_KAFKA_TOPIC")) ? env : DEFAULT_KAFKA_TOPIC,
            sizeof cfg->kafka_topic - 1);

    strncpy(cfg->ledger_endpoint,
            (env = getenv("HOLO_LEDGER_ENDPOINT")) ? env : DEFAULT_LEDGER_ENDPOINT,
            sizeof cfg->ledger_endpoint - 1);

    cfg->workers = (env = getenv("HOLO_FACTORY_WORKERS")) ? atoi(env) : MAX_WORKERS;
    if (cfg->workers < 1 || cfg->workers > MAX_WORKERS)
        cfg->workers = MAX_WORKERS;
}

/* ------------------------------------------------------------------------- */
/*                       LedgerCore (gRPC) Integration                       */
/* ------------------------------------------------------------------------- */

static int ledger_send_mint_tx(const artifact_t *a, const config_t *cfg)
{
#ifdef HOLO_MINT_FACTORY_STUBS
    (void)a; (void)cfg;
    LOG_INFO("Stub ledger_send_mint_tx called for artifact %s", a->id);
    return 0;
#else
    /* TODO: Replace with real protobuf-generated client stubs. */
    grpc_init();
    grpc_channel_credentials *creds = grpc_insecure_channel_credentials();
    grpc_channel *chan = grpc_secure_channel_create(creds, cfg->ledger_endpoint, NULL, NULL);
    /* ... build and send request ... */
    (void)chan;
    LOG_INFO("Sent mint-transaction for artifact %s to ledger (%s)",
             a->id, cfg->ledger_endpoint);
    grpc_shutdown();
    return 0;
#endif
}

/* ------------------------------------------------------------------------- */
/*                      Artifact Assembly && Validation                      */
/* ------------------------------------------------------------------------- */

static int validate_manifest(cJSON *json)
{
    /* Basic sanity checks; deeper schema validation could be added */
    if (!json) return -1;
    /* Example: require mandatory field `artist_address` */
#ifndef HOLO_MINT_FACTORY_STUBS
    cJSON *artist = cJSON_GetObjectItem(json, "artist_address");
    if (!artist || artist->type != cJSON_String) {
        LOG_WARN("Validation failed – missing/invalid artist_address");
        return -1;
    }
#endif
    return 0;
}

static artifact_t *compose_artifact(const char *payload, size_t len)
{
    (void)len;
    cJSON *json = cJSON_Parse(payload);
    if (!json) {
        LOG_WARN("Invalid JSON in mint request");
        return NULL;
    }
    if (validate_manifest(json) != 0) {
        cJSON_Delete(json);
        return NULL;
    }

    artifact_t *a = calloc(1, sizeof *a);
    if (!a) {
        LOG_ERROR("Memory allocation failed");
        cJSON_Delete(json);
        return NULL;
    }

    /* Generate deterministic artifact ID (placeholder: hash of payload) */
    unsigned long hash = 5381;
    for (const char *p = payload; *p; ++p) hash = ((hash << 5) + hash) + *p;
    snprintf(a->id, sizeof a->id, "%lx", hash);

    a->state       = ARTIFACT_DRAFT;
    a->manifest    = json;
    a->serialized  = cJSON_PrintUnformatted(json);
    if (!a->serialized) {
        LOG_ERROR("Failed to serialize JSON");
        cJSON_Delete(json);
        free(a);
        return NULL;
    }
    LOG_INFO("Composed artifact %s (state=%s)", a->id, state_str(a->state));
    return a;
}

static void destroy_artifact(artifact_t *a)
{
    if (!a) return;
    cJSON_Delete(a->manifest);
    free(a->serialized);
    free(a);
}

/* ------------------------------------------------------------------------- */
/*                             Worker Thread Pool                            */
/* ------------------------------------------------------------------------- */

typedef struct {
    bqueue_t   *queue;
    config_t   *cfg;
    int         idx;
} worker_arg_t;

static void *worker_loop(void *arg)
{
    worker_arg_t *wa = arg;
    LOG_INFO("Worker-%d online", wa->idx);

    while (!atomic_load(&g_shutdown_flag)) {
        artifact_t *a = bq_pop(wa->queue);
        if (!a) continue;

        /* Simulate on-chain commit latency */
        sleep(1);

        if (ledger_send_mint_tx(a, wa->cfg) == 0) {
            LOG_INFO("Artifact %s minted successfully", a->id);
        } else {
            LOG_WARN("Ledger commit failed for artifact %s", a->id);
        }

        destroy_artifact(a);
    }
    LOG_INFO("Worker-%d shutting down", wa->idx);
    return NULL;
}

/* ------------------------------------------------------------------------- */
/*                             Kafka Consumer Loop                           */
/* ------------------------------------------------------------------------- */

typedef struct {
    rd_kafka_t *kafka;
    bqueue_t   *queue;
    config_t   *cfg;
} consumer_ctx_t;

static void *consumer_loop(void *arg)
{
    consumer_ctx_t *ctx = arg;
    LOG_INFO("Kafka consumer thread started (topic=%s)", ctx->cfg->kafka_topic);

#ifndef HOLO_MINT_FACTORY_STUBS
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    char errstr[256];
    ctx->kafka = rd_kafka_new(RD_KAFKA_CONSUMER, conf, errstr, sizeof errstr);
    if (!ctx->kafka) {
        LOG_ERROR("Failed to create Kafka consumer: %s", errstr);
        atomic_store(&g_shutdown_flag, true);
        return NULL;
    }

    rd_kafka_poll_set_consumer(ctx->kafka);

    rd_kafka_topic_partition_list_t *topics = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, ctx->cfg->kafka_topic, -1);
    if (rd_kafka_subscribe(ctx->kafka, topics) != RD_KAFKA_RESP_ERR_NO_ERROR) {
        LOG_ERROR("Failed to subscribe to topic %s", ctx->cfg->kafka_topic);
        rd_kafka_topic_partition_list_destroy(topics);
        atomic_store(&g_shutdown_flag, true);
        return NULL;
    }
    rd_kafka_topic_partition_list_destroy(topics);
#else
    ctx->kafka = NULL; /* Stub; no real connection */
#endif

    while (!atomic_load(&g_shutdown_flag)) {

#ifndef HOLO_MINT_FACTORY_STUBS
        rd_kafka_message_t *msg = rd_kafka_consumer_poll(ctx->kafka, 500);
        if (!msg) { continue; }
        if (msg->err) {
            LOG_WARN("Kafka error: %s", rd_kafka_message_errstr(msg));
            rd_kafka_message_destroy(msg);
            continue;
        }
        /* Process good message */
        artifact_t *a = compose_artifact((char *)msg->payload, msg->len);
        rd_kafka_message_destroy(msg);
#else
        /* Stub: generate fake message every 2 seconds */
        sleep(2);
        const char *fake = "{\"artist_address\":\"0xDEADBEEF\",\"layers\":[\"shader1\",\"audio1\"]}";
        artifact_t *a = compose_artifact(fake, strlen(fake));
#endif
        if (a) bq_push(ctx->queue, a);
    }

#ifndef HOLO_MINT_FACTORY_STUBS
    rd_kafka_consumer_close(ctx->kafka);
    rd_kafka_destroy(ctx->kafka);
#endif
    LOG_INFO("Kafka consumer thread exiting");
    return NULL;
}

/* ------------------------------------------------------------------------- */
/*                             Signal Management                             */
/* ------------------------------------------------------------------------- */

static void signal_handler(int signum)
{
    (void)signum;
    atomic_store(&g_shutdown_flag, true);
}

static void setup_signals(void)
{
    struct sigaction sa;
    sa.sa_handler = signal_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/* ------------------------------------------------------------------------- */
/*                                   Main                                    */
/* ------------------------------------------------------------------------- */

int main(void)
{
    LOG_INFO("Starting %s v%s", SERVICE_NAME, VERSION_STRING);

    setup_signals();

    config_t cfg;
    load_config(&cfg);
    LOG_INFO("Config: Kafka[%s/%s] Ledger[%s] Workers[%d]",
             cfg.kafka_broker, cfg.kafka_topic,
             cfg.ledger_endpoint, cfg.workers);

    bqueue_t queue;
    bq_init(&queue);

    /* Spawn workers */
    pthread_t workers[MAX_WORKERS];
    worker_arg_t warg[MAX_WORKERS];
    for (int i = 0; i < cfg.workers; ++i) {
        warg[i].queue = &queue;
        warg[i].cfg   = &cfg;
        warg[i].idx   = i;
        if (pthread_create(&workers[i], NULL, worker_loop, &warg[i]) != 0) {
            LOG_ERROR("Failed to create worker thread");
            atomic_store(&g_shutdown_flag, true);
            break;
        }
    }

    /* Start consumer */
    pthread_t consumer;
    consumer_ctx_t cctx = { .kafka = NULL, .queue = &queue, .cfg = &cfg };
    if (pthread_create(&consumer, NULL, consumer_loop, &cctx) != 0) {
        LOG_ERROR("Failed to create Kafka consumer thread");
        atomic_store(&g_shutdown_flag, true);
    }

    /* Wait for shutdown signal */
    while (!atomic_load(&g_shutdown_flag)) {
        sleep(1);
    }

    LOG_INFO("Shutdown requested – waiting for threads");

    /* Wake queues and join threads */
    pthread_mutex_lock(&queue.mtx);
    pthread_cond_broadcast(&queue.not_empty);
    pthread_cond_broadcast(&queue.not_full);
    pthread_mutex_unlock(&queue.mtx);

    pthread_join(consumer, NULL);
    for (int i = 0; i < cfg.workers; ++i) {
        pthread_join(workers[i], NULL);
    }

    LOG_INFO("%s terminated gracefully", SERVICE_NAME);
    return 0;
}
/* End of file */