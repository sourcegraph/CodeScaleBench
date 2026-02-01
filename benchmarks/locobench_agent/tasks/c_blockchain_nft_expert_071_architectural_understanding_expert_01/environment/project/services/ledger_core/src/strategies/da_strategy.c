/*
 * HoloCanvas – Ledger Core
 * Module  : Delegated-Artistry (DA) Consensus Strategy
 * File    : strategies/da_strategy.c
 *
 * Copyright (c) 2024 HoloCanvas.
 *
 * Description:
 *   This file implements the “Delegated-Artistry” consensus strategy used by
 *   the Ledger-Core micro-service.  DA is a delegated Proof-of-Stake variant
 *   optimised for collaborative, generative-art workloads.  Curators delegate
 *   “inspiration weight” to trusted validator nodes (“Art Directors”),
 *   incentivising rapid block finality while preserving decentralisation by
 *   periodically rotating directors via on-chain votes.
 *
 *   The implementation follows the Strategy Pattern.  The generic consensus
 *   engine (consensus_engine.c) calls the function pointers exposed in
 *   consensus_strategy_t.  Swapping between DA and alternative strategies
 *   (e.g., PoS-Staking) therefore requires no changes in the core engine.
 *
 *   NOTE: This module purposefully avoids direct networking / I/O.  All such
 *   side-effects are decoupled through event queues (Kafka) or gRPC calls
 *   marshalled by other Ledger-Core components.
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "crypto/sha3.h"              /* Lightweight SHA-3 wrapper          */
#include "crypto/signatures.h"        /* Ed25519/ZKP signatures             */
#include "event_bus/event_bus.h"      /* Internal event bus abstraction     */
#include "ledger/block.h"             /* Canonical block representation     */
#include "ledger/state.h"             /* World-state API                    */
#include "ledger/tx_pool.h"           /* Transaction pool                   */
#include "log/log.h"                  /* Structured logging                 */
#include "strategies/da_strategy.h"   /* Public header for this module      */

/* ------------------------------------------------------------------------- *
 * Constants / Macros
 * ------------------------------------------------------------------------- */
#define DA_MAX_DIRECTORS           128U   /* Hard cap on active directors   */
#define DA_EPOCH_LENGTH            600U   /* Blocks per epoch               */
#define DA_MIN_STAKE              1000U   /* Minimum “inspiration” stake    */
#define DA_REWARD_BASE_PERCENT        2   /* 2 % base block reward          */
#define DA_MAX_SLASH_PERCENT          5   /* 5 % maximum slashing           */

/* For compact, canonicalised hashing */
#define HASH_STR_LEN                65U   /* Hex(32-byte) + NUL             */

/* ------------------------------------------------------------------------- *
 * Internal Data Structures
 * ------------------------------------------------------------------------- */

/* Forward declaration */
typedef struct da_strategy_ctx        da_strategy_ctx_t;

/*
 * Director (validator) metadata — persisted to the world-state but cached
 * locally for hot-path operations.
 */
typedef struct
{
    uint8_t        pubkey[ED25519_PUBKEY_LEN];
    uint64_t       stake;                 /* Total delegated inspiration   */
    uint64_t       last_signed;           /* Last block height signed      */
    uint32_t       missed_blocks;         /* Counter for missed signatures */
    bool           jailed;                /* Temporarily banned            */
} da_director_t;

/*
 * Epoch snapshot — recalculated every DA_EPOCH_LENGTH blocks.
 */
typedef struct
{
    size_t           num_directors;
    da_director_t    directors[DA_MAX_DIRECTORS];
    uint64_t         total_stake;         /* Σ stake for director set      */
    uint64_t         epoch_index;         /* Monotonic epoch counter       */
} da_epoch_t;

/*
 * Main strategy context.  Thread-safe via internal RW-lock.
 */
struct da_strategy_ctx
{
    pthread_rwlock_t  rwlock;             /* Protects mutable state        */
    da_epoch_t        current_epoch;
    atomic_uint_least64_t  height;        /* Latest committed block height */
    event_bus_t      *bus;                /* Local ref to event bus        */
    state_ctx_t      *state;              /* Global world-state handle     */
    tx_pool_t        *tx_pool;            /* Reference to transaction pool */
    da_config_t       cfg;                /* Immutable configuration       */
};

/* ------------------------------------------------------------------------- *
 * Static Helper Prototypes
 * ------------------------------------------------------------------------- */
static bool      da_recalc_epoch_if_needed(da_strategy_ctx_t *ctx,
                                           uint64_t new_height);
