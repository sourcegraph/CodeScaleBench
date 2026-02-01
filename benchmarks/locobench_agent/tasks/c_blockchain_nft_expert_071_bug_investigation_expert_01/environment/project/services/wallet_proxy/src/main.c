```c
/**
 * HoloCanvas – Wallet-Proxy Service
 * ---------------------------------
 * This micro-service exposes a gRPC façade for end-user wallets while
 * transparently relaying signed transactions to the internal event mesh
 * (Kafka) and LedgerCore.  It also ingests chain events to maintain an
 * in-memory session cache for fast UX round-trips.
 *
 * Author  : HoloCanvas Core Team
 * License : Apache-2.0
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <pthread.h>
#include <unistd.h>
#include <syslog.h>
#include <sys/stat.h>

#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>

#include <rdkafka.h>          /* librdkafka */
#include <grpc/grpc.h>        /* gRPC C core */
#include <grpc/grpc_security.h>

#include "cJSON.h"            /* single-file JSON parser – add to include path */

/* ---------- Compile-time defaults ---------- */

#define HC_SERVICE_NAME           "wallet_proxy"
#define HC_VERSION                "1.4.2"
#define HC_DEFAULT_CFG_FILE       "/etc/holocanvas/wallet_proxy.json"
#define HC_KAFKA_PRODUCER_QUEUE   16384
#define HC_MAX_TOPICS             16
#define HC_GRPC_MAX_THREADS       8

/* ---------- Logging helpers ---------- */

#define LOG_EMERG(fmt, ...)   syslog(LOG_EMERG,  "[%s] " fmt, HC_SERVICE_NAME, ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...)   syslog(LOG_ERR,    "[%s] " fmt, HC_SERVICE_NAME, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)    syslog(LOG_WARNING,"[%s] " fmt, HC_SERVICE_NAME, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)    syslog(LOG_INFO,   "[%s] " fmt, HC_SERVICE_NAME, ##__VA_ARGS__)
#define LOG_DEBUG(fmt, ...)   syslog(LOG_DEBUG,  "[%s] " fmt, HC_SERVICE_NAME, ##__VA_ARGS__)

/* ---------- Data structures ---------- */

typedef struct {
    char    *brokers;
    char    *wallet_topic_out;      /* Produced transactions */
    char    *wallet_topic_in;       /* Observed chain events */
    char    *grpc_bind_addr;        /* gRPC listen */
    char    *keystore_path;         /* PEM bundle */
    char    *keystore_pass;         /* Password for PEM (optional) */
    int      log_level;             /* syslog level */
    int      kafka_ack;             /* Kafka acks config */
} hc_app_cfg_t;

typedef struct {
    rd_kafka_t      *producer;
    rd_kafka_t      *consumer;
    rd_kafka_topic_t*topic_out;
    rd_kafka_topic_t*topic_in;
} hc_kafka_ctx_t;

/* ---------- Globals ---------- */

static atomic_bool g_running = ATOMIC_VAR_INIT(true);
static hc_app_cfg_t g_cfg   = {0};
static hc_kafka_ctx_t g_kafka = {0};
static grpc_server *g_grpc_server = NULL;

/* ---------- Forward declarations ---------- */

static bool load_cfg_file(const char *path, hc_app_cfg_t *out);
static bool init_kafka(const hc_app_cfg_t *cfg, hc_kafka_ctx_t *ctx);
static void *kafka_consume_thread(void *arg);
static void kafka_cleanup(hc_kafka_ctx_t *ctx);
static bool init_grpc(const hc_app_cfg_t *cfg);
static void shutdown_grpc(void);
static void handle_sig(int sig);
static bool ensure_singleton(void);

/* ---------- Utility ---------- */

static char* _strdup_safe(const char *s) {
    if (!s) return NULL;
    size_t len = strlen(s)+1;
    char *d = malloc(len);
    if (d) memcpy(d, s, len);
    return d;
}

/* ---------- Configuration loader (JSON) ---------- */

static bool load_cfg_file(const char *path, hc_app_cfg_t *out)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        LOG_ERROR("Unable to open config file `%s`: %s", path, strerror(errno));
        return false;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) != 0) {
        LOG_ERROR("stat() failed on config file: %s", strerror(errno));
        fclose(fp);
        return false;
    }

    char *buf = malloc(st.st_size + 1);
    if (!buf) {
        LOG_ERROR("Out of memory loading config");
        fclose(fp);
        return false;
    }
    if (fread(buf, 1, st.st_size, fp) != (size_t)st.st_size) {
        LOG_ERROR("Short read on config file");
        free(buf);
        fclose(fp);
        return false;
    }
    buf[st.st_size] = '\0';
    fclose(fp);

    cJSON *root = cJSON_Parse(buf);
    free(buf);
    if (!root) {
        LOG_ERROR("Parsing config JSON failed: %s", cJSON_GetErrorPtr());
        return false;
    }

    #define JSTR(name, dst) do {                                     \
            cJSON *jv = cJSON_GetObjectItemCaseSensitive(root, name);\
            if (cJSON_IsString(jv) && (jv->valuestring != NULL))     \
                dst = _strdup_safe(jv->valuestring);                 \
        } while (0)

    JSTR("kafka_brokers",    out->brokers);
    JSTR("wallet_topic_out", out->wallet_topic_out);
    JSTR("wallet_topic_in",  out->wallet_topic_in);
    JSTR("grpc_bind_addr",   out->grpc_bind_addr);
    JSTR("keystore_path",    out->keystore_path);
    JSTR("keystore_pass",    out->keystore_pass);

    cJSON *loglvl = cJSON_GetObjectItemCaseSensitive(root, "log_level");
    if (cJSON_IsNumber(loglvl))
        out->log_level = loglvl->valueint;
    else
        out->log_level = LOG_INFO;

    cJSON *acks = cJSON_GetObjectItemCaseSensitive(root, "kafka_ack");
    out->kafka_ack = cJSON_IsNumber(acks) ? acks->valueint : 1;

    cJSON_Delete(root);
    return true;
}

/* ---------- Kafka initialisation ---------- */

static bool init_kafka(const hc_app_cfg_t *cfg, hc_kafka_ctx_t *ctx)
{
    char errstr[256];
    rd_kafka_conf_t *pconf = rd_kafka_conf_new();
    rd_kafka_conf_set(pconf, "bootstrap.servers", cfg->brokers, errstr, sizeof(errstr));
    rd_kafka_conf_set(pconf, "queue.buffering.max.messages", "100000", NULL, 0);
    snprintf(errstr, sizeof(errstr), "%d", cfg->kafka_ack);
    rd_kafka_conf_set(pconf, "acks", errstr, NULL, 0);

    ctx->producer = rd_kafka_new(RD_KAFKA_PRODUCER, pconf, errstr, sizeof(errstr));
    if (!ctx->producer) {
        LOG_ERROR("Failed to create Kafka producer: %s", errstr);
        return false;
    }

    rd_kafka_topic_conf_t *tconf = rd_kafka_topic_conf_new();
    ctx->topic_out = rd_kafka_topic_new(ctx->producer, cfg->wallet_topic_out, tconf);
    if (!ctx->topic_out) {
        LOG_ERROR("Failed to create Kafka topic handle (out): %s",
                  rd_kafka_err2str(rd_kafka_last_error()));
        return false;
    }

    /* --- Consumer --- */
    rd_kafka_conf_t *cconf = rd_kafka_conf_new();
    rd_kafka_conf_set(cconf, "group.id", "wallet_proxy_consumer", NULL, 0);
    rd_kafka_conf_set(cconf, "bootstrap.servers", cfg->brokers, NULL, 0);
    rd_kafka_conf_set(cconf, "enable.auto.commit", "true", NULL, 0);

    ctx->consumer = rd_kafka_new(RD_KAFKA_CONSUMER, cconf, errstr, sizeof(errstr));
    if (!ctx->consumer) {
        LOG_ERROR("Failed to create Kafka consumer: %s", errstr);
        return false;
    }

    rd_kafka_poll_set_consumer(ctx->consumer);

    rd_kafka_topic_partition_list_t *subscribes = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(subscribes, cfg->wallet_topic_in, -1);

    if (rd_kafka_subscribe(ctx->consumer, subscribes) != RD_KAFKA_RESP_ERR_NO_ERROR) {
        LOG_ERROR("Kafka subscribe failed");
        rd_kafka_topic_partition_list_destroy(subscribes);
        return false;
    }

    rd_kafka_topic_partition_list_destroy(subscribes);

    LOG_INFO("Kafka initialised (brokers=%s)", cfg->brokers);
    return true;
}

static void kafka_cleanup(hc_kafka_ctx_t *ctx)
{
    if (!ctx) return;

    if (ctx->producer) {
        rd_kafka_flush(ctx->producer, 3000);
        rd_kafka_destroy(ctx->producer);
    }
    if (ctx->consumer) {
        rd_kafka_consumer_close(ctx->consumer);
        rd_kafka_destroy(ctx->consumer);
    }
}

/* ---------- Kafka consumer thread ---------- */

static void process_chain_event(const char *payload, size_t len)
{
    /* TODO: parse protobuf or JSON for transaction confirmations and
       update in-memory session cache. */
    LOG_DEBUG("Chain event received: %.*s", (int)len, payload);
}

static void *kafka_consume_thread(void *arg)
{
    rd_kafka_t *consumer = (rd_kafka_t *)arg;
    while (atomic_load(&g_running)) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(consumer, 250); /* 250ms */
        if (!rkmsg) continue;

        if (rkmsg->err) {
            if (rkmsg->err != RD_KAFKA_RESP_ERR__PARTITION_EOF)
                LOG_WARN("Kafka error: %s", rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        process_chain_event((const char *)rkmsg->payload, rkmsg->len);
        rd_kafka_message_destroy(rkmsg);
    }
    return NULL;
}

/* ---------- gRPC server scaffolding ---------- */

/* Placeholder service implementation ---------------------------------
 * In production, protobuf stubs are compiled generating a *_server.c
 * which is linked into this unit.  For brevity, only a mock skeleton
 * is provided here.
 */

typedef struct {
    grpc_completion_queue *cq;
    pthread_t              worker[HC_GRPC_MAX_THREADS];
} grpc_ctx_t;

static grpc_ctx_t g_grpc = {0};

static void *grpc_worker_thread(void *arg)
{
    grpc_completion_queue *cq = arg;
    grpc_event ev;

    while (atomic_load(&g_running)) {
        ev = grpc_completion_queue_next(cq, gpr_inf_future(GPR_CLOCK_REALTIME), NULL);
        if (ev.type == GRPC_QUEUE_SHUTDOWN) break;
        if (ev.type == GRPC_OP_COMPLETE) {
            /* Normally we would dispatch replies here */
        }
    }
    return NULL;
}

static bool init_grpc(const hc_app_cfg_t *cfg)
{
    grpc_init();
    g_grpc.cq = grpc_completion_queue_create_for_next(NULL);

    grpc_server_credentials *creds = NULL;
    if (cfg->keystore_path) {
        FILE *fp = fopen(cfg->keystore_path, "rb");
        if (!fp) {
            LOG_ERROR("Cannot open keystore path `%s`", cfg->keystore_path);
            return false;
        }
        fseek(fp, 0, SEEK_END);
        long sz = ftell(fp);
        fseek(fp, 0, SEEK_SET);
        char *pem_buf = malloc(sz + 1);
        fread(pem_buf, 1, sz, fp);
        fclose(fp);
        pem_buf[sz] = '\0';

        creds = grpc_ssl_server_credentials_create(NULL, NULL, 0, 0, NULL, NULL);
        if (!creds) {
            LOG_ERROR("Failed to create SSL credentials");
            free(pem_buf);
            return false;
        }
        free(pem_buf);
    }

    g_grpc_server = grpc_server_create(NULL, NULL);
    grpc_server_register_completion_queue(g_grpc_server, g_grpc.cq, NULL);

    if (creds) {
        if (grpc_server_add_secure_http2_port(g_grpc_server,
                                              cfg->grpc_bind_addr, creds) == 0) {
            LOG_ERROR("Failed adding secure gRPC port");
            return false;
        }
    } else {
        if (grpc_server_add_insecure_http2_port(g_grpc_server,
                                                cfg->grpc_bind_addr) == 0) {
            LOG_ERROR("Failed adding insecure gRPC port");
            return false;
        }
    }

    grpc_server_start(g_grpc_server);

    for (int i = 0; i < HC_GRPC_MAX_THREADS; ++i) {
        if (pthread_create(&g_grpc.worker[i], NULL,
                           grpc_worker_thread, g_grpc.cq) != 0) {
            LOG_ERROR("Unable to start gRPC worker thread");
            return false;
        }
    }

    LOG_INFO("gRPC server listening on %s", cfg->grpc_bind_addr);
    return true;
}

static void shutdown_grpc(void)
{
    if (!g_grpc_server) return;
    grpc_server_shutdown_and_notify(g_grpc_server, g_grpc.cq, NULL);
    grpc_completion_queue_shutdown(g_grpc.cq);

    for (int i = 0; i < HC_GRPC_MAX_THREADS; ++i)
        pthread_join(g_grpc.worker[i], NULL);

    grpc_server_destroy(g_grpc_server);
    grpc_completion_queue_destroy(g_grpc.cq);
    grpc_shutdown();
}

/* ---------- Signal handling ---------- */

static void handle_sig(int sig)
{
    (void)sig;
    atomic_store(&g_running, false);
}

static bool ensure_singleton(void)
{
    /* Simple PID-file lock to avoid double start. */
    const char *pidfile = "/var/run/holocanvas_wallet_proxy.pid";
    int fd = open(pidfile, O_RDWR | O_CREAT, 0640);
    if (fd < 0) {
        LOG_ERROR("Cannot open pidfile: %s", strerror(errno));
        return false;
    }
    if (lockf(fd, F_TLOCK, 0) < 0) {
        LOG_ERROR("Another instance appears to be running");
        close(fd);
        return false;
    }
    dprintf(fd, "%ld\n", (long)getpid());
    /* fd left open intentionally to maintain lock */
    return true;
}

/* ---------- Main entry ---------- */

int main(int argc, char **argv)
{
    /* ---------- Syslog setup ---------- */
    openlog(HC_SERVICE_NAME, LOG_PID | LOG_NDELAY, LOG_DAEMON);

    /* ---------- CLI parsing ---------- */
    const char *cfg_path = HC_DEFAULT_CFG_FILE;
    int opt;
    while ((opt = getopt(argc, argv, "c:h")) != -1) {
        switch (opt) {
            case 'c':
                cfg_path = optarg;
                break;
            case 'h':
            default:
                fprintf(stderr,
                        "%s v%s\nUsage: %s [-c config]\n",
                        HC_SERVICE_NAME, HC_VERSION, argv[0]);
                exit(EXIT_SUCCESS);
        }
    }

    /* ---------- Singleton enforcement ---------- */
    if (!ensure_singleton()) exit(EXIT_FAILURE);

    /* ---------- Load configuration ---------- */
    if (!load_cfg_file(cfg_path, &g_cfg)) {
        LOG_EMERG("Failed to load configuration — terminating");
        exit(EXIT_FAILURE);
    }
    setlogmask(LOG_UPTO(g_cfg.log_level));

    /* ---------- Register signal handlers ---------- */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sig;
    sigfillset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGQUIT, &sa, NULL);

    /* ---------- Crypto subsystem ---------- */
    if (OPENSSL_init_crypto(0, NULL) != 1) {
        LOG_EMERG("Failed to initialise OpenSSL");
        exit(EXIT_FAILURE);
    }

    /* ---------- Kafka initialisation ---------- */
    if (!init_kafka(&g_cfg, &g_kafka)) {
        LOG_EMERG("Kafka initialisation failed");
        exit(EXIT_FAILURE);
    }

    /* ---------- gRPC initialisation ---------- */
    if (!init_grpc(&g_cfg)) {
        LOG_EMERG("gRPC initialisation failed");
        kafka_cleanup(&g_kafka);
        exit(EXIT_FAILURE);
    }

    /* ---------- Start consumer thread ---------- */
    pthread_t consumer_thread;
    if (pthread_create(&consumer_thread, NULL, kafka_consume_thread,
                       g_kafka.consumer) != 0) {
        LOG_EMERG("Failed to start Kafka consumer thread");
        shutdown_grpc();
        kafka_cleanup(&g_kafka);
        exit(EXIT_FAILURE);
    }

    /* ---------- Main loop (producer flush) ---------- */
    while (atomic_load(&g_running)) {
        rd_kafka_poll(g_kafka.producer, 0);
        /* TODO: Accept outbound tx from gRPC -> produce to Kafka */
        usleep(250000); /* 250ms */
    }

    /* ---------- Shutdown ---------- */
    LOG_INFO("Shutdown initiated");

    pthread_join(consumer_thread, NULL);
    shutdown_grpc();
    kafka_cleanup(&g_kafka);
    closelog();
    return EXIT_SUCCESS;
}
```