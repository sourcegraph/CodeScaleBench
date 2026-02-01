#include "UserService.h"

#include <chrono>
#include <fmt/format.h>
#include <nlohmann/json.hpp>

#include <mutex>
#include <unordered_map>

#include "Auth/PasswordHasher.h"
#include "Auth/SocialAuthGateway.h"
#include "Infrastructure/Logger.h"
#include "Infrastructure/Metrics.h"
#include "Repositories/UserRepository.h"
#include "Services/TokenService.h"

using namespace MosaicBoardStudio::Infrastructure;
using json = nlohmann::json;

namespace MosaicBoardStudio::Services
{
namespace
{
//---------------------------------------------------------------------------------------------------------------------
// A tiny, thread-safe TTL cache used to avoid hitting the DB for frequently accessed user profiles.
// In the production system this would be swapped for Redis or Memcached, but for local runtime it is useful.
//---------------------------------------------------------------------------------------------------------------------
template <typename Key, typename Value>
class TTLCache
{
public:
    TTLCache(std::chrono::seconds ttl, std::size_t maxEntries)
        : m_ttl{ttl}, m_maxEntries{maxEntries}
    {
    }

    void insert(Key key, Value value)
    {
        std::lock_guard<std::mutex> lk{m_mutex};
        pruneIfNecessary();
        m_items.emplace(std::move(key),
                        CacheItem{std::move(value), std::chrono::steady_clock::now() + m_ttl});
    }

    std::optional<Value> fetch(const Key& key)
    {
        std::lock_guard<std::mutex> lk{m_mutex};
        const auto it = m_items.find(key);
        if (it == m_items.end())
            return std::nullopt;

        if (std::chrono::steady_clock::now() > it->second.expiry)
        {
            m_items.erase(it);
            return std::nullopt;
        }
        return it->second.payload;
    }

    void invalidate(const Key& key)
    {
        std::lock_guard<std::mutex> lk{m_mutex};
        m_items.erase(key);
    }

private:
    struct CacheItem
    {
        Value                      payload;
        std::chrono::steady_clock::time_point expiry;
    };

    void pruneIfNecessary()
    {
        if (m_items.size() < m_maxEntries)
            return;

        // Purge oldest TTL element (a naïve implementation; O(n))
        auto oldest = m_items.begin();
        for (auto it = std::next(m_items.begin()); it != m_items.end(); ++it)
        {
            if (it->second.expiry < oldest->second.expiry)
                oldest = it;
        }
        m_items.erase(oldest);
    }

