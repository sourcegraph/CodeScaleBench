#pragma once
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File     : FortiLedger360/src/services/config_manager_svc/service_impl.h
 *  License  : Proprietary, © 2024 FortiLedger360 Ltd.  All Rights Reserved.
 *
 *  Description:
 *      Concrete implementation of the Config-Manager service.  This component
 *      is responsible for:
 *          * Storing, validating and applying tenant-specific configurations
 *          * Emitting domain events when configuration-drift is detected
 *          * Acting as an Observer & Subject in the event-driven pipeline
 *
 *      The service implements a thread-safe in-memory cache, publishes domain
 *      events to the core Event-Bus, and exposes a gRPC surface defined in
 *      proto/config_manager.proto (see IConfigManagerService).
 *
 *  Notes:
 *      Only the public header is provided here because downstream components
 *      rely on inline definitions for performance-critical paths such as
 *      cache look-ups and optimistic read-locks.  Non-inline heavy logic is
 *      separated into `service_impl.cpp` in order to keep compile-times under
 *      control.
 */

#include <atomic>
#include <chrono>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "domain/config_bundle.h"          // Domain-level configuration object
#include "infra/event_bus/i_event_bus.h"   // Async Event-Bus interface
#include "infra/logging/logger.h"          // Unified structured logger
#include "services/config_manager_svc/i_service.h"  // Public service interface

namespace fortiledger360::services::config_manager {

/* =======================================================
 *  Exception Hierarchy
 * =======================================================
 */
class ConfigManagerError : public std::runtime_error {
public:
    explicit ConfigManagerError(std::string msg, std::string tenant = {})
        : std::runtime_error{std::move(msg)}, tenant_id_{std::move(tenant)} {}

