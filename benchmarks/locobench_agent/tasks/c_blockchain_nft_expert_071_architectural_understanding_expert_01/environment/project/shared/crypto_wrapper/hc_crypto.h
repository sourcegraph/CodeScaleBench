/*
 * HoloCanvas – hc_crypto.h
 *
 * Copyright (c) 2024
 * HoloCanvas: A Micro-Gallery Blockchain for Generative Artifacts
 *
 * Distributed under the MIT License.  See accompanying file LICENSE or
 * copy at https://opensource.org/licenses/MIT
 *
 * -----------------------------------------------------------------------------
 *  Cryptographic Wrapper
 *  ---------------------
 *  This header exposes a thin, ergonomic wrapper around libsodium/OpenSSL,
 *  offering the subset of cryptographic primitives required by the
 *  HoloCanvas micro-services:
 *
 *    • Secure random-number generation
 *    • SHA-2/3 hashing
 *    • Ed25519 key-pair management & signatures (default)
 *    • Secp256k1 key-pair management & ECDSA signatures (optional)
 *    • AES-256-GCM authenticated encryption (optional)
 *
 *  The wrapper purposefully hides direct dependency specifics, enabling a
 *  build-time switch between libsodium and OpenSSL back-ends.  Consumers
 *  should *only* include this header and link against `libhc_crypto`.
 * -----------------------------------------------------------------------------
 */

#ifndef HOLOCANVAS_CRYPTO_WRAPPER_HC_CRYPTO_H
#define HOLOCANVAS_CRYPTO_WRAPPER_HC_CRYPTO_H

/* -------------------------------------------------------------------------- */
/*  C Standard Library                                                        */
/* -------------------------------------------------------------------------- */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------- */
/*  Back-end Selection                                                        */
/* -------------------------------------------------------------------------- */
/*
 *  Define one of the following to explicitly choose a crypto back-end:
 *      HC_CRYPTO_USE_LIBSODIUM
 *      HC_CRYPTO_USE_OPENSSL
 *
 *  If none is defined, we try to auto-detect libsodium first, then OpenSSL.
 */
#if !defined(HC_CRYPTO_USE_LIBSODIUM) && !defined(HC_CRYPTO_USE_OPENSSL)
#   if defined(__has_include)
#       if __has_include(<sodium.h>)
#           define HC_CRYPTO_USE_LIBSODIUM 1
#       elif __has_include(<openssl/evp.h>)
#           define HC_CRYPTO_USE_OPENSSL  1
#       else
#           error "Neither libsodium nor OpenSSL headers found. "\
                 "Please install one of them or define HC_CRYPTO_USE_*."
#       endif
#   endif
#endif

/* -------------------------------------------------------------------------- */
/*  Dependencies – libsodium                                                   */
/* -------------------------------------------------------------------------- */
#ifdef HC_CRYPTO_USE_LIBSODIUM
#   include <sodium.h>
#endif

/* -------------------------------------------------------------------------- */
/*  Dependencies – OpenSSL                                                   */
/* -------------------------------------------------------------------------- */
#ifdef HC_CRYPTO_USE_OPENSSL
#   include <openssl/evp.h>
#   include <openssl/sha.h>
#   include <openssl/rand.h>
#   include <openssl/err.h>
#   include <openssl/ecdsa.h>
#   include <openssl/obj_mac.h>
#endif

/* -------------------------------------------------------------------------- */
/*  Constants                                                                 */
/* -------------------------------------------------------------------------- */

#define HC_CRYPTO_VERSION_MAJOR  1
#define HC_CRYPTO_VERSION_MINOR  0
#define HC_CRYPTO_VERSION_PATCH  0

/* SHA-256 */
#define HC_CRYPTO_SHA256_BYTES           32U

