/*
 * texture_repository.c
 *
 * SynestheticCanvas – Texture Service
 *
 * This module implements the repository layer responsible for persisting and
 * retrieving texture metadata and binary payloads.  It follows the Repository
 * pattern so that callers are insulated from the concrete storage technology
 * (PostgreSQL, in this case).
 *
 * NOTE:
 *   The database schema expected by this repository is shown below:
 *
 *     CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
 *
 *     CREATE TABLE textures (
 *         id          UUID PRIMARY KEY,
 *         name        VARCHAR(255) NOT NULL,
 *         palette_id  UUID         NOT NULL,
 *         data        BYTEA        NOT NULL,
 *         created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
 *         updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
 *     );
 *
 * Compile flags (example):
 *   cc -Wall -Wextra -pthread -lpq -o texture_repository texture_repository.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <syslog.h>
#include <libpq-fe.h>

#include "texture_repository.h"   /* Header for this source file */

/* ---------------------------------------------------------------------------*/
/* Constants                                                                  */
/* ---------------------------------------------------------------------------*/

#define REPO_OK             0
#define REPO_ERR_MEM       -1
#define REPO_ERR_DB        -2
#define REPO_ERR_NOT_FOUND -3

/* ISO-8601 conversion buffers */
#define TIMESTAMP_BUFSZ    32

/* Prepared statement names  */
static const char *STMT_CREATE = "texture_create";
static const char *STMT_GET    = "texture_get";
static const char *STMT_UPDATE = "texture_update";
static const char *STMT_DELETE = "texture_delete";
static const char *STMT_LIST   = "texture_list";

/* ---------------------------------------------------------------------------*/
/* Internal helpers                                                           */
/* ---------------------------------------------------------------------------*/

/* Guard all repository operations with this macro */
#define WITH_LOCK(repo) \
    for (bool _once = true; _once; _once = false) \
        for (pthread_mutex_lock(&(repo)->lock); _once; pthread_mutex_unlock(&(repo)->lock), _once = false)

/* Convert time_t → ISO-8601 UTC string (yyyy-mm-ddThh:mm:ssZ) */
static void
time_to_iso_utc(time_t t, char *buf, size_t bufsz)
{
    struct tm tm_utc;
    gmtime_r(&t, &tm_utc);
    strftime(buf, bufsz, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
}

/* Parse ISO-8601 UTC timestamp → time_t; returns 0 on failure */
static time_t
iso_utc_to_time(const char *s)
{
    struct tm tm_utc = {0};
    if (!strptime(s, "%Y-%m-%d %H:%M:%S", &tm_utc))
        return (time_t)0;

    /* pg timestamp without timezone delivered in session TZ; assume UTC */
    return timegm(&tm_utc);
}

/* Free heap-allocated members of a texture object */
static void
texture_clear(texture_t *tx)
{
    if (!tx) return;
    free(tx->data);
    memset(tx, 0, sizeof(*tx));
}

/* ---------------------------------------------------------------------------*/
/* Public API                                                                 */
/* ---------------------------------------------------------------------------*/

texture_repository_t *
texture_repository_new(const char *conninfo)
{
    if (!conninfo) {
        syslog(LOG_ERR, "texture_repository_new: conninfo is NULL");
        return NULL;
    }

    texture_repository_t *repo = calloc(1, sizeof(*repo));
    if (!repo) {
        syslog(LOG_CRIT, "texture_repository_new: out of memory");
        return NULL;
    }

    pthread_mutex_init(&repo->lock, NULL);

    repo->conn = PQconnectdb(conninfo);
    if (PQstatus(repo->conn) != CONNECTION_OK) {
        syslog(LOG_CRIT, "PostgreSQL connection failed: %s",
               PQerrorMessage(repo->conn));
        PQfinish(repo->conn);
        free(repo);
        return NULL;
    }

    /* Prepare statements upfront; exit if any preparation fails */
    struct {
        const char *name;
        const char *sql;
        int         nParams;
    } stmts[] = {
        { STMT_CREATE,
          "INSERT INTO textures "
          "(id, name, palette_id, data, created_at, updated_at) "
          "VALUES ($1, $2, $3, $4, $5, $6)",
          6 },
        { STMT_GET,
          "SELECT id, name, palette_id, data, "
          "       created_at, updated_at "
          "FROM textures WHERE id = $1",
          1 },
        { STMT_UPDATE,
          "UPDATE textures SET "
          "  name = $2, "
          "  palette_id = $3, "
          "  data = $4, "
          "  updated_at = $5 "
          "WHERE id = $1",
          5 },
        { STMT_DELETE,
          "DELETE FROM textures WHERE id = $1",
          1 },
        { STMT_LIST,
          "SELECT id, name, palette_id, data, "
          "       created_at, updated_at "
          "FROM textures "
          "ORDER BY created_at DESC "
          "LIMIT $1 OFFSET $2",
          2 },
    };

    for (size_t i = 0; i < sizeof(stmts) / sizeof(stmts[0]); ++i) {
        PGresult *res = PQprepare(repo->conn,
                                  stmts[i].name,
                                  stmts[i].sql,
                                  stmts[i].nParams,
                                  NULL);
        if (PQresultStatus(res) != PGRES_COMMAND_OK) {
            syslog(LOG_CRIT, "Failed to prepare statement '%s': %s",
                   stmts[i].name, PQerrorMessage(repo->conn));
            PQclear(res);
            texture_repository_destroy(repo);
            return NULL;
        }
        PQclear(res);
    }

    syslog(LOG_INFO, "Texture repository initialized");
    return repo;
}

void
texture_repository_destroy(texture_repository_t *repo)
{
    if (!repo) return;

    WITH_LOCK(repo) {
        PQfinish(repo->conn);
    }
    pthread_mutex_destroy(&repo->lock);
    free(repo);

    syslog(LOG_INFO, "Texture repository destroyed");
}

int
texture_repository_create(texture_repository_t *repo,
                          const texture_t *texture)
{
    if (!repo || !texture) return REPO_ERR_DB;

    char created_at[TIMESTAMP_BUFSZ];
    char updated_at[TIMESTAMP_BUFSZ];

    time_to_iso_utc(texture->created_at, created_at, sizeof(created_at));
    time_to_iso_utc(texture->updated_at, updated_at, sizeof(updated_at));

    const char *params[6];
    int         lengths[6];
    int         formats[6] = {0};

    params[0] = texture->id;
    lengths[0] = 0;

    params[1] = texture->name;
    lengths[1] = 0;

    params[2] = texture->palette_id;
    lengths[2] = 0;

    params[3]   = (const char *)texture->data;
    lengths[3]  = (int)texture->data_size;
    formats[3]  = 1; /* binary */

    params[4]  = created_at;
    params[5]  = updated_at;
    lengths[4] = lengths[5] = 0;

    PGresult *res = NULL;
    WITH_LOCK(repo) {
        res = PQexecPrepared(repo->conn,
                             STMT_CREATE,
                             6,
                             params,
                             lengths,
                             formats,
                             0);
    }

    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        syslog(LOG_ERR, "texture_repository_create: %s",
               PQerrorMessage(repo->conn));
        PQclear(res);
        return REPO_ERR_DB;
    }

    PQclear(res);
    return REPO_OK;
}

