/*
 * SynestheticCanvas/api-gateway/graphql/schema.c
 *
 *  A production-grade GraphQL schema module for the SynestheticCanvas API Gateway.
 *  -------------------------------------------------------------------------------
 *  Responsibilities
 *   • Load and version GraphQL SDL files at start-up (hot-reload when the file changes)
 *   • Perform syntactic/semantic validation of incoming queries
 *   • Dispatch resolvers that fan-out to downstream micro-services
 *   • Provide a thin caching layer for compiled execution plans
 *   • Emit structured logs and metrics for observability
 *
 *  Build dependencies (excerpt)
 *   • libgraphqlparser         – BSD-licensed GraphQL parser
 *   • libevent / civetweb      – HTTP/WebSocket server used by gateway
 *   • jansson                  – JSON handling
 *   • libuv                    – Async I/O + file-watcher
 *   • libmicrohttpd            – REST fallback layer
 *
 *  Author: SynestheticCanvas Core Team
 *  License: Apache-2.0
 */

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <uv.h>

#include <graphqlparser/GraphQLParser.h>
#include <jansson.h>

#include "config.h"          /* Global configuration */
#include "gateway_metrics.h" /* Prometheus-style metrics helpers */
#include "gateway_router.h"  /* Service registry + HTTP client pool */
#include "logger.h"          /* Structured logger used across the project */
#include "schema.h"          /* Public header for this compilation unit */

/* -------------------------------------------------------------------------- */
/* Constants & Macros                                                         */
/* -------------------------------------------------------------------------- */

#define SCHEMA_FILE            "schemas/v1/core.graphqls"
#define SCHEMA_VERSION_CURRENT 1
#define EXEC_CACHE_MAX         256  /* Maximum number of cached execution plans */

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
/* -------------------------------------------------------------------------- */

/* Compiled execution plan cached for a given query string                  */
typedef struct
{
    char                      *query_hash;  /* SHA-256 of original GraphQL query */
    const graphql_node         *ast_root;   /* Parsed AST root owned by cache    */
    time_t                      created_at; /* For LRU eviction                  */
} exec_plan_t;

/* Central container that stores the active schema and related metadata     */
typedef struct
{
    char                     *sdl_buf;          /* Schema file contents        */
    size_t                    sdl_len;
    const graphql_node       *schema_ast;       /* AST for SDL                */
    uint32_t                  version;          /* Major version              */
    time_t                    last_mod_time;    /* For hot-reload             */

    exec_plan_t               exec_cache[EXEC_CACHE_MAX];
    size_t                    exec_cache_sz;

    uv_fs_event_t             fs_watcher;       /* libuv file watcher         */
} schema_context_t;

/* -------------------------------------------------------------------------- */
/* Static Globals                                                             */
/* -------------------------------------------------------------------------- */

static schema_context_t g_ctx;

/* -------------------------------------------------------------------------- */
/* Forward Declarations                                                       */
/* -------------------------------------------------------------------------- */

static int  load_schema_from_disk(void);
static void fs_event_cb(uv_fs_event_t *handle, const char *file,
                        int events, int status);
static int  validate_query_ast(const graphql_node *root, json_t **errors_out);
static exec_plan_t *exec_cache_lookup(const char *hash);
static void exec_cache_store(const char *hash, const graphql_node *root);
static void exec_cache_evict_lru_if_needed(void);

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

int
schema_bootstrap(uv_loop_t *loop)
{
    memset(&g_ctx, 0, sizeof(g_ctx));

    if (load_schema_from_disk() != 0)
    {
        SC_LOG_ERROR("Failed to load GraphQL schema, aborting bootstrap");
        return -1;
    }

    /* Start hot-reload file watcher */
    int rc = uv_fs_event_init(loop, &g_ctx.fs_watcher);
    if (rc != 0)
    {
        SC_LOG_WARN("Unable to init fs watcher: %s", uv_strerror(rc));
        /* Not fatal – continue without hot-reload */
        return 0;
    }

    rc = uv_fs_event_start(&g_ctx.fs_watcher, fs_event_cb, SCHEMA_FILE,
                           UV_FS_EVENT_RECURSIVE);
    if (rc != 0)
    {
        SC_LOG_WARN("Unable to start fs watcher: %s", uv_strerror(rc));
        /* Also non-fatal */
    }

    return 0;
}

void
schema_shutdown(void)
{
    /* Stop watcher */
    uv_fs_event_stop(&g_ctx.fs_watcher);

    /* Free SDL buffer */
    free(g_ctx.sdl_buf);

    /* Free schema AST */
    graphql_node_free(g_ctx.schema_ast);

    /* Free cached execution plans */
    for (size_t i = 0; i < g_ctx.exec_cache_sz; ++i)
    {
        free(g_ctx.exec_cache[i].query_hash);
        graphql_node_free(g_ctx.exec_cache[i].ast_root);
    }
}

