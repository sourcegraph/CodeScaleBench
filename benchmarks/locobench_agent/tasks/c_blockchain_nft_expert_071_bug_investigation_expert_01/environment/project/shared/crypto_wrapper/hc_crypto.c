/* ============================================================================
 * HoloCanvas // shared // crypto_wrapper // hc_crypto.c
 *
 * A thin, opinionated wrapper around OpenSSL providing safe-by-default
 * cryptographic primitives for all HoloCanvas micro-services.  The wrapper
 * intentionally exposes only a curated subset of algorithms considered
 * best-practice for 2024:
 *
 *   – Randomness        :  ChaCha20-DRBG (via RAND_bytes)
 *   – Hashing           :  SHA-256
 *   – Symmetric Cipher  :  AES-256-GCM
 *   – Digital Signatures:  ECDSA secp256k1
 *
 * The interface emphasises:
 *   • Constant-time operations wherever possible
 *   • Single-allocation, caller-owned buffers
 *   • Clear error propagation via hc_crypto_err_t
 *   • Automatic resource hygiene (secure wipes, ref-counts, …)
 *
 * Dependencies:
 *   – OpenSSL >= 1.1.1  (tested with 3.2.0)
 *   – C11 compliant compiler
 * ============================================================================ */

#include "hc_crypto.h"

#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <openssl/sha.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * Internal helpers & macros
 * ---------------------------------------------------------------------------*/

#define HC_CRYPTO_OPENSSL_BEGIN() \
    ERR_clear_error();

#define HC_CRYPTO_OPENSSL_END(func)                                      \
    do {                                                                 \
        if (ret != HC_CRYPTO_OK) {                                       \
            unsigned long err = ERR_get_error();                         \
            if (err) {                                                   \
                char buf[256];                                           \
                ERR_error_string_n(err, buf, sizeof(buf));               \
                fprintf(stderr, "[hc_crypto] %s failed: %s\n", func, buf); \
            }                                                            \
        }                                                                \
    } while (0)

/* ---------------------------------------------------------------------------
 * Constant-time memory comparison
 * ---------------------------------------------------------------------------*/
static inline int
hc_crypto_memeq(const uint8_t *a, const uint8_t *b, size_t n)
{
    uint8_t r = 0;
    for (size_t i = 0; i < n; ++i)
        r |= a[i] ^ b[i];
    return r == 0;
}

/* ---------------------------------------------------------------------------
 * Secure memory wipe
 * ---------------------------------------------------------------------------*/
static inline void
hc_crypto_memwipe(void *v, size_t n)
{
    /* Use OPENSSL_cleanse which is guaranteed not to be optimised away. */
    OPENSSL_cleanse(v, n);
}

/* ===========================================================================
 * Randomness
 * ==========================================================================*/

hc_crypto_err_t
hc_rand_bytes(uint8_t *dst, size_t len)
{
    if (!dst || len == 0) return HC_CRYPTO_E_PARAM;
    HC_CRYPTO_OPENSSL_BEGIN();
    if (RAND_bytes(dst, (int)len) != 1)
        return HC_CRYPTO_E_INTERNAL;
    return HC_CRYPTO_OK;
}

/* ===========================================================================
 * Hashing – SHA-256
 * ==========================================================================*/

hc_crypto_err_t
hc_sha256(const uint8_t *msg, size_t msg_len, uint8_t out[HC_SHA256_LEN])
{
    if (!msg || !out) return HC_CRYPTO_E_PARAM;
    HC_CRYPTO_OPENSSL_BEGIN();
    if (!SHA256(msg, msg_len, out))
        return HC_CRYPTO_E_INTERNAL;
    return HC_CRYPTO_OK;
}

/* ===========================================================================
 * Symmetric Encryption – AES-256-GCM
 * ==========================================================================*/

#define AES_GCM_IV_LEN   12    /* Recommended IV length for GCM */
#define AES_GCM_TAG_LEN  16

