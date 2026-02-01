```c
/**
 * HoloCanvas :: DeFi-Garden
 * Unit-tests for on-chain NFT staking pools.
 *
 * File path: services/defi_garden/tests/test_staking.c
 *
 * The test-suite relies on the CMocka framework
 * (https://cmocka.org) and exercises the public
 * staking-pool API exported by defi_garden/staking.h.
 *
 * $ cc -o tests/staking_test \
 *       -I../include -DUNIT_TESTING \
 *       services/defi_garden/tests/test_staking.c \
 *       -lcmocka -ldefi_garden
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <cmocka.h>

/* ------------------------------------------------------------------------- */
/*  External API (from services/defi_garden/include/defi_garden/staking.h)   */
/* ------------------------------------------------------------------------- */
typedef struct staking_pool staking_pool_t;

int  staking_pool_init(staking_pool_t       *pool,
                       const char           *owner_addr,
                       const char           *reward_token,
                       uint64_t              reward_rate_per_block);

int  staking_pool_deposit(staking_pool_t     *pool,
                          const char         *user_addr,
                          uint64_t            amount);

int  staking_pool_withdraw(staking_pool_t    *pool,
                           const char        *user_addr,
                           uint64_t           amount);

int  staking_pool_distribute_rewards(staking_pool_t *pool,
                                     uint64_t        current_block_height);

int  staking_pool_set_reward_rate(staking_pool_t     *pool,
                                  const char         *caller_addr,
                                  uint64_t            new_rate);

uint64_t staking_pool_user_balance(const staking_pool_t *pool,
                                   const char           *user_addr);

uint64_t staking_pool_user_rewards(const staking_pool_t *pool,
                                   const char           *user_addr);

uint64_t staking_pool_total_staked(const staking_pool_t *pool);

/* ------------------------------------------------------------------------- */
/*  Test fixtures                                                            */
/* ------------------------------------------------------------------------- */

static int setup_pool(void **state)
{
    static staking_pool_t pool; /* Static to survive between setup/teardown */
    const char *owner  = "0xDEADBEEFCAFEBABE000000000000000000000001";
    const char *reward = "HOLO";          /* Governance-token symbol        */
    const uint64_t reward_rate = 50;      /* 50 HOLO / block                */

    int rc = staking_pool_init(&pool, owner, reward, reward_rate);
    assert_int_equal(rc, 0);

    *state = &pool;
    return 0;
}

static int teardown_pool(void **state)
{
    (void)state;
    /* The pool lives in static storage; nothing to free. */
    return 0;
}

/* ------------------------------------------------------------------------- */
/*  Helper macros / constants                                                */
/* ------------------------------------------------------------------------- */

#define ALICE "0x1111111111111111111111111111111111111111"
#define BOB   "0x2222222222222222222222222222222222222222"
#define CAROL "0x3333333333333333333333333333333333333333"
#define OWNER "0xDEADBEEFCAFEBABE000000000000000000000001"

/* ------------------------------------------------------------------------- */
/*  Individual unit-tests                                                    */
/* ------------------------------------------------------------------------- */

/* 1. Pool initializes correctly. */
static void test_pool_initialization(void **state)
{
    staking_pool_t *pool = * (staking_pool_t **) state;
    assert_non_null(pool);

    /* Immediately after init there should be nothing staked
     * and no rewards owed to anyone. */
    assert_int_equal(staking_pool_total_staked(pool), 0);
    assert_int_equal(staking_pool_user_balance(pool, ALICE), 0);
    assert_int_equal(staking_pool_user_rewards(pool,  ALICE), 0);
}

/* 2. Single user deposit should update balance & total supply. */
static void test_single_deposit(void **state)
{
    staking_pool_t *pool = * (staking_pool_t **) state;
    const uint64_t amount = 1'000;        /* 1000 wei-equivalent            */

    assert_int_equal(staking_pool_deposit(pool, ALICE, amount), 0);

    assert_int_equal(staking_pool_user_balance(pool, ALICE), amount);
    assert_int_equal(staking_pool_total_staked(pool),        amount);
}

/* 3. Multiple users deposit and we accrue rewards over N blocks. */
static void test_multi_deposit_and_reward_distribution(void **state)
{
    staking_pool_t *pool = *(staking_pool_t **)state;

    /* Deposits */
    assert_int_equal(staking_pool_deposit(pool, ALICE, 1'000), 0);
    assert_int_equal(staking_pool_deposit(pool, BOB,   3'000), 0);
    assert_int_equal(staking_pool_deposit(pool, CAROL, 2'000), 0);

    /* Advance blockchain by 10 blocks */
    const uint64_t current_block_height = 1000;
    assert_int_equal(staking_pool_distribute_rewards(pool, current_block_height), 0);

    const uint64_t reward_rate = 50;          /* from setup fixture          */
    const uint64_t blocks_elapsed = current_block_height; /* fudge: init at 0  */
    const uint64_t total_reward = reward_rate * blocks_elapsed;

    /* Expected proportional rewards */
    uint64_t total_staked = 1'000 + 3'000 + 2'000; /* = 6000 */
    uint64_t expected_alice = total_reward * 1'000 / total_staked;
    uint64_t expected_bob   = total_reward * 3'000 / total_staked;
    uint64_t expected_carol = total_reward * 2'000 / total_staked;

    assert_int_equal(staking_pool_user_rewards(pool, ALICE), expected_alice);
    assert_int_equal(staking_pool_user_rewards(pool, BOB),   expected_bob);
    assert_int_equal(staking_pool_user_rewards(pool, CAROL), expected_carol);
}

/* 4. Withdraw reduces stake and keeps accounting intact. */
static void test_withdraw(void **state)
{
    staking_pool_t *pool = *(staking_pool_t **)state;

    assert_int_equal(staking_pool_deposit(pool, ALICE, 5'000), 0);

    uint64_t before = staking_pool_user_balance(pool, ALICE);
    assert_true(before == 5'000);

    /* Partial withdraw */
    assert_int_equal(staking_pool_withdraw(pool, ALICE, 1'500), 0);
    uint64_t after = staking_pool_user_balance(pool, ALICE);
    assert_int_equal(after, 3'500);

    /* Total staked decreased as well */
    uint64_t total = staking_pool_total_staked(pool);
    assert_int_equal(total, 3'500);
}

/* 5. Attempt to over-withdraw returns an error and leaves state unchanged. */
static void test_over_withdraw(void **state)
{
    staking_pool_t *pool = *(staking_pool_t **)state;

    assert_int_equal(staking_pool_deposit(pool, BOB, 800), 0);
    assert_int_equal(staking_pool_user_balance(pool, BOB), 800);

    /* Expect failure (e.g., -1) */
    assert_int_equal(staking_pool_withdraw(pool, BOB, 1'000), -1);
    /* Balance must remain unchanged */
    assert_int_equal(staking_pool_user_balance(pool, BOB), 800);
}

/* 6. Only pool owner may change reward-rate. */
static void test_authorisation_on_reward_rate_change(void **state)
{
    staking_pool_t *pool = *(staking_pool_t **)state;

    /* Non-owner tries to change reward rate — should fail */
    assert_int_equal(staking_pool_set_reward_rate(pool, BOB, 777), -1);

    /* Owner succeeds */
    assert_int_equal(staking_pool_set_reward_rate(pool, OWNER, 777), 0);
}

/* ------------------------------------------------------------------------- */
/*  Test-runner                                                              */
/* ------------------------------------------------------------------------- */
int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test_setup_teardown(test_pool_initialization,
                                        setup_pool, teardown_pool),
        cmocka_unit_test_setup_teardown(test_single_deposit,
                                        setup_pool, teardown_pool),
        cmocka_unit_test_setup_teardown(test_multi_deposit_and_reward_distribution,
                                        setup_pool, teardown_pool),
        cmocka_unit_test_setup_teardown(test_withdraw,
                                        setup_pool, teardown_pool),
        cmocka_unit_test_setup_teardown(test_over_withdraw,
                                        setup_pool, teardown_pool),
        cmocka_unit_test_setup_teardown(test_authorisation_on_reward_rate_change,
                                        setup_pool, teardown_pool),
    };

    return cmocka_run_group_tests(tests, NULL, NULL);
}
```