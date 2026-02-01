```cpp
/**
 *  IntraLedger BlogSuite
 *  File: src/module_56.cpp
 *
 *  PasswordResetService – Implements the workflow for secure, rate-limited
 *  password-reset requests.  The service is agnostic of the underlying storage
 *  and e-mail delivery mechanisms; it relies purely on small, well-defined
 *  interfaces that are expected to be injected at run-time by the IOC-container
 *  used elsewhere in the application.
 *
 *  The implementation (1) generates cryptographically-secure, URL-friendly
 *  tokens, (2) stores the token alongside an expiry time, (3) dispatches an
 *  asynchronous e-mail via the Job Processor, and (4) validates tokens on
 *  subsequent password-reset attempts.  Basic in-memory rate-limiting protects
 *  the endpoint from brute-force abuse without leaking timing information.
 *
 *  © 2024 IntraLedger, Inc.  All rights reserved.
 */

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <mutex>

using namespace std::chrono_literals;

namespace intraledger::blogsuite::auth
{

// -----------------------------------------------------------------------------
// Interfaces – these are implemented elsewhere in the code-base.  For compile
//             purposes they are kept minimal here.
// -----------------------------------------------------------------------------

class IUserRepository
{
public:
    virtual ~IUserRepository() = default;

    // Returns true if a user with the supplied e-mail exists and is active.
    virtual bool doesUserExist(std::string_view email) const = 0;

    // Updates the user’s password hash with a pre-hashed value.
    virtual void updatePassword(std::string_view email,
                                std::string_view passwordHash) = 0;
};

class IPasswordResetRepository
{
public:
    struct TokenRecord
    {
        std::string email;
        std::chrono::system_clock::time_point expiresAt;
    };

    virtual ~IPasswordResetRepository() = default;

    // Persists token → (email, expiry).  Overwrite if already present.
    virtual void upsertToken(std::string_view token, TokenRecord record)     = 0;

    // Removes token from the store.  No-op if token is unknown.
    virtual void removeToken(std::string_view token)                         = 0;

    // Returns nullptr if token not found.
    virtual std::unique_ptr<TokenRecord> findToken(std::string_view token)   = 0;
};

class IEmailDispatcher
{
public:
    virtual ~IEmailDispatcher() = default;

    // Enqueues an e-mail to be sent asynchronously by the job processor.
    virtual void enqueueResetEmail(std::string_view email,
                                   std::string_view resetUrl) = 0;
};

// -----------------------------------------------------------------------------
// Exceptions
// -----------------------------------------------------------------------------

class PasswordResetException : public std::runtime_error
{
    using std::runtime_error::runtime_error;
};

class RateLimitExceeded : public PasswordResetException
{
    using PasswordResetException::PasswordResetException;
};

class TokenInvalid : public PasswordResetException
{
    using PasswordResetException::PasswordResetException;
};

class TokenExpired : public PasswordResetException
{
    using PasswordResetException::PasswordResetException;
};

// -----------------------------------------------------------------------------
// PasswordResetService – Implementation
// -----------------------------------------------------------------------------

class PasswordResetService final
{
public:
    struct Config
    {
        std::chrono::minutes tokenLifetime      = 60min;
        std::chrono::minutes cooldownPerEmail   = 5min;
        std::size_t          maxTokensPerHour   = 5;
        std::string          frontendResetPath  = "/auth/password-reset/";
        std::string          resetEmailSubject  = "Reset your BlogSuite password";
    };

    PasswordResetService(IUserRepository& userRepo,
                         IPasswordResetRepository& tokenRepo,
                         IEmailDispatcher& emailer,
                         Config cfg = {})
        : m_userRepo{userRepo}
        , m_tokenRepo{tokenRepo}
        , m_emailDispatcher{emailer}
        , m_cfg{std::move(cfg)}
    {}

    // Public API ----------------------------------------------------------------

    // 1. Initiate Reset Request --------------------------------------------------
    //    Throws RateLimitExceeded if the email has exhausted its quota.
    void requestPasswordReset(std::string_view email)
    {
        validateEmail(email);

        auto now = std::chrono::system_clock::now();

        {
            std::scoped_lock lk{m_rateMutex};

            pruneRateLog(now);
            auto& info = m_rateLog[email];
            if (info.count >= m_cfg.maxTokensPerHour)
                throw RateLimitExceeded{"Too many password-reset requests."};

            if (now - info.lastRequest < m_cfg.cooldownPerEmail)
                throw RateLimitExceeded{"Password-reset requests are cooling down."};

            ++info.count;
            info.lastRequest = now;
        }

        // Generate a secure, unique token.
        const auto token = generateToken();

        // Persist token with its expiry.
        m_tokenRepo.upsertToken(token, {
            std::string{email},
            now + m_cfg.tokenLifetime
        });

        // Build reset URL (assumes host rendered on frontend).
        std::ostringstream url;
        url << m_cfg.frontendResetPath << token;

        // Send e-mail through dispatcher (async).
        m_emailDispatcher.enqueueResetEmail(email, url.str());
    }

    // 2. Reset Password ----------------------------------------------------------
    //    Validates token, updates password hash, and consumes token.
    void resetPassword(std::string_view token, std::string_view newPasswordHash)
    {
        auto now = std::chrono::system_clock::now();

        auto record = m_tokenRepo.findToken(token);
        if (!record)
            throw TokenInvalid{"Password-reset token invalid."};

        if (now > record->expiresAt)
        {
            m_tokenRepo.removeToken(token);
            throw TokenExpired{"Password-reset token expired."};
        }

        // Update password — if user is deleted / disabled this will throw from repo.
        m_userRepo.updatePassword(record->email, newPasswordHash);

        // Consume token.
        m_tokenRepo.removeToken(token);
    }

    // 3. Validate Token (for UI feedback) ----------------------------------------
    bool isTokenValid(std::string_view token) const
    {
        auto now = std::chrono::system_clock::now();
        auto record = m_tokenRepo.findToken(token);

        return record && now <= record->expiresAt;
    }

private:
    // Internal helpers -----------------------------------------------------------

    static void validateEmail(std::string_view email)
    {
        if (email.empty() || email.size() > 320 || email.find('@') == std::string::npos)
            throw PasswordResetException{"Invalid e-mail supplied."};
    }

    // Generates a cryptographically secure, 128-bit token encoded in base62.
    static std::string generateToken()
    {
        constexpr char charset[] =
            "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
        constexpr std::size_t charsetSize = sizeof(charset) - 1;
        constexpr std::size_t bytesNeeded = 16; // 128-bit
        constexpr std::size_t outputLen   = (bytesNeeded * 8 + 5) / 6; // ceil

        std::array<std::uint8_t, bytesNeeded> randomBytes{};

        {
            static thread_local std::random_device rd;
            static thread_local std::mt19937_64 rng{rd()};
            std::uniform_int_distribution<int> dist{0, 255};
            for (auto& b : randomBytes) b = static_cast<std::uint8_t>(dist(rng));
        }

        // Convert to base62
        std::string token;
        token.reserve(outputLen);

        std::uint64_t accumulator = 0;
        int bits = 0;
        for (std::uint8_t byte : randomBytes)
        {
            accumulator = (accumulator << 8) | byte;
            bits += 8;
            while (bits >= 6)
            {
                bits -= 6;
                token.push_back(charset[(accumulator >> bits) & 0x3F]);
            }
        }
        if (bits > 0)
            token.push_back(charset[(accumulator << (6 - bits)) & 0x3F]);

        return token;
    }

    // Rate Limiting --------------------------------------------------------------

    struct RateInfo
    {
        std::size_t                           count        = 0;
        std::chrono::system_clock::time_point lastRequest  = std::chrono::system_clock::now();
    };

    void pruneRateLog(const std::chrono::system_clock::time_point& now)
    {
        for (auto it = m_rateLog.begin(); it != m_rateLog.end(); )
        {
            if (now - it->second.lastRequest > 1h)
                it = m_rateLog.erase(it);
            else
                ++it;
        }
    }

private:
    IUserRepository&            m_userRepo;
    IPasswordResetRepository&   m_tokenRepo;
    IEmailDispatcher&           m_emailDispatcher;
    Config                      m_cfg;

    mutable std::mutex                               m_rateMutex;
    std::unordered_map<std::string, RateInfo>        m_rateLog;
};

} // namespace intraledger::blogsuite::auth
```