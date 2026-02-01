/*
 * LexiLearn MVC Orchestrator – Model Registry
 * -------------------------------------------
 * File:    lexilearn_orchestrator/src/model/ml_pipeline/model_registry.c
 * Author:  LexiLearn Core Team
 *
 * Description:
 *   The Model Registry is a central, thread-safe component that stores
 *   all model metadata and metrics in an embedded SQLite database.  It is
 *   responsible for:
 *
 *     • Versioning models (semantic integer versions per model name)
 *     • Tracking the current stage (EXPERIMENT → STAGING → PRODUCTION)
 *     • Persisting training parameters & artifact URIs
 *     • Logging arbitrary evaluation metrics
 *
 *   A minimal public API is exposed so that Controller-layer Pipeline
 *   jobs can register new models, update stages, and query the latest
 *   production model for inference workloads.
 *
 * Compile:
 *   gcc -Wall -Wextra -pedantic -pthread -lsqlite3 -o model_registry.o -c model_registry.c
 *
 * --------------------------------------------------------------------------
 */

#define _POSIX_C_SOURCE 200809L  /* For clock_gettime, strdup               */

#include <sqlite3.h>
#include <pthread.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ─────────────────────────────────────────────── Private Macros ────────── */

#define MR_OK                0        /* Success                                 */
#define MR_ERR_GENERAL      -1        /* Generic failure                         */
#define MR_ERR_NOT_FOUND    -2        /* Record not present                      */
#define MR_ERR_INVALID_ARG  -3        /* Invalid function argument               */

#define LOG_FMT(level, fmt, ...) \
    fprintf(level, "[ModelRegistry] %s:%d: " fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#define LOG_ERROR(fmt, ...) LOG_FMT(stderr, fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)  LOG_FMT(stdout, fmt, ##__VA_ARGS__)

/* ─────────────────────────────────────────────── Public Types ──────────── */

typedef enum {
    MR_STAGE_NONE = 0,
    MR_STAGE_EXPERIMENT,
    MR_STAGE_STAGING,
    MR_STAGE_PRODUCTION,
    MR_STAGE_ARCHIVED
} MR_Stage;

typedef struct {
    char    name[128];       /* Model key (e.g., “summarizer_en_v2”)         */
    int     version;         /* Sequential version (1, 2, …)                 */
    MR_Stage stage;          /* Current lifecycle stage                       */
    char    framework[32];   /* e.g., “pytorch”, “onnx”, “tensorflow”         */
    char    uri[256];        /* Location of persisted artifact (S3, FS, …)    */
    char    description[256];/* Human-readable notes                          */
    char    params_json[1024];/* Hyper-parameters as raw JSON string          */
    int64_t created_at;      /* UNIX epoch seconds                            */
} MR_ModelVersion;

/* ─────────────────────────────────────────────── Internal State ────────── */

typedef struct {
    sqlite3            *db;
    pthread_rwlock_t    rwlock;
    char                path[512];
    int                 is_init;
} MR_State;

static MR_State g_state = {0};

/* ────────────────────────────────────────────── Forward Decls ──────────── */

static int  mr_ensure_tables(void);
static int  mr_get_or_create_model_id(const char *name, int *model_id_out);
static int  mr_acquire_read(void);
static int  mr_acquire_write(void);
static void mr_release(void);

/* ─────────────────────────────────────────────── Helper Utils ──────────── */

static int64_t unix_time(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec;
}

static const char *stage_to_str(MR_Stage s) {
    switch (s) {
        case MR_STAGE_EXPERIMENT: return "EXPERIMENT";
        case MR_STAGE_STAGING:    return "STAGING";
        case MR_STAGE_PRODUCTION: return "PRODUCTION";
        case MR_STAGE_ARCHIVED:   return "ARCHIVED";
        default:                  return "NONE";
    }
}

/* ───────────────────────────────────────────── Public API ──────────────── */

/*
 * mr_init
 * -------
 * Initialise the Model Registry with a SQLite database file.  If the file
 * does not exist it will be created and schema migration executed.
 */
int mr_init(const char *db_path) {
    if (!db_path) return MR_ERR_INVALID_ARG;
    if (g_state.is_init) return MR_OK;

    int rc = sqlite3_open_v2(db_path,
                             &g_state.db,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                             SQLITE_OPEN_FULLMUTEX,
                             NULL);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Failed to open SQLite DB at ‘%s’: %s", db_path, sqlite3_errmsg(g_state.db));
        return MR_ERR_GENERAL;
    }

    /* Write-ahead logging improves concurrency */
    char *errmsg = NULL;
    rc = sqlite3_exec(g_state.db, "PRAGMA journal_mode = WAL;", NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("PRAGMA WAL failed: %s", errmsg);
        sqlite3_free(errmsg);
        sqlite3_close(g_state.db);
        return MR_ERR_GENERAL;
    }

    if (pthread_rwlock_init(&g_state.rwlock, NULL) != 0) {
        LOG_ERROR("pthread_rwlock_init failed: %s", strerror(errno));
        sqlite3_close(g_state.db);
        return MR_ERR_GENERAL;
    }

    strncpy(g_state.path, db_path, sizeof(g_state.path) - 1);

    rc = mr_ensure_tables();
    if (rc != MR_OK) {
        pthread_rwlock_destroy(&g_state.rwlock);
        sqlite3_close(g_state.db);
        return rc;
    }

    g_state.is_init = 1;
    LOG_INFO("Model Registry initialised at %s", db_path);
    return MR_OK;
}

