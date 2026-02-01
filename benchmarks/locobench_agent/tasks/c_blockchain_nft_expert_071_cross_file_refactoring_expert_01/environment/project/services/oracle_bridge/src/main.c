/*
 * HoloCanvas – Oracle-Bridge Service
 *
 * File: services/oracle_bridge/src/main.c
 * Description:
 *   Periodically queries an external HTTP-based oracle, signs the payload
 *   with an on-disk private key, and publishes the resulting event to Kafka
 *   so that downstream micro-services (e.g. LedgerCore, Governance-Hall)
 *   can deterministically evolve NFTs in response to off-chain stimuli.
 *
 * Build flags (example):
 *   cc -Wall -Wextra -pedantic -std=c11 -O2 \
 *      main.c -o oracle_bridge \
 *      -lcurl -lrdkafka -lssl -lcrypto -lpthread
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>
#include <pthread.h>

/* External libs */
#include <curl/curl.h>
#include <librdkafka/rdkafka.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/err.h>
#include <openssl/bio.h>

#define ARRAY_LEN(x) (sizeof(x) / sizeof((x)[0]))

/* ---------- Logging helpers ------------------------------------------------*/
#define LOG_TAG "[oracle_bridge]"
#define LOG_COLOR_RESET  "\033[0m"
#define LOG_COLOR_GREEN  "\033[32m"
#define LOG_COLOR_RED    "\033[31m"

#define LOG_INFO(fmt, ...)  fprintf(stdout, LOG_COLOR_GREEN LOG_TAG " [INFO]  " fmt LOG_COLOR_RESET "\n", ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...) fprintf(stderr, LOG_COLOR_RED  LOG_TAG " [ERROR] " fmt LOG_COLOR_RESET "\n", ##__VA_ARGS__)

/* ---------- Global termination flag for signal handler ---------------------*/
static volatile sig_atomic_t g_running = 1;

/* ---------- Data structures ------------------------------------------------*/
typedef struct {
    char     kafka_brokers[256];
    char     kafka_topic[128];
    char     oracle_endpoint[256];
    char     oracle_api_key[128];
    char     signer_key_path[256];
    unsigned fetch_interval_secs;
} app_config_t;

typedef struct {
    app_config_t   cfg;
    rd_kafka_t    *producer;
    rd_kafka_topic_t *topic;
    EVP_PKEY      *pkey;
    pthread_mutex_t lock;     /* protects libssl in multithreaded env */
} app_ctx_t;

/* ---------- Forward declarations ------------------------------------------*/
static int  load_config(const char *path, app_config_t *out_cfg);
static int  kafka_init(app_ctx_t *ctx);
static int  crypto_init(app_ctx_t *ctx);
static int  fetch_oracle_payload(const app_ctx_t *ctx, char **out_buf, size_t *out_len);
static int  sign_payload(app_ctx_t *ctx, const unsigned char *data, size_t data_len,
                         unsigned char **sig_b64, size_t *sig_b64_len);
static int  kafka_publish(app_ctx_t *ctx,
                          const char *oracle_json, size_t oracle_len,
                          const char *sig_b64, size_t sig_b64_len);

static void sig_handler(int signo);