/* ---- Ed25519 ---- */
#ifdef HC_CRYPTO_USE_LIBSODIUM
#   define HC_CRYPTO_ED25519_PUBLIC_BYTES   crypto_sign_PUBLICKEYBYTES
#   define HC_CRYPTO_ED25519_PRIVATE_BYTES  crypto_sign_SECRETKEYBYTES
#   define HC_CRYPTO_ED25519_SIGNATURE_BYTES crypto_sign_BYTES
#else  /* OpenSSL */
#   define HC_CRYPTO_ED25519_PUBLIC_BYTES   32U
#   define HC_CRYPTO_ED25519_PRIVATE_BYTES  64U
#   define HC_CRYPTO_ED25519_SIGNATURE_BYTES  64U
#endif

/* ---- Secp256k1 ---- (Only when using OpenSSL) */
#define HC_CRYPTO_SECP256K1_PRIVATE_BYTES  32U
#define HC_CRYPTO_SECP256K1_PUBLIC_BYTES   65U      /* Uncompressed */
#define HC_CRYPTO_SECP256K1_SIGNATURE_BYTES 72U     /* DER encoded */

/* AES-256-GCM */
#define HC_CRYPTO_AES256_GCM_KEY_BYTES     32U
#define HC_CRYPTO_AES256_GCM_IV_BYTES      12U
#define HC_CRYPTO_AES256_GCM_TAG_BYTES     16U

/* -------------------------------------------------------------------------- */
/*  Error Codes                                                               */
/* -------------------------------------------------------------------------- */
/*
 *  All public API functions return an integer status:
 *      0     := Success
 *      < 0   := Error (see hc_crypto_err_t)
 */
typedef enum
{
    HC_CRYPTO_OK                 = 0,
    HC_CRYPTO_ERR_GENERIC        = -1,
    HC_CRYPTO_ERR_NOMEM          = -2,
    HC_CRYPTO_ERR_INIT           = -3,
    HC_CRYPTO_ERR_INVALID_ARG    = -4,
    HC_CRYPTO_ERR_KEYGEN         = -5,
    HC_CRYPTO_ERR_SIGN           = -6,
    HC_CRYPTO_ERR_VERIFY         = -7,
    HC_CRYPTO_ERR_RNG            = -8,
    HC_CRYPTO_ERR_UNSUPPORTED    = -9,
    HC_CRYPTO_ERR_ENCRYPT        = -10,
    HC_CRYPTO_ERR_DECRYPT        = -11
} hc_crypto_err_t;

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */

typedef struct
{
    uint8_t  bytes[HC_CRYPTO_ED25519_PUBLIC_BYTES];
} hc_ed25519_pubkey_t;

typedef struct
{
    uint8_t  bytes[HC_CRYPTO_ED25519_PRIVATE_BYTES];
} hc_ed25519_privkey_t;

typedef struct
{
    uint8_t  bytes[HC_CRYPTO_ED25519_SIGNATURE_BYTES];
} hc_ed25519_signature_t;

typedef struct
{
    uint8_t  bytes[HC_CRYPTO_SECP256K1_PUBLIC_BYTES];
    size_t   len;  /* 65 (uncompressed) or 33 (compressed) */
} hc_secp256k1_pubkey_t;

typedef struct
{
    uint8_t  bytes[HC_CRYPTO_SECP256K1_PRIVATE_BYTES];
} hc_secp256k1_privkey_t;

/* -------------------------------------------------------------------------- */
/*  Version API                                                               */
/* -------------------------------------------------------------------------- */
/**
 * hc_crypto_version
 *
 * Return library semantic-version numbers.
 */
static inline void
hc_crypto_version(int *major, int *minor, int *patch)
{
    if (major) *major = HC_CRYPTO_VERSION_MAJOR;
    if (minor) *minor = HC_CRYPTO_VERSION_MINOR;
    if (patch) *patch = HC_CRYPTO_VERSION_PATCH;
}

/* -------------------------------------------------------------------------- */
/*  Global Initialisation / Tear-down                                         */
/* -------------------------------------------------------------------------- */
/**
 * hc_crypto_init
 *
 * Initialise the crypto back-end.  Must be called once (thread-safe) before
 * any other hc_crypto_* API.  Safe to call multiple times; a ref-count
 * ensures underlying library is initialised exactly once.
 *
 * Returns 0 on success.
 */
