/*
 * HoloCanvas – Cryptograph Microservice
 * File: crypto_service.c
 *
 * Description:
 *   Provides a thin, production-ready wrapper around OpenSSL for common
 *   cryptographic primitives used across the HoloCanvas platform:
 *     • Secure random‐number generation
 *     • SHA-256 hashing
 *     • secp256k1 key-pair generation, signing and verification
 *     • AES-256-GCM authenticated symmetric encryption
 *
 *   All public functions return 0 on success and a negative value on failure.
 *   The implementation is thread-safe as long as the caller initializes
 *   OpenSSL (openssl_thread_setup) once at process start.  Error details can
 *   be retrieved with crypto_last_error().
 *
 * Build:
 *   gcc -std=c11 -Wall -Wextra -pedantic -O2 \
 *       -I/usr/local/include -L/usr/local/lib \
 *       -lcrypto -o crypto_test crypto_service.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>
#include <errno.h>

#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/sha.h>
#include <openssl/rand.h>
#include <openssl/pem.h>
#include <openssl/err.h>

/* --------------------------------------------------------------------------
 *  Public Types
 * -------------------------------------------------------------------------- */

typedef struct {
    EVP_PKEY *pkey;   /* May hold private or public part */
} crypto_key_t;

/* --------------------------------------------------------------------------
 *  Private Helpers
 * -------------------------------------------------------------------------- */

#define CRYPTO_OK            (0)
#define CRYPTO_ERR_GENERIC   (-1)
#define CRYPTO_ERR_NOMEM     (-2)
#define CRYPTO_ERR_OPENSSL   (-3)
#define CRYPTO_ERR_VERIFY    (-4)
#define CRYPTO_ERR_PARAM     (-5)

/* Thread-local copy of the last error so callers can fetch it */
static _Thread_local int      g_last_err_code = CRYPTO_OK;
static _Thread_local uint32_t g_last_err_line = 0;
static _Thread_local char     g_last_err_msg[256];

#define SET_ERR(code, msg)                           \
    do {                                             \
        g_last_err_code = (code);                    \
        g_last_err_line = (uint32_t)__LINE__;        \
        strncpy(g_last_err_msg, (msg),               \
                sizeof(g_last_err_msg) - 1);         \
        g_last_err_msg[sizeof(g_last_err_msg) - 1] = '\0'; \
    } while (0)

/* Map OpenSSL error stack to our own code base. */
static int set_openssl_err(const char *fn_ctx)
{
    unsigned long err = ERR_peek_last_error();
    if (err) {
        char buf[120];
        ERR_error_string_n(err, buf, sizeof buf);

        char full[256];
        snprintf(full, sizeof full, "%s: %s", fn_ctx, buf);
        SET_ERR(CRYPTO_ERR_OPENSSL, full);
    } else {
        SET_ERR(CRYPTO_ERR_OPENSSL, fn_ctx);
    }
    return CRYPTO_ERR_OPENSSL;
}

/* --------------------------------------------------------------------------
 *  Public Error-Handling API
 * -------------------------------------------------------------------------- */

/* Retrieve and reset last error */
int crypto_last_error(char *msg_buf, size_t buf_len, uint32_t *line_no)
{
    if (!msg_buf || buf_len == 0) {
        return CRYPTO_ERR_PARAM;
    }
    strncpy(msg_buf, g_last_err_msg, buf_len - 1);
    msg_buf[buf_len - 1] = '\0';

    if (line_no) {
        *line_no = g_last_err_line;
    }
    return g_last_err_code;
}

/* --------------------------------------------------------------------------
 *  Initialization / Cleanup
 * -------------------------------------------------------------------------- */

int crypto_global_init(void)
{
    /* OpenSSL 1.1+ performs automatic init; still, load error strings for dbg */
    ERR_load_crypto_strings();
    OpenSSL_add_all_algorithms();
    if (RAND_poll() != 1) {
        return set_openssl_err("RAND_poll");
    }
    return CRYPTO_OK;
}

