```cpp
/**
 * cardio_insight_360/src/ingestion/ingestion_service.cpp
 *
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 *  Ingestion Service:
 *      • Listens to upstream Kafka topics that carry HL7/FHIR payloads
 *      • Validates messages against domain-specific rules
 *      • Persists raw data into the Data-Lake façade
 *      • Publishes validated events to the internal streaming bus
 *      • Emits real-time metrics via Observer pattern
 *
 *  Copyright (c) 2024
 *  Author: Clinical Engineering Group
 */

#include "ingestion_service.h"

#include <chrono>
#include <exception>
#include <memory>
#include <thread>
#include <utility>

#include <tbb/parallel_for.h>
#include <tbb/blocked_range.h>
#include <tbb/task_arena.h>

#include <librdkafka/rdkafkacpp.h>

#include "common/logger.h"
#include "common/metrics/metrics_collector.h"
#include "common/telemetry/tracing.h"
#include "events/event_bus.h"
#include "etl/storage/data_lake_facade.h"
#include "hl7/hl7_parser.h"
#include "hl7/hl7_validator.h"

using namespace cardio_insight_360;

namespace {

/* --------------------------------------------------------------
 *  Kafka callback helpers
 * -------------------------------------------------------------- */
class KafkaRebalanceCb final : public RdKafka::RebalanceCb {
public:
    void rebalance_cb(RdKafka::KafkaConsumer* consumer,
                      RdKafka::ErrorCode err,
                      std::vector<RdKafka::TopicPartition*>& partitions) override {
        switch (err) {
        case RdKafka::ERR__ASSIGN_PARTITIONS:
            Logger::debug("IngestionService: Partition assignment received.");
            consumer->assign(partitions);
            break;
        case RdKafka::ERR__REVOKE_PARTITIONS:
            Logger::debug("IngestionService: Partition revocation received.");
            consumer->unassign();
            break;
        default:
            Logger::warn("IngestionService: Rebalance error: {}", RdKafka::err2str(err));
            consumer->unassign();
            break;
        }
    }
};

class KafkaEventCb final : public RdKafka::EventCb {
public:
    void event_cb(RdKafka::Event& event) override {
        switch (event.type()) {
        case RdKafka::Event::EVENT_ERROR:
            Logger::error("Kafka error: {} – {}", event.err(), event.str());
            MetricsCollector::instance().increment("ingestion.kafka.error_total");
            break;
        case RdKafka::Event::EVENT_STATS:
            MetricsCollector::instance().gauge("ingestion.kafka.stats", 1); // placeholder
            break;
        default:
            break;
        }
    }
};

} // unnamed namespace

/* --------------------------------------------------------------------------
 *  IngestionService Implementation
 * -------------------------------------------------------------------------- */

IngestionService::IngestionService(const IngestionConfig& cfg)
    : config_{cfg}
    , running_{false}
    , arena_{tbb::task_arena::automatic} {

    Logger::info("IngestionService: Initializing with topic '{}'", config_.kafkaTopic);

    /* ----------------------------
     *  Kafka Consumer Construction
     * ---------------------------- */
    std::unique_ptr<RdKafka::Conf> globalConf{RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL)};
    std::unique_ptr<RdKafka::Conf> topicConf{RdKafka::Conf::create(RdKafka::Conf::CONF_TOPIC)};

    if (!globalConf || !topicConf) {
        throw std::runtime_error("Failed to create RdKafka::Conf objects.");
    }

    std::string err;
    globalConf->set("bootstrap.servers", config_.bootstrapServers, err);
    globalConf->set("group.id", config_.consumerGroupId, err);
    globalConf->set("enable.auto.commit", "false", err);
    globalConf->set("fetch.wait.max.ms", std::to_string(config_.fetchWaitMs), err);
    globalConf->set("event_cb", &eventCb_, err);
    globalConf->set("rebalance_cb", &rebalanceCb_, err);

    consumer_.reset(RdKafka::KafkaConsumer::create(globalConf.get(), err));
    if (!consumer_) {
        throw std::runtime_error("Failed to create KafkaConsumer: " + err);
    }

    Logger::info("Kafka consumer created: {}", consumer_->name());

    /* Subscribe to topic */
    auto errCode = consumer_->subscribe({config_.kafkaTopic});
    if (errCode != RdKafka::ERR_NO_ERROR) {
        throw std::runtime_error("Failed to subscribe to topic: " + RdKafka::err2str(errCode));
    }

    /* Pre-allocate helper objects */
    parser_     = std::make_unique<HL7Parser>();
    validator_  = std::make_unique<HL7Validator>();
    dataLake_   = std::make_unique<DataLakeFacade>(config_.dataLakeRoot);
    eventBus_   = std::make_shared<EventBus>();

    Logger::info("IngestionService: Initialized successfully.");
}

IngestionService::~IngestionService() {
    stop();
}

void IngestionService::start() {
    if (running_) return;
    running_ = true;

    MetricsCollector::instance().set("ingestion.running_state", 1);

    /* Spawn worker thread (detached) */
    worker_ = std::thread([this] { consumeLoop(); });
    Logger::info("IngestionService: Started.");
}

void IngestionService::stop() {
    if (!running_) return;
    running_ = false;

    Logger::info("IngestionService: Stopping…");

    /* Shut down Kafka consumer gracefully */
    if (consumer_) {
        consumer_->close();
    }

    /* Join worker thread */
    if (worker_.joinable()) {
        worker_.join();
    }

    MetricsCollector::instance().set("ingestion.running_state", 0);
    Logger::info("IngestionService: Stopped.");
}

void IngestionService::consumeLoop() noexcept {
    const int kPollTimeoutMs = 100;

    while (running_) {
        std::unique_ptr<RdKafka::Message> msg{consumer_->consume(kPollTimeoutMs)};
        switch (msg->err()) {
        case RdKafka::ERR_NO_ERROR:
            /* Process message inside TBB arena for scalability */
            arena_.execute([this, payload = std::string{static_cast<const char*>(msg->payload()), msg->len()}] {
                processMessage(payload);
            });
            break;

        case RdKafka::ERR__TIMED_OUT:
            /* Poll timeout; nothing to do */
            break;

        default:
            Logger::warn("Kafka ingestion error: {}", msg->errstr());
            MetricsCollector::instance().increment("ingestion.kafka.consume_error_total");
            break;
        }
    }
}

void IngestionService::processMessage(const std::string& rawMsg) noexcept {
    SpanGuard span("IngestionService::processMessage"); // OpenTracing helper

    try {
        MetricsCollector::instance().increment("ingestion.msg_received_total");

        /* 1. Parse */
        auto hl7Message = parser_->parse(rawMsg);

        /* 2. Validate business rules */
        if (!validator_->validate(*hl7Message)) {
            MetricsCollector::instance().increment("ingestion.msg_invalid_total");
            Logger::warn("IngestionService: Validation failed. Message dropped.");
            return;
        }

        /* 3. Persist raw data (append-mode) */
        dataLake_->appendRaw(hl7Message->timestamp, rawMsg);

        /* 4. Publish to internal Event-Bus for downstream processing */
        eventBus_->publish(Event{
            .timestamp = hl7Message->timestamp,
            .payload   = hl7Message->toJson(),
            .type      = EventType::HL7_INGESTED
        });

        MetricsCollector::instance().increment("ingestion.msg_processed_total");
    } catch (const std::exception& ex) {
        MetricsCollector::instance().increment("ingestion.msg_exception_total");
        Logger::error("IngestionService: Exception while processing message – {}", ex.what());
    }
}
```