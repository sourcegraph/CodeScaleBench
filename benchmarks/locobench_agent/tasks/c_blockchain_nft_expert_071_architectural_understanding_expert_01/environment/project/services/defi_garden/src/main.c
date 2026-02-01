/*
 * HoloCanvas :: DeFi-Garden Micro-Service
 * --------------------------------------
 * Entry-point / runtime glue-code
 *
 * Responsibilities
 *  – Bootstrap runtime configuration (CLI flags + environment variables)
 *  – Configure & run a Kafka consumer for on-chain / off-chain events
 *  – Verify message authenticity (ECDSA-secp256k1)
 *  – Dispatch staking / yield-farming instructions via gRPC to Ledger-Core
 *  – Provide graceful shutdown & fault-tolerance guard-rails
 *
 * Build (example):
 *   cc -Wall -Wextra -std=c11 -O2               \
 *      main.c -o defi_garden                    \
 *      -lrdkafka -lssl -lcrypto -lcjson -lpthread
 *
 * Runtime (example):
 *   KAFKA_BROKERS=broker:9092 \
 *   KAFKA_TOPIC=defi.events   \
 *   GRPC_TARGET=ledger-core:50051 \
 *   ./defi_garden --service-id garden-a1
 */
#define _POSIX_C_SOURCE 200809L

#include <assert.h>
#include <errno.h>
#include <getopt.h>
#include <librdkafka/rdkafka.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/sha.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <cjson/cJSON.h>

/* -------------------------------------------------------------------------- */
/* Logging helpers (printf-based; swap w/ syslog or SPDLOG in production)     */
/* -------------------------------------------------------------------------- */
#define LOG_INFO(fmt, ...)  fprintf(stdout, "[INFO]  " fmt "\n", ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  fprintf(stderr, "[WARN]  " fmt "\n", ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...) fprintf(stderr, "[ERROR] " fmt " (%s)\n", ##__VA_ARGS__, strerror(errno))

/* -------------------------------------------------------------------------- */
/* Runtime configuration                                                      */
/* -------------------------------------------------------------------------- */
typedef struct
{
    char *kafka_brokers;      /* Comma-separated list */
    char *kafka_topic;        /* Topic to subscribe to                         */
    char *grpc_target;        /* Ledger-Core rpc endpoint                      */
    char *service_id;         /* Human-friendly id for logging / tracing       */
    long  poll_timeout_ms;    /* Kafka poll timeout                            */
} dg_config_t;

static void dg_config_init(dg_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    cfg->poll_timeout_ms = 1000; /* default 1s */
}

static void dg_config_free(dg_config_t *cfg)
{
    free(cfg->kafka_brokers);
    free(cfg->kafka_topic);
    free(cfg->grpc_target);
    free(cfg->service_id);
}

static void dg_config_load_from_env(dg_config_t *cfg)
{
#define DUP_ENV(to, var, def)                                 \
    do {                                                      \
        const char *val = getenv(var);                        \
        (to) = strdup(val ? val : (def));                     \
    } while (0)

    DUP_ENV(cfg->kafka_brokers, "KAFKA_BROKERS", "localhost:9092");
    DUP_ENV(cfg->kafka_topic,   "KAFKA_TOPIC",   "defi.events");
    DUP_ENV(cfg->grpc_target,   "GRPC_TARGET",   "localhost:50051");
#undef DUP_ENV
}

static void dg_config_parse_cli(dg_config_t *cfg, int argc, char **argv)
{
    static const struct option long_opts[] = {
        {"service-id", required_argument, 0, 's'},
        {"poll-timeout", required_argument, 0, 'p'},
        {0, 0, 0, 0}};
    int ch;
    while ((ch = getopt_long(argc, argv, "s:p:", long_opts, NULL)) != -1) {
        switch (ch) {
        case 's':
            cfg->service_id = strdup(optarg);
            break;
        case 'p':
            cfg->poll_timeout_ms = strtol(optarg, NULL, 10);
            break;
        default:
            fprintf(stderr,
                    "Usage: %s [--service-id id] [--poll-timeout ms]\n",
                    argv[0]);
            exit(EXIT_FAILURE);
        }
    }
    if (!cfg->service_id) cfg->service_id = strdup("defi-garden");
}

