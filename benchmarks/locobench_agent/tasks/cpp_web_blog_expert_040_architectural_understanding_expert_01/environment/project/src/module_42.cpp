```cpp
// ──────────────────────────────────────────────────────────────────────────────
//  IntraLedger BlogSuite
//  File:        src/module_42.cpp
//  Created:     2024-06-15
//  Author:      IntraLedger Engineering
//
//  Description:
//      An asynchronous job responsible for (re)building the full-text search
//      index for every public article in the system.  The job is designed to be
//      queued by the central JobProcessor, but it can also be executed
//      in-process for installation and disaster-recovery scenarios.
//
//  Dependencies (compile-time):
//      • <future>, <thread>, <vector>, <queue>, <condition_variable>, <atomic>
//      • Logger.hpp                 - Unified, sink-based structured logger
//      • Repository/IArticleRepository.hpp
//      • Service/SearchIndexService.hpp
//      • Util/StopToken.hpp         - Cooperative cancellation abstraction
// ──────────────────────────────────────────────────────────────────────────────

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <utility>
#include <vector>

#include "Logger.hpp"
#include "Repository/IArticleRepository.hpp"
#include "Service/SearchIndexService.hpp"
#include "Util/StopToken.hpp"

namespace ilbs          // IntraLedger BlogSuite
{
namespace jobs          // Job namespace
{
// ──────────────────────────────────────────────────────────────────────────────
//  Internal, minimalistic thread-pool for one-off jobs
// ──────────────────────────────────────────────────────────────────────────────
class ThreadPool final
{
public:
    explicit ThreadPool(std::size_t workers)
        : _shutdown{false}
    {
        workers = std::max<std::size_t>(1U, workers);
        _threads.reserve(workers);
        for (std::size_t i = 0; i < workers; ++i)
        {
            _threads.emplace_back([this] { workerLoop(); });
        }
    }

    ThreadPool(const ThreadPool&)            = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;

    ~ThreadPool()
    {
        {
            std::scoped_lock lk{_lock};
            _shutdown = true;
        }
        _condition.notify_all();
        for (auto& t : _threads)
        {
            if (t.joinable())
                t.join();
        }
    }

    template <typename F, typename... Args>
    auto enqueue(F&& fn, Args&&... args) -> std::future<decltype(fn(args...))>
    {
        using ReturnT = decltype(fn(args...));

        auto task = std::make_shared<std::packaged_task<ReturnT()>>(
            std::bind(std::forward<F>(fn), std::forward<Args>(args)...));

        std::future<ReturnT> result = task->get_future();
        {
            std::scoped_lock lk{_lock};
            if (_shutdown)
                throw std::runtime_error("ThreadPool shutting down");

            _tasks.emplace([task]() { (*task)(); });
        }
        _condition.notify_one();
        return result;
    }

private:
    void workerLoop()
    {
        while (true)
        {
            std::function<void()> task;
            {
                std::unique_lock lk{_lock};
                _condition.wait(
                    lk, [this] { return _shutdown || !_tasks.empty(); });
                if (_shutdown && _tasks.empty())
                    return;

                task = std::move(_tasks.front());
                _tasks.pop();
            }
            try
            {
                task();
            }
            catch (const std::exception& ex)
            {
                Logger::error("ThreadPool task threw: {}", ex.what());
            }
            catch (...)
            {
                Logger::error("ThreadPool task threw unknown exception");
            }
        }
    }

    std::vector<std::thread>        _threads;
    std::queue<std::function<void()>> _tasks;

    std::mutex              _lock;
    std::condition_variable _condition;
    bool                    _shutdown;
};

// ──────────────────────────────────────────────────────────────────────────────
// SearchIndexRebuilder
// ──────────────────────────────────────────────────────────────────────────────
class SearchIndexRebuilder final
{
public:
    SearchIndexRebuilder(std::shared_ptr<data::IArticleRepository> repo,
                         std::shared_ptr<svc::SearchIndexService>  svc,
                         std::size_t                               workers = std::thread::hardware_concurrency())
        : _repo{std::move(repo)}
        , _svc{std::move(svc)}
        , _pool{workers ? workers : 2}
    {
        if (!_repo || !_svc)
            throw std::invalid_argument("SearchIndexRebuilder requires valid repo and service");

        Logger::info("SearchIndexRebuilder initialized ({} workers)", workers);
    }

    // Kick off a full rebuild; returns a Future representing the completion.
    std::future<void> runAsync(util::StopToken cancel = {})
    {
        return std::async(std::launch::async, [this, cancel] { run(cancel); });
    }

    // Synchronous variant, throws on failure.
    void run(util::StopToken cancel = {})
    {
        try
        {
            Logger::info("Starting search-index rebuild…");
            const auto ids = _repo->listPublicArticleIds();

            std::vector<std::future<void>> futures;
            futures.reserve(ids.size());

            for (auto id : ids)
            {
                // Respect cancellation before queuing the next task.
                if (cancel.stopRequested())
                {
                    Logger::warn("Search-index rebuild cancelled before completion ({} / {})",
                                 futures.size(), ids.size());
                    break;
                }

                futures.emplace_back(_pool.enqueue([this, id, cancel] {
                    if (cancel.stopRequested())
                        return;  // Cooperative cancellation

                    auto article = _repo->fetchById(id);
                    if (!article)
                        return;  // Possible deletion race; ignore.

                    _svc->indexDocument(*article);
                }));
            }

            // Wait for all queued tasks.
            for (auto& f : futures)
            {
                try
                {
                    f.get();
                }
                catch (const std::exception& ex)
                {
                    // Log but continue—one document failing should not abort the rebuild.
                    Logger::error("Failed to index an article: {}", ex.what());
                }
            }

            Logger::info("Search-index rebuild finished ({} documents processed)",
                         futures.size());
        }
        catch (...)
        {
            Logger::critical("Unhandled exception bubbled to SearchIndexRebuilder::run");
            throw;  // Let caller observe failure
        }
    }

private:
    std::shared_ptr<data::IArticleRepository> _repo;
    std::shared_ptr<svc::SearchIndexService>  _svc;
    ThreadPool                                _pool;
};

// ──────────────────────────────────────────────────────────────────────────────
// Job Registration
// ──────────────────────────────────────────────────────────────────────────────
/*
 * The registration below hooks the job into the central JobProcessor,
 * enabling CLI invocation such as:
 *
 *   ./ilbsctl job dispatch SearchIndexRebuilder
 */
namespace
{
struct JobFactory final
{
    JobFactory()
    {
        jobs::JobRegistry::instance().registerCreator(
            "SearchIndexRebuilder",
            [] {
                return std::make_unique<SearchIndexRebuilder>(
                    data::RepositoryFactory::articleRepository(),
                    svc::ServiceLocator::searchIndexService());
            });
    }
} _autoRegister;  // NOLINT(readability-identifier-naming)
}  // anonymous namespace

}  // namespace jobs
}  // namespace ilbs
```