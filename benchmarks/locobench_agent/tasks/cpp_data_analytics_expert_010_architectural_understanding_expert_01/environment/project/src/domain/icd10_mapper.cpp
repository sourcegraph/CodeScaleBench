```cpp
/**
 * cardio_insight_360/src/domain/icd10_mapper.cpp
 *
 * Implementation of the ICD-10 mapper used across CardioInsight360.
 *
 * Responsibilities
 * =================
 *  • Provide fast, thread-safe look-ups from ICD-10 code → metadata
 *  • Lazy-load mapping tables either from a built-in static table or an
 *    external, auto-refreshing CSV/JSON resource shipped with the product
 *  • Serve as a canonical source of truth for all downstream components
 *    (ETL pipeline, streaming alerts, cohort analytics, UI dashboards, etc.)
 *
 * Design Notes
 * ============
 *  • Singleton pattern guarantees that all subsystems share one cache.
 *  • Read-most-ly workloads are protected by std::shared_mutex to allow
 *    concurrent readers while serializing refresh operations.
 *  • Hot-path look-ups avoid dynamic allocation by returning std::string_view
 *    into an internal, immutable string arena.
 *  • Observer hooks broadcast reload events so that ETL stages can invalidate
 *    dependent caches without recompilation (see Observer_Pattern docs).
 *
 * (c) 2023-2024 CardioInsight, Inc. – All rights reserved.
 */

#include "domain/icd10_mapper.hpp"     // ↓ Public interface/definitions
#include "infrastructure/observer.hpp" //  ↳ Lightweight Observer pattern
#include "util/file_utils.hpp"         //  ↳ Small helpers (CSV parsing, etc.)

// 3rd-party
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

// STL
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <unordered_map>
#include <vector>

using namespace std::chrono_literals;
namespace fs = std::filesystem;
namespace ci  = cardio_insight;

namespace cardio_insight::domain
{

// ──────────────────────────────────────────────────────────────────────────────
//  Private helpers
// ──────────────────────────────────────────────────────────────────────────────
namespace
{
    /**
     * Very small CSV parser tailored to the shipping ICD-10 table (<10,000 rows).
     * Delimiter is semicolon for locale independence.
     */
    std::vector<std::array<std::string, 3>>
    parseCsv(const fs::path& p)
    {
        std::ifstream in(p);
        if (!in.is_open())
            throw std::runtime_error("Cannot open ICD-10 CSV file: " + p.string());

        std::vector<std::array<std::string, 3>> rows;
        rows.reserve(10000); // typical size

        std::string line;
        while (std::getline(in, line))
        {
            if (line.empty() || line[0] == '#')
                continue; // skip comments

            std::array<std::string, 3> cols;
            std::stringstream        ss(line);
            for (std::size_t i = 0; i < 3; ++i)
            {
                if (!std::getline(ss, cols[i], ';'))
                    throw std::runtime_error("Malformed line in ICD-10 CSV: " + line);
            }
            rows.emplace_back(std::move(cols));
        }
        return rows;
    }

    /**
     * Fallback, minimal JSON schema:
     * [
     *   { "code": "I21.4", "description": "Acute subendocardial MI", "category": "Ischemic Heart" }
     * ]
     */
    std::vector<std::array<std::string, 3>>
    parseJson(const fs::path& p)
    {
        std::ifstream in(p);
        if (!in.is_open())
            throw std::runtime_error("Cannot open ICD-10 JSON file: " + p.string());

        auto json = nlohmann::json::parse(in, nullptr, /*allow_exceptions*/ true);

        std::vector<std::array<std::string, 3>> rows;
        rows.reserve(json.size());
        for (const auto& el : json)
        {
            rows.push_back(
                { el.at("code").get<std::string>(),
                  el.at("description").get<std::string>(),
                  el.value("category", "") });
        }
        return rows;
    }

} // anonymous namespace

// ──────────────────────────────────────────────────────────────────────────────
//  ICD10Mapper :: pImpl
// ──────────────────────────────────────────────────────────────────────────────
class ICD10Mapper::Impl
{
public:
    Impl() = default;

    /**
     * Thread-safe lookup. Returns |nullptr| if code not found.
     */
    const ICD10Entry* lookup(std::string_view code) const
    {
        std::shared_lock lk(mutex_);
        auto             it = map_.find(code);
        if (it == map_.end()) return nullptr;
        return &it->second;
    }

    /**
     * Load mapping from |path|. Multiple calls are allowed; the latest takes over.
     * Heavy I/O is protected by exclusive lock.
     */
    void load(const fs::path& path)
    {
        auto start = std::chrono::steady_clock::now();
        spdlog::info("Loading ICD-10 mapping table from {}", path.string());

        // Parse file outside lock for better concurrency.
        std::vector<std::array<std::string, 3>> rows;

        if (path.extension() == ".csv")
            rows = parseCsv(path);
        else if (path.extension() == ".json")
            rows = parseJson(path);
        else
            throw std::invalid_argument("Unsupported ICD-10 table format: " + path.string());

        // Build new maps.
        std::unordered_map<std::string_view, ICD10Entry, ci::util::StableStringHash,
                           std::equal_to<>>
            newMap;
        newMap.reserve(rows.size());

        // We store all raw strings inside |arena_| for stable storage.
        std::vector<std::string> newArena;
        newArena.reserve(rows.size() * 3);

        for (auto&& r : rows)
        {
            // Code
            newArena.emplace_back(std::move(r[0]));
            std::string_view codeView = newArena.back();

            // Description
            newArena.emplace_back(std::move(r[1]));
            std::string_view descView = newArena.back();

            // Category
            newArena.emplace_back(std::move(r[2]));
            std::string_view catView = newArena.back();

            ICD10Entry entry { codeView, descView, catView };
            newMap.emplace(codeView, std::move(entry));
        }

        // Commit
        {
            std::unique_lock lk(mutex_);
            map_   = std::move(newMap);
            arena_ = std::move(newArena);
        }

        ci::infrastructure::ObserverRegistry::publish(Event::ICD10_TABLE_RELOADED);

        auto elapsed = std::chrono::steady_clock::now() - start;
        spdlog::info("Loaded {} ICD-10 entries in {} ms",
                     map_.size(),
                     std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count());
    }

    size_t size() const
    {
        std::shared_lock lk(mutex_);
        return map_.size();
    }

private:
    // We need a stable allocator to guarantee string_view lifetime. The arena_
    // owns all raw strings.
    std::vector<std::string> arena_;

    // Custom hash to support heterogeneous lookup via std::string_view.
    std::unordered_map<std::string_view, ICD10Entry, ci::util::StableStringHash,
                       std::equal_to<>>
        map_;

    mutable std::shared_mutex mutex_;
};

// ──────────────────────────────────────────────────────────────────────────────
//  ICD10Mapper – public API
// ──────────────────────────────────────────────────────────────────────────────

ICD10Mapper& ICD10Mapper::instance()
{
    static ICD10Mapper inst;
    return inst;
}

ICD10Mapper::ICD10Mapper() : impl_(std::make_unique<Impl>())
{
    /* Load built-in fallback table (compiled-in resource) */
    const fs::path defaultResource =
        ci::util::resourceRoot() / "icd10" / "icd10_fallback.csv";

    try
    {
        if (fs::exists(defaultResource))
            impl_->load(defaultResource);
        else
            spdlog::warn("ICD-10 fallback resource missing: {}", defaultResource.string());
    }
    catch (const std::exception& ex)
    {
        spdlog::error("Failed to load ICD-10 fallback table: {}", ex.what());
        throw; // fail fast – we cannot run without a mapping table.
    }
}

ICD10Mapper::~ICD10Mapper() = default;

const ICD10Entry* ICD10Mapper::find(std::string_view code) const
{
    return impl_->lookup(ci::util::normalizeCode(code)); // ensures upper-case, trim, etc.
}

void ICD10Mapper::reload(const fs::path& p)
{
    impl_->load(p);
}

size_t ICD10Mapper::size() const
{
    return impl_->size();
}

} // namespace cardio_insight::domain
```
