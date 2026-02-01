#pragma once
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File     : schema_manager.h
 *  Namespace: ci360::storage
 *  Author   : Auto-generated (LLM)
 *
 *  Description:
 *      Centralised in-process registry that manages logical schemas used
 *      by the data-lake façade (Parquet), streaming bus (Avro/OAИ), and the
 *      HL7/FHIR ingestion layer.  The SchemaManager persists schema metadata,
 *      resolves versions, validates compatibility, and notifies interested
 *      subscribers when a schema is created or evolved.
 *
 *  Thread-Safety:
 *      • All public functions are safe for concurrent use.
 *      • Internally uses a `std::shared_mutex` for high read concurrency.
 *
 *  Dependencies:
 *      • nlohmann/json (header-only JSON parser)
 *      • C++17 standard library
 */

#include <nlohmann/json.hpp>

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ci360::storage
{

/* --------------------------------------------------------- *
 *                       Error Types                          *
 * --------------------------------------------------------- */

/**
 * Base class for all schema-related exceptions.
 */
class SchemaError : public std::runtime_error
{
public:
    explicit SchemaError(std::string msg) : std::runtime_error(std::move(msg)) {}
};

/**
 * Thrown when a requested schema cannot be found.
 */
class SchemaNotFoundError : public SchemaError
{
public:
    explicit SchemaNotFoundError(const std::string& name)
        : SchemaError("Schema not found: " + name) {}
};

/**
 * Thrown when a schema fails validation or is incompatible.
 */
class SchemaValidationError : public SchemaError
{
public:
    explicit SchemaValidationError(const std::string& msg)
        : SchemaError("Schema validation error: " + msg) {}
};

/* --------------------------------------------------------- *
 *                       Core Types                           *
 * --------------------------------------------------------- */

/**
 * Simple version wrapper providing monotonic comparison.
 */
struct SchemaVersion
{
    std::uint32_t major{1};
    std::uint32_t minor{0};
    std::uint32_t patch{0};

    bool operator==(const SchemaVersion& other) const noexcept
    {
        return std::tie(major, minor, patch) ==
               std::tie(other.major, other.minor, other.patch);
    }

    bool operator<(const SchemaVersion& other) const noexcept
    {
        return std::tie(major, minor, patch) <
               std::tie(other.major, other.minor, other.patch);
    }

    std::string toString() const
    {
        return std::to_string(major) + "." + std::to_string(minor) + "." +
               std::to_string(patch);
    }
};

/**
 * Immutable representation of a typed schema.
 * The payload is an opaque JSON document adhering to CI360 conventions.
 */
class Schema final
{
public:
    Schema(std::string name,
           SchemaVersion ver,
           nlohmann::json  payload,
           std::string     checksum)
        : m_name(std::move(name))
        , m_version(ver)
        , m_payload(std::move(payload))
        , m_checksum(std::move(checksum))
    {}

    const std::string&  name()     const noexcept { return m_name; }
    const SchemaVersion& version() const noexcept { return m_version; }
    const std::string&  checksum() const noexcept { return m_checksum; }
    const nlohmann::json& payload() const noexcept { return m_payload; }

private:
    std::string      m_name;
    SchemaVersion    m_version;
    nlohmann::json   m_payload;
    std::string      m_checksum;   // e.g., SHA-256 of payload
};

/* --------------------------------------------------------- *
 *                    SchemaManager API                       *
 * --------------------------------------------------------- */

class SchemaManager
{
public:
    using Ptr                         = std::shared_ptr<SchemaManager>;
    using SchemaPtr                   = std::shared_ptr<const Schema>;
    using SchemaPredicate             = std::function<bool(const Schema&)>;
    using SchemaChangeCallbackHandle  = std::size_t;
    using SchemaChangeCallback        = std::function<void(SchemaPtr)>;

    /**
     * Factory for obtaining a shared manager instance.  The function
     * guarantees thread-safe lazy initialisation (Meyers singleton).
     */
    static Ptr instance()
    {
        static Ptr s{new SchemaManager()};
        return s;
    }

    /**
     * Registers a schema with the manager after validating it for
     * structural correctness and version compatibility.
     *
     * Throws SchemaValidationError on invalid schema.
     *
     * Returns: shared pointer to the immutable Schema.
     */
    SchemaPtr registerSchema(const Schema& schema)
    {
        std::unique_lock lock(m_mutex);

        auto& versions = m_registry[schema.name()];

        // Basic compatibility: new version must be strictly newer
        if (!versions.empty() && !(versions.back()->version() < schema.version()))
        {
            throw SchemaValidationError("Schema version must be monotonically increasing: " +
                                        schema.name() + " (" + schema.version().toString() + ")");
        }

        // Optional: run custom validation plug-ins
        validateSchema(schema);

        auto ptr = std::make_shared<Schema>(schema);
        versions.push_back(ptr);  // Append as latest

        lock.unlock(); // release before notifying

        notifyWatchers(ptr);
        return ptr;
    }

    /**
     * Loads a JSON schema file from disk and registers it.
     * The file name must follow the convention:
     *      <name>_v<major>.<minor>.<patch>.json
     *
     * Throws filesystem_error / SchemaValidationError.
     */
    SchemaPtr loadFromFile(const std::filesystem::path& filePath)
    {
        if (!std::filesystem::is_regular_file(filePath))
            throw std::filesystem::filesystem_error(
                "schema file not found",
                filePath,
                std::make_error_code(std::errc::no_such_file_or_directory));

        // Extract metadata from filename
        const auto fileName = filePath.filename().string();
        const auto meta     = parseFilename(fileName);

        // Read file
        std::ifstream ifs(filePath);
        if (!ifs.is_open())
            throw std::filesystem::filesystem_error("unable to open schema file",
                                                    filePath,
                                                    std::make_error_code(std::errc::io_error));

        nlohmann::json json;
        ifs >> json;

        const auto checksum = computeChecksum(json.dump());

        Schema sch{meta.name, meta.version, json, checksum};
        return registerSchema(sch);
    }

    /**
     * Retrieves the latest version of a schema by name.
     * Returns nullopt if schema does not exist.
     */
    std::optional<SchemaPtr> latest(const std::string& name) const
    {
        std::shared_lock lock(m_mutex);
        auto it = m_registry.find(name);
        if (it == m_registry.end() || it->second.empty())
            return std::nullopt;

        return it->second.back();
    }

    /**
     * Retrieves a specific version of a schema.
     * Throws SchemaNotFoundError if not found.
     */
    SchemaPtr get(const std::string& name, const SchemaVersion& ver) const
    {
        std::shared_lock lock(m_mutex);
        auto it = m_registry.find(name);
        if (it == m_registry.end())
            throw SchemaNotFoundError(name);

        for (const auto& s : it->second)
        {
            if (s->version() == ver)
                return s;
        }
        throw SchemaNotFoundError(name + " (" + ver.toString() + ")");
    }

    /**
     * Subscribes for schema-registration events that match a predicate.
     *
     * Returns an opaque handle that can be passed to `unsubscribe`.
     */
    SchemaChangeCallbackHandle subscribe(SchemaPredicate predicate,
                                         SchemaChangeCallback cb)
    {
        std::unique_lock lock(m_mutex);
        const auto handle = m_nextCallbackId++;
        m_watchers.emplace(handle, Watcher{std::move(predicate), std::move(cb)});
        return handle;
    }

    /**
     * Cancels a previously registered callback.
     */
    void unsubscribe(SchemaChangeCallbackHandle handle)
    {
        std::unique_lock lock(m_mutex);
        m_watchers.erase(handle);
    }

    /*
     * Deletes copy semantics; manager must be a singleton.
     */
    SchemaManager(const SchemaManager&)            = delete;
    SchemaManager& operator=(const SchemaManager&) = delete;

private:
    SchemaManager() = default;

    /* ---------- Internal Helpers ---------- */

    struct Watcher
    {
        SchemaPredicate      filter;
        SchemaChangeCallback cb;
    };

    struct FilenameMeta
    {
        std::string   name;
        SchemaVersion version;
    };

    static FilenameMeta parseFilename(const std::string& fname)
    {
        // Expected: <name>_v<major>.<minor>.<patch>.json
        const auto endOfName = fname.find("_v");
        const auto dotJson   = fname.rfind(".json");

        if (endOfName == std::string::npos || dotJson == std::string::npos)
            throw SchemaValidationError("Invalid schema file name: " + fname);

        const std::string name     = fname.substr(0, endOfName);
        const std::string versionS = fname.substr(endOfName + 2, dotJson - endOfName - 2);

        SchemaVersion ver{};
        if (std::sscanf(versionS.c_str(), "%u.%u.%u",
                        &ver.major, &ver.minor, &ver.patch) != 3)
        {
            throw SchemaValidationError("Invalid version segment in: " + fname);
        }

        return {name, ver};
    }

    static std::string computeChecksum(const std::string& payload)
    {
        /* VERY simple (non-cryptographic) checksum for illustration.
           Production code should use SHA-256 or similar via OpenSSL. */
        std::uint32_t hash{0x811C9DC5u};
        for (unsigned char c : payload)
        {
            hash ^= c;
            hash *= 0x01000193u;
        }
        return "fnv1a:" + std::to_string(hash);
    }

    void validateSchema(const Schema& schema) const
    {
        // Basic validation rules – extend as needed
        if (schema.name().empty())
            throw SchemaValidationError("Schema name cannot be empty");

        if (!schema.payload().contains("$id"))
            throw SchemaValidationError("Schema must contain \"$id\" field");

        // Additional domain-specific validations can be plugged here.
    }

    void notifyWatchers(const SchemaPtr& schema)
    {
        std::vector<SchemaChangeCallback> toNotify;

        {   // Acquire read lock and collect callbacks to invoke
            std::shared_lock lock(m_mutex);
            for (const auto& [_, watcher] : m_watchers)
            {
                if (!watcher.filter || watcher.filter(*schema))
                    toNotify.emplace_back(watcher.cb);
            }
        }

        // Invoke outside lock to prevent deadlock if callbacks re-enter manager
        for (auto& cb : toNotify)
        {
            try
            {
                cb(schema);
            }
            catch (const std::exception& ex)
            {
                // Swallow exceptions to avoid destabilising callers.
                // In production we would log this via the built-in telemetry subsystem.
            }
        }
    }

    /* ---------- Data Members ---------- */

    mutable std::shared_mutex m_mutex;

    // name -> ordered vector of versions (monotonically increasing)
    std::unordered_map<std::string, std::vector<SchemaPtr>> m_registry;

    // subscription callbacks
    std::unordered_map<SchemaChangeCallbackHandle, Watcher> m_watchers;
    SchemaChangeCallbackHandle                              m_nextCallbackId{1};
};

} // namespace ci360::storage