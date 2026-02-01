/*
 * EduPay Ledger Academy
 * Shared Kernel - Infrastructure - Crypto
 * ------------------------------------------------------------
 * hash.h
 *
 * Cryptographic digest utilities leveraged throughout the
 * platform for signing, integrity-verification, audit-trail
 * sealing, and deterministic Saga compensation keys.
 *
 * The API purposefully mirrors a subset of OpenSSL’s EVP
 * interface while shielding the rest of the codebase from the
 * underlying crypto provider.  Should instructors wish to swap
 * OpenSSL for a FIPS build or a different provider entirely,
 * only this translation layer needs to be replaced.
 *
 * Author: EduPay Ledger Academy Core Team
 * License: MIT
 */

#ifndef EDUPAY_SHARED_KERNEL_CRYPTO_HASH_H
#define EDUPAY_SHARED_KERNEL_CRYPTO_HASH_H

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*  Standard Library                                                          */
/* ------------------------------------------------------------------------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>

/* ------------------------------------------------------------------------- */
/*  Third-Party Dependencies                                                  */
/* ------------------------------------------------------------------------- */
#include <openssl/evp.h>
#include <openssl/sha.h>
#include <openssl/blake2.h>

/* ------------------------------------------------------------------------- */
/*  Public Types                                                              */
/* ------------------------------------------------------------------------- */

/*
 * Algorithms supported by the shared-kernel.  Additions require
 * no changes to callers—just append here and update the switch
 * in ephash__md_from_algorithm().
 */
typedef enum
{
    EP_HASH_SHA256       = 0,
    EP_HASH_SHA3_256     = 1,
    EP_HASH_BLAKE2B_256  = 2
} ep_hash_algorithm_t;

/*
 * Error/return codes.
 */
typedef enum
{
    EP_HASH_OK                 =  0,
    EP_HASH_ERR_INVALID_ALGO   = -1,
    EP_HASH_ERR_NULL_PTR       = -2,
    EP_HASH_ERR_OPENSSL        = -3,
    EP_HASH_ERR_SHORT_BUFFER   = -4
} ep_hash_result_t;

/*
 * Opaque hashing context.  Treat as non-movable once initialised.
 */
typedef struct
{
    ep_hash_algorithm_t algorithm;
    EVP_MD_CTX         *evp_ctx;
} ep_hash_ctx_t;

/* ------------------------------------------------------------------------- */
/*  Compile-Time Constants                                                    */
/* ------------------------------------------------------------------------- */

#define EP_HASH_SHA256_SIZE      32U
#define EP_HASH_SHA3_256_SIZE    32U
#define EP_HASH_BLAKE2B_256_SIZE 32U
#define EP_HASH_MAX_DIGEST_SIZE  64U /* accommodates SHA-512 et al.          */

/* ------------------------------------------------------------------------- */
/*  Utility Macros                                                            */
/* ------------------------------------------------------------------------- */

/*
 * Compile-time mapping from algorithm enum to digest size.
 */
#define EP_HASH_DIGEST_SIZE(alg)            \
    ((alg) == EP_HASH_SHA256      ? EP_HASH_SHA256_SIZE     : \
     (alg) == EP_HASH_SHA3_256    ? EP_HASH_SHA3_256_SIZE   : \
     (alg) == EP_HASH_BLAKE2B_256 ? EP_HASH_BLAKE2B_256_SIZE: \
                                    0)

/* ------------------------------------------------------------------------- */
/*  Internal Helpers (static inline)                                          */
/* ------------------------------------------------------------------------- */

static inline const EVP_MD *
ephash__md_from_algorithm(ep_hash_algorithm_t alg)
{
    switch (alg)
    {
        case EP_HASH_SHA256:      return EVP_sha256();
        case EP_HASH_SHA3_256:    return EVP_sha3_256();
#if OPENSSL_VERSION_NUMBER >= 0x10100000L /* BLAKE2 requires OpenSSL ≥1.1.0 */
        case EP_HASH_BLAKE2B_256: return EVP_blake2b256();
#endif
        default:                  return NULL;
    }
}

/* One-time OpenSSL initialisation guard. */
static inline void
ephash__openssl_init_once(void)
{
    static bool done = false;
    if (!done)
    {
        /* OpenSSL 1.1+ self-initialises, but we call this for clarity. */
        OPENSSL_init_crypto(0, NULL);
        done = true;
    }
}

/* ------------------------------------------------------------------------- */
/*  Public API                                                                */
/* ------------------------------------------------------------------------- */

/*
 * Initialise a hashing context.
 *
 * Parameters:
 *   ctx  – caller-allocated, non-NULL
 *   alg  – algorithm to use
 *
 * Returns:
 *   EP_HASH_OK on success, negative error code on failure.
 */
