#include <algorithm>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <pqxx/pqxx>
#include <regex>
#include <shared_mutex>
#include <spdlog/spdlog.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <vector>

/*
 *  File: module_4.cpp
 *  Project: IntraLedger BlogSuite
 *
 *  Purpose:
 *  =========
 *  Implements the full–text search subsystem built on PostgreSQL’s
 *  GIN-powered `tsvector` indexes.  The module provides a small but
 *  production-ready service + repository pair that encapsulates:
 *
 *     • Index maintenance (insert / update / delete) executed
 *       asynchronously through std::async to decouple latency
 *       from HTTP request/response lifecycles.
 *
 *     • Query construction with sanitisation and language awareness.
 *
 *     • Connection-pooled interaction with the backing database
 *       using libpqxx.
 *
 *     • Thread-safe in-memory cache for prepared statements to reduce
 *       planning overhead under high concurrency.
 *
 *  The code purposefully avoids tight coupling with upper MVC layers;
 *  it could be consumed both by GraphQL and REST controllers.
 *
 *  NOTE:
 *  -----
 *  Error handling is opinionated:
 *      – DB errors are logged and re-thrown as std::runtime_error.
 *      – Invalid arguments cause std::invalid_argument.
 *      – Timeouts / cancellation propagate using std::future_error.
 */

namespace intraledger::search
{

//---------------------------------------------------------------------------------------------------------------------
// Domain primitives
//---------------------------------------------------------------------------------------------------------------------

struct Article
{
    int                 id              {};
    std::string         title;
    std::string         body;
    std::string         locale          {"en"};
    bool                is_published    {false};
};

struct SearchResult
{
    int                     id;
    std::string             title;
    std::string             excerpt;
    double                  rank;          // PostgreSQL ts_rank value
};

struct SearchQuery
{
    std::string             term;
    std::string             locale        {"en"};
    std::size_t             limit         {25};
    std::size_t             offset        {0};
};

//---------------------------------------------------------------------------------------------------------------------
// Connection Pool (very light-weight draft)
//---------------------------------------------------------------------------------------------------------------------

class PgPool
{
public:
    explicit PgPool(std::string connectionUri,
                    std::size_t poolSize = std::thread::hardware_concurrency() * 2)
        : m_uri{std::move(connectionUri)}
        , m_poolSize{std::max<std::size_t>(1, poolSize)}
    {
        for (std::size_t i = 0; i < m_poolSize; ++i)
        {
            m_pool.emplace_back(std::make_unique<pqxx::connection>(m_uri));
        }
    }

    pqxx::connection& acquire()
    {
        using namespace std::chrono_literals;
        auto start = std::chrono::steady_clock::now();

        // Busy-wait w/ timeout of 3 seconds (thin wrapper—could be replaced with
        // condvar in a heavier implementation).
        while (true)
        {
            {
                std::scoped_lock lock{m_mtx};
                if (!m_pool.empty())
                {
                    auto ptr = std::move(m_pool.back());
                    m_pool.pop_back();
                    m_inUse.emplace(ptr.get(), std::move(ptr));
                    return *m_inUse.begin()->second;
                }
            }

            if (std::chrono::steady_clock::now() - start > 3s)
            {
                throw std::runtime_error("PgPool timeout: no available connections");
            }
            std::this_thread::sleep_for(2ms);
        }
    }

    void release(pqxx::connection& conn)
    {
        std::scoped_lock lock{m_mtx};
        auto it = m_inUse.find(&conn);
        if (it == m_inUse.end())
        {
            spdlog::error("PgPool: attempted to release unknown connection");
            return;
        }
        m_pool.push_back(std::move(it->second));
        m_inUse.erase(it);
    }

private:
    std::string                                                     m_uri;
    std::size_t                                                     m_poolSize;
    std::vector<std::unique_ptr<pqxx::connection>>                  m_pool;
    std::unordered_map<pqxx::connection*, std::unique_ptr<pqxx::connection>>
                                                                    m_inUse;
    std::mutex                                                      m_mtx;
};

// Helper RAII wrapper
class PooledConnection
{
public:
    explicit PooledConnection(PgPool& pool) : m_pool{&pool}, m_conn{&pool.acquire()} {}
    ~PooledConnection() { m_pool->release(*m_conn); }

    pqxx::connection& operator*()  { return *m_conn; }
    pqxx::connection* operator->() { return m_conn;  }

private:
    PgPool*              m_pool;
    pqxx::connection*    m_conn;
};

//---------------------------------------------------------------------------------------------------------------------
// Repository Layer
//---------------------------------------------------------------------------------------------------------------------

class SearchRepository
{
public:
    explicit SearchRepository(PgPool& pool) : m_pool(pool)
    {
        prepareStatements();
    }

    void indexArticle(const Article& a)
    {
        PooledConnection conn{m_pool};
        pqxx::work txn(*conn);

        txn.prepared("idx_upsert")
           (a.id)
           (a.title)
           (a.body)
           (a.locale)
           (a.is_published)
           .exec();
        txn.commit();
    }

    void removeArticle(int id)
    {
        PooledConnection conn{m_pool};
        pqxx::work txn(*conn);

        txn.prepared("idx_delete")(id).exec();
        txn.commit();
    }

