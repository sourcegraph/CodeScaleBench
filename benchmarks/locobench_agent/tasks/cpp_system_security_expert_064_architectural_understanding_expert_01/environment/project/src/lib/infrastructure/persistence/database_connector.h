#pragma once
/**************************************************************************************************
 *  File:        database_connector.h
 *  Project:     FortiLedger360 Enterprise Security Suite
 *  Module:      Infrastructure :: Persistence
 *
 *  Description: Thread–safe, RAII-style connector with light-weight pooling for relational
 *               databases (PostgreSQL for the first implementation).  The connector is intended
 *               to be consumed by repository/DAO implementations inside the infrastructure layer
 *               and is completely agnostic to higher-level domain concepts.
 *
 *               ┌──────────────────┐
 *               │  Repository<T>   │     <- Orchestration / Domain
 *               └────────┬─────────┘
 *                        │
 *               ┌────────▼─────────┐
 *               │ DatabaseConnector│     <- This file
 *               └────────┬─────────┘
 *                        │
 *               ┌────────▼─────────┐
 *               │ libpqxx / libpq  │
 *               └──────────────────┘
 *
 *  Features:
 *      • Connection pooling with configurable max-pool-size
 *      • Blocking acquire w/ timeout
 *      • RAII ConnectionGuard that guarantees the connection is returned to the pool
 *      • Safe shutdown that invalidates outstanding guards
 *      • Parametrised query execution helper that converts result sets into a generic container
 *
 *  Usage Example:
 *      DatabaseConfig cfg{.host="db.acme.io", .port=5432, .db_name="ledger",
 *                         .user="svc_fortiledger", .password=secret, .pool_size=10};
 *
 *      DatabaseConnector connector{cfg};
 *
 *      auto rows = connector.execute(
 *              "SELECT id, status FROM tasks WHERE tenant_id = $1",
 *              {tenant_id});
 *
 *      for (auto&& row : rows.rows) { … }
 *
 **************************************************************************************************/

