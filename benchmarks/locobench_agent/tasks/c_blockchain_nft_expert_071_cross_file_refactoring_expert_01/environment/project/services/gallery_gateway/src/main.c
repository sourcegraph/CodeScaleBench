/*
 * HoloCanvas – Gallery-Gateway microservice
 *
 * services/gallery_gateway/src/main.c
 *
 * The Gallery-Gateway is the public-facing facade that streams live state-changes
 * of on-chain generative artifacts to Web clients, CLI observers and other
 * HoloCanvas micro-services.  It bridges a Kafka event mesh with a lightweight
 * gRPC endpoint so that UI front-ends and curator bots can subscribe to an
 * authenticated stream instead of polling the chain.
 *
 * Build (example):
 *   gcc -std=c11 -Wall -Wextra -pedantic                       \
 *       -I/usr/include -I/usr/local/include                   \
 *       main.c -o gallery_gateway                              \
 *       -lrdkafka -lgrpc -lgrpc++_unsecure -lpthread -lcjson
 *
 * Runtime:
 *   ./gallery_gateway -c /etc/hc/gallery_gateway.json
 *
 * ---------------------------------------------------------------------------
 * Copyright (c) 2023-2024  HoloCanvas Contributors
 * SPDX-License-Identifier: MIT
 */
#define _GNU_SOURCE
#include <errno.h>
#include <getopt.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

#include <grpc/grpc.h>
#include <grpc/grpc_security.h>
#include <grpc/support/log.h>

#include <librdkafka/rdkafka.h>

#include <cjson/cJSON.h>

/* ---------------------------------------------------------------------------
 * Compile-time defaults that can be overridden in the JSON config
 * --------------------------------------------------------------------------- */
#define DEF_KAFKA_BROKERS   "localhost:9092"
#define DEF_TOPIC_IN        "hc.chain.events"
#define DEF_TOPIC_OUT       "hc.gallery.broadcast"
#define DEF_GRPC_ADDR       "0.0.0.0:7002"
#define DEF_CLIENT_TIMEOUT  30  /* seconds */

/* ---------------------------------------------------------------------------
 * Convenience logging macros (syslog + stderr fallback for early startup)
 * --------------------------------------------------------------------------- */
#define LOG_EMERG(fmt, ...)   syslog(LOG_EMERG,   "[EMERG] " fmt, ##__VA_ARGS__)
#define LOG_ALERT(fmt, ...)   syslog(LOG_ALERT,   "[ALERT] " fmt, ##__VA_ARGS__)
#define LOG_CRIT(fmt, ...)    syslog(LOG_CRIT,    "[CRIT]  " fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...)     syslog(LOG_ERR,     "[ERROR] " fmt, ##__VA_ARGS__)
#define LOG_WARNING(fmt, ...) syslog(LOG_WARNING, "[WARN ] " fmt, ##__VA_ARGS__)
#define LOG_NOTICE(fmt, ...)  syslog(LOG_NOTICE,  "[NOTE ] " fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)    syslog(LOG_INFO,    "[INFO ] " fmt, ##__VA_ARGS__)
#define LOG_DEBUG(fmt, ...)   syslog(LOG_DEBUG,   "[DEBUG] " fmt, ##__VA_ARGS__)

/* Forward declarations */
typedef struct app_ctx_s app_ctx_t;
static bool app_load_config(app_ctx_t *ctx, const char *file);
static bool app_kafka_init(app_ctx_t *ctx);
static bool app_grpc_init(app_ctx_t *ctx);
static void app_event_loop(app_ctx_t *ctx);
static void app_cleanup(app_ctx_t *ctx);

/* ---------------------------------------------------------------------------
 * Application context
 * --------------------------------------------------------------------------- */
struct app_ctx_s {
    /* Configuration values */
    char *kafka_brokers;
    char *topic_in;
    char *topic_out;
    char *grpc_addr;
    int   client_timeout; /* seconds */

    /* Kafka handles */
    rd_kafka_t          *rk;             /* shared handle */
    rd_kafka_consumer_t *consumer;       /* high-level balanced consumer */
    rd_kafka_topic_t    *producer_topic; /* for fan-out broadcast */

