/**
 * SynestheticCanvas Palette Service
 *
 * File:    services/palette-service/src/main.c
 * Project: SynestheticCanvas API Suite (api_graphql)
 *
 * Description:
 *   A standalone micro-service exposing a REST/GraphQL façade for palette
 *   management.  Written for production use-cases: configuration through
 *   environment variables, structured logging, graceful shutdown, basic
 *   request validation, pagination and thread-safe in-memory storage.
 *
 * Build:
 *   gcc -Wall -Wextra -pedantic -std=c11 \
 *       -o palette-service main.c -lmicrohttpd -lcjson -lpthread
 *
 * Runtime env-vars:
 *   PAL_SERVICE_PORT   – listen port (default 8082)
 *   PAL_LOG_LEVEL      – LOG_DEBUG, LOG_INFO, LOG_WARNING, LOG_ERR (default INFO)
 *
 * Endpoints:
 *   GET  /healthz                       – liveness probe
 *   GET  /v1/palettes?limit&offset      – list palettes
 *   POST /v1/palettes                   – create palette  (see struct Palette spec)
 *   POST /graphql                       – GraphQL façade (accepts JSON: {query:""})
 *
 * Copyright (c) 2023-2024
 */

#define _POSIX_C_SOURCE 200809L
#include <microhttpd.h>
#include <cjson/cJSON.h>

#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/*                              Logging helpers                               */
/* -------------------------------------------------------------------------- */
static int CURRENT_LOG_LEVEL = LOG_INFO;

