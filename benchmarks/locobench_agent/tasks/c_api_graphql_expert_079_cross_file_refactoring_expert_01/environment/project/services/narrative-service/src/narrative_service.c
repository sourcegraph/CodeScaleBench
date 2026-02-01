/**
 * SynestheticCanvas – Narrative Service
 * -------------------------------------
 * This compilation unit hosts the primary service loop, REST/GraphQL handlers,
 * repository adapters (SQLite-based), and domain logic for branching story data.
 *
 * Build flags: -lpthread -lsqlite3 -ljansson -lmicrohttpd -luuid
 *
 * NOTE: In production, symbols are usually split across .h/.c pairs.  For the
 * sake of this challenge, all structures, constants, and forward declarations
 * live in this single source file.
 */
#define _GNU_SOURCE
#include <microhttpd.h>
#include <jansson.h>
#include <sqlite3.h>
#include <uuid/uuid.h>
#include <pthread.h>
#include <syslog.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>

/* ------------------------------------------------------------------------- */
/*                          CONFIGURATION CONSTANTS                          */
/* ------------------------------------------------------------------------- */
#define SERVICE_NAME              "narrative-service"
#define SERVICE_VERSION           "1.4.2"
#define DEFAULT_HTTP_PORT         7084
#define MAX_REQUEST_SIZE_BYTES    (1024 * 128)  /* 128 KiB */
#define SQLITE_BUSY_TIMEOUT_MS    3000
#define REPO_FILE                 "./data/narratives.db"
#define DB_CONN_POOL              4
#define PAGINATION_DEFAULT_LIMIT  50
#define PAGINATION_MAX_LIMIT      200

/* ------------------------------------------------------------------------- */
/*                                 UTILITIES                                 */
/* ------------------------------------------------------------------------- */
static inline uint64_t epoch_ms(void) {
    struct timespec tv;
    clock_gettime(CLOCK_REALTIME, &tv);
    return (uint64_t)tv.tv_sec * 1000ULL + (tv.tv_nsec / 1000000ULL);
}

static void send_json_error(struct MHD_Connection *connection,
                            unsigned int status,
                            const char *code,
                            const char *message)
{
    json_t *root = json_object();
    json_object_set_new(root, "error", json_string(message));
    json_object_set_new(root, "code",  json_string(code));
    json_object_set_new(root, "status", json_integer(status));
    char *payload = json_dumps(root, JSON_COMPACT);
    struct MHD_Response *resp = MHD_create_response_from_buffer(
            strlen(payload), payload, MHD_RESPMEM_MUST_FREE);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    MHD_queue_response(connection, status, resp);
    MHD_destroy_response(resp);
    json_decref(root);
}

/* ------------------------------------------------------------------------- */
/*                            DOMAIN / DTO RECORDS                           */
/* ------------------------------------------------------------------------- */
typedef struct {
    char      uuid[37];         /* canonical textual form */
    char     *title;
    char     *body;
    char      parent_uuid[37];  /* empty string when root */
    uint64_t  created_at_ms;
} narrative_node_t;

/* ------------------------------------------------------------------------- */
/*                          DATABASE (SQLite) LAYER                          */
/* ------------------------------------------------------------------------- */
typedef struct {
    sqlite3 *db;
    pthread_mutex_t mtx;
} db_conn_t;

static db_conn_t g_pool[DB_CONN_POOL];
static atomic_uint g_pool_index = 0;

static db_conn_t *pool_acquire(void) {
    /* Round-robin acquisition.  Extremely inexpensive/safe because the pool
     * size is small and connections are long-lived. */
    uint32_t idx = atomic_fetch_add(&g_pool_index, 1) % DB_CONN_POOL;
    return &g_pool[idx];
}

static bool db_exec(sqlite3 *db, const char *sql) {
    char *errmsg = NULL;
    if (sqlite3_exec(db, sql, NULL, NULL, &errmsg) != SQLITE_OK) {
        syslog(LOG_ERR, "[repo] init error: %s", errmsg);
        sqlite3_free(errmsg);
        return false;
    }
    return true;
}

