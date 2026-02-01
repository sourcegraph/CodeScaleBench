#pragma once
/***************************************************************************************************
 *  MosaicBoard Studio – User Service
 *
 *  File        : MosaicBoardStudio/src/services/UserService.h
 *  Description : High-level façade that orchestrates user-related workflows such as account
 *                creation, authentication, session management, social log-in, and cached profile
 *                retrieval.  The service follows the Repository and Service-Layer patterns and
 *                depends on externally supplied collaborators (repositories, cache, logger, etc.)
 *                that are injected through the constructor, making the code easy to unit-test and
 *                replace in different deployment scenarios.
 *
 *  Copyright   : (c) 2024 MosaicBoard Studio
 *  License     : MIT
 **************************************************************************************************/
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mosaic::domain
{
    struct User;    // Forward declaration of domain entity
} // namespace mosaic::domain

namespace mosaic::repository
{
    class IUserRepository;      // CRUD access to persistence layer
} // namespace mosaic::repository

namespace mosaic::security
{
    class IAuthTokenService;    // JWT / session token generator & validator
    class IPasswordHasher;      // Abstracts bcrypt / scrypt / Argon2, etc.
} // namespace mosaic::security

namespace mosaic::cache
{
    class ICacheProvider;       // Abstraction for Redis/Memcached/in-proc cache
} // namespace mosaic::cache

namespace mosaic::logging
{
    class ILogger;              // Unified, sink-agnostic logging interface
} // namespace mosaic::logging

namespace mosaic::services
{
/**
 * @brief A lightweight result type similar to std::expected (scheduled for C++23).
 *
 * The template avoids an additional dependency while still providing an expressive
 * alternative to throwing exceptions for recoverable errors.  In success cases the
 * `value()` accessor is valid; in error cases `error()` is valid.
 */
template <typename T>
class ServiceResult
{
public:
    using ValueType = T;

    static ServiceResult<T> Ok(T value)                        { return ServiceResult<T>(std::move(value), {}); }
    static ServiceResult<T> Err(std::string errMsg)            { return ServiceResult<T>({}, std::move(errMsg)); }

    bool                isOk()      const noexcept             { return !m_error.has_value(); }
    const T&            value()     const                      { if (!isOk())  throw std::logic_error("Bad access"); return *m_value; }
    T&                  value()                           { if (!isOk())  throw std::logic_error("Bad access"); return *m_value; }
    const std::string&  error()     const noexcept             { return *m_error; }

private:
    ServiceResult(std::optional<T> val, std::optional<std::string> err)
        : m_value(std::move(val)), m_error(std::move(err))
    {}

    std::optional<T>        m_value;
    std::optional<std::string> m_error;
};

/**
 * @brief Data transfer object for inbound registration requests.
 */
struct UserRegistration
{
    std::string username;
    std::string email;
    std::string password;                // Plaintext; hashed before persistence
};

/**
 * @brief Data transfer object for login credentials.
 */
struct Credentials
{
    std::string login;                   // username or e-mail
    std::string password;
};

/**
 * @brief Composite result returned after a successful authentication.
 */
struct AuthSession
{
    mosaic::domain::User   user;
    std::string            accessToken;  // JWT or opaque token
    std::chrono::system_clock::time_point expiresAt;
};

/**
 * @class UserService
 *
 * @note All public-facing methods are thread-safe.  Internally the class uses a
 *       readers-writer lock for an in-memory profile cache.  The service performs
 *       lightweight validation but defers heavy business rules to downstream
 *       collaborators where appropriate.
 */
class UserService final
{
public:
    UserService(std::shared_ptr<mosaic::repository::IUserRepository> userRepo,
                std::shared_ptr<mosaic::security::IAuthTokenService> tokenSvc,
                std::shared_ptr<mosaic::security::IPasswordHasher>  hasher,
                std::shared_ptr<mosaic::cache::ICacheProvider>      cache,
                std::shared_ptr<mosaic::logging::ILogger>           logger) noexcept;

    ~UserService() = default;

    UserService(const UserService&)            = delete;
    UserService& operator=(const UserService&) = delete;
    UserService(UserService&&)                 = delete;
    UserService& operator=(UserService&&)      = delete;

