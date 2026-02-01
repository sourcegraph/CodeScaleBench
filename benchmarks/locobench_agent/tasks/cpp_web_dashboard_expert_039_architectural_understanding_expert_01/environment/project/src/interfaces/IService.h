#pragma once
/**********************************************************************************************************************
 *  MosaicBoard Studio – IService.h
 *  Copyright (c) MosaicBoard
 *
 *  Licensed under the MIT License. See LICENSE file in the project root for full license information.
 *
 *  Description:
 *      Base interface for any long-living backend service in MosaicBoard Studio. Services wrap external systems
 *      (databases, payment providers, search engines, message brokers…) and expose a thin, synchronous façade
 *      to the rest of the application. Implementations are *hot-swappable* shared libraries that get loaded by the
 *      service locator at runtime.
 *
 *  Key Characteristics:
 *      • Thread-safe lifecycle management (start/stop)
 *      • Cheap health checks for “circuit-breaker” style routing
 *      • Minimal knowledge of concrete dependencies (DI-friendly)
 *      • Self-describing metadata for runtime diagnostics
 *
 *********************************************************************************************************************/

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <system_error>
#include <type_traits>

namespace mbs         // MosaicBoard Studio root namespace
{
namespace services   // all service layer abstractions live here
{

/*~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 | Forward declarations
 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~*/
class IEventBus;      // Real-time event bus used for pub/sub across the application.

/*~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 | Service-specific types
 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~*/

/**
 * ServiceState – coarse-grained lifecycle states that every service must publish.
 */
enum class ServiceState : std::uint8_t
{
    Stopped = 0,
    Starting,
    Running,
    Stopping,
    Error
};

/**
 * HealthReport – immutable snapshot of a service’s health that can be emitted on demand or pushed over the event bus.
 */
struct HealthReport
{
    ServiceState                               state          { ServiceState::Stopped };
    std::string                                message        { };     // human-readable hint (e.g. “DB unreachable”)
    std::chrono::system_clock::time_point      timestamp      { std::chrono::system_clock::now() };

    [[nodiscard]] bool ok() const noexcept
    {
        return state == ServiceState::Running;
    }
};

/**
 * ServiceException – common ancestor for all service-level issues. Wraps std::system_error to keep errno values intact.
 *
 * Rationale:
 *     We want to preserve platform-specific error codes (EACCES, ECONNREFUSED, …) while adding semantic meaning.
 */
class ServiceException : public std::system_error
{
public:
    template <typename Ec>
    explicit ServiceException(Ec ec,
                              const std::string& what_arg,
                              std::string_view service_name = {})
        : std::system_error(make_error_code(ec), what_arg)
        , m_service{ service_name }
    {}

    [[nodiscard]] std::string_view service() const noexcept { return m_service; }

private:
    std::string m_service;
};


/*~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 | IService – abstract base class
 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~*/
/**
 * Pure virtual façade every concrete service must implement.
 *
 * Thread-Safety Contract:
 *     • start() & stop() must be *idempotent* (multiple calls have no additional effect)
 *     • isRunning() & health() must be *lock-free* and *wait-free* where feasible
 *
 * Error Handling Strategy:
 *     • Business logic failures SHOULD manifest as ServiceException (or subclasses)
 *     • Fatal resource failures (e.g., bad_alloc) may propagate as-is
 */
class IService
{
public:
    virtual ~IService() = default;

    /*--------------------------------------------------------------------------------------------------------------
     | Metadata
     *-------------------------------------------------------------------------------------------------------------*/
    /**
     * Unique, stable identifier for this service (e.g. "payment-gateway", "redis-cache").
     */
    [[nodiscard]] virtual std::string_view id() const noexcept = 0;

    /**
     * Human-friendly version string (semantic versioning recommended).
     */
    [[nodiscard]] virtual std::string_view version() const noexcept = 0;

    /*--------------------------------------------------------------------------------------------------------------
     | Dependency injection
     *-------------------------------------------------------------------------------------------------------------*/
    /**
     * Inject a shared event bus for inter-service communication. Implementation may ignore if not supported.
     *
     * Note:
     *     The lifetime of the event bus is guaranteed to outlive any service for the duration of the process.
     */
    virtual void attachEventBus(std::shared_ptr<IEventBus> bus) = 0;

    /*--------------------------------------------------------------------------------------------------------------
     | Lifecycle management
     *-------------------------------------------------------------------------------------------------------------*/
    /**
     * Start the service. Blocks until the service is operational OR throws ServiceException on unrecoverable error.
     */
    virtual void start() = 0;

    /**
     * Initiates a graceful shutdown. Blocks until all resources are released.
     * Implementations must be *no-throw*.
     */
    virtual void stop() noexcept = 0;

    /**
     * Returns true if the service is currently in *Running* state.
     *
     * Thread-safe and non-blocking.
     */
    [[nodiscard]] virtual bool isRunning() const noexcept = 0;

    /*--------------------------------------------------------------------------------------------------------------
     | Operational insight
     *-------------------------------------------------------------------------------------------------------------*/
    /**
     * Returns a lightweight, read-only health snapshot usable by load-balancers and circuit-breakers.
     */
    [[nodiscard]] virtual HealthReport health() const noexcept = 0;

    /**
     * Optional opaque diagnostics blob (e.g., JSON, YAML, …) for UI introspection/metrics dashboards.
     * Defaults to empty.
     */
    [[nodiscard]] virtual std::optional<std::string> diagnostics() const { return std::nullopt; }

    /*--------------------------------------------------------------------------------------------------------------
     | Deleted copy/assignment
     *-------------------------------------------------------------------------------------------------------------*/
    IService(const IService&)            = delete;
    IService& operator=(const IService&) = delete;
    IService(IService&&)                 = delete;
    IService& operator=(IService&&)      = delete;

protected:
    IService() = default;   // protected to prevent direct instantiation
};

using IServicePtr = std::shared_ptr<IService>;

} // namespace services
} // namespace mbs