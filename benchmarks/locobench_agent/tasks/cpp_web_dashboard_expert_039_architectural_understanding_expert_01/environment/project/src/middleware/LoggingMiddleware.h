#pragma once
/***************************************************************************************************
 * File:    LoggingMiddleware.h
 * Author:  MosaicBoard Studio
 *
 * Brief:
 *  A reusable, production-grade middleware component that transparently logs every incoming
 *  HTTP request/response pair that passes through the server’s routing stack.  The middleware
 *  can be configured at runtime (e.g. log-level, max payload size, header visibility, rotating
 *  sink location, etc.) and is designed to be entirely self-contained – it requires nothing from
 *  the rest of the code-base except a lightweight “RequestContext” data structure that is also
 *  provided below for convenience/testing.
 *
 *  In a real deployment the surrounding framework (MVC / REST layer, etc.) would supply its own
 *  richer RequestContext object; swapping it in is typically as easy as adapting the field names.
 *
 *  The implementation relies on spdlog (https://github.com/gabime/spdlog) and makes sure to fall
 *  back to a console logger if a rotating-file sink cannot be initialised – this guarantees that
 *  diagnostics never silently disappear.
 **************************************************************************************************/
#include <chrono>
#include <exception>
#include <functional>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

#include <spdlog/spdlog.h>
#include <spdlog/async.h>
#include <spdlog/sinks/rotating_file_sink.h>

namespace Mosaic::Middleware
{

/*~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * LoggingMiddleware
 *~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~*/
class LoggingMiddleware
{
public:
    /*---------------------------------------------------------------------------------------------
     * Public types
     *-------------------------------------------------------------------------------------------*/
    enum class Level : uint8_t
    {
        Trace,
        Debug,
        Info,
        Warn,
        Error,
        Critical
    };

    using Headers = std::unordered_map<std::string, std::string>;

    /**
     * A minimal request/response context that can be forwarded through the middleware stack.
     * Swap this out for your framework’s own request context if necessary.
     */
    struct RequestContext
    {
        std::string                                 requestId;      //!< UUID / trace-id
        std::string                                 method;         //!< GET, POST, …
        std::string                                 path;           //!< “/api/v1/users/…”
        Headers                                     headers;        //!< All incoming headers
        std::string                                 body;           //!< Raw request body
        //──────────────────────────────────────────────────────────────────────────────────────────
        int                                         statusCode {0}; //!< HTTP 2xx/4xx/5xx
        std::string                                 responseBody;   //!< Raw payload
        //──────────────────────────────────────────────────────────────────────────────────────────
        std::chrono::steady_clock::time_point       startTime;

        void startTimer() noexcept { startTime = std::chrono::steady_clock::now(); }

        [[nodiscard]] std::chrono::milliseconds elapsed() const noexcept
        {
            return std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - startTime);
        }
    };

    using NextHandler = std::function<void(RequestContext&)>;

    /**
     * Configuration struct that can be passed into the ctor.
     */
    struct Options
    {
        Level       level           {Level::Info};             //!< Log severity threshold
        std::size_t maxPayloadSize  {1024};                    //!< Truncate big bodies
        bool        logHeaders      {false};                   //!< Dump headers as well?
        std::string logFile         {"logs/mosaic_access.log"};//!< Rotating sink
        std::size_t rotationSize    {10 * 1024 * 1024};        //!< 10 MiB
        std::size_t maxFiles        {5};                       //!< #old log-files to keep
    };

    /*---------------------------------------------------------------------------------------------
     * Ctors / dtors
     *-------------------------------------------------------------------------------------------*/
    explicit LoggingMiddleware(Options opts = Options{})
        : m_options(std::move(opts))
    {
        initialiseLogger();
    }

    LoggingMiddleware(const LoggingMiddleware&)            = delete;
    LoggingMiddleware& operator=(const LoggingMiddleware&) = delete;