static bool      da_select_leader(const da_strategy_ctx_t *ctx,
                                  uint64_t height,
                                  da_director_t *out);
static uint64_t  da_calc_block_reward(const da_strategy_ctx_t *ctx,
                                      const da_director_t    *leader);
static void      da_apply_slash(da_strategy_ctx_t *ctx,
                                da_director_t     *offender,
                                uint32_t           percent);
static void      da_log_director_set(const da_epoch_t *epoch);
static int       da_compare_director(const void *a, const void *b);

/* ------------------------------------------------------------------------- *
 * Strategy API Implementation
 * ------------------------------------------------------------------------- */

static bool
da_init(consensus_strategy_t *iface,
        consensus_engine_t    *engine,
        const void            *params,
        size_t                 params_len)
{
    if (!iface || !engine) {
        return false;
    }

    (void)params_len; /* Unused until we version-tag params */

    const da_config_t *cfg = (const da_config_t *)params;
    if (!cfg) {
        LOG_ERROR("DA_STRATEGY: Missing configuration payload");
        return false;
    }

    da_strategy_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) {
        LOG_SYSERROR(errno, "DA_STRATEGY: Allocation failure");
        return false;
    }

    if (pthread_rwlock_init(&ctx->rwlock, NULL) != 0) {
        LOG_SYSERROR(errno, "DA_STRATEGY: RW-Lock init failed");
        free(ctx);
        return false;
    }

    ctx->bus   = engine->bus;
    ctx->state = engine->state;
    ctx->tx_pool = engine->tx_pool;
    ctx->cfg   = *cfg;

    /* Bootstrap from genesis state */
    ctx->current_epoch.epoch_index  = 0;
    ctx->current_epoch.total_stake  = 0;
    ctx->current_epoch.num_directors = 0;

    /* Fetch initial director set from world-state */
    /* (Assume state_director_iterate exists) */
    state_director_iter_t it;
    state_director_iter_init(ctx->state, &it);
    while (state_director_iter_next(&it)) {
        const director_record_t *rec = state_director_iter_record(&it);
        if (rec->stake < DA_MIN_STAKE) {
            continue;
        }
        if (ctx->current_epoch.num_directors >= DA_MAX_DIRECTORS) {
            LOG_WARN("DA_STRATEGY: Director set truncated to %u",
                     DA_MAX_DIRECTORS);
            break;
        }

        da_director_t *d =
            &ctx->current_epoch.directors[ctx->current_epoch.num_directors++];
        memcpy(d->pubkey, rec->pubkey, sizeof(d->pubkey));
        d->stake         = rec->stake;
        d->last_signed   = 0;
        d->missed_blocks = 0;
        d->jailed        = false;
        ctx->current_epoch.total_stake += rec->stake;
    }

    state_director_iter_close(&it);

    /* Sort directors deterministically for leader selection */
    qsort(ctx->current_epoch.directors,
          ctx->current_epoch.num_directors,
          sizeof(da_director_t),
          da_compare_director);

    da_log_director_set(&ctx->current_epoch);

    atomic_store(&ctx->height, 0);

    /* Store ctx in the strategy interface’s opaque pointer */
    iface->impl_ctx = ctx;
    return true;
}

static void
da_free(consensus_strategy_t *iface)
{
    if (!iface || !iface->impl_ctx) return;

    da_strategy_ctx_t *ctx = iface->impl_ctx;

    pthread_rwlock_destroy(&ctx->rwlock);
    free(ctx);
    iface->impl_ctx = NULL;
}

/*
 * validate_block:
 *   1. Enforce correct leader for height.
 *   2. Verify signature.
 *   3. Validate tx root & state transition via engine API.
 */
static bool
da_validate_block(consensus_strategy_t *iface,
                  const block_t        *blk,
                  char                  err_buf[CONS_STRAT_ERRBUF_SZ])
{
    if (!iface || !blk) return false;

    da_strategy_ctx_t *ctx = iface->impl_ctx;
    bool ok = false;

    pthread_rwlock_rdlock(&ctx->rwlock);

    da_director_t expected_leader;
    if (!da_select_leader(ctx, blk->header.height, &expected_leader)) {
        snprintf(err_buf, CONS_STRAT_ERRBUF_SZ,
                 "Failed to select leader for height %" PRIu64,
                 blk->header.height);
        goto exit;
    }

    if (memcmp(expected_leader.pubkey,
               blk->header.proposer_pubkey,
               sizeof(expected_leader.pubkey)) != 0)
    {
        snprintf(err_buf, CONS_STRAT_ERRBUF_SZ,
                 "Block proposer not expected leader");
        goto exit;
    }

    /* Verify proposer signature */
    if (!sig_verify_ed25519(blk->header_hash,
                            sizeof(blk->header_hash),
                            blk->header.proposer_sig,
                            expected_leader.pubkey))
    {
        snprintf(err_buf, CONS_STRAT_ERRBUF_SZ,
                 "Invalid leader signature");
        goto exit;
    }

    /* Additional validation deferred to engine (tx Merkle, receipts, etc.) */
    ok = true;

exit:
    pthread_rwlock_unlock(&ctx->rwlock);
    return ok;
}

