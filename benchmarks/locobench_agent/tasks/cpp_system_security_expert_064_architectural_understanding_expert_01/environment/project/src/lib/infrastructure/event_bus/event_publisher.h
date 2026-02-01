```cpp
#pragma once
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File:        FortiLedger360/src/lib/infrastructure/event_bus/event_publisher.h
 *  Description: Thread-safe, asynchronous event publisher façade used by upper-
 *               layer services to push domain events onto the platform’s 
 *               message backbone (Kafka, NATS, RabbitMQ, etc.).  The interface 
 *               is intentionally broker-agnostic—an internal worker translates 
 *               the high-level envelope to the concrete broker protocol.
 *
 *  Notes:
 *      • Header-only to avoid introducing a separate compilation unit inside
 *        plugin-based micro-front-ends. 
 *      • Uses STL primitives only; broker specific I/O is abstracted behind a
 *        pluggable Strategy (see _sendToBroker).
 *      • Designed for C++17 and later.
 *
 *  Copyright:
 *      © 2024 FortiLedger360. All Rights Reserved.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include <nlohmann/json.hpp>   // MIT-licensed JSON parser (header-only)

// -----------------------------------------------------------------------------
// Namespace helpers
// -----------------------------------------------------------------------------
namespace fl360   {  // FortiLedger360 shorthand
namespace infr    {  // Infrastructure layer
namespace bus     {  // Event-Bus
// -----------------------------------------------------------------------------

/**
 * QoSLevel
 * --------
 * Messaging quality-of-service semantics exposed to callers.  Not every broker
 * supports true Exactly-Once, but including it in the contract allows the
 * gateway adaptor to downgrade or simulate where necessary.
 */
enum class QoSLevel : std::uint8_t
{
    AtMostOnce  = 0,   // Fire & forget
    AtLeastOnce = 1,   // Retry until acknowledged (default)
    ExactlyOnce = 2    // Idempotent/transactional (best-effort)
};

/**
 * EventEnvelope
 * -------------
 * Immutable metadata wrapper around the actual business payload.
 * 
 *      +-------------+------------------------------------------------+
 *      |  Field      | Description                                    |
 *      +-------------+------------------------------------------------+
 *      | id          | Globally unique event identifier (UUIDv4)      |
 *      | tenantId    | Tenant / customer the event belongs to         |
 *      | type        | Logical event type, e.g. “InitiateScan”        |
 *      | payload     | Arbitrary JSON document                        |
 *      | occurredAt  | UTC timepoint when event originated            |
 *      +-------------+------------------------------------------------+
 */
struct EventEnvelope
{
    std::string                  id;
    std::string                  tenantId;
    std::string                  type;
    nlohmann::json               payload;
    std::chrono::system_clock::time_point occurredAt;

    EventEnvelope() = default;

    EventEnvelope(std::string  id_,
                  std::string  tenantId_,
                  std::string  type_,
                  nlohmann::json payload_,
                  std::chrono::system_clock::time_point occuredAt_ = 
                      std::chrono::system_clock::now())
        : id(std::move(id_)),
          tenantId(std::move(tenantId_)),
          type(std::move(type_)),
          payload(std::move(payload_)),
          occurredAt(occuredAt_)
    {}

    // Convenience factory for now() timestamp
    static EventEnvelope create(std::string id,
                                std::string tenantId,
                                std::string type,
                                nlohmann::json payload)
    {
        return { std::move(id),
                 std::move(tenantId),
                 std::move(type),
                 std::move(payload),
                 std::chrono::system_clock::now() };
    }
};

/**
 * EventPublisher
 * --------------
 * Thread-safe façade for pushing EventEnvelope messages to the event-bus.
 * 
 *  – Provides bounded internal queue to decouple producer latency from broker
 *    RTT. 
 *  – Automatic background worker handles reconnection attempts.
 *  – Graceful shutdown w/ flush() guarantees all queued items are dispatched
 *    before destruction.
 */
class EventPublisher
{
    // ---------------------------------------------------------------------
    // Custom exceptions
    // ---------------------------------------------------------------------
public:
    class publisher_error : public std::runtime_error
    {
    public:
        explicit publisher_error(const std::string& msg)
            : std::runtime_error("[EventPublisher] " + msg) {}
    };

    class queue_overflow : public publisher_error
    {
    public:
        explicit queue_overflow()
            : publisher_error("async queue capacity exceeded") {}
    };

    // ---------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------
public:
    using BrokerSendFunc = std::function<void(
        const EventEnvelope&, const std::string&, QoSLevel)>;

    /**
     * Ctor
     * @param brokerUri      Connection string (e.g., kafka://…)
     * @param clientId       Logical application identifier
     * @param maxQueueSize   Bound for internal queue
     * @param sendFunc       Strategy to actually push to broker
     */
    explicit EventPublisher(std::string   brokerUri,
                            std::string   clientId,
                            std::size_t   maxQueueSize  = 4'096,
                            BrokerSendFunc sendFunc     = nullptr)
        : _brokerUri(std::move(brokerUri))
        , _clientId(std::move(clientId))
        , _maxQueueSize(maxQueueSize)
        , _sendFunc(std::move(sendFunc))
        , _running(true)
    {
        if (_maxQueueSize == 0)
            throw publisher_error("maxQueueSize must be > 0");

        // Default send function that simply discards the message.
        if (!_sendFunc)
        {
            _sendFunc = [](const EventEnvelope&, const std::string&, QoSLevel)
            {
                // In production, inject Kafka/NATS producer here.
            };
        }

        _worker = std::thread(&EventPublisher::_workerThread, this);
    }

    /**
     * Non-copyable but movable
     */
    EventPublisher(const EventPublisher&)            = delete;
    EventPublisher& operator=(const EventPublisher&) = delete;

    EventPublisher(EventPublisher&&) noexcept            = delete;
    EventPublisher& operator=(EventPublisher&&) noexcept = delete;

    /**
     * Dtor – flush remaining events, stop worker.
     */
    ~EventPublisher()
    {
        try
        {
            shutdown();
        }
        catch (...)
        {
            // Destructors must not throw – swallow exception but log in prod.
        }
    }

    /**
     * publish
     * -------
     * Enqueue an event for asynchronous dispatch.
     *
     * @param envelope  Immutable event container (copied into queue).
     * @param topic     Broker topic/subject.
     * @param qos       Desired delivery guarantee.
     *
     * @throws queue_overflow if internal buffer is full.
     */
    void publish(const EventEnvelope& envelope,
                 const std::string&  topic,
                 QoSLevel            qos = QoSLevel::AtLeastOnce)
    {
        {
            std::unique_lock<std::mutex> lock(_queueMutex);
            if (_queue.size() >= _maxQueueSize)
            {
                throw queue_overflow();
            }
            _queue.emplace(Task{envelope, topic, qos});
        }
        _queueCv.notify_one();
    }

    /**
     * flush
     * -----
     * Block caller until all already-queued events are handed off to broker.
     * Does NOT stop the worker thread.
     */
    void flush()
    {
        std::unique_lock<std::mutex> lock(_queueMutex);
        _flushedCv.wait(lock, [this] { return _queue.empty(); });
    }

    /**
     * shutdown
     * --------
     * Gracefully stop background worker; wait for all outstanding events.
     * Safe to call multiple times.
     */
    void shutdown()
    {
        bool expected = true;
        if (_running.compare_exchange_strong(expected, false))
        {
            _queueCv.notify_all();
            if (_worker.joinable())
                _worker.join();
        }
    }

    /**
     * Accessors
     */
    [[nodiscard]] const std::string& brokerUri() const noexcept { return _brokerUri; }
    [[nodiscard]] const std::string& clientId()  const noexcept { return _clientId;  }
    [[nodiscard]] std::size_t        maxQueue()  const noexcept { return _maxQueueSize; }

    /**
     * Queue metrics (non-blocking approximate)
     */
    [[nodiscard]] std::size_t queued() const
    {
        std::lock_guard<std::mutex> guard(_queueMutex);
        return _queue.size();
    }

    [[nodiscard]] bool isRunning() const noexcept { return _running.load(); }

    // ---------------------------------------------------------------------
    // Internal implementation
    // ---------------------------------------------------------------------
private:
    struct Task
    {
        EventEnvelope envelope;
        std::string   topic;
        QoSLevel      qos;
    };

    void _workerThread()
    {
        // Consumer loop
        while (_running.load() || !_queue.empty())
        {
            Task task;
            {
                std::unique_lock<std::mutex> lock(_queueMutex);
                _queueCv.wait(lock, [this] {
                    return !_running.load() || !_queue.empty();
                });

                if (_queue.empty())
                    continue;

                task = std::move(_queue.front());
                _queue.pop();
            }

            try
            {
                _sendToBroker(task);
            }
            catch (const std::exception& ex)
            {
                _handleSendFailure(task, ex);
            }

            // Notify flush() waiters when queue drains
            {
                std::lock_guard<std::mutex> lock(_queueMutex);
                if (_queue.empty())
                {
                    _flushedCv.notify_all();
                }
            }
        }
    }

    void _sendToBroker(const Task& task)
    {
        // Delegated to injected strategy (e.g., Kafka producer)
        _sendFunc(task.envelope, task.topic, task.qos);
    }

    void _handleSendFailure(const Task& task, const std::exception& ex)
    {
        // Basic exponential backoff w/ bounded retries
        static constexpr int maxRetries   = 5;
        static constexpr auto baseBackoff = std::chrono::milliseconds(100);

        for (int attempt = 1; attempt <= maxRetries && _running.load(); ++attempt)
        {
            try
            {
                std::this_thread::sleep_for(baseBackoff * attempt);
                _sendFunc(task.envelope, task.topic, task.qos);
                return; // success
            }
            catch (...)
            {
                // continue retrying
            }
        }

        // Too many failures: escalate (in production: push to DLQ, alarm, etc.)
        throw publisher_error("failed to publish after retries: " + std::string(ex.what()));
    }

    // ---------------------------------------------------------------------
    // Data members
    // ---------------------------------------------------------------------
    BrokerSendFunc                     _sendFunc;

    const std::string                  _brokerUri;
    const std::string                  _clientId;
    const std::size_t                  _maxQueueSize;

    std::atomic_bool                   _running { false };
    std::thread                        _worker;

    mutable std::mutex                 _queueMutex;
    std::condition_variable            _queueCv;      // producer -> consumer
    std::condition_variable            _flushedCv;    // consumer -> flush()

    std::queue<Task>                   _queue;
};

// -----------------------------------------------------------------------------
// Close namespaces
// -----------------------------------------------------------------------------
}   // namespace bus
}   // namespace infr
}   // namespace fl360
```