/**
 * EduPay Ledger Academy
 * risk_assessment_projector.c
 *
 * Description:
 *   CQRS read-model projector responsible for materialising real-time
 *   risk-assessment aggregates from the immutable event store.
 *
 *   Compile with:
 *       gcc -Wall -Wextra -pedantic -std=c11 \
 *           -pthread -lsqlite3 -ljansson \
 *           -o risk_assessment_projector risk_assessment_projector.c
 *
 * Author:
 *   EduPay Ledger Academy Core Team
 *   (c) 2024. Licensed under MIT.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>
#include <pthread.h>

#include <sqlite3.h>
#include <jansson.h>

/* ---------- Constants ---------------------------------------------------- */

#define RAP_SCHEMA_VERSION            1
#define HOURS24_IN_SECONDS            (24 * 60 * 60)
#define DEFAULT_RISK_THRESHOLD        80  /* Arbitrary risk score for flag */

/* ---------- Event Definitions ------------------------------------------- */

/* Keep event-type names in sync with the canonical domain schema */
typedef enum {
    EVT_TRANSACTION_INITIATED,
    EVT_TRANSACTION_AUTHORIZED,
    EVT_TRANSACTION_SETTLED,
    EVT_RISK_MANUALLY_FLAGGED,
    EVT_UNKNOWN
} event_type_t;

typedef struct {
    uint64_t    transaction_id;
    char        account_id[64];
    double      amount;
    char        currency[4];        /* ISO-4217 alpha-3 */
    time_t      occurred_at;        /* Unix epoch seconds */
    json_t     *json_meta;          /* Optional metadata envelope */
    event_type_t type;
} event_t;

/* ---------- Projection Store -------------------------------------------- */

typedef struct {
    sqlite3     *db;
    pthread_mutex_t lock; /* Guards sqlite API — single threaded connection */
} rap_store_t;

/* ---------- Public API --------------------------------------------------- */

bool rap_store_open(rap_store_t *store, const char *db_path);
void rap_store_close(rap_store_t *store);
bool rap_handle_event(rap_store_t *store, const event_t *evt);

/* ---------- Internal helpers (static) ----------------------------------- */

static bool  rap_apply_transaction(rap_store_t *, const event_t *);
static bool  rap_apply_manual_flag(rap_store_t *, const event_t *);
static bool  rap_recalculate_risk(rap_store_t *, const char *account_id);
static bool  rap_init_schema(sqlite3 *db);
static event_type_t rap_get_type_from_str(const char *name);

/* ------------------------------------------------------------------------ */
/*                            Implementation                                */
/* ------------------------------------------------------------------------ */

bool rap_store_open(rap_store_t *store, const char *db_path)
{
    if (!store) return false;
    memset(store, 0, sizeof(*store));

    if (sqlite3_open_v2(db_path, &store->db,
                        SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                        NULL) != SQLITE_OK)
    {
        fprintf(stderr, "SQLite open error: %s\n", sqlite3_errmsg(store->db));
        return false;
    }

    /* Foreign-keys and WAL mode for concurrency */
    sqlite3_exec(store->db, "PRAGMA foreign_keys = ON;", NULL, NULL, NULL);
    sqlite3_exec(store->db, "PRAGMA journal_mode = WAL;", NULL, NULL, NULL);

    if (!rap_init_schema(store->db)) {
        sqlite3_close(store->db);
        return false;
    }

    if (pthread_mutex_init(&store->lock, NULL) != 0) {
        sqlite3_close(store->db);
        return false;
    }

    return true;
}

void rap_store_close(rap_store_t *store)
{
    if (!store || !store->db) return;

    pthread_mutex_lock(&store->lock);
    sqlite3_close(store->db);
    pthread_mutex_unlock(&store->lock);
    pthread_mutex_destroy(&store->lock);

    store->db = NULL;
}

