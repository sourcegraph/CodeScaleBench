#ifndef CARDIO_INSIGHT_360_SRC_MONITORING_HEALTH_MONITOR_H_
#define CARDIO_INSIGHT_360_SRC_MONITORING_HEALTH_MONITOR_H_

/*
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:    health_monitor.h
 *  Author:  CardioInsight360 Core Team
 *  License: Proprietary – All Rights Reserved
 *
 *  Description:
 *      Thread–safe, observer-based subsystem that aggregates run-time
 *      health metrics (CPU, memory, queue lengths, pipeline latency, …)
 *      produced by the various engine components and dispatches
 *      snapshots to interested observers (REST gateway, Grafana plugin,
 *      CLI diagnostics, …).  The class is implemented header-only to
 *      avoid symbol-visibility issues inside the monolithic binary while
 *      still allowing LTO to inline hot paths.
 *
 *      The interface follows the Observer Pattern: components publish
 *      raw measurements via `recordMetric(…)`; observers subscribe via
 *      `registerObserver(…)` and receive periodic `MetricSnapshot`s on a
 *      dedicated dispatch thread managed by `HealthMonitor`.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace cardio_insight_360::monitoring {

/*─────────────────────────────────────────────────────────────────────────────*
 *                               Declarations                                  *
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Enumeration of all run-time health metrics that can be tracked.
 * Extend carefully – IDs are persisted in parquet/metrics schema.
 */
enum class Metric : std::uint8_t
{
    CPU_USAGE_PERCENT = 0,
    MEMORY_RSS_MB     = 1,
    DISK_FREE_GB      = 2,
    EVENT_QUEUE_DEPTH = 3,
    STREAM_LATENCY_MS = 4,
    ECG_PIPELINE_LAG_SEC = 5,
    ERROR_RATE_PER_MIN = 6
};

/* Hash-functor so Metric can be used as unordered_map key. */
struct MetricHash final
{
    std::size_t operator()(Metric m) const noexcept
    {
        return static_cast<std::size_t>(m);
    }
};

/**
 * Single point-in-time view of the system's health measurements.
 */
struct MetricSnapshot
{
    std::chrono::system_clock::time_point ts
        = std::chrono::system_clock::now();
    std::unordered_map<Metric, double, MetricHash> values;

    [[nodiscard]] std::string to_string() const;
};

/*─────────────────────────────────────────────────────────────────────────────*
 *                             Observer Interface                              *
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Observers implement this interface to receive health snapshots.
 */
class IHealthObserver :
        public std::enable_shared_from_this<IHealthObserver>
{
public:
    virtual ~IHealthObserver() = default;

    /**
     * Callback executed from HealthMonitor's dispatch thread.
     * Implementations should be non-blocking.
     */
    virtual void onHealthSnapshot(const MetricSnapshot& snapshot) = 0;
};

/*─────────────────────────────────────────────────────────────────────────────*
 *                                HealthMonitor                                *
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Central aggregator & dispatcher for run-time health metrics.
 *
 * Thread safety:
 *      – Public API is thread-safe.
 *      – Observers are called from a single dedicated thread.
 *
 * Lifetime:
 *      – Singleton accessible via `instance()`.
 *      – Destroying the singleton cleanly joins the dispatch thread.
 */
class HealthMonitor final
{
public:
    using milliseconds = std::chrono::milliseconds;

    /* Retrieves the global HealthMonitor singleton. */
    static HealthMonitor& instance()
    {
        static HealthMonitor singleton;
        return singleton;
    }

    /* Non-copyable / non-movable. */
    HealthMonitor(const HealthMonitor&)            = delete;
    HealthMonitor& operator=(const HealthMonitor&) = delete;
    HealthMonitor(HealthMonitor&&)                 = delete;
    HealthMonitor& operator=(HealthMonitor&&)      = delete;

    /**
     * Adds (or updates) a measurement for the given metric.
     *
     * Thread-safe, wait-free in the common uncontended case.
     * Throws std::invalid_argument on NaN.
     */
    void recordMetric(Metric metric, double value)
    {
        if (std::isnan(value))
            throw std::invalid_argument{"metric value must not be NaN"};

        {
            std::unique_lock lock(_metricMutex);
            _current[metric] = value;
        }
    }

    /**
     * Registers an observer.  Strong ownership is transferred into
     * HealthMonitor; observers will be kept alive until explicit
     * `unregisterObserver` or destruction of the monitor.
     *
     * Duplicate registrations are ignored.
     */
    void registerObserver(const std::shared_ptr<IHealthObserver>& obs)
    {
        if (!obs) {
            throw std::invalid_argument{"observer must not be null"};
        }
        std::unique_lock lock(_observerMutex);
        _observers.insert(obs);
    }

    /**
     * Unregisters a previously registered observer.
     * Silently ignores unknown observers.
     */
    void unregisterObserver(const std::shared_ptr<IHealthObserver>& obs)
    {
        if (!obs) return;
        std::unique_lock lock(_observerMutex);
        _observers.erase(obs);
    }

