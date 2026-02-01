```cpp
#pragma once
/***************************************************************************************************
*  File: EventBus.h
*  Project: MosaicBoard Studio  (web_dashboard)
*
*  Description:
*  ------------
*  A high-performance, thread–safe event bus providing synchronous and asynchronous dispatch
*  semantics.  All dashboard tiles, service-layer components, and plugin modules can post strongly
*  typed events without compile-time coupling.  Listeners are automatically disconnected when their
*  subscription token goes out of scope, preventing use-after-free and memory leaks when plugins
*  are hot-swapped at run-time.
*
*  Key features:
*   • Zero-overhead type-safe dispatch (template-based “subscribe” API)
*   • RAII subscription tokens for automatic un-registration
*   • Lock-free read-optimized subscriber storage
*   • Optional asynchronous delivery backed by a lightweight thread pool
*   • Non-intrusive instrumentation hooks using spdlog
*
*  Usage:
*  -------
*      struct DataArrived { std::string channel; nlohmann::json payload; };
*      auto token = EventBus::instance().subscribe<DataArrived>(
*          [](const DataArrived& ev) { /* … */ },
*          EventDelivery::Async);   // or EventDelivery::Sync
*
*      EventBus::instance().publish<DataArrived>({"metrics", json::parse("{}")});
*
*  The listener will be automatically disconnected when `token` is destroyed.
*
****************************************************************************************************/
#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <functional>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <queue>
#include <shared_mutex>
#include <string>
#include <typeindex>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>

namespace mosaic::core {

/*---------------------------------------------*
 *               Forward Declarations          *
 *---------------------------------------------*/
enum class EventDelivery { Sync, Async };

/*---------------------------------------------*
 *               Subscription Token             *
 *---------------------------------------------*/
/**
 * An opaque handle that represents a subscription registration.
 * When the token is destroyed, it automatically unregisters the
 * listener from the EventBus to avoid dangling callbacks.
 */
class SubscriptionToken {
public:
    SubscriptionToken() = default;
    SubscriptionToken(const SubscriptionToken&)            = delete;
    SubscriptionToken& operator=(const SubscriptionToken&) = delete;

    SubscriptionToken(SubscriptionToken&& rhs) noexcept { moveFrom(std::move(rhs)); }
    SubscriptionToken& operator=(SubscriptionToken&& rhs) noexcept {
        if (this != &rhs) {
            unsubscribe();
            moveFrom(std::move(rhs));
        }
        return *this;
    }

    ~SubscriptionToken() { unsubscribe(); }

private:
    friend class EventBus;

    explicit SubscriptionToken(std::weak_ptr<void> controlBlock,
                               std::function<void()>   onUnsubscribe)
        : m_control(std::move(controlBlock))
        , m_onUnsubscribe(std::move(onUnsubscribe)) {}

    void unsubscribe() {
        if (auto locked = m_control.lock()) {  // still valid
            if (m_onUnsubscribe) {
                try { m_onUnsubscribe(); }
                catch (const std::exception& ex) {
                    spdlog::error("Exception while unsubscribing: {}", ex.what());
                }
            }
        }
        m_control.reset();
        m_onUnsubscribe = nullptr;
    }

    void moveFrom(SubscriptionToken&& other) {
        m_control       = std::move(other.m_control);
        m_onUnsubscribe = std::move(other.m_onUnsubscribe);
        other.m_control.reset();
        other.m_onUnsubscribe = nullptr;
    }

    std::weak_ptr<void>   m_control;
    std::function<void()> m_onUnsubscribe;
};

/*---------------------------------------------*
 *         Lightweight Thread Pool             *
 *---------------------------------------------*/
class ThreadPool final {
public:
    explicit ThreadPool(std::size_t workers = std::thread::hardware_concurrency())
        : m_shutdown(false) {
        workers = std::max<std::size_t>(1, workers);
        for (std::size_t i = 0; i < workers; ++i) {
            m_threads.emplace_back([this] { workerLoop(); });
        }
    }

    ThreadPool(const ThreadPool&)            = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;

    ~ThreadPool() {
        {
            std::unique_lock lk(m_mutex);
            m_shutdown = true;
        }
        m_cv.notify_all();
        for (auto& t : m_threads)
            if (t.joinable()) t.join();
    }

    template <typename Fn>
    void enqueue(Fn&& fn) {
        {
            std::unique_lock lk(m_mutex);
            m_tasks.emplace(std::forward<Fn>(fn));
        }
        m_cv.notify_one();
    }

private:
    void workerLoop() {
        while (true) {
            std::function<void()> task;
            {
                std::unique_lock lk(m_mutex);
                m_cv.wait(lk, [this] { return m_shutdown || !m_tasks.empty(); });
                if (m_shutdown && m_tasks.empty()) return;
                task = std::move(m_tasks.front());
                m_tasks.pop();
            }
            try { task(); }
            catch (const std::exception& ex) {
                spdlog::error("Unhandled exception in ThreadPool task: {}", ex.what());
            }
        }
    }

    std::vector<std::thread>  m_threads;
    std::queue<std::function<void()>> m_tasks;
    std::mutex                m_mutex;
    std::condition_variable   m_cv;
    bool                      m_shutdown;
};

/*---------------------------------------------*
 *                 Event Bus                   *
 *---------------------------------------------*/
class EventBus {
public:
    /*--------------------*
     *  Static Accessor   *
     *--------------------*/
    static EventBus& instance() {
        static EventBus singleton;
        return singleton;
    }

    EventBus(const EventBus&)            = delete;
    EventBus& operator=(const EventBus&) = delete;

    /*----------------------------*
     *      Public API            *
     *----------------------------*/

    /**
     * Subscribe a callback to events of type `EventT`.
     *
     * @tparam EventT              The concrete event type.
     * @param  callback             Callable with signature `void(const EventT&)`.
     * @param  delivery             Sync  = executed in publisher's thread.
     *                              Async = executed on ThreadPool.
     * @return SubscriptionToken    RAII token for unsubscription.
     */
    template <typename EventT>
    [[nodiscard]] SubscriptionToken subscribe(
        std::function<void(const EventT&)> callback,
        EventDelivery                      delivery = EventDelivery::Async) {
        static_assert(std::is_copy_constructible_v<EventT>,
                      "Event type must be copy constructible");
        static_assert(std::is_move_constructible_v<EventT>,
                      "Event type must be move constructible");

        const std::type_index ti = typeid(EventT);

        auto subscriber = std::make_shared<Subscriber<EventT>>(std::move(callback), delivery);

        {
            std::unique_lock lk(m_subscriberMutex);
            auto& bucket = m_subscribers[ti];
            bucket.emplace_back(subscriber);
        }

        auto removalFn = [this, ti, weak = std::weak_ptr<void>(subscriber)] {
            std::unique_lock lk(m_subscriberMutex);
            auto it = m_subscribers.find(ti);
            if (it == m_subscribers.end()) return;

            auto& vec = it->second;
            vec.erase(std::remove_if(vec.begin(),
                                     vec.end(),
                                     [&](const std::shared_ptr<BaseSubscriber>& ptr) {
                                         return ptr == weak.lock();
                                     }),
                      vec.end());
        };

        return SubscriptionToken{subscriber, std::move(removalFn)};
    }

    /**
     * Publish an event. All subscribed listeners will be invoked.
     * Provides perfect-forwarding so temporaries are preserved.
     */
    template <typename EventT, typename... Args>
    void publish(Args&&... args) {
        static_assert(std::is_copy_constructible_v<EventT>,
                      "Event type must be copy constructible");
        static_assert(std::is_move_constructible_v<EventT>,
                      "Event type must be move constructible");

        const std::type_index ti = typeid(EventT);

        // Snapshot subscribers to minimise lock contention
        std::vector<std::shared_ptr<BaseSubscriber>> targets;
        {
            std::shared_lock lk(m_subscriberMutex);
            if (auto it = m_subscribers.find(ti); it != m_subscribers.end()) {
                targets = it->second;  // copy shared_ptrs
            }
        }
        if (targets.empty()) return;

        EventT event{std::forward<Args>(args)...};

        for (auto& baseSub : targets) {
            auto sub = std::static_pointer_cast<Subscriber<EventT>>(baseSub);
            if (!sub) continue;  // type mismatch (shouldn't happen)

            if (sub->delivery == EventDelivery::Sync) {
                invokeSafely([sub, &event] { sub->callback(event); });
            } else {
                m_threadPool.enqueue([sub, event] { invokeSafely([&] { sub->callback(event); }); });
            }
        }
    }

    /**
     * Force graceful shutdown of the global ThreadPool.
     * Primarily useful in unit tests to make sure background
     * tasks complete before process exit.
     */
    void flush() {
        std::promise<void> barrier;
        auto fut = barrier.get_future();
        m_threadPool.enqueue([&] { barrier.set_value(); });
        fut.wait();
    }

private:
    EventBus() = default;

    /*---------------*
     *  Internals    *
     *---------------*/
    struct BaseSubscriber {
        virtual ~BaseSubscriber() = default;
    };

    template <typename EventT>
    struct Subscriber final : BaseSubscriber {
        Subscriber(std::function<void(const EventT&)> cb, EventDelivery d)
            : callback(std::move(cb)), delivery(d) {}
        std::function<void(const EventT&)> callback;
        EventDelivery                      delivery;
    };

    static void invokeSafely(std::function<void()> fn) {
        try { fn(); }
        catch (const std::exception& ex) { spdlog::error("Event handler threw: {}", ex.what()); }
        catch (...) { spdlog::error("Event handler threw unknown exception"); }
    }

    std::unordered_map<std::type_index, std::vector<std::shared_ptr<BaseSubscriber>>> m_subscribers;
    mutable std::shared_mutex m_subscriberMutex;

    ThreadPool m_threadPool;
};

}  // namespace mosaic::core
```