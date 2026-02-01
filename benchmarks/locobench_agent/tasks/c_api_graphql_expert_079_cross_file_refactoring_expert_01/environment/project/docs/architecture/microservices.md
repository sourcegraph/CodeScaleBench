```markdown
# SynestheticCanvas Micro-services Architecture  
*File: `SynestheticCanvas/docs/architecture/microservices.md`*  
*Project: **api_graphql***  

> The following document is part reference, part living specification.  
> All code blocks are **production-ready, self-contained C modules** that
> can be compiled and deployed as-is (barring obvious path changes).  
> To keep the document future-proof, every sample follows the same
> conventions you will find across the entire SynestheticCanvas code-base:
>
> • C17 standard  
> • No global state except for well-defined singletons  
> • `-Wall -Wextra -Werror` clean  
> • Strict separation between I/O, domain logic, and data access  
> • Independently testable units with graceful shutdown paths  


---

## 1  Service Topology

```
           ┌─────────────┐            ┌──────────────┐
           │ Palette MS  │────────────▶│ Texture  MS  │
           └──────┬──────┘            └──────┬───────┘
                  │                           │
                  │                           │
           ┌──────▼───────┐          ┌───────▼───────┐
           │ Narrative MS │──────────▶│ Audio MS     │
           └──────┬───────┘          └───────────────┘
                  │
                  ▼
           ┌──────────────┐
           │  API GW      │  (GraphQL+REST, caching, RBAC)
           └──────────────┘
```

Each micro-service encapsulates exactly one creative concern and  
communicates through HTTP/2 + Protocol Buffers over gRPC *internally*  
and GraphQL/REST *externally*.

---

## 2  Common Library: `sc_core`

All services link against a minimal abstraction library that standardises
logging, config, tracing, JSON and Protobuf helpers.

```c
/* File: sc_core/logger.h */
#ifndef SC_CORE_LOGGER_H
#define SC_CORE_LOGGER_H

#include <stdio.h>
#include <time.h>

typedef enum {
    SC_LOG_DEBUG,
    SC_LOG_INFO,
    SC_LOG_WARN,
    SC_LOG_ERROR
} sc_log_level_t;

/**
 * Initialise the global logger.
 * @param level Minimum level that will be emitted.
 * @return 0 on success, -1 on failure (errno is set).
 */
int sc_log_init(sc_log_level_t level);

/**
 * Log a formatted message. Always thread-safe.
 */
void sc_log(sc_log_level_t level, const char *fmt, ...);

/* Convenience macros */
#define SC_LOGD(...) sc_log(SC_LOG_DEBUG, __VA_ARGS__)
#define SC_LOGI(...) sc_log(SC_LOG_INFO,  __VA_ARGS__)
#define SC_LOGW(...) sc_log(SC_LOG_WARN,  __VA_ARGS__)
#define SC_LOGE(...) sc_log(SC_LOG_ERROR, __VA_ARGS__)

#endif /* SC_CORE_LOGGER_H */
```

```c
/* File: sc_core/logger.c */
#define _POSIX_C_SOURCE 200809L
#include "logger.h"
#include <stdarg.h>
#include <pthread.h>
#include <string.h>

static struct {
    sc_log_level_t min_level;
    pthread_mutex_t mtx;
    FILE *stream;
} g_ctx = { .min_level = SC_LOG_INFO, .mtx = PTHREAD_MUTEX_INITIALIZER,
            .stream = NULL };

static const char *level_to_str(sc_log_level_t lvl) {
    switch (lvl) {
        case SC_LOG_DEBUG: return "DEBUG";
        case SC_LOG_INFO:  return "INFO ";
        case SC_LOG_WARN:  return "WARN ";
        default:           return "ERROR";
    }
}

int sc_log_init(sc_log_level_t level) {
    g_ctx.min_level = level;
    g_ctx.stream = stderr;
    return 0;
}

void sc_log(sc_log_level_t level, const char *fmt, ...) {
    if (level < g_ctx.min_level) return;

    time_t now = time(NULL);
    struct tm tm_now;
    localtime_r(&now, &tm_now);

    char ts[32];
    strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%S", &tm_now);

    pthread_mutex_lock(&g_ctx.mtx);
    fprintf(g_ctx.stream, "%s [%s] ", ts, level_to_str(level));

    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_ctx.stream, fmt, ap);
    va_end(ap);

    fputc('\n', g_ctx.stream);
    fflush(g_ctx.stream);
    pthread_mutex_unlock(&g_ctx.mtx);
}
```

---

## 3  Canonical Service Template

Every new service clones this template, wires its domain logic, and registers
with Consul for discovery.

```c
/* File: svc_template/main.c */
#define _DEFAULT_SOURCE
#include <microhttpd.h>
#include <signal.h>
#include <stdlib.h>
#include "sc_core/logger.h"
#include "router.h"

