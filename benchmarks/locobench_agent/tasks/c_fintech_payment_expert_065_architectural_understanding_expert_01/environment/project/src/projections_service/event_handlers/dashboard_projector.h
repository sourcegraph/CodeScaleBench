/*
 * EduPay Ledger Academy
 * ---------------------
 * File:    dashboard_projector.h
 * Desc:    Event-handler / read-model projector for the “Student-Risk Dashboard”.
 *          Consumes immutable ledger events and folds them into an optimized,
 *          query-friendly SQLite read-model that UI widgets subscribe to.
 *
 * NOTE:    This header is self-contained (both interface + inline implementation)
 *          to keep the example compact.  In production you would normally split
 *          declarations (.h) from definitions (.c).
 */

#ifndef EDUPAY_LEDGER_ACADEMY_DASHBOARD_PROJECTOR_H
#define EDUPAY_LEDGER_ACADEMY_DASHBOARD_PROJECTOR_H

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard Library                                                         */
/* ────────────────────────────────────────────────────────────────────────── */
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Third-Party Dependencies                                                 */
/* ────────────────────────────────────────────────────────────────────────── */
/*  We depend only on SQLite, an ubiquitous, embeddable RDBMS.               */
#include <sqlite3.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public API                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

#ifdef __cplusplus
extern "C" {
#endif

/* Ledger event types that the projector knows how to fold.                  */
typedef enum
{
    EVT_UNDEFINED = 0,
    EVT_PAYMENT_PROCESSED,
    EVT_TRANSACTION_SETTLED,
    EVT_FRAUD_FLAGGED,
    EVT_CURRENCY_CONVERTED,
    EVT_SCHOLARSHIP_DISBURSED
} ledger_event_type_t;

/* Immutable envelope received from the event-store / broker.                */
typedef struct
{
    ledger_event_type_t type;      /* Event discriminator.                  */
    const char         *payload;   /* UTF-8 JSON blob (null-terminated).    */
    uint64_t            sequence;  /* Global ordering, monotonic.           */
    uint64_t            ts_epoch_ms; /* Milliseconds since Unix epoch.      */
} ledger_event_t;

/* Opaque handle exposed to application code.                                */
typedef struct
{
    sqlite3        *db;            /* Connection to read-model store.       */
    pthread_mutex_t mtx;           /* Serializes concurrent folds.          */
} dashboard_projector_t;

/* Construction / teardown.  On failure, an explanatory message is written
 * to `stderr` and false is returned.                                        */
bool dashboard_projector_init(dashboard_projector_t *prj,
                              const char            *sqlite_path);

void dashboard_projector_shutdown(dashboard_projector_t *prj);

/* Fold a single ledger event into the dashboard read-model.  Thread-safe
 * (internally synchronized).                                                */
void dashboard_projector_handle_event(dashboard_projector_t *prj,
                                      const ledger_event_t  *evt);

#ifdef __cplusplus
}
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Inline Implementation                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

#ifdef DASHBOARD_PROJECTOR_IMPLEMENTATION
#error "DASHBOARD_PROJECTOR_IMPLEMENTATION already defined elsewhere"
#endif
#define DASHBOARD_PROJECTOR_IMPLEMENTATION 1

/* SQLite helpers ─────────────────────────────────────────────────────────── */

static inline void _log_sqlite_error(const char *ctx, sqlite3 *db)
{
    fprintf(stderr, "[dashboard_projector] %s: %s (code=%d)\n",
            ctx, sqlite3_errmsg(db), sqlite3_errcode(db));
}

static inline bool _exec(sqlite3 *db, const char *sql)
{
    char *errmsg = NULL;
    if (sqlite3_exec(db, sql, NULL, NULL, &errmsg) != SQLITE_OK)
    {
        fprintf(stderr, "[dashboard_projector] SQL error: %s\n", errmsg);
        sqlite3_free(errmsg);
        return false;
    }
    return true;
}

/* Schema bootstrap ───────────────────────────────────────────────────────── */

static const char *_DDL[] = {
    /* Metadata used for idempotent re-playing (at-least-once deliveries).   */
    "CREATE TABLE IF NOT EXISTS projection_metadata ("
    "  id                INTEGER PRIMARY KEY CHECK (id = 1),"
    "  last_sequence     INTEGER NOT NULL DEFAULT 0"
    ");"
    "INSERT OR IGNORE INTO projection_metadata (id, last_sequence) VALUES (1, 0);",

    /* Highly-denormalized table powering the dashboard widgets.             */
    "CREATE TABLE IF NOT EXISTS dashboard_snapshot ("
    "  id                  INTEGER PRIMARY KEY CHECK (id = 1),"
    "  total_payments_usd  REAL    NOT NULL DEFAULT 0.0,"
    "  total_settlements   REAL    NOT NULL DEFAULT 0.0,"
    "  fraud_incidents     INTEGER NOT NULL DEFAULT 0,"
    "  scholarship_outflow REAL    NOT NULL DEFAULT 0.0"
    ");"
    "INSERT OR IGNORE INTO dashboard_snapshot (id) VALUES (1);",

    NULL /* sentinel */
};

