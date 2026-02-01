```cpp
/************************************************************************************
 *  MosaicBoard Studio
 *  File:    SearchService.cpp
 *
 *  Copyright (c) 2024 MosaicBoard
 *  SPDX-License-Identifier: MIT
 *
 *  Description:
 *      Implementation of the SearchService.  The service offers a thin façade
 *      over the underlying search repository (e.g. SQLite FTS, ElasticSearch,
 *      or an in-memory fallback).  Responsibilities:
 *
 *          • Parse and validate user queries
 *          • Apply security / ACL filters
 *          • Serve hot results from an in-memory LRU cache
 *          • Dispatch asynchronous re-index operations via the event bus
 *          • Transform low-level hits into DTOs understood by higher layers
 *
 *      The service purposely contains no persistence code—those concerns live
 *      in SearchRepository implementations that satisfy the IRepository
 *      contract.
 *
 ***********************************************************************************/

#include "SearchService.h"

#include <algorithm>
#include <chrono>
#include <future>
#include <mutex>
#include <stdexcept>
#include <unordered_set>

#include "Cache/MemoryCache.h"
#include "Core/Clock.h"
#include "Core/Logger.h"
#include "Core/StringUtil.h"
#include "EventBus/EventBus.h"
#include "Repositories/SearchRepository.h"
#include "Security/AccessControl.h"
#include "Utils/ScopeExit.h"

using namespace std::chrono_literals;

namespace Mosaic::Services
{

// Convenience alias for a thread pool packaged_task result
using SearchFuture = std::future<std::vector<SearchResult>>;

/* ----------------------------------------------------------------------------- *
 *  ctor / dtor
 * ----------------------------------------------------------------------------- */
SearchService::SearchService(std::shared_ptr<Repositories::ISearchRepository> repo,
                             std::shared_ptr<Eventing::EventBus>               bus,
                             std::shared_ptr<Caching::ICache<std::string>>    cache)
    : _repository{std::move(repo)}
    , _bus{std::move(bus)}
    , _cache{std::move(cache)}
    , _stopBackgroundThreads{false}
{
    if (!_repository)
    {
        throw std::invalid_argument{"SearchService: repository must not be null."};
    }
    if (!_bus)
    {
        throw std::invalid_argument{"SearchService: event bus must not be null."};
    }
    if (!_cache)
    {
        // In the exceedingly rare case the DI container forgot a cache, fall
        // back to a local, unbounded in-memory variant so that we remain
        // operational (albeit without eviction support).
        _cache = std::make_shared<Caching::MemoryCache<std::string>>();
        Logger::warn("SearchService") << "No cache provided – falling back to MemoryCache.\n";
    }

    // Listen for tile-level mutations and schedule lazy re-index
    _busConnection = _bus->subscribe<TileChangedEvent>(
        [this](const TileChangedEvent& evt)
        {
            // Debounce events to avoid thrashing the search engine while a
            // designer is rapidly iterating in the Studio.
            std::lock_guard lk{_pendingIndexMux};
            _pendingTileIds.insert(evt.tileId);
            if (!_reIndexScheduled)
            {
                _reIndexScheduled = true;
                _backgroundFutures.emplace_back(std::async(std::launch::async,
                                                           &SearchService::flushPendingIndexTasks,
                                                           this));
            }
        });
}

SearchService::~SearchService() noexcept
{
    _stopBackgroundThreads.store(true, std::memory_order_relaxed);

    // Wait for background ops to drain.
    for (auto& f : _backgroundFutures)
    {
        // Validity check avoids std::future_error when continuation is detached
        if (f.valid())
        {
            try
            {
                f.wait();
            }
            catch (const std::exception& ex)
            {
                Logger::error("SearchService") << "Exception while shutting down: " << ex.what()
                                               << '\n';
            }
        }
    }
}

/* ----------------------------------------------------------------------------- *
 *  Public API
 * ----------------------------------------------------------------------------- */

std::vector<SearchResult> SearchService::search(const std::string& rawQuery,
                                                const SearchScope&  scope,
                                                std::size_t         limit,
                                                const Security::UserContext& userCtx)
{
    if (rawQuery.empty())
    {
        return {};
    }

    try
    {
        // Normalize the query (trim, collapse whitespace, lower-case, etc.)
        const std::string normalizedQuery = Core::String::normalize(rawQuery);

        // Compose cache key
        const std::string cacheKey =
            normalizedQuery + "::" + scope.toString() + "::" + std::to_string(limit) + "::"
            + userCtx.cacheKey();

        // Return hot results if present
        if (auto cached = _cache->get(cacheKey))
        {
            // clone() ensures caller owns its copy – avoids concurrent mutation surprises
            return cached->clone();
        }

        // Step 1: Perform the actual search
        std::vector<SearchResult> hits =
            _repository->search(normalizedQuery, scope, limit, userCtx);

        // Step 2: Filter results based on ACL rules (belt & suspenders—should already be
        //         handled by the repository SQL / query DSL, but double-check just in case).
        filterUnauthorized(hits, userCtx);

        // Step 3: Hydrate DTOs (convert raw DB rows to higher-level objects)
        hydrateMetadata(hits);

        // Step 4: Publish analytics event so the product team can track usage
        _bus->publish(SearchPerformedEvent{userCtx.userId, normalizedQuery, Clock::nowUtc()});

        // Step 5: Memoize
        _cache->put(cacheKey, hits, 5min);

        // We purposefully return by value to indulge NRVO—cheap when c++17's
        // guaranteed copy elision kicks in.
        return hits;
    }
    catch (const std::exception& ex)
    {
        Logger::error("SearchService") << "Search failed: " << ex.what() << '\n';
        throw; // Let upper layers translate into HTTP 500 / JSON-RPC error
    }
}

/* ----------------------------------------------------------------------------- *
 *  Helper: filters unauthorized results (defense-in-depth)
 * ----------------------------------------------------------------------------- */
void SearchService::filterUnauthorized(std::vector<SearchResult>&        hits,
                                       const Security::UserContext& userCtx) const
{
    hits.erase(std::remove_if(hits.begin(),
                              hits.end(),
                              [&userCtx](const SearchResult& hit)
                              {
                                  return !Security::AccessControl::canRead(userCtx, hit.acl);
                              }),
               hits.end());
}

/* ----------------------------------------------------------------------------- *
 *  Helper: enrich results with resolved metadata required by front-end tiles
 * ----------------------------------------------------------------------------- */
void SearchService::hydrateMetadata(std::vector<SearchResult>& hits) const
{
    for (auto& hit : hits)
    {
        // Lazy-load missing meta only when absent to minimize extra I/O
        if (!hit.thumbnailUrl.has_value())
        {
            hit.thumbnailUrl = _repository->resolveThumbnail(hit.kind, hit.objectId);
        }
        if (!hit.summary.has_value())
        {
            hit.summary = _repository->resolveSummary(hit.kind, hit.objectId, 140);
        }
    }
}

/* ----------------------------------------------------------------------------- *
 *  Background indexing logic
 * ----------------------------------------------------------------------------- */
void SearchService::flushPendingIndexTasks()
{
    // Any exception leaking from this routine would terminate the process
    // (std::async async continuations propagate uncaught exceptions). Guard it.
    try
    {
        // Delay slightly to batch quick successions of edits
        std::this_thread::sleep_for(750ms);

        std::unordered_set<TileId> tiles;
        {
            std::lock_guard lk{_pendingIndexMux};
            tiles.swap(_pendingTileIds);
            _reIndexScheduled = false;
        }

        if (tiles.empty() || _stopBackgroundThreads.load(std::memory_order_relaxed))
        {
            return;
        }

        Logger::debug("SearchService") << "Re-indexing " << tiles.size() << " tiles...\n";

        const auto start = Clock::nowUtc();
        _repository->reindexTiles(tiles);
        const auto durationMs =
            std::chrono::duration_cast<std::chrono::milliseconds>(Clock::nowUtc() - start).count();

        Logger::info("SearchService") << "Re-indexed " << tiles.size() << " tiles in "
                                      << durationMs << " ms.\n";
    }
    catch (const std::exception& ex)
    {
        Logger::error("SearchService") << "Re-index failed: " << ex.what() << '\n';
    }
}

} // namespace Mosaic::Services
```