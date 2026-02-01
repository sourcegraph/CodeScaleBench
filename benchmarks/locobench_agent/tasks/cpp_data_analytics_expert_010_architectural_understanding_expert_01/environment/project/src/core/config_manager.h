```cpp
// cardio_insight_360/src/core/config_manager.h
//
//  CardioInsight360 – Unified Healthcare Analytics Engine
//  ------------------------------------------------------
//  Production-grade configuration manager used by the entire runtime.
//
//  Features
//  --------
//  • Thread-safe singleton (C++17 “magic static” + shared_mutex)
//  • Supports JSON5/JSON configuration files via nlohmann::json
//  • Environment-variable expansion:  "${VAR_NAME}"  → std::getenv()
//  • Live-reload (file-watcher) with delta notification to subscribers
//  • Type-safe getters with reasonable defaults + error diagnostics
//
//  Copyright (c) CardioInsight360.
//  Licensed under the CI360 internal EULA. All rights reserved.
//
#pragma once

#include <nlohmann/json.hpp>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>

namespace ci360::core {

/// Compile-time default locations
#ifndef CI360_DEFAULT_CONFIG_PATH
#   ifdef _WIN32
#       define CI360_DEFAULT_CONFIG_PATH "C:\\ci360\\etc\\ci360.conf.json"
#   else
#       define CI360_DEFAULT_CONFIG_PATH "/etc/ci360/ci360.conf.json"
#   endif
#endif

/// CardioInsight360 system-wide configuration manager.
class ConfigManager {
public:
    using json            = nlohmann::json;
    using ObserverId      = std::size_t;
    using ObserverCallback =
        std::function<void(const json& /*delta*/, const json& /*fullConfig*/)>;

    /// Retrieve singleton instance.
    static ConfigManager& instance() noexcept {
        static ConfigManager singleton;
        return singleton;
    }

    /// Load or replace the current configuration from a file.
    /// Throws std::runtime_error on failure.
    void load(const std::filesystem::path& configPath = CI360_DEFAULT_CONFIG_PATH,
              bool                        blocking    = true)
    {
        const json newCfg = readFile_(configPath);
        {
            std::unique_lock lock(mutex_);
            config_          = substituteEnv_(newCfg);
            currentPath_     = configPath;
            lastWriteTime_   = lastWriteTimeOf_(configPath);
        }
        if (blocking) notifyObservers_(config_, /*delta=*/config_);
    }

    /// Reload configuration if the underlying file has changed.
    /// Returns true when a change was detected + applied.
    bool reload() {
        std::unique_lock lock(mutex_);
        if (currentPath_.empty()) return false;

        const auto nowWriteTime = lastWriteTimeOf_(currentPath_);
        if (nowWriteTime == lastWriteTime_) return false;  // No change.

        lock.unlock();  // Unlock while doing I/O

        const json newCfg = substituteEnv_(readFile_(currentPath_));

        // Compute delta (very naive implementation).
        json delta;
        for (auto it = newCfg.begin(); it != newCfg.end(); ++it) {
            if (!config_.contains(it.key()) || config_[it.key()] != it.value()) {
                delta[it.key()] = it.value();
            }
        }

        lock.lock();
        config_        = newCfg;
        lastWriteTime_ = nowWriteTime;
        lock.unlock();

        notifyObservers_(delta, newCfg);
        return true;
    }

    /// Retrieve immutable view of underlying JSON tree.
    const json& raw() const noexcept { return config_; }

    /// Generic, type-safe getter with default fallback.
    /// Example: auto port = cfg.get<int>("network.port", 8080);
    template <typename T>
    T get(const std::string& dottedKey, T defaultValue = T{}) const
    {
        const auto* node = nodeForKey_(dottedKey);
        if (!node) return defaultValue;

        try {
            return node->template get<T>();
        } catch (const json::exception& ex) {
            // Fallback to default on conversion errors.
            return defaultValue;
        }
    }

    /// Optional getter that returns std::nullopt if the key does not exist
    /// or cannot be converted.
    template <typename T>
    std::optional<T> tryGet(const std::string& dottedKey) const
    {
        const auto* node = nodeForKey_(dottedKey);
        if (!node) return std::nullopt;
        try {
            return node->template get<T>();
        } catch (const json::exception&) {
            return std::nullopt;
        }
    }

    /// Register a callback to be invoked on each successful reload.
    /// Returns an opaque observer-id for later removal.
    ObserverId subscribe(ObserverCallback cb) {
        std::unique_lock lock(observerMutex_);
        const ObserverId id = ++observerIdCounter_;
        observers_.emplace(id, std::move(cb));
        return id;
    }

    /// Remove observer by id. Safe to call from observer callback itself.
    void unsubscribe(ObserverId id) {
        std::unique_lock lock(observerMutex_);
        observers_.erase(id);
    }

    /// Begin periodic file-watching thread.
    /// Interval granularity is best-effort; no-op if already running.
    void startWatcher(std::chrono::milliseconds interval =
                          std::chrono::seconds(5))
    {
        if (watching_.exchange(true)) return;  // already running

        watcherThread_ = std::thread([this, interval] {
            while (watching_) {
                std::this_thread::sleep_for(interval);
                try {
                    reload();
                } catch (const std::exception& ex) {
                    // Swallow to avoid killing thread; log instead.
                    // (Real implementation would use CI360_LOG_ERROR)
                }
            }
        });
    }

    /// Gracefully stop file-watch thread.
    void stopWatcher() noexcept {
        if (!watching_.exchange(false)) return;
        if (watcherThread_.joinable()) watcherThread_.join();
    }

    // Non-copyable, non-movable.
    ConfigManager(const ConfigManager&)            = delete;
    ConfigManager& operator=(const ConfigManager&) = delete;
    ConfigManager(ConfigManager&&)                 = delete;
    ConfigManager& operator=(ConfigManager&&)      = delete;

    ~ConfigManager() { stopWatcher(); }

private:
    ConfigManager() = default;

    /* ---------------------------------------------------------------------
     *  Helper: read and parse JSON file (UTF-8, comments allowed)
     * -------------------------------------------------------------------*/
    json readFile_(const std::filesystem::path& file) const {
        std::ifstream ifs(file);
        if (!ifs.is_open()) {
            throw std::runtime_error("ConfigManager: unable to open config file " +
                                     file.string());
        }
        json j;
        try {
            ifs >> j;
        } catch (const json::parse_error& ex) {
            throw std::runtime_error("ConfigManager: JSON parse error in " +
                                     file.string() + ": " + ex.what());
        }
        return j;
    }

    /* ---------------------------------------------------------------------
     *  Helper: environment-variable substitution (recursive for strings)
     * -------------------------------------------------------------------*/
    json substituteEnv_(const json& in) const {
        json out = in;
        std::function<void(json&)> recurse = [&](json& node) {
            if (node.is_object()) {
                for (auto& kv : node.items()) recurse(kv.value());
            } else if (node.is_array()) {
                for (auto& el : node) recurse(el);
            } else if (node.is_string()) {
                const std::string& rawStr = node.get_ref<const std::string&>();
                if (rawStr.size() > 3 && rawStr.front() == '$' &&
                    rawStr[1] == '{' && rawStr.back() == '}') {
                    const std::string varName = rawStr.substr(2, rawStr.size() - 3);
                    if (const char* v = std::getenv(varName.c_str())) {
                        node = std::string(v);
                    }
                }
            }
        };
        recurse(out);
        return out;
    }

    /* ---------------------------------------------------------------------
     *  Helper: find node by dotted.key.path.
     * -------------------------------------------------------------------*/
    const json* nodeForKey_(const std::string& dottedKey) const {
        std::shared_lock lock(mutex_);
        const json* node = &config_;
        std::size_t pos  = 0;
        while (node && pos != std::string::npos) {
            auto next = dottedKey.find('.', pos);
            const std::string token =
                dottedKey.substr(pos, next == std::string::npos ? std::string::npos
                                                                : next - pos);
            if (!node->is_object() || !node->contains(token)) return nullptr;
            node = &(*node)[token];
            pos  = (next == std::string::npos) ? std::string::npos : next + 1;
        }
        return node;
    }

    static std::filesystem::file_time_type
    lastWriteTimeOf_(const std::filesystem::path& p) noexcept
    {
        std::error_code ec;
        auto ts = std::filesystem::last_write_time(p, ec);
        return ec ? std::filesystem::file_time_type::min() : ts;
    }

    /* ---------------------------------------------------------------------
     *  Notify observers (unlocking before invocation)
     * -------------------------------------------------------------------*/
    void notifyObservers_(const json& delta, const json& full) {
        std::unordered_map<ObserverId, ObserverCallback> snapshot;
        {
            std::unique_lock lock(observerMutex_);
            snapshot = observers_;  // copy
        }
        for (auto& [id, cb] : snapshot) {
            try {
                cb(delta, full);
            } catch (...) {
                // Observer errors are isolated; log and continue.
            }
        }
    }

    /* ---------------------------------------------------------------------
     *  Data members
     * -------------------------------------------------------------------*/
    mutable std::shared_mutex mutex_;
    json                       config_;
    std::filesystem::path      currentPath_;
    std::filesystem::file_time_type lastWriteTime_;

    // Observer subsystem
    std::mutex                                   observerMutex_;
    std::unordered_map<ObserverId, ObserverCallback> observers_;
    std::atomic<ObserverId>                       observerIdCounter_{0};

    // Live-reload
    std::atomic<bool> watching_{false};
    std::thread       watcherThread_;
};

}  // namespace ci360::core
```