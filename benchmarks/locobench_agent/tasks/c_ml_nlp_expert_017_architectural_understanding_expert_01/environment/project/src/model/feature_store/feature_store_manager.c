/*
 *  LexiLearn Orchestrator
 *  File:    feature_store_manager.c
 *  Author:  LexiLearn Core Team
 *  License: Apache-2.0
 *
 *  Description:
 *      Thread-safe Feature Store Manager responsible for persisting and
 *      fetching engineered features as part of the Model layer’s shared
 *      feature store.  The implementation relies on an embedded SQLite
 *      database to keep the footprint low while benefiting from ACID
 *      guarantees.  The manager supports feature-set versioning,
 *      JSON-encoded metadata, and binary blobs for numerical vectors.
 *
 *  Build:
 *      gcc -Wall -Wextra -pedantic -std=c11 -lsqlite3 -lpthread \
 *          -I../include -c feature_store_manager.c
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>

#include "feature_store_manager.h" /* public interface */

/* -------------------------------------------------------------------------- */
/*                              CONFIGURATION                                 */
/* -------------------------------------------------------------------------- */

#define FSM_SCHEMA_VERSION     1
#define FSM_DB_FILENAME        "lexilearn_feature_store.db"
#define FSM_DEFAULT_TIMEOUT_MS 5000  /* SQLite busy timeout            */
#define FSM_LOG_TAG            "FeatureStoreManager"

/* Toggle verbose SQL debug output */
#ifndef FSM_SQL_DEBUG
#define FSM_SQL_DEBUG          0
#endif

/* -------------------------------------------------------------------------- */
/*                                MACROS                                      */
/* -------------------------------------------------------------------------- */

#if defined(__GNUC__) || defined(__clang__)
#define UNUSED(x) (void)(x)
#else
#define UNUSED(x)
#endif