int  hc_crypto_init(void);

/**
 * hc_crypto_shutdown
 *
 * Release global resources acquired by hc_crypto_init().
 * After the final shutdown, calling any other function is undefined.
 */
void hc_crypto_shutdown(void);

/* -------------------------------------------------------------------------- */
/*  Random Number Generation                                                  */
/* -------------------------------------------------------------------------- */
/**
 * hc_random_bytes
 *
 * Fill `buf` with `len` cryptographically secure random bytes.
 */
int  hc_random_bytes(void *buf, size_t len);

/* -------------------------------------------------------------------------- */
/*  Hash Functions                                                            */
/* -------------------------------------------------------------------------- */
/**
 * hc_sha256
 *
 * Compute SHA-256 digest of `in` and write result into `out` (32 bytes).
 */
int  hc_sha256(const void *in, size_t in_len, uint8_t out[HC_CRYPTO_SHA256_BYTES]);

/* -------------------------------------------------------------------------- */
/*  Ed25519 – Key Management & Signatures                                     */
/* -------------------------------------------------------------------------- */
/**
 * hc_ed25519_keypair_generate
 *
 * Generate a new Ed25519 key-pair.
 */
int  hc_ed25519_keypair_generate(hc_ed25519_pubkey_t *pub,
                                 hc_ed25519_privkey_t *priv);

/**
 * hc_ed25519_sign
 *
 * Sign `message` (`message_len` bytes) producing detached signature `sig`.
 */
int  hc_ed25519_sign(const hc_ed25519_privkey_t *priv,
                     const void *message,
                     size_t message_len,
                     hc_ed25519_signature_t *sig);

/**
 * hc_ed25519_verify
 *
 * Verify detached signature `sig` for `message`.
 */
int  hc_ed25519_verify(const hc_ed25519_pubkey_t *pub,
                       const void *message,
                       size_t message_len,
                       const hc_ed25519_signature_t *sig);

/* -------------------------------------------------------------------------- */
/*  Secp256k1 – (Optional) Key Management & Signatures                        */
/* -------------------------------------------------------------------------- */
#ifdef HC_CRYPTO_USE_OPENSSL
/**
 * hc_secp256k1_keypair_generate
 */
int  hc_secp256k1_keypair_generate(hc_secp256k1_pubkey_t *pub,
                                   hc_secp256k1_privkey_t *priv,
                                   bool compressed);

/**
 * hc_secp256k1_sign
 */
int  hc_secp256k1_sign(const hc_secp256k1_privkey_t *priv,
                       const uint8_t  digest32[32],
                       uint8_t        *sig,
                       size_t         *sig_len);

/**
 * hc_secp256k1_verify
 */
int  hc_secp256k1_verify(const hc_secp256k1_pubkey_t *pub,
                         const uint8_t  digest32[32],
                         const uint8_t *sig,
                         size_t         sig_len);
#endif /* HC_CRYPTO_USE_OPENSSL */

/* -------------------------------------------------------------------------- */
/*  AES-256-GCM                                                               */
/* -------------------------------------------------------------------------- */
/**
 * hc_aes256_gcm_encrypt
 *
 * Encrypt `plaintext` (pt_len) producing `ciphertext` and auth tag.
 * `ciphertext` must be at least pt_len bytes.
 */
int  hc_aes256_gcm_encrypt(const uint8_t key[HC_CRYPTO_AES256_GCM_KEY_BYTES],
                           const uint8_t iv[HC_CRYPTO_AES256_GCM_IV_BYTES],
                           const void   *aad, size_t aad_len,
                           const void   *plaintext, size_t pt_len,
                           uint8_t      *ciphertext,
                           uint8_t       tag[HC_CRYPTO_AES256_GCM_TAG_BYTES]);

/**
 * hc_aes256_gcm_decrypt
 *
 * Decrypt `ciphertext` (ct_len) verifying `tag`.
 * On success, writes plaintext to `plaintext` (can be in-place).
 */
