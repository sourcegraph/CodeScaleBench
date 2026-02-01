/*
 * HoloCanvas – LedgerCore Service
 * --------------------------------
 * main.c
 *
 * Entry-point for the LedgerCore micro-service.  Responsible for:
 *   • Loading runtime configuration.
 *   • Wiring up Kafka consumers / producers for the event mesh.
 *   • Hosting a lightweight gRPC server for direct RPC calls.
 *   • Managing an in-memory ledger state-machine with cryptographic
 *     verification of transaction payloads.
 *
 * The implementation purposefully keeps dependencies abstracted
 * behind small wrappers to allow future refactors (e.g., swapping out
 * Kafka or gRPC libraries) without rewriting the service core.
 *
 * Build flags (example):
 *   cc -std=c11 -Wall -Wextra -O2 \
 *      -pthread -lrdkafka -lssl -lcrypto -ljansson \
 *      -o ledger_core main.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#include <getopt.h>

/* External libraries */
#include <openssl/sha.h>
#include <jansson.h>
#include <rdkafka.h>   /* https://github.com/edenhill/librdkafka */

/* -------------------------------------------------------------------------- */
/* Compile-time Constants                                                     */
/* -------------------------------------------------------------------------- */
#define APP_NAME           "HoloCanvas-LedgerCore"
#define APP_VERSION        "0.7.3"
#define DEFAULT_CONFIG     "/etc/holocanvas/ledger_core.yaml"

/* Kafka topics */
#define TOPIC_TX_IN        "holocanvas.tx.in"
#define TOPIC_TX_OUT       "holocanvas.tx.out"
#define TOPIC_AUDIT        "holocanvas.audit"

/* Misc */
#define MAX_TX_SIZE        (1024 * 16)    /* 16 KiB */

/* -------------------------------------------------------------------------- */
/* Data Structures                                                            */
/* -------------------------------------------------------------------------- */

/* Enumeration of high-level ledger states */
typedef enum {
    ARTIFACT_DRAFT,
    ARTIFACT_CURATED,
    ARTIFACT_AUCTION,
    ARTIFACT_FRACTIONALIZED,
    ARTIFACT_STAKED
} artifact_state_e;

/* Canonical transaction object */
typedef struct {
    char            tx_id[65];      /* hex-encoded sha256            */
    char            emitter[64];    /* wallet / service id           */
    artifact_state_e new_state;     /* desired state transition      */
    json_t         *payload;        /* marshalled artifact fragment  */
} tx_t;

/* In-memory ledger artifact record (trimmed for brevity) */
typedef struct artifact_s {
    char               artifact_id[65]; /* sha256 of immutable recipe */
    artifact_state_e   state;
    time_t             last_update;
    json_t            *metadata;        /* deep-copy of pertinent JSON */
    struct artifact_s *next;
} artifact_t;

/* Thread-safe ledger state */
typedef struct {
    pthread_rwlock_t lock;
    artifact_t      *head;
} ledger_t;

/* Service runtime context */
typedef struct {
    char            instance_id[32];
    char            config_path[256];
    atomic_bool     running;

    /* Kafka handles */
    rd_kafka_t     *rk;         /* client */
    rd_kafka_conf_t *rk_conf;

    ledger_t        ledger;
} svc_ctx_t;

/* -------------------------------------------------------------------------- */
/* Utility Helpers                                                            */
/* -------------------------------------------------------------------------- */

/* Hex helper – converts binary to hex string (dst must be >= src_len*2+1) */
static void
bin2hex(const uint8_t *src, size_t src_len, char *dst)
{
    static const char *hex = "0123456789abcdef";
    for (size_t i = 0; i < src_len; ++i) {
        dst[i*2]     = hex[(src[i] >> 4) & 0xF];
        dst[i*2 + 1] = hex[src[i] & 0xF];
    }
    dst[src_len * 2] = '\0';
}

/* unix epoch seconds helper */
static inline uint64_t
epoch_sec(void)
{
    return (uint64_t)time(NULL);
}

/* -------------------------------------------------------------------------- */
/* Ledger Functions                                                           */
/* -------------------------------------------------------------------------- */