/*
 * mr_shutdown
 * -----------
 * Graceful termination, frees resources and closes DB handle.
 */
int mr_shutdown(void) {
    if (!g_state.is_init) return MR_OK;

    pthread_rwlock_wrlock(&g_state.rwlock);

    int rc = sqlite3_close(g_state.db);
    if (rc != SQLITE_OK) {
        LOG_ERROR("sqlite3_close failed: %s", sqlite3_errmsg(g_state.db));
        pthread_rwlock_unlock(&g_state.rwlock);
        return MR_ERR_GENERAL;
    }
    pthread_rwlock_unlock(&g_state.rwlock);
    pthread_rwlock_destroy(&g_state.rwlock);

    memset(&g_state, 0, sizeof(g_state));
    return MR_OK;
}

/*
 * mr_register_model
 * -----------------
 * Insert a new model version, automatically incrementing the semantic
 * version number per model name.  The new version integer is returned via
 * ‘out_version’.  On success returns MR_OK.
 */
int mr_register_model(const char      *name,
                      const char      *framework,
                      const char      *uri,
                      const char      *description,
                      const char      *params_json,
                      int             *out_version)
{
    if (!name || !framework || !uri || !out_version) return MR_ERR_INVALID_ARG;

    int rc, model_id;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_write()) != MR_OK) return rc;

    /* Upsert model row and fetch numeric id */
    rc = mr_get_or_create_model_id(name, &model_id);
    if (rc != MR_OK) { mr_release(); return rc; }

    /* Determine next version */
    const char *qry_next = "SELECT COALESCE(MAX(version), 0) + 1 FROM model_versions "
                           "WHERE model_id = ?1;";
    rc = sqlite3_prepare_v2(g_state.db, qry_next, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_int(stmt, 1, model_id);
    rc = sqlite3_step(stmt);
    int next_version = (rc == SQLITE_ROW) ? sqlite3_column_int(stmt, 0) : 1;
    sqlite3_finalize(stmt); stmt = NULL;

    /* Insert new version row */
    const char *qry_ins =
        "INSERT INTO model_versions "
        "(model_id, version, stage, framework, uri, description, params_json, created_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8);";

    rc = sqlite3_prepare_v2(g_state.db, qry_ins, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_int   (stmt, 1, model_id);
    sqlite3_bind_int   (stmt, 2, next_version);
    sqlite3_bind_int   (stmt, 3, MR_STAGE_EXPERIMENT);
    sqlite3_bind_text  (stmt, 4, framework,   -1, SQLITE_TRANSIENT);
    sqlite3_bind_text  (stmt, 5, uri,         -1, SQLITE_TRANSIENT);
    sqlite3_bind_text  (stmt, 6, description ? description : "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text  (stmt, 7, params_json ? params_json : "{}", -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64 (stmt, 8, unix_time());

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) goto sqlite_fail;

    sqlite3_finalize(stmt);
    mr_release();

    *out_version = next_version;
    LOG_INFO("Registered model %s version %d (stage=%s)", name, next_version, stage_to_str(MR_STAGE_EXPERIMENT));
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/*
 * mr_get_latest
 * -------------
 * Retrieve the most recent version for a given model name.
 */
int mr_get_latest(const char *name, MR_ModelVersion *out) {
    if (!name || !out) return MR_ERR_INVALID_ARG;
    int rc;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_read()) != MR_OK) return rc;

    const char *qry =
        "SELECT mv.version, mv.stage, mv.framework, mv.uri, mv.description, "
        "       mv.params_json, mv.created_at "
        "FROM model_versions mv "
        "JOIN models m ON m.id = mv.model_id "
        "WHERE m.name = ?1 "
        "ORDER BY mv.version DESC LIMIT 1;";

    rc = sqlite3_prepare_v2(g_state.db, qry, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);

    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        mr_release();
        return MR_ERR_NOT_FOUND;
    }

    memset(out, 0, sizeof(*out));
    strncpy(out->name, name, sizeof(out->name) - 1);
    out->version      = sqlite3_column_int   (stmt, 0);
    out->stage        = sqlite3_column_int   (stmt, 1);
    strncpy(out->framework,   (const char*)sqlite3_column_text(stmt, 2), sizeof(out->framework) - 1);
    strncpy(out->uri,         (const char*)sqlite3_column_text(stmt, 3), sizeof(out->uri) - 1);
    strncpy(out->description, (const char*)sqlite3_column_text(stmt, 4), sizeof(out->description) - 1);
    strncpy(out->params_json, (const char*)sqlite3_column_text(stmt, 5), sizeof(out->params_json) - 1);
    out->created_at   = sqlite3_column_int64 (stmt, 6);

    sqlite3_finalize(stmt);
    mr_release();
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/*
 * mr_get_version
 * --------------
 * Fetch a specific version for a model by name and semantic version.
 */
