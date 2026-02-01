/*
 * popularity_evolver.c
 *
 * HoloCanvas – Muse-Observer Strategy Plug-in
 * -------------------------------------------
 * “Popularity Evolver” mutates an NFT’s audiovisual layers whenever its
 * social “heat” (likes, reposts, bids, governance up-votes, etc.) crosses a
 * configurable threshold.  The strategy listens to Muse events on Kafka,
 * remembers the last applied threshold per artifact in an embedded SQLite
 * catalogue, and publishes an “artifact_evolve” command back onto the bus.
 *
 * Build:
 *   cc -Wall -Wextra -O2 -pthread \
 *      popularity_evolver.c -o popularity_evolver \
 *      -lrdkafka -lsqlite3 -lcjson
 *
 * (link paths for librdkafka/cJSON/sqlite3 may vary per system)
 */

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sqlite3.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <cjson/cJSON.h>
#include <librdkafka/rdkafka.h>

/* ---------------------------  Constants & Macros  ------------------------- */

#define DEFAULT_KAFKA_BROKERS "127.0.0.1:9092"
#define KAFKA_GROUP_ID        "hc.popularity_evolver"
#define TOPIC_INCOMING        "muse.events"
#define TOPIC_OUTGOING        "artifact.commands"

#define MAX_THRESHOLDS        16
#define MAX_TOKEN_ID_LEN      128
#define MAX_TX_ID_LEN         128
#define STRERR_BUFSZ          128

#define SQL_CREATE_TABLE                                              \
    "CREATE TABLE IF NOT EXISTS evolver_state ("                      \
    "  token_id TEXT PRIMARY KEY NOT NULL,"                           \
    "  threshold_index INTEGER NOT NULL"                              \
    ");"

#define SQL_SELECT_STATE "SELECT threshold_index FROM evolver_state WHERE token_id=?1;"
#define SQL_INSERT_STATE "INSERT INTO evolver_state(token_id,threshold_index) VALUES(?1,?2);"
#define SQL_UPDATE_STATE "UPDATE evolver_state SET threshold_index=?2 WHERE token_id=?1;"


/* -----------------------------  Data Models  ------------------------------ */

/* Runtime configuration parsed from JSON or environment -------------------- */
typedef struct {
    long   thresholds[MAX_THRESHOLDS];   /* e.g., likes counts */
    size_t threshold_count;
    char   *kafka_brokers;
    char   *sqlite_path;
} evo_config_t;

/* Kafka-consumer and producer handles ------------------------------------- */
typedef struct {
    rd_kafka_t      *consumer;
    rd_kafka_t      *producer;
    rd_kafka_topic_t*topic_out;
} evo_bus_t;

/* Global process-wide context --------------------------------------------- */
typedef struct {
    evo_config_t cfg;
    evo_bus_t    bus;
    sqlite3      *db;
    atomic_bool   run;
} evo_ctx_t;


/* --------------------------  Utility Functions  --------------------------- */

static void fatal(const char *msg) {
    fprintf(stderr, "FATAL: %s\n", msg);
    exit(EXIT_FAILURE);
}

static void perror_fatal(const char *msg) {
    char buf[STRERR_BUFSZ];
    strerror_r(errno, buf, sizeof(buf));
    fprintf(stderr, "FATAL: %s: %s\n", msg, buf);
    exit(EXIT_FAILURE);
}

static long str_to_long(const char *s, const char *desc) {
    char *end = NULL;
    errno     = 0;
    long v    = strtol(s, &end, 10);
    if (errno || !end || *end != '\0')
        fatal(desc);
    return v;
}

/* -----------------------  Configuration Management  ----------------------- */

/* Load thresholds from JSON string ---------------------------------------- */
static void load_thresholds(evo_config_t *cfg, const char *json_str) {
    cJSON *root = cJSON_Parse(json_str);
    if (!root || !cJSON_IsArray(root))
        fatal("Invalid threshold JSON.");

    size_t idx = 0;
    cJSON *elem;
    cJSON_ArrayForEach(elem, root) {
        if (!cJSON_IsNumber(elem))
            fatal("Threshold element is not numeric.");
        if (idx >= MAX_THRESHOLDS)
            fatal("Too many thresholds.");
        cfg->thresholds[idx++] = elem->valuedouble;
    }
    cfg->threshold_count = idx;
    cJSON_Delete(root);

    if (cfg->threshold_count == 0)
        fatal("No thresholds configured.");
}

