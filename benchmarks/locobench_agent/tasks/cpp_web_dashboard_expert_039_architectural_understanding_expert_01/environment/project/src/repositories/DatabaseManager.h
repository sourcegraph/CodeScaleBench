```cpp
/***************************************************************************************************
 *  MosaicBoard Studio
 *  File:    MosaicBoardStudio/src/repositories/DatabaseManager.h
 *  Author:  MosaicBoard Core Team
 *  License: MIT (see LICENSE.md)
 *
 *  Description:
 *  ------------
 *  A lightweight, production-ready database manager that offers:
 *      • Connection-pool management (thread-safe) for SQLite3 (default) or any other driver that
 *        implements the IDatabaseConnection interface.
 *      • Parameter-binding helpers & automatic resource cleanup (RAII).
 *      • Stateless, async-friendly query helpers returning strongly-typed rows in a JSON-like
 *        structure (unordered_map<std::string, std::string>).
 *      • Centralised error handling & tracing hooks.
 *
 *  Usage:
 *  ------
 *      // Bootstrap early in application lifecycle (e.g. Server::start())
 *      DatabaseConfig cfg;
 *      cfg.type          = DBType::SQLite;
 *      cfg.databasePath  = "mosaic.db";
 *      cfg.poolSize      = 10;
 *      DatabaseManager::init(cfg);
 *
 *      // Anywhere inside request-handling thread…
 *      auto db  = DatabaseManager::instance().leaseConnection();   // RAII handle
 *      auto res = db->execute("SELECT * FROM tiles WHERE id = ?;", { tileId });
 *
 ***************************************************************************************************/
#pragma once

/* STL ***************************************************************/
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

/* 3rd-party (SQLite) ***********************************************/
#ifdef MOSAICBOARD_USE_SQLITE
    #include <sqlite3.h>
#endif

namespace Mosaic::Repository {

/* ============================================================================================== */
/*  Database-agnostic primitives                                                                   */
/* ============================================================================================== */

/* Exception hierarchy -------------------------------------------------------------------------- */
class DatabaseError : public std::runtime_error {
public:
    explicit DatabaseError(const std::string& msg) : std::runtime_error(msg) {}
};

class ConnectionTimeout : public DatabaseError {
public:
    explicit ConnectionTimeout(const std::string& msg) : DatabaseError(msg) {}
};

/* Enums / Basic types -------------------------------------------------------------------------- */
enum class DBType { SQLite /*, PostgreSQL, MySQL, … */ };

/* Named/Positional binding value */
using BindingValue = std::variant<std::nullptr_t, int64_t, double, std::string, std::vector<std::byte>>;
using Bindings     = std::vector<BindingValue>;

/* Simple JSON-like result type */
using QueryRow    = std::unordered_map<std::string, std::string>;
using QueryResult = std::vector<QueryRow>;

/* ============================================================================================== */
/*  IDatabaseConnection – Strategy Interface                                                      */
/* ============================================================================================== */

class IDatabaseConnection {
public:
    virtual ~IDatabaseConnection() = default;

    virtual QueryResult execute(const std::string& sql,
                                const Bindings&    positionalArgs = {}) = 0;

    virtual uint64_t executeNonQuery(const std::string& sql,
                                     const Bindings&    positionalArgs = {}) = 0;

    virtual void begin()  = 0;
    virtual void commit() = 0;
    virtual void rollback() = 0;
};

/* ============================================================================================== */
/*  SQLite implementation (default)                                                               */
/* ============================================================================================== */
#ifdef MOSAICBOARD_USE_SQLITE
class SQLiteConnection final : public IDatabaseConnection {
public:
    explicit SQLiteConnection(const std::string& dbPath) {
        if (sqlite3_open_v2(dbPath.c_str(), &m_db,
                            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                            nullptr) != SQLITE_OK) {
            throw DatabaseError("SQLite: failed to open database: " +
                                std::string(sqlite3_errmsg(m_db)));
        }
        // Pragmas for performance & safety
        execPragma("PRAGMA foreign_keys = ON;");
        execPragma("PRAGMA journal_mode = WAL;");
    }

    ~SQLiteConnection() override { sqlite3_close_v2(m_db); }

    QueryResult execute(const std::string& sql, const Bindings& positionalArgs) override {
        sqlite3_stmt* stmt = nullptr;
        prepare(sql, &stmt);
        bindParameters(stmt, positionalArgs);

        QueryResult result;

        while (true) {
            int rc = sqlite3_step(stmt);
            if (rc == SQLITE_ROW) {
                QueryRow row;
                const int colCount = sqlite3_column_count(stmt);
                for (int i = 0; i < colCount; ++i) {
                    const char* colName  = sqlite3_column_name(stmt, i);
                    const char* colValue = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
                    row.emplace(colName ? colName : "", colValue ? colValue : "");
                }
                result.emplace_back(std::move(row));
            } else if (rc == SQLITE_DONE) {
                break;
            } else {
                std::string err = sqlite3_errmsg(m_db);
                sqlite3_finalize(stmt);
                throw DatabaseError("SQLite execute error: " + err);
            }
        }
        sqlite3_finalize(stmt);
        return result;
    }

    uint64_t executeNonQuery(const std::string& sql, const Bindings& positionalArgs) override {
        sqlite3_stmt* stmt = nullptr;
        prepare(sql, &stmt);
        bindParameters(stmt, positionalArgs);

        int rc = sqlite3_step(stmt);
        if (rc != SQLITE_DONE) {
            std::string err = sqlite3_errmsg(m_db);
            sqlite3_finalize(stmt);
            throw DatabaseError("SQLite executeNonQuery error: " + err);
        }
        auto changes = sqlite3_changes64(m_db);
        sqlite3_finalize(stmt);
        return static_cast<uint64_t>(changes);
    }

    void begin() override { execPragma("BEGIN TRANSACTION;"); }
    void commit() override { execPragma("COMMIT;"); }
    void rollback() override { execPragma("ROLLBACK;"); }

private:
    sqlite3* m_db{ nullptr };

    void execPragma(const std::string& cmd) {
        char* errmsg = nullptr;
        if (sqlite3_exec(m_db, cmd.c_str(), nullptr, nullptr, &errmsg) != SQLITE_OK) {
            std::string err = errmsg ? errmsg : "unknown error";
            sqlite3_free(errmsg);
            throw DatabaseError("SQLite pragma failed: " + err);
        }
    }

    inline void prepare(const std::string& sql, sqlite3_stmt** stmt) {
        if (sqlite3_prepare_v2(m_db, sql.c_str(), -1, stmt, nullptr) != SQLITE_OK) {
            throw DatabaseError("SQLite prepare failed: " +
                                std::string(sqlite3_errmsg(m_db)));
        }
    }

    inline void bindParameters(sqlite3_stmt* stmt, const Bindings& args) {
        for (std::size_t i = 0; i < args.size(); ++i) {
            const auto& v = args[i];
            int idx       = static_cast<int>(i + 1); // sqlite3 is 1-based
            if (std::holds_alternative<std::nullptr_t>(v)) {
                sqlite3_bind_null(stmt, idx);
            } else if (std::holds_alternative<int64_t>(v)) {
                sqlite3_bind_int64(stmt, idx, std::get<int64_t>(v));
            } else if (std::holds_alternative<double>(v)) {
                sqlite3_bind_double(stmt, idx, std::get<double>(v));
            } else if (std::holds_alternative<std::string>(v)) {
                const auto& s = std::get<std::string>(v);
                sqlite3_bind_text(stmt, idx, s.c_str(), static_cast<int>(s.size()), SQLITE_TRANSIENT);
            } else if (std::holds_alternative<std::vector<std::byte>>(v)) {
                const auto& blob = std::get<std::vector<std::byte>>(v);
                sqlite3_bind_blob(stmt, idx, blob.data(), static_cast<int>(blob.size()), SQLITE_TRANSIENT);
            } else {
                throw DatabaseError("SQLite bindParameters: unsupported variant type");
            }
        }
    }
};
#endif // MOSAICBOARD_USE_SQLITE

/* ============================================================================================== */
/*  DatabaseConfig                                                                                */
/* ============================================================================================== */
struct DatabaseConfig {
    DBType      type           = DBType::SQLite;
    std::string databasePath   = "mosaic.db";
    std::size_t poolSize       = 8;
    bool        enableTracing  = false;
};

/* ============================================================================================== */
/*  DatabaseManager (Singleton)                                                                    */
/* ============================================================================================== */

class DatabaseManager {
public:
    /* Init must be called once from the main thread before any access */
    static void init(const DatabaseConfig& cfg) {
        static std::once_flag onceFlag;
        std::call_once(onceFlag, [&cfg]() { s_instance.reset(new DatabaseManager(cfg)); });
    }

    static DatabaseManager& instance() {
        if (!s_instance) { throw DatabaseError("DatabaseManager not initialised"); }
        return *s_instance;
    }

    /* Non-copyable / non-movable */
    DatabaseManager(const DatabaseManager&)            = delete;
    DatabaseManager(DatabaseManager&&)                 = delete;
    DatabaseManager& operator=(const DatabaseManager&) = delete;
    DatabaseManager& operator=(DatabaseManager&&)      = delete;

    /* RAII Lease --- Automatically returns connection to pool on destruction */
    class ConnectionLease {
    public:
        ConnectionLease(std::shared_ptr<IDatabaseConnection> conn,
                        std::function<void(std::shared_ptr<IDatabaseConnection>)> releaser)
            : m_conn(std::move(conn))
            , m_releaser(std::move(releaser)) {}

        ~ConnectionLease() {
            if (m_conn && m_releaser) { m_releaser(std::move(m_conn)); }
        }

        IDatabaseConnection* operator->() { return m_conn.get(); }

    private:
        std::shared_ptr<IDatabaseConnection>            m_conn;
        std::function<void(std::shared_ptr<IDatabaseConnection>)> m_releaser;
    };

    /* Lease a connection (blocks until available or timeout) */
    ConnectionLease leaseConnection(std::chrono::milliseconds timeout = std::chrono::seconds(5)) {
        std::unique_lock<std::mutex> lk(m_poolMtx);
        if (!m_poolCv.wait_for(lk, timeout, [this] { return !m_idleConnections.empty(); })) {
            throw ConnectionTimeout("DatabaseConnection lease timed out");
        }

        auto conn = m_idleConnections.front();
        m_idleConnections.pop();
        return { std::move(conn), [this](std::shared_ptr<IDatabaseConnection> c) { release(std::move(c)); } };
    }

    /* Helper for fire-and-forget (non-query) */
    uint64_t exec(const std::string& sql, const Bindings& args = {}) {
        auto lease = leaseConnection();
        return lease->executeNonQuery(sql, args);
    }

private:
    explicit DatabaseManager(const DatabaseConfig& cfg) : m_cfg(cfg) {
        for (std::size_t i = 0; i < m_cfg.poolSize; ++i) { m_idleConnections.push(createConnection()); }
    }

    std::shared_ptr<IDatabaseConnection> createConnection() {
        switch (m_cfg.type) {
#ifdef MOSAICBOARD_USE_SQLITE
        case DBType::SQLite:
            return std::make_shared<SQLiteConnection>(m_cfg.databasePath);
#endif
        default:
            throw DatabaseError("Unsupported DBType");
        }
    }

    void release(std::shared_ptr<IDatabaseConnection> conn) {
        {
            std::lock_guard<std::mutex> lk(m_poolMtx);
            m_idleConnections.push(std::move(conn));
        }
        m_poolCv.notify_one();
    }

    /* Members ---------------------------------------------------------------------------------- */
    DatabaseConfig m_cfg;

    std::mutex                                     m_poolMtx;
    std::condition_variable                        m_poolCv;
    std::queue<std::shared_ptr<IDatabaseConnection>> m_idleConnections;

    static inline std::unique_ptr<DatabaseManager> s_instance{ nullptr };
};

} // namespace Mosaic::Repository

/* ============================================================================================== */
/*  Compile-time feature toggles                                                                  */
/* ============================================================================================== */
/* Default to SQLite if nothing else defined */
#if !defined(MOSAICBOARD_USE_SQLITE)
    #define MOSAICBOARD_USE_SQLITE
#endif
```