void crypto_global_cleanup(void)
{
    EVP_cleanup();
    ERR_free_strings();
}

/* --------------------------------------------------------------------------
 *  Random Bytes
 * -------------------------------------------------------------------------- */

int crypto_random(uint8_t *buf, size_t len)
{
    if (!buf || len == 0) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_random: invalid buf/len");
        return CRYPTO_ERR_PARAM;
    }
    if (RAND_bytes(buf, (int)len) != 1) {
        return set_openssl_err("RAND_bytes");
    }
    return CRYPTO_OK;
}

/* --------------------------------------------------------------------------
 *  SHA-256 Hashing
 * -------------------------------------------------------------------------- */

#define SHA256_SIZE 32

int crypto_sha256(const uint8_t *data, size_t data_len, uint8_t out[SHA256_SIZE])
{
    if (!data || data_len == 0 || !out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_sha256: bad params");
        return CRYPTO_ERR_PARAM;
    }
    SHA256_CTX ctx;
    if (SHA256_Init(&ctx) != 1 ||
        SHA256_Update(&ctx, data, data_len) != 1 ||
        SHA256_Final(out, &ctx) != 1) {
        return set_openssl_err("SHA256_*");
    }
    return CRYPTO_OK;
}

/* --------------------------------------------------------------------------
 *  secp256k1 Public/Private-Key Support
 * -------------------------------------------------------------------------- */

static EVP_PKEY *generate_secp256k1_keypair(void)
{
    EVP_PKEY_CTX *pctx = EVP_PKEY_CTX_new_id(EVP_PKEY_EC, NULL);
    if (!pctx) {
        set_openssl_err("EVP_PKEY_CTX_new_id");
        return NULL;
    }

    if (EVP_PKEY_paramgen_init(pctx) <= 0 ||
        EVP_PKEY_CTX_set_ec_paramgen_curve_nid(pctx, NID_secp256k1) <= 0) {
        set_openssl_err("EVP_PKEY_paramgen_init");
        EVP_PKEY_CTX_free(pctx);
        return NULL;
    }

    EVP_PKEY *params = NULL;
    if (EVP_PKEY_paramgen(pctx, &params) <= 0) {
        set_openssl_err("EVP_PKEY_paramgen");
        EVP_PKEY_CTX_free(pctx);
        return NULL;
    }
    EVP_PKEY_CTX_free(pctx);

    EVP_PKEY_CTX *kctx = EVP_PKEY_CTX_new(params, NULL);
    if (!kctx) {
        set_openssl_err("EVP_PKEY_CTX_new");
        EVP_PKEY_free(params);
        return NULL;
    }

    if (EVP_PKEY_keygen_init(kctx) <= 0) {
        set_openssl_err("EVP_PKEY_keygen_init");
        EVP_PKEY_CTX_free(kctx);
        EVP_PKEY_free(params);
        return NULL;
    }

    EVP_PKEY *pkey = NULL;
    if (EVP_PKEY_keygen(kctx, &pkey) <= 0) {
        set_openssl_err("EVP_PKEY_keygen");
        EVP_PKEY_CTX_free(kctx);
        EVP_PKEY_free(params);
        return NULL;
    }

    EVP_PKEY_CTX_free(kctx);
    EVP_PKEY_free(params);
    return pkey;
}

