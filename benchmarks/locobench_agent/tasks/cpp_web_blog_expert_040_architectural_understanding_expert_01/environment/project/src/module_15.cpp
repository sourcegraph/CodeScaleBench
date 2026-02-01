```cpp
/**
 *  IntraLedger BlogSuite — Search Index Rebuilder
 *
 *  File:        src/module_15.cpp
 *  License:     MIT
 *
 *  Description:
 *      As part of the asynchronous job-processing subsystem, this module
 *      implements a background task that (re)builds the full-text search
 *      index used by BlogSuite.  The job streams every published blog post
 *      from the data-repository layer, pushes it to the search backend, and
 *      exposes a small supervisory API (status, cancellation, metrics).
 *
 *      The rebuild process is intentionally throttled to prevent resource
 *      starvation on shared production installations.
 */

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include "logging/logger.hpp"                     // Core structured logger
#include "repository/blog_post_repository.hpp"    // Data-access abstraction
#include "search/search_client.hpp"               // Full-text engine adapter

namespace intraledger::blogsuite
{

//----------------------------------------------------------------------
//  Enumerations
//----------------------------------------------------------------------

/**
 *  Enumerates all possible run-time states of a SearchIndexRebuilder.
 */
enum class RebuildStatus : std::uint8_t
{
    Pending    = 0,
    Running    = 1,
    Completed  = 2,
    Cancelled  = 3,
    Failed     = 4
};

//----------------------------------------------------------------------
//  SearchIndexRebuilder
//----------------------------------------------------------------------

class SearchIndexRebuilder : public std::enable_shared_from_this<SearchIndexRebuilder>
{
public:
    /**
     *  Factory helper; enforces shared_ptr semantics right from the start.
     */
    static std::shared_ptr<SearchIndexRebuilder>
    create(std::shared_ptr<repository::BlogPostRepository> repo,
           std::shared_ptr<search::SearchClient>            searchBackend,
           std::chrono::milliseconds                        throttle = std::chrono::milliseconds{ 15 })
    {
        return std::shared_ptr<SearchIndexRebuilder>(
            new SearchIndexRebuilder(std::move(repo),
                                     std::move(searchBackend),
                                     throttle));
    }

    /**
     *  Starts the rebuild asynchronously.
     *
     *  @throws std::logic_error if called more than once.
     */
    std::future<void> startAsync()
    {
        std::lock_guard lock(_stateMx);
        if (_hasStarted)
            throw std::logic_error("SearchIndexRebuilder can only be started once.");

        _hasStarted = true;
        _status.store(RebuildStatus::Running, std::memory_order_release);

        // Keep `this` alive for the entire lifetime of the task.
        auto self = shared_from_this();

        _future = std::async(std::launch::async, [self] {
            try
            {
                self->run();
            }
            catch (const std::exception& ex)
            {
                logging::Logger::critical("Reindex job crashed: {}", ex.what());
                self->_status.store(RebuildStatus::Failed, std::memory_order_release);
            }
            catch (...)
            {
                logging::Logger::critical("Reindex job crashed: <unknown>");
                self->_status.store(RebuildStatus::Failed, std::memory_order_release);
            }
        });

        return _future;
    }

    /**
     *  Requests cancellation.  The job may take a moment to settle.
     */
    void cancel() noexcept
    {
        _cancelRequested.store(true, std::memory_order_release);
    }

    // -----------------------------------------------------------------
    //  Introspection
    // -----------------------------------------------------------------
    [[nodiscard]] RebuildStatus status() const noexcept
    {
        return _status.load(std::memory_order_acquire);
    }

    [[nodiscard]] std::size_t processedCount() const noexcept
    {
        return _processed.load(std::memory_order_acquire);
    }

    [[nodiscard]] std::size_t failedCount() const noexcept
    {
        return _failed.load(std::memory_order_acquire);
    }

    /**
     *  Blocks the caller until the rebuild finishes or throws.
     *
     *  An exception thrown from the worker thread is re-thrown here.
     */
    void await() { _future.get(); }

private:
    // -----------------------------------------------------------------
    //  Construction / Lifetime
    // -----------------------------------------------------------------
    SearchIndexRebuilder(std::shared_ptr<repository::BlogPostRepository> repo,
                         std::shared_ptr<search::SearchClient>          searchBackend,
                         std::chrono::milliseconds                      throttle)
        : _repo(std::move(repo))
        , _search(std::move(searchBackend))
        , _throttle(throttle)
    {
        if (!_repo)   throw std::invalid_argument("BlogPostRepository must not be null.");
        if (!_search) throw std::invalid_argument("SearchClient must not be null.");
    }

    // Non-copyable / non-movable
    SearchIndexRebuilder(const SearchIndexRebuilder&)            = delete;
    SearchIndexRebuilder& operator=(const SearchIndexRebuilder&) = delete;

    // -----------------------------------------------------------------
    //  Worker implementation
    // -----------------------------------------------------------------
    void run()
    {
        logging::Logger::info("Search rebuild started.");
        constexpr std::size_t kBatchSize = 128; // reasonable default

        repository::BlogPostRepository::Cursor cursor = _repo->openPublishedCursor();

        std::vector<repository::BlogPost> batch;
        batch.reserve(kBatchSize);

        while (!_cancelRequested.load(std::memory_order_acquire))
        {
            batch.clear();
            cursor.readNext(batch, kBatchSize);

            if (batch.empty())
                break; // Reached the end

            // Bulk-index the entire batch.  A partial failure rolls back only
            // the posts that failed, while allowing the rebuild to continue.
            try
            {
                _search->bulkIndex(batch);
                _processed.fetch_add(batch.size(), std::memory_order_acq_rel);
            }
            catch (const search::PartialFailure& pf)
            {
                // Record successes & failures independently.
                _processed.fetch_add(pf.successfulCount(), std::memory_order_acq_rel);
                _failed.fetch_add(pf.failedCount(), std::memory_order_acq_rel);

                for (const auto& err : pf.errors())
                {
                    logging::Logger::error("Index error post[id={}]: {}",
                                           err.postId, err.message);
                }
            }
            catch (const std::exception& ex)
            {
                _failed.fetch_add(batch.size(), std::memory_order_acq_rel);
                logging::Logger::error("Batch indexing failed: {}", ex.what());
            }

            if (_throttle.count() > 0)
                std::this_thread::sleep_for(_throttle);
        }

        // Finalize status
        if (_cancelRequested.load(std::memory_order_acquire))
            _status.store(RebuildStatus::Cancelled, std::memory_order_release);
        else if (_failed.load(std::memory_order_acquire) > 0)
            _status.store(RebuildStatus::Failed, std::memory_order_release);
        else
            _status.store(RebuildStatus::Completed, std::memory_order_release);

        logging::Logger::info("Search rebuild finished — processed={}, failed={}, status={}.",
                              _processed.load(std::memory_order_acquire),
                              _failed.load(std::memory_order_acquire),
                              static_cast<int>(_status.load(std::memory_order_acquire)));
    }

    // -----------------------------------------------------------------
    //  Members
    // -----------------------------------------------------------------
    std::shared_ptr<repository::BlogPostRepository> _repo;
    std::shared_ptr<search::SearchClient>           _search;
    const std::chrono::milliseconds                 _throttle;

    std::future<void> _future;
    bool              _hasStarted{ false };

    std::atomic<RebuildStatus> _status{ RebuildStatus::Pending };
    std::atomic<bool>          _cancelRequested{ false };
    std::atomic<std::size_t>   _processed{ 0 };
    std::atomic<std::size_t>   _failed{ 0 };
    mutable std::mutex         _stateMx; // protects _hasStarted
};

} // namespace intraledger::blogsuite
```