```c
/*
 * test_texture_service.c
 * ---------------------------------
 * Unit–integration test-suite for the SynestheticCanvas Texture-Service.
 *
 * This file exercises the public surface of `texture_service.h`, validating
 * that generated textures meet the documented contract, that error-paths
 * behave deterministically, and that JSON serialization remains stable
 * across schema versions.
 *
 * Compile example (assuming pkg-config):
 *     cc -o test_texture_service \
 *        $(pkg-config --cflags cmocka cjson) \
 *        test_texture_service.c \
 *        -ltexture_service \
 *        $(pkg-config --libs cmocka cjson)
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <pthread.h>

#include <cmocka.h>
#include <cjson/cJSON.h>          /* JSON verification */

/* Public interface -------------------------------------------------------- */
#include "texture_service.h"       /* Production header (to be provided by the service) */

/* ------------------------------------------------------------------------- */
/* Helper utilities                                                          */
/* ------------------------------------------------------------------------- */

/* Extracts an integer value from a cJSON object and asserts its presence. */
static int
json_get_int(const cJSON *parent, const char *key)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(parent, key);
    assert_non_null(item);
    assert_true(cJSON_IsNumber(item));
    return item->valueint;
}

/* Returns the number of occurrences of `needle` inside `haystack`. */
static size_t
substr_count(const char *haystack, const char *needle)
{
    size_t count = 0;
    const char *pos = haystack;

    while ((pos = strstr(pos, needle)) != NULL) {
        ++count;
        pos += strlen(needle);
    }
    return count;
}

/* ------------------------------------------------------------------------- */
/* Positive path tests                                                       */
/* ------------------------------------------------------------------------- */

static void
test_generate_texture_success(void **state)
{
    (void)state; /* Unused */

    /* GIVEN a valid procedural pattern */
    const char *pattern     = "PerlinNoise";
    const uint32_t seed     = 42;
    const char *palette_id  = "retro-neon";

    char *error = NULL;

    /* WHEN generating a texture */
    texture_t *tex = texture_service_generate_texture(pattern, seed, palette_id, &error);

    /* THEN a non-NULL handle is returned and no error is set */
    assert_non_null(tex);
    assert_null(error);

    /* AND texture dimensions must be within documented bounds */
    assert_in_range(tex->width,  16u, 4096u);
    assert_in_range(tex->height, 16u, 4096u);

    /* AND pixel buffer length must equal width × height × 4 (RGBA) */
    assert_non_null(tex->pixels);
    const size_t expected_len = tex->width * tex->height * 4;
    assert_int_equal(expected_len, texture_service_texture_size(tex));

    /* Clean-up */
    texture_service_free_texture(tex);
}

static void
test_texture_serialization_roundtrip(void **state)
{
    (void)state;

    const char *pattern = "Voronoi";
    char *error = NULL;

    texture_t *tex = texture_service_generate_texture(pattern, 7, "pastel-rain", &error);
    assert_non_null(tex);
    assert_null(error);

    /* WHEN serializing the texture to JSON */
    char *json_blob = texture_service_serialize_texture(tex, &error);
    assert_non_null(json_blob);
    assert_null(error);

    /* THEN the JSON must contain required keys exactly once */
    assert_int_equal(1, substr_count(json_blob, "\"id\""));
    assert_int_equal(1, substr_count(json_blob, "\"width\""));
    assert_int_equal(1, substr_count(json_blob, "\"height\""));

    /* AND numeric fields must match the texture */
    cJSON *root = cJSON_Parse(json_blob);
    assert_non_null(root);

    assert_int_equal((int)tex->width,  json_get_int(root, "width"));
    assert_int_equal((int)tex->height, json_get_int(root, "height"));

    /* Clean-up */
    cJSON_Delete(root);
    free(json_blob);
    texture_service_free_texture(tex);
}

/* ------------------------------------------------------------------------- */
/* Negative / error-path tests                                               */
/* ------------------------------------------------------------------------- */

static void
test_generate_texture_invalid_pattern(void **state)
{
    (void)state;

    const char *invalid_pattern = "⛔️NotARealAlgorithm⛔️";
    char *error = NULL;

    texture_t *tex = texture_service_generate_texture(invalid_pattern, 0, NULL, &error);

    /* THEN the service must fail gracefully with a helpful message */
    assert_null(tex);
    assert_non_null(error);
    assert_string_equal(error, "Unsupported pattern: ⛔️NotARealAlgorithm⛔️");

    free(error);
}

static void
test_serialize_texture_null_input(void **state)
{
    (void)state;
    char *error = NULL;

    /* WHEN passing a NULL texture to serializer */
    char *blob = texture_service_serialize_texture(NULL, &error);

    /* THEN serialization must fail with a deterministic error */
    assert_null(blob);
    assert_non_null(error);
    assert_string_equal(error, "texture pointer may not be NULL");

    free(error);
}

/* ------------------------------------------------------------------------- */
/* Concurrency / thread-safety tests                                         */
/* ------------------------------------------------------------------------- */

typedef struct {
    const char *pattern;
    texture_t *out_texture;
    char *out_error;
} worker_ctx_t;

static void *
worker_generate(void *arg)
{
    worker_ctx_t *ctx = arg;
    ctx->out_texture = texture_service_generate_texture(ctx->pattern,
                                                        (uint32_t)pthread_self(),
                                                        "mono-ink",
                                                        &ctx->out_error);
    return NULL;
}

#define THREAD_COUNT 8

static void
test_thread_safety(void **state)
{
    (void)state;

    pthread_t threads[THREAD_COUNT];
    worker_ctx_t contexts[THREAD_COUNT] = {0};

    /* Spawn multiple generators in parallel */
    for (size_t i = 0; i < THREAD_COUNT; ++i) {
        contexts[i].pattern = (i % 2 == 0) ? "PerlinNoise" : "Voronoi";
        assert_int_equal(0, pthread_create(&threads[i], NULL, worker_generate, &contexts[i]));
    }

    /* Wait for all threads and evaluate results */
    for (size_t i = 0; i < THREAD_COUNT; ++i) {
        pthread_join(threads[i], NULL);

        assert_non_null(contexts[i].out_texture);
        assert_null(contexts[i].out_error);

        /* Basic sanity: unique IDs */
        for (size_t j = 0; j < i; ++j) {
            assert_string_not_equal(contexts[i].out_texture->id,
                                    contexts[j].out_texture->id);
        }
    }

    /* Clean-up */
    for (size_t i = 0; i < THREAD_COUNT; ++i) {
        texture_service_free_texture(contexts[i].out_texture);
    }
}

/* ------------------------------------------------------------------------- */
/* Test runner                                                               */
/* ------------------------------------------------------------------------- */

int
main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_generate_texture_success),
        cmocka_unit_test(test_texture_serialization_roundtrip),
        cmocka_unit_test(test_generate_texture_invalid_pattern),
        cmocka_unit_test(test_serialize_texture_null_input),
        cmocka_unit_test(test_thread_safety),
    };

    /* Enable leak checking for supported builds.  */
#if defined(__has_feature)
#  if __has_feature(address_sanitizer)
    puts("[Info] Running under AddressSanitizer – memory leaks will abort the test-run.");
#  endif
#endif

    return cmocka_run_group_tests_name("texture-service", tests, NULL, NULL);
}
```