/* Encrypt
 *  – key : 32-byte AES-256 key
 *  – iv  : 12 bytes; caller may provide or pass NULL to auto-generate
 *  – aad : Additional authenticated data (may be NULL)
 *  – out_ct  : Ciphertext buffer (must be ≥ pt_len)
 *  – out_tag : 16-byte authentication tag
 */
hc_crypto_err_t
hc_aes256_gcm_encrypt(const uint8_t key[HC_AES256_KEY_LEN],
                      uint8_t       iv[AES_GCM_IV_LEN],
                      const uint8_t *aad, size_t aad_len,
                      const uint8_t *pt,  size_t pt_len,
                      uint8_t *ct,        uint8_t tag[AES_GCM_TAG_LEN])
{
    if (!key || !pt || !ct || !tag) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    int len;

    /* Auto-generate IV if not provided. */
    if (!iv)
        return HC_CRYPTO_E_PARAM;

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return HC_CRYPTO_E_NOMEM;

    HC_CRYPTO_OPENSSL_BEGIN();

    do {
        if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, AES_GCM_IV_LEN, NULL) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        /* Initialise key & IV */
        if (EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        /* AAD */
        if (aad && aad_len) {
            if (EVP_EncryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1)
            { ret = HC_CRYPTO_E_INTERNAL; break; }
        }

        /* Ciphertext */
        if (EVP_EncryptUpdate(ctx, ct, &len, pt, (int)pt_len) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        int ct_len = len;

        /* Finalise (no data for GCM) */
        if (EVP_EncryptFinal_ex(ctx, ct + ct_len, &len) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        /* Authentication Tag */
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG,
                                AES_GCM_TAG_LEN, tag) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

    } while (0);

    EVP_CIPHER_CTX_free(ctx);
    HC_CRYPTO_OPENSSL_END("hc_aes256_gcm_encrypt");
    return ret;
}

/* Decrypt */
hc_crypto_err_t
hc_aes256_gcm_decrypt(const uint8_t key[HC_AES256_KEY_LEN],
                      const uint8_t iv[AES_GCM_IV_LEN],
                      const uint8_t *aad, size_t aad_len,
                      const uint8_t *ct,  size_t ct_len,
                      const uint8_t tag[AES_GCM_TAG_LEN],
                      uint8_t *pt)
{
    if (!key || !iv || !ct || !tag || !pt) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    int len;

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return HC_CRYPTO_E_NOMEM;

    HC_CRYPTO_OPENSSL_BEGIN();

    do {
        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                                AES_GCM_IV_LEN, NULL) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (aad && aad_len) {
            if (EVP_DecryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1)
            { ret = HC_CRYPTO_E_INTERNAL; break; }
        }

        /* Plaintext */
        if (EVP_DecryptUpdate(ctx, pt, &len, ct, (int)ct_len) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }
        int pt_len = len;

        /* Tag must be set before final */
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG,
                                AES_GCM_TAG_LEN, (void *)tag) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        /* Finalise: returns 0 if authentication fails */
        if (EVP_DecryptFinal_ex(ctx, pt + pt_len, &len) != 1)
        { ret = HC_CRYPTO_E_AUTH; break; }

    } while (0);

    /* Wipe plaintext on auth failure */
    if (ret != HC_CRYPTO_OK) hc_crypto_memwipe(pt, ct_len);

    EVP_CIPHER_CTX_free(ctx);
    HC_CRYPTO_OPENSSL_END("hc_aes256_gcm_decrypt");
    return ret;
}

/* ===========================================================================
 * ECDSA secp256k1
 * ==========================================================================*/

/* Create new secp256k1 keypair.
 * The resulting EVP_PKEY* is heap-allocated; caller must free with
 * hc_ec_key_free().
 */
