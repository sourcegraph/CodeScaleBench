#include <atomic>
#include <chrono>
#include <cstddef>
#include <iomanip>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

//
//  File:        src/module_27.cpp
//  Project:     IntraLedger BlogSuite (web_blog)
//  Module:      Security ‑ Token-Bucket–based Rate Limiter
//
//  Description:
//  ------------
//  This file implements a high-performance, thread-safe token-bucket rate
//  limiter intended to protect REST endpoints and other public surfaces
//  against brute-force attacks and abusive scraping.  A singleton instance
//  can be injected into controllers, middleware, or repository classes
//  without introducing global state.
//
//  Design goals:
//   • Lock-minimal hot path (per-bucket mutex only, manager uses RW lock)
//   • Constant-time Allow() even under high contention
//   • Dynamic reconfiguration for per-key overrides
//   • Automatic eviction of idle buckets to prevent unbounded memory growth
//
//  The implementation is self-contained to avoid circular dependencies with
//  other BlogSuite components.  Logging hooks have been replaced with
//  placeholders to keep this module standalone.
//

namespace BlogSuite::Security {

// ---------------------------------------------------------------------------
// TokenBucket
// ---------------------------------------------------------------------------
class TokenBucket
{
public:
    TokenBucket(std::size_t capacity, double refillRatePerSec);

    // Attempts to consume `tokens` and returns true on success.
    bool allow(std::size_t tokens = 1);

    // Update capacity or refill rate on-the-fly.
    void updateConfig(std::size_t newCapacity, double newRefillRatePerSec);

    // Prevent accidental copies; cost of moving is similar to copying.
    TokenBucket(const TokenBucket&)            = delete;
    TokenBucket& operator=(const TokenBucket&) = delete;
    TokenBucket(TokenBucket&&)                 = delete;
    TokenBucket& operator=(TokenBucket&&)      = delete;

private:
    void refillLocked();

    std::atomic<std::size_t>              m_tokens;
    std::size_t                           m_capacity;
    double                                m_refillRatePerSec;
    std::chrono::steady_clock::time_point m_lastRefill;
    mutable std::mutex                    m_mutex;
};

// ---------------------------------------------------------------------------
// RateLimiterManager — orchestrates per-key buckets
// ---------------------------------------------------------------------------
class RateLimiterManager
{
public:
    explicit RateLimiterManager(std::size_t defaultCapacity  = 60,
                                double       defaultRefillPS = 30.0 /* tokens / s */);

    bool allow(const std::string& key, std::size_t tokens = 1);

    // Runtime per-key override helpers
    void setOverride(const std::string& key,
                     std::size_t        capacity,
                     double             refillRatePerSec);
    void removeOverride(const std::string& key);

    // Purge buckets that have not been accessed for `maxIdle`
    void purgeIdle(std::chrono::seconds maxIdle = std::chrono::minutes(10));

    // Diagnostics util: returns short textual dump of bucket stats
    std::string toString(const std::string& key) const;

private:
    struct BucketWrapper
    {
        TokenBucket                           bucket;
        std::chrono::steady_clock::time_point lastAccess;

        BucketWrapper(std::size_t cap, double rate)
            : bucket(cap, rate), lastAccess(std::chrono::steady_clock::now())
        {}
    };

    using BucketMap = std::unordered_map<std::string, BucketWrapper>;

