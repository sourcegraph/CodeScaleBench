#include "LoggingMiddleware.hpp"  // The public interface for this middleware
// ──────────────────────────────────────────────────────────────────────────────
//  MosaicBoard Studio
//  File:    MosaicBoardStudio/src/middleware/LoggingMiddleware.cpp
//  Author:  MosaicBoard Core Team
//
//  Description:
//      A production-ready logging middleware that sits in the HTTP pipeline.
//      It performs the following tasks:
//          • Generates / propagates a correlation-ID for every incoming request
//          • Logs request/response metadata in structured JSON
//          • Measures latency and flags “slow” requests
//          • Delegates to the next middleware in the chain
//          • Catches and reports unhandled exceptions
//
//  Compile-time requirements:
//      Add ‘spdlog’ (≥1.11) to your dependency manager and enable C++17.
//
//  Usage:
//      auto app = http::WebApplication{};
//      app.use(std::make_shared<mosaic::middleware::LoggingMiddleware>());
// ──────────────────────────────────────────────────────────────────────────────
#include <spdlog/async.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/fmt/ostr.h>

#include <chrono>
#include <filesystem>
#include <functional>
#include <mutex>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>

// ──────────────────────────────────────────────────────────────────────────────
//  Minimal stand-ins for engine interfaces (so this TU is self-contained).
//  Remove these once linked against the real MosaicBoard HTTP pipeline.
// ──────────────────────────────────────────────────────────────────────────────
namespace mosaic::http {

struct HttpRequest {
    std::string                                 method;
    std::string                                 uri;
    std::unordered_map<std::string, std::string> headers;
    std::string                                 body;
};

struct HttpResponse {
    int                                          status {200};
    std::string                                  body;
    std::unordered_map<std::string, std::string> headers;
};

struct HttpContext {
    HttpRequest  request;
    HttpResponse response;
};

using NextMiddleware = std::function<void(HttpContext&)>;

} // namespace mosaic::http

// ──────────────────────────────────────────────────────────────────────────────
//  Actual implementation
// ──────────────────────────────────────────────────────────────────────────────
namespace mosaic::middleware {

namespace {

constexpr const char* kDefaultLogFileName = "mosaic_server.log";
constexpr std::chrono::milliseconds kDefaultSlowThreshold {700};

// Generates a pseudo-random UUID-v4 (not RFC-4122 compliant, but good enough
// for correlation purposes). Cost: O(1).
inline std::string generateUuid()
{
    static thread_local std::mt19937_64 eng {std::random_device{}()};
    static constexpr char v[] = "0123456789abcdef";
    std::uniform_int_distribution<std::uint64_t> dist;

    std::uint64_t part1 = dist(eng);
    std::uint64_t part2 = dist(eng);

    std::string uuid;
    uuid.reserve(36);

    for (int i = 0; i < 16; ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10) { uuid.push_back('-'); }
        uuid.push_back(v[(part1 >> (i * 4)) & 0xF]);
    }
    for (int i = 0; i < 16; ++i) {
        if (i == 6 || i == 8 || i == 10 || i == 12) { uuid.push_back('-'); }
        uuid.push_back(v[(part2 >> (i * 4)) & 0xF]);
    }
    return uuid;
}

// Thread-safe singleton for our spdlog instance
std::shared_ptr<spdlog::logger> createGlobalLogger(
    const std::filesystem::path& directory,
    spdlog::level::level_enum     level)
{
    namespace fs = std::filesystem;

    fs::create_directories(directory); // no-op if already exists

    std::vector<spdlog::sink_ptr> sinks;
    sinks.reserve(2);

    auto consoleSink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    consoleSink->set_level(level);
    consoleSink->set_pattern("%^[%Y-%m-%d %T.%e] [%l] %v%$");
    sinks.emplace_back(consoleSink);

    auto rotatingFileSink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
        (directory / kDefaultLogFileName).string(),
        10 * 1024 * 1024,   // 10 MiB per file
        5);                 // keep last 5 logs
    rotatingFileSink->set_level(level);
    rotatingFileSink->set_pattern(R"({"ts":"%Y-%m-%dT%T.%e%z", "lvl":"%l", "msg": %v})");
    sinks.emplace_back(rotatingFileSink);

    auto logger = std::make_shared<spdlog::logger>(
        "mosaic_global", begin(sinks), end(sinks));

    logger->set_level(level);
    logger->flush_on(spdlog::level::warn);

    spdlog::register_logger(logger);
    return logger;
}

} // namespace

// Public options struct -------------------------------------------------------
LoggingMiddleware::Options::Options() :
    logDirectory(std::filesystem::current_path() / "logs"),
    logLevel(spdlog::level::info),
    slowRequestThreshold(kDefaultSlowThreshold)
{}

// Constructor -----------------------------------------------------------------
LoggingMiddleware::LoggingMiddleware(const Options& opt) :
    _options(opt)
{
    static std::once_flag initFlag;
    std::call_once(initFlag, [&] {
        _logger = createGlobalLogger(_options.logDirectory, _options.logLevel);
    });

    if (!_logger) {
        // Fallback (should never happen)
        _logger = spdlog::stderr_color_mt("mosaic_fallback");
        _logger->set_level(spdlog::level::warn);
    }
}

// Main call operator ----------------------------------------------------------
void LoggingMiddleware::operator()(http::HttpContext& ctx,
                                   const http::NextMiddleware& next)
{
    using clock = std::chrono::steady_clock;

    const auto start    = clock::now();
    auto       corrIdIt = ctx.request.headers.find("X-Request-ID");
    const bool propagateId = corrIdIt != ctx.request.headers.end();

    std::string correlationId = propagateId ? corrIdIt->second : generateUuid();
    ctx.request.headers.insert_or_assign("X-Request-ID", correlationId);
    ctx.response.headers.insert_or_assign("X-Request-ID", correlationId);

    // Pre-request log (JSON-ish, but stringified)
    _logger->info(
        R"({"event":"request_received","id":"{}","method":"{}","uri":"{}"})",
        correlationId,
        ctx.request.method,
        ctx.request.uri);

    try {
        // Delegate to next middleware / handler
        next(ctx);
    } catch (const std::exception& ex) {
        ctx.response.status = 500;
        ctx.response.body   = "Internal Server Error";

        _logger->error(
            R"({"event":"exception","id":"{}","error":"{}"})",
            correlationId,
            ex.what());
        throw; // Let upstream decide how to recover
    } catch (...) {
        ctx.response.status = 500;
        ctx.response.body   = "Internal Server Error";

        _logger->error(
            R"({"event":"exception","id":"{}","error":"unknown"})",
            correlationId);
        throw;
    }

    const auto elapsedMs =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            clock::now() - start)
            .count();

    if (elapsedMs > _options.slowRequestThreshold.count()) {
        _logger->warn(
            R"({"event":"request_complete","slow":true,"threshold_ms":{},"latency_ms":{},"id":"{}","status":{}})",
            _options.slowRequestThreshold.count(),
            elapsedMs,
            correlationId,
            ctx.response.status);
    } else {
        _logger->info(
            R"({"event":"request_complete","slow":false,"latency_ms":{},"id":"{}","status":{}})",
            elapsedMs,
            correlationId,
            ctx.response.status);
    }
}

// Setters for dynamic control -------------------------------------------------
void LoggingMiddleware::setLogLevel(spdlog::level::level_enum lvl)
{
    std::scoped_lock lk(_mut);
    _logger->set_level(lvl);
}

void LoggingMiddleware::flush()
{
    std::scoped_lock lk(_mut);
    _logger->flush();
}

} // namespace mosaic::middleware