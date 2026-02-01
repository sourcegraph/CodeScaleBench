```c
/**
 * HoloCanvas – Muse Observer Service
 * ----------------------------------
 * File:    services/muse_observer/tests/test_triggers.c
 * Purpose: Unit-tests for trigger evaluation & reaction logic
 * Author:  HoloCanvas Core Team
 *
 * The Muse Observer watches for on-/off-chain “artistic” events
 * (likes, oracle feeds, DAO votes, etc.) and tells the rendering
 * pipeline when an NFT should evolve.  These tests exercise the
 * trigger decision tree and validate that the observer publishes
 * the proper downstream events once the criteria are met.
 *
 * Build (example):
 *   gcc -I../../include -I../../../external/cmocka/include \
 *       -L../../../external/cmocka/lib \
 *       -lcmocka -ldl -o test_triggers test_triggers.c
 *
 * NOTE: The production object files are *not* linked in; we rely
 *       on cmocka’s `--wrap` linker trick and local stubs for the
 *       few dependencies we need to intercept.
 */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>

#include <cmocka.h>

#include "muse_observer/triggers.h"
#include "muse_observer/event_bus.h"

/* -------------------------------------------------------------------------
 * Minimal stub infrastructure
 * ------------------------------------------------------------------------- */

/* In production, this comes from `event_bus.h`.  We re-declare just enough
 * so the tests compile in isolation if the real header/schema changes.     */
#ifndef HOLOCANVAS_EVENT_T_DEFINED
#define HOLOCANVAS_EVENT_T_DEFINED
typedef enum
{
    EV_TYPE_UNKNOWN = 0,
    EV_TYPE_LIKE,
    EV_TYPE_ORACLE_WEATHER,
    EV_TYPE_NFT_EVOLUTION
} hc_event_type_t;

typedef struct
{
    char            id[64];     /* UUIDv4 or keccak-256 digest */
    hc_event_type_t type;
    union {
        struct {
            uint32_t current_likes;
            uint32_t threshold_likes;
        } like;

        struct {
            double   temperature_c;
            double   humidity_rel;
        } weather;
    } payload;
} hc_event_t;
#endif /* HOLOCANVAS_EVENT_T_DEFINED */

/* -------------------------------------------------------------------------
 * cmocka link-time wrappers
 * -------------------------------------------------------------------------
 *
 * Production code calls `event_bus_publish` to fan-out events.  We override
 * it so we can assert parameters & frequency without touching the source.
 */

int __wrap_event_bus_publish(hc_event_bus_t *bus, const hc_event_t *ev)
{
    /* Push arguments into cmocka’s queue so individual tests can `expect_*`
     * and `assert_*` them. */
    check_expected_ptr(bus);
    check_expected_ptr(ev);

    /* For convenience, allow tests to inspect the full struct w/ a function
     * pointer comparator rather than field-by-field dance. */
    hc_event_t expected_event;
    memset(&expected_event, 0, sizeof(expected_event));
    memcpy(&expected_event, mock_ptr_type(const hc_event_t *), sizeof(hc_event_t));

    assert_memory_equal(ev, &expected_event, sizeof(hc_event_t));

    /* Pretend the publish succeeded. */
    return 0;
}

/* We do not need the real bus type for the tests — treat it as opaque. */
struct hc_event_bus { uint8_t _unused; };

/* Small helper to fabricate a dummy event bus instance. */
static hc_event_bus_t *make_dummy_bus(void)
{
    /* clang/gcc static analyzer will understand we only need its address. */
    static hc_event_bus_t dummy;
    memset(&dummy, 0, sizeof(dummy));
    return &dummy;
}

/* -------------------------------------------------------------------------
 * Test fixtures
 * ------------------------------------------------------------------------- */

static int test_setup(void **state)
{
    (void)state;
    /* Global init for Muse Observer if required.  For now, nothing. */
    return 0;
}

static int test_teardown(void **state)
{
    (void)state;
    return 0;
}

/* -------------------------------------------------------------------------
 * Unit-tests – LIKE trigger
 * ------------------------------------------------------------------------- */

/* Scenario:
 *   The NFT should evolve once likes >= threshold.
 */
static void test_like_trigger_should_evolve_on_threshold(void **state)
{
    (void)state;

    hc_event_bus_t *bus = make_dummy_bus();

    /* Incoming event that meets the threshold. */
    hc_event_t like_event = {
        .id   = "ev-like-0001",
        .type = EV_TYPE_LIKE,
        .payload.like = {
            .current_likes   = 500,
            .threshold_likes = 500
        }
    };

    /* Expected event the Muse Observer must publish. */
    hc_event_t expected_out = {
        .id   = "ev-nft-evolve-0001",
        .type = EV_TYPE_NFT_EVOLUTION
        /* payload intentionally left blank – the production layer will fill
         * evolution metadata downstream. */
    };

    /* Instruct cmocka what we expect to see. */
    expect_any(__wrap_event_bus_publish, bus);
    expect_any(__wrap_event_bus_publish, ev);
    will_return(__wrap_event_bus_publish, &expected_out);

    /* Run system-under-test. */
    int rc = muse_trigger_on_like(bus, &like_event);

    /* Validate return code path. */
    assert_int_equal(rc, MUSE_TRIGGER_FIRED);
}

/* Scenario:
 *   The NFT should NOT evolve when likes are below threshold.
 */
static void test_like_trigger_should_ignore_below_threshold(void **state)
{
    (void)state;
    hc_event_bus_t *bus = make_dummy_bus();

    hc_event_t like_event = {
        .id   = "ev-like-0002",
        .type = EV_TYPE_LIKE,
        .payload.like = {
            .current_likes   = 499,
            .threshold_likes = 500
        }
    };

    /* We expect *no* publish call, so don't set an expectation. */

    int rc = muse_trigger_on_like(bus, &like_event);

    assert_int_equal(rc, MUSE_TRIGGER_SKIPPED);
}

/* -------------------------------------------------------------------------
 * Unit-tests – Weather Oracle trigger
 * ------------------------------------------------------------------------- */

/* Scenario:
 *   If temperature drops below freezing, evolve NFT into “winter” edition.
 */
static void test_weather_trigger_freezing_temperature(void **state)
{
    (void)state;
    hc_event_bus_t *bus = make_dummy_bus();

    hc_event_t weather_event = {
        .id   = "ev-weather-0001",
        .type = EV_TYPE_ORACLE_WEATHER,
        .payload.weather = {
            .temperature_c = -5.3,
            .humidity_rel  = 80.0
        }
    };

    hc_event_t expected_out = {
        .id   = "ev-nft-winter-0001",
        .type = EV_TYPE_NFT_EVOLUTION
    };

    expect_any(__wrap_event_bus_publish, bus);
    expect_any(__wrap_event_bus_publish, ev);
    will_return(__wrap_event_bus_publish, &expected_out);

    int rc = muse_trigger_on_weather(bus, &weather_event);
    assert_int_equal(rc, MUSE_TRIGGER_FIRED);
}

/* Scenario:
 *   Mild temperature – no evolution should happen.
 */
static void test_weather_trigger_mild_temperature_noop(void **state)
{
    (void)state;
    hc_event_bus_t *bus = make_dummy_bus();

    hc_event_t weather_event = {
        .id   = "ev-weather-0002",
        .type = EV_TYPE_ORACLE_WEATHER,
        .payload.weather = {
            .temperature_c = 18.0,
            .humidity_rel  = 50.0
        }
    };

    int rc = muse_trigger_on_weather(bus, &weather_event);
    assert_int_equal(rc, MUSE_TRIGGER_SKIPPED);
}

/* -------------------------------------------------------------------------
 * Main driver
 * ------------------------------------------------------------------------- */

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test_setup_teardown(
            test_like_trigger_should_evolve_on_threshold,
            test_setup, test_teardown),
        cmocka_unit_test_setup_teardown(
            test_like_trigger_should_ignore_below_threshold,
            test_setup, test_teardown),
        cmocka_unit_test_setup_teardown(
            test_weather_trigger_freezing_temperature,
            test_setup, test_teardown),
        cmocka_unit_test_setup_teardown(
            test_weather_trigger_mild_temperature_noop,
            test_setup, test_teardown),
    };

    return cmocka_run_group_tests_name("Muse Observer – Trigger Suite",
                                       tests, NULL, NULL);
}
```