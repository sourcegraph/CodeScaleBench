/**
 * HoloCanvas – Cryptograph Micro-Service
 * --------------------------------------
 * File:    HoloCanvas/services/cryptograph/include/cryptograph.h
 * License: Apache-2.0
 *
 * Public facing API for all cryptographic operations performed inside the
 * HoloCanvas stack.  This header is intentionally self-contained and does
 * not leak implementation details, enabling the Cryptograph service to be
 * swapped (e.g., OpenSSL, libsodium, PKCS#11 HSM) without recompiling the
 * surrounding micro-services.
 *
 * Usage:
 *      #include "cryptograph.h"
 *
 *      cryptograph_global_init(NULL);             // optional cfg
 *      crypto_key_t *key = crypto_key_generate(CRYPTO_ECDSA_SECP256K1);
 *      crypto_hash_ctx_t *h = crypto_hash_ctx_create(CRYPTO_SHA3_256);
 *
 *      uint8_t digest[CRYPTO_MAX_HASH];
 *      crypto_hash_update(h, "Hello", 5);
 *      crypto_hash_final(h, digest, sizeof(digest));
 *
 *      crypto_sig_t sig;
 *      crypto_sign(key, digest, CRYPTO_SHA3_256_LEN, &sig);
 *
 *      bool ok = crypto_verify(&key->pub, digest, CRYPTO_SHA3_256_LEN, &sig);
 *      cryptograph_global_cleanup();
 */

#ifndef HOLOCANVAS_CRYPTOGRAPH_H
#define HOLOCANVAS_CRYPTOGRAPH_H

/*--------------------------------------------------------------------------*/
/*  System & 3rd-party headers (interface-level only—no implementation)     */
/*--------------------------------------------------------------------------*/
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*--------------------------------------------------------------------------*/
/*  Versioning                                                              */
/*--------------------------------------------------------------------------*/
#define CRYPTOGRAPH_API_VERSION_MAJOR   1
#define CRYPTOGRAPH_API_VERSION_MINOR   0
#define CRYPTOGRAPH_API_VERSION_PATCH   0

#define CRYPTOGRAPH_API_VERSION_STR  "1.0.0"

/*--------------------------------------------------------------------------*/
/*  Export / Import Macros (dllexport on Windows, visibility on *nix)       */
/*--------------------------------------------------------------------------*/
#if defined(_WIN32) && !defined(CRYPTOGRAPH_STATIC)
#   ifdef CRYPTOGRAPH_EXPORTS
#       define CRYPTO_API __declspec(dllexport)
#   else
#       define CRYPTO_API __declspec(dllimport)
#   endif
#elif defined(__GNUC__) && !defined(CRYPTOGRAPH_STATIC)
#   define CRYPTO_API __attribute__((visibility("default")))
#else
#   define CRYPTO_API
#endif

/*--------------------------------------------------------------------------*/
/*  Constants & Limits                                                     */
/*--------------------------------------------------------------------------*/
#define CRYPTO_MAX_HASH        64   /* Maximum digest size we support      */
#define CRYPTO_MAX_PUBKEY      65   /* 65-byte uncompressed SEC1           */
#define CRYPTO_MAX_PRIVKEY     80   /* Implementation-specific             */
#define CRYPTO_MAX_SIGNATURE   96   /* ECDSA r||s OR EdDSA                 */
#define CRYPTO_IV_SIZE         12   /* AES-GCM IV size                     */
#define CRYPTO_TAG_SIZE        16   /* AES-GCM Auth Tag                    */

/*--------------------------------------------------------------------------*/
/*  Enumerations                                                            */
/*--------------------------------------------------------------------------*/

/* Error / status codes (negative = fatal/error, 0 = success, positive = warn) */
typedef enum
{
    CRYPTO_OK                       = 0,

    CRYPTO_ERR_GENERIC              = -1000,
    CRYPTO_ERR_NOMEM                = -1001,
    CRYPTO_ERR_INVALID_ARG          = -1002,
    CRYPTO_ERR_UNSUPPORTED_ALGO     = -1003,
    CRYPTO_ERR_SIG_VERIFY_FAIL      = -1004,
    CRYPTO_ERR_KEY_PARSE            = -1005,
    CRYPTO_ERR_RNG_FAIL             = -1006,
    CRYPTO_ERR_CTX_INCOMPLETE       = -1007,
    CRYPTO_ERR_BUFFER_TOO_SMALL     = -1008
} crypto_err_t;

