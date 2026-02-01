```c
/**
 * HoloCanvas – LedgerCore
 * File: services/ledger_core/src/consensus_manager.c
 *
 * The Consensus Manager is responsible for:
 *   1. Dynamically loading a pluggable consensus engine (PoS-Staking,
 *      Delegated-Artistry, etc.).
 *   2. Verifying and finalising blocks produced by upstream
 *      proposer/mempool services.
 *   3. Committing state-machine transitions to durable storage.
 *   4. Publishing consensus events to the event-bus for downstream
 *      micro-services (Mint-Factory, Governance-Hall, …).
 *
 * This module is intentionally self-contained; platform-specific
 * components (Kafka, RocksDB, protobuf models, etc.) are abstracted
 * behind thin interfaces so that LedgerCore can be embedded or unit-
 * tested in isolation.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <dlfcn.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>

/* ────────────────────────────────────────────────────────── */
/* External / project headers (forward-declared if missing)  */
/* ────────────────────────────────────────────────────────── */
#include "logger.h"            /* Simple application logger      */
#include "event_bus.h"         /* Kafka/gRPC abstraction          */
#include "ledger_storage.h"    /* Durable key-value store         */
#include "artifact_state.h"    /* State-Machine for NFTs          */
#include "transaction.h"       /* Wire-format for transactions    */
#include "block.h"             /* Wire-format for ledger blocks   */
#include "consensus_manager.h" /* Public API for this component   */

/* ---------------------------------------------------------------- */
/* Fallback stubs for stand-alone compilation (unit test harnesses) */
/* ---------------------------------------------------------------- */
#ifndef BLOCK_H
#define BLOCK_H
typedef struct {
    uint64_t height;
    uint64_t timestamp;
    uint8_t  hash[32];
    uint8_t  prev_hash[32];
    tx_list_t *txs; /* Linked list of transactions (see transaction.h) */
} block_t;
#endif /* BLOCK_H */

#ifndef LOGGER_H
#define LOGGER_H
#define LOG_LEVEL_INFO  1
#define LOG_LEVEL_WARN  2
#define LOG_LEVEL_ERR   3
void logger_log(int level, const char *fmt, ...);
#endif /* LOGGER_H */

#ifndef EVENT_BUS_H
#define EVENT_BUS_H
typedef struct event_bus_s event_bus_t;
bool event_bus_publish(event_bus_t *bus, const char *topic,
                       const void *payload, size_t size);
#endif /* EVENT_BUS_H */

#ifndef LEDGER_STORAGE_H
#define LEDGER_STORAGE_H
typedef struct ledger_storage_s ledger_storage_t;
bool ledger_storage_put_block(ledger_storage_t *store,
                              const block_t *blk);
bool ledger_storage_set_state_root(ledger_storage_t *store,
                                   const uint8_t root[32]);
#endif /* LEDGER_STORAGE_H */

/* ────────────────────────────────────────────────────────── */
/* Consensus Engine plug-in interface                         */
/* ────────────────────────────────────────────────────────── */
typedef struct consensus_engine {
    const char *name;

    /* Initialise engine with JSON-encoded configuration blob.    */
    bool (*init)(const char *json_config,
                 ledger_storage_t *store,
                 event_bus_t *event_bus);

    /* Verify cryptographic validity, state transitions, gas, …   */
    bool (*verify_block)(const block_t *candidate,
                         char **err_msg);

    /* Execute state transitions & compute new state root.        */
    bool (*finalise_block)(const block_t *candidate,
                           uint8_t new_state_root[32],
                           char **err_msg);

    /* Shut down and free any engine-local resources.             */
    void (*shutdown)(void);
} consensus_engine_t;

/* The `consensus_manager_t` is opaque to other translation units. */
struct consensus_manager {
    consensus_engine_t engine;           /* Function table          */
    void              *engine_so_handle; /* dlopen handle           */

    ledger_storage_t  *storage;          /* Durable KV store        */
    event_bus_t       *event_bus;        /* Global event bus        */

    /* ────── Worker thread & queue for incoming blocks ────── */
    pthread_t          worker;
    pthread_mutex_t    q_mutex;
    pthread_cond_t     q_cond;
    struct blk_node   *q_head;
    struct blk_node   *q_tail;
    bool               stop_requested;
};

/* Linked-list node for pending blocks */
struct blk_node {
    block_t          *blk;
    struct blk_node  *next;
};

/* Internal helpers */
static void *_worker_loop(void *arg);
static bool   _load_engine(consensus_manager_t  *mgr,
                           const char           *so_path);
static void   _unload_engine(consensus_manager_t *mgr);
static void   _enqueue_block(consensus_manager_t *mgr,
                             block_t *blk);
static block_t *_dequeue_block(consensus_manager_t *mgr);

/* ═══════════════════════════════════════════════════════════ */
/* Public API                                                 */
/* ═══════════════════════════════════════════════════════════ */

consensus_manager_t *consensus_manager_create(const char    *engine_so_path,
                                              const char    *engine_cfg_json,
                                              ledger_storage_t *store,
                                              event_bus_t      *bus)
{
    if (!engine_so_path || !store || !bus) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] Invalid argument(s) to create()");
        return NULL;
    }

    consensus_manager_t *mgr = calloc(1, sizeof(*mgr));
    if (!mgr) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] Out of memory");
        return NULL;
    }

    mgr->storage   = store;
    mgr->event_bus = bus;

    pthread_mutex_init(&mgr->q_mutex, NULL);
    pthread_cond_init(&mgr->q_cond,  NULL);

    if (!_load_engine(mgr, engine_so_path)) {
        goto fail;
    }

    /* Initialise engine with config JSON */
    if (!mgr->engine.init(engine_cfg_json, store, bus)) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] Engine(%s) failed to init",
                   mgr->engine.name);
        goto fail;
    }

    /* Spawn worker thread */
    if (pthread_create(&mgr->worker, NULL,
                       _worker_loop, mgr) != 0) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] Failed to spawn worker thread: %s",
                   strerror(errno));
        goto fail;
    }

    logger_log(LOG_LEVEL_INFO,
               "[ConsensusMgr] Started with engine: %s",
               mgr->engine.name);
    return mgr;

fail:
    _unload_engine(mgr);
    pthread_mutex_destroy(&mgr->q_mutex);
    pthread_cond_destroy(&mgr->q_cond);
    free(mgr);
    return NULL;
}

void consensus_manager_destroy(consensus_manager_t *mgr)
{
    if (!mgr) return;

    /* Request worker shutdown */
    pthread_mutex_lock(&mgr->q_mutex);
    mgr->stop_requested = true;
    pthread_cond_signal(&mgr->q_cond);
    pthread_mutex_unlock(&mgr->q_mutex);

    /* Join worker */
    pthread_join(mgr->worker, NULL);

    /* Unload engine */
    if (mgr->engine.shutdown) {
        mgr->engine.shutdown();
    }
    _unload_engine(mgr);

    /* Drain any remaining queued blocks */
    struct blk_node *n, *tmp;
    n = mgr->q_head;
    while (n) {
        tmp = n->next;
        free(n->blk);
        free(n);
        n = tmp;
    }

    pthread_mutex_destroy(&mgr->q_mutex);
    pthread_cond_destroy(&mgr->q_cond);
    free(mgr);

    logger_log(LOG_LEVEL_INFO,
               "[ConsensusMgr] Clean shutdown complete");
}

bool consensus_manager_submit_block(consensus_manager_t *mgr,
                                    const block_t       *blk_in)
{
    if (!mgr || !blk_in) return false;

    /* Deep-copy block because caller may free their memory */
    block_t *copy = malloc(sizeof(*copy));
    if (!copy) return false;
    memcpy(copy, blk_in, sizeof(*copy));

    _enqueue_block(mgr, copy);
    return true;
}

/* ═══════════════════════════════════════════════════════════ */
/* Private Implementation                                     */
/* ═══════════════════════════════════════════════════════════ */

static void _enqueue_block(consensus_manager_t *mgr, block_t *blk)
{
    struct blk_node *node = calloc(1, sizeof(*node));
    if (!node) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] OOM while enqueueing block");
        return;
    }
    node->blk = blk;

    pthread_mutex_lock(&mgr->q_mutex);
    if (mgr->q_tail) {
        mgr->q_tail->next = node;
        mgr->q_tail       = node;
    } else {
        mgr->q_head = mgr->q_tail = node;
    }
    pthread_cond_signal(&mgr->q_cond);
    pthread_mutex_unlock(&mgr->q_mutex);
}

static block_t *_dequeue_block(consensus_manager_t *mgr)
{
    pthread_mutex_lock(&mgr->q_mutex);
    while (!mgr->q_head && !mgr->stop_requested) {
        pthread_cond_wait(&mgr->q_cond, &mgr->q_mutex);
    }

    if (mgr->stop_requested) {
        pthread_mutex_unlock(&mgr->q_mutex);
        return NULL;
    }

    struct blk_node *node = mgr->q_head;
    mgr->q_head = node->next;
    if (!mgr->q_head) mgr->q_tail = NULL;

    pthread_mutex_unlock(&mgr->q_mutex);

    block_t *blk = node->blk;
    free(node);
    return blk;
}

static void *_worker_loop(void *arg)
{
    consensus_manager_t *mgr = arg;

    for (;;)
    {
        block_t *blk = _dequeue_block(mgr);
        if (!blk) break; /* Shutdown requested */

        /* Step 1: Verify candidate block */
        char *err_msg = NULL;
        if (!mgr->engine.verify_block(blk, &err_msg)) {
            logger_log(LOG_LEVEL_WARN,
                       "[ConsensusMgr] Block@%lu verification failed: %s",
                       blk->height,
                       err_msg ? err_msg : "(no details)");
            free(err_msg);
            free(blk);
            continue; /* Reject block */
        }

        /* Step 2: Finalise (exec state transitions) */
        uint8_t new_state_root[32] = {0};
        if (!mgr->engine.finalise_block(blk,
                                        new_state_root,
                                        &err_msg)) {
            logger_log(LOG_LEVEL_ERR,
                       "[ConsensusMgr] Block@%lu finalisation failed: %s",
                       blk->height,
                       err_msg ? err_msg : "(no details)");
            free(err_msg);
            free(blk);
            continue; /* Inconsistent state, do not commit */
        }

        /* Step 3: Commit to durable storage */
        if (!ledger_storage_put_block(mgr->storage, blk) ||
            !ledger_storage_set_state_root(mgr->storage,
                                           new_state_root)) {
            logger_log(LOG_LEVEL_ERR,
                       "[ConsensusMgr] Storage commit failed at height %lu",
                       blk->height);
            free(blk);
            continue;
        }

        /* Step 4: Publish consensus event to bus */
        event_bus_publish(mgr->event_bus,
                          "ledger.block.finalised",
                          blk, sizeof(*blk));

        logger_log(LOG_LEVEL_INFO,
                   "[ConsensusMgr] Block@%lu committed (root=%02x%02x…)",
                   blk->height,
                   new_state_root[0], new_state_root[1]);

        free(blk);
    }

    return NULL;
}

/* ────────────────────────────────────────────────────────── */
/* Dynamic loading of Consensus Engine shared-library        */
/* ────────────────────────────────────────────────────────── */

static bool _load_engine(consensus_manager_t *mgr,
                         const char          *so_path)
{
    mgr->engine_so_handle = dlopen(so_path, RTLD_NOW | RTLD_LOCAL);
    if (!mgr->engine_so_handle) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] dlopen failed: %s",
                   dlerror());
        return false;
    }

    /* Convention: shared library exports symbol `holo_consensus_engine` */
    consensus_engine_t *sym =
        (consensus_engine_t *)dlsym(mgr->engine_so_handle,
                                    "holo_consensus_engine");
    if (!sym) {
        logger_log(LOG_LEVEL_ERR,
                   "[ConsensusMgr] dlsym 'holo_consensus_engine' missing");
        dlclose(mgr->engine_so_handle);
        mgr->engine_so_handle = NULL;
        return false;
    }

    /* Copy function table (no pointers back into the SO needed) */
    memcpy(&mgr->engine, sym, sizeof(*sym));
    return true;
}

static void _unload_engine(consensus_manager_t *mgr)
{
    if (mgr->engine_so_handle) {
        dlclose(mgr->engine_so_handle);
        mgr->engine_so_handle = NULL;
    }
}

/* ═══════════════════════════════════════════════════════════ */
/* EOF                                                        */
/* ═══════════════════════════════════════════════════════════ */
```