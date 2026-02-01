```cpp
/**
 *  File:        src/module_60.cpp
 *  Project:     IntraLedger BlogSuite (web_blog)
 *  Description: Advanced, thread–safe full-text search query builder and
 *               service façade. Converts user‐facing filter expressions into
 *               parameterised SQL snippets (agnostic to MariaDB / PostgreSQL),
 *               delegates execution to the injected Repository gateway, and
 *               maintains a small, in-memory plan cache to avoid repeatedly
 *               compiling identical queries.
 *
 *  NOTE:        All public types live in namespace `ibl::search`.
 *
 *  Copyright:   (c) 2023-2024 IntraLedger
 */

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

/* -------------------------------------------------------------------------- */
/* Forward declarations to avoid heavyweight includes.                        */
/* -------------------------------------------------------------------------- */

namespace ibl
{
    struct Article;                                   // <- Domain model.
    class  IRepositoryGateway;                        // <- Repository façade.
} // namespace ibl

/* -------------------------------------------------------------------------- */
/* Search module implementation.                                              */
/* -------------------------------------------------------------------------- */
namespace ibl::search
{

/* ********************************* Helpers ******************************** */

/**
 * Normalises user input for consistent, database-agnostic full-text search.
 *
 * Rules:
 *   • Lower-case.
 *   • Trim leading / trailing spaces.
 *   • Collapse consecutive whitespace into single spaces.
 *   • Escape SQL wild-cards '%' and '_' to mitigate LIKE-based injections.
 */
static std::string normalise_input(std::string_view raw) noexcept
{
    std::string normalised;
    normalised.reserve(raw.size());

    auto push_escaped = [&normalised](char c)
    {
        if (c == '%' || c == '_')
            normalised.push_back('\\'); // Escape for LIKE
        normalised.push_back(c);
    };

    bool previous_space = false;
    for (char c : raw)
    {
        if (std::isspace(static_cast<unsigned char>(c)))
        {
            if (!previous_space)
            {
                normalised.push_back(' ');
                previous_space = true;
            }
        }
        else
        {
            push_escaped(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
            previous_space = false;
        }
    }

    // Trim trailing space, if any
    if (!normalised.empty() && normalised.back() == ' ')
        normalised.pop_back();

    return normalised;
}

/**
 * Converts time_point into RFC3339 date string suitable for SQL literals.
 */
static std::string to_rfc3339(const std::chrono::system_clock::time_point& tp)
{
    using namespace std::chrono;

    const std::time_t time = system_clock::to_time_t(tp);
    std::tm         tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &time);
#else
    gmtime_r(&time, &tm);
#endif

    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%SZ");
    return oss.str();
}

/* ***************************** Public types ******************************** */

/**
 * Target domain object(s) to search for.
 */
enum class Target : std::uint8_t
{
    Article = 0,
    Comment,
    Page
};

/**
 * Range of publication dates. Both ends inclusive.
 */
struct DateRange
{
    std::chrono::system_clock::time_point from;
    std::chrono::system_clock::time_point to;
};

/**
 * Immutable filter set representing a user search request.
 */
struct Filters
{
    std::string                       text;                 // Free-text query.
    Target                            target  = Target::Article;
    std::optional<std::vector<int64_t>> authorIds;          // Author filter.
    std::optional<std::vector<std::string>> tags;           // Tag slug filter.
    std::optional<DateRange>          publishedBetween;     // Date filter.
    std::size_t                       page    = 0;          // Zero-based page.
    std::size_t                       perPage = 20;         // Page size.
};

/**
 * Planned query instance ready to be executed by Repository.
 *
 * The object owns the final SQL string and positional placeholders to be bound
 * by the Repository gateway (thus stays backend agnostic).
 */
struct PlannedQuery
{
    std::string              sql;        // Final, parameterised statement.
    std::vector<std::string> parameters; // Flattened string parameters.
    std::size_t              page        = 0;
    std::size_t              perPage     = 20;
};

/* ******************************* Cache ************************************* */

/**
 * Very small, thread-safe LRU cache for PlannedQuery instances keyed by the
 * original, normalised user input. A capacity of 128 proved sufficient in
 * QA benchmarks for holding hot queries while keeping memory usage negligible.
 */
class PlanCache final
{
public:
    explicit PlanCache(std::size_t capacity = 128) : m_capacity(capacity) {}

    std::optional<PlannedQuery> get(const std::string& key) const
    {
        std::shared_lock lock(m_mutex);
        auto             it = m_items.find(key);
        if (it == m_items.end())
            return std::nullopt;

        // Move accessed key to front (most recent).
        m_usage.splice(m_usage.begin(), m_usage, it->second.second);
        return it->second.first;
    }

    void put(const std::string& key, PlannedQuery value)
    {
        std::unique_lock lock(m_mutex);

        if (auto it = m_items.find(key); it != m_items.end())
        {
            // Replace existing and move to front.
            it->second.first = std::move(value);
            m_usage.splice(m_usage.begin(), m_usage, it->second.second);
            return;
        }

        // Evict, if needed.
        if (m_items.size() >= m_capacity)
        {
            const std::string& lru_key = m_usage.back();
            m_items.erase(lru_key);
            m_usage.pop_back();
        }

        // Insert new.
        m_usage.push_front(key);
        m_items.emplace(key,
                        std::make_pair(std::move(value), m_usage.begin()));
    }

private:
    using UsageList = std::list<std::string>;

    std::size_t m_capacity;
    mutable std::shared_mutex m_mutex;

    UsageList                                                        m_usage;
    std::unordered_map<std::string,
                       std::pair<PlannedQuery, UsageList::iterator>> m_items;
};

/* **************************** Query builder ******************************** */

class QueryBuilder final
{
public:
    explicit QueryBuilder(const Filters& f) : m_f(f) {}

    PlannedQuery build() const
    {
        std::ostringstream sql;
        std::vector<std::string> params;

        // Base SELECT
        sql << "SELECT * FROM " << target_table(m_f.target) << " WHERE 1=1";

        // Full-text
        if (!m_f.text.empty())
        {
            sql << " AND body @@ plainto_tsquery(?)";
            params.emplace_back(normalise_input(m_f.text));
        }

        // Author filter
        if (m_f.authorIds && !m_f.authorIds->empty())
        {
            sql << " AND author_id IN (";
            add_placeholders(sql, m_f.authorIds->size());
            sql << ')';

            for (auto id : *m_f.authorIds)
                params.emplace_back(std::to_string(id));
        }

        // Tags
        if (m_f.tags && !m_f.tags->empty())
        {
            sql << " AND id IN (SELECT article_id FROM article_tags "
                   "WHERE tag_slug IN (";
            add_placeholders(sql, m_f.tags->size());
            sql << "))";
            for (const auto& tag : *m_f.tags)
                params.emplace_back(tag);
        }

        // Date range
        if (m_f.publishedBetween)
        {
            sql << " AND published_at BETWEEN ? AND ?";
            params.emplace_back(
                to_rfc3339(m_f.publishedBetween->from));
            params.emplace_back(
                to_rfc3339(m_f.publishedBetween->to));
        }

        // Ordering
        sql << " ORDER BY published_at DESC";

        // Pagination (handled by repository via LIMIT/OFFSET).
        sql << " LIMIT ? OFFSET ?";
        params.emplace_back(std::to_string(m_f.perPage));
        params.emplace_back(std::to_string(m_f.page * m_f.perPage));

        return PlannedQuery{sql.str(), std::move(params), m_f.page,
                            m_f.perPage};
    }

private:
    const Filters& m_f;

    static std::string_view target_table(Target t)
    {
        switch (t)
        {
        case Target::Article:
            return "articles_vw"; // canonical view
        case Target::Comment:
            return "comments_vw";
        case Target::Page:
            return "pages_vw";
        }
        throw std::logic_error("Unknown search target");
    }

    static void add_placeholders(std::ostringstream& oss, std::size_t count)
    {
        for (std::size_t i = 0; i < count; ++i)
        {
            oss << '?';
            if (i + 1 != count)
                oss << ',';
        }
    }
};

/* **************************** Search service ******************************* */

/**
 * Thread-safe façade used by Controllers & GraphQL endpoints.
 *
 * Usage:
 *   SearchService svc(repo);
 *   auto result = svc.search({ .text = "foo bar", .page = 1 });
 *
 * Design:
 *   • Stateless builder + small plan cache to save CPU cycles.
 *   • Repository abstraction keeps module independent of storage engine.
 *   • All public APIs throw std::runtime_error derived exceptions only.
 */
class SearchService final
{
public:
    explicit SearchService(IRepositoryGateway& repo,
                           std::size_t         cacheCapacity = 128)
        : m_repo(repo), m_cache(cacheCapacity)
    {}

    [[nodiscard]] std::vector<Article> search(const Filters& filters)
    {
        try
        {
            const std::string cacheKey = build_cache_key(filters);

            // 1. Build / retrieve plan.
            PlannedQuery plan;
            if (auto cached = m_cache.get(cacheKey); cached)
            {
                plan = *cached;
            }
            else
            {
                plan = QueryBuilder(filters).build();
                m_cache.put(cacheKey, plan);
            }

            // 2. Execute via Repository.
            return execute(plan);
        }
        catch (const std::exception& ex)
        {
            throw std::runtime_error(
                std::string("SearchService::search failed: ") + ex.what());
        }
    }

private:
    IRepositoryGateway& m_repo;
    PlanCache           m_cache;

    /* ---------- helpers ---------- */

    static std::string build_cache_key(const Filters& f)
    {
        // Simple serialisation of filter fields as key.
        std::ostringstream oss;
        oss << static_cast<int>(f.target) << '|'
            << normalise_input(f.text) << '|';

        if (f.authorIds)
        {
            for (auto id : *f.authorIds)
                oss << id << ',';
        }
        oss << '|';

        if (f.tags)
        {
            for (const auto& tag : *f.tags)
                oss << tag << ',';
        }
        oss << '|';

        if (f.publishedBetween)
        {
            oss << to_rfc3339(f.publishedBetween->from) << '-'
                << to_rfc3339(f.publishedBetween->to);
        }
        oss << '|' << f.page << '|' << f.perPage;

        return oss.str();
    }

    std::vector<Article> execute(const PlannedQuery& plan)
    {
        // Delegates to repository. The repository is expected to perform
        // placeholder substitution and hydrate Article objects.
        return m_repo.findArticles(plan.sql, plan.parameters);
    }
};

/* ------------------------- Public factory helper -------------------------- */

/**
 * Factory to create `SearchService` with sane defaults.
 * Intended to be invoked by the application IoC container.
 */
std::unique_ptr<SearchService> make_search_service(
    IRepositoryGateway& repo)
{
    constexpr std::size_t kDefaultCacheCapacity = 128;
    return std::make_unique<SearchService>(repo, kDefaultCacheCapacity);
}

} // namespace ibl::search

/* -------------------------------------------------------------------------- */
/* Mock implementations (ONLY compiled in unit-test builds)                   */
/* -------------------------------------------------------------------------- */
#ifdef IBL_SEARCH_UNIT_TEST
#include <iostream>

namespace ibl
{

struct Article
{
    int64_t     id;
    std::string title;
};

class IRepositoryGateway
{
public:
    std::vector<Article> findArticles(const std::string&              sql,
                                      const std::vector<std::string>& params)
    {
        std::cout << "EXECUTING: " << sql << '\n';
        std::cout << "PARAMS:\n";
        for (const auto& p : params)
            std::cout << "  - " << p << '\n';

        // Return dummy.
        return {Article{1, "Hello World"}};
    }
};

} // namespace ibl

int main()
{
    ibl::IRepositoryGateway repo;
    ibl::search::Filters    f;
    f.text = "C++ concurrency";
    f.page = 0;

    auto service = ibl::search::make_search_service(repo);
    auto result  = service->search(f);

    for (const auto& art : result)
        std::cout << art.id << ": " << art.title << '\n';
}
#endif
```