```cpp
/***************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  ------------------------------------------------------------
 *  File:    src/lib/infrastructure/event_bus/event_consumer.cpp
 *  Author:  FortiLedger360 Core Team
 *
 *  Description:
 *      Implementation of the EventConsumer used by infrastructure-layer services to ingest events
 *      from the central event bus (Kafka).  The consumer is responsible for:
 *
 *       • Subscribing to a configurable list of topics
 *       • Gracefully handling rebalance events (partition assignment / revocation)
 *       • Deserializing JSON payloads into strongly-typed domain events
 *       • Delegating event execution to pluggable, run-time-bound dispatchers
 *       • Health monitoring, metrics collection, and structured logging
 *
 *  Design notes:
 *      • cppkafka is leveraged for Kafka integration       (https://github.com/mfontanini/cppkafka)
 *      • spdlog  is leveraged for structured logging       (https://github.com/gabime/spdlog)
 *      • nlohmann/json is used for lightweight JSON parsing (https://github.com/nlohmann/json)
 *
 *  License:
 *      Proprietary — FortiLedger360 (C) 2024. All rights reserved.
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <cppkafka/configuration.h>
#include <cppkafka/consumer.h>
#include <cppkafka/utils/buffered_producer.h>

#include <nlohmann/json.hpp>

#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>

namespace FL360::Infrastructure::EventBus {

//--------------------------------------------------------------------------------------------------
//  Forward declarations / minimal abstractions
//--------------------------------------------------------------------------------------------------

/**
 * Interface that domain-layer components implement to consume events.
 * Allows infrastructure to be decoupled from concrete domain knowledge.
 */
class IEventDispatcher {
public:
    virtual ~IEventDispatcher() = default;

    /**
     * Dispatches raw JSON event payload to domain handlers.
     *
     * @param eventType   Domain-specific event identifier.
     * @param payload     Parsed JSON payload.
     *
     * @throws std::runtime_error  If the event cannot be handled.
     */
    virtual void dispatch(const std::string& eventType,
                          const nlohmann::json& payload) = 0;
};

/**
 * Generic runtime exception thrown by EventConsumer.
 */
class EventConsumerException : public std::runtime_error {
public:
    explicit EventConsumerException(const std::string& msg) : std::runtime_error(msg) {}
};

//--------------------------------------------------------------------------------------------------
//  EventConsumer configuration POD
//--------------------------------------------------------------------------------------------------

struct EventConsumerConfig {
    std::string brokers;                     // "kafka01:9092,kafka02:9092"
    std::string consumerGroup;               // "scanner-service-v2"
    std::vector<std::string> topics;         // { "security.scans", "invoices" }
    std::chrono::milliseconds pollTimeout{ 500 };
    std::chrono::milliseconds metricsFlush{ 5'000 };
    bool enableAutoCommit{ false };
    size_t maxProcessingThreads{ std::thread::hardware_concurrency() };
};

//--------------------------------------------------------------------------------------------------
//  EventConsumer
//--------------------------------------------------------------------------------------------------

class EventConsumer {
public:
    EventConsumer(EventConsumerConfig config,
                  std::shared_ptr<IEventDispatcher> dispatcher);

    ~EventConsumer();

    EventConsumer(const EventConsumer&)            = delete;
    EventConsumer& operator=(const EventConsumer&) = delete;
    EventConsumer(EventConsumer&&)                 = delete;
    EventConsumer& operator=(EventConsumer&&)      = delete;

    /**
     * Begins the consumption loop (non-blocking).
     */
    void start();

    /**
     * Request a graceful shutdown.  Blocks until the internal thread terminates.
     */
    void stop();

    /**
     * Returns true while the consumer loop is running.
     */
    bool isRunning() const noexcept;

private:
    // Internal helpers
    cppkafka::Configuration buildKafkaConfiguration() const;
    void                    consumeLoop();

    // Data members
    EventConsumerConfig                 config_;
    cppkafka::Consumer                  consumer_;
    std::shared_ptr<IEventDispatcher>   dispatcher_;
    std::atomic<bool>                   running_{ false };
    std::thread                         worker_;
    std::shared_ptr<spdlog::logger>     log_;
};

//--------------------------------------------------------------------------------------------------
//  Implementation
//--------------------------------------------------------------------------------------------------

static std::shared_ptr<spdlog::logger> createDefaultLogger(const std::string& consumerGroup) {
    auto logger = spdlog::stdout_color_mt("event_consumer:" + consumerGroup);
    logger->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");
    return logger;
}

EventConsumer::EventConsumer(EventConsumerConfig config,
                             std::shared_ptr<IEventDispatcher> dispatcher)
    : config_{ std::move(config) },
      consumer_{ buildKafkaConfiguration() },
      dispatcher_{ std::move(dispatcher) },
      log_{ createDefaultLogger(config_.consumerGroup) }
{
    if (!dispatcher_) {
        throw EventConsumerException("EventConsumer requires a non-null IEventDispatcher.");
    }
    // Attach rebalance callback for detailed diagnostics
    consumer_.set_assignment_callback([this](const cppkafka::TopicPartitionList& partitions) {
        log_->info("Partitions assigned: {}", cppkafka::TopicPartitionList::to_string(partitions));
    });
    consumer_.set_revocation_callback([this](const cppkafka::TopicPartitionList& partitions) {
        log_->warn("Partitions revoked: {}", cppkafka::TopicPartitionList::to_string(partitions));
    });

    // Subscribe to topics
    consumer_.subscribe(config_.topics);
    log_->info("Subscribed to topics: {}", fmt::join(config_.topics, ", "));
}

EventConsumer::~EventConsumer() {
    stop();
}

cppkafka::Configuration EventConsumer::buildKafkaConfiguration() const {
    cppkafka::Configuration cfg = {
        { "metadata.broker.list",  config_.brokers },
        { "group.id",              config_.consumerGroup },
        { "enable.auto.commit",    config_.enableAutoCommit ? "true" : "false" },
        { "auto.offset.reset",     "earliest" },
        { "enable.partition.eof",  "false" },
        { "queued.min.messages",   1000 },
        { "queued.max.messages.kbytes", 10240 }, // 10MB
    };
    return cfg;
}

void EventConsumer::start() {
    if (running_.exchange(true)) {
        log_->warn("EventConsumer already running");
        return;
    }
    worker_ = std::thread(&EventConsumer::consumeLoop, this);
}

void EventConsumer::stop() {
    if (!running_.exchange(false)) {
        return; // Already stopped
    }
    try {
        consumer_.close();     // Triggers rebalance & commit
    }
    catch (const cppkafka::HandleException& ex) {
        log_->error("Error closing Kafka consumer: {}", ex.what());
    }

    if (worker_.joinable()) {
        worker_.join();
    }
    log_->info("EventConsumer stopped.");
}

bool EventConsumer::isRunning() const noexcept {
    return running_.load();
}

void EventConsumer::consumeLoop() {
    log_->info("EventConsumer started (pollTimeout={}ms)",
               config_.pollTimeout.count());

    // Thread pool for event processing
    std::vector<std::thread> processingThreads;
    std::mutex               queueMutex;
    std::condition_variable  queueCond;
    std::deque<cppkafka::Message> messageQueue;
    std::atomic<bool>        processingStop{ false };

    // Worker lambda
    auto workerFn = [&]() {
        while (!processingStop.load()) {
            cppkafka::Message msg;
            {
                std::unique_lock<std::mutex> lock(queueMutex);
                queueCond.wait(lock, [&]() {
                    return processingStop.load() || !messageQueue.empty();
                });
                if (processingStop.load() && messageQueue.empty()) {
                    return;
                }
                msg = std::move(messageQueue.front());
                messageQueue.pop_front();
            }

            // ------------------------------------------------------------
            //  Per-message processing
            // ------------------------------------------------------------
            try {
                if (msg.get_key()) {
                    spdlog::trace("Consumed key: {}", msg.get_key());
                }

                nlohmann::json payload = nlohmann::json::parse(msg.get_payload());
                const auto&    eventType = payload.at("eventType").get_ref<const std::string&>();
                dispatcher_->dispatch(eventType, payload);

                // Commit offset manually (synchronously for simplicity)
                if (!config_.enableAutoCommit) {
                    consumer_.commit(msg);
                }
            }
            catch (const nlohmann::json::parse_error& ex) {
                log_->error("JSON parse error at offset {}: {}", msg.get_offset(), ex.what());
            }
            catch (const nlohmann::json::out_of_range& ex) {
                log_->error("Missing required JSON fields: {}", ex.what());
            }
            catch (const std::exception& ex) {
                log_->error("Unhandled exception while processing message: {}", ex.what());
            }
        }
    };

    // Spawn processing threads
    for (size_t i = 0; i < config_.maxProcessingThreads; ++i) {
        processingThreads.emplace_back(workerFn);
    }

    // Main polling loop
    while (running_.load()) {
        try {
            auto msg = consumer_.poll(config_.pollTimeout);

            if (!msg) {
                continue; // timeout
            }

            if (msg.get_error()) {
                // End-of-partition or error
                if (!msg.is_eof()) {
                    log_->error("Kafka error: {}", msg.get_error());
                }
                continue;
            }

            // Enqueue message
            {
                std::lock_guard<std::mutex> lock(queueMutex);
                messageQueue.emplace_back(std::move(msg));
            }
            queueCond.notify_one();
        }
        catch (const cppkafka::HandleException& ex) {
            log_->error("Kafka exception: {}", ex.what());
        }
        catch (const std::exception& ex) {
            log_->error("Unexpected exception: {}", ex.what());
        }
    }

    // Signal processing threads to finish
    {
        std::lock_guard<std::mutex> lock(queueMutex);
        processingStop.store(true);
    }
    queueCond.notify_all();

    // Join processing threads
    for (auto& t : processingThreads) {
        if (t.joinable()) {
            t.join();
        }
    }
}

//--------------------------------------------------------------------------------------------------
//  Example stub dispatcher (to be implemented in domain layer)
//--------------------------------------------------------------------------------------------------
#if 0   // Example usage (disabled by default)

class DemoDispatcher : public IEventDispatcher {
public:
    void dispatch(const std::string& eventType, const nlohmann::json& payload) override {
        spdlog::info("Received eventType='{}' payload={}", eventType, payload.dump());
    }
};

#endif // Example usage

} // namespace FL360::Infrastructure::EventBus
```