    std::vector<SearchResult> search(const SearchQuery& q)
    {
        PooledConnection conn{m_pool};
        pqxx::work txn(*conn);

        const auto sanTerm = sanitize(q.term);
        auto res = txn.prepared("idx_search")(sanTerm)
                                            (q.locale)
                                            (static_cast<int>(q.limit))
                                            (static_cast<int>(q.offset))
                                            .exec();

        std::vector<SearchResult> results;
        results.reserve(res.size());

        for (auto row : res)
        {
            SearchResult r
            {
                row["id"].as<int>(),
                row["title"].c_str(),
                row["excerpt"].c_str(),
                row["rank"].as<double>()
            };
            results.push_back(std::move(r));
        }
        return results;
    }

private:
    static std::string sanitize(std::string_view in)
    {
        // Strips anything but letters, digits, and spaces to protect against
        // tsquery injection.
        static const std::regex forbidden{R"([^0-9a-zA-Z\p{L}\s]+)"};
        return std::regex_replace(std::string{in}, forbidden, " ");
    }

    void prepareStatements()
    {
        // Only run once across all threads.
        static std::once_flag once;
        std::call_once(once, [this]
        {
            PooledConnection conn{m_pool};
            conn->prepare(
                "idx_upsert",
                R"(INSERT INTO search_index(id, title, body, locale, is_published,
                                            tsv)
                   VALUES($1, $2, $3, $4, $5,
                          to_tsvector($4::regconfig, concat_ws(' ', $2, $3)))
                   ON CONFLICT(id)
                   DO UPDATE SET
                       title         = EXCLUDED.title,
                       body          = EXCLUDED.body,
                       locale        = EXCLUDED.locale,
                       is_published  = EXCLUDED.is_published,
                       tsv           = EXCLUDED.tsv)"
            );

            conn->prepare(
                "idx_delete",
                "DELETE FROM search_index WHERE id = $1"
            );

            conn->prepare(
                "idx_search",
                R"(SELECT id,
                          title,
                          ts_headline($2::regconfig, body, websearch_to_tsquery($2, $1),
                                      'StartSel=<b>,StopSel=</b>,MaxWords=40,MinWords=15')
                              AS excerpt,
                          ts_rank(tsv, websearch_to_tsquery($2, $1)) AS rank
                   FROM   search_index
                   WHERE  is_published = true
                     AND  locale       = $2
                     AND  tsv @@ websearch_to_tsquery($2, $1)
                   ORDER  BY rank DESC
                   LIMIT  $3
                   OFFSET $4)"
            );
        });
    }

    PgPool&             m_pool;
};

//---------------------------------------------------------------------------------------------------------------------
// Service Layer (Business rules / async orchestration)
//---------------------------------------------------------------------------------------------------------------------

class SearchService
{
public:
    explicit SearchService(SearchRepository& repo)
        : m_repo(repo)
    {}

    // Fire-and-forget indexing.  Caller receives a future in case they need
    // to wait for completion (e.g. tests), but production code rarely blocks.
    std::future<void> asyncIndexArticle(const Article& a)
    {
        return std::async(std::launch::async, [this, a]
        {
            try
            {
                m_repo.indexArticle(a);
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Failed to index article {}: {}", a.id, ex.what());
                throw;  // re-throw so the future becomes exceptional
            }
        });
    }

    std::future<void> asyncRemoveArticle(int id)
    {
        return std::async(std::launch::async, [this, id]
        {
            try
            {
                m_repo.removeArticle(id);
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Failed to remove article {}: {}", id, ex.what());
                throw;
            }
        });
    }

    std::vector<SearchResult> search(const SearchQuery& q)
    {
        validate(q);
        return m_repo.search(q);
    }

private:
    static void validate(const SearchQuery& q)
    {
        if (q.term.empty())
            throw std::invalid_argument("Search term cannot be empty");

        if (q.limit == 0 || q.limit > 500)
            throw std::invalid_argument("Limit must be between 1 and 500");

        if (q.locale.empty() || q.locale.size() > 8)
            throw std::invalid_argument("Invalid locale");
    }

    SearchRepository&       m_repo;
};

//---------------------------------------------------------------------------------------------------------------------
// Convenience factory (used by DI container in the larger project)
//---------------------------------------------------------------------------------------------------------------------

class SearchModule
{
public:
    explicit SearchModule(std::string connectionUri)
        : m_pool(std::move(connectionUri))
        , m_repo(m_pool)
        , m_service(m_repo)
    {}

    SearchService& service() { return m_service; }

private:
    PgPool              m_pool;
    SearchRepository    m_repo;
    SearchService       m_service;
};

} // namespace intraledger::search

//---------------------------------------------------------------------------------------------------------------------
// Unit-style self-test (compile-time only).  Remove or migrate to gtest in prod.
//---------------------------------------------------------------------------------------------------------------------

#ifdef BLOGSUITE_SEARCH_SELFTEST
#include <cassert>

int main()
{
    using namespace intraledger::search;

    // NOTE: A PostgreSQL instance with proper schema is required.
    // This self-test only checks compilation and basic flow.
    SearchModule module{"postgres://user:pass@localhost/blogsuite"};
    auto& svc = module.service();

    Article fake{42, "Hello Title", "Body lorem ipsum", "en", true};
    auto fut = svc.asyncIndexArticle(fake);
    fut.get();  // wait for finish

    SearchQuery q{"hello", "en", 10, 0};
    auto results = svc.search(q);
    spdlog::info("Got {} results", results.size());

    svc.asyncRemoveArticle(fake.id).get();
}
#endif