/* Environment-variable driven config -------------------------------------- */
static void config_init(evo_config_t *cfg) {
    memset(cfg, 0, sizeof(*cfg));

    const char *json = getenv("POP_EVOLVER_THRESHOLDS");
    if (!json)
        json = "[10,50,100,250,500]";      /* sensible default */
    load_thresholds(cfg, json);

    const char *brokers = getenv("KAFKA_BROKERS");
    cfg->kafka_brokers  = strdup(brokers ? brokers : DEFAULT_KAFKA_BROKERS);

    const char *db_path = getenv("EVOLVER_SQLITE");
    cfg->sqlite_path    = strdup(db_path ? db_path : "/var/lib/holocanvas/evolver_state.db");
}

/* ---------------------------  SQLite Helpers  ----------------------------- */

static void db_open(evo_ctx_t *ctx) {
    if (sqlite3_open(ctx->cfg.sqlite_path, &ctx->db) != SQLITE_OK)
        fatal(sqlite3_errmsg(ctx->db));

    char *errmsg = NULL;
    if (sqlite3_exec(ctx->db, SQL_CREATE_TABLE, NULL, NULL, &errmsg) != SQLITE_OK) {
        fatal(errmsg);
    }
}

/* Retrieve current threshold index for token; returns -1 if unknown -------- */
static int db_get_threshold_index(evo_ctx_t *ctx, const char *token_id) {
    sqlite3_stmt *stmt;
    if (sqlite3_prepare_v2(ctx->db, SQL_SELECT_STATE, -1, &stmt, NULL) != SQLITE_OK)
        fatal(sqlite3_errmsg(ctx->db));

    sqlite3_bind_text(stmt, 1, token_id, -1, SQLITE_STATIC);
    int idx = -1;
    if (sqlite3_step(stmt) == SQLITE_ROW)
        idx = sqlite3_column_int(stmt, 0);

    sqlite3_finalize(stmt);
    return idx;
}

/* Persist new threshold index for token ------------------------------------ */
static void db_set_threshold_index(evo_ctx_t *ctx, const char *token_id, int new_index) {
    sqlite3_stmt *stmt;
    const char *sql = (db_get_threshold_index(ctx, token_id) == -1) ? SQL_INSERT_STATE
                                                                    : SQL_UPDATE_STATE;

    if (sqlite3_prepare_v2(ctx->db, sql, -1, &stmt, NULL) != SQLITE_OK)
        fatal(sqlite3_errmsg(ctx->db));

    sqlite3_bind_text (stmt, 1, token_id, -1, SQLITE_STATIC);
    sqlite3_bind_int  (stmt, 2, new_index);

    if (sqlite3_step(stmt) != SQLITE_DONE)
        fatal(sqlite3_errmsg(ctx->db));

    sqlite3_finalize(stmt);
}

/* ------------------------------  Kafka I/O  --------------------------------*/

static rd_kafka_t* kafka_create(rd_kafka_type_t type,
                                const char *brokers,
                                const char *group_id) {

    char errstr[512];
    rd_kafka_conf_t *conf = rd_kafka_conf_new();

    if (type == RD_KAFKA_CONSUMER && group_id)
        rd_kafka_conf_set(conf, "group.id", group_id, errstr, sizeof errstr);

    rd_kafka_conf_set(conf, "bootstrap.servers", brokers, errstr, sizeof errstr);
    rd_kafka_conf_set(conf, "enable.auto.commit", "false", errstr, sizeof errstr);

    rd_kafka_t *k = rd_kafka_new(type, conf, errstr, sizeof errstr);
    if (!k)
        fatal(errstr);
    return k;
}

static void bus_init(evo_ctx_t *ctx) {
    ctx->bus.consumer = kafka_create(RD_KAFKA_CONSUMER,
                                     ctx->cfg.kafka_brokers, KAFKA_GROUP_ID);
    ctx->bus.producer = kafka_create(RD_KAFKA_PRODUCER,
                                     ctx->cfg.kafka_brokers, NULL);

    rd_kafka_poll_set_consumer(ctx->bus.consumer);

    /* Subscribe to input topic(s) */
    rd_kafka_topic_partition_list_t *subscription =
        rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(subscription, TOPIC_INCOMING, -1);

    if (rd_kafka_subscribe(ctx->bus.consumer, subscription))
        fatal("Failed to subscribe to Kafka topic.");

    rd_kafka_topic_partition_list_destroy(subscription);

    /* Prepare producer topic */
    ctx->bus.topic_out = rd_kafka_topic_new(ctx->bus.producer, TOPIC_OUTGOING, NULL);
    if (!ctx->bus.topic_out)
        fatal("Failed to create Kafka producer topic object.");
}

