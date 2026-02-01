```cpp
#pragma once
/**************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  Module : Infrastructure :: Event-Bus
 *  File   : event_consumer.h
 *
 *  Overview
 *  --------
 *  Defines a generic, strongly-typed, thread-safe EventConsumer that can be wired to any concrete
 *  message-bus implementation (Kafka, RabbitMQ, NATS, etc.).  The consumer provides:
 *
 *      •  Metadata-rich envelopes for domain events
 *      •  Compile-time safe subscription APIs with RAII unsubscription handles
 *      •  Runtime dispatch of JSON-encoded events to user-supplied callbacks
 *      •  Graceful start/stop and back-pressure friendly ingestion
 *
 *  The actual transport is delegated to an `IBusConnection` that delivers raw JSON payloads to the
 *  consumer via `pushRawMessage()`.  This decouples the infrastructure plumbing from domain logic
 *  and facilitates unit-testing of business workflows without a running broker.
 *
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>

#include <nlohmann/json.hpp>      // https://github.com/nlohmann/json

// Forward declaration of the broker connection.  A concrete implementation is expected to call
// EventConsumer::pushRawMessage(...) whenever a message arrives from the external bus.
namespace fortiledger::infrastructure::event_bus
{
    class IBusConnection;
}

namespace fortiledger::infrastructure::event_bus
{

// =----------------------------------------------------------------------
//  Helper utilities
// =----------------------------------------------------------------------

namespace detail
{
    // Non-copyable / non-movable mix-in
    struct NonCopyable
    {
        NonCopyable()  = default;
        ~NonCopyable() = default;
        NonCopyable(const NonCopyable&)            = delete;
        NonCopyable& operator=(const NonCopyable&) = delete;
        NonCopyable(NonCopyable&&)                 = delete;
        NonCopyable& operator=(NonCopyable&&)      = delete;
    };
} // namespace detail

// =----------------------------------------------------------------------
//  Event Envelopes
// =----------------------------------------------------------------------

/*
 *  EventMetadata
 *  -------------
 *  Carries cross-cutting concerns such as correlation and causation IDs used for distributed
 *  tracing.  Timestamps use std::chrono::system_clock to avoid time-zone headaches.
 */
struct EventMetadata
{
    std::string  eventId;         // Globally unique ID (UUID-v4)
    std::string  correlationId;   // Correlates commands / events across services
    std::string  causationId;     // ID of the parent event that triggered this one
    std::string  eventType;       // Fully-qualified C++ type-name or semantic alias
    std::uint32_t schemaVersion{1};
    std::chrono::system_clock::time_point occurredOn{std::chrono::system_clock::now()};
};

/*
 *  EventEnvelope<T>
 *  ----------------
 *  Wraps a concrete domain event with its metadata.  The template parameter must be
 *  serialisable/deserialisable by nlohmann::json (i.e., `to_json/from_json` overloads present).
 */
template <typename T>
struct EventEnvelope
{
    EventMetadata metadata;
    T             payload;
};

// =----------------------------------------------------------------------
//  SubscriptionHandle
// =----------------------------------------------------------------------

/*
 *  An opaque RAII object returned to callers when they `subscribe<T>()`.  Destroying
 *  the handle automatically removes the callback from the consumer.
 */
class SubscriptionHandle : private detail::NonCopyable
{
public:
    SubscriptionHandle() noexcept = default;

    SubscriptionHandle(SubscriptionHandle&& other) noexcept
        : _deleter(std::move(other._deleter))
    {
        other._deleter = nullptr;
    }

    SubscriptionHandle& operator=(SubscriptionHandle&& other) noexcept
    {
        if (this != &other)
        {
            reset();
            _deleter       = std::move(other._deleter);
            other._deleter = nullptr;
        }
        return *this;
    }

    ~SubscriptionHandle() { reset(); }

    void reset()
    {
        if (_deleter) { _deleter(); }
        _deleter = nullptr;
    }

private:
    explicit SubscriptionHandle(std::function<void()> deleter)
        : _deleter(std::move(deleter))
    {}

    std::function<void()> _deleter;

    template <typename>
    friend class EventConsumer;
};

// =----------------------------------------------------------------------
//  EventConsumer
// =----------------------------------------------------------------------

/*
 *  EventConsumer
 *  -------------
 *  Thread-safe, type-safe consumer that dispatches messages to user callbacks.
 */
class EventConsumer : public std::enable_shared_from_this<EventConsumer>, private detail::NonCopyable
{
public:
    explicit EventConsumer(std::shared_ptr<IBusConnection> connection);
    ~EventConsumer() noexcept;

    // Starts background processing.  Idempotent.
    void start();

    // Stops processing and waits until in-flight handlers finish.
    void stop();

    [[nodiscard]] bool isRunning() const noexcept { return _running.load(std::memory_order_acquire); }

    /*
     *  subscribe<T>()
     *  --------------
     *  Registers a callback for a concrete event type.  The caller owns the returned
     *  SubscriptionHandle; destroying it will automatically unsubscribe.
     *
     *  Example:
     *      auto handle = consumer->subscribe<ClusterBackupCompletedEvent>(
     *          [](const EventEnvelope<ClusterBackupCompletedEvent>& env) {
     *              // business logic
     *          });
     */
    template <typename TEvent>
    SubscriptionHandle subscribe(std::function<void(const EventEnvelope<TEvent>&)> handler);

    /*
     *  For testing / adapter layers.  Called by the IBusConnection whenever a new
     *  raw JSON message is read from the underlying broker.
     */
    void pushRawMessage(std::string_view raw);

private:
    // –– Internal types ––––––––––––––––––––––––––––––––––––––––––––––––––––

    struct IDispatcher
    {
        virtual ~IDispatcher()                          = default;
        virtual void dispatch(const nlohmann::json& j)  = 0;
    };

    template <typename TEvent>
    struct Dispatcher final : IDispatcher
    {
        explicit Dispatcher(std::function<void(const EventEnvelope<TEvent>&)> cb)
            : callback(std::move(cb))
        {}

        void dispatch(const nlohmann::json& j) override
        {
            try
            {
                EventEnvelope<TEvent> env;
                env.metadata.eventId       = j.at("metadata").at("eventId").get<std::string>();
                env.metadata.correlationId = j.at("metadata").at("correlationId").get<std::string>();
                env.metadata.causationId   = j.at("metadata").at("causationId").get<std::string>();
                env.metadata.eventType     = j.at("metadata").at("eventType").get<std::string>();
                env.metadata.schemaVersion = j.at("metadata").at("schemaVersion").get<std::uint32_t>();
                env.metadata.occurredOn    = std::chrono::system_clock::from_time_t(
                    j.at("metadata").at("occurredOnEpoch").get<std::time_t>());

                env.payload = j.at("payload").template get<TEvent>();

                callback(env);
            }
            catch (const std::exception& ex)
            {
                // Log and swallow to avoid crashing the consumer.  The actual
                // logging mechanism is deliberately not chosen here to avoid
                // leaking dependencies into the header.  Replace with your
                // favourite logger (spdlog, log4cxx, etc.) in the .cpp file.
                // e.g., LOG_ERROR("Failed to dispatch event: {}", ex.what());
            }
        }

        std::function<void(const EventEnvelope<TEvent>&)> callback;
    };

    // –– Private helpers –––––––––––––––––––––––––––––––––––––––––––––––––––

    template <typename TEvent>
    static std::string_view getEventKey() noexcept
    {
#if defined(__clang__) || defined(__GNUC__)
        return __PRETTY_FUNCTION__; // Yields human-readable type name
#else
        return typeid(TEvent).name();
#endif
    }

    void registerDispatcher(std::string_view key, std::shared_ptr<IDispatcher> dispatcher);
    void unregisterDispatcher(std::string_view key);

    // –– Data members ––––––––––––––––––––––––––––––––––––––––––––––––––––––

    std::shared_ptr<IBusConnection> _connection;

    mutable std::mutex                                      _mutex;
    std::unordered_map<std::string, std::shared_ptr<IDispatcher>> _dispatchers;

    std::atomic<bool> _running{false};
};

// =---------------- Inline / Template Implementation ‑---------------------

template <typename TEvent>
SubscriptionHandle EventConsumer::subscribe(std::function<void(const EventEnvelope<TEvent>&)> handler)
{
    static_assert(std::is_default_constructible_v<TEvent>,
                  "Subscribed event types must be default-constructible.");

    const std::string key{getEventKey<TEvent>()};

    auto dispatcher = std::make_shared<Dispatcher<TEvent>>(std::move(handler));

    {
        std::lock_guard lk{_mutex};
        if (_dispatchers.contains(key))
        {
            throw std::logic_error("Attempted to register duplicate subscription for event type: " + key);
        }
        _dispatchers.emplace(key, dispatcher);
    }

    // The deleter captures a weak_ptr to avoid prolonging the lifetime of EventConsumer.
    std::weak_ptr<EventConsumer> selfWeak = shared_from_this();
    SubscriptionHandle handle{[selfWeak, key] {
        if (auto self = selfWeak.lock())
        {
            self->unregisterDispatcher(key);
        }
    }};

    return handle;
}

inline EventConsumer::EventConsumer(std::shared_ptr<IBusConnection> connection)
    : _connection(std::move(connection))
{
    if (!_connection)
    {
        throw std::invalid_argument("IBusConnection must not be null");
    }
}

inline EventConsumer::~EventConsumer() noexcept
{
    try
    {
        stop();
    }
    catch (...)
    {
        // Swallow exceptions in destructor
    }
}

inline void EventConsumer::start()
{
    bool expected = false;
    if (_running.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
    {
        // Hook to the connection.  Each implementation of IBusConnection must offer a mechanism
        // to supply a callback executed on the calling thread or on its own IO context.
        // Example pseudo-code:
        //
        //     _connection->setMessageCallback([self = shared_from_this()](auto&& raw) {
        //         self->pushRawMessage(raw);
        //     });
        //
        // Not implemented here; left to concrete adapter.
    }
}

inline void EventConsumer::stop()
{
    bool expected = true;
    if (_running.compare_exchange_strong(expected, false, std::memory_order_acq_rel))
    {
        // Unhook from the connection if needed.
        // _connection->clearMessageCallback();
        std::lock_guard lk{_mutex};
        _dispatchers.clear();
    }
}

inline void EventConsumer::pushRawMessage(std::string_view raw)
{
    if (!_running.load(std::memory_order_acquire)) { return; }

    nlohmann::json j;
    try
    {
        j = nlohmann::json::parse(raw);
    }
    catch (const std::exception& ex)
    {
        // TODO: replace with structured logging
        return; // Drop malformed messages
    }

    const std::string key = j.at("metadata").at("eventType").get<std::string>();

    std::shared_ptr<IDispatcher> dispatcher;
    {
        std::lock_guard lk{_mutex};
        auto it = _dispatchers.find(key);
        if (it != _dispatchers.end())
        {
            dispatcher = it->second;
        }
    }

    if (dispatcher) { dispatcher->dispatch(j); }
}

inline void EventConsumer::registerDispatcher(std::string_view key,
                                              std::shared_ptr<IDispatcher> dispatcher)
{
    std::lock_guard lk{_mutex};
    _dispatchers.emplace(key, std::move(dispatcher));
}

inline void EventConsumer::unregisterDispatcher(std::string_view key)
{
    std::lock_guard lk{_mutex};
    _dispatchers.erase(std::string{key});
}

} // namespace fortiledger::infrastructure::event_bus
```