/* ---------- Utility: trim --------------------------------------------------*/
static char *ltrim(char *s)
{
    while (*s && (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r'))
        ++s;
    return s;
}
static void rtrim(char *s)
{
    for (char *e = s + strlen(s) - 1; e >= s; --e) {
        if (*e == ' ' || *e == '\t' || *e == '\n' || *e == '\r')
            *e = '\0';
        else
            break;
    }
}

/* ---------- Config loader (simple KEY=VALUE text) --------------------------*/
static int load_config(const char *path, app_config_t *out)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        LOG_ERROR("Cannot open config file '%s': %s", path, strerror(errno));
        return -1;
    }

    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        char *trimmed = ltrim(line);
        if (*trimmed == '#' || *trimmed == '\0')
            continue;                       /* comment or blank */

        char *eq = strchr(trimmed, '=');
        if (!eq)
            continue;                       /* malformed line */

        *eq = '\0';
        char *key = trimmed;
        char *val = ltrim(eq + 1);
        rtrim(val);

        if (strcmp(key, "KAFKA_BROKERS") == 0)
            strncpy(out->kafka_brokers, val, sizeof(out->kafka_brokers)-1);
        else if (strcmp(key, "KAFKA_TOPIC") == 0)
            strncpy(out->kafka_topic, val, sizeof(out->kafka_topic)-1);
        else if (strcmp(key, "ORACLE_ENDPOINT") == 0)
            strncpy(out->oracle_endpoint, val, sizeof(out->oracle_endpoint)-1);
        else if (strcmp(key, "ORACLE_API_KEY") == 0)
            strncpy(out->oracle_api_key, val, sizeof(out->oracle_api_key)-1);
        else if (strcmp(key, "SIGNER_KEY_PATH") == 0)
            strncpy(out->signer_key_path, val, sizeof(out->signer_key_path)-1);
        else if (strcmp(key, "FETCH_INTERVAL_SECS") == 0)
            out->fetch_interval_secs = (unsigned)strtoul(val, NULL, 10);
        else
            LOG_INFO("Unknown config key '%s' ignored", key);
    }

    fclose(fp);

    /* minimal validation */
    if (out->kafka_brokers[0] == '\0' ||
        out->kafka_topic[0]   == '\0' ||
        out->oracle_endpoint[0] == '\0' ||
        out->signer_key_path[0] == '\0' ||
        out->fetch_interval_secs == 0) {
        LOG_ERROR("Missing required configuration fields");
        return -1;
    }

    return 0;
}

/* ---------- Kafka delivery report callback --------------------------------*/
static void kafka_dr_cb(rd_kafka_t *rk, const rd_kafka_message_t *rkmessage, void *opaque)
{
    (void)rk;
    (void)opaque;

    if (rkmessage->err)
        LOG_ERROR("Message delivery failed: %s", rd_kafka_err2str(rkmessage->err));
}

/* ---------- Kafka init -----------------------------------------------------*/
static int kafka_init(app_ctx_t *ctx)
{
    char errstr[512];

    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    rd_kafka_conf_set_dr_msg_cb(conf, kafka_dr_cb);

    if (rd_kafka_conf_set(conf, "bootstrap.servers", ctx->cfg.kafka_brokers,
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        LOG_ERROR("Kafka conf error: %s", errstr);
        return -1;
    }

    ctx->producer = rd_kafka_new(RD_KAFKA_PRODUCER, conf,
                                 errstr, sizeof(errstr));
    if (!ctx->producer) {
        LOG_ERROR("Failed to create Kafka producer: %s", errstr);
        rd_kafka_conf_destroy(conf);
        return -1;
    }

    ctx->topic = rd_kafka_topic_new(ctx->producer, ctx->cfg.kafka_topic, NULL);
    if (!ctx->topic) {
        LOG_ERROR("Failed to create topic '%s': %s",
                  ctx->cfg.kafka_topic,
                  rd_kafka_err2str(rd_kafka_last_error()));
        rd_kafka_destroy(ctx->producer);
        return -1;
    }
    return 0;
}

/* ---------- OpenSSL base64 helper -----------------------------------------*/
static int base64_encode(const unsigned char *in, size_t in_len,
                         char **out, size_t *out_len)
{
    BIO *b64 = BIO_new(BIO_f_base64());
    if (!b64) return -1;
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);

    BIO *mem = BIO_new(BIO_s_mem());
    if (!mem) { BIO_free(b64); return -1; }

    BIO_push(b64, mem);
    if (BIO_write(b64, in, (int)in_len) <= 0) {
        BIO_free_all(b64); return -1;
    }
    if (BIO_flush(b64) != 1) {
        BIO_free_all(b64); return -1;
    }

    BUF_MEM *bptr;
    BIO_get_mem_ptr(b64, &bptr);

    *out = malloc(bptr->length + 1);
    if (!*out) { BIO_free_all(b64); return -1; }
    memcpy(*out, bptr->data, bptr->length);
    (*out)[bptr->length] = '\0';
    *out_len = bptr->length;

    BIO_free_all(b64);
    return 0;
}