#define LOG(level, fmt, ...)                     \
    do {                                         \
        if ((level) <= CURRENT_LOG_LEVEL) {      \
            syslog(level, fmt, ##__VA_ARGS__);   \
        }                                        \
    } while (0)

#define LOG_DEBUG(fmt, ...)  LOG(LOG_DEBUG,  fmt, ##__VA_ARGS__)
#define LOG_INFO_(fmt, ...)  LOG(LOG_INFO,   fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)   LOG(LOG_WARNING,fmt, ##__VA_ARGS__)
#define LOG_ERR_(fmt, ...)   LOG(LOG_ERR,    fmt, ##__VA_ARGS__)

/* -------------------------------------------------------------------------- */
/*                               Data models                                  */
/* -------------------------------------------------------------------------- */
#define UUID_LEN        36u
#define MAX_NAME_LEN   127u
#define MAX_COLORS       8u   /* maximum colours within a palette           */
#define MAX_PALETTES  4096u   /* in-memory cap (fits most demo/show-cases)  */

typedef struct {
    char     id[UUID_LEN + 1];
    char     name[MAX_NAME_LEN + 1];
    char     colors[MAX_COLORS][8];     /* hex colours “#RRGGBB”              */
    size_t   color_count;
    time_t   created_at;
} Palette;

typedef struct {
    Palette           *palettes[MAX_PALETTES];
    size_t             count;
    pthread_mutex_t    lock;
} PaletteRepository;

/* Repository instance (singleton inside this process) */
static PaletteRepository g_repo;

/* --------------------- repository (thread-safe) --------------------------- */
static void
repo_init(PaletteRepository *repo)
{
    memset(repo, 0, sizeof(*repo));
    pthread_mutex_init(&repo->lock, NULL);
}

static void
repo_destroy(PaletteRepository *repo)
{
    pthread_mutex_lock(&repo->lock);
    for (size_t i = 0; i < repo->count; ++i)
        free(repo->palettes[i]);
    pthread_mutex_unlock(&repo->lock);
    pthread_mutex_destroy(&repo->lock);
}

static int
repo_add(PaletteRepository *repo, const Palette *p_in)
{
    int rc = -1;
    pthread_mutex_lock(&repo->lock);
    if (repo->count < MAX_PALETTES) {
        Palette *copy = malloc(sizeof(*copy));
        if (copy) {
            *copy = *p_in;
            repo->palettes[repo->count++] = copy;
            rc = 0;
        }
    }
    pthread_mutex_unlock(&repo->lock);
    return rc;
}

static size_t
repo_get_paginated(PaletteRepository *repo,
                   size_t offset,
                   size_t limit,
                   Palette **out_buf,
                   size_t  buf_len)
{
    size_t written = 0;

    pthread_mutex_lock(&repo->lock);
    if (offset < repo->count) {
        const size_t avail = repo->count - offset;
        const size_t n     = (limit < avail ? limit : avail);
        for (size_t i = 0; i < n && i < buf_len; ++i)
            out_buf[written++] = repo->palettes[offset + i];
    }
    pthread_mutex_unlock(&repo->lock);

    return written;
}

/* -------------------------------------------------------------------------- */
/*                           Utility functions                                */
/* -------------------------------------------------------------------------- */
/* Very small UUIDv4 generator (pseudo-random).  NOT CRYPTO-SAFE.             */
static void
uuid_generate(char out[UUID_LEN + 1])
{
    static const char *hex = "0123456789abcdef";
    uint8_t rnd[16];
    for (size_t i = 0; i < sizeof(rnd); ++i)
        rnd[i] = (uint8_t)(rand() % 256);

    rnd[6] = (rnd[6] & 0x0F) | 0x40; /* version 4 */
    rnd[8] = (rnd[8] & 0x3F) | 0x80; /* variant 1 */

    snprintf(out, UUID_LEN + 1,
             "%02x%02x%02x%02x-"
             "%02x%02x-"
             "%02x%02x-"
             "%02x%02x-"
             "%02x%02x%02x%02x%02x%02x",
             rnd[0], rnd[1], rnd[2], rnd[3],
             rnd[4], rnd[5],
             rnd[6], rnd[7],
             rnd[8], rnd[9],
             rnd[10], rnd[11], rnd[12], rnd[13], rnd[14], rnd[15]);
}

/* Parse size_t from a string safely; returns default_val on error */
static size_t
str_to_sizet(const char *s, size_t default_val)
{
    if (!s) return default_val;
    char *endptr = NULL;
    unsigned long v = strtoul(s, &endptr, 10);
    return (endptr != s && *endptr == '\0') ? (size_t)v : default_val;
}

/* -------------------------------------------------------------------------- */
/*                          HTTP / MicroHTTPD layer                           */
/* -------------------------------------------------------------------------- */

/* Connection specific data used to aggregate POST payloads */
typedef struct {
    char  *body;
    size_t body_size;
    size_t body_cap;
} ConnInfo;

static void
conninfo_free_callback(void *cls, struct MHD_Connection *connection,
                       void **con_cls, enum MHD_RequestTerminationCode toe)
{
    (void)cls; (void)connection; (void)toe;
    ConnInfo *ci = *con_cls;
    if (ci) {
        free(ci->body);
        free(ci);
        *con_cls = NULL;
    }
}

/* Append incoming data to the buffer, auto-expanding */
static bool
conninfo_append(ConnInfo *ci, const char *data, size_t size)
{
    if (size == 0) return true;
    if (ci->body_size + size + 1 > ci->body_cap) {
        size_t new_cap = (ci->body_cap ? ci->body_cap * 2 : 1024);
        while (new_cap < ci->body_size + size + 1)
            new_cap *= 2;
        char *tmp = realloc(ci->body, new_cap);
        if (!tmp) return false;
        ci->body      = tmp;
        ci->body_cap  = new_cap;
    }
    memcpy(ci->body + ci->body_size, data, size);
    ci->body_size += size;
    ci->body[ci->body_size] = '\0';
    return true;
}

/* --------------------------- REST Handlers -------------------------------- */
static struct MHD_Response *
json_response(cJSON *json, int status_code)
{
    char *json_str = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!json_str) return NULL;

    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(json_str),
                                        json_str,
                                        MHD_RESPMEM_MUST_FREE);
    if (!resp) {
        free(json_str);
        return NULL;
    }

    MHD_add_response_header(resp, "Content-Type", "application/json");
    MHD_add_response_header(resp, "Cache-Control", "no-store");
    MHD_add_response_header(resp, "Connection", "close");
    return resp;
}

