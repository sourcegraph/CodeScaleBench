#include "core/logger.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <queue>
#include <regex>
#include <sstream>
#include <string_view>
#include <thread>
#include <unordered_map>

using namespace std::chrono_literals;

namespace ci360::core
{

// ──────────────────────────────────────────────────────────────────────────────
// Helper utilities
// ──────────────────────────────────────────────────────────────────────────────
namespace
{
constexpr std::string_view kLevelToStr[] = {
    "TRACE", "DEBUG", "INFO ", "WARN ", "ERROR", "CRIT "};

constexpr std::string_view kReset   = "\033[0m";
constexpr std::string_view kRed     = "\033[31m";
constexpr std::string_view kYellow  = "\033[33m";
constexpr std::string_view kGreen   = "\033[32m";
constexpr std::string_view kCyan    = "\033[36m";
constexpr std::string_view kMagenta = "\033[35m";
constexpr std::string_view kGrey    = "\033[90m";

std::string_view levelToColor(LogLevel lvl)
{
    switch (lvl)
    {
    case LogLevel::TRACE: return kGrey;
    case LogLevel::DEBUG: return kCyan;
    case LogLevel::INFO: return kGreen;
    case LogLevel::WARNING: return kYellow;
    case LogLevel::ERROR: return kRed;
    case LogLevel::CRITICAL: return kMagenta;
    default: return kReset;
    }
}

bool shouldColorize()
{
#ifdef _WIN32
    // Windows 10+ supports ANSI colors if the console mode is enabled,
    // but for simplicity we keep it disabled by default here.
    return false;
#else
    return true;
#endif
}

std::tm localtimeSafe(std::time_t t)
{
#ifdef _WIN32
    std::tm tm_buf;
    localtime_s(&tm_buf, &t);
    return tm_buf;
#else
    std::tm tm_buf;
    localtime_r(&t, &tm_buf);
    return tm_buf;
#endif
}

} // namespace

// ──────────────────────────────────────────────────────────────────────────────
// Logger::Impl
// ──────────────────────────────────────────────────────────────────────────────
class Logger::Impl
{
  public:
    explicit Impl(LoggerConfig cfg)
        : config_(std::move(cfg)), stopFlag_(false)
    {
        openFileSink();
        workerThread_ = std::thread([this] { this->workerLoop(); });
    }

    ~Impl()
    {
        {
            std::lock_guard lk(queueMtx_);
            stopFlag_ = true;
        }
        queueCv_.notify_one();
        if (workerThread_.joinable())
            workerThread_.join();
        if (fileStream_.is_open())
            fileStream_.close();
    }

    void log(LogLevel lvl, std::string_view category, std::string_view msg)
    {
        if (lvl < config_.globalLevel.load())
            return;

        LogEntry entry;
        entry.level    = lvl;
        entry.category = std::string(category);
        entry.message  = config_.redactPHI ? redactPHI(msg) : std::string(msg);
        entry.ts       = std::chrono::system_clock::now();

        {
            std::lock_guard lk(queueMtx_);
            queue_.push(std::move(entry));
        }
        queueCv_.notify_one();
    }

    LogLevel globalLevel() const { return config_.globalLevel.load(); }

    void setGlobalLevel(LogLevel lvl) { config_.globalLevel.store(lvl); }

  private:
    struct LogEntry
    {
        LogLevel                                   level;
        std::string                                category;
        std::string                                message;
        std::chrono::system_clock::time_point      ts;
    };

    void openFileSink()
    {
        if (config_.logDirectory.empty())
            return;

        try
        {
            std::filesystem::create_directories(config_.logDirectory);
        }
        catch (const std::exception& ex)
        {
            std::cerr << "[Logger] Failed to create log directory \""
                      << config_.logDirectory << "\": " << ex.what() << '\n';
            return;
        }

        const auto now = std::chrono::system_clock::to_time_t(
            std::chrono::system_clock::now());
        std::tm tm_buf = localtimeSafe(now);

        std::ostringstream oss;
        oss << config_.logDirectory << "/ci360_"
            << std::put_time(&tm_buf, "%Y%m%d_%H%M%S") << ".log";
        logFilePath_ = oss.str();

        fileStream_.open(logFilePath_, std::ios::out | std::ios::app);
        if (!fileStream_)
        {
            std::cerr << "[Logger] Failed to open log file " << logFilePath_
                      << '\n';
        }
    }

    // Very naive PHI redactor – real implementation would be far more
    // sophisticated. For demonstration we redact 10+ digit numbers and
    // anything that looks like "MRN:123456".
    std::string redactPHI(std::string_view text) const
    {
        static const std::regex kMrnRegex(R"(MRN:\s*\d+)", std::regex::icase);
        static const std::regex kDigits(R"(\b\d{10,}\b)");
        std::string             tmp(text);
        tmp = std::regex_replace(tmp, kMrnRegex, "MRN:[REDACTED]");
        tmp = std::regex_replace(tmp, kDigits, "[REDACTED]");
        return tmp;
    }

