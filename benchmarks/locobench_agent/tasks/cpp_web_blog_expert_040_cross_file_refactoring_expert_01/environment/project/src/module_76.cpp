```cpp
// -------------------------------------------------------------------------------------------------
// File:        src/module_76.cpp
// Project:     IntraLedger BlogSuite (web_blog)
// Module:      ScheduledPublicationService
//
// Description:
//  Implements a background service responsible for polling the database for articles that are
//  scheduled for publication and enqueueing a PublishArticleJob for each eligible record.  The
//  service is designed to run inside the built-in asynchronous job processor but can also operate
//  standalone during integration tests.
//
//  High-level flow:
//     1.   A worker thread wakes up every <poll_interval_> seconds
//     2.   Opens a fresh ORM::Session to guarantee transactional isolation
//     3.   Selects all Article entities whose status == “scheduled” AND
//          whose publish_at <= now (UTC)
//     4.   For each article, constructs a PublishArticleJob that will:
//            a. Mark article as “published”
//            b. Clear any cache entries
//            c. Fan-out notification e-mails & web-socket events
//     5.   Commits transaction, pushes jobs into the global JobQueue, and records audit entries
//
//  The implementation emphasizes:
//     • Thread-safety using std::atomic and RAII
//     • Proper exception boundaries with rich log messages
//     • Minimal coupling via forward-declared interfaces and dependency injection
//     • Graceful shutdown semantics for hot-reload deployments
//
// -------------------------------------------------------------------------------------------------

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

// ----- External / Project Headers ---------------------------------------------------------------
#include "core/log/Logger.hpp"                   // spdlog-compatible wrapper
#include "core/orm/Session.hpp"                  // Unit-of-work abstraction
#include "core/orm/SessionFactory.hpp"           // Factory for creating sessions
#include "core/queue/JobQueue.hpp"               // Global asynchronous queue
#include "core/queue/jobs/PublishArticleJob.hpp" // Job definition for publishing an article
#include "domain/models/Article.hpp"             // ORM entity
#include "domain/repository/ArticleRepository.hpp"

// -------------------------------------------------------------------------------------------------
namespace blogsuite::services
{
// Forward declaration for PIMPL to reduce compilation dependencies.
class ScheduledPublicationServiceImpl;

// =================================================================================================
// ScheduledPublicationService – Public façade
// =================================================================================================
class ScheduledPublicationService
{
public:
    ScheduledPublicationService(std::shared_ptr<orm::SessionFactory>   sessionFactory,
                                std::shared_ptr<queue::JobQueue>       jobQueue,
                                std::chrono::seconds                   pollInterval = std::chrono::seconds{30});

    ~ScheduledPublicationService(); // Ensures clean shutdown

    ScheduledPublicationService(const ScheduledPublicationService&)            = delete;
    ScheduledPublicationService(ScheduledPublicationService&&)                 = delete;
    ScheduledPublicationService& operator=(const ScheduledPublicationService&) = delete;
    ScheduledPublicationService& operator=(ScheduledPublicationService&&)      = delete;

    // Starts the background thread. No-op if already running.
    void start();

    // Signals the thread to stop and waits for it to finish.
    void stop();

    // Indicates whether the worker is currently running.
    [[nodiscard]] bool isRunning() const noexcept;

private:
    std::unique_ptr<ScheduledPublicationServiceImpl> impl_;
};

// =================================================================================================
// Implementation (PIMPL)
// =================================================================================================
class ScheduledPublicationServiceImpl
{
public:
    ScheduledPublicationServiceImpl(std::shared_ptr<orm::SessionFactory>   sessionFactory,
                                    std::shared_ptr<queue::JobQueue>       jobQueue,
                                    std::chrono::seconds                   pollInterval)
        : sessionFactory_{std::move(sessionFactory)},
          jobQueue_{std::move(jobQueue)},
          pollInterval_{pollInterval},
          stopFlag_{false}
    {
        if (!sessionFactory_)
            throw std::invalid_argument("sessionFactory must not be null");
        if (!jobQueue_)
            throw std::invalid_argument("jobQueue must not be null");
    }

    ~ScheduledPublicationServiceImpl() { stop(); }

    void start()
    {
        std::lock_guard<std::mutex> lock(startStopMutex_);
        if (workerThread_.joinable())
            return; // Already running

        stopFlag_.store(false, std::memory_order_release);
        workerThread_ = std::thread([this] { run(); });
        log::Logger::info("[SchedPub] ScheduledPublicationService started. Poll every {}s.",
                          pollInterval_.count());
    }

    void stop() noexcept
    {
        {
            std::lock_guard<std::mutex> lock(startStopMutex_);
            if (!workerThread_.joinable())
                return; // Not running
            stopFlag_.store(true, std::memory_order_release);
        }
        cv_.notify_all();
        workerThread_.join();
        log::Logger::info("[SchedPub] ScheduledPublicationService stopped.");
    }

    bool isRunning() const noexcept { return workerThread_.joinable(); }

private:
    void run()
    {
        auto nextWakeup = std::chrono::steady_clock::now() + pollInterval_;
        while (!stopFlag_.load(std::memory_order_acquire))
        {
            try
            {
                processDueArticles();
            }
            catch (const std::exception& ex)
            {
                log::Logger::error("[SchedPub] Fatal error during processing: {}", ex.what());
                // Continue looping – we do not want to kill the thread for transient failures
            }

            // Wait until next interval or stop signal
            std::unique_lock<std::mutex> lock(cvMutex_);
            cv_.wait_until(lock, nextWakeup, [this] { return stopFlag_.load(); });
            nextWakeup = std::chrono::steady_clock::now() + pollInterval_;
        }
    }

    void processDueArticles()
    {
        // 1) Open a new session (RAII – will rollback on destruction if not committed)
        auto session = sessionFactory_->createSession();
        domain::repository::ArticleRepository articleRepo{session};

        const auto nowUtc = std::chrono::system_clock::now();

        // 2) Fetch eligible articles
        auto dueArticles = articleRepo.fetchScheduledBefore(nowUtc);
        if (dueArticles.empty())
            return;

        log::Logger::debug("[SchedPub] {} article(s) ready for publication.", dueArticles.size());

        // 3) For each article, push a PublishArticleJob
        for (auto& article : dueArticles)
        {
            try
            {
                // Optimistic locking to avoid double-publishing in race conditions
                article.setStatus(domain::models::ArticleStatus::Publishing);
                articleRepo.save(article);

                auto job = std::make_unique<queue::jobs::PublishArticleJob>(article.getId());
                jobQueue_->push(std::move(job));

                log::Logger::info("[SchedPub] Enqueued PublishArticleJob for article #{}",
                                  article.getId());
            }
            catch (const orm::ConcurrencyException& ex)
            {
                // Another worker/thread updated the row first — benign; simply ignore
                log::Logger::warn(
                    "[SchedPub] Concurrency conflict while scheduling article #{}: {}",
                    article.getId(), ex.what());
            }
        }

        // 4) Commit the transaction
        session.commit();
    }

    // --- Members ---------------------------------------------------------------------------------
    std::shared_ptr<orm::SessionFactory> sessionFactory_;
    std::shared_ptr<queue::JobQueue>     jobQueue_;
    const std::chrono::seconds           pollInterval_;

    std::thread              workerThread_;
    std::atomic<bool>        stopFlag_;
    std::condition_variable  cv_;
    mutable std::mutex       cvMutex_;
    mutable std::mutex       startStopMutex_;
};

// =================================================================================================
// ScheduledPublicationService – façade forwarding to implementation
// =================================================================================================
ScheduledPublicationService::ScheduledPublicationService(
    std::shared_ptr<orm::SessionFactory> sessionFactory, std::shared_ptr<queue::JobQueue> jobQueue,
    std::chrono::seconds                 pollInterval)
    : impl_{std::make_unique<ScheduledPublicationServiceImpl>(
          std::move(sessionFactory), std::move(jobQueue), pollInterval)}
{
}

ScheduledPublicationService::~ScheduledPublicationService() = default;

void ScheduledPublicationService::start() { impl_->start(); }

void ScheduledPublicationService::stop() { impl_->stop(); }

bool ScheduledPublicationService::isRunning() const noexcept { return impl_->isRunning(); }

} // namespace blogsuite::services

// -------------------------------------------------------------------------------------------------
// Unit-test hook (compiled only when BUILD_TESTS is defined)
// -------------------------------------------------------------------------------------------------
#ifdef BUILD_TESTS
#include <gtest/gtest.h>

namespace
{
using namespace blogsuite::services;

class MockSessionFactory : public orm::SessionFactory
{
public:
    std::unique_ptr<orm::Session> createSession() override { return {}; }
};

class MockJobQueue : public queue::JobQueue
{
public:
    void push(std::unique_ptr<queue::Job> job) override { ++pushed_; }
    std::size_t pushed() const { return pushed_; }

private:
    std::atomic<std::size_t> pushed_{0};
};

TEST(ScheduledPublicationServiceTest, StartStopLifecycle)
{
    auto factory   = std::make_shared<MockSessionFactory>();
    auto jobQueue  = std::make_shared<MockJobQueue>();
    ScheduledPublicationService svc{factory, jobQueue, std::chrono::seconds{1}};
    EXPECT_FALSE(svc.isRunning());
    svc.start();
    EXPECT_TRUE(svc.isRunning());
    svc.stop();
    EXPECT_FALSE(svc.isRunning());
}
} // namespace
#endif
```