#pragma once
/*
 * MosaicBoard Studio – JsonUtils
 *
 * A small collection of convenience helpers that wrap the excellent
 * nlohmann::json library with project-specific defaults, rich error
 * reporting and a handful of production-grade utilities (schema validation,
 * diff / patch, and transparent file IO).
 *
 * This header is *header-only* to keep usage friction minimal.
 *
 * Copyright 2024 MosaicBoard Studio
 */

#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace mosaic::util
{
using Json = nlohmann::json;
namespace fs = std::filesystem;

/* ************************************************************
 * Exception hierarchy
 * ***********************************************************/

/* Base class for all JSON-related errors inside MosaicBoard Studio. */
class JsonError : public std::runtime_error
{
  public:
    explicit JsonError(std::string msg)
        : std::runtime_error{std::move(msg)}
    {}
};

/* Thrown when IO on a JSON file fails (e.g. file missing, permissions). */
class JsonIoError : public JsonError
{
  public:
    using JsonError::JsonError;
};

/* Thrown when JSON parsing fails. */
class JsonParseError : public JsonError
{
  public:
    using JsonError::JsonError;
};

/* Thrown when a JSON value fails schema validation. */
class JsonValidationError : public JsonError
{
  public:
    using JsonError::JsonError;
};

/* ************************************************************
 * Utility traits and helpers
 * ***********************************************************/

/* Simple SFINAE test: true if T has static `from_json(const Json&, T&)`. */
template <typename T, typename = void>
struct has_adl_from_json : std::false_type
{};
template <typename T>
struct has_adl_from_json<
    T,
    std::void_t<decltype(from_json(std::declval<const Json &>(),
                                   std::declval<T &>()))>> : std::true_type
{};

/* Simple SFINAE test: true if T has static `to_json(Json&, const T&)`. */
template <typename T, typename = void>
struct has_adl_to_json : std::false_type
{};
template <typename T>
struct has_adl_to_json<
    T,
    std::void_t<decltype(to_json(std::declval<Json &>(),
                                 std::declval<const T &>()))>> : std::true_type
{};

/* Serialize helper for std::optional. */
template <typename T>
inline void to_json(Json &j, const std::optional<T> &opt)
{
    if (opt)
        j = *opt;
    else
        j = nullptr;
}
template <typename T>
inline void from_json(const Json &j, std::optional<T> &opt)
{
    if (j.is_null()) {
        opt.reset();
    } else {
        opt.emplace(j.get<T>());
    }
}

/* ************************************************************
 * JsonUtils – public façade
 * ***********************************************************/
class JsonUtils
{
  public:
    /* ========= Parsing / Printing ========= */

    /* Read a JSON document from disk.
     *
     * Parameters:
     *   filePath – path to JSON file
     *   allowEmpty – when true, an empty/non-existent file will return an
     *                empty object instead of throwing an exception.
     */
    static Json parseFromFile(const fs::path &filePath, bool allowEmpty = false)
    {
        std::ifstream in{filePath, std::ios::in | std::ios::binary};
        if (!in.good()) {
            if (allowEmpty && !fs::exists(filePath))
                return Json::object();
            throw JsonIoError("Failed to open JSON file: " + filePath.string());
        }

        try {
            Json j;
            in >> j;
            return j;
        } catch (const nlohmann::json::exception &ex) {
            throw JsonParseError(
                "Failed to parse JSON file '" + filePath.string() +
                "': " + std::string{ex.what()});
        }
    }

    /* Parse JSON from a raw string view. */
    static Json parse(std::string_view jsonStr)
    {
        try {
            return Json::parse(jsonStr.begin(), jsonStr.end());
        } catch (const nlohmann::json::exception &ex) {
            throw JsonParseError("Failed to parse JSON string: " +
                                 std::string{ex.what()});
        }
    }

    /* Dump JSON to disk (pretty-printed). */
    static void dumpToFile(const fs::path &filePath,
                           const Json       &json,
                           bool              overwrite = true,
                           int               indent    = 4)
    {
        if (fs::exists(filePath) && !overwrite)
            throw JsonIoError("Refusing to overwrite existing file: " +
                              filePath.string());

        std::ofstream out{filePath, std::ios::out | std::ios::binary};
        if (!out.good())
            throw JsonIoError("Failed to open file for writing: " +
                              filePath.string());

        out << json.dump(indent);
    }

    /* Convenience wrapper for pretty printing to std::string. */
    static std::string prettyPrint(const Json &json, int indent = 4)
    {
        return json.dump(indent);
    }

    /* ========= Schema Validation =========
     *
     * A minimal schema helper that checks that required keys exist
     * and optionally that they are of a given type. For production
     * grade validation you’d likely integrate a full JSON Schema
     * validator (e.g. json-schema-validator). For typical config
     * files we keep it lightweight here.
     */

    enum class Type
    {
        Null,
        Object,
        Array,
        String,
        Boolean,
        Number,
        Any
    };

    struct Field
    {
        std::string name;
        Type        type     = Type::Any;
        bool        required = true;
    };

    static void validate(const Json &json,
                         std::string_view docName,
                         std::initializer_list<Field> expectedFields)
    {
        for (const auto &f : expectedFields) {
            if (!json.contains(f.name)) {
                if (f.required) {
                    throw JsonValidationError("JSON validation error in '" +
                                              std::string{docName} +
                                              "': missing required key '" +
                                              f.name + "'");
                }
                continue;
            }

            if (f.type == Type::Any)
                continue;

            const auto &v = json.at(f.name);
            if (!typeMatches(v, f.type)) {
                throw JsonValidationError(
                    "JSON validation error in '" + std::string{docName} +
                    "': key '" + f.name + "' is of wrong type (expected " +
                    typeToString(f.type) + ", got " + jsonTypeToString(v) +
                    ")");
            }
        }
    }

    /* ========= Diff / Patch helpers ========= */

    /* RFC 6902 style diff. */
    static Json diff(const Json &from, const Json &to)
    {
        return Json::diff(from, to);
    }

    /* RFC 7396 style merge patch. */
    static Json mergePatch(Json target, const Json &patch)
    {
        target.merge_patch(patch);
        return target;
    }

    /* ========= Deserialization helpers ========= */

    /* Extract and convert a value at key path into T
     * Optionally supply a default value.
     */
    template <typename T>
    static T getOr(const Json &json,
                   std::string_view key,
                   std::optional<T> defaultVal = std::nullopt)
    {
        auto it = json.find(key);
        if (it == json.end()) {
            if (defaultVal) {
                return *defaultVal;
            }
            throw JsonValidationError("Missing required key '" +
                                      std::string{key} + "'");
        }

        try {
            if constexpr (has_adl_from_json<T>::value) {
                T obj;
                from_json(*it, obj);
                return obj;
            } else {
                return it->get<T>();
            }
        } catch (const nlohmann::json::exception &ex) {
            throw JsonValidationError("Failed to convert key '" +
                                      std::string{key} + "': " +
                                      std::string{ex.what()});
        }
    }

  private:
    static bool typeMatches(const Json &v, Type t) noexcept
    {
        switch (t) {
        case Type::Null: return v.is_null();
        case Type::Object: return v.is_object();
        case Type::Array: return v.is_array();
        case Type::String: return v.is_string();
        case Type::Boolean: return v.is_boolean();
        case Type::Number: return v.is_number();
        case Type::Any: return true;
        default: return false;
        }
    }

    static std::string typeToString(Type t)
    {
        switch (t) {
        case Type::Null: return "null";
        case Type::Object: return "object";
        case Type::Array: return "array";
        case Type::String: return "string";
        case Type::Boolean: return "boolean";
        case Type::Number: return "number";
        case Type::Any: return "any";
        default: return "unknown";
        }
    }

    static std::string jsonTypeToString(const Json &v)
    {
        if (v.is_null())
            return "null";
        if (v.is_object())
            return "object";
        if (v.is_array())
            return "array";
        if (v.is_string())
            return "string";
        if (v.is_boolean())
            return "boolean";
        if (v.is_number())
            return "number";
        return "unknown";
    }
};

/* ************************************************************
 * Convenience macros
 * ***********************************************************/

/* Quick macro for (de)serializing strongly-typed enums to JSON. */
#define MOSAIC_JSON_DEFINE_ENUM(Type, ...)                                     \
    inline void to_json(::mosaic::util::Json &j, const Type &e)                \
    {                                                                          \
        static const char *names[] = {__VA_ARGS__};                            \
        j = names[static_cast<std::size_t>(e)];                                \
    }                                                                          \
    inline void from_json(const ::mosaic::util::Json &j, Type &e)              \
    {                                                                          \
        static const char *names[] = {__VA_ARGS__};                            \
        std::string val = j.get<std::string>();                                \
        bool        found = false;                                             \
        for (std::size_t i = 0; i < std::size(names); ++i) {                   \
            if (val == names[i]) {                                             \
                e     = static_cast<Type>(i);                                  \
                found = true;                                                  \
                break;                                                         \
            }                                                                  \
        }                                                                      \
        if (!found) {                                                          \
            throw ::mosaic::util::JsonValidationError(                         \
                "Invalid enum value '" + val + "' for enum " #Type);           \
        }                                                                      \
    }

/* ************************************************************
 * Example:
 *
 *  enum class Color { Red, Green, Blue };
 *  MOSAIC_JSON_DEFINE_ENUM(Color, "red", "green", "blue")
 *
 * ***********************************************************/

}  // namespace mosaic::util