    /*---------------------------------------------------------------------------------------------
     * Operator() – the actual middleware entry-point
     *-------------------------------------------------------------------------------------------*/
    void operator()(RequestContext& ctx, const NextHandler& next) const
    {
        try
        {
            ctx.startTimer();
            logRequest(ctx);

            next(ctx); // forward to the next piece in the pipeline (controller, …)

            logResponse(ctx);
        }
        catch (const std::exception& ex)
        {
            m_logger->error("Unhandled exception while processing [{} {}]: {}",
                            ctx.method,
                            ctx.path,
                            ex.what());
            throw; // re-throw so that upstream error-handling can do its job
        }
        catch (...)
        {
            m_logger->critical("Unknown failure while processing [{} {}]", ctx.method, ctx.path);
            throw;
        }
    }

    /*---------------------------------------------------------------------------------------------
     * Accessors
     *-------------------------------------------------------------------------------------------*/
    std::shared_ptr<spdlog::logger> logger() const noexcept { return m_logger; }

private:
    /*---------------------------------------------------------------------------------------------
     * Private data
     *-------------------------------------------------------------------------------------------*/
    Options                          m_options;
    std::shared_ptr<spdlog::logger>  m_logger;

    /*---------------------------------------------------------------------------------------------
     * Helpers
     *-------------------------------------------------------------------------------------------*/
    void initialiseLogger()
    {
        try
        {
            if (auto existing = spdlog::get("mosaic.middleware"))
            {
                m_logger = existing;
                return;
            }

            auto sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
                m_options.logFile,
                m_options.rotationSize,
                m_options.maxFiles);

            m_logger = std::make_shared<spdlog::logger>("mosaic.middleware", sink);
            spdlog::initialize_thread_pool(8192, 1);
            m_logger->set_level(translateLevel(m_options.level));
            m_logger->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");

            spdlog::register_logger(m_logger);
            m_logger->info("LoggingMiddleware initialised – logging to '{}'", m_options.logFile);
        }
        catch (const spdlog::spdlog_ex& ex)
        {
            // Fallback: never silently fail, just pipe everything to stderr
            m_logger = spdlog::stderr_color_mt("mosaic.middleware.fallback");
            m_logger->set_level(spdlog::level::info);

            m_logger->warn("Unable to initialise rotating file sink '{}': {}. "
                           "Falling back to stderr.",
                           m_options.logFile,
                           ex.what());
        }
    }

    void logRequest(const RequestContext& ctx) const
    {
        std::ostringstream oss;
        oss << ">> " << ctx.method << " " << ctx.path << " | id=" << ctx.requestId;

        if (m_options.logHeaders && !ctx.headers.empty())
        {
            oss << "\n   • Headers:";
            for (const auto& [k, v] : ctx.headers)
            {
                oss << "\n     - " << k << ": " << v;
            }
        }

        if (!ctx.body.empty())
        {
            oss << "\n   • Payload (" << ctx.body.size() << " B)";
            if (ctx.body.size() <= m_options.maxPayloadSize)
            {
                oss << "\n     \"\"\"\n" << ctx.body << "\n     \"\"\"";
            }
            else
            {
                oss << " – skipped (exceeds " << m_options.maxPayloadSize << " B)";
            }
        }

        m_logger->info("{}", oss.str());
    }

    void logResponse(const RequestContext& ctx) const
    {
        std::ostringstream oss;
        oss << "<< " << ctx.statusCode << " | "
            << ctx.elapsed().count() << " ms | id=" << ctx.requestId;

        if (!ctx.responseBody.empty())
        {
            oss << "\n   • Response (" << ctx.responseBody.size() << " B)";
            if (ctx.responseBody.size() <= m_options.maxPayloadSize)
            {
                oss << "\n     \"\"\"\n" << ctx.responseBody << "\n     \"\"\"";
            }
            else
            {
                oss << " – skipped (exceeds " << m_options.maxPayloadSize << " B)";
            }
        }

        m_logger->info("{}", oss.str());
    }

    static constexpr spdlog::level::level_enum translateLevel(Level lvl) noexcept
    {
        switch (lvl)
        {
            case Level::Trace:    return spdlog::level::trace;
            case Level::Debug:    return spdlog::level::debug;
            case Level::Info:     return spdlog::level::info;
            case Level::Warn:     return spdlog::level::warn;
            case Level::Error:    return spdlog::level::err;
            case Level::Critical: return spdlog::level::critical;
            default:              return spdlog::level::info;
        }
    }
};

} // namespace Mosaic::Middleware