/* -------------------------------------------------------------------------- */
/* Cryptographic helpers (ECDSA-secp256k1 over SHA-256)                       */
/* -------------------------------------------------------------------------- */
/* Hex-helpers */
static unsigned char hex_to_byte(char c)
{
    if ('0' <= c && c <= '9') return (unsigned char)(c - '0');
    if ('a' <= c && c <= 'f') return (unsigned char)(c - 'a' + 10);
    if ('A' <= c && c <= 'F') return (unsigned char)(c - 'A' + 10);
    return 0xFF;
}
static int hexstr_to_bin(const char *hex, unsigned char **bin, size_t *binlen)
{
    size_t len = strlen(hex);
    if (len % 2 != 0) return -1;
    *binlen = len / 2;
    *bin    = malloc(*binlen);
    if (!*bin) return -1;
    for (size_t i = 0; i < *binlen; ++i) {
        unsigned char hi = hex_to_byte(hex[2 * i]);
        unsigned char lo = hex_to_byte(hex[2 * i + 1]);
        if (hi == 0xFF || lo == 0xFF) {
            free(*bin);
            return -1;
        }
        (*bin)[i] = (hi << 4) | lo;
    }
    return 0;
}

/* Verify ECDSA signature (hex DER) */
static int verify_signature(const char *payload,
                            const char *sig_hex,
                            const char *pubkey_pem)
{
    int ret              = -1;
    unsigned char hash[32];
    EVP_PKEY *pkey       = NULL;
    EVP_MD_CTX *ctx      = NULL;
    unsigned char *sig   = NULL;
    size_t sig_len       = 0;
    BIO *bio             = NULL;

    /* 1. Hash payload */
    if (!SHA256((const unsigned char *)payload, strlen(payload), hash))
        goto end;

    /* 2. Load public key */
    bio  = BIO_new_mem_buf((void *)pubkey_pem, -1);
    if (!bio) goto end;
    pkey = PEM_read_bio_PUBKEY(bio, NULL, NULL, NULL);
    if (!pkey) goto end;

    /* 3. Decode signature hex */
    if (hexstr_to_bin(sig_hex, &sig, &sig_len) != 0) goto end;

    /* 4. Verify */
    ctx = EVP_MD_CTX_new();
    if (!ctx) goto end;
    if (EVP_DigestVerifyInit(ctx, NULL, EVP_sha256(), NULL, pkey) != 1)
        goto end;
    if (EVP_DigestVerify(ctx, sig, sig_len, hash, sizeof(hash)) == 1) {
        ret = 0; /* success */
    }

end:
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    BIO_free(bio);
    free(sig);
    return ret; /* 0 == OK */
}

/* -------------------------------------------------------------------------- */
/* Kafka consumer                                                             */
/* -------------------------------------------------------------------------- */
typedef struct
{
    rd_kafka_t *rk;
    rd_kafka_conf_t *conf;
    rd_kafka_topic_partition_list_t *sub;
} kafka_consumer_t;

static kafka_consumer_t *kafka_consumer_create(const dg_config_t *cfg)
{
    char errstr[512];
    kafka_consumer_t *kc = calloc(1, sizeof(*kc));
    if (!kc) return NULL;

    kc->conf = rd_kafka_conf_new();
    rd_kafka_conf_set(kc->conf, "group.id", cfg->service_id, NULL, 0);
    rd_kafka_conf_set(kc->conf, "bootstrap.servers", cfg->kafka_brokers, NULL,
                      0);
    rd_kafka_conf_set(kc->conf, "enable.auto.commit", "true", NULL, 0);

    kc->rk = rd_kafka_new(RD_KAFKA_CONSUMER, kc->conf, errstr, sizeof(errstr));
    if (!kc->rk) {
        LOG_ERROR("Failed to create Kafka consumer: %s", errstr);
        goto fail;
    }

    kc->sub = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(kc->sub, cfg->kafka_topic, -1);

    if (rd_kafka_subscribe(kc->rk, kc->sub) != RD_KAFKA_RESP_ERR_NO_ERROR) {
        LOG_ERROR("Failed to subscribe to topic");
        goto fail;
    }

    return kc;
fail:
    if (kc->rk) rd_kafka_destroy(kc->rk);
    rd_kafka_conf_destroy(kc->conf);
    rd_kafka_topic_partition_list_destroy(kc->sub);
    free(kc);
    return NULL;
}