int crypto_keypair_generate(crypto_key_t *priv_out, crypto_key_t *pub_out)
{
    if (!priv_out || !pub_out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_keypair_generate: null ptr");
        return CRYPTO_ERR_PARAM;
    }
    memset(priv_out, 0, sizeof *priv_out);
    memset(pub_out, 0, sizeof *pub_out);

    EVP_PKEY *kp = generate_secp256k1_keypair();
    if (!kp) {
        /* Error already set */
        return CRYPTO_ERR_OPENSSL;
    }

    /* Extract public key */
    EVP_PKEY *pub = EVP_PKEY_new();
    if (!pub) {
        EVP_PKEY_free(kp);
        return set_openssl_err("EVP_PKEY_new");
    }
    if (EVP_PKEY_set_type(pub, EVP_PKEY_EC) != 1 ||
        EVP_PKEY_copy_parameters(pub, kp) != 1) {
        set_openssl_err("EVP_PKEY_copy_parameters");
        EVP_PKEY_free(kp);
        EVP_PKEY_free(pub);
        return CRYPTO_ERR_OPENSSL;
    }

    /* Duplicate key to hold only public component */
    EC_KEY *ec_key = EVP_PKEY_get0_EC_KEY(kp);
    const EC_POINT *pub_point = EC_KEY_get0_public_key(ec_key);
    const EC_GROUP *group = EC_KEY_get0_group(ec_key);

    EC_KEY *ec_pub = EC_KEY_new();
    if (!ec_pub) {
        EVP_PKEY_free(kp);
        EVP_PKEY_free(pub);
        return set_openssl_err("EC_KEY_new");
    }
    if (EC_KEY_set_group(ec_pub, group) != 1 ||
        EC_KEY_set_public_key(ec_pub, pub_point) != 1 ||
        EVP_PKEY_assign_EC_KEY(pub, ec_pub) != 1) {
        set_openssl_err("EC_KEY_set_*");
        EVP_PKEY_free(kp);
        EVP_PKEY_free(pub);
        EC_KEY_free(ec_pub); /* if assign failed */
        return CRYPTO_ERR_OPENSSL;
    }

    priv_out->pkey = kp;
    pub_out->pkey  = pub;
    return CRYPTO_OK;
}

void crypto_key_free(crypto_key_t *ckey)
{
    if (ckey && ckey->pkey) {
        EVP_PKEY_free(ckey->pkey);
        ckey->pkey = NULL;
    }
}

/* --------------------------------------------------------------------------
 *  ECDSA (secp256k1) Sign / Verify
 * -------------------------------------------------------------------------- */

int crypto_sign(const crypto_key_t *priv,
                const uint8_t *msg, size_t msg_len,
                uint8_t **sig_out, size_t *sig_len_out)
{
    if (!priv || !priv->pkey || !msg || msg_len == 0 || !sig_out || !sig_len_out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_sign: bad params");
        return CRYPTO_ERR_PARAM;
    }

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) {
        return set_openssl_err("EVP_MD_CTX_new");
    }

    if (EVP_DigestSignInit(ctx, NULL, EVP_sha256(), NULL, priv->pkey) != 1) {
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestSignInit");
    }

    if (EVP_DigestSignUpdate(ctx, msg, msg_len) != 1) {
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestSignUpdate");
    }

    size_t req = 0;
    if (EVP_DigestSignFinal(ctx, NULL, &req) != 1) {
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestSignFinal (size)");
    }

    uint8_t *sig_buf = malloc(req);
    if (!sig_buf) {
        EVP_MD_CTX_free(ctx);
        SET_ERR(CRYPTO_ERR_NOMEM, "malloc");
        return CRYPTO_ERR_NOMEM;
    }

    if (EVP_DigestSignFinal(ctx, sig_buf, &req) != 1) {
        free(sig_buf);
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestSignFinal");
    }

    EVP_MD_CTX_free(ctx);
    *sig_out = sig_buf;
    *sig_len_out = req;
    return CRYPTO_OK;
}