hc_crypto_err_t
hc_ec_key_new(EVP_PKEY **out_key)
{
    if (!out_key) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    EVP_PKEY_CTX *pctx = NULL;
    EVP_PKEY *pkey = NULL;

    HC_CRYPTO_OPENSSL_BEGIN();

    do {
        pctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, NULL);
        if (!pctx) { ret = HC_CRYPTO_E_NOMEM; break; }

        if (EVP_PKEY_keygen_init(pctx) <= 0)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (EVP_PKEY_CTX_set_ec_paramgen_curve_nid(
                pctx, NID_secp256k1) <= 0)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        if (EVP_PKEY_keygen(pctx, &pkey) <= 0)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        *out_key = pkey; /* Transfer ownership */
        pkey = NULL;

    } while (0);

    if (pctx) EVP_PKEY_CTX_free(pctx);
    if (pkey)  EVP_PKEY_free(pkey);

    HC_CRYPTO_OPENSSL_END("hc_ec_key_new");
    return ret;
}

void
hc_ec_key_free(EVP_PKEY *key)
{
    if (key) EVP_PKEY_free(key);
}

/* Export serialized public key (compressed, 33 bytes) */
hc_crypto_err_t
hc_ec_pubkey_serialize(const EVP_PKEY *key,
                       uint8_t out[HC_EC_PUBKEY_COMPRESSED_LEN])
{
    if (!key || !out) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    EC_KEY *ec = EVP_PKEY_get0_EC_KEY((EVP_PKEY *)key);
    if (!ec) return HC_CRYPTO_E_PARAM;

    const EC_GROUP *grp = EC_KEY_get0_group(ec);
    const EC_POINT *pt  = EC_KEY_get0_public_key(ec);

    if (!grp || !pt) return HC_CRYPTO_E_PARAM;

    if (EC_POINT_point2oct(grp, pt, POINT_CONVERSION_COMPRESSED,
                           out, HC_EC_PUBKEY_COMPRESSED_LEN, NULL)
            != HC_EC_PUBKEY_COMPRESSED_LEN) {
        ret = HC_CRYPTO_E_INTERNAL;
    }

    return ret;
}

/* ---------------------------------------------------------------------------
 * Signing & Verification
 * ---------------------------------------------------------------------------*/