/* Publish evolve command --------------------------------------------------- */
static void publish_evolve(evo_ctx_t *ctx,
                           const char *token_id,
                           long new_threshold,
                           const char *tx_id) {

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "artifact_evolve");
    cJSON_AddStringToObject(root, "token_id", token_id);
    cJSON_AddNumberToObject(root, "threshold", new_threshold);
    cJSON_AddStringToObject(root, "ref_tx", tx_id);
    char *json_str = cJSON_PrintUnformatted(root);

    if (rd_kafka_produce(
            ctx->bus.topic_out, RD_KAFKA_PARTITION_UA,
            RD_KAFKA_MSG_F_COPY,
            json_str, strlen(json_str),
            NULL, 0,
            NULL) == -1) {
        fprintf(stderr, "Kafka produce failed: %s\n",
                rd_kafka_err2str(rd_kafka_last_error()));
    } else {
        rd_kafka_poll(ctx->bus.producer, 0); /* serve acks */
    }

    cJSON_Delete(root);
    free(json_str);
}

/* --------------------------  Event Processing  ---------------------------- */

/* Parse incoming JSON muse event, return true if we handled it ------------- */
static bool process_event(evo_ctx_t *ctx, const char *payload, size_t len) {
    (void)len;
    cJSON *root = cJSON_ParseWithLength(payload, len);
    if (!root)
        return false;

    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    if (!cJSON_IsString(type) || strcmp(type->valuestring, "popularity_update") != 0) {
        cJSON_Delete(root);
        return false; /* not our concern */
    }

    const cJSON *token   = cJSON_GetObjectItemCaseSensitive(root, "token_id");
    const cJSON *likes   = cJSON_GetObjectItemCaseSensitive(root, "likes");
    const cJSON *tx_id   = cJSON_GetObjectItemCaseSensitive(root, "tx_id");

    if (!cJSON_IsString(token) || !cJSON_IsNumber(likes) || !cJSON_IsString(tx_id)) {
        cJSON_Delete(root);
        return false;
    }

    const char *token_id = token->valuestring;
    long        pop_val  = likes->valuedouble;

    int current_idx = db_get_threshold_index(ctx, token_id);
    int next_idx    = current_idx + 1;

    if ((size_t)next_idx < ctx->cfg.threshold_count &&
        pop_val >= ctx->cfg.thresholds[next_idx]) {

        long new_threshold = ctx->cfg.thresholds[next_idx];
        /* Update state before publishing to keep idempotency */
        db_set_threshold_index(ctx, token_id, next_idx);
        publish_evolve(ctx, token_id, new_threshold, tx_id->valuestring);

        fprintf(stdout,
                "Evolved token %s at pop=%ld (threshold %ld)\n",
                token_id, pop_val, new_threshold);
    }

    cJSON_Delete(root);
    return true;
}

/* ------------------------  Consumer Thread Loop  -------------------------- */

static void *consumer_loop(void *arg) {
    evo_ctx_t *ctx = arg;

    while (atomic_load(&ctx->run)) {
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(ctx->bus.consumer, 500);
        if (!rkmsg)
            continue; /* timeout */

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                /* ignore */
            } else {
                fprintf(stderr, "Kafka error: %s\n",
                        rd_kafka_message_errstr(rkmsg));
            }
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        process_event(ctx,
                      (const char *)rkmsg->payload,
                      rkmsg->len);

        rd_kafka_commit_message(ctx->bus.consumer, rkmsg, 0);
        rd_kafka_message_destroy(rkmsg);
    }
    return NULL;
}

/* -------------------------  Signal Handling / Main ------------------------ */

static void handle_sig(int sig) {
    (void)sig;
}

int main(void) {
    evo_ctx_t ctx;
    memset(&ctx, 0, sizeof ctx);
    atomic_init(&ctx.run, true);

    signal(SIGINT, handle_sig);
    signal(SIGTERM, handle_sig);

    config_init(&ctx.cfg);
    db_open(&ctx);
    bus_init(&ctx);

    pthread_t tid;
    if (pthread_create(&tid, NULL, consumer_loop, &ctx))
        perror_fatal("pthread_create");

    /* Block until signal */
    pause();

    /* Shutdown sequence */
    atomic_store(&ctx.run, false);
    pthread_join(tid, NULL);

    rd_kafka_consumer_close(ctx.bus.consumer);
    rd_kafka_destroy(ctx.bus.consumer);
    rd_kafka_topic_destroy(ctx.bus.topic_out);
    rd_kafka_flush(ctx.bus.producer, 2000);
    rd_kafka_destroy(ctx.bus.producer);

    sqlite3_close(ctx.db);

    free(ctx.cfg.kafka_brokers);
    free(ctx.cfg.sqlite_path);
    return 0;
}