#include <pqxx/pqxx>                               // Official C++ wrapper for libpq
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fortiledger::infrastructure::persistence {

//-------------------------------------------------------------------------------------------------
// Type aliases & forward declarations
//-------------------------------------------------------------------------------------------------
using Timestamp = std::chrono::system_clock::time_point;

/**
 * Lightweight representation of a SQL result-set.
 * Each row is an unordered_map<column_name, textual_value>.
 *
 * NOTE:  In high-throughput scenarios you’ll likely want to map directly into strongly
 *        typed DTOs or domain aggregates.  For simplicity we return everything as string.
 */
struct QueryResult
{
    using Row = std::unordered_map<std::string, std::string>;

    std::vector<Row> rows;
    std::size_t      affected_rows {0};
    Timestamp        executed_at   {std::chrono::system_clock::now()};
};

/**
 * Configuration blob required to establish a connection to Postgres.
 */
struct DatabaseConfig
{
    std::string host;
    std::uint16_t port                 {5432};
    std::string db_name;
    std::string user;
    std::string password;
    std::uint16_t pool_size            {4};
    bool         require_ssl           {true};
    std::chrono::milliseconds connect_timeout {std::chrono::seconds(5)};
};

/**
 * Custom exception type for all database related errors.
 */
class DatabaseException final : public std::runtime_error
{
public:
    explicit DatabaseException(const std::string& message)
        : std::runtime_error(message) {}
};

// Forward declaration (needed by ConnectionGuard)
class DatabaseConnector;

/**
 * RAII handle that represents a live database connection returned from
 * DatabaseConnector::acquire().  Upon destruction or explicit release()
 * the connection is returned to the pool so that other threads can reuse it.
 */
class ConnectionGuard
{
public:
    ConnectionGuard()                                  = delete;
    ConnectionGuard(const ConnectionGuard&)            = delete;
    ConnectionGuard& operator=(const ConnectionGuard&) = delete;

    ConnectionGuard(ConnectionGuard&& other) noexcept
        : connector_{other.connector_}, conn_{std::move(other.conn_)}
    {
        other.connector_ = nullptr;
    }

    ConnectionGuard& operator=(ConnectionGuard&& rhs) noexcept
    {
        if (&rhs != this)
        {
            release();
            connector_      = rhs.connector_;
            conn_           = std::move(rhs.conn_);
            rhs.connector_  = nullptr;
        }
        return *this;
    }

    ~ConnectionGuard() noexcept
    {
        // Release on scope exit.  No-throw guarantee.
        release();
    }

    /**
     * Access underlying pqxx::connection.
     * The caller MUST guarantee not to stash references/pointers outside the guard’s lifetime.
     */
    pqxx::connection& conn()
    {
        if (!conn_)
            throw DatabaseException{"Attempt to access invalidated database connection."};
        return *conn_;
    }

private:
    friend class DatabaseConnector;

    ConnectionGuard(DatabaseConnector& connector,
                    std::unique_ptr<pqxx::connection>&& conn) noexcept
        : connector_{&connector}
        , conn_{std::move(conn)}
    {
    }

    void release() noexcept;

    DatabaseConnector*                     connector_ {nullptr};
    std::unique_ptr<pqxx::connection>      conn_;
};

//-------------------------------------------------------------------------------------------------
// DatabaseConnector – public interface
//-------------------------------------------------------------------------------------------------
class DatabaseConnector
{
public:
    explicit DatabaseConnector(DatabaseConfig cfg);
    ~DatabaseConnector();

    DatabaseConnector(const DatabaseConnector&)            = delete;
    DatabaseConnector& operator=(const DatabaseConnector&) = delete;

    /**
     * Acquires a connection from the pool (blocking).
     * Throws DatabaseException on timeout or if the connector has been shut down.
     */
    [[nodiscard]]
    ConnectionGuard acquire(std::chrono::milliseconds timeout =
                                std::chrono::seconds(30));

    /**
     * Convenience helper: Executes a parametrised SQL statement using a temporary
     * connection guard under the hood.  The helper is intended for lightweight
     * read or DML statements.  For complex multi-step workflows consider
     * orchestrating your own transactions using pqxx::transaction facilities.
     */
    QueryResult
    execute(const std::string&                                         sql,
            const std::vector<std::optional<std::string>>&             params   = {},
            std::chrono::milliseconds                                  timeout  = std::chrono::seconds(30));

    /**
     * Closes all idle connections and marks the connector as shut-down so that subsequent
     * calls to acquire() fail fast.  Outstanding guards remain valid until they get
     * destroyed by their owners.
     */
    void shutdown() noexcept;

private:
    friend class ConnectionGuard;

    std::unique_ptr<pqxx::connection> make_connection();
    void release(std::unique_ptr<pqxx::connection>&& conn) noexcept;

    DatabaseConfig                                  config_;
    std::vector<std::unique_ptr<pqxx::connection>>  pool_;
    std::mutex                                      mutex_;
    std::condition_variable                         cond_var_;
    bool                                            shutdown_requested_ {false};
};

//=================================================================================================
// Inline / template implementation
//=================================================================================================

/* ---------------------- DatabaseConnector -----------------------------------------------------*/
inline DatabaseConnector::DatabaseConnector(DatabaseConfig cfg)
    : config_{std::move(cfg)}
{
    try
    {
        for (std::size_t i = 0; i < config_.pool_size; ++i)
            pool_.emplace_back(make_connection());
    }
    catch (const std::exception& ex)
    {
        throw DatabaseException{
            std::string{"Failed to populate database connection pool: "} + ex.what()
        };
    }
}

inline DatabaseConnector::~DatabaseConnector()
{
    shutdown();
}

inline std::unique_ptr<pqxx::connection> DatabaseConnector::make_connection()
{
    std::string connection_str =
        "host=" + config_.host +
        " port=" + std::to_string(config_.port) +
        " dbname=" + config_.db_name +
        " user=" + config_.user +
        " password=" + config_.password +
        " connect_timeout=" + std::to_string(config_.connect_timeout.count() / 1000);

    if (config_.require_ssl)          connection_str += " sslmode=require";
    else                              connection_str += " sslmode=disable";

    auto conn = std::make_unique<pqxx::connection>(connection_str);

    if (!conn->is_open())
        throw DatabaseException{"Could not establish database connection."};

    return conn;
}

inline ConnectionGuard
DatabaseConnector::acquire(std::chrono::milliseconds timeout)
{
    std::unique_lock lock{mutex_};

    if (shutdown_requested_)
        throw DatabaseException{"DatabaseConnector has been shut down."};

    // Wait for available connection
    if (!cond_var_.wait_for(lock, timeout,
                            [&]{ return shutdown_requested_ || !pool_.empty(); }))
        throw DatabaseException{"Timeout while waiting for DB connection."};

    if (shutdown_requested_)
        throw DatabaseException{"DatabaseConnector has been shut down."};

    auto conn = std::move(pool_.back());
    pool_.pop_back();

    return ConnectionGuard{*this, std::move(conn)};
}

inline QueryResult
DatabaseConnector::execute(const std::string&                             sql,
                           const std::vector<std::optional<std::string>>& params,
                           std::chrono::milliseconds                      timeout)
{
    auto guard = acquire(timeout);
    auto& c    = guard.conn();

    try
    {
        pqxx::work txn{c};

        pqxx::result r;
        if (params.empty())
        {
            r = txn.exec(sql);
        }
        else
        {
            pqxx::prepare::declaration decl = txn.prepared(sql);
            for (std::size_t i = 0; i < params.size(); ++i)
            {
                if (!params[i].has_value())
                    decl(nullptr);
                else
                    decl(params[i].value());
            }
            r = decl.exec();
        }

        txn.commit();

        QueryResult qr;
        qr.affected_rows = r.affected_rows();
        qr.rows.reserve(r.size());

        for (auto const& row : r)
        {
            QueryResult::Row out;
            out.reserve(row.size());
            for (auto const& field : row)
            {
                out.emplace(field.name(), field.is_null() ? "" : field.c_str());
            }
            qr.rows.emplace_back(std::move(out));
        }
        return qr;
    }
    catch (const std::exception& ex)
    {
        throw DatabaseException{
            std::string{"Failed to execute query: "} + ex.what()
        };
    }
}

inline void DatabaseConnector::shutdown() noexcept
{
    {
        std::scoped_lock lock{mutex_};
        shutdown_requested_ = true;
    }
    cond_var_.notify_all();
    // All idle connections are closed automatically when `pool_` is destroyed.
}

inline void DatabaseConnector::release(std::unique_ptr<pqxx::connection>&& conn) noexcept
{
    if (!conn) return;

    std::scoped_lock lock{mutex_};

    if (!shutdown_requested_)
    {
        pool_.emplace_back(std::move(conn));
        cond_var_.notify_one();
    }
    // else:  connector is shutting down → drop the connection on the floor
}

/* ---------------------- ConnectionGuard -------------------------------------------------------*/
inline void ConnectionGuard::release() noexcept
{
    if (connector_ && conn_)
    {
        connector_->release(std::move(conn_));
    }
}

} // namespace fortiledger::infrastructure::persistence