int crypto_verify(const crypto_key_t *pub,
                  const uint8_t *msg, size_t msg_len,
                  const uint8_t *sig, size_t sig_len)
{
    if (!pub || !pub->pkey || !msg || msg_len == 0 || !sig || sig_len == 0) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_verify: bad params");
        return CRYPTO_ERR_PARAM;
    }

    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) {
        return set_openssl_err("EVP_MD_CTX_new");
    }

    if (EVP_DigestVerifyInit(ctx, NULL, EVP_sha256(), NULL, pub->pkey) != 1) {
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestVerifyInit");
    }

    if (EVP_DigestVerifyUpdate(ctx, msg, msg_len) != 1) {
        EVP_MD_CTX_free(ctx);
        return set_openssl_err("EVP_DigestVerifyUpdate");
    }

    int ret = EVP_DigestVerifyFinal(ctx, sig, sig_len);
    EVP_MD_CTX_free(ctx);

    if (ret == 1) {
        return CRYPTO_OK;
    } else if (ret == 0) {
        SET_ERR(CRYPTO_ERR_VERIFY, "signature mismatch");
        return CRYPTO_ERR_VERIFY;
    } else {
        return set_openssl_err("EVP_DigestVerifyFinal");
    }
}

/* --------------------------------------------------------------------------
 *  AES-256-GCM Symmetric Encryption
 * -------------------------------------------------------------------------- */

#define AES_GCM_IV_LEN  12
#define AES_GCM_TAG_LEN 16
#define AES_256_KEY_LEN 32

int crypto_aes256gcm_encrypt(const uint8_t key[AES_256_KEY_LEN],
                             const uint8_t *iv, size_t iv_len,
                             const uint8_t *aad, size_t aad_len,
                             const uint8_t *plaintext, size_t pt_len,
                             uint8_t **ct_out, size_t *ct_len_out,
                             uint8_t tag_out[AES_GCM_TAG_LEN])
{
    if (!key || !iv || iv_len != AES_GCM_IV_LEN || !plaintext ||
        pt_len == 0 || !ct_out || !ct_len_out || !tag_out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_aes256gcm_encrypt: bad params");
        return CRYPTO_ERR_PARAM;
    }

    int ret = CRYPTO_ERR_GENERIC;
    EVP_CIPHER_CTX *ctx = NULL;
    uint8_t *ciphertext = NULL;
    int len = 0, ct_len = 0;

    ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        return set_openssl_err("EVP_CIPHER_CTX_new");
    }

    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1 ||
        EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, (int)iv_len, NULL) != 1 ||
        EVP_EncryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        ret = set_openssl_err("EVP_EncryptInit_ex");
        goto cleanup;
    }

    if (aad && aad_len > 0 &&
        EVP_EncryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1) {
        ret = set_openssl_err("EVP_EncryptUpdate (AAD)");
        goto cleanup;
    }

    ciphertext = malloc(pt_len);
    if (!ciphertext) {
        SET_ERR(CRYPTO_ERR_NOMEM, "malloc");
        ret = CRYPTO_ERR_NOMEM;
        goto cleanup;
    }

    if (EVP_EncryptUpdate(ctx, ciphertext, &len, plaintext, (int)pt_len) != 1) {
        ret = set_openssl_err("EVP_EncryptUpdate");
        goto cleanup;
    }
    ct_len = len;

    if (EVP_EncryptFinal_ex(ctx, ciphertext + len, &len) != 1) {
        ret = set_openssl_err("EVP_EncryptFinal_ex");
        goto cleanup;
    }
    ct_len += len;

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG,
                            AES_GCM_TAG_LEN, tag_out) != 1) {
        ret = set_openssl_err("EVP_CTRL_GCM_GET_TAG");
        goto cleanup;
    }

    *ct_out     = ciphertext;
    *ct_len_out = (size_t)ct_len;
    ciphertext  = NULL; /* ownership transferred */
    ret = CRYPTO_OK;

cleanup:
    EVP_CIPHER_CTX_free(ctx);
    free(ciphertext);
    return ret;
}

