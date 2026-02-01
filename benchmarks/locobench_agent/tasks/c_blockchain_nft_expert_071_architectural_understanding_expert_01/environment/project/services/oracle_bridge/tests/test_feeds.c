```c
/*
 * HoloCanvas – Oracle-Bridge
 * tests/test_feeds.c
 *
 * Functional & negative-path unit tests for the Feed subsystem.
 *
 * The Feed component ingests off-chain data from HTTP/JSON oracles and
 * exposes strongly-typed, cached values to the on-chain contract layer.
 *
 * The tests are written with the CMocka framework and use link-time
 * substitution to mock the network layer (net_http_get_json).  No real
 * network traffic is generated during the suite.
 */

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <cmocka.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#include "feed.h"      /* Production header under test */

/* ---------- Test-double for the networking layer ------------------------- */

/*
 * feed.c is linked against net_http_get_json().  We intercept that symbol with
 * CMocka’s link-time wrapping mechanism (-Wl,--wrap=net_http_get_json) so that
 * the production object code will call our shim instead of the real
 * implementation.
 */
int __wrap_net_http_get_json(const char *uri, char **out_json)
{
    /* Ensure the caller passed the expected request URI */
    check_expected_ptr(uri);

    /* Return the JSON payload set up by the individual test */
    *out_json = (char *)mock_ptr_type(char *);

    /* And the integer return code (0 ‑ success) */
    return (int)mock();
}

/* --------------------------- Helper utils -------------------------------- */

/* Boilerplate to destroy dynamically allocated JSON blobs handed to Feed */
static void free_mock_json(char *json)
{
    if (json != NULL)
        free(json);
}

/* ----------------------------- Fixtures ---------------------------------- */

static int setup_feed(void **state)
{
    feed_error_t err;
    feed_t *feed = feed_create("weather.temp",
                               "https://api.example.com/weather/temp",
                               60, /* update interval (seconds) */
                               &err);

    assert_non_null(feed);
    assert_int_equal(err, FEED_ERR_OK);

    *state = feed;
    return 0;
}

static int teardown_feed(void **state)
{
    feed_t *feed = (feed_t *)*state;
    feed_destroy(feed);
    return 0;
}

/* ---------------------------- Test cases --------------------------------- */

/*
 * Positive-path: feed_create() with valid parameters should succeed.
 */
static void test_feed_create_success(void **state)
{
    (void)state; /* Unused */

    feed_error_t err;
    feed_t *feed = feed_create("btc.price",
                               "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                               30,
                               &err);

    assert_non_null(feed);
    assert_int_equal(err, FEED_ERR_OK);

    /* The feed ID must be canonical */
    assert_string_equal(feed_get_id(feed), "btc.price");

    feed_destroy(feed);
}

/*
 * Negative-path: feed_create() must fail on bad arguments.
 */
static void test_feed_create_invalid_params(void **state)
{
    (void)state; /* Unused */

    feed_error_t err;

    /* NULL ID */
    feed_t *feed = feed_create(NULL, "http://example.com", 30, &err);
    assert_null(feed);
    assert_int_equal(err, FEED_ERR_INVALID_ARG);

    /* Zero refresh interval */
    feed = feed_create("foo", "http://example.com", 0, &err);
    assert_null(feed);
    assert_int_equal(err, FEED_ERR_INVALID_ARG);
}

/*
 * Positive-path: feed_fetch_update() should ingest JSON and update the cache.
 */
static void test_feed_fetch_update_success(void **state)
{
    feed_t *feed = (feed_t *)(*state);

    /* Set up the mocked JSON response */
    const char *json_payload = "{\"value\": 42.5}";

    /* Free after test */
    char *dup_payload = strdup(json_payload);

    expect_string(__wrap_net_http_get_json, uri,
                  "https://api.example.com/weather/temp");
    will_return(__wrap_net_http_get_json, dup_payload);
    will_return(__wrap_net_http_get_json, 0); /* Return code */

    feed_error_t err;
    int rc = feed_fetch_update(feed, &err);
    assert_int_equal(rc, 0);
    assert_int_equal(err, FEED_ERR_OK);

    double value = 0.0;
    assert_int_equal(feed_get_value(feed, &value), 0);
    assert_true(value > 42.4 && value < 42.6); /* Allow tiny floating error */
}

/*
 * Negative-path: malformed JSON should surface an error.
 */
static void test_feed_fetch_update_invalid_json(void **state)
{
    feed_t *feed = (feed_t *)(*state);

    const char *bad_json = "{\"oops\": \"not-a-number\"}";
    char *dup_payload = strdup(bad_json);

    expect_string(__wrap_net_http_get_json, uri,
                  "https://api.example.com/weather/temp");
    will_return(__wrap_net_http_get_json, dup_payload);
    will_return(__wrap_net_http_get_json, 0); /* Network layer “success” */

    feed_error_t err;
    int rc = feed_fetch_update(feed, &err);

    assert_int_not_equal(rc, 0);
    assert_int_equal(err, FEED_ERR_PARSE);

    /* Cached value should remain unchanged / unavailable */
    double value = 0.0;
    assert_int_not_equal(feed_get_value(feed, &value), 0);
}

/*
 * Concurrency: multiple threads updating the same feed should not corrupt the
 * internal state.  We stub the network layer to deterministic JSON values to
 * verify final value correctness.
 */

typedef struct {
    feed_t *feed;
    double  value_to_return;
} thread_ctx_t;

static void *thread_update(void *arg)
{
    thread_ctx_t *ctx = (thread_ctx_t *)arg;

    /* Every thread will invoke feed_fetch_update() once. */
    char *json_payload = NULL;
    (void)asprintf(&json_payload, "{\"value\": %.1f}", ctx->value_to_return);

    expect_string(__wrap_net_http_get_json, uri,
                  "https://api.example.com/weather/temp");
    will_return(__wrap_net_http_get_json, json_payload);
    will_return(__wrap_net_http_get_json, 0);

    feed_error_t err;
    assert_int_equal(feed_fetch_update(ctx->feed, &err), 0);
    assert_int_equal(err, FEED_ERR_OK);

    return NULL;
}

static void test_feed_concurrent_updates(void **state)
{
    feed_t *feed = (feed_t *)(*state);
    const size_t thread_count = 8;
    pthread_t threads[thread_count];
    thread_ctx_t ctx[thread_count];

    /* Each thread will set a unique value V = i * 10, last writer wins. */
    for (size_t i = 0; i < thread_count; ++i) {
        ctx[i].feed            = feed;
        ctx[i].value_to_return = (double)(i * 10);

        assert_int_equal(pthread_create(&threads[i], NULL,
                                        thread_update, &ctx[i]), 0);
    }

    for (size_t i = 0; i < thread_count; ++i)
        assert_int_equal(pthread_join(threads[i], NULL), 0);

    /* The final cached value must be equal to the last thread’s payload. */
    double val = 0.0;
    assert_int_equal(feed_get_value(feed, &val), 0);
    assert_true(val > 70.0 && val < 70.1); /* Allow epsilon */
}

/* -------------------------- Test runner ---------------------------------- */

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_feed_create_success),
        cmocka_unit_test(test_feed_create_invalid_params),

        cmocka_unit_test_setup_teardown(
            test_feed_fetch_update_success,
            setup_feed,
            teardown_feed),

        cmocka_unit_test_setup_teardown(
            test_feed_fetch_update_invalid_json,
            setup_feed,
            teardown_feed),

        cmocka_unit_test_setup_teardown(
            test_feed_concurrent_updates,
            setup_feed,
            teardown_feed),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
```