int mr_get_version(const char *name, int version, MR_ModelVersion *out) {
    if (!name || !out) return MR_ERR_INVALID_ARG;
    int rc;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_read()) != MR_OK) return rc;

    const char *qry =
        "SELECT mv.stage, mv.framework, mv.uri, mv.description, "
        "       mv.params_json, mv.created_at "
        "FROM model_versions mv "
        "JOIN models m ON m.id = mv.model_id "
        "WHERE m.name = ?1 AND mv.version = ?2 LIMIT 1;";

    rc = sqlite3_prepare_v2(g_state.db, qry, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int (stmt, 2, version);

    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        mr_release();
        return MR_ERR_NOT_FOUND;
    }

    memset(out, 0, sizeof(*out));
    strncpy(out->name, name, sizeof(out->name) - 1);
    out->version      = version;
    out->stage        = sqlite3_column_int   (stmt, 0);
    strncpy(out->framework,   (const char*)sqlite3_column_text(stmt, 1), sizeof(out->framework) - 1);
    strncpy(out->uri,         (const char*)sqlite3_column_text(stmt, 2), sizeof(out->uri) - 1);
    strncpy(out->description, (const char*)sqlite3_column_text(stmt, 3), sizeof(out->description) - 1);
    strncpy(out->params_json, (const char*)sqlite3_column_text(stmt, 4), sizeof(out->params_json) - 1);
    out->created_at   = sqlite3_column_int64 (stmt, 5);

    sqlite3_finalize(stmt);
    mr_release();
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/*
 * mr_set_stage
 * ------------
 * Transition a model version to a new stage (e.g., promote to PRODUCTION).
 */
