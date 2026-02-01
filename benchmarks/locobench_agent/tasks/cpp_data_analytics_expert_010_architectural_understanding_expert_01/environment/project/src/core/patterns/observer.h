#pragma once
/**
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * Observer Pattern Infrastructure
 *
 * File path : cardio_insight_360/src/core/patterns/observer.h
 *
 * This header provides a lightweight but production-ready, thread-safe
 * implementation of the Observer pattern that is used throughout the
 * CardioInsight360 code-base to publish real-time events (e.g. streaming
 * metrics, ETL life-cycle hooks, validation results) to interested
 * subsystems such as the monitoring layer or the visualization module.
 *
 * Design goals
 * ------------
 * 1. Zero-or-low dependency: header-only, relies only on the C++17 stdlib
 *    with an optional integration hook for spdlog.
 * 2. Thread-safety: subscription management and dispatch are guarded by
 *    reader/writer locks (std::shared_mutex) to enable high-volume reads
 *    while minimizing write contention.
 * 3. Lifetime-safety: observers are stored as std::weak_ptr to avoid
 *    cyclic references; expired observers are purged automatically.
 * 4. RAII subscriptions: callers can hold a `Subscription` handle; when
 *    destroyed the observer is automatically un-registered.
 * 5. Performance: dispatch is non-blocking for publishers.  Callbacks are
 *    executed in the caller’s thread to keep latency low; if the receiver
 *    needs asynchronous handling it can delegate internally.
 *
 * Example
 * -------
 *   using namespace ci360::core::patterns;
 *
 *   struct MyObserver : public Observer {
 *       void on_notify(const Event& e) override {
 *           std::cout << "Received event: " << e.description << '\n';
 *       }
 *   };
 *
 *   auto subject   = std::make_shared<Observable>();
 *   auto observer  = std::make_shared<MyObserver>();
 *   auto token     = subject->subscribe(observer); // RAII
 *
 *   subject->notify(Event::make(EventType::DataIngested, "ECG batch 42"));
 *
 *   // token goes out of scope -> observer is unsubscribed
 */

#include <any>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <utility>
#include <vector>

// Optional logging (compile-time flag);
#if defined(CI360_ENABLE_OBSERVER_LOGGING)
    #include <spdlog/spdlog.h>
    #define CI360_LOG(...) spdlog::debug(__VA_ARGS__)
#else
    #define CI360_LOG(...) (void)0
#endif

namespace ci360::core::patterns {

/* ---------- Domain-level event object ----------------------------------- */

enum class EventType : std::uint16_t
{
    kUnknown = 0,
    kHeartbeat,
    kDataIngested,
    kDataValidated,
    kTransformationCompleted,
    kStorageFailure,
    kStreamError
};

struct Event
{
    EventType                               type        { EventType::kUnknown };
    std::chrono::system_clock::time_point   timestamp   { std::chrono::system_clock::now() };
    std::string                             description {};
    std::any                                payload     {};

    template <typename T>
    [[nodiscard]] bool payload_is() const noexcept
    {
        return payload.type() == typeid(T);
    }

    template <typename T>
    [[nodiscard]] const T& get_payload() const
    {
        return std::any_cast<const T&>(payload);
    }

    static Event make(EventType t,
                      std::string descr,
                      std::any     pld = {})
    {
        return Event{t, std::chrono::system_clock::now(), std::move(descr), std::move(pld)};
    }
};

/* ---------- Observer interface ------------------------------------------ */

class Observer
{
public:
    Observer() = default;
    virtual ~Observer() = default;
    Observer(const Observer&)            = delete;
    Observer& operator=(const Observer&) = delete;
    Observer(Observer&&)                 = delete;
    Observer& operator=(Observer&&)      = delete;

    virtual void on_notify(const Event& event) = 0;
};

/* ---------- Observable (Subject) ---------------------------------------- */

class Observable : public std::enable_shared_from_this<Observable>
{
public:
    Observable()  = default;
    ~Observable() = default;

