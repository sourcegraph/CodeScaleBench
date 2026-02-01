```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:    cardio_insight_360/src/event_bus/event_bus_facade.cpp
 *  Author:  CardioInsight360 Core Team
 *
 *  Description:
 *  ------------
 *  Implementation of the EventBusFacade – a thin, thread–safe wrapper around
 *  librdkafka that provides a uniform publish / subscribe API to the rest of
 *  the monolith.  The facade transparently handles Kafka-client life-cycle
 *  management, connection retries, back-pressure, metrics instrumentation, and
 *  graceful shutdown semantics so that upstream modules (ETL pipelines,
 *  strategy plug-ins, pseudo-micro-services) can focus on business logic.
 *
 *  The component is intentionally opinionated:
 *    • One Producer instance per process
 *    • At-most-once delivery semantics (clinical use-case tolerates duplicates
 *      better than lost data; upstream deduplication pipeline exists)
 *    • Consumer group id is derived from <binary-instance-id>:<topic>
 *
 *  NOTE: Header forward declarations live in
 *        cardio_insight_360/include/event_bus/event_bus_facade.hpp
 */

#include "event_bus/event_bus_facade.hpp"

#include "core/config/config_provider.hpp"
#include "core/metrics/metrics_registry.hpp"
#include "utils/logger.hpp"
#include "utils/signal_guard.hpp"

#include <nlohmann/json.hpp>
#include <rdkafka/rdkafkacpp.h>

#include <atomic>
#include <chrono>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ci360::event_bus
{
// ---------------------------------------------------------------------------
// Internal helper types
// ---------------------------------------------------------------------------

/**
 * DeliveryReportCb implementation that feeds metrics registry and logging
 */
class ProducerDeliveryReportCb final : public RdKafka::DeliveryReportCb
{
public:
    explicit ProducerDeliveryReportCb(core::metrics::MetricsRegistry &metrics)
        : _publishSuccess(metrics.counter("event_bus.producer.success")),
          _publishFailure(metrics.counter("event_bus.producer.failure"))
    {
    }

    void dr_cb(RdKafka::Message &message) noexcept override
    {
        if (message.err() == RdKafka::ERR_NO_ERROR)
        {
            _publishSuccess->inc();
        }
        else
        {
            _publishFailure->inc();
            LOG_ERROR("[EventBus] Delivery failed: {} ({})",
                      message.errstr(),
                      static_cast<int>(message.err()));
        }
    }

private:
    core::metrics::Counter *_publishSuccess;
    core::metrics::Counter *_publishFailure;
};

/**
 * Rebalance callback for consumers – logs and metrics only
 */
class RebalanceCb final : public RdKafka::RebalanceCb
{
public:
    explicit RebalanceCb(core::metrics::MetricsRegistry &metrics)
        : _partitionAssigned(metrics.counter("event_bus.consumer.partitions_assigned")),
          _partitionRevoked(metrics.counter("event_bus.consumer.partitions_revoked"))
    {
    }

    void rebalance_cb(RdKafka::KafkaConsumer *consumer,
                      RdKafka::ErrorCode         err,
                      std::vector<RdKafka::TopicPartition *> &partitions) override
    {
        if (err == RdKafka::ERR__ASSIGN_PARTITIONS)
        {
            _partitionAssigned->inc(static_cast<std::uint64_t>(partitions.size()));
            consumer->assign(partitions);
            LOG_INFO("[EventBus] Partitions assigned ({} partitions)", partitions.size());
        }
        else
        {
            _partitionRevoked->inc(static_cast<std::uint64_t>(partitions.size()));
            consumer->unassign();
            LOG_INFO("[EventBus] Partitions revoked / lost ({} partitions)", partitions.size());
        }
    }

private:
    core::metrics::Counter *_partitionAssigned;
    core::metrics::Counter *_partitionRevoked;
};

// ---------------------------------------------------------------------------
// PImpl – hides librdkafka headers from consumers of EventBusFacade.hpp
// ---------------------------------------------------------------------------
class EventBusFacade::Impl
{
public:
    Impl(const core::ConfigProvider &cfg, core::metrics::MetricsRegistry &metrics);
    ~Impl();

    // Non-copyable / non-movable
    Impl(const Impl &)            = delete;
    Impl &operator=(const Impl &) = delete;
    Impl(Impl &&)                 = delete;
    Impl &operator=(Impl &&)      = delete;

    // Business API
    void start();
    void shutdown();

    bool publish(const std::string            &topic,
                 const std::string            &key,
                 const nlohmann::json         &payload,
                 std::chrono::milliseconds     timeout);

    void subscribe(const std::string              &topic,
                   EventBusFacade::EventCallback   callback);

private:
    using ConsumerPtr = std::unique_ptr<RdKafka::KafkaConsumer>;

    void initProducer();
    ConsumerPtr createConsumer(const std::string &topic);

    void consumerLoop(const std::string &topic, ConsumerPtr consumer);

    std::string makeConsumerGroupId(const std::string &topic) const;

    // ---------------------------------------------------------------------
    // Members
    // ---------------------------------------------------------------------
    const core::ConfigProvider &_cfg;
    core::metrics::MetricsRegistry &_metrics;

    std::unique_ptr<RdKafka::Conf> _producerConf;
    std::unique_ptr<RdKafka::Producer> _producer;
    ProducerDeliveryReportCb _deliveryCb;

    std::unordered_map<std::string, EventBusFacade::EventCallback> _callbacks;
    std::vector<std::thread> _consumerThreads;
    std::atomic_bool _running{false};
    std::mutex _callbacksMtx;

    core::metrics::Counter *_consumedOk;
    core::metrics::Counter *_consumedErr;
};

// ---------------------------------------------------------------------------
// Impl – ctor / dtor
// ---------------------------------------------------------------------------
EventBusFacade::Impl::Impl(const core::ConfigProvider &cfg,
                           core::metrics::MetricsRegistry &metrics)
    : _cfg(cfg),
      _metrics(metrics),
      _deliveryCb(metrics),
      _consumedOk(metrics.counter("event_bus.consumer.ok")),
      _consumedErr(metrics.counter("event_bus.consumer.error"))
{
    initProducer();
}

EventBusFacade::Impl::~Impl()
{
    try
    {
        shutdown();
    }
    catch (const std::exception &ex)
    {
        LOG_ERROR("[EventBus] Exception in destructor: {}", ex.what());
    }
    catch (...)
    {
        LOG_ERROR("[EventBus] Unknown exception in destructor");
    }
}

// ---------------------------------------------------------------------------
// Impl – private helpers
// ---------------------------------------------------------------------------
void EventBusFacade::Impl::initProducer()
{
    _producerConf.reset(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL));
    if (!_producerConf)
    {
        throw std::runtime_error("Failed to create global kafka conf");
    }

    std::string errStr;

    const auto bootstrap = _cfg.getString("event_bus.bootstrap_servers", "localhost:9092");
    if (_producerConf->set("bootstrap.servers", bootstrap, errStr) != RdKafka::Conf::CONF_OK)
    {
        throw std::runtime_error("Producer set(bootstrap.servers): " + errStr);
    }

    _producerConf->set("enable.idempotence", "false", errStr); // at-most-once

    // Hook up delivery callback
    if (_producerConf->set("dr_cb", &_deliveryCb, errStr) != RdKafka::Conf::CONF_OK)
    {
        throw std::runtime_error("Producer set(dr_cb): " + errStr);
    }

    _producer.reset(RdKafka::Producer::create(_producerConf.get(), errStr));
    if (!_producer)
    {
        throw std::runtime_error("Failed to create producer: " + errStr);
    }

    LOG_INFO("[EventBus] Producer initialised – bootstrap.servers={}", bootstrap);
}

EventBusFacade::Impl::ConsumerPtr EventBusFacade::Impl::createConsumer(const std::string &topic)
{
    std::unique_ptr<RdKafka::Conf> conf(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL));
    if (!conf)
    {
        throw std::runtime_error("Failed to create consumer conf");
    }

    std::string errStr;
    const auto bootstrap = _cfg.getString("event_bus.bootstrap_servers", "localhost:9092");
    conf->set("bootstrap.servers", bootstrap, errStr);
    conf->set("group.id", makeConsumerGroupId(topic), errStr);
    conf->set("auto.offset.reset", "earliest", errStr);
    conf->set("enable.auto.commit", "true", errStr);
    conf->set("enable.partition.eof", "false", errStr);

    static RebalanceCb rebalanceCb(_metrics);
    conf->set("rebalance_cb", &rebalanceCb, errStr);

    ConsumerPtr consumer(RdKafka::KafkaConsumer::create(conf.get(), errStr));
    if (!consumer)
    {
        throw std::runtime_error("Failed to create consumer: " + errStr);
    }

    const RdKafka::ErrorCode ret = consumer->subscribe({ topic });
    if (ret != RdKafka::ERR_NO_ERROR)
    {
        throw std::runtime_error("Failed to subscribe to topic " + topic + ": "
                                 + RdKafka::err2str(ret));
    }

    LOG_INFO("[EventBus] Consumer created – topic={} group.id={}", topic, makeConsumerGroupId(topic));
    return consumer;
}

std::string EventBusFacade::Impl::makeConsumerGroupId(const std::string &topic) const
{
    // binary-instance-id is configured via CLI argument injection; fallback to hostname
    const std::string instance =
        _cfg.getString("ci360.instance_id", utils::getHostName());
    return instance + ":" + topic;
}

// ---------------------------------------------------------------------------
// Impl – public interface
// ---------------------------------------------------------------------------
void EventBusFacade::Impl::start()
{
    if (_running.exchange(true))
    {
        return; // already running
    }

    // Launch a thread per subscribed topic – simpler than polling all in one
    std::scoped_lock lock(_callbacksMtx);
    for (auto &[topic, cb] : _callbacks)
    {
        ConsumerPtr consumer = createConsumer(topic);

        _consumerThreads.emplace_back(
            [this, topic, cons = std::move(consumer)]() mutable
            { consumerLoop(topic, std::move(cons)); });
    }

    LOG_INFO("[EventBus] Started with {} consumer threads", _consumerThreads.size());
}

void EventBusFacade::Impl::shutdown()
{
    if (!_running.exchange(false))
    {
        return; // already stopped
    }

    // Drain producer
    _producer->flush(5'000);

    // Join consumer threads
    for (auto &t : _consumerThreads)
    {
        if (t.joinable())
        {
            t.join();
        }
    }
    _consumerThreads.clear();

    LOG_INFO("[EventBus] Shutdown completed");
}

bool EventBusFacade::Impl::publish(const std::string            &topic,
                                   const std::string            &key,
                                   const nlohmann::json         &payload,
                                   std::chrono::milliseconds     timeout)
{
    const std::string serialized = payload.dump();

    RdKafka::ErrorCode err = _producer->produce(
        topic,
        RdKafka::Topic::PARTITION_UA,
        RdKafka::Producer::RK_MSG_COPY /* kafka copies payload */,
        const_cast<char *>(serialized.data()),
        serialized.size(),
        &key,
        nullptr /* headers */,
        nullptr /* opaque */);

    if (err != RdKafka::ERR_NO_ERROR)
    {
        LOG_ERROR("[EventBus] Publish failed: {}", RdKafka::err2str(err));
        return false;
    }

    // Drive IO loop; wait up to timeout for delivery (non-blocking publish uses queue)
    _producer->poll(static_cast<int>(timeout.count()));

    return true;
}

void EventBusFacade::Impl::subscribe(const std::string            &topic,
                                     EventBusFacade::EventCallback callback)
{
    std::scoped_lock lock(_callbacksMtx);
    if (_callbacks.find(topic) != _callbacks.end())
    {
        throw std::invalid_argument("Already subscribed to topic: " + topic);
    }
    _callbacks.emplace(topic, std::move(callback));
}

void EventBusFacade::Impl::consumerLoop(const std::string &topic, ConsumerPtr consumer)
{
    constexpr auto POLL_TIMEOUT_MS = 1000;

    while (_running.load(std::memory_order_relaxed))
    {
        std::unique_ptr<RdKafka::Message> msg(consumer->consume(POLL_TIMEOUT_MS));
        if (!msg)
        {
            continue;
        }

        if (msg->err() == RdKafka::ERR__TIMED_OUT)
        {
            continue; // idle poll
        }
        else if (msg->err() != RdKafka::ERR_NO_ERROR)
        {
            _consumedErr->inc();
            LOG_WARN("[EventBus] Consumer error on {}: {}", topic, msg->errstr());
            continue;
        }

        _consumedOk->inc();

        // Parse payload as JSON; guard against malformed messages
        nlohmann::json jsonPayload;
        try
        {
            jsonPayload = nlohmann::json::parse(
                static_cast<const char *>(msg->payload()),
                static_cast<const char *>(msg->payload()) + msg->len());
        }
        catch (const std::exception &ex)
        {
            _consumedErr->inc();
            LOG_ERROR("[EventBus] Malformed JSON on topic {}: {}", topic, ex.what());
            continue;
        }

        // Dispatch to registered callback
        try
        {
            std::scoped_lock lock(_callbacksMtx);
            auto it = _callbacks.find(topic);
            if (it != _callbacks.end())
            {
                it->second(msg->key() ? *msg->key() : "",
                           jsonPayload,
                           *msg);
            }
        }
        catch (const std::exception &ex)
        {
            _consumedErr->inc();
            LOG_ERROR("[EventBus] Callback threw: {}", ex.what());
        }
    }

    consumer->close();
    LOG_INFO("[EventBus] Consumer loop stopped for {}", topic);
}

// ---------------------------------------------------------------------------
// EventBusFacade – thin delegating wrappers
// ---------------------------------------------------------------------------
EventBusFacade::EventBusFacade(const core::ConfigProvider &cfg,
                               core::metrics::MetricsRegistry &metrics)
    : _impl(std::make_unique<Impl>(cfg, metrics))
{
}

EventBusFacade::~EventBusFacade() = default;

void EventBusFacade::start()
{
    _impl->start();
}

void EventBusFacade::shutdown()
{
    _impl->shutdown();
}

bool EventBusFacade::publish(const std::string            &topic,
                             const std::string            &key,
                             const nlohmann::json         &payload,
                             std::chrono::milliseconds     timeout)
{
    return _impl->publish(topic, key, payload, timeout);
}

void EventBusFacade::subscribe(const std::string            &topic,
                               EventBusFacade::EventCallback callback)
{
    _impl->subscribe(topic, std::move(callback));
}

} // namespace ci360::event_bus
```