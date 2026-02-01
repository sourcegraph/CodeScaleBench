```cpp
/**
 * cardio_insight_360/src/monitoring/prometheus_exporter.cpp
 *
 * CardioInsight360 – Unified Healthcare Analytics Engine
 *
 * Prometheus Exporter
 * ===================
 * This compilation unit implements a production–grade Prometheus exporter that
 * exposes internal CardioInsight360 metrics (ETL throughput, pipeline latency,
 * error counters, etc.) over an HTTP endpoint.  The implementation relies on
 * the official prometheus-cpp client library and follows a lightweight
 * Singleton design so that the exporter can be safely referenced across the
 * monolithic binary without accidental duplication of the HTTP listener.
 *
 * Copyright (c) 2023–2024, CardioInsight360
 * SPDX-License-Identifier: Apache-2.0
 */

#include "monitoring/prometheus_exporter.h"  // NOLINT(build/include)
#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/gauge.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

namespace monitoring {

// --------------------------------------------------------------------------------------------------------------------
// Singleton Accessor
// --------------------------------------------------------------------------------------------------------------------
PrometheusExporter& PrometheusExporter::instance()
{
    static PrometheusExporter exporter{};
    return exporter;
}

// --------------------------------------------------------------------------------------------------------------------
// ctor / dtor
// --------------------------------------------------------------------------------------------------------------------
PrometheusExporter::PrometheusExporter() = default;

PrometheusExporter::~PrometheusExporter()
{
    try
    {
        stop();
    }
    catch (...)
    {
        // Suppress all exceptions during global destruction.
    }
}

// --------------------------------------------------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------------------------------------------------
void PrometheusExporter::start(const std::string& bind_address)
{
    // Ensure idempotency.
    if (running_.load(std::memory_order_acquire))
    {
        return;
    }

    std::lock_guard<std::mutex> _{mutex_};
    if (running_.load(std::memory_order_relaxed))
    {
        return;
    }

    try
    {
        registry_ = std::make_shared<prometheus::Registry>();
        buildCoreMetrics();

        // NOTE: The Exposer constructor starts the HTTP server immediately.
        exposer_ = std::make_unique<prometheus::Exposer>(bind_address);
        exposer_->RegisterCollectable(registry_);

        running_.store(true, std::memory_order_release);
        std::cout << "[PrometheusExporter] Running at http://" << bind_address << "/metrics\n";
    }
    catch (const std::exception& ex)
    {
        std::ostringstream oss;
        oss << "[PrometheusExporter] Failed to start: " << ex.what();
        throw std::runtime_error(oss.str());
    }
}

void PrometheusExporter::stop()
{
    if (!running_.load(std::memory_order_acquire))
    {
        return;  // Already stopped.
    }

    std::lock_guard<std::mutex> _{mutex_};

    // Destroy Exposer first to stop accepting HTTP traffic.
    exposer_.reset();

    // Clear metric references to allow for clean re-start and to limit
    // destruction order issues on process shutdown.
    ingestion_rate_by_source_.clear();
    ingested_messages_by_source_.clear();
    latency_by_stage_.clear();
    error_counter_by_component_.clear();

    registry_.reset();

    running_.store(false, std::memory_order_release);
}

void PrometheusExporter::observeIngestionRate(const std::string& source, double rate)
{
    auto* gauge = fetchOrCreateGauge(ingestion_rate_by_source_, *ingestion_rate_family_, "source", source);
    gauge->Set(rate);
}

void PrometheusExporter::incrementIngestedMessages(const std::string& source, double delta)
{
    auto* counter = fetchOrCreateCounter(ingested_messages_by_source_, *ingested_messages_family_, "source", source);
    counter->Increment(delta);
}

void PrometheusExporter::observePipelineLatency(const std::string& stage, double seconds)
{
    auto* histogram = fetchOrCreateHistogram(latency_by_stage_, *pipeline_latency_family_, "stage", stage);
    histogram->Observe(seconds);
}

void PrometheusExporter::incrementProcessingErrors(const std::string& component, double delta)
{
    auto* counter = fetchOrCreateCounter(error_counter_by_component_, *processing_errors_family_, "component", component);
    counter->Increment(delta);
}

// --------------------------------------------------------------------------------------------------------------------
// Private helpers
// --------------------------------------------------------------------------------------------------------------------
void PrometheusExporter::buildCoreMetrics()
{
    if (!registry_)
    {
        throw std::logic_error("Registry must be initialized before metrics are created.");
    }

    ingestion_rate_family_   = &prometheus::BuildGauge()
                                  .Name("ci360_ingestion_rate_per_second")
                                  .Help("Current ingestion rate per data source.")
                                  .Register(*registry_);

    ingested_messages_family_ = &prometheus::BuildCounter()
                                   .Name("ci360_ingested_messages_total")
                                   .Help("Total number of ingested messages per data source.")
                                   .Register(*registry_);

    pipeline_latency_family_ = &prometheus::BuildHistogram()
                                   .Name("ci360_pipeline_latency_seconds")
                                   .Help("Latency of pipeline stages in seconds.")
                                   .Buckets(
                                       // Prometheus-style exponential buckets (0.005s to 15s).
                                       {0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15})
                                   .Register(*registry_);

    processing_errors_family_ = &prometheus::BuildCounter()
                                    .Name("ci360_processing_errors_total")
                                    .Help("Total number of errors per component.")
                                    .Register(*registry_);
}

// Generic helper that caches metric instances to avoid re-allocations behind
// prometheus-cpp’s Family::Add(…) calls.
template <typename FamilyT, typename MetricT>
MetricT* PrometheusExporter::fetchOrCreateMetric(
    std::unordered_map<std::string, MetricT*>& cache,
    FamilyT& family,
    const char* label_key,
    const std::string& label_value)
{
    // Fast path: optimistic read.
    {
        auto it = cache.find(label_value);
        if (it != cache.end())
        {
            return it->second;
        }
    }

    // Slow path: create under lock.
    std::lock_guard<std::mutex> _{mutex_};
    auto it = cache.find(label_value);
    if (it == cache.end())
    {
        MetricT& metric =
            family.Add({{label_key, label_value}});
        it = cache.emplace(label_value, &metric).first;
    }
    return it->second;
}

// Concrete wrappers for gauge, counter, histogram.
prometheus::Gauge* PrometheusExporter::fetchOrCreateGauge(
    std::unordered_map<std::string, prometheus::Gauge*>& cache,
    prometheus::Family<prometheus::Gauge>& family,
    const char* label_key,
    const std::string& label_value)
{
    return fetchOrCreateMetric(cache, family, label_key, label_value);
}

prometheus::Counter* PrometheusExporter::fetchOrCreateCounter(
    std::unordered_map<std::string, prometheus::Counter*>& cache,
    prometheus::Family<prometheus::Counter>& family,
    const char* label_key,
    const std::string& label_value)
{
    return fetchOrCreateMetric(cache, family, label_key, label_value);
}

prometheus::Histogram* PrometheusExporter::fetchOrCreateHistogram(
    std::unordered_map<std::string, prometheus::Histogram*>& cache,
    prometheus::Family<prometheus::Histogram>& family,
    const char* label_key,
    const std::string& label_value)
{
    return fetchOrCreateMetric(cache, family, label_key, label_value);
}

}  // namespace monitoring
```

