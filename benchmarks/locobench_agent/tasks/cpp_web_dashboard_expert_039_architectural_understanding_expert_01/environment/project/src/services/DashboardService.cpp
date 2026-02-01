```cpp
/**
 * MosaicBoard Studio
 * File: MosaicBoardStudio/src/services/DashboardService.cpp
 *
 * Copyright (c) 2024 MosaicBoard.
 *
 * Implementation of the DashboardService.
 */

#include "DashboardService.h"

#include <chrono>
#include <shared_mutex>
#include <utility>

#include "../auth/AuthContext.h"
#include "../cache/ICache.h"
#include "../core/DatabaseSession.h"
#include "../events/EventBus.h"
#include "../repositories/DashboardRepository.h"
#include "../repositories/TileRepository.h"
#include "../utils/JsonUtils.h"
#include "../utils/Logger.h"

using namespace std::chrono_literals;

namespace Mosaic::Services
{
namespace
{
// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────
constexpr std::chrono::seconds DASHBOARD_CACHE_TTL = 20s;
constexpr char CACHE_NAMESPACE[]                   = "dashboard:";
constexpr char EVENT_DASHBOARD_UPDATED[]           = "DASHBOARD_UPDATED";
constexpr char EVENT_DASHBOARD_DELETED[]           = "DASHBOARD_DELETED";

// ──────────────────────────────────────────────────────────────────────────────
// Helper utilities
// ──────────────────────────────────────────────────────────────────────────────
std::string makeCacheKey(std::size_t dashboardId)
{
    return std::string(CACHE_NAMESPACE) + std::to_string(dashboardId);
}

// Throws if the user does not own the dashboard
void validateOwnership(const Auth::User &user, const Model::Dashboard &dashboard)
{
    if (dashboard.ownerId != user.id && !user.hasRole(Auth::Role::ADMIN))
    {
        throw Errors::AuthorizationError{"User does not have permission to access dashboard."};
    }
}

} // namespace

// ──────────────────────────────────────────────────────────────────────────────
// Constructor / Destructor
// ──────────────────────────────────────────────────────────────────────────────
DashboardService::DashboardService(std::shared_ptr<Repositories::DashboardRepository> dashboardRepo,
                                   std::shared_ptr<Repositories::TileRepository> tileRepo,
                                   std::shared_ptr<Cache::ICache> cache,
                                   std::shared_ptr<Events::EventBus> eventBus)
    : _dashboardRepo(std::move(dashboardRepo)),
      _tileRepo(std::move(tileRepo)),
      _cache(std::move(cache)),
      _eventBus(std::move(eventBus))
{
    if (!_dashboardRepo || !_tileRepo || !_cache || !_eventBus)
    {
        throw std::invalid_argument{"DashboardService dependencies must not be null."};
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Public API
// ──────────────────────────────────────────────────────────────────────────────
Model::Dashboard DashboardService::getDashboard(std::size_t dashboardId, const Auth::User &requester)
{
    try
    {
        const auto cacheKey = makeCacheKey(dashboardId);
        {
            // Try read cache
            std::optional<Model::Dashboard> cached;
            if (_cache->tryGet(cacheKey, cached))
            {
                validateOwnership(requester, *cached);
                return *cached;
            }
        }

        // Pull from DB
        auto dbSession = Core::DatabaseSession{};
        auto dashboard = _dashboardRepo->findById(dashboardId, dbSession);
        if (!dashboard)
        {
            throw Errors::NotFoundError{"Dashboard not found."};
        }

        validateOwnership(requester, *dashboard);

        // store in cache
        _cache->put(cacheKey, *dashboard, DASHBOARD_CACHE_TTL);
        return *dashboard;
    }
    catch (const std::exception &ex)
    {
        LOGE("getDashboard failed: {}", ex.what());
        throw;
    }
}

Model::Dashboard DashboardService::createDashboard(const std::string &title, const Auth::User &creator)
{
    // Input validation
    if (title.empty())
    {
        throw Errors::ValidationError{"Dashboard title cannot be empty."};
    }

    try
    {
        auto dbSession = Core::DatabaseSession{};

        Model::Dashboard newDashboard{};
        newDashboard.title   = title;
        newDashboard.ownerId = creator.id;
        newDashboard.createdAt =
            std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now().time_since_epoch()).count();

        auto id = _dashboardRepo->insert(newDashboard, dbSession);
        newDashboard.id = id;

        LOGI("Dashboard created. id={}, owner={}", id, creator.username);
        _eventBus->publish(EVENT_DASHBOARD_UPDATED, Json::object({{"id", id}, {"action", "create"}}));

        return newDashboard;
    }
    catch (const std::exception &ex)
    {
        LOGE("createDashboard failed: {}", ex.what());
        throw;
    }
}

void DashboardService::deleteDashboard(std::size_t dashboardId, const Auth::User &requester)
{
    auto dbSession = Core::DatabaseSession{};
    // verify ownership
    auto dashboard = _dashboardRepo->findById(dashboardId, dbSession);
    if (!dashboard)
    {
        throw Errors::NotFoundError{"Dashboard not found"};
    }
    validateOwnership(requester, *dashboard);

    // delete DB record
    _dashboardRepo->remove(dashboardId, dbSession);
    _tileRepo->removeByDashboard(dashboardId, dbSession); // cascade

    // evict cache
    _cache->remove(makeCacheKey(dashboardId));

    // notify
    _eventBus->publish(EVENT_DASHBOARD_DELETED, Json::object({{"id", dashboardId}}));

    LOGI("Dashboard deleted. id={}", dashboardId);
}

Model::Dashboard DashboardService::addTile(std::size_t dashboardId,
                                           const Model::TileDescriptor &tileDesc,
                                           const Auth::User          & requester)
{
    // Validate dashboard
    auto dbSession = Core::DatabaseSession{};
    auto dashboard = _dashboardRepo->findById(dashboardId, dbSession);
    if (!dashboard)
    {
        throw Errors::NotFoundError{"Dashboard not found"};
    }
    validateOwnership(requester, *dashboard);

    // persist tile
    auto tileId = _tileRepo->insert(dashboardId, tileDesc, dbSession);

    // update layout metadata
    dashboard->tileIds.push_back(tileId);
    _dashboardRepo->updateTiles(*dashboard, dbSession);

    // evict & publish
    _cache->remove(makeCacheKey(dashboardId));
    _eventBus->publish(EVENT_DASHBOARD_UPDATED,
                       Json::object({{"id", dashboardId}, {"action", "add_tile"}, {"tileId", tileId}}));

    LOGI("Tile {} added to dashboard {}", tileId, dashboardId);
    return *dashboard;
}

Model::Dashboard DashboardService::removeTile(std::size_t dashboardId,
                                              std::size_t tileId,
                                              const Auth::User &requester)
{
    auto dbSession = Core::DatabaseSession{};
    auto dashboard = _dashboardRepo->findById(dashboardId, dbSession);
    if (!dashboard)
    {
        throw Errors::NotFoundError{"Dashboard not found"};
    }
    validateOwnership(requester, *dashboard);

    // remove tile
    _tileRepo->remove(tileId, dbSession);

    // update layout metadata
    auto &ids = dashboard->tileIds;
    ids.erase(std::remove(ids.begin(), ids.end(), tileId), ids.end());
    _dashboardRepo->updateTiles(*dashboard, dbSession);

    // evict & publish
    _cache->remove(makeCacheKey(dashboardId));
    _eventBus->publish(EVENT_DASHBOARD_UPDATED,
                       Json::object({{"id", dashboardId}, {"action", "remove_tile"}, {"tileId", tileId}}));

    LOGI("Tile {} removed from dashboard {}", tileId, dashboardId);
    return *dashboard;
}

Model::Dashboard DashboardService::reorderTiles(std::size_t dashboardId,
                                                const std::vector<std::size_t> &orderedIds,
                                                const Auth::User              & requester)
{
    if (orderedIds.empty())
    {
        throw Errors::ValidationError{"orderedIds cannot be empty"};
    }

    auto dbSession = Core::DatabaseSession{};
    auto dashboard = _dashboardRepo->findById(dashboardId, dbSession);
    if (!dashboard)
    {
        throw Errors::NotFoundError{"Dashboard not found"};
    }
    validateOwnership(requester, *dashboard);

    // Ensure new order matches set of existing tileIds
    std::unordered_set<std::size_t> current(dashboard->tileIds.begin(), dashboard->tileIds.end());
    std::unordered_set<std::size_t> incoming(orderedIds.begin(), orderedIds.end());

    if (current != incoming)
    {
        throw Errors::ValidationError{"orderedIds does not match existing tile set"};
    }

    dashboard->tileIds = orderedIds;
    _dashboardRepo->updateTiles(*dashboard, dbSession);

    // evict & publish
    _cache->remove(makeCacheKey(dashboardId));
    _eventBus->publish(EVENT_DASHBOARD_UPDATED,
                       Json::object({{"id", dashboardId}, {"action", "reorder_tiles"}}));

    LOGI("Tiles reordered on dashboard {}", dashboardId);
    return *dashboard;
}

} // namespace Mosaic::Services
```