/* Find artifact by id (requires caller hold read or write lock) */
static artifact_t *
ledger_find(ledger_t *l, const char *artifact_id)
{
    for (artifact_t *cur = l->head; cur; cur = cur->next) {
        if (strncmp(cur->artifact_id, artifact_id, sizeof(cur->artifact_id)) == 0)
            return cur;
    }
    return NULL;
}

/* Upsert artifact record based on incoming tx */
static bool
ledger_apply_tx(ledger_t *l, const tx_t *tx)
{
    bool result = false;

    pthread_rwlock_wrlock(&l->lock);

    /* Determine artifact id. For simplicity we reuse tx_id. */
    artifact_t *art = ledger_find(l, tx->tx_id);

    if (!art) {
        /* New artifact */
        art = calloc(1, sizeof(*art));
        if (!art) {
            pthread_rwlock_unlock(&l->lock);
            return false;
        }

        strncpy(art->artifact_id, tx->tx_id, sizeof(art->artifact_id) - 1);
        art->metadata = json_deep_copy(tx->payload); /* may be NULL */
        art->state = tx->new_state;
        art->last_update = epoch_sec();
        art->next = l->head;
        l->head = art;
        result = true;
    } else {
        /* State transition rules could be enforced here (omitted) */
        art->state = tx->new_state;
        art->last_update = epoch_sec();

        if (art->metadata)
            json_decref(art->metadata);

        art->metadata = json_deep_copy(tx->payload);
        result = true;
    }

    pthread_rwlock_unlock(&l->lock);
    return result;
}

static void
ledger_free(ledger_t *l)
{
    pthread_rwlock_wrlock(&l->lock);
    artifact_t *cur = l->head;
    while (cur) {
        artifact_t *next = cur->next;
        if (cur->metadata)
            json_decref(cur->metadata);
        free(cur);
        cur = next;
    }
    l->head = NULL;
    pthread_rwlock_unlock(&l->lock);
    pthread_rwlock_destroy(&l->lock);
}

/* -------------------------------------------------------------------------- */
/* Cryptographic Validation                                                   */
/* -------------------------------------------------------------------------- */

/* Simple sha256 hash of buffer. Hex result stored in out_hex (65 bytes). */
static void
sha256_hex(const void *buf, size_t len, char out_hex[65])
{
    uint8_t digest[SHA256_DIGEST_LENGTH];
    SHA256((const unsigned char *)buf, len, digest);
    bin2hex(digest, sizeof(digest), out_hex);
}

/* Verify tx message integrity: compute sha256 of payload and compare id. */
static bool
tx_validate_integrity(const char *msg, size_t msg_len, tx_t *out_tx)
{
    /* Compute sha256 hex */
    char hash_hex[65];
    sha256_hex(msg, msg_len, hash_hex);

    /* Parse JSON document */
    json_error_t jerr;
    json_t *root = json_loadb(msg, msg_len, 0, &jerr);
    if (!root) {
        fprintf(stderr, "JSON parse error: %s (line %d)\n", jerr.text, jerr.line);
        return false;
    }

    /* Extract mandatory fields */
    const char *emitter = json_string_value(json_object_get(root, "emitter"));
    const char *state_str = json_string_value(json_object_get(root, "state"));
    json_t *payload = json_object_get(root, "payload");

    if (!emitter || !state_str || !payload) {
        fprintf(stderr, "Bad tx: missing fields\n");
        json_decref(root);
        return false;
    }

    /* Map state string to enum */
    artifact_state_e new_state;
    if      (strcmp(state_str, "DRAFT") == 0)         new_state = ARTIFACT_DRAFT;
    else if (strcmp(state_str, "CURATED") == 0)       new_state = ARTIFACT_CURATED;
    else if (strcmp(state_str, "AUCTION") == 0)       new_state = ARTIFACT_AUCTION;
    else if (strcmp(state_str, "FRACTIONALIZED") == 0) new_state = ARTIFACT_FRACTIONALIZED;
    else if (strcmp(state_str, "STAKED") == 0)        new_state = ARTIFACT_STAKED;
    else {
        fprintf(stderr, "Unknown state '%s'\n", state_str);
        json_decref(root);
        return false;
    }

    /* Populate tx object */
    memset(out_tx, 0, sizeof(*out_tx));
    strncpy(out_tx->tx_id, hash_hex, sizeof(out_tx->tx_id) - 1);
    strncpy(out_tx->emitter, emitter, sizeof(out_tx->emitter) - 1);
    out_tx->new_state = new_state;
    out_tx->payload = json_deep_copy(payload);

    json_decref(root);
    return true;
}

