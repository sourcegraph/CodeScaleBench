/*
 * HoloCanvas – Governance Hall
 * ----------------------------------
 *  proposal_lifecycle.c
 *
 *  Lifecycle state-machine for DAO governance proposals.
 *
 *  Responsibilities:
 *      •  Persist and query proposal records (SQLite backend).
 *      •  Enforce state-transition rules (draft → active → queued → executed /
 *         cancelled / expired).
 *      •  Maintain vote tallies and quorum checks.
 *      •  Publish domain events to the platform event-bus (Kafka).
 *      •  Provide a thread-safe public API for other subsystems (gRPC façade).
 *
 *  NOTE:  This file purposefully depends only on stable C libraries and a small
 *         set of internal headers. External dependencies (SQLite, rdkafka) are
 *         linked in the CMakeLists.txt of Governance-Hall.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <time.h>
#include <pthread.h>
#include <errno.h>
#include <inttypes.h>

#include <sqlite3.h>               /* Persistence layer */
#include <rdkafka.h>               /* Kafka C/C++ client (librdkafka) */

#include "proposal_lifecycle.h"    /* Public header for this compilation unit  */
#include "event_bus.h"             /* Thin wrapper around Kafka publishing     */
#include "gh_config.h"             /* Governance-Hall service configuration    */
#include "util/log.h"              /* Project-wide logging abstraction         */
#include "util/hash.h"             /* Blake2 / SHA256 helpers                  */


/* -------------------------------------------------------------------------- */
/*  Constants & Macros                                                        */
/* -------------------------------------------------------------------------- */

#define SQL_FILE               "governance.db"
#define SQL_TIMEOUT_MS         250          /* Busy timeout for SQLite        */
#define PROPOSAL_TABLE_SCHEMA                                            \
    "CREATE TABLE IF NOT EXISTS proposals ("                             \
    "   id              INTEGER PRIMARY KEY AUTOINCREMENT, "             \
    "   title           TEXT    NOT NULL, "                              \
    "   description     TEXT, "                                          \
    "   creator         TEXT    NOT NULL, "                              \
    "   ts_created      INTEGER NOT NULL, "                              \
    "   ts_active_from  INTEGER, "                                       \
    "   ts_expires_at   INTEGER, "                                       \
    "   state           INTEGER NOT NULL, "                              \
    "   vote_for        INTEGER DEFAULT 0, "                             \
    "   vote_against    INTEGER DEFAULT 0, "                             \
    "   vote_abstain    INTEGER DEFAULT 0, "                             \
    "   voting_power    INTEGER DEFAULT 0 "                              \
    "); "

#define VOTING_WINDOW_SECONDS  (60 * 60 * 24 * 3) /* 72h voting period  */
#define EXECUTION_DELAY_SEC    (60 * 10)          /* 10 minutes timelock */
#define QUORUM_PERCENT_X100    4000               /* 40% of voting power */
#define QUORUM_DENOM_X100      10000

/* Domain-event routing keys ------------------------------------------------ */
#define TOPIC_PROPOSAL_EVENT    "hc.governance.proposal"

/* -------------------------------------------------------------------------- */
/*  Module-scope Statics                                                      */
/* -------------------------------------------------------------------------- */

static sqlite3        *s_db          = NULL;
static pthread_mutex_t s_db_mutex    = PTHREAD_MUTEX_INITIALIZER;
static pthread_rwlock_t s_kafka_lock = PTHREAD_RWLOCK_INITIALIZER;
static rd_kafka_t     *s_kafka       = NULL;
static rd_kafka_topic_t *s_kafka_topic = NULL;

/* -------------------------------------------------------------------------- */
/*  Internal helpers                                                          */
/* -------------------------------------------------------------------------- */

