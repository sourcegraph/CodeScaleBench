#pragma once
/**
 * FortiLedger360 – Enterprise Security Suite
 *
 *  File:    metrics_observer.h
 *  Author:  FortiLedger360 Infrastructure Team
 *  License: Proprietary – All Rights Reserved.
 *
 *  Description:
 *      MetricsObserver offers a thread–safe façade for collecting fine-grained
 *      telemetry across FortiLedger360 micro-services.  The observer follows the
 *      Observer Pattern and may be wired to domain / orchestration events
 *      (e.g., “BackupCompleted”, “ScanFailed”) or used ad-hoc by low-level
 *      components that need to expose counters, gauges, and histograms.
 *
 *      Collected samples are periodically flushed to a pluggable MetricsSink
 *      (Prometheus, InfluxDB, StatsD, etc.) provided at construction time.
 *
 *      The implementation is header-only to simplify integration in statically
 *      linked service binaries while retaining zero-cost abstractions through
 *      inline ‑O2 compilation.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fl360::infra::monitoring {

/* ===================================================================== */
/*                             ENUMERATIONS                              */
/* ===================================================================== */

/**
 * @brief Defines the canonical metric types supported by the observer.
 */
enum class MetricType : uint8_t
{
    Counter   = 0,   ///< Monotonic unsigned 64-bit counter.
    Gauge     = 1,   ///< Arbitrary signed 64-bit gauge.
    Histogram = 2    ///< Latency/size buckets – stored in nanoseconds.
};

/* ===================================================================== */
/*                                DATA                                   */
/* ===================================================================== */

/**
 * @brief Bag-of-bytes representation of a metric sample.
 */
struct MetricSample
{
    std::string                          name;     ///< Metric key.
    std::unordered_map<std::string,
                       std::string>      labels;   ///< Prom-style KV labels.
    MetricType                           type;     ///< Sample type.
    std::uint64_t                        value;    ///< Raw value (ns for hist).
    std::chrono::steady_clock::time_point timestamp; ///< When recorded.
};

/* ===================================================================== */
/*                           METRICS SINK API                            */
/* ===================================================================== */

/**
 * @brief Interface implemented by pluggable telemetry back-ends.
 *        Implementations MUST be thread-safe and non-blocking.
 */
class MetricsSink
{
public:
    virtual ~MetricsSink() = default;

    /**
     * @param samples vector of collected samples to persist/forward.
     * @throws std::runtime_error on unrecoverable I/O or protocol errors.
     */
    virtual void publish(std::vector<MetricSample>&& samples) = 0;
};

/* ===================================================================== */
/*                           METRICS OBSERVER                            */
/* ===================================================================== */

class MetricsObserver : public std::enable_shared_from_this<MetricsObserver>
{
public:
    using Clock = std::chrono::steady_clock;

    /**
     * @brief Factory helper producing std::shared_ptr instances.
     */
    template <typename SinkT, typename... Args>
    static std::shared_ptr<MetricsObserver> create(Args&&... args)
    {
        static_assert(std::is_base_of_v<MetricsSink, SinkT>,
                      "SinkT must derive from MetricsSink");
        return std::shared_ptr<MetricsObserver>(
            new MetricsObserver(std::make_unique<SinkT>(std::forward<Args>(args)...)));
    }

    /**
     * @name Counter helpers
     * @{
     */

    /**
     * @brief Atomically increment a counter by delta (default=+1).
     */
    void increment(const std::string& name,
                   std::int64_t        delta = 1,
                   std::unordered_map<std::string, std::string> labels = {})
    {
        addSample(name, MetricType::Counter, delta, std::move(labels));
    }

    /**
     * @name Gauge helpers
     * @{
     */

    /**
     * @brief Set gauge to an arbitrary value.
     */
    void gauge(const std::string& name,
               std::int64_t       value,
               std::unordered_map<std::string, std::string> labels = {})
    {
        addSample(name, MetricType::Gauge, value, std::move(labels));
    }
    /** @} */

    /**
     * @name Histogram helpers
     * @{
     */

    /**
     * @brief Observe a latency/size sample in arbitrary chrono units.
     */
    template <typename Rep, typename Period>
    void observe(const std::string&                                    name,
                 const std::chrono::duration<Rep, Period>&             dur,
                 std::unordered_map<std::string, std::string>          labels = {})
    {
        auto nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(dur).count();
        addSample(name, MetricType::Histogram, static_cast<std::int64_t>(nanos),
                  std::move(labels));
    }
    /** @} */