    /* gRPC */
    grpc_completion_queue *cq;
    grpc_server            *server;

    /* Control */
    atomic_bool terminate;
};

/* ---------------------------------------------------------------------------
 * Graceful shutdown handling
 * --------------------------------------------------------------------------- */
static app_ctx_t *g_ctx = NULL;

static void signal_handler(int signo)
{
    if (g_ctx) {
        atomic_store(&g_ctx->terminate, true);
    }
    (void)signo;
}

/* ---------------------------------------------------------------------------
 * Helpers
 * --------------------------------------------------------------------------- */
static char *strdup_null(const char *s)
{
    return s ? strdup(s) : NULL;
}

static void free_null(void *p)
{
    if (p) free(p);
}

/* ---------------------------------------------------------------------------
 * Kafka message processing – determine whether the incoming chain event
 * should be forwarded to front-ends.  For brevity we simply forward all
 * messages but a real implementation could filter by NFT id, phase, etc.
 * --------------------------------------------------------------------------- */
static void kafka_process_message(app_ctx_t       *ctx,
                                  rd_kafka_message_t *rkmsg)
{
    if (rkmsg->err) {
        LOG_ERR("Kafka consumption error: %s", rd_kafka_message_errstr(rkmsg));
        return;
    }

    /* Forward message payload to broadcast topic */
    rd_kafka_resp_err_t err =
        rd_kafka_produce(
            rd_kafka_topic_name(ctx->producer_topic)
            ? ctx->producer_topic : NULL,
            RD_KAFKA_PARTITION_UA,
            RD_KAFKA_MSG_F_COPY,
            rkmsg->payload, rkmsg->len,
            NULL, 0,
            NULL);

    if (err)
        LOG_ERR("Failed to produce broadcast message: %s", rd_kafka_err2str(err));
}

/* ---------------------------------------------------------------------------
 * Read configuration from JSON file
 * --------------------------------------------------------------------------- */
static bool app_load_config(app_ctx_t *ctx, const char *file_path)
{
    FILE *fp = fopen(file_path, "r");
    if (!fp) {
        LOG_ERR("Unable to open config file '%s': %s", file_path, strerror(errno));
        return false;
    }

    fseek(fp, 0, SEEK_END);
    long len = ftell(fp);
    rewind(fp);

    char *raw = calloc(1, len + 1);
    if (fread(raw, 1, len, fp) != (size_t)len) {
        LOG_ERR("Failed to read config file");
        fclose(fp);
        free(raw);
        return false;
    }
    fclose(fp);

    cJSON *json = cJSON_Parse(raw);
    free(raw);
    if (!json) {
        LOG_ERR("Config JSON malformed: %s", cJSON_GetErrorPtr());
        return false;
    }

    /* Extract with fallbacks */
    ctx->kafka_brokers  = strdup_null(cJSON_GetStringValue(cJSON_GetObjectItem(json, "kafka_brokers"))) ?: strdup(DEF_KAFKA_BROKERS);
    ctx->topic_in       = strdup_null(cJSON_GetStringValue(cJSON_GetObjectItem(json, "topic_in")))      ?: strdup(DEF_TOPIC_IN);
    ctx->topic_out      = strdup_null(cJSON_GetStringValue(cJSON_GetObjectItem(json, "topic_out")))     ?: strdup(DEF_TOPIC_OUT);
    ctx->grpc_addr      = strdup_null(cJSON_GetStringValue(cJSON_GetObjectItem(json, "grpc_addr")))     ?: strdup(DEF_GRPC_ADDR);
    ctx->client_timeout = cJSON_GetObjectItem(json, "client_timeout") ?
                          cJSON_GetObjectItem(json, "client_timeout")->valueint :
                          DEF_CLIENT_TIMEOUT;

    cJSON_Delete(json);
    return true;
}

/* ---------------------------------------------------------------------------
 * Initialize Kafka consumer + producer
 * --------------------------------------------------------------------------- */
