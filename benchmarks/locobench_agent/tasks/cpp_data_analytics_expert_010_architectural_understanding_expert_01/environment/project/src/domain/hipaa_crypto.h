#pragma once
/**************************************************************************************************
 *  File:    hipaa_crypto.h
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      A lightweight, yet production-ready, cryptography façade that wraps OpenSSL and provides
 *      HIPAA-grade encryption primitives (AES-256-GCM & RSA-OAEP) for data-at-rest and
 *      data-in-transit.  The public interface deliberately hides OpenSSL details while exposing a
 *      domain-specific, exception-safe API that integrates seamlessly with the rest of
 *      CardioInsight360.
 *
 *  Design goals:
 *      • Provide a minimal, testable surface area—nothing more than what the engine needs.
 *      • Fail fast with strong exception guarantees and detailed diagnostic information.
 *      • Keep all OpenSSL initialization/cleanup under strict RAII control.
 *      • Default to FIPS-validated algorithms where available.
 *
 *  Note:
 *      Only relatively small helper functions are implemented inline for header-only convenience.
 *      Heavy-weight logic (batch encryption, streaming transformers, etc.) lives in the
 *      corresponding *.cpp compilation unit.
 *
 *  Copyright:
 *      © 2024 CardioInsight360.  All rights reserved.
 **************************************************************************************************/
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/err.h>
#include <openssl/fips.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace ci360::domain {

/*======================================================================================================================
 *  Utility helpers
 *====================================================================================================================*/

namespace detail {

/**
 * Hex-encode arbitrary binary data.
 */
inline std::string hexEncode(const std::vector<std::uint8_t>& data) {
    std::ostringstream oss;
    for (auto byte : data) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(byte);
    }
    return oss.str();
}

/**
 * Hex-decode into a byte vector.  Throws std::invalid_argument for malformed input.
 */
inline std::vector<std::uint8_t> hexDecode(std::string_view hex) {
    if (hex.size() % 2 != 0) {
        throw std::invalid_argument("hex string has odd length");
    }
    std::vector<std::uint8_t> data(hex.size() / 2);
    for (std::size_t i = 0; i < data.size(); ++i) {
        unsigned int byte;
        std::istringstream iss(std::string(hex.substr(i * 2, 2)));
        iss >> std::hex >> byte;
        if (iss.fail()) {
            throw std::invalid_argument("hex string contains non-hex characters");
        }
        data[i] = static_cast<std::uint8_t>(byte);
    }
    return data;
}

/**
 * Generate cryptographically secure random bytes.
 */
inline std::vector<std::uint8_t> randomBytes(std::size_t len) {
    std::vector<std::uint8_t> buf(len);
    if (RAND_bytes(buf.data(), static_cast<int>(len)) != 1) {
        throw std::runtime_error("RAND_bytes failed");
    }
    return buf;
}

} // namespace detail

/*======================================================================================================================
 *  Exceptions
 *====================================================================================================================*/

/**
 * Domain-specific exception used by all cryptographic operations.  Captures the most recent
 * OpenSSL error stack for easier diagnostics.
 */
class CryptoException final : public std::runtime_error {
public:
    explicit CryptoException(const std::string& what_arg)
        : std::runtime_error(what_arg + ": " + fetchOpenSSLErrors()) {}

private:
    static std::string fetchOpenSSLErrors() {
        std::ostringstream oss;
        unsigned long err = 0;
        while ((err = ERR_get_error()) != 0) {
            oss << ERR_error_string(err, nullptr) << '\n';
        }
        return oss.str();
    }
};

/*======================================================================================================================
 *  Type definitions
 *====================================================================================================================*/

/**
 * Symmetric and asymmetric ciphers supported inside the platform.
 */
enum class CipherType {
    AES_256_GCM,
    AES_128_CBC,
    RSA_OAEP,
    CHACHA20_POLY1305
};

/**
 * Transport metadata that accompanies every ciphertext blob when stored or transmitted.  Caller
 * fills or inspects the structure but should not rely on its exact wire layout.
 */
