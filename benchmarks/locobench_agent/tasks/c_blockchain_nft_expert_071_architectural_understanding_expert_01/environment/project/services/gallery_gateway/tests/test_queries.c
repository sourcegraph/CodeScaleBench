/*
 * HoloCanvas – Gallery Gateway
 * tests/test_queries.c
 *
 * Unit-tests for query serialization / deserialization routines that are
 * responsible for talking to the Gallery-Gateway micro-service.  These tests
 * use the CMocka framework and the Jansson JSON library.
 *
 * Compile (example):
 *      cc -Wall -Wextra -std=c17 \
 *         -I/usr/include \
 *         -o test_queries \
 *         test_queries.c \
 *         -lcmocka -ljansson
 *
 * The code in this file purposefully embeds a *minimal* reference
 * implementation of the component under test so the test binary can be
 * compiled and executed in isolation from the remainder of the platform.
 * In production builds, those symbols are expected to come from the real
 * gallery_gateway library and the reference implementation will be skipped
 * thanks to weak symbol aliases (see the `#ifndef HAVE_REAL_GG_QUERY_API`
 * guard below).
 */

#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <jansson.h>
#include <cmocka.h>

/* -------------------------------------------------------------------------
 * Public gallery-gateway API
 * ------------------------------------------------------------------------- */

/* Artifact life-cycle state as tracked by the State-Machine consensus layer */
typedef enum {
    GG_STATE_DRAFT,
    GG_STATE_CURATED,
    GG_STATE_AUCTION,
    GG_STATE_FRACTIONALIZED,
    GG_STATE_STAKED,
    GG_STATE_UNKNOWN
} gg_state_t;

/* Structure representing a UI / REST query from a client */
typedef struct {
    char       *owner;      /* wallet address / owner filter (nullable) */
    gg_state_t  state;      /* life-cycle state filter (GG_STATE_UNKNOWN = any) */
    uint32_t    limit;      /* pagination size                         */
    uint32_t    offset;     /* pagination offset                       */
} gg_query_t;

/* A single artifact record as delivered by the gateway */
typedef struct {
    char     *id;           /* unique artifact ID, hex string          */
    char     *title;        /* human-readable title                    */
    gg_state_t state;       /* current state                           */
} gg_artifact_t;

/*
 * Serialize query into JSON.  `buf` may be NULL, in which case the function
 * will return the required buffer size in `*out_len` and return ‑ENOSPC.
 *
 * Returns 0 on success, ‑errno on failure.
 */
int gg_query_to_json(const gg_query_t *query,
                     char             *buf,
                     size_t            buf_sz,
                     size_t           *out_len);

/*
 * Parse gateway JSON response (an array of artifacts) into an allocated
 * `gg_artifact_t *` owned by the caller.  On success the function allocates
 * `*artifacts` which must be freed via gg_free_artifacts() by the caller.
 *
 * Returns 0 on success, ‑errno on error.
 */
int gg_query_parse_response(const char      *json_str,
                            gg_artifact_t  **artifacts,
                            size_t          *count);

/* Helper for freeing an artifact array allocated by the parser. */
void gg_free_artifacts(gg_artifact_t *arts, size_t count);

/* -------------------------------------------------------------------------
 * Reference implementation (only used when linking tests stand-alone)
 * ------------------------------------------------------------------------- */
#ifndef HAVE_REAL_GG_QUERY_API

static const char *state_to_str(gg_state_t s)
{
    switch (s) {
    case GG_STATE_DRAFT:         return "Draft";
    case GG_STATE_CURATED:       return "Curated";
    case GG_STATE_AUCTION:       return "Auction";
    case GG_STATE_FRACTIONALIZED:return "Fractionalized";
    case GG_STATE_STAKED:        return "Staked";
    default:                     return "Unknown";
    }
}

static gg_state_t str_to_state(const char *s)
{
    if (!s) return GG_STATE_UNKNOWN;
    if (strcmp(s, "Draft")          == 0) return GG_STATE_DRAFT;
    if (strcmp(s, "Curated")        == 0) return GG_STATE_CURATED;
    if (strcmp(s, "Auction")        == 0) return GG_STATE_AUCTION;
    if (strcmp(s, "Fractionalized") == 0) return GG_STATE_FRACTIONALIZED;
    if (strcmp(s, "Staked")         == 0) return GG_STATE_STAKED;
    return GG_STATE_UNKNOWN;
}