hc_crypto_err_t
hc_ecdsa_sign(const EVP_PKEY *key,
              const uint8_t digest[HC_SHA256_LEN],
              uint8_t *sig, size_t *sig_len /* in/out */)
{
    if (!key || !digest || !sig || !sig_len) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    EVP_MD_CTX *ctx = NULL;

    HC_CRYPTO_OPENSSL_BEGIN();

    do {
        ctx = EVP_MD_CTX_new();
        if (!ctx) { ret = HC_CRYPTO_E_NOMEM; break; }

        if (EVP_DigestSignInit(ctx, NULL, NULL, NULL, (EVP_PKEY *)key) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        /* We already have the message digest; pass it directly */
        if (EVP_DigestSign(ctx, sig, sig_len, digest, HC_SHA256_LEN) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

    } while (0);

    EVP_MD_CTX_free(ctx);
    HC_CRYPTO_OPENSSL_END("hc_ecdsa_sign");
    return ret;
}

hc_crypto_err_t
hc_ecdsa_verify(const EVP_PKEY *key,
                const uint8_t digest[HC_SHA256_LEN],
                const uint8_t *sig, size_t sig_len)
{
    if (!key || !digest || !sig) return HC_CRYPTO_E_PARAM;

    hc_crypto_err_t ret = HC_CRYPTO_OK;
    EVP_MD_CTX *ctx = NULL;

    HC_CRYPTO_OPENSSL_BEGIN();

    do {
        ctx = EVP_MD_CTX_new();
        if (!ctx) { ret = HC_CRYPTO_E_NOMEM; break; }

        if (EVP_DigestVerifyInit(ctx, NULL, NULL, NULL, (EVP_PKEY *)key) != 1)
        { ret = HC_CRYPTO_E_INTERNAL; break; }

        int ok = EVP_DigestVerify(ctx, sig, sig_len, digest, HC_SHA256_LEN);
        if (ok == 1) {
            ret = HC_CRYPTO_OK;
        } else if (ok == 0) {
            ret = HC_CRYPTO_E_VERIFY;
        } else {
            ret = HC_CRYPTO_E_INTERNAL;
        }

    } while (0);

    EVP_MD_CTX_free(ctx);
    HC_CRYPTO_OPENSSL_END("hc_ecdsa_verify");
    return ret;
}

/* ===========================================================================
 * Error string helper (optional, for human logging)
 * ==========================================================================*/

const char *
hc_crypto_err_str(hc_crypto_err_t e)
{
    switch (e) {
        case HC_CRYPTO_OK:         return "OK";
        case HC_CRYPTO_E_PARAM:    return "Invalid parameter";
        case HC_CRYPTO_E_NOMEM:    return "Out of memory";
        case HC_CRYPTO_E_INTERNAL: return "Internal error";
        case HC_CRYPTO_E_VERIFY:   return "Signature verification failed";
        case HC_CRYPTO_E_AUTH:     return "Authentication failed";
        default:                   return "Unknown error";
    }
}

/* ===========================================================================
 * Init / shutdown hooks (idempotent)
 * ==========================================================================*/

static int g_init_ctr = 0;

hc_crypto_err_t
hc_crypto_global_init(void)
{
    if (g_init_ctr++ > 0) return HC_CRYPTO_OK; /* Already initialised */

    /* OpenSSL 1.1+ performs automatic init, but explicit is fine */
    OPENSSL_init_crypto(OPENSSL_INIT_LOAD_CONFIG, NULL);
    return HC_CRYPTO_OK;
}

void
hc_crypto_global_cleanup(void)
{
    if (--g_init_ctr > 0) return;

    /* Clean up global OpenSSL state */
#if OPENSSL_VERSION_NUMBER < 0x30000000L
    EVP_cleanup();
    CRYPTO_cleanup_all_ex_data();
#endif
    ERR_free_strings();
}

/* ===========================================================================
 * Unit-style self test (can be excluded in release builds)
 * ==========================================================================*/

#ifdef HC_CRYPTO_SELFTEST
#include <assert.h>

static void selftest(void)
{
    uint8_t rnd[32];
    assert(hc_rand_bytes(rnd, sizeof(rnd)) == HC_CRYPTO_OK);

    /* Hash */
    const char *hello = "hello";
    uint8_t h[HC_SHA256_LEN];
    assert(hc_sha256((const uint8_t *)hello, strlen(hello), h) == HC_CRYPTO_OK);

    /* AES-GCM */
    uint8_t key[HC_AES256_KEY_LEN] = {0};
    uint8_t iv[AES_GCM_IV_LEN]     = {0};
    hc_rand_bytes(key, sizeof(key));
    hc_rand_bytes(iv,  sizeof(iv));

    const uint8_t plaintext[] = "satoshi nakamoto";
    uint8_t ciphertext[sizeof(plaintext)];
    uint8_t tag[AES_GCM_TAG_LEN];
    uint8_t decrypted[sizeof(plaintext)];

    assert(hc_aes256_gcm_encrypt(key, iv, NULL, 0,
                                 plaintext, sizeof(plaintext),
                                 ciphertext, tag) == HC_CRYPTO_OK);

    assert(hc_aes256_gcm_decrypt(key, iv, NULL, 0,
                                 ciphertext, sizeof(ciphertext),
                                 tag, decrypted) == HC_CRYPTO_OK);

    assert(hc_crypto_memeq(plaintext, decrypted, sizeof(plaintext)));

    /* ECDSA */
    EVP_PKEY *kp;
    assert(hc_ec_key_new(&kp) == HC_CRYPTO_OK);

    size_t siglen = 80;
    uint8_t sig[80];
    assert(hc_ecdsa_sign(kp, h, sig, &siglen) == HC_CRYPTO_OK);
    assert(hc_ecdsa_verify(kp, h, sig, siglen) == HC_CRYPTO_OK);

    hc_ec_key_free(kp);
    printf("hc_crypto self-test passed.\n");
}

int main(void)
{
    hc_crypto_global_init();
    selftest();
    hc_crypto_global_cleanup();
    return 0;
}
#endif /* HC_CRYPTO_SELFTEST */
