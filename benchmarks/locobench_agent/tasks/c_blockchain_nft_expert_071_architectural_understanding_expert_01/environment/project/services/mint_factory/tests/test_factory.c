/*
 * HoloCanvas – Mint-Factory Service
 * Unit-Tests (Check framework)
 *
 * File path: HoloCanvas/services/mint_factory/tests/test_factory.c
 *
 * These tests exercise the public surface of the Mint-Factory
 * micro-service: initialization, artifact minting, state-machine
 * transitions and basic concurrency safety.
 *
 * Compile example (with pkg-config):
 *   cc -Wall -Wextra -pedantic -pthread \
 *      $(pkg-config --cflags check) \
 *      -o test_factory test_factory.c \
 *      $(pkg-config --libs check) \
 *      -lmint_factory             # production object/lib
 *
 * Author: HoloCanvas Core Team
 * SPDX-License-Identifier: MIT
 */
#include <check.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

/* Production headers */
#include "mint_factory.h"     /* primary public header */
#include "mint_factory_events.h"
#include "mint_factory_types.h"

/*----------------------------------------------------------------------
 * Test-Helpers / Fixtures
 *--------------------------------------------------------------------*/
#define TEST_CONFIG_FILE  "tests/data/mint_factory_test.toml"
#define THREAD_COUNT      8
#define MINTS_PER_THREAD  32

static factory_t *g_factory = NULL;

/* Minimal helper to build an in-memory recipe.  Production code usually
 * acquires this via gRPC or REST, but for tests we craft it manually.   */
static recipe_t
test_build_recipe(const char *title, const char *shader, const char *audio)
{
    recipe_t r;
    memset(&r, 0, sizeof(r));

    strncpy(r.title,  title,  sizeof(r.title)  - 1);
    strncpy(r.shader, shader, sizeof(r.shader) - 1);
    strncpy(r.audio,  audio,  sizeof(r.audio)  - 1);

    /* For brevity we leave hash/author fields zeroed. */
    r.fragment_count = 2;
    r.fragments[0].type = FRAGMENT_SHADER;
    strncpy(r.fragments[0].path, shader, sizeof(r.fragments[0].path) - 1);
    r.fragments[1].type = FRAGMENT_AUDIO;
    strncpy(r.fragments[1].path, audio, sizeof(r.fragments[1].path)  - 1);

    return r;
}

/* -------------- Suite Fixture Hooks --------------------------------- */
static void
setup_factory(void)
{
    int rc = factory_init(TEST_CONFIG_FILE, &g_factory);
    ck_assert_msg(rc == FACTORY_OK, "factory_init() failed with %d", rc);
    ck_assert_ptr_nonnull(g_factory);
}

static void
teardown_factory(void)
{
    if (g_factory) {
        factory_destroy(g_factory);
        g_factory = NULL;
    }
}

/*----------------------------------------------------------------------
 * Tests: Initialization / Configuration
 *--------------------------------------------------------------------*/
START_TEST(test_factory_init_ok)
{
    /* The fixture already called factory_init() */
    ck_assert_ptr_nonnull(g_factory);
    ck_assert_uint_eq(factory_get_artifact_count(g_factory), 0U);
}
END_TEST

START_TEST(test_factory_init_bad_path)
{
    factory_t *fac = NULL;
    int rc = factory_init("/non/existent/file.toml", &fac);
    ck_assert_int_ne(rc, FACTORY_OK);
    ck_assert_ptr_null(fac);
}
END_TEST

/*----------------------------------------------------------------------
 * Tests: Artifact Minting
 *--------------------------------------------------------------------*/
START_TEST(test_mint_artifact_success)
{
    recipe_t recipe = test_build_recipe("Generative Sunrise",
                                        "assets/sunrise.frag",
                                        "assets/sunrise.wav");

    artifact_id_t id = 0;
    int rc = factory_mint_artifact(g_factory, &recipe, &id);
    ck_assert_int_eq(rc, FACTORY_OK);
    ck_assert_uint_gt(id, 0U);
    ck_assert_uint_eq(factory_get_artifact_count(g_factory), 1U);

    metadata_t meta = {0};
    rc = factory_get_metadata(g_factory, id, &meta);
    ck_assert_int_eq(rc, FACTORY_OK);
    ck_assert_str_eq(meta.title, "Generative Sunrise");
}
END_TEST

START_TEST(test_mint_duplicate_recipe)
{
    recipe_t recipe = test_build_recipe("Loop #1", "a.frag", "b.wav");

    artifact_id_t id1, id2;
    ck_assert_int_eq(factory_mint_artifact(g_factory, &recipe, &id1), FACTORY_OK);
    ck_assert_int_eq(factory_mint_artifact(g_factory, &recipe, &id2),
                     FACTORY_ERR_DUPLICATE_RECIPE);
    ck_assert_uint_eq(factory_get_artifact_count(g_factory), 1U);
}
END_TEST

/*----------------------------------------------------------------------
 * Tests: State-Machine Transitions
 *--------------------------------------------------------------------*/
