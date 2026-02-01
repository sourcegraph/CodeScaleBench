```cpp
/**
 *  IntraLedger BlogSuite
 *  File:    src/module_20.cpp
 *  Project: web_blog
 *
 *  Description:
 *      SearchIndexService and SearchReindexJob implementation.
 *      These components keep the full-text search index in-sync with
 *      persisted domain entities (articles, pages, comments, etc.).
 *
 *  The service is exposed through the service locator and safely used
 *  by write-side use-cases (ArticleService, CommentService) while the
 *  asynchronous job can be queued by administrators or automatically
 *  after large data migrations.
 *
 *  NOTE:
 *      This file purposefully references several project-local headers
 *      (core/*, repository/*, service/* …). In the full code-base these
 *      headers do exist. Replace or adapt them to your environment if
 *      you compile this file in isolation.
 */

#include <chrono>
#include <exception>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>

#include "core/ServiceLocator.hpp"
#include "core/StopToken.hpp"
#include "core/exceptions/ConfigurationError.hpp"
#include "jobs/JobDispatcher.hpp"
#include "jobs/JobInterface.hpp"
#include "repository/ArticleRepository.hpp"
#include "search/SearchBackend.hpp"

namespace IntraLedger::BlogSuite::Search {

/* --------------------------------------------------------------------- */
/*  Small utility: scoped time-tracker for instrumentation                */
/* --------------------------------------------------------------------- */
class ScopedPerfTimer
{
public:
    explicit ScopedPerfTimer(std::string operation,
                             std::shared_ptr<spdlog::logger> logger =
                                 spdlog::default_logger())
        : _operation(std::move(operation))
        , _logger(std::move(logger))
        , _start(std::chrono::steady_clock::now())
    { }

    // non-copyable
    ScopedPerfTimer(const ScopedPerfTimer&)            = delete;
    ScopedPerfTimer& operator=(const ScopedPerfTimer&) = delete;

    // movable
    ScopedPerfTimer(ScopedPerfTimer&&)            = default;
    ScopedPerfTimer& operator=(ScopedPerfTimer&&) = default;

    ~ScopedPerfTimer()
    {
        using namespace std::chrono;
        const auto elapsed = duration_cast<milliseconds>(steady_clock::now() - _start).count();
        _logger->debug("[perf] {} took {}ms", _operation, elapsed);
    }

private:
    std::string                     _operation;
    std::shared_ptr<spdlog::logger> _logger;
    std::chrono::steady_clock::time_point _start;
};

/* --------------------------------------------------------------------- */
/*  SearchIndexService                                                   */
/* --------------------------------------------------------------------- */
/**
 * SearchIndexService encapsulates interactions with the configured
 * search backend (e.g. MeiliSearch, ElasticSearch, or SQLite FTS5)
 * and offers coarse-grained operations required by the business layer.
 */
class SearchIndexService final
{
public:
    // Acquire via ServiceLocator
    static std::shared_ptr<SearchIndexService> instance()
    {
        return ServiceLocator::instance()
            .resolveShared<SearchIndexService>();
    }

    explicit SearchIndexService(std::shared_ptr<Search::SearchBackend> backend,
                                std::shared_ptr<ArticleRepository>     articleRepository)
        : _backend(std::move(backend))
        , _articleRepository(std::move(articleRepository))
    {
        if (!_backend || !_articleRepository)
            throw core::exceptions::ConfigurationError(
                "SearchIndexService requires valid dependencies.");
    }

    /**
     * Adds or updates a single article within the search index.
     * The call is synchronous; for batch-inserts use rebuildIndex()
     * or queue a SearchReindexJob.
     */
    void upsertArticle(const domain::Article& article)
    {
        std::shared_lock guard(_mutex);
        try
        {
            _backend->upsertDocument(article.id(),
                                     buildDocument(article));
            spdlog::info("Indexed article [{}] ‑ {}", article.id(), article.title());
        }
        catch (const std::exception& ex)
        {
            spdlog::error("Unable to index article [{}]: {}", article.id(), ex.what());
            throw; // Let callers decide if failure is fatal.
        }
    }

    /**
     * Removes a deleted article from the index.
     */
    void removeArticle(std::uint64_t articleId)
    {
        std::shared_lock guard(_mutex);
        try
        {
            _backend->deleteDocument(articleId);
            spdlog::info("Removed article [{}] from search index", articleId);
        }
        catch (const std::exception& ex)
        {
            spdlog::warn("Failed to delete article [{}] from index: {}", articleId, ex.what());
        }
    }

    /**
     * Rebuilds the entire search index. The public method only delegates
     * to the private implementation guarded by an exclusive lock.
     *
     * Optionally accepts a StopToken so that long-running indexing
     * operations can be aborted (e.g. shutting down).
     */
    void rebuildIndex(const core::StopToken& stopToken = core::StopToken{})
    {
        ScopedPerfTimer timer("SearchIndexService::rebuildIndex");

        std::unique_lock guard(_mutex); // exclusive – no concurrent writes
        spdlog::info("Starting full-text search index rebuild.");

        try
        {
            _backend->clearAll();
            std::uint64_t batchSize = 250;
            std::uint64_t offset    = 0;

            while (!stopToken.stopRequested())
            {
                auto batch = _articleRepository->fetchPublished(offset, batchSize);
                if (batch.empty()) break;

                std::vector<Search::Document> docs;
                docs.reserve(batch.size());

                for (const auto& article : batch)
                    docs.emplace_back(buildDocument(article));

                _backend->bulkUpsert(docs);
                spdlog::info("Indexed {} / ? articles …", offset + batch.size());

                offset += batch.size();
            }

            spdlog::info("Search index rebuild completed.");
        }
        catch (const std::exception& ex)
        {
            spdlog::critical("Search index rebuild FAILED: {}", ex.what());
            throw;
        }
    }

private:
    /* ----------------------------------------------------------------- */
    /* Helper methods                                                    */
    /* ----------------------------------------------------------------- */
    static Search::Document buildDocument(const domain::Article& article)
    {
        Search::Document doc;
        doc.id    = article.id();
        doc.title = article.title();
        doc.body  = article.body();
        doc.tags  = article.tags();
        doc.date  = article.publishedAt();
        return doc;
    }

    /* ----------------------------------------------------------------- */
    /* Member variables                                                  */
    /* ----------------------------------------------------------------- */
    std::shared_ptr<Search::SearchBackend> _backend;
    std::shared_ptr<ArticleRepository>     _articleRepository;

    // For concurrency control (shared = read, unique = write).
    mutable std::shared_mutex              _mutex;
};

/* --------------------------------------------------------------------- */
/*  SearchReindexJob                                                     */
/* --------------------------------------------------------------------- */
/**
 * A long-running background job that rebuilds the entire search index.
 * It reports progress through the configured logger and respects a
 * StopToken so that the job can be cancelled if the application shuts
 * down or the administrator explicitly aborts the task.
 */
class SearchReindexJob final : public jobs::JobInterface
{
public:
    explicit SearchReindexJob(core::StopToken token = core::StopToken{})
        : _stopToken(std::move(token))
    { }

    std::string name() const noexcept override { return "search.index.rebuild"; }

    /**
     * Execute the job.
     * Throws on unrecoverable failure so the JobDispatcher can decide
     * whether to retry or mark as failed.
     */
    void run() override
    {
        auto service = SearchIndexService::instance();
        if (!service)
        {
            throw std::runtime_error(
                "SearchIndexService unavailable. Cannot rebuild search index.");
        }

        spdlog::info("[job:{}] started", name());
        service->rebuildIndex(_stopToken);
        spdlog::info("[job:{}] finished", name());
    }

    core::StopToken stopToken() noexcept override { return _stopToken; }

private:
    core::StopToken _stopToken;
};

/* --------------------------------------------------------------------- */
/*  Service Registration                                                 */
/* --------------------------------------------------------------------- */

/**
 * This anonymous namespace performs early registration of
 * SearchIndexService and binds our job to the dispatcher once this TU
 * is loaded. In the production code-base, the ServiceLocator is usually
 * configured at application start-up; however, the following code path
 * ensures that CLI sub-commands or integration tests that only link
 * this module still have a usable default configuration.
 */
namespace
{
    struct ModuleInit
    {
        ModuleInit()
        {
            try
            {
                // Register default SearchBackend implementation if not provided.
                if (!ServiceLocator::instance().contains<Search::SearchBackend>())
                {
                    auto backend = Search::SearchBackend::createFromEnvironment();
                    ServiceLocator::instance().bindShared<Search::SearchBackend>(backend);
                }

                // Register ArticleRepository (optional in minimal env).
                if (!ServiceLocator::instance().contains<ArticleRepository>())
                {
                    auto repo = std::make_shared<ArticleRepository>(
                        RepositoryConfig::fromEnv());
                    ServiceLocator::instance().bindShared<ArticleRepository>(repo);
                }

                // Finally register SearchIndexService.
                if (!ServiceLocator::instance().contains<SearchIndexService>())
                {
                    auto svc = std::make_shared<SearchIndexService>(
                        ServiceLocator::instance().resolveShared<Search::SearchBackend>(),
                        ServiceLocator::instance().resolveShared<ArticleRepository>());
                    ServiceLocator::instance().bindShared<SearchIndexService>(svc);
                }

                // Register the job with the global dispatcher.
                jobs::JobDispatcher::instance()
                    .registerJobFactory("search.index.rebuild",
                                        [] { return std::make_unique<SearchReindexJob>(); });

                spdlog::debug("Search module initialised.");
            }
            catch (const std::exception& ex)
            {
                spdlog::critical("Failed to initialise search module: {}", ex.what());
                // Fail-fast: configuration errors at this stage are unrecoverable.
                std::terminate();
            }
        }
    } _autoInit;
} // namespace

} // namespace IntraLedger::BlogSuite::Search
```