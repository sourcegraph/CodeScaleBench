/**
 * HoloCanvas LedgerCore – Block Management API
 * ------------------------------------------------------------
 * This header exposes a production-quality Block abstraction for
 * HoloCanvas’ micro-gallery blockchain.  It provides:
 *   • Canonical block/merkle-root hashing (double-SHA-256)
 *   • Dynamic transaction aggregation
 *   • Binary (de)serialization helpers
 *   • Memory-safe construction / destruction helpers
 *
 * The API is delivered as a single-file header.  To include the
 * implementation in exactly one translation unit, define
 *
 *      #define BLOCK_IMPLEMENTATION
 *
 * before including this file.
 *
 * Dependencies:
 *   – OpenSSL (or compatible) for SHA-256
 *   – Standard C11 headers
 *
 * NOTE: The LedgerCore transaction API is forward-declared and must
 *       be linked from the `transaction` module.
 */

#ifndef HOLOCANVAS_LEDGER_CORE_BLOCK_H
#define HOLOCANVAS_LEDGER_CORE_BLOCK_H

#ifdef __cplusplus
extern "C" {
#endif

/* ----------  Standard C & System Includes  ---------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>

/* ----------  Public Constants  ---------- */
#define BLOCK_HASH_SIZE         32      /* SHA-256 */
#define BLOCK_DEFAULT_VERSION   0x0001
#define BLOCK_MAX_TX            8192    /* soft-cap guard */

/* ----------  Error Codes  ---------- */
typedef enum {
    BLOCK_SUCCESS            =  0,
    BLOCK_ERR_MEM            = -1,
    BLOCK_ERR_PARAM          = -2,
    BLOCK_ERR_TX_LIMIT       = -3,
    BLOCK_ERR_SERIALIZATION  = -4,
    BLOCK_ERR_HASH           = -5,
    BLOCK_ERR_VALIDATION     = -6
} block_err_t;

/* ----------  Forward Declarations  ---------- */
struct ledger_tx;  /* Opaque transaction type handled by LedgerCore */

/* LedgerCore transaction helper prototypes (implemented elsewhere) */
int  ledger_tx_hash      (const struct ledger_tx *tx,
                          uint8_t hash_out[BLOCK_HASH_SIZE]);
int  ledger_tx_serialize (const struct ledger_tx *tx,
                          uint8_t **buf_out, size_t *len_out);
int  ledger_tx_deserialize(const uint8_t *buf, size_t buf_len,
                           struct ledger_tx **tx_out);
void ledger_tx_free      (struct ledger_tx *tx);

/* ----------  Type Definitions  ---------- */
/* Block header (wire format) */
typedef struct {
    uint32_t version;                              /* always little-endian in-memory */
    uint8_t  prev_hash[BLOCK_HASH_SIZE];
    uint8_t  merkle_root[BLOCK_HASH_SIZE];
    uint64_t timestamp;                            /* UNIX epoch (sec) */
    uint32_t bits;                                 /* difficulty target */
    uint32_t nonce;
} block_header_t;

/* Full block object (in-memory) */
typedef struct {
    /* Header (must remain the first member!) */
    block_header_t header;

    /* Chain-position metadata (not serialized) */
    uint64_t height;

    /* Dynamic transaction list */
    struct ledger_tx **txs;
    size_t   tx_count;
    size_t   tx_capacity;      /* internal capacity */

    /* Cached header hash (double-SHA-256) */
    uint8_t  hash[BLOCK_HASH_SIZE];
    bool     hash_valid;

    bool     finalized;        /* true after block_finalize() */
} block_t;


/* ----------  Public API  ---------- */

/**
 * block_init
 * Initialize an empty block with the given previous-block hash and height.
 * `prev_hash` may be NULL for the genesis block.
 */
int block_init(block_t            *blk,
               const uint8_t       prev_hash[BLOCK_HASH_SIZE],
               uint64_t            height,
               uint32_t            bits);

/**
 * block_add_tx
 * Append a transaction to the block (O(1) amortized).
 * The block assumes ownership of `tx`.
 */
int block_add_tx(block_t *blk, struct ledger_tx *tx);

/**
 * block_finalize
 * Compute the Merkle root and the block hash.
 * After finalization the block is considered immutable.
 */
int block_finalize(block_t *blk);

/**
 * block_validate
 * Sanity-check a block and all of its transactions.
 * (cryptographic signature verification is delegated to the tx layer).
 */
int block_validate(const block_t *blk);

/**
 * block_serialize / block_deserialize
 * Convert between binary on-wire representation and in-memory struct.
 * Caller owns the returned buffer from serialize(), must free().
 */
int block_serialize  (const block_t *blk,
                      uint8_t **buf_out, size_t *len_out);
int block_deserialize(const uint8_t *buf, size_t buf_len,
                      block_t *blk_out);

/**
 * block_free
 * Release all heap memory associated with the block.
 */
void block_free(block_t *blk);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ------------------------------------------------------------------------- */
/*                       — Implementation Section —                          */
/* ------------------------------------------------------------------------- */
#ifdef BLOCK_IMPLEMENTATION
/* ----------  Private Helper Utilities  ---------- */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <arpa/inet.h>   /* for htonl / ntohl */
#include <openssl/sha.h> /* OpenSSL SHA-256   */

#define _BLOCK_MIN_TX_CAPACITY  8
#define _BLOCK_GROWTH_FACTOR    2

/* Varint helpers (Bitcoin-style, compactSize) */
static size_t _varint_encoded_size(uint64_t v)
{
    if (v < 0xFDULL)             return 1;
    else if (v <= 0xFFFFULL)     return 3;
    else if (v <= 0xFFFFFFFFULL) return 5;
    else                         return 9;
}

static uint8_t *_varint_write(uint8_t *dst, uint64_t v)
{
    if (v < 0xFDULL) {
        *dst++ = (uint8_t)v;
    } else if (v <= 0xFFFFULL) {
        *dst++ = 0xFD;
        uint16_t le = (uint16_t)v;
        memcpy(dst, &le, sizeof(le));
        dst += sizeof(le);
    } else if (v <= 0xFFFFFFFFULL) {
        *dst++ = 0xFE;
        uint32_t le = (uint32_t)v;
        memcpy(dst, &le, sizeof(le));
        dst += sizeof(le);
    } else {
        *dst++ = 0xFF;
        uint64_t le = v;
        memcpy(dst, &le, sizeof(le));
        dst += sizeof(le);
    }
    return dst;
}

static const uint8_t *_varint_read(const uint8_t *src,
                                   const uint8_t *end,
                                   uint64_t *v_out)
{
    if (src >= end) return NULL;
    uint8_t prefix = *src++;
    if (prefix < 0xFDU) {
        *v_out = prefix;
        return src;
    } else if (prefix == 0xFD) {
        if (src + 2 > end) return NULL;
        uint16_t le;
        memcpy(&le, src, 2); src += 2;
        *v_out = le;
    } else if (prefix == 0xFE) {
        if (src + 4 > end) return NULL;
        uint32_t le;
        memcpy(&le, src, 4); src += 4;
        *v_out = le;
    } else {
        if (src + 8 > end) return NULL;
        uint64_t le;
        memcpy(&le, src, 8); src += 8;
        *v_out = le;
    }
    return src;
}

/* Compute double-SHA-256 */
static void _sha256d(const uint8_t *data, size_t len,
                     uint8_t hash_out[BLOCK_HASH_SIZE])
{
    uint8_t tmp[SHA256_DIGEST_LENGTH];
    SHA256(data, len, tmp);
    SHA256(tmp, sizeof(tmp), hash_out);
}

/* Merkle root calculation (simple, iterative) */
static int _merkle_root(struct ledger_tx **txs, size_t n,
                        uint8_t root_out[BLOCK_HASH_SIZE])
{
    if (n == 0 || txs == NULL) return BLOCK_ERR_PARAM;

    /* Allocate scratch space for level hashing */
    uint8_t (*hashes)[BLOCK_HASH_SIZE] = malloc(n * BLOCK_HASH_SIZE);
    if (!hashes) return BLOCK_ERR_MEM;

    /* Seed with transaction hashes */
    for (size_t i = 0; i < n; ++i) {
        if (ledger_tx_hash(txs[i], hashes[i]) != 0) {
            free(hashes);
            return BLOCK_ERR_HASH;
        }
    }

    size_t level_count = n;
    while (level_count > 1) {
        size_t next_count = (level_count + 1) / 2;
        for (size_t i = 0; i < next_count; ++i) {
            /* Duplicate last hash if odd number */
            const uint8_t *left  = hashes[i * 2];
            const uint8_t *right = (i * 2 + 1 < level_count)
                                   ? hashes[i * 2 + 1]
                                   : hashes[i * 2];
            uint8_t concat[BLOCK_HASH_SIZE * 2];
            memcpy(concat, left,  BLOCK_HASH_SIZE);
            memcpy(concat + BLOCK_HASH_SIZE, right, BLOCK_HASH_SIZE);
            _sha256d(concat, sizeof(concat), hashes[i]);
        }
        level_count = next_count;
    }
    memcpy(root_out, hashes[0], BLOCK_HASH_SIZE);
    free(hashes);
    return BLOCK_SUCCESS;
}

/* Block header hashing */
static void _compute_block_hash(const block_header_t *hdr,
                                uint8_t hash_out[BLOCK_HASH_SIZE])
{
    _sha256d((const uint8_t *)hdr, sizeof(*hdr), hash_out);
}

/* ----------  Public API Implementations  ---------- */
int block_init(block_t            *blk,
               const uint8_t       prev_hash[BLOCK_HASH_SIZE],
               uint64_t            height,
               uint32_t            bits)
{
    if (!blk) return BLOCK_ERR_PARAM;
    memset(blk, 0, sizeof(*blk));

    blk->header.version = BLOCK_DEFAULT_VERSION;

    if (prev_hash)
        memcpy(blk->header.prev_hash, prev_hash, BLOCK_HASH_SIZE);

    blk->header.timestamp = (uint64_t)time(NULL);
    blk->header.bits      = bits;
    blk->header.nonce     = 0;          /* mined later */

    blk->height       = height;
    blk->tx_capacity  = _BLOCK_MIN_TX_CAPACITY;
    blk->txs          = calloc(blk->tx_capacity, sizeof(struct ledger_tx *));
    if (!blk->txs) return BLOCK_ERR_MEM;

    return BLOCK_SUCCESS;
}

int block_add_tx(block_t *blk, struct ledger_tx *tx)
{
    if (!blk || !tx) return BLOCK_ERR_PARAM;
    if (blk->finalized) return BLOCK_ERR_VALIDATION;
    if (blk->tx_count >= BLOCK_MAX_TX) return BLOCK_ERR_TX_LIMIT;

    /* Grow capacity if needed */
    if (blk->tx_count == blk->tx_capacity) {
        size_t new_cap = blk->tx_capacity * _BLOCK_GROWTH_FACTOR;
        if (new_cap == 0) new_cap = _BLOCK_MIN_TX_CAPACITY;
        struct ledger_tx **new_arr = realloc(blk->txs,
                                    new_cap * sizeof(struct ledger_tx *));
        if (!new_arr) return BLOCK_ERR_MEM;
        blk->txs = new_arr;
        blk->tx_capacity = new_cap;
    }

    blk->txs[blk->tx_count++] = tx;
    blk->hash_valid = false;
    return BLOCK_SUCCESS;
}

int block_finalize(block_t *blk)
{
    if (!blk) return BLOCK_ERR_PARAM;
    if (blk->finalized) return BLOCK_SUCCESS;
    if (blk->tx_count == 0) return BLOCK_ERR_VALIDATION;

    int rc = _merkle_root(blk->txs, blk->tx_count, blk->header.merkle_root);
    if (rc != BLOCK_SUCCESS) return rc;

    _compute_block_hash(&blk->header, blk->hash);
    blk->hash_valid = true;
    blk->finalized  = true;
    return BLOCK_SUCCESS;
}

int block_validate(const block_t *blk)
{
    if (!blk || !blk->finalized) return BLOCK_ERR_PARAM;

    /* Validate merkle root */
    uint8_t root[BLOCK_HASH_SIZE];
    int rc = _merkle_root((struct ledger_tx **)blk->txs,
                          blk->tx_count, root);
    if (rc != BLOCK_SUCCESS) return rc;
    if (memcmp(root, blk->header.merkle_root, BLOCK_HASH_SIZE) != 0)
        return BLOCK_ERR_VALIDATION;

    /* Validate cached hash */
    uint8_t calc_hash[BLOCK_HASH_SIZE];
    _compute_block_hash(&blk->header, calc_hash);
    if (memcmp(calc_hash, blk->hash, BLOCK_HASH_SIZE) != 0)
        return BLOCK_ERR_HASH;

    /* Validate each transaction (delegated) */
    for (size_t i = 0; i < blk->tx_count; ++i) {
        /* Transaction-level validation stub.
         * ledger_tx_validate() could be invoked here if available. */
        (void)i;
    }
    return BLOCK_SUCCESS;
}

int block_serialize(const block_t *blk,
                    uint8_t **buf_out, size_t *len_out)
{
    if (!blk || !buf_out || !len_out) return BLOCK_ERR_PARAM;
    if (!blk->finalized) return BLOCK_ERR_VALIDATION;

    /* First determine required buffer size */
    size_t size = sizeof(block_header_t);
    size += _varint_encoded_size(blk->tx_count);

    for (size_t i = 0; i < blk->tx_count; ++i) {
        uint8_t *tx_buf = NULL; size_t tx_len = 0;
        if (ledger_tx_serialize(blk->txs[i], &tx_buf, &tx_len) != 0)
            return BLOCK_ERR_SERIALIZATION;
        size += _varint_encoded_size(tx_len) + tx_len;
        free(tx_buf); /* length only */
    }

    uint8_t *buf = malloc(size);
    if (!buf) return BLOCK_ERR_MEM;
    uint8_t *ptr = buf;

    /* Header */
    memcpy(ptr, &blk->header, sizeof(blk->header));
    ptr += sizeof(blk->header);

    /* Transaction list length */
    ptr = _varint_write(ptr, blk->tx_count);

    /* Transactions */
    for (size_t i = 0; i < blk->tx_count; ++i) {
        uint8_t *tx_buf = NULL; size_t tx_len = 0;
        if (ledger_tx_serialize(blk->txs[i], &tx_buf, &tx_len) != 0) {
            free(buf);
            return BLOCK_ERR_SERIALIZATION;
        }
        ptr = _varint_write(ptr, tx_len);
        memcpy(ptr, tx_buf, tx_len);
        ptr += tx_len;
        free(tx_buf);
    }

    /* Sanity check */
    if ((size_t)(ptr - buf) != size) {
        free(buf);
        return BLOCK_ERR_SERIALIZATION;
    }

    *buf_out = buf;
    *len_out = size;
    return BLOCK_SUCCESS;
}

int block_deserialize(const uint8_t *buf, size_t buf_len,
                      block_t *blk_out)
{
    if (!buf || !blk_out) return BLOCK_ERR_PARAM;
    const uint8_t *ptr = buf, *end = buf + buf_len;

    if (ptr + sizeof(block_header_t) > end) return BLOCK_ERR_SERIALIZATION;
    block_header_t hdr;
    memcpy(&hdr, ptr, sizeof(hdr));
    ptr += sizeof(hdr);

    /* Read tx_count */
    uint64_t tx_count = 0;
    ptr = _varint_read(ptr, end, &tx_count);
    if (!ptr) return BLOCK_ERR_SERIALIZATION;
    if (tx_count > BLOCK_MAX_TX) return BLOCK_ERR_TX_LIMIT;

    /* Init block */
    int rc = block_init(blk_out, hdr.prev_hash, 0 /* height unknown */, hdr.bits);
    if (rc != BLOCK_SUCCESS) return rc;
    blk_out->header = hdr;  /* Override timestamp, etc. */
    blk_out->tx_count = 0;  /* Will be rebuilt */

    /* Deserialize each transaction */
    for (uint64_t i = 0; i < tx_count; ++i) {
        uint64_t tx_len = 0;
        ptr = _varint_read(ptr, end, &tx_len);
        if (!ptr || ptr + tx_len > end) {
            block_free(blk_out);
            return BLOCK_ERR_SERIALIZATION;
        }
        struct ledger_tx *tx = NULL;
        if (ledger_tx_deserialize(ptr, (size_t)tx_len, &tx) != 0) {
            block_free(blk_out);
            return BLOCK_ERR_SERIALIZATION;
        }
        ptr += tx_len;
        rc = block_add_tx(blk_out, tx);
        if (rc != BLOCK_SUCCESS) {
            ledger_tx_free(tx);
            block_free(blk_out);
            return rc;
        }
    }

    blk_out->finalized  = true;
    _compute_block_hash(&blk_out->header, blk_out->hash);
    blk_out->hash_valid = true;
    return BLOCK_SUCCESS;
}

void block_free(block_t *blk)
{
    if (!blk) return;
    for (size_t i = 0; i < blk->tx_count; ++i) {
        ledger_tx_free(blk->txs[i]);
    }
    free(blk->txs);
    memset(blk, 0, sizeof(*blk));
}

#endif /* BLOCK_IMPLEMENTATION */
#endif /* HOLOCANVAS_LEDGER_CORE_BLOCK_H */
