#pragma once
/***************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  Module : scanner_svc
 *  File   : scanner_engine.h
 *
 *  Copyright (c) 2023-2024
 *  Author : FortiLedger360 Core Team <dev@fortiledger.io>
 *
 *  Licensed under the Apache License, Version 2.0 (the “License”); you may not use this file except
 *  in compliance with the License. You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software distributed under the License
 *  is distributed on an “AS IS” BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
 *  or implied. See the License for the specific language governing permissions and limitations under
 *  the License.
 *
 *  Description:
 *      Thread-safe security-scanner engine that orchestrates on-demand and scheduled
 *      vulnerability scans. The engine delegates the actual scanning work to a pluggable
 *      IScanStrategy implementation (Strategy Pattern) while emitting domain events over the
 *      platform’s event bus (Event-Driven Architecture). Metrics are captured via the platform’s
 *      telemetry collector, and the entire lifecycle is driven by a dedicated worker thread.
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fortiledger
{
namespace infra   { class IEventBus;       }   // Event dispatcher (gRPC-based)
namespace config  { class IConfigProvider; }   // Runtime configuration
namespace telemetry{ class IMetricCollector;}  // Prometheus/OpenTelemetry wrapper
} // namespace fortiledger

namespace fortiledger::scanner
{
/*-----------------------------------------------------------------------------------------------
 *  Domain types
 *---------------------------------------------------------------------------------------------*/
enum class ScanSeverity : std::uint8_t
{
    kLow,
    kMedium,
    kHigh,
    kCritical
};

/*!
 * A single vulnerability-scan outcome. Immutable value-object.
 */
struct ScanResult
{
    std::string                                  target;         // Endpoint / asset identifier
    bool                                         success {false};
    std::chrono::system_clock::time_point        timestamp;
    std::vector<std::string>                     vulnerabilities;
    ScanSeverity                                 severity {ScanSeverity::kLow};
};

/*-----------------------------------------------------------------------------------------------
 *  Strategy interface
 *---------------------------------------------------------------------------------------------*/
/*!
 * Abstract strategy for performing vulnerability scans.
 * Concrete strategies may implement deep-packet inspection, cloud-API interrogation, etc.
 */
class IScanStrategy
{
public:
    virtual ~IScanStrategy() = default;

    /*!
     * Performs a scan against the given target.
     * @param target   Fully-qualified identifier (IP, FQDN, resource-ID, …)
     * @param timeout  Optional maximum runtime.
     * @throws std::runtime_error on fatal scanner mis-configuration.
     * @return         Populated ScanResult object.
     */
    virtual ScanResult Scan(const std::string&                            target,
                            std::optional<std::chrono::seconds>          timeout) = 0;
};

/*-----------------------------------------------------------------------------------------------
 *  ScannerEngine
 *---------------------------------------------------------------------------------------------*/
/*!
 * Thread-safe orchestrator for vulnerability scans. Supports on-demand execution, periodic
 * scheduling, graceful cancellation, callback registration, and event emission.
 */
class ScannerEngine final : public std::enable_shared_from_this<ScannerEngine>
{
public:
    using ScanId       = std::string;
    using ScanCallback = std::function<void(const ScanId&, const ScanResult&)>;

    /*-- Factory -----------------------------------------------------------------------------*/
    static std::shared_ptr<ScannerEngine>
    Create(std::shared_ptr<infra::IEventBus>         eventBus,
           std::shared_ptr<config::IConfigProvider>  config,
           std::shared_ptr<telemetry::IMetricCollector> metrics);

    /*-- dtor / Rule-of-Five -----------------------------------------------------------------*/
    ~ScannerEngine() noexcept;

    ScannerEngine(const ScannerEngine&)            = delete;
    ScannerEngine& operator=(const ScannerEngine&) = delete;
    ScannerEngine(ScannerEngine&&)                 = default;
    ScannerEngine& operator=(ScannerEngine&&)      = default;