static inline bool _ensure_schema(sqlite3 *db)
{
    for (const char **ddl = _DDL; *ddl; ++ddl)
        if (!_exec(db, *ddl))
            return false;
    return true;
}

/* Primitive JSON parsing utilities (no external dependency).                */
/* Security: Not a full JSON parser — good enough for our limited shapes.    */

static inline bool _json_extract_double(const char *json,
                                        const char *key,
                                        double     *out_val)
{
    if (!json || !key || !out_val) return false;

    const size_t key_len = strlen(key);
    const char  *pos     = json;
    while ((pos = strstr(pos, key)))
    {
        pos += key_len;
        /* Skip whitespace, colon, whitespace */
        while (*pos && (*pos == ' ' || *pos == '\t' || *pos == '\n' ||
                        *pos == '\r' || *pos == ':'))
            ++pos;
        if (!*pos) break;

        /* +/-? digits?. */
        char *endptr = NULL;
        errno = 0;
        double val  = strtod(pos, &endptr);
        if (endptr != pos && errno == 0)
        {
            *out_val = val;
            return true;
        }
        /* Else: continue searching (false hit). */
    }
    return false;
}

/* Fetch last processed sequence to achieve idempotency.                     */
static inline uint64_t _get_last_sequence(sqlite3 *db)
{
    sqlite3_stmt *stmt = NULL;
    uint64_t      seq  = 0;

    if (sqlite3_prepare_v2(db,
                           "SELECT last_sequence FROM projection_metadata "
                           "WHERE id = 1;",
                           -1, &stmt, NULL) == SQLITE_OK)
    {
        if (sqlite3_step(stmt) == SQLITE_ROW)
            seq = (uint64_t)sqlite3_column_int64(stmt, 0);
    }
    else
        _log_sqlite_error("_get_last_sequence/prepare", db);

    sqlite3_finalize(stmt);
    return seq;
}

static inline bool _update_last_sequence(sqlite3 *db, uint64_t seq)
{
    sqlite3_stmt *stmt = NULL;
    bool          ok   = false;

    if (sqlite3_prepare_v2(db,
                           "UPDATE projection_metadata SET last_sequence = ?"
                           " WHERE id = 1;",
                           -1, &stmt, NULL) == SQLITE_OK)
    {
        sqlite3_bind_int64(stmt, 1, (sqlite3_int64)seq);
        ok = (sqlite3_step(stmt) == SQLITE_DONE);
    }
    else
        _log_sqlite_error("_update_last_sequence/prepare", db);

    sqlite3_finalize(stmt);
    return ok;
}

/* Public functions ───────────────────────────────────────────────────────── */

bool dashboard_projector_init(dashboard_projector_t *prj,
                              const char            *sqlite_path)
{
    if (!prj || !sqlite_path)
    {
        fprintf(stderr, "[dashboard_projector] init: invalid arguments\n");
        return false;
    }

    memset(prj, 0, sizeof(*prj));

    /* Open SQLite in WAL mode for concurrency friendliness.                 */
    int rc = sqlite3_open_v2(sqlite_path,
                             &prj->db,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                                 SQLITE_OPEN_FULLMUTEX,
                             NULL);
    if (rc != SQLITE_OK)
    {
        _log_sqlite_error("sqlite3_open_v2", prj->db);
        return false;
    }

    if (!_ensure_schema(prj->db))
        goto fail;

    if (pthread_mutex_init(&prj->mtx, NULL) != 0)
    {
        fprintf(stderr, "[dashboard_projector] pthread_mutex_init failed\n");
        goto fail;
    }

    /* Switch to WAL for perf. */
    if (!_exec(prj->db, "PRAGMA journal_mode=WAL;"))
        goto fail_mutex;

    return true;

/* Error unwind helpers */
fail_mutex:
    pthread_mutex_destroy(&prj->mtx);
fail:
    sqlite3_close(prj->db);
    prj->db = NULL;
    return false;
}

void dashboard_projector_shutdown(dashboard_projector_t *prj)
{
    if (!prj || !prj->db) return;

    pthread_mutex_lock(&prj->mtx);
    sqlite3_close(prj->db);
    prj->db = NULL;
    pthread_mutex_unlock(&prj->mtx);

    pthread_mutex_destroy(&prj->mtx);
}

