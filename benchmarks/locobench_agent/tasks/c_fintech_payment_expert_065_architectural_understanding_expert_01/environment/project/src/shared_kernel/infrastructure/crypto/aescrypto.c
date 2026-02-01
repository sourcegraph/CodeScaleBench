/**
 * Copyright (c) 2024 EduPay Ledger Academy
 *
 * aescrypto.c
 *
 * Shared-kernel infrastructure component that provides AES-256-GCM
 * authenticated encryption and related crypto utilities.
 *
 * The implementation is intentionally isolated from the rest of the codebase
 * so that instructors can swap out the vendor library (e.g., OpenSSL →
 * mbedTLS) without touching business rules.  All higher-level modules
 * depend solely on the header (aescrypto.h) defined in this package.
 *
 * Build requirements:
 *   - OpenSSL 1.1.1 or 3.x
 *
 * Thread-safety:
 *   All routines are re-entrant. No global state is mutated after OpenSSL
 *   library initialization.
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/err.h>

#include "aescrypto.h"   /* Public interface */
#include "edupay_log.h"  /* Centralized logging abstraction */

/* -------------------------------------------------------------------------- */
/*  Local macros & constants                                                  */
/* -------------------------------------------------------------------------- */

#define AES_256_KEY_SIZE       32U
#define AES_GCM_IV_SIZE        12U    /* Recommended size for GCM */
#define AES_GCM_TAG_SIZE       16U
#define AES_CRYPTO_OK          (0)
#define AES_CRYPTO_ERR        (-1)

/* -------------------------------------------------------------------------- */
/*  Static helpers                                                            */
/* -------------------------------------------------------------------------- */

/**
 * secure_memzero
 *
 * Overwrite sensitive memory in a way that the compiler will not optimise out.
 */
static void secure_memzero(void *ptr, size_t len)
{
#if defined(__STDC_LIB_EXT1__) && (__STDC_WANT_LIB_EXT1__ == 1)
    memset_s(ptr, len, 0, len);
#elif defined(_WIN32)
    SecureZeroMemory(ptr, len);
#else
    /* Fallback: volatile pointer to prevent optimisation */
    volatile uint8_t *volatile p = (volatile uint8_t *volatile)ptr;
    while (len--)
        *p++ = 0;
#endif
}

/**
 * secure_memcmp
 *
 * Constant-time byte array comparison to mitigate timing attacks.
 * Returns 0 when buffers are identical, non-zero otherwise.
 */
