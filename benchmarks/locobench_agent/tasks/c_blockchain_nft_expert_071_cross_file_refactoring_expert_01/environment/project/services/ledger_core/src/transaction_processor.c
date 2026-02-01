/*
 * HoloCanvas – LedgerCore
 * File: transaction_processor.c
 *
 * Description:
 *   The transaction processor is the canonical write-path into the LedgerCore
 *   subsystem.  It is responsible for:
 *     1. Verifying basic and contextual validity of incoming transactions.
 *     2. Applying state-transitions to the on-chain ledger representation.
 *     3. Emitting domain events for downstream micro-services (Mint-Factory,
 *        Governance-Hall, etc.) via the event-bus.
 *     4. Surfacing metrics for observability (Prometheus/OpenTelemetry).
 *
 *   The code purposefully avoids any blockchain-consensus specifics; it only
 *   performs deterministic, replayable state-mutation that higher layers
 *   (e.g., the Consensus Engine) may later commit or roll back.
 *
 * © 2024 HoloCanvas Contributors – MIT License
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/* External module interfaces (defined elsewhere in LedgerCore)             */
/* ────────────────────────────────────────────────────────────────────────── */
#include "config.h"          /* global configuration / feature flags          */
#include "crypto.h"          /* ed25519_verify(), sha3_256(), etc.            */
#include "event_bus.h"       /* event_bus_publish(), event_t                  */
#include "ledger.h"          /* append_ledger_entry(), get_account_state()    */
#include "logger.h"          /* log_debug(), log_error(), log_info()          */
#include "metrics.h"         /* metrics_counter_inc(), metrics_histogram_obs  */
#include "state_machine.h"   /* artifact_state_transition()                   */
#include "transaction.h"     /* tx_t, tx_type_t, tx_decode()                  */

/* ────────────────────────────────────────────────────────────────────────── */
/* Compile-time configuration                                               */
/* ────────────────────────────────────────────────────────────────────────── */
#ifndef HLC_TX_PROCESSOR_MAX_SCRIPT_SIZE
#define HLC_TX_PROCESSOR_MAX_SCRIPT_SIZE 8192U /* bytes */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal structures                                                      */
/* ────────────────────────────────────────────────────────────────────────── */

/* Processing statistics (hot in write-path, kept in memory) */
typedef struct txp_stats_s
{
    uint64_t accepted;
    uint64_t rejected_sig;
    uint64_t rejected_nonce;
    uint64_t rejected_balance;
    uint64_t rejected_payload;
} txp_stats_t;

/*
 * Transaction Processor context.
 * One instance per LedgerCore node – shared across worker threads.
 */
typedef struct txp_ctx_s
{
    ledger_t       *ledger;
    event_bus_t    *bus;
    txp_stats_t     stats;
    metrics_handle_t m_metrics;     /* Prometheus/OpenTelemetry handle       */
    pthread_mutex_t mtx;            /* protects ledger & stats during write  */
} txp_ctx_t;

/* Forward declarations */
static bool   tp_verify_signature(const tx_t *tx);
static bool   tp_verify_nonce(txp_ctx_t *ctx, const tx_t *tx);
static bool   tp_verify_funds(txp_ctx_t *ctx, const tx_t *tx);
static int    tp_apply(txp_ctx_t *ctx, const tx_t *tx, uint64_t ts_unix);
static void   tp_emit_event(txp_ctx_t *ctx, const tx_t *tx);
static void   tp_record_metrics(txp_ctx_t *ctx, const char *label, uint64_t dur_ns);

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * tp_init()
 *   Allocate and initialise a Transaction Processor context.
 */
txp_ctx_t *tp_init(ledger_t *ledger, event_bus_t *bus)
{
    if (!ledger || !bus) {
        log_error("tp_init: invalid argument (ledger/bus)");
        return NULL;
    }

    txp_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) {
        log_error("tp_init: calloc failed (%s)", strerror(errno));
        return NULL;
    }

    ctx->ledger = ledger;
    ctx->bus    = bus;
    pthread_mutex_init(&ctx->mtx, NULL);

    /* Register metrics */
    ctx->m_metrics = metrics_register_namespace("ledger_core_tx_processor");
    if (ctx->m_metrics == METRICS_HANDLE_INVALID) {
        log_error("tp_init: failed to register metrics namespace");
        /* Continue; metrics are optional */
    }

    log_info("Transaction Processor initialised.");
    return ctx;
}

/*
 * tp_shutdown()
 *   Free processor resources.
 */
void tp_shutdown(txp_ctx_t **pctx)
{
    if (!pctx || !*pctx) return;

    txp_ctx_t *ctx = *pctx;

    pthread_mutex_destroy(&ctx->mtx);
    free(ctx);
    *pctx = NULL;

    log_info("Transaction Processor shutdown complete.");
}

