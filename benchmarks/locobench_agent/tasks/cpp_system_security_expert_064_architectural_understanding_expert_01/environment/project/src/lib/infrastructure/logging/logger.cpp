```cpp
/**
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 * Source:  src/lib/infrastructure/logging/logger.cpp
 *
 * Logging façade around spdlog that provides:
 *   • Global, thread–safe, asynchronous log aggregation
 *   • Rotating-file + colourised console output
 *   • Per-request contextual information (tenant-id, correlation-id)
 *   • Minimal-overhead convenience macros (FL360_LOG_*)
 *
 * The logger lives in the Infrastructure layer; higher layers interact only
 * through the public API & macros defined in this compilation unit (or the
 * accompanying header, if split).
 *
 * Author : FortiLedger360 Engineering
 * License: Proprietary – All Rights Reserved
 */

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <fmt/format.h>
#include <spdlog/async.h>
#include <spdlog/async_logger.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

namespace fl360::infra::logging {

// ---------------------------------------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------------------------------------
/// Lightweight RFC-4122-ish (v4) UUID generator for correlation-IDs.
// (NOTE: Not cryptographically secure.  For stronger guarantees use a proper UUID
//        library such as boost::uuid or libuuid and wire it in via CMake.)
static std::string generate_uuid()
{
    static thread_local std::mt19937_64 rng{std::random_device{}()};
    std::uniform_int_distribution<uint64_t> dist;

    uint64_t part1 = dist(rng);
    uint64_t part2 = dist(rng);

    return fmt::format("{:08x}-{:04x}-4{:03x}-a{:03x}-{:012x}",
                       static_cast<std::uint32_t>(part1 >> 32),
                       static_cast<std::uint16_t>((part1 >> 16) & 0xFFFF),
                       static_cast<std::uint16_t>(part1 & 0x0FFF),
                       static_cast<std::uint16_t>((part2 >> 48) & 0x0FFF),
                       (part2 & 0xFFFFFFFFFFFFULL));
}

// ---------------------------------------------------------------------------------------------------------------------
// Thread-local contextual data (MDC)
// ---------------------------------------------------------------------------------------------------------------------
struct ThreadContext
{
    std::string tenant_id;
    std::string correlation_id;
};

static thread_local ThreadContext g_thread_ctx;

// ---------------------------------------------------------------------------------------------------------------------
// Logger singleton
// ---------------------------------------------------------------------------------------------------------------------
class Logger final
{
public:
    static Logger &instance()
    {
        static Logger _instance;
        return _instance;
    }

    // Non-copyable / non-movable
    Logger(const Logger &)            = delete;
    Logger(Logger &&)                 = delete;
    Logger &operator=(const Logger &) = delete;
    Logger &operator=(Logger &&)      = delete;

    // -------------------------------------------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------------------------------------------
    void set_level(spdlog::level::level_enum lvl)
    {
        m_core->set_level(lvl);
    }

    spdlog::level::level_enum level() const noexcept
    {
        return m_core->level();
    }

    // -------- Context management ---------------------------------------------------------------------------------
    void set_tenant_id(std::string tenant_id)
    {
        g_thread_ctx.tenant_id = std::move(tenant_id);
    }

    void clear_tenant_id()
    {
        g_thread_ctx.tenant_id.clear();
    }

    void set_correlation_id(std::string correlation_id)
    {
        g_thread_ctx.correlation_id = std::move(correlation_id);
    }

    // Auto-generate & return a correlation ID when one has not been supplied.
    const std::string &ensure_correlation_id()
    {
        if (g_thread_ctx.correlation_id.empty())
        {
            g_thread_ctx.correlation_id = generate_uuid();
        }
        return g_thread_ctx.correlation_id;
    }

    void clear_correlation_id()
    {
        g_thread_ctx.correlation_id.clear();
    }

    // -------- Logging wrappers ------------------------------------------------------------------------------------
    template <typename... Args>
    void trace(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::trace, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    void debug(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::debug, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    void info(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::info, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    void warn(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::warn, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    void error(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::err, fmt, std::forward<Args>(args)...);
    }

    template <typename... Args>
    void critical(const std::string &fmt, Args &&... args)
    {
        log(spdlog::level::critical, fmt, std::forward<Args>(args)...);
    }

    // Flush pending messages (mainly for unit-tests / graceful shutdown)
    void flush()
    {
        m_core->flush();
    }

private:
    Logger()
    {
        initialise();
    }

    ~Logger()
    {
        spdlog::shutdown();  // Ensures all async buffers are flushed.
    }

    void initialise()
    {
        constexpr std::size_t k_queue_size      = 16 * 1024;      // Entries in async queue
        constexpr std::size_t k_rot_max_size_mb = 32;             // 32 MB per file
        constexpr std::size_t k_rot_files       = 5;              // Keep 5 rotations

        auto tp = std::make_shared<spdlog::details::thread_pool>(k_queue_size, 1);

        // (1) Console sink – vividly coloured when terminal supports it.
        auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        console_sink->set_level(spdlog::level::debug);

        // (2) Rotating file sink
        std::filesystem::create_directories("logs");  // Ensure dir exists (ignore errors).
        auto rotating_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            "logs/fortiledger360.log", k_rot_max_size_mb * 1024 * 1024, k_rot_files, true);

        rotating_sink->set_level(spdlog::level::trace);  // Capture everything here.

        std::vector<spdlog::sink_ptr> sinks{console_sink, rotating_sink};

        m_core = std::make_shared<spdlog::async_logger>(
            "FortiLedger360",
            sinks.begin(),
            sinks.end(),
            tp,
            spdlog::async_overflow_policy::block);

        spdlog::register_logger(m_core);
        m_core->set_level(spdlog::level::info);

        // Pattern explanation:
        //  %Y-%m-%d %H:%M:%S.%e   ─ ISO timestamp w/ µs precision
        //  %^ / %$                ─ colour range start / end
        //  %l                     ─ log level
        //  %n                     ─ logger name (FortiLedger360)
        //  %t                     ─ thread id
        //  %v                     ─ logged message
        m_core->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] [tid %t] %v");
    }

    // Centralised logging pipeline (adds context & routing).
    template <typename... Args>
    void log(spdlog::level::level_enum lvl,
             const std::string       &fmt_msg,
             Args &&... args)
    {
        if (!m_core->should_log(lvl))
            return;

        try
        {
            const auto full_msg_body = fmt::format(fmt_msg, std::forward<Args>(args)...);

            // Prepend context if available.
            const std::string prefix =
                fmt::format("[tenant:{}] [corr:{}] ",
                            g_thread_ctx.tenant_id.empty() ? "-" : g_thread_ctx.tenant_id,
                            g_thread_ctx.correlation_id.empty() ? ensure_correlation_id()
                                                                : g_thread_ctx.correlation_id);

            m_core->log(lvl, "{}{}", prefix, full_msg_body);
        }
        catch (const std::exception &ex)
        {
            // As logging should NEVER crash the application, we fallback to stderr.
            try
            {
                std::fprintf(stderr, "Logging failure: %s\n", ex.what());
            }
            catch (...)
            {
                /* swallow */
            }
        }
    }

private:
    std::shared_ptr<spdlog::logger> m_core;
};

// ---------------------------------------------------------------------------------------------------------------------
// Convenience macros – mimic spdlog’s API so caller side remains uncluttered
// ---------------------------------------------------------------------------------------------------------------------
#define FL360_LOG_TRACE(fmt, ...)    ::fl360::infra::logging::Logger::instance().trace(fmt, ##__VA_ARGS__)
#define FL360_LOG_DEBUG(fmt, ...)    ::fl360::infra::logging::Logger::instance().debug(fmt, ##__VA_ARGS__)
#define FL360_LOG_INFO(fmt, ...)     ::fl360::infra::logging::Logger::instance().info(fmt, ##__VA_ARGS__)
#define FL360_LOG_WARN(fmt, ...)     ::fl360::infra::logging::Logger::instance().warn(fmt, ##__VA_ARGS__)
#define FL360_LOG_ERROR(fmt, ...)    ::fl360::infra::logging::Logger::instance().error(fmt, ##__VA_ARGS__)
#define FL360_LOG_CRITICAL(fmt, ...) ::fl360::infra::logging::Logger::instance().critical(fmt, ##__VA_ARGS__)

// Context manipulation shortcuts
#define FL360_LOG_SET_TENANT(id)        ::fl360::infra::logging::Logger::instance().set_tenant_id(id)
#define FL360_LOG_CLEAR_TENANT()        ::fl360::infra::logging::Logger::instance().clear_tenant_id()
#define FL360_LOG_SET_CORRELATION(id)   ::fl360::infra::logging::Logger::instance().set_correlation_id(id)
#define FL360_LOG_CLEAR_CORRELATION()   ::fl360::infra::logging::Logger::instance().clear_correlation_id()
#define FL360_LOG_GENERATE_CORRELATION() ::fl360::infra::logging::Logger::instance().ensure_correlation_id()

}  // namespace fl360::infra::logging
```