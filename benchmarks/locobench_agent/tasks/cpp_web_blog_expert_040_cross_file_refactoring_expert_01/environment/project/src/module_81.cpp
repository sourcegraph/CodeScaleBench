```cpp
/**
 *  IntraLedger BlogSuite – Search Service Implementation
 *
 *  File:        src/module_81.cpp
 *  Project:     web_blog
 *  Description: High–level search facility responsible for translating an
 *               end–user search request into an SQL statement, delegating the
 *               query to the underlying repository, caching the result, and
 *               returning a list of article DTOs.  The module contains:
 *
 *                 • SearchRequest – POD describing the user’s query.
 *                 • SearchResult  – Aggregated answer with pagination meta.
 *                 • LruCache      – Header-only, thread-safe LRU cache helper.
 *                 • SearchService – The façade orchestrating the workflow.
 *
 *  The service is intentionally independent of HTTP/REST concerns; it may be
 *  invoked from a controller or a background task (e.g. auto-suggest worker).
 *
 *  Author:      IntraLedger Engineering
 *  Copyright:   © 2024 IntraLedger
 *  License:     Proprietary – All Rights Reserved
 */

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iterator>
#include <list>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

// Third-party dependencies available project-wide.
#include <fmt/format.h>      // For string formatting
#include <spdlog/spdlog.h>   // For logging

// Internal headers forward-declared to avoid needless coupling.
#include "repository/article_repository.hpp"  // IArticleRepository
#include "dto/article_dto.hpp"                // ArticleDto
#include "util/sql_helpers.hpp"               // escape_like, ...
#include "config/runtime_config.hpp"          // RuntimeConfig

namespace ilb   // IntraLedger BlogSuite root namespace
{
namespace search
{

// ============================================================================
//  SearchRequest
// ============================================================================

struct SearchRequest
{
    std::string                query;               // Raw search phrase
    std::vector<std::string>   tags;                // Tag slug filters
    std::optional<std::uint64_t> authorId;          // Optional filter by author
    std::optional<std::uint32_t> year;              // Filter by publication year
    std::uint32_t              page      = 1;       // 1-based page index
    std::uint32_t              pageSize  = 20;      // Page size (max 100)
    bool                       useCache  = true;    // Allow cached results?
};

// ============================================================================
//  SearchResult
// ============================================================================

struct SearchResult
{
    std::vector<dto::ArticleDto> articles;
    std::uint32_t                page        = 1;
    std::uint32_t                pageSize    = 0;
    std::uint64_t                totalHits   = 0;
};

// ============================================================================
//  Small, header-only LRU cache (thread-safe)
//
//  The implementation utilises a doubly–linked list to track usage order and
//  an unordered_map for O(1) look-ups.  Because result sets can be large,
//  values are wrapped in std::shared_ptr to avoid expensive copies.
// ============================================================================

template <typename Key, typename Value>
class LruCache
{
public:
    explicit LruCache(std::size_t capacity)
        : m_capacity{std::max<std::size_t>(1, capacity)}
    {
    }

    void put(const Key& key, Value value)
    {
        std::unique_lock lock{m_mutex};

        auto it = m_itemsMap.find(key);
        if (it != m_itemsMap.end())
        {
            // Update value + move to front
            it->second->second = std::move(value);
            m_items.splice(m_items.begin(), m_items, it->second);
            return;
        }

        // Evict least recently used item if needed
        if (m_items.size() >= m_capacity)
        {
            const Key& lruKey = m_items.back().first;
            m_itemsMap.erase(lruKey);
            m_items.pop_back();
        }

        m_items.emplace_front(key, std::move(value));
        m_itemsMap[key] = m_items.begin();
    }

    std::optional<Value> get(const Key& key)
    {
        std::unique_lock lock{m_mutex};

        auto it = m_itemsMap.find(key);
        if (it == m_itemsMap.end())
        {
            return std::nullopt;
        }

        // Move to front (most recently used)
        m_items.splice(m_items.begin(), m_items, it->second);
        return it->second->second;
    }

    [[nodiscard]] std::size_t size() const noexcept
    {
        std::shared_lock lock{m_mutex};
        return m_items.size();
    }

private:
    using List   = std::list<std::pair<Key, Value>>;
    using Map    = std::unordered_map<Key, typename List::iterator>;

    const std::size_t m_capacity;
    List              m_items;
    Map               m_itemsMap;

    mutable std::shared_mutex m_mutex;
};

// ============================================================================
//  SearchService
// ============================================================================

class SearchService
{
public:
    explicit SearchService(std::shared_ptr<repository::IArticleRepository> repo,
                           const config::RuntimeConfig&                     cfg)
        : m_repo{std::move(repo)}
        , m_cache{cfg.search.cacheEntries}
        , m_cfg{cfg}
    {
        if (!m_repo)
        {
            throw std::invalid_argument{"SearchService requires a repository"};
        }
    }

    SearchResult search(const SearchRequest& req)
    {
        validateRequest(req);

        const auto cacheKey = makeCacheKey(req);

        if (req.useCache)
        {
            if (auto cached = m_cache.get(cacheKey); cached.has_value())
            {
                spdlog::trace("SearchService cache hit for key='{}'", cacheKey);
                return *cached;  // Copy elision or NRVO
            }
            spdlog::trace("SearchService cache miss for key='{}'", cacheKey);
        }

        // Translate request into SQL and parameters
        const auto [sql, params] = buildSql(req);

        // Delegating to repository (which may do prepared statement binding)
        auto [records, total] = m_repo->query(sql, params, req.page, req.pageSize);

        // Map entities to DTOs
        std::vector<dto::ArticleDto> dtos;
        dtos.reserve(records.size());
        std::transform(records.begin(),
                       records.end(),
                       std::back_inserter(dtos),
                       [](const auto& entity) { return dto::ArticleDto::from(entity); });

        SearchResult result;
        result.articles  = std::move(dtos);
        result.page      = req.page;
        result.pageSize  = req.pageSize;
        result.totalHits = total;

        // Store in cache
        if (req.useCache)
        {
            m_cache.put(cacheKey, result);
        }

        return result;
    }

private:
    // ----- Data -------------------------------------------------------------------
    std::shared_ptr<repository::IArticleRepository> m_repo;
    LruCache<std::string, SearchResult>            m_cache;
    const config::RuntimeConfig&                   m_cfg;

    // ----- Validation -------------------------------------------------------------
    static void validateRequest(const SearchRequest& req)
    {
        if (req.pageSize == 0 || req.pageSize > 100)
        {
            throw std::out_of_range{"pageSize must be within 1..100"};
        }
        if (req.page == 0)
        {
            throw std::out_of_range{"page must be >= 1"};
        }
    }

    // ----- Cache-Key Builder ------------------------------------------------------
    static std::string makeCacheKey(const SearchRequest& r)
    {
        std::ostringstream oss;
        oss << r.query << '|';
        for (const auto& tag : r.tags)
        {
            oss << tag << ',';
        }
        oss << '|';
        if (r.authorId) oss << *r.authorId;
        oss << '|';
        if (r.year) oss << *r.year;
        oss << '|' << r.page << '|' << r.pageSize;
        return std::move(oss).str();
    }

    // ----- SQL Builder ------------------------------------------------------------
    // Returns (SQL, params)
    static std::pair<std::string, std::vector<std::string>> buildSql(const SearchRequest& r)
    {
        std::vector<std::string> params;
        std::ostringstream sql;

        sql << "SELECT SQL_CALC_FOUND_ROWS  "
               " a.id, a.title, a.slug, a.excerpt, a.published_at, "
               " u.id AS author_id, u.display_name "
               "FROM articles a "
               "JOIN users u ON u.id = a.author_id "
               "WHERE a.is_published = 1 ";

        // Full-text search
        if (!r.query.empty())
        {
            sql << "AND MATCH(a.title, a.body, a.excerpt) "
                   "AGAINST (? IN BOOLEAN MODE) ";
            params.emplace_back(r.query);
        }

        // Tag filter
        if (!r.tags.empty())
        {
            sql << "AND EXISTS ( SELECT 1 FROM article_tags at "
                   "            JOIN tags t ON t.id = at.tag_id "
                   "           WHERE at.article_id = a.id "
                   "             AND t.slug IN (";
            for (std::size_t i = 0; i < r.tags.size(); ++i)
            {
                sql << (i ? ",?" : "?");
                params.emplace_back(r.tags[i]);
            }
            sql << ") ) ";
        }

        // Author
        if (r.authorId.has_value())
        {
            sql << "AND a.author_id = ? ";
            params.emplace_back(std::to_string(*r.authorId));
        }

        // Year
        if (r.year.has_value())
        {
            sql << "AND YEAR(a.published_at) = ? ";
            params.emplace_back(std::to_string(*r.year));
        }

        // Ordering
        sql << "ORDER BY a.published_at DESC ";

        // Pagination
        sql << "LIMIT ? OFFSET ? ";
        params.emplace_back(std::to_string(r.pageSize));
        std::uint32_t offset = (r.page - 1) * r.pageSize;
        params.emplace_back(std::to_string(offset));

        return {std::move(sql).str(), std::move(params)};
    }
};

// ============================================================================
//  Factory helper for DI containers (static-link friendly)
// ============================================================================
std::shared_ptr<SearchService> makeSearchService(
    std::shared_ptr<repository::IArticleRepository> repo,
    const config::RuntimeConfig&                    cfg)
{
    return std::make_shared<SearchService>(std::move(repo), cfg);
}

}  // namespace search
}  // namespace ilb
```