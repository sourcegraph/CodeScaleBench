#pragma once
/*
    MosaicBoard Studio - Logging Utility
    ------------------------------------
    A light-weight, asynchronous, multi-sink logger designed for high-throughput
    web-dashboard workloads.  Completely header-only: simply include Logger.h
    wherever logging is needed.

    Usage
    -----
        mbs::Logger::init(mbs::LogLevel::INFO, "mbs.log");
        MBS_LOG_INFO("Server started on port {}", port);

    Compile-time flags
    ------------------
        -DMBS_DISABLE_LOGGING      Disables all logging calls (compiled out)
        -DMBS_LOG_USETZ=1          Print timestamps in local timezone (default: UTC)

    Copyright (c) 2024— MosaicBoard
*/
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <ctime>
#include <deque>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifndef MBS_DISABLE_LOGGING

namespace mbs
{
//--------------------------------------------------------------------------------------
// LogLevel
//--------------------------------------------------------------------------------------
enum class LogLevel : uint8_t
{
    TRACE = 0,
    DEBUG,
    INFO,
    WARN,
    ERROR,
    CRITICAL,
    OFF
};

// Convert level to readable string.
inline const char* levelToString(LogLevel level) noexcept
{
    switch (level)
    {
        case LogLevel::TRACE:    return "TRACE";
        case LogLevel::DEBUG:    return "DEBUG";
        case LogLevel::INFO:     return "INFO";
        case LogLevel::WARN:     return "WARN";
        case LogLevel::ERROR:    return "ERROR";
        case LogLevel::CRITICAL: return "CRIT";
        default:                 return "OFF";
    }
}

//--------------------------------------------------------------------------------------
// Sink interface
//--------------------------------------------------------------------------------------
struct LogMessage
{
    std::chrono::system_clock::time_point ts;
    LogLevel                              level;
    std::string                           text;
    std::string                           file;
    int                                   line;
    std::thread::id                       tid;
};

class Sink
{
public:
    virtual ~Sink() = default;
    virtual void write(const LogMessage& msg) = 0;
};

//--------------------------------------------------------------------------------------
// Console sink
//--------------------------------------------------------------------------------------
class ConsoleSink final : public Sink
{
public:
    void write(const LogMessage& msg) override
    {
        std::lock_guard<std::mutex> lk(_coutMutex);
        std::cout << formatPrefix(msg) << msg.text << std::endl;
    }

private:
    static std::string formatPrefix(const LogMessage& msg)
    {
        std::ostringstream oss;
        oss << '[' << formatTimestamp(msg.ts) << "] "
            << '[' << levelToString(msg.level) << "] "
            << '[' << msg.tid << "] ";
        return oss.str();
    }

    static std::string formatTimestamp(std::chrono::system_clock::time_point tp)
    {
        auto timeT   = std::chrono::system_clock::to_time_t(tp);
        std::tm tm{};
    #ifdef _WIN32
        gmtime_s(&tm, &timeT);
    #else
        gmtime_r(&timeT, &tm);
    #endif
        char buf[32];
        std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
        return {buf};
    }

    static std::mutex _coutMutex;
};
inline std::mutex ConsoleSink::_coutMutex;

//--------------------------------------------------------------------------------------
// File sink
//--------------------------------------------------------------------------------------
class FileSink final : public Sink
{
public:
    explicit FileSink(std::string  path) : _filePath(std::move(path))
    {
        _ofs.open(_filePath, std::ios::app);
        if (!_ofs.is_open())
        {
            throw std::runtime_error("Logger: Unable to open log file: " + _filePath);
        }
    }

    void write(const LogMessage& msg) override
    {
        std::lock_guard<std::mutex> lk(_fileMtx);
        _ofs << formatPrefix(msg) << msg.text << '\n';
        if (++_counter % _flushInterval == 0) { _ofs.flush(); }
    }

private:
    std::string _filePath;
    std::ofstream _ofs;
    std::mutex _fileMtx;
    size_t _counter{0};
    static constexpr size_t _flushInterval{20};

