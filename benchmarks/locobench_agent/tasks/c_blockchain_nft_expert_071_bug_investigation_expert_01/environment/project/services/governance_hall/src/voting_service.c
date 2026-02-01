```c
/**
 * HoloCanvas – Governance-Hall: voting_service.c
 *
 * A production-grade voting micro-service that listens to the
 * “governance-votes” Kafka topic, verifies incoming ballots,
 * persists them to a lightweight SQL store, tallies finalized
 * proposals, and emits “governance-result” events.
 *
 * Dependencies
 *   – librdkafka      : high-performance Kafka client
 *   – libssl / OpenSSL: cryptographic signature verification
 *   – sqlite3         : embedded persistence for ballots / tallies
 *   – cJSON           : minimal JSON serialization
 *
 * Build example
 *   gcc -Wall -Wextra -pedantic -std=c17 \
 *       voting_service.c -o voting_service \
 *       -lrdkafka -lssl -lcrypto -lsqlite3 -lpthread
 *
 * Author: HoloCanvas Core Team
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>

/* External libs */
#include <sqlite3.h>
#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/err.h>
#include <librdkafka/rdkafka.h>
#include "cJSON.h"

/* ------------------------------------------------------------------------- */
/* Constants                                                                 */
/* ------------------------------------------------------------------------- */

#define CONF_PATH_ENV              "HOLOCANVAS_CONF"
#define DEFAULT_CONF_PATH          "./governance_hall.toml"

#define KAFKA_TOPIC_VOTES          "governance-votes"
#define KAFKA_TOPIC_RESULTS        "governance-results"
#define KAFKA_BROKERS_DEFAULT      "localhost:9092"

#define DB_FILE_DEFAULT            "governance_votes.db"
#define SQL_CREATE_BALLOTS         "CREATE TABLE IF NOT EXISTS ballots(\
                                        id TEXT PRIMARY KEY,          \
                                        proposal_id TEXT NOT NULL,    \
                                        voter_pk BLOB NOT NULL,       \
                                        choice INTEGER NOT NULL,      \
                                        ts INTEGER NOT NULL);"

#define SQL_CREATE_RESULTS         "CREATE TABLE IF NOT EXISTS results( \
                                        proposal_id TEXT PRIMARY KEY,   \
                                        yes_cnt INTEGER NOT NULL,       \
                                        no_cnt INTEGER NOT NULL,        \
                                        abstain_cnt INTEGER NOT NULL,   \
                                        finalized INTEGER NOT NULL);"

#define FINALIZATION_DELAY_SEC     30      /* finalize after inactivity */

/* ------------------------------------------------------------------------- */
/* Data types                                                                */
/* ------------------------------------------------------------------------- */

typedef enum {
    VOTE_CHOICE_YES     = 1,
    VOTE_CHOICE_NO      = 0,
    VOTE_CHOICE_ABSTAIN = 2
} vote_choice_e;

typedef struct {
    char      id[64];          /* UUID of the ballot                   */
    char      proposal_id[64]; /* UUID of proposal                     */
    uint8_t   voter_pk[65];    /* compressed secp256k1 public key      */
    vote_choice_e choice;      /* voter’s decision                     */
    int64_t   ts;              /* unix epoch milliseconds              */
    uint8_t   sig[72];         /* DER encoded ECDSA signature          */
    size_t    sig_len;
} ballot_t;

typedef struct {
    rd_kafka_t         *rk_consumer;
    rd_kafka_topic_t   *rkt_consumer;
    rd_kafka_t         *rk_producer;
    rd_kafka_topic_t   *rkt_producer;

    sqlite3            *db;

    char                *kafka_brokers;
    char                *db_file;
} svc_ctx_t;

/* ------------------------------------------------------------------------- */
/* Global state                                                              */
/* ------------------------------------------------------------------------- */

static atomic_bool g_terminate = ATOMIC_VAR_INIT(false);

/* ------------------------------------------------------------------------- */
/* Forward declarations                                                      */
/* ------------------------------------------------------------------------- */

static bool load_config(svc_ctx_t *ctx);
static bool init_kafka(svc_ctx_t *ctx);
static bool init_sqlite(svc_ctx_t *ctx);
static bool verify_ballot_signature(const ballot_t *ballot);
static bool persist_ballot(sqlite3 *db, const ballot_t *ballot);
static bool update_tally(sqlite3 *db, const ballot_t *ballot);
static bool maybe_finalize_proposal(svc_ctx_t *ctx, const char *proposal_id);
static void emit_result(svc_ctx_t *ctx, const char *proposal_id,
                        uint64_t yes_cnt, uint64_t no_cnt, uint64_t abstain_cnt);
static void poll_loop(svc_ctx_t *ctx);
static void cleanup(svc_ctx_t *ctx);

/* ------------------------------------------------------------------------- */
/* Utility helpers                                                           */
/* ------------------------------------------------------------------------- */

static void sig_handler(int sig) {
    (void)sig;
    atomic_store(&g_terminate, true);
}

static int64_t now_ms(void) {
    struct timespec tv;
    clock_gettime(CLOCK_REALTIME, &tv);
    return (int64_t)tv.tv_sec * 1000 + tv.tv_nsec / 1000000;
}

static void log_err(const char *ctx, const char *msg) {
    fprintf(stderr, "[ERR] %s: %s (errno=%d)\n", ctx, msg, errno);
}

static void log_info(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    printf("[INF] ");
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
}

/* ------------------------------------------------------------------------- */
/* Implementation                                                            */
/* ------------------------------------------------------------------------- */

int main(void)
{
    svc_ctx_t ctx = {0};

    signal(SIGINT,  sig_handler);
    signal(SIGTERM, sig_handler);

    if (!load_config(&ctx)) {
        log_err("config", "failed to load");
        return EXIT_FAILURE;
    }
    if (!init_sqlite(&ctx)) {
        log_err("sqlite", "initialization failed");
        return EXIT_FAILURE;
    }
    if (!init_kafka(&ctx)) {
        log_err("kafka", "initialization failed");
        return EXIT_FAILURE;
    }

    log_info("Voting service started (brokers=%s, db=%s)",
             ctx.kafka_brokers, ctx.db_file);

    poll_loop(&ctx);

    cleanup(&ctx);
    log_info("Voting service stopped");
    return EXIT_SUCCESS;
}

/* ------------------------------------------------------------------------- */
/* Config (simple env-var / defaults)                                        */
/* ------------------------------------------------------------------------- */

static bool load_config(svc_ctx_t *ctx)
{
    /* In production, parse TOML/YAML. For brevity we use env vars. */
    const char *kafka_env    = getenv("HOLOCANVAS_KAFKA_BROKERS");
    const char *db_file_env  = getenv("HOLOCANVAS_SQLITE_PATH");

    ctx->kafka_brokers = strdup(kafka_env ? kafka_env : KAFKA_BROKERS_DEFAULT);
    ctx->db_file       = strdup(db_file_env ? db_file_env : DB_FILE_DEFAULT);

    return ctx->kafka_brokers && ctx->db_file;
}

/* ------------------------------------------------------------------------- */
/* SQLite persistence                                                        */
/* ------------------------------------------------------------------------- */

static bool init_sqlite(svc_ctx_t *ctx)
{
    if (sqlite3_open(ctx->db_file, &ctx->db) != SQLITE_OK) {
        log_err("sqlite", sqlite3_errmsg(ctx->db));
        return false;
    }

    char *errmsg = NULL;
    if (sqlite3_exec(ctx->db, "PRAGMA journal_mode=WAL;", NULL, NULL, &errmsg) != SQLITE_OK) {
        log_err("sqlite", errmsg);
        sqlite3_free(errmsg);
    }

    if (sqlite3_exec(ctx->db, SQL_CREATE_BALLOTS, NULL, NULL, &errmsg) != SQLITE_OK) {
        log_err("sqlite", errmsg);
        sqlite3_free(errmsg);
        return false;
    }
    if (sqlite3_exec(ctx->db, SQL_CREATE_RESULTS, NULL, NULL, &errmsg) != SQLITE_OK) {
        log_err("sqlite", errmsg);
        sqlite3_free(errmsg);
        return false;
    }
    return true;
}

static bool persist_ballot(sqlite3 *db, const ballot_t *ballot)
{
    const char *sql = "INSERT INTO ballots(id, proposal_id, voter_pk, choice, ts)"
                      " VALUES(?,?,?,?,?);";
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK)
        return false;

    sqlite3_bind_text(stmt, 1, ballot->id, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, ballot->proposal_id, -1, SQLITE_STATIC);
    sqlite3_bind_blob(stmt, 3, ballot->voter_pk, sizeof(ballot->voter_pk), SQLITE_STATIC);
    sqlite3_bind_int(stmt, 4, ballot->choice);
    sqlite3_bind_int64(stmt, 5, ballot->ts);

    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok && sqlite3_errcode(db) == SQLITE_CONSTRAINT_PRIMARYKEY) {
        /* duplicate ballot, ignore silently */
        ok = true;
    }
    sqlite3_finalize(stmt);
    return ok;
}

static bool update_tally(sqlite3 *db, const ballot_t *ballot)
{
    /* Upsert counts inside a transaction */
    const char *sql_begin = "BEGIN;";
    const char *sql_cnt   = "SELECT yes_cnt, no_cnt, abstain_cnt FROM results WHERE proposal_id=?;";
    const char *sql_ins   = "INSERT OR REPLACE INTO results(proposal_id, yes_cnt, no_cnt, abstain_cnt, finalized)"
                            " VALUES(?,?,?,?,0);";
    sqlite3_exec(db, sql_begin, NULL, NULL, NULL);

    sqlite3_stmt *stmt_cnt = NULL;
    if (sqlite3_prepare_v2(db, sql_cnt, -1, &stmt_cnt, NULL) != SQLITE_OK)
        goto fail;
    sqlite3_bind_text(stmt_cnt, 1, ballot->proposal_id, -1, SQLITE_STATIC);

    uint64_t yes=0, no=0, abst=0;
    if (sqlite3_step(stmt_cnt) == SQLITE_ROW) {
        yes  = sqlite3_column_int64(stmt_cnt, 0);
        no   = sqlite3_column_int64(stmt_cnt, 1);
        abst = sqlite3_column_int64(stmt_cnt, 2);
    }
    sqlite3_finalize(stmt_cnt);

    switch (ballot->choice) {
        case VOTE_CHOICE_YES:     yes++;  break;
        case VOTE_CHOICE_NO:      no++;   break;
        case VOTE_CHOICE_ABSTAIN: abst++; break;
    }

    sqlite3_stmt *stmt_ins = NULL;
    if (sqlite3_prepare_v2(db, sql_ins, -1, &stmt_ins, NULL) != SQLITE_OK)
        goto fail;

    sqlite3_bind_text(stmt_ins, 1, ballot->proposal_id, -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt_ins, 2, yes);
    sqlite3_bind_int64(stmt_ins, 3, no);
    sqlite3_bind_int64(stmt_ins, 4, abst);

    if (sqlite3_step(stmt_ins) != SQLITE_DONE)
        goto fail;

    sqlite3_finalize(stmt_ins);
    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    return true;

fail:
    sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
    return false;
}

static bool maybe_finalize_proposal(svc_ctx_t *ctx, const char *proposal_id)
{
    /* If no new ballots for FINALIZATION_DELAY_SEC, mark finalized */
    const char *sql_sel = "SELECT ts FROM ballots WHERE proposal_id=? ORDER BY ts DESC LIMIT 1;";
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(ctx->db, sql_sel, -1, &stmt, NULL) != SQLITE_OK)
        return false;
    sqlite3_bind_text(stmt, 1, proposal_id, -1, SQLITE_STATIC);

    int64_t last_ts = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW)
        last_ts = sqlite3_column_int64(stmt, 0);
    sqlite3_finalize(stmt);

    if (now_ms() - last_ts < FINALIZATION_DELAY_SEC * 1000)
        return false; /* still active */

    const char *sql_upd = "UPDATE results SET finalized=1 WHERE proposal_id=?;";
    if (sqlite3_prepare_v2(ctx->db, sql_upd, -1, &stmt, NULL) != SQLITE_OK)
        return false;
    sqlite3_bind_text(stmt, 1, proposal_id, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) != SQLITE_DONE) {
        sqlite3_finalize(stmt);
        return false;
    }
    sqlite3_finalize(stmt);

    /* fetch counts */
    const char *sql_get = "SELECT yes_cnt, no_cnt, abstain_cnt FROM results WHERE proposal_id=?;";
    if (sqlite3_prepare_v2(ctx->db, sql_get, -1, &stmt, NULL) != SQLITE_OK)
        return false;
    sqlite3_bind_text(stmt, 1, proposal_id, -1, SQLITE_STATIC);

    uint64_t yes=0,no=0,abst=0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        yes  = sqlite3_column_int64(stmt, 0);
        no   = sqlite3_column_int64(stmt, 1);
        abst = sqlite3_column_int64(stmt, 2);
    }
    sqlite3_finalize(stmt);

    emit_result(ctx, proposal_id, yes, no, abst);
    return true;
}

/* ------------------------------------------------------------------------- */
/* OpenSSL crypto                                                            */
/* ------------------------------------------------------------------------- */

static bool verify_ballot_signature(const ballot_t *ballot)
{
    /* Verify using secp256k1 SHA256(message) ECDSA signatures */
    bool ok = false;
    EVP_PKEY *pkey = NULL;
    EVP_MD_CTX *md_ctx = NULL;
    EC_KEY *ec_key = NULL;
    const unsigned char *pub_ptr = ballot->voter_pk;

    ec_key = o2i_ECPublicKey(NULL, &pub_ptr, sizeof(ballot->voter_pk));
    if (!ec_key) {
        log_err("crypto", "invalid public key");
        goto end;
    }
    pkey = EVP_PKEY_new();
    if (!EVP_PKEY_set1_EC_KEY(pkey, ec_key))
        goto end;

    md_ctx = EVP_MD_CTX_new();
    if (!md_ctx)
        goto end;

    if (EVP_DigestVerifyInit(md_ctx, NULL, EVP_sha256(), NULL, pkey) != 1)
        goto end;

    /* Construct message: proposal_id || choice || ts */
    unsigned char msg[128];
    int msg_len = snprintf((char*)msg, sizeof(msg), "%s|%d|%lld",
                           ballot->proposal_id, ballot->choice, (long long)ballot->ts);

    if (EVP_DigestVerify(md_ctx, ballot->sig, ballot->sig_len,
                         msg, (size_t)msg_len) == 1)
        ok = true;

end:
    EVP_MD_CTX_free(md_ctx);
    EVP_PKEY_free(pkey);
    EC_KEY_free(ec_key);
    return ok;
}

/* ------------------------------------------------------------------------- */
/* Kafka                                                                     */
/* ------------------------------------------------------------------------- */

static bool init_kafka(svc_ctx_t *ctx)
{
    char errstr[512];

    /* --- Producer --- */
    rd_kafka_conf_t *kconf_p = rd_kafka_conf_new();
    rd_kafka_conf_set(kconf_p, "bootstrap.servers", ctx->kafka_brokers, errstr, sizeof(errstr));

    ctx->rk_producer = rd_kafka_new(RD_KAFKA_PRODUCER, kconf_p, errstr, sizeof(errstr));
    if (!ctx->rk_producer) {
        log_err("kafka", errstr);
        return false;
    }
    ctx->rkt_producer = rd_kafka_topic_new(ctx->rk_producer, KAFKA_TOPIC_RESULTS, NULL);

    /* --- Consumer --- */
    rd_kafka_conf_t *kconf_c = rd_kafka_conf_new();
    rd_kafka_conf_set(kconf_c, "group.id", "governance-hall", errstr, sizeof(errstr));
    rd_kafka_conf_set(kconf_c, "enable.auto.commit", "true", errstr, sizeof(errstr));
    rd_kafka_conf_set(kconf_c, "bootstrap.servers", ctx->kafka_brokers, errstr, sizeof(errstr));

    ctx->rk_consumer = rd_kafka_new(RD_KAFKA_CONSUMER, kconf_c, errstr, sizeof(errstr));
    if (!ctx->rk_consumer) {
        log_err("kafka", errstr);
        return false;
    }

    rd_kafka_poll_set_consumer(ctx->rk_consumer);
    ctx->rkt_consumer = rd_kafka_topic_new(ctx->rk_consumer, KAFKA_TOPIC_VOTES, NULL);

    rd_kafka_resp_err_t err = rd_kafka_subscribe(ctx->rk_consumer, 
                              rd_kafka_topic_partition_list_new(1));
    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        log_err("kafka", rd_kafka_err2str(err));
        return false;
    }

    return true;
}

static void emit_result(svc_ctx_t *ctx, const char *proposal_id,
                        uint64_t yes_cnt, uint64_t no_cnt, uint64_t abstain_cnt)
{
    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "proposal_id", proposal_id);
    cJSON_AddNumberToObject(json, "yes", (double)yes_cnt);
    cJSON_AddNumberToObject(json, "no", (double)no_cnt);
    cJSON_AddNumberToObject(json, "abstain", (double)abstain_cnt);
    cJSON_AddNumberToObject(json, "ts", (double)now_ms());

    char *payload = cJSON_PrintUnformatted(json);

    rd_kafka_produce(ctx->rkt_producer, RD_KAFKA_PARTITION_UA,
                     RD_KAFKA_MSG_F_FREE,
                     payload, strlen(payload),
                     NULL, 0,
                     NULL);
    rd_kafka_poll(ctx->rk_producer, 0); /* serve delivery reports */

    log_info("Finalized proposal %s  (yes=%llu no=%llu abstain=%llu)",
             proposal_id,
             (unsigned long long)yes_cnt,
             (unsigned long long)no_cnt,
             (unsigned long long)abstain_cnt);

    cJSON_Delete(json);
}

/* ------------------------------------------------------------------------- */
/* Poll loop                                                                 */
/* ------------------------------------------------------------------------- */

static void poll_loop(svc_ctx_t *ctx)
{
    log_info("Entering poll loop…");
    while (!atomic_load(&g_terminate)) {
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(ctx->rk_consumer, 100 /*ms*/);
        if (!rkmsg) continue;

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                rd_kafka_message_destroy(rkmsg);
                continue;
            }
            log_err("kafka", rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Parse JSON */
        cJSON *json = cJSON_ParseWithLength((const char*)rkmsg->payload, rkmsg->len);
        if (!json) {
            log_err("json", "invalid vote payload");
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        ballot_t ballot = {0};
        const cJSON *id         = cJSON_GetObjectItem(json, "id");
        const cJSON *proposal   = cJSON_GetObjectItem(json, "proposal_id");
        const cJSON *voter_pk   = cJSON_GetObjectItem(json, "voter_pk");
        const cJSON *choice     = cJSON_GetObjectItem(json, "choice");
        const cJSON *ts         = cJSON_GetObjectItem(json, "ts");
        const cJSON *sig_hex    = cJSON_GetObjectItem(json, "sig");

        bool fields_ok = cJSON_IsString(id) && cJSON_IsString(proposal) &&
                         cJSON_IsString(voter_pk) && cJSON_IsNumber(choice) &&
                         cJSON_IsNumber(ts) && cJSON_IsString(sig_hex);

        if (!fields_ok) {
            log_err("json", "missing fields in ballot");
            cJSON_Delete(json);
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        strncpy(ballot.id, id->valuestring, sizeof(ballot.id)-1);
        strncpy(ballot.proposal_id, proposal->valuestring, sizeof(ballot.proposal_id)-1);
        ballot.choice = (vote_choice_e)cJSON_GetNumberValue(choice);
        ballot.ts     = (int64_t)cJSON_GetNumberValue(ts);

        /* decode public key and signature from hex */
        size_t pk_len = strlen(voter_pk->valuestring)/2;
        for (size_t i=0;i<pk_len && i<sizeof(ballot.voter_pk);i++)
            sscanf(&voter_pk->valuestring[i*2], "%2hhx", &ballot.voter_pk[i]);

        ballot.sig_len = strlen(sig_hex->valuestring)/2;
        for (size_t i=0;i<ballot.sig_len && i<sizeof(ballot.sig);i++)
            sscanf(&sig_hex->valuestring[i*2], "%2hhx", &ballot.sig[i]);

        cJSON_Delete(json);
        rd_kafka_message_destroy(rkmsg);

        if (!verify_ballot_signature(&ballot)) {
            log_err("crypto", "signature verification failed");
            continue;
        }
        if (!persist_ballot(ctx->db, &ballot)) {
            log_err("sqlite", "failed to persist ballot");
            continue;
        }
        if (!update_tally(ctx->db, &ballot)) {
            log_err("sqlite", "failed to update tally");
            continue;
        }
        maybe_finalize_proposal(ctx, ballot.proposal_id);
    }
}

/* ------------------------------------------------------------------------- */
/* Cleanup                                                                   */
/* ------------------------------------------------------------------------- */

static void cleanup(svc_ctx_t *ctx)
{
    if (ctx->rk_consumer) {
        rd_kafka_consumer_close(ctx->rk_consumer);
        rd_kafka_destroy(ctx->rk_consumer);
    }
    if (ctx->rk_producer) {
        rd_kafka_flush(ctx->rk_producer, 5000);
        rd_kafka_destroy(ctx->rk_producer);
    }
    if (ctx->db) sqlite3_close(ctx->db);
    free(ctx->kafka_brokers);
    free(ctx->db_file);
}
```