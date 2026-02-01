```c
/* =========================================================================
 * HoloCanvas – Governance-Hall
 * File: governance.h
 * ------------------------------------------------------------
 * Copyright (c) 2024 HoloCanvas Contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Description:
 *    Public interface for the Governance-Hall micro-service.  The module
 *    exposes a compact, thread-safe C API used by other HoloCanvas
 *    services (and potentially external plug-ins) to perform DAO-style
 *    operations such as:
 *
 *      • Submitting new proposals (payload-agnostic, signed)
 *      • Casting weighted votes (staking power, delegated power, NFT
 *        fractional ownership, etc.)
 *      • Real-time vote tally streaming (Kafka topic “gov_tally”)
 *      • Quorum & super-majority validation
 *      • Proposal life-cycle state machine (DRAFT → ACTIVE → PASSED/REJECTED)
 *
 *    NOTE:
 *      This header purposefully hides all storage details.  Callers interact
 *      only through opaque handles to guarantee ABI stability.
 * ------------------------------------------------------------------------- */

#pragma once

/* ────────────────────────────────────────────────────────────────────────── */
/* System & Standard Library Includes                                        */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#if defined(__cplusplus)
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward Declarations / Opaque Handles                                     */

/* Forward-declaration for the governance context handle (thread-safe).   */
typedef struct hc_gov_ctx      hc_gov_ctx_t;
/* Opaque handle representing a proposal inside a context.                */
typedef struct hc_gov_proposal hc_gov_proposal_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Compile-Time Tunables & Limits                                           */

/* Maximum length (in bytes) of optional, human-readable proposal metadata
 * (title, description, etc.) retained in memory.  Bigger data goes off-chain
 * via IPFS or Rollup store. */
#ifndef HC_GOV_MAX_METADATA_LEN
#define HC_GOV_MAX_METADATA_LEN   512
#endif

/* Cryptographically signed payload length (ED25519 signature size). */
#ifndef HC_GOV_CRYPTO_SIG_LEN
#define HC_GOV_CRYPTO_SIG_LEN     64
#endif

/* Kafka topic names may be overridden at compile time. */
#ifndef HC_GOV_KAFKA_TOPIC_PROPOSE
#define HC_GOV_KAFKA_TOPIC_PROPOSE    "gov_proposals"
#endif

#ifndef HC_GOV_KAFKA_TOPIC_TALLY
#define HC_GOV_KAFKA_TOPIC_TALLY      "gov_tally"
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Enumerations                                                              */

/* Error / status codes returned by all API functions.                     */
typedef enum
{
    HC_GOV_OK = 0,
    HC_GOV_E_INVALID_ARGUMENT,
    HC_GOV_E_NOMEM,
    HC_GOV_E_CONTEXT_SHUTDOWN,
    HC_GOV_E_NOT_FOUND,
    HC_GOV_E_STATE,
    HC_GOV_E_IO,
    HC_GOV_E_CRYPTO,
    HC_GOV_E_INTERNAL,

    /* Keep this last */
    HC_GOV_E__MAX_ENUM
} hc_gov_err_t;

/* Proposal states as tracked by the on-chain state machine.               */
typedef enum
{
    HC_GOV_STATE_DRAFT = 0,      /* Submitted but not yet activated.       */
    HC_GOV_STATE_ACTIVE,         /* Voting window is open.                 */
    HC_GOV_STATE_PASSED,         /* Quorum reached & majority in favor.    */
    HC_GOV_STATE_REJECTED,       /* Quorum reached & majority against.     */
    HC_GOV_STATE_ABORTED,        /* Canceled by proposer or system.        */
    HC_GOV_STATE_EXPIRED,        /* No quorum within deadline.             */

    /* Sentinel */
    HC_GOV_STATE__MAX_ENUM
} hc_gov_state_t;

/* Voting options.                                                         */
typedef enum
{
    HC_GOV_VOTE_ABSTAIN = 0,
    HC_GOV_VOTE_YES,
    HC_GOV_VOTE_NO,

    /* Sentinel */
    HC_GOV_VOTE__MAX_ENUM
} hc_gov_vote_choice_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Data Structures                                                          */

/* Lightweight, self-contained metadata blob for proposals.                */
typedef struct
{
    uint8_t  sig[HC_GOV_CRYPTO_SIG_LEN];            /* Ed25519 signature of payload. */
    uint32_t creator_chain_id;                      /* Originating chain ID.         */
    uint64_t created_unix_ms;                       /* Unix epoch (ms) of creation.  */
    uint64_t vote_deadline_unix_ms;                 /* Voting window end.            */
    char     meta[HC_GOV_MAX_METADATA_LEN];         /* UTF-8 text (title, JSON, …).  */
} hc_gov_prop_header_t;

/* Vote record unit.                                                       */
typedef struct
{
    uint64_t voter_account;                         /* Unique on-chain account ID.   */
    hc_gov_vote_choice_t choice;                    /* YES / NO / ABSTAIN.           */
    uint64_t weight;                                /* Proportional stake weight.    */
} hc_gov_vote_t;

/* Aggregate snapshot produced by the tally function.                      */
typedef struct
{
    uint64_t yes_weight;
    uint64_t no_weight;
    uint64_t abstain_weight;
    uint64_t total_weight;  /* yes + no + abstain                           */

    uint64_t voters_count;  /* number of unique voter accounts              */
} hc_gov_tally_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Callback / Observer Interfaces                                           */

/* Application may subscribe to real-time proposal state changes.  The
 * callback executes on internal IO threads—DON’T BLOCK. */
typedef void (*hc_gov_on_state_cb)(
        const hc_gov_proposal_t *proposal,
        hc_gov_state_t           new_state,
        void                    *user_data /* user-supplied pointer */
);

/* Application may subscribe to continuous vote results (partial tallies). */
typedef void (*hc_gov_on_tally_cb)(
        const hc_gov_proposal_t *proposal,
        const hc_gov_tally_t    *tally,
        void                    *user_data
);

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                               */

/* Create a governance context.
 *
 * Parameters:
 *      kafka_brokers   Comma-separated list of Kafka bootstrap servers.
 *      storage_uri     URI for persisting proposal & vote history
 *                      (e.g., "leveldb:///var/lib/hc/gov").
 *      out_ctx         On success, receives the created context.
 *
 * Returns:
 *      HC_GOV_OK on success, or an error code.
 */
hc_gov_err_t
hc_gov_ctx_create(const char  *kafka_brokers,
                  const char  *storage_uri,
                  hc_gov_ctx_t **out_ctx);

/* Increase reference count—thread-safe.                       */
hc_gov_err_t
hc_gov_ctx_retain(hc_gov_ctx_t *ctx);

/* Release a context.  The object is destroyed when the refcount
 * reaches zero or when hc_gov_ctx_shutdown() completes. */
void
hc_gov_ctx_release(hc_gov_ctx_t *ctx);

/* Request graceful shutdown.  Stops IO loops and flushes storage.
 * Blocks until shutdown is complete or the timeout (ms) expires. */
hc_gov_err_t
hc_gov_ctx_shutdown(hc_gov_ctx_t *ctx, uint32_t timeout_ms);

/* ------------------------------------------------------------------------ */

/* Submit a new proposal (asynchronously published to Kafka + persisted).
 *
 * Parameters:
 *      ctx         Governance context.
 *      header      Fully-populated header (signature validated internally).
 *      payload     Binary payload holding DSL/JSON commands for the DAO.
 *      payload_len Bytes of payload.
 *      out_prop    On success, receives an opaque handle to the proposal
 *                  (may be NULL if caller does not need it).
 *
 * Returns:
 *      HC_GOV_OK on success.
 */
hc_gov_err_t
hc_gov_proposal_submit(hc_gov_ctx_t           *ctx,
                       const hc_gov_prop_header_t *header,
                       const void             *payload,
                       size_t                  payload_len,
                       hc_gov_proposal_t     **out_prop);

/* Acquire additional reference to a proposal.                    */
hc_gov_err_t
hc_gov_proposal_retain(hc_gov_proposal_t *prop);

/* Release a proposal handle.                                     */
void
hc_gov_proposal_release(hc_gov_proposal_t *prop);

/* Retrieve immutable header.  Returned pointer is owned by the
 * proposal and must NOT be freed by the caller. */
const hc_gov_prop_header_t *
hc_gov_proposal_get_header(const hc_gov_proposal_t *prop);

/* Retrieve current state (cached / thread-safe).                 */
hc_gov_state_t
hc_gov_proposal_get_state(const hc_gov_proposal_t *prop);

/* Cast a vote; idempotent (re-casting overwrites existing vote).
 *
 * Parameters:
 *      prop        Target proposal.
 *      account_id  Caller’s unique chain account.
 *      choice      YES / NO / ABSTAIN.
 *      weight      Voting power (validated externally by LedgerCore).
 *
 * Returns:
 *      HC_GOV_OK or error.
 */
hc_gov_err_t
hc_gov_proposal_cast_vote(hc_gov_proposal_t      *prop,
                          uint64_t                account_id,
                          hc_gov_vote_choice_t    choice,
                          uint64_t                weight);

/* Fetch current tally snapshot.                                   */
hc_gov_err_t
hc_gov_proposal_get_tally(const hc_gov_proposal_t *prop,
                          hc_gov_tally_t          *out_tally);

/* ------------------------------------------------------------------------ */
/* Observer Subscription Helpers                                            */

/* Subscribe to proposal state changes.                                    */
hc_gov_err_t
hc_gov_ctx_subscribe_state(hc_gov_ctx_t       *ctx,
                           hc_gov_on_state_cb  cb,
                           void               *user_data);

/* Subscribe to tally updates (may be high-frequency).                      */
hc_gov_err_t
hc_gov_ctx_subscribe_tally(hc_gov_ctx_t       *ctx,
                           hc_gov_on_tally_cb  cb,
                           void               *user_data);

/* ------------------------------------------------------------------------ */
/* Utility / Helper Functions                                               */

/* Convert error code to a static string (non-localized). */
const char *
hc_gov_err_str(hc_gov_err_t err);

/* Pretty-print proposal state to a static string. */
const char *
hc_gov_state_str(hc_gov_state_t state);

/* ────────────────────────────────────────────────────────────────────────── */
/* Inline Utilities                                                         */

#include <stdlib.h>
#include <string.h>

/* Defensive inline for zero-initializing header structure. */
static inline void
hc_gov_prop_header_init(hc_gov_prop_header_t *hdr)
{
    if (hdr)
        memset(hdr, 0, sizeof(*hdr));
}

/* Lightweight guard macro for checking API return codes. */
#ifndef HC_GOV_CHECK
#define HC_GOV_CHECK(expr)                           \
    do {                                             \
        hc_gov_err_t _e = (expr);                    \
        if (_e != HC_GOV_OK)                         \
            return _e;                               \
    } while (0)
#endif

#if defined(__cplusplus)
} /* extern "C" */
#endif
```