    Observable(const Observable&)            = delete;
    Observable& operator=(const Observable&) = delete;
    Observable(Observable&&)                 = delete;
    Observable& operator=(Observable&&)      = delete;

    /* ----- RAII subscription token ------------------------------------- */
    class Subscription
    {
    public:
        Subscription() = default;
        explicit Subscription(std::weak_ptr<Observable> subj,
                              std::shared_ptr<Observer> obs) noexcept
            : subject_(std::move(subj))
            , observer_(std::move(obs))
        {}

        Subscription(const Subscription&)            = delete;
        Subscription& operator=(const Subscription&) = delete;

        Subscription(Subscription&& other) noexcept
            : subject_(std::move(other.subject_))
            , observer_(std::move(other.observer_))
        {
            other.observer_.reset();
        }

        Subscription& operator=(Subscription&& other) noexcept
        {
            if (this != &other) {
                unsubscribe();
                subject_  = std::move(other.subject_);
                observer_ = std::move(other.observer_);
                other.observer_.reset();
            }
            return *this;
        }

        ~Subscription() { unsubscribe(); }

        void unsubscribe() noexcept
        {
            if (observer_.expired())
                return;

            if (auto subj = subject_.lock()) {
                subj->unsubscribe(observer_);
            }
            observer_.reset();
        }

        [[nodiscard]] bool active() const noexcept { return !observer_.expired(); }

    private:
        std::weak_ptr<Observable> subject_;
        std::weak_ptr<Observer>   observer_;
    };

    /* ----- Public API --------------------------------------------------- */

    Subscription subscribe(const std::shared_ptr<Observer>& observer)
    {
        {
            std::unique_lock lock(mutex_);
            observers_.emplace_back(observer);
            CI360_LOG("Observer subscribed (count = {})", observers_.size());
        }
        return Subscription{this->weak_from_this(), observer};
    }

    void unsubscribe(const std::weak_ptr<Observer>& observer) noexcept
    {
        std::unique_lock lock(mutex_);
        const auto before = observers_.size();
        observers_.erase(std::remove_if(observers_.begin(),
                                        observers_.end(),
                                        [&](const std::weak_ptr<Observer>& ptr) {
                                            return ptr.lock() == observer.lock();
                                        }),
                         observers_.end());
        CI360_LOG("Observer unsubscribed (before = {}, after = {})",
                  before,
                  observers_.size());
    }

    void notify(const Event& event)
    {
        // Copy live observers under shared lock for minimal blocking.
        std::vector<std::shared_ptr<Observer>> alive;
        {
            std::shared_lock lock(mutex_);
            alive.reserve(observers_.size());
            for (const auto& weak : observers_) {
                if (auto obs = weak.lock(); obs) {
                    alive.emplace_back(std::move(obs));
                }
            }
        }

        // Dispatch outside lock to avoid deadlocks/re-entrancy.
        for (const auto& obs : alive) {
            try {
                obs->on_notify(event);
            } catch (const std::exception& ex) {
                CI360_LOG("Observer threw: {}", ex.what());
            } catch (...) {
                CI360_LOG("Observer threw unknown exception.");
            }
        }

        cleanup_expired();
    }

    [[nodiscard]] std::size_t observer_count() const noexcept
    {
        std::shared_lock lock(mutex_);
        return observers_.size();
    }

private:
    void cleanup_expired()
    {
        std::unique_lock lock(mutex_);
        const auto before = observers_.size();
        observers_.erase(std::remove_if(observers_.begin(),
                                        observers_.end(),
                                        [](const std::weak_ptr<Observer>& ptr) {
                                            return ptr.expired();
                                        }),
                         observers_.end());
        if (before != observers_.size())
            CI360_LOG("Cleaned up {} expired observers.", before - observers_.size());
    }

    mutable std::shared_mutex              mutex_;
    std::vector<std::weak_ptr<Observer>>   observers_;
};

} // namespace ci360::core::patterns