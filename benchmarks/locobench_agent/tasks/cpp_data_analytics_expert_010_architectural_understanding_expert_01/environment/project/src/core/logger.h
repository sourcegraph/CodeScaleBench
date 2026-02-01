#ifndef CARDIO_INSIGHT_360_CORE_LOGGER_H_
#define CARDIO_INSIGHT_360_CORE_LOGGER_H_

/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * Production-grade logging façade that wraps spdlog and exposes
 * a minimal, project-wide API for structured, asynchronous logging.
 *
 * The wrapper owns two loggers:
 *   1. core   – all diagnostic output from the analytics engine
 *   2. audit  – immutable, compliance-grade audit events
 *
 * Loggers are:
 *   • Asynchronous (single background thread, bounded queue)
 *   • Rotating (long-running hospital servers)
 *   • Thread-safe
 *
 * Usage:
 *   ci360::core::Logger::init();              // One-time during bootstrap
 *   CI360_LOG_INFO("ECG ingestion started");  // Ubiquitous macro
 *   ci360::core::Logger::shutdown();          // Graceful application exit
 */

#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

#define SPDLOG_ACTIVE_LEVEL SPDLOG_LEVEL_TRACE
#include <spdlog/async.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

namespace ci360::core {

class Logger
{
public:
    enum class Level
    {
        Trace,
        Debug,
        Info,
        Warn,
        Error,
        Critical,
        Off
    };

    /*------------------------------------------------------------------
     * init
     * -----------------------------------------------------------------
     * Initializes the asynchronous logging subsystem.
     *      level        – minimal severities accepted by the core logger
     *      logDir       – directory for rotating log files
     *      maxFileSize  – individual file size in bytes before rotation
     *      maxFiles     – maximum number of rotated files to keep
     * Throws spdlog::spdlog_ex if underlying logger fails.
     * Thread-safe and idempotent.
     */
    static void init(Level           level         = Level::Info,
                     std::string_view logDir       = "logs",
                     std::size_t      maxFileSize  = 10 * 1024 * 1024, // 10 MiB
                     std::size_t      maxFiles     = 5);

    // Flush and release resources.
    static void shutdown() noexcept;

    // Change minimal severity at runtime (e.g. from an admin console).
    static void setLevel(Level level);

    static Level getLevel();

    // -----------------------------------------------------------------
    // Variadic convenience wrappers (fmt-compatible).
    // -----------------------------------------------------------------
    template <typename... Args>
    static void trace(std::string_view fmt, Args&&... args);

    template <typename... Args>
    static void debug(std::string_view fmt, Args&&... args);

    template <typename... Args>
    static void info(std::string_view fmt, Args&&... args);

    template <typename... Args>
    static void warn(std::string_view fmt, Args&&... args);

    template <typename... Args>
    static void error(std::string_view fmt, Args&&... args);

    template <typename... Args>
    static void critical(std::string_view fmt, Args&&... args);

    // Direct access for advanced use-cases (structured logging, sinks).
    static std::shared_ptr<spdlog::logger> core();
    static std::shared_ptr<spdlog::logger> audit();

private:
    Logger()  = delete;
    ~Logger() = delete;

    static spdlog::level::level_enum toSpd(Level lvl) noexcept;
    static Level                     fromSpd(spdlog::level::level_enum) noexcept;

    static std::filesystem::path ensureDirectory(std::string_view dir);

    // -----------------------------------------------------------------
    // Data
    // -----------------------------------------------------------------
    static inline std::shared_ptr<spdlog::logger> coreLogger_{};
    static inline std::shared_ptr<spdlog::logger> auditLogger_{};
    static inline std::atomic<bool>               initialized_{false};
    static inline std::mutex                      initMutex_;
};

/*=====================================================================
 * Implementation (header-only)
 *===================================================================*/
inline void Logger::init(Level           level,
                         std::string_view logDir,
                         std::size_t      maxFileSize,
                         std::size_t      maxFiles)
{
    if (initialized_.load(std::memory_order_acquire))
        return;

    std::lock_guard<std::mutex> lock(initMutex_);
    if (initialized_.load(std::memory_order_relaxed))
        return;

    // Override level from environment when requested (idempotent).
    if (const char* env = std::getenv("CI360_LOG_LEVEL"); env && *env)
    {
        std::string s{env};
        std::transform(s.begin(), s.end(), s.begin(), ::toupper);
        if (s == "TRACE") level = Level::Trace;
        else if (s == "DEBUG") level = Level::Debug;
        else if (s == "INFO") level = Level::Info;
        else if (s == "WARN") level = Level::Warn;
        else if (s == "ERROR") level = Level::Error;
        else if (s == "CRITICAL") level = Level::Critical;
        else if (s == "OFF") level = Level::Off;
    }

    const std::filesystem::path directory = ensureDirectory(logDir);

    // Initialize a bounded async thread pool – single background worker.
    constexpr std::size_t kQueueSize = 8192;
    static auto           threadPool =
        std::make_shared<spdlog::details::thread_pool>(kQueueSize, 1);
    spdlog::init_thread_pool(kQueueSize, 1);

    try
    {
        auto stdoutSink =
            std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        stdoutSink->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");

        auto rotatingSink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            (directory / "ci360.log").string(), maxFileSize, maxFiles, false);

        coreLogger_ = std::make_shared<spdlog::async_logger>(
            "core",
            spdlog::sinks_init_list{stdoutSink, rotatingSink},
            threadPool,
            spdlog::async_overflow_policy::block);
        coreLogger_->set_level(toSpd(level));
        coreLogger_->flush_on(spdlog::level::warn);

        // Audit logger writes only to file, never rotates, never truncates.
        auto auditSink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            (directory / "ci360_audit.log").string(),
            maxFileSize,
            maxFiles,
            false);
        auditSink->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [AUDIT] %v");

