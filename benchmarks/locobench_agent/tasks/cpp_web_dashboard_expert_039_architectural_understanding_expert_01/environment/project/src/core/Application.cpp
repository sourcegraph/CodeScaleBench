#include "core/Application.h"

#include <csignal>
#include <future>
#include <iostream>
#include <thread>
#include <utility>

#include <filesystem>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include "core/Version.h"
#include "core/Config.h"
#include "events/EventBus.h"
#include "network/HttpServer.h"
#include "network/WebSocketHub.h"
#include "plugins/PluginLoader.h"
#include "services/ServiceLocator.h"
#include "services/AuthenticationService.h"
#include "services/NotificationService.h"
#include "services/PaymentService.h"
#include "utils/ScopeGuard.h"

using namespace std::chrono_literals;
namespace fs = std::filesystem;

namespace mosaic::core
{

namespace
{
//--------------------------------------------------------------------------------------------------
//  Process-level signal handling
//--------------------------------------------------------------------------------------------------
std::promise<void>   g_shutdownPromise;
std::atomic_bool     g_isShuttingDown{false};

void onSignal(const int sig) noexcept
{
    if (g_isShuttingDown.exchange(true)) { return; }

    spdlog::warn("Received signal {} – initiating graceful shutdown …", sig);
    g_shutdownPromise.set_value();
}

void installSignalHandlers()
{
    std::signal(SIGINT,  onSignal);
    std::signal(SIGTERM, onSignal);
#ifdef SIGQUIT
    std::signal(SIGQUIT, onSignal);
#endif
}
} // namespace

//--------------------------------------------------------------------------------------------------
//  Application implementation
//--------------------------------------------------------------------------------------------------

Application& Application::instance()
{
    static Application inst;
    return inst;
}

Application::Application() = default;

Application::~Application()
{
    try     { shutdown(); }
    catch   { /* destructor must not throw */ }
}

void Application::init(int argc, char* argv[])
{
    using utils::ScopeGuard;

    installSignalHandlers();

    //
    // Initialize logger ASAP so all subsequent components can use it
    //
    auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    console_sink->set_pattern("[%T][%^%l%$] %v");

    auto logger = std::make_shared<spdlog::logger>("mosaic", console_sink);
    spdlog::register_logger(logger);
    spdlog::set_default_logger(logger);
    spdlog::set_level(spdlog::level::info);

    spdlog::info("MosaicBoard Studio v{}", Version::Long());

    //
    // Parse command-line arguments
    //
    parseCommandLine(argc, argv);

    //
    // Load configuration (will throw on failure)
    //
    Config::load(m_cliOptions.configPath);

    //
    // Bootstrap core subsystems
    //
    bootstrapServices();

    //
    // Discover plug-ins
    //
    loadPlugins();

    //
    // Print some diagnostic information
    //
    spdlog::info("Startup complete – web-dashboard is ready at http://{}:{}",
                 m_httpServer->address(), m_httpServer->port());

    //
    // Keep main thread alive until we are asked to shut down
    //
    auto shutdownFuture = g_shutdownPromise.get_future();
    shutdownFuture.wait();

    //
    // Actual shutdown sequence (in reverse order):
    //
    shutdown();
}

void Application::parseCommandLine(int argc, char* argv[])
{
    // NOTE: In real-world code, we would use CLI11/cxxopts/boost::program_options.
    //       Here we implement a bare-bones parser to avoid extra dependencies.
    //
    m_cliOptions.configPath = "config/studio.json";

    for (int i = 1; i < argc; ++i)
    {
        std::string_view arg = argv[i];
        if (arg == "--config" && i + 1 < argc)
        {
            m_cliOptions.configPath = argv[++i];
        }
        else if (arg == "--help")
        {
            std::cout << "Usage: mosaic_studio [--config path] [--help]\n";
            std::exit(EXIT_SUCCESS);
        }
        else
        {
            spdlog::warn("Unknown command-line argument '{}'", arg);
        }
    }
}

void Application::bootstrapServices()
{
    // Instantiate event bus
    m_eventBus = std::make_shared<events::EventBus>();

    // Start HTTP server
    m_httpServer = std::make_shared<network::HttpServer>(
        Config::get<int>("http.port", 8080),
        Config::get<std::string>("http.address", "0.0.0.0"));

    // Start WebSocket hub
    m_webSocketHub = std::make_shared<network::WebSocketHub>(*m_eventBus);

    // Register core services in the Service Locator
    services::ServiceLocator::registerSingleton(m_eventBus);
    services::ServiceLocator::registerSingleton(m_webSocketHub);

    // Lazy create authentication/notification/payment services
    services::ServiceLocator::registerFactory<services::AuthenticationService>(
        [] { return std::make_shared<services::AuthenticationService>(); });

    services::ServiceLocator::registerFactory<services::NotificationService>(
        [] { return std::make_shared<services::NotificationService>(); });

    services::ServiceLocator::registerFactory<services::PaymentService>(
        [] { return std::make_shared<services::PaymentService>(); });

    //
    // Wire HTTP server routes for the core API
    //
    configureApiEndpoints();

    //
    // Launch IO threads
    //
    m_httpServer->runAsync();
    m_webSocketHub->runAsync();
}

void Application::configureApiEndpoints()
{
    using network::HttpVerb;

    m_httpServer->route(HttpVerb::GET, "/health", [](const network::HttpRequest& req)
    {
        network::HttpResponse res;
        res.status = 200;
        res.body   = R"({"status":"ok"})";
        return res;
    });

    // Additional endpoints registered by other services or plug-ins.
}

void Application::loadPlugins()
{
    const fs::path pluginDir = Config::get<std::string>("plugins.path", "plugins");

    if (!fs::exists(pluginDir))
    {
        spdlog::warn("Plug-in directory '{}' does not exist – skipping discovery", pluginDir.string());
        return;
    }

    m_pluginLoader = std::make_unique<plugins::PluginLoader>(pluginDir, *m_eventBus);

    try
    {
        m_pluginLoader->discover();
        spdlog::info("Loaded {} plug-ins", m_pluginLoader->count());
    }
    catch (const plugins::PluginLoader::DiscoveryError& ex)
    {
        spdlog::error("Failed to discover plug-ins: {}", ex.what());
    }
}

void Application::shutdown()
{
    if (m_isShutdown.exchange(true))
    {
        return; // Already shut down
    }

    spdlog::info("Shutting down MosaicBoard Studio …");

    //
    // 1. Stop accepting new connections
    //
    if (m_httpServer)     { m_httpServer->stop(); }
    if (m_webSocketHub)   { m_webSocketHub->stop(); }

    //
    // 2. Unload plug-ins
    //
    if (m_pluginLoader)   { m_pluginLoader->unloadAll(); }

    //
    // 3. Flush logs & clean up singletons
    //
    services::ServiceLocator::clear();

    spdlog::info("Shutdown complete – goodbye!");
}

} // namespace mosaic::core