static bool app_kafka_init(app_ctx_t *ctx)
{
    char errstr[512];

    /* Global config */
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    if (rd_kafka_conf_set(conf, "bootstrap.servers", ctx->kafka_brokers, errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        LOG_ERR("Kafka conf error: %s", errstr);
        rd_kafka_conf_destroy(conf);
        return false;
    }
    /* We want the consumer to re-balance automatically */
    rd_kafka_conf_set(conf, "group.id", "hc_gallery_gateway", NULL, 0);
    rd_kafka_conf_set(conf, "auto.offset.reset", "earliest", NULL, 0);

    /* Provide opaque pointer to access ctx in callbacks if needed */
    rd_kafka_conf_set_opaque(conf, ctx);

    /* Create handle */
    ctx->rk = rd_kafka_new(RD_KAFKA_CONSUMER, conf, errstr, sizeof(errstr));
    if (!ctx->rk) {
        LOG_ERR("Failed to create Kafka consumer: %s", errstr);
        return false;
    }

    /* Create producer topic (same handle) */
    rd_kafka_topic_conf_t *tconf = rd_kafka_topic_conf_new();
    ctx->producer_topic = rd_kafka_topic_new(ctx->rk, ctx->topic_out, tconf);
    if (!ctx->producer_topic) {
        LOG_ERR("Failed to create producer topic");
        return false;
    }

    /* Create high-level consumer */
    ctx->consumer = (rd_kafka_consumer_t *)ctx->rk;
    rd_kafka_poll_set_consumer(ctx->consumer);

    rd_kafka_resp_err_t err = rd_kafka_subscribe(ctx->consumer, rd_kafka_topic_partition_list_new(1));
    if (err) {
        LOG_ERR("Kafka subscribe failed: %s", rd_kafka_err2str(err));
        return false;
    }

    /* In high-level consumer, we must supply topic list */
    rd_kafka_topic_partition_list_t *topics = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, ctx->topic_in, RD_KAFKA_PARTITION_UA);
    err = rd_kafka_subscribe(ctx->consumer, topics);
    rd_kafka_topic_partition_list_destroy(topics);
    if (err) {
        LOG_ERR("Kafka subscribe error: %s", rd_kafka_err2str(err));
        return false;
    }

    LOG_INFO("Kafka initialized – brokers=%s, consume=%s, produce=%s",
             ctx->kafka_brokers, ctx->topic_in, ctx->topic_out);
    return true;
}

/* ---------------------------------------------------------------------------
 * Minimal gRPC service definition – a single “Ping” unary method.
 * For production you would compile .proto files to C code.
 * --------------------------------------------------------------------------- */
static void handle_ping(grpc_server       *server,
                        grpc_completion_queue *cq,
                        void *tag, int ok)
{
    (void)server; (void)cq; (void)tag; (void)ok;
    /* TODO: Provide implementation using generated stubs */
}

static bool app_grpc_init(app_ctx_t *ctx)
{
    grpc_init();

    ctx->cq = grpc_completion_queue_create_for_next(NULL);
    if (!ctx->cq) {
        LOG_ERR("Failed to create gRPC completion queue");
        return false;
    }

    grpc_channel_args args = {
        .num_args = 0,
        .args     = NULL
    };

    ctx->server = grpc_server_create(&args, NULL);
    if (!ctx->server) {
        LOG_ERR("Failed to create gRPC server");
        return false;
    }

    /* Insecure creds are fine for internal mesh; in prod use mTLS. */
    grpc_server_credentials *creds = grpc_insecure_server_credentials_create();
    grpc_server_register_completion_queue(ctx->server, ctx->cq, NULL);
    grpc_server_add_insecure_http2_port(ctx->server, ctx->grpc_addr);
    grpc_server_start(ctx->server);

    LOG_INFO("gRPC server listening on %s", ctx->grpc_addr);
    (void)creds; /* unused placeholder */

    return true;
}

/* ---------------------------------------------------------------------------
 * Main event loop – multiplex Kafka polling + gRPC completions.
 * We use a simple interleaved loop to avoid complex pollsets.
 * --------------------------------------------------------------------------- */
