```cpp
// ──────────────────────────────────────────────────────────────────────────────
// File:        src/module_72.cpp
// Project:     IntraLedger BlogSuite (web_blog)
// Description: Asynchronous incremental search-indexing job, complete with
//              fail-fast semantics, exponential back-off, and repository
//              boundaries.  This module is invoked by the JobProcessor whenever
//              a BlogArticle entity is created or updated.  The component is
//              fully self-contained and requires only the standard library and
//              the forward-declared interfaces provided by the larger codebase.
// Author:      BlogSuite Engineering
// SPDX-License-Identifier: BUSL-1.1
// ──────────────────────────────────────────────────────────────────────────────

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <exception>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations for cross-module interfaces owned elsewhere in the
// codebase.  These are intentionally light-weight so that this compilation unit
// can remain self-contained in a demo context. In production, the full header
// files would be included instead.
// ──────────────────────────────────────────────────────────────────────────────
namespace intraledger::core {

class ILogger
{
public:
    virtual ~ILogger()                                 = default;
    virtual void info(const std::string& msg)          = 0;
    virtual void warn(const std::string& msg)          = 0;
    virtual void error(const std::string& msg)         = 0;
    virtual void debug(const std::string& msg)         = 0;
};

class IClock
{
public:
    virtual ~IClock()                                                     = default;
    virtual std::chrono::system_clock::time_point now() const noexcept    = 0;
};

class JobContext
{
public:
    std::atomic<bool> cancelled { false }; // cooperative-cancel flag
    std::size_t        retryAttempt { 0U }; // incremented by JobProcessor
};

} // namespace intraledger::core

// ──────────────────────────────────────────────────────────────────────────────
// Simplified DTO and repository abstractions. Real classes include dozens of
// attributes, validation, and transactional semantics.
// ──────────────────────────────────────────────────────────────────────────────
namespace intraledger::blog {

struct ArticleDTO
{
    std::uint64_t id;
    std::string   title;
    std::string   body;
    std::string   language;
    std::chrono::system_clock::time_point updatedAt;
};

class IArticleRepository
{
public:
    virtual ~IArticleRepository() = default;

    // Returns all articles that have been created or modified since `cursor`
    // (non-inclusive).  A nullopt cursor means fetch everything.
    virtual std::vector<ArticleDTO>
    fetchModifiedSince(const std::optional<std::chrono::system_clock::time_point>& cursor,
                       std::size_t limit) = 0;
};

class ISearchIndex
{
public:
    virtual ~ISearchIndex() = default;

    // Adds or updates an article in the search index.
    virtual void upsert(const ArticleDTO& article) = 0;

    // Removes an article from the index.
    virtual void remove(std::uint64_t articleId)   = 0;
};

} // namespace intraledger::blog

// ──────────────────────────────────────────────────────────────────────────────
// Implementation
// ──────────────────────────────────────────────────────────────────────────────
namespace intraledger::blog {

namespace {

constexpr std::chrono::seconds kBackoffBase     { 2 };
constexpr std::chrono::seconds kBackoffCap      { 60 };
constexpr std::size_t          kBatchSize       { 128 };
constexpr std::size_t          kMaxRetries      { 5 };

// Naïve jittered exponential back-off helper.
std::chrono::seconds backoffDelay(std::size_t attempt)
{
    const auto pow        = std::min<std::size_t>(attempt, 30U); // avoid overflow
    auto       delay      = kBackoffBase * static_cast<int>(1ull << pow);
    delay                 = std::min(delay, kBackoffCap);

    // Add jitter (+/- 20%) to avoid thundering-herd on recover.
    static thread_local std::mt19937 rng { std::random_device{}() };
    std::uniform_real_distribution<>  dist { 0.8, 1.2 };

    using secs = std::chrono::seconds;
    return secs { static_cast<int>(delay.count() * dist(rng)) };
}

// Human-friendly time-point formatting for logging.
std::string formatTimePoint(const std::chrono::system_clock::time_point& tp)
{
    std::time_t t      = std::chrono::system_clock::to_time_t(tp);
    std::tm      tm    = *std::gmtime(&t);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%F %T") << "Z";
    return oss.str();
}

} // anonymous namespace

class SearchIndexer final
{
public:
    SearchIndexer(std::shared_ptr<IArticleRepository> repo,
                  std::shared_ptr<ISearchIndex>      index,
                  std::shared_ptr<core::ILogger>      logger,
                  std::shared_ptr<core::IClock>       clock)
        : m_repo(std::move(repo))
        , m_index(std::move(index))
        , m_logger(std::move(logger))
        , m_clock(std::move(clock))
        , m_lastIndexedAt(std::nullopt)
    {
        if (!m_repo || !m_index || !m_logger || !m_clock)
        {
            throw std::invalid_argument("SearchIndexer dependencies must not be nullptr");
        }
    }

    // Entrypoint for the JobProcessor. Performs incremental indexing until all
    // pending work is consumed or the job is cancelled.
    void operator()(core::JobContext& ctx)
    {
        m_logger->info("[SearchIndexer] Job started.");
        try
        {
            process(ctx);
            m_logger->info("[SearchIndexer] Job finished successfully.");
        }
        catch (const std::exception& ex)
        {
            m_logger->error(std::string("[SearchIndexer] Fatal error: ") + ex.what());
            throw; // propagate to JobProcessor for unified error handling
        }
    }

private:
    void process(core::JobContext& ctx)
    {
        while (!ctx.cancelled.load())
        {
            auto articles = m_repo->fetchModifiedSince(m_lastIndexedAt, kBatchSize);

            if (articles.empty())
            {
                m_logger->debug("[SearchIndexer] No more articles to index.");
                break;
            }

            m_logger->info("[SearchIndexer] Indexing batch of " +
                           std::to_string(articles.size()) + " articles.");

            indexBatchWithRetry(articles, ctx);

            // Update cursor based on last article processed in batch.
            const auto lastUpdated =
                std::max_element(articles.begin(), articles.end(),
                                 [](const ArticleDTO& a, const ArticleDTO& b) {
                                     return a.updatedAt < b.updatedAt;
                                 })
                    ->updatedAt;
            m_lastIndexedAt = lastUpdated;
        }
    }

    void indexBatchWithRetry(const std::vector<ArticleDTO>& batch, core::JobContext& ctx)
    {
        std::size_t attempt = 0;
        while (attempt <= kMaxRetries && !ctx.cancelled.load())
        {
            try
            {
                for (const auto& article : batch)
                {
                    if (ctx.cancelled.load()) { break; }
                    m_index->upsert(article);
                }
                return; // success
            }
            catch (const std::exception& ex)
            {
                ++attempt;
                m_logger->warn("[SearchIndexer] Attempt " + std::to_string(attempt) +
                               " failed: " + ex.what());

                if (attempt > kMaxRetries)
                {
                    m_logger->error("[SearchIndexer] Exhausted retries.");
                    throw; // rethrow to outer handler
                }

                auto delay = backoffDelay(attempt);
                m_logger->info("[SearchIndexer] Backing off for " +
                               std::to_string(delay.count()) + "s before retry.");
                std::this_thread::sleep_for(delay);
            }
        }
    }

private:
    std::shared_ptr<IArticleRepository> m_repo;
    std::shared_ptr<ISearchIndex>       m_index;
    std::shared_ptr<core::ILogger>      m_logger;
    std::shared_ptr<core::IClock>       m_clock;

    // Cursor for incremental indexing.
    std::optional<std::chrono::system_clock::time_point> m_lastIndexedAt;

}; // class SearchIndexer

// ──────────────────────────────────────────────────────────────────────────────
// Factory method that the Service Layer can use to enqueue a SearchIndexer job
// with the central JobProcessor.
// ──────────────────────────────────────────────────────────────────────────────
std::function<void(core::JobContext&)> createSearchIndexerJob(
    std::shared_ptr<IArticleRepository> repo,
    std::shared_ptr<ISearchIndex>       index,
    std::shared_ptr<core::ILogger>      logger,
    std::shared_ptr<core::IClock>       clock)
{
    // Capture by value to keep shared_ptr ownership semantics intact for the
    // lifetime of the job.
    return [indexer = SearchIndexer(std::move(repo),
                                    std::move(index),
                                    std::move(logger),
                                    std::move(clock))](core::JobContext& ctx) mutable {
        indexer(ctx);
    };
}

// ──────────────────────────────────────────────────────────────────────────────
// Basic stdout logger + system clock for standalone compilation/testing.  The
// real application provides a fully-featured SLF4J-style facade and a monotonic
// clock adapter.
// ──────────────────────────────────────────────────────────────────────────────
namespace {

class StdOutLogger final : public intraledger::core::ILogger
{
public:
    void info(const std::string& msg) override  { log("INFO", msg); }
    void warn(const std::string& msg) override  { log("WARN", msg); }
    void error(const std::string& msg) override { log("ERROR", msg); }
    void debug(const std::string& msg) override { log("DEBUG", msg); }

private:
    void log(const char* level, const std::string& msg)
    {
        auto tp = std::chrono::system_clock::now();
        std::cout << "[" << formatTimePoint(tp) << "] [" << level << "] " << msg << '\n';
    }
};

class SystemClock final : public intraledger::core::IClock
{
public:
    std::chrono::system_clock::time_point now() const noexcept override
    {
        return std::chrono::system_clock::now();
    }
};

} // anonymous namespace

// ──────────────────────────────────────────────────────────────────────────────
// Self-contained demo main() guarded behind #ifdef for optional compilation.
// Comment out or remove the macro to integrate with the larger monolith.
// ──────────────────────────────────────────────────────────────────────────────
#ifdef IL_BLOGSUITE_STANDALONE_DEMO

// A dummy in-memory article repository for demonstration purposes.
class DummyRepo final : public IArticleRepository
{
public:
    std::vector<ArticleDTO> fetchModifiedSince(
        const std::optional<std::chrono::system_clock::time_point>& cursor,
        std::size_t                                                limit) override
    {
        using namespace std::chrono_literals;
        static std::vector<ArticleDTO> storage {
            { 1, "Hello World", "Lorem ipsum", "en",
              std::chrono::system_clock::now() - 10s },
            { 2, "News", "Dolor sit amet", "en",
              std::chrono::system_clock::now() - 5s },
            { 3, "New Feature", "Consectetur adipiscing", "en",
              std::chrono::system_clock::now() - 1s },
        };

        std::vector<ArticleDTO> result;
        std::copy_if(storage.begin(), storage.end(), std::back_inserter(result),
                     [&](const ArticleDTO& article) {
                         return !cursor || article.updatedAt > *cursor;
                     });

        if (result.size() > limit) { result.resize(limit); }
        return result;
    }
};

// A dummy in-memory search index.
class DummyIndex final : public ISearchIndex
{
public:
    void upsert(const ArticleDTO& article) override
    {
        std::lock_guard<std::mutex> lock(mutex_);
        index_[article.id] = article.title; // store title only for brevity
    }

    void remove(std::uint64_t articleId) override
    {
        std::lock_guard<std::mutex> lock(mutex_);
        index_.erase(articleId);
    }

private:
    std::mutex                          mutex_;
    std::unordered_map<std::uint64_t, std::string> index_;
};

int main()
{
    auto repo   = std::make_shared<DummyRepo>();
    auto index  = std::make_shared<DummyIndex>();
    auto logger = std::make_shared<StdOutLogger>();
    auto clock  = std::make_shared<SystemClock>();

    auto jobFn  = createSearchIndexerJob(repo, index, logger, clock);

    intraledger::core::JobContext ctx;
    jobFn(ctx); // execute synchronously for demo

    return EXIT_SUCCESS;
}

#endif // IL_BLOGSUITE_STANDALONE_DEMO
```