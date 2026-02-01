```cpp
/**
 *  IntraLedger BlogSuite
 *  File: src/module_74.cpp
 *
 *  SecureTokenService
 *  -------------------
 *  Provides generation and validation of signed, short-lived tokens that are
 *  used throughout the authentication middleware (password resets, e-mail
 *  confirmations, OAuth state, etc.).  The implementation is intentionally
 *  kept self-contained to avoid any tight coupling with the rest of the
 *  security stack.  Tokens are similar in spirit to JWTs but use a reduced
 *  header and an application-specific payload to minimize bloat.
 *
 *  Dependencies:
 *      • OpenSSL   – HMAC-SHA256 signing
 *      • nlohmann/json – Lightweight JSON serialization
 *      • spdlog    – Structured logging
 *
 *  The public API is thread-safe, exception-safe, and respects RAII.
 */

#include <openssl/hmac.h>
#include <openssl/rand.h>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace intraledger::security
{
using Json     = nlohmann::json;
using Clock    = std::chrono::system_clock;
using Seconds  = std::chrono::seconds;
using TimePoint= std::chrono::time_point<Clock>;

/*--------------------------------------------------------
 * Exceptions
 *-------------------------------------------------------*/
class TokenError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

class TokenExpired : public TokenError
{
public:
    TokenExpired() : TokenError("Token has expired") {}
};

class TokenInvalid : public TokenError
{
public:
    explicit TokenInvalid(const std::string& msg = "Invalid token")
        : TokenError(msg) {}
};

/*--------------------------------------------------------
 * Base64URL helpers
 *-------------------------------------------------------*/
namespace detail
{
constexpr char kAlphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789-_";

inline std::string base64url_encode(const std::vector<uint8_t>& data)
{
    BIO* b64 = BIO_new(BIO_f_base64());
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);   // No newlines
    BIO* bio = BIO_new(BIO_s_mem());
    BIO_push(b64, bio);

    BIO_write(b64, data.data(), static_cast<int>(data.size()));
    BIO_flush(b64);

    BUF_MEM* bufferPtr = nullptr;
    BIO_get_mem_ptr(b64, &bufferPtr);

    std::string encoded(bufferPtr->data, bufferPtr->length);
    BIO_free_all(b64);

    // Standard -> URL safe
    for (char& c : encoded)
    {
        if (c == '+') c = '-';
        else if (c == '/') c = '_';
    }

    // Trim padding '='
    while (!encoded.empty() && encoded.back() == '=')
        encoded.pop_back();

    return encoded;
}

inline std::vector<uint8_t> base64url_decode(std::string_view input)
{
    std::string temp(input);

    // URL safe -> standard
    for (char& c : temp)
    {
        if (c == '-') c = '+';
        else if (c == '_') c = '/';
    }

    // Restore padding if necessary
    while (temp.size() % 4 != 0)
        temp.push_back('=');

    BIO* b64 = BIO_new(BIO_f_base64());
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    BIO* bio = BIO_new_mem_buf(temp.data(), static_cast<int>(temp.size()));
    bio    = BIO_push(b64, bio);

    std::vector<uint8_t> decoded(temp.size());
    const int len = BIO_read(bio, decoded.data(),
                             static_cast<int>(decoded.size()));
    if (len <= 0)
    {
        BIO_free_all(bio);
        throw TokenInvalid("Base64 decode failed");
    }
    decoded.resize(static_cast<std::size_t>(len));
    BIO_free_all(bio);
    return decoded;
}
} // namespace detail

/*--------------------------------------------------------
 * SecureTokenService
 *-------------------------------------------------------*/
class SecureTokenService
{
public:
    struct Config
    {
        std::string       secretKey;     // HMAC secret (binary safe)
        Seconds           defaultTTL     = Seconds { 900 }; // 15 minutes
        std::string       issuer         = "IntraLedger-BlogSuite";
        std::size_t       randomBytes    = 16;  // Random nonce length
    };

    explicit SecureTokenService(Config config)
        : cfg_(std::move(config))
    {
        if (cfg_.secretKey.empty())
            throw std::invalid_argument("Secret key must not be empty");
    }

    /*----------------------------------------------------
     * generateToken
     *
     * Generates a compact, URL-safe token for an arbitrary
     * user payload.  The payload is augmented with standard
     * claims (iss, iat, exp, jti).
     *---------------------------------------------------*/
    std::string generateToken(Json userPayload,
                              std::optional<Seconds> ttl = std::nullopt) const
    {
        const auto now = Clock::now();
        const auto exp = now + (ttl ? *ttl : cfg_.defaultTTL);

        userPayload["iss"] = cfg_.issuer;
        userPayload["iat"] = std::chrono::duration_cast<Seconds>(
                                 now.time_since_epoch()).count();
        userPayload["exp"] = std::chrono::duration_cast<Seconds>(
                                 exp.time_since_epoch()).count();
        userPayload["jti"] = randomHex(cfg_.randomBytes);

        const std::string payloadStr = userPayload.dump();
        const std::vector<uint8_t> payloadBin(
            payloadStr.begin(), payloadStr.end());

        const std::string encodedPayload =
            detail::base64url_encode(payloadBin);

        const std::vector<uint8_t> signature =
            hmacSHA256(encodedPayload);

        const std::string encodedSig = detail::base64url_encode(signature);

        return encodedPayload + '.' + encodedSig;
    }

    /*----------------------------------------------------
     * verifyToken
     *
     * Checks integrity & validity, then returns the decoded
     * payload on success.  On failure, a TokenError
     * derivative is thrown.
     *---------------------------------------------------*/
    Json verifyToken(std::string_view token) const
    {
        const auto delimPos = token.find('.');
        if (delimPos == std::string_view::npos)
            throw TokenInvalid("Token format incorrect");

        const std::string_view encodedPayload = token.substr(0, delimPos);
        const std::string_view encodedSig     =
            token.substr(delimPos + 1);

        // Verify signature
        const std::vector<uint8_t> expectedSig =
            hmacSHA256(encodedPayload);

        const std::vector<uint8_t> providedSig =
            detail::base64url_decode(encodedSig);

        if (!constantTimeEquals(expectedSig, providedSig))
            throw TokenInvalid("Signature mismatch");

        // Decode payload
        const std::vector<uint8_t> payloadBin =
            detail::base64url_decode(encodedPayload);
        const std::string payloadStr(payloadBin.begin(), payloadBin.end());

        Json payload;
        try
        {
            payload = Json::parse(payloadStr);
        }
        catch (const Json::exception& e)
        {
            throw TokenInvalid("Malformed JSON payload");
        }

        // Validate timestamps
        const auto nowSecs =
            std::chrono::duration_cast<Seconds>(
                Clock::now().time_since_epoch()).count();

        if (payload.contains("exp") && payload["exp"].is_number())
        {
            if (nowSecs > payload["exp"].get<int64_t>())
                throw TokenExpired();
        }

        if (payload.contains("nbf") && payload["nbf"].is_number())
        {
            if (nowSecs < payload["nbf"].get<int64_t>())
                throw TokenInvalid("Token not yet valid (nbf)");
        }

        return payload;
    }

private:
    Config cfg_;

    /*----------------------------------------------------
     * hmacSHA256
     *---------------------------------------------------*/
    std::vector<uint8_t> hmacSHA256(std::string_view data) const
    {
        unsigned int len = EVP_MAX_MD_SIZE;
        std::vector<uint8_t> result(len);

        HMAC_CTX* ctx = HMAC_CTX_new();
        if (!ctx)
            throw TokenError("HMAC_CTX allocation failed");

        if (HMAC_Init_ex(ctx,
                         cfg_.secretKey.data(),
                         static_cast<int>(cfg_.secretKey.size()),
                         EVP_sha256(), nullptr) != 1)
        {
            HMAC_CTX_free(ctx);
            throw TokenError("HMAC_Init_ex failed");
        }

        HMAC_Update(ctx,
                    reinterpret_cast<const unsigned char*>(data.data()),
                    data.size());

        HMAC_Final(ctx, result.data(), &len);
        HMAC_CTX_free(ctx);
        result.resize(len);
        return result;
    }

    /*----------------------------------------------------
     * randomHex
     *
     * Generates a cryptographically secure random hex
     * string of length `byteCount * 2`.
     *---------------------------------------------------*/
    static std::string randomHex(std::size_t byteCount)
    {
        std::vector<uint8_t> buf(byteCount);
        if (RAND_bytes(buf.data(), static_cast<int>(buf.size())) != 1)
            throw TokenError("RAND_bytes failed");

        std::ostringstream oss;
        oss << std::hex << std::setfill('0');
        for (uint8_t b : buf)
            oss << std::setw(2) << static_cast<int>(b);
        return oss.str();
    }

    /*----------------------------------------------------
     * constantTimeEquals
     *
     * Compares two byte sequences in constant time to
     * mitigate timing attacks.
     *---------------------------------------------------*/
    static bool constantTimeEquals(std::span<const uint8_t> a,
                                   std::span<const uint8_t> b)
    {
        if (a.size() != b.size())
            return false;
        uint8_t diff = 0;
        for (std::size_t i = 0; i < a.size(); ++i)
            diff |= a[i] ^ b[i];
        return diff == 0;
    }
}; // class SecureTokenService

/*--------------------------------------------------------
 * Unit-test like self-check (only compiled in debug builds)
 *-------------------------------------------------------*/
#ifndef NDEBUG
#include <cassert>
static void self_check()
{
    using namespace std::chrono_literals;
    intraledger::security::SecureTokenService::Config cfg;
    cfg.secretKey = "super-secret-server-key!";
    intraledger::security::SecureTokenService svc(cfg);

    nlohmann::json payload = {
        { "uid", 42 },
        { "role", "admin" }
    };

    const std::string token = svc.generateToken(payload, 10s);
    spdlog::debug("Generated token: {}", token);

    const auto decoded = svc.verifyToken(token);
    assert(decoded["uid"] == 42);
    assert(decoded["role"] == "admin");
}
static const int _ = (self_check(), 0);
#endif

} // namespace intraledger::security
```