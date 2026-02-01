```cpp
#pragma once
/**************************************************************************************************
 *  File:        SearchService.h
 *  Project:     MosaicBoard Studio – Web Dashboard
 *
 *  Description:
 *      SearchService is an application-level singleton responsible for indexing and full-text
 *      search across every asset that may exist inside MosaicBoard Studio: dashboards, tiles,
 *      data sources, user collections, etc.  The service provides a thread-safe API, incremental
 *      indexing, on-disk persistence through SQLite/FTS5, and an in-memory LRU cache to avoid
 *      expensive disk hits for frequently repeated queries.
 *
 *  NOTE:
 *      This header is self-contained.  The implementation is placed directly in the header to
 *      keep the example functional without additional compilation units.
 *
 *  Author:      MosaicBoard Studio Core Team
 *  License:     MIT (see LICENSE.txt)
 **************************************************************************************************/
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <list>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef MBS_ENABLE_SQLITE
    #include <sqlite3.h>
#endif

namespace mbs { // MosaicBoard Studio
// =================================================================================================
//  Utility types
// =================================================================================================

/**
 *  SearchQuery – user-level search request
 */
struct SearchQuery
{
    std::string                     text;           // Raw search string (tokenized internally)
    std::map<std::string, std::string> filters;     // Arbitrary key:value filters (e.g. type=tile)
    std::size_t                     limit     {50}; // Pagination – max results returned
    std::size_t                     offset    {0};  // Pagination – starting row

    // Generates a canonical key used by the LRU cache
    [[nodiscard]] std::string cacheKey() const
    {
        std::ostringstream oss;
        oss << text << '|';
        for (const auto& kv : filters) { oss << kv.first << '=' << kv.second << ';'; }
        oss << '#' << limit << '/' << offset;
        return oss.str();
    }
};

/**
 *  SearchResultItem – single hit
 */
struct SearchResultItem
{
    std::string id;         // Tile/dashboard/asset id
    std::string type;       // "tile" | "dashboard" | "datasource" | etc.
    std::string title;      // Human-readable label
    double      score;      // Full-text score (higher == better)
};

/**
 *  SearchResult – paginated container of hits
 */
struct SearchResult
{
    std::vector<SearchResultItem> hits;
    std::size_t                   totalCount {0}; // Total matching records (ignoring pagination)
};

// =================================================================================================
//  LRUCache – minimal header-only implementation
// =================================================================================================

template <typename Key, typename Value>
class LRUCache
{
public:
    explicit LRUCache(std::size_t capacity) : _capacity{capacity} {}

    bool get(const Key& key, Value& out)
    {
        std::unique_lock lock{_mtx};
        auto it = _map.find(key);
        if (it == _map.end()) { return false; }

        // Move to front
        _order.splice(_order.begin(), _order, it->second.second);
        out = it->second.first;
        return true;
    }

    void put(const Key& key, const Value& value)
    {
        std::unique_lock lock{_mtx};

        auto it = _map.find(key);
        if (it != _map.end())
        {
            it->second.first = value;
            _order.splice(_order.begin(), _order, it->second.second);
            return;
        }

        if (_map.size() >= _capacity) // Evict LRU
        {
            const Key& lruKey = _order.back();
            _map.erase(lruKey);
            _order.pop_back();
        }

        _order.push_front(key);
        _map.emplace(key, std::make_pair(value, _order.begin()));
    }

    void clear()
    {
        std::unique_lock lock{_mtx};
        _map.clear();
        _order.clear();
    }

private:
    using ListIt = typename std::list<Key>::iterator;
    std::size_t                                               _capacity;
    std::list<Key>                                            _order;
    std::unordered_map<Key, std::pair<Value, ListIt>>         _map;
    std::mutex                                                _mtx;
};

// =================================================================================================
//  SearchService – main entry point
// =================================================================================================

class SearchService
{
public:
    // ---------------------------------------------------------------------
    //  Singleton Helpers
    // ---------------------------------------------------------------------
    static SearchService& instance()
    {
        static SearchService _instance;
        return _instance;
    }

    SearchService(const SearchService&)            = delete;
    SearchService& operator=(const SearchService&) = delete;
    SearchService(SearchService&&)                 = delete;
    SearchService& operator=(SearchService&&)      = delete;

    // ---------------------------------------------------------------------
    //  Public API
    // ---------------------------------------------------------------------

    /*
     * Adds or updates a record inside the full-text index.
     *
     * Params:
     *   id        – globally unique component ID
     *   type      – e.g. "tile", "dashboard"
     *   title     – human-readable title (subject to full-text search)
     *   payload   – additional JSON or string payload that should be indexed
     */
    void indexRecord(std::string_view id,
                     std::string_view type,
                     std::string_view title,
                     std::string_view payload);

    /*
     * Removes a record (all versions) from the index.
     */
    void removeRecord(std::string_view id);

    /*
     * Executes a query against the index.  Results are automatically cached.
     */
    [[nodiscard]] SearchResult search(const SearchQuery& query);

    /*
     * Forces a full re-index by clearing existing data and executing the provided
     * callback for each record in the system.
     */
    void reindex(const std::function<void(SearchService&)>& indexCallback);

    /*
     * Cache operations
     */
    void clearQueryCache() { _queryCache.clear(); }

    /*
     * Flush index to disk
     */
    void persistIndex(const std::filesystem::path& file);
    /*
     * Load index from disk
     */
    void loadIndex(const std::filesystem::path& file);

private:
    SearchService();
    ~SearchService();

    // ---------------------------------------------------------------------
    //  Internal Helpers
    // ---------------------------------------------------------------------

#ifdef MBS_ENABLE_SQLITE
    void openDatabase(const std::filesystem::path& file);
    void prepareStatements();
    void closeDatabase();
#endif

    // Converts query filters to SQL AND clause
    static std::string buildFilterClause(const SearchQuery& query,
                                         std::vector<std::string>& paramValues);

    // ---------------------------------------------------------------------
    //  Data Members
    // ---------------------------------------------------------------------
    mutable std::shared_mutex _rwMtx;           // Reader/writer lock for index access
    LRUCache<std::string, SearchResult> _queryCache{128};

#ifdef MBS_ENABLE_SQLITE
    sqlite3* _db {nullptr};
    sqlite3_stmt* _stmtInsert {nullptr};
    sqlite3_stmt* _stmtDelete {nullptr};
#endif
};

// =================================================================================================
//  Implementation
// =================================================================================================

inline SearchService::SearchService()
{
#ifdef MBS_ENABLE_SQLITE
    // Create in-memory DB by default.  PersistIndex/loadIndex can override.
    openDatabase(":memory:");
    prepareStatements();
#endif
}

inline SearchService::~SearchService()
{
#ifdef MBS_ENABLE_SQLITE
    closeDatabase();
#endif
}

inline void SearchService::indexRecord(std::string_view id,
                                       std::string_view type,
                                       std::string_view title,
                                       std::string_view payload)
{
#ifdef MBS_ENABLE_SQLITE
    std::unique_lock lock{_rwMtx};
    if (!_stmtInsert) { throw std::runtime_error("SearchService – insert statement not prepared"); }

    sqlite3_reset(_stmtInsert);
    sqlite3_bind_text(_stmtInsert, 1, id.data(), static_cast<int>(id.size()), SQLITE_TRANSIENT);
    sqlite3_bind_text(_stmtInsert, 2, type.data(), static_cast<int>(type.size()), SQLITE_TRANSIENT);
    sqlite3_bind_text(_stmtInsert, 3, title.data(), static_cast<int>(title.size()), SQLITE_TRANSIENT);
    sqlite3_bind_text(_stmtInsert, 4, payload.data(), static_cast<int>(payload.size()), SQLITE_TRANSIENT);

    const int rc = sqlite3_step(_stmtInsert);
    if (rc != SQLITE_DONE)
        throw std::runtime_error("SearchService – indexRecord failed: " +
                                 std::string(sqlite3_errmsg(_db)));
#else
    (void)id; (void)type; (void)title; (void)payload;
#endif
    clearQueryCache(); // Invalidate cached results
}

inline void SearchService::removeRecord(std::string_view id)
{
#ifdef MBS_ENABLE_SQLITE
    std::unique_lock lock{_rwMtx};
    sqlite3_reset(_stmtDelete);
    sqlite3_bind_text(_stmtDelete, 1, id.data(), static_cast<int>(id.size()), SQLITE_TRANSIENT);
    if (sqlite3_step(_stmtDelete) != SQLITE_DONE)
        throw std::runtime_error("SearchService – removeRecord failed: " +
                                 std::string(sqlite3_errmsg(_db)));
#else
    (void)id;
#endif
    clearQueryCache();
}

inline SearchResult SearchService::search(const SearchQuery& query)
{
    // Check cache first ----------------------------------------------------
    if (SearchResult cached; _queryCache.get(query.cacheKey(), cached))
    {
        return cached;
    }

    SearchResult result;

#ifdef MBS_ENABLE_SQLITE
    std::shared_lock lock{_rwMtx};

    std::ostringstream sql;
    sql << "SELECT id, type, title, bm25(search_index) AS score "
           "FROM search_index ";

    // Full-text query
    sql << "WHERE search_index MATCH ? ";

    // Filters as AND conditions
    std::vector<std::string> paramValues;
    const std::string filterClause = buildFilterClause(query, paramValues);
    if (!filterClause.empty()) sql << "AND " << filterClause << ' ';

    sql << "ORDER BY score LIMIT ? OFFSET ?;";

    // Prepare ad-hoc stmt
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(_db, sql.str().c_str(), -1, &stmt, nullptr) != SQLITE_OK)
        throw std::runtime_error("SearchService – search prepare failed: " +
                                 std::string(sqlite3_errmsg(_db)));

    int bindIndex = 1;
    sqlite3_bind_text(stmt, bindIndex++, query.text.c_str(),
                      static_cast<int>(query.text.size()), SQLITE_TRANSIENT);

    for (const auto& val : paramValues)
        sqlite3_bind_text(stmt, bindIndex++, val.c_str(),
                          static_cast<int>(val.size()), SQLITE_TRANSIENT);

    sqlite3_bind_int(stmt, bindIndex++, static_cast<int>(query.limit));
    sqlite3_bind_int(stmt, bindIndex++, static_cast<int>(query.offset));

    // Execute
    while (sqlite3_step(stmt) == SQLITE_ROW)
    {
        SearchResultItem item;
        item.id    = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        item.type  = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        item.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        item.score = sqlite3_column_double(stmt, 3);
        result.hits.emplace_back(std::move(item));
    }

    // Get total count ------------------------------------------------------
    // NB: Using FTS5 'count(*)' is costly; we use separate query
    {
        std::ostringstream cntSql;
        cntSql << "SELECT count(*) FROM search_index WHERE search_index MATCH ? ";
        if (!filterClause.empty()) cntSql << "AND " << filterClause;
        sqlite3_stmt* cntStmt = nullptr;
        if (sqlite3_prepare_v2(_db, cntSql.str().c_str(), -1, &cntStmt, nullptr) == SQLITE_OK)
        {
            int idx = 1;
            sqlite3_bind_text(cntStmt, idx++, query.text.c_str(),
                              static_cast<int>(query.text.size()), SQLITE_TRANSIENT);
            for (const auto& val : paramValues)
                sqlite3_bind_text(cntStmt, idx++, val.c_str(),
                                  static_cast<int>(val.size()), SQLITE_TRANSIENT);

            if (sqlite3_step(cntStmt) == SQLITE_ROW)
                result.totalCount = static_cast<std::size_t>(sqlite3_column_int64(cntStmt, 0));
        }
        sqlite3_finalize(cntStmt);
    }

    sqlite3_finalize(stmt);
#else
    // Dummy implementation when SQLite is disabled
    (void)query;
    result.totalCount = 0;
#endif

    // Store in cache -------------------------------------------------------
    _queryCache.put(query.cacheKey(), result);
    return result;
}

inline void SearchService::reindex(const std::function<void(SearchService&)>& indexCallback)
{
#ifdef MBS_ENABLE_SQLITE
    std::unique_lock lock{_rwMtx};
    sqlite3_exec(_db, "DELETE FROM search_index;", nullptr, nullptr, nullptr);
#endif
    clearQueryCache();
    indexCallback(*this);
}

inline void SearchService::persistIndex(const std::filesystem::path& file)
{
#ifdef MBS_ENABLE_SQLITE
    std::unique_lock lock{_rwMtx};
    // Backup to file using SQLite online backup API
    sqlite3* backupDb = nullptr;
    if (sqlite3_open(file.string().c_str(), &backupDb) != SQLITE_OK)
        throw std::runtime_error("SearchService – persistIndex: cannot open backup file");

    sqlite3_backup* backupHandle =
        sqlite3_backup_init(backupDb, "main", _db, "main");
    if (!backupHandle)
        throw std::runtime_error("SearchService – persistIndex: backup_init failed");

    sqlite3_backup_step(backupHandle, -1);
    sqlite3_backup_finish(backupHandle);
    sqlite3_close(backupDb);
#else
    (void)file;
#endif
}

inline void SearchService::loadIndex(const std::filesystem::path& file)
{
#ifdef MBS_ENABLE_SQLITE
    std::unique_lock lock{_rwMtx};
    closeDatabase();
    openDatabase(file);
    prepareStatements();
#else
    (void)file;
#endif
    clearQueryCache();
}

#ifdef MBS_ENABLE_SQLITE
// -------------------------------------------------------------------------------------------------
inline void SearchService::openDatabase(const std::filesystem::path& file)
{
    if (sqlite3_open(file.string().c_str(), &_db) != SQLITE_OK)
        throw std::runtime_error("SearchService – failed to open database: " +
                                 std::string(sqlite3_errmsg(_db)));

    // Enable FTS5
    const char* ddl =
        "PRAGMA journal_mode=WAL;"
        "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5("
        "  id UNINDEXED, "
        "  type UNINDEXED, "
        "  title, "
        "  payload, "
        "  tokenize = 'porter' "
        ");";
    char* err = nullptr;
    if (sqlite3_exec(_db, ddl, nullptr, nullptr, &err) != SQLITE_OK)
    {
        std::string msg = err ? err : "Unknown error";
        sqlite3_free(err);
        throw std::runtime_error("SearchService – DDL failed: " + msg);
    }
}

inline void SearchService::prepareStatements()
{
    const char* insertSql =
        "INSERT INTO search_index(id, type, title, payload)"
        "VALUES(?, ?, ?, ?)"
        "ON CONFLICT(id) DO UPDATE SET"
        "  type = excluded.type, "
        "  title = excluded.title, "
        "  payload = excluded.payload;";
    if (sqlite3_prepare_v2(_db, insertSql, -1, &_stmtInsert, nullptr) != SQLITE_OK)
        throw std::runtime_error("SearchService – prepare insert failed");

    const char* delSql = "DELETE FROM search_index WHERE id = ?;";
    if (sqlite3_prepare_v2(_db, delSql, -1, &_stmtDelete, nullptr) != SQLITE_OK)
        throw std::runtime_error("SearchService – prepare delete failed");
}

inline void SearchService::closeDatabase()
{
    if (_stmtInsert) { sqlite3_finalize(_stmtInsert); _stmtInsert = nullptr; }
    if (_stmtDelete) { sqlite3_finalize(_stmtDelete); _stmtDelete = nullptr; }
    if (_db)
    {
        sqlite3_close(_db);
        _db = nullptr;
    }
}

std::string SearchService::buildFilterClause(const SearchQuery& query,
                                             std::vector<std::string>& paramValues)
{
    if (query.filters.empty()) return {};
    std::ostringstream oss;
    bool first = true;
    for (const auto& kv : query.filters)
    {
        if (!first) oss << "AND ";
        first = false;
        oss << kv.first << " = ? ";
        paramValues.emplace_back(kv.second);
    }
    return oss.str();
}
#endif // MBS_ENABLE_SQLITE

} // namespace mbs
```