int  hc_aes256_gcm_decrypt(const uint8_t key[HC_CRYPTO_AES256_GCM_KEY_BYTES],
                           const uint8_t iv[HC_CRYPTO_AES256_GCM_IV_BYTES],
                           const void   *aad, size_t aad_len,
                           const void   *ciphertext, size_t ct_len,
                           const uint8_t tag[HC_CRYPTO_AES256_GCM_TAG_BYTES],
                           uint8_t      *plaintext);

/* -------------------------------------------------------------------------- */
/*  Utility Helpers                                                           */
/* -------------------------------------------------------------------------- */
/**
 * hc_hex_encode
 *
 * Encode binary `in` buffer to hex string `out`.
 * `out` must be at least `in_len * 2 + 1` bytes (null-terminated).
 */
void hc_hex_encode(const void *in, size_t in_len, char *out);

/**
 * hc_hex_decode
 *
 * Decode hex string `in` to binary buffer `out`.
 * Returns number of bytes written, or <0 on error.
 */
int  hc_hex_decode(const char *in_hex, void *out, size_t out_len);

/* -------------------------------------------------------------------------- */
/*  Implementation (header-only for small helpers)                            */
/* -------------------------------------------------------------------------- */
#ifndef HC_CRYPTO_HEADER_ONLY_IMPL_GUARD
#define HC_CRYPTO_HEADER_ONLY_IMPL_GUARD

/* ----------------- Reference Counting & Back-end Init -------------------- */
#include <stdatomic.h>

static atomic_uint_least32_t _hc_crypto_refcnt = 0;

static int _hc_crypto_backend_init(void)
{
#ifdef HC_CRYPTO_USE_LIBSODIUM
    if (sodium_init() < 0)
        return HC_CRYPTO_ERR_INIT;
    return HC_CRYPTO_OK;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    /* OpenSSL 1.1+ does init automatically, but we do explicit for clarity */
    if (OPENSSL_init_crypto(OPENSSL_INIT_LOAD_CONFIG, NULL) == 0)
        return HC_CRYPTO_ERR_INIT;
    return HC_CRYPTO_OK;
#endif
}

static void _hc_crypto_backend_cleanup(void)
{
#ifdef HC_CRYPTO_USE_OPENSSL
    /* No cleanup necessary in 1.1+, but retained for completeness */
    /* OPENSSL_cleanup(); */
    (void)0;
#endif
}

/* PUBLIC */
static inline int
hc_crypto_init(void)
{
    uint32_t prev = atomic_fetch_add_explicit(&_hc_crypto_refcnt, 1,
                                              memory_order_acq_rel);

    if (prev == 0)  /* first caller */
        return _hc_crypto_backend_init();

    return HC_CRYPTO_OK;
}

static inline void
hc_crypto_shutdown(void)
{
    uint32_t prev = atomic_fetch_sub_explicit(&_hc_crypto_refcnt, 1,
                                              memory_order_acq_rel);
    if (prev == 1)
        _hc_crypto_backend_cleanup();
}

/* ------------------ Random ------------------------------------------------ */
static inline int
hc_random_bytes(void *buf, size_t len)
{
    if (!buf || len == 0)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    randombytes_buf(buf, len);
    return HC_CRYPTO_OK;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    if (RAND_bytes((unsigned char *)buf, (int)len) == 1)
        return HC_CRYPTO_OK;
    return HC_CRYPTO_ERR_RNG;
#endif
}

/* ------------------ SHA-256 ---------------------------------------------- */
static inline int
hc_sha256(const void *in, size_t in_len, uint8_t out[HC_CRYPTO_SHA256_BYTES])
{
    if (!in || !out)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    crypto_hash_sha256(out, in, (unsigned long long)in_len);
    return HC_CRYPTO_OK;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    if (SHA256(in, in_len, out) == NULL)
        return HC_CRYPTO_ERR_GENERIC;
    return HC_CRYPTO_OK;
#endif
}

