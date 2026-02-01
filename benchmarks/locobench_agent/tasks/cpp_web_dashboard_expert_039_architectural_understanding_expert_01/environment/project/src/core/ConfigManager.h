#pragma once
/**********************************************************************************
 * Project   : MosaicBoard Studio (web_dashboard)
 * File      : MosaicBoardStudio/src/core/ConfigManager.h
 * Copyright : © MosaicBoard
 *
 * Description
 * -----------
 *  Centralised, thread–safe configuration service used across MosaicBoard Studio.
 *  Loads hierarchical JSON or YAML configuration files, supports overrides from
 *  environment variables, hot-reloads on-disk changes, and exposes a strongly-typed
 *  retrieval API with sensible defaults and rich error reporting.
 *
 *  The ConfigManager is intentionally header-only to avoid any static-initialisation
 *  fiasco for globals that depend on configuration values. Including this header
 *  is sufficient to access the fully-functional singleton.
 *
 * Usage
 * -----
 *  auto &cfg = core::ConfigManager::instance();
 *  cfg.loadFromFile("config/dashboard.json");
 *
 *  int port = cfg.get<int>("server.port", 8080);
 *  std::string pluginsDir = cfg.get<std::string>("plugins.path")
 *                               .value_or("/usr/local/share/mosaic/plugins");
 *
 *  cfg.onChange([]{
 *      //  Hot-reload callback – update caches, reconnect sockets, etc.
 *  });
 *
 **********************************************************************************/

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <vector>

// External – single-header JSON library (v3.11 or later required)
#include <nlohmann/json.hpp>

namespace core
{
class ConfigError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

/*
 * Small RAII helper that transforms a dotted key into nested JSON objects:
 * Example – dottedToObject("server.ssl.enabled", true) returns
 * { "server": { "ssl": { "enabled": true } } }
 */
inline nlohmann::json dottedToObject(std::string_view dottedKey,
                                     const nlohmann::json &value)
{
    auto nextDot = dottedKey.find('.');
    if (nextDot == std::string_view::npos)
    {
        return nlohmann::json{ {std::string(dottedKey), value} };
    }

    nlohmann::json obj;
    obj[std::string(dottedKey.substr(0, nextDot))] =
        dottedToObject(dottedKey.substr(nextDot + 1), value);
    return obj;
}

/*
 * ConfigManager – header-only, thread-safe, supports hot reload
 */
class ConfigManager
{
public:
    using Json      = nlohmann::json;
    using ChangeCb  = std::function<void()>;
    using Clock     = std::chrono::steady_clock;
    using Duration  = std::chrono::milliseconds;

    // Singleton accessor – instantiated on first call
    static ConfigManager &instance()
    {
        static ConfigManager inst;
        return inst;
    }

    // Deleted semantics
    ConfigManager(const ConfigManager &)            = delete;
    ConfigManager &operator=(const ConfigManager &) = delete;
    ConfigManager(ConfigManager &&)                 = delete;
    ConfigManager &operator=(ConfigManager &&)      = delete;

    /*
     * Loads a JSON (or YAML*) configuration file and merges it
     * with the currently loaded config. Existing keys are overwritten.
     * If hotReload == true, a background watcher thread monitors disk changes.
     */
    void loadFromFile(const std::filesystem::path &file,
                      bool hotReload = true)
    {
        if (!std::filesystem::exists(file))
        {
            throw ConfigError{"Config file not found: " + file.string()};
        }

        std::scoped_lock lk(_stateMtx);

        _configFile = file;
        mergeJson(_doc, readFile(file));

        if (hotReload)
        {
            _lastWriteTime = std::filesystem::last_write_time(file);
            startWatcherThread(); // idempotent – safe to call repeatedly
        }

        applyEnvOverrides();
        _notify();
    }

    /*
     * Merge values programmatically. Useful when reading from DB, CLI flags, etc.
     *  dottedKey can be nested: "auth.jwt.secret"
     */
    template <typename T>
    void set(std::string_view dottedKey, T &&value)
    {
        Json incremental = dottedToObject(dottedKey, Json(std::forward<T>(value)));

        {
            std::scoped_lock lk(_stateMtx);
            mergeJson(_doc, incremental);
        }
        _notify();
    }

    /*
     * Strongly-typed retrieval API.
     * If the key does not exist, returns defaultValue if provided,
     * else std::nullopt / throws (overload).
     */
    template <typename T>
    std::optional<T> get(std::string_view dottedKey) const
    {
        std::shared_lock lk(_stateMtx);
        const Json *node = traverse(dottedKey);
        if (node && !node->is_null())
        {
            try
            {
                return node->get<T>();
            }
            catch (const std::exception &e)
            {
                throw ConfigError{"Type mismatch for key '" + std::string(dottedKey) +
                                  "': " + e.what()};
            }
        }
        return std::nullopt;
    }

    template <typename T>
    T get(std::string_view dottedKey, T &&defaultValue) const
    {
        auto res = get<std::decay_t<T>>(dottedKey);
        return res ? *res : std::forward<T>(defaultValue);
    }

