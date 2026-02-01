#include "UserRepository.h"

#include <nlohmann/json.hpp>
#include <pqxx/pqxx>
#include <spdlog/spdlog.h>

#include <chrono>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <utility>

using namespace std::chrono_literals;

namespace mosaic::repositories {

// -------------------------------------------------------------
//  Utilities
// -------------------------------------------------------------

namespace {

constexpr std::string_view kCacheUserIdPrefix    = "user:id:";
constexpr std::string_view kCacheUserEmailPrefix = "user:email:";

/// Wraps a pqxx::row into a domain User object.
User hydrateUser(const pqxx::row& r) {
    User user;
    user.id              = r["id"].as<std::string>();
    user.email           = r["email"].as<std::string>();
    user.passwordHash    = r["password_hash"].as<std::string>();
    user.displayName     = r["display_name"].as<std::string>();
    user.createdAt       = r["created_at"].as<std::string>();
    user.updatedAt       = r["updated_at"].as<std::string>();
    user.socialProvider  = r["social_provider"].is_null() ? std::nullopt
                                                          : std::make_optional(r["social_provider"].as<std::string>());
    user.socialId        = r["social_id"].is_null() ? std::nullopt
                                                    : std::make_optional(r["social_id"].as<std::string>());
    user.isActive        = r["is_active"].as<bool>();
    return user;
}

/// Serialize a User to JSON for cache storage.
nlohmann::json userToJson(const User& u) {
    return {
        {"id", u.id},
        {"email", u.email},
        {"passwordHash", u.passwordHash},
        {"displayName", u.displayName},
        {"createdAt", u.createdAt},
        {"updatedAt", u.updatedAt},
        {"socialProvider", u.socialProvider.value_or("")},
        {"socialId", u.socialId.value_or("")},
        {"isActive", u.isActive}};
}

/// Deserialize JSON payload from cache into User.
User jsonToUser(const nlohmann::json& j) {
    User u;
    u.id             = j.at("id").get<std::string>();
    u.email          = j.at("email").get<std::string>();
    u.passwordHash   = j.at("passwordHash").get<std::string>();
    u.displayName    = j.at("displayName").get<std::string>();
    u.createdAt      = j.at("createdAt").get<std::string>();
    u.updatedAt      = j.at("updatedAt").get<std::string>();
    const auto socialProvider = j.at("socialProvider").get<std::string>();
    const auto socialId       = j.at("socialId").get<std::string>();
    if (!socialProvider.empty()) u.socialProvider = socialProvider;
    if (!socialId.empty()) u.socialId = socialId;
    u.isActive       = j.at("isActive").get<bool>();
    return u;
}

} // namespace

// -------------------------------------------------------------
//  Ctor / Dtor
// -------------------------------------------------------------

UserRepository::UserRepository(std::shared_ptr<db::IDatabase> database,
                               std::shared_ptr<cache::ICache> cache,
                               std::chrono::seconds ttl)
    : _db(std::move(database)), _cache(std::move(cache)), _cacheTTL(ttl) {
    if (!_db) {
        throw std::invalid_argument("UserRepository: database dependency is null");
    }
    if (!_cache) {
        throw std::invalid_argument("UserRepository: cache dependency is null");
    }

    try {
        pqxx::work tx(_db->connection());
        tx.conn().prepare("user_find_by_id",     "SELECT * FROM users WHERE id = $1 LIMIT 1");
        tx.conn().prepare("user_find_by_email",  "SELECT * FROM users WHERE email = $1 LIMIT 1");
        tx.conn().prepare("user_insert",
                          "INSERT INTO users (id,email,password_hash,display_name,social_provider,social_id)"
                          " VALUES ($1,$2,$3,$4,$5,$6)");
        tx.conn().prepare("user_update",
                          "UPDATE users SET email=$2,password_hash=$3,display_name=$4,social_provider=$5,"
                          "social_id=$6,is_active=$7,updated_at=NOW() WHERE id=$1");
        tx.conn().prepare("user_delete", "DELETE FROM users WHERE id = $1");
        tx.commit();
    } catch (const std::exception& ex) {
        spdlog::critical("UserRepository: failed preparing statements - {}", ex.what());
        throw;
    }
}

UserRepository::~UserRepository() = default;

// -------------------------------------------------------------
//  Public API
// -------------------------------------------------------------

std::optional<User> UserRepository::findById(const std::string& id) {
    const auto cacheKey = fmt::format("{}{}", kCacheUserIdPrefix, id);

    // 1) Cache lookup
    if (auto cached = _cache->get(cacheKey)) {
        try {
            return jsonToUser(nlohmann::json::parse(*cached));
        } catch (const std::exception& ex) {
            spdlog::warn("UserRepository::findById cache deserialization failed: {}", ex.what());
            _cache->erase(cacheKey); // purge corrupted entry
        }
    }

    // 2) DB lookup
    try {
        pqxx::work tx(_db->connection());
        pqxx::result r = tx.prepared("user_find_by_id")(id).exec();
        tx.commit();
        if (r.empty()) return std::nullopt;

        const User user = hydrateUser(r.front());

        // 3) Backfill cache
        _cache->set(cacheKey, userToJson(user).dump(), _cacheTTL);
        _cache->set(fmt::format("{}{}", kCacheUserEmailPrefix, user.email), userToJson(user).dump(), _cacheTTL);

        return user;
    } catch (const std::exception& ex) {
        spdlog::error("UserRepository::findById DB failure: {}", ex.what());
        throw;
    }
}

std::optional<User> UserRepository::findByEmail(const std::string& email) {
    const auto cacheKey = fmt::format("{}{}", kCacheUserEmailPrefix, email);

    if (auto cached = _cache->get(cacheKey)) {
        try {
            return jsonToUser(nlohmann::json::parse(*cached));
        } catch (const std::exception& ex) {
            spdlog::warn("UserRepository::findByEmail cache deserialization failed: {}", ex.what());
            _cache->erase(cacheKey);
        }
    }

    try {
        pqxx::work tx(_db->connection());
        pqxx::result r = tx.prepared("user_find_by_email")(email).exec();
        tx.commit();

        if (r.empty()) return std::nullopt;

        const User user = hydrateUser(r.front());

        _cache->set(cacheKey, userToJson(user).dump(), _cacheTTL);
        _cache->set(fmt::format("{}{}", kCacheUserIdPrefix, user.id), userToJson(user).dump(), _cacheTTL);

        return user;
    } catch (const std::exception& ex) {
        spdlog::error("UserRepository::findByEmail DB failure: {}", ex.what());
        throw;
    }
}

void UserRepository::create(User& user) {
    try {
        pqxx::work tx(_db->connection());
        tx.prepared("user_insert")(user.id)(user.email)(user.passwordHash)(user.displayName)
            (user.socialProvider.has_value() ? user.socialProvider.value() : pqxx::null{})
            (user.socialId.has_value()       ? user.socialId.value()       : pqxx::null{})
            .exec();
        tx.commit();
    } catch (const std::exception& ex) {
        spdlog::error("UserRepository::create failed: {}", ex.what());
        throw;
    }

    // Warm cache
    _cache->set(fmt::format("{}{}", kCacheUserIdPrefix, user.id), userToJson(user).dump(), _cacheTTL);
    _cache->set(fmt::format("{}{}", kCacheUserEmailPrefix, user.email), userToJson(user).dump(), _cacheTTL);
}

bool UserRepository::update(const User& user) {
    bool success = false;
    try {
        pqxx::work tx(_db->connection());
        pqxx::result r = tx.prepared("user_update")(user.id)(user.email)(user.passwordHash)
                             (user.displayName)
                             (user.socialProvider.has_value() ? user.socialProvider.value() : pqxx::null{})
                             (user.socialId.has_value()       ? user.socialId.value()       : pqxx::null{})
                             (user.isActive)
                             .exec();
        success = r.affected_rows() == 1;
        tx.commit();
    } catch (const std::exception& ex) {
        spdlog::error("UserRepository::update failed: {}", ex.what());
        throw;
    }

    if (success) {
        // Invalidate and repopulate
        _cache->erase(fmt::format("{}{}", kCacheUserIdPrefix, user.id));
        _cache->erase(fmt::format("{}{}", kCacheUserEmailPrefix, user.email));
        _cache->set(fmt::format("{}{}", kCacheUserIdPrefix, user.id), userToJson(user).dump(), _cacheTTL);
        _cache->set(fmt::format("{}{}", kCacheUserEmailPrefix, user.email), userToJson(user).dump(), _cacheTTL);
    }

    return success;
}

bool UserRepository::remove(const std::string& id) {
    std::optional<User> existing = findById(id);
    if (!existing) return false;

    bool success = false;
    try {
        pqxx::work tx(_db->connection());
        pqxx::result r = tx.prepared("user_delete")(id).exec();
        success = r.affected_rows() == 1;
        tx.commit();
    } catch (const std::exception& ex) {
        spdlog::error("UserRepository::remove failed: {}", ex.what());
        throw;
    }

    if (success) {
        _cache->erase(fmt::format("{}{}", kCacheUserIdPrefix, id));
        _cache->erase(fmt::format("{}{}", kCacheUserEmailPrefix, existing->email));
    }

    return success;
}

// -------------------------------------------------------------
//  Additional Domain-Specific Helpers
// -------------------------------------------------------------

bool UserRepository::linkSocialAccount(const std::string& userId,
                                       const std::string& provider,
                                       const std::string& socialId) {
    auto userOpt = findById(userId);
    if (!userOpt) {
        return false;
    }
    User user = *userOpt;
    user.socialProvider = provider;
    user.socialId       = socialId;
    return update(user);
}

} // namespace mosaic::repositories