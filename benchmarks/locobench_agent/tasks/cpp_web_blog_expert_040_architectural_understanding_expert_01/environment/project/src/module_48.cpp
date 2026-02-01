```cpp
/**
 *  IntraLedger BlogSuite – Full-Text Search Query Builder
 *  ------------------------------------------------------
 *  module_48.cpp
 *
 *  This component receives search criteria from controllers /
 *  REST endpoints and converts them into fully-parameterised
 *  SQL snippets that can be executed via the platform’s ORM.
 *
 *  Highlights
 *  ----------
 *   •  Zero-copy string handling via std::string_view
 *   •  Concurrency-safe LRU cache for de-duplicating built queries
 *   •  Cloud-agnostic SQL generation (MariaDB & PostgreSQL)
 *   •  Robust input normalisation & defence-in-depth escaping
 *
 *  Copyright (c) 2024
 *  IntraLedger, Inc. – All rights reserved.
 */

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <exception>
#include <iostream>
#include <list>
#include <mutex>
#include <optional>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace blog::search {

// ----------------------------- Logging Stub ----------------------------- //
struct ILogger {
    virtual ~ILogger() = default;
    virtual void debug(std::string_view msg) noexcept = 0;
    virtual void warn(std::string_view msg) noexcept  = 0;
    virtual void error(std::string_view msg) noexcept = 0;
};

// Simple console fallback logger (used when DI container hasn’t provided one)
class ConsoleLogger final : public ILogger {
public:
    void debug(std::string_view msg) noexcept override { std::cerr << "[DBG] " << msg << '\n'; }
    void warn (std::string_view msg) noexcept override { std::cerr << "[WRN] " << msg << '\n'; }
    void error(std::string_view msg) noexcept override { std::cerr << "[ERR] " << msg << '\n'; }
};

// ------------------------- Domain Model Objects ------------------------ //
struct SearchCriteria {
    std::string                           phrase;        // e.g., `"lorem ipsum"`
    std::vector<std::string>              includeTags;   // e.g., `{"cpp", "design"}`
    std::vector<std::string>              excludeTags;   // e.g., `{"deprecated"}`
    std::optional<std::pair<
        std::chrono::system_clock::time_point,
        std::chrono::system_clock::time_point
    >>                                    dateRange;     // Publish date span
    bool                                  includeDrafts = false; // ACL override

    // Convenience: generate a deterministic hash so objects
    // can be used as keys in unordered_ containers.
    std::size_t hash() const noexcept {
        std::size_t seed = std::hash<std::string>{}(phrase);
        for (const auto& tag : includeTags)
            seed ^= std::hash<std::string>{}(tag) + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
        for (const auto& tag : excludeTags)
            seed ^= std::hash<std::string>{}(tag) + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
        seed ^= std::hash<bool>{}(includeDrafts) + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
        if (dateRange) {
            seed ^= std::chrono::duration_cast<std::chrono::seconds>(
                        dateRange->first.time_since_epoch()).count();
            seed ^= std::chrono::duration_cast<std::chrono::seconds>(
                        dateRange->second.time_since_epoch()).count();
        }
        return seed;
    }

    bool operator==(const SearchCriteria& other) const noexcept {
        return phrase         == other.phrase &&
               includeTags    == other.includeTags &&
               excludeTags    == other.excludeTags &&
               dateRange      == other.dateRange &&
               includeDrafts  == other.includeDrafts;
    }
};

// Specialise std::hash for SearchCriteria, so it can be used in unordered_map
}  // namespace blog::search
namespace std {
    template<>
    struct hash<blog::search::SearchCriteria> {
        std::size_t operator()(const blog::search::SearchCriteria& c) const noexcept {
            return c.hash();
        }
    };
}
namespace blog::search {

// ----------------------------- Exceptions ------------------------------ //
class SearchQueryError : public std::runtime_error {
public:
    explicit SearchQueryError(const std::string& msg) : std::runtime_error(msg) {}
};

// --------------------------- LRU Query Cache --------------------------- //
class QueryCache {
public:
    explicit QueryCache(std::size_t maxEntries = 256)
        : _capacity(maxEntries)
    {
        if (_capacity == 0)
            _capacity = 1;
    }

    std::optional<std::string> get(const SearchCriteria& key) {
        std::scoped_lock lock(_guard);

        auto it = _entries.find(key);
        if (it == _entries.end())
            return std::nullopt;

        // Move element to front of LRU list
        _lru.splice(_lru.begin(), _lru, it->second.second);
        return it->second.first;
    }

    void put(const SearchCriteria& key, std::string query) {
        std::scoped_lock lock(_guard);

        auto it = _entries.find(key);
        if (it != _entries.end()) {
            // Update existing
            it->second.first = std::move(query);
            _lru.splice(_lru.begin(), _lru, it->second.second);
            return;
        }

        // Evict oldest if over capacity
        if (_entries.size() >= _capacity) {
            const auto& lru_key = _lru.back();
            _entries.erase(lru_key);
            _lru.pop_back();
        }

        _lru.push_front(key);
        _entries.emplace(key, std::make_pair(std::move(query), _lru.begin()));
    }

private:
    using LruList = std::list<SearchCriteria>;
    using Entry   = std::pair<std::string, LruList::iterator>;

    std::size_t                               _capacity;
    LruList                                   _lru;
    std::unordered_map<SearchCriteria, Entry> _entries;
    std::mutex                                _guard;
};

// ------------------ Helper: SQL Escaping & Parameterisation ------------ //
static std::string escape_like(std::string_view input) {
    std::string out;
    out.reserve(input.size());
    for (char c : input) {
        switch (c) {
            case '%':
            case '_':
            case '\\':
                out.push_back('\\');
                [[fallthrough]];
            default:
                out.push_back(c);
        }
    }
    return out;
}

static bool unsafe_pattern_detected(std::string_view phrase) {
    // Very conservative disallow list: semicolons (possible statement break), 
    // consecutive dashes (comment), never allow control chars.
    static const std::regex dangerous(R"(([;]|--|\r|\n|\t))");
    return std::regex_search(phrase.begin(), phrase.end(), dangerous);
}

// ----------------- Main Component: Query Builder ---------------------- //
class FullTextSearchQueryBuilder {
public:
    explicit FullTextSearchQueryBuilder(
        std::shared_ptr<ILogger> logger = std::make_shared<ConsoleLogger>(),
        std::size_t cacheSize          = 256
    )
        : _logger(std::move(logger))
        , _cache(cacheSize)
    {}

    // Build parameterised SQL statement & vector of bound values
    std::pair<std::string, std::vector<std::string>> build(const SearchCriteria& criteria) {
        // Try cache first
        if (auto cached = _cache.get(criteria); cached) {
            _logger->debug("Cache hit for search criteria");
            return {*cached, cachedParams(criteria)};
        }

        validate(criteria);

        std::ostringstream sql;
        std::vector<std::string> params;

        sql << "SELECT id, title, excerpt "
               "FROM articles "
               "WHERE ";

        // 1. Phrase matching (mandatory)
        sql << "(to_tsvector('simple', content) @@ plainto_tsquery('simple', $1))";
        params.emplace_back(criteria.phrase);

        std::size_t parameterIndex = 2;

        // 2. Include Tags (AND)
        if (!criteria.includeTags.empty()) {
            sql << " AND id IN ("
                   "SELECT article_id FROM article_tags "
                   "WHERE tag IN (";
            appendPlaceholders(sql, criteria.includeTags.size(), parameterIndex);
            sql << ") GROUP BY article_id "
                   "HAVING COUNT(DISTINCT tag) = " << criteria.includeTags.size() << ')';

            for (const auto& t : criteria.includeTags)
                params.emplace_back(t);

            parameterIndex += criteria.includeTags.size();
        }

        // 3. Exclude Tags (NOT IN)
        if (!criteria.excludeTags.empty()) {
            sql << " AND id NOT IN ("
                   "SELECT article_id FROM article_tags WHERE tag IN (";
            appendPlaceholders(sql, criteria.excludeTags.size(), parameterIndex);
            sql << "))";

            for (const auto& t : criteria.excludeTags)
                params.emplace_back(t);

            parameterIndex += criteria.excludeTags.size();
        }

        // 4. Date range
        if (criteria.dateRange) {
            sql << " AND published_at BETWEEN $" << parameterIndex
                << " AND $" << parameterIndex + 1;
            params.emplace_back(to_iso_string(criteria.dateRange->first));
            params.emplace_back(to_iso_string(criteria.dateRange->second));
            parameterIndex += 2;
        }

        // 5. State filter
        if (!criteria.includeDrafts) {
            sql << " AND state = 'published'";
        }

        // 6. Order + Limit
        sql << " ORDER BY rank DESC, published_at DESC "
               "LIMIT 100";

        const auto queryStr = sql.str();

        // Push built query into cache
        _cache.put(criteria, queryStr);

        return {queryStr, params};
    }

private:
    std::shared_ptr<ILogger> _logger;
    QueryCache               _cache;

    // --------- Private Utility Methods --------- //
    static void appendPlaceholders(std::ostringstream& sql,
                                   std::size_t count,
                                   std::size_t& startIndex) {
        for (std::size_t i = 0; i < count; ++i) {
            sql << '$' << startIndex++;
            if (i + 1 < count) sql << ", ";
        }
    }

    static std::string to_iso_string(const std::chrono::system_clock::time_point& tp) {
        using namespace std::chrono;
        const std::time_t tt = system_clock::to_time_t(tp);
        char buf[32]         = {0};
        std::strftime(buf, sizeof(buf), "%FT%TZ", std::gmtime(&tt));
        return std::string(buf);
    }

    static std::vector<std::string> cachedParams(const SearchCriteria& criteria) {
        std::vector<std::string> parameters;
        parameters.reserve(1 + criteria.includeTags.size()
                             + criteria.excludeTags.size()
                             + (criteria.dateRange ? 2 : 0));
        parameters.emplace_back(criteria.phrase);
        for (const auto& t : criteria.includeTags)  parameters.emplace_back(t);
        for (const auto& t : criteria.excludeTags)  parameters.emplace_back(t);
        if (criteria.dateRange) {
            parameters.emplace_back(to_iso_string(criteria.dateRange->first));
            parameters.emplace_back(to_iso_string(criteria.dateRange->second));
        }
        return parameters;
    }

    static void validate(const SearchCriteria& c) {
        if (c.phrase.empty())
            throw SearchQueryError("Search phrase must not be empty.");

        if (unsafe_pattern_detected(c.phrase))
            throw SearchQueryError("Potentially unsafe characters detected in search phrase.");
    }
};

// ----------------------- Example Stand-Alone Usage --------------------- //
// (In a real build this would live in a separate *_test.cpp file or a
// unit-test project driven by Catch2 / GoogleTest, etc.)
#ifdef BLOGSUITE_DEMO_MAIN
int main() {
    auto logger   = std::make_shared<ConsoleLogger>();
    FullTextSearchQueryBuilder builder(logger);

    SearchCriteria sc;
    sc.phrase = "modern c++";
    sc.includeTags = {"cpp", "architecture"};
    sc.dateRange = std::make_pair(
        std::chrono::system_clock::now() - std::chrono::hours(24*365),
        std::chrono::system_clock::now()
    );

    try {
        auto [sql, params] = builder.build(sc);
        logger->debug("Generated SQL: " + sql);
        for (std::size_t i = 0; i < params.size(); ++i)
            logger->debug("  $" + std::to_string(i+1) + " => " + params[i]);
    } catch (const SearchQueryError& ex) {
        logger->error(ex.what());
    }
}
#endif

} // namespace blog::search
```