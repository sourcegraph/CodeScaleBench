```cpp
//
//  module_13.cpp
//  IntraLedger BlogSuite – Search Index Service
//
//  Created by OpenAI ChatGPT on 2024-05-02.
//  Copyright © 2024 IntraLedger.
//  SPDX-License-Identifier: Apache-2.0
//
//  This file implements BlogSuite’s asynchronous search-index maintenance
//  facility.  Whenever articles are created, updated, or removed, the service
//  schedules a lightweight background job that syncs the canonical database
//  representation with the search backend (Apache Lucene / OpenSearch / etc.).
//
//  Design notes
//  ---------------------------------------------------------------------------
//  • Non-blocking: Writers are never stalled by indexing work.
//  • Idempotent: Duplicate update requests for the same post are coalesced.
//  • Fault-tolerant: Jobs are automatically retried using an exponential
//    backoff strategy on network / I/O errors.
//  • Observable: Rich, structured logging is emitted at every stage.
//  • Pluggable: The concrete search backend is injected via the `ISearchClient`
//    interface; swapping Lucene for ElasticSearch requires zero code changes.
//

#include "search/module_13.hpp"          // Interface definition
#include "core/Logger.hpp"               // spdlog-backed logger
#include "core/Config.hpp"               // Runtime configuration access
#include "async/JobDispatcher.hpp"       // Asynchronous worker pool
#include "async/IRetryPolicy.hpp"        // Retry strategy interface
#include "async/RetryPolicies.hpp"       // Built-in exponential backoff policy
#include "db/repository/PostRepository.hpp"
#include "search/ISearchClient.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <exception>
#include <future>
#include <set>
#include <stdexcept>
#include <thread>
#include <utility>

using namespace std::chrono_literals;

namespace blogsuite::search {

namespace {

constexpr char kLoggerCategory[] = "SearchIndexService";

spdlog::logger& logger()
{
    static spdlog::logger& instance = core::Logger::instance().get(kLoggerCategory);
    return instance;
}

// Maximum duration a request is allowed to live in the coalescing queue
constexpr auto kCoalesceWindow = 300ms;

// ---------------------------------------------------------------------------
// Helper structs representing the individual job payloads
// ---------------------------------------------------------------------------

struct IncrementalPayload
{
    std::uint64_t postId;
};

struct FullRebuildPayload
{
    /* no user data */
};

} // namespace

// ---------------------------------------------------------------------------
//                         C O N S T R U C T O R S
// ---------------------------------------------------------------------------

SearchIndexService::SearchIndexService(std::shared_ptr<db::PostRepository>  postRepo,
                                       std::shared_ptr<ISearchClient>       searchClient,
                                       std::shared_ptr<async::JobDispatcher> dispatcher,
                                       std::shared_ptr<async::IRetryPolicy> retryPolicy)
    : m_postRepo(std::move(postRepo))
    , m_searchClient(std::move(searchClient))
    , m_dispatcher(std::move(dispatcher))
    , m_retryPolicy(std::move(retryPolicy))
    , m_shutdownRequested(false)
{
    if (!m_postRepo || !m_searchClient || !m_dispatcher) {
        throw std::invalid_argument("SearchIndexService: dependencies must not be nullptr");
    }

    if (!m_retryPolicy) {
        m_retryPolicy = std::make_shared<async::ExponentialBackoffPolicy>(
            /* initial delay */ 1s, /* max delay */ 30s, /* factor */ 2.0);
    }

    logger().info("SearchIndexService initialized");
}

SearchIndexService::~SearchIndexService()
{
    shutdown();
    logger().info("SearchIndexService terminated");
}

// ---------------------------------------------------------------------------
//                       P U B L I C   A P I
// ---------------------------------------------------------------------------

void SearchIndexService::scheduleIncrementalIndex(std::uint64_t postId)
{
    {
        std::scoped_lock lk(m_coalesceMutex);
        m_pendingUpdates.insert(postId);
    }

    // Post a coalescing task if none exists yet.
    bool expected = false;
    if (m_coalescingScheduled.compare_exchange_strong(expected, true)) {
        m_dispatcher->postDelayed(kCoalesceWindow, [self = shared_from_this()] {
            self->flushPendingIncrementals();
        });
    }
}

void SearchIndexService::scheduleFullIndexRebuild()
{
    m_dispatcher->post([self = shared_from_this()] {
        self->executeWithRetry<FullRebuildPayload>({}, &SearchIndexService::handleFullRebuild);
    });
}

void SearchIndexService::shutdown()
{
    bool expected = false;
    if (m_shutdownRequested.compare_exchange_strong(expected, true)) {
        logger().info("Shutting down SearchIndexService …");
        m_dispatcher->drain();
    }
}

// ---------------------------------------------------------------------------
//                         I N T E R N A L
// ---------------------------------------------------------------------------

void SearchIndexService::flushPendingIncrementals()
{
    std::set<std::uint64_t> batch;
    {
        std::scoped_lock lk(m_coalesceMutex);
        batch.swap(m_pendingUpdates);
        m_coalescingScheduled.store(false);
    }

    for (auto id : batch) {
        m_dispatcher->post([self = shared_from_this(), id] {
            self->executeWithRetry<IncrementalPayload>({id}, &SearchIndexService::handleIncremental);
        });
    }
}

template <typename PayloadT, typename HandlerT>
void SearchIndexService::executeWithRetry(PayloadT                payload,
                                          HandlerT                handler) noexcept
{
    size_t attempt = 0;
    while (!m_shutdownRequested.load()) {
        try {
            (this->*handler)(payload);
            return; // successful execution
        } catch (const std::exception& ex) {
            attempt++;
            auto delay = m_retryPolicy->nextDelay(attempt);
            logger().warn("Search indexing attempt {} failed: {} – retrying in {} ms",
                          attempt, ex.what(),
                          std::chrono::duration_cast<std::chrono::milliseconds>(delay).count());
            std::this_thread::sleep_for(delay);
        } catch (...) {
            attempt++;
            auto delay = m_retryPolicy->nextDelay(attempt);
            logger().error("Search indexing attempt {} failed due to unknown error – retrying "
                           "in {} ms",
                           attempt,
                           std::chrono::duration_cast<std::chrono::milliseconds>(delay).count());
            std::this_thread::sleep_for(delay);
        }
    }

    logger().warn("SearchIndexService is shutting down; aborting retry loop");
}

// ---------------------------------------------------------------------------
//                         H A N D L E R S
// ---------------------------------------------------------------------------

void SearchIndexService::handleIncremental(const IncrementalPayload& payload)
{
    // Retrieve only the modified post, minimise I/O
    auto post = m_postRepo->findById(payload.postId);

    if (!post) {
        logger().warn("Incremental index: post {} not found (might have been deleted)",
                      payload.postId);
        m_searchClient->removeDocument(std::to_string(payload.postId));
        return;
    }

    search::Document doc;
    doc.id         = std::to_string(post->id());
    doc.title      = post->title();
    doc.body       = post->body();
    doc.published  = post->publishedAtUtc();
    doc.authorSlug = post->author().username();

    m_searchClient->upsertDocument(std::move(doc));

    logger().debug("Incrementally indexed post {}", payload.postId);
}

void SearchIndexService::handleFullRebuild(const FullRebuildPayload&)
{
    logger().info("Starting full search index rebuild");

    // 1. Wipe existing index
    m_searchClient->clearIndex();

    // 2. Stream rows from the database in a memory-friendly way
    m_postRepo->forEachPublished([this](const db::Post& post) {
        search::Document doc;
        doc.id         = std::to_string(post.id());
        doc.title      = post.title();
        doc.body       = post.body();
        doc.published  = post.publishedAtUtc();
        doc.authorSlug = post.author().username();

        m_searchClient->upsertDocument(std::move(doc));
    });

    logger().info("Finished full search index rebuild");
}

} // namespace blogsuite::search
```