    std::size_t                 m_defaultCap;
    double                      m_defaultRate;
    mutable std::shared_mutex   m_mapMutex;
    BucketMap                   m_buckets;
};

// ===========================================================================
// TokenBucket implementation
// ===========================================================================
TokenBucket::TokenBucket(std::size_t capacity, double refillRatePerSec)
    : m_tokens(capacity)
    , m_capacity(capacity)
    , m_refillRatePerSec(refillRatePerSec)
    , m_lastRefill(std::chrono::steady_clock::now())
{
    if (capacity == 0u)
        throw std::invalid_argument("TokenBucket capacity must be greater than 0");

    if (refillRatePerSec <= 0.0)
        throw std::invalid_argument("TokenBucket refill rate must be positive");
}

bool TokenBucket::allow(std::size_t tokens)
{
    if (tokens == 0u)
        return true;  // trivial

    std::scoped_lock lock(m_mutex);
    refillLocked();

    if (m_tokens.load(std::memory_order_relaxed) < tokens)
        return false;

    m_tokens.fetch_sub(tokens, std::memory_order_relaxed);
    return true;
}

void TokenBucket::updateConfig(std::size_t newCapacity, double newRefillRatePerSec)
{
    if (newCapacity == 0u || newRefillRatePerSec <= 0.0)
        throw std::invalid_argument("updateConfig supplied invalid parameters");

    std::scoped_lock lock(m_mutex);
    m_capacity          = newCapacity;
    m_refillRatePerSec  = newRefillRatePerSec;
    // Clamp token balance if over new capacity
    auto current = m_tokens.load(std::memory_order_relaxed);
    if (current > newCapacity)
        m_tokens.store(newCapacity, std::memory_order_relaxed);
}

void TokenBucket::refillLocked()
{
    using namespace std::chrono;
    const auto now = steady_clock::now();
    const auto ms  = duration_cast<milliseconds>(now - m_lastRefill).count();

    if (ms <= 0)
        return;

    // high-precision refill; could overflow but capacity is small (<= UINT64_MAX)
    const double tokensToAdd = (static_cast<double>(ms) / 1000.0) * m_refillRatePerSec;
    if (tokensToAdd < 1.0)
        return;  // not enough elapsed

    const std::size_t toAdd = static_cast<std::size_t>(tokensToAdd);
    auto current            = m_tokens.load(std::memory_order_relaxed);
    auto newValue           = std::min<std::size_t>(m_capacity, current + toAdd);

    m_tokens.store(newValue, std::memory_order_relaxed);
    m_lastRefill = now;
}

// ===========================================================================
// RateLimiterManager implementation
// ===========================================================================
RateLimiterManager::RateLimiterManager(std::size_t defaultCapacity,
                                       double       defaultRefillPS)
    : m_defaultCap(defaultCapacity)
    , m_defaultRate(defaultRefillPS)
{
    if (defaultCapacity == 0u || defaultRefillPS <= 0)
        throw std::invalid_argument("RateLimiterManager: defaults must be positive");
}

bool RateLimiterManager::allow(const std::string& key, std::size_t tokens)
{
    using namespace std::chrono;

    // Fast path: try shared lock first
    {
        std::shared_lock shared(m_mapMutex);
        auto it = m_buckets.find(key);
        if (it != m_buckets.end())
        {
            it->second.lastAccess = steady_clock::now();
            return it->second.bucket.allow(tokens);
        }
    }

    // Slow path: need to create bucket
    std::unique_lock unique(m_mapMutex);
    auto [it, inserted] =
        m_buckets.try_emplace(key, m_defaultCap, m_defaultRate);

    it->second.lastAccess = std::chrono::steady_clock::now();
    return it->second.bucket.allow(tokens);
}

void RateLimiterManager::setOverride(const std::string& key,
                                     std::size_t        capacity,
                                     double             refillRatePerSec)
{
    std::unique_lock lock(m_mapMutex);
    auto [it, inserted] =
        m_buckets.try_emplace(key, capacity, refillRatePerSec);

    if (!inserted)  // already existed
        it->second.bucket.updateConfig(capacity, refillRatePerSec);
}

void RateLimiterManager::removeOverride(const std::string& key)
{
    std::unique_lock lock(m_mapMutex);
    m_buckets.erase(key);
}

void RateLimiterManager::purgeIdle(std::chrono::seconds maxIdle)
{
    using namespace std::chrono;
    const auto cutOff = steady_clock::now() - maxIdle;

    std::unique_lock lock(m_mapMutex);
    for (auto it = m_buckets.begin(); it != m_buckets.end();)
    {
        if (it->second.lastAccess < cutOff)
            it = m_buckets.erase(it);
        else
            ++it;
    }
}

std::string RateLimiterManager::toString(const std::string& key) const
{
    std::shared_lock lock(m_mapMutex);
    const auto it = m_buckets.find(key);
    if (it == m_buckets.end())
        return "<bucket not found>";

    std::ostringstream oss;
    oss << "TokenBucket[cap=" << it->second.bucket.allow(0) /* side-effect free */
        << ", lastAccess="
        << std::chrono::duration_cast<std::chrono::seconds>(
               std::chrono::steady_clock::now() - it->second.lastAccess)
               .count()
        << "s ago]";
    return oss.str();
}

} // namespace BlogSuite::Security

// ------------------- End of src/module_27.cpp ------------------------------