    void workerLoop()
    {
        std::unique_lock lk(queueMtx_);
        while (true)
        {
            queueCv_.wait(lk, [this] {
                return !queue_.empty() || stopFlag_;
            });

            if (stopFlag_ && queue_.empty())
                break;

            while (!queue_.empty())
            {
                LogEntry entry = std::move(queue_.front());
                queue_.pop();
                lk.unlock();
                try
                {
                    flushEntry(entry);
                }
                catch (const std::exception& ex)
                {
                    std::cerr << "[Logger] flushEntry threw: " << ex.what()
                              << '\n';
                }
                lk.lock();
            }
        }
    }

    void flushEntry(const LogEntry& e)
    {
        // Timestamp formatting
        const auto     t   = std::chrono::system_clock::to_time_t(e.ts);
        const auto     ms  = std::chrono::duration_cast<std::chrono::milliseconds>(
            e.ts.time_since_epoch()) %
                            1000;
        std::tm tm_buf = localtimeSafe(t);

        std::ostringstream oss;
        oss << std::put_time(&tm_buf, "%Y-%m-%d %H:%M:%S") << '.'
            << std::setw(3) << std::setfill('0') << ms.count() << ' ';

        oss << kLevelToStr[static_cast<int>(e.level)] << ' ';
        oss << '[' << e.category << "] ";
        oss << e.message << '\n';

        const std::string line = oss.str();

        // Console sink
        if (config_.consoleEnabled)
        {
            if (shouldColorize())
                std::cout << levelToColor(e.level);
            std::cout << line;
            if (shouldColorize())
                std::cout << kReset;
            std::cout.flush();
        }

        // File sink
        if (fileStream_)
        {
            fileStream_ << line;
            if (++fileLineCounter_ % 100 == 0)
                fileStream_.flush();

            if (config_.rotationBytes > 0 &&
                static_cast<uintmax_t>(fileStream_.tellp()) >
                    config_.rotationBytes)
            {
                rotateFileSink();
            }
        }
    }

    void rotateFileSink()
    {
        if (!fileStream_)
            return;

        fileStream_.flush();
        fileStream_.close();

        std::string rotated =
            logFilePath_ + ".1"; // simple .1 suffix rotation policy
        try
        {
            std::filesystem::rename(logFilePath_, rotated);
        }
        catch (const std::exception& ex)
        {
            std::cerr << "[Logger] File rotation failed: " << ex.what() << '\n';
        }

        openFileSink();
    }

    // ──────────────────────────────────────────────────────────────────────────
    LoggerConfig              config_;
    std::ofstream             fileStream_;
    std::string               logFilePath_;
    std::atomic<uint64_t>     fileLineCounter_{0};

    // Async queue
    std::queue<LogEntry>      queue_;
    std::mutex                queueMtx_;
    std::condition_variable   queueCv_;
    std::thread               workerThread_;
    bool                      stopFlag_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Logger façade (singleton)
// ──────────────────────────────────────────────────────────────────────────────
Logger& Logger::instance()
{
    static Logger logger;
    return logger;
}

void Logger::init(LoggerConfig cfg)
{
    std::lock_guard lk(mtx_);
    if (pimpl_)
        throw std::logic_error("Logger already initialized");
    pimpl_ = std::make_unique<Impl>(std::move(cfg));
}

bool Logger::isInitialized() const
{
    std::lock_guard lk(mtx_);
    return static_cast<bool>(pimpl_);
}

void Logger::destroy()
{
    std::lock_guard lk(mtx_);
    pimpl_.reset();
}

void Logger::log(LogLevel lvl, std::string_view category, std::string_view msg)
{
    std::shared_lock lk(rwMtx_);
    if (!pimpl_)
    {
        // Fallback: log synchronously to std::cerr
        std::cerr << "[Logger] Uninitialized: " << msg << '\n';
        return;
    }
    pimpl_->log(lvl, category, msg);
}

LogLevel Logger::level() const
{
    std::shared_lock lk(rwMtx_);
    return pimpl_ ? pimpl_->globalLevel() : LogLevel::INFO;
}

void Logger::setLevel(LogLevel lvl)
{
    std::shared_lock lk(rwMtx_);
    if (pimpl_)
        pimpl_->setGlobalLevel(lvl);
}

// ──────────────────────────────────────────────────────────────────────────────
// Shorthand helpers
// ──────────────────────────────────────────────────────────────────────────────
namespace detail
{
void log(LogLevel lvl, std::string_view category, std::string_view fmt,
         fmt::format_args args)
{
    std::string msg = fmt::vformat(fmt, args);
    Logger::instance().log(lvl, category, msg);
}
} // namespace detail

} // namespace ci360::core