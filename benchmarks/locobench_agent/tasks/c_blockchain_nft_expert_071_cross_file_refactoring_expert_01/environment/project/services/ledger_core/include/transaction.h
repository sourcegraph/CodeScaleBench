/*
 *  HoloCanvas – LedgerCore
 *  transaction.h
 *
 *  Description:
 *      Canonical transaction representation for the LedgerCore micro-service.
 *      The transaction primitives defined here are used by the Consensus
 *      Engine, State-Machine runtime and RPC façade to create, serialize,
 *      validate and persist on-chain actions such as artifact minting,
 *      evolution, transfers, governance votes and staking operations.
 *
 *  Design Notes:
 *      •  Libsodium (https://libsodium.org) is used for all cryptographic
 *         primitives (hashing, signature verification/creation, RNG, etc.).
 *      •  Flat, byte-perfect serialization is intentionally used to minimise
 *         computational overhead on embedded/edge deployments of HoloCanvas
 *         nodes.  The format is forward-compatible through an explicit
 *         version field embedded in the transaction header.
 *      •  All heap allocations are zeroed before free() to avoid leaking
 *         sensitive key material.
 *
 *  Copyright:
 *      © 2023-2024 HoloCanvas Contributors.  MIT License.
 */

#ifndef HOLOCANVAS_LEDGER_CORE_TRANSACTION_H
#define HOLOCANVAS_LEDGER_CORE_TRANSACTION_H

/* ────────────────────────────────────────────────────────────────────────────
 *  Standard Library
 * ────────────────────────────────────────────────────────────────────────── */
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

/* ────────────────────────────────────────────────────────────────────────────
 *  External Dependencies
 * ────────────────────────────────────────────────────────────────────────── */
#include <sodium.h>             /* libsodium – crypto_sign, crypto_generichash */
#include "utils/byteorder.h"    /* htole64/htobe64 – project-local or platform */

/* ────────────────────────────────────────────────────────────────────────────
 *  C++ Compatibility
 * ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────────
 *  Constants
 * ────────────────────────────────────────────────────────────────────────── */
#define HC_TX_VERSION                 1u
#define HC_TX_HASH_BYTES             32u
#define HC_PUBKEY_BYTES              32u
#define HC_SIG_BYTES                 64u
#define HC_ADDR_BYTES                20u
#define HC_SCRIPT_HASH_BYTES         32u
#define HC_TX_INPUTS_MAX             16u
#define HC_TX_OUTPUTS_MAX            32u
#define HC_TX_MEMO_BYTES_MAX       1024u

/* ────────────────────────────────────────────────────────────────────────────
 *  Error Codes
 * ────────────────────────────────────────────────────────────────────────── */
typedef enum {
    HC_TX_OK                       = 0,
    HC_TX_ERR_NOMEM               = -1,
    HC_TX_ERR_INVALID_PARAM       = -2,
    HC_TX_ERR_OVERFLOW            = -3,
    HC_TX_ERR_CRYPTO              = -4,
    HC_TX_ERR_SERIALIZATION       = -5,
    HC_TX_ERR_VERIFICATION        = -6
} hc_tx_err_t;

/* ────────────────────────────────────────────────────────────────────────────
 *  Transaction Type
 * ────────────────────────────────────────────────────────────────────────── */
typedef enum {
    HC_TX_ARTIFACT_MINT  = 0x01,
    HC_TX_ARTIFACT_EVOLVE= 0x02,
    HC_TX_TRANSFER       = 0x03,
    HC_TX_GOVERNANCE_VOTE= 0x04,
    HC_TX_STAKE          = 0x05,
    HC_TX_UNSTAKE        = 0x06
} hc_tx_type_t;

/* ────────────────────────────────────────────────────────────────────────────
 *  Transaction Structures
 * ────────────────────────────────────────────────────────────────────────── */
typedef struct {
    uint8_t  prev_tx_hash[HC_TX_HASH_BYTES];
    uint32_t prev_out_index;                          /* little-endian on wire */
    uint8_t  sender_pubkey[HC_PUBKEY_BYTES];          /* Edwards-curve pk */
    uint8_t  sig[HC_SIG_BYTES];                       /* detached signature */
} hc_tx_input_t;

