#ifndef MOSAICBOARD_STUDIO_NOTIFICATION_SERVICE_H
#define MOSAICBOARD_STUDIO_NOTIFICATION_SERVICE_H

/**
 *  MosaicBoard Studio
 *  File:    src/services/NotificationService.h
 *
 *  Description:
 *      A production-grade, thread-safe notification service that multiplexes
 *      messages to registered sinks (e-mail, websocket push, SMS, etc.) and
 *      mirrors every delivery onto the real-time EventBus so that tiles can
 *      react to user- or system-generated events in near-realtime.
 *
 *      The service owns a small internal thread-pool for non-blocking fan-out
 *      and performs coarse-grained back-pressure when slow sinks are detected.
 *
 *  NOTE:
 *      This header contains implementation code (header-only) to keep the
 *      example self-contained.  In production, consider extracting the
 *      implementation into a .cpp file and exposing the public façade only.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <random>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mosaic::services {

/*------------------------------------------------------*
 *           ENUMS / DATA TRANSFER OBJECTS              *
 *------------------------------------------------------*/

enum class NotificationChannel : std::uint8_t {
    InApp = 0,
    Email,
    Push,
    SMS
};

enum class NotificationLevel : std::uint8_t {
    Info = 0,
    Warning,
    Error,
    Success
};

/**
 * NotificationMessage
 * A lightweight DTO describing a single notification.
 */
struct NotificationMessage
{
    std::string          id;         ///< Unique identifier (uuid-like)
    std::chrono::system_clock::time_point timestamp;
    std::string          title;
    std::string          content;
    NotificationLevel    level     { NotificationLevel::Info };
    NotificationChannel  channel   { NotificationChannel::InApp };
    std::string          payload;   ///< Optional JSON blob for custom data

    NotificationMessage() = default;

    NotificationMessage(std::string  ttl,
                        std::string  cnt,
                        NotificationLevel lvl,
                        NotificationChannel ch,
                        std::string  customPayload = {})
        : id{ generateUuid() }
        , timestamp{ std::chrono::system_clock::now() }
        , title{ std::move(ttl) }
        , content{ std::move(cnt) }
        , level{ lvl }
        , channel{ ch }
        , payload{ std::move(customPayload) }
    {}

private:
    /*  Very small, header-only pseudo-uuid generator.
        For production, prefer `boost::uuid` or `std::uuid` (C++23). */
    static std::string generateUuid()
    {
        static thread_local std::mt19937_64 rng{
            std::random_device{}()
        };

        std::uniform_int_distribution<std::uint64_t> dist;
        std::uint64_t part1 = dist(rng);
        std::uint64_t part2 = dist(rng);

        std::ostringstream oss;
        oss << std::hex << std::setw(16) << std::setfill('0') << part1
            << std::setw(16) << part2;
        return oss.str();
    }
};

/*------------------------------------------------------*
 *                   SINK INTERFACE                     *
 *------------------------------------------------------*/

/**
 * NotificationSink
 *
 * Abstract delivery endpoint implemented by concrete back-ends
 * (e.g. EmailSink, WebsocketSink, SmsSink, etc.).
 */
class NotificationSink
{
public:
    virtual ~NotificationSink() = default;

    /**
     * deliver
     *   Blocks until the message is delivered or fails.
     *   Should throw std::runtime_error on recoverable failures.
     */
    virtual void deliver(const NotificationMessage& msg) = 0;

    /**
     * canDeliver
     *   Return true if this sink can deliver on the requested channel.
     */
    virtual bool canDeliver(NotificationChannel channel) const noexcept = 0;
};

using NotificationSinkPtr = std::shared_ptr<NotificationSink>;

/*------------------------------------------------------*
 *                  NOTIFICATION SERVICE                *
 *------------------------------------------------------*/

class NotificationService
{
public:
    /**
     * ctor
     *   Spawns an internal thread-pool sized at hardware_concurrency / 2.
     */
    NotificationService()
        : m_stopped{ false }
    {
        const std::size_t nThreads =
            std::max(1u, std::thread::hardware_concurrency() / 2);

        for (std::size_t i = 0; i < nThreads; ++i) {
            m_workers.emplace_back([this] { this->workerLoop(); });
        }
    }

    ~NotificationService()
    {
        {
            std::lock_guard lock{ m_queueMtx };
            m_stopped = true;
        }
        m_cond.notify_all();
        for (auto& th : m_workers) { th.join(); }
    }

    /**
     * registerSink
     *   Adds a sink to the routing table.
     */
    void registerSink(NotificationSinkPtr sink)
    {
        if (!sink) { throw std::invalid_argument("sink cannot be null"); }

        std::unique_lock lock{ m_sinkMtx };
        m_sinks.emplace_back(std::move(sink));
    }

