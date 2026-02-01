```cpp
#pragma once
/******************************************************************************
 * File:        prometheus_exporter.h
 * Project:     CardioInsight360 – Unified Healthcare Analytics Engine
 *
 * Description:
 *   A small yet powerful wrapper around the excellent prometheus-cpp library
 *   that turns CardioInsight360’s in-process Observer hooks into a production-
 *   grade Prometheus /metrics endpoint.  The exporter is intentionally header-
 *   only to simplify the monolithic build and to avoid an extra shared‐library
 *   dependency.  Thread-safety, sane defaults, and graceful shutdown semantics
 *   are provided out-of-the-box.
 *
 * Copyright:
 *   (c) 2023–2024 CardioInsight LLC – All Rights Reserved.
 ******************************************************************************/

#include <atomic>
#include <chrono>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/gauge.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>

namespace cardio_insight {
namespace monitoring {

/**
 * PrometheusExporterConfig
 *
 * User-tunable parameters for the exporter.  All fields have sensible defaults
 * so in the common case the caller can simply do:
 *     PrometheusExporter exporter;
 *     exporter.Start();
 */
struct PrometheusExporterConfig {
    // TCP listen address, e.g. "0.0.0.0:9100"
    std::string listen_address = "0.0.0.0:9100";

    // HTTP URI for metrics endpoint
    std::string endpoint = "/metrics";

    // True  -> collect internal “process_” metrics: CPU, RSS, open fds, …
    // False -> user metrics only
    bool collect_process_metrics = true;

    // Frequency at which expensive system metrics are refreshed
    std::chrono::seconds collection_interval{5};
};

/**
 * PrometheusExporter
 *
 * A thin façade that hides prometheus-cpp’s details and offers a more domain-
 * specific API targeted at CardioInsight360’s subsystems.
 */
class PrometheusExporter
    : public std::enable_shared_from_this<PrometheusExporter> {
public:
    using LabelMap = std::map<std::string, std::string>;

    /* --------------------------------------------------------------------- */
    /*  Construction / Destruction                                           */
    /* --------------------------------------------------------------------- */

    explicit PrometheusExporter(
        PrometheusExporterConfig cfg = PrometheusExporterConfig{});

    // Copy / move semantics are disabled – there must be only one exporter.
    PrometheusExporter(const PrometheusExporter&) = delete;
    PrometheusExporter& operator=(const PrometheusExporter&) = delete;
    PrometheusExporter(PrometheusExporter&&) = delete;
    PrometheusExporter& operator=(PrometheusExporter&&) = delete;

    ~PrometheusExporter();

    /* --------------------------------------------------------------------- */
    /*  Lifecycle                                                            */
    /* --------------------------------------------------------------------- */

    // Spins up HTTP server and (optionally) background collectors
    void Start();

    // Blocks until Stop() has completed or destructor is called
    void Join();

    // Gracefully tears everything down
    void Stop();

    /* --------------------------------------------------------------------- */
    /*  Metric Builders – convenience helpers                                */
    /* --------------------------------------------------------------------- */

    prometheus::Counter& BuildCounter(const std::string& name,
                                      const std::string& help,
                                      const LabelMap& labels = LabelMap{});

    prometheus::Gauge& BuildGauge(const std::string& name,
                                  const std::string& help,
                                  const LabelMap& labels = LabelMap{});

    prometheus::Histogram& BuildHistogram(
        const std::string& name, const std::string& help,
        const std::vector<double>& buckets,
        const LabelMap& labels = LabelMap{});

    /* --------------------------------------------------------------------- */
    /*  Introspection                                                        */
    /* --------------------------------------------------------------------- */

    bool IsRunning() const noexcept { return is_running_.load(); }
    const PrometheusExporterConfig& Config() const noexcept { return cfg_; }

private:
    /* --------------------------------------------------------------------- */
    /*  Internal helpers                                                     */
    /* --------------------------------------------------------------------- */

    void CollectProcessMetrics();
    void RunProcessMetricsThread();
    void RegisterDefaultProcessMetrics();

    /* --------------------------------------------------------------------- */
    /*  Data Members                                                         */
    /* --------------------------------------------------------------------- */

    PrometheusExporterConfig                cfg_;
    std::shared_ptr<prometheus::Registry>   registry_;
    std::optional<prometheus::Exposer>      exposer_;

    mutable std::shared_mutex metric_mutex_;  // protects registry_ access

    // “process_” metrics
    prometheus::Gauge* process_cpu_seconds_total_ = nullptr;
    prometheus::Gauge* process_resident_memory_bytes_ = nullptr;
    prometheus::Gauge* process_open_fds_ = nullptr;

    std::atomic<bool>  is_running_{false};
    std::atomic<bool>  stop_requested_{false};
    std::thread        collector_thread_;
};

/*==============================================================================
 *                              Implementation
 *============================================================================*/

inline PrometheusExporter::PrometheusExporter(PrometheusExporterConfig cfg)
    : cfg_(std::move(cfg)), registry_(std::make_shared<prometheus::Registry>()) {}

/* ------------------------------------------------------------------------- */

inline PrometheusExporter::~PrometheusExporter() {
    Stop();  // Ensure resources are released, even if user forgot
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::Start() {
    std::unique_lock lock(metric_mutex_);
    if (is_running_.load()) { return; }

    // Initialize HTTP exposer
    exposer_.emplace(cfg_.listen_address, cfg_.endpoint);
    exposer_->RegisterCollectable(registry_);

    // Register default “process_” metrics if requested
    if (cfg_.collect_process_metrics) {
        RegisterDefaultProcessMetrics();
        collector_thread_ = std::thread(&PrometheusExporter::RunProcessMetricsThread,
                                        this);
    }

    is_running_.store(true);
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::Join() {
    if (collector_thread_.joinable()) { collector_thread_.join(); }
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::Stop() {
    if (!is_running_.exchange(false)) { return; }  // already stopped

    stop_requested_.store(true);
    if (collector_thread_.joinable()) { collector_thread_.join(); }

    // Exposer_ must be destroyed last so that /metrics keeps serving until
    // after background collectors have quit.
    {
        std::unique_lock lock(metric_mutex_);
        exposer_.reset();
        registry_.reset();
    }
}

/* ------------------------------------------------------------------------- */

template <typename FamilyT>
static typename FamilyT::MetricType& AddMetricToFamily(
    prometheus::Family<FamilyT>& family,
    const PrometheusExporter::LabelMap& labels) {
    return family.Add(labels);
}

inline prometheus::Counter& PrometheusExporter::BuildCounter(
    const std::string& name, const std::string& help, const LabelMap& labels) {
    std::unique_lock lock(metric_mutex_);
    auto& family = prometheus::BuildCounter()
                       .Name(name)
                       .Help(help)
                       .Register(*registry_);
    return family.Add(labels);
}

inline prometheus::Gauge& PrometheusExporter::BuildGauge(
    const std::string& name, const std::string& help, const LabelMap& labels) {
    std::unique_lock lock(metric_mutex_);
    auto& family = prometheus::BuildGauge()
                       .Name(name)
                       .Help(help)
                       .Register(*registry_);
    return family.Add(labels);
}

inline prometheus::Histogram& PrometheusExporter::BuildHistogram(
    const std::string& name, const std::string& help,
    const std::vector<double>& buckets, const LabelMap& labels) {
    std::unique_lock lock(metric_mutex_);
    auto& family = prometheus::BuildHistogram()
                       .Name(name)
                       .Help(help)
                       .Buckets(buckets)
                       .Register(*registry_);
    return family.Add(labels);
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::RegisterDefaultProcessMetrics() {
    // Note: The prometheus convention uses `process_` prefix.
    process_cpu_seconds_total_ =
        &BuildGauge("process_cpu_seconds_total",
                    "Total user and system CPU time spent in seconds.");

    process_resident_memory_bytes_ =
        &BuildGauge("process_resident_memory_bytes",
                    "Resident memory size in bytes.");

    process_open_fds_ =
        &BuildGauge("process_open_fds",
                    "Number of open file descriptors.");
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::CollectProcessMetrics() {
#if defined(__linux__)
    // --- CPU time ---------------------------------------------------------
    {
        struct timespec ts {};
        if (::clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &ts) == 0 && process_cpu_seconds_total_) {
            const double seconds = ts.tv_sec + ts.tv_nsec / 1e9;
            process_cpu_seconds_total_->Set(seconds);
        }
    }

    // --- Memory usage -----------------------------------------------------
    {
        // On Linux we can parse /proc/self/statm for resident pages
        constexpr long page_size = sysconf(_SC_PAGESIZE);
        FILE* fp = ::fopen("/proc/self/statm", "r");
        if (fp) {
            long rss_pages = 0;
            if (::fscanf(fp, "%*s %ld", &rss_pages) == 1 && process_resident_memory_bytes_) {
                process_resident_memory_bytes_->Set(static_cast<double>(rss_pages * page_size));
            }
            ::fclose(fp);
        }
    }

    // --- FD count ---------------------------------------------------------
    {
        int fd_count = 0;
        if (DIR* dir = ::opendir("/proc/self/fd")) {
            while (::readdir(dir)) { ++fd_count; }
            ::closedir(dir);
            if (process_open_fds_) { process_open_fds_->Set(fd_count); }
        }
    }
#else
    // Non-Linux platform: no-op but keep compiler happy
    (void)process_cpu_seconds_total_;
    (void)process_resident_memory_bytes_;
    (void)process_open_fds_;
#endif
}

/* ------------------------------------------------------------------------- */

inline void PrometheusExporter::RunProcessMetricsThread() {
    using namespace std::chrono_literals;
    while (!stop_requested_.load()) {
        CollectProcessMetrics();
        std::this_thread::sleep_for(cfg_.collection_interval);
    }
}

}  // namespace monitoring
}  // namespace cardio_insight
```