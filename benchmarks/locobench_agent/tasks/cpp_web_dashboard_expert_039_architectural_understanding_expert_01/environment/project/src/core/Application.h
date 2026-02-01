#pragma once
/**
 *  File:        Application.h
 *  Project:     MosaicBoard Studio – Web Dashboard
 *
 *  Description:
 *      Central façade that wires together subsystems such as configuration,
 *      logging, plug-in discovery, HTTP/API services, WebSocket event bus,
 *      and graceful shutdown.  Each dashboard session owns an Application
 *      instance that supervises the life-cycle of the runtime.
 *
 *      The interface is header-only to keep compile-time visibility for
 *      unit tests while deferring expensive implementation details into
 *      the corresponding *.cpp TU.
 *
 *  Copyright:
 *      © 2024 MosaicBoard Studio (BSD-3-Clause)
 */

#include <chrono>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include "core/Export.h"           // Contains MOSAIC_CORE_API macro
#include "core/Version.h"          // SemVer struct
#include "infra/Logging.h"         // Logger interface
#include "infra/Signals.h"         // Signal/Slot utility
#include "services/Error.h"        // Domain errors/exceptions
#include "services/Shutdown.h"     // Shutdown hooks

// Forward declarations – reduce compile-time coupling
namespace mosaic::plugins {
    class IPlugin;
    class PluginManager;
}  // namespace mosaic::plugins

namespace mosaic::io {
    class ConfigRepository;
}  // namespace mosaic::io

namespace mosaic::net {
    class IHttpServer;
    class IWebSocketHub;
}  // namespace mosaic::net

// ---------------------------------------------------------------------------
//  Application – public contract
// ---------------------------------------------------------------------------
namespace mosaic::core {

class MOSAIC_CORE_API Application final : public std::enable_shared_from_this<Application>
{
public:
    using Clock          = std::chrono::steady_clock;
    using Millis         = std::chrono::milliseconds;
    using UptimeCallback = std::function<void(std::chrono::seconds)>;

    enum class State : std::uint8_t
    {
        Created,
        Initializing,
        Running,
        ShuttingDown,
        Terminated
    };

    struct Options
    {
        std::string                 name           = "MosaicBoard Studio";
        std::string                 userHomeDir    = {};
        bool                        headless       = false;
        std::uint16_t               httpPort       = 8080;
        std::uint16_t               wsPort         = 8081;
        std::shared_ptr<io::ConfigRepository> configRepo;  // optional
        std::shared_ptr<infra::ILogger>        logger;      // optional

        // Sanity check & default injection
        void validate();
    };

    // -----------------------------------------------------------------------
    //  Creation helpers
    // -----------------------------------------------------------------------

    // Factory: ensures shared_ptr semantics
    static std::shared_ptr<Application> create(Options opts);

    // Deleted copy ‑ only move (unique supervisors)
    Application(const Application&)            = delete;
    Application& operator=(const Application&) = delete;
    Application(Application&&)                 = delete;
    Application& operator=(Application&&)      = delete;

    ~Application() noexcept;

    // -----------------------------------------------------------------------
    //  Life-cycle
    // -----------------------------------------------------------------------
    void init();      // Allocates subsystems, loads plugins, prepares network
    void run();       // Blocking run-loop until shutdown() is requested
    void shutdown();  // Asynchronous request – non-blocking

    // Returns when state >= Terminated
    void wait() const;

    // -----------------------------------------------------------------------
    //  Observability
    // -----------------------------------------------------------------------
    [[nodiscard]] State          state() const noexcept;
    [[nodiscard]] std::string    name()  const noexcept;
    [[nodiscard]] Version        version() const noexcept;
    [[nodiscard]] Millis         uptime() const noexcept;
    [[nodiscard]] bool           headless() const noexcept { return m_opts.headless; }

    // Expose infra for higher-level components – use w_ptr to avoid cycles
    [[nodiscard]] std::weak_ptr<net::IWebSocketHub>  eventBus()   const noexcept;
    [[nodiscard]] std::weak_ptr<plugins::PluginManager> pluginManager() const noexcept;
    [[nodiscard]] std::weak_ptr<infra::ILogger>         logger() const noexcept;

    // Allow subscription to significant events
    infra::Signal<State /*from*/, State /*to*/>& onStateChanged() noexcept { return m_stateChanged; }

    // External modules can register a function that will be called every
    // second while the app is running.  Use for statistics collection.
    void setUptimeCallback(UptimeCallback cb);

private:
    explicit Application(Options opts);

    // Internal helpers
    void runLoop_();
    void failFast_(const std::exception& ex) noexcept;
    void transitionState_(State next);
    void installSignalHandlers_();
    void loadPlugins_();
    void startNetworkServices_();
    void stopNetworkServices_();

    // --------------------------------------------------------------------
    //  Data members
    // --------------------------------------------------------------------
    Options m_opts;

    std::atomic<State>           m_state{State::Created};
    Clock::time_point            m_startTime{};
    mutable std::mutex           m_stateMutex;
    mutable std::condition_variable m_stateCv;

    std::thread                  m_runtimeThread;   // main run loop

    // Subsystems (constructed in init)
    std::shared_ptr<infra::ILogger>        m_logger;
    std::shared_ptr<plugins::PluginManager> m_pluginManager;
    std::shared_ptr<net::IHttpServer>       m_httpServer;
    std::shared_ptr<net::IWebSocketHub>     m_wsHub;

    UptimeCallback               m_uptimeCb;

    infra::Signal<State, State>  m_stateChanged;
};

// ---------------------------------------------------------------------------
//  Inline definitions
// ---------------------------------------------------------------------------
inline Application::State Application::state() const noexcept
{
    return m_state.load(std::memory_order_relaxed);
}

inline std::string Application::name() const noexcept
{
    return m_opts.name;
}

inline Version Application::version() const noexcept
{
    return core::currentVersion();
}

inline Application::Millis Application::uptime() const noexcept
{
    using namespace std::chrono;
    if (state() == State::Created) { return Millis{0}; }
    return duration_cast<Millis>(Clock::now() - m_startTime);
}

inline std::weak_ptr<net::IWebSocketHub> Application::eventBus() const noexcept
{
    return m_wsHub;
}

inline std::weak_ptr<plugins::PluginManager> Application::pluginManager() const noexcept
{
    return m_pluginManager;
}

inline std::weak_ptr<infra::ILogger> Application::logger() const noexcept
{
    return m_logger;
}

}  // namespace mosaic::core