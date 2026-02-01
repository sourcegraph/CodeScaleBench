#ifndef FORTILEDGER360_LIB_INFRASTRUCTURE_MONITORING_METRICS_REPORTER_H_
#define FORTILEDGER360_LIB_INFRASTRUCTURE_MONITORING_METRICS_REPORTER_H_

/*
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File:        metrics_reporter.h
 *  License:     Proprietary & Confidential
 *  Description: Thin, thread–safe, header-only facade that allows any component
 *               in the FortiLedger360 stack to publish operational metrics
 *               (counter, gauge, histogram) to the system-wide observability
 *               backplane. The implementation purposefully stays independent
 *               of the actual exporter (Prometheus, InfluxDB, OTEL, …).
 *
 *  NOTE:        This header is *header-only* for maximal reachability from all
 *               micro-targets. Implementation incurs negligible overhead and
 *               is guarded by the FORTILEDGER_METRICS_ENABLED macro.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace fortiledger360::infrastructure::monitoring {

#ifndef FORTILEDGER_METRICS_ENABLED
// Can be overridden by CMake, Meson, Bazel, etc.
#define FORTILEDGER_METRICS_ENABLED 1
#endif

// ------------------------------- Helper Types -------------------------------

using Label          = std::pair<std::string, std::string>;
using LabelContainer = std::vector<Label>;

/*
 * Canonical format used as the internal map key. We flatten metric name and
 * labels into a single string to avoid deep map nesting and speed-up lookups.
 * <metric_name>{k1=v1,k2=v2}
 */
inline std::string toCanonicalKey(std::string_view name,
                                  const LabelContainer& labels) {
    std::ostringstream oss;
    oss << name;
    if (!labels.empty()) {
        oss << "{";
        for (std::size_t i = 0; i < labels.size(); ++i) {
            const auto& [k, v] = labels[i];
            oss << k << '=' << v;
            if (i + 1 < labels.size()) { oss << ','; }
        }
        oss << "}";
    }
    return oss.str();
}

// ----------------------------- Metric Datatypes -----------------------------

enum class MetricType : std::uint8_t { kCounter, kGauge, kHistogram };

/*
 * The Metric class is an *internal* POD that stores a numeric value in an
 * atomic fashion. AtomicDouble emulation is required because std::atomic
 * doesn’t support double pre-C++20. We encode the double as a 64-bit uint64_t.
 */
class AtomicDouble {
public:
    AtomicDouble() noexcept : bits_(0) {}
    explicit AtomicDouble(double d) noexcept {
        std::uint64_t u;
        static_assert(sizeof(double) == sizeof(std::uint64_t));
        std::memcpy(&u, &d, sizeof(double));
        bits_.store(u, std::memory_order_relaxed);
    }

    double load() const noexcept {
        std::uint64_t u = bits_.load(std::memory_order_relaxed);
        double         d;
        std::memcpy(&d, &u, sizeof(double));
        return d;
    }

    void store(double d) noexcept {
        std::uint64_t u;
        std::memcpy(&u, &d, sizeof(double));
        bits_.store(u, std::memory_order_relaxed);
    }

    void fetch_add(double d) noexcept {
        double current;
        do {
            current = load();
        } while (!bits_.compare_exchange_weak(
            *reinterpret_cast<std::uint64_t*>(&current),
            *reinterpret_cast<std::uint64_t const*>(&d), std::memory_order_relaxed));
        // Fallback naive loop to keep header simple. Collisions negligible for ops/s scale.
    }

private:
    std::atomic<std::uint64_t> bits_;
};

struct MetricData {
    MetricType   type;
    AtomicDouble value;
};

// ----------------------------- MetricsReporter ------------------------------

/*
 * MetricsReporter
 * ---------------
 * Thread-safe Singleton facade that aggregates in-process metrics and exposes a
 * *pull* API (`flush`) meant to be called by the exporter thread.
 */
class MetricsReporter final {
public:
    MetricsReporter(const MetricsReporter&)            = delete;
    MetricsReporter& operator=(const MetricsReporter&) = delete;

    static MetricsReporter& instance() {
        static MetricsReporter inst;
        return inst;
    }

    // -------------------------- Counter Operations --------------------------
#if FORTILEDGER_METRICS_ENABLED
    void incrementCounter(std::string_view metricName,
                          double            increment  = 1.0,
                          LabelContainer    labels     = {}) {
        setOrUpdate(metricName, MetricType::kCounter, labels,
                    [increment](MetricData& data) { data.value.fetch_add(increment); });
    }
#else
    void incrementCounter(std::string_view, double = 1.0,
                          LabelContainer = {}) noexcept {}
#endif