/* ------------------ Ed25519 ---------------------------------------------- */
static inline int
hc_ed25519_keypair_generate(hc_ed25519_pubkey_t *pub,
                             hc_ed25519_privkey_t *priv)
{
    if (!pub || !priv)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    if (crypto_sign_keypair(pub->bytes, priv->bytes) != 0)
        return HC_CRYPTO_ERR_KEYGEN;
    return HC_CRYPTO_OK;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    int ret = HC_CRYPTO_ERR_GENERIC;
    EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_ED25519, NULL);
    if (!ctx) return HC_CRYPTO_ERR_NOMEM;
    if (EVP_PKEY_keygen_init(ctx) == 1)
    {
        EVP_PKEY *pkey = NULL;
        if (EVP_PKEY_keygen(ctx, &pkey) == 1)
        {
            size_t publen = HC_CRYPTO_ED25519_PUBLIC_BYTES;
            size_t privlen = HC_CRYPTO_ED25519_PRIVATE_BYTES;
            if (EVP_PKEY_get_raw_public_key(pkey, pub->bytes, &publen) == 1 &&
                EVP_PKEY_get_raw_private_key(pkey, priv->bytes, &privlen) == 1)
                ret = HC_CRYPTO_OK;
            EVP_PKEY_free(pkey);
        }
    }
    EVP_PKEY_CTX_free(ctx);
    return ret;
#endif
}

static inline int
hc_ed25519_sign(const hc_ed25519_privkey_t *priv,
                const void *message, size_t message_len,
                hc_ed25519_signature_t *sig)
{
    if (!priv || !message || !sig)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    if (crypto_sign_detached(sig->bytes, NULL,
                             message, (unsigned long long)message_len,
                             priv->bytes) == 0)
        return HC_CRYPTO_OK;
    return HC_CRYPTO_ERR_SIGN;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    EVP_PKEY *pkey = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519,
                                                  NULL,
                                                  priv->bytes,
                                                  HC_CRYPTO_ED25519_PRIVATE_BYTES);
    if (!pkey) return HC_CRYPTO_ERR_KEYGEN;

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) { EVP_PKEY_free(pkey); return HC_CRYPTO_ERR_NOMEM; }

    int rc = HC_CRYPTO_ERR_SIGN;
    if (EVP_DigestSignInit(ctx, NULL, NULL, NULL, pkey) == 1)
    {
        size_t siglen = HC_CRYPTO_ED25519_SIGNATURE_BYTES;
        if (EVP_DigestSign(ctx, sig->bytes, &siglen,
                           message, message_len) == 1 &&
            siglen == HC_CRYPTO_ED25519_SIGNATURE_BYTES)
            rc = HC_CRYPTO_OK;
    }
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    return rc;
#endif
}

static inline int
hc_ed25519_verify(const hc_ed25519_pubkey_t *pub,
                  const void *message, size_t message_len,
                  const hc_ed25519_signature_t *sig)
{
    if (!pub || !message || !sig)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    if (crypto_sign_verify_detached(sig->bytes,
                                    message,
                                    (unsigned long long)message_len,
                                    pub->bytes) == 0)
        return HC_CRYPTO_OK;
    return HC_CRYPTO_ERR_VERIFY;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    EVP_PKEY *pkey = EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519,
                                                 NULL,
                                                 pub->bytes,
                                                 HC_CRYPTO_ED25519_PUBLIC_BYTES);
    if (!pkey) return HC_CRYPTO_ERR_VERIFY;

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) { EVP_PKEY_free(pkey); return HC_CRYPTO_ERR_NOMEM; }

    int rc = HC_CRYPTO_ERR_VERIFY;
    if (EVP_DigestVerifyInit(ctx, NULL, NULL, NULL, pkey) == 1 &&
        EVP_DigestVerify(ctx, sig->bytes,
                         HC_CRYPTO_ED25519_SIGNATURE_BYTES,
                         message, message_len) == 1)
        rc = HC_CRYPTO_OK;

    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    return rc;
#endif
}