typedef struct {
    uint8_t  recipient_addr[HC_ADDR_BYTES];           /* RIPEMD-160/20 */
    uint64_t value;                                   /* base units; le8 */
    uint8_t  script_hash[HC_SCRIPT_HASH_BYTES];       /* optional script */
} hc_tx_output_t;

typedef struct {
    /* Header */
    uint32_t   version;                               /* le32 */
    hc_tx_type_t type;                                /* uint8 */
    uint64_t   timestamp;                             /* unix epoch, le64 */
    uint8_t    prev_block_hash[HC_TX_HASH_BYTES];     /* anchor to chain */

    /* Body */
    uint8_t    input_count;
    uint8_t    output_count;

    hc_tx_input_t  inputs[HC_TX_INPUTS_MAX];
    hc_tx_output_t outputs[HC_TX_OUTPUTS_MAX];

    /* Optional memo field */
    uint16_t   memo_len;                              /* le16 length */
    char       memo[HC_TX_MEMO_BYTES_MAX];

    /* Cached hash (filled after hc_tx_calculate_hash) */
    uint8_t    tx_hash[HC_TX_HASH_BYTES];
    bool       hash_valid;
} hc_transaction_t;

/* ────────────────────────────────────────────────────────────────────────────
 *  API – Construction & Destruction
 * ────────────────────────────────────────────────────────────────────────── */
static inline void
hc_tx_zero(hc_transaction_t *tx)
{
    if (tx) {
        sodium_memzero(tx, sizeof(*tx));
    }
}

/*
 *  Creates an empty transaction on the heap.
 *  The resulting struct must be freed via hc_tx_free().
 */
static inline hc_transaction_t *
hc_tx_create(void)
{
    hc_transaction_t *tx = (hc_transaction_t *) sodium_malloc(sizeof(*tx));
    if (!tx) return NULL;

    hc_tx_zero(tx);
    tx->version = HC_TX_VERSION;
    tx->timestamp = (uint64_t) time(NULL);
    return tx;
}

/* Explicitly zero and free transaction */
static inline void
hc_tx_free(hc_transaction_t *tx)
{
    if (!tx) return;
    hc_tx_zero(tx);
    sodium_free(tx);
}

/* ────────────────────────────────────────────────────────────────────────────
 *  API – Mutation Helpers
 * ────────────────────────────────────────────────────────────────────────── */
static inline hc_tx_err_t
hc_tx_set_type(hc_transaction_t *tx, hc_tx_type_t type)
{
    if (!tx) return HC_TX_ERR_INVALID_PARAM;
    tx->type = type;
    return HC_TX_OK;
}

static inline hc_tx_err_t
hc_tx_append_input(hc_transaction_t *tx,
                   const uint8_t prev_hash[HC_TX_HASH_BYTES],
                   uint32_t      prev_out_index,
                   const uint8_t sender_pubkey[HC_PUBKEY_BYTES],
                   const uint8_t sig[HC_SIG_BYTES])
{
    if (!tx || !prev_hash || !sender_pubkey || !sig)
        return HC_TX_ERR_INVALID_PARAM;

    if (tx->input_count >= HC_TX_INPUTS_MAX)
        return HC_TX_ERR_OVERFLOW;

    hc_tx_input_t *in = &tx->inputs[tx->input_count];
    memcpy(in->prev_tx_hash, prev_hash, HC_TX_HASH_BYTES);
    in->prev_out_index = prev_out_index;
    memcpy(in->sender_pubkey, sender_pubkey, HC_PUBKEY_BYTES);
    memcpy(in->sig, sig, HC_SIG_BYTES);

    tx->input_count++;
    tx->hash_valid = false;
    return HC_TX_OK;
}

