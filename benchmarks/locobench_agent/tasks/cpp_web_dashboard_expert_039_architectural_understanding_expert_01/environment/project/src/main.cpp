```cpp
/**
 *  MosaicBoard Studio – main entry point
 *
 *  File:        src/main.cpp
 *  Description: Bootstraps the MosaicBoard Studio application, including:
 *                 • CLI argument parsing
 *                 • Configuration loading (JSON)
 *                 • Logging initialisation (spdlog)
 *                 • Dynamic plugin discovery & loading
 *                 • Event-bus instantiation
 *                 • HTTP/WebSocket server boot (Crow)
 *                 • Graceful shutdown handling
 *
 *  Build flags (example):
 *      g++ -std=c++17 -pthread -ldl -lssl -lcrypto \
 *          -I third_party/spdlog/include \
 *          -I third_party/crow \
 *          src/main.cpp -o mosaicboard
 */

#include <crow_all.h>            // Header-only web framework
#include <spdlog/spdlog.h>       // Header-only logging
#include <spdlog/sinks/rotating_file_sink.h>
#include <nlohmann/json.hpp>     // Header-only JSON library
#include <filesystem>
#include <fstream>
#include <unordered_map>
#include <csignal>
#include <dlfcn.h>               // POSIX dynamic loading
#include <atomic>
#include <chrono>
#include <optional>
#include <mutex>

namespace fs = std::filesystem;
using json = nlohmann::json;

/* ──────────────────────────────────────────────────────────────────────────── */
/*                              Utility helpers                                */
/* ──────────────────────────────────────────────────────────────────────────── */

static constexpr auto DEFAULT_CONFIG_FILE  = "config.json";
static constexpr auto DEFAULT_PLUGINS_DIR  = "plugins";
static constexpr auto DEFAULT_HTTP_ADDRESS = "0.0.0.0";
static constexpr uint16_t DEFAULT_HTTP_PORT = 8080;


/* ──────────────────────────────────────────────────────────────────────────── */
/*                                  Config                                     */
/* ──────────────────────────────────────────────────────────────────────────── */

struct AppConfig
{
    std::string  httpAddress { DEFAULT_HTTP_ADDRESS };
    std::uint16_t httpPort   { DEFAULT_HTTP_PORT };
    fs::path     pluginsDir  { DEFAULT_PLUGINS_DIR };
    std::string  logFile     { "mosaicboard.log"  };
    std::size_t  logFileSize { 10 * 1024 * 1024 }; // 10 MB
    std::size_t  logFiles    { 5 };

    static AppConfig load(const std::string& filePath)
    {
        AppConfig cfg;
        if (!fs::exists(filePath))
        {
            spdlog::warn("Config file '{}' not found. Using defaults.", filePath);
            return cfg;
        }

        std::ifstream in(filePath);
        if (!in.good())
            throw std::runtime_error("Unable to read config file: " + filePath);

        json j;
        in >> j;

        if (j.contains("server"))
        {
            auto server = j["server"];
            cfg.httpAddress = server.value("address", DEFAULT_HTTP_ADDRESS);
            cfg.httpPort    = server.value("port", DEFAULT_HTTP_PORT);
        }

        cfg.pluginsDir  = j.value("plugins_dir", DEFAULT_PLUGINS_DIR);
        cfg.logFile     = j.value("log_file", cfg.logFile);
        cfg.logFileSize = j.value("log_file_size", cfg.logFileSize);
        cfg.logFiles    = j.value("log_files", cfg.logFiles);

        return cfg;
    }
};


/* ──────────────────────────────────────────────────────────────────────────── */
/*                                  EventBus                                   */
/*        (simple in-process pub/sub mechanics – threadsafe, copyable)         */
/* ──────────────────────────────────────────────────────────────────────────── */

class EventBus
{
public:
    using Topic     = std::string;
    using Payload   = json;
    using Callback  = std::function<void(const Payload&)>;

    void subscribe(const Topic& t, Callback cb)
    {
        std::lock_guard lg{ _mx };
        _subscribers[t].push_back(std::move(cb));
    }

    void publish(const Topic& t, const Payload& p) const
    {
        std::vector<Callback> cbs;
        {
            std::lock_guard lg{ _mx };
            if (auto found = _subscribers.find(t); found != _subscribers.end())
                cbs = found->second;
        }
        for (auto& cb : cbs)
        {
            try       { cb(p); }
            catch (...) { spdlog::error("EventBus callback on topic '{}' failed", t); }
        }
    }

private:
    mutable std::mutex _mx;
    std::unordered_map<Topic, std::vector<Callback>> _subscribers;
};


/* ──────────────────────────────────────────────────────────────────────────── */
/*                              Plugin Manager                                 */
/* ──────────────────────────────────────────────────────────────────────────── */

struct TileInfo
{
    std::string id;
    std::string name;
    std::string version;
    json        meta;
};

/**
 *  The shared-lib side is expected to expose a "C" factory symbol with the
 *  signature:
 *
 *      extern "C"
 *      bool registerTile(std::function<void(const TileInfo&, std::function<json(const json&)>)>);
 *
 *  The function receives a callback that the plugin uses to register itself.
 */
using TileCallback    = std::function<json(const json&)>;
using RegisterTileSig = bool(*)(std::function<void(const TileInfo&, TileCallback)>);

class PluginManager
{
public:
    explicit PluginManager(EventBus& bus)
    : _bus(bus)
    {}

    void discover(const fs::path& dir)
    {
        if (!fs::exists(dir) || !fs::is_directory(dir))
        {
            spdlog::warn("Plugin directory '{}' not found.", dir.string());
            return;
        }

        for (auto& entry : fs::directory_iterator(dir))
        {
            if (!entry.is_regular_file()) continue;

            auto path = entry.path();
            if (path.extension() != ".so" && path.extension() != ".dylib")
                continue; // only loading Unix-like shared libraries

            try { loadLibrary(path); }
            catch (const std::exception& ex)
            {
                spdlog::error("Plugin load failed ({}): {}", path.string(), ex.what());
            }
        }
    }

    std::vector<TileInfo> listTiles() const
    {
        std::lock_guard lg{ _mx };
        std::vector<TileInfo> v;
        v.reserve(_tiles.size());
        for (auto& [id, pair] : _tiles) v.push_back(pair.first);
        return v;
    }

    std::optional<json> invokeTile(const std::string& id, const json& payload)
    {
        std::lock_guard lg{ _mx };
        auto it = _tiles.find(id);
        if (it == _tiles.end()) return std::nullopt;

        return it->second.second(payload);
    }

    ~PluginManager()
    {
        for (auto handle : _handles) dlclose(handle);
    }

private:
    void loadLibrary(const fs::path& path)
    {
        void* handle = dlopen(path.c_str(), RTLD_NOW);
        if (!handle)
            throw std::runtime_error(dlerror());

        auto reg = (RegisterTileSig)dlsym(handle, "registerTile");
        if (!reg)
        {
            dlclose(handle);
            spdlog::warn("Shared library {} missing registerTile symbol.", path.string());
            return;
        }

        bool ok = reg([this](const TileInfo& info, TileCallback cb) {
            std::lock_guard lg{ _mx };
            if (_tiles.contains(info.id))
                throw std::runtime_error("Duplicate tile id: " + info.id);
            _tiles.emplace(info.id, std::make_pair(info, std::move(cb)));
            spdlog::info("Tile registered: {} (v{})", info.name, info.version);
            _bus.publish("tiles/registered", { {"id", info.id}, {"name", info.name} });
        });

        if (!ok)
            throw std::runtime_error("Plugin registration reported failure.");

        _handles.push_back(handle);
        spdlog::info("Loaded plugin '{}'", path.filename().string());
    }

    EventBus& _bus;
    mutable std::mutex _mx;

    std::unordered_map<std::string, std::pair<TileInfo, TileCallback>> _tiles;
    std::vector<void*> _handles;
};


/* ──────────────────────────────────────────────────────────────────────────── */
/*                              Application Core                               */
/* ──────────────────────────────────────────────────────────────────────────── */

class MosaicBoardApp
{
public:
    MosaicBoardApp(AppConfig cfg)
      : _cfg(std::move(cfg)),
        _logger(initLogger(_cfg)),
        _pluginManager(_bus)
    {}

    void run()
    {
        spdlog::info("Booting MosaicBoard Studio…");

        // Discover plugins
        _pluginManager.discover(_cfg.pluginsDir);
        spdlog::info("Discovered {} tiles", _pluginManager.listTiles().size());

        // Wire internal event bus handlers, example:
        _bus.subscribe("tiles/registered", [](const json& payload){
            spdlog::info("Event: new tile registered -> {}", payload.dump());
        });

        // Build REST API
        initRoutes();

        // Signal handling for graceful shutdown
        std::signal(SIGINT,  signalHandler);
        std::signal(SIGTERM, signalHandler);

        // Start server (blocking call)
        _server.bindaddr(_cfg.httpAddress)
               .port(_cfg.httpPort)
               .multithreaded()
               .run();
    }

private:
    /* Logging ----------------------------------------------------------------*/

    static std::shared_ptr<spdlog::logger> initLogger(const AppConfig& cfg)
    {
        try
        {
            auto sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
                cfg.logFile, cfg.logFileSize, cfg.logFiles
            );
            auto logger = std::make_shared<spdlog::logger>("MosaicBoard", sink);
            logger->set_pattern("[%Y-%m-%d %H:%M:%S] [%l] %v");
            spdlog::set_default_logger(logger);
            spdlog::flush_on(spdlog::level::info);
            return logger;
        }
        catch (const spdlog::spdlog_ex& ex)
        {
            throw std::runtime_error("Logger init failed: " + std::string(ex.what()));
        }
    }

    /* REST/API routes --------------------------------------------------------*/

    void initRoutes()
    {
        // Health
        CROW_ROUTE(_server, "/api/v1/health")
        .methods("GET"_method)
        ([]{
            json payload = { {"status", "ok"}, {"ts", std::chrono::system_clock::to_time_t(std::chrono::system_clock::now())} };
            return crow::response{ payload.dump() };
        });

        // List tiles
        CROW_ROUTE(_server, "/api/v1/tiles")
        .methods("GET"_method)
        ([this]{
            json arr = json::array();
            for (auto& t : _pluginManager.listTiles()) {
                arr.push_back({ {"id", t.id}, {"name", t.name}, {"version", t.version}, {"meta", t.meta} });
            }
            return crow::response{ arr.dump() };
        });

        // Invoke tile action
        CROW_ROUTE(_server, "/api/v1/tiles/<string>/action")
        .methods("POST"_method)
        ([this](const std::string& id, const crow::request& req){
            try
            {
                auto payload = json::parse(req.body.empty() ? "{}" : req.body);
                auto res     = _pluginManager.invokeTile(id, payload);
                if (!res) return crow::response(404, "Tile not found");

                return crow::response{ res->dump() };
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Tile invocation failed: {}", ex.what());
                return crow::response(500, "Internal server error");
            }
        });

        // WebSocket endpoint for real-time events
        CROW_ROUTE(_server, "/ws")
        .websocket()
        .onopen([this](crow::websocket::connection& conn){
            _wsConnections.insert(&conn);
            spdlog::info("WebSocket client connected ({} connections total)", _wsConnections.size());
        })
        .onclose([this](crow::websocket::connection& conn, const std::string& reason){
            _wsConnections.erase(&conn);
            spdlog::info("WebSocket client disconnected: {}", reason);
        })
        .onmessage([this](crow::websocket::connection& conn, const std::string& msg, bool is_bin){
            if (is_bin) return;
            try {
                auto j = json::parse(msg);
                if (j.contains("subscribe"))
                {
                    std::string topic = j["subscribe"];
                    _bus.subscribe(topic, [&conn](const json& event){
                        if (conn.is_open())
                            conn.send_text(event.dump());
                    });
                }
            } catch(...) {}
        });
    }

    /* Static signal handler --------------------------------------------------*/

    static void signalHandler(int sig)
    {
        if (sig == SIGINT || sig == SIGTERM)
        {
            spdlog::info("Shutdown requested (signal {}).", sig);
            _shutdownRequested.store(true);
        }
    }

private:
    AppConfig                                _cfg;
    std::shared_ptr<spdlog::logger>          _logger;
    EventBus                                 _bus;
    PluginManager                            _pluginManager;
    crow::SimpleApp                          _server;

    std::unordered_set<crow::websocket::connection*> _wsConnections;

    static inline std::atomic<bool> _shutdownRequested{false};
};


/* ──────────────────────────────────────────────────────────────────────────── */
/*                                 main()                                      */
/* ──────────────────────────────────────────────────────────────────────────── */

int main(int argc, char* argv[])
{
    // Simple CLI arg parsing
    std::string configFile = DEFAULT_CONFIG_FILE;

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if ((arg == "-c" || arg == "--config") && i + 1 < argc)
        {
            configFile = argv[++i];
        }
        else if (arg == "-h" || arg == "--help")
        {
            fmt::print("Usage: {} [-c|--config <file>]\n", argv[0]);
            return 0;
        }
    }

    try
    {
        auto cfg = AppConfig::load(configFile);
        MosaicBoardApp app(std::move(cfg));
        app.run();
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("Fatal: {}", ex.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
```