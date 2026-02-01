/*
 * consensus.h
 *
 * HoloCanvas :: LedgerCore
 * ---------------------------------------------
 * Pluggable consensus abstraction for the micro-gallery blockchain.
 *
 * This header exposes the run-time interface used by LedgerCore and
 * higher-level services (Mint-Factory, DeFi-Garden, Governance-Hall, …)
 * to interact with an interchangeable consensus engine.  The API is
 * intentionally minimal yet expressive enough to accommodate PoS-Staking,
 * Delegated-Artistry, or future experimental strategies.
 *
 * NOTE:
 *   The accompanying implementation lives in `consensus.c`.
 *   All exported symbols are thread-safe unless stated otherwise.
 *
 * Copyright (c) 2023-2024  HoloCanvas Contributors
 * SPDX-License-Identifier: MIT
 */

#ifndef HOLOCANVAS_SERVICES_LEDGER_CORE_CONSENSUS_H
#define HOLOCANVAS_SERVICES_LEDGER_CORE_CONSENSUS_H

/* ---------- System Dependencies ------------------------------------------------ */

#include <stddef.h>     /* size_t                */
#include <stdint.h>     /* uint*_t               */
#include <stdbool.h>    /* bool                  */

/* Forward declaration of cryptographic primitives used by consensus engines.
 * Concrete definitions live in `crypto_primitives.h`. */
struct hc_hash256;
struct hc_pubkey;
struct hc_signature;

/* ---------- Versioning --------------------------------------------------------- */

#define LC_CONSENSUS_API_VERSION_MAJOR  1
#define LC_CONSENSUS_API_VERSION_MINOR  0
#define LC_CONSENSUS_API_VERSION_PATCH  0

#define LC_CONSENSUS_MAKE_VERSION(maj, min, pat) \
        (((maj) << 22u) | ((min) << 12u) | (pat))

#define LC_CONSENSUS_API_VERSION \
        LC_CONSENSUS_MAKE_VERSION(LC_CONSENSUS_API_VERSION_MAJOR, \
                                  LC_CONSENSUS_API_VERSION_MINOR, \
                                  LC_CONSENSUS_API_VERSION_PATCH)


/* ---------- Enumerations & Constants ------------------------------------------ */

/* High-level life-cycle hooks that a consensus engine may emit. */
typedef enum {
    LC_CONSENSUS_EVT_BLOCK_PROPOSED,     /* A new block proposal is available.            */
    LC_CONSENSUS_EVT_BLOCK_FINALIZED,    /* A block has been finalized/irreversible.      */
    LC_CONSENSUS_EVT_VALIDATOR_JOINED,   /* A validator joined the active set.            */
    LC_CONSENSUS_EVT_VALIDATOR_LEFT,     /* A validator left/was slashed.                 */
    LC_CONSENSUS_EVT_STATE_SYNCED,       /* Node caught up with canonical chain.          */
    LC_CONSENSUS_EVT_SHUTDOWN            /* Engine is shutting down.                      */
} lc_consensus_event_kind_t;

/* Return codes shared by all consensus operations. */
typedef enum {
    LC_CONSENSUS_OK                       =  0,
    LC_CONSENSUS_ERR_GENERIC              = -1,
    LC_CONSENSUS_ERR_UNSUPPORTED          = -2,
    LC_CONSENSUS_ERR_INVALID_ARG          = -3,
    LC_CONSENSUS_ERR_OUT_OF_MEMORY        = -4,
    LC_CONSENSUS_ERR_IO                   = -5,
    LC_CONSENSUS_ERR_TX_REJECTED          = -6,
    LC_CONSENSUS_ERR_BLOCK_INVALID        = -7,
    LC_CONSENSUS_ERR_STATE_MISMATCH       = -8,
    LC_CONSENSUS_ERR_NOT_INITIALISED      = -9
} lc_consensus_rc_t;


/* ---------- Data Structures ---------------------------------------------------- */

/* Opaque transaction buffer (RLP, protobuf, whatever the engine expects). */
typedef struct {
    const uint8_t *bytes;
    size_t         len;
} lc_tx_blob_t;

/* Compact representation of a block header shared across engines.
 * Field selection is intentionally minimal; engines may embed additional
 * metadata via `extension` point. */
typedef struct {
    uint64_t            height;
    uint64_t            timestamp;     /* Unix epoch, milliseconds.           */
    struct hc_hash256   parent_hash;
    struct hc_hash256   merkle_root;   /* Engine-specific transaction tree.   */
    struct hc_hash256   state_root;    /* Global world-state commitment.      */
    struct hc_pubkey    proposer;      /* Block author / validator.           */
    void               *extension;     /* Optional engine-specific payload.   */
} lc_block_header_t;

/* Full block container – header + opaque body pointer.
 * The consensus library never dereferences `body`; the actual layout is
 * defined by the engine (could be protobuf, SSZ, etc.). */
typedef struct {
    lc_block_header_t  header;
    void              *body;           /* Engine-specific, may be NULL.       */
    size_t             body_size;      /* Raw body size in bytes.             */
} lc_block_t;

/* Event payload forwarded to subscribers. */
typedef struct {
    lc_consensus_event_kind_t  kind;
    const lc_block_t          *block;       /* NULL for non-block events.    */
    const void                *opaque;      /* Engine-specific pointer.      */
} lc_consensus_event_t;

