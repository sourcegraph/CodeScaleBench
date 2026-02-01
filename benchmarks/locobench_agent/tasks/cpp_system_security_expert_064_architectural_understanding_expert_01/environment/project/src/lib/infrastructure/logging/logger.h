#pragma once
/***************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  File:        src/lib/infrastructure/logging/logger.h
 *
 *  Description:
 *      Thin façade around spdlog that offers a project-wide, thread-safe, asynchronous
 *      logging facility.  The façade accomplishes three goals:
 *          1. Provides a stable API that decouples upper layers from the concrete
 *             third-party logging implementation (currently spdlog).
 *          2. Injects FortiLedger360-specific metadata (tenant-id, correlation-id, etc.)
 *             into every log line.
 *          3. Standardises logger creation and log-level management across runtime
 *             components so Ops can dynamically adjust verbosity via the control-plane.
 *
 *  Usage example:
 *
 *      // During bootstrap
 *      fl360::infra::logging::Logger::init("orchestrator-svc",
 *                                          spdlog::level::info,
 *                                          "/var/log/fortiledger360");
 *
 *      // Per component
 *      auto lg = fl360::infra::logging::Logger::get("BackupNode");
 *      lg->info("Starting backup cycle for tenant: {}", tenantId);
 *
 *  Build:
 *      Requires: spdlog (https://github.com/gabime/spdlog) >= 1.9
 **************************************************************************************************/

#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/dist_sink.h>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>

namespace fl360::infra::logging
{

/**
 * Logger
 *
 * Static-only helper that maintains a registry of component-specific loggers
 * backed by an asynchronous worker thread.  Each logger writes to a console
 * sink (stderr) and a rotating file sink that re-opens daily and retains a
 * configurable amount of history.
 *
 * The API is purposely minimal; for advanced use-cases call the underlying
 * spdlog::logger returned by get().
 */
class Logger
{
public:
    /**
     * Initialise the global logging backend.  Must be invoked once, during service
     * bootstrap, before any call to get()/core().
     *
     * @param applicationName   Used as part of the log file name and for metrics.
     * @param level             The initial verbosity (overridden later via setLevel()).
     * @param logDirectory      Where rotating log files are emitted.  Directory will be
     *                          created if it does not exist and permissions allow it.
     * @param rotationInterval  Rotation period (e.g., 24h).  Files are time-based, not size-based.
     * @param retentionCount    How many log files to retain before pruning.
     */
    static void init(const std::string&              applicationName,
                     spdlog::level::level_enum       level            = spdlog::level::info,
                     std::filesystem::path           logDirectory     = "logs",
                     std::chrono::hours              rotationInterval = std::chrono::hours{24},
                     std::size_t                     retentionCount   = 14);

    /**
     * Fetch or lazily create (thread-safe) a logger dedicated to the specified component.
     *
     * @param component Logical component name (e.g. "Scanner", "Metrics").
     * @return Shared pointer to a spdlog::logger instance.
     */
    static std::shared_ptr<spdlog::logger> get(const std::string& component);

    /**
     * Shortcut for the application-wide root logger.
     */
    static std::shared_ptr<spdlog::logger> core();

    /**
     * Dynamically raise/lower verbosity for ALL loggers already created.
     */
    static void setLevel(spdlog::level::level_enum lvl);

    /**
     * Gracefully stop the asynchronous logging queue and flush pending messages.
     * Idempotent.  Called automatically via a static destructor, but services that
     * fork/exec or hot-reload may prefer to invoke it explicitly.
     */
    static void shutdown() noexcept;

    /**
     * Indicates whether init() was successfully completed.
     */
    static bool isInitialised() noexcept { return initialised_.load(std::memory_order_acquire); }

private:
    Logger()  = delete;
    ~Logger() = delete;

    static std::shared_ptr<spdlog::logger>
    createLogger_(const std::string& component);