    /**
     * @brief Flush accumulated samples to the configured sink.
     *
     *        The call is non-blocking: heavy lifting is executed on a
     *        background thread or via the caller-provided sink implementation.
     */
    void flush()
    {
        std::vector<MetricSample> snapshot;
        {
            std::unique_lock lock(m_mutex_);
            snapshot.swap(buffer_);
        }

        if (snapshot.empty()) { return; }

        try
        {
            sink_->publish(std::move(snapshot));
        }
        catch (const std::exception& ex)
        {
            // Best-effort: log and drop the batch – platform stability first.
            // (Assumes LOG_ERROR macro or replace with std::cerr.)
#ifdef FL360_HAS_SPDLOG
            spdlog::error("[MetricsObserver] Failed to publish metrics: {}", ex.what());
#else
            ::fprintf(stderr, "[MetricsObserver] Failed to publish metrics: %s\n", ex.what());
#endif
        }
    }

    /**
     * @brief RAII helper tracking histogram durations for the given metric name.
     *
     *        Example:
     *          {
     *              auto timer = observer->scopeTimer("db_query_latency");
     *              db.query(...);
     *          } // <-- duration automatically recorded.
     */
    class ScopedTimer
    {
    public:
        ScopedTimer(std::shared_ptr<MetricsObserver> observer,
                    std::string                      metricName,
                    std::unordered_map<std::string, std::string> labels)
            : observer_(std::move(observer)),
              name_(std::move(metricName)),
              labels_(std::move(labels)),
              start_(Clock::now())
        {
        }

        // Non-copyable, movable
        ScopedTimer(const ScopedTimer&)            = delete;
        ScopedTimer& operator=(const ScopedTimer&) = delete;

        ScopedTimer(ScopedTimer&& other) noexcept
            : observer_(std::move(other.observer_)),
              name_(std::move(other.name_)),
              labels_(std::move(other.labels_)),
              start_(other.start_)
        {
            other.observer_.reset();
        }

        ScopedTimer& operator=(ScopedTimer&&) = delete;

        ~ScopedTimer()
        {
            if (observer_)
            {
                observer_->observe(name_, Clock::now() - start_, std::move(labels_));
            }
        }

    private:
        std::shared_ptr<MetricsObserver>            observer_;
        std::string                                 name_;
        std::unordered_map<std::string, std::string> labels_;
        Clock::time_point                           start_;
    };

    /**
     * @brief Produce a ScopedTimer instance tied to *this observer.
     */
    ScopedTimer scopeTimer(std::string metricName,
                           std::unordered_map<std::string, std::string> labels = {})
    {
        return ScopedTimer(shared_from_this(), std::move(metricName), std::move(labels));
    }

    /** @} */

    ~MetricsObserver() = default;

private:
    explicit MetricsObserver(std::unique_ptr<MetricsSink>&& sink)
        : sink_(std::move(sink))
    {
    }

    void addSample(const std::string&                               name,
                   MetricType                                       type,
                   std::int64_t                                     value,
                   std::unordered_map<std::string, std::string>&&   labels)
    {
        MetricSample sample;
        sample.name       = name;
        sample.type       = type;
        sample.value      = static_cast<std::uint64_t>(value);
        sample.labels     = std::move(labels);
        sample.timestamp  = Clock::now();

        {
            std::unique_lock lock(m_mutex_);
            buffer_.emplace_back(std::move(sample));
        }
    }

    std::unique_ptr<MetricsSink> sink_;

    std::mutex                  m_mutex_;  // protects buffer_
    std::vector<MetricSample>   buffer_;
};

/* ===================================================================== */
/*                       HELPER DEFAULT SINK (OPTIONAL)                  */
/* ===================================================================== */

/**
 * @brief A no-op sink that simply discards the samples.
 *        Useful for unit tests or components that do not need telemetry.
 */
class NullSink final : public MetricsSink
{
public:
    void publish(std::vector<MetricSample>&&) override {} // NOP
};

/* ===================================================================== */
/*                             NAMESPACE END                             */
/* ===================================================================== */

} // namespace fl360::infra::monitoring