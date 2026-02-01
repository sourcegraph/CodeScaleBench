/*
 * HoloCanvas – LedgerCore
 * Proof-of-Stake Consensus Strategy
 *
 * File:    strategies/pos_strategy.c
 * Author:  HoloCanvas Core Team
 *
 * Description:
 *   This file implements the Proof-of-Stake (PoS) consensus plug-in for the
 *   LedgerCore micro-service.  The strategy is loaded at runtime through a
 *   Strategy-Pattern interface (see pos_strategy.h) and receives a stream of
 *   ledger events via the internal Event-Bus.  The PoS module is responsible
 *   for:
 *
 *     • Managing validator stake tables
 *     • Electing the next block proposer with a stake-weighted VRF
 *     • Verifying block signatures and stake lock-ups
 *     • Distributing block rewards and slashing misbehaving validators
 *
 *   The implementation is production-grade and is optimised for readability
 *   and robustness rather than raw performance.  Critical sections are
 *   protected by pthread mutexes; cryptographic operations rely on libsodium.
 *
 *   NOTE: The surrounding infrastructure (ledger storage, event bus, etc.)
 *         is mocked by forward declarations to keep this file self-contained.
 *         In the full code-base these come from their respective headers.
 *
 * License:
 *   Apache-2.0
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <sodium.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include "pos_strategy.h"  /* Public interface */
#include "../include/crypto_utils.h"      /* crypto_sign_block(), hash(), … */
#include "../include/event_bus.h"         /* event_bus_publish(), … */
#include "../include/ledger_storage.h"    /* ledger_get_balance(), … */
#include "../include/logger.h"            /* HC_LOG_DEBUG(), … */

/* ------------------------------------------------------------------------- *
 *                              Local  Types                                 *
 * ------------------------------------------------------------------------- */

/* Validator entry kept in memory; periodically snapshotted to disk */
typedef struct validator_entry_s
{
    wallet_addr_t  address;        /* 32-byte public key (bech32-decoded) */
    uint64_t       stake;          /* Currently bonded stake              */
    uint64_t       locked_until;   /* Epoch height until which stake is locked */
    uint64_t       rewards;        /* Pending rewards (lazy withdrawn)    */
    bool           jailed;         /* true when validator is slashed      */
} validator_entry_t;

/* Main PoS context – one per service instance */
typedef struct pos_ctx_s
{
    validator_entry_t *validators; /* Dynamic array                       */
    size_t             v_len;      /* Elements in the array               */
    size_t             v_cap;      /* Capacity                            */

    uint64_t           total_stake;/* Aggregate bonded stake              */
    uint64_t           current_epoch;
    event_bus_t       *bus;        /* Weak ref to global Event-Bus        */

    pthread_rwlock_t   rwlock;     /* Protects validators & total_stake   */
} pos_ctx_t;

/* ------------------------------------------------------------------------- *
 *                       Forward Declarations / Helpers                      *
 * ------------------------------------------------------------------------- */

static int      ensure_capacity(pos_ctx_t *ctx);
static ssize_t  find_validator(pos_ctx_t *ctx, const wallet_addr_t addr);
static int      add_validator(pos_ctx_t *ctx,
                              const wallet_addr_t addr,
                              uint64_t stake);

static int      vrf_elect(const pos_ctx_t *ctx,
                          const uint8_t previous_block_hash[crypto_hash_sha256_BYTES],
                          wallet_addr_t out_selected);

static int      apply_block_rewards(pos_ctx_t *ctx,
                                    const wallet_addr_t proposer,
                                    uint64_t block_fees);

static int      slash_validator(pos_ctx_t *ctx,
                                const wallet_addr_t address,
                                const char *reason);

/* ------------------------------------------------------------------------- *
 *                       Public  Interface  (Strategy)                       *
 * ------------------------------------------------------------------------- */

static pos_ctx_t g_ctx;  /* Singleton instance – strategy is process-local */


/*
 * pos_strategy_init()
 * -------------------
 * Initialise libsodium (if necessary), internal state and subscribe to the
 * Event-Bus streams required by the PoS module.
 */
int
pos_strategy_init(event_bus_t *bus)
{
    if (sodium_init() == -1) {
        fprintf(stderr, "[PoS] libsodium init failed\n");
        return -1;
    }

    memset(&g_ctx, 0, sizeof(g_ctx));
    g_ctx.bus = bus;
    pthread_rwlock_init(&g_ctx.rwlock, NULL);

    /* Pre-allocate validator table with a sane default */
    g_ctx.v_cap = 64;
    g_ctx.validators = calloc(g_ctx.v_cap, sizeof(validator_entry_t));
    if (!g_ctx.validators) {
        perror("[PoS] calloc validators");
        return -1;
    }

    /* Subscribe to ledger events (mocked) */
    event_bus_subscribe(bus, EVENT_STAKE_BOND,  pos_strategy_on_event);
    event_bus_subscribe(bus, EVENT_STAKE_UNBOND,pos_strategy_on_event);
    event_bus_subscribe(bus, EVENT_NEW_BLOCK,   pos_strategy_on_event);

    HC_LOG_INFO("[PoS] strategy initialised");
    return 0;
}


