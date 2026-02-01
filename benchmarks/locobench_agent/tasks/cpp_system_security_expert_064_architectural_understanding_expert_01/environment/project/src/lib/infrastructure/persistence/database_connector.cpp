```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File        : database_connector.cpp
 *  Project     : FortiLedger360 :: Infrastructure :: Persistence
 *  Description : Thread-safe PostgreSQL connection-pool implementation that
 *                provides RAII-style connection handles for upper layers.
 *
 *  Build Notes :
 *      – Requires libpqxx (≥ 6.4) and spdlog (≥ 1.8) at compile time
 *      – Compile with -std=c++17
 *
 *  Copyright   : FortiLedger Inc. – All Rights Reserved
 */

#include <cstdlib>                         // std::getenv
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <queue>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pqxx/pqxx>                       // PostgreSQL C++ client
#include <spdlog/spdlog.h>                 // Structured & leveled logging

namespace fortiledger360::infrastructure::persistence
{

/* -------------------------------------------------------------------------- */
/*                            Forward Declarations                             */
/* -------------------------------------------------------------------------- */

/**
 * Lightweight RAII wrapper that represents a pooled database connection.
 * When the handle goes out of scope it automatically returns the connection
 * to the owning DatabaseConnector.
 */
class ConnectionHandle;

/* -------------------------------------------------------------------------- */
/*                            DatabaseConnector                               */
/* -------------------------------------------------------------------------- */

class DatabaseConnector final
{
public:
    /**
     * Returns the global singleton instance.
     * Thread-safe lazy initialization is guaranteed since C++11.
     */
    static DatabaseConnector& instance()
    {
        static DatabaseConnector connector;
        return connector;
    }

    // Non-copyable / Non-movable
    DatabaseConnector(const DatabaseConnector&)            = delete;
    DatabaseConnector& operator=(const DatabaseConnector&) = delete;
    DatabaseConnector(DatabaseConnector&&)                 = delete;
    DatabaseConnector& operator=(DatabaseConnector&&)      = delete;

    /**
     * Acquires a connection from the pool. The returned handle
     * will automatically release the resource once destroyed.
     *
     * Throws std::runtime_error if no connection can be established.
     */
    [[nodiscard]] ConnectionHandle acquire();

    /**
     * Executes user-supplied Fn object inside a database transaction.
     * If the callable throws, the transaction is rolled back and the
     * exception is rethrown.  Commit happens automatically upon success.
     */
    template <typename Fn>
    void executeWithinTransaction(Fn&& callable);

    /**
     * Non-blocking health check: returns true if a connection
     * can be acquired and a trivial query succeeds.
     */
    bool isHealthy();

private:
    DatabaseConnector();
    ~DatabaseConnector() = default;

    /* ------------- Internal Types & Data Members -------------------------- */

    struct DbConfig
    {
        std::string host;
        std::string port;
        std::string dbname;
        std::string user;
        std::string password;
        std::string sslMode;
        std::size_t poolSize {};
    };

    DbConfig                               cfg_;
    std::vector<std::unique_ptr<pqxx::connection>> pool_ {};     // owned conns
    std::queue<std::size_t>                available_ {};        // index pool
    std::mutex                             mtx_ {};
    std::condition_variable                cv_ {};
    bool                                   shutdown_ {false};

    /* ------------- Internal Helpers -------------------------------------- */

    // Constructs libpq connection string from stored configuration
    std::string buildConnectionString() const;

    // Blocks until a connection index becomes available
    std::size_t checkoutIndex();

    // Returns the borrowed index back to pool
    void releaseIndex(std::size_t idx);

    friend class ConnectionHandle;
};

/* -------------------------------------------------------------------------- */
/*                              ConnectionHandle                              */
/* -------------------------------------------------------------------------- */

class ConnectionHandle
{
public:
    ConnectionHandle()                                = delete;
    ConnectionHandle(const ConnectionHandle&)         = delete;
    ConnectionHandle& operator=(const ConnectionHandle&) = delete;

    ConnectionHandle(ConnectionHandle&& other) noexcept
        : connector_{other.connector_}
        , index_     {other.index_}
        , conn_      {other.conn_}
    {
        other.index_ = SIZE_MAX;
        other.conn_  = nullptr;
    }

    ConnectionHandle& operator=(ConnectionHandle&& other) noexcept
    {
        if (this != &other)
        {
            cleanup();
            connector_ = other.connector_;
            index_     = other.index_;
            conn_      = other.conn_;
            other.index_ = SIZE_MAX;
            other.conn_  = nullptr;
        }
        return *this;
    }

    ~ConnectionHandle() { cleanup(); }

    pqxx::connection& operator*()  const { return *conn_; }
    pqxx::connection* operator->() const { return  conn_; }
    pqxx::connection* get()             { return  conn_; }

private:
    friend class DatabaseConnector;

    ConnectionHandle(DatabaseConnector* connector,
                     std::size_t        idx,
                     pqxx::connection*  conn)
        : connector_{connector}
        , index_    {idx}
        , conn_     {conn}
    {}

    void cleanup()
    {
        if (connector_ && index_ != SIZE_MAX)
        {
            connector_->releaseIndex(index_);
        }
        connector_ = nullptr;
        conn_      = nullptr;
        index_     = SIZE_MAX;
    }

    DatabaseConnector* connector_ {nullptr};
    std::size_t        index_     {SIZE_MAX};
    pqxx::connection*  conn_      {nullptr};
};

/* -------------------------------------------------------------------------- */
/*                         DatabaseConnector :: impl                          */
/* -------------------------------------------------------------------------- */

DatabaseConnector::DatabaseConnector()
{
    // 1) Hydrate configuration from environment variables
    const char* envHost     = std::getenv("DB_HOST");
    const char* envPort     = std::getenv("DB_PORT");
    const char* envName     = std::getenv("DB_NAME");
    const char* envUser     = std::getenv("DB_USER");
    const char* envPwd      = std::getenv("DB_PASSWORD");
    const char* envSsl      = std::getenv("DB_SSL_MODE");
    const char* envPoolSize = std::getenv("DB_POOL_SIZE");

    cfg_.host     = envHost     ? envHost     : "localhost";
    cfg_.port     = envPort     ? envPort     : "5432";
    cfg_.dbname   = envName     ? envName     : "fortiledger360";
    cfg_.user     = envUser     ? envUser     : "security_suite";
    cfg_.password = envPwd      ? envPwd      : "";
    cfg_.sslMode  = envSsl      ? envSsl      : "require";
    cfg_.poolSize = envPoolSize ? std::stoul(envPoolSize) : 4u;

    if (cfg_.poolSize == 0)
        cfg_.poolSize = 1; // guarantee at least one connection

    spdlog::info("[DB] Initializing connection pool (size={})...", cfg_.poolSize);

    // 2) Pre-allocate connections
    const std::string connStr = buildConnectionString();
    try
    {
        pool_.reserve(cfg_.poolSize);
        for (std::size_t i = 0; i < cfg_.poolSize; ++i)
        {
            auto conn = std::make_unique<pqxx::connection>(connStr);
            if (!conn->is_open())
            {
                throw std::runtime_error("Failed to open DB connection " + std::to_string(i));
            }
            pool_.emplace_back(std::move(conn));
            available_.push(i);
            spdlog::debug("[DB] Connection #{} established", i);
        }
    }
    catch (const std::exception& ex)
    {
        // If any part of the pool fails we tear down everything and propagate
        spdlog::critical("[DB] Pool initialization failed: {}", ex.what());
        throw;
    }
}

std::string DatabaseConnector::buildConnectionString() const
{
    std::string str;
    str.reserve(256);

    str += "host="      + cfg_.host     + " ";
    str += "port="      + cfg_.port     + " ";
    str += "dbname="    + cfg_.dbname   + " ";
    str += "user="      + cfg_.user     + " ";
    if (!cfg_.password.empty())
        str += "password=" + cfg_.password + " ";
    str += "sslmode="   + cfg_.sslMode;

    return str;
}

std::size_t DatabaseConnector::checkoutIndex()
{
    std::unique_lock<std::mutex> lock(mtx_);
    cv_.wait(lock, [this] { return !available_.empty() || shutdown_; });

    if (shutdown_)
        throw std::runtime_error("DB connector is shutting down");

    auto idx = available_.front();
    available_.pop();
    return idx;
}

void DatabaseConnector::releaseIndex(std::size_t idx)
{
    {
        std::lock_guard<std::mutex> lg{mtx_};
        available_.push(idx);
    }
    cv_.notify_one();
}

ConnectionHandle DatabaseConnector::acquire()
{
    const auto idx = checkoutIndex();
    pqxx::connection* rawPtr = pool_[idx].get();

    if (!rawPtr->is_open())
    {
        try
        {
            rawPtr->activate();
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[DB] Failed to reactivate connection #{}: {}", idx, ex.what());
            releaseIndex(idx);
            throw;
        }
    }

    return ConnectionHandle{this, idx, rawPtr};
}

template <typename Fn>
void DatabaseConnector::executeWithinTransaction(Fn&& callable)
{
    auto connHandle = acquire();

    try
    {
        pqxx::work txn{*connHandle};
        std::invoke(std::forward<Fn>(callable), txn);
        txn.commit();
    }
    catch (...)
    {
        // rollback occurs automatically in pqxx::work destructor
        spdlog::error("[DB] Transaction failed – rolled back");
        throw;
    }
}

bool DatabaseConnector::isHealthy()
{
    try
    {
        auto connHandle = acquire();
        pqxx::nontransaction txn{*connHandle};
        txn.exec0("SELECT 1");
        return true;
    }
    catch (const std::exception& ex)
    {
        spdlog::warn("[DB] Health check failed: {}", ex.what());
        return false;
    }
}

/* -------------------------------------------------------------------------- */
/*                               Usage Example                                */
/*
    auto& db = DatabaseConnector::instance();
    db.executeWithinTransaction([](pqxx::work& txn) {
        txn.exec_params("INSERT INTO audit_log(actor, event) VALUES($1, $2)",
                        "scanner-svc", "scan_started");
    });
*/
/* -------------------------------------------------------------------------- */

} // namespace fortiledger360::infrastructure::persistence
```