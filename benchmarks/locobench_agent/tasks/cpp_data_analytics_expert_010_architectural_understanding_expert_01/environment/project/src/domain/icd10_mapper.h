#pragma once
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File:    cardio_insight_360/src/domain/icd10_mapper.h
 *
 *  Description:
 *      Domain utility that maintains an in-memory bi-directional map between
 *      ICD-10 codes and their domain-specific metadata (high-level category,
 *      human-readable description, etc.).  The implementation balances fast
 *      concurrent look-ups with the ability to hot-patch mappings at runtime
 *      (e.g. when the terminology domain team releases new or corrected codes).
 *
 *  Design notes:
 *      • Fast path look-ups are entirely lock-free thanks to an immutable
 *        std::unordered_map that is only replaced (copy-on-write) when a
 *        mutation occurs.
 *      • Light-weight regex validation ensures that codes follow the official
 *        ICD-10 pattern (e.g. “I21.9”).  This catches typos early.
 *      • The component is header-only to avoid symbol-visibility issues when
 *        linking the monolithic binary with dozens of shared libraries.
 *      • All string parameters use std::string_view to avoid unnecessary
 *        allocations along the hot path.
 *
 *  Thread-safety:
 *      • Readers never block each other.
 *      • Writers obtain a unique lock and publish a new shared_ptr snapshot.
 *
 *  Author:  CardioInsight360 Core Team
 *  License: Proprietary – All Rights Reserved
 */

#include <algorithm>
#include <atomic>
#include <cctype>
#include <memory>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ci360::domain {

/**
 * High-level ICD-10 category that aligns with CardioInsight360’s analytics
 * modules and reporting dashboards.
 */
enum class Icd10Category {
    Cardiovascular,
    Respiratory,
    Endocrine,
    Neurological,
    Musculoskeletal,
    Oncology,
    Infectious,
    Undefined
};

/**
 * Convert enum to human-readable string.
 */
inline constexpr std::string_view to_string(Icd10Category category) noexcept {
    switch (category) {
        case Icd10Category::Cardiovascular:  return "Cardiovascular";
        case Icd10Category::Respiratory:     return "Respiratory";
        case Icd10Category::Endocrine:       return "Endocrine";
        case Icd10Category::Neurological:    return "Neurological";
        case Icd10Category::Musculoskeletal: return "Musculoskeletal";
        case Icd10Category::Oncology:        return "Oncology";
        case Icd10Category::Infectious:      return "Infectious";
        default:                             return "Undefined";
    }
}

/**
 * Immutable value object that represents a single ICD-10 mapping entry.
 */
struct Icd10Entry {
    std::string      code;        // Canonical ICD-10 code, e.g. "I21.9"
    std::string      description; // Human-readable description
    Icd10Category    category {}; // High-level category
};

/**
 * ICD-10 Mapper – fast thread-safe look-ups & hot-patchable dictionary.
 */
class Icd10Mapper
{
public:
    /* Singleton accessor --------------------------------------------------- */
    static Icd10Mapper& instance()
    {
        static Icd10Mapper inst;
        return inst;
    }

    /* Deleted copy operations – singleton semantics ------------------------ */
    Icd10Mapper(const Icd10Mapper&)            = delete;
    Icd10Mapper& operator=(const Icd10Mapper&) = delete;
    Icd10Mapper(Icd10Mapper&&)                 = delete;
    Icd10Mapper& operator=(Icd10Mapper&&)      = delete;

    /* Public API ----------------------------------------------------------- */

    /**
     * Checks whether the provided ICD-10 code is syntactically valid AND
     * present in the internal dictionary.
     */
    [[nodiscard]] bool exists(std::string_view code) const noexcept
    {
        if (!is_valid_format(code)) { return false; }
        const auto local = _map.load();
        return local->find(normalize(code)) != local->end();
    }

    /**
     * Fetch the description for the given code.  Returns std::nullopt if the
     * code is unknown or invalid.
     */
    [[nodiscard]] std::optional<std::string_view>
    description(std::string_view code) const noexcept
    {
        const auto localCode = normalize(code);
        const auto local     = _map.load();
        auto       it        = local->find(localCode);
        if (it == local->end()) { return std::nullopt; }
        return it->second.description;
    }

    /**
     * Fetch the category for a given code.  Returns std::nullopt if the code
     * is unknown or invalid.
     */
    [[nodiscard]] std::optional<Icd10Category>
    category(std::string_view code) const noexcept
    {
        const auto localCode = normalize(code);
        const auto local     = _map.load();
        auto       it        = local->find(localCode);
        if (it == local->end()) { return std::nullopt; }
        return it->second.category;
    }

