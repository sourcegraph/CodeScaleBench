#pragma once
/**
 *  MosaicBoard Studio – User Repository
 *  ------------------------------------
 *  Production-quality, header-only implementation of the user repository that
 *  demonstrates an opinionated repository pattern backed by SQLite, equipped
 *  with an optional, thread-safe in-memory cache.
 *
 *  NOTE:
 *     • This file is entirely self-contained to simplify integration in this
 *       showcase project.  In a real-world code-base, entities, database
 *       abstractions, UUID helpers, and caching utilities would be factored
 *       out into their own translation units / libraries.
 *     • Linking requires SQLite3 (`-lsqlite3`) and Boost.UUID.
 */

#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>

#include <sqlite3.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace MosaicBoard::Data
{
    /**
     * Very thin interface a concrete SQLite connection must fulfil.
     * Allows the repository to stay decoupled from the actual connection
     * life-cycle management.
     */
    class IDatabaseConnection
    {
    public:
        virtual ~IDatabaseConnection()                                   = default;
        virtual sqlite3* handle()                                 noexcept = 0;
    };
} // namespace MosaicBoard::Data

namespace MosaicBoard::Domain::Entities
{
    /**
     *  Domain entity representing an application user.
     *  Only a subset of fields typically found in production code.
     */
    struct User
    {
        boost::uuids::uuid id;
        std::string        email;
        std::string        passwordHash;
        std::string        displayName;
        std::time_t        createdAt{};
        bool               isActive{true};
    };

    struct UserCreateRequest
    {
        std::string email;
        std::string plainPassword;
        std::string displayName;
    };
} // namespace MosaicBoard::Domain::Entities

namespace MosaicBoard::Util
{
    // Hash functor for boost::uuids::uuid to be used inside unordered_map
    struct UuidHash
    {
        std::size_t operator()(const boost::uuids::uuid& uuid) const noexcept
        {
            return boost::hash<boost::uuids::uuid>()(uuid);
        }
    };

    // Convenience helpers for UUID/string conversions
    inline std::string uuidToString(const boost::uuids::uuid& id)
    {
        return boost::uuids::to_string(id);
    }

    inline boost::uuids::uuid stringToUuid(const std::string& s)
    {
        boost::uuids::string_generator gen;
        return gen(s);
    }
} // namespace MosaicBoard::Util

namespace MosaicBoard::Repositories
{

using MosaicBoard::Data::IDatabaseConnection;
using MosaicBoard::Domain::Entities::User;
using MosaicBoard::Domain::Entities::UserCreateRequest;

/**
 * UserRepository
 * --------------
 * Exposes CRUD operations for the User domain entity with integrated,
 * TTL-based in-memory caching and robust error handling.
 */
class UserRepository final
{
public:
    struct Options
    {
        bool                       enableCache{true};
        std::chrono::minutes       cacheTtl{5};
        std::chrono::milliseconds  busyTimeout{3000};
    };

    explicit UserRepository(std::shared_ptr<IDatabaseConnection> db, Options opts = {})
        : m_db(std::move(db))
        , m_options(opts)
    {
        if (!m_db || !m_db->handle())
            throw std::invalid_argument("UserRepository: database connection is null");

        sqlite3_busy_timeout(m_db->handle(), static_cast<int>(m_options.busyTimeout.count()));
        ensureSchema();
    }

    // -------------------------------------------------------------------------
    // CRUD
    // -------------------------------------------------------------------------

    std::optional<User> getById(const boost::uuids::uuid& id)
    {
        // 1. Check cache
        if (m_options.enableCache)
            if (auto cached = fetchFromCache(id))
                return cached;

        // 2. Query database
        const std::string sql =
            "SELECT id, email, password_hash, display_name, created_at, is_active "
            "FROM users WHERE id = ?1 LIMIT 1;";

        sqlite3_stmt* stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);
        if (sqlite3_bind_text(stmt, 1, Util::uuidToString(id).c_str(), -1, SQLITE_STATIC) != SQLITE_OK)
            throwSqliteError("Failed to bind id");

        auto result = stepUser(stmt);
        sqlite3_finalize(stmt);

        if (result && m_options.enableCache)
            cacheUser(*result);

        return result;
    }