static int db_open(const char *path)
{
    if (sqlite3_open(path, &s_db) != SQLITE_OK) {
        log_error("SQLite open failed: %s", sqlite3_errmsg(s_db));
        return -1;
    }

    sqlite3_busy_timeout(s_db, SQL_TIMEOUT_MS);

    char *errmsg = NULL;
    if (sqlite3_exec(s_db, PROPOSAL_TABLE_SCHEMA, NULL, NULL, &errmsg) != SQLITE_OK) {
        log_error("SQLite schema init failed: %s", errmsg);
        sqlite3_free(errmsg);
        sqlite3_close(s_db);
        s_db = NULL;
        return -1;
    }
    return 0;
}

static void db_close(void)
{
    if (s_db) {
        sqlite3_close(s_db);
        s_db = NULL;
    }
}

static bool publish_event(const char *key, const char *payload)
{
    bool ok = false;

    pthread_rwlock_rdlock(&s_kafka_lock);
    if (!s_kafka_topic) {
        pthread_rwlock_unlock(&s_kafka_lock);
        return false;
    }

    if (rd_kafka_produce(
            s_kafka_topic,
            RD_KAFKA_PARTITION_UA,
            RD_KAFKA_MSG_F_COPY,
            (void*)payload,
            strlen(payload),
            key,
            key ? strlen(key) : 0,
            NULL) == 0) {
        ok = true;
    } else {
        log_warn("Kafka produce failed: %s",
                 rd_kafka_err2str(rd_kafka_last_error()));
    }

    pthread_rwlock_unlock(&s_kafka_lock);
    return ok;
}

/* Convert ProposalState enum to string for logging / JSON. */
static const char *state_to_str(ProposalState state)
{
    switch (state) {
        case PROPOSAL_STATE_DRAFT:            return "DRAFT";
        case PROPOSAL_STATE_ACTIVE_VOTING:    return "ACTIVE_VOTING";
        case PROPOSAL_STATE_QUEUED_FOR_EXEC:  return "QUEUED_FOR_EXECUTION";
        case PROPOSAL_STATE_EXECUTED:         return "EXECUTED";
        case PROPOSAL_STATE_CANCELLED:        return "CANCELLED";
        case PROPOSAL_STATE_EXPIRED:          return "EXPIRED";
        default:                              return "UNKNOWN";
    }
}

/* Serialize a proposal row into a minimal JSON payload. (stack-allocated)    */
static size_t proposal_to_json(char *dst, size_t max, const ProposalRecord *r)
{
    return (size_t)snprintf(dst, max,
        "{\"id\":%" PRIu64 ",\"title\":\"%s\",\"state\":\"%s\",\"for\":%"
        PRIu64 ",\"against\":%" PRIu64 ",\"abstain\":%" PRIu64 "}",
        r->id, r->title, state_to_str(r->state),
        r->vote_for, r->vote_against, r->vote_abstain);
}

/* -------------------------------------------------------------------------- */
/*  API Implementation                                                        */
/* -------------------------------------------------------------------------- */

int proposal_lifecycle_init(const GhConfig *cfg)
{
    if (!cfg) {
        log_error("Config pointer is NULL");
        return -1;
    }
    /* ---- DB ---- */
    if (db_open(SQL_FILE) != 0)
        return -1;

    /* ---- Kafka ---- */
    char errstr[256];
    rd_kafka_conf_t *rk_conf = rd_kafka_conf_new();
    if (rd_kafka_conf_set(rk_conf, "bootstrap.servers",
                          cfg->kafka_brokers, errstr, sizeof(errstr)) !=
        RD_KAFKA_CONF_OK) {
        log_error("Kafka config error: %s", errstr);
        return -1;
    }

    s_kafka = rd_kafka_new(RD_KAFKA_PRODUCER, rk_conf, errstr, sizeof(errstr));
    if (!s_kafka) {
        log_error("Kafka init failed: %s", errstr);
        return -1;
    }

    s_kafka_topic = rd_kafka_topic_new(s_kafka, TOPIC_PROPOSAL_EVENT, NULL);
    if (!s_kafka_topic) {
        log_error("Kafka topic error: %s",
                  rd_kafka_err2str(rd_kafka_last_error()));
        return -1;
    }

    log_info("proposal_lifecycle initialized (DB=%s, Kafka=%s)",
             SQL_FILE, cfg->kafka_brokers);
    return 0;
}