/* ---------- Crypto init (load key) ----------------------------------------*/
static int crypto_init(app_ctx_t *ctx)
{
    FILE *fp = fopen(ctx->cfg.signer_key_path, "r");
    if (!fp) {
        LOG_ERROR("Cannot open signer key '%s': %s",
                  ctx->cfg.signer_key_path, strerror(errno));
        return -1;
    }

    ctx->pkey = PEM_read_PrivateKey(fp, NULL, NULL, NULL);
    fclose(fp);

    if (!ctx->pkey) {
        LOG_ERROR("Failed to read private key (OpenSSL err: %s)",
                  ERR_error_string(ERR_get_error(), NULL));
        return -1;
    }

    /* OpenSSL/thread safety: Initialize mutex callbacks if not already done
       (OpenSSL 1.1+ is thread-safe by default). We still keep a local mutex
       to serialize EVP calls inside this process. */
    pthread_mutex_init(&ctx->lock, NULL);
    return 0;
}

/* ---------- Sign payload ---------------------------------------------------*/
static int sign_payload(app_ctx_t *ctx, const unsigned char *data, size_t data_len,
                        unsigned char **sig_b64, size_t *sig_b64_len)
{
    int ret = -1;
    EVP_MD_CTX *md_ctx = EVP_MD_CTX_new();
    if (!md_ctx) {
        LOG_ERROR("EVP_MD_CTX_new failed");
        return -1;
    }

    pthread_mutex_lock(&ctx->lock);

    if (EVP_DigestSignInit(md_ctx, NULL, EVP_sha256(), NULL, ctx->pkey) != 1) {
        LOG_ERROR("DigestSignInit failed");
        goto cleanup;
    }

    if (EVP_DigestSignUpdate(md_ctx, data, data_len) != 1) {
        LOG_ERROR("DigestSignUpdate failed");
        goto cleanup;
    }

    size_t sig_len = 0;
    if (EVP_DigestSignFinal(md_ctx, NULL, &sig_len) != 1) {
        LOG_ERROR("DigestSignFinal (size) failed");
        goto cleanup;
    }

    unsigned char *sig = malloc(sig_len);
    if (!sig) {
        LOG_ERROR("Out of memory allocating signature");
        goto cleanup;
    }

    if (EVP_DigestSignFinal(md_ctx, sig, &sig_len) != 1) {
        LOG_ERROR("DigestSignFinal (sign) failed");
        free(sig);
        goto cleanup;
    }

    pthread_mutex_unlock(&ctx->lock);

    /* Base64 encode */
    if (base64_encode(sig, sig_len, (char **)sig_b64, sig_b64_len) == 0)
        ret = 0;

    free(sig);
    EVP_MD_CTX_free(md_ctx);
    return ret;

cleanup:
    pthread_mutex_unlock(&ctx->lock);
    EVP_MD_CTX_free(md_ctx);
    return -1;
}

/* ---------- CURL write callback -------------------------------------------*/
typedef struct {
    char  *buf;
    size_t size;
} dynbuf_t;

static size_t curl_write_cb(void *contents, size_t size, size_t nmemb, void *userp)
{
    size_t realsz = size * nmemb;
    dynbuf_t *mem = (dynbuf_t *)userp;

    char *ptr = realloc(mem->buf, mem->size + realsz + 1);
    if (!ptr) {
        LOG_ERROR("Out of memory in CURL callback");
        return 0; /* will abort transfer */
    }

    mem->buf = ptr;
    memcpy(&(mem->buf[mem->size]), contents, realsz);
    mem->size += realsz;
    mem->buf[mem->size] = '\0';
    return realsz;
}

/* ---------- Fetch oracle payload ------------------------------------------*/
static int fetch_oracle_payload(const app_ctx_t *ctx, char **out_buf, size_t *out_len)
{
    CURL *curl = curl_easy_init();
    if (!curl) {
        LOG_ERROR("curl_easy_init failed");
        return -1;
    }

    dynbuf_t d = { .buf = NULL, .size = 0 };

    char url[512];
    snprintf(url, sizeof(url), "%s?key=%s",
             ctx->cfg.oracle_endpoint, ctx->cfg.oracle_api_key);

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&d);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        LOG_ERROR("curl_easy_perform failed: %s", curl_easy_strerror(res));
        curl_easy_cleanup(curl);
        free(d.buf);
        return -1;
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    if (http_code != 200) {
        LOG_ERROR("Oracle responded with HTTP %ld", http_code);
        curl_easy_cleanup(curl);
        free(d.buf);
        return -1;
    }

    curl_easy_cleanup(curl);

    *out_buf = d.buf;
    *out_len = d.size;
    return 0;
}