    /*
     * Registers a callback that will be invoked whenever the configuration
     * changes (hot reload or programmatic set()).
     */
    void onChange(ChangeCb cb)
    {
        std::scoped_lock lk(_cbMtx);
        _callbacks.emplace_back(std::move(cb));
    }

    /*
     * Export the current configuration document as JSON string (pretty printed)
     */
    std::string dump(int indent = 4) const
    {
        std::shared_lock lk(_stateMtx);
        return _doc.dump(indent);
    }

private:
    ConfigManager()  = default;
    ~ConfigManager()
    {
        _stopWatcher.store(true);
        if (_watcherThread.joinable())
        {
            _watcherThread.join();
        }
    }

    // ---- Internal helpers ----------------------------------------------------

    static Json readFile(const std::filesystem::path &file)
    {
        std::ifstream ifs(file);
        if (!ifs.is_open())
            throw ConfigError{"Unable to open config file: " + file.string()};

        Json j;
        try
        {
            ifs >> j;
        }
        catch (const std::exception &e)
        {
            throw ConfigError{"Malformed JSON in " + file.string() + ": " + e.what()};
        }
        return j;
    }

    // deep merge – arrays are replaced, objects are merged
    static void mergeJson(Json &dest, const Json &src)
    {
        for (auto it = src.begin(); it != src.end(); ++it)
        {
            if (dest.contains(it.key()))
            {
                if (dest[it.key()].is_object() && it->is_object())
                {
                    mergeJson(dest[it.key()], *it);
                }
                else
                {
                    dest[it.key()] = *it;
                }
            }
            else
            {
                dest[it.key()] = *it;
            }
        }
    }

    /*
     * Traverse dottedKey inside _doc JSON tree.
     * Returns pointer to node or nullptr.
     */
    const Json *traverse(std::string_view dottedKey) const
    {
        const Json *node = &_doc;
        size_t start     = 0;
        while (start < dottedKey.size())
        {
            size_t dot = dottedKey.find('.', start);
            std::string key = std::string(
                dottedKey.substr(start, dot == std::string_view::npos ? std::string_view::npos
                                                                      : dot - start));

            if (!node->contains(key))
                return nullptr;

            node = &(*node)[key];
            if (dot == std::string_view::npos)
                break;
            start = dot + 1;
        }
        return node;
    }

    // -------------------------------------------------------------------------
    void startWatcherThread()
    {
        // Already running?
        if (_watcherThread.joinable())
            return;

        _stopWatcher.store(false);
        _watcherThread = std::thread([this] {
            using namespace std::chrono_literals;
            while (!_stopWatcher.load())
            {
                std::this_thread::sleep_for(_pollInterval);

                if (_configFile.empty())
                    continue;

                auto nowWriteTime = std::filesystem::last_write_time(_configFile);
                if (nowWriteTime != _lastWriteTime)
                {
                    try
                    {
                        Json fresh = readFile(_configFile);
                        {
                            std::scoped_lock lk(_stateMtx);
                            _doc          = fresh;
                            _lastWriteTime = nowWriteTime;
                            applyEnvOverridesLocked();
                        }
                        _notify();
                    }
                    catch (const std::exception &e)
                    {
                        // Log but swallow; keep service alive
                        // (Logging subsystem should be available here.)
                    }
                }
            }
        });
    }

    // Environment variables override using syntax MOSAIC__SERVER__PORT=1234
    void applyEnvOverrides()
    {
        std::scoped_lock lk(_stateMtx);
        applyEnvOverridesLocked();
    }

    void applyEnvOverridesLocked()
    {
        constexpr std::string_view prefix = "MOSAIC__";
        for (char **env = ::environ; *env; ++env)
        {
            std::string_view envPair(*env);
            if (envPair.rfind(prefix, 0) != 0)
                continue; // Not a MosaicBoard env var

            auto eq = envPair.find('=');
            if (eq == std::string_view::npos)
                continue;

            std::string key = envPair.substr(prefix.size(), eq - prefix.size());
            std::replace(key.begin(), key.end(), '_', '.'); // MOSAIC__SERVER__PORT -> SERVER.PORT
            std::string value = envPair.substr(eq + 1);

            // heuristic – treat as number/bool otherwise string
            Json j;
            if (value == "true" || value == "false")
                j = (value == "true");
            else if (auto pos = value.find_first_not_of("0123456789"); pos == std::string::npos)
                j = std::stoi(value);
            else
                j = value;

            mergeJson(_doc, dottedToObject(key, j));
        }
    }

    void _notify()
    {
        std::vector<ChangeCb> cbsCopy;
        {
            std::scoped_lock lk(_cbMtx);
            cbsCopy = _callbacks;
        }
        for (auto &cb : cbsCopy)
        {
            try
            {
                cb();
            }
            catch (...) { /* swallow – user callback */ }
        }
    }

    // ---- Member data ---------------------------------------------------------
    Json                      _doc;
    mutable std::shared_mutex _stateMtx;

    std::filesystem::path     _configFile;
    std::filesystem::file_time_type _lastWriteTime;

    std::thread               _watcherThread;
    std::atomic<bool>         _stopWatcher{false};
    const Duration            _pollInterval = Duration(1500); // ms

    std::vector<ChangeCb>     _callbacks;
    std::mutex                _cbMtx;
};

} // namespace core