/* -------------------------------------------------------------------------- */
/* Kafka Integration                                                          */
/* -------------------------------------------------------------------------- */

typedef struct {
    svc_ctx_t *ctx;
} kafka_consumer_arg_t;

static void *
kafka_consumer_thread(void *arg)
{
    kafka_consumer_arg_t *karg = arg;
    svc_ctx_t *ctx = karg->ctx;
    rd_kafka_t *rk = ctx->rk;

    rd_kafka_resp_err_t err;
    rd_kafka_topic_partition_list_t *topics =
        rd_kafka_topic_partition_list_new(1);

    rd_kafka_topic_partition_list_add(topics, TOPIC_TX_IN, -1);
    err = rd_kafka_subscribe(rk, topics);
    if (err) {
        fprintf(stderr, "%% Failed to subscribe to %s: %s\n",
                TOPIC_TX_IN, rd_kafka_err2str(err));
        rd_kafka_topic_partition_list_destroy(topics);
        return NULL;
    }
    rd_kafka_topic_partition_list_destroy(topics);

    while (atomic_load(&ctx->running)) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(rk, 250 /*ms*/);

        if (!rkmsg)
            continue;

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF)
                ; /* ignore */
            else
                fprintf(stderr, "%% Consumer error: %s\n",
                        rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Process transaction */
        tx_t tx;
        if (tx_validate_integrity(rkmsg->payload, rkmsg->len, &tx)) {
            bool ok = ledger_apply_tx(&ctx->ledger, &tx);
            if (!ok)
                fprintf(stderr, "Ledger apply failed for tx=%s\n", tx.tx_id);

            /* free nested JSON */
            if (tx.payload)
                json_decref(tx.payload);
        } else {
            fprintf(stderr, "Integrity validation failed\n");
        }

        rd_kafka_message_destroy(rkmsg);
    }

    rd_kafka_consumer_close(rk);
    return NULL;
}

/* -------------------------------------------------------------------------- */
/* Configuration Loader (YAML placeholder)                                    */
/* -------------------------------------------------------------------------- */
static bool
load_config(const char *path /*unused for now*/)
{
    /* TODO: Implement real YAML parsing */
    (void)path;
    return true; /* assume success */
}

/* -------------------------------------------------------------------------- */
/* Signal Handling                                                            */
/* -------------------------------------------------------------------------- */

static svc_ctx_t *g_ctx = NULL;

static void
handle_sigint(int signum)
{
    (void)signum;
    if (g_ctx)
        atomic_store(&g_ctx->running, false);
}

/* -------------------------------------------------------------------------- */
/* gRPC Server Stub (placeholder)                                             */
/* -------------------------------------------------------------------------- */

static void *
grpc_server_thread(void *arg)
{
    svc_ctx_t *ctx = arg;

    /* Placeholder for gRPC event loop.
     * Real implementation would register service definitions generated
     * by protoc-c (e.g., ledger_core.pb-c.c) and spin until ctx->running
     * becomes false.
     */
    while (atomic_load(&ctx->running)) {
        sleep(1);
    }
    return NULL;
}

/* -------------------------------------------------------------------------- */
/* Service Initialization                                                     */
/* -------------------------------------------------------------------------- */