static int secure_memcmp(const void *a, const void *b, size_t len)
{
#if defined(OPENSSL_VERSION_MAJOR) && (OPENSSL_VERSION_MAJOR >= 3)
    return CRYPTO_memcmp(a, b, len);
#else
    /* Polyfill for versions where CRYPTO_memcmp exists in <openssl/crypto.h>. */
    const uint8_t *pa = (const uint8_t *)a;
    const uint8_t *pb = (const uint8_t *)b;
    uint8_t diff = 0;

    while (len--) {
        diff |= (*pa++) ^ (*pb++);
    }
    return diff;
#endif
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

int aes_generate_key(uint8_t *key_out, size_t key_len)
{
    if (key_out == NULL || key_len != AES_256_KEY_SIZE) {
        errno = EINVAL;
        return AES_CRYPTO_ERR;
    }

    if (RAND_bytes(key_out, (int)key_len) != 1) {
        edupay_log_error("RAND_bytes() failed: %s",
                         ERR_error_string(ERR_get_error(), NULL));
        return AES_CRYPTO_ERR;
    }
    return AES_CRYPTO_OK;
}

int aes_generate_iv(uint8_t *iv_out, size_t iv_len)
{
    if (iv_out == NULL || iv_len != AES_GCM_IV_SIZE) {
        errno = EINVAL;
        return AES_CRYPTO_ERR;
    }
    if (RAND_bytes(iv_out, (int)iv_len) != 1) {
        edupay_log_error("RAND_bytes() failed: %s",
                         ERR_error_string(ERR_get_error(), NULL));
        return AES_CRYPTO_ERR;
    }
    return AES_CRYPTO_OK;
}

int aes_encrypt_gcm(const uint8_t  *key,
                    size_t          key_len,
                    const uint8_t  *iv,
                    size_t          iv_len,
                    const uint8_t  *aad,
                    size_t          aad_len,
                    const uint8_t  *plaintext,
                    size_t          plaintext_len,
                    uint8_t        *ciphertext_out,
                    uint8_t        *tag_out,
                    size_t          tag_len)
{
    int ret = AES_CRYPTO_ERR;
    EVP_CIPHER_CTX *ctx = NULL;
    int len = 0;
    int cipher_len = 0;

    if (!key || key_len != AES_256_KEY_SIZE ||
        !iv  || iv_len != AES_GCM_IV_SIZE  ||
        !plaintext || !ciphertext_out ||
        !tag_out || tag_len != AES_GCM_TAG_SIZE) {
        errno = EINVAL;
        return AES_CRYPTO_ERR;
    }

    ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        edupay_log_error("EVP_CIPHER_CTX_new() failed");
        goto cleanup;
    }

    /* Initialise encryption operation */
    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) {
        edupay_log_error("EVP_EncryptInit_ex() failed");
        goto cleanup;
    }

    /* Set IV length (default is 12 bytes for GCM; this call is optional) */
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, (int)iv_len, NULL) != 1) {
        edupay_log_error("EVP_CIPHER_CTX_ctrl(SET_IVLEN) failed");
        goto cleanup;
    }

    /* Provide key and IV */
    if (EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        edupay_log_error("EVP_EncryptInit_ex(setkey) failed");
        goto cleanup;
    }

    /* Pass Additional Authenticated Data (AAD) */
    if (aad && aad_len > 0) {
        if (EVP_EncryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1) {
            edupay_log_error("EVP_EncryptUpdate(AAD) failed");
            goto cleanup;
        }
    }

    /* Encrypt plaintext */
    if (EVP_EncryptUpdate(ctx, ciphertext_out, &len,
                          plaintext, (int)plaintext_len) != 1) {
        edupay_log_error("EVP_EncryptUpdate(data) failed");
        goto cleanup;
    }
    cipher_len = len;

    /* Finalise encryption (no additional ciphertext for GCM) */
    if (EVP_EncryptFinal_ex(ctx, ciphertext_out + cipher_len, &len) != 1) {
        edupay_log_error("EVP_EncryptFinal_ex() failed");
        goto cleanup;
    }
    cipher_len += len;

    /* Get authentication tag */
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG,
                            (int)tag_len, tag_out) != 1) {
        edupay_log_error("EVP_CIPHER_CTX_ctrl(GET_TAG) failed");
        goto cleanup;
    }

    ret = cipher_len; /* return ciphertext length on success */

cleanup:
    if (ctx)
        EVP_CIPHER_CTX_free(ctx);

    if (ret == AES_CRYPTO_ERR)
        secure_memzero(ciphertext_out, plaintext_len);  /* zero partial output */

    secure_memzero(&len, sizeof(len));
    secure_memzero(&cipher_len, sizeof(cipher_len));
    return ret;
}