    static std::string formatPrefix(const LogMessage& msg)
    {
        std::ostringstream oss;
        oss << '[' << ConsoleSink::formatTimestamp(msg.ts) << "] "
            << '[' << levelToString(msg.level) << "] "
            << '[' << msg.file << ':' << msg.line << "] "
            << '[' << msg.tid << "] ";
        return oss.str();
    }
};

//--------------------------------------------------------------------------------------
// Callback sink – for piping logs into an event bus or remote collector.
//--------------------------------------------------------------------------------------
class CallbackSink final : public Sink
{
public:
    using Callback = std::function<void(const LogMessage&)>;
    explicit CallbackSink(Callback cb) : _cb(std::move(cb)) {}
    void write(const LogMessage& msg) override { _cb(msg); }

private:
    Callback _cb;
};

//--------------------------------------------------------------------------------------
// Logger
//--------------------------------------------------------------------------------------
class Logger
{
public:
    Logger(const Logger&)            = delete;
    Logger& operator=(const Logger&) = delete;

    // Initialize logger; thread-safe, idempotent.
    static void init(LogLevel level              = LogLevel::INFO,
                     const std::string& filePath = "",
                     bool enableConsole          = true)
    {
        instance()._init(level, filePath, enableConsole);
    }

    // Programmatic sink registration (must be called before first log message).
    static void addSink(std::unique_ptr<Sink> sink)
    {
        instance()._addSink(std::move(sink));
    }

    // Log a message (internal use – prefer macros below).
    static void log(LogLevel lvl,
                    std::string msg,
                    const char* file,
                    int line)
    {
        instance()._enqueue({std::chrono::system_clock::now(),
                             lvl,
                             std::move(msg),
                             file,
                             line,
                             std::this_thread::get_id()});
    }

    // Flush and stop background thread; implicitly called at exit.
    static void shutdown() { instance()._shutdown(); }

private:
    Logger()  = default;
    ~Logger() { _shutdown(); }

    static Logger& instance()
    {
        static Logger inst;
        return inst;
    }

    // Internal initialization.
    void _init(LogLevel level,
               const std::string& filePath,
               bool enableConsole)
    {
        std::lock_guard<std::mutex> lk(_initMutex);
        if (_active) { return; }

        _level.store(level, std::memory_order_relaxed);

        if (enableConsole)
            _sinks.emplace_back(std::make_unique<ConsoleSink>());

        if (!filePath.empty())
            _sinks.emplace_back(std::make_unique<FileSink>(filePath));

        // Start worker.
        _worker = std::thread([this] { this->_process(); });

        _active = true;
    }

    void _addSink(std::unique_ptr<Sink> sink)
    {
        std::lock_guard<std::mutex> lk(_queueMutex);
        _sinks.emplace_back(std::move(sink));
    }

    void _enqueue(LogMessage&& msg)
    {
        if (!_active.load(std::memory_order_acquire)) { return; }
        if (msg.level < _level.load(std::memory_order_relaxed)) { return; }

        {
            std::lock_guard<std::mutex> lk(_queueMutex);
            _queue.emplace_back(std::move(msg));
        }
        _cv.notify_one();
    }

    void _process()
    {
        for (;;)
        {
            std::unique_lock<std::mutex> lk(_queueMutex);
            _cv.wait(lk, [this] { return !_queue.empty() || _shouldExit; });

            if (_shouldExit && _queue.empty()) { break; }

            auto msg = std::move(_queue.front());
            _queue.pop_front();
            lk.unlock(); // Unlock early – writing may be slow.

            for (auto& s : _sinks)
            {
                try { s->write(msg); }
                catch (const std::exception& e)
                {
                    // Last-chance error handling: write to std::cerr.
                    std::cerr << "Logger sink error: " << e.what() << std::endl;
                }
            }
        }
    }