void proposal_lifecycle_shutdown(void)
{
    pthread_rwlock_wrlock(&s_kafka_lock);
    if (s_kafka_topic) {
        rd_kafka_topic_destroy(s_kafka_topic);
        s_kafka_topic = NULL;
    }
    if (s_kafka) {
        rd_kafka_flush(s_kafka, 3000);
        rd_kafka_destroy(s_kafka);
        s_kafka = NULL;
    }
    pthread_rwlock_unlock(&s_kafka_lock);

    db_close();
    log_info("proposal_lifecycle shutdown complete");
}

int proposal_create(const ProposalSpec *spec, ProposalID *out_id)
{
    if (!spec || !out_id)
        return EINVAL;

    int rc = 0;
    const char *sql =
        "INSERT INTO proposals (title, description, creator, ts_created, "
        "ts_active_from, ts_expires_at, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?);";

    uint64_t now = (uint64_t)time(NULL);
    uint64_t active_from = now; /* immediate activation */
    uint64_t expires_at  = active_from + VOTING_WINDOW_SECONDS;

    pthread_mutex_lock(&s_db_mutex);

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(s_db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
        goto finish;
    }

    sqlite3_bind_text(stmt,  1, spec->title, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt,  2, spec->description, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt,  3, spec->creator, -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, (sqlite3_int64)now);
    sqlite3_bind_int64(stmt, 5, (sqlite3_int64)active_from);
    sqlite3_bind_int64(stmt, 6, (sqlite3_int64)expires_at);
    sqlite3_bind_int(stmt,   7, PROPOSAL_STATE_ACTIVE_VOTING);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        log_error("SQLite insert failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
    } else {
        *out_id = (ProposalID)sqlite3_last_insert_rowid(s_db);
        log_debug("Proposal %" PRIu64 " created", *out_id);
    }

finish:
    if (stmt)
        sqlite3_finalize(stmt);

    pthread_mutex_unlock(&s_db_mutex);

    if (rc == 0) {
        /* Emit proposal_created event */
        char json[256];
        ProposalRecord tmp = {
            .id = *out_id,
            .title = (char*)spec->title,
            .state = PROPOSAL_STATE_ACTIVE_VOTING,
            .vote_for = 0,
            .vote_against = 0,
            .vote_abstain = 0
        };
        size_t len = proposal_to_json(json, sizeof(json), &tmp);
        json[len] = '\0';

        publish_event("proposal_created", json);
    }

    return rc;
}

static int fetch_proposal(ProposalID id, ProposalRecord *out)
{
    const char *sql =
        "SELECT id, title, state, vote_for, vote_against, vote_abstain, "
        "voting_power, ts_expires_at "
        "FROM proposals WHERE id = ?;";

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(s_db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        return EIO;
    }

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)id);
    rc = sqlite3_step(stmt);

    if (rc == SQLITE_ROW) {
        out->id            = (uint64_t)sqlite3_column_int64(stmt, 0);
        strncpy(out->title, (const char*)sqlite3_column_text(stmt, 1),
                sizeof(out->title) - 1);
        out->state         = (ProposalState)sqlite3_column_int(stmt, 2);
        out->vote_for      = (uint64_t)sqlite3_column_int64(stmt, 3);
        out->vote_against  = (uint64_t)sqlite3_column_int64(stmt, 4);
        out->vote_abstain  = (uint64_t)sqlite3_column_int64(stmt, 5);
        out->voting_power  = (uint64_t)sqlite3_column_int64(stmt, 6);
        out->ts_expires_at = (uint64_t)sqlite3_column_int64(stmt, 7);
        rc = 0;
    } else {
        rc = ENOENT;
    }

    sqlite3_finalize(stmt);
    return rc;
}

