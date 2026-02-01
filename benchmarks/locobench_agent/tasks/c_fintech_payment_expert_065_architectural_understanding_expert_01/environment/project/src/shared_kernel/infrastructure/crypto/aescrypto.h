#ifndef EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_INFRASTRUCTURE_CRYPTO_AESCRYPTO_H
#define EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_INFRASTRUCTURE_CRYPTO_AESCRYPTO_H
/*
 * EduPay Ledger Academy – Shared Kernel
 * -------------------------------------
 * AES-GCM convenience wrapper used by bounded-context modules that require
 * authenticated encryption (e.g. Audit_Trail, PCI token vault, PSD2 flows).
 *
 * The API purposefully avoids exposing OpenSSL internals to callers so that
 * professors may swap the provider (e.g. BoringSSL, libsodium, hardware-HSM)
 * without disrupting domain code.
 *
 * NOTE:
 *   • All functions are declared `static inline` so that this header is
 *     self-contained (source+header) as requested by the coursework tooling.
 *   • Link every translation unit with `-lcrypto`.
 *
 * Thread-safety: OpenSSL ≥1.1 is thread-safe once initialized; we expose
 * `aescrypto_global_init()` as an explicit initialization step for clarity.
 */

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------- */
/*                               Public Constants                             */
/* -------------------------------------------------------------------------- */

#define AESCRYPTO_KEY_BYTES  32U  /* AES-256 */
#define AESCRYPTO_IV_BYTES   12U  /* Recommended IV size for GCM            */
#define AESCRYPTO_TAG_BYTES  16U  /* 128-bit authentication tag             */

/* Error/return codes                                                         */
#define AESCRYPTO_OK               0
#define AESCRYPTO_ERR_ARGUMENT    -1
#define AESCRYPTO_ERR_INIT        -2
#define AESCRYPTO_ERR_RAND        -3
#define AESCRYPTO_ERR_CRYPTO      -4
#define AESCRYPTO_ERR_AUTH        -5
#define AESCRYPTO_ERR_INTERNAL    -128  /* Catch-all                        */

/* -------------------------------------------------------------------------- */
/*                                Data Types                                  */
/* -------------------------------------------------------------------------- */

/*
 * aescrypto_ctx_t
 * ----------------
 * Holds an AES-256-GCM key/IV pair. Allocate this on the stack where possible.
 */
typedef struct
{
    uint8_t key[AESCRYPTO_KEY_BYTES];
    uint8_t iv [AESCRYPTO_IV_BYTES];
} aescrypto_ctx_t;

/* -------------------------------------------------------------------------- */
/*                              Initialization                                */
/* -------------------------------------------------------------------------- */

/*
 * aescrypto_global_init
 * ---------------------
 * Idempotent library initialization wrapper.
 *
 * Returns: AESCRYPTO_OK on success, error code otherwise.
 */
static inline int
aescrypto_global_init(void)
{
    /*
     * OPENSSL_init_crypto() may be called multiple times; it will NOP after
     * the first successful call.
     */
    if (OPENSSL_init_crypto(0, NULL) != 1)
        return AESCRYPTO_ERR_INIT;

    return AESCRYPTO_OK;
}

/*
 * aescrypto_random_key_iv
 * -----------------------
 * Generate a cryptographically strong random key/IV pair.
 *
 * ctx  [out] – context to populate.
 */
static inline int
aescrypto_random_key_iv(aescrypto_ctx_t *ctx)
{
    if (!ctx) return AESCRYPTO_ERR_ARGUMENT;

    if (RAND_bytes(ctx->key, sizeof ctx->key) != 1)
        return AESCRYPTO_ERR_RAND;

    if (RAND_bytes(ctx->iv, sizeof ctx->iv) != 1)
        return AESCRYPTO_ERR_RAND;

    return AESCRYPTO_OK;
}

/* -------------------------------------------------------------------------- */
/*                          Authenticated Encryption                           */
/* -------------------------------------------------------------------------- */

/*
 * aescrypto_encrypt
 * -----------------
 * Authenticated encryption (AES-256-GCM).
 *
 * Parameters
 *   ctx            – key/IV pair generated via aescrypto_random_key_iv()
 *   plaintext      – buffer to encrypt
 *   plaintext_len  – length of plaintext
 *   aad            – additional authenticated data (may be NULL if aad_len=0)
 *   aad_len        – length of AAD
 *   ciphertext     – output buffer (same length as plaintext)
 *   tag            – output 16-byte GCM tag
 *
 * Returns
 *   AESCRYPTO_OK           – success
 *   AESCRYPTO_ERR_CRYPTO   – encryption failure
 *   AESCRYPTO_ERR_ARGUMENT – invalid input
 */