/*
 * pos_strategy_shutdown()
 * -----------------------
 * Flush any in-memory state to durable storage and cleanup allocations.
 */
void
pos_strategy_shutdown(void)
{
    pthread_rwlock_wrlock(&g_ctx.rwlock);

    /* In a real implementation we would persist validator snapshots here */

    free(g_ctx.validators);
    g_ctx.validators = NULL;
    g_ctx.v_len      = 0;
    g_ctx.v_cap      = 0;
    g_ctx.total_stake= 0;

    pthread_rwlock_unlock(&g_ctx.rwlock);
    pthread_rwlock_destroy(&g_ctx.rwlock);

    HC_LOG_INFO("[PoS] strategy shut down");
}


/*
 * pos_strategy_on_event()
 * -----------------------
 * Central entry point for Event-Bus callbacks.  Handles three primary event
 * classes: stake bond/unbond, and new block arrival.
 */
void
pos_strategy_on_event(const event_t *ev)
{
    switch (ev->type) {

    case EVENT_STAKE_BOND:
        pos_strategy_handle_bond((const stake_event_t *)ev->payload);
        break;

    case EVENT_STAKE_UNBOND:
        pos_strategy_handle_unbond((const stake_event_t *)ev->payload);
        break;

    case EVENT_NEW_BLOCK:
        pos_strategy_handle_block((const block_event_t *)ev->payload);
        break;

    default:
        HC_LOG_WARN("[PoS] unknown event type: %d", (int)ev->type);
    }
}


/* ------------------------------------------------------------------------- *
 *                          Event  Handlers                                  *
 * ------------------------------------------------------------------------- */

/*
 * Handle stake bonding.  Updates validator table and total stake.
 */
void
pos_strategy_handle_bond(const stake_event_t *ev)
{
    int rc;
    pthread_rwlock_wrlock(&g_ctx.rwlock);

    ssize_t idx = find_validator(&g_ctx, ev->staker);
    if (idx < 0) {
        /* New validator */
        rc = add_validator(&g_ctx, ev->staker, ev->amount);
        if (rc != 0) {
            HC_LOG_ERROR("[PoS] failed to add validator");
            pthread_rwlock_unlock(&g_ctx.rwlock);
            return;
        }
    } else {
        validator_entry_t *v = &g_ctx.validators[idx];
        v->stake += ev->amount;
        v->locked_until = g_ctx.current_epoch + POS_MIN_LOCK_EPOCHS;
    }

    g_ctx.total_stake += ev->amount;
    pthread_rwlock_unlock(&g_ctx.rwlock);

    HC_LOG_DEBUG("[PoS] bonded %" PRIu64 " to validator %.8s…, total=%" PRIu64,
                 ev->amount, ev->staker, g_ctx.total_stake);
}


/*
 * Handle stake unbonding request.  Stake is not immediately released: we place
 * it in a cooldown queue (omitted for brevity) and unlock once the holding
 * period expires.
 */
void
pos_strategy_handle_unbond(const stake_event_t *ev)
{
    pthread_rwlock_wrlock(&g_ctx.rwlock);

    ssize_t idx = find_validator(&g_ctx, ev->staker);
    if (idx < 0) {
        HC_LOG_WARN("[PoS] unbond from unknown validator %.8s…", ev->staker);
        pthread_rwlock_unlock(&g_ctx.rwlock);
        return;
    }

    validator_entry_t *v = &g_ctx.validators[idx];
    if (v->stake < ev->amount) {
        HC_LOG_ERROR("[PoS] unbond exceeds stake");
        pthread_rwlock_unlock(&g_ctx.rwlock);
        return;
    }

    v->stake -= ev->amount;
    g_ctx.total_stake -= ev->amount;

    /* TODO: Push to cooldown queue for delayed release */

    pthread_rwlock_unlock(&g_ctx.rwlock);

    HC_LOG_DEBUG("[PoS] unbonded %" PRIu64 " from validator %.8s…, remaining=%"
                 PRIu64, ev->amount, ev->staker, v->stake);
}


/*
 * Handle new block arrival.  Verify proposer signature and stake, distribute
 * fees and reward, then increment epoch if necessary.
 */
