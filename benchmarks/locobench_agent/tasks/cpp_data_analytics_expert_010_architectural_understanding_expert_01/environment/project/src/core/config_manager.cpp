```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:        cardio_insight_360/src/core/config_manager.cpp
 *  Description: Thread-safe runtime configuration manager.
 *
 *  The ConfigManager is responsible for:
 *    1. Discovering and loading configuration files (JSON)
 *    2. Overlaying environment-variable overrides
 *    3. Serving typed, read-only views of configuration values
 *    4. Hot-reloading on-disk changes and notifying observers
 *
 *  The implementation favours immutability by exposing
 *  only const reads while the internal state can be swapped
 *  atomically when the backing file changes.  This guarantees
 *  readers never observe partial updates.
 */

#include "core/config_manager.hpp"

#include <cstdlib>              // std::getenv
#include <fstream>              // std::ifstream
#include <iomanip>              // std::setw (pretty print)
#include <mutex>                // std::unique_lock
#include <shared_mutex>         // std::shared_mutex
#include <stdexcept>            // std::runtime_error
#include <thread>               // std::thread
#include <utility>              // std::move
#include <chrono>               // std::chrono literals

// Third-party – single-header JSON lib (header-only dependency)
#include <nlohmann/json.hpp>

// Project-local utilities
#include "utils/logger.hpp"
#include "utils/strings.hpp"    // string helpers (trim, split, etc.)

namespace ci360::core {

using json          = nlohmann::json;
using Clock         = std::chrono::steady_clock;
using namespace std::chrono_literals;

/*----------------------------------------------------------
 *  Construction / Destruction
 *---------------------------------------------------------*/
ConfigManager::ConfigManager(std::filesystem::path configPath,
                             ReloadPolicy              reloadPolicy,
                             std::chrono::milliseconds pollInterval)
    : _configPath    { std::move(configPath) }
    , _reloadPolicy  { reloadPolicy }
    , _pollInterval  { pollInterval }
{
    if (_configPath.empty()) {
        throw std::invalid_argument("ConfigManager: config path must not be empty");
    }

    _logger = utils::Logger::instance().createChild("ConfigManager");
    loadInitialConfig();

    if (_reloadPolicy == ReloadPolicy::Auto) {
        startWatcherThread();
    }
}

ConfigManager::~ConfigManager() noexcept
{
    _terminateWatcher.test_and_set();
    if (_watcherThread.joinable()) {
        _watcherThread.join();
    }
}

/*----------------------------------------------------------
 *  Public API
 *---------------------------------------------------------*/

bool ConfigManager::reload()
{
    std::unique_lock lock{ _writeMutex };
    json newConfig;
    if (!parseConfigFile(newConfig)) {
        return false;
    }
    overlayEnvironmentVariables(newConfig);

    {
        // Atomically swap state under unique lock
        std::unique_lock stateLock{ _stateMutex };
        _state = std::move(newConfig);
        _lastReloadTs = Clock::now();
    }

    _logger->info("Configuration reloaded from disk: {}", _configPath.string());
    notifyCallbacks();
    return true;
}

/**
 * Template specialization is handled in header;
 * here we only implement generic string-based retrieval.
 */
std::optional<std::string> ConfigManager::getString(std::string_view key) const
{
    std::shared_lock lock{ _stateMutex };
    const json* node = drillDown(_state, key);
    if (node && node->is_string()) {
        return node->get<std::string>();
    }
    return std::nullopt;
}

void ConfigManager::registerCallback(CallbackFn fn)
{
    if (!fn) return;
    std::unique_lock lock{ _callbackMutex };
    _callbacks.emplace_back(std::move(fn));
}

/*----------------------------------------------------------
 *  Private helpers
 *---------------------------------------------------------*/

void ConfigManager::loadInitialConfig()
{
    json cfg;
    if (!parseConfigFile(cfg)) {
        throw std::runtime_error("ConfigManager: unable to parse configuration file " +
                                 _configPath.string());
    }

    overlayEnvironmentVariables(cfg);

    {
        std::unique_lock lock{ _stateMutex };
        _state         = std::move(cfg);
        _lastReloadTs  = Clock::now();
    }

    _logger->info("Loaded configuration file: {}", _configPath.string());
}

bool ConfigManager::parseConfigFile(json& out) const
{
    std::ifstream ifs{ _configPath };
    if (!ifs) {
        _logger->error("Failed to open configuration file: {}", _configPath.string());
        return false;
    }

    try {
        ifs >> out;
        return true;
    } catch (const json::parse_error& ex) {
        _logger->error("JSON parse error at byte {}: {}", ex.byte, ex.what());
        return false;
    }
}

void ConfigManager::overlayEnvironmentVariables(json& cfg) const
{
    /* Environment override syntax:
     *   CI360_CFG_<UPPERCASE_WITH_UNDERSCORES>=value
     * It maps to JSON keys using '.' as separator.
     *
     * Example:
     *   CI360_CFG_STREAMING_KAFKA.BOOTSTRAP_SERVERS=localhost:9092
     *   -> json["streaming"]["kafka"]["bootstrap_servers"]
     */
    constexpr std::string_view prefix = "CI360_CFG_";

#if defined(_WIN32)
    // Windows: use getenv_s
    size_t  len = 0;
    char**  envVars = nullptr;
    _dupenv_s(envVars, &len, "*"); // Ugly: retrieving entire env on Windows is non-portable.
#else
    extern char** environ; // POSIX
    for (char** env = environ; *env != nullptr; ++env) {
        std::string var{ *env };
        if (var.rfind(prefix, 0) != 0) continue; // skip non-prefixed
        auto eqPos = var.find('=');
        if (eqPos == std::string::npos) continue;

        std::string key = var.substr(prefix.size(), eqPos - prefix.size());
        std::string val = var.substr(eqPos + 1);

        // Normalize: UPPERCASE_WITH_UNDERSCORES -> lowercase.with.dots
        utils::strings::toLower(key);
        std::replace(key.begin(), key.end(), '_', '.');

        // Drill/create hierarchy
        json* cursor = &cfg;
        auto  tokens = utils::strings::split(key, '.');
        for (size_t i = 0; i < tokens.size(); ++i) {
            const auto& tk = tokens[i];
            if (i + 1 == tokens.size()) {
                // leaf
                (*cursor)[tk] = val;
            } else {
                cursor = &((*cursor)[tk]);
            }
        }
        _logger->debug("Environment override: {} -> {}", key, val);
    }
#endif
}

void ConfigManager::startWatcherThread()
{
    _watcherThread = std::thread([this] {
        auto lastWriteTime = std::filesystem::last_write_time(_configPath);
        while (!_terminateWatcher.test()) {
            std::this_thread::sleep_for(_pollInterval);

            std::error_code ec;
            auto currentWriteTime = std::filesystem::last_write_time(_configPath, ec);
            if (ec) {
                _logger->warn("Unable to stat config file: {}", ec.message());
                continue;
            }

            if (currentWriteTime != lastWriteTime) {
                _logger->info("Detected change in configuration file");
                lastWriteTime = currentWriteTime;
                reload();
            }
        }
    });
    _logger->info("Started configuration file watcher thread");
}

void ConfigManager::notifyCallbacks()
{
    std::vector<CallbackFn> snapshot;
    {
        std::unique_lock lock{ _callbackMutex };
        snapshot = _callbacks; // copy
    }

    for (auto& cb : snapshot) {
        try {
            cb();
        } catch (const std::exception& ex) {
            _logger->error("Exception thrown from ConfigManager callback: {}", ex.what());
        }
    }
}

/**
 * Helper: navigate nested JSON using dotted keys.
 * Returns nullptr if key is not present.
 */
const json* ConfigManager::drillDown(const json& root, std::string_view dotted) const
{
    size_t pos   = 0;
    size_t start = 0;
    const json* node = &root;

    while (pos != std::string_view::npos) {
        pos = dotted.find('.', start);
        std::string_view token = dotted.substr(start, pos == std::string_view::npos
                                                     ? std::string_view::npos
                                                     : pos - start);

        if (!node->contains(token)) {
            return nullptr;
        }
        node = &((*node)[token]);
        start = pos + 1;
    }
    return node;
}

/*----------------------------------------------------------
 *  Debug helpers
 *---------------------------------------------------------*/

void ConfigManager::dumpToLog() const
{
    std::shared_lock lock{ _stateMutex };
    std::stringstream ss;
    ss << std::setw(2) << _state;
    _logger->info("Current configuration:\n{}", ss.str());
}

} // namespace ci360::core
```
