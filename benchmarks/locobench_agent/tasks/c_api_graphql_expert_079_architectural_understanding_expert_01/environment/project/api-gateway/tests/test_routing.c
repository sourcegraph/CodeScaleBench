```c
/*
 * SynestheticCanvas/api-gateway/tests/test_routing.c
 *
 * Copyright (c) 2024  PixelWorx.
 *
 * Unit-tests for the API-gateway’s routing subsystem.
 * The tests use the cmocka framework.  To build:
 *
 *      cc -o test_routing \
 *          test_routing.c \
 *          -lcmocka -Wall -Wextra -pedantic -std=c99
 *
 * In the real project these tests would link against the actual routing
 * implementation that lives in api-gateway/src/.  For the sake of having a
 * self-contained, runnable example we embed a **very small** reference
 * implementation that behaves like the production code in the happy-path
 * scenarios we want to validate.
 */

#define _GNU_SOURCE     /* strdup(3) */
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>      /* snprintf */
#include <ctype.h>

#include <cmocka.h>

/* ──────────────────────────────────────────────
 *  Public interface (would normally be in routing.h)
 * ────────────────────────────────────────────── */

typedef enum {
    ROUTE_TYPE_GRAPHQL,
    ROUTE_TYPE_REST,
} route_type_t;

typedef struct {
    /* Service identifier, e.g. "palette" */
    char service_name[64];

    /* Concrete endpoint that the gateway should contact once resolved,
     * e.g. "palette.internal.svc.cluster.local:7080/graphql"            */
    char endpoint[128];

    /* Requested/selected version number   */
    int  version;

    /* HTTP status code on failure, 0 on success */
    int  status_code;

    route_type_t type;
} route_result_t;

/*
 * Resolves an incoming HTTP method/path pair.
 *
 *  method      – "GET", "POST", …
 *  path        – full resource path, possibly version-prefixed (e.g. "/v2/palette")
 *  out         – populated on success, untouched when return value != 0
 *
 * Returns 0 on success, non-zero on error (HTTP status code recommended).
 */
int api_gateway_resolve_route(const char *method,
                              const char *path,
                              route_result_t *out);

/* ──────────────────────────────────────────────
 *  Very small in-memory registry that behaves like the real thing.
 *  ( ONLY included here so the example is self-contained. )
 * ────────────────────────────────────────────── */
typedef struct {
    char           method[8];         /* “GET”/“POST”/… (upper-case)      */
    char           path_pattern[96];  /* “/palette”, “/texture/{id}” …    */
    char           service[64];       /* “palette”, “texture”, …          */
    char           endpoint[128];     /* Host:port + resource path        */
    int            version;           /* Major API version                */
    route_type_t   type;              /* GraphQL / REST                   */
} route_entry_t;

#define MAX_ROUTES 128

static route_entry_t g_registry[MAX_ROUTES];
static size_t        g_route_count = 0;

static void routing_register(const char *method,
                             const char *path_pattern,
                             const char *service,
                             const char *endpoint,
                             int version,
                             route_type_t type)
{
    assert(method && path_pattern && service && endpoint);
    assert(g_route_count < MAX_ROUTES);

    route_entry_t *e = &g_registry[g_route_count++];
    snprintf(e->method,       sizeof(e->method),       "%s", method);
    snprintf(e->path_pattern, sizeof(e->path_pattern), "%s", path_pattern);
    snprintf(e->service,      sizeof(e->service),      "%s", service);
    snprintf(e->endpoint,     sizeof(e->endpoint),     "%s", endpoint);
    e->version = version;
    e->type    = type;
}

/* Helper: strcasecmp that treats NULL as "" */
static int safe_strcasecmp(const char *a, const char *b)
{
    if (!a) a = "";
    if (!b) b = "";
    return strcasecmp(a, b);
}

/* Extracts leading "v<NUM>/" component if present.
 * Returns version or ‑1 when none. out_path is updated to point
 * after the version segment. */
static int extract_version(const char *path, const char **out_path)
{
    if (!path) { *out_path = ""; return -1; }

    if (path[0] == '/' && path[1] == 'v') {
        const char *p = path + 2;
        char numbuf[8] = {0};
        size_t idx = 0;

        while (*p && isdigit((unsigned char)*p) && idx < sizeof(numbuf) - 1)
            numbuf[idx++] = *p++;

        if (idx > 0 && *p == '/') {        /* valid “v<digits>/”  */
            *out_path = p;                 /* point at '/'        */
            return atoi(numbuf);
        }
    }

    *out_path = path;
    return -1;          /* No explicit version prefix            */
}

int api_gateway_resolve_route(const char *method,
                              const char *path,
                              route_result_t *out)
{
    if (!method || !path || !out)
        return 400; /* BadRequest */

    route_entry_t const *best = NULL;
    int requested_version     = -1;

    /* Strip version prefix (“/vN/…”) if supplied. */
    const char *normalized_path = NULL;
    requested_version = extract_version(path, &normalized_path);

    /* First pass – exact method match, exact path pattern. */
    for (size_t i = 0; i < g_route_count; ++i) {
        route_entry_t const *entry = &g_registry[i];

        if (safe_strcasecmp(entry->method, method) != 0)
            continue;

        if (strcmp(entry->path_pattern, normalized_path) != 0)
            continue;

        if (requested_version >= 0 && entry->version != requested_version)
            continue;

        /* Perfect match.                           */
        best = entry;
        break;
    }

    /* Second pass – look for highest compatible version of the same path.  */
    if (!best) {
        int best_version = -1;
        for (size_t i = 0; i < g_route_count; ++i) {
            route_entry_t const *entry = &g_registry[i];

            if (safe_strcasecmp(entry->method, method) != 0)
                continue;

            if (strcmp(entry->path_pattern, normalized_path) != 0)
                continue;

            /* Compatible when requested_version < 0 OR entry->version <= requested_version */
            if (requested_version >= 0 && entry->version > requested_version)
                continue;

            if (entry->version > best_version) {
                best_version = entry->version;
                best = entry;
            }
        }
    }

    if (!best)
        return 404; /* Not Found */

    /* Populate result */
    memset(out, 0, sizeof(*out));
    snprintf(out->service_name, sizeof(out->service_name), "%s", best->service);
    snprintf(out->endpoint,     sizeof(out->endpoint),     "%s", best->endpoint);
    out->version     = best->version;
    out->status_code = 0;
    out->type        = best->type;
    return 0;
}

/* ──────────────────────────────────────────────
 *  Test fixtures
 * ────────────────────────────────────────────── */

static int routing_test_setup(void **state)
{
    (void)state;
    g_route_count = 0;

    /*
     * Palette service (GraphQL + REST fallback, v1 + v2)
     */
    routing_register("POST", "/palette",  "palette",  "palette.svc/graphql", 1, ROUTE_TYPE_GRAPHQL);
    routing_register("GET",  "/palette",  "palette",  "palette.svc/rest",    1, ROUTE_TYPE_REST   );
    routing_register("POST", "/palette",  "palette",  "palette.svc/graphql", 2, ROUTE_TYPE_GRAPHQL);

    /*
     * Texture service (GraphQL only, v2)
     */
    routing_register("POST", "/texture",  "texture",  "texture.svc/graphql", 2, ROUTE_TYPE_GRAPHQL);

    return 0;
}

static int routing_test_teardown(void **state)
{
    (void)state;
    g_route_count = 0;
    return 0;
}

/* ──────────────────────────────────────────────
 *  Individual test cases
 * ────────────────────────────────────────────── */

/* Happy-path: exact version & method match (GraphQL) */
static void test_exact_graphql_match(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("POST", "/v1/palette", &res);
    assert_int_equal(rc, 0);
    assert_string_equal(res.service_name, "palette");
    assert_string_equal(res.endpoint, "palette.svc/graphql");
    assert_int_equal(res.version, 1);
    assert_int_equal(res.type, ROUTE_TYPE_GRAPHQL);
}

/* Version negotiation: requested /v1/palette (POST) but GraphQL v2 also exists.
 * Expect v1 because it is the highest <= requested.                         */
static void test_version_negotiation_downwards(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("POST", "/v1/palette", &res);
    assert_int_equal(rc, 0);
    assert_int_equal(res.version, 1);
}

/* Version negotiation: client does NOT specify version,
 * gateway should pick latest (major) – here v2             */
static void test_latest_version_default(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("POST", "/palette", &res);
    assert_int_equal(rc, 0);
    assert_int_equal(res.version, 2);
}

/* REST fallback when GraphQL missing:
 * GET /v1/palette should map to REST route,
 * because only POST is registered for GraphQL.           */
static void test_rest_fallback(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("GET", "/v1/palette", &res);
    assert_int_equal(rc, 0);
    assert_int_equal(res.type, ROUTE_TYPE_REST);
    assert_string_equal(res.endpoint, "palette.svc/rest");
}

/* Unknown route: expect 404 */
static void test_route_not_found(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("POST", "/v9999/unknown", &res);
    assert_int_equal(rc, 404);
}

/* Method case-insensitivity: “post” vs “POST” should still match */
static void test_method_case_insensitive(void **state)
{
    (void)state;
    route_result_t res;

    int rc = api_gateway_resolve_route("post", "/v2/palette", &res);
    assert_int_equal(rc, 0);
    assert_string_equal(res.service_name, "palette");
}

/* ──────────────────────────────────────────────
 *  Test runner
 * ────────────────────────────────────────────── */

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test_setup_teardown(test_exact_graphql_match,
                                        routing_test_setup, routing_test_teardown),
        cmocka_unit_test_setup_teardown(test_version_negotiation_downwards,
                                        routing_test_setup, routing_test_teardown),
        cmocka_unit_test_setup_teardown(test_latest_version_default,
                                        routing_test_setup, routing_test_teardown),
        cmocka_unit_test_setup_teardown(test_rest_fallback,
                                        routing_test_setup, routing_test_teardown),
        cmocka_unit_test_setup_teardown(test_route_not_found,
                                        routing_test_setup, routing_test_teardown),
        cmocka_unit_test_setup_teardown(test_method_case_insensitive,
                                        routing_test_setup, routing_test_teardown),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
```