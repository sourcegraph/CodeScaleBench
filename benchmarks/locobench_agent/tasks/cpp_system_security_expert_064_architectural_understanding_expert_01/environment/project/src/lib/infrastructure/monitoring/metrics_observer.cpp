```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  Component : Infrastructure :: Monitoring
 *  File      : metrics_observer.cpp
 *
 *  Description:
 *      Concrete implementation of the Observer which converts domain/infrastructure
 *      events into Prometheus-compatible metrics.  A single MetricsObserver instance
 *      is registered against the global EventBus and translates every pertinent
 *      event (security-scan, throughput, backup, etc.) into a meaningful metric.
 *
 *  Notes:
 *      • Uses prometheus-cpp for metric exposition
 *      • Uses spdlog for logging
 *      • Thread-safe (internal caching guarded by a mutex)
 *      • Non-copyable, movable (singleton-style usage recommended)
 *
 *  Copyright
 *      Copyright (c) 2024 FortiLedger360
 *      SPDX-License-Identifier: Business Source License 1.1
 */

#include "infrastructure/monitoring/metrics_observer.h"

// ---- 3rd-party -------------------------------------------------------------
#include <prometheus/build_counter.h>
#include <prometheus/counter.h>
#include <prometheus/build_gauge.h>
#include <prometheus/gauge.h>
#include <prometheus/build_histogram.h>
#include <prometheus/histogram.h>
#include <spdlog/spdlog.h>

// ---- Project (Event definitions) ------------------------------------------
#include "application/events/security_scan_events.h"
#include "application/events/throughput_events.h"
#include "application/events/backup_events.h"

#include <chrono>
#include <mutex>
#include <sstream>
#include <unordered_map>

using namespace fortiledger360;
using namespace fortiledger360::infrastructure::monitoring;
using namespace prometheus;

namespace
{
/* --------------------------------------------------------------------------
 * Metric cache helpers
 * ------------------------------------------------------------------------ */
template <typename TMetric>
using MetricCache = std::unordered_map<std::string, TMetric*>;

/**
 * Compose a deterministic cache key from a labels map.
 */
inline std::string composeCacheKey(const Labels& labels)
{
    std::ostringstream oss;
    for (auto it = labels.begin(); it != labels.end(); ++it)
    {
        oss << it->first << '=' << it->second;
        if (std::next(it) != labels.end()) { oss << '|'; }
    }
    return oss.str();
}

/**
 * Fetch an existing child from a prometheus family or create it if it
 * doesn't already exist (cached by the composeCacheKey()).
 */
template <typename TFamily, typename TMetric>
TMetric& fetchOrAddMetric(
        TFamily*                                      family,
        MetricCache<TMetric>&                         cache,
        const Labels&                                 lbls,
        std::mutex&                                   mtx)
{
    const std::string key = composeCacheKey(lbls);

    {
        std::lock_guard<std::mutex> lock(mtx);
        auto cached = cache.find(key);
        if (cached != cache.end()) { return *cached->second; }
        // Create new child when not cached
        TMetric& metricRef = family->Add(lbls);
        cache.emplace(key, &metricRef);
        return metricRef;
    }
}
} // ^ anonymous namespace ^

/* ============================================================================
 * MetricsObserver :: ctor / dtor
 * ========================================================================== */
MetricsObserver::MetricsObserver(std::shared_ptr<Registry> registry)
    : registry_{std::move(registry)}
{
    if (!registry_)
    {
        throw std::invalid_argument("MetricsObserver requires a non-null prometheus::Registry");
    }

    // Families are lazily instantiated in initMetricFamilies()
    initMetricFamilies();
    spdlog::info("MetricsObserver initialised successfully.");
}

MetricsObserver::~MetricsObserver()
{
    spdlog::info("MetricsObserver destroyed");
}

/* ============================================================================
 * Event handling (Observer interface)
 * ========================================================================== */
void MetricsObserver::onEvent(const events::IEvent& event)
{
    // RTTI dispatch – only the events we understand are converted to metrics.
    if (const auto* scanEvt = dynamic_cast<const events::SecurityScanCompleted*>(&event))
    {
        handleSecurityScanCompleted(*scanEvt);
    }
    else if (const auto* tpEvt = dynamic_cast<const events::NodeThroughputUpdated*>(&event))
    {
        handleThroughputUpdated(*tpEvt);
    }
    else if (const auto* bkEvt = dynamic_cast<const events::BackupCompleted*>(&event))
    {
        handleBackupCompleted(*bkEvt);
    }
    else
    {
        spdlog::debug("MetricsObserver: Received unsupported event type: {}", event.name());
    }
}

/* ============================================================================
 * Private helpers – Metric family initialisation
 * ========================================================================== */
void MetricsObserver::initMetricFamilies()
{
    /* Histogram: Security scan duration */
    scanDurationFamily_ =
        &BuildHistogram()
              .Name("fl360_security_scan_duration_seconds")
              .Help("Duration of security scans (in seconds)")
              .Buckets({0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 90, 120})
              .Register(*registry_);

    /* Gauge: Per-node throughput */
    throughputFamily_ =
        &BuildGauge()
              .Name("fl360_node_throughput_bytes_per_second")
              .Help("Current network throughput for FL360 nodes")
              .Register(*registry_);

    /* Counter: Backup failures */
    backupFailureFamily_ =
        &BuildCounter()
              .Name("fl360_backup_failure_total")
              .Help("Total number of failed backups")
              .Register(*registry_);
}

/* ============================================================================
 * Event-specific handlers
 * ========================================================================== */
void MetricsObserver::handleSecurityScanCompleted(const events::SecurityScanCompleted& e)
{
    Labels labels = {
        {"tenant",    e.tenantId()},
        {"scan_type", e.scanTypeAsString()},
        {"status",    e.success() ? "success" : "failure"}
    };

    auto& histogram =
        fetchOrAddMetric<Family<Histogram>, Histogram>(
            scanDurationFamily_, scanDurationCache_, labels, metricCacheMtx_);

    histogram.Observe(e.duration().count());

    spdlog::debug("SecurityScanCompleted recorded for tenant={}, type={}, duration={:.3f}",
                  e.tenantId(), e.scanTypeAsString(), e.duration().count());
}

void MetricsObserver::handleThroughputUpdated(const events::NodeThroughputUpdated& e)
{
    Labels labels = {
        {"node_id",  e.nodeId()},
        {"tenant",   e.tenantId()},
        {"protocol", e.protocolAsString()}
    };

    auto& gauge =
        fetchOrAddMetric<Family<Gauge>, Gauge>(
            throughputFamily_, throughputCache_, labels, metricCacheMtx_);

    gauge.Set(static_cast<double>(e.bytesPerSecond()));

    spdlog::trace("ThroughputUpdated: node={} bps={}", e.nodeId(), e.bytesPerSecond());
}

void MetricsObserver::handleBackupCompleted(const events::BackupCompleted& e)
{
    if (e.success()) { return; } // Only track failures

    Labels labels = {
        {"tenant",        e.tenantId()},
        {"backup_policy", e.policyName()}
    };

    auto& counter =
        fetchOrAddMetric<Family<Counter>, Counter>(
            backupFailureFamily_, backupFailureCache_, labels, metricCacheMtx_);

    counter.Increment();

    spdlog::warn("Backup failure detected for tenant={} policy={}", e.tenantId(), e.policyName());
}
```