    // --------------------------- Gauge Operations ---------------------------
#if FORTILEDGER_METRICS_ENABLED
    void setGauge(std::string_view metricName,
                  double            value,
                  LabelContainer    labels = {}) {
        setOrUpdate(metricName, MetricType::kGauge, labels,
                    [value](MetricData& data) { data.value.store(value); });
    }
#else
    void setGauge(std::string_view, double,
                  LabelContainer = {}) noexcept {}
#endif

    // ------------------------- Histogram Operations -------------------------
    // For histograms, we only expose observation. Bucketing & percentile logic
    // happens in the exporter.
#if FORTILEDGER_METRICS_ENABLED
    void observe(std::string_view metricName,
                 double            sample,
                 LabelContainer    labels = {}) {
        setOrUpdate(metricName, MetricType::kHistogram, labels,
                    [sample](MetricData& data) { data.value.fetch_add(sample); });
    }
#else
    void observe(std::string_view, double,
                 LabelContainer = {}) noexcept {}
#endif

    /*
     * flush()
     * -------
     * Atomically snapshots the current metric map, encodes it as plain text
     * (“Prometheus exposition format”) and returns the string. The caller is
     * responsible for streaming the payload to the target endpoint
     * (e.g. scrape handler, pushgateway, OpenTelemetry exporter).
     *
     * The method is *non-blocking* for writers: we swap the internal map with
     * an empty one under mutex and release immediately.
     */
    std::string flush() {
#if !FORTILEDGER_METRICS_ENABLED
        return {};
#else
        std::lock_guard lk(mapMutex_);
        MetricMap       snapshot;
        snapshot.swap(metricMap_);
        mapMutex_.unlock();  // Release before heavy encoding.

        std::ostringstream oss;
        for (const auto& [key, data] : snapshot) {
            oss << "# TYPE " << key << ' ' << metricTypeToString(data.type) << '\n'
                << key << ' ' << std::fixed << std::setprecision(6) << data.value.load()
                << '\n';
        }
        return oss.str();
#endif
    }

    /*
     * Utility RAII helper that measures wall-clock duration of a scope and
     * pushes it as a histogram sample when destroyed.
     *
     * Example:
     * {
     *     MetricsReporter::ScopedTimer _(“db_query_latency_ms”,
     *                                    {{"tenant", tenantId}});
     *     runSlowQuery();
     * } // histogram observed automatically
     */
    class ScopedTimer {
    public:
        ScopedTimer(std::string_view metricName,
                    LabelContainer   labels = {})
            : metricName_(metricName),
              labels_(std::move(labels)),
              start_(Clock::now()) {}

        ~ScopedTimer() noexcept {
            using namespace std::chrono;
            auto end    = Clock::now();
            auto millis = duration<double, std::milli>(end - start_).count();
            MetricsReporter::instance().observe(metricName_, millis, labels_);
        }

    private:
        using Clock = std::chrono::steady_clock;

        std::string  metricName_;
        LabelContainer labels_;
        Clock::time_point start_;
    };

private:
    MetricsReporter() = default;

    using MetricMap = std::map<std::string, MetricData>;

#if FORTILEDGER_METRICS_ENABLED
    template <typename F>
    void setOrUpdate(std::string_view name,
                     MetricType       type,
                     const LabelContainer& labels,
                     F&&              mutator) {
        const std::string key = toCanonicalKey(name, labels);

        std::lock_guard lock(mapMutex_);
        auto            it = metricMap_.find(key);
        if (it == metricMap_.end()) {
            MetricData m{};
            m.type = type;
            m.value.store(0.0);
            mutator(m);
            metricMap_.emplace(key, std::move(m));
        } else {
            mutator(it->second);
        }
    }
#endif

    static const char* metricTypeToString(MetricType t) noexcept {
        switch (t) {
            case MetricType::kCounter:   return "counter";
            case MetricType::kGauge:     return "gauge";
            case MetricType::kHistogram: return "histogram";
            default:                     return "unknown";
        }
    }

    MetricMap        metricMap_;
    std::mutex       mapMutex_;
};

}  // namespace fortiledger360::infrastructure::monitoring

#endif  // FORTILEDGER360_LIB_INFRASTRUCTURE_MONITORING_METRICS_REPORTER_H_
