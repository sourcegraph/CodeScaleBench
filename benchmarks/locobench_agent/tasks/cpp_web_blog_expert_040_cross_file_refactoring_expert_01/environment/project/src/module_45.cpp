```cpp
/*
 *  IntraLedger BlogSuite – Search Index Rebuilder
 *  ------------------------------------------------
 *  This source file contains the implementation of an asynchronous,
 *  fault-tolerant service that (re)builds the full-text search index
 *  whenever articles are created, updated, or removed from the data-store.
 *
 *  File:        src/module_45.cpp
 *  Author:      IntraLedger Engineering
 *  License:     Proprietary
 *
 *  The class is designed to live inside the monolith and interact with the
 *  internal job-processor.  It purposefully avoids compile-time coupling
 *  to any concrete back-end (e.g., Elastic, Solr, bespoke) and instead
 *  utilises two small abstraction layers:
 *
 *      • data::IArticleRepository  – CRUD gateway for blog articles
 *      • search::ISearchBackend    – Driver interface for the search engine
 *
 *  Both are injected via factory helpers or a DI container at runtime.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward-declarations for core cross-cutting types.  The actual contracts   */
/* live in their respective include paths.                                   */
namespace logging {
class Logger;
using LoggerPtr = std::shared_ptr<Logger>;
} // namespace logging

namespace data {

/* Lightweight data transfer object used for re-indexing. */
struct Article final
{
    std::uint64_t                              id          {0};
    std::string                                title;
    std::string                                body;
    std::vector<std::string>                   tags;
    std::chrono::system_clock::time_point      publishedAt {};
};

class IArticleRepository
{
public:
    virtual ~IArticleRepository() = default;

    /* Fetches all articles that are publicly visible. */
    virtual std::vector<Article> fetchPublishedArticles() = 0;

    /* Streams articles in chunks. Optional optimisation. */
    virtual std::vector<Article> fetchPublishedChunk(std::size_t offset,
                                                     std::size_t limit) = 0;
};

using ArticleRepositoryPtr = std::shared_ptr<IArticleRepository>;
} // namespace data

namespace search {

class ISearchBackend
{
public:
    virtual ~ISearchBackend() = default;

    /* Bulk-begin / commit are optional but highly encouraged for performance. */
    virtual void beginBulk()                                    = 0;
    virtual void commitBulk()                                   = 0;

    /* (Re)index an article; must be idempotent. */
    virtual void index(const data::Article& article)            = 0;

    /* Remove an article from the index. */
    virtual void remove(std::uint64_t articleId)                = 0;
};

using SearchBackendPtr = std::shared_ptr<ISearchBackend>;

} // namespace search

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation – blog::search::SearchIndexRebuilder                       */
namespace blog::search {

class SearchIndexRebuilder final
{
public:
    /* Thread-safe singleton accessor. */
    static SearchIndexRebuilder& instance()
    {
        static SearchIndexRebuilder inst;
        return inst;
    }

    /*
     * scheduleRebuild()
     * -----------------
     * Queues a rebuild instruction.  If 'lowPriority' is false, the task is
     * pushed to the front of the queue, ensuring faster execution (e.g.,
     * after an urgent security patch or when weird edge-cases are suspected).
     *
     * The caller receives a std::future that can be awaited for completion
     * or ignored if fire-and-forget semantics are acceptable.
     */
    std::future<void> scheduleRebuild(bool lowPriority = true)
    {
        if (!_backend || !_articleRepo)
            throw std::logic_error(
                "SearchIndexRebuilder: dependencies have not been set");

        std::promise<void> p;
        auto fut = p.get_future();

        {
            std::lock_guard<std::mutex> lock(_mutex);
            if (lowPriority) {
                _queue.emplace_back(std::move(p));
            } else {
                _queue.emplace_front(std::move(p));
            }
        }
        _cv.notify_one();
        return fut;
    }

    /*
     * Dependency injection.   Must be called once during application start-up.
     * Invoking these twice is considered a programmer error.
     */
    void setArticleRepository(const data::ArticleRepositoryPtr& repo)
    {
        if (_articleRepo) {
            throw std::logic_error(
                "SearchIndexRebuilder: ArticleRepository already configured");
        }
        _articleRepo = repo;
    }

    void setSearchBackend(const search::SearchBackendPtr& backend)
    {
        if (_backend) {
            throw std::logic_error(
                "SearchIndexRebuilder: SearchBackend already configured");
        }
        _backend = backend;
    }

    void setLogger(const logging::LoggerPtr& logger) { _logger = logger; }

    /* Gracefully stop the worker thread; used for test-tear-down / shutdown. */
    void stop()
    {
        _shutdown.store(true, std::memory_order_release);
        _cv.notify_one();
        if (_worker.joinable()) { _worker.join(); }
    }

    /* Non-movable, non-copyable. */
    SearchIndexRebuilder(const SearchIndexRebuilder&)            = delete;
    SearchIndexRebuilder(SearchIndexRebuilder&&)                 = delete;
    SearchIndexRebuilder& operator=(const SearchIndexRebuilder&) = delete;
    SearchIndexRebuilder& operator=(SearchIndexRebuilder&&)      = delete;

private:
    SearchIndexRebuilder()
    {
        _worker = std::thread([this] { this->workerLoop(); });
        _worker.detach(); /* Detach to avoid shutdown dead-locks. */
    }

    ~SearchIndexRebuilder() { stop(); }

    /* ────────────────────────────────────────────────────────────── */

    /*
     * workerLoop()
     * ------------
     * Centralised background executor that drains the rebuild queue.
     */
    void workerLoop()
    {
        while (!_shutdown.load(std::memory_order_acquire)) {
            std::promise<void> promise;
            {
                std::unique_lock<std::mutex> lock(_mutex);
                _cv.wait(lock, [this] {
                    return _shutdown.load(std::memory_order_relaxed) ||
                           !_queue.empty();
                });

                if (_shutdown.load(std::memory_order_relaxed)) { break; }
                promise = std::move(_queue.front());
                _queue.pop_front();
            }

            try {
                if (_logger) { /* Lazy logging to avoid perf impact */
                    // _logger->info("SearchIndexRebuilder: starting rebuild");
                }
                performRebuild();
                promise.set_value();

                if (_logger) {
                    // _logger->info("SearchIndexRebuilder: rebuild complete");
                }
            } catch (const std::exception& ex) {
                if (_logger) {
                    // _logger->error("SearchIndexRebuilder failed: {}", ex.what());
                }
                promise.set_exception(std::current_exception());
            } catch (...) {
                if (_logger) {
                    // _logger->error("SearchIndexRebuilder failed: <unknown>");
                }
                promise.set_exception(std::current_exception());
            }
        }
    }

    /*
     * performRebuild()
     * ----------------
     * Heavy-lifting function that runs inside the worker thread.
     * The process is deliberately simple: blow away everything and rebuild
     * from scratch.  Incremental indexing could be implemented later.
     */
    void performRebuild()
    {
        if (!_backend || !_articleRepo) {
            throw std::runtime_error("SearchIndexRebuilder: dependencies missing");
        }

        const auto start = std::chrono::steady_clock::now();
        _backend->beginBulk();

        constexpr std::size_t CHUNK_SIZE = 256;
        std::size_t offset               = 0;

        while (true) {
            auto chunk = _articleRepo->fetchPublishedChunk(offset, CHUNK_SIZE);
            if (chunk.empty()) { break; }

            for (const auto& article : chunk) {
                _backend->index(article);
            }

            offset += chunk.size();
        }

        _backend->commitBulk();

        const auto durMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now() - start)
                               .count();
        if (_logger) {
            // _logger->info("SearchIndexRebuilder: indexed {} articles in {} ms",
            //               offset, durMs);
        }
    }

    /* ────────────────────────────────────────────────────────────── */

    std::atomic_bool                    _shutdown {false};
    std::mutex                          _mutex;
    std::condition_variable             _cv;
    std::deque<std::promise<void>>      _queue;
    std::thread                         _worker;

    /* Dependencies */
    data::ArticleRepositoryPtr          _articleRepo {};
    search::SearchBackendPtr            _backend     {};
    logging::LoggerPtr                  _logger      {};
};

} // namespace blog::search

/* ────────────────────────────────────────────────────────────────────────── */
/* Global convenience helper.  This may be used in client code:              */
/*
 *     auto fut = blog::search::SearchIndexRebuilder::instance()
 *                   .scheduleRebuild(false); // High priority
 *     fut.get(); // Wait for completion
 */
/* ────────────────────────────────────────────────────────────────────────── */
```