/* ------------------ Secp256k1 (OpenSSL only) ----------------------------- */
#ifdef HC_CRYPTO_USE_OPENSSL
static inline int
hc_secp256k1_keypair_generate(hc_secp256k1_pubkey_t *pub,
                              hc_secp256k1_privkey_t *priv,
                              bool compressed)
{
    if (!pub || !priv)
        return HC_CRYPTO_ERR_INVALID_ARG;

    int rc = HC_CRYPTO_ERR_GENERIC;
    EC_KEY *eckey = EC_KEY_new_by_curve_name(NID_secp256k1);
    if (!eckey) return HC_CRYPTO_ERR_NOMEM;

    if (!EC_KEY_generate_key(eckey))
        goto cleanup;

    /* Private key */
    const BIGNUM *bn_priv = EC_KEY_get0_private_key(eckey);
    if (!bn_priv) goto cleanup;
    if (BN_bn2binpad(bn_priv, priv->bytes,
                     HC_CRYPTO_SECP256K1_PRIVATE_BYTES) !=
        HC_CRYPTO_SECP256K1_PRIVATE_BYTES)
        goto cleanup;

    /* Public key */
    EC_KEY_set_conv_form(eckey,
        compressed ? POINT_CONVERSION_COMPRESSED : POINT_CONVERSION_UNCOMPRESSED);

    int pub_len = i2o_ECPublicKey(eckey, NULL);
    if (pub_len <= 0 || (size_t)pub_len > sizeof(pub->bytes))
        goto cleanup;

    uint8_t *pub_ptr = pub->bytes;
    if (i2o_ECPublicKey(eckey, &pub_ptr) != pub_len)
        goto cleanup;

    pub->len = (size_t)pub_len;
    rc = HC_CRYPTO_OK;

cleanup:
    EC_KEY_free(eckey);
    return rc;
}

static inline int
hc_secp256k1_sign(const hc_secp256k1_privkey_t *priv,
                  const uint8_t digest32[32],
                  uint8_t *sig, size_t *sig_len)
{
    if (!priv || !digest32 || !sig || !sig_len || *sig_len == 0)
        return HC_CRYPTO_ERR_INVALID_ARG;

    int rc = HC_CRYPTO_ERR_SIGN;
    EC_KEY *eckey = EC_KEY_new_by_curve_name(NID_secp256k1);
    if (!eckey) return HC_CRYPTO_ERR_NOMEM;

    BIGNUM *bn_priv = BN_bin2bn(priv->bytes,
                                HC_CRYPTO_SECP256K1_PRIVATE_BYTES, NULL);
    if (!bn_priv) goto cleanup;
    if (EC_KEY_set_private_key(eckey, bn_priv) != 1) goto cleanup;

    ECDSA_SIG *sig_obj = ECDSA_do_sign(digest32, 32, eckey);
    if (!sig_obj) goto cleanup;

    int len = i2d_ECDSA_SIG(sig_obj, NULL);
    if (len <= 0 || (size_t)len > *sig_len)
        goto cleanup;

    uint8_t *ptr = sig;
    if (i2d_ECDSA_SIG(sig_obj, &ptr) != len)
        goto cleanup;

    *sig_len = (size_t)len;
    rc = HC_CRYPTO_OK;

cleanup:
    ECDSA_SIG_free(sig_obj);
    BN_free(bn_priv);
    EC_KEY_free(eckey);
    return rc;
}

static inline int
hc_secp256k1_verify(const hc_secp256k1_pubkey_t *pub,
                    const uint8_t digest32[32],
                    const uint8_t *sig,
                    size_t sig_len)
{
    if (!pub || !digest32 || !sig || sig_len == 0)
        return HC_CRYPTO_ERR_INVALID_ARG;

    int rc = HC_CRYPTO_ERR_VERIFY;
    EC_KEY *eckey = EC_KEY_new_by_curve_name(NID_secp256k1);
    if (!eckey) return HC_CRYPTO_ERR_NOMEM;

    const uint8_t *pp = pub->bytes;
    if (!o2i_ECPublicKey(&eckey, &pp, (long)pub->len))
        goto cleanup;

    const uint8_t *sp = sig;
    ECDSA_SIG *sig_obj = d2i_ECDSA_SIG(NULL, &sp, (long)sig_len);
    if (!sig_obj) goto cleanup;

    int ver = ECDSA_do_verify(digest32, 32, sig_obj, eckey);
    if (ver == 1)
        rc = HC_CRYPTO_OK;
    else if (ver == 0)
        rc = HC_CRYPTO_ERR_VERIFY;
    else
        rc = HC_CRYPTO_ERR_GENERIC;

cleanup:
    ECDSA_SIG_free(sig_obj);
    EC_KEY_free(eckey);
    return rc;
}
#endif /* HC_CRYPTO_USE_OPENSSL */

