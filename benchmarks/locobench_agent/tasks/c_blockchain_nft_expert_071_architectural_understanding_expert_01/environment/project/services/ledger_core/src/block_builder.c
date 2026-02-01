/*
 * HoloCanvas – Ledger Core
 * File: block_builder.c
 *
 * Description:
 *   The Block-Builder is responsible for assembling pending transactions into
 *   candidate blocks and submitting them to the consensus engine for final
 *   verification and commitment.  The module operates in its own worker thread,
 *   watching the mem-pool for new transactions or a timeout, whichever comes
 *   first.  Once triggered, it takes a consistent snapshot of the mem-pool,
 *   builds a Merkle tree, computes the block header and forwards the block to
 *   the Consensus service via gRPC.
 *
 *   The implementation favours robustness: it features extensive error
 *   checking, clear separation between public and private API, and graceful
 *   shutdown semantics.  All heap allocations are guarded, and the worker
 *   thread is cancel-safe.
 *
 * Copyright (c) 2024, HoloCanvas Contributors
 * SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "block_builder.h"            /* Public interface for this module   */
#include "config/ledger_config.h"     /* Constants, CLI / file overrides    */
#include "consensus/consensus.h"      /* consensus_submit_block()           */
#include "crypto/crypto.h"            /* sha256(), blake2b(), etc.          */
#include "mem_pool/tx_pool.h"         /* tx_pool_*() API                    */
#include "utils/logger.h"             /* log_debug(), log_error(), ...      */

/* ------------------------------------------------------------------------- *
 * Static helpers forward declarations                                       *
 * ------------------------------------------------------------------------- */
static void *           builder_thread_main(void *arg);
static ledger_err_t     build_block(struct block_builder *ctx,
                                    struct ledger_block *out_block);
static ledger_err_t     compute_merkle_root(const tx_list_t *txs,
                                            hash256_t        out_root);
static inline uint64_t  unix_epoch_ms(void);

/* ------------------------------------------------------------------------- *
 * Public API                                                                *
 * ------------------------------------------------------------------------- */

ledger_err_t
block_builder_init(struct block_builder        *builder,
                   const struct builder_cfg    *cfg,
                   struct tx_pool              *pool,
                   consensus_client_t          *consensus)
{
    if (!builder || !cfg || !pool || !consensus) {
        return LEDGER_EINVAL;
    }

    memset(builder, 0, sizeof *builder);
    builder->cfg       = *cfg; /* structure copy */
    builder->pool      = pool;
    builder->consensus = consensus;
    atomic_init(&builder->running, false);

    int rc = pthread_mutex_init(&builder->lock, NULL);
    if (rc != 0) {
        return LEDGER_EOS; /* Out of system resources (POSIX mutex) */
    }

    rc = pthread_cond_init(&builder->cond, NULL);
    if (rc != 0) {
        pthread_mutex_destroy(&builder->lock);
        return LEDGER_EOS;
    }

    return LEDGER_OK;
}

ledger_err_t
block_builder_start(struct block_builder *builder)
{
    if (!builder) return LEDGER_EINVAL;

    bool expected = false;
    if (!atomic_compare_exchange_strong(&builder->running, &expected, true)) {
        /* already running */
        return LEDGER_EALREADY;
    }

    int rc = pthread_create(&builder->worker, NULL, builder_thread_main, builder);
    if (rc != 0) {
        atomic_store(&builder->running, false);
        log_error("Block-Builder: failed to spawn worker thread: %s", strerror(rc));
        return LEDGER_EOS;
    }

    pthread_detach(builder->worker);
    return LEDGER_OK;
}

ledger_err_t
block_builder_stop(struct block_builder *builder)
{
    if (!builder) return LEDGER_EINVAL;

    bool expected = true;
    if (!atomic_compare_exchange_strong(&builder->running, &expected, false)) {
        return LEDGER_EALREADY; /* not running */
    }

    /* Wake the worker in case it's sleeping */
    pthread_mutex_lock(&builder->lock);
    pthread_cond_broadcast(&builder->cond);
    pthread_mutex_unlock(&builder->lock);

    /* Worker thread is detached; best effort join semantics via poll */
    const uint64_t deadline = unix_epoch_ms() + 5000;
    while (unix_epoch_ms() < deadline) {
        if (atomic_load(&builder->terminated)) {
            break;
        }
        usleep(20000); /* 20 ms */
    }

    if (!atomic_load(&builder->terminated)) {
        log_error("Block-Builder: timed out waiting for stop");
        return LEDGER_ETIMEDOUT;
    }

    pthread_cond_destroy(&builder->cond);
    pthread_mutex_destroy(&builder->lock);
    return LEDGER_OK;
}

/* ------------------------------------------------------------------------- *
 * Worker thread                                                             *
 * ------------------------------------------------------------------------- */