static bool repo_init(void)
{
    for (size_t i = 0; i < DB_CONN_POOL; ++i) {
        if (sqlite3_open(REPO_FILE, &g_pool[i].db) != SQLITE_OK) {
            syslog(LOG_CRIT, "[repo] cannot open %s: %s",
                   REPO_FILE, sqlite3_errmsg(g_pool[i].db));
            return false;
        }
        sqlite3_busy_timeout(g_pool[i].db, SQLITE_BUSY_TIMEOUT_MS);
        pthread_mutex_init(&g_pool[i].mtx, NULL);
    }

    /* schema migration – idempotent */
    const char *DDL =
        "CREATE TABLE IF NOT EXISTS narrative_nodes ("
        "  uuid TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  body TEXT NOT NULL,"
        "  parent_uuid TEXT,"
        "  created_at_ms INTEGER NOT NULL"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_parent_uuid ON narrative_nodes(parent_uuid);"
        ;
    return db_exec(g_pool[0].db, DDL);
}

static bool repo_insert_node(const narrative_node_t *node)
{
    static const char *SQL =
        "INSERT INTO narrative_nodes (uuid, title, body, parent_uuid, created_at_ms) "
        "VALUES (?, ?, ?, ?, ?);";
    db_conn_t *conn = pool_acquire();
    pthread_mutex_lock(&conn->mtx);

    sqlite3_stmt *stmt = NULL;
    bool ok = false;
    if (sqlite3_prepare_v2(conn->db, SQL, -1, &stmt, NULL) == SQLITE_OK &&
        sqlite3_bind_text (stmt, 1, node->uuid, -1, SQLITE_STATIC) == SQLITE_OK &&
        sqlite3_bind_text (stmt, 2, node->title, -1, SQLITE_STATIC) == SQLITE_OK &&
        sqlite3_bind_text (stmt, 3, node->body, -1, SQLITE_STATIC) == SQLITE_OK &&
        sqlite3_bind_text (stmt, 4, node->parent_uuid[0] ? node->parent_uuid : NULL, -1, SQLITE_STATIC) == SQLITE_OK &&
        sqlite3_bind_int64(stmt, 5, (sqlite3_int64)node->created_at_ms) == SQLITE_OK &&
        sqlite3_step(stmt) == SQLITE_DONE) {
        ok = true;
    } else {
        syslog(LOG_ERR, "[repo] insert failed: %s", sqlite3_errmsg(conn->db));
    }
    sqlite3_finalize(stmt);
    pthread_mutex_unlock(&conn->mtx);
    return ok;
}

static json_t *repo_get_node(const char *uuid)
{
    static const char *SQL =
        "SELECT uuid, title, body, parent_uuid, created_at_ms "
        "FROM narrative_nodes WHERE uuid = ? LIMIT 1;";
    db_conn_t *conn = pool_acquire();
    pthread_mutex_lock(&conn->mtx);

    sqlite3_stmt *stmt = NULL;
    json_t *obj = NULL;

    if (sqlite3_prepare_v2(conn->db, SQL, -1, &stmt, NULL) == SQLITE_OK &&
        sqlite3_bind_text(stmt, 1, uuid, -1, SQLITE_STATIC) == SQLITE_OK &&
        sqlite3_step(stmt) == SQLITE_ROW) {

        obj = json_pack("{s:s, s:s, s:s, s:s?, s:I}",
                        "uuid",          (const char *)sqlite3_column_text(stmt, 0),
                        "title",         (const char *)sqlite3_column_text(stmt, 1),
                        "body",          (const char *)sqlite3_column_text(stmt, 2),
                        "parent_uuid",   (const char *)sqlite3_column_text(stmt, 3),
                        "created_at_ms", (json_int_t)sqlite3_column_int64(stmt, 4));
    }
    sqlite3_finalize(stmt);
    pthread_mutex_unlock(&conn->mtx);
    return obj;
}