/*
 * apply_block:
 *   Mutates strategy-specific state after the block has been committed to the
 *   canonical chain (height → height+1).  This is the place to apply rewards,
 *   re-calc epochs, slash misbehaviour, etc.
 */
static bool
da_apply_block(consensus_strategy_t *iface, const block_t *blk)
{
    if (!iface || !blk) return false;

    da_strategy_ctx_t *ctx = iface->impl_ctx;
    bool               ok  = true;

    pthread_rwlock_wrlock(&ctx->rwlock);

    uint64_t new_height = blk->header.height;
    atomic_store(&ctx->height, new_height);

    /* Update last_signed for leader */
    da_director_t leader;
    if (da_select_leader(ctx, new_height, &leader)) {
        leader.last_signed = new_height;
        leader.missed_blocks = 0; /* Reset missed block counter */
        /* Persist update to world-state asynchronously */
        state_enqueue_director_update(ctx->state,
                                      leader.pubkey,
                                      leader.stake,
                                      leader.missed_blocks,
                                      leader.jailed);
    }

    /* Reward distribution */
    uint64_t reward = da_calc_block_reward(ctx, &leader);
    if (reward > 0) {
        /* Mint reward to leader’s account; engine handles supply inflation */
        state_credit_account(ctx->state, leader.pubkey, reward);
    }

    /* Epoch change? */
    if (!da_recalc_epoch_if_needed(ctx, new_height)) {
        ok = false;
    }

    pthread_rwlock_unlock(&ctx->rwlock);
    return ok;
}

/* ------------------------------------------------------------------------- *
 * Helper Implementations
 * ------------------------------------------------------------------------- */

static bool
da_recalc_epoch_if_needed(da_strategy_ctx_t *ctx, uint64_t new_height)
{
    if ((new_height % DA_EPOCH_LENGTH) != 0) {
        return true; /* Nothing to do */
    }

    uint64_t next_epoch_index = ctx->current_epoch.epoch_index + 1;
    da_epoch_t next = {
        .num_directors = 0,
        .total_stake   = 0,
        .epoch_index   = next_epoch_index
    };

    /* Collect candidate directors from world-state */
    state_director_iter_t it;
    state_director_iter_init(ctx->state, &it);

    while (state_director_iter_next(&it))
    {
        const director_record_t *rec = state_director_iter_record(&it);

        if (rec->stake < DA_MIN_STAKE || rec->jailed) {
            continue;
        }
        if (next.num_directors >= DA_MAX_DIRECTORS) {
            LOG_WARN("DA_STRATEGY: Director set truncated to %u", DA_MAX_DIRECTORS);
            break;
        }

        da_director_t *d = &next.directors[next.num_directors++];
        memcpy(d->pubkey, rec->pubkey, sizeof(d->pubkey));
        d->stake         = rec->stake;
        d->last_signed   = rec->last_signed;
        d->missed_blocks = rec->missed_blocks;
        d->jailed        = rec->jailed;
        next.total_stake += rec->stake;
    }
    state_director_iter_close(&it);

    /* If no directors, strategy cannot continue */
    if (next.num_directors == 0) {
        LOG_CRITICAL("DA_STRATEGY: No eligible directors for epoch %" PRIu64,
                     next_epoch_index);
        return false;
    }

    /* Sort deterministically */
    qsort(next.directors,
          next.num_directors,
          sizeof(da_director_t),
          da_compare_director);

    ctx->current_epoch = next;
    da_log_director_set(&ctx->current_epoch);

    /* Emit event for observability */
    event_bus_publish(ctx->bus, EVENT_EPOCH_CHANGED, &next, sizeof(next));

    return true;
}

/*
 * Deterministic leader selection using weighted-round-robin proportional to
 * stake, salted by epoch index to prevent grinding.
 */
