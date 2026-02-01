```c
/**
 * SynestheticCanvas – Audio Service
 * ---------------------------------
 * File        : audio_repository.c
 * Author      : SynestheticCanvas Core Team
 * Description : SQLite-backed repository that persists and retrieves
 *               audio-track metadata.  Designed for high-traffic,
 *               low-latency GraphQL/REST micro-environments.
 *
 * NOTE: This file purposefully contains both interface and implementation
 *       details so it can stand alone for the purposes of this prompt.
 *       In production the public API would be split out to
 *       `audio_repository.h`.
 */

#define _POSIX_C_SOURCE 200809L

#include <sqlite3.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdarg.h>
#include <stdio.h>

/* ---------- Forward declarations for logging --------------------------- */
typedef struct logger_s Logger;

/* Simple logging abstraction; in production this would come from
 * SynestheticCanvas’ shared logging package.                                */
static void logger_log(Logger *lg, const char *lvl,
                       const char *fmt, ...)
                       __attribute__((format(printf, 3, 4)));

static void logger_log(Logger *lg, const char *lvl,
                       const char *fmt, ...)
{
    (void)lg; /* logger pointer reserved for future back-ends               */
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[%s] ", lvl);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

/* Convenience macros */
#define LOG_I(repo, ...) logger_log((repo)->logger, "INFO",  __VA_ARGS__)
#define LOG_E(repo, ...) logger_log((repo)->logger, "ERROR", __VA_ARGS__)

/* ----------------------------------------------------------------------- */
/*                               Data Model                                */
/* ----------------------------------------------------------------------- */

/* Each audio track is uniquely identified by “track_id”; it may reference
 * a local file or a remote stream.                                         */
typedef struct audio_track_s
{
    uint64_t track_id;          /* Stable primary key                       */
    char    *title;
    char    *artist;
    char    *album;
    double   duration_sec;      /* Track length in seconds                  */
    char    *media_uri;         /* Absolute URI or relative file path       */
    time_t   created_at;        /* UNIX epoch                               */
    uint32_t version;           /* Optimistic-locking field                 */
} AudioTrack;

/* A lightweight page of results returned for list queries.                 */
typedef struct track_page_s
{
    AudioTrack *items;
    size_t      count;
    size_t      capacity;
} TrackPage;

/* ----------------------------------------------------------------------- */
/*                           Repository Interface                           */
/* ----------------------------------------------------------------------- */
typedef enum
{
    AUDIO_REPO_OK = 0,
    AUDIO_REPO_ERR_DB,
    AUDIO_REPO_ERR_NOT_FOUND,
    AUDIO_REPO_ERR_CONFLICT,      /* Optimistic-lock / version mismatch      */
    AUDIO_REPO_ERR_ARG,
    AUDIO_REPO_ERR_OOM
} AudioRepoStatus;

typedef struct audio_repository_s
{
    sqlite3   *db;
    Logger    *logger;
    pthread_mutex_t mtx;
} AudioRepository;

/* Public API */
AudioRepoStatus audio_repo_init(AudioRepository *repo,
                                const char      *db_path,
                                Logger          *logger);

void            audio_repo_close(AudioRepository *repo);

AudioRepoStatus audio_repo_create(AudioRepository *repo,
                                  const AudioTrack *track_in,
                                  uint64_t         *out_track_id);

AudioRepoStatus audio_repo_get_by_id(AudioRepository *repo,
                                     uint64_t         track_id,
                                     AudioTrack      *out_track);

AudioRepoStatus audio_repo_update(AudioRepository *repo,
                                  const AudioTrack *track);

AudioRepoStatus audio_repo_delete(AudioRepository *repo,
                                  uint64_t         track_id);

AudioRepoStatus audio_repo_list(AudioRepository *repo,
                                size_t           limit,
                                size_t           offset,
                                TrackPage       *out_page);

/* Utility functions */
void            audio_track_free(AudioTrack *track);
void            track_page_free(TrackPage *page);

/* ----------------------------------------------------------------------- */
/*                       Internal helpers / macros                          */
/* ----------------------------------------------------------------------- */
#define CHECK_ARG(expr)                  \
    do                                   \
    {                                    \
        if (!(expr))                     \
            return AUDIO_REPO_ERR_ARG;   \
    } while (0)

#define CHECK_SQL(rc, repo, stmt)                                    \
    do                                                               \
    {                                                                \
        if ((rc) != SQLITE_OK)                                       \
        {                                                            \
            LOG_E(repo, "SQLite error (%d): %s", rc,                 \
                  sqlite3_errmsg((repo)->db));                       \
            if ((stmt) != NULL)                                      \
                sqlite3_finalize(stmt);                              \
            pthread_mutex_unlock(&(repo)->mtx);                      \
            return AUDIO_REPO_ERR_DB;                                \
        }                                                            \
    } while (0)

/* Ensure mutex is always released when leaving scope                    */
#define LOCK_REPO(repo)                    pthread_mutex_lock(&(repo)->mtx)
#define UNLOCK_REPO(repo)                  pthread_mutex_unlock(&(repo)->mtx)

/* ----------------------------------------------------------------------- */
/*                           SQL Schema & DDL                              */
/* ----------------------------------------------------------------------- */

static const char *SCHEMA_SQL =
    "CREATE TABLE IF NOT EXISTS audio_tracks ("
    "  track_id     INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  title        TEXT NOT NULL,"
    "  artist       TEXT,"
    "  album        TEXT,"
    "  duration_sec REAL NOT NULL CHECK(duration_sec >= 0),"
    "  media_uri    TEXT NOT NULL,"
    "  created_at   INTEGER NOT NULL,"
    "  version      INTEGER NOT NULL DEFAULT 1"
    ");"
    "CREATE INDEX IF NOT EXISTS idx_audio_tracks_created "
    "  ON audio_tracks(created_at);";

/* ----------------------------------------------------------------------- */
/*                         Conversion helper funcs                         */
/* ----------------------------------------------------------------------- */

static void bind_track_fields(sqlite3_stmt *stmt, const AudioTrack *t)
{
    /* Bind indices are 1-based */
    sqlite3_bind_text (stmt, 1,  t->title,      -1, SQLITE_TRANSIENT);
    sqlite3_bind_text (stmt, 2,  t->artist,     -1, SQLITE_TRANSIENT);
    sqlite3_bind_text (stmt, 3,  t->album,      -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 4,  t->duration_sec);
    sqlite3_bind_text (stmt, 5,  t->media_uri,  -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6,  (sqlite3_int64)t->created_at);
}

static void column_to_track(sqlite3_stmt *stmt, AudioTrack *t)
{
    t->track_id     = (uint64_t)sqlite3_column_int64(stmt, 0);
    t->title        = strdup((const char*)sqlite3_column_text(stmt, 1));
    t->artist       = strdup((const char*)sqlite3_column_text(stmt, 2));
    t->album        = strdup((const char*)sqlite3_column_text(stmt, 3));
    t->duration_sec = sqlite3_column_double(stmt, 4);
    t->media_uri    = strdup((const char*)sqlite3_column_text(stmt, 5));
    t->created_at   = (time_t)sqlite3_column_int64(stmt, 6);
    t->version      = (uint32_t)sqlite3_column_int(stmt, 7);
}

/* ----------------------------------------------------------------------- */
/*                          Repository functions                           */
/* ----------------------------------------------------------------------- */

AudioRepoStatus
audio_repo_init(AudioRepository *repo,
                const char      *db_path,
                Logger          *logger)
{
    CHECK_ARG(repo && db_path);

    int rc = sqlite3_open_v2(db_path, &repo->db,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                             SQLITE_OPEN_FULLMUTEX, NULL);

    if (rc != SQLITE_OK)
    {
        logger_log(logger, "ERROR", "Could not open DB '%s': %s",
                   db_path, sqlite3_errmsg(repo->db));
        sqlite3_close(repo->db);
        return AUDIO_REPO_ERR_DB;
    }

    repo->logger = logger;
    pthread_mutex_init(&repo->mtx, NULL);

    /* Create schema if missing */
    char *errmsg = NULL;
    rc = sqlite3_exec(repo->db, SCHEMA_SQL, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK)
    {
        logger_log(logger, "ERROR", "Failed to install schema: %s", errmsg);
        sqlite3_free(errmsg);
        sqlite3_close(repo->db);
        pthread_mutex_destroy(&repo->mtx);
        return AUDIO_REPO_ERR_DB;
    }

    LOG_I(repo, "Audio repository initialized using %s", db_path);
    return AUDIO_REPO_OK;
}

void
audio_repo_close(AudioRepository *repo)
{
    if (!repo) return;
    sqlite3_close(repo->db);
    pthread_mutex_destroy(&repo->mtx);
}

/* Create ---------------------------------------------------------------- */
AudioRepoStatus
audio_repo_create(AudioRepository *repo,
                  const AudioTrack *track_in,
                  uint64_t         *out_track_id)
{
    CHECK_ARG(repo && track_in);

    static const char *SQL =
        "INSERT INTO audio_tracks "
        "(title, artist, album, duration_sec, media_uri, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)";

    LOCK_REPO(repo);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, SQL, -1, &stmt, NULL);
    CHECK_SQL(rc, repo, stmt);

    AudioTrack tmp = *track_in;
    time(&tmp.created_at);
    bind_track_fields(stmt, &tmp);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE)
    {
        LOG_E(repo, "Failed to execute INSERT");
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_ERR_DB;
    }

    if (out_track_id)
        *out_track_id = (uint64_t)sqlite3_last_insert_rowid(repo->db);

    sqlite3_finalize(stmt);
    UNLOCK_REPO(repo);

    LOG_I(repo, "Created audio track id=%" PRIu64, *out_track_id);
    return AUDIO_REPO_OK;
}

/* Read ------------------------------------------------------------------ */
AudioRepoStatus
audio_repo_get_by_id(AudioRepository *repo,
                     uint64_t         track_id,
                     AudioTrack      *out_track)
{
    CHECK_ARG(repo && out_track);

    static const char *SQL =
        "SELECT track_id, title, artist, album, duration_sec, "
        "media_uri, created_at, version "
        "FROM audio_tracks WHERE track_id = ?";

    LOCK_REPO(repo);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, SQL, -1, &stmt, NULL);
    CHECK_SQL(rc, repo, stmt);

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)track_id);

    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW)
    {
        column_to_track(stmt, out_track);
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_OK;
    }
    else
    {
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_ERR_NOT_FOUND;
    }
}

/* Update (Optimistic locking) ------------------------------------------ */
AudioRepoStatus
audio_repo_update(AudioRepository *repo,
                  const AudioTrack *track)
{
    CHECK_ARG(repo && track);

    static const char *SQL =
        "UPDATE audio_tracks SET "
        "title = ?, artist = ?, album = ?, duration_sec = ?, "
        "media_uri = ?, version = version + 1 "
        "WHERE track_id = ? AND version = ?";

    LOCK_REPO(repo);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, SQL, -1, &stmt, NULL);
    CHECK_SQL(rc, repo, stmt);

    /* Bind fields 1-5 */
    bind_track_fields(stmt, track);
    /* Bind where-clause identifiers */
    sqlite3_bind_int64(stmt, 7, (sqlite3_int64)track->track_id);
    sqlite3_bind_int (stmt, 8, (int)track->version);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE)
    {
        LOG_E(repo, "Update failed to execute");
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_ERR_DB;
    }

    int rows = sqlite3_changes(repo->db);
    sqlite3_finalize(stmt);
    UNLOCK_REPO(repo);

    if (rows == 0)
        return AUDIO_REPO_ERR_CONFLICT;

    LOG_I(repo, "Updated audio track id=%" PRIu64, track->track_id);
    return AUDIO_REPO_OK;
}

/* Delete ---------------------------------------------------------------- */
AudioRepoStatus
audio_repo_delete(AudioRepository *repo,
                  uint64_t         track_id)
{
    CHECK_ARG(repo);

    static const char *SQL =
        "DELETE FROM audio_tracks WHERE track_id = ?";

    LOCK_REPO(repo);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, SQL, -1, &stmt, NULL);
    CHECK_SQL(rc, repo, stmt);

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)track_id);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE)
    {
        LOG_E(repo, "Delete failed");
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_ERR_DB;
    }

    int rows = sqlite3_changes(repo->db);
    sqlite3_finalize(stmt);
    UNLOCK_REPO(repo);

    if (rows == 0)
        return AUDIO_REPO_ERR_NOT_FOUND;

    LOG_I(repo, "Deleted audio track id=%" PRIu64, track_id);
    return AUDIO_REPO_OK;
}

/* List / Pagination ----------------------------------------------------- */
AudioRepoStatus
audio_repo_list(AudioRepository *repo,
                size_t           limit,
                size_t           offset,
                TrackPage       *out_page)
{
    CHECK_ARG(repo && out_page);

    static const char *SQL_BASE =
        "SELECT track_id, title, artist, album, duration_sec, media_uri, "
        "created_at, version "
        "FROM audio_tracks ORDER BY created_at DESC LIMIT ? OFFSET ?";

    LOCK_REPO(repo);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(repo->db, SQL_BASE, -1, &stmt, NULL);
    CHECK_SQL(rc, repo, stmt);

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)limit);
    sqlite3_bind_int64(stmt, 2, (sqlite3_int64)offset);

    /* Initialize dynamic array */
    size_t cap = (limit > 0) ? limit : 16;
    out_page->items = calloc(cap, sizeof(AudioTrack));
    if (!out_page->items)
    {
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        return AUDIO_REPO_ERR_OOM;
    }
    out_page->count     = 0;
    out_page->capacity  = cap;

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW)
    {
        if (out_page->count == out_page->capacity)
        {
            /* Grow */
            cap *= 2;
            AudioTrack *tmp = realloc(out_page->items,
                                      cap * sizeof(AudioTrack));
            if (!tmp)
            {
                sqlite3_finalize(stmt);
                UNLOCK_REPO(repo);
                track_page_free(out_page);
                return AUDIO_REPO_ERR_OOM;
            }
            out_page->items    = tmp;
            out_page->capacity = cap;
        }

        column_to_track(stmt, &out_page->items[out_page->count++]);
    }

    if (rc != SQLITE_DONE)
    {
        LOG_E(repo, "Iteration failure");
        sqlite3_finalize(stmt);
        UNLOCK_REPO(repo);
        track_page_free(out_page);
        return AUDIO_REPO_ERR_DB;
    }

    sqlite3_finalize(stmt);
    UNLOCK_REPO(repo);
    return AUDIO_REPO_OK;
}

/* ----------------------------------------------------------------------- */
/*                    Memory-management utility helpers                    */
/* ----------------------------------------------------------------------- */

void
audio_track_free(AudioTrack *t)
{
    if (!t) return;
    free(t->title);
    free(t->artist);
    free(t->album);
    free(t->media_uri);
    memset(t, 0, sizeof(*t));
}

void
track_page_free(TrackPage *p)
{
    if (!p) return;
    for (size_t i = 0; i < p->count; ++i)
        audio_track_free(&p->items[i]);
    free(p->items);
    memset(p, 0, sizeof(*p));
}
```