static json_t *repo_list_children(const char *parent_uuid,
                                  unsigned limit, unsigned offset)
{
    static const char *BASE_SQL =
        "SELECT uuid, title, body, parent_uuid, created_at_ms "
        "FROM narrative_nodes WHERE parent_uuid %s ORDER BY created_at_ms ASC LIMIT ? OFFSET ?";

    char *sql = NULL;
    asprintf(&sql, BASE_SQL,
             parent_uuid ? "= ?" : "IS NULL");

    db_conn_t *conn = pool_acquire();
    pthread_mutex_lock(&conn->mtx);

    sqlite3_stmt *stmt = NULL;
    json_t *arr = json_array();
    if (sqlite3_prepare_v2(conn->db, sql, -1, &stmt, NULL) == SQLITE_OK) {
        int idx = 1;
        if (parent_uuid) {
            sqlite3_bind_text(stmt, idx++, parent_uuid, -1, SQLITE_STATIC);
        }
        sqlite3_bind_int(stmt, idx++, limit);
        sqlite3_bind_int(stmt, idx, offset);

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json_t *obj = json_pack("{s:s, s:s, s:s, s:s?, s:I}",
                                    "uuid",          (const char *)sqlite3_column_text(stmt, 0),
                                    "title",         (const char *)sqlite3_column_text(stmt, 1),
                                    "body",          (const char *)sqlite3_column_text(stmt, 2),
                                    "parent_uuid",   (const char *)sqlite3_column_text(stmt, 3),
                                    "created_at_ms", (json_int_t)sqlite3_column_int64(stmt, 4));
            json_array_append_new(arr, obj);
        }
    } else {
        syslog(LOG_ERR, "[repo] child list failed: %s", sqlite3_errmsg(conn->db));
    }
    sqlite3_finalize(stmt);
    pthread_mutex_unlock(&conn->mtx);
    free(sql);
    return arr;
}

/* ------------------------------------------------------------------------- */
/*                               GRAPHQL LAYER                               */
/* ------------------------------------------------------------------------- */
/* We provide a minimalistic GraphQL lexer for two queries:
 *
 *  (1) node(uuid: "…")      -> fetch single node
 *  (2) children(parent: …)  -> list children with pagination
 *
 * In production we would delegate to a fully-featured GraphQL runtime.
 */

static int handle_graphql_request(const char *raw_query, char **response_body)
{
    json_error_t jerr;
    json_t *root = json_loads(raw_query, 0, &jerr);  /* naive: treat "query" as JSON for simplicity */
    if (!root) {
        return MHD_HTTP_BAD_REQUEST;
    }

    const char *op = json_string_value(json_object_get(root, "op"));
    if (!op) {
        json_decref(root);
        return MHD_HTTP_BAD_REQUEST;
    }

    if (strcmp(op, "node") == 0) {
        const char *uuid = json_string_value(json_object_get(root, "uuid"));
        json_t *node = uuid ? repo_get_node(uuid) : NULL;
        if (!node) {
            json_decref(root);
            return MHD_HTTP_NOT_FOUND;
        }
        *response_body = json_dumps(node, JSON_COMPACT);
        json_decref(node);
        json_decref(root);
        return MHD_HTTP_OK;

    } else if (strcmp(op, "children") == 0) {
        const char *parent = NULL;
        json_t *parent_json = json_object_get(root, "parent_uuid");
        if (parent_json && json_is_string(parent_json)) parent = json_string_value(parent_json);

        unsigned limit  = (unsigned) json_integer_value(json_object_get(root, "limit"));
        unsigned offset = (unsigned) json_integer_value(json_object_get(root, "offset"));
        if (!limit)  limit  = PAGINATION_DEFAULT_LIMIT;
        if (limit > PAGINATION_MAX_LIMIT) limit = PAGINATION_MAX_LIMIT;

        json_t *arr = repo_list_children(parent, limit, offset);
        *response_body = json_dumps(arr, JSON_COMPACT);
        json_decref(arr);
        json_decref(root);
        return MHD_HTTP_OK;
    }

    json_decref(root);
    return MHD_HTTP_BAD_REQUEST;
}

/* ------------------------------------------------------------------------- */
/*                               REST HANDLERS                               */
/* ------------------------------------------------------------------------- */
typedef struct {
    char *data;
    size_t size;
} req_ctx_t;

static int on_request_iter(void *cls, enum MHD_ValueKind kind,
                           const char *key, const char *value)
{
    json_t *j = (json_t *)cls;
    json_object_set_new(j, key, json_string(value));
    return MHD_YES;
}

/* Parse URL pattern /v1/narratives/{uuid} */
static const char *extract_uuid_from_url(const char *url)
{
    const char *base = "/v1/narratives/";
    size_t len = strlen(base);
    if (strncmp(url, base, len) != 0) return NULL;
    const char *uuid = url + len;
    return (*uuid) ? uuid : NULL;
}

