/*
 * SynestheticCanvas Palette Service
 * ---------------------------------
 * palette_handler.c
 *
 * Service-layer entry points for Palette operations.
 * Provides HTTP / GraphQL request handlers that translate
 * inbound payloads into repository commands or queries.
 *
 * This module purposefully contains no transport–specific
 * code (e.g. sockets, HTTP routers).  It is intended to be
 * wired into whichever framework the deployment chooses
 * (REST gateway, GraphQL resolver, message-queue worker,
 * etc.).  All external I/O is expressed through abstract
 * request / response objects so the handler stays
 * decoupled from higher layers.
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include "palette_handler.h"

#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "config.h"             /* service-wide configuration */
#include "logger.h"             /* structured logging facade  */
#include "metrics.h"            /* Prometheus/StatsD exporter */
#include "palette_repository.h" /* storage adapter            */
#include "validation.h"         /* request validation helpers */

#include "cjson/cJSON.h"        /* third-party JSON lib       */

/* ------------------------------------------------------------------------- */
/*  Internal helpers                                                         */
/* ------------------------------------------------------------------------- */

/*
 * Convert a Palette domain object into a cJSON representation.
 */
static cJSON *palette_to_json(const Palette *palette)
{
    assert(palette != NULL);

    cJSON *json = cJSON_CreateObject();
    if (!json)
        return NULL;

    cJSON_AddStringToObject(json, "id", palette->id);
    cJSON_AddStringToObject(json, "name", palette->name);

    cJSON *colors = cJSON_AddArrayToObject(json, "colors");
    for (size_t i = 0; i < palette->color_count; ++i)
    {
        cJSON_AddItemToArray(colors, cJSON_CreateString(palette->colors[i]));
    }

    cJSON_AddStringToObject(json, "createdAt", palette->created_at_iso8601);
    cJSON_AddStringToObject(json, "updatedAt", palette->updated_at_iso8601);

    return json;
}

/*
 * Parse query parameters ?page=<n>&size=<m>.  Defaults are taken from
 * configuration if params are missing.  Returns 0 on success, -1 on failure.
 */
static int parse_pagination(const HttpRequest *req,
                            Pagination       *out_pg,
                            char            **error_msg)
{
    assert(req != NULL);
    assert(out_pg != NULL);

    const char *page_str = http_request_query_param(req, "page");
    const char *size_str = http_request_query_param(req, "size");

    uint32_t page = page_str ? (uint32_t)strtoul(page_str, NULL, 10)
                             : CONFIG_DEFAULT_PAGE;
    uint32_t size = size_str ? (uint32_t)strtoul(size_str, NULL, 10)
                             : CONFIG_DEFAULT_PAGE_SIZE;

    if (page == 0)
        page = CONFIG_DEFAULT_PAGE; /* page numbers start at 1 */

    if (size == 0 || size > CONFIG_MAX_PAGE_SIZE)
    {
        asprintf(error_msg,
                 "Page size must be between 1 and %u",
                 CONFIG_MAX_PAGE_SIZE);
        return -1;
    }

    out_pg->page = page;
    out_pg->size = size;
    return 0;
}

/*
 * Push JSON to HttpResponse and handle memory.
 */
static int json_to_response(HttpResponse *resp, cJSON *json, int status_code)
{
    char *payload = cJSON_PrintUnformatted(json);
    if (!payload)
        return -1;

    http_response_set_status(resp, status_code);
    http_response_set_header(resp, "Content-Type", "application/json");
    http_response_set_body(resp, payload, strlen(payload));

    free(payload);
    return 0;
}

/* ------------------------------------------------------------------------- */
/*  Public API                                                               */
/* ------------------------------------------------------------------------- */

PaletteHandler *palette_handler_create(PaletteRepository *repo,
                                       Logger            *logger,
                                       MetricsRegistry   *metrics,
                                       const char        *service_version)
{
    assert(repo && logger && metrics && service_version);

    PaletteHandler *handler = calloc(1, sizeof *handler);
    if (!handler)
        return NULL;

    handler->repo            = repo;
    handler->log             = logger;
    handler->metrics         = metrics;
    handler->service_version = strdup(service_version);
    if (!handler->service_version)
    {
        free(handler);
        return NULL;
    }

    return handler;
}

void palette_handler_destroy(PaletteHandler *handler)
{
    if (!handler)
        return;

    free(handler->service_version);
    free(handler);
}

void palette_handler_handle_healthz(PaletteHandler    *handler,
                                    const HttpRequest *req,
                                    HttpResponse      *resp)
{
    (void)req; /* unused */

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "status", "ok");
    cJSON_AddStringToObject(root, "service", "palette");
    cJSON_AddStringToObject(root, "version", handler->service_version);

    json_to_response(resp, root, HTTP_STATUS_OK);
    cJSON_Delete(root);

    logger_info(handler->log, "healthz", "Served health check");
}

