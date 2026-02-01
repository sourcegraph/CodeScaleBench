#pragma once
/**
 * FortiLedger360 – Enterprise Security Suite
 * -----------------------------------------
 * Logging Observer (Header)
 *
 * The Logging subsystem sits inside the Infrastructure-layer and is consumed by
 * both low-level platform services (gRPC mesh nodes, background workers) and
 * higher-level orchestrators (API Gateway, Billing service).  The subsystem
 * offers an Observer facade that can be attached to the core event-bus,
 * transforming arbitrarily-shaped domain events into structured log messages,
 * then dispatching them to a chain of sinks (file, syslog, GELF, etc.).
 *
 * Design goals:
 *   • Decoupled:  No concrete sink implementation leaks into the observer.
 *   • High-throughput & thread-safe.
 *   • Zero-cost abstractions for events that already expose the expected API.
 *
 * NOTE:  This is a header-only component so that template-based event adaptation
 *        remains visible to the compiler.  Implementation is kept minimal to
 *        avoid multiple-definition hazards; ODR-safe inline definitions are
 *        employed where required.
 */

#include <chrono>
#include <cstdint>
#include <iomanip>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace fl360::infrastructure::logging {

// ------------------------------------------------------------------------------------------------
// LogLevel
// ------------------------------------------------------------------------------------------------
enum class LogLevel : std::uint8_t
{
    trace = 0,
    debug,
    info,
    warning,
    error,
    critical
};

inline constexpr std::string_view to_string(LogLevel lvl) noexcept
{
    switch (lvl)
    {
        case LogLevel::trace:    return "TRACE";
        case LogLevel::debug:    return "DEBUG";
        case LogLevel::info:     return "INFO";
        case LogLevel::warning:  return "WARN";
        case LogLevel::error:    return "ERROR";
        case LogLevel::critical: return "CRITICAL";
    }
    return "UNKNOWN";
}

// ------------------------------------------------------------------------------------------------
// LogEvent – Normalised, structured log message
// ------------------------------------------------------------------------------------------------
struct LogEvent
{
    std::chrono::system_clock::time_point                timestamp;
    LogLevel                                             level;
    std::string                                          component;  // e.g. "Scanner", "API-GW"
    std::string                                          message;    // pre-formatted, human readable
    std::unordered_map<std::string, std::string>         context;    // arbitrary K/V metadata

    LogEvent() = default;

    LogEvent(LogLevel                               lvl,
             std::string_view                       comp,
             std::string_view                       msg,
             std::unordered_map<std::string, std::string> ctx = {})
        : timestamp(std::chrono::system_clock::now()),
          level(lvl),
          component(comp),
          message(msg),
          context(std::move(ctx))
    {}

    // Serialise to a single-line JSON document (GELF-friendly).
    [[nodiscard]] std::string to_json() const
    {
        std::ostringstream oss;
        const auto time    = std::chrono::system_clock::to_time_t(timestamp);
        const auto millis  = std::chrono::duration_cast<std::chrono::milliseconds>(
                                 timestamp.time_since_epoch()) %
                            1000;

        oss << '{'
            << "\"ts\":\"" << std::put_time(std::gmtime(&time), "%FT%T")
            << '.' << std::setw(3) << std::setfill('0') << millis.count() << "Z\","
            << "\"level\":\"" << to_string(level) << "\","
            << "\"component\":\"" << component << "\","
            << "\"message\":\"" << message << '"';

        for (const auto& [k, v] : context)
        {
            oss << ",\"" << k << "\":\"" << v << '"';
        }
        oss << '}';
        return oss.str();
    }
};

// ------------------------------------------------------------------------------------------------
// Concept:  Events that can auto-adapt to LogEvent
// ------------------------------------------------------------------------------------------------
#if __cpp_concepts
template <typename T>
concept LoggableEvent =
    requires(const T& e)
{
    // Mandatory API that allows implicit adaptation.
    { e.logLevel() } -> std::same_as<LogLevel>;
    { e.component() } -> std::convertible_to<std::string_view>;
    { e.message() }  -> std::convertible_to<std::string_view>;

    // Optional constext; when absent, substitution fails & SFINAE picks the
    // overload taking no context.
    { e.context() } -> std::convertible_to<std::unordered_map<std::string, std::string>>;
};
#endif

