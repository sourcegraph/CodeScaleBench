```cpp
/**
 *  IntraLedger BlogSuite – Configuration Sub-system
 *
 *  File:    src/config.cpp
 *  License: MIT
 *
 *  This unit is responsible for loading, validating, and providing read-only
 *  access to application runtime configuration.  A JSON document stored on
 *  disk is used as the primary source of truth and can be overridden by
 *  environment variables at boot time.  Hot-reloading is supported through a
 *  light-weight polling watcher thread.
 *
 *  The implementation purposefully avoids exposing the underlying JSON
 *  representation to the rest of the codebase, instead offering a strongly-
 *  typed, thread-safe API with helpful error messages on type mismatches.
 */

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "config.hpp"          // Public header (not shown)
#include "logging.hpp"         // In-house logging facade (spdlog-style)
#include "utils/string_utils.hpp" // to_upper(), split(), join() …

#include <nlohmann/json.hpp>   // Header-only JSON library

namespace ilbs    = intraledger::blogsuite;
namespace fs      = std::filesystem;
using     json    = nlohmann::json;

/* ───────────────────────────────────────── Internal helpers ──────────────── */

namespace
{
    /**
     * Flattens a JSON object into a dot-separated key map.
     * Example: { "server": { "port": 8080 } }
     *          -> "server.port" = 8080
     */
    void flatten(const json& node,
                 const std::string& prefix,
                 std::unordered_map<std::string, json>& out)
    {
        if (node.is_object())
        {
            for (auto it = node.cbegin(); it != node.cend(); ++it)
            {
                const std::string newPrefix = prefix.empty()
                                              ? it.key()
                                              : prefix + "." + it.key();
                flatten(it.value(), newPrefix, out);
            }
        }
        else
        {
            out.emplace(prefix, node);
        }
    }

    /**
     * Converts environment variables (e.g., BLOGSUITE_SERVER__PORT) into a
     * dot-notation key (server.port) that matches our flattened map.  Double
     * underscores are considered hierarchy delimiters to avoid conflicts with
     * single underscores frequently used in generic ENV names.
     */
    std::string envToKey(std::string env)
    {
        ilbs::utils::to_lower(env);
        static const std::regex  r { "_{2,}" };
        static const std::string dot = ".";
        env = std::regex_replace(env, r, dot);
        return env;
    }

    /**
     * Reads an entire file into memory; throws on failure.
     */
    std::string readFile(const fs::path& p)
    {
        std::ifstream ifs(p, std::ios::in | std::ios::binary);
        if (!ifs)
        {
            throw std::runtime_error("Unable to open configuration file: " +
                                     p.string());
        }

        std::ostringstream ss;
        ss << ifs.rdbuf();
        return ss.str();
    }
} // namespace

/* ────────────────────────────────────────── Config class ─────────────────── */

namespace intraledger::blogsuite
{
    /* static */ Config& Config::instance()
    {
        static Config singleton;
        return singleton;
    }

    Config::Config() = default;
    Config::~Config() { stopWatcher(); }

    /* --------------------------------------------------------------------- */
    /*  Public API                                                           */
    /* --------------------------------------------------------------------- */

    void Config::initialize(const fs::path& filePath,
                            bool             enableHotReload /* = true */,
                            std::chrono::milliseconds pollRate /* = 1s */)
    {
        std::unique_lock writeLock { m_mutex };

        if (m_initialized)
        {
            throw std::logic_error("Config::initialize() called twice");
        }

        m_configFile   = filePath;
        m_pollInterval = pollRate;

        loadInternal(); // Throws on failure

        if (enableHotReload)
        {
            startWatcher();
        }

        m_initialized = true;
        LOG_INFO("Configuration system initialized ({} keys)",
                 m_flat.count());
    }

    bool Config::isInitialized() const noexcept
    {
        return m_initialized;
    }

    /* --------------- Value retrieval (typed) ----------------------------- */

    template <typename T>
    T Config::get(const std::string& key) const
    {
        std::shared_lock readLock { m_mutex };

        const auto it = m_flat.find(key);
        if (it == m_flat.end())
            throw std::out_of_range("Missing configuration key: " + key);

        try
        {
            return it->second.get<T>();
        }
        catch (const json::exception& ex)
        {
            throw std::runtime_error(
                "Type mismatch for configuration key '" + key +
                "': " + std::string { ex.what() });
        }
    }

    template <typename T>
    T Config::getOr(const std::string& key, T&& defaultValue) const
    {
        std::shared_lock readLock { m_mutex };

        const auto it = m_flat.find(key);
        if (it == m_flat.end())
            return std::forward<T>(defaultValue);

        try
        {
            return it->second.get<T>();
        }
        catch (const json::exception&)
        {
            return std::forward<T>(defaultValue);
        }
    }

    /* --------------- Change Notification --------------------------------- */

    void Config::onReload(ReloadCallback cb)
    {
        std::unique_lock writeLock { m_mutex };
        m_callbacks.emplace_back(std::move(cb));
    }

    /* --------------------------------------------------------------------- */
    /*  Private helpers                                                      */
    /* --------------------------------------------------------------------- */

    void Config::loadInternal()
    {
        const std::string raw = readFile(m_configFile);
        json parsed           = json::parse(raw); // throws on bad syntax

        // Flatten for fast O(1) lookups
        std::unordered_map<std::string, json> flat;
        flatten(parsed, "", flat);

        // Merge environment variable overrides
        for (char** env = ::environ; env && *env; ++env)
        {
            std::string pair(*env);
            const auto  pos = pair.find('=');
            if (pos == std::string::npos) continue;

            std::string name  = pair.substr(0, pos);
            const std::string val   = pair.substr(pos + 1);

            constexpr std::string_view prefix = "BLOGSUITE_";
            if (name.rfind(prefix.data(), 0) != 0) continue; // skip others

            name.erase(0, prefix.size()); // Remove prefix
            const std::string key = envToKey(name);

            flat[key] = val; // string, conversion handled on retrieval
        }

        // Install fresh map atomically
        m_flat.swap(flat);
        m_lastWriteTime = fs::last_write_time(m_configFile);
    }

    void Config::startWatcher()
    {
        m_watchActive = true;
        m_watchThread = std::thread([this]
        {
            for (;;)
            {
                std::this_thread::sleep_for(m_pollInterval);
                if (!m_watchActive.load(std::memory_order_relaxed))
                    break;

                std::error_code ec;
                const auto ts = fs::last_write_time(m_configFile, ec);
                if (ec) continue; // ignore transient FS errors

                if (ts != m_lastWriteTime)
                {
                    try
                    {
                        std::unique_lock lock { m_mutex };
                        loadInternal();
                        lock.unlock(); // Release early before callbacks

                        LOG_INFO("Configuration reloaded from {}",
                                 m_configFile.string());

                        for (auto& cb : m_callbacks)
                        {
                            try { cb(); }
                            catch (const std::exception& ex)
                            {
                                LOG_ERROR("Config reload callback threw: {}",
                                          ex.what());
                            }
                        }
                    }
                    catch (const std::exception& ex)
                    {
                        LOG_ERROR(
                            "Failed to hot-reload configuration: {}", ex.what());
                    }
                }
            }
        });
        m_watchThread.detach(); // becomes a detached background thread
    }

    void Config::stopWatcher()
    {
        m_watchActive = false;
        // Thread is detached; nothing to join.
    }

} // namespace intraledger::blogsuite

/* ───────────────────────────── Template Instantiations ──────────────────── */

#define ILBS_CONFIG_INSTANTIATE(Type) \
    template Type                                      \
    intraledger::blogsuite::Config::get<Type>(         \
        const std::string&) const;                     \
    template Type                                      \
    intraledger::blogsuite::Config::getOr<Type>(       \
        const std::string&, Type&&) const;

// Frequently used types
ILBS_CONFIG_INSTANTIATE(std::string)
ILBS_CONFIG_INSTANTIATE(bool)
ILBS_CONFIG_INSTANTIATE(int)
ILBS_CONFIG_INSTANTIATE(std::int64_t)
ILBS_CONFIG_INSTANTIATE(double)

#undef ILBS_CONFIG_INSTANTIATE
```