/* Hash / digest algorithms */
typedef enum
{
    CRYPTO_SHA2_256,
    CRYPTO_SHA3_256,
    CRYPTO_BLAKE3,
    CRYPTO_HASH_MAX
} crypto_hash_algo_t;

/* Digest sizes in bytes (match enum order) */
static const uint8_t g_crypto_hash_size[CRYPTO_HASH_MAX] = {
    32, /* SHA2-256   */
    32, /* SHA3-256   */
    32  /* BLAKE3     */
};

/* Asymmetric key algorithms */
typedef enum
{
    CRYPTO_ECDSA_SECP256K1,
    CRYPTO_ED25519,
    CRYPTO_KEY_ALGO_MAX
} crypto_key_algo_t;

/*--------------------------------------------------------------------------*/
/*  Opaque Structures                                                       */
/*--------------------------------------------------------------------------*/
typedef struct crypto_key            crypto_key_t;
typedef struct crypto_pubkey         crypto_pubkey_t;
typedef struct crypto_hash_ctx       crypto_hash_ctx_t;

/*--------------------------------------------------------------------------*/
/*  Simple Data Containers                                                  */
/*--------------------------------------------------------------------------*/
typedef struct
{
    uint8_t  bytes[CRYPTO_MAX_SIGNATURE];
    size_t   len;               /* Actual length populated by sign op */
} crypto_sig_t;

typedef struct
{
    uint8_t iv[CRYPTO_IV_SIZE];
    uint8_t tag[CRYPTO_TAG_SIZE];
} crypto_aead_hdr_t;

/*--------------------------------------------------------------------------*/
/*  Global  Init / Cleanup                                                  */
/*--------------------------------------------------------------------------*/

/**
 * cryptograph_global_init
 *
 * Initialise the Cryptograph service.  Must be called ONCE per process before
 * any other cryptograph_* API.  Thread-safe thereafter.
 *
 * cfg     – optional backend-specific configuration blob
 * cfg_len – length of cfg in bytes
 *
 * Returns CRYPTO_OK on success, or error code < 0.
 */
CRYPTO_API crypto_err_t
cryptograph_global_init(const void *cfg, size_t cfg_len);

/**
 * cryptograph_global_cleanup
 *
 * Release global resources (DRBG, FIPS provider, etc.).  No further calls to
 * the API are legal after this function has returned.
 */
CRYPTO_API void
cryptograph_global_cleanup(void);

/*--------------------------------------------------------------------------*/
/*  Randomness                                                              */
/*--------------------------------------------------------------------------*/

/* Fills `buf` with cryptographically secure random bytes. */
CRYPTO_API crypto_err_t
crypto_random_bytes(void *buf, size_t len);

/*--------------------------------------------------------------------------*/
/*  Hashing                                                                 */
/*--------------------------------------------------------------------------*/

/* Allocate & initialise a streaming hash context. */
CRYPTO_API crypto_hash_ctx_t *
crypto_hash_ctx_create(crypto_hash_algo_t algo);

/* Incrementally feed data into the hash. */
CRYPTO_API crypto_err_t
crypto_hash_update(crypto_hash_ctx_t *ctx, const void *data, size_t len);

/* Finalise the hash; writes up to `digest_len` bytes into `digest`.           *
 * digest_len must be >= algorithm digest size (see g_crypto_hash_size).      */
CRYPTO_API crypto_err_t
crypto_hash_final(crypto_hash_ctx_t *ctx, void *digest, size_t digest_len);

/* Shortcut helper: one-shot convenience wrapper. */
CRYPTO_API crypto_err_t
crypto_hash(crypto_hash_algo_t algo,
            const void       *data,
            size_t            len,
            void             *digest,
            size_t            digest_len);

/* Destroy (and securely zero) a hash context. */
CRYPTO_API void
crypto_hash_ctx_destroy(crypto_hash_ctx_t *ctx);

/*--------------------------------------------------------------------------*/
/*  Key Management                                                          */
/*--------------------------------------------------------------------------*/

/* Generate a new private key of a given algorithm using CSPRNG */
CRYPTO_API crypto_key_t *
crypto_key_generate(crypto_key_algo_t algo);

/* Parse/Import a serialized private key (raw / DER / PEM, backend dependant) */
CRYPTO_API crypto_key_t *
crypto_key_from_bytes(crypto_key_algo_t algo, const void *buf, size_t len);

