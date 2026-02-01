#ifndef CARDIO_INSIGHT_360_EVENT_BUS_FACADE_H_
#define CARDIO_INSIGHT_360_EVENT_BUS_FACADE_H_

/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * event_bus_facade.h
 *
 * A thin, thread–safe façade over librdkafka that standardises message
 * publishing/subscription semantics for the rest of the monolith.  The class
 * exposes a simplified API while internally handling the gnarly details of
 * Kafka initialisation, re-connection, polling loops, back-pressure, and
 * graceful teardown.
 *
 * The façade is intentionally header-only to reduce link-time coupling across
 * the monolith’s many shared objects.  It should therefore stay light-weight
 * and avoid dragging heavy implementation dependencies into translation units.
 *
 * Author: CardioInsight360 Engineering
 * Copyright (c) 2024
 */

#include <rdkafka/rdkafka.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace cardio::event_bus {

/* ===========================================================================
 *  Configuration
 * ======================================================================== */
struct EventBusConfig {
    std::string brokers              = "localhost:9092";
    std::string groupId              = "cardioinsight360";
    std::size_t  ioQueueCapacity     = 10000;                 // Local queue
    int          retries             = 3;
    std::chrono::milliseconds pollInterval{100};
    std::chrono::milliseconds linger{5};
    bool         enableIdempotence   = true;
};

/* ===========================================================================
 *  Exceptions
 * ======================================================================== */
class EventBusException : public std::runtime_error {
public:
    explicit EventBusException(const std::string& msg) : std::runtime_error(msg) {}
};

/* ===========================================================================
 *  EventBusFacade
 * ======================================================================== */
class EventBusFacade {
public:
    using Timestamp       = std::chrono::system_clock::time_point;
    using EventCallback   = std::function<void(const std::string& topic,
                                               const std::string& key,
                                               const std::string& payload,
                                               Timestamp ts)>;

    using SubscriptionId  = std::uint64_t;

    /* -----------------------------------------------------------------------
     *  Accessor for the single, process-wide instance.
     * -------------------------------------------------------------------- */
    static EventBusFacade& instance() {
        static EventBusFacade bus;   // Meyers singleton
        return bus;
    }

    /* -----------------------------------------------------------------------
     *  Non-copyable / non-movable – centralised global resource
     * -------------------------------------------------------------------- */
    EventBusFacade(const EventBusFacade&)            = delete;
    EventBusFacade(EventBusFacade&&)                 = delete;
    EventBusFacade& operator=(const EventBusFacade&) = delete;
    EventBusFacade& operator=(EventBusFacade&&)      = delete;

    /* -----------------------------------------------------------------------
     *  Lifecycle
     * -------------------------------------------------------------------- */
    void initialise(EventBusConfig cfg = {}) {
        std::lock_guard<std::mutex> lk(initMtx_);
        if (initialised_) { return; }

        cfg_ = std::move(cfg);
        createProducer();
        createConsumer();
        startPollThread();
        initialised_ = true;
    }

    void shutdown() noexcept {
        std::lock_guard<std::mutex> lk(initMtx_);
        if (!initialised_) { return; }

        stopRequested_.store(true);
        if (pollThread_.joinable()) { pollThread_.join(); }

        if (producer_) { rd_kafka_flush(producer_.get(), 5000); }
        producer_.reset();
        consumer_.reset();
        initialised_ = false;
    }

    ~EventBusFacade() {
        try {
            shutdown();
        } catch (...) {
            // Destructors must not throw.
        }
    }

