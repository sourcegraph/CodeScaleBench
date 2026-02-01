#include "event_publisher.hpp"

#include <condition_variable>
#include <chrono>
#include <deque>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp> // Single-header JSON (https://github.com/nlohmann/json)

/*
 *  FortiLedger360 – Enterprise Security Suite
 *  -------------------------------------------------
 *  Infrastructure Layer – Event Bus
 *
 *  event_publisher.cpp
 *
 *  A high-level, thread-safe façade that encapsulates publishing DomainEvents
 *  to the shared, multi-tenant event bus.  Responsibilities:
 *      • payload serialization (default: JSON via nlohmann::json)
 *      • automatic retry with exponential back-off
 *      • futures-based asynchronous API
 *      • graceful shutdown (drains queue before destructing)
 *
 *  NOTE:
 *      ‑ An abstract IEventBus is expected to be provided by the platform team
 *        (backed by NATS, Kafka, RabbitMQ, etc.).  The publisher is agnostic
 *        to the actual transport.
 *
 *      ‑ This single compilation unit purposefully includes *minimal* stub
 *        interfaces so that the file compiles in isolation while still
 *        respecting the open/closed principle for production builds.
 */

namespace fl360::infra::eventbus
{

/* ----------  Light-weight stubbed dependencies  ----------------------------------------- */

class IEventBus
{
public:
    virtual ~IEventBus() = default;

    /*
     *  Publish a raw byte-payload to the bus.
     *
     *  @param routingKey   logical topic / subject (e.g. "scan.initiated")
     *  @param payload      raw, serialized bytes
     *  @param timeout      operation timeout – implementations MAY ignore
     */
    virtual void send(const std::string& routingKey,
                      const std::string& payload,
                      std::chrono::milliseconds timeout) = 0;
};

class ILogger
{
public:
    virtual ~ILogger() = default;

    virtual void info (const std::string& msg) = 0;
    virtual void warn (const std::string& msg) = 0;
    virtual void error(const std::string& msg) = 0;
};

/* ----------  Concrete, header-only JSON serializer  ------------------------------------ */

struct JsonSerializer
{
    template <typename T>
    std::string serialize(const T& obj) const
    {
        nlohmann::json j = obj;             // relies on ADL / to_json defined for T
        return j.dump();
    }
};

/* ----------  EventPublisher implementation  -------------------------------------------- */

class EventPublisher::Impl
{
public:
    explicit Impl(std::shared_ptr<IEventBus> bus,
                  std::shared_ptr<ILogger>   logger,
                  std::size_t                maxRetry,
                  std::chrono::milliseconds  defaultTimeout);

    ~Impl();

    template <typename TEvent>
    std::future<void> publishAsync(const std::string& routingKey,
                                   const TEvent&     evt);

    void flush();

private:
    struct Task final
    {
        std::string                      routingKey;
        std::string                      payload;
        std::chrono::milliseconds        timeout;
        std::shared_ptr<std::promise<void>> promise;
        std::size_t                      attempt {0};
    };

    void workerLoop();
    bool send(const Task& t);
    void backoff(std::size_t attempt) const;

private:
    std::shared_ptr<IEventBus> bus_;
    std::shared_ptr<ILogger>   logger_;
    JsonSerializer             serializer_;

    const std::size_t          maxRetry_;
    const std::chrono::milliseconds defaultTimeout_;

    std::deque<Task>           queue_;
    std::mutex                 queueMtx_;
    std::condition_variable    queueCv_;

