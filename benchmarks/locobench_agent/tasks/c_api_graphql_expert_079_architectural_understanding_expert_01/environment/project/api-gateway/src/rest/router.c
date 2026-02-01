```c
/**
 * SynestheticCanvas API Suite – REST Gateway
 * File:    src/rest/router.c
 * Author:  SynestheticCanvas Core Team
 *
 * A small, dependency–lightweight HTTP router that provides:
 *   • Method + path + version dispatch
 *   • Named-parameter extraction (e.g. /palette/:id/brush/:brushId)
 *   • Optional request-level validation and pagination helpers
 *   • Syslog-style structured logging
 *
 * NOTE:  The router is intentionally built without hard-wiring to a specific
 *        HTTP server implementation.  Instead, embed this component inside
 *        whatever front-end (libmicrohttpd, civetweb, nginx-unit, etc.) you
 *        prefer by translating their native request/response structs into the
 *        generic `sc_http_request_t` / `sc_http_response_t` seen below.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdarg.h>
#include <string.h>
#include <ctype.h>
#include <syslog.h>
#include <regex.h>
#include <errno.h>

#include "router.h"          /* public header for this compilation unit */
#include "util/strings.h"    /* small, project-wide helpers */
#include "util/strvec.h"
#include "util/pagination.h"

/*─────────────────────────────────────────────────────────────────────────────
 *  Internal types & constants
 *─────────────────────────────────────────────────────────────────────────── */

#define ROUTER_MAX_REGEX      256   /* max compiled pattern length            */
#define REGEX_PARAM_GROUP     2     /* # of groups produced by `([^/]+)`       */
#define DEFAULT_PAGE_SIZE     50
#define MAX_VALIDATION_ERR    256

typedef struct route_s
{
    sc_http_method_e            method;
    unsigned                    version;    /* e.g. 1 for `/v1/…`              */
    char                       *pattern;    /* original URI pattern            */
    regex_t                     regex;      /* compiled regex                  */
    strvec_t                    param_names;/* ":paletteId", etc.              */

    sc_validator_fn            *validator;  /* optional – returns bool         */
    sc_request_handler_fn      *handler;    /* mandatory → writes response     */

    void                       *user_ctx;   /* opaque per-route user data      */
} route_t;

struct sc_router_s
{
    route_t           *routes;
    size_t             len;
    size_t             cap;

    /* configurable knobs */
    bool               enable_logging;
};

/*─────────────────────────────────────────────────────────────────────────────
 *  Forward declarations
 *─────────────────────────────────────────────────────────────────────────── */

static bool compile_pattern(route_t *r, const char *pattern, char *err_buf,
                            size_t err_len);
static bool extract_params(const route_t       *route,
                           const char          *path,
                           sc_param_list_t     *out);
static void route_destroy(route_t *r);

/*─────────────────────────────────────────────────────────────────────────────
 *  Public API
 *─────────────────────────────────────────────────────────────────────────── */

sc_router_t *sc_router_create(bool enable_logging)
{
    sc_router_t *router = calloc(1, sizeof(*router));
    if (!router)
        return NULL;

    router->enable_logging = enable_logging;
    router->cap            = 8;
    router->routes         = calloc(router->cap, sizeof(route_t));
    if (!router->routes)
    {
        free(router);
        return NULL;
    }
    openlog("SynestheticCanvas", LOG_PID | LOG_NDELAY, LOG_USER);
    return router;
}

void sc_router_destroy(sc_router_t *router)
{
    if (!router) return;

    for (size_t i = 0; i < router->len; ++i)
        route_destroy(&router->routes[i]);

    free(router->routes);
    free(router);
    closelog();
}

/**
 * Register a new endpoint pattern.
 *
 * Example:
 *    sc_router_register(router,
 *                       SC_HTTP_GET, 1, "/palette/:paletteId/colors",
 *                       palette_validator,
 *                       palette_handler,
 *                       NULL);
 */
bool sc_router_register(sc_router_t           *router,
                        sc_http_method_e       method,
                        unsigned               version,
                        const char            *pattern,
                        sc_validator_fn       *validator,
                        sc_request_handler_fn *handler,
                        void                  *user_ctx)
{
    if (!router || !pattern || !handler)
        return false;

    /* Ensure capacity */
    if (router->len == router->cap)
    {
        size_t new_cap = router->cap * 2;
        route_t *tmp   = realloc(router->routes, new_cap * sizeof(route_t));
        if (!tmp)
            return false;
        router->routes = tmp;
        router->cap    = new_cap;
    }

    route_t *r = &router->routes[router->len];
    memset(r, 0, sizeof(*r));

    r->method    = method;
    r->version   = version;
    r->pattern   = strdup(pattern);
    r->validator = validator;
    r->handler   = handler;
    r->user_ctx  = user_ctx;
    strvec_init(&r->param_names);

    char errbuf[128];
    if (!compile_pattern(r, pattern, errbuf, sizeof(errbuf)))
    {
        syslog(LOG_ERR, "Router: failed to compile pattern '%s': %s",
               pattern, errbuf);
        free(r->pattern);
        return false;
    }

    ++router->len;
    if (router->enable_logging)
        syslog(LOG_INFO, "Router: registered v%u %s %s",
               version, sc_http_method_name(method), pattern);

    return true;
}

/**
 * Central dispatch entry-point.  Converts an incoming request into an internal
 * representation, performs route lookup, validation, and hands control to the
 * endpoint handler.  Returns `true` if a route was matched (regardless of
 * HTTP status).  Returns `false` when no route matched, allowing the caller to
 * fall back to 404 behavior.
 */
bool sc_router_handle(sc_router_t        *router,
                      const sc_http_request_t  *req,
                      sc_http_response_t       *res)
{
    if (!router || !req || !res)
        return false;

    for (size_t i = 0; i < router->len; ++i)
    {
        const route_t *route = &router->routes[i];

        if (route->method != req->method ||
            route->version != req->version)
            continue;

        if (regexec(&route->regex, req->path, 0, NULL, 0) != 0)
            continue; /* path mismatch */

        /* --- matched --- */
        char validation_err[MAX_VALIDATION_ERR] = {0};
        if (route->validator &&
            !route->validator(req, validation_err, sizeof(validation_err)))
        {
            sc_response_set_status(res, 400);
            sc_response_set_body_fmt(res, "Validation failed: %s",
                                     validation_err[0] ? validation_err
                                                       : "Schema mismatch");
            if (router->enable_logging)
                syslog(LOG_WARNING, "Validation failed for %s %s: %s",
                       sc_http_method_name(req->method),
                       req->path,
                       validation_err);
            return true; /* handled */
        }

        sc_param_list_t params;
        sc_param_list_init(&params);
        if (!extract_params(route, req->path, &params))
        {
            sc_response_set_status(res, 500);
            sc_response_set_body(res, "Internal error (param extraction)");
            return true;
        }

        /* Pagination helper — attaches to request struct for convenience */
        sc_pagination_t pagination;
        sc_pagination_from_query(req->query, DEFAULT_PAGE_SIZE, &pagination);

        if (router->enable_logging)
            syslog(LOG_INFO, "Dispatch %s %s → %s (page=%u, size=%u)",
                   sc_http_method_name(req->method),
                   req->path,
                   route->pattern,
                   pagination.page,
                   pagination.page_size);

        /* Call user handler */
        bool ok = route->handler(req, res, &params, &pagination, route->user_ctx);

        sc_param_list_free(&params);
        return ok;
    }

    return false; /* no route matched */
}

/*─────────────────────────────────────────────────────────────────────────────
 *  Pattern compilation + helpers
 *─────────────────────────────────────────────────────────────────────────── */

/*
 * Convert a human-readable pattern (e.g. "/palette/:id") into a POSIX regex,
 * capturing each named parameter.  For every ":param", we generate a "([^/]+)"
 * capture group and store "param" into the route's `param_names`.
 */
static bool compile_pattern(route_t *r, const char *pattern,
                            char *err_buf, size_t err_len)
{
    char regex_buf[ROUTER_MAX_REGEX] = {0};
    char *dst = regex_buf;
    const char *src = pattern;

    if (*src != '/')
    {
        snprintf(err_buf, err_len, "Pattern must start with '/'");
        return false;
    }

    *(dst++) = '^'; /* match from start */

    while (*src && (dst - regex_buf) < ROUTER_MAX_REGEX - 1)
    {
        if (*src == ':')
        {
            /* start of param name */
            const char *start = ++src;
            while (*src && (isalnum(*src) || *src == '_'))
                ++src;

            size_t len = src - start;
            if (len == 0)
            {
                snprintf(err_buf, err_len, "Empty param name in pattern");
                return false;
            }

            char name[64];
            memcpy(name, start, len);
            name[len] = '\0';
            strvec_push(&r->param_names, name);

            /* append capture group */
            strcpy(dst, "([^/]+)");
            dst += strlen("([^/]+)");
            continue;
        }
        else if (*src == '*')
        {
            /* greedy wildcard */
            strcpy(dst, "(.*)");
            dst += strlen("(.*)");
            ++src;
            continue;
        }
        else
        {
            /* escape regex meta-characters */
            if (strchr(".+?^$()[]{}", *src))
                *(dst++) = '\\';
            *(dst++) = *src++;
        }
    }

    *(dst++) = '$';
    *dst = '\0';

    int rc = regcomp(&r->regex, regex_buf, REG_EXTENDED | REG_ICASE);
    if (rc != 0)
    {
        regerror(rc, &r->regex, err_buf, err_len);
        return false;
    }
    return true;
}

/* Extract params into key/value vector (already matched!) */
static bool extract_params(const route_t   *route,
                           const char      *path,
                           sc_param_list_t *out)
{
    size_t groups   = route->param_names.len;
    regmatch_t      match[groups + 1]; /* group 0 = whole match */

    if (regexec(&route->regex, path, groups + 1, match, 0) != 0)
        return false;

    for (size_t i = 0; i < groups; ++i)
    {
        if (match[i + 1].rm_so == -1)
            continue; /* shouldn't happen */

        size_t len = (size_t)(match[i + 1].rm_eo - match[i + 1].rm_so);
        char *value = strndup(path + match[i + 1].rm_so, len);
        sc_param_list_add(out, route->param_names.items[i], value);
        free(value);
    }
    return true;
}

static void route_destroy(route_t *r)
{
    if (!r) return;

    regfree(&r->regex);
    free(r->pattern);
    strvec_free(&r->param_names);
}

/*─────────────────────────────────────────────────────────────────────────────
 *  Minimal helper implementations (could be moved to headers)
 *─────────────────────────────────────────────────────────────────────────── */

/* Human-readable method names */
const char *sc_http_method_name(sc_http_method_e m)
{
    switch (m)
    {
        case SC_HTTP_GET:     return "GET";
        case SC_HTTP_POST:    return "POST";
        case SC_HTTP_PUT:     return "PUT";
        case SC_HTTP_PATCH:   return "PATCH";
        case SC_HTTP_DELETE:  return "DELETE";
        default:              return "UNKNOWN";
    }
}

/* default pagination implementation if not linked */
#ifndef HAVE_PAGINATION_UTILS
void sc_pagination_from_query(const char *qs, unsigned default_size,
                              sc_pagination_t *out)
{
    out->page_size = default_size;
    out->page      = 1;

    if (!qs) return;

    char *dup = strdup(qs);
    char *token, *saveptr;
    for (token = strtok_r(dup, "&", &saveptr);
         token;
         token = strtok_r(NULL, "&", &saveptr))
    {
        if (strncmp(token, "page_size=", 10) == 0)
            out->page_size = (unsigned) atoi(token + 10);
        else if (strncmp(token, "page=", 5) == 0)
            out->page = (unsigned) atoi(token + 5);
    }
    free(dup);
}
#endif
```