int aes_decrypt_gcm(const uint8_t  *key,
                    size_t          key_len,
                    const uint8_t  *iv,
                    size_t          iv_len,
                    const uint8_t  *aad,
                    size_t          aad_len,
                    const uint8_t  *ciphertext,
                    size_t          ciphertext_len,
                    const uint8_t  *tag,
                    size_t          tag_len,
                    uint8_t        *plaintext_out)
{
    int ret = AES_CRYPTO_ERR;
    EVP_CIPHER_CTX *ctx = NULL;
    int len = 0;
    int plain_len = 0;
    uint8_t tag_buf[AES_GCM_TAG_SIZE];

    if (!key || key_len != AES_256_KEY_SIZE ||
        !iv  || iv_len != AES_GCM_IV_SIZE  ||
        !ciphertext || !plaintext_out ||
        !tag || tag_len != AES_GCM_TAG_SIZE) {
        errno = EINVAL;
        return AES_CRYPTO_ERR;
    }

    ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        edupay_log_error("EVP_CIPHER_CTX_new() failed");
        goto cleanup;
    }

    if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) {
        edupay_log_error("EVP_DecryptInit_ex() failed");
        goto cleanup;
    }

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                            (int)iv_len, NULL) != 1) {
        edupay_log_error("EVP_CIPHER_CTX_ctrl(SET_IVLEN) failed");
        goto cleanup;
    }

    if (EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        edupay_log_error("EVP_DecryptInit_ex(setkey) failed");
        goto cleanup;
    }

    if (aad && aad_len > 0) {
        if (EVP_DecryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1) {
            edupay_log_error("EVP_DecryptUpdate(AAD) failed");
            goto cleanup;
        }
    }

    if (EVP_DecryptUpdate(ctx, plaintext_out, &len,
                          ciphertext, (int)ciphertext_len) != 1) {
        edupay_log_error("EVP_DecryptUpdate(data) failed");
        goto cleanup;
    }
    plain_len = len;

    /* Set expected tag */
    memcpy(tag_buf, tag, tag_len);
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG,
                            (int)tag_len, tag_buf) != 1) {
        edupay_log_error("EVP_CIPHER_CTX_ctrl(SET_TAG) failed");
        goto cleanup;
    }

    /* Finalise decryption: returns >0 if MAC is valid */
    ret = EVP_DecryptFinal_ex(ctx, plaintext_out + plain_len, &len);
    if (ret > 0) {
        plain_len += len;
        ret = plain_len; /* success: return plaintext length */
    } else {
        edupay_log_warn("Authentication tag mismatch – possible tampering");
        secure_memzero(plaintext_out, ciphertext_len);
        ret = AES_CRYPTO_ERR;
    }

cleanup:
    secure_memzero(tag_buf, sizeof(tag_buf));
    if (ctx)
        EVP_CIPHER_CTX_free(ctx);

    secure_memzero(&len, sizeof(len));
    secure_memzero(&plain_len, sizeof(plain_len));
    return ret;
}

/* -------------------------------------------------------------------------- */
/*  Self-test (used in CI pipeline, can be disabled in production)            */
/* -------------------------------------------------------------------------- */

#ifdef EDU_PAY_AESCRYPTO_SELFTEST

static int self_test(void)
{
    const char *msg = "Hello, EduPay Ledger Academy!";
    uint8_t key[AES_256_KEY_SIZE];
    uint8_t iv[AES_GCM_IV_SIZE];
    uint8_t tag[AES_GCM_TAG_SIZE];
    uint8_t ciphertext[256];
    uint8_t plaintext[256];

    size_t msg_len = strlen(msg);

    if (aes_generate_key(key, sizeof key) != AES_CRYPTO_OK)
        return -1;
    if (aes_generate_iv(iv, sizeof iv) != AES_CRYPTO_OK)
        return -1;

    int enc_len = aes_encrypt_gcm(key, sizeof key,
                                  iv, sizeof iv,
                                  NULL, 0,
                                  (const uint8_t *)msg, msg_len,
                                  ciphertext, tag, sizeof tag);
    if (enc_len <= 0)
        return -1;

    int dec_len = aes_decrypt_gcm(key, sizeof key,
                                  iv, sizeof iv,
                                  NULL, 0,
                                  ciphertext, (size_t)enc_len,
                                  tag, sizeof tag,
                                  plaintext);
    if (dec_len <= 0)
        return -1;

    if (dec_len != (int)msg_len ||
        secure_memcmp(msg, plaintext, msg_len) != 0) {
        edupay_log_error("AES self-test failed");
        return -1;
    }

    edupay_log_info("AES self-test passed");
    return 0;
}

/* Register self-test with the unit test harness */
EDUPAY_TEST(setup_dummy, self_test);

#endif /* EDU_PAY_AESCRYPTO_SELFTEST */
