```c
/**
 * SynestheticCanvas – Palette Service
 * -----------------------------------
 * palette_repository.c
 *
 * A production-ready repository implementation that persists palette entities
 * to a local SQLite database.  The repository exposes a small CRUD surface
 * area that is consumed by the service layer and, ultimately, the GraphQL /
 * REST transport adapters that make up the public API.
 *
 * The implementation purposefully avoids leaking any SQLite-specific details
 * outside the compilation unit:  call-sites work with simple C structs,
 * repository status codes, and pagination helpers.
 *
 * Compile with:
 *     cc -std=c11 -Wall -Wextra -pedantic -pthread \
 *        palette_repository.c -lsqlite3 -o palette_repository.o
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <sqlite3.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "palette_repository.h"

/* -------------------------------------------------------------------------
 * Logging fallback (in case the higher-level logging facility is not linked)
 * ------------------------------------------------------------------------- */
#ifndef LOG_DEBUG
#   define LOG_DEBUG(fmt, ...) fprintf(stderr, "[DEBUG] " fmt "\n", ##__VA_ARGS__)
#endif
#ifndef LOG_INFO
#   define LOG_INFO(fmt, ...)  fprintf(stderr, "[INFO ] " fmt "\n", ##__VA_ARGS__)
#endif
#ifndef LOG_WARN
#   define LOG_WARN(fmt, ...)  fprintf(stderr, "[WARN ] " fmt "\n", ##__VA_ARGS__)
#endif
#ifndef LOG_ERROR
#   define LOG_ERROR(fmt, ...) fprintf(stderr, "[ERROR] " fmt "\n", ##__VA_ARGS__)
#endif

/* -------------------------------------------------------------------------
 * Constants
 * ------------------------------------------------------------------------- */
#define DEFAULT_DB_PATH "./palette.db"
#define SQL_TIMEOUT_MS  3000                /* Busy timeout for write-heavy traffic */

/* -------------------------------------------------------------------------
 * Internal data structures
 * ------------------------------------------------------------------------- */
struct palette_repository {
    sqlite3     *db;
    pthread_mutex_t lock;

    /* Prepared statements (one-time allocation, reused across calls) */
    sqlite3_stmt *stmt_get_by_id;
    sqlite3_stmt *stmt_list_paginated;
    sqlite3_stmt *stmt_insert;
    sqlite3_stmt *stmt_update;
    sqlite3_stmt *stmt_delete;
};

/* -------------------------------------------------------------------------
 * Forward declarations
 * ------------------------------------------------------------------------- */
static int repository_prepare_statements(struct palette_repository *repo);
static void repository_finalize_statements(struct palette_repository *repo);

/* -------------------------------------------------------------------------
 * Public  API
 * ------------------------------------------------------------------------- */
palette_repo_status_t
palette_repository_init(const char *db_file, struct palette_repository **out_repo)
{
    if (!out_repo) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    const char *db_path = (db_file && db_file[0]) ? db_file : DEFAULT_DB_PATH;

    struct palette_repository *repo = calloc(1, sizeof *repo);
    if (!repo) {
        LOG_ERROR("Failed to allocate repository – %s", strerror(errno));
        return PAL_REPO_NO_MEMORY;
    }

    int rc = sqlite3_open(db_path, &repo->db);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Unable to open SQLite database '%s': %s",
                  db_path,
                  sqlite3_errmsg(repo->db));
        sqlite3_close(repo->db);
        free(repo);
        return PAL_REPO_STORAGE_ERROR;
    }

    /* Use WAL for better concurrency and resilience */
    sqlite3_exec(repo->db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);
    sqlite3_exec(repo->db, "PRAGMA foreign_keys=ON;",  NULL, NULL, NULL);
    sqlite3_busy_timeout(repo->db, SQL_TIMEOUT_MS);

    /*
     * Ensure that the schema exists. Migrations for more complex scenarios
     * should be handled by an external tool, but we provide a default here
     * to keep the service self-contained.
     */
    static const char *SCHEMA_SQL =
        "CREATE TABLE IF NOT EXISTS palettes ("
        "    id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    name         TEXT    NOT NULL,"
        "    description  TEXT    DEFAULT '',"
        "    dominant_hex TEXT    NOT NULL CHECK(length(dominant_hex) = 7),"
        "    created_at   INTEGER NOT NULL,"
        "    updated_at   INTEGER NOT NULL"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_palettes_name ON palettes(name);";

    rc = sqlite3_exec(repo->db, SCHEMA_SQL, NULL, NULL, NULL);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Failed to initialize schema: %s", sqlite3_errmsg(repo->db));
        sqlite3_close(repo->db);
        free(repo);
        return PAL_REPO_STORAGE_ERROR;
    }

    if (pthread_mutex_init(&repo->lock, NULL) != 0) {
        LOG_ERROR("pthread_mutex_init failed");
        sqlite3_close(repo->db);
        free(repo);
        return PAL_REPO_INTERNAL_ERROR;
    }

    /* Prepared statements (fail early if they cannot be compiled) */
    if (repository_prepare_statements(repo) != PAL_REPO_OK) {
        palette_repository_shutdown(repo);
        return PAL_REPO_STORAGE_ERROR;
    }

    *out_repo = repo;
    LOG_INFO("Palette repository initialized – db='%s'", db_path);
    return PAL_REPO_OK;
}

void
palette_repository_shutdown(struct palette_repository *repo)
{
    if (!repo) {
        return;
    }

    repository_finalize_statements(repo);
    sqlite3_close(repo->db);
    pthread_mutex_destroy(&repo->lock);
    free(repo);
    LOG_INFO("Palette repository shut down");
}

palette_repo_status_t
palette_repository_create(struct palette_repository *repo,
                          const struct palette *in_palette,
                          uint64_t *out_id)
{
    if (!repo || !in_palette) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    time_t now = time(NULL);

    pthread_mutex_lock(&repo->lock);

    sqlite3_reset(repo->stmt_insert);
    sqlite3_clear_bindings(repo->stmt_insert);

    sqlite3_bind_text (repo->stmt_insert, 1, in_palette->name,        -1, SQLITE_STATIC);
    sqlite3_bind_text (repo->stmt_insert, 2, in_palette->description, -1, SQLITE_STATIC);
    sqlite3_bind_text (repo->stmt_insert, 3, in_palette->dominant_hex,-1, SQLITE_STATIC);
    sqlite3_bind_int64(repo->stmt_insert, 4, (sqlite3_int64)now);
    sqlite3_bind_int64(repo->stmt_insert, 5, (sqlite3_int64)now);

    int rc = sqlite3_step(repo->stmt_insert);
    if (rc != SQLITE_DONE) {
        LOG_ERROR("INSERT failed: %s", sqlite3_errmsg(repo->db));
        pthread_mutex_unlock(&repo->lock);
        return PAL_REPO_STORAGE_ERROR;
    }

    uint64_t id = (uint64_t)sqlite3_last_insert_rowid(repo->db);
    if (out_id) {
        *out_id = id;
    }

    pthread_mutex_unlock(&repo->lock);
    LOG_DEBUG("Palette created (id=%" PRIu64 ")", id);
    return PAL_REPO_OK;
}

palette_repo_status_t
palette_repository_get(const struct palette_repository *repo,
                       uint64_t id,
                       struct palette *out_palette)
{
    if (!repo || !out_palette) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    pthread_mutex_lock((pthread_mutex_t *)&repo->lock); /* cast away const */

    sqlite3_reset(repo->stmt_get_by_id);
    sqlite3_clear_bindings(repo->stmt_get_by_id);
    sqlite3_bind_int64(repo->stmt_get_by_id, 1, (sqlite3_int64)id);

    int rc = sqlite3_step(repo->stmt_get_by_id);
    if (rc == SQLITE_ROW) {
        out_palette->id = (uint64_t)sqlite3_column_int64(repo->stmt_get_by_id, 0);
        strncpy(out_palette->name,
                (const char *)sqlite3_column_text(repo->stmt_get_by_id, 1),
                sizeof(out_palette->name) - 1);

        strncpy(out_palette->description,
                (const char *)sqlite3_column_text(repo->stmt_get_by_id, 2),
                sizeof(out_palette->description) - 1);

        strncpy(out_palette->dominant_hex,
                (const char *)sqlite3_column_text(repo->stmt_get_by_id, 3),
                sizeof(out_palette->dominant_hex) - 1);

        out_palette->created_at = (time_t)sqlite3_column_int64(repo->stmt_get_by_id, 4);
        out_palette->updated_at = (time_t)sqlite3_column_int64(repo->stmt_get_by_id, 5);

        sqlite3_reset(repo->stmt_get_by_id);
        pthread_mutex_unlock((pthread_mutex_t *)&repo->lock);
        return PAL_REPO_OK;
    }

    sqlite3_reset(repo->stmt_get_by_id);
    pthread_mutex_unlock((pthread_mutex_t *)&repo->lock);

    if (rc == SQLITE_DONE) {
        return PAL_REPO_NOT_FOUND;
    } else {
        LOG_ERROR("SELECT failed: %s", sqlite3_errmsg(repo->db));
        return PAL_REPO_STORAGE_ERROR;
    }
}

palette_repo_status_t
palette_repository_list(const struct palette_repository *repo,
                        struct palette_pagination pagination,
                        struct palette_list *out_list)
{
    if (!repo || !out_list) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    if (pagination.limit == 0) {
        pagination.limit = 50; /* sane default */
    }

    pthread_mutex_lock((pthread_mutex_t *)&repo->lock); /* cast away const */

    sqlite3_reset(repo->stmt_list_paginated);
    sqlite3_clear_bindings(repo->stmt_list_paginated);
    sqlite3_bind_int (repo->stmt_list_paginated, 1, (int)pagination.limit);
    sqlite3_bind_int (repo->stmt_list_paginated, 2, (int)pagination.offset);

    struct palette *items   = NULL;
    size_t          count   = 0;
    size_t          capacity= 0;

    int rc;
    while ((rc = sqlite3_step(repo->stmt_list_paginated)) == SQLITE_ROW) {
        if (count == capacity) {
            size_t new_cap = capacity == 0 ? 8 : capacity * 2;
            void *tmp = realloc(items, new_cap * sizeof *items);
            if (!tmp) {
                LOG_ERROR("Out of memory during list pagination");
                free(items);
                sqlite3_reset(repo->stmt_list_paginated);
                pthread_mutex_unlock((pthread_mutex_t *)&repo->lock);
                return PAL_REPO_NO_MEMORY;
            }
            items = tmp;
            capacity = new_cap;
        }

        struct palette *p = &items[count++];
        memset(p, 0, sizeof *p);

        p->id = (uint64_t)sqlite3_column_int64(repo->stmt_list_paginated, 0);

        strncpy(p->name,
                (const char *)sqlite3_column_text(repo->stmt_list_paginated, 1),
                sizeof(p->name) - 1);

        strncpy(p->description,
                (const char *)sqlite3_column_text(repo->stmt_list_paginated, 2),
                sizeof(p->description) - 1);

        strncpy(p->dominant_hex,
                (const char *)sqlite3_column_text(repo->stmt_list_paginated, 3),
                sizeof(p->dominant_hex) - 1);

        p->created_at = (time_t)sqlite3_column_int64(repo->stmt_list_paginated, 4);
        p->updated_at = (time_t)sqlite3_column_int64(repo->stmt_list_paginated, 5);
    }

    sqlite3_reset(repo->stmt_list_paginated);
    pthread_mutex_unlock((pthread_mutex_t *)&repo->lock);

    if (rc != SQLITE_DONE) {
        LOG_ERROR("LIST failed: %s", sqlite3_errmsg(repo->db));
        free(items);
        return PAL_REPO_STORAGE_ERROR;
    }

    out_list->items = items;
    out_list->count = count;
    return PAL_REPO_OK;
}

palette_repo_status_t
palette_repository_update(struct palette_repository *repo,
                          const struct palette *palette_in)
{
    if (!repo || !palette_in) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    time_t now = time(NULL);

    pthread_mutex_lock(&repo->lock);

    sqlite3_reset(repo->stmt_update);
    sqlite3_clear_bindings(repo->stmt_update);

    sqlite3_bind_text (repo->stmt_update, 1, palette_in->name,        -1, SQLITE_STATIC);
    sqlite3_bind_text (repo->stmt_update, 2, palette_in->description, -1, SQLITE_STATIC);
    sqlite3_bind_text (repo->stmt_update, 3, palette_in->dominant_hex,-1, SQLITE_STATIC);
    sqlite3_bind_int64(repo->stmt_update, 4, (sqlite3_int64)now);
    sqlite3_bind_int64(repo->stmt_update, 5, (sqlite3_int64)palette_in->id);

    int rc = sqlite3_step(repo->stmt_update);

    if (rc != SQLITE_DONE) {
        LOG_ERROR("UPDATE failed: %s", sqlite3_errmsg(repo->db));
        sqlite3_reset(repo->stmt_update);
        pthread_mutex_unlock(&repo->lock);
        return PAL_REPO_STORAGE_ERROR;
    }

    int changes = sqlite3_changes(repo->db);
    sqlite3_reset(repo->stmt_update);
    pthread_mutex_unlock(&repo->lock);

    return changes == 0 ? PAL_REPO_NOT_FOUND : PAL_REPO_OK;
}

palette_repo_status_t
palette_repository_delete(struct palette_repository *repo, uint64_t id)
{
    if (!repo) {
        return PAL_REPO_INVALID_ARGUMENT;
    }

    pthread_mutex_lock(&repo->lock);

    sqlite3_reset(repo->stmt_delete);
    sqlite3_clear_bindings(repo->stmt_delete);
    sqlite3_bind_int64(repo->stmt_delete, 1, (sqlite3_int64)id);

    int rc = sqlite3_step(repo->stmt_delete);
    if (rc != SQLITE_DONE) {
        LOG_ERROR("DELETE failed: %s", sqlite3_errmsg(repo->db));
        sqlite3_reset(repo->stmt_delete);
        pthread_mutex_unlock(&repo->lock);
        return PAL_REPO_STORAGE_ERROR;
    }

    int changes = sqlite3_changes(repo->db);
    sqlite3_reset(repo->stmt_delete);
    pthread_mutex_unlock(&repo->lock);

    return changes == 0 ? PAL_REPO_NOT_FOUND : PAL_REPO_OK;
}

/* -------------------------------------------------------------------------
 * Internal helpers
 * ------------------------------------------------------------------------- */
static int
repository_prepare_statements(struct palette_repository *repo)
{
    assert(repo && repo->db);

    struct {
        sqlite3_stmt **stmt;
        const char    *sql;
    } statements[] = {
        {
            &repo->stmt_get_by_id,
            "SELECT id, name, description, dominant_hex, created_at, updated_at "
            "  FROM palettes "
            " WHERE id = ?1;"
        },
        {
            &repo->stmt_list_paginated,
            "SELECT id, name, description, dominant_hex, created_at, updated_at "
            "  FROM palettes "
            " ORDER BY id "
            " LIMIT ?1 OFFSET ?2;"
        },
        {
            &repo->stmt_insert,
            "INSERT INTO palettes "
            " (name, description, dominant_hex, created_at, updated_at) "
            "VALUES "
            " (?1, ?2, ?3, ?4, ?5);"
        },
        {
            &repo->stmt_update,
            "UPDATE palettes "
            "   SET name = ?1, "
            "       description = ?2, "
            "       dominant_hex = ?3, "
            "       updated_at = ?4 "
            " WHERE id = ?5;"
        },
        {
            &repo->stmt_delete,
            "DELETE FROM palettes WHERE id = ?1;"
        },
    };

    for (size_t i = 0; i < sizeof statements / sizeof statements[0]; ++i) {
        int rc = sqlite3_prepare_v2(repo->db,
                                    statements[i].sql,
                                    -1,
                                    statements[i].stmt,
                                    NULL);
        if (rc != SQLITE_OK) {
            LOG_ERROR("Failed to compile statement (%zu): %s",
                      i,
                      sqlite3_errmsg(repo->db));
            return PAL_REPO_STORAGE_ERROR;
        }
    }
    return PAL_REPO_OK;
}

static void
repository_finalize_statements(struct palette_repository *repo)
{
    if (!repo) {
        return;
    }
    sqlite3_finalize(repo->stmt_get_by_id);
    sqlite3_finalize(repo->stmt_list_paginated);
    sqlite3_finalize(repo->stmt_insert);
    sqlite3_finalize(repo->stmt_update);
    sqlite3_finalize(repo->stmt_delete);
}

/* -------------------------------------------------------------------------
 * End of file
 * ------------------------------------------------------------------------- */
```