START_TEST(test_state_transitions_valid)
{
    /* Mint first */
    recipe_t recipe = test_build_recipe("Transitional Piece", "t.frag", "t.wav");
    artifact_id_t id;
    ck_assert_int_eq(factory_mint_artifact(g_factory, &recipe, &id), FACTORY_OK);

    /* Transition: Draft -> Curated */
    factory_event_t ev_curate = {
        .type       = FACTORY_EVENT_CURATE,
        .artifact_id = id,
        .payload    = {0}
    };
    ck_assert_int_eq(factory_apply_event(g_factory, &ev_curate), FACTORY_OK);

    /* Transition: Curated -> Auction */
    factory_event_t ev_auction = {
        .type        = FACTORY_EVENT_START_AUCTION,
        .artifact_id = id,
        .payload     = { .reserve_price = 10_000 } /* 0.0001 ETH for tests */
    };
    ck_assert_int_eq(factory_apply_event(g_factory, &ev_auction), FACTORY_OK);

    /* Verify */
    artifact_state_t state = factory_get_state(g_factory, id);
    ck_assert_int_eq(state, ARTIFACT_STATE_AUCTION);
}
END_TEST

START_TEST(test_state_transition_invalid)
{
    recipe_t recipe = test_build_recipe("Broken State", "broken.frag", "broken.wav");
    artifact_id_t id;
    ck_assert_int_eq(factory_mint_artifact(g_factory, &recipe, &id), FACTORY_OK);

    /* Attempt invalid transition: Draft -> Staked (skips steps) */
    factory_event_t bad_ev = {
        .type        = FACTORY_EVENT_STAKE,
        .artifact_id = id,
        .payload     = { .stake_amount = 1_000 }
    };
    ck_assert_int_eq(factory_apply_event(g_factory, &bad_ev),
                     FACTORY_ERR_INVALID_STATE);
}
END_TEST

/*----------------------------------------------------------------------
 * Tests: Concurrency – multi-threaded minting
 *--------------------------------------------------------------------*/
struct thread_ctx {
    factory_t *factory;
    int        mints;
};

static void *
mint_worker(void *arg)
{
    struct thread_ctx *ctx = arg;
    for (int i = 0; i < ctx->mints; ++i) {
        char title[32];
        snprintf(title, sizeof(title), "Auto #%d", i);

        recipe_t r = test_build_recipe(title, "auto.frag", "auto.wav");
        artifact_id_t id;
        /* Ignore duplicates because recipe differs per iteration */
        if (factory_mint_artifact(ctx->factory, &r, &id) != FACTORY_OK) {
            /* Should never happen, but don't crash the thread */
            pthread_exit((void *)1);
        }
    }
    return NULL;
}

START_TEST(test_concurrent_minting)
{
    pthread_t   th[THREAD_COUNT];
    struct thread_ctx ctx = {
        .factory = g_factory,
        .mints   = MINTS_PER_THREAD
    };

    /* Spawn */
    for (int i = 0; i < THREAD_COUNT; ++i)
        ck_assert_int_eq(pthread_create(&th[i], NULL, mint_worker, &ctx), 0);

    /* Join */
    for (int i = 0; i < THREAD_COUNT; ++i) {
        void *ret;
        ck_assert_int_eq(pthread_join(th[i], &ret), 0);
        ck_assert_ptr_eq(ret, NULL); /* worker returned NULL on success */
    }

    unsigned expected = THREAD_COUNT * MINTS_PER_THREAD;
    ck_assert_uint_eq(factory_get_artifact_count(g_factory), expected);
}
END_TEST

/*----------------------------------------------------------------------
 * Suite / Runner
 *--------------------------------------------------------------------*/
static Suite *
factory_suite(void)
{
    Suite *s  = suite_create("Mint-Factory");

    /* Core group ------------------------------------------------------ */
    TCase *tc_core = tcase_create("Core");
    tcase_add_checked_fixture(tc_core, setup_factory, teardown_factory);
    tcase_set_timeout(tc_core, 10);

    tcase_add_test(tc_core, test_factory_init_ok);
    tcase_add_test(tc_core, test_mint_artifact_success);
    tcase_add_test(tc_core, test_mint_duplicate_recipe);
    tcase_add_test(tc_core, test_state_transitions_valid);
    tcase_add_test(tc_core, test_state_transition_invalid);
    tcase_add_test(tc_core, test_concurrent_minting);

    suite_add_tcase(s, tc_core);

    /* Negative-path tests without fixture ----------------------------- */
    TCase *tc_cfg = tcase_create("Config");
    tcase_add_test(tc_cfg, test_factory_init_bad_path);
    suite_add_tcase(s, tc_cfg);

    return s;
}

int
main(void)
{
    Suite   *s  = factory_suite();
    SRunner *sr = srunner_create(s);

    /* Run all */
    srunner_run_all(sr, CK_NORMAL);

    int failed = srunner_ntests_failed(sr);
    srunner_free(sr);
    return (failed == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}