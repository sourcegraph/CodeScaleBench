/*
 * ============================================================================
 * IntraLedger BlogSuite – module_24.cpp
 * ----------------------------------------------------------------------------
 *  Search Module : PostSearchService
 *
 *  Responsible for:
 *      • Indexing BlogPost domain objects into the configured search backend.
 *      • Executing full-text search queries with RBAC-aware filtering.
 *      • Scheduling asynchronous (re)index jobs through the JobQueue.
 *      • Providing lightweight in-memory analytics for popular queries.
 *
 *  This implementation purposefully depends only on public interfaces defined
 *  elsewhere in the code-base.  It therefore integrates cleanly inside the
 *  larger monolith while keeping compilation units independent.
 *
 *  Copyright (c) 2024  IntraLedger
 * ============================================================================
 */

#include <algorithm>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// Third-party dependencies
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

// Project dependencies (interfaces; implemented elsewhere)
#include "core/Config.hpp"
#include "core/auth/UserContext.hpp"
#include "core/errors/Error.hpp"
#include "jobs/IJobQueue.hpp"
#include "repository/BlogPostRepository.hpp"
#include "search/ISearchBackend.hpp"
#include "search/SearchResult.hpp"

using json = nlohmann::json;

namespace intraledger::blogsuite::search {

/*───────────────────────────────────────────────────────────────────────────*/
/*  Helper: RAII scope timer for metric instrumentation.                     */
/*───────────────────────────────────────────────────────────────────────────*/
class ScopedMetricTimer final
{
public:
    explicit ScopedMetricTimer(std::string_view metricName) noexcept
        : m_metricName(metricName),
          m_start(std::chrono::steady_clock::now())
    {}

    // Not copyable / movable
    ScopedMetricTimer(const ScopedMetricTimer&) = delete;
    ScopedMetricTimer& operator=(const ScopedMetricTimer&) = delete;
    ScopedMetricTimer(ScopedMetricTimer&&)            = delete;
    ScopedMetricTimer& operator=(ScopedMetricTimer&&) = delete;

    ~ScopedMetricTimer() noexcept
    {
        using namespace std::chrono;
        const auto duration = duration_cast<milliseconds>(
                                  steady_clock::now() - m_start)
                                  .count();

        // Push to central metrics collector (here we just log)
        spdlog::trace("[METRIC] {} = {} ms", m_metricName, duration);
    }

private:
    std::string m_metricName;
    std::chrono::steady_clock::time_point m_start;
};

/*───────────────────────────────────────────────────────────────────────────*/
/*  PostSearchService                                                       */
/*───────────────────────────────────────────────────────────────────────────*/
class PostSearchService final : public std::enable_shared_from_this<PostSearchService>
{
public:
    struct Options
    {
        std::chrono::seconds  reindexInterval      = std::chrono::hours(6);
        std::size_t           popularQueryCapacity = 500;
        std::size_t           defaultLimit         = 20;
    };

    PostSearchService(std::shared_ptr<repository::IBlogPostRepository> repository,
                      std::shared_ptr<ISearchBackend>                  backend,
                      std::shared_ptr<jobs::IJobQueue>                 jobQueue,
                      Options                                          opts = {})
        : m_repository(std::move(repository)),
          m_backend(std::move(backend)),
          m_jobQueue(std::move(jobQueue)),
          m_opts(std::move(opts))
    {
        if (!m_repository || !m_backend || !m_jobQueue)
            throw std::invalid_argument("PostSearchService received null deps");

        m_lastReindex.store(std::chrono::system_clock::now() -
                            2 * m_opts.reindexInterval);

        // Schedule the first reindex after boot
        scheduleReindexAll();
    }

    ~PostSearchService() = default;

    /*───────────────────────────────────────────────────────────────────────*/
    /*  Public API                                                          */
    /*───────────────────────────────────────────────────────────────────────*/

    // Executes a full-text search across available blog posts.
    SearchResult search(std::string               query,
                        core::auth::UserContext   user,
                        std::size_t               limit = 0)
    {
        ScopedMetricTimer tmr("PostSearchService::search");

        if (query.empty())
            throw core::InvalidArgumentError("Search query must not be empty");

        limit = (limit == 0) ? m_opts.defaultLimit : limit;
        recordPopularQuery(query);

        // Build domain-specific filter
        SearchQuery sq;
        sq.text     = std::move(query);
        sq.limit    = limit;
        sq.language = user.preferredLanguage();
        sq.tags     = user.visibleTags();

        auto results = m_backend->execute(sq);

        // RBAC enforcement for premium / restricted posts
        results.items.erase(
            std::remove_if(results.items.begin(),
                           results.items.end(),
                           [&](const SearchItem& it) {
                               return !user.hasAccess(it.requiredRole);
                           }),
            results.items.end());

        return results;
    }

