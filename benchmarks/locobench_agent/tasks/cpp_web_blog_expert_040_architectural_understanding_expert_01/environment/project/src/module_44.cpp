```cpp
/**
 *  IntraLedger BlogSuite — module_44.cpp
 *
 *  Real-time analytics aggregator responsible for collecting page–view
 *  events in-memory and persisting them to the database at a fixed cadence
 *  or once a configurable threshold is reached.
 *
 *  This module demonstrates a small yet representative slice of the larger
 *  architecture: it touches Repository, Service-Layer, ORM abstraction and
 *  asynchronous background processing while remaining self-contained.
 *
 *  © 2024 IntraLedger Corporation — All rights reserved.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations for external dependencies (ORM / Repository layer).
// In production these live in dedicated headers but are reduced here for
// compilation-isolation of the single source file target.
// ──────────────────────────────────────────────────────────────────────────────

namespace ilb   // (IntraLedger BlogSuite)
{
namespace orm   // Database/ORM abstraction layer
{
class DbSession
{
public:
    DbSession()                              = default;
    DbSession(const DbSession&)             = delete;
    DbSession& operator=(const DbSession&)  = delete;
    DbSession(DbSession&&) noexcept         = default;
    DbSession& operator=(DbSession&&)       = default;
    ~DbSession()                            = default;

    void beginTransaction() { /* stub */ }
    void commit()           { /* stub */ }
    void rollback()         { /* stub */ }

    template <typename Callable>
    void transactional(Callable&& cb)
    {
        beginTransaction();
        try
        {
            cb(*this);
            commit();
        }
        catch (...)
        {
            rollback();
            throw;
        }
    }
};
}  // namespace orm

namespace repository
{

struct AnalyticsUpdate
{
    std::int64_t tenantId;
    std::int64_t articleId;
    std::uint64_t viewCount;
};

class AnalyticsRepository
{
public:
    explicit AnalyticsRepository(orm::DbSession& session) : m_session(session) {}

    /**
     * Bulk increment view counters for each (tenant, article) pair.
     * Uses the underlying RDBMS `INSERT ... ON CONFLICT DO UPDATE` semantics.
     */
    void bulkIncrement(const std::vector<AnalyticsUpdate>& updates)
    {
        // NOTE: Implementation of prepared statements is elided.
        // The call structure is kept to demonstrate expected usage.
        for (const auto& upd : updates)
        {
            (void)upd;
            // prepare("INSERT INTO article_analytics ...");
        }
    }

private:
    orm::DbSession& m_session;
};

}  // namespace repository
}  // namespace ilb

// ──────────────────────────────────────────────────────────────────────────────
// Analytics Aggregator – public API (Service Layer)
// ──────────────────────────────────────────────────────────────────────────────

namespace ilb::service
{

/**
 * Thread-safe, process-wide singleton that collects raw page-view events
 * and flushes the aggregated counters to the persistence layer.
 *
 * Usage:
 *     AnalyticsAggregator::instance().recordView(tenantId, articleId, userId);
 */
class AnalyticsAggregator
{
public:
    // Non-copyable / Non-movable
    AnalyticsAggregator(const AnalyticsAggregator&)            = delete;
    AnalyticsAggregator& operator=(const AnalyticsAggregator&) = delete;
    AnalyticsAggregator(AnalyticsAggregator&&)                 = delete;
    AnalyticsAggregator& operator=(AnalyticsAggregator&&)      = delete;

    static AnalyticsAggregator& instance()
    {
        static AnalyticsAggregator inst;
        return inst;
    }

    ~AnalyticsAggregator()
    {
        shutdown();
    }

    /**
     * Records a page-view event. Extremely hot path; optimized for minimal
     * contention via per-bucket sharding and atomic counters.
     */
    void recordView(std::int64_t tenantId, std::int64_t articleId, std::int64_t /*userId*/)
    {
        const Key key{tenantId, articleId};
        auto& bucket = m_buckets[key % m_buckets.size()];

        {
            std::unique_lock lk(bucket.mutex);
            ++bucket.map[key];
        }

        // Fast path: only wake the flusher when certain thresholds are met.
        const auto current = ++m_eventCounter;
        if (current >= m_flushThreshold)
        {
            std::lock_guard lg(m_flushMutex);
            m_shouldFlush = true;
            m_cvFlush.notify_one();
        }
    }

    /**
     * Graceful shutdown – ensures all counters make it to persistent storage.
     * Safe to call multiple times.
     */
    void shutdown()
    {
        bool expected = false;
        if (!m_shutdown.compare_exchange_strong(expected, true)) return;

        {
            std::lock_guard lg(m_flushMutex);
            m_shouldFlush = true;
            m_cvFlush.notify_one();
        }
        if (m_flushThread.joinable()) m_flushThread.join();
    }

private:
    // ───── Types ────────────────────────────────────────────────────────────
    struct Key
    {
        std::int64_t tenantId;
        std::int64_t articleId;

        std::size_t operator%(std::size_t mod) const noexcept
        {
            // Simple mixing hash for bucket selection.
            std::uint64_t h = static_cast<std::uint64_t>(tenantId) ^ (static_cast<std::uint64_t>(articleId) << 1);
            return static_cast<std::size_t>(h % mod);
        }

        bool operator==(const Key& other) const noexcept
        {
            return tenantId == other.tenantId && articleId == other.articleId;
        }
    };

    struct KeyHash
    {
        std::size_t operator()(const Key& k) const noexcept
        {
            return k.tenantId * 31ull ^ k.articleId;
        }
    };

    using Map  = std::unordered_map<Key, std::uint64_t, KeyHash>;
    using Pair = std::pair<Key, std::uint64_t>;

    struct Bucket
    {
        Map             map;
        std::mutex      mutex;
    };

    // ───── Ctor (private) ───────────────────────────────────────────────────
    AnalyticsAggregator()
        : m_flushThread(&AnalyticsAggregator::flushLoop, this)
    {
    }

    // ───── Flushing Logic ───────────────────────────────────────────────────
    void flushLoop()
    {
        auto nextWake = std::chrono::steady_clock::now() + m_flushInterval;
        std::unique_lock lk(m_flushMutex);

        while (!m_shutdown.load(std::memory_order_acquire))
        {
            m_cvFlush.wait_until(lk, nextWake, [this] { return m_shouldFlush || m_shutdown.load(); });
            m_shouldFlush = false;
            lk.unlock();

            try
            {
                flushOnce();
            }
            catch (const std::exception& ex)
            {
                // Log and continue. In production use a proper logger.
                std::cerr << "[AnalyticsAggregator] flush failed: " << ex.what() << '\n';
            }

            nextWake = std::chrono::steady_clock::now() + m_flushInterval;
            lk.lock();
        }

        // Final flush on shutdown
        lk.unlock();
        flushOnce();
    }

    void flushOnce()
    {
        // Move data out of buckets with minimal holding time.
        std::vector<Pair> snapshot;
        snapshot.reserve(m_eventCounter.load());

        for (auto& bucket : m_buckets)
        {
            std::lock_guard lg(bucket.mutex);
            for (auto& [k, v] : bucket.map)
            {
                snapshot.emplace_back(k, v);
            }
            bucket.map.clear();
        }

        if (snapshot.empty()) return;
        m_eventCounter = 0;

        // Aggregate duplicates (rare; only occurs if hash bucket collision across shards).
        std::unordered_map<Key, std::uint64_t, KeyHash> aggregated;
        aggregated.reserve(snapshot.size());
        for (const auto& [k, v] : snapshot) aggregated[k] += v;

        // Persist to DB
        orm::DbSession session;
        repository::AnalyticsRepository repo(session);

        session.transactional([&](orm::DbSession& /*tx*/) {
            std::vector<repository::AnalyticsUpdate> batch;
            batch.reserve(aggregated.size());

            for (const auto& [k, count] : aggregated)
            {
                batch.push_back({k.tenantId, k.articleId, count});
                if (batch.size() >= m_dbBatchSize)
                {
                    repo.bulkIncrement(batch);
                    batch.clear();
                }
            }
            if (!batch.empty()) repo.bulkIncrement(batch);
        });
    }

    // ───── Data Members ─────────────────────────────────────────────────────
    static constexpr std::size_t kShardCount   = 64;
    static constexpr std::uint64_t kDefaultThreshold = 10'000;

    std::array<Bucket, kShardCount>    m_buckets{};
    std::atomic<std::uint64_t>         m_eventCounter{0};

    const std::chrono::seconds         m_flushInterval{10};
    const std::uint64_t                m_flushThreshold{kDefaultThreshold};
    const std::size_t                  m_dbBatchSize{1'024};

    std::atomic<bool>                  m_shutdown{false};
    std::thread                        m_flushThread;
    std::condition_variable            m_cvFlush;
    std::mutex                         m_flushMutex;
    bool                               m_shouldFlush{false};
};

}  // namespace ilb::service

// ──────────────────────────────────────────────────────────────────────────────
// Convenience API for other modules (free function wrapper)
// ──────────────────────────────────────────────────────────────────────────────
namespace ilb
{

inline void recordPageView(std::int64_t tenantId,
                           std::int64_t articleId,
                           std::int64_t userId = 0)
{
    service::AnalyticsAggregator::instance().recordView(tenantId, articleId, userId);
}

}  // namespace ilb

// ──────────────────────────────────────────────────────────────────────────────
// Unit-Test-like manual driver (can be removed when integrated into full tree)
// ──────────────────────────────────────────────────────────────────────────────
#ifdef ILB_ANALYTICS_MODULE_44_STANDALONE_DEMO
int main()
{
    using namespace std::chrono_literals;
    for (int i = 0; i < 50'000; ++i)
        ilb::recordPageView(1 /*tenant*/, i % 23 /*article*/);

    std::this_thread::sleep_for(5s);
    // Destructor will perform final flush.
}
#endif
```