```c
/**
 * SynestheticCanvas - Palette Service Unit-Tests
 *
 * File: services/palette-service/tests/test_palette_service.c
 * Copyright (c) 2024  SynestheticCanvas
 *
 * These tests exercise the public surface of the palette-service module.
 * They are intended to be run with CMocka (`-lcmocka`) as part of the
 * continuous-integration pipeline.
 *
 * IMPORTANT:
 *   1. All assertions must stay environment-agnostic; no hard-coded
 *      filesystem paths or environment variables.
 *   2. The palette-service is expected to be linked in from the main build;
 *      only the public header is included here.
 */

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <cmocka.h>

#include <errno.h>
#include <pthread.h>
#include <string.h>

#include "palette_service.h"   /* Public API under test */

/* ---------- Test Helpers -------------------------------------------------- */

/* Convenience struct for thread-safety tests */
typedef struct {
    sc_palette_t *palette;
    uint8_t       r, g, b;
    float         weight;
    int           expected_errno;
} add_color_job_t;

static void *
thread_add_color(void *arg)
{
    add_color_job_t *job = (add_color_job_t *)arg;

    /* libc's errno can be thread-local; capture it manually for assertions. */
    int ret = palette_add_color(job->palette,
                                job->r, job->g, job->b,
                                job->weight);

    /* Store errno in weight (hacky but we know it is float) if needed */
    job->expected_errno = ret;
    return NULL;
}

/* Validate palette_get_color() returns the same values that were inserted */
static void
assert_color_equal(const sc_palette_t *palette,
                   size_t index,
                   uint8_t r, uint8_t g, uint8_t b,
                   float weight)
{
    uint8_t r_out, g_out, b_out;
    float   weight_out;

    assert_int_equal(palette_get_color(palette,
                                       index,
                                       &r_out, &g_out, &b_out,
                                       &weight_out), 0);

    assert_int_equal(r_out, r);
    assert_int_equal(g_out, g);
    assert_int_equal(b_out, b);
    assert_true(fabsf(weight_out - weight) < 0.0001f);
}

/* ---------- Unit-Tests ----------------------------------------------------- */

static void
test_palette_create_and_destroy(void **state)
{
    (void)state;

    sc_palette_t *p = palette_create("unittest-palette", 8);
    assert_non_null(p);
    assert_int_equal(palette_size(p), 0);

    palette_destroy(p);
}

static void
test_palette_add_and_get_color(void **state)
{
    (void)state;

    sc_palette_t *p = palette_create("rainbow", 3);
    assert_non_null(p);

    /* Insert three distinct colors */
    assert_int_equal(palette_add_color(p, 255, 0,   0, 1.0f), 0); /* Red   */
    assert_int_equal(palette_add_color(p, 0,   255, 0, 1.0f), 0); /* Green */
    assert_int_equal(palette_add_color(p, 0,   0,   255, 1.0f), 0); /* Blue */

    assert_int_equal(palette_size(p), 3);

    /* Verify order & values */
    assert_color_equal(p, 0, 255, 0,   0,   1.0f);
    assert_color_equal(p, 1, 0,   255, 0,   1.0f);
    assert_color_equal(p, 2, 0,   0,   255, 1.0f);

    /* Expect overflow on 4th insert */
    assert_int_equal(palette_add_color(p, 255, 255, 255, 1.0f), -ENOSPC);

    palette_destroy(p);
}

static void
test_palette_remove_color(void **state)
{
    (void)state;

    sc_palette_t *p = palette_create("eraser", 4);
    assert_non_null(p);

    palette_add_color(p, 10, 20, 30, 0.5f);
    palette_add_color(p, 40, 50, 60, 0.6f);
    palette_add_color(p, 70, 80, 90, 0.7f);

    assert_int_equal(palette_size(p), 3);

    /* Remove middle element */
    assert_int_equal(palette_remove_color(p, 1), 0);
    assert_int_equal(palette_size(p), 2);

    /* Remaining colors should have shifted */
    assert_color_equal(p, 0, 10, 20, 30, 0.5f);
    assert_color_equal(p, 1, 70, 80, 90, 0.7f);

    /* Out-of-bounds removal */
    assert_int_equal(palette_remove_color(p, 2), -EINVAL);

    palette_destroy(p);
}

static void
test_palette_serialize_json(void **state)
{
    (void)state;

    sc_palette_t *p = palette_create("json-test", 2);
    assert_non_null(p);

    palette_add_color(p, 1,   2,   3,   0.1f);
    palette_add_color(p, 254, 253, 252, 0.9f);

    char *json = palette_serialize_json(p);
    assert_non_null(json);

    /* Basic smoke-tests: ensure required fields are present */
    assert_non_null(strstr(json, "\"id\":\"json-test\""));
    assert_non_null(strstr(json, "\"colors\""));
    assert_non_null(strstr(json, "\"r\":1"));
    assert_non_null(strstr(json, "\"g\":2"));
    assert_non_null(strstr(json, "\"b\":3"));
    assert_non_null(strstr(json, "\"weight\":0.1"));
    assert_non_null(strstr(json, "\"r\":254"));

    free(json);
    palette_destroy(p);
}

static void
test_palette_thread_safety(void **state)
{
    (void)state;

    const size_t kThreadCount = 16;
    sc_palette_t *p           = palette_create("concurrency-pal", kThreadCount);
    assert_non_null(p);

    pthread_t       tids[kThreadCount];
    add_color_job_t jobs[kThreadCount];

    /* Spawn multiple threads writing concurrently */
    for (size_t i = 0; i < kThreadCount; ++i) {
        jobs[i].palette         = p;
        jobs[i].r               = (uint8_t)i;
        jobs[i].g               = (uint8_t)(255 - i);
        jobs[i].b               = (uint8_t)(i * 10);
        jobs[i].weight          = 1.0f;
        jobs[i].expected_errno  = 0;

        assert_int_equal(pthread_create(&tids[i],
                                        NULL,
                                        thread_add_color,
                                        &jobs[i]), 0);
    }

    /* Join all */
    for (size_t i = 0; i < kThreadCount; ++i)
        pthread_join(tids[i], NULL);

    /* All insertions should succeed, palette size == kThreadCount */
    assert_int_equal(palette_size(p), kThreadCount);

    palette_destroy(p);
}

static void
test_palette_null_guards(void **state)
{
    (void)state;

    /* Null pointer arguments should fail gracefully */
    uint8_t r, g, b;
    float   weight;

    assert_int_equal(palette_get_color(NULL, 0, &r, &g, &b, &weight), -EINVAL);
    assert_int_equal(palette_add_color(NULL, 0, 0, 0, 0.0f), -EINVAL);
    assert_int_equal(palette_remove_color(NULL, 0), -EINVAL);
    assert_int_equal(palette_size(NULL), 0);
    assert_null(palette_serialize_json(NULL));
}

/* ---------- Test Runner ---------------------------------------------------- */

int
main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_palette_create_and_destroy),
        cmocka_unit_test(test_palette_add_and_get_color),
        cmocka_unit_test(test_palette_remove_color),
        cmocka_unit_test(test_palette_serialize_json),
        cmocka_unit_test(test_palette_thread_safety),
        cmocka_unit_test(test_palette_null_guards),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
```