/* Main dispatcher  ------------------------------------------------------- */
bool rap_handle_event(rap_store_t *store, const event_t *evt)
{
    if (!store || !evt) return false;

    bool rc = false;
    pthread_mutex_lock(&store->lock);

    switch (evt->type) {
        case EVT_TRANSACTION_INITIATED:
        case EVT_TRANSACTION_AUTHORIZED:
        case EVT_TRANSACTION_SETTLED:
            rc = rap_apply_transaction(store, evt);
            break;

        case EVT_RISK_MANUALLY_FLAGGED:
            rc = rap_apply_manual_flag(store, evt);
            break;

        default:
            fprintf(stderr, "Unknown event type encountered\n");
            rc = false;
    }

    pthread_mutex_unlock(&store->lock);
    return rc;
}

/* ---------- Event Applicators ------------------------------------------- */

static bool rap_apply_transaction(rap_store_t *store, const event_t *evt)
{
    /* Insert row into rolling_transactions table */
    const char *sql_insert =
        "INSERT INTO rolling_transactions "
        "(transaction_id, account_id, amount, currency, occurred_at) "
        "VALUES (?, ?, ?, ?, ?);";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(store->db, sql_insert, -1, &stmt, NULL) != SQLITE_OK) {
        fprintf(stderr, "SQLite prepare error: %s\n", sqlite3_errmsg(store->db));
        return false;
    }

    sqlite3_bind_int64 (stmt, 1, (sqlite3_int64)evt->transaction_id);
    sqlite3_bind_text  (stmt, 2, evt->account_id, -1, SQLITE_STATIC);
    sqlite3_bind_double(stmt, 3, evt->amount);
    sqlite3_bind_text  (stmt, 4, evt->currency, -1, SQLITE_STATIC);
    sqlite3_bind_int64 (stmt, 5, (sqlite3_int64)evt->occurred_at);

    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok) {
        fprintf(stderr, "SQLite insert error: %s\n", sqlite3_errmsg(store->db));
    }
    sqlite3_finalize(stmt);

    /* House-keeping: purge rolling window > 24h */
    const char *sql_purge =
        "DELETE FROM rolling_transactions "
        "WHERE occurred_at < strftime('%s','now') - ?1;";

    if (sqlite3_prepare_v2(store->db, sql_purge, -1, &stmt, NULL) == SQLITE_OK) {
        sqlite3_bind_int(stmt, 1, HOURS24_IN_SECONDS);
        sqlite3_step(stmt);
    }
    sqlite3_finalize(stmt);

    /* Recalculate risk */
    if (ok) {
        ok = rap_recalculate_risk(store, evt->account_id);
    }
    return ok;
}

static bool rap_apply_manual_flag(rap_store_t *store, const event_t *evt)
{
    const char *sql =
        "UPDATE risk_metrics "
        "SET flagged = 1, flag_reason = 'Manual user flag', "
        "    updated_at = strftime('%s','now') "
        "WHERE account_id = ?;";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(store->db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        fprintf(stderr, "SQLite prepare error: %s\n", sqlite3_errmsg(store->db));
        return false;
    }
    sqlite3_bind_text(stmt, 1, evt->account_id, -1, SQLITE_STATIC);
    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok) fprintf(stderr, "SQLite update error: %s\n", sqlite3_errmsg(store->db));
    sqlite3_finalize(stmt);
    return ok;
}