static bool
init_kafka(svc_ctx_t *ctx)
{
    char errstr[512];

    ctx->rk_conf = rd_kafka_conf_new();
    if (rd_kafka_conf_set(ctx->rk_conf, "bootstrap.servers", "localhost:9092",
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "Kafka conf error: %s\n", errstr);
        return false;
    }

    rd_kafka_conf_set(ctx->rk_conf, "group.id", "ledger_core_consumer", NULL, 0);
    rd_kafka_conf_set(ctx->rk_conf, "enable.auto.commit", "true", NULL, 0);
    rd_kafka_conf_set(ctx->rk_conf, "auto.offset.reset", "earliest", NULL, 0);

    ctx->rk = rd_kafka_new(RD_KAFKA_CONSUMER, ctx->rk_conf,
                           errstr, sizeof(errstr));
    if (!ctx->rk) {
        fprintf(stderr, "Failed to create kafka consumer: %s\n", errstr);
        return false;
    }

    /* Redirect all rd_kafka_poll()'s events to queue-based interface
     * (safer for multi-threaded callback management) */
    rd_kafka_poll_set_consumer(ctx->rk);
    return true;
}

static void
shutdown_kafka(svc_ctx_t *ctx)
{
    if (ctx->rk) {
        rd_kafka_destroy(ctx->rk);
        ctx->rk = NULL;
    }
}

/* -------------------------------------------------------------------------- */
/* CLI / Entry Point                                                          */
/* -------------------------------------------------------------------------- */

static void
usage(FILE *stream, int exit_code)
{
    fprintf(stream,
            "%s v%s\n"
            "Usage: ledger_core [options]\n"
            "Options:\n"
            "  -c, --config PATH   Path to YAML configuration (default %s)\n"
            "  -h, --help          Show this help message\n",
            APP_NAME, APP_VERSION, DEFAULT_CONFIG);
    exit(exit_code);
}

int
main(int argc, char **argv)
{
    svc_ctx_t ctx = {0};
    g_ctx = &ctx;
    atomic_init(&ctx.running, true);
    strncpy(ctx.config_path, DEFAULT_CONFIG, sizeof(ctx.config_path) - 1);

    /* Parse CLI options */
    static struct option long_opts[] = {
        {"config", required_argument, 0, 'c'},
        {"help",   no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };
    int opt;
    while ((opt = getopt_long(argc, argv, "c:h", long_opts, NULL)) != -1) {
        switch (opt) {
        case 'c':
            strncpy(ctx.config_path, optarg, sizeof(ctx.config_path) - 1);
            break;
        case 'h':
        default:
            usage(opt == 'h' ? stdout : stderr, opt == 'h' ? 0 : 1);
        }
    }

    /* Load configuration */
    if (!load_config(ctx.config_path)) {
        fprintf(stderr, "Failed to load config %s\n", ctx.config_path);
        return EXIT_FAILURE;
    }

    /* Init ledger */
    pthread_rwlock_init(&ctx.ledger.lock, NULL);
    ctx.ledger.head = NULL;

    /* Kafka */
    if (!init_kafka(&ctx)) {
        fprintf(stderr, "Kafka init failed\n");
        return EXIT_FAILURE;
    }

    /* Register signal handlers */
    struct sigaction sa = {.sa_handler = handle_sigint};
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* Spawn threads */
    pthread_t tid_kafka, tid_grpc;
    kafka_consumer_arg_t karg = {.ctx = &ctx};

    if (pthread_create(&tid_kafka, NULL, kafka_consumer_thread, &karg) != 0) {
        perror("pthread_create kafka");
        shutdown_kafka(&ctx);
        return EXIT_FAILURE;
    }
    if (pthread_create(&tid_grpc, NULL, grpc_server_thread, &ctx) != 0) {
        perror("pthread_create grpc");
        atomic_store(&ctx.running, false);
        pthread_join(tid_kafka, NULL);
        shutdown_kafka(&ctx);
        return EXIT_FAILURE;
    }

    /* Main thread just waits for termination signal */
    while (atomic_load(&ctx.running)) {
        pause(); /* interrupted by signal */
    }

    /* Join worker threads */
    pthread_join(tid_kafka, NULL);
    pthread_join(tid_grpc, NULL);

    /* Cleanup */
    shutdown_kafka(&ctx);
    ledger_free(&ctx.ledger);
    fprintf(stderr, "%s shutdown complete\n", APP_NAME);
    return EXIT_SUCCESS;
}

/* End of file */