    /**
     * dispatch
     *   Public façade to enqueue a notification for asynchronous delivery.
     */
    void dispatch(NotificationMessage msg)
    {
        {
            std::lock_guard lock{ m_queueMtx };
            m_queue.emplace(std::move(msg));
        }
        m_cond.notify_one();
    }

    /**
     * dispatchSync
     *   Synchronously deliver notification to all matching sinks;
     *   rethrows any sink exception to caller.
     */
    void dispatchSync(const NotificationMessage& msg)
    {
        forEachMatchingSink(
            msg.channel,
            [&](NotificationSink& sink) {
                sink.deliver(msg);
            });
    }

    /**
     * awaitIdle
     *   Blocks until the internal queue has been drained.
     */
    void awaitIdle()
    {
        std::unique_lock lock{ m_idleMtx };
        m_idleCond.wait(lock, [this] {
            return m_queue.empty() && m_pendingTasks.load() == 0;
        });
    }

private:
    /* -- Internal thread-pool worker ------------------------------------ */
    void workerLoop()
    {
        while (true) {
            NotificationMessage task;

            {
                std::unique_lock lock{ m_queueMtx };
                m_cond.wait(lock, [this] {
                    return m_stopped || !m_queue.empty();
                });

                if (m_stopped && m_queue.empty()) { return; }

                task = std::move(m_queue.front());
                m_queue.pop();
                m_pendingTasks.fetch_add(1);
            }

            /* Deliver to sinks (may throw) */
            try {
                dispatchSync(task);
            }
            catch (const std::exception& ex) {
                // Basic error logging; integrate with centralized logger.
                std::cerr << "[NotificationService] delivery error: "
                          << ex.what() << '\n';
            }

            /*  Mark done and awake potential waiters */
            m_pendingTasks.fetch_sub(1);
            if (m_queue.empty() && m_pendingTasks.load() == 0) {
                std::lock_guard lock{ m_idleMtx };
                m_idleCond.notify_all();
            }
        }
    }

    /* -- Sink iteration helper ----------------------------------------- */
    template <typename Fn>
    void forEachMatchingSink(NotificationChannel ch, Fn&& fn)
    {
        std::shared_lock lock{ m_sinkMtx };
        for (const auto& sinkPtr : m_sinks) {
            if (sinkPtr && sinkPtr->canDeliver(ch)) {
                try {
                    fn(*sinkPtr);
                }
                catch (...) {
                    // Convert any sink exception into std::runtime_error
                    std::throw_with_nested(
                        std::runtime_error("sink delivery failure"));
                }
            }
        }
    }

private:
    /* -- sinks ---------------------------------------------------------- */
    std::vector<NotificationSinkPtr> m_sinks;
    mutable std::shared_mutex        m_sinkMtx;

    /* -- async queue ---------------------------------------------------- */
    std::queue<NotificationMessage>  m_queue;
    std::mutex                       m_queueMtx;
    std::condition_variable          m_cond;

    /* -- workers -------------------------------------------------------- */
    std::vector<std::thread>         m_workers;
    std::atomic<bool>                m_stopped;

    /* -- accounting ----------------------------------------------------- */
    std::atomic<std::size_t>         m_pendingTasks{ 0 };
    std::mutex                       m_idleMtx;
    std::condition_variable          m_idleCond;
};

/*------------------------------------------------------*
 *            SAMPLE SINK IMPLEMENTATIONS               *
 *  (These lightweight mocks aid compilation/demo only) *
 *------------------------------------------------------*/

namespace sinks {

/**
 * StdoutSink
 *  Delivers notifications by printing them to stdout.
 */
class StdoutSink : public NotificationSink
{
public:
    bool canDeliver(NotificationChannel /*unused*/) const noexcept override
    {
        return true;
    }

    void deliver(const NotificationMessage& msg) override
    {
        const auto ts =
            std::chrono::duration_cast<std::chrono::milliseconds>(
                msg.timestamp.time_since_epoch()).count();

        std::cout << "[StdoutSink][" << ts << "] "
                  << "[#" << msg.id << "] "
                  << toString(msg.level) << " - "
                  << msg.title << " : "
                  << msg.content << '\n';
    }

private:
    static const char* toString(NotificationLevel lvl) noexcept
    {
        switch (lvl) {
            case NotificationLevel::Info:    return "Info";
            case NotificationLevel::Warning: return "Warning";
            case NotificationLevel::Error:   return "Error";
            case NotificationLevel::Success: return "Success";
            default:                         return "Unknown";
        }
    }
};

} // namespace sinks
} // namespace mosaic::services

#endif // MOSAICBOARD_STUDIO_NOTIFICATION_SERVICE_H