static int
handle_healthz(struct MHD_Connection *connection)
{
    const char *ok = "ok";
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(ok),
                                        (void *)ok,
                                        MHD_RESPMEM_PERSISTENT);
    if (!resp) return MHD_NO;
    int ret = MHD_queue_response(connection, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int
handle_get_palettes(struct MHD_Connection *connection,
                    const char           *url)
{
    (void)url;
    size_t limit  = str_to_sizet(MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "limit"), 10);
    size_t offset = str_to_sizet(MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "offset"), 0);

    if (limit == 0 || limit > 100)
        limit = 100; /* enforce server-side caps */

    Palette *stack_buf[128]; /* limit capped at 100 so safe */
    const size_t n = repo_get_paginated(&g_repo, offset, limit, stack_buf, 128);

    cJSON *root  = cJSON_CreateObject();
    cJSON *items = cJSON_AddArrayToObject(root, "items");

    for (size_t i = 0; i < n; ++i) {
        Palette *p = stack_buf[i];
        cJSON *jpal = cJSON_CreateObject();
        cJSON_AddStringToObject(jpal, "id", p->id);
        cJSON_AddStringToObject(jpal, "name", p->name);
        cJSON *col = cJSON_AddArrayToObject(jpal, "colors");
        for (size_t c = 0; c < p->color_count; ++c)
            cJSON_AddItemToArray(col, cJSON_CreateString(p->colors[c]));
        cJSON_AddNumberToObject(jpal, "createdAt", (double)p->created_at);
        cJSON_AddItemToArray(items, jpal);
    }
    cJSON_AddNumberToObject(root, "total", (double)g_repo.count);

    struct MHD_Response *resp = json_response(root, MHD_HTTP_OK);
    if (!resp) return MHD_NO;
    int ret = MHD_queue_response(connection, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

static bool
parse_palette_from_json(const char *json_str, Palette *out)
{
    bool ok = false;
    cJSON *root = cJSON_Parse(json_str);
    if (!root) return false;

    cJSON *name  = cJSON_GetObjectItemCaseSensitive(root, "name");
    cJSON *colors= cJSON_GetObjectItemCaseSensitive(root, "colors");
    if (!cJSON_IsString(name) || !name->valuestring ||
        !cJSON_IsArray(colors) )
        goto exit;

    size_t color_count = cJSON_GetArraySize(colors);
    if (color_count == 0 || color_count > MAX_COLORS)
        goto exit;

    memset(out, 0, sizeof(*out));
    uuid_generate(out->id);
    strncpy(out->name, name->valuestring, MAX_NAME_LEN);
    out->color_count = color_count;
    for (size_t i = 0; i < color_count; ++i) {
        cJSON *col = cJSON_GetArrayItem(colors, (int)i);
        if (!cJSON_IsString(col) || strlen(col->valuestring) != 7) /* #RRGGBB */
            goto exit;
        strncpy(out->colors[i], col->valuestring, 7);
    }
    out->created_at = time(NULL);
    ok = true;
exit:
    cJSON_Delete(root);
    return ok;
}

static int
handle_post_palettes(struct MHD_Connection *connection,
                     ConnInfo             *ci)
{
    Palette p;
    if (!parse_palette_from_json(ci->body, &p)) {
        const char *err = "{\"error\":\"Invalid payload\"}";
        struct MHD_Response *resp =
            MHD_create_response_from_buffer(strlen(err),
                                            (void *)err,
                                            MHD_RESPMEM_PERSISTENT);
        MHD_add_response_header(resp, "Content-Type", "application/json");
        int ret = MHD_queue_response(connection, MHD_HTTP_BAD_REQUEST, resp);
        MHD_destroy_response(resp);
        return ret;
    }

    if (repo_add(&g_repo, &p) != 0) {
        const char *err = "{\"error\":\"Repository full\"}";
        struct MHD_Response *resp =
            MHD_create_response_from_buffer(strlen(err),
                                            (void *)err,
                                            MHD_RESPMEM_PERSISTENT);
        MHD_add_response_header(resp, "Content-Type", "application/json");
        int ret = MHD_queue_response(connection, MHD_HTTP_SERVICE_UNAVAILABLE, resp);
        MHD_destroy_response(resp);
        return ret;
    }

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "id", p.id);
    struct MHD_Response *resp = json_response(root, MHD_HTTP_CREATED);
    if (!resp) return MHD_NO;
    int ret = MHD_queue_response(connection, MHD_HTTP_CREATED, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* ------------------------ GraphQL façade (stub) --------------------------- */
static int
handle_graphql(struct MHD_Connection *connection, ConnInfo *ci)
{
    /* Very naive GraphQL stub:
     * Accepts { "query":"{ palettes { id name } }" } and always returns the
     * full palette list identical to REST.
     */
    cJSON *req_json = cJSON_Parse(ci->body);
    if (!req_json) {
        const char *err = "{\"errors\":[{\"message\":\"Malformed JSON\"}]}";
        struct MHD_Response *resp =
            MHD_create_response_from_buffer(strlen(err),
                                            (void *)err,
                                            MHD_RESPMEM_PERSISTENT);
        MHD_add_response_header(resp, "Content-Type", "application/json");
        int ret = MHD_queue_response(connection, MHD_HTTP_BAD_REQUEST, resp);
        MHD_destroy_response(resp);
        return ret;
    }
    cJSON_Delete(req_json); /* We ignore the actual query for brevity */

    /* Re-use repository listing */
    Palette *stack_buf[128];
    const size_t n = repo_get_paginated(&g_repo, 0, 128, stack_buf, 128);

    cJSON *root     = cJSON_CreateObject();
    cJSON *data     = cJSON_AddObjectToObject(root, "data");
    cJSON *pal_arr  = cJSON_AddArrayToObject(data, "palettes");

    for (size_t i = 0; i < n; ++i) {
        Palette *p = stack_buf[i];
        cJSON *jpal = cJSON_CreateObject();
        cJSON_AddStringToObject(jpal, "id", p->id);
        cJSON_AddStringToObject(jpal, "name", p->name);
        cJSON_AddItemToArray(pal_arr, jpal);
    }

    struct MHD_Response *resp = json_response(root, MHD_HTTP_OK);
    if (!resp) return MHD_NO;
    int ret = MHD_queue_response(connection, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* --------------------- Master request dispatcher ------------------------- */
static int
dispatcher(void                    *cls,
           struct MHD_Connection   *connection,
           const char              *url,
           const char              *method,
           const char              *version,
           const char              *upload_data,
           size_t                  *upload_data_size,
           void                   **con_cls)
{
    (void)cls; (void)version;
    ConnInfo *ci = *con_cls;

    if (!ci) { /* first call */
        ci = calloc(1, sizeof(*ci));
        if (!ci) return MHD_NO;
        *con_cls = ci;
        return MHD_YES;
    }

    /* Aggregate incoming POST chunks */
    if (strcmp(method, "POST") == 0) {
        if (*upload_data_size != 0) {
            if (!conninfo_append(ci, upload_data, *upload_data_size))
                return MHD_NO;
            *upload_data_size = 0; /* signal we consumed data */
            return MHD_YES;
        }
        /* Once *upload_data_size == 0, we processed entire body */
    }

    int ret = MHD_NO;

    if (strcmp(url, "/healthz") == 0 && strcmp(method, "GET") == 0) {
        ret = handle_healthz(connection);
    }
    else if (strncmp(url, "/v1/palettes", 12) == 0) {
        if (strcmp(method, "GET") == 0) {
            ret = handle_get_palettes(connection, url);
        } else if (strcmp(method, "POST") == 0) {
            ret = handle_post_palettes(connection, ci);
        } else {
            ret = MHD_queue_response(connection, MHD_HTTP_METHOD_NOT_ALLOWED, NULL);
        }
    }
    else if (strcmp(url, "/graphql") == 0 && strcmp(method, "POST") == 0) {
        ret = handle_graphql(connection, ci);
    }
    else {
        ret = MHD_queue_response(connection, MHD_HTTP_NOT_FOUND, NULL);
    }

    return ret;
}

/* -------------------------------------------------------------------------- */
/*                             Service lifecycle                              */
/* -------------------------------------------------------------------------- */
static volatile sig_atomic_t g_running = 1;

static void
signal_handler(int sig)
{
    (void)sig;
    g_running = 0;
}

static void
load_config(int *out_port)
{
    const char *port_env = getenv("PAL_SERVICE_PORT");
    *out_port = port_env ? atoi(port_env) : 8082;

    const char *lvl = getenv("PAL_LOG_LEVEL");
    if (lvl) {
        if (strcmp(lvl, "LOG_DEBUG") == 0)   CURRENT_LOG_LEVEL = LOG_DEBUG;
        else if (strcmp(lvl, "LOG_INFO") == 0)    CURRENT_LOG_LEVEL = LOG_INFO;
        else if (strcmp(lvl, "LOG_WARNING") == 0) CURRENT_LOG_LEVEL = LOG_WARNING;
        else if (strcmp(lvl, "LOG_ERR") == 0)     CURRENT_LOG_LEVEL = LOG_ERR;
    }
}

/* -------------------------------------------------------------------------- */
/*                                    main                                    */
/* -------------------------------------------------------------------------- */
int
main(void)
{
    openlog("palette-service", LOG_PID | LOG_CONS, LOG_USER);

    int port;
    load_config(&port);
    LOG_INFO_("Starting Palette Service on port %d", port);

    repo_init(&g_repo);

    signal(SIGINT,  signal_handler);
    signal(SIGTERM, signal_handler);

    struct MHD_Daemon *daemon = MHD_start_daemon(
        MHD_USE_SELECT_INTERNALLY | MHD_USE_DEBUG,
        port,
        NULL, NULL,
        &dispatcher, NULL,
        MHD_OPTION_NOTIFY_COMPLETED, conninfo_free_callback, NULL,
        MHD_OPTION_END);

    if (!daemon) {
        LOG_ERR_("Failed to start HTTP daemon");
        return EXIT_FAILURE;
    }

    while (g_running)
        sleep(1);

    LOG_INFO_("Shutting down…");
    MHD_stop_daemon(daemon);
    repo_destroy(&g_repo);
    closelog();
    return EXIT_SUCCESS;
}