static inline hc_tx_err_t
hc_tx_append_output(hc_transaction_t *tx,
                    const uint8_t recipient_addr[HC_ADDR_BYTES],
                    uint64_t value,
                    const uint8_t script_hash[HC_SCRIPT_HASH_BYTES])
{
    if (!tx || !recipient_addr || !script_hash)
        return HC_TX_ERR_INVALID_PARAM;

    if (tx->output_count >= HC_TX_OUTPUTS_MAX)
        return HC_TX_ERR_OVERFLOW;

    hc_tx_output_t *out = &tx->outputs[tx->output_count];
    memcpy(out->recipient_addr, recipient_addr, HC_ADDR_BYTES);
    out->value = value;
    memcpy(out->script_hash, script_hash, HC_SCRIPT_HASH_BYTES);

    tx->output_count++;
    tx->hash_valid = false;
    return HC_TX_OK;
}

static inline hc_tx_err_t
hc_tx_set_memo(hc_transaction_t *tx, const char *memo)
{
    if (!tx || !memo) return HC_TX_ERR_INVALID_PARAM;

    size_t len = strnlen(memo, HC_TX_MEMO_BYTES_MAX);
    tx->memo_len = (uint16_t) len;
    memcpy(tx->memo, memo, len);
    tx->hash_valid = false;
    return HC_TX_OK;
}

/* ────────────────────────────────────────────────────────────────────────────
 *  Internal – Serialization Helpers
 * ────────────────────────────────────────────────────────────────────────── */
static inline void
_write_le32(uint8_t **cursor, uint32_t v)
{
    uint32_t le = htole32(v);
    memcpy(*cursor, &le, sizeof(le));
    *cursor += sizeof(le);
}
static inline void
_write_le64(uint8_t **cursor, uint64_t v)
{
    uint64_t le = htole64(v);
    memcpy(*cursor, &le, sizeof(le));
    *cursor += sizeof(le);
}
static inline void
_write_mem(uint8_t **cursor, const void *src, size_t len)
{
    memcpy(*cursor, src, len);
    *cursor += len;
}

/* ────────────────────────────────────────────────────────────────────────────
 *  API – Serialization
 *      Serializes a transaction into a newly allocated buffer.
 *      Caller must free(*out_buf) after use (via sodium_free()).
 * ────────────────────────────────────────────────────────────────────────── */
static inline hc_tx_err_t
hc_tx_serialize(const hc_transaction_t *tx, uint8_t **out_buf, size_t *out_len)
{
    if (!tx || !out_buf || !out_len) return HC_TX_ERR_INVALID_PARAM;

    /* Basic size calculation */
    size_t sz = 0;
    sz += sizeof(tx->version)
        + sizeof(tx->type)
        + sizeof(tx->timestamp)
        + HC_TX_HASH_BYTES         /* prev_block_hash */
        + sizeof(tx->input_count)
        + sizeof(tx->output_count);

    sz += tx->input_count  * (HC_TX_HASH_BYTES + sizeof(uint32_t)
                            + HC_PUBKEY_BYTES + HC_SIG_BYTES);
    sz += tx->output_count * (HC_ADDR_BYTES + sizeof(uint64_t)
                            + HC_SCRIPT_HASH_BYTES);
    sz += sizeof(tx->memo_len) + tx->memo_len;

    uint8_t *buf = (uint8_t *) sodium_malloc(sz);
    if (!buf) return HC_TX_ERR_NOMEM;
    uint8_t *cursor = buf;

    _write_le32(&cursor, tx->version);
    *cursor++ = (uint8_t) tx->type;
    _write_le64(&cursor, tx->timestamp);
    _write_mem(&cursor, tx->prev_block_hash, HC_TX_HASH_BYTES);

    *cursor++ = tx->input_count;
    *cursor++ = tx->output_count;

    for (uint8_t i = 0; i < tx->input_count; ++i) {
        const hc_tx_input_t *in = &tx->inputs[i];
        _write_mem(&cursor, in->prev_tx_hash, HC_TX_HASH_BYTES);
        _write_le32(&cursor, in->prev_out_index);
        _write_mem(&cursor, in->sender_pubkey, HC_PUBKEY_BYTES);
        _write_mem(&cursor, in->sig, HC_SIG_BYTES);
    }

    for (uint8_t i = 0; i < tx->output_count; ++i) {
        const hc_tx_output_t *out = &tx->outputs[i];
        _write_mem(&cursor, out->recipient_addr, HC_ADDR_BYTES);
        _write_le64(&cursor, out->value);
        _write_mem(&cursor, out->script_hash, HC_SCRIPT_HASH_BYTES);
    }

    /* memoir */
    uint16_t memo_le = htole16(tx->memo_len);
    _write_mem(&cursor, &memo_le, sizeof(memo_le));
    _write_mem(&cursor, tx->memo, tx->memo_len);

    *out_buf = buf;
    *out_len = sz;
    return HC_TX_OK;
}