/* ------------------ AES-256-GCM ------------------------------------------ */
static inline int
hc_aes256_gcm_encrypt(const uint8_t key[HC_CRYPTO_AES256_GCM_KEY_BYTES],
                      const uint8_t iv[HC_CRYPTO_AES256_GCM_IV_BYTES],
                      const void *aad, size_t aad_len,
                      const void *plaintext, size_t pt_len,
                      uint8_t *ciphertext,
                      uint8_t tag[HC_CRYPTO_AES256_GCM_TAG_BYTES])
{
    if (!key || !iv || (!plaintext && pt_len) || !ciphertext || !tag)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    /* sodium provides crypto_aead_aes256gcm_* but requires AES-NI. */
    if (!crypto_aead_aes256gcm_is_available())
        return HC_CRYPTO_ERR_UNSUPPORTED;

    unsigned long long ct_len = 0;
    if (crypto_aead_aes256gcm_encrypt(ciphertext, &ct_len,
                                      plaintext, pt_len,
                                      aad, aad_len,
                                      NULL,
                                      iv, key) != 0)
        return HC_CRYPTO_ERR_ENCRYPT;

    /* libsodium appends tag to ciphertext; we split it for uniform API */
    ct_len -= HC_CRYPTO_AES256_GCM_TAG_BYTES;
    memcpy(tag,
           ciphertext + ct_len,
           HC_CRYPTO_AES256_GCM_TAG_BYTES);
    return HC_CRYPTO_OK;
#elif defined(HC_CRYPTO_USE_OPENSSL)
    int rc = HC_CRYPTO_ERR_ENCRYPT;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return HC_CRYPTO_ERR_NOMEM;

    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        goto cleanup;
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                            HC_CRYPTO_AES256_GCM_IV_BYTES, NULL) != 1)
        goto cleanup;
    if (EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) != 1)
        goto cleanup;

    int len;
    if (aad_len > 0 && EVP_EncryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1)
        goto cleanup;
    if (EVP_EncryptUpdate(ctx, ciphertext, &len, plaintext, (int)pt_len) != 1)
        goto cleanup;
    int total_len = len;

    if (EVP_EncryptFinal_ex(ctx, ciphertext + total_len, &len) != 1)
        goto cleanup;
    total_len += len; /* should equal pt_len */

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG,
                            HC_CRYPTO_AES256_GCM_TAG_BYTES, tag) != 1)
        goto cleanup;
    rc = HC_CRYPTO_OK;

cleanup:
    EVP_CIPHER_CTX_free(ctx);
    return rc;
#endif
}