    /*-- Public API --------------------------------------------------------------------------*/

    /*!
     * Injects a new scan strategy at runtime. If nullptr is supplied, the call is ignored.
     * Thread-safe.
     */
    void ConfigureStrategy(std::unique_ptr<IScanStrategy> strategy);

    /*!
     * Kicks off an immediate scan. Non-blocking.
     * Completion is signalled via: (1) callback; (2) Event-Bus publication.
     * @return Correlation identifier for subsequent cancellation.
     */
    [[nodiscard]]
    ScanId StartScan(const std::string&                       target,
                     std::optional<std::chrono::seconds>      timeout = std::nullopt);

    /*!
     * Attempts to cancel an in-flight scan (best effort).
     */
    void CancelScan(const ScanId& id);

    /*!
     * Registers a periodic scan. The Scheduler owns the lifecycle until UnscheduleScan is called.
     * @return Correlation identifier for future management.
     */
    [[nodiscard]]
    ScanId ScheduleScan(const std::string&                     target,
                        std::chrono::seconds                   interval,
                        std::optional<std::chrono::seconds>    timeout = std::nullopt);

    /*!
     * Removes a previously registered periodic scan.
     */
    void UnscheduleScan(const ScanId& id);

    /*!
     * Registers (replaces) a callback that will be invoked on every scan completion.
     */
    void RegisterCallback(ScanCallback cb);

    /*!
     * Gracefully shuts down the worker thread and aborts pending work.
     * Blocking.
     */
    void Shutdown() noexcept;

private:
    /*-- Internal ---------------------------------------------------------------------------*/
    explicit ScannerEngine(std::shared_ptr<infra::IEventBus>        eventBus,
                           std::shared_ptr<config::IConfigProvider> config,
                           std::shared_ptr<telemetry::IMetricCollector> metrics);

    void WorkerThread();        // Main loop
    ScanId GenerateId();        // Thread-safe monotonic id generator

    /*-- Data structures ---------------------------------------------------------------------*/
    struct ScheduledJob
    {
        ScanId                                     id;
        std::string                                target;
        std::chrono::seconds                       interval;
        std::chrono::system_clock::time_point      next_run;
        std::optional<std::chrono::seconds>        timeout;
        std::atomic<bool>                          cancelled{false};
    };

    /*-- Members ----------------------------------------------------------------------------*/
    std::atomic<bool>                                               running_{true};

    /* Strategy */
    std::unique_ptr<IScanStrategy>                                  strategy_;
    mutable std::mutex                                              strategy_mtx_;

    /* Scheduler */
    std::unordered_map<ScanId, std::shared_ptr<ScheduledJob>>       scheduled_;
    mutable std::mutex                                              scheduled_mtx_;

    /* Concurrency */
    std::thread                                                     worker_;
    std::condition_variable                                         cv_;

    /* Callbacks */
    ScanCallback                                                    callback_{};
    mutable std::mutex                                              cb_mtx_;

    /* External services */
    std::shared_ptr<infra::IEventBus>                               event_bus_;
    std::shared_ptr<config::IConfigProvider>                        config_;
    std::shared_ptr<telemetry::IMetricCollector>                    metrics_;

    /* Utils */
    std::atomic<std::uint64_t>                                      id_sequence_{0};
};

/*-----------------------------------------------------------------------------------------------
 *  Inline / constexpr implementations (header-only helpers)
 *---------------------------------------------------------------------------------------------*/

inline std::shared_ptr<ScannerEngine>
ScannerEngine::Create(std::shared_ptr<infra::IEventBus>             eventBus,
                      std::shared_ptr<config::IConfigProvider>      config,
                      std::shared_ptr<telemetry::IMetricCollector>  metrics)
{
    return std::shared_ptr<ScannerEngine>(
        new ScannerEngine(std::move(eventBus), std::move(config), std::move(metrics)));
}

} // namespace fortiledger::scanner