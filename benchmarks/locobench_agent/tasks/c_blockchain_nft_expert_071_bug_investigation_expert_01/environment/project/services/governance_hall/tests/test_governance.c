```c
/**
 * HoloCanvas :: Governance-Hall
 * Unit-Tests for the on-chain governance engine.
 *
 * File: services/governance_hall/tests/test_governance.c
 *
 * These tests exercise the public governance API, validate
 * quorum / threshold logic and make sure that events are published
 * at the right moments (proposal creation, finalisation, execution).
 *
 * Build:
 *   gcc -I../../include -I. \
 *       -o test_governance \
 *       test_governance.c \
 *       -lcmocka
 */

#define _POSIX_C_SOURCE 200809L

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>

#include <cmocka.h>

/* ──────────────────────────────────────────────────────────
 * Governance-Hall public header.
 * In the real tree this would be:  #include "governance.h"
 * For the purpose of unit-tests we embed a subset of the API
 * so the test suite stays self-contained and compilable.
 * ────────────────────────────────────────────────────────── */
#ifndef HOLOCANVAS_GOVERNANCE_H
#define HOLOCANVAS_GOVERNANCE_H

/* ---------- domain objects ---------- */

typedef uint64_t proposal_id_t;
typedef uint64_t block_height_t;
typedef uint64_t wallet_id_t;

typedef enum {
    VOTE_YES = 0,
    VOTE_NO,
    VOTE_ABSTAIN
} vote_t;

typedef enum {
    PSTATE_DRAFT    = 0,
    PSTATE_ACTIVE,
    PSTATE_PASSED,
    PSTATE_REJECTED,
    PSTATE_EXECUTED
} proposal_state_t;

typedef struct {
    proposal_id_t  id;
    char           title[96];
    char           description[256];
    uint32_t       quorum;           /* minimum votes required          */
    uint32_t       threshold_pct;    /* % of YES over total to pass     */
    uint32_t       votes_yes;
    uint32_t       votes_no;
    uint32_t       votes_abstain;
    block_height_t start_block;
    block_height_t end_block;
    proposal_state_t state;
} proposal_t;

typedef struct governance_ctx governance_ctx_t;

/* ---------- public API (subset) ---------- */
governance_ctx_t* governance_create_ctx(uint32_t default_quorum,
                                        uint32_t default_threshold_pct);

void governance_destroy_ctx(governance_ctx_t *ctx);

int governance_submit_proposal(governance_ctx_t *ctx,
                               const char *title,
                               const char *description,
                               proposal_id_t *out_id);

int governance_cast_vote(governance_ctx_t *ctx,
                         proposal_id_t     pid,
                         wallet_id_t       voter,
                         vote_t            vote);

int governance_finalize_proposal(governance_ctx_t *ctx,
                                 proposal_id_t pid,
                                 proposal_state_t *out_state);

int governance_execute_proposal(governance_ctx_t *ctx,
                                proposal_id_t pid);

/* Error codes */
#define GOV_SUCCESS             0
#define GOV_ERR_INVALID_ID     -1
#define GOV_ERR_DUP_VOTE       -2
#define GOV_ERR_NOT_ACTIVE     -3
#define GOV_ERR_ALREADY_FIN    -4
#define GOV_ERR_QUORUM         -5
#define GOV_ERR_NOT_PASSED     -6
#define GOV_ERR_ALREADY_EXEC   -7

#endif /* HOLOCANVAS_GOVERNANCE_H */
/* ────────────────────────────────────────────────────────── */

/* -------------
/// MOCKS for external collaborators (Event-Bus, Ledger, etc.)
 *
 *  The real implementation of governance_hall publishes events
 *  to an internal event bus and validates voters through the
 *  ledger micro-service.  We provide lightweight mocks so we can
 *  assert interactions without dragging the entire dependency
 *  graph into the test binary.
 * ----------------------------------------------------------- */

/* event_bus_publish(topic, payload, len) */
int __wrap_event_bus_publish(const char *topic,
                             const void *payload,
                             size_t len)
{
    check_expected_ptr(topic);
    check_expected(payload != NULL);
    check_expected(len > 0);
    return mock_type(int);
}

/* ledger_wallet_exists(wallet_id) */
bool __wrap_ledger_wallet_exists(wallet_id_t wid)
{
    /* For tests we assume every wallet < 1'000'000 exists */
    return wid < 1000000ULL;
}

/* ──────────────────────────────────────────────────────────
 * Helper functions shared by test cases.
 * ────────────────────────────────────────────────────────── */

/* Generate pseudo-random wallet IDs for test-data reproducibility */
static wallet_id_t
rnd_wallet(void)
{
    static uint64_t seed = 0xC0FFEEDDULL;
    seed = seed * 6364136223846793005ULL + 1;
    return (wallet_id_t)(seed % 999999);
}

/* Cast a bulk of YES votes on a proposal */
static void
cast_yes_votes(governance_ctx_t *ctx,
               proposal_id_t pid,
               uint32_t count)
{
    for (uint32_t i = 0; i < count; ++i) {
        wallet_id_t wid = rnd_wallet();
        int rc = governance_cast_vote(ctx, pid, wid, VOTE_YES);
        assert_int_equal(rc, GOV_SUCCESS);
    }
}

/* ──────────────────────────────────────────────────────────
 *  Test-Cases
 * ────────────────────────────────────────────────────────── */

/* Make sure a newly created proposal is in expected default state. */
static void
test_submit_proposal(void **state)
{
    (void)state;
    governance_ctx_t *ctx = governance_create_ctx(/*quorum*/10, /*threshold*/60);
    assert_non_null(ctx);

    proposal_id_t pid;
    int rc = governance_submit_proposal(ctx,
                                        "Upgrade Render Shader",
                                        "Switch to ray-marching pipeline.",
                                        &pid);
    assert_int_equal(rc, GOV_SUCCESS);
    assert_true(pid > 0);

    /* Finalise context */
    governance_destroy_ctx(ctx);
}

/* Validate duplicate voting protection. */
static void
test_duplicate_vote_rejected(void **state)
{
    (void)state;
    governance_ctx_t *ctx = governance_create_ctx(5, 51);
    proposal_id_t pid;
    governance_submit_proposal(ctx,
                               "Add Weather Oracle",
                               "Incorporate live weather patterns.",
                               &pid);

    wallet_id_t voter = rnd_wallet();
    assert_int_equal(governance_cast_vote(ctx, pid, voter, VOTE_NO), GOV_SUCCESS);
    /* Second vote from same wallet should fail */
    assert_int_equal(governance_cast_vote(ctx, pid, voter, VOTE_YES), GOV_ERR_DUP_VOTE);

    governance_destroy_ctx(ctx);
}

/* Proposal with insufficient quorum must be rejected when finalised. */
static void
test_quorum_failure(void **state)
{
    (void)state;
    governance_ctx_t *ctx = governance_create_ctx(/*quorum*/3, 60);
    proposal_id_t pid;
    governance_submit_proposal(ctx, "Tiny Proposal", "Test quorum failure", &pid);

    /* Only 2 votes, quorum = 3 */
    cast_yes_votes(ctx, pid, 2);

    proposal_state_t st;
    assert_int_equal(governance_finalize_proposal(ctx, pid, &st), GOV_ERR_QUORUM);
    assert_int_equal(st, PSTATE_REJECTED);

    governance_destroy_ctx(ctx);
}

/* Happy path: Proposal passes quorum and threshold, then is executed. */
static void
test_proposal_lifecycle_pass_and_execute(void **state)
{
    (void)state;
    governance_ctx_t *ctx = governance_create_ctx(/*quorum*/5, /*threshold*/67);
    proposal_id_t pid;
    governance_submit_proposal(ctx,
                               "Enable Fractionalization",
                               "Let collectors own fractions of NFTs.",
                               &pid);

    /* 6 YES, 1 NO  ->  YES% = 85.7, votes = 7 ≥ quorum */
    cast_yes_votes(ctx, pid, 6);
    governance_cast_vote(ctx, pid, rnd_wallet(), VOTE_NO);

    /* Expect event-bus to be notified on finalisation */
    expect_string(__wrap_event_bus_publish, topic, "governance/proposal/finalised");
    expect_value(__wrap_event_bus_publish, payload != NULL, true);
    expect_value(__wrap_event_bus_publish, len > 0, true);
    will_return(__wrap_event_bus_publish, 0);

    proposal_state_t st;
    assert_int_equal(governance_finalize_proposal(ctx, pid, &st), GOV_SUCCESS);
    assert_int_equal(st, PSTATE_PASSED);

    /* Execution should also publish an event */
    expect_string(__wrap_event_bus_publish, topic, "governance/proposal/executed");
    expect_value(__wrap_event_bus_publish, payload != NULL, true);
    expect_value(__wrap_event_bus_publish, len > 0, true);
    will_return(__wrap_event_bus_publish, 0);

    assert_int_equal(governance_execute_proposal(ctx, pid), GOV_SUCCESS);

    /* Second execution attempt must fail */
    assert_int_equal(governance_execute_proposal(ctx, pid), GOV_ERR_ALREADY_EXEC);

    governance_destroy_ctx(ctx);
}

/* Finalising a non-existent proposal should error out */
static void
test_invalid_proposal_id(void **state)
{
    (void)state;
    governance_ctx_t *ctx = governance_create_ctx(3, 50);

    proposal_state_t st = PSTATE_DRAFT;
    assert_int_equal(governance_finalize_proposal(ctx, /*invalid id*/9999, &st),
                     GOV_ERR_INVALID_ID);
    assert_int_equal(st, PSTATE_DRAFT);

    governance_destroy_ctx(ctx);
}

/* ----------------------------------------------------------------------
 *  main()
 * ---------------------------------------------------------------------- */
int
main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_submit_proposal),
        cmocka_unit_test(test_duplicate_vote_rejected),
        cmocka_unit_test(test_quorum_failure),
        cmocka_unit_test(test_proposal_lifecycle_pass_and_execute),
        cmocka_unit_test(test_invalid_proposal_id),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
```