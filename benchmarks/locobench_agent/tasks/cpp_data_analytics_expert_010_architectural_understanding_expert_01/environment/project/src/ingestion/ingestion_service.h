#pragma once
/**
 * cardio_insight_360/src/ingestion/ingestion_service.h
 *
 * CardioInsight360 – Unified Healthcare Analytics Engine (data_analytics)
 * ----------------------------------------------------------------------
 * Copyright (c) 2024
 *
 * Description:
 *   IngestionService is the entry-point for all external physiological and
 *   operational data streams flowing into CardioInsight360.  The service
 *   is responsible for:
 *
 *     • Accepting and validating source-specific configuration
 *     • Running per-source acquisition threads with back-pressure control
 *     • Transforming inbound payloads into the internal, canonical schema
 *     • Publishing normalized events onto the in-process Kafka event bus
 *     • Emitting runtime metrics through the Observer pattern hooks
 *
 *   The implementation lives in `ingestion_service.cpp`; this header
 *   intentionally exposes only the public interface, plus minimal details
 *   required by unit tests and downstream components.
 *
 * Build-time Requirements:
 *   – C++17
 *   – librdkafka (for the embedded event bus)
 *   – spdlog     (for structured logging)
 *   – Intel TBB  (thread scheduling / task groups)
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include <spdlog/fmt/fmt.h>
#include <spdlog/spdlog.h>

#include "common/observer/metric_publisher.h"
#include "common/event_bus/event_bus.h"
#include "ingestion/ingestion_payload.h"

namespace ci360::ingestion {

/**
 * IngestionError
 * --------------
 * Thin wrapper around std::runtime_error for domain-specific failures.
 */
class IngestionError final : public std::runtime_error {
public:
    explicit IngestionError(const std::string& msg) : std::runtime_error(msg) {}
};


/**
 * SourceDescriptor
 * ----------------
 * Metadata & configuration for an individual ingest source.
 *
 * Examples:
 *   – Hospital ADT broker publishing HL7v2 via TCP
 *   – Wearable ECG device pushing FHIR R4 bundles over HTTPS
 *   – Local directory hot-folder that receives DICOM waveforms
 */
struct SourceDescriptor {
    enum class Kind {
        HL7_TCP,
        FHIR_HTTPS,
        FILESYSTEM_WATCHER
    };

    std::string        id;                 // Unique, human-readable identifier
    Kind               kind;               // Transport / protocol family
    std::string        endpoint;           // Host:port, URL, or path
    std::optional<int> qos;                // Optional QoS / priority level
    bool               tls_enabled{false}; // HIPAA transport encryption

    // User-supplied key/value options for protocol-specific knobs
    std::unordered_map<std::string, std::string> options;

    // Equality helpers allow use as unordered_map key if desired
    bool operator==(const SourceDescriptor& other) const { return id == other.id; }
};

}   // namespace ci360::ingestion

// Hash specialization for SourceDescriptor so it can sit in unordered_(set|map)
template <>
struct std::hash<ci360::ingestion::SourceDescriptor> {
    std::size_t operator()(const ci360::ingestion::SourceDescriptor& d) const noexcept {
        return std::hash<std::string>{}(d.id);
    }
};

namespace ci360::ingestion {

/**
 * IngestionServiceConfig
 * ----------------------
 * High-level knobs for the entire service instance.
 */
struct IngestionServiceConfig {
    std::string kafka_bootstrap_servers = "localhost:9092";
    std::string kafka_topic            = "ci360.raw.ingest";
    std::chrono::milliseconds health_check_interval{5'000};
    std::chrono::milliseconds shutdown_grace_period{15'000};
};


/**
 * IIngestionService
 * -----------------
 * Pure virtual interface – enables mocking in unit tests and lets
 * future alternative implementations (e.g., remote collector) coexist.
 */
class IIngestionService {
public:
    virtual ~IIngestionService() = default;

    // Lifecycle
    virtual void start()                                     = 0;
    virtual void stop() noexcept                             = 0;
    virtual bool isRunning() const noexcept                  = 0;
    virtual void wait()                                      = 0; // Block until fully stopped

    // Source management
    virtual void registerSource(const SourceDescriptor& src) = 0;
    virtual void unregisterSource(const std::string& source_id) = 0;

    // Manual, synchronous ingestion – primarily for unit tests and
    // low-frequency batch import tooling.
    virtual void ingest(const SourceDescriptor& src,
                        IngestionPayload&&      payload)     = 0;
};


/**
 * IngestionService
 * ----------------
 * Concrete implementation used by production deployments.
 */
class IngestionService final : public IIngestionService,
                               public std::enable_shared_from_this<IngestionService> {
public:
    explicit IngestionService(IngestionServiceConfig                cfg,
                              std::shared_ptr<common::EventBus>      event_bus,
                              std::shared_ptr<common::MetricPublisher> metrics);

    ~IngestionService() override;

    // IIngestionService ----------------------------------------------------
    void start() override;
    void stop() noexcept override;
    bool isRunning() const noexcept override { return running_.load(std::memory_order_acquire); }
    void wait() override;

    void registerSource(const SourceDescriptor& src) override;
    void unregisterSource(const std::string& source_id) override;

    void ingest(const SourceDescriptor& src,
                IngestionPayload&&      payload) override;

    // Non-copyable / non-movable
    IngestionService(const IngestionService&)            = delete;
    IngestionService& operator=(const IngestionService&) = delete;
    IngestionService(IngestionService&&)                 = delete;
    IngestionService& operator=(IngestionService&&)      = delete;

private:
    struct SourceState {
        SourceDescriptor                         descriptor;
        std::unique_ptr<std::thread>             thread;      // Acquisition loop
        std::atomic<bool>                        stop_flag{false};
    };

    // Internal helpers -----------------------------------------------------
    void acquisitionLoop(const SourceDescriptor& src, std::shared_ptr<SourceState> state);
    void publishHealthMetric();
    void gracefulShutdown();

    // Members --------------------------------------------------------------
    const IngestionServiceConfig                 cfg_;
    std::shared_ptr<common::EventBus>            event_bus_;
    std::shared_ptr<common::MetricPublisher>     metrics_;

    mutable std::mutex                           mtx_;
    std::unordered_map<std::string, std::shared_ptr<SourceState>> sources_;

    std::atomic<bool>                            running_{false};
    std::condition_variable                      cv_stop_;
    std::unique_ptr<std::thread>                 health_thread_;
};

}  // namespace ci360::ingestion