int crypto_aes256gcm_decrypt(const uint8_t key[AES_256_KEY_LEN],
                             const uint8_t *iv, size_t iv_len,
                             const uint8_t *aad, size_t aad_len,
                             const uint8_t tag[AES_GCM_TAG_LEN],
                             const uint8_t *ciphertext, size_t ct_len,
                             uint8_t **pt_out, size_t *pt_len_out)
{
    if (!key || !iv || iv_len != AES_GCM_IV_LEN || !tag ||
        !ciphertext || ct_len == 0 || !pt_out || !pt_len_out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_aes256gcm_decrypt: bad params");
        return CRYPTO_ERR_PARAM;
    }

    int ret = CRYPTO_ERR_GENERIC;
    EVP_CIPHER_CTX *ctx = NULL;
    uint8_t *plaintext = NULL;
    int len = 0, pt_len = 0;

    ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        return set_openssl_err("EVP_CIPHER_CTX_new");
    }

    if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1 ||
        EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, (int)iv_len, NULL) != 1 ||
        EVP_DecryptInit_ex(ctx, NULL, NULL, key, iv) != 1) {
        ret = set_openssl_err("EVP_DecryptInit_ex");
        goto cleanup;
    }

    if (aad && aad_len > 0 &&
        EVP_DecryptUpdate(ctx, NULL, &len, aad, (int)aad_len) != 1) {
        ret = set_openssl_err("EVP_DecryptUpdate (AAD)");
        goto cleanup;
    }

    plaintext = malloc(ct_len);
    if (!plaintext) {
        SET_ERR(CRYPTO_ERR_NOMEM, "malloc");
        ret = CRYPTO_ERR_NOMEM;
        goto cleanup;
    }

    if (EVP_DecryptUpdate(ctx, plaintext, &len, ciphertext, (int)ct_len) != 1) {
        ret = set_openssl_err("EVP_DecryptUpdate");
        goto cleanup;
    }
    pt_len = len;

    if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG,
                            AES_GCM_TAG_LEN, (void *)tag) != 1) {
        ret = set_openssl_err("EVP_CTRL_GCM_SET_TAG");
        goto cleanup;
    }

    if (EVP_DecryptFinal_ex(ctx, plaintext + len, &len) != 1) {
        /* Authentication failed */
        SET_ERR(CRYPTO_ERR_VERIFY, "GCM tag mismatch");
        ret = CRYPTO_ERR_VERIFY;
        goto cleanup;
    }
    pt_len += len;

    *pt_out     = plaintext;
    *pt_len_out = (size_t)pt_len;
    plaintext   = NULL; /* ownership transferred */
    ret = CRYPTO_OK;

cleanup:
    EVP_CIPHER_CTX_free(ctx);
    free(plaintext);
    return ret;
}

/* --------------------------------------------------------------------------
 *  PEM (de)serialization helpers
 * -------------------------------------------------------------------------- */

int crypto_privkey_save_pem(const crypto_key_t *priv, const char *path)
{
    if (!priv || !priv->pkey || !path) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_privkey_save_pem");
        return CRYPTO_ERR_PARAM;
    }

    FILE *f = fopen(path, "wb");
    if (!f) {
        SET_ERR(-errno, "fopen");
        return -errno;
    }

    int ok = PEM_write_PrivateKey(f, priv->pkey, NULL, NULL, 0, NULL, NULL);
    fclose(f);
    if (!ok) {
        return set_openssl_err("PEM_write_PrivateKey");
    }
    return CRYPTO_OK;
}

int crypto_pubkey_save_pem(const crypto_key_t *pub, const char *path)
{
    if (!pub || !pub->pkey || !path) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_pubkey_save_pem");
        return CRYPTO_ERR_PARAM;
    }

    FILE *f = fopen(path, "wb");
    if (!f) {
        SET_ERR(-errno, "fopen");
        return -errno;
    }

    int ok = PEM_write_PUBKEY(f, pub->pkey);
    fclose(f);
    if (!ok) {
        return set_openssl_err("PEM_write_PUBKEY");
    }
    return CRYPTO_OK;
}