    std::optional<User> getByEmail(const std::string& email)
    {
        const std::string sql =
            "SELECT id, email, password_hash, display_name, created_at, is_active "
            "FROM users WHERE email = ?1 COLLATE NOCASE LIMIT 1;";

        sqlite3_stmt* stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);
        if (sqlite3_bind_text(stmt, 1, email.c_str(), -1, SQLITE_STATIC) != SQLITE_OK)
            throwSqliteError("Failed to bind email");

        auto user = stepUser(stmt);
        sqlite3_finalize(stmt);

        if (user && m_options.enableCache)
            cacheUser(*user);

        return user;
    }

    boost::uuids::uuid create(const UserCreateRequest& req)
    {
        const boost::uuids::uuid id = boost::uuids::random_generator()();
        const auto now              = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());

        const std::string sql =
            "INSERT INTO users "
            "(id, email, password_hash, display_name, created_at, is_active) "
            "VALUES (?1, ?2, ?3, ?4, ?5, 1);";

        sqlite3_stmt* stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);

        const std::string idStr = Util::uuidToString(id);

        if (sqlite3_bind_text(stmt, 1, idStr.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 2, req.email.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 3, hashPassword(req.plainPassword).c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 4, req.displayName.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_int64(stmt, 5, static_cast<sqlite3_int64>(now)) != SQLITE_OK)
        {
            throwSqliteError("Failed to bind parameters in create");
        }

        stepExpectDone(stmt, "insert user");
        sqlite3_finalize(stmt);

        // populate cache
        if (m_options.enableCache)
        {
            User u{ id, req.email, "(hash withheld)", req.displayName, now, true };
            cacheUser(u);
        }

        return id;
    }

    bool update(const User& u)
    {
        const std::string sql =
            "UPDATE users SET "
            "email = ?1, "
            "password_hash = ?2, "
            "display_name = ?3, "
            "is_active = ?4 "
            "WHERE id = ?5;";

        sqlite3_stmt* stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);

        if (sqlite3_bind_text(stmt, 1, u.email.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 2, u.passwordHash.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 3, u.displayName.c_str(), -1, SQLITE_STATIC) != SQLITE_OK ||
            sqlite3_bind_int(stmt, 4, u.isActive ? 1 : 0) != SQLITE_OK ||
            sqlite3_bind_text(stmt, 5, Util::uuidToString(u.id).c_str(), -1, SQLITE_STATIC) != SQLITE_OK)
        {
            throwSqliteError("Failed to bind parameters in update");
        }

        int rc = sqlite3_step(stmt);
        if (rc != SQLITE_DONE)
            throwSqliteError("Updating user failed");

        const bool updated = sqlite3_changes(m_db->handle()) > 0;
        sqlite3_finalize(stmt);

        if (updated && m_options.enableCache)
            invalidateCache(u.id);

        return updated;
    }

    bool remove(const boost::uuids::uuid& id)
    {
        const std::string sql = "DELETE FROM users WHERE id = ?1;";
        sqlite3_stmt*     stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);

        if (sqlite3_bind_text(stmt, 1, Util::uuidToString(id).c_str(), -1, SQLITE_STATIC) != SQLITE_OK)
            throwSqliteError("Failed to bind id in delete");

        int rc = sqlite3_step(stmt);
        if (rc != SQLITE_DONE)
            throwSqliteError("Deleting user failed");

        const bool removed = sqlite3_changes(m_db->handle()) > 0;
        sqlite3_finalize(stmt);

        if (removed && m_options.enableCache)
            invalidateCache(id);

        return removed;
    }

    std::vector<User> list(std::size_t limit = 100, std::size_t offset = 0)
    {
        const std::string sql =
            "SELECT id, email, password_hash, display_name, created_at, is_active "
            "FROM users "
            "ORDER BY created_at DESC "
            "LIMIT ?1 OFFSET ?2;";

        sqlite3_stmt* stmt{nullptr};
        prepareStatement(sql.c_str(), &stmt);

        if (sqlite3_bind_int64(stmt, 1, static_cast<sqlite3_int64>(limit)) != SQLITE_OK ||
            sqlite3_bind_int64(stmt, 2, static_cast<sqlite3_int64>(offset)) != SQLITE_OK)
        {
            throwSqliteError("Failed to bind pagination values");
        }

        std::vector<User> users;
        while (sqlite3_step(stmt) == SQLITE_ROW)
        {
            users.emplace_back(extractUser(stmt));
            if (m_options.enableCache)
                cacheUser(users.back());
        }

        sqlite3_finalize(stmt);
        return users;
    }