static inline ep_hash_result_t
ep_hash_init(ep_hash_ctx_t *ctx, ep_hash_algorithm_t alg)
{
    if (!ctx)
        return EP_HASH_ERR_NULL_PTR;

    const EVP_MD *md = ephash__md_from_algorithm(alg);
    if (!md)
        return EP_HASH_ERR_INVALID_ALGO;

    ephash__openssl_init_once();

    ctx->evp_ctx = EVP_MD_CTX_new();
    if (!ctx->evp_ctx)
        return EP_HASH_ERR_OPENSSL;

    if (EVP_DigestInit_ex(ctx->evp_ctx, md, NULL) != 1)
    {
        EVP_MD_CTX_free(ctx->evp_ctx);
        ctx->evp_ctx = NULL;
        return EP_HASH_ERR_OPENSSL;
    }
    ctx->algorithm = alg;
    return EP_HASH_OK;
}

/*
 * Incrementally add data to hash.
 */
static inline ep_hash_result_t
ep_hash_update(ep_hash_ctx_t *ctx, const void *data, size_t len)
{
    if (!ctx || !ctx->evp_ctx || (!data && len))
        return EP_HASH_ERR_NULL_PTR;

    if (EVP_DigestUpdate(ctx->evp_ctx, data, len) != 1)
        return EP_HASH_ERR_OPENSSL;

    return EP_HASH_OK;
}

/*
 * Finalise digest and free underlying EVP resources.
 *
 * out_digest  – destination buffer, size ≥ EP_HASH_DIGEST_SIZE(ctx->algorithm)
 * out_len     – optional; receives number of bytes written
 */
static inline ep_hash_result_t
ep_hash_final(ep_hash_ctx_t *ctx, uint8_t *out_digest, size_t *out_len)
{
    if (!ctx || !ctx->evp_ctx || !out_digest)
        return EP_HASH_ERR_NULL_PTR;

    unsigned int tmp_len = 0;
    if (EVP_DigestFinal_ex(ctx->evp_ctx, out_digest, &tmp_len) != 1)
    {
        EVP_MD_CTX_free(ctx->evp_ctx);
        ctx->evp_ctx = NULL;
        return EP_HASH_ERR_OPENSSL;
    }

    if (out_len)
        *out_len = (size_t)tmp_len;

    EVP_MD_CTX_free(ctx->evp_ctx);
    ctx->evp_ctx = NULL;
    return EP_HASH_OK;
}

/*
 * Convenience one-shot hashing function.
 *
 * out_len must point to caller-provided size_t containing available
 * buffer length.  It will be overwritten with actual digest size.
 */
static inline ep_hash_result_t
ep_hash_compute(ep_hash_algorithm_t alg,
                const void        *data,
                size_t             data_len,
                uint8_t           *out_digest,
                size_t            *out_len)
{
    if (!data && data_len)
        return EP_HASH_ERR_NULL_PTR;

    size_t required_len = (size_t)EP_HASH_DIGEST_SIZE(alg);
    if (!out_digest || !out_len || *out_len < required_len)
        return EP_HASH_ERR_SHORT_BUFFER;

    ep_hash_ctx_t ctx;
    ep_hash_result_t rc = ep_hash_init(&ctx, alg);
    if (rc != EP_HASH_OK) return rc;

    rc = ep_hash_update(&ctx, data, data_len);
    if (rc != EP_HASH_OK) return rc;

    rc = ep_hash_final(&ctx, out_digest, out_len);
    return rc;
}

/*
 * Convert digest bytes to hexadecimal C-string.
 *
 * hex_buf_size must be >= digest_len * 2 + 1 (NUL terminator).
 */
static inline ep_hash_result_t
ep_hash_to_hex(const uint8_t *digest,
               size_t         digest_len,
               char          *hex_buf,
               size_t         hex_buf_size)
{
    static const char HEX[] = "0123456789abcdef";

    if (!digest || !hex_buf)
        return EP_HASH_ERR_NULL_PTR;

    if (hex_buf_size < (digest_len * 2U + 1U))
        return EP_HASH_ERR_SHORT_BUFFER;

    for (size_t i = 0; i < digest_len; ++i)
    {
        hex_buf[i*2]     = HEX[(digest[i] >> 4) & 0xF];
        hex_buf[i*2 + 1] = HEX[digest[i] & 0xF];
    }
    hex_buf[digest_len * 2U] = '\0';
    return EP_HASH_OK;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDUPAY_SHARED_KERNEL_CRYPTO_HASH_H */
