```cpp
/***************************************************************************************************
 *  IntraLedger BlogSuite
 *  File: src/module_11.cpp
 *
 *  Module 11: AdaptiveRateLimiter
 *  --------------------------------
 *  A production-grade, thread-safe rate limiting component based on the token-bucket algorithm.
 *
 *  Motivation:
 *      • Protect public REST endpoints (login, file uploads, comment posting, etc.).
 *      • Provide configurable burst-capacity and refill rates.
 *      • Support multiple scopes (per-IP, per-user, global).
 *      • Offer pluggable persistence (in-memory default, Redis/Memcached extension points).
 *
 *  Usage:
 *      AdaptiveRateLimiter limiter{AdaptiveRateLimiter::Options{/*…*/}};
 *      if (!limiter.allow("user:42")) {
 *          // throttle client …
 *      }
 *
 *  NOTE: This file is *self-contained* and depends only on the C++ standard library.
 *        Integration with external KV stores can be achieved by implementing IBackend.
 **************************************************************************************************/

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

namespace intraledger::security {

//----------------------------------------------------------------------------------------------------------------------
// Exception helpers
//----------------------------------------------------------------------------------------------------------------------

class RateLimitExceededError final : public std::runtime_error {
public:
    explicit RateLimitExceededError(std::string  key,
                                    std::chrono::milliseconds retryAfter)            // NOLINT(modernize-pass-by-value)
        : std::runtime_error{buildMessage(std::move(key), retryAfter)},
          m_retryAfter{retryAfter}
    {}

    [[nodiscard]] std::chrono::milliseconds retryAfter() const noexcept { return m_retryAfter; }

private:
    static std::string buildMessage(const std::string& key,
                                    std::chrono::milliseconds retryAfter)
    {
        std::ostringstream oss;
        oss << "Rate-limit exceeded for key '" << key
            << "'. Retry after " << retryAfter.count() << "ms.";
        return oss.str();
    }

    std::chrono::milliseconds m_retryAfter;
};

//----------------------------------------------------------------------------------------------------------------------
// Storage Backend Abstraction (Strategy Pattern)
//----------------------------------------------------------------------------------------------------------------------

class IBackend {
public:
    virtual ~IBackend() = default;

    // Consume 'tokens' for the given key and return the remaining tokens after the operation.
    // If insufficient tokens are available, std::nullopt is returned.
    virtual std::optional<uint64_t> consume(const std::string& key, uint64_t tokens) = 0;

    // Return the time until tokens will be available again. std::nullopt if the bucket does not exist.
    virtual std::optional<std::chrono::milliseconds> retryAfter(const std::string& key) = 0;
};

//----------------------------------------------------------------------------------------------------------------------
// In-Memory Backend (default implementation)
//----------------------------------------------------------------------------------------------------------------------

namespace detail {

struct Bucket {
    uint64_t            tokensAvailable;
    std::chrono::steady_clock::time_point lastRefill;

    Bucket(uint64_t capacity, std::chrono::steady_clock::time_point now)
        : tokensAvailable{capacity}, lastRefill{now} {}
};

} // namespace detail

class InMemoryBackend final : public IBackend {
public:
    struct Config {
        uint64_t                    capacity       = 60;                 // tokens
        std::chrono::milliseconds   refillInterval = std::chrono::seconds{60};
        uint64_t                    refillAmount   = 60;                 // tokens per interval
        std::chrono::seconds        bucketTtl      = std::chrono::minutes{10};
    };

    explicit InMemoryBackend(Config cfg = Config{}) : m_cfg{cfg} {}

    std::optional<uint64_t> consume(const std::string& key,
                                    uint64_t          tokens) override
    {
        using clock = std::chrono::steady_clock;
        const auto now = clock::now();

        {
            // Acquire lock for bucket manipulation
            std::scoped_lock lock{m_mutex};
            auto& bucket = m_buckets.try_emplace(key, m_cfg.capacity, now).first->second;

            refill(bucket, now);

            if (tokens > bucket.tokensAvailable) {
                return std::nullopt;
            }

            bucket.tokensAvailable -= tokens;
            return bucket.tokensAvailable;
        }
    }

    std::optional<std::chrono::milliseconds> retryAfter(const std::string& key) override
    {
        using clock = std::chrono::steady_clock;
        const auto now = clock::now();

        std::scoped_lock lock{m_mutex};

        const auto it = m_buckets.find(key);
        if (it == m_buckets.end())
            return std::nullopt;

        const detail::Bucket& bucket = it->second;
        if (bucket.tokensAvailable > 0)
            return std::chrono::milliseconds{0};

        const auto elapsed    = now - bucket.lastRefill;
        const auto intervalMs = std::chrono::duration_cast<std::chrono::milliseconds>(m_cfg.refillInterval);
        auto       waitMs     = intervalMs - std::chrono::duration_cast<std::chrono::milliseconds>(elapsed);
        if (waitMs < std::chrono::milliseconds{0})
            waitMs = std::chrono::milliseconds{0};
        return waitMs;
    }

private:
    void refill(detail::Bucket& bucket,
                std::chrono::steady_clock::time_point now)
    {
        const auto elapsed = now - bucket.lastRefill;
        if (elapsed < m_cfg.refillInterval)
            return;

        const uint64_t intervals = static_cast<uint64_t>(
            elapsed / m_cfg.refillInterval);
        const uint64_t newTokens = intervals * m_cfg.refillAmount;

        bucket.tokensAvailable = std::min<uint64_t>(
            bucket.tokensAvailable + newTokens, m_cfg.capacity);
        bucket.lastRefill = bucket.lastRefill + intervals * m_cfg.refillInterval;
    }

private:
    Config                                                              m_cfg;
    std::unordered_map<std::string, detail::Bucket>                     m_buckets;
    std::mutex                                                          m_mutex;
};

//----------------------------------------------------------------------------------------------------------------------
// Adaptive Rate Limiter – public façade
//----------------------------------------------------------------------------------------------------------------------

class AdaptiveRateLimiter {
public:
    struct Options {
        // Optional identifier used for logging/diagnostics.
        std::string                     name              = "AdaptiveRateLimiter";

        // ======== Default in-memory backend configuration ========
        InMemoryBackend::Config         backendConfig     {};

        // Clients may supply a custom backend (e.g. Redis).
        // Ownership is shared because the backend may be reused elsewhere.
        std::shared_ptr<IBackend>       backend           = nullptr;

        // Whether to throw RateLimitExceededError on violation.
        bool                            throwOnViolation  = true;
    };

    explicit AdaptiveRateLimiter(Options opts = Options{})
        : m_opts{std::move(opts)}
    {
        if (!m_opts.backend) {
            m_opts.backend = std::make_shared<InMemoryBackend>(m_opts.backendConfig);
        }

        if (!m_opts.backend) {
            throw std::invalid_argument{
                "AdaptiveRateLimiter requires a non-null backend"};
        }
    }

    // Attempts to consume 'tokens' from the bucket identified by 'key'.
    // Returns true if request is allowed; false/exception otherwise.
    bool allow(const std::string& key, uint64_t tokens = 1)
    {
        const auto remaining = m_opts.backend->consume(key, tokens);
        if (remaining)
            return true;

        if (m_opts.throwOnViolation) {
            const auto retryAfter = m_opts.backend->retryAfter(key)
                                        .value_or(std::chrono::milliseconds{0});
            throw RateLimitExceededError{key, retryAfter};
        }
        return false;
    }

    [[nodiscard]] std::optional<std::chrono::milliseconds> retryAfter(
        const std::string& key) const
    {
        return m_opts.backend->retryAfter(key);
    }

    [[nodiscard]] const std::string& name() const noexcept { return m_opts.name; }

private:
    Options m_opts;
};

//----------------------------------------------------------------------------------------------------------------------
// Convenience helper for compile-time tests / example usage.
//----------------------------------------------------------------------------------------------------------------------
#ifdef INTRALEDGER_RATE_LIMITER_SELF_TEST
#include <iostream>
#include <thread>

static void selfTest()
{
    using namespace std::chrono_literals;
    AdaptiveRateLimiter limiter{
        {
            .name             = "self-test",
            .backendConfig    = {.capacity = 5, .refillInterval = 1s, .refillAmount = 5},
            .backend          = nullptr,
            .throwOnViolation = false
        }
    };

    for (int i = 0; i < 7; ++i) {
        const bool allowed = limiter.allow("unit:test");
        std::cout << "[" << i << "] allowed=" << std::boolalpha << allowed << '\n';
    }

    const auto wait = limiter.retryAfter("unit:test");
    std::cout << "Retry after: "
              << wait->count() << "ms\n";
}

#endif // INTRALEDGER_RATE_LIMITER_SELF_TEST

} // namespace intraledger::security
```