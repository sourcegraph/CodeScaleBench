```cpp
/***************************************************************************************************
 *  File:    metrics_registry.cpp
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      Thread–safe singleton registry that owns, exposes, and snapshots run–time metrics produced
 *      throughout the CardioInsight360 monolith.  The registry is intentionally self-contained and
 *      dependency-free (outside of the STL) so that it can be embedded in low-level components
 *      without creating circular-dependency headaches.
 *
 *      The implementation follows the Observer pattern—producers push samples into concrete Metric
 *      objects (Counter, Gauge, Histogram, …), while the registry offers a pull-style API for
 *      exporters (Prometheus, StatsD, CSV, etc.) that periodically harvest a consistent snapshot of
 *      all metrics in O(#metrics) time.
 *
 *      Unless the environment variable CI360_MONITORING_DISABLED is set to “1”, the registry is
 *      active; otherwise all calls devolve into no-ops so that unit tests and low-footprint CLI
 *      utilities can run without paying the monitoring tax.
 *
 *  Copyright:
 *      © 2024 CathLabs, Inc.  All rights reserved.
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <cstdlib>          // std::getenv
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace cardio::monitoring {

// -------------------------------------------------------------------------------------------------
// Forward declarations.
// -------------------------------------------------------------------------------------------------
enum class MetricType
{
    Counter,
    Gauge,
    Histogram,
    Timer
};

/**
 * @brief Light-weight, engine-agnostic snapshot object.
 *
 *        We intentionally copy the metric’s current value(s) into a POD-ish struct to ensure that
 *        the registry can release its locks quickly and exporters can manipulate the snapshot
 *        without interfering with on-going updates from producers.
 */
struct MetricSnapshot
{
    std::string   name;
    MetricType    type;
    std::vector<double> values;       // For simple metrics sizes() == 1; histograms/timers may emit N
    std::chrono::system_clock::time_point captured_at;
};

/**
 * @brief Abstract base class for all concrete metric implementations.
 *
 *        The interface is deliberately small so that new metric types can be added without touching
 *        the registry code.
 */
class MetricBase
{
public:
    virtual ~MetricBase() = default;

    virtual MetricType type() const noexcept = 0;

    /**
     * @return Thread-safe snapshot of the metric’s current state.  Must NOT block for long periods.
     */
    virtual MetricSnapshot snapshot() const = 0;
};

// =================================================================================================
// MetricsRegistry
// =================================================================================================
class MetricsRegistry
{
public:
    using MetricPtr = std::shared_ptr<MetricBase>;

    /**
     * @return Global singleton handle.  Thread–safe and lazily initialized.
     */
    static MetricsRegistry& instance()
    {
        static MetricsRegistry g_instance;
        return g_instance;
    }

    /**
     * Registers—or returns an existing—metric with the given canonical name.
     *
     * @param name     Unique, case-sensitive identifier (e.g. “etl_batch_duration_seconds”).
     * @param metric   Concrete MetricBase pointer.  If a metric with the same name already exists,
     *                 the call is ignored and the existing instance is returned.
     *
     * @throws std::invalid_argument if ‘metric’ is null.
     */
    MetricPtr register_metric(const std::string& name, MetricPtr metric)
    {
        if (CI360_MONITORING_DISABLED.load(std::memory_order_relaxed))
        {
            return nullptr;
        }

        if (!metric)
        {
            throw std::invalid_argument(
                "MetricsRegistry::register_metric – metric pointer must not be null");
        }

        {
            // Fast path: reader lock to check whether the metric already exists.
            std::shared_lock rd_lock(mutex_);
            auto it = metrics_.find(name);
            if (it != metrics_.end())
            {
                return it->second;
            }
        }

        // Slow path: writer lock to actually insert.
        std::unique_lock wr_lock(mutex_);
        auto [it, inserted] = metrics_.emplace(name, std::move(metric));
        return it->second;
    }

    /**
     * Immutable lookup.
     *
     * @return nullptr if name is unknown or monitoring is disabled.
     */
    MetricPtr get_metric(const std::string& name) const
    {
        if (CI360_MONITORING_DISABLED.load(std::memory_order_relaxed))
        {
            return nullptr;
        }

        std::shared_lock rd_lock(mutex_);
        auto              it = metrics_.find(name);
        return it == metrics_.end() ? nullptr : it->second;
    }

    /**
     * Retrieves an atomic, point-in-time snapshot of all registered metrics.
     */
    std::vector<MetricSnapshot> snapshot_all() const
    {
        std::vector<MetricSnapshot> snapshots;

        if (CI360_MONITORING_DISABLED.load(std::memory_order_relaxed))
        {
            return snapshots; // empty
        }

        // Take a quick copy of shared_ptrs so that we can drop the lock immediately afterwards.
        {
            std::shared_lock rd_lock(mutex_);
            snapshots.reserve(metrics_.size());
            for (const auto& [_, metric] : metrics_)
            {
                copies_.push_back(metric);
            }
        }

        // Now capture snapshots without holding the registry lock.
        snapshots.reserve(copies_.size());
        for (const auto& m : copies_)
        {
            if (m) { snapshots.push_back(m->snapshot()); }
        }

        return snapshots;
    }

    /**
     * Convenience helper that serializes the snapshot into Prometheus text exposition format.
     *
     * NOTE: This helper is *NOT* meant to replace a full Prometheus exporter; it simply facilitates
     *       unit tests and ad-hoc diagnostics when the entire Prometheus dependency stack is
     *       undesirable.
     */
    std::string to_prometheus_exposition() const
    {
        std::ostringstream oss;
        auto               shots = snapshot_all();

        for (const auto& s : shots)
        {
            switch (s.type)
            {
            case MetricType::Counter:
                oss << "# TYPE " << s.name << " counter\n";
                break;
            case MetricType::Gauge:
                oss << "# TYPE " << s.name << " gauge\n";
                break;
            case MetricType::Histogram:
                oss << "# TYPE " << s.name << " histogram\n";
                break;
            case MetricType::Timer:
                oss << "# TYPE " << s.name << " summary\n";
                break;
            default:
                break;
            }

            if (s.values.empty())
            {
                continue;
            }

            if (s.type == MetricType::Histogram || s.type == MetricType::Timer)
            {
                // Naïve exposition, real code would include buckets/quantiles.
                for (std::size_t i = 0; i < s.values.size(); ++i)
                {
                    oss << s.name << "{le=\"" << i << "\"} " << s.values[i] << '\n';
                }
            }
            else
            {
                oss << s.name << ' ' << s.values.front() << '\n';
            }
        }

        return oss.str();
    }

    /**
     * Clears all metrics—primarily intended for unit tests.  Live code should refrain from calling.
     */
    void clear_for_tests_only()
    {
        std::unique_lock wr_lock(mutex_);
        metrics_.clear();
    }

private:
    MetricsRegistry()  = default;
    ~MetricsRegistry() = default;

    MetricsRegistry(const MetricsRegistry&)            = delete;
    MetricsRegistry& operator=(const MetricsRegistry&) = delete;
    MetricsRegistry(MetricsRegistry&&)                 = delete;
    MetricsRegistry& operator=(MetricsRegistry&&)      = delete;

    // ---------------------------------------------------------------------------------------------
    // Implementation details.
    // ---------------------------------------------------------------------------------------------
    using MetricMap = std::unordered_map<std::string, MetricPtr>;

    mutable std::shared_mutex mutex_;
    MetricMap                 metrics_;

    // Reused buffer to avoid re-allocation on each snapshot_all() call.
    // (mutable because snapshot_all() is logically const.)
    mutable std::vector<MetricPtr> copies_;

    // Environment-driven kill switch that must be initialized *before* main().
    static inline const std::atomic_bool CI360_MONITORING_DISABLED =
        []() { return std::getenv("CI360_MONITORING_DISABLED") != nullptr; }();
};

} // namespace cardio::monitoring
```