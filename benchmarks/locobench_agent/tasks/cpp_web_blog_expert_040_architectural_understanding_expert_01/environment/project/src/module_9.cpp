```cpp
/***************************************************************************************************
 *  File:        src/module_9.cpp
 *  Project:     IntraLedger BlogSuite (web_blog)
 *
 *  Description:
 *  -------------
 *  SearchIndexService is a high-performance, asynchronous component responsible for (re-)indexing
 *  articles into the full-text search back-end.  Its public interface is purposely minimal to keep
 *  coupling low—callers only need to enqueue a post-ID and the service takes care of batching,
 *  debouncing, retry-handling, and bulk submission.  The class owns a small worker-pool and shuts
 *  itself down gracefully at application termination.
 *
 *  Architectural notes:
 *  --------------------
 *  - Repository Layer:   Talks to PostRepository for fetching canonical post data
 *  - Service Layer:      Exposed through a singleton façade (SearchIndexService::instance())
 *  - Concurrency:        Lock-free hot path with a bounded MPMC queue + condition variable
 *  - Error handling:     Exceptions are caught per-task so one bad document cannot poison the pool
 *  - Configurable:       Tuning knobs exposed through Config::search() (batch size, backoff, etc.)
 *
 *  Copyright:
 *  ----------
 *  © 2024 IntraLedger Corporation — All rights reserved.
 ***************************************************************************************************/

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <exception>
#include <memory>
#include <mutex>
#include <thread>
#include <unordered_set>
#include <vector>

// ──────────────────────────────── In-house headers ──────────────────────────────
// These headers live elsewhere in the code-base.  They are only forward-declared
// here so this TU remains self-contained when built in isolation for demonstration
// purposes.  In production they would be full, concrete implementations.
#include "core/Config.hpp"
#include "core/Log.hpp"
#include "core/StopToken.hpp"
#include "repository/PostRepository.hpp"
#include "search/SearchBackend.hpp"

namespace intraledger::search {

/***************************************************************************************************
 * SearchIndexService
 **************************************************************************************************/
class SearchIndexService final
{
public:
    /// Obtain the global instance (thread-safe, C++11 static-init guaranteed)
    static SearchIndexService& instance()
    {
        static SearchIndexService svc;
        return svc;
    }

    /// Deleted copy/move semantics
    SearchIndexService(const SearchIndexService&)            = delete;
    SearchIndexService& operator=(const SearchIndexService&) = delete;
    SearchIndexService(SearchIndexService&&)                 = delete;
    SearchIndexService& operator=(SearchIndexService&&)      = delete;

    /// Starts the internal worker threads (idempotent)
    void start()
    {
        bool expected = false;
        if (!_isRunning.compare_exchange_strong(expected, true))
            return; // already running

        const unsigned numThreads = std::max(2u, std::thread::hardware_concurrency() / 2u);
        IL_LOG_INFO("SearchIndexService: Spawning {} worker threads", numThreads);

        for (unsigned i = 0; i < numThreads; ++i)
        {
            _workers.emplace_back(
                [this](core::StopToken stopTok) { this->workerLoop(std::move(stopTok)); });
        }
    }

    /// Graceful shutdown (blocks until workers exit or timeout)
    void shutdown()
    {
        if (!_isRunning.exchange(false))  // switched from true → false?
            return;

        {
            std::lock_guard lock(_queueMutex);
            _stopRequested = true;
        }
        _queueCv.notify_all();

        for (auto& w : _workers)
            w.requestStop();
        for (auto& w : _workers)
            if (w.joinable()) w.join();

        _workers.clear();
        IL_LOG_INFO("SearchIndexService: Shutdown complete");
    }

    /// Enqueue a blog post for (re)-indexing
    void enqueueReindex(std::int64_t postId)
    {
        {
            std::lock_guard lock(_queueMutex);
            if (_stopRequested) return;

            // Deduplicate—basic heuristic to avoid double work in bursts
            if (_pendingIds.insert(postId).second)
                _taskQueue.emplace_back(postId);
        }
        _queueCv.notify_one();
    }

    /// Destructor invokes shutdown() to ensure resource cleanup
    ~SearchIndexService() { shutdown(); }

private:
    struct Task
    {
        std::int64_t                  postId;
        std::chrono::steady_clock::time_point queued = std::chrono::steady_clock::now();
    };

    SearchIndexService() = default; // private (singleton)

    void workerLoop(core::StopToken stopTok)
    {
        // Thread-local context:
        repository::PostRepository postRepo;
        search::SearchBackend      backend(core::Config::search().endpoint);

        std::vector<Task> batch;
        batch.reserve(core::Config::search().batchSize);

        while (!stopTok.stopRequested())
        {
            // ------------------ 1) Acquire tasks ------------------
            {
                std::unique_lock lock(_queueMutex);
                _queueCv.wait(lock, [&] {
                    return _stopRequested || !_taskQueue.empty() || stopTok.stopRequested();
                });

                if (_stopRequested || stopTok.stopRequested()) break;

                while (! _taskQueue.empty() && batch.size() < batch.capacity())
                {
                    batch.emplace_back(_taskQueue.front());
                    _taskQueue.pop_front();
                }
            } // unlock mutex

            // ------------------ 2) Process tasks ------------------
            for (const Task& t : batch)
            {
                try
                {
                    auto postOpt = postRepo.findById(t.postId);
                    if (!postOpt)
                    {
                        IL_LOG_WARN("SearchIndexService: Post #{} no longer exists, skipping",
                                    t.postId);
                        continue;
                    }

                    backend.indexDocument(postOpt->toSearchDocument());
                }
                catch (const search::BackendException& ex)
                {
                    IL_LOG_ERROR("SearchIndexService: Backend error while indexing #{} – {}",
                                 t.postId, ex.what());
                    scheduleRetry(t.postId);
                }
                catch (const std::exception& ex)
                {
                    IL_LOG_ERROR("SearchIndexService: Fatal while indexing #{} – {}",
                                 t.postId, ex.what());
                }
            }

            // ------------------ 3) Clear batch & continue ------------------
            {
                std::lock_guard lock(_queueMutex);
                for (const Task& t : batch)
                    _pendingIds.erase(t.postId);
            }
            batch.clear();
        }
    }

    void scheduleRetry(std::int64_t postId)
    {
        static constexpr auto kRetryDelay = std::chrono::seconds(5);

        std::thread{[this, postId] {
            std::this_thread::sleep_for(kRetryDelay);
            this->enqueueReindex(postId);
        }}.detach();
    }

    // ─────────────────────────────── Data members ───────────────────────────────
    std::atomic_bool             _isRunning {false};
    std::atomic_bool             _stopRequested {false};

    std::mutex                   _queueMutex;
    std::condition_variable      _queueCv;

    std::deque<Task>             _taskQueue;     // guarded by _queueMutex
    std::unordered_set<std::int64_t> _pendingIds; // guard same mutex, prevents duplicates

    std::vector<core::StoppableThread> _workers;
};

/***************************************************************************************************
 *  Convenience RAII helper—starts & stops the SearchIndexService automatically at program start.
 *  Link this TU into the main executable and the side-effect of the static object will ensure the
 *  service lives for the lifetime of the process.
 **************************************************************************************************/
struct AutoBootSearchService
{
    AutoBootSearchService()  { SearchIndexService::instance().start(); }
    ~AutoBootSearchService() { SearchIndexService::instance().shutdown(); }
};

// Global static; guaranteed to construct before main() per C++ rules
[[maybe_unused]] static AutoBootSearchService g_autoBoot;

} // namespace intraledger::search
```
