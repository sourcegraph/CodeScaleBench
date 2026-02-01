```cpp
/**
 *  IntraLedger BlogSuite – module_78.cpp
 *
 *  Purpose:
 *      Provides a production-ready, thread-safe full-text search service
 *      with an internal LRU cache.  The module sits in the Service Layer
 *      and talks to a DAO (data-access object) that abstracts the ORM or
 *      external search back-end.  The service sanitises user queries,
 *      executes searches, highlights matches, caches hot queries, and
 *      exposes lightweight instrumentation hooks.
 *
 *  Build:
 *      # C++20
 *      g++ -std=c++20 -pthread -O2 -Wall -Wextra -pedantic -c module_78.cpp
 *
 *  © 2024 IntraLedger, Inc.  All rights reserved.
 */

#include <algorithm>
#include <chrono>
#include <future>
#include <iomanip>
#include <iostream>
#include <list>
#include <mutex>
#include <regex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

// ---------------------------------------------------------------------------
//                       namespace organisation
// ---------------------------------------------------------------------------
namespace intraledger::blogsuite::search {

// ---------------------------------------------------------------------------
//                            helper types
// ---------------------------------------------------------------------------

/**
 * SearchException
 *  Thin domain-specific wrapper to clearly demarcate search errors from
 *  generic std::runtime_error.
 */
class SearchException final : public std::runtime_error {
public:
    explicit SearchException(std::string msg)
        : std::runtime_error{std::move(msg)} {}
};

/**
 * SearchResult
 *  DTO returned to controllers / view renderers.
 */
struct SearchResult {
    std::uint64_t id;
    std::string   title;
    std::string   snippet;
    double        score = 0.0;
};

// ---------------------------------------------------------------------------
//                        thread-safe LRU cache
// ---------------------------------------------------------------------------

/**
 * LRUCache
 *  Generic, thread-safe, single-shard LRU cache.
 *
 *  - Readers operate under shared_lock.
 *  - Writers obtain unique_lock.
 *  - Values are copied into the cache.  If your Value is heavy, consider
 *    std::shared_ptr<Value>.
 */
template <typename Key, typename Value>
class LRUCache {
public:
    explicit LRUCache(std::size_t capacity)
        : m_capacity{std::max<std::size_t>(1, capacity)} {}

    bool get(const Key& key, Value& out) {
        std::shared_lock lock{m_mutex};
        auto it = m_index.find(key);
        if (it == m_index.end()) { return false; }
        // Move the used item to the front (MRU)
        m_order.splice(m_order.begin(), m_order, it->second);
        out = it->second->second;
        return true;
    }

    void put(Key key, Value value) {
        std::unique_lock lock{m_mutex};

        auto it = m_index.find(key);
        if (it != m_index.end()) {                         // Update
            it->second->second = std::move(value);
            m_order.splice(m_order.begin(), m_order, it->second);
            return;
        }

        if (m_order.size() >= m_capacity) {                // Evict LRU
            const auto& lruKey = m_order.back().first;
            m_index.erase(lruKey);
            m_order.pop_back();
        }

        m_order.emplace_front(std::move(key), std::move(value));
        m_index[m_order.front().first] = m_order.begin();
    }

    std::size_t size() const noexcept {
        std::shared_lock lock{m_mutex};
        return m_order.size();
    }

    std::size_t capacity() const noexcept { return m_capacity; }

private:
    using ListPair = std::pair<Key, Value>;
    std::size_t                                    m_capacity;
    std::list<ListPair>                            m_order;  // MRU at front
    std::unordered_map<Key, typename std::list<ListPair>::iterator> m_index;
    mutable std::shared_mutex                      m_mutex;
};

// ---------------------------------------------------------------------------
//               DAO stub – would typically reside elsewhere
// ---------------------------------------------------------------------------

/**
 * FullTextSearchDao
 *  Extremely simplified DAO that would in reality:
 *    - run a SQL `SELECT * FROM search_index WHERE MATCH (...)`
 *    - or call out to Elasticsearch / MeiliSearch / Solr, etc.
 *
 *  Here it is mocked so that the rest of the module is build-able in
 *  isolation.  Replace with real implementation wired via DI.
 */
class FullTextSearchDao {
public:
    [[nodiscard]]
    std::vector<SearchResult> search(std::string_view query, std::size_t limit) const {
        // Simulate latency & result set.
        std::this_thread::sleep_for(std::chrono::milliseconds{20});

        if (query == "trigger_db_error") {
            throw SearchException{"Database unavailable"};
        }

        std::vector<SearchResult> results;
        for (std::size_t i = 0; i < limit; ++i) {
            results.push_back(SearchResult{
                /*id*/     static_cast<std::uint64_t>(i + 1000),
                /*title*/  "Sample Article " + std::to_string(i + 1),
                /*snippet*/ "... " + std::string(query) + " snippet ...",
                /*score*/  1.0 / (i + 1)
            });
        }
        return results;
    }
};

// ---------------------------------------------------------------------------
//                    SearchService – public entry point
// ---------------------------------------------------------------------------

/**
 * SearchService
 *  Facade orchestrating query sanitisation, DAO calls, result highlighting,
 *  caching, and instrumentation.  Thread-safe.  Designed to be a long-lived
 *  singleton injected into controllers.
 */
class SearchService {
public:
    explicit SearchService(std::size_t cacheCapacity = 256)
        : m_cache{cacheCapacity} {}

    /**
     * execute
     *  Main API called by controllers.
     *
     *  Throws:
     *      SearchException on unrecoverable back-end error.
     */
    [[nodiscard]]
    std::vector<SearchResult> execute(std::string rawQuery,
                                      std::size_t limit = 10) {

        const auto query = sanitiseQuery(std::move(rawQuery));
        if (query.empty()) { return {}; }

        // --- fast path: cached ----------------------------
        std::vector<SearchResult> cached;
        if (m_cache.get(query, cached)) {
            recordHit(true);
            return cached;   // already highlighted, safe to return
        }

        // --- slow path: DAO + post-processing -------------
        auto results = m_dao.search(query, limit);
        highlight(results, query);
        m_cache.put(query, results);
        recordHit(false);

        // Fire-and-forget pre-warm of similar queries
        asyncPrefetchSimilar(query);

        return results;
    }

    /**
     * metricsSnapshot
     *  Returns a copy of simple runtime metrics for dashboards.
     */
    [[nodiscard]]
    std::unordered_map<std::string, std::uint64_t> metricsSnapshot() const {
        std::lock_guard lock{m_metricsMutex};
        return m_metrics;
    }

private:
    // ------------------- helpers ------------------------------------------

    static std::string sanitiseQuery(std::string query) {
        // Lower-case, trim, collapse spaces, strip control chars
        std::transform(query.begin(), query.end(), query.begin(),
                       [](unsigned char c){ return static_cast<char>(std::tolower(c)); });

        // Remove anything except printable ASCII and basic UTF-8 continuation bytes
        query.erase(std::remove_if(query.begin(), query.end(),
                                   [](unsigned char ch){
                                       return (ch < 0x20 && ch != 0x09) || ch == 0x7F;
                                   }),
                    query.end());

        // Collapse whitespace
        query = std::regex_replace(query, std::regex{R"(\s+)"}, " ");

        // Trim
        if (!query.empty() && query.front() == ' ') query.erase(query.begin());
        if (!query.empty() && query.back()  == ' ') query.pop_back();

        return query;
    }

    static void highlight(std::vector<SearchResult>& results,
                          const std::string& query) {

        // Escape regex meta-characters in query
        const std::string escaped =
            std::regex_replace(query, std::regex{R"([.^$|()\\+*\[\]{}])"}, R"(\$&)");
        const std::regex needle{escaped, std::regex_constants::icase};

        for (auto& r : results) {
            r.snippet = std::regex_replace(
                r.snippet, needle, "<mark>$&</mark>");
            r.title = std::regex_replace(
                r.title, needle, "<mark>$&</mark>");
        }
    }

    // Fire asynchronous warm-up for "query*" and "*query"
    void asyncPrefetchSimilar(const std::string& baseQuery) {
        if (baseQuery.size() < 3) { return; }

        // Keep the task lightweight to avoid thread oversubscription.
        std::async(std::launch::async, [this, baseQuery] {
            for (const auto& variant : similarVariants(baseQuery)) {
                std::vector<SearchResult> tmp;
                if (!m_cache.get(variant, tmp)) {
                    try {
                        auto res = m_dao.search(variant, 5);
                        highlight(res, variant);
                        m_cache.put(variant, std::move(res));
                    } catch (const std::exception& ex) {
                        // Silently ignore; background prefetch, not critical.
                        logError("prefetch", ex.what());
                    }
                }
            }
        });
    }

    static std::vector<std::string> similarVariants(const std::string& q) {
        std::vector<std::string> v;

        const std::string prefixStar = q + '*';
        const std::string suffixStar = '*' + q;

        v.reserve(2);
        v.push_back(prefixStar);
        v.push_back(suffixStar);

        return v;
    }

    void recordHit(bool fromCache) {
        std::lock_guard lock{m_metricsMutex};
        ++m_metrics[fromCache ? "cache_hits" : "cache_misses"];
    }

    static void logError(const char* scope, const std::string& msg) noexcept {
        using namespace std::chrono;

        auto now = system_clock::now();
        auto t   = system_clock::to_time_t(now);
        std::cerr << "[SearchService][" << scope << "]["
                  << std::put_time(std::localtime(&t), "%F %T")
                  << "] ERROR: " << msg << '\n';
    }

    // ------------------- members ------------------------------------------
    FullTextSearchDao                     m_dao;
    LRUCache<std::string, std::vector<SearchResult>> m_cache;

    // minimal metrics collection
    std::unordered_map<std::string, std::uint64_t>  m_metrics;
    mutable std::mutex                              m_metricsMutex;
};

} // namespace intraledger::blogsuite::search

// ---------------------------------------------------------------------------
//                         (optional) unit test harness
// ---------------------------------------------------------------------------
#ifdef BLOGSUITE_SEARCH_MODULE_TEST
int main() {
    using namespace intraledger::blogsuite::search;

    SearchService svc{64};

    const auto res1 = svc.execute("IntraLedger");
    std::cout << "Results #1: " << res1.size() << '\n';

    const auto res2 = svc.execute("IntraLedger");   // cache hit
    std::cout << "Results #2: " << res2.size() << '\n';

    for (const auto& [k,v] : svc.metricsSnapshot()) {
        std::cout << k << " = " << v << '\n';
    }
}
#endif
```