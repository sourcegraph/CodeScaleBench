```cpp
#pragma once
/**
 *  MosaicBoard Studio
 *  File: utils/Validator.h
 *
 *  A header-only, thread-safe validation utility that centralises
 *  common string validations (e-mail, URL, UUID, file path, JSON, …)
 *  and allows run-time registration of custom validators as well as
 *  JSON-schema definitions consumed by plug-ins.
 *
 *  All functions return a lightweight Result object carrying success
 *  information and an optional diagnostic message.
 *
 *  Dependencies:
 *      – <filesystem>       : Path canonicalisation / traversal checks
 *      – <regex>            : RFC-style validations
 *      – <shared_mutex>     : Concurrency support for registry
 *      – <unordered_map>    : Validator / schema storage
 *      – nlohmann/json.hpp  : JSON parsing (header-only, pulled in by plug-ins)
 *      – nlohmann/json-schema.hpp (optional) : JSON-schema validation
 *
 *  Build note:
 *      To enable JSON-schema (recommended) add `-DMOSAICBOARD_VALIDATOR_JSON_SCHEMA`
 *      and make sure the nlohmann/json-schema header is on the include path.
 */

#include <filesystem>
#include <regex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>

#ifdef MOSAICBOARD_VALIDATOR_JSON
    #include <nlohmann/json.hpp>
#endif
#ifdef MOSAICBOARD_VALIDATOR_JSON_SCHEMA
    #include <nlohmann/json-schema.hpp>
#endif

namespace mb::utils
{

/**
 * Result of any Validator operation.
 */
struct ValidationResult
{
    bool        valid{false};
    std::string message;

    explicit operator bool() const noexcept { return valid; }
};

/**
 * Singleton helper that owns all validation logic.
 * Thread-safe, header-only, no external linkage required.
 */
class Validator
{
public:
    using ValidatorFn = std::function<ValidationResult(const std::string&)>;

    /*
     *  Access to global instance.
     *  Meyers singleton ‑ call_once ensures thread- safety.
     */
    static Validator& instance()
    {
        static Validator inst;
        return inst;
    }

    /* --------------------------------------------------------------------- */
    /*  Frequently used ready-made validators                                */
    /* --------------------------------------------------------------------- */

    static ValidationResult validateEmail(const std::string& email)
    {
        // Simplified RFC 5322 compliant pattern
        static const std::regex re(
            R"((?:[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*"
            R"(@(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+"
            R"(?:[A-Za-z]{2,})))",
            std::regex::optimize);

        if (std::regex_match(email, re))
            return {true, {}};

        return {false, "E-mail address failed RFC 5322 validation."};
    }

    static ValidationResult validateURL(const std::string& url)
    {
        static const std::regex re(
            R"((http|https)://([\w\-]+(\.[\w\-]+)+)(:[0-9]+)?(/[\w\-._~:/?#[\]@!$&'()*+,;=]*)?)",
            std::regex::icase | std::regex::optimize);

        if (std::regex_match(url, re))
            return {true, {}};

        return {false, "URL does not conform to (http|https) schema."};
    }

    static ValidationResult validateUUID(const std::string& uuid)
    {
        static const std::regex re(
            R"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})",
            std::regex::icase | std::regex::optimize);

        if (std::regex_match(uuid, re))
            return {true, {}};

        return {false, "String is not a valid RFC 4122 UUID."};
    }

    /**
     * Path validation that ensures the path stays within
     * a root directory (e.g. /uploads) and does not perform
     * traversal (..).  No I/O is performed.
     */
    static ValidationResult validatePathSecurity(const std::string& path,
                                                 const std::filesystem::path& root = std::filesystem::current_path())
    {
        namespace fs = std::filesystem;
        try
        {
            const fs::path absolute   = fs::weakly_canonical(root / path);
            const fs::path canonicalRoot = fs::weakly_canonical(root);

            if (absolute.string().rfind(canonicalRoot.string(), 0) == 0)
                return {true, {}};

            std::ostringstream oss;
            oss << "Path escapes root directory: " << canonicalRoot;
            return {false, oss.str()};
        }
        catch (const fs::filesystem_error& e)
        {
            return {false, e.what()};
        }
    }

#ifdef MOSAICBOARD_VALIDATOR_JSON
    /**
     * Checks if the supplied string is valid JSON.  If
     * MOSAICBOARD_VALIDATOR_JSON_SCHEMA is set and the schema
     * has been registered, validates against that schema as well.
     *
     * @param jsonStr   The JSON document/content.
     * @param schemaId  Optional schema identifier to validate against.
     */
    static ValidationResult validateJSON(const std::string& jsonStr,
                                         const std::string& schemaId = {})
    {
        using nlohmann::json;

        json document;
        try
        {
            document = json::parse(jsonStr);
        }
        catch (const json::parse_error& e)
        {
            return {false, e.what()};
        }

    #ifdef MOSAICBOARD_VALIDATOR_JSON_SCHEMA
        if (!schemaId.empty())
        {
            auto& v = instance();
            std::shared_lock lock(v._mutex);

            const auto it = v._schemas.find(schemaId);
            if (it == v._schemas.end())
                return {false, "Schema '" + schemaId + "' has not been registered."};

            json schemaDoc;
            try
            {
                schemaDoc = json::parse(it->second);
            }
            catch (const json::parse_error& e)
            {
                return {false, "Stored schema '" + schemaId + "' is invalid JSON: " + std::string(e.what())};
            }

            try
            {
                nlohmann::json_schema::json_validator validator(
                    [](const std::string& uri, nlohmann::json_schema::schema_loader& loader) {
                        throw std::runtime_error("External refs are not supported (uri=" + uri + ')');
                    });

                validator.set_root_schema(schemaDoc);
                validator.validate(document);
            }
            catch (const std::exception& e)
            {
                return {false, "JSON does not satisfy schema '" + schemaId + "': " + e.what()};
            }
        }
    #endif
        return {true, {}};
    }
#endif // MOSAICBOARD_VALIDATOR_JSON

    /* --------------------------------------------------------------------- */
    /*  Dynamic (plug-in) validation                                         */
    /* --------------------------------------------------------------------- */

    /**
     * Register custom validation functor under a symbolic name.
     * Thread-safe and idempotent.
     */
    static void registerCustom(const std::string& name, ValidatorFn fn)
    {
        if (name.empty())
            throw std::invalid_argument("Validator name cannot be empty.");

        auto& v = instance();
        std::unique_lock lock(v._mutex);
        v._custom[name] = std::move(fn);
    }

    /**
     * Execute named custom validator.
     */
    static ValidationResult validate(const std::string& name, const std::string& value)
    {
        auto& v = instance();
        std::shared_lock lock(v._mutex);

        const auto it = v._custom.find(name);
        if (it == v._custom.end())
            return {false, "No validator '" + name + "' has been registered."};

        return it->second(value);
    }

#ifdef MOSAICBOARD_VALIDATOR_JSON_SCHEMA
    /**
     * Store JSON Schema by identifier.  The schema JSON
     * is **not** validated upon registration for performance
     * reasons; it will be parsed during the first validation
     * request that references it.
     */
    static void registerSchema(const std::string& id, const std::string& schemaJson)
    {
        if (id.empty())
            throw std::invalid_argument("Schema id cannot be empty.");
        if (schemaJson.empty())
            throw std::invalid_argument("Schema JSON cannot be empty.");

        auto& v = instance();
        std::unique_lock lock(v._mutex);
        v._schemas[id] = schemaJson;
    }
#endif

private:
    // Private ctor/dtor to enforce the singleton
    Validator()  = default;
    ~Validator() = default;

    // Non-copyable
    Validator(const Validator&)            = delete;
    Validator& operator=(const Validator&) = delete;

    /* --------------------------------------------------------------------- */
    /*  Internal state                                                       */
    /* --------------------------------------------------------------------- */
    std::unordered_map<std::string, ValidatorFn> _custom;
#ifdef MOSAICBOARD_VALIDATOR_JSON_SCHEMA
    std::unordered_map<std::string, std::string> _schemas;
#endif
    mutable std::shared_mutex _mutex;
};

} // namespace mb::utils
```