void palette_handler_handle_get_list(PaletteHandler    *handler,
                                     const HttpRequest *req,
                                     HttpResponse      *resp)
{
    Pagination pg = {0};
    char *pg_err  = NULL;

    if (parse_pagination(req, &pg, &pg_err) < 0)
    {
        logger_warn(handler->log, "validation",
                    "Invalid pagination params: %s", pg_err);
        http_response_send_error(resp, HTTP_STATUS_BAD_REQUEST, pg_err);
        free(pg_err);
        return;
    }

    RepositoryResult *repo_res = palette_repository_fetch_page(
        handler->repo, pg.page, pg.size);

    if (repo_res->error)
    {
        logger_error(handler->log, "repository",
                     "Failed to fetch palettes: %s", repo_res->error);
        http_response_send_error(resp, HTTP_STATUS_INTERNAL_SERVER_ERROR,
                                 "Internal server error");
        repository_result_free(repo_res);
        return;
    }

    cJSON *root = cJSON_CreateObject();
    cJSON *arr  = cJSON_AddArrayToObject(root, "items");

    for (size_t i = 0; i < repo_res->palettes_len; ++i)
    {
        cJSON *jpal = palette_to_json(repo_res->palettes[i]);
        cJSON_AddItemToArray(arr, jpal);
    }

    cJSON_AddNumberToObject(root, "page", (double)pg.page);
    cJSON_AddNumberToObject(root, "size", (double)pg.size);
    cJSON_AddNumberToObject(root, "total",
                            (double)repo_res->total_records);

    json_to_response(resp, root, HTTP_STATUS_OK);

    cJSON_Delete(root);
    repository_result_free(repo_res);

    metrics_inc_counter(handler->metrics,
                        "palette_list_requests_total", 1);
}

void palette_handler_handle_get_single(PaletteHandler    *handler,
                                       const HttpRequest *req,
                                       HttpResponse      *resp,
                                       const char        *palette_id)
{
    if (!validation_is_uuid(palette_id))
    {
        http_response_send_error(resp, HTTP_STATUS_BAD_REQUEST,
                                 "Invalid palette ID");
        return;
    }

    Palette *pal = palette_repository_get(handler->repo, palette_id);
    if (!pal)
    {
        http_response_send_error(resp, HTTP_STATUS_NOT_FOUND,
                                 "Palette not found");
        return;
    }

    cJSON *jpal = palette_to_json(pal);
    json_to_response(resp, jpal, HTTP_STATUS_OK);

    cJSON_Delete(jpal);
    palette_free(pal);

    metrics_inc_counter(handler->metrics,
                        "palette_read_requests_total", 1);
}

void palette_handler_handle_create(PaletteHandler    *handler,
                                   const HttpRequest *req,
                                   HttpResponse      *resp)
{
    const char *body      = http_request_body(req);
    size_t      body_len  = http_request_body_length(req);
    char       *val_error = NULL;

    /* Basic JSON schema validation */
    if (!validation_validate_json(body, body_len,
                                  "schemas/palette_create.json",
                                  &val_error))
    {
        http_response_send_error(resp, HTTP_STATUS_BAD_REQUEST, val_error);
        free(val_error);
        return;
    }

    cJSON *json = cJSON_ParseWithLength(body, body_len);
    if (!json)
    {
        http_response_send_error(resp, HTTP_STATUS_BAD_REQUEST,
                                 "Malformed JSON");
        return;
    }

    const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(json, "name"));
    cJSON      *col  = cJSON_GetObjectItem(json, "colors");

    size_t color_count = (size_t)cJSON_GetArraySize(col);
    char  **colors     = calloc(color_count, sizeof(char *));
    if (!colors)
    {
        cJSON_Delete(json);
        http_response_send_error(resp, HTTP_STATUS_INTERNAL_SERVER_ERROR,
                                 "Memory allocation failed");
        return;
    }

    for (size_t i = 0; i < color_count; ++i)
    {
        const char *cstr = cJSON_GetStringValue(
            cJSON_GetArrayItem(col, (int)i));
        colors[i] = strdup(cstr);
    }

    PaletteCreateSpec spec = {
        .name        = name,
        .colors      = colors,
        .color_count = color_count,
    };

    Palette *created = palette_repository_create(handler->repo, &spec);
    palette_create_spec_free(&spec); /* frees colors list */

    if (!created)
    {
        cJSON_Delete(json);
        http_response_send_error(resp, HTTP_STATUS_CONFLICT,
                                 "Palette with the same name already exists");
        return;
    }

    cJSON *resp_json = palette_to_json(created);
    json_to_response(resp, resp_json, HTTP_STATUS_CREATED);

    cJSON_Delete(resp_json);
    cJSON_Delete(json);
    palette_free(created);

    metrics_inc_counter(handler->metrics,
                        "palette_create_requests_total", 1);
}

void palette_handler_handle_delete(PaletteHandler    *handler,
                                   const HttpRequest *req,
                                   HttpResponse      *resp,
                                   const char        *palette_id)
{
    (void)req; /* Not used for now */

    if (!validation_is_uuid(palette_id))
    {
        http_response_send_error(resp, HTTP_STATUS_BAD_REQUEST,
                                 "Invalid palette ID");
        return;
    }

    if (!palette_repository_delete(handler->repo, palette_id))
    {
        http_response_send_error(resp, HTTP_STATUS_NOT_FOUND,
                                 "Palette not found");
        return;
    }

    http_response_set_status(resp, HTTP_STATUS_NO_CONTENT);

    metrics_inc_counter(handler->metrics,
                        "palette_delete_requests_total", 1);
}

/* EOF */