        auditLogger_ = std::make_shared<spdlog::async_logger>(
            "audit",
            spdlog::sinks_init_list{auditSink},
            threadPool,
            spdlog::async_overflow_policy::block);
        auditLogger_->set_level(spdlog::level::info);
        auditLogger_->flush_on(spdlog::level::info);

        spdlog::register_logger(coreLogger_);
        spdlog::register_logger(auditLogger_);
        spdlog::set_default_logger(coreLogger_);
        spdlog::set_level(toSpd(level));

        initialized_.store(true, std::memory_order_release);
    }
    catch (const spdlog::spdlog_ex& ex)
    {
        // Last resort: stderr. We cannot throw further in many embedded
        // contexts (early bootstrap or exit handler).
        std::fprintf(stderr, "Logger initialization failed: %s\n", ex.what());
        std::fflush(stderr);
        throw; // propagate to caller – bootstrap should handle.
    }
}

inline void Logger::shutdown() noexcept
{
    if (!initialized_.load(std::memory_order_acquire))
        return;

    spdlog::shutdown();
    coreLogger_.reset();
    auditLogger_.reset();
    initialized_.store(false, std::memory_order_release);
}

inline void Logger::setLevel(Level lvl)
{
    coreLogger_->set_level(toSpd(lvl));
}

inline Logger::Level Logger::getLevel()
{
    return fromSpd(coreLogger_->level());
}

template <typename... Args>
inline void Logger::trace(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->trace(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void Logger::debug(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->debug(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void Logger::info(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->info(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void Logger::warn(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->warn(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void Logger::error(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->error(fmt, std::forward<Args>(args)...);
}

template <typename... Args>
inline void Logger::critical(std::string_view fmt, Args&&... args)
{
    if (coreLogger_)
        coreLogger_->critical(fmt, std::forward<Args>(args)...);
}

inline std::shared_ptr<spdlog::logger> Logger::core()
{
    return coreLogger_;
}
inline std::shared_ptr<spdlog::logger> Logger::audit()
{
    return auditLogger_;
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------
inline spdlog::level::level_enum Logger::toSpd(Level lvl) noexcept
{
    using LL = Logger::Level;
    switch (lvl)
    {
        case LL::Trace: return spdlog::level::trace;
        case LL::Debug: return spdlog::level::debug;
        case LL::Info: return spdlog::level::info;
        case LL::Warn: return spdlog::level::warn;
        case LL::Error: return spdlog::level::err;
        case LL::Critical: return spdlog::level::critical;
        case LL::Off: return spdlog::level::off;
        default: return spdlog::level::info;
    }
}

inline Logger::Level Logger::fromSpd(spdlog::level::level_enum lvl) noexcept
{
    using SL = spdlog::level::level_enum;
    switch (lvl)
    {
        case SL::trace: return Level::Trace;
        case SL::debug: return Level::Debug;
        case SL::info: return Level::Info;
        case SL::warn: return Level::Warn;
        case SL::err: return Level::Error;
        case SL::critical: return Level::Critical;
        case SL::off: return Level::Off;
        default: return Level::Info;
    }
}

inline std::filesystem::path Logger::ensureDirectory(std::string_view dir)
{
    std::filesystem::path p{dir};
    std::error_code       ec;
    if (!std::filesystem::exists(p, ec))
    {
        std::filesystem::create_directories(p, ec);
        if (ec)
        {
            std::ostringstream oss;
            oss << "Unable to create log directory [" << p << "]: " << ec.message();
            throw spdlog::spdlog_ex{oss.str()};
        }
    }
    return p;
}

/*=====================================================================
 * Global convenience macros
 *   • Do not evaluate arguments when the level is disabled.
 *===================================================================*/
#define CI360_LOG_TRACE(...)    \
    if (ci360::core::Logger::getLevel() <= ci360::core::Logger::Level::Trace) \
    ci360::core::Logger::trace(__VA_ARGS__)

#define CI360_LOG_DEBUG(...)    \
    if (ci360::core::Logger::getLevel() <= ci360::core::Logger::Level::Debug) \
    ci360::core::Logger::debug(__VA_ARGS__)

#define CI360_LOG_INFO(...)     \
    if (ci360::core::Logger::getLevel() <= ci360::core::Logger::Level::Info)  \
    ci360::core::Logger::info(__VA_ARGS__)

#define CI360_LOG_WARN(...)     ci360::core::Logger::warn(__VA_ARGS__)
#define CI360_LOG_ERROR(...)    ci360::core::Logger::error(__VA_ARGS__)
#define CI360_LOG_CRITICAL(...) ci360::core::Logger::critical(__VA_ARGS__)

} // namespace ci360::core

#endif // CARDIO_INSIGHT_360_CORE_LOGGER_H_