/* Recalculate risk score for given account_id ---------------------------- */
static bool rap_recalculate_risk(rap_store_t *store, const char *account_id)
{
    /* Fetch stats for last 24h */
    const char *sql_stats =
        "SELECT COUNT(*), SUM(amount) "
        "FROM rolling_transactions "
        "WHERE account_id = ? "
        "AND occurred_at >= strftime('%s','now') - ?;";

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(store->db, sql_stats, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "SQLite prepare error: %s\n", sqlite3_errmsg(store->db));
        return false;
    }

    sqlite3_bind_text(stmt, 1, account_id, -1, SQLITE_STATIC);
    sqlite3_bind_int (stmt, 2, HOURS24_IN_SECONDS);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_ROW) {
        fprintf(stderr, "SQLite step error: %s\n", sqlite3_errmsg(store->db));
        sqlite3_finalize(stmt);
        return false;
    }

    int txn_count = sqlite3_column_int(stmt, 0);
    double total_amount = sqlite3_column_double(stmt, 1);
    sqlite3_finalize(stmt);

    /* Very naive heuristic (for pedagogical purposes) */
    int risk_score = 0;
    if (total_amount > 10000.0)                     risk_score += 50;
    if (txn_count > 15)                             risk_score += 20;
    if (total_amount > 50000.0)                     risk_score += 30;
    if (txn_count > 40)                             risk_score += 20;

    bool flagged = (risk_score >= DEFAULT_RISK_THRESHOLD);

    /* Upsert into risk_metrics */
    const char *sql_upsert =
        "INSERT INTO risk_metrics "
        "(account_id, txn_count_24h, total_amount_24h, risk_score, flagged, updated_at) "
        "VALUES (?, ?, ?, ?, ?, strftime('%s','now')) "
        "ON CONFLICT(account_id) DO UPDATE SET "
        "    txn_count_24h  = excluded.txn_count_24h, "
        "    total_amount_24h = excluded.total_amount_24h, "
        "    risk_score     = excluded.risk_score, "
        "    flagged        = excluded.flagged, "
        "    updated_at     = excluded.updated_at;";

    rc = sqlite3_prepare_v2(store->db, sql_upsert, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "SQLite prepare error: %s\n", sqlite3_errmsg(store->db));
        return false;
    }

    sqlite3_bind_text  (stmt, 1, account_id, -1, SQLITE_STATIC);
    sqlite3_bind_int   (stmt, 2, txn_count);
    sqlite3_bind_double(stmt, 3, total_amount);
    sqlite3_bind_int   (stmt, 4, risk_score);
    sqlite3_bind_int   (stmt, 5, flagged ? 1 : 0);

    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok) fprintf(stderr, "SQLite upsert error: %s\n", sqlite3_errmsg(store->db));
    sqlite3_finalize(stmt);
    return ok;
}

/* ---------- Schema Initialisation --------------------------------------- */

static bool rap_init_schema(sqlite3 *db)
{
    const char *ddl =
        "BEGIN;"
        "CREATE TABLE IF NOT EXISTS rolling_transactions ("
        "    transaction_id INTEGER PRIMARY KEY,"
        "    account_id     TEXT NOT NULL,"
        "    amount         REAL NOT NULL,"
        "    currency       TEXT NOT NULL,"
        "    occurred_at    INTEGER NOT NULL"
        ");"

        "CREATE TABLE IF NOT EXISTS risk_metrics ("
        "    account_id        TEXT PRIMARY KEY,"
        "    txn_count_24h     INTEGER NOT NULL DEFAULT 0,"
        "    total_amount_24h  REAL    NOT NULL DEFAULT 0.0,"
        "    risk_score        INTEGER NOT NULL DEFAULT 0,"
        "    flagged           INTEGER NOT NULL DEFAULT 0,"
        "    flag_reason       TEXT,"
        "    updated_at        INTEGER NOT NULL"
        ");"

        "CREATE TABLE IF NOT EXISTS meta ("
        "    key TEXT PRIMARY KEY, "
        "    value TEXT NOT NULL"
        ");"

        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');"
        "COMMIT;";

    char *errmsg = NULL;
    int rc = sqlite3_exec(db, ddl, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "SQLite DDL error: %s\n", errmsg);
        sqlite3_free(errmsg);
        return false;
    }

    /* Verify schema version to guard migrations */
    const char *sql_version = "SELECT value FROM meta WHERE key='schema_version';";
    sqlite3_stmt *stmt;
    rc = sqlite3_prepare_v2(db, sql_version, -1, &stmt, NULL);
    if (rc != SQLITE_OK || sqlite3_step(stmt) != SQLITE_ROW) {
        fprintf(stderr, "Schema version lookup failed\n");
        sqlite3_finalize(stmt);
        return false;
    }
    int version = atoi((const char*)sqlite3_column_text(stmt, 0));
    sqlite3_finalize(stmt);

    if (version != RAP_SCHEMA_VERSION) {
        fprintf(stderr, "Unsupported schema version %d (expecting %d)\n",
                version, RAP_SCHEMA_VERSION);
        return false;
    }
    return true;
}