/* Export a private key in implementation-defined raw format.                *
 * Use NULL buf to query required length.                                    */
CRYPTO_API crypto_err_t
crypto_key_serialize(const crypto_key_t *key, void *buf, size_t *len);

/* Retrieve the matching public key */
CRYPTO_API const crypto_pubkey_t *
crypto_key_pub(const crypto_key_t *key);

/* Destroy (securely zero) a private key */
CRYPTO_API void
crypto_key_destroy(crypto_key_t *key);

/* Serialize a public key (compressed SEC1 or EdDSA raw).                    *
 * Use NULL buf to query size.                                               */
CRYPTO_API crypto_err_t
crypto_pubkey_serialize(const crypto_pubkey_t *pk, void *buf, size_t *len);

/* Compare two public keys for equality (constant time). */
CRYPTO_API bool
crypto_pubkey_equal(const crypto_pubkey_t *a, const crypto_pubkey_t *b);

/*--------------------------------------------------------------------------*/
/*  Digital Signatures                                                      */
/*--------------------------------------------------------------------------*/

/* Sign an arbitrary message digest (the digest itself—not raw msg) */
CRYPTO_API crypto_err_t
crypto_sign(const crypto_key_t *key,
            const void         *digest,
            size_t              digest_len,
            crypto_sig_t       *sig_out);

/* Verify a signature against a digest */
CRYPTO_API crypto_err_t
crypto_verify(const crypto_pubkey_t *pub,
              const void            *digest,
              size_t                 digest_len,
              const crypto_sig_t    *sig);

/*--------------------------------------------------------------------------*/
/*  Authenticated Encryption (AEAD)                                         */
/*--------------------------------------------------------------------------*/

/* AES-256-GCM (or ChaCha-Poly1305 on platforms lacking AES) helper.          *
 * Automatically derives sub-keys from `key` through HKDF(SHA-256).           *
 * AAD (Additional Authenticated Data) may be NULL/0.                        *
 *  ‑ cipher_text can in-place overlap with plain_text.                       */
CRYPTO_API crypto_err_t
crypto_aead_encrypt(const crypto_key_t *key,
                    const void         *plain_text, size_t pt_len,
                    const void         *aad,        size_t aad_len,
                    crypto_aead_hdr_t  *hdr_out,
                    void               *cipher_text /* out/in-place */);

CRYPTO_API crypto_err_t
crypto_aead_decrypt(const crypto_key_t *key,
                    const crypto_aead_hdr_t *hdr,
                    const void             *cipher_text, size_t ct_len,
                    const void             *aad,         size_t aad_len,
                    void                   *plain_text /* out/in-place */);

/*--------------------------------------------------------------------------*/
/*  Utility                                                                 */
/*--------------------------------------------------------------------------*/

/**
 * crypto_secure_zero
 *
 * Constant-time memory zeroer guaranteed not to be optimised out by the
 * compiler (uses volatile pointer trick).
 */
static inline void
crypto_secure_zero(void *ptr, size_t len)
{
    volatile uint8_t *p = (volatile uint8_t *)ptr;
    while (len--) { *p++ = 0; }
}

/* Return textual representation of a crypto_err_t (for logging). */
CRYPTO_API const char *
crypto_err_str(crypto_err_t err);

/*--------------------------------------------------------------------------*/
/*  Event-Topic Canonicalisation                                            */
/*--------------------------------------------------------------------------*/

/**
 * crypto_topic_hash
 *
 * Produce a 256-bit (32-byte) canonical hash of an event topic plus optional
 * namespace.  This is used by the Event-Driven mesh (Kafka topic naming) to
 * deduplicate producers and prevent collision with user-supplied topic names.
 *
 *      namespace – ASCII URI component (e.g., "oracle/weather")
 *      topic     – UTF-8 event name (e.g., "rain-change")
 */
CRYPTO_API crypto_err_t
crypto_topic_hash(const char *namespace,
                  const char *topic,
                  uint8_t out_digest[32]); /* SHA3-256 */

/*--------------------------------------------------------------------------*/
/*  Compile-Time Checks                                                     */
/*--------------------------------------------------------------------------*/
#if CRYPTO_MAX_HASH < 32
#   error "CRYPTO_MAX_HASH must be >= 32 bytes"
#endif

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* HOLOCANVAS_CRYPTOGRAPH_H */
