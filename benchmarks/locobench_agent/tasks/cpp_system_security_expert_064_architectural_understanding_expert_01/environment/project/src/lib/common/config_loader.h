#pragma once
/***************************************************************************************************
 *  File:        config_loader.h
 *  Project:     FortiLedger360 Enterprise Security Suite – System Security (common lib)
 *
 *  Description:
 *      Thread-safe, production-grade configuration loader with hot-reload capability.  The loader
 *      consumes JSON (default), but can be extended to YAML/TOML by specializing the Adapter
 *      wrapper (see `detail::IParser`).  A global singleton is provided for convenience, however
 *      multiple local instances are fully supported and encouraged for unit-testing.
 *
 *  Usage:
 *      auto& cfg = fl360::common::ConfigLoader::instance();
 *      std::string listen_addr = cfg.get_or<std::string>("server.listen", "0.0.0.0");
 *
 *  Features:
 *      • Atomic hot-reload (polling-based, avoids costly inotify/kqueue abstractions)
 *      • Dot-notation lookups (ex: `"orchestration.grpc.timeout_secs"`)
 *      • Environment-variable override (ex: `FL360__ORCHESTRATION__GRPC__TIMEOUT_SECS=90`)
 *      • Type-safe getters with descriptive exception messages
 *      • Header-only; pay-as-you-use compilation via inline definitions
 *
 *  Copyright:
 *      © 2023-2024 FortiLedger360, Inc.  All Rights Reserved.
 **************************************************************************************************/

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include <nlohmann/json.hpp>   // Single-header, MIT-licensed – pulled in via vcpkg/CPM.

//--------------------------------------------------------------------------------------------------
//  Namespace root
//--------------------------------------------------------------------------------------------------
namespace fl360::common {

//--------------------------------------------------------------------------------------------------
//  Constants & helpers
//--------------------------------------------------------------------------------------------------
static constexpr char kEnvDelim       = '__';      // Flattened env var delimiter (“__” => '.')
static constexpr int  kDefaultPollMs  = 5'000;     // 5 seconds

//--------------------------------------------------------------------------------------------------
//  Exception hierarchy
//--------------------------------------------------------------------------------------------------
class ConfigError final : public std::runtime_error
{
public:
    explicit ConfigError(std::string_view msg)
        : std::runtime_error{std::string{msg}} {}
};

//--------------------------------------------------------------------------------------------------
//  Option bag
//--------------------------------------------------------------------------------------------------
struct ConfigLoaderOptions
{
    bool                        enable_hot_reload {true};                  // Watch for FS changes
    std::chrono::milliseconds   poll_interval    {kDefaultPollMs};         // Hot-reload cadence
    bool                        honor_env_vars   {true};                   // Apply env overrides
};

//--------------------------------------------------------------------------------------------------
//  Parser abstraction – allows for future YAML/TOML support without touching public surface.
//--------------------------------------------------------------------------------------------------
namespace detail {

struct IParser
{
    virtual ~IParser() = default;
    virtual nlohmann::json parse(std::istream&)                       = 0;
    virtual std::string    media_type() const                         = 0;
};

class JsonParser final : public IParser
{
public:
    nlohmann::json parse(std::istream& in) override
    {
        return nlohmann::json::parse(in, /*callback*/ nullptr, /*allow_exceptions*/ true,
                                     /*ignore_comments*/ true);
    }
    std::string media_type() const override { return "application/json"; }
};

} // namespace detail

//--------------------------------------------------------------------------------------------------
//  ConfigLoader – main façade
//--------------------------------------------------------------------------------------------------
class ConfigLoader
{
public:
    using json = nlohmann::json;

    // Construct from file-system path.  Throws ConfigError on failure.
    explicit ConfigLoader(const std::filesystem::path& cfg_file,
                          ConfigLoaderOptions             opts = {},
                          std::unique_ptr<detail::IParser> parser = std::make_unique<detail::JsonParser>())
        : cfg_path_{cfg_file}
        , opts_    {std::move(opts)}
        , parser_  {std::move(parser)}
    {
        if (!std::filesystem::exists(cfg_path_))
            throw ConfigError{"ConfigLoader: configuration file does not exist: " + cfg_path_.string()};

        load_from_disk_locked();    // Initial sync

        if (opts_.enable_hot_reload)
            watcher_thread_ = std::thread(&ConfigLoader::hot_reload_loop_, this);
    }

    // Non-copyable, non-movable
    ConfigLoader(const ConfigLoader&)            = delete;
    ConfigLoader& operator=(const ConfigLoader&) = delete;
    ConfigLoader(ConfigLoader&&)                 = delete;
    ConfigLoader& operator=(ConfigLoader&&)      = delete;

    ~ConfigLoader()
    {
        stop_requested_ = true;
        if (watcher_thread_.joinable()) watcher_thread_.join();
    }

    //------------------------------------------------------------------------------
    //  Query helpers
    //------------------------------------------------------------------------------
    template<typename T>
    T get(const std::string& dotted_path) const
    {
        std::shared_lock lk{rw_};
        const json* node = navigate_(dotted_path, doc_);
        if (!node)
            throw ConfigError{"ConfigLoader: key not found – '" + dotted_path + '\''};
        try {
            return node->get<T>();
        } catch (const std::exception& e) {
            throw ConfigError{"ConfigLoader: type mismatch at '" + dotted_path + "': " + std::string{e.what()}};
        }
    }

    template<typename T>
    T get_or(const std::string& dotted_path, T fallback) const noexcept
    {
        try { return get<T>(dotted_path); }
        catch (...) { return fallback; }
    }

