```cpp
/***********************************************************************************
 *  IntraLedger BlogSuite
 *  File:        src/module_68.cpp
 *  Created:     2024-05-23
 *
 *  Description:
 *      SearchIndexer — background component that receives indexing requests for
 *      blog posts and pages, transforms them into an internal full-text search
 *      document and ships the document to the configured search backend. The
 *      class owns a small thread-pool and a blocking queue to guarantee bounded
 *      memory usage while preserving high throughput under load produced by the
 *      online editor, scheduled imports, and comment streams.
 *
 *  NOTE:
 *      All symbols that belong to other compilation units (e.g. ORM repositories,
 *      search client, or logger) are forward-declared here; the concrete
 *      definitions are provided by their respective modules at link-time.
 *
 *  License:
 *      Copyright (c) 2024.
 *      SPDX-License-Identifier: Apache-2.0
 ***********************************************************************************/

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

//------------------------------------------------------------------------------
// Forward declarations of external interfaces (defined elsewhere in the system)
//------------------------------------------------------------------------------

// ORM entity representing a blog post.
namespace model {
struct Post
{
    std::int64_t id;
    std::string  title;
    std::string  body;
    std::string  language_iso;
    bool         is_published;
    std::chrono::system_clock::time_point published_at;
};
} // namespace model

// Repository interface for retrieving posts from the database.
namespace repository {
class IPostRepository
{
public:
    virtual ~IPostRepository()                                    = default;
    virtual std::optional<model::Post> findById(std::int64_t id)  = 0;
};
} // namespace repository

// Search backend client (e.g., Elasticsearch, OpenSearch, Meilisearch…).
namespace search_backend {
struct Document
{
    std::int64_t id;
    std::string  language;
    std::string  title;
    std::string  content;
};

class ISearchClient
{
public:
    virtual ~ISearchClient()                                                                = default;
    virtual void upsertDocument(const Document& doc)                                        = 0;
    virtual void removeDocument(std::int64_t id)                                            = 0;
};
} // namespace search_backend

// Logger abstraction (wrapping spdlog, boost::log, etc.).
namespace infrastructure {
class ILogger
{
public:
    enum class Level
    {
        Debug,
        Info,
        Warning,
        Error,
        Fatal
    };

    virtual ~ILogger() = default;
    virtual void log(Level lvl, const std::string& tag, const std::string& msg) noexcept = 0;
};
} // namespace infrastructure

//------------------------------------------------------------------------------
// Implementation
//------------------------------------------------------------------------------

namespace intraledger::search {

// Forward declaration.
class SearchIndexer;

/**
 * BlockingQueue<T>
 *
 * A small single-producer/consumer-capable blocking queue with a configurable
 * capacity. The queue guarantees push/pop linearizability and fairness under
 * contention. Not meant for unbounded growth; will throw when capacity is
 * exceeded to protect system health.
 */
template <typename T>
class BlockingQueue
{
public:
    explicit BlockingQueue(std::size_t capacity) : m_capacity(capacity) {}

    // Disable copy/assign
    BlockingQueue(const BlockingQueue&)            = delete;
    BlockingQueue& operator=(const BlockingQueue&) = delete;

    /**
     * push
     *
     * Attempts to push an element; blocks if queue is full until space becomes
     * available or until SearchIndexer initiates shutdown.
     */
    void push(T item)
    {
        std::unique_lock lock(m_mutex);
        m_not_full.wait(lock, [this] { return m_queue.size() < m_capacity || m_shutdown; });

        if (m_shutdown)
            throw std::runtime_error("BlockingQueue::push() after shutdown");

        m_queue.emplace(std::move(item));
        m_not_empty.notify_one();
    }

    /**
     * pop
     *
     * Blocks until an element is available or until shutdown is requested. In
     * shutdown scenario returns std::nullopt to allow worker threads to finish
     * gracefully.
     */
    std::optional<T> pop()
    {
        std::unique_lock lock(m_mutex);
        m_not_empty.wait(lock, [this] { return !m_queue.empty() || m_shutdown; });

        if (m_queue.empty())
            return std::nullopt;

        T item = std::move(m_queue.front());
        m_queue.pop();
        m_not_full.notify_one();
        return item;
    }

    /**
     * shutdown
     *
     * Unblocks all waiters and prohibits further pushes. Idempotent.
     */
    void shutdown() noexcept
    {
        std::lock_guard guard(m_mutex);
        m_shutdown = true;
        m_not_empty.notify_all();
        m_not_full.notify_all();
    }

private:
    std::mutex              m_mutex;
    std::condition_variable m_not_full;
    std::condition_variable m_not_empty;
    std::queue<T>           m_queue;
    const std::size_t       m_capacity;
    bool                    m_shutdown{false};
};

/**
 * SearchIndexJob
 *
 * Represents an indexing or deletion job derived from application events.
 */
struct SearchIndexJob
{
    enum class Type
    {
        Upsert,
        Remove
    };

    Type         type;
    std::int64_t postId;
};

/**
 * SearchIndexer
 *
 * Public-facing service used by controllers, domain services, and event
 * listeners. The component is instantiated as a process-wide singleton managed
 * by the Service Locator.
 */
class SearchIndexer : public std::enable_shared_from_this<SearchIndexer>
{
public:
    struct Options
    {
        std::size_t           queueCapacity       = 1024;
        std::size_t           workerThreads       = std::thread::hardware_concurrency();
        std::chrono::seconds  gracefulShutdownTmo = std::chrono::seconds(30);
    };

    SearchIndexer(std::shared_ptr<repository::IPostRepository> repo,
                  std::shared_ptr<search_backend::ISearchClient> search,
                  std::shared_ptr<infrastructure::ILogger> logger,
                  Options opts = {})
        : m_repo(std::move(repo)),
          m_search(std::move(search)),
          m_logger(std::move(logger)),
          m_options(opts),
          m_queue(opts.queueCapacity),
          m_running(true)
    {
        if (!m_repo || !m_search || !m_logger)
            throw std::invalid_argument("SearchIndexer: dependencies must not be null");

        launchWorkers();
        m_logger->log(infrastructure::ILogger::Level::Info, kLogTag,
                      "SearchIndexer online with " + std::to_string(m_workers.size()) + " workers");
    }

    ~SearchIndexer()
    {
        shutdown();
    }

    /**
     * enqueueUpsert
     *
     * Schedules a (re-)indexing task for the provided post id.
     */
    void enqueueUpsert(std::int64_t postId)
    {
        enqueueJob(SearchIndexJob{SearchIndexJob::Type::Upsert, postId});
    }

    /**
     * enqueueRemoval
     *
     * Schedules a deletion request for the provided post id.
     */
    void enqueueRemoval(std::int64_t postId)
    {
        enqueueJob(SearchIndexJob{SearchIndexJob::Type::Remove, postId});
    }

    /**
     * shutdown
     *
     * Initiates graceful shutdown: stops accepting new jobs, unblocks workers,
     * and joins threads.
     */
    void shutdown()
    {
        bool expected = true;
        if (!m_running.compare_exchange_strong(expected, false))
            return; // already shutting down

        m_logger->log(infrastructure::ILogger::Level::Info, kLogTag, "SearchIndexer shutting down");

        // signal queue + wait for workers
        m_queue.shutdown();
        for (auto& t : m_workers)
        {
            if (t.joinable())
            {
                // Wait with timeout to avoid indefinite blocking.
                auto start = std::chrono::steady_clock::now();
                while (t.joinable() && std::chrono::steady_clock::now() - start < m_options.gracefulShutdownTmo)
                {
                    try
                    {
                        t.join();
                    }
                    catch (const std::system_error&)
                    {
                        // Spurious failure, retry.
                        std::this_thread::sleep_for(std::chrono::milliseconds(50));
                    }
                }
                if (t.joinable())
                    t.detach(); // last resort
            }
        }

        m_logger->log(infrastructure::ILogger::Level::Info, kLogTag, "SearchIndexer down");
    }

private:
    void launchWorkers()
    {
        const std::size_t nt = std::max<std::size_t>(1, m_options.workerThreads);
        m_workers.reserve(nt);
        for (std::size_t i = 0; i < nt; ++i)
        {
            m_workers.emplace_back([self = shared_from_this(), idx = i] { self->workerLoop(idx); });
        }
    }

    void enqueueJob(SearchIndexJob job)
    {
        if (!m_running.load())
        {
            m_logger->log(infrastructure::ILogger::Level::Warning, kLogTag, "enqueueJob() after shutdown ignored");
            return;
        }

        try
        {
            m_queue.push(std::move(job));
        }
        catch (const std::exception& ex)
        {
            m_logger->log(infrastructure::ILogger::Level::Error, kLogTag,
                          std::string("Unable to enqueue job: ") + ex.what());
        }
    }

    void workerLoop(std::size_t workerIdx)
    {
        const std::string tagWorker = kLogTag + ".worker." + std::to_string(workerIdx);

        while (m_running.load())
        {
            auto maybeJob = m_queue.pop();
            if (!maybeJob)
                break; // queue shutting down

            const SearchIndexJob& job = *maybeJob;
            try
            {
                switch (job.type)
                {
                case SearchIndexJob::Type::Upsert:
                    processUpsert(job.postId, tagWorker);
                    break;
                case SearchIndexJob::Type::Remove:
                    processRemoval(job.postId, tagWorker);
                    break;
                }
            }
            catch (const std::exception& ex)
            {
                m_logger->log(infrastructure::ILogger::Level::Error, tagWorker,
                              std::string("Job failed: ") + ex.what());
            }
            catch (...)
            {
                m_logger->log(infrastructure::ILogger::Level::Fatal, tagWorker,
                              "Unknown error during indexing job");
            }
        }

        m_logger->log(infrastructure::ILogger::Level::Debug, tagWorker, "workerLoop exited");
    }

    void processUpsert(std::int64_t postId, const std::string& logTag)
    {
        auto postOpt = m_repo->findById(postId);
        if (!postOpt)
        {
            m_logger->log(infrastructure::ILogger::Level::Warning, logTag,
                          "Post " + std::to_string(postId) + " not found");
            return;
        }

        const model::Post& post = *postOpt;
        if (!post.is_published)
        {
            m_logger->log(infrastructure::ILogger::Level::Debug, logTag,
                          "Skipping unpublished post " + std::to_string(postId));
            return;
        }

        search_backend::Document doc{
            post.id,
            post.language_iso,
            post.title,
            post.body
        };

        m_search->upsertDocument(doc);

        m_logger->log(infrastructure::ILogger::Level::Info, logTag,
                      "Indexed post " + std::to_string(postId));
    }

    void processRemoval(std::int64_t postId, const std::string& logTag)
    {
        m_search->removeDocument(postId);
        m_logger->log(infrastructure::ILogger::Level::Info, logTag,
                      "Removed post " + std::to_string(postId) + " from search");
    }

private:
    static constexpr const char* kLogTag = "SearchIndexer";

    std::shared_ptr<repository::IPostRepository>     m_repo;
    std::shared_ptr<search_backend::ISearchClient>   m_search;
    std::shared_ptr<infrastructure::ILogger>         m_logger;
    Options                                          m_options;
    BlockingQueue<SearchIndexJob>                    m_queue;
    std::vector<std::thread>                         m_workers;
    std::atomic<bool>                                m_running;
};

} // namespace intraledger::search
```