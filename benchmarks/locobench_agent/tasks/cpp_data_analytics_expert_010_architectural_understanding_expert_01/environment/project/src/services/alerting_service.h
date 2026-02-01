#pragma once
/**
 * cardio_insight_360/src/services/alerting_service.h
 *
 * CardioInsight360 – Unified Healthcare Analytics Engine
 *
 * An in-process alerting subsystem that evaluates vital-sign samples
 * against configurable thresholds and dispatches alerts to registered
 * sinks (pager, e-mail, nurse-station dashboard, etc.).
 *
 * This header provides a header-only implementation in order to make
 * unit-testing and integration into plugin-like modules easier.  The
 * interface is thread-safe and designed for low-latency in-memory
 * operation; heavy I/O should be implemented in downstream sinks.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <fmt/format.h>     // Lightweight string-formatting
#include <spdlog/spdlog.h>  // Production-grade logging

namespace cardio_insight_360::services
{

/**
 * Enumerates alert severity levels.
 */
enum class Severity
{
    INFO,
    WARNING,
    CRITICAL
};

/**
 * Domain object that represents an alert emitted by the analytics engine.
 */
struct Alert
{
    std::string patient_id;   // Medical-record or device identifier
    std::string metric;       // Human-readable metric name (HR, SpO2, …)
    double      value{};      // Observed value
    double      threshold_min{};
    double      threshold_max{};
    Severity    severity{Severity::INFO};
    std::chrono::system_clock::time_point ts{std::chrono::system_clock::now()};
    std::string message;      // Pre-formatted, user-friendly description

    /**
     * Serialises the alert into a single-line representation suitable
     * for logs or quick debugging.
     */
    [[nodiscard]] std::string to_string() const
    {
        using std::chrono::duration_cast;
        using std::chrono::milliseconds;

        auto epoch_ms = duration_cast<milliseconds>(ts.time_since_epoch()).count();

        return fmt::format(
            "[{}] Patient={} Metric={} Value={:.2f} Range=[{:.2f},{:.2f}] Sev={} {}",
            epoch_ms,
            patient_id,
            metric,
            value,
            threshold_min,
            threshold_max,
            static_cast<int>(severity),
            message);
    }
};

/**
 * Abstract sink interface — any component interested in alerts must
 * implement this contract and register with AlertingService.
 *
 * Implementations must be thread-safe; handleAlert() may be invoked
 * concurrently from multiple threads.
 */
class AbstractAlertSink
{
public:
    virtual ~AbstractAlertSink() = default;

    /**
     * Unique sink identifier used for registration and diagnostics.
     */
    [[nodiscard]] virtual std::string id() const = 0;

    /**
     * Callback invoked for every alert that passes through the service.
     */
    virtual void handleAlert(const Alert& alert) = 0;
};

/**
 * Thread-safe, low-latency alerting service.
 *
 * Typical usage:
 *   auto svc = AlertingService{};
 *   svc.setThreshold("HR", {40, 180, Severity::CRITICAL});
 *   svc.registerSink(std::make_shared<PagerSink>(…));
 *   svc.ingest({patient_id, "HR", 190, now});
 */
class AlertingService final
{
public:
    AlertingService()  = default;
    ~AlertingService() = default;

    AlertingService(const AlertingService&)            = delete;
    AlertingService& operator=(const AlertingService&) = delete;

    /**
     * Represents an inclusive range and its associated alert severity.
     */
    struct Range
    {
        double   min{};
        double   max{};
        Severity severity{Severity::CRITICAL};
    };

    /**
     * Incoming sample structure (minimal representation; the full
     * analytics engine uses richer protobuf models, but those are
     * intentionally decoupled from this low-level dependency).
     */
    struct VitalSign
    {
        std::string                               patient_id;
        std::string                               metric;
        double                                    value{};
        std::chrono::system_clock::time_point     ts{std::chrono::system_clock::now()};
    };

    /* ---------------- Sink management ---------------- */

