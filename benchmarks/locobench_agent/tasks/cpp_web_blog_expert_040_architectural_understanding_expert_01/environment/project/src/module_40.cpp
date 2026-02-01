```cpp
/**
 *  IntraLedger BlogSuite – Search Indexer Job
 *
 *  File:    src/module_40.cpp
 *  Project: web_blog
 *
 *  Description:
 *      Implementation of an asynchronous background job responsible for
 *      (re-)indexing articles in the full-text search engine.  The job is
 *      triggered whenever an article is created, updated, or deleted.  Running
 *      inside the built-in job processor, it leverages a Unit-of-Work boundary
 *      to ensure that database reads are consistent and executes CPU-bound
 *      indexing tasks in parallel using std::async.
 *
 *  NOTE:
 *      This translation unit purposefully *does not* expose any symbols outside
 *      of the “blogsuite” namespace hierarchy.  Relying code must include the
 *      accompanying header <jobs/SearchIndexerJob.hpp>.
 */

#include <algorithm>
#include <chrono>
#include <exception>
#include <future>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "core/job/JobInterface.hpp"
#include "core/log/Logger.hpp"
#include "database/UnitOfWork.hpp"
#include "repository/ArticleRepository.hpp"
#include "service/SearchService.hpp"
#include "util/Stopwatch.hpp"

namespace blogsuite::jobs
{

/* ─────────────────────────────────────────────────────────────────────────────
 * Forward declarations
 * ────────────────────────────────────────────────────────────────────────────*/

namespace // (anonymous)
{
    // Maximum number of worker futures that may be outstanding at once.  This
    // keeps memory pressure / CPU contention under control for installations
    // with very large article sets.
    constexpr std::size_t kMaxConcurrency =
        std::max<std::size_t>(2u, std::thread::hardware_concurrency());
}

/* ─────────────────────────────────────────────────────────────────────────────
 * SearchIndexerJob
 * ────────────────────────────────────────────────────────────────────────────*/

class SearchIndexerJob final : public core::job::JobInterface
{
public:
    explicit SearchIndexerJob(std::vector<std::int64_t> articleIds);
    ~SearchIndexerJob() override = default;

    // ---------------------------------------------------------------------
    // core::job::JobInterface
    // ---------------------------------------------------------------------
    [[nodiscard]] std::string_view name() const noexcept override;
    void                       run() override;

private:
    void doReindexArticle(
        std::int64_t                        articleId,
        service::SearchService&             searchSvc,
        repository::ArticleRepository&      repo,
        std::vector<std::string>&           errorCollector) noexcept;

    std::vector<std::int64_t> m_articleIds;
    core::log::Logger         m_logger{core::log::category::job,
                               "SearchIndexerJob"};
};

/* ─────────────────────────────────────────────────────────────────────────────
 * Implementation
 * ────────────────────────────────────────────────────────────────────────────*/

SearchIndexerJob::SearchIndexerJob(std::vector<std::int64_t> articleIds)
    : m_articleIds(std::move(articleIds))
{
    if (m_articleIds.empty())
    {
        throw std::invalid_argument(
            "SearchIndexerJob cannot be instantiated with an empty "
            "article-id list");
    }

    // Deduplicate IDs (defensive—caller *should* already do this)
    std::sort(m_articleIds.begin(), m_articleIds.end());
    m_articleIds.erase(std::unique(m_articleIds.begin(), m_articleIds.end()),
                       m_articleIds.end());
}

std::string_view SearchIndexerJob::name() const noexcept
{
    return "search_indexer";
}

void SearchIndexerJob::run()
{
    m_logger.info("Started search re-indexing for {} article(s)",
                  m_articleIds.size());

    util::Stopwatch stopwatch; // simple RAII wall-clock timer

    // Create a UnitOfWork to scope repository lifetime and transaction
    database::UnitOfWork uow;
    repository::ArticleRepository articleRepo{uow};
    service::SearchService        searchSvc;

    std::vector<std::string> errorCollector;
    std::vector<std::future<void>> futures;
    futures.reserve(kMaxConcurrency);

    const auto launchPolicy =
        std::launch::async | std::launch::deferred; // let runtime decide

    for (auto id : m_articleIds)
    {
        // Throttle outstanding futures to kMaxConcurrency.
        if (futures.size() >= kMaxConcurrency)
        {
            futures.front().get();
            futures.erase(futures.begin());
        }

        futures.emplace_back(
            std::async(launchPolicy,
                       [this, id, &searchSvc, &articleRepo, &errorCollector]()
                       {
                           doReindexArticle(id, searchSvc, articleRepo,
                                            errorCollector);
                       }));
    }

    // Wait for leftovers
    for (auto& fut : futures) { fut.get(); }

    // Commit search index after all individual indexing operations succeed.
    // Any stored failures reload the transaction.
    if (errorCollector.empty())
    {
        try
        {
            searchSvc.commit();
            m_logger.info("Search re-indexing completed in {:.2f} ms "
                          "({} article(s))",
                          stopwatch.ms(), m_articleIds.size());
        }
        catch (const std::exception& ex)
        {
            m_logger.error("Failed to commit search index: {}", ex.what());
            // Re-throw to signal job processor that retry/backoff is needed.
            throw;
        }
    }
    else
    {
        for (auto& msg : errorCollector) { m_logger.error("{}", msg); }
        throw std::runtime_error(
            "SearchIndexerJob finished with one or more errors");
    }
}

void SearchIndexerJob::doReindexArticle(
    std::int64_t                   articleId,
    service::SearchService&        searchSvc,
    repository::ArticleRepository& repo,
    std::vector<std::string>&      errorCollector) noexcept
{
    try
    {
        auto articleOpt = repo.findById(articleId);
        if (!articleOpt)
        {
            m_logger.warn("Article #{} not found, skipping", articleId);
            return;
        }

        const auto& article = *articleOpt;
        searchSvc.indexDocument(article.id(),
                                article.title(),
                                article.body(),
                                article.isPublished(),
                                article.locale());

        m_logger.debug("Article #{} ({}) indexed", article.id(),
                       article.title());
    }
    catch (const std::exception& ex)
    {
        errorCollector.emplace_back(
            fmt::format("Failed to index article #{}: {}", articleId,
                        ex.what()));
    }
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Factory function
 * ────────────────────────────────────────────────────────────────────────────*/

// The job-processor requires a C-linkage factory symbol. This allows the
// scheduler to dynamically create the job from a shared library at runtime.
/* NOLINTNEXTLINE */
extern "C" std::unique_ptr<core::job::JobInterface>
create_search_indexer_job(std::vector<std::int64_t> articleIds)
{
    return std::make_unique<blogsuite::jobs::SearchIndexerJob>(
        std::move(articleIds));
}

} // namespace blogsuite::jobs
```