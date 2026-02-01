```c
/**
 * SynestheticCanvas – Narrative Service
 * -------------------------------------
 * narrative_repository.c
 *
 * A thread-safe repository implementation responsible for CRUD operations on the
 * `narratives` table.  Uses SQLite3 for illustrative purposes, but the public
 * interface is storage-agnostic so the underlying driver can be swapped with a
 * Postgres, MySQL, or in-memory adapter without changing callers.
 *
 * Build flags (example):
 *   cc -Wall -Wextra -pedantic -std=c11 -pthread \
 *      narrative_repository.c -lsqlite3 -o narrative_repository_test
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <sqlite3.h>

/* ──────────────── Logging Helpers ───────────────── */

#ifndef NARR_LOG_LEVEL
#define NARR_LOG_LEVEL 3   /* 0=OFF 1=ERROR 2=WARN 3=INFO 4=DEBUG */
#endif

#define _LOG_PREFIX       "[narrative-repository] "
#define _LOG(level, fmt, ...) \
    do {                                                            \
        if (level <= NARR_LOG_LEVEL) {                              \
            fprintf((level == 1) ? stderr : stdout,                \
                    _LOG_PREFIX fmt "%s",                           \
                    ##__VA_ARGS__,                                  \
                    (level <= 2 ? ": " : ""),                       \
                    (level == 1 ? strerror(errno) : ""));           \
            if (level <= 2) fputc('\n', stderr); else fputc('\n', stdout); \
        }                                                           \
    } while (0)

#define LOG_ERR(fmt, ...)   _LOG(1, "ERROR: " fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  _LOG(2, "WARN : " fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)  _LOG(3, "INFO : " fmt, ##__VA_ARGS__)
#define LOG_DEBUG(fmt, ...) _LOG(4, "DEBUG: " fmt, ##__VA_ARGS__)

/* ──────────────── Models ───────────────── */

typedef struct {
    int64_t  id;
    char    *title;
    char    *author;
    char    *content;     /* May be arbitrarily long  */
    char    *created_at;  /* ISO-8601 representation  */
    char    *updated_at;  /* ISO-8601 representation  */
    uint32_t version;     /* For optimistic locking   */
    bool     is_deleted;
} Narrative;

/* Forward declaration for cleanup helpers */
static void narrative_free(Narrative *n);

/* ──────────────── Repository Interface ───────────────── */

typedef struct {
    sqlite3        *db;
    pthread_mutex_t lock;
} NarrativeRepository;

/* Callback signature used by list operation */
typedef bool (*narrative_iter_cb)(const Narrative *record, void *user_data);

/* API */
int  narrative_repo_init(NarrativeRepository *repo, const char *db_path);
void narrative_repo_close(NarrativeRepository *repo);

int  narrative_repo_migrate(NarrativeRepository *repo);

int  narrative_repo_create(NarrativeRepository *repo,
                           const Narrative    *input,
                           int64_t            *out_id);

int  narrative_repo_get(NarrativeRepository *repo,
                        int64_t id,
                        Narrative *out_record);

int  narrative_repo_update(NarrativeRepository *repo,
                           const Narrative    *record);

int  narrative_repo_soft_delete(NarrativeRepository *repo, int64_t id);

int  narrative_repo_list(NarrativeRepository *repo,
                         size_t limit,
                         size_t offset,
                         narrative_iter_cb cb,
                         void *user_data);

/* ──────────────── Utility Functions ───────────────── */

static char *current_iso8601(void)
{
    time_t     now = time(NULL);
    struct tm  tm_now;
    if (gmtime_r(&now, &tm_now) == NULL) {
        return NULL;
    }
    char *buf = malloc(21); /* "YYYY-MM-DDTHH:MM:SSZ" + '\0' */
    if (!buf) return NULL;
    strftime(buf, 21, "%Y-%m-%dT%H:%M:%SZ", &tm_now);
    return buf;
}

static int exec_sql(sqlite3 *db, const char *sql)
{
    char *errmsg = NULL;
    int   rc     = sqlite3_exec(db, sql, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        LOG_ERR("SQL error: %s", errmsg);
        sqlite3_free(errmsg);
    }
    return rc;
}

static Narrative *narrative_dup(const Narrative *src)
{
    if (!src) return NULL;
    Narrative *dst = calloc(1, sizeof(*dst));
    if (!dst) return NULL;

    dst->id         = src->id;
    dst->title      = src->title      ? strdup(src->title)   : NULL;
    dst->author     = src->author     ? strdup(src->author)  : NULL;
    dst->content    = src->content    ? strdup(src->content) : NULL;
    dst->created_at = src->created_at ? strdup(src->created_at) : NULL;
    dst->updated_at = src->updated_at ? strdup(src->updated_at) : NULL;
    dst->version    = src->version;
    dst->is_deleted = src->is_deleted;

    return dst;
}

static void narrative_free(Narrative *n)
{
    if (!n) return;
    free(n->title);
    free(n->author);
    free(n->content);
    free(n->created_at);
    free(n->updated_at);
    free(n);
}

/* ──────────────── Implementation ───────────────── */

int narrative_repo_init(NarrativeRepository *repo, const char *db_path)
{
    if (!repo || !db_path) return SQLITE_MISUSE;

    memset(repo, 0, sizeof(*repo));

    int rc = sqlite3_open(db_path, &repo->db);
    if (rc != SQLITE_OK) {
        LOG_ERR("Failed to open database %s", db_path);
        return rc;
    }

    pthread_mutex_init(&repo->lock, NULL);

    return narrative_repo_migrate(repo);
}

void narrative_repo_close(NarrativeRepository *repo)
{
    if (!repo) return;

    sqlite3_close(repo->db);
    pthread_mutex_destroy(&repo->lock);
    memset(repo, 0, sizeof(*repo));
}

int narrative_repo_migrate(NarrativeRepository *repo)
{
    const char *sql =
        "CREATE TABLE IF NOT EXISTS narratives ("
        "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  title       TEXT    NOT NULL,"
        "  author      TEXT    NOT NULL,"
        "  content     TEXT    NOT NULL,"
        "  created_at  TEXT    NOT NULL,"
        "  updated_at  TEXT    NOT NULL,"
        "  version     INTEGER NOT NULL DEFAULT 1,"
        "  is_deleted  INTEGER NOT NULL DEFAULT 0"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_narratives_not_deleted "
        "ON narratives(is_deleted);";

    pthread_mutex_lock(&repo->lock);
    int rc = exec_sql(repo->db, sql);
    pthread_mutex_unlock(&repo->lock);

    if (rc == SQLITE_OK)
        LOG_INFO("Migration completed successfully");

    return rc;
}

int narrative_repo_create(NarrativeRepository *repo,
                          const Narrative    *input,
                          int64_t            *out_id)
{
    if (!repo || !input) return SQLITE_MISUSE;

    const char *sql =
        "INSERT INTO narratives (title, author, content, created_at, "
        "updated_at, version, is_deleted) "
        "VALUES (?1, ?2, ?3, ?4, ?5, 1, 0);";

    char *now = current_iso8601();
    if (!now) return SQLITE_NOMEM;

    pthread_mutex_lock(&repo->lock);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto cleanup;

    sqlite3_bind_text(stmt, 1, input->title,  -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, input->author, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, input->content, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, now, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 5, now, -1, SQLITE_STATIC);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_DONE) {
        if (out_id)
            *out_id = sqlite3_last_insert_rowid(repo->db);
        rc = SQLITE_OK;
        LOG_DEBUG("Inserted narrative id=%lld", (long long)*out_id);
    } else {
        LOG_ERR("Insert failed");
    }

cleanup:
    if (stmt) sqlite3_finalize(stmt);
    pthread_mutex_unlock(&repo->lock);
    free(now);
    return rc;
}

int narrative_repo_get(NarrativeRepository *repo,
                       int64_t id,
                       Narrative *out_record)
{
    if (!repo || !out_record) return SQLITE_MISUSE;

    const char *sql =
        "SELECT id, title, author, content, created_at, updated_at, "
        "version, is_deleted "
        "FROM narratives WHERE id = ?1 AND is_deleted = 0 LIMIT 1;";

    pthread_mutex_lock(&repo->lock);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto cleanup;

    sqlite3_bind_int64(stmt, 1, id);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        out_record->id         = sqlite3_column_int64(stmt, 0);
        out_record->title      = strdup((const char *)sqlite3_column_text(stmt, 1));
        out_record->author     = strdup((const char *)sqlite3_column_text(stmt, 2));
        out_record->content    = strdup((const char *)sqlite3_column_text(stmt, 3));
        out_record->created_at = strdup((const char *)sqlite3_column_text(stmt, 4));
        out_record->updated_at = strdup((const char *)sqlite3_column_text(stmt, 5));
        out_record->version    = (uint32_t)sqlite3_column_int(stmt, 6);
        out_record->is_deleted = sqlite3_column_int(stmt, 7) != 0;
        rc = SQLITE_OK;
    } else if (rc == SQLITE_DONE) {
        rc = SQLITE_NOTFOUND;
    }

cleanup:
    if (stmt) sqlite3_finalize(stmt);
    pthread_mutex_unlock(&repo->lock);
    return rc;
}

int narrative_repo_update(NarrativeRepository *repo,
                          const Narrative    *record)
{
    if (!repo || !record) return SQLITE_MISUSE;

    const char *sql =
        "UPDATE narratives SET "
        "title = ?1, author = ?2, content = ?3, updated_at = ?4, "
        "version = version + 1 "
        "WHERE id = ?5 AND version = ?6 AND is_deleted = 0;";

    char *now = current_iso8601();
    if (!now) return SQLITE_NOMEM;

    pthread_mutex_lock(&repo->lock);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto cleanup;

    sqlite3_bind_text(stmt, 1, record->title,   -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, record->author,  -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, record->content, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, now, -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 5, record->id);
    sqlite3_bind_int(stmt,  6, record->version);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_DONE && sqlite3_changes(repo->db) == 1) {
        rc = SQLITE_OK;
        LOG_DEBUG("Updated narrative id=%lld", (long long)record->id);
    } else if (rc == SQLITE_DONE) {
        rc = SQLITE_CONSTRAINT; /* optimistic lock failed */
        LOG_WARN("Optimistic lock failed for id=%lld", (long long)record->id);
    } else {
        LOG_ERR("Update failed");
    }

cleanup:
    if (stmt) sqlite3_finalize(stmt);
    pthread_mutex_unlock(&repo->lock);
    free(now);
    return rc;
}

int narrative_repo_soft_delete(NarrativeRepository *repo, int64_t id)
{
    if (!repo) return SQLITE_MISUSE;

    const char *sql =
        "UPDATE narratives SET is_deleted = 1 WHERE id = ?1 AND is_deleted = 0;";

    pthread_mutex_lock(&repo->lock);
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto cleanup;

    sqlite3_bind_int64(stmt, 1, id);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_DONE && sqlite3_changes(repo->db) == 1) {
        rc = SQLITE_OK;
        LOG_DEBUG("Soft deleted narrative id=%lld", (long long)id);
    } else if (rc == SQLITE_DONE) {
        rc = SQLITE_NOTFOUND;
    }

cleanup:
    if (stmt) sqlite3_finalize(stmt);
    pthread_mutex_unlock(&repo->lock);
    return rc;
}

int narrative_repo_list(NarrativeRepository *repo,
                        size_t limit,
                        size_t offset,
                        narrative_iter_cb cb,
                        void *user_data)
{
    if (!repo || !cb) return SQLITE_MISUSE;

    const char *sql =
        "SELECT id, title, author, content, created_at, updated_at, "
        "version, is_deleted FROM narratives "
        "WHERE is_deleted = 0 "
        "ORDER BY id ASC LIMIT ?1 OFFSET ?2;";

    pthread_mutex_lock(&repo->lock);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) goto cleanup;

    sqlite3_bind_int(stmt, 1, (int)limit);
    sqlite3_bind_int(stmt, 2, (int)offset);

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        Narrative row = {0};
        row.id         = sqlite3_column_int64(stmt, 0);
        row.title      = strdup((const char *)sqlite3_column_text(stmt, 1));
        row.author     = strdup((const char *)sqlite3_column_text(stmt, 2));
        row.content    = strdup((const char *)sqlite3_column_text(stmt, 3));
        row.created_at = strdup((const char *)sqlite3_column_text(stmt, 4));
        row.updated_at = strdup((const char *)sqlite3_column_text(stmt, 5));
        row.version    = (uint32_t)sqlite3_column_int(stmt, 6);
        row.is_deleted = sqlite3_column_int(stmt, 7) != 0;

        bool keep_going = cb(&row, user_data);
        narrative_free(&row); /* only frees dynamic strings, not struct pointer */

        if (!keep_going) break;
    }
    if (rc == SQLITE_DONE) rc = SQLITE_OK;

cleanup:
    if (stmt) sqlite3_finalize(stmt);
    pthread_mutex_unlock(&repo->lock);
    return rc;
}

/* ──────────────── Example usage (compile w/ -DMAIN_TEST) ───────────────── */
#ifdef MAIN_TEST
static bool printer(const Narrative *n, void *ud)
{
    (void)ud;
    printf("ID: %lld | Title: %s | Author: %s\n",
           (long long)n->id, n->title, n->author);
    return true; /* continue iterating */
}

int main(void)
{
    NarrativeRepository repo;
    if (narrative_repo_init(&repo, "narratives.db") != SQLITE_OK)
        return EXIT_FAILURE;

    Narrative n1 = {
        .title   = "The First Brush Stroke",
        .author  = "Ada Lovelace",
        .content = "Once upon a waveform..."
    };
    narrative_repo_create(&repo, &n1, &n1.id);

    narrative_repo_list(&repo, 10, 0, printer, NULL);

    narrative_repo_close(&repo);
    return EXIT_SUCCESS;
}
#endif
```