/* Simple logging macros; can be swapped for syslog or spdlog later */
#define FSM_LOG_ERR(fmt, ...)  fprintf(stderr, "[%s] ERROR: " fmt "\n", FSM_LOG_TAG, ##__VA_ARGS__)
#define FSM_LOG_INFO(fmt, ...) fprintf(stdout, "[%s] INFO:  " fmt "\n", FSM_LOG_TAG, ##__VA_ARGS__)
#define FSM_LOG_DBG(fmt, ...)                                                         \
    do {                                                                              \
        if (FSM_SQL_DEBUG) {                                                          \
            fprintf(stdout, "[%s] DEBUG: " fmt "\n", FSM_LOG_TAG, ##__VA_ARGS__);     \
        }                                                                             \
    } while (0)

/* -------------------------------------------------------------------------- */
/*                              DATA STRUCTURES                               */
/* -------------------------------------------------------------------------- */

typedef struct
{
    sqlite3   *db;       /* Shared SQLite handle */
    pthread_mutex_t lock;
    volatile bool is_initialized;
} fsm_context_t;

/* Singleton context */
static fsm_context_t g_ctx = { 0 };

/* -------------------------------------------------------------------------- */
/*                             STATIC UTILITIES                               */
/* -------------------------------------------------------------------------- */

/* RAII-like helper for SQLite statement life-cycle */
#define SQLITE_STMT_GUARD_BEGIN(stmt_ptr)    sqlite3_stmt *__stmt = (stmt_ptr);
#define SQLITE_STMT_GUARD_END()              \
    do {                                     \
        if (__stmt) {                        \
            sqlite3_finalize(__stmt);        \
        }                                    \
    } while (0)

static inline const char *fsm_strerror(int err)
{
    switch (err)
    {
        case FSM_OK:              return "FSM_OK";
        case FSM_EINIT:           return "FSM_EINIT";
        case FSM_EINVAL:          return "FSM_EINVAL";
        case FSM_ENOTFOUND:       return "FSM_ENOTFOUND";
        case FSM_EDB:             return "FSM_EDB";
        case FSM_EIO:             return "FSM_EIO";
        case FSM_ELOCK:           return "FSM_ELOCK";
        default:                  return "FSM_UNKNOWN";
    }
}

/* Acquire global mutex; if lock acquisition fails, return FSM_ELOCK */
static fsm_status_t fsm_lock(void)
{
    int rc = pthread_mutex_lock(&g_ctx.lock);
    if (rc != 0)
    {
        FSM_LOG_ERR("pthread_mutex_lock failed: %s", strerror(rc));
        return FSM_ELOCK;
    }
    return FSM_OK;
}

static void fsm_unlock(void)
{
    int rc = pthread_mutex_unlock(&g_ctx.lock);
    if (rc != 0)
    {
        /* We cannot do much at this point */
        FSM_LOG_ERR("pthread_mutex_unlock failed: %s", strerror(rc));
    }
}

/* Check whether file exists */
static bool fsm_file_exists(const char *path)
{
    struct stat sb;
    return (stat(path, &sb) == 0);
}

/* Create directory path if it does not exist (recursive single level) */
static int fsm_ensure_dir(const char *path)
{
    struct stat st = { 0 };

    if (stat(path, &st) == -1)
    {
        if (mkdir(path, 0700) == -1)
        {
            FSM_LOG_ERR("mkdir(%s) failed: %s", path, strerror(errno));
            return -1;
        }
    }
    return 0;
}

/* Initialize SQLite DB schema (idempotent) */
static int fsm_init_schema(void)
{
    static const char *schema_sql =
        "PRAGMA foreign_keys = ON;"

        "CREATE TABLE IF NOT EXISTS meta ("
        "    key TEXT PRIMARY KEY,"
        "    value TEXT NOT NULL"
        ");"

        "CREATE TABLE IF NOT EXISTS feature_vectors ("
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    feature_set   TEXT NOT NULL,"
        "    entity_id     TEXT NOT NULL,"
        "    version       INTEGER NOT NULL,"
        "    updated_ts    INTEGER NOT NULL,"
        "    metadata_json TEXT,"
        "    vector        BLOB NOT NULL,"
        "    vector_dim    INTEGER NOT NULL,"
        "    UNIQUE(feature_set, entity_id, version)"
        ");"

        "CREATE INDEX IF NOT EXISTS idx_fv_lookup "
        "ON feature_vectors(feature_set, entity_id, version DESC);";

    char *errmsg = NULL;
    int rc = sqlite3_exec(g_ctx.db, schema_sql, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK)
    {
        FSM_LOG_ERR("SQLite schema initialization failed: %s", errmsg);
        sqlite3_free(errmsg);
        return -1;
    }

    /* Store schema version (overwrite for simplicity) */
    sqlite3_stmt *stmt = NULL;
    rc = sqlite3_prepare_v2(g_ctx.db,
                            "REPLACE INTO meta (key, value) VALUES ('schema_version', ?);",
                            -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return -1;
    }

    SQLITE_STMT_GUARD_BEGIN(stmt);
    sqlite3_bind_int(stmt, 1, FSM_SCHEMA_VERSION);
    rc = sqlite3_step(stmt);
    SQLITE_STMT_GUARD_END();

    if (rc != SQLITE_DONE) {
        FSM_LOG_ERR("SQLite step failed: %s", sqlite3_errmsg(g_ctx.db));
        return -1;
    }

    return 0;
}

/* -------------------------------------------------------------------------- */
/*                           PUBLIC API IMPLEMENTATION                        */
/* -------------------------------------------------------------------------- */

fsm_status_t fsm_init(const char *db_root_dir)
{
    if (g_ctx.is_initialized)
        return FSM_OK;

    if (!db_root_dir || strlen(db_root_dir) == 0)
        return FSM_EINVAL;

    if (fsm_ensure_dir(db_root_dir) != 0)
        return FSM_EIO;

    /* Compose DB path */
    char db_path[PATH_MAX] = { 0 };
    snprintf(db_path, sizeof(db_path), "%s/%s", db_root_dir, FSM_DB_FILENAME);

    int rc = sqlite3_open(db_path, &g_ctx.db);
    if (rc != SQLITE_OK)
    {
        FSM_LOG_ERR("Cannot open feature store DB '%s': %s", db_path, sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    /* Configure busy timeout for concurrent access */
    sqlite3_busy_timeout(g_ctx.db, FSM_DEFAULT_TIMEOUT_MS);

    /* Enable WAL journal for better concurrency */
    sqlite3_exec(g_ctx.db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);

    /* Create schema if absent */
    if (fsm_init_schema() != 0)
    {
        sqlite3_close(g_ctx.db);
        g_ctx.db = NULL;
        return FSM_EDB;
    }

    /* Init mutex */
    if (pthread_mutex_init(&g_ctx.lock, NULL) != 0)
    {
        FSM_LOG_ERR("pthread_mutex_init failed");
        sqlite3_close(g_ctx.db);
        g_ctx.db = NULL;
        return FSM_ELOCK;
    }

    g_ctx.is_initialized = true;
    FSM_LOG_INFO("Feature Store Manager initialized at %s", db_path);
    return FSM_OK;
}

fsm_status_t fsm_shutdown(void)
{
    if (!g_ctx.is_initialized)
        return FSM_OK;

    /* Close DB connection */
    if (g_ctx.db)
    {
        sqlite3_close(g_ctx.db);
        g_ctx.db = NULL;
    }

    pthread_mutex_destroy(&g_ctx.lock);
    g_ctx.is_initialized = false;
    FSM_LOG_INFO("Feature Store Manager shutdown complete");
    return FSM_OK;
}

fsm_status_t fsm_put_vector(const char       *feature_set,
                            const char       *entity_id,
                            int64_t           version,
                            const float      *vector,
                            size_t            dim,
                            const char       *metadata_json)
{
    if (!g_ctx.is_initialized)
        return FSM_EINIT;

    if (!feature_set || !entity_id || !vector || dim == 0)
        return FSM_EINVAL;

    /* Serialize float array into binary blob */
    const size_t bytes = dim * sizeof(float);

    fsm_status_t status = fsm_lock();
    if (status != FSM_OK)
        return status;

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(
        g_ctx.db,
        "INSERT INTO feature_vectors "
        "(feature_set, entity_id, version, updated_ts, metadata_json, vector, vector_dim) "
        "VALUES (?, ?, ?, strftime('%s','now'), ?, ?, ?);",
        -1, &stmt, NULL);

    if (rc != SQLITE_OK)
    {
        fsm_unlock();
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    SQLITE_STMT_GUARD_BEGIN(stmt);

    sqlite3_bind_text(stmt, 1, feature_set, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, entity_id, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, version);
    if (metadata_json)
        sqlite3_bind_text(stmt, 4, metadata_json, -1, SQLITE_TRANSIENT);
    else
        sqlite3_bind_null(stmt, 4);
    sqlite3_bind_blob(stmt, 5, vector, (int)bytes, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, (int)dim);

    rc = sqlite3_step(stmt);
    SQLITE_STMT_GUARD_END();
    fsm_unlock();

    if (rc != SQLITE_DONE)
    {
        FSM_LOG_ERR("SQLite step failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    FSM_LOG_DBG("Inserted vector for set=%s, entity=%s, version=%" PRId64, feature_set, entity_id, version);
    return FSM_OK;
}

/* Helper to map SQLite row to out parameters */
static fsm_status_t fsm_map_row_to_vector(sqlite3_stmt *stmt,
                                          float       **out_vec,
                                          size_t       *out_dim,
                                          char        **out_metadata)
{
    const void *blob   = sqlite3_column_blob(stmt, 0);
    int         bytes  = sqlite3_column_bytes(stmt, 0);
    int         dim    = sqlite3_column_int(stmt, 2);
    const char *meta   = (const char *)sqlite3_column_text(stmt, 1);

    if (!blob || bytes <= 0 || dim <= 0 || (size_t)bytes != (size_t)dim * sizeof(float))
        return FSM_EDB;

    float *vec = malloc((size_t)bytes);
    if (!vec)
        return FSM_EIO;
    memcpy(vec, blob, (size_t)bytes);

    *out_vec  = vec;
    *out_dim  = (size_t)dim;

    if (out_metadata)
    {
        if (meta)
        {
            *out_metadata = strdup(meta);
            if (!*out_metadata)
            {
                free(vec);
                return FSM_EIO;
            }
        }
        else
        {
            *out_metadata = NULL;
        }
    }
    return FSM_OK;
}

fsm_status_t fsm_get_vector(const char  *feature_set,
                            const char  *entity_id,
                            int64_t      version,     /* if -1, fetch latest */
                            float      **out_vector,  /* out: malloc'd */
                            size_t      *out_dim,
                            char       **out_metadata_json) /* out: malloc'd (can be NULL) */
{
    if (!g_ctx.is_initialized)
        return FSM_EINIT;

    if (!feature_set || !entity_id || !out_vector || !out_dim)
        return FSM_EINVAL;

    fsm_status_t status = fsm_lock();
    if (status != FSM_OK)
        return status;

    const char *sql_latest =
        "SELECT vector, metadata_json, vector_dim "
        "FROM feature_vectors "
        "WHERE feature_set=? AND entity_id=? "
        "ORDER BY version DESC LIMIT 1;";

    const char *sql_specific =
        "SELECT vector, metadata_json, vector_dim "
        "FROM feature_vectors "
        "WHERE feature_set=? AND entity_id=? AND version=?;";

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(
        g_ctx.db,
        (version < 0) ? sql_latest : sql_specific,
        -1, &stmt, NULL);

    if (rc != SQLITE_OK)
    {
        fsm_unlock();
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    SQLITE_STMT_GUARD_BEGIN(stmt);

    sqlite3_bind_text(stmt, 1, feature_set, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, entity_id, -1, SQLITE_TRANSIENT);
    if (version >= 0)
        sqlite3_bind_int64(stmt, 3, version);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW)
    {
        status = fsm_map_row_to_vector(stmt, out_vector, out_dim, out_metadata_json);
    }
    else if (rc == SQLITE_DONE)
    {
        status = FSM_ENOTFOUND;
    }
    else
    {
        status = FSM_EDB;
        FSM_LOG_ERR("SQLite step failed: %s", sqlite3_errmsg(g_ctx.db));
    }

    SQLITE_STMT_GUARD_END();
    fsm_unlock();
    return status;
}

fsm_status_t fsm_get_latest_version(const char *feature_set,
                                    const char *entity_id,
                                    int64_t     *out_version)
{
    if (!g_ctx.is_initialized)
        return FSM_EINIT;

    if (!feature_set || !entity_id || !out_version)
        return FSM_EINVAL;

    fsm_status_t status = fsm_lock();
    if (status != FSM_OK)
        return status;

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(
        g_ctx.db,
        "SELECT version FROM feature_vectors "
        "WHERE feature_set=? AND entity_id=? "
        "ORDER BY version DESC LIMIT 1;",
        -1, &stmt, NULL);

    if (rc != SQLITE_OK)
    {
        fsm_unlock();
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    SQLITE_STMT_GUARD_BEGIN(stmt);
    sqlite3_bind_text(stmt, 1, feature_set, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, entity_id, -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW)
    {
        *out_version = sqlite3_column_int64(stmt, 0);
        status = FSM_OK;
    }
    else if (rc == SQLITE_DONE)
    {
        status = FSM_ENOTFOUND;
    }
    else
    {
        FSM_LOG_ERR("SQLite step failed: %s", sqlite3_errmsg(g_ctx.db));
        status = FSM_EDB;
    }

    SQLITE_STMT_GUARD_END();
    fsm_unlock();
    return status;
}

/* Delete all versions for entity OR specific version if provided */
fsm_status_t fsm_delete_vector(const char *feature_set,
                               const char *entity_id,
                               int64_t     version) /* -1 => ALL versions */
{
    if (!g_ctx.is_initialized)
        return FSM_EINIT;

    if (!feature_set || !entity_id)
        return FSM_EINVAL;

    fsm_status_t status = fsm_lock();
    if (status != FSM_OK)
        return status;

    const char *sql_all =
        "DELETE FROM feature_vectors WHERE feature_set=? AND entity_id=?;";

    const char *sql_specific =
        "DELETE FROM feature_vectors "
        "WHERE feature_set=? AND entity_id=? AND version=?;";

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(
        g_ctx.db,
        (version < 0) ? sql_all : sql_specific,
        -1, &stmt, NULL);

    if (rc != SQLITE_OK)
    {
        fsm_unlock();
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    SQLITE_STMT_GUARD_BEGIN(stmt);
    sqlite3_bind_text(stmt, 1, feature_set, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, entity_id, -1, SQLITE_TRANSIENT);
    if (version >= 0)
        sqlite3_bind_int64(stmt, 3, version);

    rc = sqlite3_step(stmt);
    SQLITE_STMT_GUARD_END();
    fsm_unlock();

    if (rc != SQLITE_DONE)
    {
        FSM_LOG_ERR("SQLite deletion failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    return FSM_OK;
}

/* -------------------------------------------------------------------------- */
/*                       OPTIONAL DIAGNOSTIC UTILITIES                        */
/* -------------------------------------------------------------------------- */

fsm_status_t fsm_dump_stats(FILE *out)
{
    if (!g_ctx.is_initialized)
        return FSM_EINIT;
    if (!out)
        out = stdout;

    const char *sql =
        "SELECT feature_set, COUNT(*), "
        "       MAX(version) AS latest_version "
        "FROM feature_vectors "
        "GROUP BY feature_set;";

    fsm_status_t status = fsm_lock();
    if (status != FSM_OK)
        return status;

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(g_ctx.db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK)
    {
        fsm_unlock();
        FSM_LOG_ERR("SQLite prepare failed: %s", sqlite3_errmsg(g_ctx.db));
        return FSM_EDB;
    }

    fprintf(out, "Feature Store Statistics\n");
    fprintf(out, "------------------------\n");
    fprintf(out, "%-24s %-10s %-10s\n", "Feature Set", "Rows", "Latest Ver");

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW)
    {
        const char *fs     = (const char *)sqlite3_column_text(stmt, 0);
        int         rows   = sqlite3_column_int(stmt, 1);
        int         latest = sqlite3_column_int(stmt, 2);
        fprintf(out, "%-24s %-10d %-10d\n", fs ? fs : "(null)", rows, latest);
    }

    SQLITE_STMT_GUARD_END();
    fsm_unlock();

    return FSM_OK;
}

/* -------------------------------------------------------------------------- */
/*                          Fault Injection / Testing                         */
/* -------------------------------------------------------------------------- */
#ifdef FSM_UNIT_TEST

/* Very light-weight unit test harness; compile with:
 * gcc -DFSM_UNIT_TEST -std=c11 -Wall -Wextra feature_store_manager.c -lsqlite3 -lpthread -o fsm_test
 */
#include <math.h>

static void assert_true(bool cond, const char *msg)
{
    if (!cond)
    {
        fprintf(stderr, "Assertion failed: %s\n", msg);
        exit(EXIT_FAILURE);
    }
}

int main(void)
{
    const char *tmpdir = "/tmp/lexilearn_fs_test";
    /* Clean slate */
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "rm -rf %s && mkdir -p %s", tmpdir, tmpdir);
    system(cmd);

    assert_true(fsm_init(tmpdir) == FSM_OK, "fsm_init failed");

    float vec[3] = { 1.0f, 2.0f, 3.0f };
    assert_true(fsm_put_vector("sentiment", "essay_42", 1, vec, 3, "{\"note\":\"baseline\"}") == FSM_OK,
                "fsm_put_vector");

    float *out_vec = NULL;
    size_t dim = 0;
    char *meta = NULL;
    assert_true(fsm_get_vector("sentiment", "essay_42", -1, &out_vec, &dim, &meta) == FSM_OK,
                "fsm_get_vector");

    assert_true(dim == 3 && fabs(out_vec[2] - 3.0f) < 1e-5, "vector mismatch");
    free(out_vec);
    free(meta);

    int64_t latest = -1;
    assert_true(fsm_get_latest_version("sentiment", "essay_42", &latest) == FSM_OK,
                "fsm_get_latest_version");
    assert_true(latest == 1, "latest version mismatch");

    assert_true(fsm_shutdown() == FSM_OK, "fsm_shutdown");

    printf("All Feature Store Manager tests passed.\n");
    return 0;
}

#endif /* FSM_UNIT_TEST */

/* -------------------------------------------------------------------------- */
/*                               END OF FILE                                  */
/* -------------------------------------------------------------------------- */
