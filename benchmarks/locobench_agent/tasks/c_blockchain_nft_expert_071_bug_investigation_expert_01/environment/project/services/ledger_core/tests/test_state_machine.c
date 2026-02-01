/*
 * File:    HoloCanvas/services/ledger_core/tests/test_state_machine.c
 * Project: HoloCanvas – Ledger-Core
 *
 * Unit-tests for the Ledger-Core artifact state-machine.
 * Uses the CMocka framework: https://cmocka.org/
 *
 * Compile example:
 *   gcc -std=c11 -Wall -Wextra -Werror \
 *       -I../include -L/usr/lib \
 *       -lcmocka -lpthread \
 *       ../src/state_machine.c test_state_machine.c -o test_state_machine
 */

#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include <cmocka.h>

#include "ledger_core/state_machine.h"   /* Production header */

/* --------------------------------------------------------------------------
 *  Helpers
 * -------------------------------------------------------------------------- */

/* Context wrapper passed to each test instance */
typedef struct {
    artifact_sm_t sm;
} sm_fixture_t;

/* Common set-up: initialize the state-machine to STATE_DRAFT. */
static int sm_setup(void **state)
{
    sm_fixture_t *fx = malloc(sizeof(*fx));
    if (!fx) {
        return -1;
    }

    int rc = sm_init(&fx->sm);
    if (rc != 0) {
        free(fx);
        return -1;
    }

    *state = fx;
    return 0;
}

/* Common tear-down: free fixture memory. */
static int sm_teardown(void **state)
{
    sm_fixture_t *fx = *state;
    sm_destroy(&fx->sm);    /* In case the SM reserves resources */
    free(fx);
    return 0;
}

/* --------------------------------------------------------------------------
 *  Positive transition tests
 * -------------------------------------------------------------------------- */

/* Draft → Curated */
static void test_transition_draft_to_curated(void **state)
{
    sm_fixture_t *fx = *state;

    assert_int_equal(STATE_DRAFT, sm_get_state(&fx->sm));
    assert_int_equal(0, sm_apply_event(&fx->sm, EVT_SUBMIT_FOR_CURATION));
    assert_int_equal(STATE_CURATED, sm_get_state(&fx->sm));
}

/* Full happy-path life-cycle */
static void test_full_lifecycle(void **state)
{
    sm_fixture_t *fx = *state;

    const artifact_event_t path[] = {
        EVT_SUBMIT_FOR_CURATION,   /* Draft → Curated  */
        EVT_START_AUCTION,         /* Curated → Auction */
        EVT_COMPLETE_AUCTION,      /* Auction → Won     */
        EVT_FRACTIONALIZE,         /* Won → Fractionalized */
        EVT_STAKE                  /* Fractionalized → Staked */
    };

    for (size_t i = 0; i < sizeof(path) / sizeof(path[0]); ++i) {
        assert_int_equal(0, sm_apply_event(&fx->sm, path[i]));
    }

    assert_int_equal(STATE_STAKED, sm_get_state(&fx->sm));
}

/* --------------------------------------------------------------------------
 *  Negative transition tests
 * -------------------------------------------------------------------------- */

/* Attempt an illegal jump directly from Draft → Auction */
static void test_invalid_transition(void **state)
{
    sm_fixture_t *fx = *state;

    assert_int_equal(-1, sm_apply_event(&fx->sm, EVT_START_AUCTION));
    /* State must stay unchanged */
    assert_int_equal(STATE_DRAFT, sm_get_state(&fx->sm));
}

/* Redundant event in the same state (idempotency) */
static void test_redundant_event(void **state)
{
    sm_fixture_t *fx = *state;

    assert_int_equal(0, sm_apply_event(&fx->sm, EVT_SUBMIT_FOR_CURATION));
    /* Second attempt should fail because already curated */
    assert_int_equal(-1, sm_apply_event(&fx->sm, EVT_SUBMIT_FOR_CURATION));
    assert_int_equal(STATE_CURATED, sm_get_state(&fx->sm));
}

/* --------------------------------------------------------------------------
 *  Concurrency / thread-safety test
 * -------------------------------------------------------------------------- */

typedef struct {
    sm_fixture_t *fx;
    atomic_int *success_ctr;
} thread_ctx_t;

static void *submit_for_curation_thread(void *arg)
{
    thread_ctx_t *tctx = arg;
    if (sm_apply_event(&tctx->fx->sm, EVT_SUBMIT_FOR_CURATION) == 0) {
        atomic_fetch_add(tctx->success_ctr, 1);
    }
    return NULL;
}

/* Verify that only one thread is able to perform Draft → Curated */
static void test_thread_safety_first_transition(void **state)
{
    enum { THREAD_COUNT = 10 };
    sm_fixture_t *fx = *state;
    pthread_t threads[THREAD_COUNT];
    atomic_int success_ctr = 0;
    thread_ctx_t tctx = { .fx = fx, .success_ctr = &success_ctr };

    for (int i = 0; i < THREAD_COUNT; ++i) {
        assert_int_equal(0, pthread_create(&threads[i], NULL,
                                           submit_for_curation_thread, &tctx));
    }

    for (int i = 0; i < THREAD_COUNT; ++i) {
        pthread_join(threads[i], NULL);
    }

    /* Exactly one thread should have succeeded */
    assert_int_equal(1, atomic_load(&success_ctr));
    assert_int_equal(STATE_CURATED, sm_get_state(&fx->sm));
}

/* --------------------------------------------------------------------------
 *  Test runner
 * -------------------------------------------------------------------------- */

int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test_setup_teardown(
            test_transition_draft_to_curated, sm_setup, sm_teardown),

        cmocka_unit_test_setup_teardown(
            test_full_lifecycle, sm_setup, sm_teardown),

        cmocka_unit_test_setup_teardown(
            test_invalid_transition, sm_setup, sm_teardown),

        cmocka_unit_test_setup_teardown(
            test_redundant_event, sm_setup, sm_teardown),

        cmocka_unit_test_setup_teardown(
            test_thread_safety_first_transition, sm_setup, sm_teardown),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}