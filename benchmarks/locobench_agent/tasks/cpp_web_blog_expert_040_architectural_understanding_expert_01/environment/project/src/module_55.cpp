```cpp
/**
 *  src/module_55.cpp
 *
 *  IntraLedger BlogSuite (web_blog)
 *  ---------------------------------
 *  Search & Index Service Layer
 *
 *  This compilation unit implements the production–grade content-search
 *  service used across the BlogSuite application.  It performs three major
 *  duties:
 *
 *    1. Structured full-text search against the underlying repository.
 *    2. Asynchronous (background) re-indexing of content entities.
 *    3. Thin business-logic validations + observability hooks (metrics/logs).
 *
 *  The implementation purposefully hides concurrency and transport details
 *  behind repository interfaces so that the rest of the code-base can remain
 *  storage-agnostic (PostgreSQL tsvector, OpenSearch, etc.).
 *
 *  NOTE: Other translation units are responsible for providing concrete
 *        implementations of ISearchIndexRepository and IMetricSink.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <future>
#include <iomanip>
#include <memory>
#include <mutex>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

// Third-party, single-header dependencies
#include <nlohmann/json.hpp>      // External JSON library
#include <spdlog/spdlog.h>        // External logging library

namespace blog::search
{

//---------------------------------------------------------------------
// Utility helpers
//---------------------------------------------------------------------

/**
 * RAII helper that measures execution time and automatically logs the result
 * when destroyed.
 */
class ScopedTimer
{
public:
    explicit ScopedTimer(std::string_view tag)            // NOLINT
        : _tag(tag), _start(std::chrono::steady_clock::now()) {}

    ~ScopedTimer() noexcept
    {
        try
        {
            const auto elapsed =
                std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - _start);

            spdlog::debug("[TIMER] {} took {} ms", _tag, elapsed.count());
        }
        catch (...)
        {
            // Make destructor noexcept; swallow any logging errors.
        }
    }

private:
    std::string _tag;
    std::chrono::steady_clock::time_point _start;
};

//---------------------------------------------------------------------
// Public data structures
//---------------------------------------------------------------------

enum class SearchOperator
{
    And,
    Or
};

struct SearchQuery
{
    std::string                text;          // The actual search phrase
    std::vector<std::string>   filters;       // Arbitrary key:value pairs
    std::size_t                offset{0};     // Pagination start
    std::size_t                limit{20};     // Page size
    SearchOperator             op{SearchOperator::And};
};

struct SearchResultItem
{
    std::uint64_t  contentId{};
    std::string    title;
    std::string    snippet;
    double         score{0.0};

    [[nodiscard]] nlohmann::json toJson() const
    {
        return {{"id", contentId},
                {"title", title},
                {"snippet", snippet},
                {"score", score}};
    }
};

struct SearchResult
{
    std::vector<SearchResultItem> items;
    std::size_t                   total{0};
    std::chrono::milliseconds     took{0};

    [[nodiscard]] nlohmann::json toJson() const
    {
        nlohmann::json arr = nlohmann::json::array();
        for (const auto &itm : items) { arr.push_back(itm.toJson()); }

        return {{"total", total},
                {"took_ms", took.count()},
                {"results", std::move(arr)}};
    }
};

//---------------------------------------------------------------------
// Abstract repository & metrics interfaces
//---------------------------------------------------------------------

class SearchException final : public std::runtime_error
{
public:
    explicit SearchException(std::string msg)  // NOLINT
        : std::runtime_error(std::move(msg)) {}
};

/**
 * Interface that hides whatever search technology is configured
 * (e.g., PostgreSQL full-text search, Elastic/OpenSearch, etc.).
 */
class ISearchIndexRepository
{
public:
    virtual ~ISearchIndexRepository() = default;

    virtual SearchResult executeQuery(const SearchQuery &query) = 0;
    virtual void          indexContent(std::uint64_t contentId) = 0;
};

/**
 * Very small metrics interface so we don’t impose a specific monitoring
 * solution (Prometheus, StatsD, Influx, …) at the service level.
 */
class IMetricSink
{
public:
    virtual ~IMetricSink() = default;

    virtual void incrementCounter(std::string_view key,
                                  double            value = 1.0) = 0;

    virtual void observeHistogram(std::string_view key,
                                  double            value) = 0;
};

//---------------------------------------------------------------------
// ContentSearchService – main implementation
//---------------------------------------------------------------------

class ContentSearchService
{
public:
    ContentSearchService(std::shared_ptr<ISearchIndexRepository> repo,
                         std::shared_ptr<IMetricSink>            metrics,
                         std::size_t                             workerCount = 2);

    ~ContentSearchService(); // NOLINT

    ContentSearchService(const ContentSearchService &)            = delete;
    ContentSearchService(ContentSearchService &&)                 = delete;
    ContentSearchService &operator=(const ContentSearchService &) = delete;
    ContentSearchService &operator=(ContentSearchService &&)      = delete;

    // Business API ---------------------------------------------------

    [[nodiscard]] SearchResult search(const SearchQuery &query);

    // Fire-and-forget. Content is queued for background indexing.
    void scheduleReindex(std::uint64_t contentId);

private:
    // Background worker handling
    void          workerLoop(std::size_t workerIndex);
    void          stopWorkers();
    std::uint64_t popTask(); // Blocks until task is available or shutdown

    //-----------------------------------------------------------------
    // Data members
    //-----------------------------------------------------------------
    const std::shared_ptr<ISearchIndexRepository> _repo;
    const std::shared_ptr<IMetricSink>            _metrics;

    // Concurrency constructs
    std::vector<std::thread>           _workers;
    std::queue<std::uint64_t>          _taskQueue;
    std::mutex                         _queueMutex;
    std::condition_variable            _queueCond;
    std::atomic<bool>                  _shutdown{false};
};

//---------------------------------------------------------------------
// ContentSearchService – Implementation
//---------------------------------------------------------------------

ContentSearchService::ContentSearchService(
    std::shared_ptr<ISearchIndexRepository> repo,
    std::shared_ptr<IMetricSink>            metrics,
    const std::size_t                       workerCount)
    : _repo(std::move(repo))
    , _metrics(std::move(metrics))
{
    if (!_repo)
    {
        throw std::invalid_argument(
            "ContentSearchService: repository instance must not be null");
    }
    if (!_metrics)
    {
        throw std::invalid_argument(
            "ContentSearchService: metrics sink instance must not be null");
    }

    // Spin up background workers.
    try
    {
        for (std::size_t i = 0; i < workerCount; ++i)
        {
            _workers.emplace_back(
                [this, i]()
                {
                    spdlog::info("Search worker {} started", i);
                    workerLoop(i);
                    spdlog::info("Search worker {} terminated", i);
                });
        }
    }
    catch (...)
    {
        _shutdown = true;
        stopWorkers();
        throw; // propagate
    }
}

ContentSearchService::~ContentSearchService()
{
    _shutdown = true;
    stopWorkers();
}

void ContentSearchService::stopWorkers()
{
    _queueCond.notify_all();
    for (auto &w : _workers)
    {
        if (w.joinable())
        {
            w.join();
        }
    }
}

SearchResult ContentSearchService::search(const SearchQuery &query)
{
    ScopedTimer t{"ContentSearchService::search"};

    // Basic validation
    if (query.text.empty())
    {
        throw SearchException("Search query cannot be empty");
    }

    auto start = std::chrono::steady_clock::now();

    // Delegate to repository
    auto result = _repo->executeQuery(query);

    auto elapsed =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start);

    // Emit metrics
    _metrics->incrementCounter("search.invocations");
    _metrics->observeHistogram("search.latency_ms",
                               static_cast<double>(elapsed.count()));

    return result;
}

void ContentSearchService::scheduleReindex(const std::uint64_t contentId)
{
    {
        std::scoped_lock lock(_queueMutex);
        _taskQueue.push(contentId);
    }
    _queueCond.notify_one();

    _metrics->incrementCounter("search.reindex.scheduled");
}

std::uint64_t ContentSearchService::popTask()
{
    std::unique_lock lock(_queueMutex);

    _queueCond.wait(lock,
                    [this]()
                    { return _shutdown || !_taskQueue.empty(); });

    if (_shutdown)
    {
        return 0; // 0 is treated as special 'shutdown' signal
    }

    auto contentId = _taskQueue.front();
    _taskQueue.pop();
    return contentId;
}

void ContentSearchService::workerLoop(const std::size_t workerIndex)
{
    (void)workerIndex; // not used for now, but left for logging/tracing.

    while (!_shutdown)
    {
        const auto contentId = popTask();
        if (contentId == 0) { continue; } // spurious, but safe.

        try
        {
            _repo->indexContent(contentId);
            _metrics->incrementCounter("search.reindex.completed");
        }
        catch (const std::exception &ex)
        {
            spdlog::error("Re-indexing of content {} failed: {}",
                          contentId,
                          ex.what());
            _metrics->incrementCounter("search.reindex.failed");
        }
    }
}

} // namespace blog::search
```
