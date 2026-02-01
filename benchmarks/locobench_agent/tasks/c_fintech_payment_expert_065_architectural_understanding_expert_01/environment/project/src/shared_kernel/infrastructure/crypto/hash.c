```c
/**
 * @file hash.c
 * @author
 *      EduPay Ledger Academy – Shared-Kernel Team
 *
 * @brief
 *      Thin, defence-in-depth wrapper around OpenSSL’s generic EVP
 *      interface for computing and verifying cryptographic hashes.
 *
 *      The helper functions centralise hardening measures (constant-time
 *      comparisons, parameter validation, secure memory cleansing) so that
 *      higher-level payment and compliance modules do not have to interact
 *      with OpenSSL directly.  Only modern, collision-resistant algorithms
 *      are exposed (SHA-256/384/512 and BLAKE2b-512).  Legacy or broken
 *      digests (MD5, SHA-1, etc.) are deliberately ommitted to comply
 *      with PCI-DSS v4 and PSD2-RTS requirements.
 *
 *      THREAD-SAFETY:
 *          OpenSSL >= 1.1.0 is fully thread-safe once initialised.
 *          The initialisation is performed lazily on first use by this
 *          module and is idempotent.  No additional locking is required.
 */

#include "hash.h"          /* Project-internal public header */
#include <openssl/evp.h>    /* Generic EVP digest interface   */
#include <openssl/err.h>
#include <openssl/crypto.h>

#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* ------------------------------------------------------------------------- */
/*  Constant definitions                                                     */
/* ------------------------------------------------------------------------- */

#define MAX_DIGEST_SIZE     64  /* SHA-512 & BLAKE2b-512 output length */

/* ------------------------------------------------------------------------- */
/*  Private utilities                                                        */
/* ------------------------------------------------------------------------- */

/**
 * Perform a constant-time comparison between two buffers.
 *
 * @return 1 if equal, 0 otherwise.
 */
static int
ct_compare(const uint8_t *a, const uint8_t *b, size_t len)
{
    /* xor-accumulate so timing does not depend on the first mismatch */
    uint8_t diff = 0;

    for (size_t i = 0; i < len; ++i) {
        diff |= a[i] ^ b[i];
    }

    /* diff == 0 → buffers are equal */
    return diff == 0;
}

/**
 * Map algorithm identifiers to OpenSSL digest implementations.
 *
 * @param[in]  algorithm Either canonical name ("SHA256") or lower/upper
 *                       case alias ("sha-256", "sha512", "blake2b").
 * @param[out] md_out    Returns a pointer to the OpenSSL EVP_MD struct.
 *
 * @return HASH_OK on success, HASH_ERR_ALGO_UNSUPPORTED otherwise.
 */
static hash_status_t
resolve_algorithm(const char *algorithm, const EVP_MD **md_out)
{
    if (!algorithm || !md_out) {
        return HASH_ERR_INVALID_ARGUMENT;
    }

    /* Normalise to upper case for comparison */
    char norm[32] = { 0 };
    size_t len = strlen(algorithm);
    if (len >= sizeof(norm)) {
        return HASH_ERR_ALGO_UNSUPPORTED; /* name too long */
    }

    for (size_t i = 0; i < len; ++i) {
        norm[i] = (char)toupper((int)algorithm[i]);
    }

    const EVP_MD *md = NULL;

    if (strcmp(norm, "SHA256") == 0 || strcmp(norm, "SHA-256") == 0) {
        md = EVP_sha256();
    } else if (strcmp(norm, "SHA384") == 0 || strcmp(norm, "SHA-384") == 0) {
        md = EVP_sha384();
    } else if (strcmp(norm, "SHA512") == 0 || strcmp(norm, "SHA-512") == 0) {
        md = EVP_sha512();
    } else if (strcmp(norm, "BLAKE2B") == 0 || strcmp(norm, "BLAKE2B-512") == 0) {
#if OPENSSL_VERSION_NUMBER >= 0x10100000L
        md = EVP_blake2b512();
#else
        md = NULL; /* Not available on legacy OpenSSL */
#endif
    }

    if (!md) {
        return HASH_ERR_ALGO_UNSUPPORTED;
    }

    *md_out = md;
    return HASH_OK;
}

/**
 * Securely wipe a buffer using OpenSSL's OPENSSL_cleanse.
 */
static void
secure_wipe(void *ptr, size_t len)
{
    if (ptr && len) {
        OPENSSL_cleanse(ptr, len);
    }
}

/* ------------------------------------------------------------------------- */
/*  Public API implementation                                                */
/* ------------------------------------------------------------------------- */

hash_status_t
hash_init(void)
{
    /* OpenSSL >= 1.1.0 performs implicit initialisation; keep for 1.0.x */
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    OpenSSL_add_all_algorithms();
    ERR_load_crypto_strings();
#endif
    return HASH_OK;
}

void
hash_deinit(void)
{
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    EVP_cleanup();
    ERR_free_strings();
#endif
}

/**
 * Compute a digest of (data, data_len) using the selected algorithm.
 *
 * The caller must ensure that out_digest has at least MAX_DIGEST_SIZE bytes.
 *
 * @param algorithm         Algorithm name ("SHA256", "SHA512", …).
 * @param data              Pointer to data to hash.
 * @param data_len          Length of data.
 * @param[out] out_digest   Buffer to receive the binary digest.
 * @param[out] out_len      Receives the actual digest length.
 */
hash_status_t
hash_compute(const char  *algorithm,
             const void  *data,
             size_t       data_len,
             uint8_t     *out_digest,
             size_t      *out_len)
{
    if (!algorithm || !data || !out_digest || !out_len) {
        return HASH_ERR_INVALID_ARGUMENT;
    }

    const EVP_MD *md = NULL;
    hash_status_t status = resolve_algorithm(algorithm, &md);
    if (status != HASH_OK) {
        return status;
    }

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) {
        return HASH_ERR_INTERNAL;
    }

    if (EVP_DigestInit_ex(ctx, md, NULL) != 1 ||
        EVP_DigestUpdate(ctx, data, data_len) != 1 ||
        EVP_DigestFinal_ex(ctx, out_digest, (unsigned int *)out_len) != 1)
    {
        EVP_MD_CTX_free(ctx);
        return HASH_ERR_OPENSSL;
    }

    EVP_MD_CTX_free(ctx);
    return HASH_OK;
}

/**
 * Convenience wrapper: compute digest and encode as lower-case hex string.
 *
 * @param[out] out_hex      Must be at least (2*MAX_DIGEST_SIZE + 1) bytes.
 */
hash_status_t
hash_compute_hex(const char  *algorithm,
                 const void  *data,
                 size_t       data_len,
                 char        *out_hex,
                 size_t       out_hex_len)
{
    if (!out_hex || out_hex_len < (2 * MAX_DIGEST_SIZE + 1)) {
        return HASH_ERR_BUFFER_TOO_SMALL;
    }

    uint8_t digest[MAX_DIGEST_SIZE];
    size_t  digest_len = 0;

    hash_status_t rc = hash_compute(algorithm, data, data_len,
                                    digest, &digest_len);
    if (rc != HASH_OK) {
        return rc;
    }

    /* Convert to hex */
    static const char hex_tbl[] = "0123456789abcdef";
    for (size_t i = 0; i < digest_len; ++i) {
        out_hex[i * 2]     = hex_tbl[digest[i] >> 4];
        out_hex[i * 2 + 1] = hex_tbl[digest[i] & 0x0F];
    }
    out_hex[digest_len * 2] = '\0';

    /* Wipe stack copy of digest */
    secure_wipe(digest, sizeof(digest));

    return HASH_OK;
}

/**
 * Verify that the provided digest equals the freshly computed one.
 *
 * @return HASH_OK if digests match,
 *         HASH_ERR_VERIFICATION_FAILED on mismatch.
 */
hash_status_t
hash_verify(const char  *algorithm,
            const void  *data,
            size_t       data_len,
            const uint8_t *expected_digest,
            size_t        expected_len)
{
    if (!algorithm || !data || !expected_digest) {
        return HASH_ERR_INVALID_ARGUMENT;
    }

    uint8_t digest[MAX_DIGEST_SIZE];
    size_t  digest_len = 0;

    hash_status_t rc = hash_compute(algorithm, data, data_len,
                                    digest, &digest_len);
    if (rc != HASH_OK) {
        return rc;
    }

    int equal = (digest_len == expected_len) &&
                ct_compare(digest, expected_digest, expected_len);

    /* Wipe stack copy of digest */
    secure_wipe(digest, sizeof(digest));

    return equal ? HASH_OK : HASH_ERR_VERIFICATION_FAILED;
}

/**
 * Same as hash_verify, but takes the expected value as a hex string.
 */
hash_status_t
hash_verify_hex(const char *algorithm,
                const void *data,
                size_t      data_len,
                const char *expected_hex)
{
    if (!expected_hex) {
        return HASH_ERR_INVALID_ARGUMENT;
    }

    size_t exp_len = strlen(expected_hex);
    if (exp_len % 2 != 0 || exp_len / 2 > MAX_DIGEST_SIZE) {
        return HASH_ERR_INVALID_ARGUMENT;
    }

    /* Convert hex -> binary */
    uint8_t expected_bin[MAX_DIGEST_SIZE] = { 0 };

    for (size_t i = 0; i < exp_len / 2; ++i) {
        char byte_str[3] = { expected_hex[2 * i], expected_hex[2 * i + 1], '\0' };
        char *endptr = NULL;
        long val = strtol(byte_str, &endptr, 16);
        if (*endptr != '\0' || val < 0 || val > 0xFF) {
            return HASH_ERR_INVALID_ARGUMENT;
        }
        expected_bin[i] = (uint8_t)val;
    }

    return hash_verify(algorithm,
                       data,
                       data_len,
                       expected_bin,
                       exp_len / 2);
}

/* ------------------------------------------------------------------------- */
/*  Diagnostic helpers                                                       */
/* ------------------------------------------------------------------------- */

/**
 * Convert a hash_status_t to human-readable text.
 */
const char *
hash_strerror(hash_status_t code)
{
    switch (code) {
        case HASH_OK:                         return "Ok";
        case HASH_ERR_INVALID_ARGUMENT:       return "Invalid argument";
        case HASH_ERR_ALGO_UNSUPPORTED:       return "Algorithm not supported";
        case HASH_ERR_OPENSSL:                return "OpenSSL failure";
        case HASH_ERR_VERIFICATION_FAILED:    return "Verification failed";
        case HASH_ERR_BUFFER_TOO_SMALL:       return "Buffer too small";
        case HASH_ERR_INTERNAL:               return "Internal error";
        default:                              return "Unknown error";
    }
}

/**
 * Pushes the last OpenSSL error onto stderr in a developer-friendly format.
 * Only compiled in DEBUG builds to avoid leaking internals in production logs.
 */
#ifdef DEBUG
void
hash_dump_openssl_error(const char *msg)
{
    unsigned long err;
    while ((err = ERR_get_error()) != 0) {
        fprintf(stderr, "hash: %s: %s\n", msg, ERR_error_string(err, NULL));
    }
}
#endif

/* ------------------------------------------------------------------------- */
/*  End of file                                                              */
/* ------------------------------------------------------------------------- */
```