int proposal_cast_vote(ProposalID id,
                       const char *voter_addr,
                       VoteChoice choice,
                       uint64_t voting_power)
{
    (void)voter_addr; /* For MVP we skip per-voter storage */
    if (choice == VOTE_CHOICE_NONE || voting_power == 0)
        return EINVAL;

    int rc = 0;
    pthread_mutex_lock(&s_db_mutex);

    /* Fetch current state to guard business rules. */
    ProposalRecord rec = {0};
    rc = fetch_proposal(id, &rec);
    if (rc != 0) {
        pthread_mutex_unlock(&s_db_mutex);
        return rc;
    }
    if (rec.state != PROPOSAL_STATE_ACTIVE_VOTING) {
        pthread_mutex_unlock(&s_db_mutex);
        return EPERM;
    }

    const char *sql =
        "UPDATE proposals SET "
        "vote_for     = vote_for     + ?, "
        "vote_against = vote_against + ?, "
        "vote_abstain = vote_abstain + ?, "
        "voting_power = voting_power + ? "
        "WHERE id = ?;";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(s_db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
        goto finish;
    }

    int64_t inc_for     = (choice == VOTE_CHOICE_FOR)     ? (int64_t)voting_power : 0;
    int64_t inc_against = (choice == VOTE_CHOICE_AGAINST) ? (int64_t)voting_power : 0;
    int64_t inc_abstain = (choice == VOTE_CHOICE_ABSTAIN) ? (int64_t)voting_power : 0;

    sqlite3_bind_int64(stmt, 1, inc_for);
    sqlite3_bind_int64(stmt, 2, inc_against);
    sqlite3_bind_int64(stmt, 3, inc_abstain);
    sqlite3_bind_int64(stmt, 4, (int64_t)voting_power);
    sqlite3_bind_int64(stmt, 5, (int64_t)id);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        log_error("SQLite vote update failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
    } else {
        log_debug("Vote registered (proposal=%" PRIu64 ", power=%" PRIu64 ")",
                  id, voting_power);
    }

finish:
    if (stmt)
        sqlite3_finalize(stmt);
    pthread_mutex_unlock(&s_db_mutex);

    /* Emit event regardless of success to allow observers for duplicates */
    if (rc == 0) {
        char payload[256];
        rec.vote_for     += inc_for;
        rec.vote_against += inc_against;
        rec.vote_abstain += inc_abstain;
        size_t n = proposal_to_json(payload, sizeof(payload), &rec);
        payload[n] = '\0';
        publish_event("proposal_vote", payload);
    }
    return rc;
}

/* Evaluate quorum + majority to decide if proposal succeeded. */
static ProposalOutcome evaluate_outcome(const ProposalRecord *rec)
{
    uint64_t total_votes = rec->vote_for + rec->vote_against + rec->vote_abstain;
    if (total_votes == 0)
        return OUTCOME_FAIL_NO_QUORUM;

    uint64_t quorum = (rec->voting_power * QUORUM_PERCENT_X100) / QUORUM_DENOM_X100;
    if (total_votes < quorum)
        return OUTCOME_FAIL_NO_QUORUM;

    if (rec->vote_for > rec->vote_against)
        return OUTCOME_SUCCESS;

    return OUTCOME_FAIL_REJECTED;
}

/*
 * Execute state machine tick. Call periodically (e.g., every minute) from
 * the governance main loop or a cron thread.
 */