static int handle_get_node(struct MHD_Connection *connection, const char *uuid)
{
    json_t *node = repo_get_node(uuid);
    if (!node) {
        send_json_error(connection, MHD_HTTP_NOT_FOUND, "NOT_FOUND", "Narrative node not found");
        return MHD_YES;
    }

    char *payload = json_dumps(node, JSON_COMPACT);
    struct MHD_Response *resp = MHD_create_response_from_buffer(strlen(payload), payload,
                                                                MHD_RESPMEM_MUST_FREE);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(connection, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    json_decref(node);
    return ret;
}

static int handle_post_node(struct MHD_Connection *connection, const char *upload_data,
                            size_t *upload_data_size, void **con_cls)
{
    req_ctx_t *ctx = *con_cls;
    if (!ctx) { /* first call */
        ctx = calloc(1, sizeof(req_ctx_t));
        *con_cls = ctx;
        return MHD_YES;
    }

    if (*upload_data_size != 0) {
        if (ctx->size + *upload_data_size > MAX_REQUEST_SIZE_BYTES) {
            send_json_error(connection, MHD_HTTP_PAYLOAD_TOO_LARGE, "PAYLOAD_TOO_LARGE",
                            "Request payload too large");
            return MHD_NO;
        }
        ctx->data = realloc(ctx->data, ctx->size + *upload_data_size + 1);
        memcpy(ctx->data + ctx->size, upload_data, *upload_data_size);
        ctx->size += *upload_data_size;
        ctx->data[ctx->size] = '\0';
        *upload_data_size = 0;
        return MHD_YES;
    }

    /* final call: body fully read */
    json_error_t jerr;
    json_t *root = json_loads(ctx->data, 0, &jerr);
    if (!root) {
        send_json_error(connection, MHD_HTTP_BAD_REQUEST, "BAD_JSON", "Invalid JSON payload");
        goto cleanup;
    }

    const char *title = json_string_value(json_object_get(root, "title"));
    const char *body  = json_string_value(json_object_get(root, "body"));
    const char *parent_uuid = json_string_value(json_object_get(root, "parent_uuid"));

    if (!title || !body) {
        send_json_error(connection, MHD_HTTP_BAD_REQUEST, "VALIDATION_ERROR",
                        "title and body are required");
        json_decref(root);
        goto cleanup;
    }

    narrative_node_t node = {0};
    uuid_t uu;
    uuid_generate(uu);
    uuid_unparse_lower(uu, node.uuid);
    node.title = (char *)title;
    node.body  = (char *)body;
    if (parent_uuid) strncpy(node.parent_uuid, parent_uuid, sizeof(node.parent_uuid) - 1);
    node.created_at_ms = epoch_ms();

    if (!repo_insert_node(&node)) {
        send_json_error(connection, MHD_HTTP_INTERNAL_SERVER_ERROR, "DB_ERROR", "Failed to persist node");
        json_decref(root);
        goto cleanup;
    }

    json_t *resp_body = json_pack("{s:s}", "uuid", node.uuid);
    char *payload = json_dumps(resp_body, JSON_COMPACT);
    struct MHD_Response *resp = MHD_create_response_from_buffer(strlen(payload),
                                                                payload, MHD_RESPMEM_MUST_FREE);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    MHD_queue_response(connection, MHD_HTTP_CREATED, resp);
    MHD_destroy_response(resp);
    json_decref(resp_body);
    json_decref(root);

cleanup:
    free(ctx->data);
    free(ctx);
    *con_cls = NULL;
    return MHD_YES;
}

static int http_router(void *cls, struct MHD_Connection *connection,
                       const char *url, const char *method,
                       const char *version, const char *upload_data,
                       size_t *upload_data_size, void **con_cls)
{
    (void)cls; (void)version;
    if (strcmp(method, "GET") == 0) {
        const char *uuid = extract_uuid_from_url(url);
        if (uuid) {
            return handle_get_node(connection, uuid);
        }
        /* GraphQL endpoint GET not allowed */
        send_json_error(connection, MHD_HTTP_NOT_FOUND, "NOT_FOUND", "Endpoint not found");
        return MHD_YES;

    } else if (strcmp(method, "POST") == 0) {
        if (strcmp(url, "/v1/narratives") == 0) {
            return handle_post_node(connection, upload_data, upload_data_size, con_cls);
        } else if (strcmp(url, "/v1/graphql") == 0) {
            if (*upload_data_size > 0) {
                /* accumulate entire body, we assume small */
                req_ctx_t *ctx = *con_cls;
                if (!ctx) {
                    ctx = calloc(1, sizeof(req_ctx_t));
                    *con_cls = ctx;
                }
                ctx->data = realloc(ctx->data, ctx->size + *upload_data_size + 1);
                memcpy(ctx->data + ctx->size, upload_data, *upload_data_size);
                ctx->size += *upload_data_size;
                ctx->data[ctx->size] = '\0';
                *upload_data_size = 0;
                return MHD_YES;
            } else if (*con_cls) {
                req_ctx_t *ctx = *con_cls;
                char *resp_body = NULL;
                int status = handle_graphql_request(ctx->data, &resp_body);
                if (!resp_body && status == MHD_HTTP_OK) {
                    send_json_error(connection, MHD_HTTP_INTERNAL_SERVER_ERROR, "UNKNOWN",
                                    "No response produced");
                    free(ctx->data);
                    free(ctx);
                    *con_cls = NULL;
                    return MHD_YES;
                }
                if (status != MHD_HTTP_OK) {
                    send_json_error(connection, status,
                                    status == MHD_HTTP_NOT_FOUND ? "NOT_FOUND" : "BAD_REQUEST",
                                    "GraphQL request failed");
                } else {
                    struct MHD_Response *resp = MHD_create_response_from_buffer(
                                strlen(resp_body), resp_body, MHD_RESPMEM_MUST_FREE);
                    MHD_add_response_header(resp, "Content-Type", "application/json");
                    MHD_queue_response(connection, status, resp);
                    MHD_destroy_response(resp);
                }
                free(ctx->data);
                free(ctx);
                *con_cls = NULL;
                return MHD_YES;
            }
        }
    }
    send_json_error(connection, MHD_HTTP_NOT_FOUND, "NOT_FOUND", "Endpoint not found");
    return MHD_YES;
}

/* ------------------------------------------------------------------------- */
/*                                 LIFECYCLE                                 */
/* ------------------------------------------------------------------------- */
static struct MHD_Daemon *g_daemon = NULL;

static void signal_handler(int sig)
{
    (void)sig;
    if (g_daemon) {
        MHD_quiesce_daemon(g_daemon);
    }
}

static bool http_startup(uint16_t port)
{
    g_daemon = MHD_start_daemon(
        MHD_USE_AUTO_INTERNAL_THREAD | MHD_USE_THREAD_PER_CONNECTION,
        port,
        NULL, NULL,
        &http_router, NULL,
        MHD_OPTION_CONNECTION_MEMORY_LIMIT, MAX_REQUEST_SIZE_BYTES,
        MHD_OPTION_END);
    return g_daemon != NULL;
}

static void http_shutdown(void)
{
    if (g_daemon) {
        MHD_stop_daemon(g_daemon);
        g_daemon = NULL;
    }
}

static void pool_destroy(void)
{
    for (size_t i = 0; i < DB_CONN_POOL; ++i) {
        if (g_pool[i].db) sqlite3_close(g_pool[i].db);
        pthread_mutex_destroy(&g_pool[i].mtx);
    }
}

/* ------------------------------------------------------------------------- */
/*                                    MAIN                                   */
/* ------------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    openlog(SERVICE_NAME, LOG_PID | LOG_CONS, LOG_USER);
    syslog(LOG_INFO, "%s v%s starting up", SERVICE_NAME, SERVICE_VERSION);

    if (!repo_init()) {
        syslog(LOG_CRIT, "Repository initialization failed");
        return EXIT_FAILURE;
    }

    uint16_t port = DEFAULT_HTTP_PORT;
    const char *env_port = getenv("NARRATIVE_PORT");
    if (env_port) {
        int tmp = atoi(env_port);
        if (tmp > 0 && tmp < 65536) port = (uint16_t)tmp;
    }

    signal(SIGTERM, signal_handler);
    signal(SIGINT,  signal_handler);

    if (!http_startup(port)) {
        syslog(LOG_CRIT, "Failed to launch HTTP server on port %u", port);
        pool_destroy();
        return EXIT_FAILURE;
    }

    syslog(LOG_INFO, "Listening on port %u", port);
    pause(); /* Block until a termination signal arrives */

    syslog(LOG_INFO, "Shutting down");
    http_shutdown();
    pool_destroy();
    closelog();
    return EXIT_SUCCESS;
}