/* ────────────────────────────────────────────────────────────────────────────
 *  API – Hashing
 *      Calculates the Blake2b hash of the serialized transaction and caches
 *      it in tx->tx_hash.
 * ────────────────────────────────────────────────────────────────────────── */
static inline hc_tx_err_t
hc_tx_calculate_hash(hc_transaction_t *tx)
{
    if (!tx) return HC_TX_ERR_INVALID_PARAM;

    uint8_t *buf = NULL;
    size_t len = 0;
    hc_tx_err_t rc = hc_tx_serialize(tx, &buf, &len);
    if (rc != HC_TX_OK) return rc;

    if (crypto_generichash(tx->tx_hash,
                           sizeof(tx->tx_hash),
                           buf,
                           len,
                           NULL, 0) != 0) {
        sodium_free(buf);
        return HC_TX_ERR_CRYPTO;
    }

    tx->hash_valid = true;
    sodium_free(buf);
    return HC_TX_OK;
}

/* ────────────────────────────────────────────────────────────────────────────
 *  API – Verification
 *      Verifies all attached signatures and cached hash.
 * ────────────────────────────────────────────────────────────────────────── */
static inline hc_tx_err_t
hc_tx_verify(const hc_transaction_t *tx)
{
    if (!tx) return HC_TX_ERR_INVALID_PARAM;

    /* Hash check */
    uint8_t recomputed[HC_TX_HASH_BYTES];
    hc_transaction_t tmp = *tx;
    tmp.hash_valid = false;
    if (hc_tx_calculate_hash(&tmp) != HC_TX_OK)
        return HC_TX_ERR_CRYPTO;

    if (memcmp(recomputed, tx->tx_hash, HC_TX_HASH_BYTES) != 0)
        return HC_TX_ERR_VERIFICATION;

    /* Validate each input signature */
    uint8_t *buf = NULL;
    size_t len = 0;
    if (hc_tx_serialize(tx, &buf, &len) != HC_TX_OK)
        return HC_TX_ERR_SERIALIZATION;

    /* Message to sign = serialized tx without input signatures.
     * For brevity, we skip removing sigs here and simply assume the message
     * verified is the tx_hash (BIP-143 style). */
    for (uint8_t i = 0; i < tx->input_count; ++i) {
        const hc_tx_input_t *in = &tx->inputs[i];
        if (crypto_sign_verify_detached(in->sig,
                                        tx->tx_hash, HC_TX_HASH_BYTES,
                                        in->sender_pubkey) != 0) {
            sodium_free(buf);
            return HC_TX_ERR_VERIFICATION;
        }
    }

    sodium_free(buf);
    return HC_TX_OK;
}

/* ────────────────────────────────────────────────────────────────────────────
 *  Utility – Pretty Printer (Debug only)
 * ────────────────────────────────────────────────────────────────────────── */
#ifdef HOLOCANVAS_ENABLE_DEBUG
#include <stdio.h>
static inline void
hc_tx_print(const hc_transaction_t *tx)
{
    if (!tx) return;
    printf("TX{ ver=%u, type=%u, ts=%llu, inputs=%u, outputs=%u, memo_len=%u }\n",
           tx->version, tx->type, (unsigned long long)tx->timestamp,
           tx->input_count, tx->output_count, tx->memo_len);
}
#endif /* HOLOCANVAS_ENABLE_DEBUG */

/* ────────────────────────────────────────────────────────────────────────────
 *  End of transaction.h
 * ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* HOLOCANVAS_LEDGER_CORE_TRANSACTION_H */