int gg_query_to_json(const gg_query_t *query,
                     char             *buf,
                     size_t            buf_sz,
                     size_t           *out_len)
{
    if (!query || !out_len) return -EINVAL;

    json_t *root = json_object();
    if (!root) return -ENOMEM;

    if (query->owner)
        json_object_set_new(root, "owner", json_string(query->owner));

    if (query->state != GG_STATE_UNKNOWN)
        json_object_set_new(root, "state", json_string(state_to_str(query->state)));

    json_object_set_new(root, "limit",  json_integer(query->limit));
    json_object_set_new(root, "offset", json_integer(query->offset));

    char *rendered = json_dumps(root, JSON_COMPACT | JSON_SORT_KEYS);
    json_decref(root);
    if (!rendered) return -ENOMEM;

    *out_len = strlen(rendered) + 1; /* +NUL */

    int rc = 0;
    if (buf) {
        if (*out_len > buf_sz) {
            rc = -ENOSPC;
        } else {
            memcpy(buf, rendered, *out_len);
        }
    } else {
        rc = -ENOSPC;
    }

    free(rendered);
    return rc;
}

int gg_query_parse_response(const char      *json_str,
                            gg_artifact_t  **artifacts,
                            size_t          *count)
{
    if (!json_str || !artifacts || !count) return -EINVAL;

    json_error_t jerr;
    json_t *root = json_loads(json_str, 0, &jerr);
    if (!root) return -EINVAL;

    if (!json_is_array(root)) {
        json_decref(root);
        return -EINVAL;
    }

    size_t arr_size = json_array_size(root);
    gg_artifact_t *out = calloc(arr_size, sizeof(*out));
    if (!out) {
        json_decref(root);
        return -ENOMEM;
    }

    for (size_t i = 0; i < arr_size; ++i) {
        json_t *item = json_array_get(root, i);
        if (!json_is_object(item)) {
            json_decref(root);
            gg_free_artifacts(out, i);
            return -EINVAL;
        }

        const char *id    = json_string_value(json_object_get(item, "id"));
        const char *title = json_string_value(json_object_get(item, "title"));
        const char *state = json_string_value(json_object_get(item, "state"));

        if (!id || !title || !state) {
            json_decref(root);
            gg_free_artifacts(out, i);
            return -EINVAL;
        }

        out[i].id    = strdup(id);
        out[i].title = strdup(title);
        out[i].state = str_to_state(state);

        if (!out[i].id || !out[i].title) {
            json_decref(root);
            gg_free_artifacts(out, i + 1);
            return -ENOMEM;
        }
    }

    json_decref(root);
    *artifacts = out;
    *count     = arr_size;
    return 0;
}

void gg_free_artifacts(gg_artifact_t *arts, size_t count)
{
    if (!arts) return;
    for (size_t i = 0; i < count; ++i) {
        free(arts[i].id);
        free(arts[i].title);
    }
    free(arts);
}

#endif /* !HAVE_REAL_GG_QUERY_API */

/* -------------------------------------------------------------------------
 * Test helpers
 * ------------------------------------------------------------------------- */
static gg_query_t make_test_query(void)
{
    return (gg_query_t){
        .owner  = "0xdeadbeefcafecafe1234",
        .state  = GG_STATE_CURATED,
        .limit  = 25,
        .offset = 0
    };
}

static const char *sample_response_json =
    "["
    " {\"id\":\"a1\",\"title\":\"Sunset Mirage\",\"state\":\"Draft\"},"
    " {\"id\":\"a2\",\"title\":\"Glitch Garden\",\"state\":\"Curated\"}"
    "]";

/* -------------------------------------------------------------------------
 * Unit Tests
 * ------------------------------------------------------------------------- */

