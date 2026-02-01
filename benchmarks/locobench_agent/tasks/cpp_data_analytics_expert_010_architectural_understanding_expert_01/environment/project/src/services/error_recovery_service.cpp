```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:    cardio_insight_360/src/services/error_recovery_service.cpp
 *
 *  Purpose: Centralised service responsible for capturing, persisting
 *           and automatically recovering from runtime faults that occur
 *           across the analytics engine (ETL, Streaming, Visualisation).
 *
 *  Notes:
 *   • Operates as an in-process “pseudo-microservice” but remains part of
 *     the monolithic binary for simplified deployment and certification.
 *   • Subscribes to the internal Event-Bus for FaultEvent messages.
 *   • Persists fault metadata to durable storage for auditability.
 *   • Applies a configurable retry strategy (exponential back-off).
 *   • Emits real-time metrics to the Monitoring subsystem.
 *
 *  Copyright:
 *    © 2024 CardioInsight Inc. – All rights reserved.
 */

#include "services/error_recovery_service.hpp"           // Own interface
#include "core/event_bus.hpp"                             // Event-Bus abstraction
#include "core/events/fault_event.hpp"                    // Domain event type
#include "core/etl/job_descriptor.hpp"                    // Job identifiers
#include "storage/datalake/datalake_facade.hpp"           // Persistent store
#include "utils/concurrency/thread_name.hpp"              // Thread affinity helper
#include "utils/metrics/metrics_registry.hpp"             // Observer pattern
#include "utils/time/iso8601.hpp"                         // Time utilities

#include <nlohmann/json.hpp>                              // For JSON serialisation
#include <spdlog/spdlog.h>                                // Structured logging
#include <tbb/task_group.h>                               // Parallel retry group

#include <atomic>
#include <chrono>
#include <filesystem>
#include <future>
#include <random>
#include <thread>

using namespace std::chrono_literals;
namespace fs = std::filesystem;
using json = nlohmann::json;

namespace ci360::services {

//---------------------------------------------------------------------------------------------------------------------
//  RetryPolicy – data object encapsulating retry parameters
//---------------------------------------------------------------------------------------------------------------------

namespace
{
    struct RetryPolicy
    {
        uint32_t  maxAttempts      {5};
        std::chrono::milliseconds initialBackoff {500ms};
        std::chrono::milliseconds maxBackoff     {30s};
        double     jitterFactor    {0.25};   // ±25 % randomisation

        std::chrono::milliseconds nextBackoff(uint32_t attempt) const noexcept
        {
            using dur_ms = std::chrono::milliseconds;

            // Exponential back-off: initial × 2^(attempt-1)
            auto raw = initialBackoff * static_cast<int>(1u << (attempt - 1u));
            raw = std::min(raw, maxBackoff);

            // Add jitter to prevent thundering-herd
            std::uniform_real_distribution<double> dist{-jitterFactor, jitterFactor};
            static thread_local std::mt19937 rng{std::random_device{}()};
            auto jitter = raw * dist(rng);
            return dur_ms(static_cast<dur_ms::rep>(raw.count() + jitter.count()));
        }
    };
} // anonymous namespace

//---------------------------------------------------------------------------------------------------------------------
//  ErrorRecoveryService – implementation
//---------------------------------------------------------------------------------------------------------------------

ErrorRecoveryService::ErrorRecoveryService(
        core::EventBus&                                  eventBus,
        storage::datalake::DataLakeFacade&               dataLake,
        utils::metrics::MetricsRegistry&                 metricsRegistry)
    : _eventBus{eventBus}
    , _dataLake{dataLake}
    , _metrics{metricsRegistry.createFamily(
          "ci360_error_recovery",
          "Error recovery metrics for CardioInsight360")}
    , _retryThreads{std::thread::hardware_concurrency()}
{
    _faultCounter = _metrics->addCounter("fault_total",
                                         "Number of fault events received");
    _retryCounter = _metrics->addCounter("retry_total",
                                         "Number of retry attempts executed");
    _successGauge = _metrics->addGauge("inflight_retries",
                                       "Number of retries currently active");

    // Pre-create directory for persisted fault metadata
    _faultDir = (_dataLake.root() / "faults").string();
    fs::create_directories(_faultDir);

    // Subscribe to FaultEvent channel on the Event-Bus
    _subscription = _eventBus.subscribe<core::events::FaultEvent>(
        [this](const core::events::FaultEvent& ev) { this->onFault(ev); });

    spdlog::info("[ErrorRecoveryService] Online – listening for fault events");
}

//---------------------------------------------------------------------------------------------------------------------

ErrorRecoveryService::~ErrorRecoveryService()
{
    _stopped.store(true);
    _subscription.cancel();    // Detach from Event-Bus

    _retryThreads.wait();
    spdlog::info("[ErrorRecoveryService] Shutdown complete.");
}

//---------------------------------------------------------------------------------------------------------------------

void ErrorRecoveryService::onFault(const core::events::FaultEvent& ev)
{
    _faultCounter->increment();
    spdlog::warn("[ErrorRecoveryService] Fault received: job_id={}, reason={}",
                 ev.jobId, ev.reason);

    // Persist fault metadata for audit/reprocessing
    persistFaultMetadata(ev);

    // Enqueue asynchronous retry attempt
    _retryThreads.run([this, event = ev] {
        utils::concurrency::ThreadName::set("ci360_retry_worker");
        attemptRecovery(event);
    });
}

//---------------------------------------------------------------------------------------------------------------------

void ErrorRecoveryService::persistFaultMetadata(const core::events::FaultEvent& ev) const
{
    json j;
    j["timestamp"]  = utils::time::to_iso8601(ev.timestamp);
    j["job_id"]     = ev.jobId.to_string();
    j["module"]     = ev.module;
    j["severity"]   = ev.severity_string();
    j["reason"]     = ev.reason;
    j["payload"]    = ev.payload;  // Arbitrary JSON with context

    try
    {
        auto path = fs::path(_faultDir) /
                    fmt::format("{}_{}.json", ev.jobId.to_string(), ev.timestamp.time_since_epoch().count());
        std::ofstream file(path);
        file << j.dump(4);
    }
    catch (const std::exception& ex)
    {
        // Persistence failures should not cascade
        spdlog::error("[ErrorRecoveryService] Failed to persist fault metadata: {}", ex.what());
    }
}

//---------------------------------------------------------------------------------------------------------------------

void ErrorRecoveryService::attemptRecovery(const core::events::FaultEvent& ev)
{
    RetryPolicy policy{};
    uint32_t    attempt = 0;

    _successGauge->increment();

    while (!_stopped.load() && attempt < policy.maxAttempts)
    {
        ++attempt;
        _retryCounter->increment();
        spdlog::info("[ErrorRecoveryService] Attempting recovery ({}/{}) for job_id={}",
                     attempt, policy.maxAttempts, ev.jobId);

        try
        {
            // Ask the Job-Scheduler to re-queue the failed job
            auto future = core::scheduler::Scheduler::instance().resubmitJob(ev.jobId);

            // Block (with timeout) waiting for scheduler acceptance
            if (future.wait_for(2s) == std::future_status::ready)
            {
                auto status = future.get();
                if (status == core::scheduler::ResubmitStatus::ACCEPTED)
                {
                    spdlog::info("[ErrorRecoveryService] Recovery succeeded for job_id={}", ev.jobId);
                    _successGauge->decrement();
                    return;
                }
            }
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[ErrorRecoveryService] Recovery attempt failed: {}", ex.what());
        }

        // Wait before next attempt (exponential back-off with jitter)
        auto backoff = policy.nextBackoff(attempt);
        spdlog::debug("[ErrorRecoveryService] Backing off for {} ms before next retry", backoff.count());
        std::this_thread::sleep_for(backoff);
    }

    _successGauge->decrement();
    spdlog::error("[ErrorRecoveryService] Exhausted all retry attempts for job_id={}", ev.jobId);
}

//---------------------------------------------------------------------------------------------------------------------

} // namespace ci360::services
```