```c
/**
 * SynestheticCanvas Narrative Service
 * -----------------------------------
 * narrative_handler.c
 *
 * Production-quality narrative handler for the SynestheticCanvas API suite.
 * The module exposes a small but complete REST-style surface that can be wired
 * into any HTTP server / gateway.  It uses SQLite as a lightweight repository,
 * cJSON for JSON (de)serialization, and syslog for operational logging.
 *
 * Supported Routes
 *   GET  /narratives/<id>        – Fetch a single narrative node
 *   POST /narratives             – Create a new narrative node
 *   GET  /health                 – Liveness probe for orchestration
 *
 * NOTE: The surrounding web framework must provide the raw HTTP elements
 * (method, path, body).  The handler produces a fully-formatted HTTP response
 * string that the caller must free().
 *
 * Build Dependencies
 *   -lpthread -lsqlite3 -lcjson
 *
 * ---------------------------------------------------------------------------
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sqlite3.h>
#include <pthread.h>
#include <syslog.h>
#include <ctype.h>

#include "cJSON.h"        /* https://github.com/DaveGamble/cJSON */

/* ---------------------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------------------
 */
#define DB_DEFAULT_PATH   "./data/narratives.db"
#define MAX_SQL_ERROR     256
#define HTTP_HDR_FMT      "HTTP/1.1 %d %s\r\n" \
                          "Content-Type: application/json\r\n" \
                          "Content-Length: %zu\r\n" \
                          "Connection: close\r\n\r\n%s"

#define SERVICE_NAME      "narrative_service"

/* ---------------------------------------------------------------------------
 * Forward declarations
 * ---------------------------------------------------------------------------
 */
static int   repo_init(const char *db_path);
static void  repo_shutdown(void);
static int   repo_get_node(int node_id, cJSON **out_node);
static int   repo_create_node(const char *title,
                              const char *content,
                              int parent_id,
                              int      *out_id);

static char *build_http_response(int status_code,
                                 const char *status_txt,
                                 const char *json_body);

static int   parse_int_from_path(const char *path, int *out_val);

/* ---------------------------------------------------------------------------
 * Globals
 * ---------------------------------------------------------------------------
 */
static sqlite3        *g_db          = NULL;
static pthread_mutex_t g_db_mutex    = PTHREAD_MUTEX_INITIALIZER;
static int             g_initialized = 0;

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------------
 */

/**
 * narrative_init_service
 * ----------------------
 * Initializes the repository and logging facilities.
 *
 * returns 0 on success, otherwise -1.
 */
int narrative_init_service(const char *db_path)
{
    if (g_initialized) return 0;

    /* Initialize syslog */
    openlog(SERVICE_NAME, LOG_PID | LOG_CONS, LOG_USER);

    const char *path = db_path ? db_path : DB_DEFAULT_PATH;
    if (repo_init(path) != 0) {
        syslog(LOG_ERR, "Failed to initialize repository at %s", path);
        return -1;
    }

    syslog(LOG_INFO, "Narrative service initialized (db=%s)", path);
    g_initialized = 1;
    return 0;
}

/**
 * narrative_shutdown_service
 * --------------------------
 * Gracefully closes underlying resources.
 */
void narrative_shutdown_service(void)
{
    if (!g_initialized) return;
    repo_shutdown();
    closelog();
    g_initialized = 0;
}

/**
 * narrative_handle_request
 * ------------------------
 * Core dispatcher.  Accepts HTTP fragments and produces a complete
 * HTTP response string (caller must free()).
 *
 * returns 0 on success, else -1 which indicates internal error.  Even on
 * logical failures (e.g., 404) the returned response is valid.
 */
int narrative_handle_request(const char *method,
                             const char *path,
                             const char *body,
                             char      **response_out)
{
    if (!method || !path || !response_out) return -1;

    *response_out = NULL;
    cJSON *root     = NULL;
    int    rc       = 0;
    char  *json_str = NULL;

    /* ------------------------------------------------------------------- *
     * 1. Health probe
     * ------------------------------------------------------------------- */
    if (strcmp(method, "GET") == 0 && strcmp(path, "/health") == 0) {
        root = cJSON_CreateObject();
        cJSON_AddStringToObject(root, "status", "ok");
        json_str = cJSON_PrintUnformatted(root);
        *response_out = build_http_response(200, "OK", json_str);
        goto cleanup;
    }

    /* ------------------------------------------------------------------- *
     * 2. GET /narratives/<id>
     * ------------------------------------------------------------------- */
    if (strcmp(method, "GET") == 0 && strncmp(path, "/narratives/", 12) == 0) {
        int node_id;
        if (parse_int_from_path(path + 12, &node_id) != 0) {
            *response_out = build_http_response(400, "Bad Request",
                                                "{\"error\":\"invalid id\"}");
            goto cleanup;
        }

        if (repo_get_node(node_id, &root) != 0 || root == NULL) {
            *response_out = build_http_response(404, "Not Found",
                                                "{\"error\":\"node not found\"}");
            goto cleanup;
        }

        json_str = cJSON_PrintUnformatted(root);
        *response_out = build_http_response(200, "OK", json_str);
        goto cleanup;
    }

    /* ------------------------------------------------------------------- *
     * 3. POST /narratives
     * ------------------------------------------------------------------- */
    if (strcmp(method, "POST") == 0 && strcmp(path, "/narratives") == 0) {
        if (!body) {
            *response_out = build_http_response(400, "Bad Request",
                                                "{\"error\":\"empty body\"}");
            goto cleanup;
        }

        cJSON *payload = cJSON_Parse(body);
        if (!payload) {
            *response_out = build_http_response(400, "Bad Request",
                                                "{\"error\":\"invalid json\"}");
            goto cleanup;
        }

        const cJSON *title_json   = cJSON_GetObjectItemCaseSensitive(payload, "title");
        const cJSON *content_json = cJSON_GetObjectItemCaseSensitive(payload, "content");
        const cJSON *parent_json  = cJSON_GetObjectItemCaseSensitive(payload, "parent_id");

        if (!cJSON_IsString(title_json)   || !cJSON_IsString(content_json) ||
            (parent_json && !cJSON_IsNumber(parent_json))) {
            cJSON_Delete(payload);
            *response_out = build_http_response(422, "Unprocessable Entity",
                                                "{\"error\":\"validation failed\"}");
            goto cleanup;
        }

        int parent_id = parent_json ? parent_json->valueint : -1;
        int new_id;

        if (repo_create_node(title_json->valuestring,
                             content_json->valuestring,
                             parent_id,
                             &new_id) != 0) {
            cJSON_Delete(payload);
            *response_out = build_http_response(500, "Internal Server Error",
                                                "{\"error\":\"db failure\"}");
            goto cleanup;
        }
        cJSON_Delete(payload);

        /* Build success payload */
        root = cJSON_CreateObject();
        cJSON_AddNumberToObject(root, "id", new_id);
        cJSON_AddStringToObject(root, "message", "created");
        json_str = cJSON_PrintUnformatted(root);
        *response_out = build_http_response(201, "Created", json_str);
        goto cleanup;
    }

    /* ------------------------------------------------------------------- *
     * 4. Fallback – route not found
     * ------------------------------------------------------------------- */
    *response_out = build_http_response(404, "Not Found",
                                        "{\"error\":\"route not found\"}");

cleanup:
    if (root)     cJSON_Delete(root);
    if (json_str) free(json_str);

    return (*response_out) ? 0 : -1;
}

/* ---------------------------------------------------------------------------
 * Repository implementation (SQLite)
 * ---------------------------------------------------------------------------
 */

/**
 * repo_init
 * ---------
 * Opens / creates SQLite database and prepares required DDL.
 */
static int repo_init(const char *db_path)
{
    char *err = NULL;
    int   rc;

    rc = sqlite3_open(db_path, &g_db);
    if (rc != SQLITE_OK) {
        syslog(LOG_ERR, "SQLite open error: %s", sqlite3_errmsg(g_db));
        return -1;
    }

    const char *ddl =
        "PRAGMA foreign_keys = ON;"
        "CREATE TABLE IF NOT EXISTS narrative_nodes ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  title TEXT NOT NULL,"
        "  content TEXT NOT NULL,"
        "  parent_id INTEGER REFERENCES narrative_nodes(id) ON DELETE SET NULL,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ");";

    rc = sqlite3_exec(g_db, ddl, NULL, NULL, &err);
    if (rc != SQLITE_OK) {
        syslog(LOG_ERR, "SQLite DDL error: %s", err);
        sqlite3_free(err);
        return -1;
    }
    return 0;
}

static void repo_shutdown(void)
{
    if (g_db) {
        sqlite3_close(g_db);
        g_db = NULL;
    }
}

/**
 * repo_get_node
 * -------------
 * Fetches a single narrative node as a cJSON object.
 *
 * returns 0 on success, otherwise -1 (not found or db error).
 */
static int repo_get_node(int node_id, cJSON **out_node)
{
    static const char *sql =
        "SELECT id, title, content, parent_id, "
        "       datetime(created_at), datetime(updated_at) "
        "  FROM narrative_nodes WHERE id = ?;";

    sqlite3_stmt *stmt = NULL;
    int           rc   = 0;

    pthread_mutex_lock(&g_db_mutex);

    if (sqlite3_prepare_v2(g_db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        syslog(LOG_ERR, "SQLite prepare error: %s", sqlite3_errmsg(g_db));
        rc = -1; goto unlock;
    }

    sqlite3_bind_int(stmt, 1, node_id);

    if (sqlite3_step(stmt) != SQLITE_ROW) {
        rc = -1; goto finalise;
    }

    cJSON *node = cJSON_CreateObject();
    cJSON_AddNumberToObject(node, "id",        sqlite3_column_int(stmt, 0));
    cJSON_AddStringToObject(node, "title",     (const char*)sqlite3_column_text(stmt,1));
    cJSON_AddStringToObject(node, "content",   (const char*)sqlite3_column_text(stmt,2));

    if (sqlite3_column_type(stmt,3) != SQLITE_NULL)
        cJSON_AddNumberToObject(node, "parent_id", sqlite3_column_int(stmt,3));
    else
        cJSON_AddNullToObject(node, "parent_id");

    cJSON_AddStringToObject(node, "created_at",(const char*)sqlite3_column_text(stmt,4));
    cJSON_AddStringToObject(node, "updated_at",(const char*)sqlite3_column_text(stmt,5));

    *out_node = node;

finalise:
    sqlite3_finalize(stmt);
unlock:
    pthread_mutex_unlock(&g_db_mutex);
    return rc;
}

/**
 * repo_create_node
 * ----------------
 * Inserts new node and returns its auto-generated id.
 *
 * returns 0 on success, otherwise -1.
 */
static int repo_create_node(const char *title,
                            const char *content,
                            int         parent_id,
                            int        *out_id)
{
    static const char *sql =
        "INSERT INTO narrative_nodes (title, content, parent_id) "
        "VALUES (?, ?, ?);";

    sqlite3_stmt *stmt = NULL;
    int           rc   = 0;

    pthread_mutex_lock(&g_db_mutex);

    if (sqlite3_prepare_v2(g_db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        syslog(LOG_ERR, "SQLite prepare error: %s", sqlite3_errmsg(g_db));
        rc = -1; goto unlock;
    }

    /* Bind parameters */
    sqlite3_bind_text(stmt, 1, title,   -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, content, -1, SQLITE_TRANSIENT);

    if (parent_id >= 0)
        sqlite3_bind_int(stmt, 3, parent_id);
    else
        sqlite3_bind_null(stmt, 3);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        syslog(LOG_ERR, "SQLite insert error: %s", sqlite3_errmsg(g_db));
        rc = -1; goto finalise;
    }

    *out_id = (int)sqlite3_last_insert_rowid(g_db);

finalise:
    sqlite3_finalize(stmt);
unlock:
    pthread_mutex_unlock(&g_db_mutex);
    return rc;
}

/* ---------------------------------------------------------------------------
 * Utility helpers
 * ---------------------------------------------------------------------------
 */

/**
 * build_http_response
 * -------------------
 * Allocates and returns a well-formed HTTP response string.
 */
static char *build_http_response(int status_code,
                                 const char *status_txt,
                                 const char *json_body)
{
    const char *body = json_body ? json_body : "{}";
    size_t body_len  = strlen(body);

    size_t resp_len  = strlen(HTTP_HDR_FMT) + body_len + 32; /* rough */
    char  *resp      = (char*)malloc(resp_len);

    if (!resp) return NULL;

    int n = snprintf(resp, resp_len, HTTP_HDR_FMT,
                     status_code, status_txt,
                     body_len, body);
    /* Trim to actual */
    char *shrink = realloc(resp, n + 1);
    return shrink ? shrink : resp;
}

/**
 * parse_int_from_path
 * -------------------
 * Accepts a substring of the path and parses a positive integer.  Ensures no
 * trailing characters (e.g., "/123abc" is invalid).
 *
 * returns 0 on success, else -1.
 */
static int parse_int_from_path(const char *path, int *out_val)
{
    if (!path || !*path) return -1;

    char *endptr;
    errno = 0;
    long val = strtol(path, &endptr, 10);

    if (errno || endptr == path || *endptr != '\0' || val <= 0 || val > INT_MAX)
        return -1;

    *out_val = (int)val;
    return 0;
}
```