    [[nodiscard]] const std::string& tenant_id() const noexcept { return tenant_id_; }

private:
    std::string tenant_id_;
};

/**
 *  Thrown when configuration fails semantic validation
 */
class InvalidConfigurationError final : public ConfigManagerError {
public:
    inline InvalidConfigurationError(std::string msg, std::string tenant = {})
        : ConfigManagerError{std::move(msg), std::move(tenant)} {}
};

/**
 *  Thrown when an I/O error occurs while persisting or loading configuration
 */
class ConfigurationPersistenceError final : public ConfigManagerError {
public:
    inline ConfigurationPersistenceError(std::string msg, std::string tenant = {})
        : ConfigManagerError{std::move(msg), std::move(tenant)} {}
};

/* =======================================================
 *  Forward Declarations
 * =======================================================
 */
namespace details {
    // Internal helper for input validation and sanitisation
    class ConfigValidator;
}

/* =======================================================
 *  ConfigManagerServiceImpl
 * =======================================================
 */
class ConfigManagerServiceImpl final :
        public IConfigManagerService,
        public std::enable_shared_from_this<ConfigManagerServiceImpl> {
public:
    using Ptr = std::shared_ptr<ConfigManagerServiceImpl>;
    using Clock = std::chrono::steady_clock;

    /**
     * Constructs a Config-Manager service instance
     *
     * @param config_root    Filesystem root where per-tenant config files live
     * @param event_bus      Handle to the central Event-Bus (non-null)
     * @param logger         Structured logger instance (optional)
     */
    explicit ConfigManagerServiceImpl(std::filesystem::path   config_root,
                                      infra::event_bus::IEventBus::Ptr event_bus,
                                      infra::logging::Logger::Ptr       logger = nullptr);

    ~ConfigManagerServiceImpl() override;

    /* -------------------------------
     * IConfigManagerService overrides
     * -------------------------------
     */
    domain::ConfigBundle
    get_active_configuration(const std::string& tenant_id) const override;

    std::future<void>
    apply_configuration(const std::string&          tenant_id,
                        domain::ConfigBundle        new_config,
                        ApplyMode                   mode = ApplyMode::kTransactional) override;

    void
    subscribe(observer::IObserver<ConfigEvent>::Ptr observer) override;

    void
    shutdown() noexcept override;

    [[nodiscard]] bool is_shutdown() const noexcept override { return shutdown_.load(); }

    /* -------------------------------
     * Non-interface API
     * -------------------------------
     */

    /**
     *  Convenience helper that asynchronously reloads configuration for all tenants.
     *  A full reload is typically triggered on bootstrap or when an external SCM
     *  system notifies us about a commit to the config repository.
     *
     *  @throws ConfigurationPersistenceError on I/O failure.
     */
    std::future<void> reload_all_async();

    /**
     * Forces an in-memory cache evict for the specified tenant.
     * Thread-safe and O(1).
     */
    void evict_tenant(const std::string& tenant_id);

    /**
     *  Returns the monotonic timestamp of the last full reload.
     */
    [[nodiscard]] Clock::time_point last_reload() const noexcept;

private:
    /* -------------------------------
     *  Helper / private members
     * -------------------------------
     */

    // Guard reads/writes to `in_memory_cache_`
    mutable std::shared_mutex cache_mutex_;

    // tenant-id -> ConfigBundle
    std::unordered_map<std::string, domain::ConfigBundle> in_memory_cache_;

    // Observers interested in ConfigEvents
    mutable std::mutex observers_mutex_;
    std::vector<std::weak_ptr<observer::IObserver<ConfigEvent>>> observers_;

    // External infrastructure
    const std::filesystem::path            config_root_;
    const infra::event_bus::IEventBus::Ptr event_bus_;
    const infra::logging::Logger::Ptr      logger_;

    // Internal helper for semantic validation
    std::unique_ptr<details::ConfigValidator> validator_;

    // Whether shutdown() has been called
    std::atomic_bool shutdown_{false};

    // Last time reload_all_async() completed
    std::atomic<Clock::time_point> last_reload_timestamp_;

private:
    // Performs a blocking reload for a single tenant
    void reload_tenant_locked(const std::string& tenant_id, std::unique_lock<std::shared_mutex>& guard);

    // Emits ConfigEvent::kDriftDetected when incoming config differs from cached
    void publish_drift_event(const std::string& tenant_id,
                             const domain::ConfigBundle& old_cfg,
                             const domain::ConfigBundle& new_cfg);

    // Notifies observers in a fire-and-forget fashion
    void notify_observers(const ConfigEvent& evt);

    // Helper for logging with fallback
    void log(infra::logging::LogLevel lvl, std::string_view msg,
             const std::string& tenant_id = {}) const noexcept;
};

/* =======================================================
 *  Inline / Template definitions
 * =======================================================
 */

inline fortiledger360::services::config_manager::ConfigManagerServiceImpl::
ConfigManagerServiceImpl(std::filesystem::path   config_root,
                         infra::event_bus::IEventBus::Ptr event_bus,
                         infra::logging::Logger::Ptr      logger)
    : config_root_{std::move(config_root)}
    , event_bus_{std::move(event_bus)}
    , logger_{std::move(logger)}
{
    if (!event_bus_) {
        throw ConfigManagerError{"EventBus pointer must not be null"};
    }
    if (!std::filesystem::exists(config_root_)) {
        throw ConfigManagerError{
            "Config root path does not exist: " + config_root_.string()};
    }

    validator_ = std::make_unique<details::ConfigValidator>();
    last_reload_timestamp_.store(Clock::now());

    log(infra::logging::LogLevel::kInfo,
        "ConfigManagerService instantiated", {});
}

inline fortiledger360::services::config_manager::ConfigManagerServiceImpl::
~ConfigManagerServiceImpl()
{
    try {
        shutdown();
    } catch (...) {
        // Destructors must not throw
    }
}

inline domain::ConfigBundle
fortiledger360::services::config_manager::ConfigManagerServiceImpl::
get_active_configuration(const std::string& tenant_id) const
{
    std::shared_lock guard{cache_mutex_};
    const auto it = in_memory_cache_.find(tenant_id);
    if (it == in_memory_cache_.end()) {
        throw ConfigManagerError{"No active configuration for tenant", tenant_id};
    }
    return it->second; // copy elision
}

inline void
fortiledger360::services::config_manager::ConfigManagerServiceImpl::
evict_tenant(const std::string& tenant_id)
{
    std::unique_lock guard{cache_mutex_};
    auto erased = in_memory_cache_.erase(tenant_id);
    if (erased > 0) {
        log(infra::logging::LogLevel::kDebug,
            "Evicted configuration from cache", tenant_id);
    }
}

inline fortiledger360::services::config_manager::ConfigManagerServiceImpl::Clock::time_point
fortiledger360::services::config_manager::ConfigManagerServiceImpl::
last_reload() const noexcept
{
    return last_reload_timestamp_.load();
}

inline void
fortiledger360::services::config_manager::ConfigManagerServiceImpl::
log(infra::logging::LogLevel lvl, std::string_view msg, const std::string& tenant_id) const noexcept
{
    if (logger_) {
        logger_->log(lvl, "[ConfigManager] " + std::string{msg}, tenant_id);
    }
}

} // namespace fortiledger360::services::config_manager