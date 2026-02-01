#include "EventBus.h"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cassert>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <queue>
#include <shared_mutex>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace mbs {    // MosaicBoard Studio
// ─────────────────────────────────────────────────────────────────────────────
// Utility
// ─────────────────────────────────────────────────────────────────────────────
namespace {
constexpr const char* kWildcardTopic = "*";  // Listeners that want everything
}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
// ListenerHandle ‑ implementation
// ─────────────────────────────────────────────────────────────────────────────
ListenerHandle::ListenerHandle() noexcept = default;

ListenerHandle::ListenerHandle(std::weak_ptr<EventBus> bus, ListenerId id) noexcept
    : _bus(std::move(bus)), _id(id) {}

ListenerHandle::ListenerHandle(ListenerHandle&& rhs) noexcept
    : _bus(std::move(rhs._bus)), _id(rhs._id) {
    rhs._id = 0;
}

ListenerHandle& ListenerHandle::operator=(ListenerHandle&& rhs) noexcept {
    if (this != &rhs) {
        unsubscribe();
        _bus = std::move(rhs._bus);
        _id  = rhs._id;
        rhs._id = 0;
    }
    return *this;
}

ListenerHandle::~ListenerHandle() {
    try {
        unsubscribe();
    } catch (...) {
        // never propagate from dtor
    }
}

void ListenerHandle::unsubscribe() {
    if (_id == 0) return;

    if (auto bus = _bus.lock()) {
        bus->unsubscribe(_id);
    }
    _id = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// EventBus ‑ ctor / dtor
// ─────────────────────────────────────────────────────────────────────────────
EventBus::EventBus(std::size_t workerCount)
    : _nextListenerId(1), _shutdown(false) {
    if (workerCount == 0) {
        workerCount = std::max<std::size_t>(1, std::thread::hardware_concurrency());
    }

    // Pre-allocate worker threads
    _workers.reserve(workerCount);
    for (std::size_t i = 0; i < workerCount; ++i) {
        _workers.emplace_back(&EventBus::workerLoop, this);
    }
}

EventBus::~EventBus() {
    shutdown();
}

std::shared_ptr<EventBus> EventBus::create(std::size_t workerCount) {
    return std::shared_ptr<EventBus>(new EventBus(workerCount));
}

// ─────────────────────────────────────────────────────────────────────────────
// Subscription API
// ─────────────────────────────────────────────────────────────────────────────
ListenerHandle EventBus::subscribe(std::string topic,
                                    EventCallback callback,
                                    ExecutionModel model) {
    if (!callback) {
        throw std::invalid_argument("EventBus::subscribe – callback cannot be empty");
    }

    if (topic.empty()) topic = kWildcardTopic;

    std::unique_lock lock(_listenerMutex);
    const ListenerId id = _nextListenerId++;

    ListenerInfo info;
    info.id        = id;
    info.topic     = std::move(topic);
    info.callback  = std::move(callback);
    info.execModel = model;

    _listeners.emplace(id, info);
    _topicToIds[info.topic].insert(id);

    return ListenerHandle(shared_from_this(), id);
}

void EventBus::unsubscribe(ListenerId id) {
    std::unique_lock lock(_listenerMutex);
    auto it = _listeners.find(id);
    if (it == _listeners.end()) return;

    auto topicIt = _topicToIds.find(it->second.topic);
    if (topicIt != _topicToIds.end()) {
        topicIt->second.erase(id);
        if (topicIt->second.empty()) _topicToIds.erase(topicIt);
    }

    _listeners.erase(it);
}

// ─────────────────────────────────────────────────────────────────────────────
// Publish
// ─────────────────────────────────────────────────────────────────────────────
void EventBus::publish(Event evt, PublishPolicy policy) {
    {
        std::shared_lock lock(_listenerMutex);

        // 1. synchronous listeners (always immediate)
        dispatchSyncUnlocked(evt);

        // 2. async listeners (if any)
        if (policy != PublishPolicy::SYNC_ONLY) {
            enqueueAsyncTasksUnlocked(evt);
        }
    }

    if (policy == PublishPolicy::FLUSH_AFTER_PUBLISH) {
        flush();
    }
}

void EventBus::dispatchSyncUnlocked(const Event& evt) const {
    iterateUnlocked(evt.topic, ExecutionModel::SYNC, [&](const ListenerInfo& l) {
        safeInvoke(l, evt);
    });
}

void EventBus::enqueueAsyncTasksUnlocked(const Event& evt) {
    iterateUnlocked(evt.topic, ExecutionModel::ASYNC, [&](const ListenerInfo& l) {
        {
            std::lock_guard ql(_queueMutex);
            _tasks.emplace([=] { safeInvoke(l, evt); });
        }
        _cv.notify_one();
    });
}

template <typename Fn>
void EventBus::iterateUnlocked(const std::string& topic,
                               ExecutionModel model,
                               const Fn& cb) const {
    auto callForSet = [&](const auto& set) {
        for (ListenerId id : set) {
            auto lit = _listeners.find(id);
            if (lit == _listeners.end()) continue;
            if (lit->second.execModel == model) cb(lit->second);
        }
    };

    if (auto it = _topicToIds.find(topic); it != _topicToIds.end()) {
        callForSet(it->second);
    }
    if (auto it = _topicToIds.find(kWildcardTopic); it != _topicToIds.end()) {
        callForSet(it->second);
    }
}

void EventBus::safeInvoke(const ListenerInfo& li, const Event& evt) const {
    try {
        li.callback(evt);
    } catch (const std::exception& ex) {
        spdlog::error("EventBus listener(id={},topic='{}') threw: {}", li.id, li.topic, ex.what());
    } catch (...) {
        spdlog::error("EventBus listener(id={},topic='{}') threw unknown exception", li.id,
                      li.topic);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Thread-pool internals
// ─────────────────────────────────────────────────────────────────────────────
void EventBus::workerLoop() {
    while (true) {
        std::function<void()> work;
        {
            std::unique_lock lock(_queueMutex);
            _cv.wait(lock, [&] { return _shutdown || !_tasks.empty(); });

            if (_shutdown && _tasks.empty()) return;

            work = std::move(_tasks.front());
            _tasks.pop();
        }
        try {
            work();
        } catch (const std::exception& ex) {
            spdlog::error("EventBus worker task exception: {}", ex.what());
        } catch (...) {
            spdlog::error("EventBus worker task unknown exception");
        }
    }
}

void EventBus::flush() {
    std::unique_lock lock(_queueMutex);
    _cv.wait(lock, [&] { return _tasks.empty(); });
}

void EventBus::shutdown() {
    bool expected = false;
    if (!_shutdown.compare_exchange_strong(expected, true)) return;  // already shutting down

    {
        std::lock_guard lock(_queueMutex);
    }

    _cv.notify_all();

    for (auto& w : _workers) {
        if (w.joinable()) w.join();
    }

    // clean remaining tasks
    std::queue<std::function<void()>> empty;
    {
        std::lock_guard lock(_queueMutex);
        _tasks.swap(empty);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Diagnostics
// ─────────────────────────────────────────────────────────────────────────────
std::size_t EventBus::pendingTasks() const {
    std::lock_guard lock(_queueMutex);
    return _tasks.size();
}

std::size_t EventBus::listenerCount() const {
    std::shared_lock lock(_listenerMutex);
    return _listeners.size();
}

}  // namespace mbs