    void _shutdown()
    {
        bool expected = true;
        if (!_active.compare_exchange_strong(expected, false))
            return; // already shut down

        {
            std::lock_guard<std::mutex> lk(_queueMutex);
            _shouldExit = true;
        }
        _cv.notify_all();
        if (_worker.joinable()) { _worker.join(); }

        // Flush file sinks.
        for (auto& s : _sinks)
        {
            if (auto* fs = dynamic_cast<FileSink*>(s.get()))
            {
                // ensure destructor flushes.
                (void)fs;
            }
        }
    }

private:
    std::atomic<LogLevel>       _level{LogLevel::INFO};
    std::atomic_bool            _active{false};
    std::vector<std::unique_ptr<Sink>> _sinks;

    // Asynchronous queue
    std::deque<LogMessage>      _queue;
    std::mutex                  _queueMutex;
    std::condition_variable     _cv;
    std::thread                 _worker;
    std::atomic_bool            _shouldExit{false};

    std::mutex                  _initMutex; // protects init()
};

//--------------------------------------------------------------------------------------
// Helper macro machinery (compile-time formatting)
//--------------------------------------------------------------------------------------
namespace detail
{
    template<typename... Args>
    std::string format(const std::string& fmt, Args&&... args)
    {
        // Simple, safe, minimalistic format using stringstream.
        // For production workloads consider <fmt> or std::format (C++20).
        std::ostringstream oss;
        size_t  arg_index = 0;
        (oss << ... << ([&] {
            size_t pos = fmt.find("{}", arg_index);
            if (pos == std::string::npos)
                return std::string(fmt.substr(arg_index)), arg_index = fmt.size(), "";

            std::string prefix = fmt.substr(arg_index, pos - arg_index);
            arg_index = pos + 2;
            return prefix;
        }(), args));
        if (arg_index < fmt.size())
            oss << fmt.substr(arg_index);

        return oss.str();
    }
} // namespace detail

// Main macro – builds message lazily.
#define MBS_LOG(LVL, FMT, ...)                                                       \
    do                                                                               \
    {                                                                                \
        if (mbs::LogLevel::LVL >= mbs::Logger::instance()._level.load())             \
        {                                                                            \
            mbs::Logger::log(mbs::LogLevel::LVL,                                     \
                             mbs::detail::format((FMT), ##__VA_ARGS__),              \
                             __FILE__,                                               \
                             __LINE__);                                              \
        }                                                                            \
    } while (false)

#define MBS_LOG_TRACE(FMT, ...)    MBS_LOG(TRACE,    FMT, ##__VA_ARGS__)
#define MBS_LOG_DEBUG(FMT, ...)    MBS_LOG(DEBUG,    FMT, ##__VA_ARGS__)
#define MBS_LOG_INFO(FMT, ...)     MBS_LOG(INFO,     FMT, ##__VA_ARGS__)
#define MBS_LOG_WARN(FMT, ...)     MBS_LOG(WARN,     FMT, ##__VA_ARGS__)
#define MBS_LOG_ERROR(FMT, ...)    MBS_LOG(ERROR,    FMT, ##__VA_ARGS__)
#define MBS_LOG_CRITICAL(FMT, ...) MBS_LOG(CRITICAL, FMT, ##__VA_ARGS__)

} // namespace mbs

#else // MBS_DISABLE_LOGGING

// Logging disabled – compile out calls
namespace mbs { enum class LogLevel : uint8_t { OFF }; struct Logger { static void init(...) {} }; }
#define MBS_LOG_TRACE(...)
#define MBS_LOG_DEBUG(...)
#define MBS_LOG_INFO(...)
#define MBS_LOG_WARN(...)
#define MBS_LOG_ERROR(...)
#define MBS_LOG_CRITICAL(...)

#endif  // MBS_DISABLE_LOGGING