/*
 * schema_execute
 *  -------------
 *  Validate and execute a GraphQL query string. If successful, the resulting
 *  JSON payload is returned in *result_out. Caller owns the returned object.
 *
 *  returns 0 on success; !=0 on failure and *error_out is set.
 */
int
schema_execute(const char  *query,
               const json_t *variables,
               json_t      **result_out,
               json_t      **error_out)
{
    if (!query || !result_out || !error_out)
        return EINVAL;

    *result_out = NULL;
    *error_out  = NULL;

    /* -------------------------------------------------- */
    /* Step 1: Compute cache key (SHA-256 hex)            */
    /* -------------------------------------------------- */
    char query_hash[65] = {0};
    sc_sha256_hex(query, strlen(query), query_hash);

    /* -------------------------------------------------- */
    /* Step 2: Look up cached execution plan              */
    /* -------------------------------------------------- */
    exec_plan_t *plan = exec_cache_lookup(query_hash);

    if (!plan)
    {
        /* Parse query into AST */
        graphql_error_list *parse_errs = NULL;
        const graphql_node *query_ast  = graphql_parse_string(query, &parse_errs);

        if (!query_ast)
        {
            /* Convert parser errors to JSON */
            *error_out = graphql_errors_to_json(parse_errs);
            graphql_error_list_free(parse_errs);
            return EPROTO;
        }

        /* Validate AST against active schema */
        int v_rc = validate_query_ast(query_ast, error_out);
        if (v_rc != 0)
        {
            graphql_node_free(query_ast);
            return v_rc;
        }

        /* Cache compiled plan */
        exec_cache_store(query_hash, query_ast);

        plan = exec_cache_lookup(query_hash);
    }

    /* -------------------------------------------------- */
    /* Step 3: Execute plan (query AST)                   */
    /* -------------------------------------------------- */
    sc_timer_t exec_timer;
    sc_timer_start(&exec_timer);

    int exec_rc = router_execute_query(plan->ast_root, variables, result_out,
                                       error_out);

    double elapsed_ms = sc_timer_stop(&exec_timer);
    metrics_observe_histogram(METRIC_GRAPHQL_LATENCY_MS, elapsed_ms);

    if (exec_rc != 0)
    {
        metrics_inc_counter(METRIC_GRAPHQL_ERRORS_TOTAL);
        return exec_rc;
    }

    metrics_inc_counter(METRIC_GRAPHQL_SUCCESS_TOTAL);
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Internal – Schema Loading & Hot-Reload                                     */
/* -------------------------------------------------------------------------- */

static int
load_schema_from_disk(void)
{
    struct stat st;
    if (stat(SCHEMA_FILE, &st) != 0)
    {
        SC_LOG_ERROR("stat(%s) failed: %s", SCHEMA_FILE, strerror(errno));
        return -1;
    }

    FILE *fp = fopen(SCHEMA_FILE, "rb");
    if (!fp)
    {
        SC_LOG_ERROR("Failed opening schema file %s: %s",
                     SCHEMA_FILE, strerror(errno));
        return -1;
    }

    char *buf = malloc(st.st_size + 1);
    if (!buf)
    {
        fclose(fp);
        return ENOMEM;
    }

    if (fread(buf, 1, st.st_size, fp) != (size_t)st.st_size)
    {
        SC_LOG_ERROR("Read error on schema file");
        fclose(fp);
        free(buf);
        return EIO;
    }
    buf[st.st_size] = '\0'; /* Null-terminate */
    fclose(fp);

    graphql_error_list *parse_errs = NULL;
    const graphql_node *schema_ast = graphql_parse_string(buf, &parse_errs);
    if (!schema_ast)
    {
        json_t *errs_json = graphql_errors_to_json(parse_errs);
        char   *errs_str  = json_dumps(errs_json, JSON_INDENT(2));

        SC_LOG_ERROR("Schema SDL parsing failed:\n%s", errs_str);

        free(errs_str);
        json_decref(errs_json);
        graphql_error_list_free(parse_errs);
        free(buf);
        return EPROTO;
    }

    /* Validation of SDL against itself / spec rules (optional) */
    /* .. omitted for brevity .. */

    /* Replace previous schema (if any) */
    free(g_ctx.sdl_buf);
    graphql_node_free(g_ctx.schema_ast);

    g_ctx.sdl_buf       = buf;
    g_ctx.sdl_len       = st.st_size;
    g_ctx.schema_ast    = schema_ast;
    g_ctx.version       = SCHEMA_VERSION_CURRENT;
    g_ctx.last_mod_time = st.st_mtime;

    SC_LOG_INFO("GraphQL schema (v%d) loaded, size=%zu bytes",
                g_ctx.version, g_ctx.sdl_len);

    metrics_set_gauge(METRIC_GRAPHQL_SCHEMA_VERSION, (double)g_ctx.version);
    return 0;
}

static void
fs_event_cb(uv_fs_event_t *handle, const char *file,
            int events, int status)
{
    (void)handle;
    (void)events;
    (void)status;

    /* libuv sometimes triggers multiple events – debounce via mtime */
    struct stat st;
    if (stat(SCHEMA_FILE, &st) != 0)
        return;

    if (st.st_mtime == g_ctx.last_mod_time)
        return; /* No change */

    SC_LOG_INFO("Schema file change detected – reloading");
    if (load_schema_from_disk() != 0)
    {
        SC_LOG_WARN("Hot-reload failed – continuing with previous schema");
    }
}

/* -------------------------------------------------------------------------- */
/* Internal – Validation                                                      */
/* -------------------------------------------------------------------------- */

static int
validate_query_ast(const graphql_node *root, json_t **errors_out)
{
    graphql_error_list *validation_errors = NULL;

    bool ok = graphql_validate(g_ctx.schema_ast,
                               root,
                               &validation_errors);

    if (ok)
        return 0;

    if (errors_out)
        *errors_out = graphql_errors_to_json(validation_errors);

    graphql_error_list_free(validation_errors);
    return EPERM;
}

/* -------------------------------------------------------------------------- */
/* Internal – Execution Plan Cache                                            */
/* -------------------------------------------------------------------------- */

static exec_plan_t *
exec_cache_lookup(const char *hash)
{
    for (size_t i = 0; i < g_ctx.exec_cache_sz; ++i)
    {
        if (strcmp(g_ctx.exec_cache[i].query_hash, hash) == 0)
        {
            g_ctx.exec_cache[i].created_at = time(NULL); /* Touch for LRU */
            return &g_ctx.exec_cache[i];
        }
    }
    return NULL;
}

static void
exec_cache_store(const char *hash, const graphql_node *root)
{
    exec_cache_evict_lru_if_needed();

    exec_plan_t *slot = &g_ctx.exec_cache[g_ctx.exec_cache_sz++];

    slot->query_hash = strdup(hash);
    slot->ast_root   = root; /* Ownership transferred */
    slot->created_at = time(NULL);
}

static void
exec_cache_evict_lru_if_needed(void)
{
    if (g_ctx.exec_cache_sz < EXEC_CACHE_MAX)
        return;

    size_t lru_idx     = 0;
    time_t lru_ts      = g_ctx.exec_cache[0].created_at;

    for (size_t i = 1; i < g_ctx.exec_cache_sz; ++i)
    {
        if (g_ctx.exec_cache[i].created_at < lru_ts)
        {
            lru_idx = i;
            lru_ts  = g_ctx.exec_cache[i].created_at;
        }
    }

    /* Free LRU entry */
    free(g_ctx.exec_cache[lru_idx].query_hash);
    graphql_node_free(g_ctx.exec_cache[lru_idx].ast_root);

    /* Collapse array */
    memmove(&g_ctx.exec_cache[lru_idx],
            &g_ctx.exec_cache[lru_idx + 1],
            sizeof(exec_plan_t) * (g_ctx.exec_cache_sz - lru_idx - 1));

    g_ctx.exec_cache_sz--;
}

/* -------------------------------------------------------------------------- */
/* Helper – Convert GraphQL errors to JSON (thin wrapper)                     */
/* -------------------------------------------------------------------------- */

json_t *
graphql_errors_to_json(const graphql_error_list *errs)
{
    json_t *arr = json_array();
    for (const graphql_error *e = errs; e; e = e->next)
    {
        json_t *obj = json_object();
        json_object_set_new(obj, "message", json_string(e->message));
        /* Could add locations, path, extensions... */
        json_array_append_new(arr, obj);
    }
    return arr;
}

/* -------------------------------------------------------------------------- */
/* Optional – SDL Introspection Serving                                       */
/* -------------------------------------------------------------------------- */

/*
 * schema_get_sdl
 * --------------
 *  Return the raw SDL buffer for /__schema (REST) introspection endpoint.
 *  The pointer is owned by the schema module – do NOT free.
 */
const char *
schema_get_sdl(size_t *len_out)
{
    if (len_out)
        *len_out = g_ctx.sdl_len;
    return g_ctx.sdl_buf;
}

/* -------------------------------------------------------------------------- */
/* End of file                                                                */
/* -------------------------------------------------------------------------- */