    bool contains(const std::string& dotted_path) const
    {
        std::shared_lock lk{rw_};
        return navigate_(dotted_path, doc_) != nullptr;
    }

    std::chrono::system_clock::time_point last_loaded_at() const noexcept
    {
        std::shared_lock lk{rw_};
        return last_loaded_;
    }

    //------------------------------------------------------------------------------
    //  Singleton access – created on first use.  The location of the default
    //  configuration file is platform-specific; for Linux we default to:
    //      /etc/fl360/fl360.conf
    //------------------------------------------------------------------------------
    static ConfigLoader& instance()
    {
        std::call_once(init_flag_, [] {
            const char* env = std::getenv("FL360_CONFIG_PATH");
            std::filesystem::path cfg = env ? env : "/etc/fl360/fl360.conf";
            instance_.reset(new ConfigLoader{cfg});
        });
        return *instance_;
    }

    //------------------------------------------------------------------------------
    //  Manual reload (e.g., triggered by admin endpoint)
    //------------------------------------------------------------------------------
    void reload()
    {
        std::unique_lock lk{rw_};
        load_from_disk_locked();
    }

private:
    //------------------------------------------------------------------------------
    //  Private helpers
    //------------------------------------------------------------------------------
    void hot_reload_loop_()
    {
        while (!stop_requested_) {
            std::this_thread::sleep_for(opts_.poll_interval);
            try {
                auto ts = std::filesystem::last_write_time(cfg_path_);
                std::unique_lock lk{rw_};          // Exclusive lock ONLY when we reload
                if (ts > fs_timestamp_)            // file changed?
                    load_from_disk_locked();
            } catch (const std::exception& e) {
                // Swallow to keep thread alive but log warnings (real impl would forward to logger)
            }
        }
    }

    // Load configuration file (caller must hold unique_lock)
    void load_from_disk_locked()
    {
        std::ifstream in{cfg_path_};
        if (!in.is_open())
            throw ConfigError{"ConfigLoader: unable to open config file: " + cfg_path_.string()};

        json root = parser_->parse(in);

        if (opts_.honor_env_vars)
            apply_env_overrides_(root);

        doc_          = std::move(root);
        last_loaded_  = std::chrono::system_clock::now();
        fs_timestamp_ = std::filesystem::last_write_time(cfg_path_);
    }

    // Split dotted path and walk JSON tree.  Returns nullptr on missing keys.
    static const json* navigate_(const std::string& dotted, const json& root)
    {
        const json* node = &root;
        size_t pos = 0, dot;
        while (node && (dot = dotted.find('.', pos)) != std::string::npos) {
            std::string_view key{&dotted[pos], dot - pos};
            node = node->contains(key) ? &(*node)[key] : nullptr;
            pos  = dot + 1;
        }
        if (!node) return nullptr;

        std::string_view last_key{&dotted[pos], dotted.size() - pos};
        return node->contains(last_key) ? &(*node)[last_key] : nullptr;
    }

    // ENV override: FL360__FOO__BAR maps to json path "foo.bar"
    static std::optional<std::string> match_env_prefix_(std::string_view full)
    {
        constexpr std::string_view kPrefix = "FL360__";
        if (full.rfind(kPrefix, 0) != 0) return std::nullopt;
        return std::string{full.substr(kPrefix.size())};
    }

    static std::vector<std::string> split_(std::string_view src, std::string_view delim)
    {
        std::vector<std::string> out;
        size_t pos = 0;
        while (true) {
            size_t idx = src.find(delim, pos);
            out.emplace_back(src.substr(pos, idx - pos));
            if (idx == std::string_view::npos) break;
            pos = idx + delim.size();
        }
        return out;
    }

    static void assign_raw_(json& root, const std::string& dotted_key, const std::string& raw_val)
    {
        auto parts = split_(dotted_key, ".");
        json* node = &root;
        for (size_t i = 0; i < parts.size(); ++i) {
            const auto& k = parts[i];
            if (i + 1 == parts.size()) {
                // Leaf – attempt to deserialize as JSON; fallback to string
                try {
                    node->operator[](k) = json::parse(raw_val);
                } catch (...) {
                    node->operator[](k) = raw_val;
                }
            } else {
                node = &((*node)[k]);  // auto-creates object nodes
            }
        }
    }

    static void apply_env_overrides_(json& root)
    {
        for (char **env = environ; *env; ++env) {
            std::string_view entry{*env};
            size_t eq = entry.find('=');
            if (eq == std::string_view::npos) continue;
            std::string_view k = entry.substr(0, eq);
            auto key = match_env_prefix_(k);
            if (!key) continue;

            std::string dotted = *key;
            for (auto& c : dotted) if (c == kEnvDelim) c = '.';

            std::string raw_val = std::string{entry.substr(eq + 1)};
            assign_raw_(root, dotted, raw_val);
        }
    }

private:
    // User-provided
    std::filesystem::path         cfg_path_;
    ConfigLoaderOptions           opts_;
    std::unique_ptr<detail::IParser> parser_;

    // State
    mutable std::shared_mutex     rw_;
    json                          doc_;
    std::chrono::system_clock::time_point last_loaded_{};
    std::filesystem::file_time_type       fs_timestamp_{};
    std::thread                   watcher_thread_;
    std::atomic_bool              stop_requested_{false};

    // Singleton
    static std::once_flag                         init_flag_;
    static std::unique_ptr<ConfigLoader>          instance_;
};

//--------------------------------------------------------------------------------------------------
//  Static member definitions
//--------------------------------------------------------------------------------------------------
inline std::once_flag ConfigLoader::init_flag_;
inline std::unique_ptr<ConfigLoader> ConfigLoader::instance_ = nullptr;

} // namespace fl360::common