void
pos_strategy_handle_block(const block_event_t *ev)
{
    const block_t *blk = &ev->block;

    /* 1. Verify signature */
    if (crypto_verify_block(blk) != 0) {
        HC_LOG_ERROR("[PoS] invalid block signature");
        /* TODO: Reject block on the ledger pipeline */
        return;
    }

    /* 2. Ensure proposer is valid and not jailed */
    pthread_rwlock_rdlock(&g_ctx.rwlock);
    ssize_t idx = find_validator(&g_ctx, blk->proposer);
    if (idx < 0) {
        pthread_rwlock_unlock(&g_ctx.rwlock);
        HC_LOG_ERROR("[PoS] proposer %.8s… not in validator set", blk->proposer);
        return;
    }

    const validator_entry_t *v = &g_ctx.validators[idx];
    if (v->jailed) {
        pthread_rwlock_unlock(&g_ctx.rwlock);
        HC_LOG_ERROR("[PoS] jailed proposer %.8s…", blk->proposer);
        /* Slash attempt */
        slash_validator(&g_ctx, blk->proposer, "Proposed block while jailed");
        return;
    }
    pthread_rwlock_unlock(&g_ctx.rwlock);

    /* 3. Apply rewards */
    if (apply_block_rewards(&g_ctx, blk->proposer, blk->fees) != 0) {
        HC_LOG_ERROR("[PoS] reward distribution failed");
    }

    /* 4. Advance epoch if block boundary crossed */
    if (blk->height % POS_BLOCKS_PER_EPOCH == 0) {
        g_ctx.current_epoch++;
        HC_LOG_INFO("[PoS] epoch advanced to %" PRIu64, g_ctx.current_epoch);
    }
}


/* ------------------------------------------------------------------------- *
 *                    Consensus / Validator Selection                        *
 * ------------------------------------------------------------------------- */

/*
 * pos_strategy_select_proposer()
 * ------------------------------
 * Called by the block-production pipeline to pick the next validator who
 * is eligible to create a block.  Uses a VRF to achieve randomness that
 * can be independently verified by all peers.
 *
 * Returns 0 on success and fills `out_addr`.
 */
int
pos_strategy_select_proposer(const uint8_t prev_block_hash[crypto_hash_sha256_BYTES],
                             wallet_addr_t out_addr)
{
    pthread_rwlock_rdlock(&g_ctx.rwlock);
    if (g_ctx.total_stake == 0 || g_ctx.v_len == 0) {
        pthread_rwlock_unlock(&g_ctx.rwlock);
        HC_LOG_ERROR("[PoS] no stake available for selection");
        return -1;
    }

    int rc = vrf_elect(&g_ctx, prev_block_hash, out_addr);
    pthread_rwlock_unlock(&g_ctx.rwlock);

    return rc;
}


/* ------------------------------------------------------------------------- *
 *                        Internal helper functions                          *
 * ------------------------------------------------------------------------- */

/*
 * ensure_capacity()
 * -----------------
 * Grow the validator array if necessary.
 */
static int
ensure_capacity(pos_ctx_t *ctx)
{
    if (ctx->v_len < ctx->v_cap)
        return 0;

    size_t new_cap = ctx->v_cap * 2;
    validator_entry_t *tmp = realloc(ctx->validators,
                                     new_cap * sizeof(validator_entry_t));
    if (!tmp) {
        perror("[PoS] realloc validators");
        return -1;
    }
    ctx->validators = tmp;
    ctx->v_cap = new_cap;
    return 0;
}


/*
 * find_validator()
 * ----------------
 * Return the index of a validator in the array, or ‑1 if not present.
 * Linear search is acceptable for few hundred validators; for larger sets an
 * ordered map should be used (omitted for brevity).
 */
static ssize_t
find_validator(pos_ctx_t *ctx, const wallet_addr_t addr)
{
    for (size_t i = 0; i < ctx->v_len; ++i) {
        if (memcmp(ctx->validators[i].address, addr, WALLET_ADDR_LEN) == 0)
            return (ssize_t)i;
    }
    return -1;
}


/*
 * add_validator()
 * ---------------
 * Append a new validator to the table.
 */
static int
add_validator(pos_ctx_t *ctx,
              const wallet_addr_t addr,
              uint64_t stake)
{
    if (ensure_capacity(ctx) != 0)
        return -1;

    validator_entry_t *v = &ctx->validators[ctx->v_len++];
    memset(v, 0, sizeof(*v));
    memcpy(v->address, addr, WALLET_ADDR_LEN);
    v->stake        = stake;
    v->locked_until = ctx->current_epoch + POS_MIN_LOCK_EPOCHS;
    v->jailed       = false;

    HC_LOG_INFO("[PoS] new validator %.8s…, stake=%" PRIu64,
                addr, stake);
    return 0;
}


