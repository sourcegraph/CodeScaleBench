```cpp
/**
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 *  File   : FortiLedger360/src/lib/infrastructure/logging/log_observer.cpp
 *  Author : FortiLedger360 Core Team
 *  Brief  : Concrete Observer that translates Domain/Platform events into
 *           structured, asynchronous log entries. The component relies on
 *           spdlog for high-performance logging, as well as a minimal
 *           internal rate-limiter to guard against log-flooding scenarios
 *           (e.g., service-mesh cascading failures).
 *
 *  NOTE   : The companion header `log_observer.h` declares the
 *           `LogObserver` class and its `ObserverConfig` helper.
 *           This source file purposefully stays implementation-only.
 */

#include "infrastructure/logging/log_observer.h"

#include <spdlog/async.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

using namespace fortiledger360::infrastructure::logging;

namespace {

/* -------------------------------------------------------------
 * Anonymous-namespace helpers
 * ----------------------------------------------------------- */

/* string_view-based map lookup without allocations */
spdlog::level::level_enum to_spd_level(system_security::Severity sev) noexcept
{
    using namespace system_security;
    switch (sev)
    {
        case Severity::kTrace:    return spdlog::level::trace;
        case Severity::kDebug:    return spdlog::level::debug;
        case Severity::kInfo:     return spdlog::level::info;
        case Severity::kWarning:  return spdlog::level::warn;
        case Severity::kError:    return spdlog::level::err;
        case Severity::kCritical: return spdlog::level::critical;
        default:                  return spdlog::level::info;
    }
}

/* Very small token-bucket limiter – thread-safe & lock-free */
class TokenBucket final
{
public:
    explicit TokenBucket(std::size_t max_tokens,
                         std::chrono::seconds refill_period)
        : _max_tokens(max_tokens),
          _refill_period(refill_period),
          _tokens(max_tokens),
          _last_refill(std::chrono::steady_clock::now()) {}

    bool allow() noexcept
    {
        refill_if_necessary();
        std::size_t current = _tokens.load(std::memory_order_relaxed);

        while (current > 0)
        {
            if (_tokens.compare_exchange_weak(
                    current, current - 1, std::memory_order_acq_rel))
            {
                return true;
            }
        }
        return false; // Bucket empty.
    }

private:
    void refill_if_necessary() noexcept
    {
        auto now          = std::chrono::steady_clock::now();
        auto elapsed      = now - _last_refill.load(std::memory_order_acquire);
        if (elapsed < _refill_period) { return; }

        if (_last_refill.compare_exchange_strong(
                _cache_time, now, std::memory_order_acq_rel))
        {
            _tokens.store(_max_tokens, std::memory_order_release);
        }
    }

    const std::size_t              _max_tokens;
    const std::chrono::seconds     _refill_period;
    std::atomic<std::size_t>       _tokens;
    std::atomic<std::chrono::steady_clock::time_point> _last_refill;
    std::chrono::steady_clock::time_point _cache_time{};
};

} // namespace

/* =============================================================
 *  LogObserver Implementation
 * =========================================================== */

LogObserver::LogObserver(const ObserverConfig& cfg)
    : _cfg(cfg)
    , _rate_limiter(std::make_unique<TokenBucket>(cfg.rate_limit.burst,
                                                  cfg.rate_limit.period))
{
    try
    {
        //
        // Create/Reuse global async thread-pool. This is safe to call
        // multiple times — spdlog internally guards the creation.
        //
        spdlog::init_thread_pool(cfg.thread_pool_size, cfg.thread_count);

        //
        // Rotating file sink: <logfile>.<index>. Older files are rotated out.
        //
        auto file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            cfg.log_file,
            cfg.max_file_size,
            cfg.max_files);

        file_sink->set_level(cfg.sink_level);

        //
        // Build the asynchronous logger.
        //
        _logger = std::make_shared<spdlog::async_logger>(
            cfg.logger_name,
            file_sink,
            spdlog::thread_pool(),
            spdlog::async_overflow_policy::block);

        _logger->set_level(cfg.runtime_level);
        _logger->set_pattern("%Y-%m-%d %H:%M:%S.%e [%^%l%$] [%n] [%t] %v");
        _logger->flush_on(cfg.flush_level);

        spdlog::register_logger(_logger);
    }
    catch (const spdlog::spdlog_ex& ex)
    {
        std::ostringstream oss;
        oss << "LogObserver failed initialization: " << ex.what();
        throw std::runtime_error(oss.str());
    }
}

LogObserver::~LogObserver()
{
    // Destruction order: guarantee logger is unregistered before pool teardown.
    if (_logger)
    {
        _logger->flush();
        spdlog::drop(_logger->name());
    }
}

void LogObserver::on_event(const system_security::EventBase& evt)
{
    if (!_rate_limiter->allow())
    {
        // Optionally we could still count suppressed logs or forward
        // a health metric. For now we silently drop to safeguard I/O.
        return;
    }

    try
    {
        auto level = to_spd_level(evt.severity());

        // Format event into JSON so that downstream analytics can parse.
        auto payload = to_json(evt);

        _logger->log(level,
                     "tenant_id={} | correlation_id={} | type={} | payload={}",
                     evt.tenant_id(),
                     evt.correlation_id(),
                     evt.type(),
                     payload.dump());

        // If the event signals a critical error, flush immediately.
        if (level >= spdlog::level::critical) { _logger->flush(); }
    }
    catch (const std::exception& ex)
    {
        // Fallback to stderr as logging is compromised.
        std::cerr << "[LogObserver] Logging failure: " << ex.what() << '\n';
    }
}

/* -------------------------------------------------------------
 *  Private helpers
 * ----------------------------------------------------------- */

nlohmann::json LogObserver::to_json(const system_security::EventBase& evt) const
{
    // We rely on the EventBase API being immutable & thread-safe.
    nlohmann::json j;
    j["timestamp"]      = evt.timestamp().time_since_epoch().count();
    j["tenant_id"]      = evt.tenant_id();
    j["correlation_id"] = evt.correlation_id();
    j["payload"]        = evt.payload(); // Assuming string-based JSON.
    j["extra"]          = evt.extra();   // May contain nested map.
    return j;
}
```