static void kafka_consumer_destroy(kafka_consumer_t *kc)
{
    if (!kc) return;
    rd_kafka_unsubscribe(kc->rk);
    rd_kafka_consumer_close(kc->rk);
    rd_kafka_destroy(kc->rk);
    rd_kafka_topic_partition_list_destroy(kc->sub);
    free(kc);
}

/* -------------------------------------------------------------------------- */
/* gRPC Stub (Ledger-Core)                                                    */
/* In production, use grpc-c / upb / nanopb. Here we stub the interface.      */
/* -------------------------------------------------------------------------- */
static int grpc_send_stake(const char *grpc_target,
                           const char *artifact_id,
                           uint64_t amount,
                           const char *sender)
{
    (void)grpc_target;
    /* TODO: implement actual grpc call */
    LOG_INFO("gRPC [Stub] Stake: artifact=%s amount=%" PRIu64 " from=%s",
             artifact_id, amount, sender);
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Business logic                                                             */
/* -------------------------------------------------------------------------- */
static int process_event_json(const char *json_str, const dg_config_t *cfg)
{
    int rc           = -1;
    cJSON *root      = cJSON_Parse(json_str);
    if (!root) {
        LOG_WARN("Malformed JSON payload");
        return -1;
    }

    const cJSON *action = cJSON_GetObjectItemCaseSensitive(root, "action");
    const cJSON *artifact_id =
        cJSON_GetObjectItemCaseSensitive(root, "artifact_id");
    const cJSON *amount   = cJSON_GetObjectItemCaseSensitive(root, "amount");
    const cJSON *sig      = cJSON_GetObjectItemCaseSensitive(root, "signature");
    const cJSON *pubkey   = cJSON_GetObjectItemCaseSensitive(root, "pubkey");

    if (!cJSON_IsString(action) || !cJSON_IsString(artifact_id) ||
        !cJSON_IsNumber(amount) || !cJSON_IsString(sig) ||
        !cJSON_IsString(pubkey)) {
        LOG_WARN("Missing fields in payload");
        goto cleanup;
    }

    /* Signature verification */
    if (verify_signature(json_str, sig->valuestring, pubkey->valuestring) !=
        0) {
        LOG_WARN("Signature verification failed for artifact %s",
                 artifact_id->valuestring);
        goto cleanup;
    }

    /* Dispatch based on action */
    if (strcmp(action->valuestring, "STAKE") == 0) {
        if (grpc_send_stake(cfg->grpc_target, artifact_id->valuestring,
                            (uint64_t)amount->valuedouble, pubkey->valuestring) ==
            0) {
            rc = 0;
        }
    } else {
        LOG_WARN("Unsupported action: %s", action->valuestring);
    }

cleanup:
    cJSON_Delete(root);
    return rc;
}

/* -------------------------------------------------------------------------- */
/* Signal handling                                                            */
/* -------------------------------------------------------------------------- */
static atomic_bool g_should_stop = ATOMIC_VAR_INIT(false);

static void on_sigint(int sig)
{
    (void)sig;
    atomic_store(&g_should_stop, true);
}

/* -------------------------------------------------------------------------- */
/* Main loop                                                                  */
/* -------------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    dg_config_t cfg;
    dg_config_init(&cfg);
    dg_config_load_from_env(&cfg);
    dg_config_parse_cli(&cfg, argc, argv);

    LOG_INFO("Starting DeFi-Garden (%s)", cfg.service_id);

    /* Signal handlers */
    struct sigaction sa = {.sa_handler = on_sigint};
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* Kafka consumer */
    kafka_consumer_t *kc = kafka_consumer_create(&cfg);
    if (!kc) {
        dg_config_free(&cfg);
        return EXIT_FAILURE;
    }

    while (!atomic_load(&g_should_stop)) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(kc->rk, (int)cfg.poll_timeout_ms);

        if (!rkmsg) continue; /* timeout */

        if (rkmsg->err) {
            LOG_WARN("Kafka error: %s",
                     rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        const char *payload = rkmsg->payload;
        LOG_INFO("Received event (len=%zu)", rkmsg->len);

        process_event_json(payload, &cfg);

        rd_kafka_message_destroy(rkmsg);
    }

    LOG_INFO("Shutting down…");
    kafka_consumer_destroy(kc);
    dg_config_free(&cfg);
    return EXIT_SUCCESS;
}