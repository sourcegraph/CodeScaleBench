```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File:        src/lib/common/config_loader.cpp
 *  Author:      FortiLedger360 Core Team
 *  Description: Robust configuration loader with support for
 *               - Hierarchical JSON configuration (default + tenant-specific)
 *               - Environment-variable overrides
 *               - Thread-safe runtime hot-reload
 *               - Lazy, on-demand value retrieval through dotted-path look-ups
 *
 *  NOTE:
 *  This translation unit depends on the single-header version of
 *  `nlohmann::json` (https://github.com/nlohmann/json) and requires
 *  C++17 for <filesystem>.
 */

#include "config_loader.hpp"

#include <cstdlib>              // std::getenv
#include <fstream>              // std::ifstream
#include <iomanip>              // std::setw (pretty print)
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string_view>

#include <nlohmann/json.hpp>

namespace fl360::common {

namespace fs = std::filesystem;
using json    = nlohmann::json;

/* ----------------------------------------------------------- *
 *  Utilities
 * ----------------------------------------------------------- */

/**
 * Convert an environment variable constructed in FL360_* notation
 *  – single underscore '_'  → kept as '_' inside key
 *  – double underscore '__' → segments separator ('.')
 *
 * Example:
 *   FL360_SECURITY_SCANNING__MAX_DEPTH  ->  security_scanning.max_depth
 */
static std::string envKeyToDottedPath(std::string_view rawKey) {
    constexpr std::string_view kPrefix = "FL360_";
    if (!rawKey.starts_with(kPrefix)) { return {}; }

    // Strip prefix
    std::string_view body = rawKey.substr(kPrefix.length());
    std::string       out;
    out.reserve(body.size());

    for (size_t i = 0; i < body.size();) {
        if (i + 1 < body.size() && body[i] == '_' && body[i + 1] == '_') {
            out.push_back('.');
            i += 2;
        } else {
            out.push_back(static_cast<char>(std::tolower(body[i])));
            ++i;
        }
    }
    return out;
}

/**
 * Dumb heuristic JSON value parser from string.
 * Attempts bool, int, unsigned, double before defaulting to
 * plain string.
 */
static json parsePrimitive(std::string_view raw) {
    // Attempt boolean
    if (raw == "true" || raw == "TRUE" || raw == "True")  return true;
    if (raw == "false" || raw == "FALSE" || raw == "False") return false;

    // Attempt integer
    {
        char* end = nullptr;
        long   l  = std::strtol(raw.data(), &end, 10);
        if (end && static_cast<size_t>(end - raw.data()) == raw.size()) {
            return static_cast<int64_t>(l);
        }
    }
    // Attempt floating point
    {
        char* end = nullptr;
        double d  = std::strtod(raw.data(), &end);
        if (end && static_cast<size_t>(end - raw.data()) == raw.size()) {
            return d;
        }
    }
    // Fallback to raw string
    return std::string(raw);
}

/* ----------------------------------------------------------- *
 *  ConfigLoader Impl
 * ----------------------------------------------------------- */

ConfigLoader::ConfigLoader(Options opts)
    : options_(std::move(opts)) {

    if (!fs::exists(options_.defaultConfig)) {
        throw std::runtime_error(
            "ConfigLoader: default config file not found at " +
            options_.defaultConfig.string());
    }
    reload();  // initial load
}

ConfigLoader& ConfigLoader::instance() {
    static ConfigLoader singleton{Options{}};
    return singleton;
}

void ConfigLoader::reload() {
    // Acquire unique lock while re-populating the config tree
    std::unique_lock lock(mutex_);

    json merged;

    // 1. Load default config
    loadJsonFile(options_.defaultConfig, merged);

    // 2. Merge tenant-specific config, if any
    if (const char* tenantCfg = std::getenv("FORTILEDGER360_CONFIG")) {
        fs::path tenantPath(tenantCfg);
        if (fs::exists(tenantPath)) {
            loadJsonFile(tenantPath, merged);
        } else {
            throw std::runtime_error(
                "ConfigLoader: $FORTILEDGER360_CONFIG points to non-existent file '" +
                tenantPath.string() + "'");
        }
    }

    // 3. Environment overrides
    mergeEnvironmentOverrides(merged);

    // Atomically swap
    config_ = std::move(merged);
}

json ConfigLoader::get() const {
    std::shared_lock lock(mutex_);
    return config_;
}

void ConfigLoader::toStream(std::ostream& os, bool pretty) const {
    std::shared_lock lock(mutex_);
    if (pretty) {
        os << std::setw(2) << config_;
    } else {
        os << config_.dump();
    }
    os.flush();
}

/* ----------------------------------------------------------- *
 *  Template helpers
 * ----------------------------------------------------------- */

namespace {

/**
 * Walk a dotted path ("a.b.c") inside json j and return pointer,
 * or nullptr if not found.
 */
const json* locate(const json& j, std::string_view dottedPath) {
    size_t start = 0;
    const json* cur = &j;
    while (true) {
        size_t dot = dottedPath.find('.', start);
        std::string_view segment =
            dottedPath.substr(start, dot == std::string_view::npos ? std::string_view::npos
                                                                   : dot - start);

        if (!cur->is_object() || !cur->contains(std::string(segment))) {
            return nullptr;
        }
        cur = &(*cur)[std::string(segment)];

        if (dot == std::string_view::npos) break;
        start = dot + 1;
    }
    return cur;
}

}  // namespace

/* ----------------------------------------------------------- *
 *  Non-template interface
 * ----------------------------------------------------------- */

bool ConfigLoader::contains(std::string_view path) const {
    std::shared_lock lock(mutex_);
    return locate(config_, path) != nullptr;
}

/* ----------------------------------------------------------- *
 *  Private helpers
 * ----------------------------------------------------------- */

void ConfigLoader::loadJsonFile(const fs::path& p, json& target) const {
    std::ifstream inFile(p);
    if (!inFile) {
        throw std::runtime_error(
            "ConfigLoader: failed to open config file '" + p.string() + "'");
    }

    json candidate;
    try {
        inFile >> candidate;
    } catch (const json::parse_error& ex) {
        throw std::runtime_error(
            "ConfigLoader: malformed JSON in '" + p.string() +
            "': " + ex.what());
    }

    // Deep merge: values in candidate override target
    target.merge_patch(candidate);
}

void ConfigLoader::mergeEnvironmentOverrides(json& target) const {
    extern char **environ;
    for (char **env = environ; *env; ++env) {
        std::string_view line(*env);
        auto delim = line.find('=');
        if (delim == std::string_view::npos) continue;

        std::string_view key   = line.substr(0, delim);
        std::string_view value = line.substr(delim + 1);

        std::string dotted = envKeyToDottedPath(key);
        if (dotted.empty()) continue;  // not a FL360_* variable

        // Create nested structure as needed
        json* cursor = &target;
        std::stringstream ss(dotted);
        std::string segment;
        while (std::getline(ss, segment, '.')) {
            if (ss.peek() == EOF) {
                // last segment
                (*cursor)[segment] = parsePrimitive(value);
            } else {
                cursor = &((*cursor)[segment]);  // create object if absent
            }
        }
    }
}

/* ----------------------------------------------------------- *
 *  Template instantiations
 * ----------------------------------------------------------- */

template <>
std::string ConfigLoader::value<std::string>(
    std::string_view path, const std::string& fallback) const {
    std::shared_lock lock(mutex_);
    const json* j = locate(config_, path);
    if (!j) return fallback;
    if (j->is_string()) return j->get<std::string>();
    return j->dump();  // basic conversion
}

template <>
bool ConfigLoader::value<bool>(std::string_view path, const bool& fallback) const {
    std::shared_lock lock(mutex_);
    const json* j = locate(config_, path);
    if (!j) return fallback;
    if (j->is_boolean()) return j->get<bool>();
    return fallback;
}

template <>
int64_t ConfigLoader::value<int64_t>(std::string_view path,
                                     const int64_t&  fallback) const {
    std::shared_lock lock(mutex_);
    const json* j = locate(config_, path);
    if (!j) return fallback;
    if (j->is_number_integer()) return j->get<int64_t>();
    return fallback;
}

template <>
double ConfigLoader::value<double>(std::string_view path,
                                   const double&  fallback) const {
    std::shared_lock lock(mutex_);
    const json* j = locate(config_, path);
    if (!j) return fallback;
    if (j->is_number_float()) return j->get<double>();
    if (j->is_number_integer()) return static_cast<double>(j->get<int64_t>());
    return fallback;
}

/* Explicit template for generic json */
template <>
json ConfigLoader::value<json>(std::string_view path, const json& fallback) const {
    std::shared_lock lock(mutex_);
    const json* j = locate(config_, path);
    if (!j) return fallback;
    return *j;
}

}  // namespace fl360::common
```