/* Callback invoked on asynchronous engine events. */
typedef void (*lc_consensus_evt_cb)(const lc_consensus_event_t *evt,
                                    void                       *user_data);


/* ---------- Engine Plug-in ABI ------------------------------------------------- */

/*
 * lc_consensus_engine_t
 *
 * Contract that every consensus plug-in must satisfy.  The implementation
 * may be dynamically loaded via `dlopen()` or linked statically.
 *
 * All function pointers must be non-NULL unless stated otherwise.
 * Functions returning `lc_consensus_rc_t` MUST honour the values defined
 * above.  Additional diagnostics may be returned via `err_buf`.
 */
typedef struct lc_consensus_engine {

    /* Human-readable engine identifier (e.g., "pos_staking"). */
    const char *name;

    /* SemVer-encoded engine version */
    uint32_t version;

    /* ---------- Life-cycle ---------------------------------------------------- */

    /* Initialise engine instance.
     *   ctx_out    – Engine-defined opaque context returned to the caller.
     *   cfg_json   – NULL-terminated JSON configuration string.
     *   err_buf    – Optional buffer for error message (may be NULL).
     *   err_len    – Size of err_buf in bytes.
     *
     * Implementation MUST return LC_CONSENSUS_OK on success.
     */
    lc_consensus_rc_t (*init)(void      **ctx_out,
                              const char *cfg_json,
                              char       *err_buf,
                              size_t      err_len);

    /* Shut down and free resources associated with `ctx`. */
    void (*destroy)(void *ctx);

    /* ---------- Validator RPC -------------------------------------------------- */

    /* Submit a transaction to the mempool / gossip layer. */
    lc_consensus_rc_t (*submit_tx)(void         *ctx,
                                   const uint8_t *tx_bytes,
                                   size_t         tx_len,
                                   char          *err_buf,
                                   size_t         err_len);

    /* (Optional) Pre-apply transaction validation – may be NULL. */
    lc_consensus_rc_t (*check_tx)(void         *ctx,
                                  const uint8_t *tx_bytes,
                                  size_t         tx_len,
                                  char          *err_buf,
                                  size_t         err_len);

    /* Propose the next block – called by block-producer nodes. */
    lc_consensus_rc_t (*propose_block)(void       *ctx,
                                       lc_block_t *out_block,
                                       char       *err_buf,
                                       size_t      err_len);

    /* Validate an incoming block. */
    lc_consensus_rc_t (*validate_block)(void             *ctx,
                                        const lc_block_t *blk,
                                        char             *err_buf,
                                        size_t            err_len);

    /* Finalize a block and persist state changes. */
    lc_consensus_rc_t (*finalize_block)(void             *ctx,
                                        const lc_block_t *blk,
                                        char             *err_buf,
                                        size_t            err_len);

    /* ---------- Event Subscription -------------------------------------------- */

    /* Register callback for asynchronous events.
     * May be invoked multiple times – implementation should manage
     * its own subscriber list.  Passing NULL un-registers callback. */
    lc_consensus_rc_t (*subscribe)(void                *ctx,
                                   lc_consensus_evt_cb  cb,
                                   void                *user_data);

} lc_consensus_engine_t;


/* ---------- Public API --------------------------------------------------------- */

/* Register a consensus plug-in with LedgerCore.
 * May be called exactly once per engine shared object. */
lc_consensus_rc_t
lc_consensus_register_engine(const lc_consensus_engine_t *engine);

/* Select the active engine by name.
 * Returns LC_CONSENSUS_ERR_UNSUPPORTED if the engine is not found. */
lc_consensus_rc_t
lc_consensus_select_engine(const char *name);

/* Convenience wrapper that loads an engine, initialises it with `cfg_json`,
 * and returns an opaque handle representing the run-time instance. */
lc_consensus_rc_t
lc_consensus_start(const char *engine_name,
                   const char *cfg_json,
                   void      **instance_out,
                   char       *err_buf,
                   size_t      err_len);

/* Clean shutdown of a previously started consensus instance. */
void
lc_consensus_stop(void *instance);

/* Synchronously submit a transaction (thread-safe). */
static inline lc_consensus_rc_t
lc_consensus_submit_tx(void         *instance,
                       const uint8_t *tx,
                       size_t         tx_len,
                       char          *err_buf,
                       size_t         err_len)
{
    const lc_consensus_engine_t *eng = (const lc_consensus_engine_t *)instance;
    return eng->submit_tx(instance, tx, tx_len, err_buf, err_len);
}

/* Broadcast user-level event subscription to the active engine. */
static inline lc_consensus_rc_t
lc_consensus_subscribe(void                *instance,
                       lc_consensus_evt_cb  cb,
                       void                *user_data)
{
    const lc_consensus_engine_t *eng = (const lc_consensus_engine_t *)instance;
    return eng->subscribe(instance, cb, user_data);
}


/* ---------- Utility Helpers --------------------------------------------------- */

/* Human-friendly description for return codes – thread-safe. */
const char *
lc_consensus_strerror(lc_consensus_rc_t rc);


/* ---------- Compile-time Assertions ------------------------------------------ */

#define LC_STATIC_ASSERT(cond, msg) \
    typedef char static_assertion_##msg[(cond) ? 1 : -1]

LC_STATIC_ASSERT(sizeof(uint64_t) == 8, uint64_must_be_8_bytes);


/* ---------- C++ Interop ------------------------------------------------------- */

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_SERVICES_LEDGER_CORE_CONSENSUS_H */