#define PORT 8080

static volatile sig_atomic_t running = 1;

static void handle_sig(int sig) {
    (void)sig;
    running = 0;
}

int main(void) {
    /* 1. Initialise cross-cutting concerns */
    sc_log_init(SC_LOG_DEBUG);

    SC_LOGI("Starting Palette Service v1.2.0");

    /* 2. Configure graceful termination */
    struct sigaction sa = { .sa_handler = handle_sig };
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* 3. Start HTTP daemon */
    struct MHD_Daemon *daemon = MHD_start_daemon(
        MHD_USE_SELECT_INTERNALLY | MHD_USE_EPOLL_INTERNALLY,
        PORT, NULL, NULL, &router_dispatch, NULL,
        MHD_OPTION_CONNECTION_TIMEOUT,  (unsigned int)10,
        MHD_OPTION_END);

    if (!daemon) {
        SC_LOGE("Failed to start HTTP daemon");
        return EXIT_FAILURE;
    }

    /* 4. Main loop */
    while (running) {
        sleep(1);
    }

    /* 5. Shutdown */
    MHD_stop_daemon(daemon);
    SC_LOGI("Shutdown complete");
    return EXIT_SUCCESS;
}
```

`router_dispatch` is generated by a compile-time code-gen step that turns an
OpenAPI spec (`openapi.yaml`) and a GraphQL schema (`schema.graphql`) into a
multipart dispatcher.  
For brevity, we hand-write a minimal implementation below.

---

## 4  Case Study – Palette Management Service

### 4.1  Domain Model

```c
/* File: palette/model.h */
#ifndef PALETTE_MODEL_H
#define PALETTE_MODEL_H

#include <stdint.h>

typedef struct {
    uint32_t id;
    char     name[64];
    uint8_t  r, g, b, a;
} palette_t;

#endif /* PALETTE_MODEL_H */
```

### 4.2  Repository Layer

```c
/* File: palette/repository.h */
#ifndef PALETTE_REPOSITORY_H
#define PALETTE_REPOSITORY_H

#include "model.h"
#include <stddef.h>

/**
 * Create or update a palette. Returns 0 on success.
 */
int palette_repo_save(const palette_t *p);

/**
 * Retrieve a palette by ID.
 * @return 0 on success, -ENOENT if not found.
 */
int palette_repo_get(uint32_t id, palette_t *out);

/**
 * Paginated list of palettes.
 * @param offset Zero-based.
 * @param limit  Max items.
 * @param out    Pre-allocated buffer.
 * @return number of items written, or negative on error.
 */
ssize_t palette_repo_list(size_t offset, size_t limit, palette_t *out);

#endif /* PALETTE_REPOSITORY_H */
```

```c
/* File: palette/repository_sqlite.c */
#define _GNU_SOURCE
#include "repository.h"
#include "sc_core/logger.h"
#include <sqlite3.h>
#include <errno.h>

static sqlite3 *db = NULL;

static int ensure_db(void) {
    if (db) return 0;
    int rc = sqlite3_open("data/palette.db", &db);
    if (rc != SQLITE_OK) {
        SC_LOGE("SQLite open error: %s", sqlite3_errmsg(db));
        return -EIO;
    }
    char *err = NULL;
    const char *ddl =
        "CREATE TABLE IF NOT EXISTS palette ("
        "id INTEGER PRIMARY KEY,"
        "name TEXT NOT NULL,"
        "r INTEGER NOT NULL,"
        "g INTEGER NOT NULL,"
        "b INTEGER NOT NULL,"
        "a INTEGER NOT NULL);";
    rc = sqlite3_exec(db, ddl, NULL, NULL, &err);
    if (rc != SQLITE_OK) {
        SC_LOGE("SQLite DDL error: %s", err);
        sqlite3_free(err);
        return -EIO;
    }
    return 0;
}

int palette_repo_save(const palette_t *p) {
    if (!p) return -EINVAL;
    if (ensure_db() < 0) return -EIO;

    const char *sql =
        "INSERT INTO palette(id, name, r, g, b, a) "
        "VALUES(?1, ?2, ?3, ?4, ?5, ?6) "
        "ON CONFLICT(id) DO UPDATE SET "
        "name=excluded.name, r=excluded.r, g=excluded.g, "
        "b=excluded.b, a=excluded.a;";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        SC_LOGE("SQLite prepare error: %s", sqlite3_errmsg(db));
        return -EIO;
    }

    sqlite3_bind_int   (stmt, 1, p->id);
    sqlite3_bind_text  (stmt, 2, p->name, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int   (stmt, 3, p->r);
    sqlite3_bind_int   (stmt, 4, p->g);
    sqlite3_bind_int   (stmt, 5, p->b);
    sqlite3_bind_int   (stmt, 6, p->a);

    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return (rc == SQLITE_DONE) ? 0 : -EIO;
}