int mr_set_stage(const char *name, int version, MR_Stage new_stage) {
    if (!name) return MR_ERR_INVALID_ARG;
    int rc;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_write()) != MR_OK) return rc;

    const char *qry =
        "UPDATE model_versions "
        "SET stage = ?3 "
        "WHERE id IN (SELECT mv.id FROM model_versions mv "
        "             JOIN models m ON m.id = mv.model_id "
        "             WHERE m.name = ?1 AND mv.version = ?2);";

    rc = sqlite3_prepare_v2(g_state.db, qry, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int (stmt, 2, version);
    sqlite3_bind_int (stmt, 3, new_stage);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) goto sqlite_fail;

    sqlite3_finalize(stmt);
    mr_release();
    LOG_INFO("Model %s v%d moved to stage %s", name, version, stage_to_str(new_stage));
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/*
 * mr_log_metric
 * -------------
 * Attach an evaluation metric (k,v) to a model version.
 */
int mr_log_metric(const char *name, int version,
                  const char *metric_key, double metric_value)
{
    if (!name || !metric_key) return MR_ERR_INVALID_ARG;

    int rc;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_write()) != MR_OK) return rc;

    /* Resolve model_version_id */
    const char *qry_res =
        "SELECT mv.id FROM model_versions mv "
        "JOIN models m ON m.id = mv.model_id "
        "WHERE m.name = ?1 AND mv.version = ?2 LIMIT 1;";

    rc = sqlite3_prepare_v2(g_state.db, qry_res, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int (stmt, 2, version);

    if (sqlite3_step(stmt) != SQLITE_ROW) {
        sqlite3_finalize(stmt);
        mr_release();
        return MR_ERR_NOT_FOUND;
    }
    int model_version_id = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt); stmt = NULL;

    /* Insert metric */
    const char *qry_ins =
        "INSERT INTO metrics (model_version_id, key, value, logged_at) "
        "VALUES (?1, ?2, ?3, ?4);";

    rc = sqlite3_prepare_v2(g_state.db, qry_ins, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_int   (stmt, 1, model_version_id);
    sqlite3_bind_text  (stmt, 2, metric_key, -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 3, metric_value);
    sqlite3_bind_int64 (stmt, 4, unix_time());

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) goto sqlite_fail;

    sqlite3_finalize(stmt);
    mr_release();
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/*
 * mr_list_versions
 * ----------------
 * Returns an array of versions for a model name, newest first.  The caller
 * is responsible for free()-ing *out_list.
 */
int mr_list_versions(const char *name,
                     MR_ModelVersion **out_list,
                     size_t *out_count)
{
    if (!name || !out_list || !out_count) return MR_ERR_INVALID_ARG;
    int rc;
    sqlite3_stmt *stmt = NULL;

    if ((rc = mr_acquire_read()) != MR_OK) return rc;

    const char *qry =
        "SELECT mv.version, mv.stage, mv.framework, mv.uri, mv.description, "
        "       mv.params_json, mv.created_at "
        "FROM model_versions mv "
        "JOIN models m ON m.id = mv.model_id "
        "WHERE m.name = ?1 "
        "ORDER BY mv.version DESC;";

    rc = sqlite3_prepare_v2(g_state.db, qry, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);

    /* First pass: count rows */
    size_t count = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) count++;
    sqlite3_reset(stmt);

    MR_ModelVersion *arr = calloc(count ? count : 1, sizeof(MR_ModelVersion));
    if (!arr) { rc = MR_ERR_GENERAL; goto alloc_fail; }

    size_t idx = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        MR_ModelVersion *mv = &arr[idx++];
        memset(mv, 0, sizeof(*mv));
        strncpy(mv->name, name, sizeof(mv->name)-1);
        mv->version    = sqlite3_column_int   (stmt, 0);
        mv->stage      = sqlite3_column_int   (stmt, 1);
        strncpy(mv->framework,   (const char*)sqlite3_column_text(stmt, 2), sizeof(mv->framework)-1);
        strncpy(mv->uri,         (const char*)sqlite3_column_text(stmt, 3), sizeof(mv->uri)-1);
        strncpy(mv->description, (const char*)sqlite3_column_text(stmt, 4), sizeof(mv->description)-1);
        strncpy(mv->params_json, (const char*)sqlite3_column_text(stmt, 5), sizeof(mv->params_json)-1);
        mv->created_at = sqlite3_column_int64 (stmt, 6);
    }

    sqlite3_finalize(stmt);
    mr_release();

    *out_list  = arr;
    *out_count = count;
    return MR_OK;