struct CipherMetadata {
    CipherType         cipher       {CipherType::AES_256_GCM};
    std::string        keyId;      // Id for symmetric key in KeyProvider
    std::string        iv;         // Hex-encoded IV / nonce
    std::string        tag;        // Hex-encoded authentication tag (for AEAD ciphers)

    /* Optional: algorithm parameters */
    std::string        aad;        // Hex-encoded additional authenticated data
};

/*======================================================================================================================
 *  Key management
 *====================================================================================================================*/

/**
 * Abstract key provider that supplies encryption keys for symmetric operations.  In production
 * this will be implemented by HSM or KMS back-ends (AWS KMS, Azure Key Vault, on-prem Thales, etc.)
 * but for unit tests an in-memory default provider is supplied below.
 */
class KeyProvider {
public:
    virtual ~KeyProvider() = default;

    /**
     * Retrieve the raw key material for a given keyId.  Throws CryptoException if the key cannot
     * be found or accessed.
     */
    virtual std::vector<std::uint8_t> getKey(const std::string& keyId) const = 0;

    /**
     * Generate a new data key suitable for the requested cipher.  The outKey vector will contain
     * the raw key bytes; the returned string is the newly minted keyId to be stored in
     * CipherMetadata.  Implementations are free to delegate key generation to a hardware module.
     */
    virtual std::string generateDataKey(CipherType cipher,
                                        std::vector<std::uint8_t>& outKey)            = 0;
};

/*------------------------------------------------ In-memory provider (testing only) -----*/
class InMemoryKeyProvider final : public KeyProvider {
public:
    std::vector<std::uint8_t> getKey(const std::string& keyId) const override {
        auto it = m_keys.find(keyId);
        if (it == m_keys.end())
            throw CryptoException("Key not found: " + keyId);
        return it->second;
    }

    std::string generateDataKey(CipherType cipher,
                                std::vector<std::uint8_t>& outKey) override {
        const std::size_t keyLen =
            (cipher == CipherType::AES_256_GCM) ? 32 :
            (cipher == CipherType::AES_128_CBC) ? 16 : 32; // default
        outKey = detail::randomBytes(keyLen);

        std::string keyId = "mem_" + detail::hexEncode(detail::randomBytes(8));
        m_keys.emplace(keyId, outKey);
        return keyId;
    }

private:
    mutable std::unordered_map<std::string, std::vector<std::uint8_t>> m_keys;
};

/*======================================================================================================================
 *  OpenSSL RAII context
 *====================================================================================================================*/

/**
 * Ensures that OpenSSL is properly initialised exactly once within the process and is cleaned up
 * after all cryptographic activities finish.  Thread-safe per OpenSSL >= 1.1.
 */
class CryptoContext {
public:
    CryptoContext() {
        if (OPENSSL_init_crypto(OPENSSL_INIT_LOAD_CONFIG, nullptr) != 1) {
            throw CryptoException("OPENSSL_init_crypto failed");
        }
        ERR_clear_error();
    }

    ~CryptoContext() {
        EVP_cleanup();
        ERR_free_strings();
    }

    CryptoContext(const CryptoContext&)            = delete;
    CryptoContext& operator=(const CryptoContext&) = delete;
};

/*======================================================================================================================
 *  HipaaCrypto – primary façade
 *====================================================================================================================*/
class HipaaCrypto final {
public:
    explicit HipaaCrypto(std::shared_ptr<KeyProvider> keyProvider)
        : m_keyProvider(std::move(keyProvider)) {
        if (!m_keyProvider) {
            throw std::invalid_argument("KeyProvider cannot be null");
        }
    }

