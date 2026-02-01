```cpp
/**
 *  module_35.cpp
 *  IntraLedger BlogSuite (web_blog)
 *
 *  Description:
 *  -------------
 *  Search-layer service responsible for building and maintaining the full-text
 *  search index for blog articles. This source file provides a production-grade
 *  implementation that plays well with the platform’s asynchronous job engine,
 *  repository abstraction and pluggable search back-end.
 *
 *  The service listens for “article changed” domain events (created / updated /
 *  deleted) and schedules indexing jobs, while also exposing a bulk
 *  `rebuildIndex()` helper for administrators—or for disaster recovery.
 *
 *  NOTE: This module does not own the concrete implementations of the
 *  repository, dispatcher or search back-end; those are provided elsewhere in
 *  the application and injected at runtime (Dependency Injection).
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

// 3rd-party logging library (compile-time dependency; provided by the build
// system). Fallback to <iostream> if logging is disabled.
#include <spdlog/spdlog.h>

namespace intraledger::blog::domain
{

using UUID = std::string;

/**
 * Lightweight projection of the ‘Article’ aggregate used by the search service.
 * The real aggregate is considerably larger; only the required fields are
 * replicated here to avoid layering violations.
 */
struct Article
{
    UUID         id;
    std::string  title;
    std::string  body;
    std::string  language;
    std::string  author;
    std::string  slug;
    bool         published {false};

    bool isSearchable() const noexcept
    {
        return published && !body.empty();
    }
};

} // namespace intraledger::blog::domain

// -----------------------------------------------------------------------------
// Repository & Backend Interfaces.
// -----------------------------------------------------------------------------
namespace intraledger::blog::repo
{

/**
 * Generic abstraction for data-access operations over the Article table.
 *
 * Implementations live in the data-access layer and are instantiated via the
 * dependency-injection container.
 */
class ArticleRepository
{
public:
    virtual ~ArticleRepository() = default;

    /**
     * Fetch a contiguous slice of articles ordered by primary key.
     * @param offset Row offset (zero-based).
     * @param limit  Maximum number of rows to retrieve.
     */
    [[nodiscard]]
    virtual std::vector<domain::Article>
    fetchArticles(std::size_t offset, std::size_t limit)                            = 0;

    /**
     * Find a single article by its UUID.
     * @return Optional article—empty if not found.
     */
    [[nodiscard]]
    virtual std::optional<domain::Article>
    findById(const domain::UUID &id)                                                = 0;
};

} // namespace intraledger::blog::repo

namespace intraledger::blog::search
{

/**
 * Interface representing the underlying full-text search storage—Elasticsearch,
 * Meilisearch, Postgres GIN, Sphinx, etc.
 */
class SearchBackend
{
public:
    virtual ~SearchBackend() = default;

    virtual void indexDocument(const domain::Article &article)                     = 0;
    virtual void removeDocument(const domain::UUID &id)                            = 0;
};

} // namespace intraledger::blog::search

// -----------------------------------------------------------------------------
// Job Dispatching (asynchronous runtime).
// -----------------------------------------------------------------------------
namespace intraledger::blog::job
{

/**
 * Simple callable wrapper; real implementation may include retry policy,
 * persistence, metrics, etc.
 */
using JobHandle = std::function<void()>;

/**
 * Thread-safe in-memory job dispatcher that accepts lightweight tasks. In
 * production the system uses a more sophisticated queue that can survive
 * process restarts, but this implementation is suitable for runtime
 * composition or testing.
 */
class JobDispatcher
{
public:
    JobDispatcher()
        : running_{true}, worker_{[this] { workerLoop(); }} {}

    ~JobDispatcher()
    {
        {
            std::unique_lock l{mutex_};
            running_ = false;
            cond_.notify_all();
        }
        if (worker_.joinable())
            worker_.join();
    }

    void submit(JobHandle job)
    {
        {
            std::unique_lock l{mutex_};
            queue_.emplace(std::move(job));
        }
        cond_.notify_one();
    }

private:
    void workerLoop()
    {
        while (true)
        {
            JobHandle job;
            {
                std::unique_lock l{mutex_};
                cond_.wait(l, [this] { return !queue_.empty() || !running_; });

                if (!running_ && queue_.empty())
                    break;

                job = std::move(queue_.front());
                queue_.pop();
            }

            try
            {
                job();
            }
            catch (const std::exception &ex)
            {
                spdlog::error("[JobDispatcher] job failed: {}", ex.what());
            }
            catch (...)
            {
                spdlog::error("[JobDispatcher] job failed with unknown error");
            }
        }
    }

    std::atomic_bool         running_;
    std::thread              worker_;
    std::queue<JobHandle>    queue_;
    std::mutex               mutex_;
    std::condition_variable  cond_;
};

} // namespace intraledger::blog::job

// -----------------------------------------------------------------------------
// Utility (text sanitisation / tokenisation).
// -----------------------------------------------------------------------------
namespace intraledger::blog::util
{

/**
 * Very naive HTML tag stripper. A real implementation would use a proper HTML
 * parser (e.g., Gumbo) but this is sufficient for demonstration purposes.
 */
[[nodiscard]]
std::string stripHtml(std::string_view input)
{
    std::string output;
    output.reserve(input.size());

    bool inTag = false;
    for (char c : input)
    {
        if (c == '<')
        {
            inTag = true;
            continue;
        }
        if (c == '>')
        {
            inTag = false;
            continue;
        }
        if (!inTag)
            output.push_back(c);
    }

    return output;
}

/**
 * Basic word tokenizer that lowercases and splits on whitespace / punctuation.
 */
[[nodiscard]]
std::vector<std::string> tokenize(std::string_view text)
{
    std::vector<std::string> tokens;
    std::string current;

    auto flushToken = [&]() {
        if (!current.empty())
        {
            std::transform(current.begin(), current.end(), current.begin(),
                           [](unsigned char c) { return std::tolower(c); });
            tokens.emplace_back(std::move(current));
            current.clear();
        }
    };

    for (char c : text)
    {
        if (std::isalnum(static_cast<unsigned char>(c)))
        {
            current.push_back(c);
        }
        else
        {
            flushToken();
        }
    }
    flushToken();
    return tokens;
}

} // namespace intraledger::blog::util

// -----------------------------------------------------------------------------
// Full-Text Search Service.
// -----------------------------------------------------------------------------
namespace intraledger::blog::search
{

class FullTextSearchService
{
public:
    FullTextSearchService(std::shared_ptr<repo::ArticleRepository> articleRepo,
                          std::shared_ptr<SearchBackend>           backend,
                          std::shared_ptr<job::JobDispatcher>      dispatcher)
        : repo_{std::move(articleRepo)}
        , backend_{std::move(backend)}
        , dispatcher_{std::move(dispatcher)}
    {
        if (!repo_ || !backend_ || !dispatcher_)
            throw std::invalid_argument(
                "FullTextSearchService received null dependency");
    }

    /**
     * Index or re-index a single article. If the article is not searchable, the
     * previously indexed instance (if any) will be deleted.
     */
    void onArticleChanged(const domain::UUID &id)
    {
        dispatcher_->submit([self = shared_from_this(), id]() {
            self->processArticleChange(id);
        });
    }

    /**
     * Remove an article from the search index (e.g., author deleted).
     */
    void onArticleDeleted(const domain::UUID &id)
    {
        dispatcher_->submit([self = shared_from_this(), id]() {
            try
            {
                self->backend_->removeDocument(id);
                spdlog::info("[SearchService] removed article {} from index", id);
            }
            catch (const std::exception &ex)
            {
                spdlog::error("[SearchService] failed to remove article {}: {}",
                              id, ex.what());
            }
        });
    }

    /**
     * Rebuild the complete index in batches. Long-running operation executed in
     * the background and progress is reported through logging.
     *
     * @param pause Optional pause between batches to reduce DB load.
     */
    void rebuildIndex(std::optional<std::chrono::milliseconds> pause =
                          std::chrono::milliseconds{50})
    {
        dispatcher_->submit([self = shared_from_this(), pause]() {
            constexpr std::size_t kBatchSize = 256;
            std::size_t           offset     = 0;
            std::size_t           total      = 0;

            spdlog::info("[SearchService] Starting full index rebuild");

            while (true)
            {
                auto articles = self->repo_->fetchArticles(offset, kBatchSize);
                if (articles.empty())
                    break;

                for (auto &article : articles)
                {
                    try
                    {
                        if (article.isSearchable())
                            self->backend_->indexDocument(article);
                        else
                            self->backend_->removeDocument(article.id);
                    }
                    catch (const std::exception &ex)
                    {
                        spdlog::warn(
                            "[SearchService] Skipping article {}: {}", article.id,
                            ex.what());
                    }
                    ++total;
                }

                offset += articles.size();

                if (pause && *pause > std::chrono::milliseconds::zero())
                    std::this_thread::sleep_for(*pause);
            }
            spdlog::info("[SearchService] Rebuild finished. {} articles processed.",
                         total);
        });
    }

private:
    void processArticleChange(const domain::UUID &id)
    {
        auto optArticle = repo_->findById(id);
        if (!optArticle)
        {
            spdlog::warn("[SearchService] article {} not found, deleting from index",
                         id);
            backend_->removeDocument(id);
            return;
        }

        const auto &article = *optArticle;
        try
        {
            if (article.isSearchable())
            {
                backend_->indexDocument(article);
                spdlog::info("[SearchService] indexed article {}", id);
            }
            else
            {
                backend_->removeDocument(id);
                spdlog::info("[SearchService] removed unpublished article {}", id);
            }
        }
        catch (const std::exception &ex)
        {
            spdlog::error("[SearchService] failed to index article {}: {}", id,
                          ex.what());
        }
    }

    // Enable shared_from_this to keep the service alive until async jobs finish.
    std::shared_ptr<FullTextSearchService> shared_from_this()
    {
        return std::shared_ptr<FullTextSearchService>(this, [](FullTextSearchService*){});
    }

    std::shared_ptr<repo::ArticleRepository> repo_;
    std::shared_ptr<SearchBackend>           backend_;
    std::shared_ptr<job::JobDispatcher>      dispatcher_;
};

} // namespace intraledger::blog::search

// -----------------------------------------------------------------------------
// Mock back-end implementations for standalone unit testing
// (these would normally live in separate test files).
// -----------------------------------------------------------------------------
#ifdef BLOGSUITE_SEARCH_SERVICE_SELFTEST

#include <iostream>

namespace intraledger::blog::search
{

class InMemoryBackend : public SearchBackend
{
public:
    void indexDocument(const domain::Article &article) override
    {
        index_[article.id] = util::stripHtml(article.title + " " + article.body);
        spdlog::debug("[InMemoryBackend] indexed {}", article.id);
    }

    void removeDocument(const domain::UUID &id) override
    {
        index_.erase(id);
        spdlog::debug("[InMemoryBackend] removed {}", id);
    }

    [[nodiscard]]
    std::size_t size() const { return index_.size(); }

private:
    std::unordered_map<domain::UUID, std::string> index_;
};

class DummyRepo : public repo::ArticleRepository
{
public:
    DummyRepo()
    {
        for (int i = 1; i <= 1000; ++i)
        {
            domain::Article article;
            article.id        = std::to_string(i);
            article.title     = "Title " + std::to_string(i);
            article.body      = "<p>Lorem ipsum dolor " + std::to_string(i) + "</p>";
            article.published = (i % 10 != 0); // some unpublished
            articles_.push_back(std::move(article));
        }
    }

    std::vector<domain::Article>
    fetchArticles(std::size_t offset, std::size_t limit) override
    {
        auto begin = articles_.cbegin() + static_cast<ptrdiff_t>(offset);
        auto end   = begin + std::min(limit, articles_.size() - offset);
        return {begin, end};
    }

    std::optional<domain::Article>
    findById(const domain::UUID &id) override
    {
        auto it = std::find_if(articles_.begin(), articles_.end(),
                               [&](const auto &a) { return a.id == id; });
        if (it != articles_.end())
            return *it;
        return std::nullopt;
    }

private:
    std::vector<domain::Article> articles_;
};

void selfTest()
{
    auto repo       = std::make_shared<DummyRepo>();
    auto backend    = std::make_shared<InMemoryBackend>();
    auto dispatcher = std::make_shared<job::JobDispatcher>();

    auto service =
        std::make_shared<FullTextSearchService>(repo, backend, dispatcher);

    // Rebuild entire index.
    service->rebuildIndex(std::nullopt);

    // Give worker loop some time to finish.
    std::this_thread::sleep_for(std::chrono::seconds{2});
    std::cout << "Index contains " << backend->size() << " documents\n";
}

} // namespace intraledger::blog::search

int main()
{
    intraledger::blog::search::selfTest();
}

#endif // BLOGSUITE_SEARCH_SERVICE_SELFTEST
```