int
texture_repository_get(texture_repository_t *repo,
                       const char *id,
                       texture_t *out_texture)
{
    if (!repo || !id || !out_texture) return REPO_ERR_DB;

    const char *params[1] = { id };
    int lengths[1]  = { 0 };
    int formats[1]  = { 0 };

    PGresult *res = NULL;
    WITH_LOCK(repo) {
        res = PQexecPrepared(repo->conn,
                             STMT_GET,
                             1,
                             params,
                             lengths,
                             formats,
                             0);
    }

    if (PQresultStatus(res) != PGRES_TUPLES_OK) {
        syslog(LOG_ERR, "texture_repository_get: %s",
               PQerrorMessage(repo->conn));
        PQclear(res);
        return REPO_ERR_DB;
    }

    if (PQntuples(res) == 0) {
        PQclear(res);
        return REPO_ERR_NOT_FOUND;
    }

    /* Fetch data */
    int idx = 0;
    strncpy(out_texture->id, PQgetvalue(res, 0, idx++), sizeof(out_texture->id)-1);
    strncpy(out_texture->name, PQgetvalue(res, 0, idx++), sizeof(out_texture->name)-1);
    strncpy(out_texture->palette_id, PQgetvalue(res, 0, idx++), sizeof(out_texture->palette_id)-1);

    /* BYTEA field */
    size_t bin_len = (size_t)PQgetlength(res, 0, idx);
    const unsigned char *bin_data = (const unsigned char *)PQgetvalue(res, 0, idx++);
    out_texture->data = malloc(bin_len);
    if (!out_texture->data) {
        PQclear(res);
        return REPO_ERR_MEM;
    }
    memcpy(out_texture->data, bin_data, bin_len);
    out_texture->data_size = bin_len;

    /* created_at / updated_at */
    out_texture->created_at = iso_utc_to_time(PQgetvalue(res, 0, idx++));
    out_texture->updated_at = iso_utc_to_time(PQgetvalue(res, 0, idx++));

    PQclear(res);
    return REPO_OK;
}

