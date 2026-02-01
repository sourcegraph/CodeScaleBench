#pragma once
/**
 * @file visualization_service.h
 * @author
 * @brief Service-level façade that orchestrates real-time and historical data
 *        visualization pipelines inside CardioInsight360.
 *
 *  Responsibilities
 *  -----------------
 *  • Subscribes to the in-process Kafka Event-Bus for low-latency streaming
 *    updates (vital signs, alarms, quality-checks, etc.).
 *  • Dispatches rendering jobs to one of several pluggable “visualization
 *    providers” (e.g., SVG, OpenGL, REST/JSON, WebSocket).
 *  • Caches and coalesces high-frequency data points to avoid overwhelming
 *    downstream dashboards while preserving fidelity.
 *  • Persists rendered artefacts or intermediate state in the Data-Lake when
 *    historical mode is requested.
 *  • Exposes a thread-safe public API to the rest of the monolith; avoids any
 *    UI framework dependencies so unit-tests can run head-less.
 *
 *  Thread-Safety
 *  -------------
 *  All public member functions are thread-safe.  Internally, the class relies
 *  on a combination of `std::mutex`, `std::atomic`, and the single-writer rule
 *  to protect shared state.
 *
 *  Exception Safety
 *  ----------------
 *  Strong guarantee for public APIs: if an exception is thrown, observable
 *  state remains unchanged.  All recoverable errors are translated into the
 *  Error-Recovery microservice via an Observer hook.
 */

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "common/logger.h"               // Lightweight spdlog façade
#include "event_bus/event_bus.h"         // In-process Kafka wrapper
#include "storage/data_lake_facade.h"    // Parquet persistence abstraction
#include "telemetry/metrics_collector.h" // Observer pattern

namespace cardioinsight360::services {

// Forward declarations for heavy types we do not want to include in the header
class RenderingContext;

/**
 * @enum VisualizationMode
 * @brief Determines the execution semantics for the visualization request.
 */
enum class VisualizationMode : uint8_t
{
    Realtime,   ///< Continuous stream; low-latency.
    Historical  ///< Batch rendering for archived data.
};

/**
 * @struct VisualizationRequest
 * @brief Serializable DTO passed from UI controllers or REST gateway.
 */
struct VisualizationRequest
{
    std::string          patient_id;           ///< Unique patient identifier.
    std::vector<std::string> signal_ids;       ///< List of signals (ECG-lead, BP, etc.).
    std::chrono::system_clock::time_point from;
    std::chrono::system_clock::time_point to;
    VisualizationMode     mode { VisualizationMode::Realtime };
    std::optional<std::string> custom_style;   ///< Optional theme/style JSON.

    bool isValid() const noexcept;
};

/**
 * @interface IVisualizationProvider
 * @brief Strategy interface used by VisualizationService to support multiple
 *        rendering backends (SVG, OpenGL, etc.).
 */
class IVisualizationProvider
{
public:
    using Ptr = std::shared_ptr<IVisualizationProvider>;
    virtual ~IVisualizationProvider() = default;

    /**
     * Renders the supplied request into the given rendering context.
     * Must be thread-safe.
     */
    virtual void render(const VisualizationRequest &request,
                        RenderingContext          &ctx) = 0;

    /**
     * Returns a short, unique identifier (e.g., "svg", "opengl").
     */
    [[nodiscard]] virtual std::string_view id() const noexcept = 0;
};

/**
 * @class VisualizationService
 * @brief High-level orchestrator encapsulating visualization responsibilities.
 */
class VisualizationService : public std::enable_shared_from_this<VisualizationService>
{
public:
    /**
     * Ctor/Dtor: accept heavyweight collaborators through DI.
     */
    VisualizationService(std::shared_ptr<eventbus::EventBus>           event_bus,
                         std::shared_ptr<storage::DataLakeFacade>      data_lake,
                         std::shared_ptr<telemetry::MetricsCollector>  metrics,
                         std::shared_ptr<logging::Logger>              logger);

    ~VisualizationService();

    // Non-copyable / movable
    VisualizationService(const VisualizationService &)            = delete;
    VisualizationService &operator=(const VisualizationService &) = delete;
    VisualizationService(VisualizationService &&)                 = delete;
    VisualizationService &operator=(VisualizationService &&)      = delete;

    /**
     * Starts all internal worker threads and subscriptions.
     * Idempotent.
     */
    void start();

    /**
     * Gracefully shuts down the service and waits for in-flight jobs.
     * Idempotent; safe to call from dtor.
     */
    void stop();

    /**
     * Registers a visualization provider.  If a provider with the same id()
     * already exists, the call is ignored and `false` is returned.
     */
    bool registerProvider(const IVisualizationProvider::Ptr &provider);

    /**
     * Removes a provider by id.
     */
    bool unregisterProvider(std::string_view id) noexcept;

    /**
     * Client-facing API: schedules a visualization request for execution.
     * Returns a future that becomes ready when the render completes.
     *
     * Strong exception guarantee.
     */
    std::future<void> visualize(VisualizationRequest request);

    /**
     * Shortcut for real-time mode that uses “best effort” semantics and never
     * throws. Suitable for fire-and-forget use-cases (e.g., alarm lamps).
     *
     * Returns `true` if scheduling succeeded.
     */
    bool tryVisualizeRealtime(std::string patient_id,
                              std::vector<std::string> signals);

    /**
     * Runtime info for diagnostics/UI panels.
     */
    std::vector<std::string> activeProviderIds() const;

private:
    // Internal helpers --------------------------------------------------------

    void consumeEventLoop(); // Long-running Kafka consumer thread.
    void processRequest(VisualizationRequest request);

    IVisualizationProvider::Ptr pickProvider(const VisualizationRequest &req) const;

    // Collaborators (shared ownership) ---------------------------------------

    const std::shared_ptr<eventbus::EventBus>          event_bus_;
    const std::shared_ptr<storage::DataLakeFacade>     data_lake_;
    const std::shared_ptr<telemetry::MetricsCollector> metrics_;
    const std::shared_ptr<logging::Logger>             log_;

    // Provider registry (ID -> provider) -------------------------------------

    mutable std::shared_mutex                             providers_mx_;
    std::unordered_map<std::string, IVisualizationProvider::Ptr> providers_;

    // Background worker thread -----------------------------------------------

    std::atomic<bool>         running_ { false };
    std::thread               consumer_thread_;

    // Serialization queue -----------------------------------------------------

    struct RequestItem
    {
        VisualizationRequest                    request;
        std::promise<void>                      promise;
    };

    std::mutex                          queue_mx_;
    std::condition_variable_any         queue_cv_;
    std::vector<std::unique_ptr<RequestItem>> request_queue_;
};

/* ========================================================================== */
/* Inline/constexpr implementations                                           */
/* ========================================================================== */

inline bool VisualizationRequest::isValid() const noexcept
{
    return !patient_id.empty() && !signal_ids.empty() && from <= to;
}

} // namespace cardioinsight360::services
