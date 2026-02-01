/*
 *  IntraLedger BlogSuite – Search Indexer Module
 *  File: src/module_21.cpp
 *
 *  Purpose:
 *      Provides a small, production-grade indexing service used by BlogSuite’s
 *      asynchronous job processor to (re)index Articles into the full-text
 *      search backend.  The module demonstrates:
 *
 *          • Loose coupling with Repository/Service layers
 *          • Thread-safe task scheduling
 *          • Robust error handling & retry logic
 *          • Modern C++17 idioms and RAII
 *
 *  NOTE:
 *      This file purposefully avoids depending on any third-party search
 *      library.  Instead, it exposes a micro-client interface that can be
 *      adapted to Elasticsearch, MeiliSearch, Solr, etc.  Unit-tests can
 *      replace the client with a mock implementation.
 *
 *  Copyright (c) 2024
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <new>
#include <optional>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace intraledger::common
{
// -----------------------------------------------------------------------------
// Helper: ISO-8601 timestamp
// -----------------------------------------------------------------------------
inline std::string make_iso_timestamp(std::chrono::system_clock::time_point tp)
{
    using namespace std::chrono;
    auto t          = system_clock::to_time_t(tp);
    auto us         = duration_cast<microseconds>(tp.time_since_epoch()).count() % 1'000'000;
    std::tm tm      = *std::gmtime(&t);

    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S") << '.' << std::setw(6) << std::setfill('0') << us << "Z";
    return oss.str();
}
} // namespace intraledger::common

namespace intraledger::domain
{
// -----------------------------------------------------------------------------
// Domain Entity: Post
// -----------------------------------------------------------------------------
struct Post
{
    std::uint64_t                        id           = 0;
    std::string                          title;
    std::string                          body;
    std::chrono::system_clock::time_point updated_at{};

    bool empty() const noexcept { return title.empty() && body.empty(); }
};

} // namespace intraledger::domain

namespace intraledger::infrastructure
{
// -----------------------------------------------------------------------------
// Search Document DTO (Data Transfer Object)
// -----------------------------------------------------------------------------
struct SearchDocument
{
    std::uint64_t id           = 0;
    std::string   title;
    std::string   excerpt;
    std::string   updated_at_iso;
};

// -----------------------------------------------------------------------------
// Interface: ISearchEngineClient
//      Adaptor for concrete search engine backends
// -----------------------------------------------------------------------------
class ISearchEngineClient
{
public:
    virtual ~ISearchEngineClient() = default;

    virtual void upsert_document(const SearchDocument& doc) = 0;
    virtual void remove_document(std::uint64_t id)          = 0;
};

// -----------------------------------------------------------------------------
// Dummy implementation (fallback) so that the file is self-contained.
// In production, this is replaced at link-time by the actual client.
// -----------------------------------------------------------------------------
class ConsoleSearchClient : public ISearchEngineClient
{
public:
    void upsert_document(const SearchDocument& doc) override
    {
        std::cout << "[SearchClient] UPSERT id=" << doc.id << " title=\"" << doc.title
                  << "\" updated=" << doc.updated_at_iso << '\n';
    }

    void remove_document(std::uint64_t id) override
    {
        std::cout << "[SearchClient] REMOVE id=" << id << '\n';
    }
};

} // namespace intraledger::infrastructure

namespace intraledger::repository
{
// -----------------------------------------------------------------------------
// Simple in-memory Post repository stub.
// Production code uses a DB backed repository (via ORM).
// -----------------------------------------------------------------------------
class IPostRepository
{
public:
    virtual ~IPostRepository()                             = default;
    virtual std::optional<domain::Post> find_by_id(uint64_t id) = 0;
};

// -----------------------------------------------------------------------------
// MemoryPostRepository – stubbed for demonstration.
// -----------------------------------------------------------------------------
class MemoryPostRepository : public IPostRepository
{
public:
    void add(domain::Post post) { store_[post.id] = std::move(post); }

    std::optional<domain::Post> find_by_id(uint64_t id) override
    {
        auto it = store_.find(id);
        if (it == store_.end()) { return std::nullopt; }
        return it->second;
    }

private:
    std::unordered_map<std::uint64_t, domain::Post> store_;
};

} // namespace intraledger::repository

namespace intraledger::service
{
// -----------------------------------------------------------------------------
// Exponential backoff helper
// -----------------------------------------------------------------------------
inline void backoff(std::size_t attempt)
{
    using namespace std::chrono_literals;
    constexpr auto kMaxBackoff = 8s;

    auto delay = std::min(kMaxBackoff, 100ms * (1u << attempt));
    std::this_thread::sleep_for(delay);
}

// -----------------------------------------------------------------------------
// Thread-safe task queue
// -----------------------------------------------------------------------------
class TaskQueue
{
public:
    using Task = std::function<void()>;

    void push(Task t)
    {
        {
            std::lock_guard<std::mutex> l(m_);
            q_.emplace(std::move(t));
        }
        cv_.notify_one();
    }

    bool try_pop(Task& out)
    {
        std::unique_lock<std::mutex> l(m_);
        if (q_.empty()) { return false; }
        out = std::move(q_.front());
        q_.pop();
        return true;
    }

    void wait_and_pop(Task& out)
    {
        std::unique_lock<std::mutex> l(m_);
        cv_.wait(l, [this] { return !q_.empty() || stopped_; });

        if (stopped_) { throw std::runtime_error("TaskQueue stopped"); }

        out = std::move(q_.front());
        q_.pop();
    }

    void stop()
    {
        {
            std::lock_guard<std::mutex> l(m_);
            stopped_ = true;
        }
        cv_.notify_all();
    }

private:
    std::queue<Task>   q_;
    std::mutex         m_;
    std::condition_variable cv_;
    bool               stopped_ = false;
};

// -----------------------------------------------------------------------------
// SearchIndexerService – schedules and processes indexing jobs
// -----------------------------------------------------------------------------
class SearchIndexerService
{
public:
    SearchIndexerService(std::shared_ptr<repository::IPostRepository> repo,
                         std::unique_ptr<infrastructure::ISearchEngineClient> client,
                         std::size_t                                       worker_count = std::thread::hardware_concurrency())
        : repo_{std::move(repo)}, client_{std::move(client)}, active_{true}
    {
        if (!repo_ || !client_) { throw std::invalid_argument("Null dependencies passed to SearchIndexerService"); }

        for (std::size_t i = 0; i < std::max<std::size_t>(1, worker_count); ++i)
        {
            workers_.emplace_back(&SearchIndexerService::worker_loop, this);
        }
    }

    ~SearchIndexerService()
    {
        shutdown();
    }

    // Disallow copying
    SearchIndexerService(const SearchIndexerService&)            = delete;
    SearchIndexerService& operator=(const SearchIndexerService&) = delete;

    // Schedule a post to be (re)indexed asynchronously
    void enqueue_index(std::uint64_t post_id)
    {
        task_queue_.push([this, post_id] { index_post(post_id); });
    }

    // Schedule a post to be removed from index
    void enqueue_remove(std::uint64_t post_id)
    {
        task_queue_.push([this, post_id] { client_->remove_document(post_id); });
    }

    // Graceful shutdown
    void shutdown()
    {
        bool expected = true;
        if (!active_.compare_exchange_strong(expected, false)) { return; } // already shut down

        task_queue_.stop();
        for (auto& t : workers_) { if (t.joinable()) t.join(); }
    }

private:
    // Worker thread mainloop
    void worker_loop()
    {
        try
        {
            while (active_)
            {
                TaskQueue::Task t;
                try
                {
                    task_queue_.wait_and_pop(t);
                }
                catch (const std::runtime_error&)
                {
                    // queue stopped
                    break;
                }
                if (t) { t(); }
            }
        }
        catch (const std::exception& ex)
        {
            std::cerr << "[SearchIndexerService] Worker terminated: " << ex.what() << '\n';
        }
    }

    // Actual indexing logic with retry
    void index_post(std::uint64_t post_id)
    {
        constexpr std::size_t kMaxRetries = 4;
        for (std::size_t attempt = 0; attempt <= kMaxRetries; ++attempt)
        {
            try
            {
                auto opt_post = repo_->find_by_id(post_id);
                if (!opt_post)
                {
                    std::cerr << "[SearchIndexerService] Post#" << post_id << " not found.\n";
                    return;
                }

                const auto& post = *opt_post;
                if (post.empty())
                {
                    std::cerr << "[SearchIndexerService] Post#" << post_id << " empty – skipping\n";
                    return;
                }

                infrastructure::SearchDocument doc{
                    post.id,
                    post.title,
                    make_excerpt(post.body),
                    intraledger::common::make_iso_timestamp(post.updated_at),
                };

                client_->upsert_document(doc);
                return; // success
            }
            catch (const std::exception& ex)
            {
                std::cerr << "[SearchIndexerService] Attempt " << attempt + 1 << " failed for Post#"
                          << post_id << ": " << ex.what() << '\n';

                if (attempt == kMaxRetries) { std::cerr << "[SearchIndexerService] Giving up on Post#" << post_id << '\n'; }
                else
                {
                    backoff(attempt);
                }
            }
        }
    }

    // Utility: generate an excerpt from HTML/markdown body
    static std::string make_excerpt(const std::string& body, std::size_t max_len = 200)
    {
        // VERY naive implementation – strips everything after max_len characters
        if (body.size() <= max_len) { return body; }
        auto excerpt = body.substr(0, max_len);
        excerpt.append("…");
        return excerpt;
    }

private:
    std::shared_ptr<repository::IPostRepository>     repo_;
    std::unique_ptr<infrastructure::ISearchEngineClient> client_;
    TaskQueue                                        task_queue_;
    std::vector<std::thread>                         workers_;
    std::atomic<bool>                                active_;
};

// -----------------------------------------------------------------------------
// Convenience factory that wires the default components together
// -----------------------------------------------------------------------------
inline std::unique_ptr<SearchIndexerService> make_default_indexer_service()
{
    auto repo   = std::make_shared<repository::MemoryPostRepository>();
    auto client = std::make_unique<infrastructure::ConsoleSearchClient>();

    // Seed repository with two fake posts
    domain::Post p1{1, "Hello World", "This is the first blog post ever…", std::chrono::system_clock::now()};
    domain::Post p2{2, "Enterprise Blogging", "Detailed guide on scaling corporate blogs…", std::chrono::system_clock::now()};
    static_cast<repository::MemoryPostRepository*>(repo.get())->add(std::move(p1));
    static_cast<repository::MemoryPostRepository*>(repo.get())->add(std::move(p2));

    return std::make_unique<SearchIndexerService>(repo, std::move(client));
}

} // namespace intraledger::service

// -----------------------------------------------------------------------------
// Self-test (will only compile into binary when this TU is built directly)
// -----------------------------------------------------------------------------
#ifdef INTRALEDGER_BUILD_STANDALONE
int main()
{
    using namespace intraledger::service;

    auto indexer = make_default_indexer_service();
    indexer->enqueue_index(1);
    indexer->enqueue_index(2);
    indexer->enqueue_remove(42);

    std::this_thread::sleep_for(std::chrono::seconds(1)); // wait for async work
    indexer->shutdown();
    return 0;
}
#endif