    std::chrono::seconds                     m_ttl;
    std::size_t                              m_maxEntries;
    std::unordered_map<Key, CacheItem>       m_items;
    std::mutex                               m_mutex;
};

} // anonymous namespace

//---------------------------------------------------------------------------------------------------------------------
// UserService implementation
//---------------------------------------------------------------------------------------------------------------------

UserService::UserService(std::shared_ptr<Repositories::UserRepository> userRepo,
                         std::shared_ptr<TokenService>                 tokenService,
                         std::shared_ptr<PasswordHasher>              hasher,
                         std::shared_ptr<SocialAuthGateway>           socialAuth,
                         std::shared_ptr<Logger>                      logger)
    : m_userRepo{std::move(userRepo)}
    , m_tokenService{std::move(tokenService)}
    , m_hasher{std::move(hasher)}
    , m_socialAuth{std::move(socialAuth)}
    , m_logger{std::move(logger)}
    , m_profileCache{std::make_unique<TTLCache<std::string, DTO::User>>(std::chrono::seconds{60},
                                                                        1024)}
{
    if (!m_userRepo || !m_tokenService || !m_hasher || !m_socialAuth || !m_logger)
        throw std::invalid_argument("UserService: dependencies may not be null");
}

//---------------------------------------------------------------------------------------------------------------------
// Registration
//---------------------------------------------------------------------------------------------------------------------
DTO::AuthResponse UserService::registerUser(const DTO::RegistrationRequest& request)
{
    Metrics::Timer timer("user_service.register");

    if (request.email.empty() || request.password.empty())
        throw std::invalid_argument("Registration requires email and password");

    if (m_userRepo->existsByEmail(request.email))
        throw DuplicateResourceError("Email is already registered");

    auto salt = m_hasher->generateSalt();
    auto hash = m_hasher->hashPassword(request.password, salt);

    Entities::User entity;
    entity.id            = Utilities::generateUuidV4();
    entity.email         = request.email;
    entity.passwordHash  = std::move(hash);
    entity.passwordSalt  = std::move(salt);
    entity.displayName   = request.displayName.empty() ? "Anonymous" : request.displayName;
    entity.createdAt     = std::chrono::system_clock::now();
    entity.lastLoginAt   = entity.createdAt;

    m_userRepo->save(entity);

    m_logger->info(fmt::format("New user registered: {}", entity.id));

    // Auto-login after registration
    auto token   = m_tokenService->generateToken(entity.id, entity.email);
    DTO::User dto{entity.id, entity.email, entity.displayName, entity.avatarUrl};

    m_profileCache->insert(dto.id, dto);

    return DTO::AuthResponse{std::move(token), dto};
}

//---------------------------------------------------------------------------------------------------------------------
// Email & Password Login
//---------------------------------------------------------------------------------------------------------------------
DTO::AuthResponse UserService::loginUser(const DTO::LoginRequest& request)
{
    Metrics::Timer timer("user_service.login");

    auto userOpt = m_userRepo->findByEmail(request.email);
    if (!userOpt)
        throw AuthenticationError("Invalid credentials");

    const auto& user = *userOpt;

    if (!m_hasher->validatePassword(request.password, user.passwordSalt, user.passwordHash))
        throw AuthenticationError("Invalid credentials");

    m_userRepo->updateLastLogin(user.id);

    auto token = m_tokenService->generateToken(user.id, user.email);
    DTO::User dto{user.id, user.email, user.displayName, user.avatarUrl};

    m_profileCache->insert(dto.id, dto);

    m_logger->debug(fmt::format("User logged in: {}", user.id));

    return DTO::AuthResponse{std::move(token), dto};
}

//---------------------------------------------------------------------------------------------------------------------
// Social Login
//---------------------------------------------------------------------------------------------------------------------
DTO::AuthResponse UserService::socialLogin(SocialProvider               provider,
                                           const DTO::SocialAuthPayload payload)
{
    Metrics::Timer timer("user_service.social_login");

    auto profile = m_socialAuth->exchangeCodeForProfile(provider, payload.authCode);
    if (!profile)
        throw AuthenticationError("Social login failed");

    auto userOpt = m_userRepo->findBySocialId(provider, profile->id);

    Entities::User userEntity;
    bool           isNewUser = !userOpt.has_value();

    if (isNewUser)
    {
        userEntity.id          = Utilities::generateUuidV4();
        userEntity.email       = profile->email;
        userEntity.displayName = profile->displayName;
        userEntity.avatarUrl   = profile->avatarUrl;
        userEntity.createdAt   = std::chrono::system_clock::now();
        userEntity.lastLoginAt = userEntity.createdAt;
        userEntity.socialIds[provider] = profile->id;

        m_userRepo->save(userEntity);

        m_logger->info(fmt::format("New social user created [{}:{}]",
                                   to_string(provider),
                                   userEntity.id));
    }
    else
    {
        userEntity              = *userOpt;
        userEntity.lastLoginAt  = std::chrono::system_clock::now();
        userEntity.avatarUrl    = profile->avatarUrl; // refresh avatar on each login
        m_userRepo->update(userEntity);
    }

    auto token = m_tokenService->generateToken(userEntity.id, userEntity.email);
    DTO::User dto{userEntity.id, userEntity.email, userEntity.displayName, userEntity.avatarUrl};

    m_profileCache->insert(dto.id, dto);

    return DTO::AuthResponse{std::move(token), dto};
}

//---------------------------------------------------------------------------------------------------------------------
// Get Profile
//---------------------------------------------------------------------------------------------------------------------
DTO::User UserService::getProfile(const std::string& userId)
{
    if (auto cached = m_profileCache->fetch(userId); cached.has_value())
        return *cached;

    auto userOpt = m_userRepo->findById(userId);
    if (!userOpt)
        throw ResourceNotFoundError(fmt::format("No such user {}", userId));

    const auto& e = *userOpt;
    DTO::User dto{e.id, e.email, e.displayName, e.avatarUrl};

    m_profileCache->insert(dto.id, dto);

    return dto;
}

//---------------------------------------------------------------------------------------------------------------------
// Update Profile (display name + avatar + metadata)
//---------------------------------------------------------------------------------------------------------------------
DTO::User UserService::updateProfile(const std::string&             userId,
                                     const DTO::UpdateProfileInput& input)
{
    Metrics::Timer timer("user_service.update_profile");

    auto userOpt = m_userRepo->findById(userId);
    if (!userOpt)
        throw ResourceNotFoundError("User not found");

    auto entity = *userOpt;

    bool changed = false;

    if (input.displayName && *input.displayName != entity.displayName)
    {
        entity.displayName = *input.displayName;
        changed            = true;
    }
    if (input.avatarUrl && *input.avatarUrl != entity.avatarUrl)
    {
        entity.avatarUrl = *input.avatarUrl;
        changed          = true;
    }
    if (!changed)
        return DTO::User{entity.id, entity.email, entity.displayName, entity.avatarUrl};

    m_userRepo->update(entity);

    m_profileCache->invalidate(entity.id);

    DTO::User dto{entity.id, entity.email, entity.displayName, entity.avatarUrl};
    m_profileCache->insert(entity.id, dto);

    return dto;
}

//---------------------------------------------------------------------------------------------------------------------
// Logout simply invalidates the token client-side; we record lastLogout for analytics.
//---------------------------------------------------------------------------------------------------------------------
void UserService::logout(const std::string& userId)
{
    m_userRepo->updateLastLogout(userId);
    m_logger->debug(fmt::format("User logged out: {}", userId));
}

} // namespace MosaicBoardStudio::Services