    /**
     * Encrypt a clear-text blob.  Algorithm defaults to AES-256-GCM and the function will
     * automatically generate a fresh key and IV for every invocation, unless the caller pre-sets
     * metadata.keyId or metadata.iv.  The authentication tag is stored in metadata.tag.
     */
    std::vector<std::uint8_t> encrypt(const std::vector<std::uint8_t>& plaintext,
                                      CipherMetadata& metadata) const {
        /* Obtain or generate key */
        std::vector<std::uint8_t> key;
        if (metadata.keyId.empty()) {
            metadata.keyId = m_keyProvider->generateDataKey(metadata.cipher, key);
        } else {
            key = m_keyProvider->getKey(metadata.keyId);
        }

        switch (metadata.cipher) {
            case CipherType::AES_256_GCM:
                return aesEncrypt(plaintext, key, metadata);
            default:
                throw CryptoException("Unsupported cipher in encrypt()");
        }
    }

    /**
     * Decrypt a cipher-text blob using metadata previously attached to the message.
     */
    std::vector<std::uint8_t> decrypt(const std::vector<std::uint8_t>& ciphertext,
                                      const CipherMetadata& metadata) const {
        const auto key = m_keyProvider->getKey(metadata.keyId);

        switch (metadata.cipher) {
            case CipherType::AES_256_GCM:
                return aesDecrypt(ciphertext, key, metadata);
            default:
                throw CryptoException("Unsupported cipher in decrypt()");
        }
    }

    /**
     * Envelope encryption for small payloads (mainly configuration secrets) using the
     * recipient's RSA public key.  Internally, this generates a random AES-256-GCM data key and
     * encrypts it with RSA-OAEP; the cipher parameters are returned in metadata.
     */
    std::vector<std::uint8_t> encryptEnvelope(const std::vector<std::uint8_t>& /*plaintext*/,
                                              const std::string&               /*publicKeyPem*/,
                                              CipherMetadata&                  /*outMetadata*/) const;

    /**
     * Reverse operation of encryptEnvelope().  Decrypts an envelope using the provided RSA private
     * key (PEM) and optional passphrase.
     */
    std::vector<std::uint8_t>
    decryptEnvelope(const std::vector<std::uint8_t>& /*envelope*/,
                    const std::string&               /*privateKeyPem*/,
                    const CipherMetadata&            /*metadata*/,
                    const std::string&               /*passphrase*/ = {}) const;

