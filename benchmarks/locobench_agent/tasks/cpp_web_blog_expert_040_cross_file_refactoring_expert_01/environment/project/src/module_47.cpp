```cpp
/**
 *  IntraLedger BlogSuite — web_blog
 *  --------------------------------
 *  module_47.cpp
 *
 *  Full-text re-indexing facilities for the enterprise-grade BlogSuite platform.
 *
 *  Responsibility:
 *      • Detect articles that are stale or missing from the search index
 *      • (Re-)generate documents and hand them to the SearchIndexer
 *      • Execute the process asynchronously without blocking the HTTP layer
 *
 *  This compilation unit purposefully couples only to thin, stable
 *  abstractions (repositories, indexers, etc.) instead of concrete
 *  implementations to keep business rules isolated and easily testable.
 *
 *  Copyright (c) 2024
 *  SPDX-License-Identifier: MIT
 */

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

namespace ilbs   // IntraLedger BlogSuite
{
namespace util
{
// ---------------------------------------------------------------------
// Very small logging helper (std::cout-based fallback)
// In production we route this through the platform logging façade.
// ---------------------------------------------------------------------
enum class LogLevel
{
    Trace,
    Debug,
    Info,
    Warn,
    Error,
    Fatal
};

inline void log(LogLevel lvl, std::string_view msg)
{
    static constexpr std::string_view prefixes[]{
        "[TRACE] ", "[DEBUG] ", "[INFO] ", "[WARN] ", "[ERROR] ", "[FATAL] "};

    std::ostringstream os;
    os << prefixes[static_cast<std::size_t>(lvl)]
       << msg << '\n';
    std::cout << os.str();
}

} // namespace util

// ---------------------------------------------------------------------
// Basic thread-pool implementation used by multiple subsystems.
// ---------------------------------------------------------------------
class BackgroundTaskPool
{
public:
    explicit BackgroundTaskPool(std::size_t workers = std::thread::hardware_concurrency())
        : m_shutdown(false)
    {
        if (workers == 0)
            workers = 1;

        for (std::size_t i = 0; i < workers; ++i)
        {
            m_threads.emplace_back([this, i] {
                workerLoop(i);
            });
        }
        util::log(util::LogLevel::Info, "BackgroundTaskPool initialized with " +
                                             std::to_string(workers) + " workers.");
    }

    BackgroundTaskPool(const BackgroundTaskPool &) = delete;
    BackgroundTaskPool &operator=(const BackgroundTaskPool &) = delete;

    ~BackgroundTaskPool()
    {
        {
            std::unique_lock lk(m_mutex);
            m_shutdown = true;
        }
        m_cv.notify_all();
        for (auto &th : m_threads)
            th.join();
        util::log(util::LogLevel::Info, "BackgroundTaskPool shut down gracefully.");
    }

    template <typename Fn, typename... Args>
    auto submit(Fn &&fn, Args &&...args)
        -> std::future<std::invoke_result_t<std::decay_t<Fn>, std::decay_t<Args>...>>
    {
        using Ret = std::invoke_result_t<std::decay_t<Fn>, std::decay_t<Args>...>;

        auto task = std::make_shared<std::packaged_task<Ret()>>(
            std::bind(std::forward<Fn>(fn), std::forward<Args>(args)...));

        std::future<Ret> fut = task->get_future();
        {
            std::unique_lock lk(m_mutex);
            if (m_shutdown)
                throw std::runtime_error("submit on stopped BackgroundTaskPool");
            m_tasks.emplace([task]() { (*task)(); });
        }
        m_cv.notify_one();
        return fut;
    }

private:
    void workerLoop(std::size_t workerId)
    {
        for (;;)
        {
            std::function<void()> job;
            {
                std::unique_lock lk(m_mutex);
                m_cv.wait(lk, [this] { return m_shutdown || !m_tasks.empty(); });
                if (m_shutdown && m_tasks.empty())
                    return;
                job = std::move(m_tasks.front());
                m_tasks.pop();
            }

            try
            {
                job();
            }
            catch (const std::exception &ex)
            {
                util::log(util::LogLevel::Error,
                          "Unhandled exception in BackgroundTaskPool worker " +
                              std::to_string(workerId) + ": " + ex.what());
            }
            catch (...)
            {
                util::log(util::LogLevel::Fatal,
                          "Unknown exception in BackgroundTaskPool worker " +
                              std::to_string(workerId));
            }
        }
    }

    std::vector<std::thread>       m_threads;
    std::queue<std::function<void()>> m_tasks;
    std::mutex                     m_mutex;
    std::condition_variable        m_cv;
    bool                           m_shutdown;
};

// ---------------------------------------------------------------------
// Domain abstractions — simplified stubs providing only the members
// required by the re-indexing logic.
// ---------------------------------------------------------------------
using Timestamp = std::chrono::system_clock::time_point;

struct ArticleRecord
{
    std::int64_t id;
    std::string  slug;
    std::string  title;
    std::string  body;
    Timestamp    updatedAt;
};

class ArticleRepository
{
public:
    // Return all articles updated at, or after, the supplied timestamp.
    virtual std::vector<ArticleRecord> fetchUpdatedSince(Timestamp ts) = 0;

    // Return an article unconditionally (used during full re-index).
    virtual std::vector<ArticleRecord> fetchAll() = 0;

    virtual ~ArticleRepository() = default;
};

struct SearchDocument
{
    std::int64_t id;
    std::string  title;
    std::string  body;
    std::string  language;
    Timestamp    timestamp;
};

class SearchIndexer
{
public:
    virtual void index(const SearchDocument &doc)           = 0;
    virtual void remove(std::int64_t articleId)             = 0;
    virtual bool isIndexed(std::int64_t articleId) const    = 0;
    virtual ~SearchIndexer()                                = default;
};

// ---------------------------------------------------------------------
// Re-indexing job
// ---------------------------------------------------------------------
class ReindexJob
{
public:
    enum class Mode
    {
        Full,
        Incremental
    };

    ReindexJob(Mode mode, Timestamp since)
        : m_mode(mode)
        , m_since(std::move(since))
    {}

    Mode      mode()  const noexcept { return m_mode; }
    Timestamp since() const noexcept { return m_since; }

private:
    Mode      m_mode;
    Timestamp m_since;
};

// ---------------------------------------------------------------------
// ReindexService — schedules and orchestrates (re-)indexing tasks.
// ---------------------------------------------------------------------
class ReindexService
{
public:
    ReindexService(std::shared_ptr<ArticleRepository> repo,
                   std::shared_ptr<SearchIndexer>    indexer,
                   std::shared_ptr<BackgroundTaskPool> pool)
        : m_repo(std::move(repo))
        , m_indexer(std::move(indexer))
        , m_pool(std::move(pool))
    {
        if (!m_repo || !m_indexer || !m_pool)
            throw std::invalid_argument("ReindexService received nullptr dependency");
    }

    // Schedule a full re-index. Returns a future tracking completion.
    std::future<void> scheduleFullReindex()
    {
        return submitJob(ReindexJob{ReindexJob::Mode::Full, Timestamp{}});
    }

    // Schedule an incremental re-index (since 'duration' ago).
    std::future<void> scheduleIncrementalReindex(std::chrono::hours window)
    {
        const auto since = std::chrono::system_clock::now() - window;
        return submitJob(ReindexJob{ReindexJob::Mode::Incremental, since});
    }

private:
    std::future<void> submitJob(ReindexJob &&job)
    {
        util::log(util::LogLevel::Info, "Scheduling re-index job…");
        return m_pool->submit([this, job = std::move(job)]() mutable {
            try
            {
                runJob(job);
                util::log(util::LogLevel::Info, "Re-index job finished successfully.");
            }
            catch (const std::exception &ex)
            {
                util::log(util::LogLevel::Error,
                          std::string{"Re-index job failed: "} + ex.what());
                throw; // propagate to future
            }
        });
    }

    static SearchDocument toDocument(const ArticleRecord &rec)
    {
        // Detect language heuristically; stubbed to "en".
        return SearchDocument{
            rec.id,
            rec.title,
            rec.body,
            "en",
            rec.updatedAt};
    }

    void runJob(const ReindexJob &job)
    {
        std::vector<ArticleRecord> records;
        if (job.mode() == ReindexJob::Mode::Full)
        {
            util::log(util::LogLevel::Info, "Starting full article re-index…");
            records = m_repo->fetchAll();
        }
        else
        {
            util::log(util::LogLevel::Info, "Starting incremental re-index…");
            records = m_repo->fetchUpdatedSince(job.since());
        }

        std::size_t indexedCount = 0;
        for (const auto &rec : records)
        {
            SearchDocument doc = toDocument(rec);

            // Skip unchanged articles when possible.
            if (job.mode() == ReindexJob::Mode::Incremental &&
                m_indexer->isIndexed(rec.id))
            {
                continue;
            }

            m_indexer->index(doc);
            ++indexedCount;
        }

        std::ostringstream msg;
        msg << "Re-index complete. Reprocessed = " << indexedCount
            << " / " << records.size();
        util::log(util::LogLevel::Info, msg.str());
    }

    std::shared_ptr<ArticleRepository> m_repo;
    std::shared_ptr<SearchIndexer>     m_indexer;
    std::shared_ptr<BackgroundTaskPool> m_pool;
};

// ---------------------------------------------------------------------
// Mock implementations (used during unit-tests & CLI diagnostics).
// In production these are supplied by other compilation units.
// ---------------------------------------------------------------------
namespace mock
{

class MemoryArticleRepo final : public ArticleRepository
{
public:
    explicit MemoryArticleRepo(std::vector<ArticleRecord> seed)
        : m_records(std::move(seed))
    {}

    std::vector<ArticleRecord> fetchUpdatedSince(Timestamp ts) override
    {
        std::vector<ArticleRecord> out;
        std::copy_if(m_records.begin(), m_records.end(), std::back_inserter(out),
                     [&](const auto &r) { return r.updatedAt >= ts; });
        return out;
    }

    std::vector<ArticleRecord> fetchAll() override
    {
        return m_records;
    }

private:
    std::vector<ArticleRecord> m_records;
};

class MemoryIndexer final : public SearchIndexer
{
public:
    void index(const SearchDocument &doc) override
    {
        m_docs[doc.id] = doc;
        util::log(util::LogLevel::Debug, "Indexed article #" + std::to_string(doc.id));
    }

    void remove(std::int64_t articleId) override
    {
        m_docs.erase(articleId);
    }

    bool isIndexed(std::int64_t articleId) const override
    {
        return m_docs.find(articleId) != m_docs.end();
    }

private:
    std::unordered_map<std::int64_t, SearchDocument> m_docs;
};

} // namespace mock

// ---------------------------------------------------------------------
// CLI driver (only compiled into maintenance binaries — excluded from
// the web executable via build configuration). Provided here for
// completeness and demonstration purposes.
// ---------------------------------------------------------------------
#ifdef ILBS_BUILD_REINDEX_CLI
int main()
{
    using namespace std::chrono;

    auto now = std::chrono::system_clock::now();

    // Fill repository with dummy data
    std::vector<ArticleRecord> seed = {
        {1, "welcome", "Welcome", "Hi there!", now - hours(48)},
        {2, "roadmap", "Roadmap", "Where we are heading…", now - hours(2)},
        {3, "launch", "Launch Day", "We are live!", now - hours(1)}};

    auto repo    = std::make_shared<mock::MemoryArticleRepo>(seed);
    auto indexer = std::make_shared<mock::MemoryIndexer>();
    auto pool    = std::make_shared<BackgroundTaskPool>(2);

    ReindexService svc(repo, indexer, pool);

    auto fut1 = svc.scheduleFullReindex();
    fut1.get();

    auto fut2 = svc.scheduleIncrementalReindex(hours(3));
    fut2.get();

    return 0;
}
#endif

} // namespace ilbs
```