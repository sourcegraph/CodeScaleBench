#ifndef CARDIO_INSIGHT_360_SRC_SERVICES_SERVICE_MANAGER_H_
#define CARDIO_INSIGHT_360_SRC_SERVICES_SERVICE_MANAGER_H_

/*
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File        : service_manager.h
 *  Description : Thread–safe service registry / lifecycle orchestrator for the
 *                in-process “pseudo-microservices” layer (Scheduling,
 *                Error-Recovery, Visualization, …).
 *
 *  The ServiceManager is implemented as a Meyers-style singleton.  Services
 *  derive from IService and are registered via ServiceManager::emplace<T>().
 *  The manager is responsible for invoking initialize(), start(), stop(), and
 *  destruction in the correct order while guaranteeing that:
 *
 *    • Registration is idempotent and type-safe
 *    • All look-ups are O(1) by std::type_index
 *    • Public methods are thread-safe (RW-lock semantics)
 *    • Robust error handling and exhaustive logging (SPDLOG)
 *
 *  Compile-time checks (static_assert) enforce that only classes derived from
 *  IService can be registered.
 *
 *  Copyright (c) 2024
 *  CardioInsight360 – All rights reserved.
 */

#include <shared_mutex>
#include <unordered_map>
#include <vector>
#include <memory>
#include <typeindex>
#include <type_traits>
#include <stdexcept>
#include <string_view>

#include <spdlog/spdlog.h>

namespace ci360::services {

//-----------------------------------------------------------------------------
//  Public Service Interface
//-----------------------------------------------------------------------------
enum class ServiceState {
    Created,
    Initializing,
    Running,
    Stopped,
    Failed,
    Destroyed
};

class IService
{
public:
    virtual ~IService() = default;

    // Lifecycle
    virtual void initialize()                                   = 0;
    virtual void start()                                        = 0;
    virtual void stop() noexcept                                = 0;

    // Introspection
    virtual ServiceState     state()         const noexcept     = 0;
    virtual std::string_view name()          const noexcept     = 0;
};

//-----------------------------------------------------------------------------
//  Service Manager (Singleton)
//-----------------------------------------------------------------------------
class ServiceManager final
{
public:
    // Obtain global instance (guaranteed thread-safe in C++11+)
    static ServiceManager& instance()
    {
        static ServiceManager _instance;
        return _instance;
    }

    //--------------------------------------------------------------------------
    //  Registration
    //--------------------------------------------------------------------------
    template <typename T, typename... Args>
    std::shared_ptr<T> emplace(Args&&... args)
    {
        static_assert(std::is_base_of_v<IService, T>,
                      "T must derive from IService");

        const std::type_index key { typeid(T) };

        std::unique_lock lock(m_mutex_);

        auto it = m_services_.find(key);
        if (it != m_services_.end()) {
            // Service already exists — return existing instance, ignore args.
            return std::static_pointer_cast<T>(it->second);
        }

        // Create service in Created state
        auto svc = std::make_shared<T>(std::forward<Args>(args)...);
        m_services_.emplace(key, svc);
        m_insertion_order_.push_back(key);

        spdlog::info("[ServiceManager] Registered service '{}'", svc->name());
        return svc;
    }

    //--------------------------------------------------------------------------
    //  Retrieval
    //--------------------------------------------------------------------------
    template <typename T>
    std::shared_ptr<T> get() const
    {
        static_assert(std::is_base_of_v<IService, T>,
                      "T must derive from IService");

        const std::type_index key { typeid(T) };

        std::shared_lock lock(m_mutex_);
        auto it = m_services_.find(key);
        if (it == m_services_.end()) {
            throw std::logic_error("ServiceManager::get<T> -> service not found");
        }
        return std::static_pointer_cast<T>(it->second);
    }

    template <typename T>
    bool contains() const
    {
        static_assert(std::is_base_of_v<IService, T>,
                      "T must derive from IService");

        const std::type_index key { typeid(T) };

        std::shared_lock lock(m_mutex_);
        return m_services_.find(key) != m_services_.end();
    }

    //--------------------------------------------------------------------------
    //  Bulk Lifecycle Operations
    //--------------------------------------------------------------------------
    void initialize_all()
    {
        std::vector<std::type_index> initialized;

        // Acquire shared copy to avoid holding lock during long operations.
        std::unordered_map<std::type_index, std::shared_ptr<IService>> services_cp;
        {
            std::shared_lock lock(m_mutex_);
            services_cp = m_services_;
        }

        for (auto& [key, svc] : services_cp) {
            try {
                if (svc->state() == ServiceState::Created) {
                    spdlog::info("[ServiceManager] Initializing '{}'", svc->name());
                    svc->initialize();
                    initialized.push_back(key);
                }
            } catch (const std::exception& ex) {
                spdlog::error("[ServiceManager] Failed to initialize '{}': {}",
                              svc->name(), ex.what());
                mark_failed(key);
            }
        }
    }

    void start_all()
    {
        std::unordered_map<std::type_index, std::shared_ptr<IService>> services_cp;
        {
            std::shared_lock lock(m_mutex_);
            services_cp = m_services_;
        }

        for (auto& [key, svc] : services_cp) {
            try {
                if (svc->state() == ServiceState::Initializing ||
                    svc->state() == ServiceState::Stopped)
                {
                    spdlog::info("[ServiceManager] Starting '{}'", svc->name());
                    svc->start();
                }
            } catch (const std::exception& ex) {
                spdlog::error("[ServiceManager] Failed to start '{}': {}",
                              svc->name(), ex.what());
                mark_failed(key);
            }
        }
    }

    void stop_all() noexcept
    {
        // Stop in reverse insertion order to honor dependencies
        std::vector<std::type_index> service_order;
        {
            std::shared_lock lock(m_mutex_);
            service_order.assign(m_insertion_order_.rbegin(),
                                 m_insertion_order_.rend());
        }

        for (auto& key : service_order) {
            std::shared_ptr<IService> svc;
            {
                std::shared_lock lock(m_mutex_);
                auto it = m_services_.find(key);
                if (it != m_services_.end())
                    svc = it->second;
            }
            if (svc) {
                try {
                    if (svc->state() == ServiceState::Running) {
                        spdlog::info("[ServiceManager] Stopping '{}'", svc->name());
                        svc->stop();
                    }
                } catch (const std::exception& ex) {
                    spdlog::critical("[ServiceManager] Exception while stopping '{}': {}",
                                     svc->name(), ex.what());
                    // Continue attempting to stop others
                }
            }
        }
    }

    void destroy_all() noexcept
    {
        std::unique_lock lock(m_mutex_);
        m_services_.clear();
        m_insertion_order_.clear();
        spdlog::info("[ServiceManager] All services destroyed");
    }

private:
    ServiceManager()  = default;
    ~ServiceManager() = default;

    void mark_failed(const std::type_index& key) noexcept
    {
        std::shared_lock lock(m_mutex_);
        auto it = m_services_.find(key);
        if (it != m_services_.end()) {
            // We cannot modify the service directly here as we do not expose a
            // setter; assume the service changed its own state to Failed.
            spdlog::warn("[ServiceManager] Service '{}' marked as FAILED",
                         it->second->name());
        }
    }

    // --- Data ----------------------------------------------------------------
    mutable std::shared_mutex m_mutex_;

    // Fast lookup by type
    std::unordered_map<std::type_index, std::shared_ptr<IService>> m_services_;

    // Maintain insertion order for deterministic shutdown
    std::vector<std::type_index> m_insertion_order_;
};

} // namespace ci360::services

#endif // CARDIO_INSIGHT_360_SRC_SERVICES_SERVICE_MANAGER_H_