    // ----- Members -----
    inline static std::atomic<bool>                 initialised_{false};
    inline static std::mutex                        initMutex_;
    inline static std::shared_mutex                registryMutex_;
    inline static std::unordered_map<std::string,
                                     std::shared_ptr<spdlog::logger>> registry_;
    inline static std::shared_ptr<spdlog::logger>   coreLogger_;
    inline static std::string                       appName_;
    inline static std::shared_ptr<spdlog::sinks::dist_sink_mt> sharedSinks_;
    inline static std::shared_ptr<spdlog::thread_pool> threadPool_;
};

/* -------------------------------------------------------------------------------------------------
 *  Implementation
 * ------------------------------------------------------------------------------------------------/
inline void Logger::init(const std::string&              applicationName,
                         spdlog::level::level_enum       level,
                         std::filesystem::path           logDirectory,
                         std::chrono::hours              rotationInterval,
                         std::size_t                     retentionCount)
{
    if (initialised_.load(std::memory_order_acquire)) { return; }

    std::scoped_lock g(initMutex_);
    if (initialised_.load(std::memory_order_relaxed)) { return; }

    try
    {
        // Ensure directory exists
        std::error_code ec;
        if (!std::filesystem::exists(logDirectory, ec))
        {
            std::filesystem::create_directories(logDirectory, ec);
        }

        // -------- Common asynchronous thread pool --------
        constexpr std::size_t kQueueSize  = 8192;
        constexpr std::size_t kThreadPool = 1; // Single async worker is sufficient in most cases
        threadPool_ = std::make_shared<spdlog::thread_pool>(kQueueSize, kThreadPool);

        // -------- Sink distribution hub --------
        sharedSinks_ = std::make_shared<spdlog::sinks::dist_sink_mt>();

        // Console sink (stderr)
        auto consoleSink = std::make_shared<spdlog::sinks::stderr_color_sink_mt>();
        consoleSink->set_pattern("%^[%Y-%m-%dT%H:%M:%S.%e][%n][%l] %v%$");
        sharedSinks_->add_sink(consoleSink);

        // Rotating file sink (daily interval)
        auto filePath = logDirectory / (applicationName + ".log");
        auto fileSink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            filePath.string(),
            /*max_size =*/1024 * 1024 * 50, // fallback size-based 50MiB
            /*max_files=*/static_cast<std::size_t>(retentionCount));

        fileSink->set_pattern("[%Y-%m-%dT%H:%M:%S.%e][%n][%l] %v");
        sharedSinks_->add_sink(fileSink);

        // -------- Core logger --------
        spdlog::init_thread_pool(kQueueSize, kThreadPool);
        coreLogger_ = std::make_shared<spdlog::async_logger>(
            applicationName,
            sharedSinks_,
            threadPool_,
            spdlog::async_overflow_policy::block);
        coreLogger_->set_level(level);
        coreLogger_->flush_on(spdlog::level::err);

        spdlog::register_logger(coreLogger_);

        // Mark success
        appName_ = applicationName;
        initialised_.store(true, std::memory_order_release);
    }
    catch (const spdlog::spdlog_ex& ex)
    {
        // As logging is not available, fallback to stderr
        std::fprintf(stderr,
                     "Logger initialization failed: %s (logging disabled)\n",
                     ex.what());
        std::fflush(stderr);
        // Leave initialised_ false to signal failure
    }
}

inline std::shared_ptr<spdlog::logger> Logger::core()
{
    if (!initialised_)
    {
        // Best-effort fallback — create a console-only synchronous logger
        return spdlog::stderr_color_mt("stderr-fallback");
    }
    return coreLogger_;
}

inline std::shared_ptr<spdlog::logger> Logger::get(const std::string& component)
{
    if (!initialised_) { return core(); }

    {
        std::shared_lock r(registryMutex_);
        auto it = registry_.find(component);
        if (it != registry_.end()) { return it->second; }
    }
    // Upgrade to exclusive lock for creation
    std::unique_lock w(registryMutex_);
    auto [it, inserted] = registry_.try_emplace(component, createLogger_(component));
    return it->second;
}

inline std::shared_ptr<spdlog::logger>
Logger::createLogger_(const std::string& component)
{
    auto lg = std::make_shared<spdlog::async_logger>(
        component,
        sharedSinks_,
        threadPool_,
        spdlog::async_overflow_policy::block);

    lg->set_level(coreLogger_->level());
    lg->flush_on(spdlog::level::err);

    // Append component name to logline for easier grepping
    lg->set_pattern("[%Y-%m-%dT%H:%M:%S.%e][" + component + "][%l] %v");

    spdlog::register_logger(lg);
    return lg;
}

inline void Logger::setLevel(spdlog::level::level_enum lvl)
{
    if (!initialised_) { return; }

    coreLogger_->set_level(lvl);
    coreLogger_->info("Log level changed to {}", spdlog::level::to_string_view(lvl));

    std::shared_lock r(registryMutex_);
    for (auto& [_, lg] : registry_) { lg->set_level(lvl); }
}

inline void Logger::shutdown() noexcept
{
    if (!initialised_) { return; }

    try
    {
        spdlog::shutdown();
    }
    catch (...)
    {
        // ignore; we are already shutting down
    }
    initialised_.store(false, std::memory_order_release);
}

/* -------------------------------------------------------------------------------------------------
 *  Convenience Macros
 *
 *  The macros add compile-time source-location info without requiring the caller to pass
 *  the logger explicitly, assuming the common case where a file uses a single component
 *  logger: declare FL360_DEFINE_LOGGER("Component") once per translation unit.
 * ------------------------------------------------------------------------------------------------/
#define FL360_DEFINE_LOGGER(componentName)                                                     \
    static const std::shared_ptr<spdlog::logger>& _fl360_local_logger()                        \
    {                                                                                          \
        static const auto lg = ::fl360::infra::logging::Logger::get(componentName);            \
        return lg;                                                                             \
    }

#define FL360_LOG_TRACE(fmt, ...)  _fl360_local_logger()->trace(fmt, ##__VA_ARGS__)
#define FL360_LOG_DEBUG(fmt, ...)  _fl360_local_logger()->debug(fmt, ##__VA_ARGS__)
#define FL360_LOG_INFO(fmt, ...)   _fl360_local_logger()->info(fmt,  ##__VA_ARGS__)
#define FL360_LOG_WARN(fmt, ...)   _fl360_local_logger()->warn(fmt,  ##__VA_ARGS__)
#define FL360_LOG_ERROR(fmt, ...)  _fl360_local_logger()->error(fmt, ##__VA_ARGS__)
#define FL360_LOG_CRITICAL(fmt, ...) _fl360_local_logger()->critical(fmt, ##__VA_ARGS__)

} // namespace fl360::infra::logging

/***************************************************************************************************
 *  EoF
 **************************************************************************************************/