/* ---------- JSON Event Parsing Utility ---------------------------------- */
/*  Not strictly part of the projector—provided for completeness so that
 *  instructors can demo an end-to-end flow without scaffolding.            */

bool rap_parse_event(const char *json_str, event_t *out_evt)
{
    if (!json_str || !out_evt) return false;

    json_error_t jerr;
    json_t *root = json_loads(json_str, 0, &jerr);
    if (!root) {
        fprintf(stderr, "JSON parse error: %s (at %d:%d)\n",
                jerr.text, jerr.line, jerr.column);
        return false;
    }

    const char *type_str = json_string_value(json_object_get(root, "type"));
    if (!type_str) goto fail;

    event_type_t ev_type = rap_get_type_from_str(type_str);
    if (ev_type == EVT_UNKNOWN) goto fail;

    out_evt->type           = ev_type;
    out_evt->transaction_id = (uint64_t)json_integer_value(json_object_get(root, "transaction_id"));

    const char *acct = json_string_value(json_object_get(root, "account_id"));
    const char *curr = json_string_value(json_object_get(root, "currency"));
    if (!acct || !curr) goto fail;

    strncpy(out_evt->account_id, acct, sizeof(out_evt->account_id) - 1);
    strncpy(out_evt->currency,  curr, sizeof(out_evt->currency) - 1);

    out_evt->amount      = json_number_value(json_object_get(root, "amount"));
    out_evt->occurred_at = (time_t)json_integer_value(json_object_get(root, "occurred_at"));

    /* Keep metadata ref-counted */
    json_t *meta = json_object_get(root, "metadata");
    out_evt->json_meta = meta ? json_incref(meta) : NULL;

    json_decref(root);
    return true;

fail:
    json_decref(root);
    return false;
}

void rap_free_event(event_t *evt)
{
    if (evt && evt->json_meta) {
        json_decref(evt->json_meta);
        evt->json_meta = NULL;
    }
}

static event_type_t rap_get_type_from_str(const char *name)
{
    if (!name) return EVT_UNKNOWN;
    if (strcmp(name, "TransactionInitiated")   == 0) return EVT_TRANSACTION_INITIATED;
    if (strcmp(name, "TransactionAuthorized")  == 0) return EVT_TRANSACTION_AUTHORIZED;
    if (strcmp(name, "TransactionSettled")     == 0) return EVT_TRANSACTION_SETTLED;
    if (strcmp(name, "RiskManuallyFlagged")    == 0) return EVT_RISK_MANUALLY_FLAGGED;
    return EVT_UNKNOWN;
}

/* ---------- Example Main (Optional) ------------------------------------- */
/*
int main(void)
{
    rap_store_t store;
    if (!rap_store_open(&store, "risk_projection.db")) exit(EXIT_FAILURE);

    const char *json_evt =
        "{"
        "  \"type\": \"TransactionInitiated\","
        "  \"transaction_id\": 12345,"
        "  \"account_id\": \"student_abc\","
        "  \"amount\": 2500.00,"
        "  \"currency\": \"USD\","
        "  \"occurred_at\": 1700000000"
        "}";

    event_t evt;
    if (rap_parse_event(json_evt, &evt)) {
        rap_handle_event(&store, &evt);
        rap_free_event(&evt);
    }

    rap_store_close(&store);
    return 0;
}
*/

/* END OF FILE */