    /**
     * Return true if OpenSSL FIPS mode is active in the current process.
     */
    static bool isOpenSSLFipsModeEnabled() {
#if OPENSSL_VERSION_NUMBER >= 0x30000000L
        return EVP_default_properties_is_fips_enabled(nullptr);
#else
        return FIPS_mode() != 0;
#endif
    }

private:
    /*=== Implementation details =====================================================================================*/
    std::vector<std::uint8_t> aesEncrypt(const std::vector<std::uint8_t>& plaintext,
                                         const std::vector<std::uint8_t>& key,
                                         CipherMetadata&                  metadata) const {
        static constexpr std::size_t GCM_IV_LEN  = 12;
        static constexpr std::size_t GCM_TAG_LEN = 16;

        if (metadata.iv.empty()) {
            metadata.iv = detail::hexEncode(detail::randomBytes(GCM_IV_LEN));
        }
        std::vector<std::uint8_t> iv = detail::hexDecode(metadata.iv);

        EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
        if (!ctx)
            throw CryptoException("EVP_CIPHER_CTX_new failed");

        auto ctxGuard = std::unique_ptr<EVP_CIPHER_CTX, decltype(&EVP_CIPHER_CTX_free)>(
            ctx, &EVP_CIPHER_CTX_free);

        const EVP_CIPHER* cipher = EVP_aes_256_gcm();
        if (EVP_EncryptInit_ex(ctx, cipher, nullptr, nullptr, nullptr) != 1)
            throw CryptoException("EVP_EncryptInit_ex failed (phase 1)");

        /* IV length must be set before actual key/IV init for GCM */
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, GCM_IV_LEN, nullptr) != 1)
            throw CryptoException("EVP_CIPHER_CTX_ctrl SET_IVLEN failed");

        if (EVP_EncryptInit_ex(ctx, nullptr, nullptr, key.data(), iv.data()) != 1)
            throw CryptoException("EVP_EncryptInit_ex failed (phase 2)");

        std::vector<std::uint8_t> ciphertext(plaintext.size());
        int len = 0;

        if (!metadata.aad.empty()) {
            const auto aadBytes = detail::hexDecode(metadata.aad);
            if (EVP_EncryptUpdate(ctx, nullptr, &len, aadBytes.data(),
                                  static_cast<int>(aadBytes.size())) != 1)
                throw CryptoException("EVP_EncryptUpdate failed (AAD)");
        }

        if (EVP_EncryptUpdate(ctx, ciphertext.data(), &len, plaintext.data(),
                              static_cast<int>(plaintext.size())) != 1)
            throw CryptoException("EVP_EncryptUpdate failed (payload)");
        int ciphertext_len = len;

        if (EVP_EncryptFinal_ex(ctx, ciphertext.data() + len, &len) != 1)
            throw CryptoException("EVP_EncryptFinal_ex failed");
        ciphertext_len += len;
        ciphertext.resize(ciphertext_len);

        /* Get authentication tag */
        std::array<std::uint8_t, GCM_TAG_LEN> tag {};
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, GCM_TAG_LEN, tag.data()) != 1)
            throw CryptoException("EVP_CIPHER_CTX_ctrl GET_TAG failed");

        metadata.tag = detail::hexEncode(std::vector<std::uint8_t>(tag.begin(), tag.end()));
        return ciphertext;
    }

    std::vector<std::uint8_t> aesDecrypt(const std::vector<std::uint8_t>& ciphertext,
                                         const std::vector<std::uint8_t>& key,
                                         const CipherMetadata&            metadata) const {
        static constexpr std::size_t GCM_TAG_LEN = 16;

        std::vector<std::uint8_t> iv  = detail::hexDecode(metadata.iv);
        std::vector<std::uint8_t> tag = detail::hexDecode(metadata.tag);

        EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
        if (!ctx)
            throw CryptoException("EVP_CIPHER_CTX_new failed");

        auto ctxGuard = std::unique_ptr<EVP_CIPHER_CTX, decltype(&EVP_CIPHER_CTX_free)>(
            ctx, &EVP_CIPHER_CTX_free);

        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1)
            throw CryptoException("EVP_DecryptInit_ex failed (phase 1)");

        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                                static_cast<int>(iv.size()), nullptr) != 1)
            throw CryptoException("EVP_CIPHER_CTX_ctrl SET_IVLEN failed");

        if (EVP_DecryptInit_ex(ctx, nullptr, nullptr, key.data(), iv.data()) != 1)
            throw CryptoException("EVP_DecryptInit_ex failed (phase 2)");

        int len = 0;
        if (!metadata.aad.empty()) {
            const auto aadBytes = detail::hexDecode(metadata.aad);
            if (EVP_DecryptUpdate(ctx, nullptr, &len, aadBytes.data(),
                                  static_cast<int>(aadBytes.size())) != 1)
                throw CryptoException("EVP_DecryptUpdate failed (AAD)");
        }

        std::vector<std::uint8_t> plaintext(ciphertext.size());
        if (EVP_DecryptUpdate(ctx, plaintext.data(), &len, ciphertext.data(),
                              static_cast<int>(ciphertext.size())) != 1)
            throw CryptoException("EVP_DecryptUpdate failed (payload)");
        int plaintext_len = len;

        /* Set expected auth tag */
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, GCM_TAG_LEN,
                                const_cast<std::uint8_t*>(tag.data())) != 1)
            throw CryptoException("EVP_CIPHER_CTX_ctrl SET_TAG failed");

        int ret = EVP_DecryptFinal_ex(ctx, plaintext.data() + len, &len);
        if (ret <= 0) {
            throw CryptoException("EVP_DecryptFinal_ex failed – authentication tag mismatch");
        }
        plaintext_len += len;
        plaintext.resize(plaintext_len);
        return plaintext;
    }

    /*=== Data members ==============================================================================================*/
    std::shared_ptr<KeyProvider> m_keyProvider;
    CryptoContext                m_context;
};

} // namespace ci360::domain