    /*-----------------------------------------------------------------------------
     |  Business API – Registration / Authentication
     *----------------------------------------------------------------------------*/
    ServiceResult<AuthSession> registerUser(const UserRegistration& dto);
    ServiceResult<AuthSession> login(const Credentials& cred);
    ServiceResult<void>        logout(std::string_view token);

    /*-----------------------------------------------------------------------------
     |  Business API – Profile Management
     *----------------------------------------------------------------------------*/
    std::optional<mosaic::domain::User> getUserById(const std::string& userId);
    ServiceResult<mosaic::domain::User> updateProfile(const mosaic::domain::User& user);
    ServiceResult<void>                 deleteUser(const std::string& userId);

    /*-----------------------------------------------------------------------------
     |  Misc
     *----------------------------------------------------------------------------*/
    void                                flushCache();   // Explicitly drop every cached profile

private:
    /*-----------------------------------------------------------------------------
     |  Validation helpers
     *----------------------------------------------------------------------------*/
    [[nodiscard]] bool isEmailValid(std::string_view email) const;
    [[nodiscard]] bool isUsernameValid(std::string_view user) const;

    /*-----------------------------------------------------------------------------
     |  Internals
     *----------------------------------------------------------------------------*/
    AuthSession buildSession(const mosaic::domain::User& user) const;

    // Dependencies
    std::shared_ptr<mosaic::repository::IUserRepository> m_userRepo;
    std::shared_ptr<mosaic::security::IAuthTokenService> m_tokenSvc;
    std::shared_ptr<mosaic::security::IPasswordHasher>  m_hasher;
    std::shared_ptr<mosaic::cache::ICacheProvider>      m_cache;
    std::shared_ptr<mosaic::logging::ILogger>           m_logger;