static inline int
hc_aes256_gcm_decrypt(const uint8_t key[HC_CRYPTO_AES256_GCM_KEY_BYTES],
                      const uint8_t iv[HC_CRYPTO_AES256_GCM_IV_BYTES],
                      const void *aad, size_t aad_len,
                      const void *ciphertext, size_t ct_len,
                      const uint8_t tag[HC_CRYPTO_AES256_GCM_TAG_BYTES],
                      uint8_t *plaintext)
{
    if (!key || !iv || (!ciphertext && ct_len) || !plaintext || !tag)
        return HC_CRYPTO_ERR_INVALID_ARG;

#ifdef HC_CRYPTO_USE_LIBSODIUM
    if (!crypto_aead_aes256gcm_is_available())
        return HC_CRYPTO_ERR_UNSUPPORTED;

    /* libsodium expects tag concatenated */
    uint8_t *tmp = (uint8_t *)sodium_malloc(ct_len + HC_CRYPTO_AES256_GCM_TAG_BYTES);
    if (!tmp) return HC_CRYPTO_ERR_NOMEM;
    memcpy(tmp, ciphertext, ct_len);
    memcpy(tmp + ct_len, tag, HC_CRYPTO_AES256_GCM_TAG_BYTES);

    unsigned long long pt_out = 0;
    int rc = HC_CRYPTO_OK;
    if (crypto_aead_aes256gcm_decrypt(plaintext, &pt_out,
                                      NULL,
                                      tmp, ct_len + HC_CRYPTO_AES256_GCM_TAG_BYTES,
                                      aad, aad_len,
                                      iv, key) != 0)
        rc = HC_CRYPTO_ERR_DECRYPT;

    sodium_free(tmp);
    return rc;

#elif defined(HC_CRYPTO_USE_OPENSSL)
    int rc = HC_CRYPTO_ERR_DECRYPT;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return HC_CRYPTO_ERR_NOMEM;

    if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        goto cleanup;
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                            HC_CRYPTO_AES256_GCM_IV_BYTES, NULL) != 1)
        goto cleanup;
    if (EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) != 1)
        goto cleanup;

    int len;
    if (aad_len > 0 && EVP_DecryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1)
        goto cleanup;
    if (EVP_DecryptUpdate(ctx, plaintext, &len, ciphertext, (int)ct_len) != 1)
        goto cleanup;

    /* Set expected tag value */
    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG,
                            HC_CRYPTO_AES256_GCM_TAG_BYTES, (void *)tag) != 1)
        goto cleanup;

    if (EVP_DecryptFinal_ex(ctx, plaintext + len, &len) != 1)
        goto cleanup;

    rc = HC_CRYPTO_OK;

cleanup:
    EVP_CIPHER_CTX_free(ctx);
    return rc;
#endif
}

/* ------------------ Hex Encoding/Decoding -------------------------------- */
#include <ctype.h>

static inline void
hc_hex_encode(const void *in_buf, size_t in_len, char *out_hex)
{
    const uint8_t *src = (const uint8_t *)in_buf;
    static const char tbl[] = "0123456789abcdef";
    for (size_t i = 0; i < in_len; ++i)
    {
        out_hex[i * 2]       = tbl[src[i] >> 4];
        out_hex[i * 2 + 1]   = tbl[src[i] & 0xF];
    }
    out_hex[in_len * 2] = '\0';
}

static inline int
hc_hex_decode(const char *in_hex, void *out_buf, size_t out_len)
{
    if (!in_hex || !out_buf) return HC_CRYPTO_ERR_INVALID_ARG;

    size_t hex_len = 0;
    while (in_hex[hex_len] != '\0') hex_len++;

    if (hex_len % 2) return HC_CRYPTO_ERR_INVALID_ARG;
    size_t need_len = hex_len / 2;
    if (need_len > out_len) return HC_CRYPTO_ERR_NOMEM;

    uint8_t *dst = (uint8_t *)out_buf;
    for (size_t i = 0; i < need_len; ++i)
    {
        int hi = tolower((unsigned char)in_hex[i * 2]);
        int lo = tolower((unsigned char)in_hex[i * 2 + 1]);

        if (!isxdigit(hi) || !isxdigit(lo))
            return HC_CRYPTO_ERR_INVALID_ARG;

        hi = (hi >= 'a') ? (hi - 'a' + 10) : (hi - '0');
        lo = (lo >= 'a') ? (lo - 'a' + 10) : (lo - '0');

        dst[i] = (uint8_t)((hi << 4) | lo);
    }
    return (int)need_len;
}

#endif /* HC_CRYPTO_HEADER_ONLY_IMPL_GUARD */

/* -------------------------------------------------------------------------- */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* HOLOCANVAS_CRYPTO_WRAPPER_HC_CRYPTO_H */
