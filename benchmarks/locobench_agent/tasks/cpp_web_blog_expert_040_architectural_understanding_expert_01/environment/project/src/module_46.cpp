```cpp
/**
 *  IntraLedger BlogSuite
 *  ---------------------
 *  Module 46: Token-Bucket Rate-Limiter
 *
 *  This module provides a concurrency-safe, token-bucket based rate-limiter
 *  that can be dropped in as a middleware component for any hot-spot
 *  endpoint (login, password reset, comment posting, etc.).  Although the
 *  implementation relies only on the C++17 standard library, it follows the
 *  same coding conventions as the rest of BlogSuite and hooks into the
 *  platform’s diagnostic facilities.
 *
 *  NOTE: All time values are expressed in steady_clock time to avoid issues
 *  with system-clock adjustments (NTP, daylight-savings, leap seconds).
 */

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <fmt/core.h>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>

#include "core/Logger.hpp"           // Project-wide asynchronous logger
#include "core/RuntimeConfig.hpp"    // Access to strongly-typed env/config
#include "util/ScopeGuard.hpp"       // Simple defer/RAII helpers

namespace intraledger::security
{
using Clock          = std::chrono::steady_clock;
using Duration       = Clock::duration;
using TimePoint      = Clock::time_point;
using milliseconds   = std::chrono::milliseconds;
using seconds        = std::chrono::seconds;

/**
 *  TokenBucket
 *  -----------
 *  POJO holding the refill algorithm state for a single key.
 */
class TokenBucket final
{
public:
    TokenBucket(std::size_t maxTokens, double refillRatePerSec) noexcept
        : _maxTokens(static_cast<double>(maxTokens))
        , _refillRatePerSec(refillRatePerSec)
        , _tokens(_maxTokens)
        , _lastRefill(Clock::now())
    {
    }

    TokenBucket(const TokenBucket&)            = delete;
    TokenBucket& operator=(const TokenBucket&) = delete;
    TokenBucket(TokenBucket&&)                 = default;
    TokenBucket& operator=(TokenBucket&&)      = default;

    /**
     *  Attempt to remove one token from the bucket. Returns true if a token
     *  was successfully consumed, false otherwise.
     */
    bool consume()
    {
        refill();

        if (_tokens >= 1.0)
        {
            _tokens -= 1.0;
            return true;
        }
        return false;
    }

    /**
     *  Returns how many whole tokens are currently available. Mainly used
     *  for diagnostics.
     */
    std::size_t availableTokens() const noexcept
    {
        return static_cast<std::size_t>(_tokens);
    }

    /**
     *  Update internal token count based on elapsed time.
     */
    void refill()
    {
        auto now          = Clock::now();
        auto elapsed      = std::chrono::duration_cast<milliseconds>(now - _lastRefill);
        double newTokens  = (elapsed.count() / 1000.0) * _refillRatePerSec;

        if (newTokens > 0.0)
        {
            _tokens      = std::min(_maxTokens, _tokens + newTokens);
            _lastRefill  = now;
        }
    }

    /**
     *  Touch the bucket so the cleaner thread won’t prematurely delete it.
     */
    void touch() noexcept { _lastAccess = Clock::now(); }

    /**
     *  Age since last access; used by the cleaner thread for eviction.
     */
    Duration age() const noexcept { return Clock::now() - _lastAccess; }

private:
    double     _maxTokens          { 0.0 };
    double     _refillRatePerSec   { 0.0 };
    double     _tokens             { 0.0 };
    TimePoint  _lastRefill         { Clock::now() };
    TimePoint  _lastAccess         { Clock::now() };
};

/**
 *  TokenBucketRateLimiter
 *  ----------------------
 *  Thread-safe map of token buckets keyed by an arbitrary string (IP, user
 *  id, session id, etc.).  Buckets are lazily created on first access and
 *  garbage-collected after `bucketTTL` of inactivity by a low-priority
 *  maintenance thread.
 */
class TokenBucketRateLimiter final
{
    // Reasonable default: 100 buckets, refill 5 tokens/second, bucket size 20
    static constexpr std::size_t kDefaultCapacity        = 20;
    static constexpr double      kDefaultRefillPerSecond = 5.0;
    static constexpr seconds     kDefaultBucketTTL       = seconds{ 300 };      // 5 min
    static constexpr seconds     kDefaultCleanupInterval = seconds{ 30 };

public:
    struct Settings
    {
        std::size_t maxTokens         { kDefaultCapacity };
        double      refillRatePerSec  { kDefaultRefillPerSecond };
        seconds     bucketTTL         { kDefaultBucketTTL };
        seconds     cleanupInterval   { kDefaultCleanupInterval };
    };

    explicit TokenBucketRateLimiter(const Settings& settings = {})
        : _settings(settings)
        , _shutdownFlag(false)
        , _maintenanceThread(&TokenBucketRateLimiter::maintenanceLoop, this)
    {
        BLOGSUITE_LOG_INFO(
            "TokenBucketRateLimiter started: max={}, refill={}/s, TTL={}s", 
            _settings.maxTokens, 
            _settings.refillRatePerSec, 
            _settings.bucketTTL.count());
    }

    ~TokenBucketRateLimiter() noexcept
    {
        {
            std::lock_guard lk(_maintenanceMutex);
            _shutdownFlag = true;
            _maintenanceCv.notify_all();
        }
        if (_maintenanceThread.joinable())
            _maintenanceThread.join();
    }

    TokenBucketRateLimiter(const TokenBucketRateLimiter&)            = delete;
    TokenBucketRateLimiter& operator=(const TokenBucketRateLimiter&) = delete;

    /**
     *  Attempts to consume a single token for the provided key.  Returns
     *  true if the operation is permitted, false otherwise.
     *
     *  Thread-safe and lock-free on the common path; uses a shared-mutex to
     *  handle bucket map mutations.
     */
    bool allow(const std::string& key)
    {
        auto bucket = getOrCreateBucket(key);
        if (!bucket)
            return false;

        bool permitted = bucket->consume();
        bucket->touch();

        if (!permitted)
        {
            BLOGSUITE_LOG_WARN("RateLimiter blocked key='{}' (remaining={})",
                               key, bucket->availableTokens());
        }
        return permitted;
    }

    /**
     *  Returns the number of whole tokens available for the given key.
     *  Mainly used for introspection endpoints so does not optimize for speed.
     */
    std::optional<std::size_t> available(const std::string& key)
    {
        std::shared_lock rlk(_mapMutex);
        if (auto it = _buckets.find(key); it != _buckets.end())
            return it->second.availableTokens();
        return std::nullopt;
    }

private:
    /**
     *  Retrieve (or lazily create) a bucket for the given key.  Uses an
     *  upgrade path from shared to unique lock to keep contention low.
     */
    TokenBucket* getOrCreateBucket(const std::string& key)
    {
        // First try with read lock
        {
            std::shared_lock rlk(_mapMutex);
            auto             it = _buckets.find(key);
            if (it != _buckets.end())
                return &it->second;
        }
        // Upgrade to write lock for insertion
        {
            std::unique_lock wlk(_mapMutex);
            auto             [it, inserted] = _buckets.try_emplace(
                key, _settings.maxTokens, _settings.refillRatePerSec);
            return &it->second;
        }
    }

    /**
     *  Background thread that periodically removes stale buckets to prevent
     *  unbounded memory growth.  The thread exits when the object is
     *  destructed.
     */
    void maintenanceLoop()
    {
        BLOGSUITE_LOG_DEBUG("RateLimiter maintenance thread started");
        while (true)
        {
            std::unique_lock lk(_maintenanceMutex);
            _maintenanceCv.wait_for(lk, _settings.cleanupInterval, [this]() { return _shutdownFlag; });
            if (_shutdownFlag)
                break;

            const auto now   = Clock::now();
            const auto ttl   = _settings.bucketTTL;

            std::size_t removed = 0;
            {
                std::unique_lock mapLock(_mapMutex);
                for (auto it = _buckets.begin(); it != _buckets.end();)
                {
                    if (it->second.age() >= ttl)
                    {
                        it = _buckets.erase(it);
                        ++removed;
                    }
                    else
                    {
                        ++it;
                    }
                }
            }
            if (removed > 0)
            {
                BLOGSUITE_LOG_DEBUG("RateLimiter cleaned {} expired bucket(s)", removed);
            }
        }
        BLOGSUITE_LOG_DEBUG("RateLimiter maintenance thread stopped");
    }

private:
    Settings                                       _settings;
    std::unordered_map<std::string, TokenBucket>   _buckets;

    mutable std::shared_mutex                      _mapMutex;

    // Maintenance thread state
    std::atomic<bool>                              _shutdownFlag;
    std::mutex                                     _maintenanceMutex;
    std::condition_variable                        _maintenanceCv;
    std::thread                                    _maintenanceThread;
};

/* -------------------------------------------------------------------------- */
/*  Global Singleton                                                           */
/* -------------------------------------------------------------------------- */

/**
 *  Provides a process-wide instance of the rate-limiter using runtime config.
 *  Because BlogSuite is a single executable, we keep the global hidden inside
 *  this translation unit to avoid static-init-order issues.
 */
static TokenBucketRateLimiter& globalLoginRateLimiter()
{
    static TokenBucketRateLimiter::Settings s {
        core::RuntimeConfig::get<std::size_t>("security.rateLimiter.maxTokens", 10),
        core::RuntimeConfig::get<double>("security.rateLimiter.refillPerSec", 2.0),
        seconds{ core::RuntimeConfig::get<int>("security.rateLimiter.bucketTTL", 300) },
        seconds{ core::RuntimeConfig::get<int>("security.rateLimiter.cleanupInterval", 60) }
    };

    static TokenBucketRateLimiter instance { s };
    return instance;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                 */
/* -------------------------------------------------------------------------- */

namespace api
{

/**
 *  Checks if a request originating from `clientKey` is allowed to proceed.
 *  Proxy/wrapper that delegates to the TU-local singleton.
 *
 *  Example usage:
 *
 *    if (!api::isLoginAttemptAllowed(ipAddress)) {
 *        return HttpResponse::too_many_requests();
 *    }
 */
bool isLoginAttemptAllowed(const std::string& clientKey)
{
    return globalLoginRateLimiter().allow(clientKey);
}

/**
 *  Exposes bucket diagnostics to other parts of the system (metrics, admin UI).
 */
std::optional<std::size_t> tokensAvailable(const std::string& clientKey)
{
    return globalLoginRateLimiter().available(clientKey);
}

} // namespace api
} // namespace intraledger::security
```