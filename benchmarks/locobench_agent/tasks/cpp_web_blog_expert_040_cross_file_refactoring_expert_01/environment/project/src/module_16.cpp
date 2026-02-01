```cpp
/**
 *  IntraLedger BlogSuite
 *  File: src/module_16.cpp
 *
 *  Purpose:
 *      Incremental, asynchronous full-text indexing of article content.
 *      New or modified articles are periodically picked up from the
 *      database, normalised, and pushed to the search back-end.
 *
 *  This module is wired into the global job scheduler during start-up
 *  and may also be triggered ad-hoc from the administration interface.
 *
 *  Copyright (c) 2023-2024
 *  SPDX-License-Identifier: MIT
 */

#include <algorithm>
#include <chrono>
#include <exception>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "Core/Config.hpp"                    // Global configuration API
#include "Core/Logger.hpp"                    // Structured logger
#include "Core/StopToken.hpp"                 // Cooperative cancellation
#include "Jobs/IJob.hpp"                      // Abstract job interface
#include "Jobs/JobScheduler.hpp"              // Centralised scheduler
#include "ORM/DatabaseSession.hpp"            // Unit-of-work / session
#include "Repository/ArticleRepository.hpp"   // Data access abstraction
#include "Search/SearchIndexClient.hpp"       // Search back-end adapter

using namespace std::chrono_literals;

namespace intraledger::blogsuite::jobs {

// ----------------------------------------------------------------------
// Constants & helpers
// ----------------------------------------------------------------------

namespace {
constexpr std::string_view kCfgLastIndexedId = "search.last_indexed_id";
constexpr std::string_view kCfgBatchSize     = "search.batch_size";

static uint64_t readLastIndexedId(core::Config& cfg)
{
    try {
        return cfg.get<uint64_t>(kCfgLastIndexedId);
    } catch (const std::exception& ex) {
        core::Logger::warn("ContentIndexerJob")
            .field("key", kCfgLastIndexedId)
            .msg("Falling back to zero for last indexed id: {}", ex.what());
        return 0;
    }
}

static uint64_t readBatchSize(core::Config& cfg)
{
    constexpr uint64_t kDefaultBatchSize = 250;
    try {
        return std::clamp(cfg.get<uint64_t>(kCfgBatchSize), 10ULL, 2'000ULL);
    } catch (...) {
        return kDefaultBatchSize;
    }
}
}  // namespace

// ----------------------------------------------------------------------
// ContentIndexerJob
// ----------------------------------------------------------------------

class ContentIndexerJob final : public core::jobs::IJob
{
public:
    explicit ContentIndexerJob(std::shared_ptr<repositories::ArticleRepository>  articleRepo,
                               std::shared_ptr<search::SearchIndexClient>       searchClient,
                               std::shared_ptr<orm::IDatabaseSessionFactory>    sessionFactory)
        : _articleRepo(std::move(articleRepo)),
          _searchClient(std::move(searchClient)),
          _sessionFactory(std::move(sessionFactory)),
          _batchSize(readBatchSize(core::Config::instance()))
    {
        if (!_articleRepo || !_searchClient || !_sessionFactory) {
            throw std::invalid_argument("ContentIndexerJob dependencies must not be null");
        }
    }

    core::jobs::JobResult run(const core::jobs::JobContext& ctx) noexcept override
    {
        constexpr std::string_view kLogTag = "ContentIndexerJob";
        auto& logger = core::Logger::info(kLogTag);

        try {
            core::Config& cfg               = core::Config::instance();
            uint64_t      lastProcessedId   = readLastIndexedId(cfg);
            uint64_t      processedThisRun  = 0;

            logger.field("last_id", lastProcessedId)
                  .field("batch_size", _batchSize)
                  .msg("Starting incremental indexing cycle");

            orm::DatabaseSession dbSession{_sessionFactory->create()};
            std::vector<repositories::ArticleDTO> articles =
                _articleRepo->fetchUpdatedAfter(dbSession, lastProcessedId, _batchSize);

            if (articles.empty()) {
                logger.msg("No articles to index");
                return core::jobs::JobResult::success();
            }

            // Transform & push documents
            std::vector<search::Document> docs;
            docs.reserve(articles.size());

            std::transform(articles.begin(), articles.end(), std::back_inserter(docs),
                           [](const repositories::ArticleDTO& dto) {
                               search::Document doc;
                               doc.id          = dto.id;
                               doc.language    = dto.language;
                               doc.title       = dto.title;
                               doc.content     = dto.body;
                               doc.publishedAt = dto.publishedAt;
                               doc.tags        = dto.tags;
                               return doc;
                           });

            _searchClient->bulkIndex(docs, ctx.cancelToken);  // May throw

            // Persist last indexed id
            uint64_t newLastId =
                std::max_element(articles.begin(), articles.end(),
                                 [](auto& a, auto& b) { return a.id < b.id; })
                    ->id;

            cfg.set<uint64_t>(kCfgLastIndexedId, newLastId);
            cfg.save();  // Durably persist changes

            processedThisRun = articles.size();
            logger.field("processed", processedThisRun)
                  .field("new_last_id", newLastId)
                  .msg("Incremental indexing completed");

            return core::jobs::JobResult::success();

        } catch (const core::StopRequestedException&) {
            core::Logger::info(kLogTag).msg("Indexing cancelled via stop token");
            return core::jobs::JobResult::cancelled();
        } catch (const std::exception& ex) {
            core::Logger::error(kLogTag)
                .msg("Indexing run failed: {}", ex.what());
            return core::jobs::JobResult::retry();  // Let scheduler requeue
        } catch (...) {
            core::Logger::critical(kLogTag).msg("Unknown failure during indexing");
            return core::jobs::JobResult::abort();
        }
    }

    std::string name() const noexcept override { return "ContentIndexerJob"; }

private:
    std::shared_ptr<repositories::ArticleRepository>  _articleRepo;
    std::shared_ptr<search::SearchIndexClient>        _searchClient;
    std::shared_ptr<orm::IDatabaseSessionFactory>     _sessionFactory;
    uint64_t                                          _batchSize;
};

// ----------------------------------------------------------------------
// Registration helper
// ----------------------------------------------------------------------

/**
 *  Boot-time registration API.
 *  This is called from ModuleInit.cpp after infrastructure setup.
 */
void registerContentIndexer(core::jobs::JobScheduler&                  scheduler,
                            std::shared_ptr<repositories::ArticleRepository> articleRepo,
                            std::shared_ptr<search::SearchIndexClient> searchClient,
                            std::shared_ptr<orm::IDatabaseSessionFactory> sessionFactory)
{
    using core::jobs::SchedulePolicy;
    using core::jobs::TimeOfDay;

    static std::mutex registrationGuard;
    std::lock_guard lk{registrationGuard};

    auto job = std::make_shared<ContentIndexerJob>(std::move(articleRepo),
                                                   std::move(searchClient),
                                                   std::move(sessionFactory));

    // Policy: Run every 5 minutes, starting at service boot.
    SchedulePolicy policy;
    policy.interval = 5min;
    policy.anchor   = TimeOfDay::immediate();

    scheduler.registerJob(job, policy);
}

}  // namespace intraledger::blogsuite::jobs
```