    /**
     * Configures the snapshot frequency at run-time.
     * NOTE: Must be called before the monitoring thread starts;
     * otherwise the change takes effect after the next restart.
     */
    void setDispatchInterval(milliseconds interval)
    {
        if (interval.count() <= 0)
            throw std::invalid_argument{"dispatch interval must be >0 ms"};
        _dispatchInterval.store(interval);
    }

    /* Starts the background dispatch thread if not running yet. */
    void start()
    {
        std::lock_guard lock(_startStopMutex);
        if (_running.load()) return;   // already running

        _terminate.store(false);
        _dispatcherThread = std::thread{&HealthMonitor::dispatchLoop, this};
        _running.store(true);
    }

    /* Stops the background thread and blocks until it joined. */
    void stop()
    {
        std::lock_guard lock(_startStopMutex);
        if (!_running.load()) return;

        _terminate.store(true);
        if (_dispatcherThread.joinable())
            _dispatcherThread.join();
        _running.store(false);
    }

    /* Convenience: RAII guard to automatically start/stop monitoring. */
    class Guard
    {
    public:
        explicit Guard(HealthMonitor& m) : _mon{m} { _mon.start(); }
        ~Guard() { _mon.stop(); }
    private:
        HealthMonitor& _mon;
    };

    ~HealthMonitor()
    {
        stop();
    }

private:
    HealthMonitor()                               = default;

    /*────────────────────────── Implementation details ─────────────────────*/

    void dispatchLoop() noexcept
    {
        try {
            while (!_terminate.load()) {
                auto nextWake =
                    std::chrono::steady_clock::now() + _dispatchInterval.load();

                MetricSnapshot snapshot;
                {
                    std::shared_lock lock(_metricMutex);
                    snapshot.values = _current;   // cheap since double map
                }
                notifyObservers(snapshot);
                std::this_thread::sleep_until(nextWake);
            }
        }
        catch (const std::exception& ex) {
            // Catastrophic failure – last resort logging to stderr.
            // In production this would use the central logger.
            std::fprintf(stderr,
                         "[HealthMonitor] dispatchLoop fatal: %s\n",
                         ex.what());
        }
    }

    void notifyObservers(const MetricSnapshot& snap)
    {
        std::unordered_set<std::shared_ptr<IHealthObserver>> copy;
        {
            std::shared_lock lock(_observerMutex);
            copy = _observers; // copy to avoid holding lock while invoking
        }

        for (auto& obs : copy) {
            if (!obs) continue;
            try {
                obs->onHealthSnapshot(snap);
            }
            catch (const std::exception& ex) {
                // Observers MUST NOT throw; convert to log entry.
                std::fprintf(stderr,
                             "[HealthMonitor] observer threw: %s\n", ex.what());
            }
        }
    }

    /*─────────────  State  ─────────────*/

    std::atomic<bool> _terminate{false};
    std::atomic<bool> _running{false};
    std::atomic<milliseconds> _dispatchInterval{milliseconds{1000}};

    std::thread _dispatcherThread;
    std::mutex  _startStopMutex;  // serializes start()/stop()

    std::unordered_map<Metric, double, MetricHash> _current;
    mutable std::shared_mutex _metricMutex;

    std::unordered_set<std::shared_ptr<IHealthObserver>> _observers;
    mutable std::shared_mutex _observerMutex;
};

/*─────────────────────────────────────────────────────────────────────────────*
 *                         MetricSnapshot – implementation                     *
 *─────────────────────────────────────────────────────────────────────────────*/

inline std::string MetricSnapshot::to_string() const
{
    using std::chrono::duration_cast;
    using std::chrono::milliseconds;

    const auto ms =
        duration_cast<milliseconds>(ts.time_since_epoch()).count();

    std::string out = "MetricSnapshot{ ts=" + std::to_string(ms) + "ms";
    for (const auto& [metric, value] : values) {
        out += ", ";
        switch (metric) {
        case Metric::CPU_USAGE_PERCENT:   out += "CPU=";   break;
        case Metric::MEMORY_RSS_MB:       out += "RSS=";   break;
        case Metric::DISK_FREE_GB:        out += "Disk=";  break;
        case Metric::EVENT_QUEUE_DEPTH:   out += "QDepth=";break;
        case Metric::STREAM_LATENCY_MS:   out += "Latency=";break;
        case Metric::ECG_PIPELINE_LAG_SEC:out += "ECGLag=";break;
        case Metric::ERROR_RATE_PER_MIN:  out += "ErrRate=";break;
        default:                          out += "Unknown=";break;
        }
        out += std::to_string(value);
    }
    return out + " }";
}

} // namespace cardio_insight_360::monitoring

#endif // CARDIO_INSIGHT_360_SRC_MONITORING_HEALTH_MONITOR_H_
