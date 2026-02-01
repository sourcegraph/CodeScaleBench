#include "core/ConfigManager.hpp"

#include <spdlog/spdlog.h>
#include <nlohmann/json.hpp>
#include <yaml-cpp/yaml.h>

#include <filesystem>
#include <fstream>
#include <sstream>
#include <charconv>
#include <thread>
#include <regex>

using json = nlohmann::json;
namespace fs = std::filesystem;

namespace mosaic::core
{

// ─────────────────────────────────────────────────────────────────────────────
// Helper utilities (anonymous namespace)
// ─────────────────────────────────────────────────────────────────────────────
namespace
{
    // Convert dotted.path.notation into nested JSON pointer format
    // E.g. "database.host"  -> "/database/host"
    std::string toPointer(const std::string& dotted)
    {
        if (dotted.empty())
            return {};

        std::string ptr{"/"};
        ptr.reserve(dotted.size() + 2);
        for (char c : dotted)
            ptr.push_back(c == '.' ? '/' : c);
        return ptr;
    }

    std::string toEnvName(const std::string& dotted)
    {
        std::string upper;
        upper.reserve(dotted.size());
        for (char c : dotted)
            upper.push_back(c == '.' ? '_' : static_cast<char>(::toupper(c)));
        return upper;
    }

    // Try to convert raw string to a specific type; fallback to default value.
    template <typename T>
    T fromString(const std::string& s, const T& fallback)
    {
        std::istringstream iss{s};
        T value;
        if (iss >> value)
            return value;
        return fallback;
    }

    template <>
    std::string fromString<std::string>(const std::string& s, const std::string&)
    {
        return s;
    }

    template <>
    bool fromString<bool>(const std::string& s, const bool& fallback)
    {
        if (s == "true" || s == "1")
            return true;
        if (s == "false" || s == "0")
            return false;
        return fallback;
    }

} // namespace

// ─────────────────────────────────────────────────────────────────────────────
// ConfigManager implementation
// ─────────────────────────────────────────────────────────────────────────────

ConfigManager &ConfigManager::instance()
{
    static ConfigManager inst;
    return inst;
}

ConfigManager::ConfigManager() = default;

ConfigManager::~ConfigManager()
{
    _terminate.store(true);
    if (_watcher.joinable())
        _watcher.join();
}

void ConfigManager::initialize(const fs::path &configRoot,
                               bool autoReload,
                               std::chrono::milliseconds pollInterval)
{
    {
        std::unique_lock lk(_mutex);
        if (_initialized)
            throw std::runtime_error("ConfigManager already initialized.");

        _configRoot    = configRoot;
        _pollInterval  = pollInterval;
        _initialized   = true;
    }

    loadFiles(); // Throws on failure

    if (autoReload)
    {
        _watcher = std::jthread([this](std::stop_token st) { watchLoop(std::move(st)); });
        spdlog::info("ConfigManager: File watcher thread started.");
    }
}

void ConfigManager::watchLoop(std::stop_token st)
{
    while (!st.stop_requested() && !_terminate.load())
    {
        std::this_thread::sleep_for(_pollInterval);

        try
        {
            if (detectChanges())
            {
                spdlog::info("ConfigManager: configuration change detected. Reloading…");
                loadFiles();
            }
        }
        catch (const std::exception &ex)
        {
            spdlog::error("ConfigManager: error while reloading configuration: {}", ex.what());
        }
    }
}

bool ConfigManager::detectChanges()
{
    bool changed = false;
    for (const auto &entry : fs::recursive_directory_iterator(_configRoot))
    {
        if (!entry.is_regular_file())
            continue;

        const auto path         = entry.path();
        const auto currentWrite = fs::last_write_time(path);

        auto it = _fileTimestamps.find(path.string());
        if (it == _fileTimestamps.end())
        {
            // New file
            changed = true;
            break;
        }
        else if (it->second != currentWrite)
        {
            changed = true;
            break;
        }
    }
    return changed;
}

void ConfigManager::loadFiles()
{
    json merged;

    if (!fs::exists(_configRoot))
        throw std::runtime_error("ConfigManager: configuration directory does not exist: " + _configRoot.string());

    for (const auto &entry : fs::recursive_directory_iterator(_configRoot))
    {
        if (!entry.is_regular_file())
            continue;

        const auto ext = entry.path().extension().string();
        try
        {
            if (ext == ".json")
            {
                json j;
                std::ifstream ifs(entry.path());
                if (!ifs)
                    throw std::runtime_error("Failed to open JSON file.");

                ifs >> j;
                merged.merge_patch(j);
            }
            else if (ext == ".yaml" || ext == ".yml")
            {
                YAML::Node node = YAML::LoadFile(entry.path().string());
                json j          = json::parse(YAML::Dump(node));
                merged.merge_patch(j);
            }
        }
        catch (const std::exception &ex)
        {
            spdlog::warn("ConfigManager: Could not parse file '{}': {}", entry.path().string(), ex.what());
        }

        _fileTimestamps[entry.path().string()] = fs::last_write_time(entry.path());
    }

    {
        std::unique_lock lk(_mutex);
        _config = std::move(merged);
        _lastRefresh = std::chrono::system_clock::now();
    }
}

void ConfigManager::reload()
{
    std::unique_lock lk(_mutex);
    spdlog::info("ConfigManager: forced reload requested.");
    loadFiles();
}

json ConfigManager::subtree(const std::string &dottedPath) const
{
    std::shared_lock lk(_mutex);

    auto ptr = toPointer(dottedPath);
    json result = _config;

    if (!ptr.empty() && result.contains(json::json_pointer(ptr)))
        result = result.at(json::json_pointer(ptr));
    else
        result = json::object();

    return result;
}

std::vector<std::string> ConfigManager::keys(const std::string &dottedPath) const
{
    json node = subtree(dottedPath);
    std::vector<std::string> ks;
    ks.reserve(node.size());

    for (auto it = node.begin(); it != node.end(); ++it)
        ks.push_back(it.key());
    return ks;
}

template <typename T>
T ConfigManager::get(const std::string &dottedPath, const T &defaultValue) const
{
    // 1) Check environment override
    const auto envName = toEnvName(dottedPath);
    if (const char *envVal = std::getenv(envName.c_str()); envVal)
    {
        return fromString<T>(envVal, defaultValue);
    }

    // 2) Configuration tree lookup
    std::shared_lock lk(_mutex);
    auto ptr = toPointer(dottedPath);

    try
    {
        if (_config.contains(json::json_pointer(ptr)))
            return _config.at(json::json_pointer(ptr)).get<T>();
    }
    catch (const std::exception &ex)
    {
        spdlog::error("ConfigManager: Error converting '{}' value: {}", dottedPath, ex.what());
    }

    return defaultValue;
}

// Explicit template instantiations
template int               ConfigManager::get<int>(const std::string&, const int&) const;
template double            ConfigManager::get<double>(const std::string&, const double&) const;
template bool              ConfigManager::get<bool>(const std::string&, const bool&) const;
template std::string       ConfigManager::get<std::string>(const std::string&, const std::string&) const;
template std::vector<int>  ConfigManager::get<std::vector<int>>(const std::string&, const std::vector<int>&) const;
template json              ConfigManager::get<json>(const std::string&, const json&) const;

} // namespace mosaic::core