/* ---------- Kafka publish --------------------------------------------------*/
static int kafka_publish(app_ctx_t *ctx,
                         const char *oracle_json, size_t oracle_len,
                         const char *sig_b64, size_t sig_b64_len)
{
    /* Compose message payload: small JSON wrapper */
    char ts_str[32];
    time_t now = time(NULL);
    snprintf(ts_str, sizeof(ts_str), "%ld", (long)now);

    size_t msg_cap = oracle_len + sig_b64_len + 128;
    char *msg = malloc(msg_cap);
    if (!msg) {
        LOG_ERROR("Unable to allocate message buffer");
        return -1;
    }

    int n = snprintf(msg, msg_cap,
                     "{\"timestamp\":%s, \"payload\":%.*s, \"signature\":\"%.*s\"}",
                     ts_str,
                     (int)oracle_len, oracle_json,
                     (int)sig_b64_len, sig_b64);
    if (n < 0 || (size_t)n >= msg_cap) {
        LOG_ERROR("Message serialization truncated");
        free(msg);
        return -1;
    }

    rd_kafka_resp_err_t err = rd_kafka_produce(
        ctx->topic,
        RD_KAFKA_PARTITION_UA,
        RD_KAFKA_MSG_F_COPY,
        msg, (size_t)n,
        NULL, 0,
        NULL);

    free(msg);

    if (err) {
        LOG_ERROR("kafka_produce failed: %s", rd_kafka_err2str(err));
        return -1;
    }

    rd_kafka_poll(ctx->producer, 0); /* serve delivery reports */
    return 0;
}

/* ---------- Signal handler -------------------------------------------------*/
static void sig_handler(int signo)
{
    if (signo == SIGINT || signo == SIGTERM) {
        g_running = 0;
    }
}

/* ---------- Main worker loop ----------------------------------------------*/
static int run_event_loop(app_ctx_t *ctx)
{
    while (g_running) {
        char *oracle_json = NULL;
        size_t oracle_len = 0;

        if (fetch_oracle_payload(ctx, &oracle_json, &oracle_len) == 0) {
            unsigned char *sig_b64 = NULL;
            size_t sig_b64_len = 0;

            if (sign_payload(ctx,
                             (unsigned char *)oracle_json, oracle_len,
                             &sig_b64, &sig_b64_len) == 0) {
                kafka_publish(ctx,
                              oracle_json, oracle_len,
                              (char *)sig_b64, sig_b64_len);
            }

            free(sig_b64);
        }

        free(oracle_json);

        /* Sleep with early exit support */
        for (unsigned i = 0; i < ctx->cfg.fetch_interval_secs && g_running; ++i)
            sleep(1);
    }

    return 0;
}

/* ---------- Resource cleanup ----------------------------------------------*/
static void cleanup(app_ctx_t *ctx)
{
    if (ctx->topic)
        rd_kafka_topic_destroy(ctx->topic);

    if (ctx->producer) {
        rd_kafka_flush(ctx->producer, 5000 /*ms*/);
        rd_kafka_destroy(ctx->producer);
    }

    if (ctx->pkey)
        EVP_PKEY_free(ctx->pkey);

    curl_global_cleanup();
    rd_kafka_wait_destroyed(2000);
    pthread_mutex_destroy(&ctx->lock);
}

/* ---------- Entry-point ----------------------------------------------------*/
int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <config.cfg>\n", argv[0]);
        return EXIT_FAILURE;
    }

    app_ctx_t ctx = {0};

    if (load_config(argv[1], &ctx.cfg) != 0)
        return EXIT_FAILURE;

    /* Hook signals for graceful shutdown */
    struct sigaction sa = { .sa_handler = sig_handler };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* Initialize libraries */
    curl_global_init(CURL_GLOBAL_DEFAULT);
    ERR_load_crypto_strings();
    OpenSSL_add_all_algorithms();

    if (kafka_init(&ctx) != 0)
        goto err;
    if (crypto_init(&ctx) != 0)
        goto err;

    LOG_INFO("Oracle-Bridge started: polling '%s' every %u sec, publishing to topic '%s'",
             ctx.cfg.oracle_endpoint, ctx.cfg.fetch_interval_secs, ctx.cfg.kafka_topic);

    run_event_loop(&ctx);

    LOG_INFO("Shutting down...");
    cleanup(&ctx);
    LOG_INFO("Bye.");
    return EXIT_SUCCESS;

err:
    cleanup(&ctx);
    return EXIT_FAILURE;
}