static void *
builder_thread_main(void *arg)
{
    struct block_builder *ctx = arg;
    log_info("Block-Builder: worker thread started");

    int rc = pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
    if (rc == 0) {
        pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, NULL);
    }

    uint64_t last_build_ms = unix_epoch_ms();

    while (atomic_load(&ctx->running)) {

        /* Determine whether we should create a block */
        bool should_build = false;

        /* 1) Transaction count triggers */
        size_t tx_count = tx_pool_size(ctx->pool);
        if (tx_count >= ctx->cfg.max_txs_per_block &&
            ctx->cfg.max_txs_per_block != 0) {
            should_build = true;
        }

        /* 2) Time-based trigger */
        const uint64_t now_ms        = unix_epoch_ms();
        const uint64_t elapsed_ms    = now_ms - last_build_ms;
        if (!should_build &&
            ctx->cfg.max_block_interval_ms > 0 &&
            elapsed_ms >= ctx->cfg.max_block_interval_ms) {
            should_build = true;
        }

        /* 3) Manual flush (via condition) */
        pthread_mutex_lock(&ctx->lock);
        if (!should_build) {
            const struct timespec ts = {
                .tv_sec  = (now_ms / 1000) + 1,
                .tv_nsec = (now_ms % 1000) * 1e6,
            };
            pthread_cond_timedwait(&ctx->cond, &ctx->lock, &ts);
        }
        pthread_mutex_unlock(&ctx->lock);

        if (!atomic_load(&ctx->running)) break;

        if (!should_build) continue;

        struct ledger_block block;
        ledger_err_t       err = build_block(ctx, &block);
        if (err != LEDGER_OK) {
            log_error("Block-Builder: failed to build block: %s",
                      ledger_err_to_string(err));
            continue;
        }

        err = consensus_submit_block(ctx->consensus, &block);
        if (err != LEDGER_OK) {
            log_error("Block-Builder: consensus rejected block: %s",
                      ledger_err_to_string(err));
            /* Implement your own policy here (retry, stash, ...). */
        } else {
            last_build_ms = now_ms;
            log_info("Block-Builder: successfully proposed block %" PRIu64,
                     block.header.height);
        }

        ledger_block_free(&block); /* Free heap allocations in block */
    }

    log_info("Block-Builder: worker thread terminating");
    atomic_store(&ctx->terminated, true);
    pthread_exit(NULL);
    return NULL;
}

/* ------------------------------------------------------------------------- *
 * Block assembly                                                            *
 * ------------------------------------------------------------------------- */

/* build_block()
 * Take a snapshot of tx-pool and compose a ledger_block ready for consensus.
 */
static ledger_err_t
build_block(struct block_builder *ctx, struct ledger_block *out_block)
{
    if (!ctx || !out_block) return LEDGER_EINVAL;

    size_t snapshot_size = ctx->cfg.max_txs_per_block
                               ? ctx->cfg.max_txs_per_block
                               : TX_POOL_MAX_POP_BULK;

    tx_list_t *txs = tx_pool_pop_bulk(ctx->pool, snapshot_size);
    if (!txs) {
        return LEDGER_EEMPTY; /* No pending transactions */
    }

    memset(out_block, 0, sizeof *out_block);

    /* Fill block header */
    out_block->header.version        = LEDGER_BLOCK_VERSION;
    out_block->header.timestamp_ms   = unix_epoch_ms();
    out_block->header.height         = consensus_next_height(ctx->consensus);
    out_block->header.prev_blockhash = consensus_last_hash(ctx->consensus);

    /* Merkle root */
    ledger_err_t err = compute_merkle_root(txs, out_block->header.merkle_root);
    if (err != LEDGER_OK) {
        tx_list_free(txs);
        return err;
    }

    /* Copy txs to block body */
    out_block->txs      = txs;
    out_block->tx_count = txs->count;

    /* Finalise block hash */
    crypto_hash256_ctx hctx;
    crypto_hash256_init(&hctx);
    crypto_hash256_update(&hctx, &out_block->header, sizeof out_block->header);
    crypto_hash256_update(&hctx, out_block->header.merkle_root,
                          sizeof out_block->header.merkle_root);
    crypto_hash256_final(&hctx, out_block->block_hash);

    return LEDGER_OK;
}

/* ------------------------------------------------------------------------- *
 * Merkle tree                                                               *
 * ------------------------------------------------------------------------- */

static ledger_err_t
compute_merkle_root(const tx_list_t *txs, hash256_t out_root)
{
    if (!txs || txs->count == 0) {
        return LEDGER_EINVAL;
    }

    size_t leaf_count = txs->count;
    size_t level_count = leaf_count;

    /* Allocate working buffer – power of two rounding */
    size_t capacity = 1;
    while (capacity < leaf_count) capacity <<= 1;
    hash256_t *buf = calloc(capacity, sizeof(hash256_t));
    if (!buf) return LEDGER_ENOMEM;

    /* Copy leaves (tx hashes) */
    for (size_t i = 0; i < leaf_count; ++i) {
        memcpy(buf[i], txs->items[i]->tx_hash, sizeof(hash256_t));
    }
    /* Pad duplicate of last leaf if odd count */
    for (size_t i = leaf_count; i < capacity; ++i) {
        memcpy(buf[i], buf[leaf_count - 1], sizeof(hash256_t));
    }

    /* Iteratively hash pairs */
    hash256_t tmp;
    while (level_count > 1) {
        size_t next_level = (level_count + 1) / 2;
        for (size_t i = 0, j = 0; i < level_count; i += 2, ++j) {
            crypto_hash256_ctx hctx;
            crypto_hash256_init(&hctx);
            crypto_hash256_update(&hctx, buf[i],   sizeof(hash256_t));
            crypto_hash256_update(&hctx, buf[i+1], sizeof(hash256_t));
            crypto_hash256_final(&hctx, tmp);
            memcpy(buf[j], tmp, sizeof(hash256_t));
        }
        level_count = next_level;
    }

    memcpy(out_root, buf[0], sizeof(hash256_t));
    free(buf);
    return LEDGER_OK;
}

/* ------------------------------------------------------------------------- *
 * Utilities                                                                 *
 * ------------------------------------------------------------------------- */

static inline uint64_t
unix_epoch_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)(ts.tv_nsec / 1e6);
}