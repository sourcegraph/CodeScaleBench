```cpp
/**
 *  cardio_insight_360/src/domain/hipaa_crypto.cpp
 *
 *  Copyright (c) 2024
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  HIPAA-grade encryption / decryption utilities
 *  =================================================
 *  This translation unit contains a thin, cross-platform wrapper around
 *  OpenSSL’s EVP interface providing:
 *
 *      • AES-256-GCM streaming encryption / decryption
 *      • Envelope encryption (RSA-OAEP wrapping of the session key)
 *      • Integrated authentication tag verification (GCM)
 *      • Basic key-rotation through a local Key-Vault abstraction
 *
 *  The utilities emphasize:
 *      – Secure memory handling
 *      – Clear error propagation
 *      – Minimal dynamic allocation in hot paths
 *
 *  NOTE: All functions throw hipaa_crypto::CryptoException on failure.
 */

#include <array>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include <openssl/evp.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/rand.h>

#include "monitoring/logger.hpp"               // wrapper around spdlog (project local)
#include "config/config_manager.hpp"           // runtime configuration accessor

namespace hipaa_crypto
{
using ByteArray = std::vector<std::uint8_t>;

class CryptoException final : public std::runtime_error
{
public:
    explicit CryptoException(const std::string& msg)
        : std::runtime_error(msg)
    {
    }
};

/* ----------------------------------------------------------
 *  OpenSSL RAII helpers
 * -------------------------------------------------------- */

namespace detail
{
struct CtxDeleter
{
    void operator()(EVP_CIPHER_CTX* ctx) const noexcept { EVP_CIPHER_CTX_free(ctx); }
};

using EvpCipherCtxPtr = std::unique_ptr<EVP_CIPHER_CTX, CtxDeleter>;

inline void throwOnError(const std::string& prefix)
{
    unsigned long err = ERR_get_error(); // NOLINT(google-runtime-int)
    char buf[256];
    ERR_error_string_n(err, buf, sizeof(buf));
    throw CryptoException(prefix + ": " + buf);
}

inline EvpCipherCtxPtr makeCipherCtx()
{
    auto ctx = EvpCipherCtxPtr{EVP_CIPHER_CTX_new()};
    if (!ctx)
    {
        throwOnError("Failed to create EVP_CIPHER_CTX");
    }
    return ctx;
}

struct PkeyDeleter
{
    void operator()(EVP_PKEY* p) const noexcept { EVP_PKEY_free(p); }
};
using EvpPkeyPtr = std::unique_ptr<EVP_PKEY, PkeyDeleter>;

} // namespace detail

/* ----------------------------------------------------------
 *  Key-Vault abstraction (very thin)
 * -------------------------------------------------------- */
class KeyVault final
{
public:
    // Singleton accessor
    static KeyVault& instance()
    {
        static KeyVault kv;
        return kv;
    }

    // Retrieve the active RSA public key for wrapping
    detail::EvpPkeyPtr getActivePublicKey() const
    {
        std::scoped_lock lock(mutex_);
        return loadKey(publicKeyPath_);
    }

    // Retrieve the active RSA private key for unwrapping
    detail::EvpPkeyPtr getActivePrivateKey() const
    {
        std::scoped_lock lock(mutex_);
        return loadKey(privateKeyPath_);
    }

    // Where keys are stored on disk (PEM)
    const std::filesystem::path& vaultRoot() const noexcept { return vaultRoot_; }

    // Reload configuration (for hot key-rotation)
    void reload()
    {
        std::scoped_lock lock(mutex_);

        const auto& cfg = config::ConfigManager::instance();
        vaultRoot_      = cfg.getPath("hipaa_crypto.vault_root", "./keys/");
        publicKeyPath_  = vaultRoot_ / cfg.getString("hipaa_crypto.active_pub", "ci_rsa_pub.pem");
        privateKeyPath_ = vaultRoot_ / cfg.getString("hipaa_crypto.active_priv", "ci_rsa_priv.pem");

        if (!std::filesystem::exists(publicKeyPath_) || !std::filesystem::exists(privateKeyPath_))
        {
            throw CryptoException("Active key-pair not found in vault: " + vaultRoot_.string());
        }
    }

private:
    KeyVault()
    {
        reload(); // initial load
    }

    static detail::EvpPkeyPtr loadKey(const std::filesystem::path& p)
    {
        FILE* fp = std::fopen(p.string().c_str(), "rb");
        if (!fp)
        {
            throw CryptoException("Unable to open key file: " + p.string());
        }

        detail::EvpPkeyPtr k;
        if (p.extension() == ".pem" || p.extension() == ".pub" || p.extension() == ".key")
        {
            if (std::strstr(p.filename().string().c_str(), "_priv"))
            {
                k.reset(PEM_read_PrivateKey(fp, nullptr, nullptr, nullptr));
            }
            else
            {
                k.reset(PEM_read_PUBKEY(fp, nullptr, nullptr, nullptr));
            }
        }
        std::fclose(fp);

        if (!k)
        {
            detail::throwOnError("Failed to load RSA key: " + p.string());
        }
        return k;
    }

    mutable std::mutex       mutex_;
    std::filesystem::path    vaultRoot_;
    std::filesystem::path    publicKeyPath_;
    std::filesystem::path    privateKeyPath_;
};

/* ----------------------------------------------------------
 *  AES-256-GCM cipher (encryption / decryption)
 * -------------------------------------------------------- */
class AesGcmCipher final
{
public:
    static constexpr std::size_t KeySize   = 32; // 256-bit
    static constexpr std::size_t IvSize    = 12; // 96-bit (recommended for GCM)
    static constexpr std::size_t TagSize   = 16; // 128-bit

    struct EnvelopeHeader
    {
        // Magic bytes + version
        char      magic[4]        = {'C', 'I', 'C', '1'};
        uint8_t   headerVersion   = 1;
        uint8_t   cipherId        = 1; // 1 = AES-256-GCM
        uint16_t  reserved        = 0;

        uint16_t  wrappedKeySize  = 0; // length of wrapped AES key
        uint16_t  ivSize          = IvSize;
        uint16_t  tagSize         = TagSize;
        uint16_t  _pad            = 0;

        // IMPORTANT: structure is packed to guarantee serialization layout
    } __attribute__((packed));

    /************************************************************
     *  Encrypt a file (streaming) and write an envelope file
     ***********************************************************/
    static void encryptFile(const std::filesystem::path& in,
                            const std::filesystem::path& out,
                            std::optional<std::string_view> aad = std::nullopt)
    {
        std::ifstream ifs(in, std::ios::binary);
        if (!ifs)
        {
            throw CryptoException("Unable to open plaintext file: " + in.string());
        }
        std::ofstream ofs(out, std::ios::binary | std::ios::trunc);
        if (!ofs)
        {
            throw CryptoException("Unable to create ciphertext file: " + out.string());
        }

        // 1. Generate random key + IV
        std::array<std::uint8_t, KeySize> key{};
        std::array<std::uint8_t, IvSize>  iv{};
        RAND_bytes(key.data(), static_cast<int>(key.size()));
        RAND_bytes(iv.data(), static_cast<int>(iv.size()));

        // 2. Wrap key with RSA-OAEP
        const auto pubKey = KeyVault::instance().getActivePublicKey();

        constexpr int kMaxWrappedKeySize = 512; // support up to 4096-bit RSA
        std::array<std::uint8_t, kMaxWrappedKeySize> wrappedKey{};
        int wrappedKeyLen = EVP_PKEY_encrypt_old(nullptr,
                                                 nullptr,
                                                 0,
                                                 pubKey.get()); // Deprecated; we use modern API below but keep constant for len.

        EVP_PKEY_CTX* pkeyCtx = EVP_PKEY_CTX_new(pubKey.get(), nullptr);
        if (!pkeyCtx)
            detail::throwOnError("EVP_PKEY_CTX_new");

        if (EVP_PKEY_encrypt_init(pkeyCtx) <= 0)
            detail::throwOnError("EVP_PKEY_encrypt_init");

        if (EVP_PKEY_CTX_set_rsa_padding(pkeyCtx, RSA_PKCS1_OAEP_PADDING) <= 0)
            detail::throwOnError("EVP_PKEY_CTX_set_rsa_padding");

        size_t wrappedLen = wrappedKey.size();
        if (EVP_PKEY_encrypt(pkeyCtx,
                             wrappedKey.data(),
                             &wrappedLen,
                             key.data(),
                             key.size()) <= 0)
            detail::throwOnError("EVP_PKEY_encrypt");

        EVP_PKEY_CTX_free(pkeyCtx);

        // 3. Write envelope header
        EnvelopeHeader hdr;
        hdr.wrappedKeySize = static_cast<uint16_t>(wrappedLen);

        ofs.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        ofs.write(reinterpret_cast<const char*>(wrappedKey.data()), static_cast<std::streamsize>(wrappedLen));
        ofs.write(reinterpret_cast<const char*>(iv.data()), iv.size());

        // 4. Initialize cipher context
        auto ctx = detail::makeCipherCtx();

        if (EVP_EncryptInit_ex(ctx.get(), EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1)
            detail::throwOnError("EVP_EncryptInit_ex");

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN, IvSize, nullptr) != 1)
            detail::throwOnError("EVP_CIPHER_CTX_ctrl");

        if (EVP_EncryptInit_ex(ctx.get(), nullptr, nullptr, key.data(), iv.data()) != 1)
            detail::throwOnError("EVP_EncryptInit_ex (key/iv)");

        // AAD
        if (aad)
        {
            int len = 0;
            if (EVP_EncryptUpdate(ctx.get(),
                                  nullptr,
                                  &len,
                                  reinterpret_cast<const unsigned char*>(aad->data()),
                                  static_cast<int>(aad->size())) != 1)
                detail::throwOnError("EVP_EncryptUpdate (AAD)");
        }

        // 5. Stream encrypt
        constexpr std::size_t BufferSize = 64 * 1024;
        std::array<std::uint8_t, BufferSize> inBuf{};
        std::array<std::uint8_t, BufferSize> outBuf{};

        while (ifs.good())
        {
            ifs.read(reinterpret_cast<char*>(inBuf.data()), BufferSize);
            std::streamsize readBytes = ifs.gcount();
            if (readBytes <= 0)
                break;

            int outLen = 0;
            if (EVP_EncryptUpdate(ctx.get(),
                                  outBuf.data(),
                                  &outLen,
                                  inBuf.data(),
                                  static_cast<int>(readBytes)) != 1)
                detail::throwOnError("EVP_EncryptUpdate");

            ofs.write(reinterpret_cast<char*>(outBuf.data()), outLen);
        }

        // 6. Finalize GCM
        int len = 0;
        if (EVP_EncryptFinal_ex(ctx.get(), outBuf.data(), &len) != 1)
            detail::throwOnError("EVP_EncryptFinal_ex");

        ofs.write(reinterpret_cast<char*>(outBuf.data()), len);

        // 7. Get tag and write
        std::array<std::uint8_t, TagSize> tag{};
        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_GET_TAG, TagSize, tag.data()) != 1)
            detail::throwOnError("EVP_CIPHER_CTX_ctrl (GET_TAG)");

        ofs.write(reinterpret_cast<char*>(tag.data()), tag.size());

        monitoring::Logger::instance().info("Encrypted file '{}' -> '{}'", in.string(), out.string());
    }

    /************************************************************
     *  Decrypt a previously encrypted envelope file
     ***********************************************************/
    static void decryptFile(const std::filesystem::path& in,
                            const std::filesystem::path& out,
                            std::optional<std::string_view> aad = std::nullopt)
    {
        std::ifstream ifs(in, std::ios::binary);
        if (!ifs)
        {
            throw CryptoException("Unable to open ciphertext file: " + in.string());
        }

        std::ofstream ofs(out, std::ios::binary | std::ios::trunc);
        if (!ofs)
        {
            throw CryptoException("Unable to create plaintext file: " + out.string());
        }

        // 1. Read header
        EnvelopeHeader hdr{};
        ifs.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
        if (std::memcmp(hdr.magic, "CIC1", 4) != 0 || hdr.headerVersion != 1)
        {
            throw CryptoException("Unknown envelope header format");
        }
        if (hdr.cipherId != 1)
        {
            throw CryptoException("Unsupported cipherId");
        }

        // 2. Read wrapped key & IV
        ByteArray wrappedKey(hdr.wrappedKeySize);
        ifs.read(reinterpret_cast<char*>(wrappedKey.data()), wrappedKey.size());

        ByteArray iv(hdr.ivSize);
        ifs.read(reinterpret_cast<char*>(iv.data()), iv.size());

        // Tag will be at file end; save position
        std::streampos tagPos = ifs.tellg();
        ifs.seekg(0, std::ios::end);
        std::streampos fileEnd = ifs.tellg();
        ifs.seekg(tagPos);

        const std::streamsize cipherTextLen = fileEnd - tagPos - hdr.tagSize;
        const std::streampos  cipherTextEnd = tagPos + cipherTextLen;

        // 3. Unwrap key
        const auto privKey = KeyVault::instance().getActivePrivateKey();
        ByteArray key(KeySize);

        EVP_PKEY_CTX* pkeyCtx = EVP_PKEY_CTX_new(privKey.get(), nullptr);
        if (!pkeyCtx)
            detail::throwOnError("EVP_PKEY_CTX_new");

        if (EVP_PKEY_decrypt_init(pkeyCtx) <= 0)
            detail::throwOnError("EVP_PKEY_decrypt_init");

        if (EVP_PKEY_CTX_set_rsa_padding(pkeyCtx, RSA_PKCS1_OAEP_PADDING) <= 0)
            detail::throwOnError("EVP_PKEY_CTX_set_rsa_padding");

        size_t keyLen = key.size();
        if (EVP_PKEY_decrypt(pkeyCtx,
                             key.data(),
                             &keyLen,
                             wrappedKey.data(),
                             wrappedKey.size()) <= 0)
            detail::throwOnError("EVP_PKEY_decrypt");

        EVP_PKEY_CTX_free(pkeyCtx);

        if (keyLen != KeySize)
        {
            throw CryptoException("Invalid unwrapped key length");
        }

        // 4. Read ciphertext segment into buffer (streaming)
        constexpr std::size_t BufferSize = 64 * 1024;
        std::array<std::uint8_t, BufferSize> inBuf{};
        std::array<std::uint8_t, BufferSize> outBuf{};

        auto ctx = detail::makeCipherCtx();

        if (EVP_DecryptInit_ex(ctx.get(), EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1)
            detail::throwOnError("EVP_DecryptInit_ex");

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN, static_cast<int>(iv.size()), nullptr) != 1)
            detail::throwOnError("EVP_CIPHER_CTX_ctrl");

        if (EVP_DecryptInit_ex(ctx.get(), nullptr, nullptr, key.data(), iv.data()) != 1)
            detail::throwOnError("EVP_DecryptInit_ex (key/iv)");

        // AAD
        if (aad)
        {
            int len = 0;
            if (EVP_DecryptUpdate(ctx.get(),
                                  nullptr,
                                  &len,
                                  reinterpret_cast<const unsigned char*>(aad->data()),
                                  static_cast<int>(aad->size())) != 1)
                detail::throwOnError("EVP_DecryptUpdate (AAD)");
        }

        // Stream decryption
        while (ifs.good() && ifs.tellg() < cipherTextEnd)
        {
            std::streamsize toRead =
                std::min<std::streamsize>(BufferSize, cipherTextEnd - ifs.tellg());
            ifs.read(reinterpret_cast<char*>(inBuf.data()), toRead);
            std::streamsize readBytes = ifs.gcount();
            if (readBytes <= 0)
                break;

            int len = 0;
            if (EVP_DecryptUpdate(ctx.get(),
                                  outBuf.data(),
                                  &len,
                                  inBuf.data(),
                                  static_cast<int>(readBytes)) != 1)
                detail::throwOnError("EVP_DecryptUpdate");

            ofs.write(reinterpret_cast<char*>(outBuf.data()), len);
        }

        // 5. Read tag
        ByteArray tag(hdr.tagSize);
        ifs.read(reinterpret_cast<char*>(tag.data()), tag.size());

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_TAG, static_cast<int>(tag.size()), tag.data()) != 1)
            detail::throwOnError("EVP_CIPHER_CTX_ctrl (SET_TAG)");

        int len = 0;
        if (EVP_DecryptFinal_ex(ctx.get(), outBuf.data(), &len) != 1)
        {
            throw CryptoException("Authentication tag verification failed – possible tampering");
        }
        ofs.write(reinterpret_cast<char*>(outBuf.data()), len);

        monitoring::Logger::instance().info("Decrypted file '{}' -> '{}'", in.string(), out.string());
    }
};

/* ----------------------------------------------------------
 *  Initialization routine (executed at load-time)
 * -------------------------------------------------------- */
namespace
{
struct OpenSslGlobalInit
{
    OpenSslGlobalInit()
    {
        ERR_load_crypto_strings();
        OpenSSL_add_all_algorithms();
        OPENSSL_init_ssl(0, nullptr);
    }

    ~OpenSslGlobalInit()
    {
        EVP_cleanup();
        CRYPTO_cleanup_all_ex_data();
        ERR_free_strings();
    }
} opensslGlobal; // NOLINT(cert-err58-cpp)
} // namespace

} // namespace hipaa_crypto

/* **********************************************************************************************
 *  UNIT-TEST (Compile-time optional) – Enable with -DCRYPTO_SELFTEST to validate at startup
 * ******************************************************************************************** */
#ifdef CRYPTO_SELFTEST
#include <cassert>
#include <random>

static void selfTest()
{
    using namespace hipaa_crypto;

    std::filesystem::path tempIn  = "ci_crypto_selftest_plain.bin";
    std::filesystem::path tempEnc = "ci_crypto_selftest_enc.bin";
    std::filesystem::path tempOut = "ci_crypto_selftest_dec.bin";

    // generate random test data (~2 MB)
    {
        std::ofstream f(tempIn, std::ios::binary);
        std::mt19937_64                 prng{std::random_device{}()};
        std::uniform_int_distribution<> dist{0, 255};
        for (std::size_t i = 0; i < 2 * 1024 * 1024; ++i)
            f.put(static_cast<char>(dist(prng)));
    }

    AesGcmCipher::encryptFile(tempIn, tempEnc, "CardioInsight360");
    AesGcmCipher::decryptFile(tempEnc, tempOut, "CardioInsight360");

    // Verify
    std::ifstream a(tempIn, std::ios::binary);
    std::ifstream b(tempOut, std::ios::binary);
    assert(std::equal(std::istreambuf_iterator<char>(a), {},
                      std::istreambuf_iterator<char>(b)));

    std::filesystem::remove(tempIn);
    std::filesystem::remove(tempEnc);
    std::filesystem::remove(tempOut);

    monitoring::Logger::instance().info("hipaa_crypto self-test passed");
}

struct SelfTestRunner
{
    SelfTestRunner() { selfTest(); }
} selfTestRunner; // NOLINT(cert-err58-cpp)
#endif
```