    /**
     * Search codes by case-insensitive substring match in either the code or
     * description field.  Used by UI autocomplete widgets.
     */
    [[nodiscard]] std::vector<Icd10Entry>
    search(std::string_view term, std::size_t maxResults = 20) const
    {
        const auto local      = _map.load();
        std::vector<Icd10Entry> results;
        results.reserve(maxResults);

        const std::string termLower = to_lower(std::string{term});

        for (const auto& [key, entry] : *local) {
            if (results.size() >= maxResults) { break; }

            const std::string codeLower = to_lower(key);
            const std::string descLower = to_lower(entry.description);

            if (codeLower.find(termLower) != std::string::npos ||
                descLower.find(termLower) != std::string::npos)
            {
                results.push_back(entry);
            }
        }
        return results;
    }

    /**
     * Hot-patch or insert a new mapping.  Writer obtains exclusive lock,
     * clones the current map, applies modification, and publishes it.
     */
    void upsert(Icd10Entry entry)
    {
        if (!is_valid_format(entry.code)) {
            throw std::invalid_argument("Invalid ICD-10 format: " + entry.code);
        }

        const std::string key = normalize(entry.code);

        std::unique_lock lock(_writeMutex);

        // Clone current snapshot
        auto newMap = std::make_shared<MapType>(*_map.load());

        // Insert / overwrite
        (*newMap)[key] = std::move(entry);

        // Publish new snapshot atomically
        _map.store(std::move(newMap));
    }

    /**
     * Bulk load a set of entries.  Overwrites existing duplicates.
     * Exception safety: strong guarantee – either everything is committed or
     * the state remains unchanged.
     */
    void bulk_load(const std::vector<Icd10Entry>& entries)
    {
        // Validate first (can throw), no partial publishes
        for (const auto& e : entries) {
            if (!is_valid_format(e.code)) {
                throw std::invalid_argument("Invalid ICD-10 code in bulk load: " + e.code);
            }
        }

        std::unique_lock lock(_writeMutex);
        auto newMap = std::make_shared<MapType>(*_map.load());
        for (const auto& e : entries) {
            (*newMap)[normalize(e.code)] = e;
        }
        _map.store(std::move(newMap));
    }

private:
    /* Private types -------------------------------------------------------- */
    using MapType = std::unordered_map<std::string, Icd10Entry>;

    /* Ctor (private – singleton) ------------------------------------------- */
    Icd10Mapper()
        : _map(std::make_shared<MapType>(initial_seed()))
    {}

    /* Internal helpers ----------------------------------------------------- */

    static bool is_valid_format(std::string_view code) noexcept
    {
        // Official ICD-10: One letter, 2 digits, optional '.' and up to 4
        // alphanumeric characters. Examples: I21.9, J45
        static const std::regex kRegex(R"(^[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?$)",
                                       std::regex::ECMAScript | std::regex::icase);

        return !code.empty() && std::regex_match(code.begin(), code.end(), kRegex);
    }

    /* Normalize code to uppercase without leading/trailing whitespace */
    static std::string normalize(std::string_view code)
    {
        std::string s;
        s.reserve(code.size());
        std::for_each(code.begin(), code.end(), [&s](char c) {
            if (!std::isspace(static_cast<unsigned char>(c))) {
                s.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
            }
        });
        return s;
    }

    static std::string to_lower(std::string s)
    {
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        return s;
    }

    /* Seed a minimal in-memory dictionary so the mapper is immediately usable */
    static MapType initial_seed()
    {
        MapType map;
        auto insert = [&map](std::string code,
                             std::string desc,
                             Icd10Category cat)
        {
            map.emplace(std::move(code),
                        Icd10Entry{code, std::move(desc), cat});
        };

        insert("I21.9", "Acute myocardial infarction, unspecified",
               Icd10Category::Cardiovascular);
        insert("I50.9", "Heart failure, unspecified",
               Icd10Category::Cardiovascular);
        insert("I10",   "Essential (primary) hypertension",
               Icd10Category::Cardiovascular);
        insert("I48.0", "Paroxysmal atrial fibrillation",
               Icd10Category::Cardiovascular);
        insert("E11.9", "Type 2 diabetes mellitus without complications",
               Icd10Category::Endocrine);
        insert("J45.9", "Asthma, unspecified",
               Icd10Category::Respiratory);
        insert("G40.9", "Epilepsy, unspecified",
               Icd10Category::Neurological);
        insert("C50.9", "Malignant neoplasm of breast, unspecified",
               Icd10Category::Oncology);
        insert("M54.5", "Low back pain",
               Icd10Category::Musculoskeletal);
        insert("B34.9", "Viral infection, unspecified",
               Icd10Category::Infectious);
        return map;
    }

    /* Data members --------------------------------------------------------- */
    std::atomic<std::shared_ptr<MapType>> _map;    // Atomic snapshot pointer
    mutable std::shared_mutex            _writeMutex; // Serialize writers
};

} // namespace ci360::domain