/* Test JSON serialization with a properly sized buffer */
static void test_serialize_basic_query(void **state)
{
    (void)state;

    gg_query_t q = make_test_query();

    /* First pass: ask for required size */
    size_t required = 0;
    int rc = gg_query_to_json(&q, NULL, 0, &required);
    assert_int_equal(rc, -ENOSPC);
    assert_true(required > 0);

    char *buf = malloc(required);
    assert_non_null(buf);

    rc = gg_query_to_json(&q, buf, required, &required);
    assert_int_equal(rc, 0);

    /* Ensure JSON contains the expected keys/values */
    assert_non_null(strstr(buf, "\"owner\":\"0xdeadbeefcafecafe1234\""));
    assert_non_null(strstr(buf, "\"state\":\"Curated\""));
    assert_non_null(strstr(buf, "\"limit\":25"));
    assert_non_null(strstr(buf, "\"offset\":0"));

    free(buf);
}

/* Verify serializer signals insufficient buffer size */
static void test_serialize_small_buffer(void **state)
{
    (void)state;
    gg_query_t q = make_test_query();

    char tiny[4];
    size_t out_len = 0;
    int rc = gg_query_to_json(&q, tiny, sizeof(tiny), &out_len);
    assert_int_equal(rc, -ENOSPC);
    assert_true(out_len > sizeof(tiny));
}

/* Parse a valid response and check resulting artifact data */
static void test_parse_valid_response(void **state)
{
    (void)state;

    gg_artifact_t *arts = NULL;
    size_t         cnt  = 0;

    int rc = gg_query_parse_response(sample_response_json, &arts, &cnt);
    assert_int_equal(rc, 0);
    assert_int_equal(cnt, 2);

    assert_string_equal(arts[0].id,    "a1");
    assert_string_equal(arts[0].title, "Sunset Mirage");
    assert_int_equal(arts[0].state,    GG_STATE_DRAFT);

    assert_string_equal(arts[1].id,    "a2");
    assert_string_equal(arts[1].title, "Glitch Garden");
    assert_int_equal(arts[1].state,    GG_STATE_CURATED);

    gg_free_artifacts(arts, cnt);
}

/* Ensure parser returns error on malformed JSON */
static void test_parse_invalid_json(void **state)
{
    (void)state;
    gg_artifact_t *arts = NULL;
    size_t cnt = 0;
    const char *bad_json = "{ \"not_an_array\": true }";

    int rc = gg_query_parse_response(bad_json, &arts, &cnt);
    assert_int_equal(rc, -EINVAL);
    assert_null(arts);
    assert_int_equal(cnt, 0);
}

/* Round-trip: serialize → parse using pagination values ≠ defaults */
static void test_roundtrip_pagination(void **state)
{
    (void)state;

    gg_query_t q = {
        .owner  = NULL,
        .state  = GG_STATE_UNKNOWN,
        .limit  = 10,
        .offset = 30,
    };

    /* Serialize */
    size_t need = 0;
    (void)gg_query_to_json(&q, NULL, 0, &need);

    char *json = malloc(need);
    assert_non_null(json);
    assert_int_equal(gg_query_to_json(&q, json, need, &need), 0);

    /* The gateway echoes the query for observability; mimic that */
    json_t *root       = json_loads(json, 0, NULL);
    json_t *artifacts  = json_array();
    json_t *response   = json_array();
    json_array_append_new(response, root);
    json_array_extend(response, artifacts); /* keep first element as query echo */

    char *rendered_resp = json_dumps(response, JSON_COMPACT);
    json_decref(response);

    gg_artifact_t *arts = NULL;
    size_t cnt = 0;
    int rc = gg_query_parse_response(rendered_resp, &arts, &cnt);

    /* Parser should ignore the query echo (not a valid artifact object) and fail */
    assert_int_equal(rc, -EINVAL);

    free(json);
    free(rendered_resp);
}

/* -------------------------------------------------------------------------
 * Main
 * ------------------------------------------------------------------------- */
int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_serialize_basic_query),
        cmocka_unit_test(test_serialize_small_buffer),
        cmocka_unit_test(test_parse_valid_response),
        cmocka_unit_test(test_parse_invalid_json),
        cmocka_unit_test(test_roundtrip_pagination),
    };

    return cmocka_run_group_tests_name("Gallery-Gateway Query API", tests,
                                       NULL, /* group_setup  */
                                       NULL  /* group_teardown */);
}