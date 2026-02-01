```cpp
/******************************************************************************
 *  CardioInsight360 – Unified Healthcare Analytics Engine                    *
 *  File: cardio_insight_360/tests/unit/test_hipaa_crypto.cpp                 *
 *                                                                            *
 *  Description                                                               *
 *  -------------                                                             *
 *  Unit-tests that exercise the HIPAA-grade cryptography helpers used by     *
 *  CardioInsight360 to encrypt PHI prior to persistence or transmission.     *
 *  The production code lives in `src/security/hipaa_crypto.hpp/.cpp`, but    *
 *  for the purpose of the test target we provide a compact reference         *
 *  implementation that uses OpenSSL EVP AES-256-GCM. These tests validate    *
 *  correct round-trips, integrity-checking, key-rotation, and thread-safety. *
 *                                                                            *
 *  Build Requirements                                                        *
 *  ------------------                                                        *
 *  • GoogleTest (gtest)                                                      *
 *  • OpenSSL development headers + libs                                      *
 *                                                                            *
 *  Example CMake snippet                                                     *
 *  ----------------------------------                                        *
 *  find_package(OpenSSL REQUIRED)                                            *
 *  find_package(GTest REQUIRED)                                              *
 *  add_executable(test_hipaa_crypto test_hipaa_crypto.cpp)                   *
 *  target_link_libraries(test_hipaa_crypto PRIVATE GTest::gtest OpenSSL::SSL *
 *                                                       OpenSSL::Crypto)     *
 ******************************************************************************/

#include <gtest/gtest.h>

#include <openssl/evp.h>
#include <openssl/rand.h>

#include <array>
#include <cstdint>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace cardio::security
{

/* ***************************************************************************
 *                               Error Types                                  *
 * ***************************************************************************/
class CryptoError final : public std::runtime_error
{
public:
    explicit CryptoError(const std::string& what) : std::runtime_error{what} {}
};

/* ***************************************************************************
 *                           RAII Context Guard                               *
 * ***************************************************************************/
class EvpCtx final
{
public:
    EvpCtx() : ctx_{EVP_CIPHER_CTX_new()}
    {
        if (!ctx_)
        {
            throw CryptoError("EVP_CIPHER_CTX_new() failed");
        }
    }

    ~EvpCtx() noexcept { EVP_CIPHER_CTX_free(ctx_); }

    EVP_CIPHER_CTX* get() noexcept { return ctx_; }
    const EVP_CIPHER_CTX* get() const noexcept { return ctx_; }

    // non-copyable
    EvpCtx(const EvpCtx&)            = delete;
    EvpCtx& operator=(const EvpCtx&) = delete;

    // movable
    EvpCtx(EvpCtx&& other) noexcept : ctx_{other.ctx_} { other.ctx_ = nullptr; }
    EvpCtx& operator=(EvpCtx&& other) noexcept
    {
        if (this != &other)
        {
            EVP_CIPHER_CTX_free(ctx_);
            ctx_       = other.ctx_;
            other.ctx_ = nullptr;
        }
        return *this;
    }

private:
    EVP_CIPHER_CTX* ctx_;
};

/* ***************************************************************************
 *                               Cipher Blob                                  *
 * ***************************************************************************/
struct CipherBlob
{
    std::vector<std::uint8_t> iv;      // 96-bit recommended for GCM
    std::vector<std::uint8_t> data;    // encrypted bytes
    std::vector<std::uint8_t> tag;     // 128-bit auth tag
};

/* ***************************************************************************
 *                              AES-256-GCM                                   *
 * ***************************************************************************/
class Aes256GcmCipher
{
public:
    static constexpr std::size_t KEY_SIZE   = 32; // 256 bit
    static constexpr std::size_t IV_SIZE    = 12; // 96 bit (GCM standard)
    static constexpr std::size_t TAG_SIZE   = 16; // 128 bit
    static constexpr std::size_t MAX_PLAINTEXT_SIZE = 1024 * 1024 * 32; // 32 MiB cap for demo

    using Key = std::array<std::uint8_t, KEY_SIZE>;

public:
    Aes256GcmCipher() = delete;

    /*------------------------------------------------------------------------
     *  Generates a cryptographically secure random key
     *-----------------------------------------------------------------------*/
    static Key generate_key()
    {
        Key key {};
        if (RAND_bytes(key.data(), static_cast<int>(key.size())) != 1)
        {
            throw CryptoError("RAND_bytes() failed while generating key");
        }
        return key;
    }

    /*------------------------------------------------------------------------
     *  Encrypts plaintext into a CipherBlob
     *-----------------------------------------------------------------------*/
    static CipherBlob encrypt(const Key& key,
                              const std::uint8_t* plaintext,
                              std::size_t         plaintext_len,
                              const std::vector<std::uint8_t>& aad = {})
    {
        if (plaintext_len > MAX_PLAINTEXT_SIZE)
        {
            throw CryptoError("Plaintext too large");
        }

        CipherBlob blob;
        blob.iv.resize(IV_SIZE);
        blob.tag.resize(TAG_SIZE);
        blob.data.resize(plaintext_len);

        if (RAND_bytes(blob.iv.data(), static_cast<int>(blob.iv.size())) != 1)
        {
            throw CryptoError("RAND_bytes() failed while generating IV");
        }

        EvpCtx ctx;

        if (EVP_EncryptInit_ex(ctx.get(),
                               EVP_aes_256_gcm(),
                               nullptr,
                               nullptr,
                               nullptr) != 1)
        {
            throw CryptoError("EVP_EncryptInit_ex() failed");
        }

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN,
                                static_cast<int>(blob.iv.size()), nullptr) != 1)
        {
            throw CryptoError("EVP_CIPHER_CTX_ctrl(SET_IVLEN) failed");
        }

        if (EVP_EncryptInit_ex(ctx.get(),
                               nullptr,
                               nullptr,
                               key.data(),
                               blob.iv.data()) != 1)
        {
            throw CryptoError("EVP_EncryptInit_ex(set key/iv) failed");
        }

        int len = 0;
        if (!aad.empty())
        {
            if (EVP_EncryptUpdate(ctx.get(),
                                  nullptr, &len,
                                  aad.data(), static_cast<int>(aad.size())) != 1)
            {
                throw CryptoError("EVP_EncryptUpdate(AAD) failed");
            }
        }

        if (EVP_EncryptUpdate(ctx.get(),
                              blob.data.data(), &len,
                              plaintext,
                              static_cast<int>(plaintext_len)) != 1)
        {
            throw CryptoError("EVP_EncryptUpdate(plaintext) failed");
        }
        int ciphertext_len = len;

        if (EVP_EncryptFinal_ex(ctx.get(),
                                blob.data.data() + len,
                                &len) != 1)
        {
            throw CryptoError("EVP_EncryptFinal_ex() failed");
        }
        ciphertext_len += len;

        if (ciphertext_len != static_cast<int>(plaintext_len))
        {
            // Should never happen
            throw CryptoError("Ciphertext length mismatch");
        }

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_GET_TAG,
                                static_cast<int>(blob.tag.size()),
                                blob.tag.data()) != 1)
        {
            throw CryptoError("EVP_CIPHER_CTX_ctrl(GET_TAG) failed");
        }

        return blob;
    }

    /*------------------------------------------------------------------------
     *  Decrypts CipherBlob into plaintext
     *-----------------------------------------------------------------------*/
    static std::vector<std::uint8_t> decrypt(const Key& key,
                                             const CipherBlob& blob,
                                             const std::vector<std::uint8_t>& aad = {})
    {
        if (blob.tag.size() != TAG_SIZE || blob.iv.size() != IV_SIZE)
        {
            throw CryptoError("CipherBlob malformed");
        }

        std::vector<std::uint8_t> plaintext(blob.data.size());

        EvpCtx ctx;
        if (EVP_DecryptInit_ex(ctx.get(),
                               EVP_aes_256_gcm(),
                               nullptr,
                               nullptr,
                               nullptr) != 1)
        {
            throw CryptoError("EVP_DecryptInit_ex() failed");
        }

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_IVLEN,
                                static_cast<int>(blob.iv.size()), nullptr) != 1)
        {
            throw CryptoError("EVP_CIPHER_CTX_ctrl(SET_IVLEN) failed");
        }

        if (EVP_DecryptInit_ex(ctx.get(),
                               nullptr,
                               nullptr,
                               key.data(),
                               blob.iv.data()) != 1)
        {
            throw CryptoError("EVP_DecryptInit_ex(set key/iv) failed");
        }

        int len = 0;
        if (!aad.empty())
        {
            if (EVP_DecryptUpdate(ctx.get(),
                                  nullptr, &len,
                                  aad.data(), static_cast<int>(aad.size())) != 1)
            {
                throw CryptoError("EVP_DecryptUpdate(AAD) failed");
            }
        }

        if (EVP_DecryptUpdate(ctx.get(),
                              plaintext.data(), &len,
                              blob.data.data(),
                              static_cast<int>(blob.data.size())) != 1)
        {
            throw CryptoError("EVP_DecryptUpdate(ciphertext) failed");
        }
        int plaintext_len = len;

        if (EVP_CIPHER_CTX_ctrl(ctx.get(), EVP_CTRL_GCM_SET_TAG,
                                static_cast<int>(blob.tag.size()),
                                const_cast<std::uint8_t*>(blob.tag.data())) != 1)
        {
            throw CryptoError("EVP_CIPHER_CTX_ctrl(SET_TAG) failed");
        }

        int ret = EVP_DecryptFinal_ex(ctx.get(),
                                      plaintext.data() + len, &len);

        if (ret <= 0)
        {
            throw CryptoError("Authentication failed – possible tampering");
        }
        plaintext_len += len;

        plaintext.resize(plaintext_len);
        return plaintext;
    }
};

/* ***************************************************************************
 *                         Utilities for Test Suite                           *
 * ***************************************************************************/
namespace
{

// Mutex ensures OpenSSL global init is only performed once from unit tests.
std::once_flag OPENSSL_INIT_FLAG;

void openssl_init_once()
{
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    OpenSSL_add_all_algorithms();
#endif
}

/* Helper that converts a std::string to raw byte vector */
inline std::vector<std::uint8_t> to_bytes(std::string_view s)
{
    return std::vector<std::uint8_t>(s.begin(), s.end());
}

} // anonymous namespace
} // namespace cardio::security

/* ****************************************************************************
 *                               Test Suite                                   *
 * ***************************************************************************/
using cardio::security::Aes256GcmCipher;
using cardio::security::CipherBlob;
using cardio::security::CryptoError;

class HipaaCryptoTest : public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        std::call_once(OPENSSL_INIT_FLAG,
                       cardio::security::openssl_init_once);
    }
};

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, RoundTripEncryptionDecryption)
{
    const auto key  = Aes256GcmCipher::generate_key();
    const auto data = to_bytes("Protected Health Information – §164.304");

    const CipherBlob blob =
        Aes256GcmCipher::encrypt(key, data.data(), data.size());

    ASSERT_EQ(blob.data.size(), data.size());
    ASSERT_EQ(blob.iv.size(), Aes256GcmCipher::IV_SIZE);
    ASSERT_EQ(blob.tag.size(), Aes256GcmCipher::TAG_SIZE);

    const auto decrypted =
        Aes256GcmCipher::decrypt(key, blob);

    EXPECT_EQ(decrypted, data);
}

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, DecryptionFailsWithWrongKey)
{
    const auto key_good = Aes256GcmCipher::generate_key();
    const auto key_bad  = Aes256GcmCipher::generate_key();
    const auto data     = to_bytes("Ejection fraction: 55%");

    const CipherBlob blob =
        Aes256GcmCipher::encrypt(key_good, data.data(), data.size());

    EXPECT_THROW(
        {
            try
            {
                Aes256GcmCipher::decrypt(key_bad, blob);
            }
            catch (const CryptoError& ex)
            {
                EXPECT_STREQ("Authentication failed – possible tampering",
                             ex.what());
                throw;
            }
        },
        CryptoError);
}

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, DecryptionFailsWhenCiphertextIsTamperedWith)
{
    const auto key  = Aes256GcmCipher::generate_key();
    const auto data = to_bytes("QT interval: 420ms");

    CipherBlob blob =
        Aes256GcmCipher::encrypt(key, data.data(), data.size());

    // Flip a random bit
    blob.data[3] ^= 0xFF;

    EXPECT_THROW({ Aes256GcmCipher::decrypt(key, blob); }, CryptoError);
}

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, KeyRotationScenario)
{
    // Old key protects legacy data
    const auto key_old = Aes256GcmCipher::generate_key();
    // New key post-rotation
    const auto key_new = Aes256GcmCipher::generate_key();

    const auto data_old = to_bytes("Pre-rotation record");
    const auto data_new = to_bytes("Post-rotation record");

    const CipherBlob blob_old =
        Aes256GcmCipher::encrypt(key_old, data_old.data(), data_old.size());

    const CipherBlob blob_new =
        Aes256GcmCipher::encrypt(key_new, data_new.data(), data_new.size());

    // Validate old data with old key
    EXPECT_EQ(
        Aes256GcmCipher::decrypt(key_old, blob_old),
        data_old);

    // Validate new data with new key
    EXPECT_EQ(
        Aes256GcmCipher::decrypt(key_new, blob_new),
        data_new);

    // Ensure cross-decryption fails
    EXPECT_THROW({ Aes256GcmCipher::decrypt(key_old, blob_new); },
                 CryptoError);
    EXPECT_THROW({ Aes256GcmCipher::decrypt(key_new, blob_old); },
                 CryptoError);
}

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, ThreadSafetyUnderConcurrentUse)
{
    constexpr std::size_t THREADS = 8;
    constexpr std::size_t ITER    = 100;

    const auto key = Aes256GcmCipher::generate_key();
    const auto msg = to_bytes("Telemetry: Lead-II rhythm normal.");

    auto worker = [&]()
    {
        for (std::size_t i = 0; i < ITER; ++i)
        {
            CipherBlob blob =
                Aes256GcmCipher::encrypt(key, msg.data(), msg.size());
            auto plain =
                Aes256GcmCipher::decrypt(key, blob);

            ASSERT_EQ(plain, msg);
        }
    };

    std::vector<std::thread> pool;
    for (std::size_t i = 0; i < THREADS; ++i)
        pool.emplace_back(worker);

    for (auto& t : pool) t.join();
}

/*-------------------------------------------------------------------------*/
TEST_F(HipaaCryptoTest, AdditionalAuthenticatedDataIsVerified)
{
    const auto key  = Aes256GcmCipher::generate_key();
    const auto data = to_bytes("Glucose Level: 110 mg/dL");
    const auto aad  = to_bytes("patient-uuid:123e4567-e89b-12d3-a456-426614174000");

    CipherBlob blob =
        Aes256GcmCipher::encrypt(key, data.data(), data.size(), aad);

    // Decrypting with same AAD succeeds
    EXPECT_EQ(
        Aes256GcmCipher::decrypt(key, blob, aad),
        data);

    // Decrypting with different AAD fails
    const auto wrong_aad = to_bytes("patient-uuid:badbeef");
    EXPECT_THROW({ Aes256GcmCipher::decrypt(key, blob, wrong_aad); },
                 CryptoError);
}
```