private:
    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    void ensureSchema()
    {
        constexpr const char* ddl =
            "CREATE TABLE IF NOT EXISTS users ("
            "   id TEXT PRIMARY KEY NOT NULL,"
            "   email TEXT NOT NULL UNIQUE,"
            "   password_hash TEXT NOT NULL,"
            "   display_name TEXT,"
            "   created_at INTEGER NOT NULL,"
            "   is_active INTEGER NOT NULL DEFAULT 1"
            ");";
        char* errMsg = nullptr;
        if (sqlite3_exec(m_db->handle(), ddl, nullptr, nullptr, &errMsg) != SQLITE_OK)
        {
            std::string err = errMsg ? errMsg : "unknown sqlite error";
            sqlite3_free(errMsg);
            throw std::runtime_error("UserRepository::ensureSchema: " + err);
        }
    }

    static std::string hashPassword(const std::string& plain)
    {
        // Very naive hashing placeholder. Replace w/ bcrypt/argon2 in prod.
        std::hash<std::string> hasher;
        return std::to_string(hasher(plain));
    }

    void prepareStatement(const char* sql, sqlite3_stmt** stmt) const
    {
        if (sqlite3_prepare_v2(m_db->handle(), sql, -1, stmt, nullptr) != SQLITE_OK)
            throwSqliteError("Preparing statement failed");
    }

    // Throws runtime_error with sqlite3_errmsg
    [[noreturn]] void throwSqliteError(const std::string& what) const
    {
        std::string err = what + " – " + sqlite3_errmsg(m_db->handle());
        throw std::runtime_error(err);
    }

    void stepExpectDone(sqlite3_stmt* stmt, const char* opName) const
    {
        int rc = sqlite3_step(stmt);
        if (rc != SQLITE_DONE)
            throwSqliteError(std::string("Failed to ") + opName);
    }

    std::optional<User> stepUser(sqlite3_stmt* stmt)
    {
        int rc = sqlite3_step(stmt);
        if (rc == SQLITE_ROW)
            return extractUser(stmt);
        if (rc == SQLITE_DONE)
            return std::nullopt;
        throwSqliteError("Reading user row failed");
    }

    User extractUser(sqlite3_stmt* stmt)
    {
        User u;
        u.id           = Util::stringToUuid(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)));
        u.email        = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        u.passwordHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        u.displayName  = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        u.createdAt    = static_cast<std::time_t>(sqlite3_column_int64(stmt, 4));
        u.isActive     = sqlite3_column_int(stmt, 5) != 0;
        return u;
    }

    // -------------------------------------------------------------------------
    // Caching
    // -------------------------------------------------------------------------

    struct CachedUser
    {
        User                                   user;
        std::chrono::steady_clock::time_point  expiresAt;
    };

    void cacheUser(const User& u)
    {
        if (!m_options.enableCache) return;

        std::unique_lock lock(m_cacheMutex);
        m_userCache[u.id] = CachedUser{
            u, std::chrono::steady_clock::now() + m_options.cacheTtl
        };
    }

    std::optional<User> fetchFromCache(const boost::uuids::uuid& id) const
    {
        if (!m_options.enableCache) return std::nullopt;

        std::shared_lock lock(m_cacheMutex);
        auto it = m_userCache.find(id);
        if (it == m_userCache.end()) return std::nullopt;

        if (std::chrono::steady_clock::now() > it->second.expiresAt)
            return std::nullopt; // expired – caller may reload and re-cache

        return it->second.user;
    }

    void invalidateCache(const boost::uuids::uuid& id)
    {
        std::unique_lock lock(m_cacheMutex);
        m_userCache.erase(id);
    }

    // -------------------------------------------------------------------------
    // Members
    // -------------------------------------------------------------------------

    std::shared_ptr<IDatabaseConnection> m_db;
    Options                              m_options;

    mutable std::shared_mutex
                            m_cacheMutex;
    std::unordered_map<boost::uuids::uuid, CachedUser, Util::UuidHash>
                            m_userCache;
};

} // namespace MosaicBoard::Repositories