static inline int
aescrypto_encrypt(const aescrypto_ctx_t *ctx,
                  const uint8_t *plaintext,
                  size_t plaintext_len,
                  const uint8_t *aad,
                  size_t aad_len,
                  uint8_t *ciphertext,
                  uint8_t tag[AESCRYPTO_TAG_BYTES])
{
    if (!ctx || !plaintext || !ciphertext || !tag)
        return AESCRYPTO_ERR_ARGUMENT;

    int rc              = AESCRYPTO_ERR_INTERNAL;
    int out_len         = 0;
    EVP_CIPHER_CTX *cpx = EVP_CIPHER_CTX_new();
    if (!cpx) return AESCRYPTO_ERR_CRYPTO;

    do
    {
        if (EVP_EncryptInit_ex(cpx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_CIPHER_CTX_ctrl(cpx, EVP_CTRL_GCM_SET_IVLEN,
                                AESCRYPTO_IV_BYTES, NULL) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_EncryptInit_ex(cpx, NULL, NULL, ctx->key, ctx->iv) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (aad && aad_len > 0)
        {
            if (EVP_EncryptUpdate(cpx, NULL, &out_len, aad,
                                  (int)aad_len) != 1)
            { rc = AESCRYPTO_ERR_CRYPTO; break; }
        }

        if (EVP_EncryptUpdate(cpx, ciphertext, &out_len,
                              plaintext, (int)plaintext_len) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        /*
         * Finalize encryption. No ciphertext out for GCM; merely flushes.
         */
        if (EVP_EncryptFinal_ex(cpx, ciphertext + out_len, &out_len) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_CIPHER_CTX_ctrl(cpx, EVP_CTRL_GCM_GET_TAG,
                                AESCRYPTO_TAG_BYTES, tag) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        rc = AESCRYPTO_OK;

    } while (0);

    EVP_CIPHER_CTX_free(cpx);
    return rc;
}

/*
 * aescrypto_decrypt
 * -----------------
 * Authenticated decryption (AES-256-GCM).
 *
 * Parameters
 *   ctx             – key/IV pair
 *   ciphertext      – buffer to decrypt
 *   ciphertext_len  – length of ciphertext
 *   aad             – additional authenticated data (must be same as encrypt)
 *   aad_len         – length of AAD
 *   tag             – 16-byte authentication tag produced by encryption
 *   plaintext_out   – output buffer (same length as ciphertext)
 *
 * Returns
 *   AESCRYPTO_OK         – success
 *   AESCRYPTO_ERR_AUTH   – authentication failed (tag mismatch)
 *   AESCRYPTO_ERR_CRYPTO – other crypto failure
 */
static inline int
aescrypto_decrypt(const aescrypto_ctx_t *ctx,
                  const uint8_t *ciphertext,
                  size_t ciphertext_len,
                  const uint8_t *aad,
                  size_t aad_len,
                  const uint8_t tag[AESCRYPTO_TAG_BYTES],
                  uint8_t *plaintext_out)
{
    if (!ctx || !ciphertext || !plaintext_out || !tag)
        return AESCRYPTO_ERR_ARGUMENT;

    int rc              = AESCRYPTO_ERR_INTERNAL;
    int out_len         = 0;
    EVP_CIPHER_CTX *cpx = EVP_CIPHER_CTX_new();
    if (!cpx) return AESCRYPTO_ERR_CRYPTO;

    do
    {
        if (EVP_DecryptInit_ex(cpx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_CIPHER_CTX_ctrl(cpx, EVP_CTRL_GCM_SET_IVLEN,
                                AESCRYPTO_IV_BYTES, NULL) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_DecryptInit_ex(cpx, NULL, NULL, ctx->key, ctx->iv) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (aad && aad_len > 0)
        {
            if (EVP_DecryptUpdate(cpx, NULL, &out_len, aad,
                                  (int)aad_len) != 1)
            { rc = AESCRYPTO_ERR_CRYPTO; break; }
        }

        if (EVP_DecryptUpdate(cpx, plaintext_out, &out_len,
                              ciphertext, (int)ciphertext_len) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        /* Set expected tag before finalizing */
        if (EVP_CIPHER_CTX_ctrl(cpx, EVP_CTRL_GCM_SET_TAG,
                                AESCRYPTO_TAG_BYTES, (void *)tag) != 1)
        { rc = AESCRYPTO_ERR_CRYPTO; break; }

        if (EVP_DecryptFinal_ex(cpx, plaintext_out + out_len, &out_len) != 1)
        {
            /* Tag mismatch or decryption error */
            rc = AESCRYPTO_ERR_AUTH;
            break;
        }

        rc = AESCRYPTO_OK;

    } while (0);

    EVP_CIPHER_CTX_free(cpx);
    return rc;
}

/* -------------------------------------------------------------------------- */
/*                           Context Sanitization                             */
/* -------------------------------------------------------------------------- */

/*
 * aescrypto_ctx_clear
 * -------------------
 * Zeroize sensitive material before releasing stack/heap memory. Callers
 * should prefer this helper over memset() because the latter may be optimized
 * away by aggressive compilers.
 */
static inline void
aescrypto_ctx_clear(aescrypto_ctx_t *ctx)
{
    if (!ctx) return;
#if defined(__STDC_LIB_EXT1__)   /* C11's memset_s */
    memset_s(ctx, sizeof *ctx, 0, sizeof *ctx);
#elif defined(_WIN32)
    SecureZeroMemory(ctx, sizeof *ctx);
#else
    /* Portable fall-back that attempts to prevent optimizing out */
    volatile uint8_t *p = (volatile uint8_t *)ctx;
    for (size_t i = 0; i < sizeof *ctx; ++i) p[i] = 0;
#endif
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_INFRASTRUCTURE_CRYPTO_AESCRYPTO_H */
