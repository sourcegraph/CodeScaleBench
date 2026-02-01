```c
/**
 * HoloCanvas Cryptograph Service – main.c
 *
 *  Project: HoloCanvas – A Micro-Gallery Blockchain for Generative Artifacts
 *  Service: Cryptograph
 *  Purpose: Provides cryptographic primitives (hashing, signing, verification)
 *           and event-driven message handling for the HoloCanvas platform.
 *
 *  Build:
 *      gcc -Wall -Wextra -pedantic -O2 \
 *          main.c -o cryptograph \
 *          -lssl -lcrypto -lrdkafka -pthread
 *
 *  Runtime:
 *      env KAFKA_BROKERS="localhost:9092" \
 *          KAFKA_TOPIC="cryptograph-events" \
 *          PRIVATE_KEY="./secrets/crypto_key.pem" \
 *          ./cryptograph
 */

#define _POSIX_C_SOURCE 200809L

#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/sha.h>
#include <openssl/err.h>

#include <librdkafka/rdkafka.h>

#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* --------------------------------------------------------------------------
 *  Utility macros / constants
 * -------------------------------------------------------------------------- */

#define APP_NAME        "cryptograph"
#define LOG_BUFFER_SZ   1024
#define HEX_BUFFER_SZ   4096

#define UNUSED(x)       (void)(x)

/* --------------------------------------------------------------------------
 *  Global shutdown flag (set by signal handler)
 * -------------------------------------------------------------------------- */
static volatile sig_atomic_t g_shutdown_requested = 0;

/* --------------------------------------------------------------------------
 *  Simple logger – prints RFC-3339 timestamps and level prefixes
 * -------------------------------------------------------------------------- */
typedef enum {
    LOG_DBG,
    LOG_INFO,
    LOG_WARN,
    LOG_ERR
} log_level_t;

static void log_message(log_level_t lvl, const char *fmt, ...)
{
    static const char *level_str[] = { "DBG", "INF", "WRN", "ERR" };
    char ts[32];
    time_t now = time(NULL);
    struct tm tm_now;

    gmtime_r(&now, &tm_now);
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &tm_now);

    char buf[LOG_BUFFER_SZ];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    fprintf((lvl == LOG_ERR) ? stderr : stdout,
            "%s [%s] %s: %s\n", ts, level_str[lvl], APP_NAME, buf);
}

/* --------------------------------------------------------------------------
 *  Environment-based configuration
 * -------------------------------------------------------------------------- */
typedef struct {
    const char *kafka_brokers;
    const char *kafka_topic;
    const char *private_key_path;
} service_cfg_t;

static const char *read_env(const char *var, const char *fallback)
{
    const char *val = getenv(var);
    return val ? val : fallback;
}

static service_cfg_t load_config(void)
{
    service_cfg_t cfg;
    cfg.kafka_brokers   = read_env("KAFKA_BROKERS", "localhost:9092");
    cfg.kafka_topic     = read_env("KAFKA_TOPIC",   "cryptograph-events");
    cfg.private_key_path= read_env("PRIVATE_KEY",   "./crypto_key.pem");
    return cfg;
}

/* --------------------------------------------------------------------------
 *  OpenSSL helpers
 * -------------------------------------------------------------------------- */

/**
 * Initialise OpenSSL libraries (thread-safe where applicable).
 */
static void crypto_init(void)
{
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    /* Prior to 1.1.0 we need to initialise algorithms manually */
    OpenSSL_add_all_algorithms();
    ERR_load_crypto_strings();
#endif
}

/**
 * Release OpenSSL global resources (for completeness).
 */
static void crypto_cleanup(void)
{
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    EVP_cleanup();
    ERR_free_strings();
#endif
}

/**
 * Load an EVP_PKEY (private or public) from PEM file.
 */
static EVP_PKEY *load_pem_key(const char *path, int is_private)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        log_message(LOG_ERR, "Failed to open key '%s'", path);
        return NULL;
    }

    EVP_PKEY *pkey = NULL;
    if (is_private)
        pkey = PEM_read_PrivateKey(fp, NULL, NULL, NULL);
    else
        pkey = PEM_read_PUBKEY(fp, NULL, NULL, NULL);

    fclose(fp);

    if (!pkey) {
        log_message(LOG_ERR, "OpenSSL: %s while reading key '%s'",
                    ERR_error_string(ERR_get_error(), NULL), path);
    }

    return pkey;
}

/**
 * Create SHA-256 digest of the supplied buffer.
 * Digest is written into 'out_digest' (32 bytes).
 */
static int sha256(const unsigned char *data, size_t len,
                  unsigned char out_digest[SHA256_DIGEST_LENGTH])
{
    if (!data || !out_digest) return 0;

    SHA256_CTX ctx;
    if (SHA256_Init(&ctx) != 1) return 0;
    if (SHA256_Update(&ctx, data, len) != 1) return 0;
    if (SHA256_Final(out_digest, &ctx) != 1) return 0;
    return 1;
}

/**
 * Sign arbitrary data buffer with a private key (ECDSA, RSA, etc).
 * Resulting signature is allocated with OPENSSL_malloc().
 */
static int sign_buffer(EVP_PKEY *priv,
                       const unsigned char *data,
                       size_t data_len,
                       unsigned char **sig,
                       size_t *sig_len)
{
    int ret = 0;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) return 0;

    if (EVP_DigestSignInit(ctx, NULL, EVP_sha256(), NULL, priv) != 1)
        goto cleanup;

    if (EVP_DigestSignUpdate(ctx, data, data_len) != 1)
        goto cleanup;

    /* First call with NULL to obtain signature length */
    if (EVP_DigestSignFinal(ctx, NULL, sig_len) != 1)
        goto cleanup;

    *sig = OPENSSL_malloc(*sig_len);
    if (!*sig) goto cleanup;

    if (EVP_DigestSignFinal(ctx, *sig, sig_len) != 1) {
        OPENSSL_free(*sig);
        *sig = NULL;
        goto cleanup;
    }

    ret = 1;

cleanup:
    EVP_MD_CTX_free(ctx);
    return ret;
}

/**
 * Verify previously signed buffer.
 */
static int verify_buffer(EVP_PKEY *pub,
                         const unsigned char *data, size_t data_len,
                         const unsigned char *sig,  size_t sig_len)
{
    int ret = 0;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) return 0;

    if (EVP_DigestVerifyInit(ctx, NULL, EVP_sha256(), NULL, pub) != 1)
        goto cleanup;

    if (EVP_DigestVerifyUpdate(ctx, data, data_len) != 1)
        goto cleanup;

    ret = EVP_DigestVerifyFinal(ctx, sig, sig_len);

cleanup:
    EVP_MD_CTX_free(ctx);
    return ret == 1; /* 1 = success, 0 = fail, negative = error */
}

/**
 * Convert binary to hex string (caller-provided buffer).
 */
static void bin2hex(const unsigned char *src, size_t len, char *dst, size_t dstlen)
{
    static const char hexmap[] = "0123456789abcdef";
    size_t i;

    if (dstlen < (len * 2 + 1)) return;

    for (i = 0; i < len; ++i) {
        dst[i * 2]     = hexmap[(src[i] >> 4) & 0x0F];
        dst[i * 2 + 1] = hexmap[src[i] & 0x0F];
    }
    dst[len * 2] = '\0';
}

/* --------------------------------------------------------------------------
 *  Kafka helpers (librdkafka)
 * -------------------------------------------------------------------------- */

typedef struct {
    rd_kafka_t        *rk;
    rd_kafka_conf_t   *conf;
    rd_kafka_topic_t  *rtopic;
} kafka_ctx_t;

static kafka_ctx_t *kafka_init(const char *brokers, const char *topic)
{
    char errstr[512];

    kafka_ctx_t *kctx = calloc(1, sizeof(*kctx));
    if (!kctx) return NULL;

    kctx->conf = rd_kafka_conf_new();
    if (rd_kafka_conf_set(kctx->conf, "bootstrap.servers", brokers,
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        log_message(LOG_ERR, "Kafka conf error: %s", errstr);
        goto fail;
    }

    kctx->rk = rd_kafka_new(RD_KAFKA_PRODUCER, kctx->conf,
                            errstr, sizeof(errstr));
    if (!kctx->rk) {
        log_message(LOG_ERR, "Kafka new error: %s", errstr);
        goto fail;
    }

    kctx->rtopic = rd_kafka_topic_new(kctx->rk, topic, NULL);
    if (!kctx->rtopic) {
        log_message(LOG_ERR, "Kafka topic error: %s",
                    rd_kafka_err2str(rd_kafka_last_error()));
        goto fail;
    }

    log_message(LOG_INFO, "Kafka producer initialised for '%s' on %s",
                topic, brokers);
    return kctx;

fail:
    if (kctx->rtopic) rd_kafka_topic_destroy(kctx->rtopic);
    if (kctx->rk) rd_kafka_destroy(kctx->rk);
    /* rd_kafka_conf_destroy handled by rd_kafka_destroy */
    free(kctx);
    return NULL;
}

static void kafka_cleanup(kafka_ctx_t *kctx)
{
    if (!kctx) return;

    rd_kafka_flush(kctx->rk, 2000); /* Wait 2s for outstanding messages */
    rd_kafka_topic_destroy(kctx->rtopic);
    rd_kafka_destroy(kctx->rk);
    free(kctx);
}

/**
 * Non-blocking produce. On failure, will log the error.
 */
static void kafka_send(kafka_ctx_t *kctx,
                       const void *payload, size_t len,
                       const char *key)
{
    if (!kctx) return;

    rd_kafka_resp_err_t err =
        rd_kafka_produce(
            kctx->rtopic,
            RD_KAFKA_PARTITION_UA,
            RD_KAFKA_MSG_F_COPY,
            (void *)payload, len,
            key, key ? strlen(key) : 0,
            NULL /* opaque */);

    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        log_message(LOG_ERR, "Kafka produce failed: %s",
                    rd_kafka_err2str(err));
    }
}

/* --------------------------------------------------------------------------
 *  Graceful shutdown handlers
 * -------------------------------------------------------------------------- */
static void handle_sig(int sig)
{
    UNUSED(sig);
    g_shutdown_requested = 1;
}

/* --------------------------------------------------------------------------
 *  Service-specific message struct and (de)serialisers
 * -------------------------------------------------------------------------- */

/*  Very minimal message format for demonstration:
 *      <32-byte SHA-256-HEX>|<signature-hex>
 */
typedef struct {
    uint8_t  digest[SHA256_DIGEST_LENGTH];
    uint8_t *signature;
    size_t   sig_len;
} sign_msg_t;

static char *serialise_message(const sign_msg_t *msg)
{
    if (!msg || !msg->signature) return NULL;

    size_t hex_sig_len = msg->sig_len * 2;
    size_t total_len   = SHA256_DIGEST_LENGTH * 2 + 1 + hex_sig_len + 1;

    char *buf = malloc(total_len);
    if (!buf) return NULL;

    char hex_digest[SHA256_DIGEST_LENGTH * 2 + 1];
    bin2hex(msg->digest, SHA256_DIGEST_LENGTH, hex_digest, sizeof(hex_digest));

    char *cursor = buf;
    memcpy(cursor, hex_digest, strlen(hex_digest));
    cursor += strlen(hex_digest);
    *cursor++ = '|';

    bin2hex(msg->signature, msg->sig_len, cursor, hex_sig_len + 1);
    cursor += hex_sig_len;
    *cursor = '\0';

    return buf;
}

/* --------------------------------------------------------------------------
 *  Main Operational Loop
 * -------------------------------------------------------------------------- */
static int run_service(const service_cfg_t *cfg)
{
    crypto_init();

    /* Load private key for signing */
    EVP_PKEY *pkey = load_pem_key(cfg->private_key_path, 1);
    if (!pkey) {
        crypto_cleanup();
        return EXIT_FAILURE;
    }

    /* Kafka producer setup */
    kafka_ctx_t *kctx = kafka_init(cfg->kafka_brokers, cfg->kafka_topic);
    if (!kctx) {
        EVP_PKEY_free(pkey);
        crypto_cleanup();
        return EXIT_FAILURE;
    }

    /* Register periodic statistics callback (optional) */
    /* rd_kafka_conf_set_log_cb ... */

    log_message(LOG_INFO, "Service started. Awaiting events…");

    /* Simple demo loop: read stdin lines to sign and emit */
    char *line = NULL;
    size_t n = 0;
    ssize_t len;

    while (!g_shutdown_requested &&
           (len = getline(&line, &n, stdin)) != -1)
    {
        /* Remove trailing newline */
        if (len > 0 && line[len-1] == '\n') {
            line[--len] = '\0';
        }

        if (len == 0) continue;

        /* Compute digest */
        unsigned char digest[SHA256_DIGEST_LENGTH];
        if (!sha256((unsigned char *)line, len, digest)) {
            log_message(LOG_ERR, "SHA-256 computation failed");
            continue;
        }

        /* Sign */
        unsigned char *sig = NULL;
        size_t sig_len = 0;
        if (!sign_buffer(pkey, (unsigned char *)line, len, &sig, &sig_len)) {
            log_message(LOG_ERR, "Signing failed");
            continue;
        }

        sign_msg_t smsg = {0};
        memcpy(smsg.digest, digest, sizeof(digest));
        smsg.signature = sig;
        smsg.sig_len   = sig_len;

        char *payload = serialise_message(&smsg);
        OPENSSL_free(sig);

        if (!payload) {
            log_message(LOG_ERR, "Serialisation failed");
            continue;
        }

        kafka_send(kctx, payload, strlen(payload), NULL);
        log_message(LOG_INFO, "Produced signed message (len=%zu)", strlen(payload));
        free(payload);

        /* Poll for delivery reports etc. */
        rd_kafka_poll(kctx->rk, 0 /* non-blocking */);
    }

    free(line);

    kafka_cleanup(kctx);
    EVP_PKEY_free(pkey);
    crypto_cleanup();

    log_message(LOG_INFO, "Service stopped gracefully");
    return EXIT_SUCCESS;
}

/* --------------------------------------------------------------------------
 *  Entry point
 * -------------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    UNUSED(argc);
    UNUSED(argv);

    /* Capture SIGINT / SIGTERM for graceful shutdown */
    struct sigaction sa = {0};
    sa.sa_handler = handle_sig;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    service_cfg_t cfg = load_config();

    log_message(LOG_INFO, "Configuration: brokers=%s, topic=%s, key=%s",
                cfg.kafka_brokers, cfg.kafka_topic, cfg.private_key_path);

    return run_service(&cfg);
}
```