    // Schedules a complete reindex in the background.  If a reindex has run
    // recently, the call is ignored to avoid unnecessary load.
    void scheduleReindexAll()
    {
        const auto now = std::chrono::system_clock::now();
        const auto last = m_lastReindex.load();

        if (now - last < m_opts.reindexInterval)
        {
            spdlog::info("Skipping reindex – last run was too recent");
            return;
        }

        // Atomically update so concurrent calls do not queue duplicates
        if (m_lastReindex.compare_exchange_strong(last, now))
        {
            auto self = shared_from_this();
            m_jobQueue->enqueue(
                "search.reindex.posts",
                [self]() {
                    self->reindexAll();
                });

            spdlog::info("Reindex job enqueued");
        }
    }

private:
    /*───────────────────────────────────────────────────────────────────────*/
    /*  Internal helpers                                                    */
    /*───────────────────────────────────────────────────────────────────────*/

    void reindexAll()
    {
        ScopedMetricTimer tmr("PostSearchService::reindexAll");

        try
        {
            auto posts = m_repository->findAllPublished();
            m_backend->beginBulk();

            for (const auto& post : posts)
            {
                SearchDocument doc;
                doc.id          = std::to_string(post.id());
                doc.title       = post.title();
                doc.body        = post.markdown();
                doc.language    = post.language();
                doc.tags        = post.tags();
                doc.requiredRole = post.requiredRole();

                m_backend->index(doc);
            }

            m_backend->commitBulk();
            spdlog::info("Indexed {} posts into search backend", posts.size());
        }
        catch (const std::exception& ex)
        {
            spdlog::error("PostSearchService::reindexAll failed – {}", ex.what());
            // Mark reindex time back so we can try again soon
            m_lastReindex.store(std::chrono::system_clock::now() -
                                m_opts.reindexInterval);
        }
    }

    // Records query counts for lightweight popularity analytics.
    void recordPopularQuery(const std::string& query)
    {
        std::unique_lock lock(m_popularMutex);
        auto& count = m_popularQueries[query];
        count++;

        if (m_popularQueries.size() > m_opts.popularQueryCapacity)
        {
            // Remove least frequently used (simple O(n) pass)
            auto lfuIt = std::min_element(
                m_popularQueries.begin(), m_popularQueries.end(),
                [](const auto& a, const auto& b) { return a.second < b.second; });

            if (lfuIt != m_popularQueries.end())
                m_popularQueries.erase(lfuIt);
        }
    }

private:
    /*───────────────────────────────────────────────────────────────────────*/
    /*  Members                                                             */
    /*───────────────────────────────────────────────────────────────────────*/
    std::shared_ptr<repository::IBlogPostRepository> m_repository;
    std::shared_ptr<ISearchBackend>                  m_backend;
    std::shared_ptr<jobs::IJobQueue>                 m_jobQueue;

    Options                                          m_opts;
    std::atomic<std::chrono::system_clock::time_point>
                                                    m_lastReindex;

    std::unordered_map<std::string, std::size_t>     m_popularQueries;
    std::shared_mutex                                m_popularMutex;
};

/*───────────────────────────────────────────────────────────────────────────*/
/*  Factory function for DI container registration.                         */
/*───────────────────────────────────────────────────────────────────────────*/
std::shared_ptr<PostSearchService>
makePostSearchService(const core::Config& cfg,
                      std::shared_ptr<repository::IBlogPostRepository> repo,
                      std::shared_ptr<ISearchBackend>                  backend,
                      std::shared_ptr<jobs::IJobQueue>                 queue)
{
    PostSearchService::Options opts;
    opts.reindexInterval =
        std::chrono::seconds(cfg.get<int>("search.reindex_interval_sec", 21600));
    opts.popularQueryCapacity =
        cfg.get<std::size_t>("search.popular_query_capacity", 500);
    opts.defaultLimit = cfg.get<std::size_t>("search.default_limit", 20);

    return std::make_shared<PostSearchService>(std::move(repo),
                                               std::move(backend),
                                               std::move(queue),
                                               std::move(opts));
}

} // namespace intraledger::blogsuite::search