    /* -----------------------------------------------------------------------
     *  Publishing
     * -------------------------------------------------------------------- */
    void publish(const std::string& topic,
                 const std::string& key,
                 const std::string& payload,
                 std::chrono::milliseconds timeout = std::chrono::milliseconds{3000})
    {
        ensureInitialised();

        rd_kafka_topic_t* rkt = rd_kafka_topic_new(producer_.get(), topic.c_str(), nullptr);
        if (!rkt) {
            throw EventBusException("Failed to create rd_kafka_topic_t");
        }

        /* Note: rd_kafka_topic_new is ref-counted against producer_ */
        auto rkt_guard = std::unique_ptr<rd_kafka_topic_t, decltype(&rd_kafka_topic_destroy)>(
            rkt, &rd_kafka_topic_destroy);

        constexpr int partition = RD_KAFKA_PARTITION_UA;

        if (RD_KAFKA_RESP_ERR_NO_ERROR != rd_kafka_produce(
                rkt,
                partition,
                RD_KAFKA_MSG_F_COPY,
                const_cast<char*>(payload.data()),
                payload.size(),
                key.data(), key.size(),
                nullptr))
        {
            std::ostringstream oss;
            oss << "rd_kafka_produce failed: "
                << rd_kafka_err2str(rd_kafka_last_error());
            throw EventBusException(oss.str());
        }

        // Poll producer queue to invoke delivery callbacks
        rd_kafka_poll(producer_.get(), static_cast<int>(timeout.count()));
    }

    /* Type-safe publishing for protobuf/flatbuffers/etc. */
    template <typename Serializable>
    void publish(const std::string& topic,
                 const std::string& key,
                 const Serializable& msg)
    {
        std::string payload;
        if (!msg.SerializeToString(&payload)) {
            throw EventBusException("Failed to serialise message.");
        }
        publish(topic, key, payload);
    }

    /* -----------------------------------------------------------------------
     *  Subscribing
     * -------------------------------------------------------------------- */
    SubscriptionId subscribe(const std::string& topic, EventCallback cb) {
        ensureInitialised();

        SubscriptionId id = nextSubId_.fetch_add(1, std::memory_order_relaxed);
        {
            std::unique_lock<std::shared_mutex> lk(subMtx_);
            subscriptions_.emplace(id,
                                   Subscription{ topic, std::move(cb) });
            rebuildTopicSubscription();   // Re-evaluate subscription list
        }
        return id;
    }

    void unsubscribe(SubscriptionId id) {
        std::unique_lock<std::shared_mutex> lk(subMtx_);
        if (subscriptions_.erase(id)) {
            rebuildTopicSubscription();
        }
    }

private:
    /* ===========================================================================
     *  Internal types
     * ======================================================================== */
    struct RdKafkaDeleter {
        void operator()(rd_kafka_t* ptr) const noexcept {
            if (ptr) { rd_kafka_destroy(ptr); }
        }
    };

    struct Subscription {
        std::string   topic;
        EventCallback cb;
    };

    /* ===========================================================================
     *  Construction helpers
     * ======================================================================== */
    EventBusFacade() = default;

    void createProducer() {
        char errstr[512]{};
        rd_kafka_conf_t* conf = rd_kafka_conf_new();

        rd_kafka_conf_set(conf, "bootstrap.servers", cfg_.brokers.c_str(), errstr, sizeof(errstr));
        rd_kafka_conf_set(conf, "queue.buffering.max.messages",
                          std::to_string(cfg_.ioQueueCapacity).c_str(),
                          errstr, sizeof(errstr));
        rd_kafka_conf_set(conf, "enable.idempotence",
                          cfg_.enableIdempotence ? "true" : "false",
                          errstr, sizeof(errstr));
        rd_kafka_conf_set(conf, "linger.ms",
                          std::to_string(cfg_.linger.count()).c_str(),
                          errstr, sizeof(errstr));

        rd_kafka_t* producer = rd_kafka_new(RD_KAFKA_PRODUCER, conf, errstr, sizeof(errstr));
        if (!producer) {
            throw EventBusException(std::string("Failed to create producer: ") + errstr);
        }
        producer_.reset(producer);
    }

    void createConsumer() {
        char errstr[512]{};
        rd_kafka_conf_t* conf = rd_kafka_conf_new();

        rd_kafka_conf_set(conf, "bootstrap.servers", cfg_.brokers.c_str(), errstr, sizeof(errstr));
        rd_kafka_conf_set(conf, "group.id", cfg_.groupId.c_str(), errstr, sizeof(errstr));
        rd_kafka_conf_set(conf, "enable.auto.commit", "true", errstr, sizeof(errstr));

        rd_kafka_t* consumer = rd_kafka_new(RD_KAFKA_CONSUMER, conf, errstr, sizeof(errstr));
        if (!consumer) {
            throw EventBusException(std::string("Failed to create consumer: ") + errstr);
        }

        // Subscribe to a dummy topic list; will be overwritten in rebuildTopicSubscription()
        rd_kafka_poll_set_consumer(consumer);
        consumer_.reset(consumer);
    }

