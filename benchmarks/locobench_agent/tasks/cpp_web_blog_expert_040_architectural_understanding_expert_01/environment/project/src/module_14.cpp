```cpp
/**
 *  IntraLedger BlogSuite – Search Indexer Module
 *  ==================================================
 *  File:        src/module_14.cpp
 *  Copyright:   (c) 2024 IntraLedger
 *  License:     Proprietary – All Rights Reserved
 *
 *  Summary:
 *  --------
 *  Background worker that maintains the full-text search index for
 *  blog articles.  Whenever an article is created, updated or deleted
 *  the service receives a signal through `scheduleIndexUpdate()` and
 *  performs the heavy lifting in an isolated thread so that the web
 *  request/transaction can finish quickly.
 *
 *  Design notes:
 *  -------------
 *  • Implements a very small in-file task queue (single-producer/
 *    multi-consumer safe) to avoid an external dependency.
 *  • Abstracts the data-source through `IArticleRepository` so that
 *    either MariaDB or PostgreSQL can be used transparently.
 *  • Abstracts the destination search engine through `ISearchBackend`,
 *    allowing pluggable adapters (e.g. SQLite FTS5, ElasticSearch, etc.).
 *  • Performs graceful shutdown using RAII and joins the worker thread
 *    in the destructor.
 *
 *  Thread-safety:
 *  --------------
 *  – `SearchIndexer` is internally synchronized and may be called from
 *    multiple threads.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace intraledger::blogsuite::search {

// -----------------------------------------------------------------------------
// Simple thread-safe logger helper
// -----------------------------------------------------------------------------
enum class LogLevel { TRACE, INFO, WARN, ERROR };

class Logger
{
public:
    static void log(LogLevel level, const std::string& msg)
    {
        static std::mutex mtx;
        std::lock_guard<std::mutex> lg(mtx);

        const char* lvlStr = nullptr;
        switch (level)
        {
        case LogLevel::TRACE: lvlStr = "TRACE"; break;
        case LogLevel::INFO:  lvlStr = "INFO "; break;
        case LogLevel::WARN:  lvlStr = "WARN "; break;
        case LogLevel::ERROR: lvlStr = "ERROR"; break;
        default:              lvlStr = "UNK  "; break;
        }

        std::cerr << "[" << lvlStr << "] "
                  << std::chrono::duration_cast<std::chrono::milliseconds>(
                         std::chrono::system_clock::now().time_since_epoch())
                         .count()
                  << "  " << msg << '\n';
    }
};

// -----------------------------------------------------------------------------
// Domain entities & repository interface
// -----------------------------------------------------------------------------
struct Article
{
    std::int64_t                               id      = 0;
    std::string                                title;
    std::string                                body;
    std::string                                language;
    std::chrono::system_clock::time_point      updatedAt;
};

class IArticleRepository
{
public:
    virtual ~IArticleRepository() = default;

    // Retrieve single article (throws if not found)
    virtual Article findById(std::int64_t id) const = 0;

    // Retrieve all articles updated after a given time point
    virtual std::vector<Article>
    fetchUpdatedAfter(const std::chrono::system_clock::time_point& ts) const = 0;
};

// -----------------------------------------------------------------------------
// Search backend abstraction
// -----------------------------------------------------------------------------
class ISearchBackend
{
public:
    virtual ~ISearchBackend() = default;

    // Index or update one article
    virtual void index(const Article& a) = 0;

    // Remove article from index
    virtual void remove(std::int64_t id) = 0;

    // Flush buffered operations (if backend supports batching)
    virtual void flush() = 0;
};

// -----------------------------------------------------------------------------
// Concrete stub implementations (for demo / unit tests)
// -----------------------------------------------------------------------------
class InMemoryArticleRepository final : public IArticleRepository
{
public:
    explicit InMemoryArticleRepository(std::vector<Article> data)
        : data_{std::move(data)}
    {}

    Article findById(std::int64_t id) const override
    {
        auto it = std::find_if(data_.begin(), data_.end(),
                               [&](const Article& a) { return a.id == id; });
        if (it == data_.end())
            throw std::runtime_error("Article not found");
        return *it;
    }

    std::vector<Article>
    fetchUpdatedAfter(const std::chrono::system_clock::time_point& ts) const
        override
    {
        std::vector<Article> res;
        std::copy_if(data_.begin(), data_.end(), std::back_inserter(res),
                     [&](const Article& a) { return a.updatedAt >= ts; });
        return res;
    }

private:
    std::vector<Article> data_;
};

class SimpleSearchBackend final : public ISearchBackend
{
public:
    void index(const Article& a) override
    {
        std::stringstream ss;
        ss << "Indexed article #" << a.id << " (" << a.title << ")";
        Logger::log(LogLevel::TRACE, ss.str());
        store_[a.id] = a.title; // Simplified
    }

    void remove(std::int64_t id) override
    {
        store_.erase(id);
        Logger::log(LogLevel::TRACE, "Removed article #" + std::to_string(id));
    }

    void flush() override
    {
        Logger::log(LogLevel::TRACE, "Flush called (" +
                                         std::to_string(store_.size()) +
                                         " entries cached)");
    }

private:
    std::unordered_map<std::int64_t, std::string> store_;
};

// -----------------------------------------------------------------------------
// SearchIndexer – public façade
// -----------------------------------------------------------------------------
class SearchIndexer
{
public:
    SearchIndexer(std::shared_ptr<IArticleRepository> repo,
                  std::shared_ptr<ISearchBackend>   backend)
        : repo_{std::move(repo)}
        , backend_{std::move(backend)}
        , worker_{&SearchIndexer::workerLoop, this}
    {}

    ~SearchIndexer()
    {
        {
            std::lock_guard<std::mutex> lg(mtx_);
            shuttingDown_ = true;
        }
        cv_.notify_all();
        if (worker_.joinable())
            worker_.join();
    }

    // ---------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------
    void scheduleIndexUpdate(std::int64_t articleId)
    {
        enqueue(Operation{Type::UPSERT, articleId});
    }

    void scheduleIndexDelete(std::int64_t articleId)
    {
        enqueue(Operation{Type::DELETE, articleId});
    }

    // Force immediate flush (e.g., at transaction commit)
    void flush()
    {
        enqueue(Operation{Type::FLUSH, std::nullopt});
    }

private:
    // ---------------------------------------------------------------------
    // Internal types
    // ---------------------------------------------------------------------
    enum class Type { UPSERT, DELETE, FLUSH };

    struct Operation
    {
        Type                         type;
        std::optional<std::int64_t>  articleId;
    };

    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------
    void enqueue(Operation op)
    {
        {
            std::lock_guard<std::mutex> lg(mtx_);
            queue_.push(std::move(op));
        }
        cv_.notify_one();
    }

    void workerLoop()
    {
        Logger::log(LogLevel::INFO, "SearchIndexer worker started");

        try
        {
            while (true)
            {
                Operation op;

                {
                    std::unique_lock<std::mutex> ulk(mtx_);
                    cv_.wait(ulk, [&] {
                        return shuttingDown_ || !queue_.empty();
                    });

                    if (shuttingDown_ && queue_.empty())
                        break;

                    op = std::move(queue_.front());
                    queue_.pop();
                }

                processOperation(op);
            }

            // Final flush to guarantee durability
            backend_->flush();
            Logger::log(LogLevel::INFO, "SearchIndexer worker stopped (clean)");
        }
        catch (const std::exception& ex)
        {
            Logger::log(LogLevel::ERROR,
                        std::string("Indexer worker aborted: ") + ex.what());
        }
        catch (...)
        {
            Logger::log(LogLevel::ERROR, "Indexer worker aborted: <unknown>");
        }
    }

    void processOperation(const Operation& op)
    {
        switch (op.type)
        {
        case Type::UPSERT:
            handleUpsert(op.articleId.value());
            break;
        case Type::DELETE:
            backend_->remove(op.articleId.value());
            break;
        case Type::FLUSH:
            backend_->flush();
            break;
        }
    }

    void handleUpsert(std::int64_t articleId)
    {
        try
        {
            const Article article = repo_->findById(articleId);
            backend_->index(article);
        }
        catch (const std::exception& ex)
        {
            Logger::log(LogLevel::WARN,
                        "Failed to index article #" + std::to_string(articleId) +
                            ": " + ex.what());
        }
    }

    // ---------------------------------------------------------------------
    // Data members
    // ---------------------------------------------------------------------
    std::shared_ptr<IArticleRepository> repo_;
    std::shared_ptr<ISearchBackend>     backend_;

    std::queue<Operation>               queue_;
    std::mutex                          mtx_;
    std::condition_variable             cv_;
    std::atomic<bool>                   shuttingDown_{false};
    std::thread                         worker_;
};

// -----------------------------------------------------------------------------
// Demo / self-test (compiled out in production)
// -----------------------------------------------------------------------------
#ifdef INTRALEDGER_SEARCH_INDEXER_DEMO
int main()
{
    using namespace std::chrono_literals;
    auto now   = std::chrono::system_clock::now();
    auto repo  = std::make_shared<InMemoryArticleRepository>(
        std::vector<Article>{
            {1, "Hello World",  "Body1", "en", now},
            {2, "Hallo Welt",   "Body2", "de", now},
            {3, "Bonjour Monde","Body3", "fr", now},
        });

    auto backend = std::make_shared<SimpleSearchBackend>();
    SearchIndexer indexer{repo, backend};

    indexer.scheduleIndexUpdate(1);
    indexer.scheduleIndexUpdate(2);
    indexer.scheduleIndexDelete(3);
    indexer.flush();

    std::this_thread::sleep_for(500ms); // give worker some time
}
#endif

} // namespace intraledger::blogsuite::search
```