    std::atomic<bool>          running_ {true};
    std::thread                worker_;
};

EventPublisher::Impl::Impl(std::shared_ptr<IEventBus> bus,
                           std::shared_ptr<ILogger>   logger,
                           std::size_t                maxRetry,
                           std::chrono::milliseconds  defaultTimeout)
    : bus_(std::move(bus))
    , logger_(std::move(logger))
    , maxRetry_(maxRetry)
    , defaultTimeout_(defaultTimeout)
    , worker_(&Impl::workerLoop, this)
{
    if (!bus_)
        throw std::invalid_argument("EventPublisher requires a non-null IEventBus");
    if (!logger_)
        throw std::invalid_argument("EventPublisher requires a non-null ILogger");
}

EventPublisher::Impl::~Impl()
{
    try
    {
        flush();
        running_ = false;
        queueCv_.notify_all();
        if (worker_.joinable())
            worker_.join();
    }
    catch (...)
    {
        // Destructor must not throw – log & swallow
        // (logger_ might be already destroyed)
    }
}

template <typename TEvent>
std::future<void>
EventPublisher::Impl::publishAsync(const std::string& routingKey,
                                   const TEvent&     evt)
{
    if (!running_)
        throw std::runtime_error("EventPublisher is shutting down");

    Task task;
    task.routingKey = routingKey;
    task.payload    = serializer_.serialize(evt);
    task.timeout    = defaultTimeout_;
    task.promise    = std::make_shared<std::promise<void>>();

    {
        std::lock_guard<std::mutex> lg(queueMtx_);
        queue_.emplace_back(std::move(task));
    }
    queueCv_.notify_one();

    return task.promise->get_future();
}

void EventPublisher::Impl::flush()
{
    std::unique_lock<std::mutex> ul(queueMtx_);
    queueCv_.wait(ul, [this] { return queue_.empty(); });
}

void EventPublisher::Impl::workerLoop()
{
    while (running_)
    {
        Task task;
        {
            std::unique_lock<std::mutex> ul(queueMtx_);
            queueCv_.wait(ul, [this] { return !queue_.empty() || !running_; });

            if (!running_ && queue_.empty())
                break;

            task = std::move(queue_.front());
            queue_.pop_front();
        }

        if (!send(task))
        {
            if (task.attempt < maxRetry_)
            {
                ++task.attempt;
                backoff(task.attempt);

                std::lock_guard<std::mutex> lg(queueMtx_);
                queue_.push_back(std::move(task)); // push to tail (FIFO)
                queueCv_.notify_one();
            }
            else
            {
                std::string err =
                    "Failed to publish after " + std::to_string(maxRetry_) +
                    " attempts. Dropping message for route '" + task.routingKey + "'";
                logger_->error(err);

                task.promise->set_exception(
                    std::make_exception_ptr(std::runtime_error(err)));
            }
        }
        else
        {
            task.promise->set_value();
        }
    }
}

bool EventPublisher::Impl::send(const Task& t)
{
    try
    {
        bus_->send(t.routingKey, t.payload, t.timeout);
        return true;
    }
    catch (const std::exception& ex)
    {
        std::ostringstream oss;
        oss << "Publish attempt " << (t.attempt + 1)
            << " to '" << t.routingKey
            << "' failed: " << ex.what();
        logger_->warn(oss.str());
        return false;
    }
    catch (...)
    {
        logger_->warn("Publish attempt failed: <unknown exception>");
        return false;
    }
}

void EventPublisher::Impl::backoff(std::size_t attempt) const
{
    // Simple exponential back-off with jitter
    using namespace std::chrono_literals;
    const auto base     = 50ms;
    const auto cap      = 2s;
    auto delay          = base * (1ULL << attempt);
    if (delay > cap) delay = cap;

    std::this_thread::sleep_for(delay);
}

/* ----------  EventPublisher public façade  --------------------------------------------- */

EventPublisher::EventPublisher(std::shared_ptr<IEventBus> bus,
                               std::shared_ptr<ILogger>   logger,
                               std::size_t                maxRetry,
                               std::chrono::milliseconds  defaultTimeout)
    : impl_(std::make_unique<Impl>(std::move(bus),
                                   std::move(logger),
                                   maxRetry,
                                   defaultTimeout))
{ }

EventPublisher::~EventPublisher() = default;

void EventPublisher::flush()
{
    impl_->flush();
}

template <typename TEvent>
std::future<void> EventPublisher::publishAsync(const std::string& routingKey,
                                               const TEvent&     event)
{
    return impl_->publishAsync(routingKey, event);
}

/*
 *  Explicit instantiations – you can append additional common event-types
 *  here to avoid template bloat in translation units that only include the
 *  header.  For now we leave it header-only, but keep the mechanism
 *  documented for scalability.
 */

} // namespace fl360::infra::eventbus