    /* ===========================================================================
     *  Polling loop
     * ======================================================================== */
    void startPollThread() {
        pollThread_ = std::thread([this]() {
            while (!stopRequested_.load()) {
                pollOnce();
                std::this_thread::sleep_for(cfg_.pollInterval);
            }
        });
    }

    void pollOnce() {
        ensureInitialised();

        rd_kafka_message_t* msg = rd_kafka_consumer_poll(consumer_.get(),
                                                         static_cast<int>(cfg_.pollInterval.count()));
        if (!msg) { return; }

        std::unique_ptr<rd_kafka_message_t, decltype(&rd_kafka_message_destroy)>
            msg_guard(msg, &rd_kafka_message_destroy);

        if (msg->err == RD_KAFKA_RESP_ERR_NO_ERROR) {
            std::string topic  = rd_kafka_topic_name(msg->rkt);
            std::string key    = (msg->key_len > 0 && msg->key)
                                 ? std::string(static_cast<char*>(msg->key), msg->key_len)
                                 : "";
            std::string payload(static_cast<char*>(msg->payload), msg->len);

            // Snapshot subscription map without holding lock during callbacks
            std::vector<EventCallback> callbacks;
            {
                std::shared_lock<std::shared_mutex> lk(subMtx_);
                for (auto& [_, sub] : subscriptions_) {
                    if (sub.topic == topic) { callbacks.emplace_back(sub.cb); }
                }
            }

            for (auto& cb : callbacks) {
                try {
                    cb(topic, key, payload, std::chrono::system_clock::now());
                } catch (const std::exception& ex) {
                    // User callback must not crash poll thread; log and continue.
                    logError("Event callback threw: ", ex.what());
                }
            }
        } else if (msg->err != RD_KAFKA_RESP_ERR__PARTITION_EOF &&
                   msg->err != RD_KAFKA_RESP_ERR__TIMED_OUT)
        {
            logError("Kafka consumer error: ", rd_kafka_message_errstr(msg));
        }
    }

    /* ===========================================================================
     *  Helpers
     * ======================================================================== */
    void rebuildTopicSubscription() {
        // Build topic list
        rd_kafka_topic_partition_list_t* tpl = rd_kafka_topic_partition_list_new(
            static_cast<int>(subscriptions_.size()));

        for (auto& [_, sub] : subscriptions_) {
            rd_kafka_topic_partition_list_add(tpl, sub.topic.c_str(),
                                              RD_KAFKA_PARTITION_UA);
        }

        rd_kafka_resp_err_t err = rd_kafka_subscribe(consumer_.get(), tpl);
        rd_kafka_topic_partition_list_destroy(tpl);

        if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
            std::ostringstream oss;
            oss << "rd_kafka_subscribe failed: " << rd_kafka_err2str(err);
            throw EventBusException(oss.str());
        }
    }

    void ensureInitialised() const {
        if (!initialised_) { throw EventBusException("EventBusFacade not initialised."); }
    }

    template <typename... Args>
    static void logError(Args&&... args) noexcept {
        // Very light-weight logging to std::cerr; replace with spdlog or similar.
        (std::cerr << ... << args) << '\n';
    }

    /* ===========================================================================
     *  Data members
     * ======================================================================== */
    EventBusConfig cfg_;

    std::unique_ptr<rd_kafka_t, RdKafkaDeleter> producer_;
    std::unique_ptr<rd_kafka_t, RdKafkaDeleter> consumer_;

    std::atomic<bool>        initialised_{false};
    std::atomic<bool>        stopRequested_{false};

    std::thread              pollThread_;
    mutable std::mutex       initMtx_;

    std::shared_mutex        subMtx_;
    std::unordered_map<SubscriptionId, Subscription> subscriptions_;
    std::atomic<SubscriptionId> nextSubId_{1};
};

}  // namespace cardio::event_bus

#endif  // CARDIO_INSIGHT_360_EVENT_BUS_FACADE_H_