static void app_event_loop(app_ctx_t *ctx)
{
    while (!atomic_load(&ctx->terminate)) {
        /* 1. Handle Kafka messages with short timeout */
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(ctx->consumer, 100 /*ms*/);
        if (rkmsg) {
            kafka_process_message(ctx, rkmsg);
            rd_kafka_message_destroy(rkmsg);
        }

        /* 2. Handle gRPC events (non-blocking) */
        grpc_event ev = grpc_completion_queue_next(ctx->cq,
                                                   gpr_time_add(gpr_now(GPR_CLOCK_REALTIME),
                                                                gpr_time_from_millis(10, GPR_CLOCK_REALTIME)),
                                                   NULL);
        if (ev.type != GRPC_QUEUE_TIMEOUT) {
            /* Dispatch tag */
            void (*cb)(grpc_server*, grpc_completion_queue*, void*, int) = ev.tag;
            cb(ctx->server, ctx->cq, ev.tag, ev.success);
        }
    }
}

/* ---------------------------------------------------------------------------
 * Cleanup resources
 * --------------------------------------------------------------------------- */
static void app_cleanup(app_ctx_t *ctx)
{
    if (!ctx) return;

    /* gRPC */
    if (ctx->server) {
        grpc_server_shutdown_and_notify(ctx->server, ctx->cq, NULL);
        grpc_completion_queue_next(ctx->cq,
                                   gpr_inf_future(GPR_CLOCK_REALTIME), NULL);
        grpc_server_destroy(ctx->server);
    }
    if (ctx->cq)
        grpc_completion_queue_destroy(ctx->cq);
    grpc_shutdown();

    /* Kafka */
    if (ctx->producer_topic)
        rd_kafka_topic_destroy(ctx->producer_topic);

    if (ctx->consumer) {
        rd_kafka_consumer_close(ctx->consumer);
    }
    if (ctx->rk) {
        rd_kafka_flush(ctx->rk, 5000);
        rd_kafka_destroy(ctx->rk);
    }

    /* Free config strings */
    free_null(ctx->kafka_brokers);
    free_null(ctx->topic_in);
    free_null(ctx->topic_out);
    free_null(ctx->grpc_addr);
}

/* ---------------------------------------------------------------------------
 * CLI usage
 * --------------------------------------------------------------------------- */
static void usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s [-c, --config <file>] [-h]\n"
            "  -c  Path to JSON configuration file\n"
            "  -h  Show this help message\n",
            prog);
}

/* ---------------------------------------------------------------------------
 * Entrypoint
 * --------------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    const char *config_path = "/etc/hc/gallery_gateway.json";

    static const struct option long_opts[] = {
        {"config", required_argument, 0, 'c'},
        {"help",   no_argument,       0, 'h'},
        {0,        0,                 0,  0 }
    };

    int opt, idx;
    while ((opt = getopt_long(argc, argv, "c:h", long_opts, &idx)) != -1) {
        switch (opt) {
            case 'c': config_path = optarg; break;
            case 'h':
            default:  usage(argv[0]); return EXIT_FAILURE;
        }
    }

    openlog("hc_gallery_gateway", LOG_PID | LOG_CONS, LOG_USER);

    app_ctx_t ctx = {0};
    g_ctx = &ctx;

    if (!app_load_config(&ctx, config_path))
        goto fatal;

    if (!app_kafka_init(&ctx))
        goto fatal;

    if (!app_grpc_init(&ctx))
        goto fatal;

    /* Setup signal handlers for graceful termination */
    struct sigaction sa = { .sa_handler = signal_handler };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LOG_NOTICE("Gallery-Gateway started (build %s %s)",
               __DATE__, __TIME__);

    app_event_loop(&ctx);

    LOG_NOTICE("Shutting down…");
    app_cleanup(&ctx);
    closelog();
    return EXIT_SUCCESS;

fatal:
    LOG_CRIT("Fatal startup error, aborting");
    app_cleanup(&ctx);
    closelog();
    return EXIT_FAILURE;
}