/*
 * tp_process()
 *   Entry-point for one transaction.  Thread-safe.
 *
 *   Returns:
 *     0  – transaction accepted & applied
 *    >0 – transaction rejected (status code defined below)
 *    <0 – fatal/internal error
 */
int tp_process(txp_ctx_t *ctx, const uint8_t *raw, size_t raw_len)
{
    if (!ctx || !raw || !raw_len) {
        return -EINVAL;
    }

    /* Decode/deserialize */
    tx_t tx;
    memset(&tx, 0, sizeof(tx));
    if (tx_decode(&tx, raw, raw_len) != 0) {
        log_debug("tp_process: failed to decode transaction (len=%zu)", raw_len);
        pthread_mutex_lock(&ctx->mtx);
        ctx->stats.rejected_payload++;
        pthread_mutex_unlock(&ctx->mtx);
        return 4; /* invalid payload */
    }

    const uint64_t ts_unix = (uint64_t)time(NULL);
    const uint64_t t0_ns   = metrics_now_ns();

    /* Validation pipeline */
    if (!tp_verify_signature(&tx)) {
        pthread_mutex_lock(&ctx->mtx);
        ctx->stats.rejected_sig++;
        pthread_mutex_unlock(&ctx->mtx);
        return 1; /* bad signature */
    }
    if (!tp_verify_nonce(ctx, &tx)) {
        pthread_mutex_lock(&ctx->mtx);
        ctx->stats.rejected_nonce++;
        pthread_mutex_unlock(&ctx->mtx);
        return 2; /* nonce mismatch */
    }
    if (!tp_verify_funds(ctx, &tx)) {
        pthread_mutex_lock(&ctx->mtx);
        ctx->stats.rejected_balance++;
        pthread_mutex_unlock(&ctx->mtx);
        return 3; /* insufficient funds */
    }

    /* ── Critical section: apply & emit event ───────────────────────────── */
    if (tp_apply(ctx, &tx, ts_unix) != 0) {
        return -EIO; /* internal error applying */
    }

    tp_emit_event(ctx, &tx);
    tp_record_metrics(ctx, "accepted", metrics_now_ns() - t0_ns);

    pthread_mutex_lock(&ctx->mtx);
    ctx->stats.accepted++;
    pthread_mutex_unlock(&ctx->mtx);

    return 0; /* success */
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Validation helpers                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * Signature verification
 */
static bool tp_verify_signature(const tx_t *tx)
{
    if (!tx) return false;

    /* Ed25519 public key & signature size are fixed (32 / 64 bytes) */
    if (tx->sig_len != 64 || tx->pubkey_len != 32) {
        log_debug("tp_verify_signature: malformed key/sig");
        return false;
    }

    /* Hash the canonicalised, signature-free frame of the transaction */
    uint8_t digest[32];
    if (sha3_256(tx->frame, tx->frame_len, digest) != 0) {
        log_error("tp_verify_signature: sha3_256 failed");
        return false;
    }

    const bool ok = ed25519_verify(tx->signature, digest, sizeof(digest),
                                   tx->pubkey);
    if (!ok) {
        log_debug("tp_verify_signature: invalid signature for tx %s", tx->tx_id);
    }
    return ok;
}

/*
 * Nonce verification
 *   Protects against replay and preserves causal order per-account.
 */
static bool tp_verify_nonce(txp_ctx_t *ctx, const tx_t *tx)
{
    account_state_t acct;
    if (ledger_get_account_state(ctx->ledger, tx->from, &acct) != 0) {
        log_debug("tp_verify_nonce: unknown account %s", tx->from);
        return false; /* account must exist */
    }

    const bool ok = (tx->nonce == acct.next_nonce);
    if (!ok) {
        log_debug("tp_verify_nonce: expected nonce=%" PRIu64 ", got=%" PRIu64,
                  acct.next_nonce, tx->nonce);
    }
    return ok;
}

/*
 * Balance / funds verification
 */
static bool tp_verify_funds(txp_ctx_t *ctx, const tx_t *tx)
{
    account_state_t acct;
    if (ledger_get_account_state(ctx->ledger, tx->from, &acct) != 0) {
        return false;
    }

    /* Gas cost: base + payload-dependent */
    const uint64_t gas_cost = tx->gas_price * tx->gas_limit;
    const uint64_t total    = gas_cost + tx->value;

    const bool ok = (acct.balance >= total);
    if (!ok) {
        log_debug("tp_verify_funds: balance %" PRIu64
                  " < required %" PRIu64 " (gas=%" PRIu64 ", value=%" PRIu64 ")",
                  acct.balance, total, gas_cost, tx->value);
    }
    return ok;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Application / state-mutation                                             */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * tp_apply()
 *   Mutate ledger state and any domain-level state-machines.
 *
 *   NOTE: called inside the global mutex for now.  In production deployments
 *   we may employ sharded, fine-grained locks or MVCC to improve throughput.
 */
static int tp_apply(txp_ctx_t *ctx, const tx_t *tx, uint64_t ts_unix)
{
    int rc = 0;

    pthread_mutex_lock(&ctx->mtx);

    /* Append ledger entry – durable write-ahead log (WAL) */
    ledger_entry_t entry = {
        .timestamp  = ts_unix,
        .tx_id      = {0},
        .raw        = tx->raw,
        .raw_len    = tx->raw_len
    };
    memcpy(entry.tx_id, tx->tx_id, sizeof(entry.tx_id));

    if ((rc = ledger_append(ctx->ledger, &entry)) != 0) {
        log_error("tp_apply: ledger_append failed (rc=%d)", rc);
        goto exit;
    }

    /* Update account nonce & balance */
    if ((rc = ledger_inc_nonce(ctx->ledger, tx->from)) != 0) {
        log_error("tp_apply: ledger_inc_nonce failed");
        goto exit;
    }
    if ((rc = ledger_debit(ctx->ledger, tx->from,
                           tx->value + (tx->gas_price * tx->gas_limit))) != 0) {
        log_error("tp_apply: ledger_debit failed");
        goto exit;
    }
    if (tx->value > 0 && tx->to[0] != '\0') {
        if ((rc = ledger_credit(ctx->ledger, tx->to, tx->value)) != 0) {
            log_error("tp_apply: ledger_credit failed");
            goto exit;
        }
    }

    /* Domain-specific: NFT state transitions, governance votes, etc. */
    switch (tx->type) {
        case TX_MINT_NFT:
            rc = artifact_state_on_mint(ctx->ledger, &tx->payload.mint);
            break;
        case TX_TRANSFER_NFT:
            rc = artifact_state_on_transfer(ctx->ledger, &tx->payload.transfer);
            break;
        case TX_GOVERNANCE_VOTE:
            rc = governance_apply_vote(ctx->ledger, &tx->payload.vote);
            break;
        case TX_STATE_MACHINE_EVOLUTION:
            rc = artifact_state_transition(ctx->ledger, &tx->payload.evolve);
            break;
        default:
            /* For payment-only transactions nothing else to do */
            break;
    }

    if (rc != 0) {
        log_error("tp_apply: domain mutation failed (rc=%d)", rc);
        /* TODO: roll-back ledger_write via undo-log once implemented */
    }

exit:
    pthread_mutex_unlock(&ctx->mtx);
    return rc;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Event-Bus integration                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

static void tp_emit_event(txp_ctx_t *ctx, const tx_t *tx)
{
    event_t ev = {
        .topic = "ledger.tx.applied",
        .ts_unix = (uint64_t)time(NULL)
    };
    snprintf(ev.key, sizeof(ev.key), "%s", tx->tx_id);

    /* Copy raw transaction as payload; consumer services know how to decode */
    ev.payload     = tx->raw;
    ev.payload_len = tx->raw_len;

    if (event_bus_publish(ctx->bus, &ev) != 0) {
        log_error("tp_emit_event: failed to publish event for tx %s", tx->tx_id);
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Metrics                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

static void tp_record_metrics(txp_ctx_t *ctx, const char *label, uint64_t dur_ns)
{
    if (ctx->m_metrics == METRICS_HANDLE_INVALID) return;

    metrics_counter_inc(ctx->m_metrics, "tx_total", label, 1);
    metrics_histogram_observe(ctx->m_metrics, "tx_latency_ns", label, dur_ns);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Debug/Introspection helpers                                              */
/* ────────────────────────────────────────────────────────────────────────── */

void tp_dump_stats(const txp_ctx_t *ctx, FILE *out)
{
    if (!ctx) return;
    if (!out) out = stdout;

    pthread_mutex_lock((pthread_mutex_t *)&ctx->mtx); /* cast away const */

    fprintf(out,
        "LedgerCore/TxProcessor stats:\n"
        "  accepted          : %" PRIu64 "\n"
        "  rejected_sig      : %" PRIu64 "\n"
        "  rejected_nonce    : %" PRIu64 "\n"
        "  rejected_balance  : %" PRIu64 "\n"
        "  rejected_payload  : %" PRIu64 "\n",
        ctx->stats.accepted,
        ctx->stats.rejected_sig,
        ctx->stats.rejected_nonce,
        ctx->stats.rejected_balance,
        ctx->stats.rejected_payload);

    pthread_mutex_unlock((pthread_mutex_t *)&ctx->mtx);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* End of file                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
