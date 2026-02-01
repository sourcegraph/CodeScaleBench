```cpp
// -----------------------------------------------------------------------------
// File:    src/module_66.cpp
// Project: IntraLedger BlogSuite (web_blog)
// License: Business Source License 1.1 (see LICENSE file in project root)
// -----------------------------------------------------------------------------
//
//  ContentMetricsService
//  ---------------------
//  Computes article‐level metrics (views, trends, reading time) and exposes
//  them to controllers, background jobs and the real-time analytics panel.
//
//  Responsibilities
//  1.  Increment view counters while applying de-duplication strategies
//      (IP + user + sliding window) to mitigate fraudulent traffic.
//  2.  Persist counters in the database through the Repository layer,
//      flushing in-memory buckets on a configurable interval.
//  3.  Provide trend calculations (top-N articles within arbitrary windows).
//  4.  Interact with CacheProvider to reduce DB round-trips.
//  5.  Dispatch heavy computations (e.g., historical rebuild) to the async
//      JobDispatcher without blocking the request cycle.
//
// -----------------------------------------------------------------------------

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

// External dependencies (provided by the larger codebase / vendor libraries).
#include <spdlog/spdlog.h>

namespace intraledger::blog {

// -----------------------------------------------------------------------------
// Forward declarations for project wide abstractions.
// (Real definitions live elsewhere in the codebase.)
// -----------------------------------------------------------------------------
struct UserContext {
    std::string id;          // Authenticated user ID (empty for anonymous)
    std::string ipAddress;   // Client IP (already sanitized)
};

struct Article {
    std::uint64_t id;
    std::string   slug;
    std::string   title;
    std::chrono::system_clock::time_point createdAt;
    std::uint64_t viewCount;
};

struct ArticleMetrics {
    Article article;
    std::uint64_t views;
    double        viewsPerHour;
};

// Repository interface --------------------------------------------------------
class IArticleRepository {
public:
    virtual ~IArticleRepository() = default;

    virtual std::optional<Article> findById(std::uint64_t id) = 0;
    virtual void                   persistViewCount(std::uint64_t id,
                                                    std::uint64_t newCount) = 0;

    virtual std::vector<Article>
    fetchPublishedSince(std::chrono::system_clock::time_point since) = 0;
};

// Cache provider interface ----------------------------------------------------
class ICacheProvider {
public:
    virtual ~ICacheProvider()                                  = default;
    virtual void set(std::string_view key,
                     std::string      value,
                     std::chrono::seconds ttl)                 = 0;
    virtual std::optional<std::string> get(std::string_view key) = 0;
    virtual void                       erase(std::string_view key) = 0;
};

// Asynchronous job dispatcher --------------------------------------------------
class IJobDispatcher {
public:
    virtual ~IJobDispatcher()                                   = default;
    virtual void dispatch(std::string_view jobName,
                          std::unordered_map<std::string,
                                             std::string> payload) = 0;
};

// -----------------------------------------------------------------------------
// ContentMetricsService
// -----------------------------------------------------------------------------
class ContentMetricsService {
public:
    ContentMetricsService(std::shared_ptr<IArticleRepository> repo,
                          std::shared_ptr<ICacheProvider>     cache,
                          std::shared_ptr<IJobDispatcher>     dispatcher,
                          std::chrono::seconds                dedupWindow =
                              std::chrono::seconds{ 900 })
        : repository_(std::move(repo))
        , cache_(std::move(cache))
        , dispatcher_(std::move(dispatcher))
        , dedupWindow_(dedupWindow)
    {
        if (!repository_ || !cache_ || !dispatcher_) {
            throw std::invalid_argument(
                "ContentMetricsService requires non-null dependencies.");
        }
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    // Increment the view counter for an article. Applies de-duplication against
    // the tuple (articleId, userId|ipAddress) for the configured window.
    void recordView(std::uint64_t articleId, const UserContext& userCtx)
    {
        if (!articleId) {
            spdlog::warn("ContentMetricsService::recordView called with "
                          "articleId=0");
            return;
        }

        const auto dedupKey = makeDedupKey(articleId, userCtx);
        if (isDuplicateView(dedupKey)) { return; }

        // Non-duplicate; increment in-memory bucket first.
        {
            std::unique_lock lk(bucketsMutex_);
            auto&            bucket = viewBuckets_[articleId];
            ++bucket;
        }

        // Persist asynchronously when threshold is reached.
        // A threshold of 25 minimizes DB chatter while keeping counters fresh.
        constexpr std::size_t flushThreshold = 25;
        commitIfNeeded(articleId, flushThreshold);

        // Memoize dedup key.
        cache_->set(dedupKey, "1", dedupWindow_);
    }

    // Flush all in-memory buckets to the persistent store. Exposed for graceful
    // shutdown or periodic cron invocation.
    void flushAll()
    {
        std::unordered_map<std::uint64_t, std::uint64_t> snapshot;
        {
            std::unique_lock lk(bucketsMutex_);
            snapshot.swap(viewBuckets_);
        }

        for (const auto& [articleId, increment] : snapshot) {
            applyIncrement(articleId, increment);
        }
    }

    // Compute the N most trending articles within the given look-back window.
    // Complexity: O(M log N) where M is #articles published since cutoff.
    std::vector<ArticleMetrics>
    trending(std::size_t topN,
             std::chrono::hours windowSize = std::chrono::hours{ 24 })
    {
        using namespace std::chrono;

        const auto cutoff = system_clock::now() - windowSize;
        auto       recent = repository_->fetchPublishedSince(cutoff);

        // Pre-sort candidate list by viewCount delta / hour.
        std::vector<ArticleMetrics> metrics;
        metrics.reserve(recent.size());

        const double hours = std::max<double>(1.0, windowSize.count());
        for (auto& a : recent) {
            double vph = static_cast<double>(a.viewCount) / hours;
            metrics.push_back({ a, a.viewCount, vph });
        }

        std::sort(metrics.begin(), metrics.end(),
                  [](const ArticleMetrics& lhs, const ArticleMetrics& rhs) {
                      return lhs.viewsPerHour > rhs.viewsPerHour;
                  });

        if (metrics.size() > topN) { metrics.resize(topN); }
        return metrics;
    }

    // Initiate an asynchronous rebuild of historical metrics—for instance when
    // back-filling after a DB restore.
    void rebuildHistoricalMetrics()
    {
        dispatcher_->dispatch("RebuildHistoricalMetrics", {});
    }

private:
    // -------------------------------------------------------------------------
    // Internals
    // -------------------------------------------------------------------------
    std::string makeDedupKey(std::uint64_t articleId,
                             const UserContext& ctx) const
    {
        return "view_dedupe:" + std::to_string(articleId) + ":" +
               (!ctx.id.empty() ? ctx.id : ctx.ipAddress);
    }

    bool isDuplicateView(const std::string& key)
    {
        return cache_->get(key).has_value();
    }

    // Commits bucket for single article if threshold is reached.
    void commitIfNeeded(std::uint64_t articleId,
                        std::size_t   threshold) noexcept
    {
        std::uint64_t pending = 0;
        {
            std::shared_lock lk(bucketsMutex_);
            auto             it = viewBuckets_.find(articleId);
            if (it != viewBuckets_.end()) { pending = it->second; }
        }

        if (pending >= threshold) {
            std::unique_lock lk(flushMutex_, std::try_to_lock);
            if (!lk.owns_lock()) { return; } // Another thread flushing.

            std::uint64_t delta = 0;
            {
                std::unique_lock bucketLock(bucketsMutex_);
                auto             it = viewBuckets_.find(articleId);
                if (it != viewBuckets_.end()) {
                    delta          = it->second;
                    it->second     = 0;
                    if (delta == 0) { return; } // Double-checked
                }
            }
            applyIncrement(articleId, delta);
        }
    }

    void applyIncrement(std::uint64_t articleId, std::uint64_t delta) noexcept
    {
        try {
            auto articleOpt = repository_->findById(articleId);
            if (!articleOpt) {
                spdlog::warn("applyIncrement: article {} not found", articleId);
                return;
            }

            auto& article = *articleOpt;
            const std::uint64_t newCount = article.viewCount + delta;
            repository_->persistViewCount(articleId, newCount);
            spdlog::trace("Flushed {} new views for article {} (total={})",
                          delta,
                          articleId,
                          newCount);
        } catch (const std::exception& ex) {
            spdlog::error("ContentMetricsService::applyIncrement error: {}",
                          ex.what());
            // Bucket rollback (best-effort): re-queue delta.
            std::unique_lock lk(bucketsMutex_);
            viewBuckets_[articleId] += delta;
        }
    }

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------
    std::shared_ptr<IArticleRepository> repository_;
    std::shared_ptr<ICacheProvider>     cache_;
    std::shared_ptr<IJobDispatcher>     dispatcher_;
    std::chrono::seconds                dedupWindow_;

    // Buckets for non-persisted view increments—indexed by article ID.
    std::unordered_map<std::uint64_t, std::uint64_t> viewBuckets_;
    mutable std::shared_mutex                         bucketsMutex_;

    // Protects concurrent flush attempts.
    std::mutex flushMutex_;
};

} // namespace intraledger::blog
```