alloc_fail:
    if (arr) free(arr);
sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    mr_release();
    return MR_ERR_GENERAL;
}

/* ───────────────────────────────────────────── Schema & Helpers ────────── */

/*
 * mr_ensure_tables
 * ----------------
 * One-time schema migration executed at registry initialisation.
 */
static int mr_ensure_tables(void) {
    const char *schema_sql =
        "BEGIN;"
        "CREATE TABLE IF NOT EXISTS models ("
        "  id   INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT NOT NULL UNIQUE"
        ");"
        "CREATE TABLE IF NOT EXISTS model_versions ("
        "  id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  model_id     INTEGER NOT NULL,"
        "  version      INTEGER NOT NULL,"
        "  stage        INTEGER NOT NULL,"
        "  framework    TEXT NOT NULL,"
        "  uri          TEXT NOT NULL,"
        "  description  TEXT,"
        "  params_json  TEXT,"
        "  created_at   INTEGER NOT NULL,"
        "  UNIQUE(model_id, version),"
        "  FOREIGN KEY(model_id) REFERENCES models(id)"
        ");"
        "CREATE TABLE IF NOT EXISTS metrics ("
        "  id               INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  model_version_id INTEGER NOT NULL,"
        "  key              TEXT NOT NULL,"
        "  value            REAL NOT NULL,"
        "  logged_at        INTEGER NOT NULL,"
        "  FOREIGN KEY(model_version_id) REFERENCES model_versions(id)"
        ");"
        "COMMIT;";

    char *errmsg = NULL;
    int rc = sqlite3_exec(g_state.db, schema_sql, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Schema migration failed: %s", errmsg);
        sqlite3_free(errmsg);
        return MR_ERR_GENERAL;
    }
    return MR_OK;
}

/*
 * mr_get_or_create_model_id
 * -------------------------
 * Returns the numeric id for a model name, inserting the model if absent.
 */
static int mr_get_or_create_model_id(const char *name, int *model_id_out) {
    sqlite3_stmt *stmt = NULL;
    int rc;

    /* Attempt to fetch existing id */
    const char *qry_sel = "SELECT id FROM models WHERE name = ?1;";
    rc = sqlite3_prepare_v2(g_state.db, qry_sel, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        *model_id_out = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        return MR_OK;
    }
    sqlite3_finalize(stmt); stmt = NULL;

    /* Insert new model */
    const char *qry_ins = "INSERT INTO models(name) VALUES(?1);";
    rc = sqlite3_prepare_v2(g_state.db, qry_ins, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto sqlite_fail;

    sqlite3_bind_text(stmt, 1, name, -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) goto sqlite_fail;

    *model_id_out = (int)sqlite3_last_insert_rowid(g_state.db);
    sqlite3_finalize(stmt);
    return MR_OK;

sqlite_fail:
    LOG_ERROR("SQLite error: %s", sqlite3_errmsg(g_state.db));
    if (stmt) sqlite3_finalize(stmt);
    return MR_ERR_GENERAL;
}

/* ───────────────────────────────────────────── RW-Lock Wrappers ────────── */

static int mr_acquire_read(void) {
    if (!g_state.is_init) return MR_ERR_GENERAL;
    if (pthread_rwlock_rdlock(&g_state.rwlock) != 0) {
        LOG_ERROR("pthread_rwlock_rdlock failed");
        return MR_ERR_GENERAL;
    }
    return MR_OK;
}

static int mr_acquire_write(void) {
    if (!g_state.is_init) return MR_ERR_GENERAL;
    if (pthread_rwlock_wrlock(&g_state.rwlock) != 0) {
        LOG_ERROR("pthread_rwlock_wrlock failed");
        return MR_ERR_GENERAL;
    }
    return MR_OK;
}

static void mr_release(void) {
    pthread_rwlock_unlock(&g_state.rwlock);
}

/* ───────────────────────────────────────────── End of File ─────────────── */

