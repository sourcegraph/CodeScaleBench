/*
 * LexiLearn MVC Orchestrator – Experiment Tracker
 * ------------------------------------------------
 * File   : experiment_tracker.c
 * Author : LexiLearn Engineering Team
 *
 * Description:
 *   A lightweight, thread-safe experiment-tracking component that persists
 *   experiment metadata and metrics to an embedded SQLite3 database.  Designed
 *   for use by the Model layer’s MLOps Pipeline, this module provides a C API
 *   for starting runs, logging metrics, and finalizing experiments, enabling
 *   reproducibility, model versioning, and auditability.
 *
 *   Compile with:
 *       gcc -std=c11 -Wall -Wextra -pthread \
 *           -I/path/to/sqlite3/include \
 *           experiment_tracker.c -lsqlite3 -o experiment_tracker
 *
 * Public API:
 *   et_init()
 *   et_close()
 *   et_start_run()
 *   et_log_metric()
 *   et_end_run()
 *
 * Thread-Safety:
 *   A single pthread_mutex guards all access to the SQLite handle, allowing
 *   concurrent reads/writes from multiple training threads within the same
 *   process.
 */

#define _POSIX_C_SOURCE 200809L   /* For clock_gettime, strdup, etc. */

#include <sqlite3.h>
#include <pthread.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>

/* ============================================================================
 *  Local definitions
 * ==========================================================================*/

#ifndef ET_EXPORT
#define ET_EXPORT /* visibility handled by the build system */
#endif

#ifndef ET_MAX_ERR_MSG
#define ET_MAX_ERR_MSG 256
#endif

typedef enum {
    ET_OK            = 0,
    ET_ERR_SQL       = -1,
    ET_ERR_DB_LOCK   = -2,
    ET_ERR_INVALID   = -3,
    ET_ERR_NOMEM     = -4,
    ET_ERR_UNKNOWN   = -100
} et_status_t;

/* Forward declaration for opaque handle */
typedef struct experiment_tracker_s experiment_tracker_t;

/* ============================================================================
 *  Public API
 * ==========================================================================*/

/**
 * Initialize experiment tracker.
 *
 * db_path  : Path to SQLite database file (created if it does not exist)
 * tracker  : Pointer to (NULL-initialized) tracker handle
 *
 * Returns ET_OK on success, otherwise error code (<0)
 */
ET_EXPORT et_status_t et_init(const char *db_path, experiment_tracker_t **tracker);

/**
 * Close tracker and free all resources.
 */
ET_EXPORT void et_close(experiment_tracker_t *tracker);

/**
 * Start a new experiment run.
 *
 * experiment_name : Logical experiment grouping (e.g., “bert_finetune”)
 * model_strategy  : Strategy pattern identifier (e.g., “TRANSFORMER_V1”)
 * hyperparams_json: JSON string containing hyper-parameters
 * out_run_id      : Receives auto-generated run id
 */
ET_EXPORT et_status_t et_start_run(
    experiment_tracker_t *tracker,
    const char           *experiment_name,
    const char           *model_strategy,
    const char           *hyperparams_json,
    int64_t              *out_run_id);

/**
 * Log a scalar metric for a given run.
 *
 * run_id      : Experiment run identifier
 * metric_name : e.g., "val_accuracy"
 * value       : Floating point value
 * step        : Training step / epoch (optional; use ‑1 if not applicable)
 */
ET_EXPORT et_status_t et_log_metric(
    experiment_tracker_t *tracker,
    int64_t               run_id,
    const char           *metric_name,
    double                value,
    int                   step);

/**
 * End a run, updating its status and end timestamp.
 *
 * status : One of “COMPLETED”, “FAILED”, “KILLED”, “TIMED_OUT”
 */
ET_EXPORT et_status_t et_end_run(
    experiment_tracker_t *tracker,
    int64_t               run_id,
    const char           *status);

/* ============================================================================
 *  Implementation
 * ==========================================================================*/

struct experiment_tracker_s {
    sqlite3     *db;
    char         db_path[PATH_MAX];
    pthread_mutex_t mutex;
    bool         initialized;
};

/* --------------------------- Utility helpers ------------------------------*/

static int64_t et_now_epoch_seconds(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) == 0)
        return (int64_t)ts.tv_sec;
    /* Fallback:  time() is less precise but never fails */
    return (int64_t)time(NULL);
}