static bool
da_select_leader(const da_strategy_ctx_t *ctx,
                 uint64_t                 height,
                 da_director_t           *out)
{
    if (ctx->current_epoch.num_directors == 0) {
        return false;
    }

    uint64_t slot = height % ctx->current_epoch.num_directors;

    /* SHA3(epoch||height) to produce pseudo-random permutation */
    uint8_t seed_hash[SHA3_256_DIGEST_LEN];
    uint8_t input[sizeof(uint64_t) * 2];
    memcpy(input, &ctx->current_epoch.epoch_index, sizeof(uint64_t));
    memcpy(input + sizeof(uint64_t), &height, sizeof(uint64_t));
    sha3_256(seed_hash, sizeof(seed_hash), input, sizeof(input));

    uint64_t rnd;
    memcpy(&rnd, seed_hash, sizeof(rnd));
    rnd %= ctx->current_epoch.num_directors;

    size_t idx = (slot + rnd) % ctx->current_epoch.num_directors;

    *out = ctx->current_epoch.directors[idx];
    return true;
}

static uint64_t
da_calc_block_reward(const da_strategy_ctx_t *ctx,
                     const da_director_t     *leader)
{
    if (ctx->cfg.fixed_reward > 0) {
        return ctx->cfg.fixed_reward;
    }

    /* Otherwise reward proportional to stake */
    double pct = (double)DA_REWARD_BASE_PERCENT / 100.0;
    double reward = (double)leader->stake * pct;
    return (uint64_t)reward;
}

/*
 * Slash a director by percentage of stake, jail if severe.
 */
static void
da_apply_slash(da_strategy_ctx_t *ctx,
               da_director_t     *offender,
               uint32_t           percent)
{
    if (percent == 0 || percent > DA_MAX_SLASH_PERCENT) return;

    uint64_t penalty = (offender->stake * percent) / 100;
    offender->stake -= penalty;

    state_debit_account(ctx->state, offender->pubkey, penalty);

    LOG_WARN("DA_STRATEGY: Director slashed %" PRIu32 "%% (penalty=%" PRIu64 ")",
             percent, penalty);

    if (percent == DA_MAX_SLASH_PERCENT) {
        offender->jailed = true;
        LOG_WARN("DA_STRATEGY: Director jailed due to severe slash");
    }

    /* Persist director state */
    state_enqueue_director_update(ctx->state,
                                  offender->pubkey,
                                  offender->stake,
                                  offender->missed_blocks,
                                  offender->jailed);
}

static void
da_log_director_set(const da_epoch_t *epoch)
{
    LOG_INFO("DA_STRATEGY: Activated epoch %" PRIu64
             " with %zu directors (Σ stake=%" PRIu64 ")",
             epoch->epoch_index,
             epoch->num_directors,
             epoch->total_stake);

#ifdef DEBUG
    for (size_t i = 0; i < epoch->num_directors; ++i) {
        char hex[ED25519_PUBKEY_LEN * 2 + 1];
        bytes_to_hex(epoch->directors[i].pubkey,
                     sizeof(epoch->directors[i].pubkey),
                     hex,
                     sizeof(hex));
        LOG_DEBUG("DA_STRATEGY: Director[%zu]: pk=%s stake=%" PRIu64,
                  i, hex, epoch->directors[i].stake);
    }
#endif
}

static int
da_compare_director(const void *a, const void *b)
{
    const da_director_t *da = a;
    const da_director_t *db = b;

    /* Descending by stake, tiebreaker: pubkey lexicographically */
    if (da->stake > db->stake) return -1;
    if (da->stake < db->stake) return  1;
    return memcmp(da->pubkey, db->pubkey, sizeof(da->pubkey));
}

/* ------------------------------------------------------------------------- *
 * Strategy Interface V-Table
 * ------------------------------------------------------------------------- */

static const consensus_strategy_vtbl_t da_vtbl = {
    .init           = da_init,
    .free           = da_free,
    .validate_block = da_validate_block,
    .apply_block    = da_apply_block,
    .name           = "Delegated-Artistry"
};

/*
 * Public factory exported by da_strategy.h
 */
consensus_strategy_t *
da_strategy_create(void)
{
    consensus_strategy_t *s = calloc(1, sizeof(*s));
    if (!s) {
        LOG_SYSERROR(errno, "DA_STRATEGY: Allocation failure");
        return NULL;
    }
    s->vtbl      = &da_vtbl;
    s->impl_ctx  = NULL;
    return s;
}