int crypto_privkey_load_pem(const char *path, crypto_key_t *out)
{
    if (!path || !out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_privkey_load_pem");
        return CRYPTO_ERR_PARAM;
    }

    FILE *f = fopen(path, "rb");
    if (!f) {
        SET_ERR(-errno, "fopen");
        return -errno;
    }

    EVP_PKEY *pkey = PEM_read_PrivateKey(f, NULL, NULL, NULL);
    fclose(f);
    if (!pkey) {
        return set_openssl_err("PEM_read_PrivateKey");
    }

    out->pkey = pkey;
    return CRYPTO_OK;
}

int crypto_pubkey_load_pem(const char *path, crypto_key_t *out)
{
    if (!path || !out) {
        SET_ERR(CRYPTO_ERR_PARAM, "crypto_pubkey_load_pem");
        return CRYPTO_ERR_PARAM;
    }

    FILE *f = fopen(path, "rb");
    if (!f) {
        SET_ERR(-errno, "fopen");
        return -errno;
    }

    EVP_PKEY *pkey = PEM_read_PUBKEY(f, NULL, NULL, NULL);
    fclose(f);
    if (!pkey) {
        return set_openssl_err("PEM_read_PUBKEY");
    }

    out->pkey = pkey;
    return CRYPTO_OK;
}

/* --------------------------------------------------------------------------
 *  Self-Test (may be compiled out in production)
 * -------------------------------------------------------------------------- */

#ifdef CRYPTO_SERVICE_TEST
#include <assert.h>

static void self_test(void)
{
    uint8_t rnd[32];
    assert(crypto_random(rnd, sizeof rnd) == CRYPTO_OK);

    /* Hash */
    uint8_t hash[SHA256_SIZE];
    assert(crypto_sha256((uint8_t*)"abc", 3, hash) == CRYPTO_OK);

    /* Key pair */
    crypto_key_t priv = {0}, pub = {0};
    assert(crypto_keypair_generate(&priv, &pub) == CRYPTO_OK);

    /* Sign/Verify */
    const char *msg = "Hello, HoloCanvas!";
    uint8_t *sig = NULL;
    size_t sig_len = 0;

    assert(crypto_sign(&priv, (uint8_t*)msg, strlen(msg), &sig, &sig_len) == CRYPTO_OK);
    assert(crypto_verify(&pub, (uint8_t*)msg, strlen(msg), sig, sig_len) == CRYPTO_OK);
    free(sig);

    /* AEAD */
    uint8_t key[AES_256_KEY_LEN];
    assert(crypto_random(key, sizeof key) == CRYPTO_OK);

    uint8_t iv[AES_GCM_IV_LEN];
    assert(crypto_random(iv, sizeof iv) == CRYPTO_OK);

    uint8_t tag[AES_GCM_TAG_LEN];
    uint8_t *ct = NULL, *pt = NULL;
    size_t ct_len = 0, pt_len = 0;

    assert(crypto_aes256gcm_encrypt(key, iv, sizeof iv,
                                    NULL, 0,
                                    (uint8_t*)msg, strlen(msg),
                                    &ct, &ct_len, tag) == CRYPTO_OK);

    assert(crypto_aes256gcm_decrypt(key, iv, sizeof iv,
                                    NULL, 0, tag,
                                    ct, ct_len,
                                    &pt, &pt_len) == CRYPTO_OK);

    assert(pt_len == strlen(msg) && memcmp(pt, msg, pt_len) == 0);

    free(ct);
    free(pt);
    crypto_key_free(&priv);
    crypto_key_free(&pub);

    puts("crypto_service self-test OK");
}

int main(void)
{
    assert(crypto_global_init() == CRYPTO_OK);
    self_test();
    crypto_global_cleanup();
    return 0;
}
#endif /* CRYPTO_SERVICE_TEST */