    /**
     * Registers a new sink.
     * Throws std::invalid_argument if sink is null or duplicate id.
     */
    void registerSink(const std::shared_ptr<AbstractAlertSink>& sink)
    {
        if (!sink)
        {
            throw std::invalid_argument("AlertingService::registerSink – sink must not be null");
        }

        const auto& sink_id = sink->id();
        if (sink_id.empty())
        {
            throw std::invalid_argument("AlertingService::registerSink – sink id must not be empty");
        }

        std::unique_lock lock{sinks_mtx_};
        if (sinks_.contains(sink_id))
        {
            throw std::invalid_argument(fmt::format(
                "AlertingService::registerSink – sink with id '{}' already registered", sink_id));
        }

        sinks_.emplace(sink_id, sink);
        spdlog::info("AlertingService: registered sink '{}'", sink_id);
    }

    /**
     * Unregisters a sink by id; silently no-ops if unknown.
     */
    void unregisterSink(const std::string& sink_id)
    {
        std::unique_lock lock{sinks_mtx_};
        if (sinks_.erase(sink_id))
        {
            spdlog::info("AlertingService: unregistered sink '{}'", sink_id);
        }
    }

    /* ---------------- Threshold management ---------------- */

    /**
     * Adds or updates a threshold for a given metric.
     */
    void setThreshold(const std::string& metric, Range range)
    {
        if (metric.empty()) { throw std::invalid_argument("metric must not be empty"); }
        if (range.min > range.max)
        {
            throw std::invalid_argument("range.min must be <= range.max");
        }

        {
            std::unique_lock lock{thresh_mtx_};
            thresholds_[metric] = range;
        }
        spdlog::info("AlertingService: threshold for '{}' set to [{:.2f}, {:.2f}]",
                     metric, range.min, range.max);
    }

    /**
     * Removes a threshold.  If none exists, the call is ignored.
     */
    void clearThreshold(const std::string& metric)
    {
        std::unique_lock lock{thresh_mtx_};
        thresholds_.erase(metric);
    }

    /* ---------------- Ingestion path ---------------- */

    /**
     * Streams a sample into the alerting engine; evaluates it against
     * the current threshold map and emits an alert if out-of-range.
     */
    void ingest(const VitalSign& vs)
    {
        ++samples_ingested_;

        Range range;
        {
            // Fast read-path: acquire shared lock only
            std::shared_lock lock{thresh_mtx_};
            auto             it = thresholds_.find(vs.metric);
            if (it == thresholds_.cend()) { return; }  // Metric not monitored
            range = it->second;
        }

        if (vs.value < range.min || vs.value > range.max)
        {
            Alert alert;
            alert.patient_id    = vs.patient_id;
            alert.metric        = vs.metric;
            alert.value         = vs.value;
            alert.threshold_min = range.min;
            alert.threshold_max = range.max;
            alert.severity      = range.severity;
            alert.ts            = vs.ts;
            alert.message       = fmt::format("{} out of range ({:.2f} ∉ [{:.2f}, {:.2f}])",
                                              vs.metric, vs.value, range.min, range.max);

            dispatch(alert);
        }
    }

    /* ---------------- Runtime statistics ---------------- */

    [[nodiscard]] std::uint64_t alertsDispatched() const noexcept
    {
        return alerts_dispatched_.load();
    }

    [[nodiscard]] std::uint64_t samplesIngested() const noexcept
    {
        return samples_ingested_.load();
    }

private:
    /* ---------------- Internal helpers ---------------- */

    void dispatch(const Alert& alert) noexcept
    {
        ++alerts_dispatched_;

        std::shared_lock lock{sinks_mtx_};
        for (const auto& [id, sink] : sinks_)
        {
            if (!sink) { continue; }
            try
            {
                sink->handleAlert(alert);
            }
            catch (const std::exception& ex)
            {
                spdlog::error("AlertingService: sink '{}' threw – {}", id, ex.what());
            }
            catch (...)
            {
                spdlog::error("AlertingService: sink '{}' threw unknown exception", id);
            }
        }

        spdlog::debug("AlertingService: dispatched alert {}", alert.to_string());
    }

    /* ---------------- State ---------------- */

    // Registered output sinks
    std::unordered_map<std::string, std::shared_ptr<AbstractAlertSink>> sinks_;
    mutable std::shared_mutex                                         sinks_mtx_;

    // Metric thresholds
    std::unordered_map<std::string, Range> thresholds_;
    mutable std::shared_mutex               thresh_mtx_;

    // Telemetry counters
    std::atomic<std::uint64_t> alerts_dispatched_{0};
    std::atomic<std::uint64_t> samples_ingested_{0};
};

}  // namespace cardio_insight_360::services