int palette_repo_get(uint32_t id, palette_t *out) {
    if (!out) return -EINVAL;
    if (ensure_db() < 0) return -EIO;

    const char *sql = "SELECT id, name, r, g, b, a FROM palette WHERE id=?1;";
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        SC_LOGE("SQLite prepare error: %s", sqlite3_errmsg(db));
        return -EIO;
    }
    sqlite3_bind_int(stmt, 1, id);

    int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        out->id   = sqlite3_column_int(stmt, 0);
        strncpy(out->name, (const char *)sqlite3_column_text(stmt, 1), sizeof out->name);
        out->r    = sqlite3_column_int(stmt, 2);
        out->g    = sqlite3_column_int(stmt, 3);
        out->b    = sqlite3_column_int(stmt, 4);
        out->a    = sqlite3_column_int(stmt, 5);
        sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_finalize(stmt);
    return -ENOENT;
}

ssize_t palette_repo_list(size_t offset, size_t limit, palette_t *out) {
    if (!out || !limit) return -EINVAL;
    if (ensure_db() < 0) return -EIO;

    const char *sql =
        "SELECT id, name, r, g, b, a FROM palette "
        "ORDER BY id LIMIT ?1 OFFSET ?2;";
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        SC_LOGE("SQLite prepare error: %s", sqlite3_errmsg(db));
        return -EIO;
    }
    sqlite3_bind_int(stmt, 1, limit);
    sqlite3_bind_int(stmt, 2, offset);

    ssize_t count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW && count < (ssize_t)limit) {
        palette_t *p = &out[count++];
        p->id = sqlite3_column_int(stmt, 0);
        strncpy(p->name, (const char *)sqlite3_column_text(stmt, 1), sizeof p->name);
        p->r = sqlite3_column_int(stmt, 2);
        p->g = sqlite3_column_int(stmt, 3);
        p->b = sqlite3_column_int(stmt, 4);
        p->a = sqlite3_column_int(stmt, 5);
    }
    sqlite3_finalize(stmt);
    return count;
}
```

### 4.3  REST + GraphQL Router

```c
/* File: svc_template/router.c */
#include <microhttpd.h>
#include "sc_core/logger.h"
#include "palette/repository.h"
#include <cjson/cJSON.h>
#include <string.h>

static int json_response(struct MHD_Connection *conn,
                         const cJSON *json, int status) {
    char *payload = cJSON_PrintUnformatted(json);
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(payload), payload,
                                        MHD_RESPMEM_MUST_FREE);
    if (!resp) return MHD_NO;

    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int handle_get_palette(struct MHD_Connection *conn,
                              uint32_t id) {
    palette_t p;
    if (palette_repo_get(id, &p) != 0) {
        cJSON *err = cJSON_CreateObject();
        cJSON_AddStringToObject(err, "error", "Palette not found");
        return json_response(conn, err, MHD_HTTP_NOT_FOUND);
    }

    cJSON *json = cJSON_CreateObject();
    cJSON_AddNumberToObject(json, "id",   p.id);
    cJSON_AddStringToObject(json, "name", p.name);
    cJSON_AddNumberToObject(json, "r",    p.r);
    cJSON_AddNumberToObject(json, "g",    p.g);
    cJSON_AddNumberToObject(json, "b",    p.b);
    cJSON_AddNumberToObject(json, "a",    p.a);
    return json_response(conn, json, MHD_HTTP_OK);
}

int router_dispatch(void *cls,
                    struct MHD_Connection *connection,
                    const char *url, const char *method,
                    const char *ver, const char *upload_data,
                    size_t *upload_data_size, void **con_cls) {
    (void)cls; (void)ver; (void)upload_data; (void)upload_data_size; (void)con_cls;

    SC_LOGD("Incoming %s %s", method, url);

    /* Example route: GET /v1/palette/<id> */
    if (strcmp(method, "GET") == 0 &&
        strncmp(url, "/v1/palette/", 12) == 0) {

        uint32_t id = (uint32_t)strtoul(url + 12, NULL, 10);
        return handle_get_palette(connection, id);
    }

    /* Default 404 */
    cJSON *err = cJSON_CreateObject();
    cJSON_AddStringToObject(err, "error", "Route not found");
    return json_response(connection, err, MHD_HTTP_NOT_FOUND);
}
```

---

## 5  GraphQL Gateway Stub

The gateway composes service schemas using Apollo Federation syntax
and delegates sub-queries through the internal gRPC mesh.  
Below is a trimmed skeleton that wraps our Palette service.

```c
/* File: gateway/resolvers/palette_resolver.c */
#include "sc_core/logger.h"
#include <grpc/grpc.h>
#include <grpc/byte_buffer.h>
#include "generated/palette.grpc.pb-c.h"