    // Simple in-process profile cache (last-writer-wins)
    mutable std::unordered_map<std::string, mosaic::domain::User> m_profileCache;
    mutable std::shared_mutex                                     m_cacheMutex;
};

/*==================================================================================================
=                               Inline / Header-Only Definitions                                  =
==================================================================================================*/

inline UserService::UserService(std::shared_ptr<mosaic::repository::IUserRepository> userRepo,
                                std::shared_ptr<mosaic::security::IAuthTokenService> tokenSvc,
                                std::shared_ptr<mosaic::security::IPasswordHasher>  hasher,
                                std::shared_ptr<mosaic::cache::ICacheProvider>      cache,
                                std::shared_ptr<mosaic::logging::ILogger>           logger) noexcept
    : m_userRepo(std::move(userRepo))
    , m_tokenSvc(std::move(tokenSvc))
    , m_hasher(std::move(hasher))
    , m_cache(std::move(cache))
    , m_logger(std::move(logger))
{
    // Dependency sanity check in debug configuration
    assert(m_userRepo && m_tokenSvc && m_hasher && m_cache && m_logger);
}

/*--------------------------------- Registration -----------------------------------------------*/
inline ServiceResult<AuthSession> UserService::registerUser(const UserRegistration& dto)
{
    try
    {
        if (!isUsernameValid(dto.username))
            return ServiceResult<AuthSession>::Err("Username contains invalid characters or length.");

        if (!isEmailValid(dto.email))
            return ServiceResult<AuthSession>::Err("E-mail address is not syntactically valid.");

        // Check duplicates
        if (m_userRepo->existsByUsername(dto.username))
            return ServiceResult<AuthSession>::Err("Username already in use.");

        if (m_userRepo->existsByEmail(dto.email))
            return ServiceResult<AuthSession>::Err("E-mail already in use.");

        auto hashed = m_hasher->hash(dto.password);
        mosaic::domain::User newUser{ dto.username, dto.email, hashed };
        auto persisted = m_userRepo->create(newUser);

        // Update cache
        {
            std::unique_lock lock(m_cacheMutex);
            m_profileCache[persisted.id] = persisted;
        }

        auto session = buildSession(persisted);
        m_logger->info("User '{}' registered successfully.", persisted.username);

        return ServiceResult<AuthSession>::Ok(std::move(session));
    }
    catch (const std::exception& ex)
    {
        m_logger->error("registerUser: {}", ex.what());
        return ServiceResult<AuthSession>::Err("Internal server error.");
    }
}

/*----------------------------------- Login ----------------------------------------------------*/
inline ServiceResult<AuthSession> UserService::login(const Credentials& cred)
{
    try
    {
        auto userOpt = m_userRepo->findByLogin(cred.login);
        if (!userOpt)
            return ServiceResult<AuthSession>::Err("Invalid credentials.");

        const auto& user = *userOpt;
        if (!m_hasher->verify(cred.password, user.passwordHash))
            return ServiceResult<AuthSession>::Err("Invalid credentials.");

        auto session = buildSession(user);
        m_logger->info("User '{}' logged in.", user.username);

        return ServiceResult<AuthSession>::Ok(std::move(session));
    }
    catch (const std::exception& ex)
    {
        m_logger->error("login: {}", ex.what());
        return ServiceResult<AuthSession>::Err("Internal server error.");
    }
}

/*---------------------------------- Logout ----------------------------------------------------*/
inline ServiceResult<void> UserService::logout(std::string_view token)
{
    try
    {
        m_tokenSvc->revoke(token);
        return ServiceResult<void>::Ok({});
    }
    catch (const std::exception& ex)
    {
        m_logger->warn("logout: {}", ex.what());
        return ServiceResult<void>::Err("Failed to revoke token.");
    }
}

/*------------------------------ Profile Retrieval ---------------------------------------------*/
inline std::optional<mosaic::domain::User> UserService::getUserById(const std::string& userId)
{
    // 1) Check thread-safe in-proc cache
    {
        std::shared_lock lock(m_cacheMutex);
        auto it = m_profileCache.find(userId);
        if (it != m_profileCache.end())
            return it->second;
    }

    // 2) Cache miss; fallback to repository
    auto fetched = m_userRepo->findById(userId);
    if (fetched)
    {
        std::unique_lock lock(m_cacheMutex);
        m_profileCache[userId] = *fetched;
    }
    return fetched;
}

/*------------------------------ Update Profile -----------------------------------------------*/
inline ServiceResult<mosaic::domain::User> UserService::updateProfile(const mosaic::domain::User& user)
{
    try
    {
        auto updated = m_userRepo->update(user);

        // Invalidate cache entry
        {
            std::unique_lock lock(m_cacheMutex);
            m_profileCache.erase(user.id);
            m_profileCache[user.id] = updated;
        }
        m_logger->info("User '{}' updated profile.", user.username);
        return ServiceResult<mosaic::domain::User>::Ok(updated);
    }
    catch (const std::exception& ex)
    {
        m_logger->error("updateProfile: {}", ex.what());
        return ServiceResult<mosaic::domain::User>::Err("Failed to persist changes.");
    }
}

/*------------------------------- Delete Profile ----------------------------------------------*/
inline ServiceResult<void> UserService::deleteUser(const std::string& userId)
{
    try
    {
        m_userRepo->remove(userId);
        std::unique_lock lock(m_cacheMutex);
        m_profileCache.erase(userId);
        m_logger->info("User '{}' deleted.", userId);
        return ServiceResult<void>::Ok({});
    }
    catch (const std::exception& ex)
    {
        m_logger->error("deleteUser: {}", ex.what());
        return ServiceResult<void>::Err("Failed to delete user.");
    }
}

/*--------------------------------- Cache Flush -----------------------------------------------*/
inline void UserService::flushCache()
{
    std::unique_lock lock(m_cacheMutex);
    m_profileCache.clear();
    m_logger->debug("UserService cache flushed.");
}

/*==================================== Helpers ================================================*/
inline bool UserService::isEmailValid(std::string_view email) const
{
    // Simplified RFC 5322 regex
    static const std::regex kEmailRegex(R"(^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$)",
                                        std::regex::ECMAScript | std::regex::icase);
    return std::regex_match(email.begin(), email.end(), kEmailRegex);
}

inline bool UserService::isUsernameValid(std::string_view user) const
{
    static const std::regex kUsernameRegex(R"(^[A-Za-z0-9_]{3,32}$)");
    return std::regex_match(user.begin(), user.end(), kUsernameRegex);
}

inline AuthSession UserService::buildSession(const mosaic::domain::User& user) const
{
    constexpr std::chrono::minutes kDefaultTTL{ 60 };

    auto token  = m_tokenSvc->issue(user.id, kDefaultTTL);
    auto expiry = std::chrono::system_clock::now() + kDefaultTTL;

    return AuthSession{ user, std::move(token), expiry };
}

} // namespace mosaic::services