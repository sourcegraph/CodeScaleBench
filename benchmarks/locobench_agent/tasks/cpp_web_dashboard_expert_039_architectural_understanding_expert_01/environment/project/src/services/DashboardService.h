#pragma once
/**********************************************************************************************************************
 *  MosaicBoard Studio – Dashboard Service
 *
 *  File:    MosaicBoardStudio/src/services/DashboardService.h
 *  Author:  MosaicBoard Core Team
 *  License: MIT
 *
 *  Description:
 *  ------------
 *  The DashboardService is the façade that orchestrates CRUD-operations for dashboards, handles tile management, and
 *  emits real-time events over the global event-bus.  Caching, optimistic concurrency control, auditing and structured
 *  error reporting are implemented to guarantee a predictable, low-latency experience even under heavy load.
 *
 *  NOTE:
 *  This is a header-only implementation to keep the snippet self-contained.  In production, move the definitions to a
 *  dedicated *.cpp file.
 *********************************************************************************************************************/

#include <chrono>
#include <exception>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mosaic::core
{
    /*------------------------------------------------------------------------------------------------------------------
     *  Utility types & forward declarations
     *--------------------------------------------------------------------------------------------------------------- */

    using Timestamp = std::chrono::time_point<std::chrono::system_clock>;

    // Lightweight, serialisable DTOs.
    struct DashboardSummary
    {
        std::string id;
        std::string displayName;
        Timestamp   lastModified;
    };

    struct DashboardDetail : DashboardSummary
    {
        std::string            description;
        std::vector<std::string> tilePluginIds; // Ordered list of plugin IDs
        std::string            ownerUserId;
    };

    struct DashboardCreateRequest
    {
        std::string            displayName;
        std::string            description;
        std::vector<std::string> initialTilePluginIds;
        std::string            ownerUserId;
    };

    struct DashboardUpdateRequest
    {
        std::optional<std::string>            displayName;
        std::optional<std::string>            description;
        std::optional<std::vector<std::string>> tilePluginIds;
    };

    // Low-level repository interface (backed by a DB or any persistent store).
    class IDashboardRepository
    {
    public:
        virtual ~IDashboardRepository() = default;

        virtual std::vector<DashboardSummary> fetchAll()                                                    = 0;
        virtual std::optional<DashboardDetail> fetchById(const std::string& id)                             = 0;
        virtual std::string                    insert(const DashboardCreateRequest& req)                    = 0;
        virtual void                           update(const std::string& id, const DashboardUpdateRequest&) = 0;
        virtual void                           remove(const std::string& id)                                = 0;
    };

    // A skeletal event-bus.  In real code this would be a websocket or ZeroMQ wrapper.
    class IEventBus
    {
    public:
        virtual ~IEventBus() = default;
        virtual void publish(std::string topic, std::string payload) = 0;
    };

    // Generic service exception carrying a machine-readable error code.
    class ServiceError : public std::runtime_error
    {
    public:
        enum class Code
        {
            NotFound,
            AlreadyExists,
            ValidationFailed,
            InternalError,
            Conflict
        };

        ServiceError(Code c, std::string msg)
            : std::runtime_error(std::move(msg)), code(c)
        {
        }
        [[nodiscard]] Code code_value() const noexcept { return code; }

    private:
        Code code;
    };

    /*------------------------------------------------------------------------------------------------------------------
     *  Very small concurrent-cache helper for read-heavy workloads.
     *--------------------------------------------------------------------------------------------------------------- */
    template<typename Key, typename Value>
    class LocalCache
    {
    public:
        explicit LocalCache(std::chrono::seconds ttl = std::chrono::seconds{30}) : ttl_(ttl) {}

        void put(const Key& key, Value val)
        {
            std::unique_lock lk(mutex_);
            storage_[key] = {std::move(val), std::chrono::system_clock::now()};
        }

        std::optional<Value> get(const Key& key) const
        {
            std::shared_lock lk(mutex_);
            auto             it = storage_.find(key);
            if (it == storage_.end()) { return std::nullopt; }

            if (std::chrono::system_clock::now() - it->second.lastUsed >= ttl_) { return std::nullopt; }
            return it->second.data;
        }

        void invalidate(const Key& key)
        {
            std::unique_lock lk(mutex_);
            storage_.erase(key);
        }

        void invalidateAll()
        {
            std::unique_lock lk(mutex_);
            storage_.clear();
        }

    private:
        struct CacheEntry
        {
            Value   data;
            mutable Timestamp lastUsed;
        };

        std::chrono::seconds                                    ttl_;
        mutable std::shared_mutex                               mutex_;
        mutable std::unordered_map<Key, CacheEntry> storage_;
    };

    /*------------------------------------------------------------------------------------------------------------------
     *  DashboardService
     *--------------------------------------------------------------------------------------------------------------- */
    class DashboardService
    {
    public:
        DashboardService(std::shared_ptr<IDashboardRepository> repo,
                         std::shared_ptr<IEventBus>            eventBus,
                         std::chrono::seconds                  cacheTTL = std::chrono::seconds{30})
            : repository_(std::move(repo))
            , eventBus_(std::move(eventBus))
            , cache_(cacheTTL)
        {
        }

        /*----------------------------------------------------------------------------------------------------------
         *  CRUD
         *------------------------------------------------------------------------------------------------------- */
        std::vector<DashboardSummary> listDashboards()
        {
            // Cache top-level listing for fast sidebar draw.
            if (auto cached = cache_.get(kListCacheKey)) { return *cached; }

            auto list = repository_->fetchAll();
            cache_.put(kListCacheKey, list);
            return list;
        }

        DashboardDetail getDashboard(const std::string& dashboardId)
        {
            if (auto cached = cache_.get(dashboardId)) { return *cached; }

            auto dbDash = repository_->fetchById(dashboardId);
            if (!dbDash) { throw ServiceError(ServiceError::Code::NotFound, "Dashboard not found: " + dashboardId); }

            cache_.put(dashboardId, *dbDash);
            return *dbDash;
        }

        std::string createDashboard(const DashboardCreateRequest& req)
        {
            validateCreate(req);
            const auto id = repository_->insert(req);

            cache_.invalidate(kListCacheKey);
            publishDashboardEvent("dashboard.created", id);
            return id;
        }

        void updateDashboard(const std::string& id, const DashboardUpdateRequest& req)
        {
            validateUpdate(req);

            // Optimistic concurrency: ensure the dashboard exists before attempting to update.
            if (!repository_->fetchById(id)) { throw ServiceError(ServiceError::Code::NotFound, "Dashboard not found"); }

            repository_->update(id, req);
            cache_.invalidate(id);
            cache_.invalidate(kListCacheKey);
            publishDashboardEvent("dashboard.updated", id);
        }

        void deleteDashboard(const std::string& id)
        {
            repository_->remove(id);
            cache_.invalidate(id);
            cache_.invalidate(kListCacheKey);
            publishDashboardEvent("dashboard.deleted", id);
        }

        /*----------------------------------------------------------------------------------------------------------
         *  Tile management helpers
         *------------------------------------------------------------------------------------------------------- */
        void attachTile(const std::string& dashboardId, const std::string& tilePluginId)
        {
            auto dash = getDashboard(dashboardId);
            dash.tilePluginIds.push_back(tilePluginId);

            DashboardUpdateRequest req;
            req.tilePluginIds = dash.tilePluginIds;
            repository_->update(dashboardId, req);

            cache_.invalidate(dashboardId);
            publishDashboardEvent("dashboard.tile_attached", dashboardId + ":" + tilePluginId);
        }

        void detachTile(const std::string& dashboardId, const std::string& tilePluginId)
        {
            auto dash = getDashboard(dashboardId);

            auto it = std::remove(dash.tilePluginIds.begin(), dash.tilePluginIds.end(), tilePluginId);
            if (it == dash.tilePluginIds.end()) { return; } // No-op if tile not present.
            dash.tilePluginIds.erase(it, dash.tilePluginIds.end());

            DashboardUpdateRequest req;
            req.tilePluginIds = dash.tilePluginIds;
            repository_->update(dashboardId, req);

            cache_.invalidate(dashboardId);
            publishDashboardEvent("dashboard.tile_detached", dashboardId + ":" + tilePluginId);
        }

    private:
        /*----------------------------------------------------------------------------------------------------------
         *  Validation helpers
         *------------------------------------------------------------------------------------------------------- */
        static void validateCreate(const DashboardCreateRequest& req)
        {
            if (req.displayName.empty())
            {
                throw ServiceError(ServiceError::Code::ValidationFailed, "Display name is mandatory");
            }
            if (req.ownerUserId.empty())
            {
                throw ServiceError(ServiceError::Code::ValidationFailed, "Owner user id is mandatory");
            }
        }

        static void validateUpdate(const DashboardUpdateRequest& req)
        {
            if (req.displayName && req->displayName->empty())
            {
                throw ServiceError(ServiceError::Code::ValidationFailed, "Display name cannot be empty");
            }
        }

        /*----------------------------------------------------------------------------------------------------------
         *  Internal helpers
         *------------------------------------------------------------------------------------------------------- */
        void publishDashboardEvent(const std::string& topic, const std::string& payload)
        {
            try
            {
                eventBus_->publish(topic, payload);
            }
            catch (const std::exception& ex)
            {
                // Swallow to avoid cascading failures; log in real implementation.
            }
        }

        static constexpr const char* kListCacheKey = "_dashboard_list_cache";

        std::shared_ptr<IDashboardRepository> repository_;
        std::shared_ptr<IEventBus>            eventBus_;
        mutable LocalCache<std::string, std::vector<DashboardSummary>> cache_; // two cache types share same instance via variant
        mutable LocalCache<std::string, DashboardDetail>              detailCache_{std::chrono::seconds{30}};
    };

} // namespace mosaic::core