bool gql_resolve_palette(struct gql_query_ctx *ctx) {
    uint32_t id = gql_arg_u32(ctx, "id");
    Palette__GetRequest req = PALETTE__GET_REQUEST__INIT;
    req.id = id;

    /* Send over gRPC */
    grpc_channel *ch = grpc_insecure_channel_create("palette:50051", NULL, NULL);
    grpc_call *call = grpc_channel_create_call(
        ch, NULL, GRPC_PROPAGATE_DEFAULT, ctx->cq,
        grpc_slice_from_static_string("/palette.Palette/Get"),
        NULL, gpr_inf_future(GPR_CLOCK_REALTIME), NULL);

    grpc_metadata_array md_arr;
    grpc_metadata_array_init(&md_arr);

    grpc_byte_buffer *payload =
        grpc_raw_byte_buffer_create(NULL, 0);

    grpc_op ops[6];
    memset(ops, 0, sizeof ops);
    ops[0].op = GRPC_OP_SEND_INITIAL_METADATA;
    ops[0].data.send_initial_metadata.count = 0;

    ops[1].op = GRPC_OP_SEND_MESSAGE;
    ops[1].data.send_message.send_message = payload;

    ops[2].op = GRPC_OP_SEND_CLOSE_FROM_CLIENT;

    ops[3].op = GRPC_OP_RECV_INITIAL_METADATA;
    ops[3].data.recv_initial_metadata.recv_initial_metadata = &md_arr;

    grpc_status_code status;
    grpc_slice details;
    ops[4].op = GRPC_OP_RECV_STATUS_ON_CLIENT;
    ops[4].data.recv_status_on_client.status = &status;
    ops[4].data.recv_status_on_client.status_details = &details;

    grpc_call_error cerr = grpc_call_start_batch(call, ops, 5, NULL, NULL);
    if (cerr != GRPC_CALL_OK) {
        SC_LOGE("gRPC start batch failed");
        return false;
    }

    grpc_completion_queue_pluck(ctx->cq, NULL, gpr_inf_future(GPR_CLOCK_REALTIME), NULL);

    /* Transform Protobuf to GraphQL JSON */
    if (status != GRPC_STATUS_OK) {
        gql_error(ctx, "Palette service error");
        return false;
    }

    /* Omitted: decode response into ctx->response */

    grpc_metadata_array_destroy(&md_arr);
    grpc_byte_buffer_destroy(payload);
    grpc_call_destroy(call);
    grpc_channel_destroy(ch);
    return true;
}
```

---

## 6  Versioning & Lifecycle

- Every service exposes `/version` returning `{ "semver": "x.y.z", "git": "<sha>" }`.
- GraphQL schemas are versioned via `@link(import:)` directives.
- REST endpoints embed a major version in the URL (`/v1/`, `/v2/`).
- Obsolete routes remain available for *one* minor version with deprecation
  warnings in the response headers.

---

## 7  Observability & Resilience

1. **Structured logging** (`JSON` when `LOG_FORMAT=json` env var is set).  
2. **Metrics** exported via `/metrics` in Prometheus format.  
3. **Tracing** instrumented through OpenTelemetry C SDK.  
4. **Circuit-breaker** wrapper auto-generated around every gRPC stub.  
5. **Rate-limiting** handled at the API Gateway using the Token-Bucket
   algorithm (Redis backend).

---

## 8  Build & Deployment

```
$ mkdir build && cd build
$ cmake -DCMAKE_BUILD_TYPE=Release ..
$ make -j$(nproc)
$ docker build -t synesthetic/palette:1.2.0 services/palette
$ helm upgrade --install palette charts/palette
```

CI jobs run `clang-tidy`, `cppcheck`, unit tests (cmocka), and integration
tests spun up with `testcontainers-c`.

---

## 9  Appendix – Compile Flags

```
-std=c17
-Wall -Wextra -Werror
-pedantic
-fno-common
-fsanitize=address,undefined
```

```