int proposal_lifecycle_tick(void)
{
    uint64_t now = (uint64_t)time(NULL);
    pthread_mutex_lock(&s_db_mutex);

    /* 1. Move expired voting proposals to QUEUED / EXPIRED ----------------- */
    const char *sql_select =
        "SELECT id FROM proposals "
        "WHERE state = ? AND ts_expires_at <= ?;";

    sqlite3_stmt *select_stmt = NULL;
    if (sqlite3_prepare_v2(s_db, sql_select, -1, &select_stmt, NULL) != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        pthread_mutex_unlock(&s_db_mutex);
        return EIO;
    }

    sqlite3_bind_int(select_stmt, 1, PROPOSAL_STATE_ACTIVE_VOTING);
    sqlite3_bind_int64(select_stmt, 2, (sqlite3_int64)now);

    int rc = 0;
    while ((rc = sqlite3_step(select_stmt)) == SQLITE_ROW) {
        ProposalID id = (ProposalID)sqlite3_column_int64(select_stmt, 0);

        ProposalRecord rec = {0};
        fetch_proposal(id, &rec);

        ProposalOutcome outcome = evaluate_outcome(&rec);
        ProposalState next_state =
            (outcome == OUTCOME_SUCCESS) ? PROPOSAL_STATE_QUEUED_FOR_EXEC
                                         : PROPOSAL_STATE_EXPIRED;

        const char *sql_upd = "UPDATE proposals SET state = ? WHERE id = ?;";
        sqlite3_stmt *upd_stmt = NULL;
        if (sqlite3_prepare_v2(s_db, sql_upd, -1, &upd_stmt, NULL) != SQLITE_OK) {
            log_error("SQLite prepare failed (update): %s",
                      sqlite3_errmsg(s_db));
            continue;
        }
        sqlite3_bind_int(upd_stmt, 1, next_state);
        sqlite3_bind_int64(upd_stmt, 2, (sqlite3_int64)id);

        if (sqlite3_step(upd_stmt) != SQLITE_DONE) {
            log_error("SQLite update failed: %s", sqlite3_errmsg(s_db));
        } else {
            log_info("Proposal %" PRIu64 " transitioned to %s",
                     id, state_to_str(next_state));

            char payload[256];
            rec.state = next_state;
            size_t len = proposal_to_json(payload, sizeof(payload), &rec);
            payload[len] = '\0';
            publish_event("proposal_state_changed", payload);
        }
        sqlite3_finalize(upd_stmt);
    }
    sqlite3_finalize(select_stmt);

    /* 2. Execute queued proposals whose timelock passed -------------------- */
    const char *sql_queued =
        "SELECT id FROM proposals "
        "WHERE state = ? AND ts_expires_at + ? <= ?;";

    sqlite3_stmt *q_stmt = NULL;
    if (sqlite3_prepare_v2(s_db, sql_queued, -1, &q_stmt, NULL) != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        pthread_mutex_unlock(&s_db_mutex);
        return EIO;
    }

    sqlite3_bind_int(q_stmt, 1, PROPOSAL_STATE_QUEUED_FOR_EXEC);
    sqlite3_bind_int64(q_stmt, 2, (sqlite3_int64)EXECUTION_DELAY_SEC);
    sqlite3_bind_int64(q_stmt, 3, (sqlite3_int64)now);

    while ((rc = sqlite3_step(q_stmt)) == SQLITE_ROW) {
        ProposalID id = (ProposalID)sqlite3_column_int64(q_stmt, 0);

        /* In a real system, we would call into smart-contract execution here. */
        /* For this micro-service dashed implementation, we simply mark EXECUTED. */

        const char *sql_exec = "UPDATE proposals SET state = ? WHERE id = ?;";
        sqlite3_stmt *e_stmt = NULL;
        if (sqlite3_prepare_v2(s_db, sql_exec, -1, &e_stmt, NULL) != SQLITE_OK) {
            log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
            continue;
        }

        sqlite3_bind_int(e_stmt, 1, PROPOSAL_STATE_EXECUTED);
        sqlite3_bind_int64(e_stmt, 2, (sqlite3_int64)id);

        if (sqlite3_step(e_stmt) != SQLITE_DONE) {
            log_error("SQLite execution update failed: %s", sqlite3_errmsg(s_db));
        } else {
            log_info("Proposal %" PRIu64 " executed", id);

            ProposalRecord rec = {0};
            fetch_proposal(id, &rec);
            char payload[256];
            size_t len = proposal_to_json(payload, sizeof(payload), &rec);
            payload[len] = '\0';
            publish_event("proposal_executed", payload);
        }
        sqlite3_finalize(e_stmt);
    }

    sqlite3_finalize(q_stmt);
    pthread_mutex_unlock(&s_db_mutex);
    return 0;
}