/* Guard all SQLite operations with this macro */
#define ET_LOCK(tracker)   pthread_mutex_lock(&(tracker)->mutex)
#define ET_UNLOCK(tracker) pthread_mutex_unlock(&(tracker)->mutex)

static void et_log_error(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

/* Translate SQLite return codes to our domain-specific codes */
static et_status_t et_from_sqlite(int rc)
{
    switch (rc) {
        case SQLITE_OK:          return ET_OK;
        case SQLITE_BUSY:
        case SQLITE_LOCKED:      return ET_ERR_DB_LOCK;
        case SQLITE_NOMEM:       return ET_ERR_NOMEM;
        default:                 return ET_ERR_SQL;
    }
}

/* Create tables if they don’t exist */
static const char *ET_SCHEMA_SQL =
    "PRAGMA foreign_keys = ON;"
    "CREATE TABLE IF NOT EXISTS runs ("
    "   id               INTEGER PRIMARY KEY AUTOINCREMENT,"
    "   experiment_name  TEXT    NOT NULL,"
    "   model_strategy   TEXT    NOT NULL,"
    "   hyperparams_json TEXT,"
    "   status           TEXT    NOT NULL DEFAULT 'RUNNING',"
    "   started_at       INTEGER NOT NULL,"
    "   ended_at         INTEGER"
    ");"
    "CREATE TABLE IF NOT EXISTS metrics ("
    "   id           INTEGER PRIMARY KEY AUTOINCREMENT,"
    "   run_id       INTEGER NOT NULL,"
    "   metric_name  TEXT    NOT NULL,"
    "   metric_value REAL    NOT NULL,"
    "   step         INTEGER,"
    "   logged_at    INTEGER NOT NULL,"
    "   FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE"
    ");"
    "CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);";

static et_status_t et_init_schema(sqlite3 *db)
{
    char *errmsg = NULL;
    int   rc     = sqlite3_exec(db, ET_SCHEMA_SQL, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        et_log_error("SQLite schema init error: %s", errmsg ? errmsg : "unknown");
        sqlite3_free(errmsg);
    }
    return et_from_sqlite(rc);
}

/* --------------------------- Public API impl ------------------------------*/

et_status_t et_init(const char *db_path, experiment_tracker_t **out_tracker)
{
    if (!db_path || !out_tracker) return ET_ERR_INVALID;

    *out_tracker = NULL;
    experiment_tracker_t *tracker = calloc(1, sizeof(*tracker));
    if (!tracker) return ET_ERR_NOMEM;

    /* Copy path for diagnostics */
    strncpy(tracker->db_path, db_path, sizeof(tracker->db_path) - 1);
    tracker->db_path[sizeof(tracker->db_path) - 1] = '\0';

    if (pthread_mutex_init(&tracker->mutex, NULL) != 0) {
        free(tracker);
        return ET_ERR_UNKNOWN;
    }

    /* Open SQLite connection */
    int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX;
    int rc    = sqlite3_open_v2(db_path, &tracker->db, flags, NULL);
    if (rc != SQLITE_OK) {
        et_log_error("Failed to open SQLite DB '%s': %s", db_path, sqlite3_errmsg(tracker->db));
        pthread_mutex_destroy(&tracker->mutex);
        free(tracker);
        return ET_ERR_SQL;
    }

    /* Enable WAL for concurrent read/write */
    sqlite3_exec(tracker->db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);

    /* Initialize schema */
    et_status_t st = et_init_schema(tracker->db);
    if (st != ET_OK) {
        sqlite3_close(tracker->db);
        pthread_mutex_destroy(&tracker->mutex);
        free(tracker);
        return st;
    }

    tracker->initialized = true;
    *out_tracker = tracker;
    return ET_OK;
}

void et_close(experiment_tracker_t *tracker)
{
    if (!tracker) return;

    ET_LOCK(tracker);
    if (tracker->db) sqlite3_close(tracker->db);
    tracker->initialized = false;
    ET_UNLOCK(tracker);

    pthread_mutex_destroy(&tracker->mutex);
    free(tracker);
}

et_status_t et_start_run(
    experiment_tracker_t *tracker,
    const char           *experiment_name,
    const char           *model_strategy,
    const char           *hyperparams_json,
    int64_t              *out_run_id)
{
    if (!tracker || !tracker->initialized || !experiment_name || !model_strategy)
        return ET_ERR_INVALID;

    const char *SQL =
        "INSERT INTO runs (experiment_name, model_strategy, hyperparams_json, started_at) "
        "VALUES (?1, ?2, ?3, ?4);";

    ET_LOCK(tracker);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(tracker->db, SQL, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        ET_UNLOCK(tracker);
        return ET_ERR_SQL;
    }

    sqlite3_bind_text(stmt, 1, experiment_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, model_strategy,  -1, SQLITE_TRANSIENT);
    if (hyperparams_json)
        sqlite3_bind_text(stmt, 3, hyperparams_json, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 3);
    sqlite3_bind_int64(stmt, 4, et_now_epoch_seconds());

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    if (rc != SQLITE_DONE) {
        ET_UNLOCK(tracker);
        return ET_ERR_SQL;
    }

    int64_t new_id = sqlite3_last_insert_rowid(tracker->db);
    ET_UNLOCK(tracker);

    if (out_run_id) *out_run_id = new_id;
    return ET_OK;
}

et_status_t et_log_metric(
    experiment_tracker_t *tracker,
    int64_t               run_id,
    const char           *metric_name,
    double                value,
    int                   step)
{
    if (!tracker || !tracker->initialized || !metric_name)
        return ET_ERR_INVALID;

    const char *SQL =
        "INSERT INTO metrics (run_id, metric_name, metric_value, step, logged_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5);";

    ET_LOCK(tracker);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(tracker->db, SQL, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        ET_UNLOCK(tracker);
        return ET_ERR_SQL;
    }

    sqlite3_bind_int64(stmt, 1, run_id);
    sqlite3_bind_text(stmt, 2, metric_name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 3, value);
    if (step >= 0)
        sqlite3_bind_int(stmt, 4, step);
    else
        sqlite3_bind_null(stmt, 4);
    sqlite3_bind_int64(stmt, 5, et_now_epoch_seconds());

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    ET_UNLOCK(tracker);

    if (rc != SQLITE_DONE) return ET_ERR_SQL;
    return ET_OK;
}

et_status_t et_end_run(
    experiment_tracker_t *tracker,
    int64_t               run_id,
    const char           *status)
{
    if (!tracker || !tracker->initialized) return ET_ERR_INVALID;
    if (!status) status = "COMPLETED";

    const char *SQL =
        "UPDATE runs SET status = ?1, ended_at = ?2 WHERE id = ?3;";

    ET_LOCK(tracker);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(tracker->db, SQL, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        ET_UNLOCK(tracker);
        return ET_ERR_SQL;
    }

    sqlite3_bind_text(stmt, 1, status, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, et_now_epoch_seconds());
    sqlite3_bind_int64(stmt, 3, run_id);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    ET_UNLOCK(tracker);

    if (rc != SQLITE_DONE) return ET_ERR_SQL;
    return ET_OK;
}

/* ============================================================================
 *  Unit test (compile with ‑DTEST_EXPERIMENT_TRACKER)
 * ==========================================================================*/
#ifdef TEST_EXPERIMENT_TRACKER
#include <assert.h>

static void run_basic_flow(void)
{
    experiment_tracker_t *tracker = NULL;
    assert(et_init("file:et_test.db?mode=memory&cache=shared", &tracker) == ET_OK);

    int64_t run_id = 0;
    assert(et_start_run(tracker,
                        "unit_test_experiment",
                        "NGRAM_V1",
                        "{\"learning_rate\": 0.01, \"epochs\": 3}",
                        &run_id) == ET_OK);
    assert(run_id > 0);

    for (int epoch = 0; epoch < 3; ++epoch) {
        assert(et_log_metric(tracker, run_id, "train_loss", 0.01 * epoch, epoch) == ET_OK);
        assert(et_log_metric(tracker, run_id, "val_accuracy", 0.9 + 0.01 * epoch, epoch) == ET_OK);
    }

    assert(et_end_run(tracker, run_id, "COMPLETED") == ET_OK);
    et_close(tracker);
    printf("All experiment-tracker unit tests passed.\n");
}

int main(void)
{
    run_basic_flow();
    return EXIT_SUCCESS;
}
#endif /* TEST_EXPERIMENT_TRACKER */