/* Actual fold implementation per event type.                                */

static inline bool _fold_payment_processed(sqlite3 *db, double amount_usd)
{
    sqlite3_stmt *stmt = NULL;
    bool          ok   = false;

    if (sqlite3_prepare_v2(
            db,
            "UPDATE dashboard_snapshot "
            "SET total_payments_usd = total_payments_usd + ? "
            "WHERE id = 1;",
            -1, &stmt, NULL) == SQLITE_OK)
    {
        sqlite3_bind_double(stmt, 1, amount_usd);
        ok = (sqlite3_step(stmt) == SQLITE_DONE);
    }
    else
        _log_sqlite_error("_fold_payment_processed/prepare", db);

    sqlite3_finalize(stmt);
    return ok;
}

static inline bool _fold_transaction_settled(sqlite3 *db, double amount)
{
    sqlite3_stmt *stmt = NULL;
    bool          ok   = false;

    if (sqlite3_prepare_v2(
            db,
            "UPDATE dashboard_snapshot "
            "SET total_settlements = total_settlements + ? "
            "WHERE id = 1;",
            -1, &stmt, NULL) == SQLITE_OK)
    {
        sqlite3_bind_double(stmt, 1, amount);
        ok = (sqlite3_step(stmt) == SQLITE_DONE);
    }
    else
        _log_sqlite_error("_fold_transaction_settled/prepare", db);

    sqlite3_finalize(stmt);
    return ok;
}

static inline bool _fold_fraud_flagged(sqlite3 *db)
{
    return _exec(db,
                 "UPDATE dashboard_snapshot "
                 "SET fraud_incidents = fraud_incidents + 1 "
                 "WHERE id = 1;");
}

static inline bool _fold_scholarship_disbursed(sqlite3 *db, double amount)
{
    sqlite3_stmt *stmt = NULL;
    bool          ok   = false;

    if (sqlite3_prepare_v2(
            db,
            "UPDATE dashboard_snapshot "
            "SET scholarship_outflow = scholarship_outflow + ? "
            "WHERE id = 1;",
            -1, &stmt, NULL) == SQLITE_OK)
    {
        sqlite3_bind_double(stmt, 1, amount);
        ok = (sqlite3_step(stmt) == SQLITE_DONE);
    }
    else
        _log_sqlite_error("_fold_scholarship_disbursed/prepare", db);

    sqlite3_finalize(stmt);
    return ok;
}

/* Main folding orchestrator                                                 */

void dashboard_projector_handle_event(dashboard_projector_t *prj,
                                      const ledger_event_t  *evt)
{
    if (!prj || !evt || !prj->db) return;

    pthread_mutex_lock(&prj->mtx);

    /* Idempotent replay guard.                                              */
    uint64_t last_seq = _get_last_sequence(prj->db);
    if (evt->sequence <= last_seq)
    {
        pthread_mutex_unlock(&prj->mtx);
        return; /* Already processed. */
    }

    /* Begin transaction.                                                    */
    if (!_exec(prj->db, "BEGIN;"))
        goto unlock;

    bool fold_ok  = false;
    double amount = 0.0;

    switch (evt->type)
    {
        case EVT_PAYMENT_PROCESSED:
            if (_json_extract_double(evt->payload, "\"amount\"", &amount))
                fold_ok = _fold_payment_processed(prj->db, amount);
            break;

        case EVT_TRANSACTION_SETTLED:
            if (_json_extract_double(evt->payload, "\"amount\"", &amount))
                fold_ok = _fold_transaction_settled(prj->db, amount);
            break;

        case EVT_FRAUD_FLAGGED:
            fold_ok = _fold_fraud_flagged(prj->db);
            break;

        case EVT_SCHOLARSHIP_DISBURSED:
            if (_json_extract_double(evt->payload, "\"amount\"", &amount))
                fold_ok = _fold_scholarship_disbursed(prj->db, amount);
            break;

        /* Events not relevant for the dashboard are safely ignored.         */
        default:
            fold_ok = true;
            break;
    }

    /* Update checkpoint if the fold succeeded.                              */
    if (fold_ok)
        fold_ok = _update_last_sequence(prj->db, evt->sequence);

    /* Commit or rollback.                                                   */
    if (fold_ok)
    {
        if (!_exec(prj->db, "COMMIT;"))
            _exec(prj->db, "ROLLBACK;");
    }
    else
    {
        _exec(prj->db, "ROLLBACK;");
    }

unlock:
    pthread_mutex_unlock(&prj->mtx);
}

#endif /* EDUPAY_LEDGER_ACADEMY_DASHBOARD_PROJECTOR_H */