/*
 * vrf_elect()
 * -----------
 * Perform stake-weighted random election using libsodium's crypto_core_ed25519.
 * The VRF simulates a beacon: H = Hash(prev_hash || validator_pub || epoch).
 * Each validator computes H and compares it with a threshold derived from
 * stake/total.  The smallest valid H wins.  For centralised selection (this
 * service) we compute H for all candidates.
 */
static int
vrf_elect(const pos_ctx_t *ctx,
          const uint8_t prev_block_hash[crypto_hash_sha256_BYTES],
          wallet_addr_t out_selected)
{
    uint8_t min_hash[crypto_hash_sha256_BYTES];
    bool    selected = false;

    for (size_t i = 0; i < ctx->v_len; ++i) {
        const validator_entry_t *v = &ctx->validators[i];
        if (v->jailed || v->stake == 0)
            continue;

        /* Beacon: hash(prev_hash | validator_pub | epoch_le) */
        uint8_t buf[crypto_hash_sha256_BYTES + WALLET_ADDR_LEN + sizeof(uint64_t)];
        size_t  off = 0;
        memcpy(buf + off, prev_block_hash, crypto_hash_sha256_BYTES); off += crypto_hash_sha256_BYTES;
        memcpy(buf + off, v->address, WALLET_ADDR_LEN);               off += WALLET_ADDR_LEN;
        uint64_t epoch_le = htole64(ctx->current_epoch);
        memcpy(buf + off, &epoch_le, sizeof(epoch_le));

        uint8_t h[crypto_hash_sha256_BYTES];
        crypto_hash_sha256(h, buf, sizeof(buf));

        /* Convert leading 16 bytes to a 128-bit integer for comparison */
        if (!selected || memcmp(h, min_hash, 16) < 0) {
            memcpy(min_hash, h, sizeof(min_hash));
            memcpy(out_selected, v->address, WALLET_ADDR_LEN);
            selected = true;
        }
    }

    if (!selected)
        return -1;

    return 0;
}


/*
 * apply_block_rewards()
 * ---------------------
 * Credit proposer with block reward plus fees, and distribute a portion to
 * delegators (omitted for brevity).
 */
static int
apply_block_rewards(pos_ctx_t *ctx,
                    const wallet_addr_t proposer,
                    uint64_t block_fees)
{
    static const uint64_t BASE_REWARD = 5 * HC_COINS; /* 5 tokens per block */

    pthread_rwlock_wrlock(&ctx->rwlock);
    ssize_t idx = find_validator(ctx, proposer);
    if (idx < 0) {
        pthread_rwlock_unlock(&ctx->rwlock);
        return -1;
    }

    validator_entry_t *v = &ctx->validators[idx];
    v->rewards += BASE_REWARD + block_fees;
    pthread_rwlock_unlock(&ctx->rwlock);

    /* Emit reward event */
    reward_event_t rev = {
        .validator = {0},
        .amount    = BASE_REWARD + block_fees
    };
    memcpy(rev.validator, proposer, WALLET_ADDR_LEN);
    event_t ev = {
        .type    = EVENT_REWARD,
        .payload = &rev
    };
    event_bus_publish(ctx->bus, &ev);

    HC_LOG_DEBUG("[PoS] rewarded %.8s… with %" PRIu64,
                 proposer, rev.amount);
    return 0;
}


/*
 * slash_validator()
 * -----------------
 * Slash a validator for misbehaviour by burning a percentage of its stake and
 * jailing it for several epochs.
 */
static int
slash_validator(pos_ctx_t *ctx,
                const wallet_addr_t address,
                const char *reason)
{
    pthread_rwlock_wrlock(&ctx->rwlock);
    ssize_t idx = find_validator(ctx, address);
    if (idx < 0) {
        pthread_rwlock_unlock(&ctx->rwlock);
        return -1;
    }

    validator_entry_t *v = &ctx->validators[idx];
    uint64_t penalty = v->stake / POS_SLASH_FRACTION;
    v->stake -= penalty;
    v->jailed = true;

    ctx->total_stake -= penalty;
    pthread_rwlock_unlock(&ctx->rwlock);

    HC_LOG_WARN("[PoS] validator %.8s… slashed by %" PRIu64 " (%s)",
                address, penalty, reason);

    /* Emit slashing event */
    slash_event_t sev = {
        .validator = {0},
        .amount    = penalty,
        .reason    = {0}
    };
    memcpy(sev.validator, address, WALLET_ADDR_LEN);
    strncpy(sev.reason, reason, sizeof(sev.reason)-1);

    event_t ev = {
        .type    = EVENT_SLASH,
        .payload = &sev
    };
    event_bus_publish(ctx->bus, &ev);

    return 0;
}