// ------------------------------------------------------------------------------------------------
// Sink interface
// ------------------------------------------------------------------------------------------------
class ILogSink
{
public:
    virtual ~ILogSink() = default;

    // Thread-safe: must be internally synchronised by the implementation.
    virtual void consume(const LogEvent& event) = 0;
};

// ------------------------------------------------------------------------------------------------
// LogObserver – Subject in the Observer graph, delegated from the Event-Bus
// ------------------------------------------------------------------------------------------------
class LogObserver : public std::enable_shared_from_this<LogObserver>
{
public:
    LogObserver()                                  = default;
    LogObserver(const LogObserver&)                = delete;
    LogObserver& operator=(const LogObserver&)     = delete;
    LogObserver(LogObserver&&) noexcept            = delete;
    LogObserver& operator=(LogObserver&&) noexcept = delete;
    ~LogObserver()                                 = default;

    // Singleton accessor (lazy, thread-safe, call-once).
    static std::shared_ptr<LogObserver> instance()
    {
        static std::shared_ptr<LogObserver> _instance{new LogObserver};
        return _instance;
    }

    // Attach / detach sinks (runtime configurable)
    void attachSink(std::shared_ptr<ILogSink> sink)
    {
        std::unique_lock lk{_sinkMtx};
        _sinks.emplace_back(std::move(sink));
    }

    void detachSink(const std::shared_ptr<ILogSink>& sink)
    {
        std::unique_lock lk{_sinkMtx};
        _sinks.erase(std::remove(_sinks.begin(), _sinks.end(), sink), _sinks.end());
    }

    void setMinimumLevel(LogLevel lvl) noexcept { _minLevel.store(lvl, std::memory_order_relaxed); }
    [[nodiscard]] LogLevel minimumLevel() const noexcept { return _minLevel.load(std::memory_order_relaxed); }

    // ---------------------------------------------------------------------
    // Public API – Generic event forwarding
    // ---------------------------------------------------------------------
    template <typename EventT>
#if __cpp_concepts
        requires LoggableEvent<EventT>
#endif
    void onEvent(const EventT& evt)
    {
        LogEvent le{evt.logLevel(), evt.component(), evt.message(), evt.context()};
        dispatch(std::move(le));
    }

    // Overload for manual usage where the caller already built a LogEvent
    void onEvent(LogEvent evt) { dispatch(std::move(evt)); }

private:
    // Dispatch with filtering & exception safety
    void dispatch(LogEvent&& evt)
    {
        if (evt.level < minimumLevel())
            return;

        // Acquire shared view of sinks (copy so that unlocked for each consume)
        std::vector<std::shared_ptr<ILogSink>> localSinks;
        {
            std::shared_lock lk{_sinkMtx};
            localSinks = _sinks;
        }

        for (const auto& sink : localSinks)
        {
            if (!sink) continue;

            try
            {
                sink->consume(evt);
            }
            catch (const std::exception& ex)
            {
                // Swallow & degrade – logging must never affect business flow.
                // In production we may route this to a fallback (stderr, syslog).
                (void)ex; // suppress unused-var warning
            }
        }
    }

    // Thread-safe state
    std::vector<std::shared_ptr<ILogSink>> _sinks;
    std::shared_mutex                       _sinkMtx;
    std::atomic<LogLevel>                   _minLevel{LogLevel::info};
};

// ------------------------------------------------------------------------------------------------
// Convenience builder for ad-hoc log records
// ------------------------------------------------------------------------------------------------
class LogBuilder
{
public:
    explicit LogBuilder(LogLevel lvl) : _event(lvl, "", "") {}
    ~LogBuilder() { flush(); }

    LogBuilder& component(std::string_view comp) noexcept
    {
        _event.component = comp;
        return *this;
    }
    LogBuilder& message(std::string_view msg) noexcept
    {
        _event.message = msg;
        return *this;
    }
    LogBuilder& kv(std::string_view k, std::string_view v)
    {
        _event.context.emplace(std::string{k}, std::string{v});
        return *this;
    }

private:
    void flush()
    {
        if (!_flushed)
        {
            LogObserver::instance()->onEvent(std::move(_event));
            _flushed = true;
        }
    }

    LogEvent _event;
    bool     _flushed{false};
};

// ------------------------------------------------------------------------------------------------
} // namespace fl360::infrastructure::logging