int
texture_repository_update(texture_repository_t *repo,
                          const texture_t *texture)
{
    if (!repo || !texture) return REPO_ERR_DB;

    char updated_at[TIMESTAMP_BUFSZ];
    time_to_iso_utc(texture->updated_at, updated_at, sizeof(updated_at));

    const char *params[5];
    int         lengths[5];
    int         formats[5] = {0};

    params[0] = texture->id;
    lengths[0] = 0;

    params[1] = texture->name;
    lengths[1] = 0;

    params[2] = texture->palette_id;
    lengths[2] = 0;

    params[3]  = (const char *)texture->data;
    lengths[3] = (int)texture->data_size;
    formats[3] = 1; /* binary */

    params[4] = updated_at;
    lengths[4] = 0;

    PGresult *res = NULL;
    WITH_LOCK(repo) {
        res = PQexecPrepared(repo->conn,
                             STMT_UPDATE,
                             5,
                             params,
                             lengths,
                             formats,
                             0);
    }

    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        syslog(LOG_ERR, "texture_repository_update: %s",
               PQerrorMessage(repo->conn));
        PQclear(res);
        return REPO_ERR_DB;
    }

    PQclear(res);
    return REPO_OK;
}

int
texture_repository_delete(texture_repository_t *repo,
                          const char *id)
{
    if (!repo || !id) return REPO_ERR_DB;

    const char *params[1] = { id };
    int lengths[1] = { 0 };
    int formats[1] = { 0 };

    PGresult *res = NULL;
    WITH_LOCK(repo) {
        res = PQexecPrepared(repo->conn,
                             STMT_DELETE,
                             1,
                             params,
                             lengths,
                             formats,
                             0);
    }

    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        syslog(LOG_ERR, "texture_repository_delete: %s",
               PQerrorMessage(repo->conn));
        PQclear(res);
        return REPO_ERR_DB;
    }

    /* Verify that a row was actually deleted */
    if (PQcmdTuples(res)[0] == '0') {
        PQclear(res);
        return REPO_ERR_NOT_FOUND;
    }

    PQclear(res);
    return REPO_OK;
}

int
texture_repository_list(texture_repository_t *repo,
                        size_t limit,
                        size_t offset,
                        texture_t **out_list,
                        size_t *out_count)
{
    if (!repo || !out_list || !out_count) return REPO_ERR_DB;

    char limit_s[32];
    char offset_s[32];
    snprintf(limit_s, sizeof(limit_s), "%zu", limit);
    snprintf(offset_s, sizeof(offset_s), "%zu", offset);

    const char *params[2] = { limit_s, offset_s };
    int lengths[2] = { 0, 0 };
    int formats[2] = { 0, 0 };

    PGresult *res = NULL;
    WITH_LOCK(repo) {
        res = PQexecPrepared(repo->conn,
                             STMT_LIST,
                             2,
                             params,
                             lengths,
                             formats,
                             0);
    }

    if (PQresultStatus(res) != PGRES_TUPLES_OK) {
        syslog(LOG_ERR, "texture_repository_list: %s",
               PQerrorMessage(repo->conn));
        PQclear(res);
        return REPO_ERR_DB;
    }

    size_t rows = (size_t)PQntuples(res);
    *out_count = rows;

    texture_t *arr = calloc(rows, sizeof(texture_t));
    if (!arr && rows > 0) {
        PQclear(res);
        return REPO_ERR_MEM;
    }

    for (size_t r = 0; r < rows; ++r) {
        int c = 0;
        strncpy(arr[r].id, PQgetvalue(res, (int)r, c++), sizeof(arr[r].id)-1);
        strncpy(arr[r].name, PQgetvalue(res, (int)r, c++), sizeof(arr[r].name)-1);
        strncpy(arr[r].palette_id, PQgetvalue(res, (int)r, c++), sizeof(arr[r].palette_id)-1);

        size_t bin_len = (size_t)PQgetlength(res, (int)r, c);
        const unsigned char *bin_data = (const unsigned char *)PQgetvalue(res, (int)r, c++);
        arr[r].data = malloc(bin_len);
        if (!arr[r].data) {
            /* Roll back allocations already made */
            for (size_t i = 0; i < r; ++i)
                texture_clear(&arr[i]);
            free(arr);
            PQclear(res);
            return REPO_ERR_MEM;
        }
        memcpy(arr[r].data, bin_data, bin_len);
        arr[r].data_size = bin_len;

        arr[r].created_at = iso_utc_to_time(PQgetvalue(res, (int)r, c++));
        arr[r].updated_at = iso_utc_to_time(PQgetvalue(res, (int)r, c++));
    }

    PQclear(res);
    *out_list = arr;
    return REPO_OK;
}

/* ---------------------------------------------------------------------------*/
/* Memory-safe free for arrays returned by list()                             */
/* ---------------------------------------------------------------------------*/
void
texture_repository_free_list(texture_t *list, size_t count)
{
    if (!list) return;
    for (size_t i = 0; i < count; ++i)
        texture_clear(&list[i]);
    free(list);
}

/* ---------------------------------------------------------------------------*/
/* EOF                                                                        */
/* ---------------------------------------------------------------------------*/