int proposal_cancel(ProposalID id)
{
    int rc = 0;
    pthread_mutex_lock(&s_db_mutex);

    ProposalRecord rec = {0};
    rc = fetch_proposal(id, &rec);
    if (rc != 0) {
        pthread_mutex_unlock(&s_db_mutex);
        return rc;
    }

    if (rec.state == PROPOSAL_STATE_EXECUTED ||
        rec.state == PROPOSAL_STATE_CANCELLED ||
        rec.state == PROPOSAL_STATE_EXPIRED) {
        pthread_mutex_unlock(&s_db_mutex);
        return EPERM;
    }

    const char *sql =
        "UPDATE proposals SET state = ? WHERE id = ?;";
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(s_db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        log_error("SQLite prepare failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
        goto finish;
    }

    sqlite3_bind_int(stmt, 1, PROPOSAL_STATE_CANCELLED);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)id);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        log_error("SQLite cancel update failed: %s", sqlite3_errmsg(s_db));
        rc = EIO;
    } else {
        log_info("Proposal %" PRIu64 " cancelled", id);
    }

finish:
    if (stmt)
        sqlite3_finalize(stmt);

    pthread_mutex_unlock(&s_db_mutex);

    if (rc == 0) {
        char payload[256];
        rec.state = PROPOSAL_STATE_CANCELLED;
        size_t len = proposal_to_json(payload, sizeof(payload), &rec);
        payload[len] = '\0';
        publish_event("proposal_cancelled", payload);
    }
    return rc;
}

int proposal_get(ProposalID id, ProposalRecord *out)
{
    if (!out)
        return EINVAL;
    pthread_mutex_lock(&s_db_mutex);
    int rc = fetch_proposal(id, out);
    pthread_mutex_unlock(&s_db_mutex);
    return rc;
}

/* -------------------------------------------------------------------------- */
/*  Unit-test hooks (compile with –DUNIT_TEST)                                */
/* -------------------------------------------------------------------------- */
#ifdef UNIT_TEST
#include "minunit.h"
static char *all_tests(void)
{
    /* Minimal coverage test for proposal CRUD */
    GhConfig cfg = {.kafka_brokers = "localhost:9092"};
    mu_assert("init failed", proposal_lifecycle_init(&cfg) == 0);

    ProposalSpec spec = {
        .title = "Test Proposal",
        .description = "Lorem ipsum",
        .creator = "0xdeadbeef"
    };
    ProposalID id = 0;
    mu_assert("create failed", proposal_create(&spec, &id) == 0);

    mu_assert("invalid id", id > 0);

    ProposalRecord rec = {0};
    mu_assert("get failed", proposal_get(id, &rec) == 0);
    mu_assert("state mismatch", rec.state == PROPOSAL_STATE_ACTIVE_VOTING);

    mu_assert("vote failed",
              proposal_cast_vote(id, "0xcafe", VOTE_CHOICE_FOR, 100) == 0);

    proposal_lifecycle_shutdown();
    return 0;
}

int main(void)
{
    char *result = all_tests();
    if (result != 0) {
        printf("FAILED: %s\n", result);
    } else {
        printf("ALL TESTS PASSED\n");
    }
    return result != 0;
}
#endif /* UNIT_TEST */

/* -------------------------------------------------------------------------- */
/*  End of file                                                               */
/* -------------------------------------------------------------------------- */
