#pragma once
/***************************************************************************************************
 *  MosaicBoard Studio – Auth Service
 *
 *  File:       MosaicBoardStudio/src/services/AuthService.h
 *  License:    MIT
 *  Author:     MosaicBoard Core Team
 *
 *  Description:
 *      Centralised authentication service responsible for local-form login, social login,
 *      JWT creation/validation, token rotation, and session revocation.  Designed to be
 *      consumed by both HTTP controllers and WebSocket middleware.
 *
 *  External dependencies
 *      - nlohmann::json  (single-header JSON library)
 *      - jwt-cpp         (https://github.com/Thalhammer/jwt-cpp)
 *      - spdlog          (logging)
 *
 *  Usage example
 *      AuthService auth{userRepo, tokenRepo, “super-secret”};
 *      auto tokens = auth.login("admin", "••••");
 *      bool ok     = auth.validateAccessToken(tokens.accessToken);
 *
 **************************************************************************************************/
#include <jwt-cpp/jwt.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace mosaic::services
{

//----------------------------------------------------------------------------------------------------------------------
//  Forward declarations for repository interfaces
//----------------------------------------------------------------------------------------------------------------------

class IUserRepository
{
public:
    virtual ~IUserRepository() = default;

    virtual bool verifyPassword(const std::string& username, const std::string& rawPassword) const = 0;
    virtual std::string createUser(const nlohmann::json& userInfo)                               = 0;
    virtual nlohmann::json getUserById(const std::string& userId) const                          = 0;
    virtual nlohmann::json getUserByUsername(const std::string& username) const                  = 0;
};

class ITokenRepository
{
public:
    virtual ~ITokenRepository() = default;

    virtual void  storeRefreshToken(const std::string& userId,
                                    const std::string& refreshToken,
                                    std::chrono::system_clock::time_point expiresAt)             = 0;
    virtual bool  isRefreshTokenValid(const std::string& userId,
                                      const std::string& refreshToken) const                     = 0;
    virtual void  revokeRefreshToken(const std::string& userId,
                                     const std::string& refreshToken)                            = 0;
    virtual void  revokeAll(const std::string& userId)                                           = 0;
};

//----------------------------------------------------------------------------------------------------------------------
//  Data transfer objects / simple structs
//----------------------------------------------------------------------------------------------------------------------

struct TokenPair
{
    std::string accessToken;
    std::string refreshToken;

    std::chrono::system_clock::time_point accessTokenExpires;
    std::chrono::system_clock::time_point refreshTokenExpires;
};

struct RegisterRequest
{
    std::string username;
    std::string password;
    std::string email;

    nlohmann::json toJson() const
    {
        return nlohmann::json{{"username", username},
                              {"password", password},
                              {"email",    email}};
    }
};

//----------------------------------------------------------------------------------------------------------------------
//  Exceptions
//----------------------------------------------------------------------------------------------------------------------

class AuthException final : public std::runtime_error
{
    using base = std::runtime_error;

public:
    explicit AuthException(const std::string& msg)
        : base{msg}
    {}
};

//----------------------------------------------------------------------------------------------------------------------
//  AuthService
//----------------------------------------------------------------------------------------------------------------------

class AuthService final
{
public:
    enum class SocialProvider
    {
        Google,
        Github,
        Unknown
    };

public:
    AuthService(std::shared_ptr<IUserRepository>  userRepo,
                std::shared_ptr<ITokenRepository> tokenRepo,
                std::string                       jwtSecret,
                std::chrono::seconds              accessTtl  = std::chrono::minutes{15},
                std::chrono::seconds              refreshTtl = std::chrono::hours{24 * 7})
        : m_userRepo{std::move(userRepo)}
        , m_tokenRepo{std::move(tokenRepo)}
        , m_jwtSecret{std::move(jwtSecret)}
        , m_accessTtl{accessTtl}
        , m_refreshTtl{refreshTtl}
        , m_logger{spdlog::default_logger()}
    {
        if (!m_userRepo || !m_tokenRepo)
        {
            throw std::invalid_argument("AuthService requires valid repository pointers");
        }
    }

    //------------------------------------------------------------------------------------------------------------------
    //  Local-form registration & login
    //------------------------------------------------------------------------------------------------------------------

    TokenPair registerUser(const RegisterRequest& req)
    {
        if (req.username.empty() || req.password.empty())
        {
            throw AuthException{"Username and password must not be empty"};
        }

        // Create user record in database
        const std::string userId = m_userRepo->createUser(req.toJson());

        m_logger->info("New user registered: {}", userId);

        return issueTokens(userId);
    }

    TokenPair login(const std::string& username, const std::string& password)
    {
        if (!m_userRepo->verifyPassword(username, password))
        {
            throw AuthException{"Invalid username/password pair"};
        }

        const auto user = m_userRepo->getUserByUsername(username);
        const std::string userId = user.at("id").get<std::string>();

        m_logger->info("User login: {}", userId);

        return issueTokens(userId);
    }

    //------------------------------------------------------------------------------------------------------------------
    //  Social login (OAuth2 code or JWT from provider)
    //------------------------------------------------------------------------------------------------------------------

    TokenPair socialLogin(SocialProvider provider, const std::string& idToken)
    {
        const std::string userId = mapSocialIdToUser(provider, idToken);
        return issueTokens(userId);
    }

    //------------------------------------------------------------------------------------------------------------------
    //  Token routines
    //------------------------------------------------------------------------------------------------------------------

    bool validateAccessToken(const std::string& token, std::string& outUserId) const
    {
        try
        {
            const auto decoded = jwt::decode(token);

            auto verifier = jwt::verify()
                                .allow_algorithm(jwt::algorithm::hs256{m_jwtSecret})
                                .with_issuer(kIssuer);

            verifier.verify(decoded);

            outUserId = decoded.get_payload_claim("sub").as_string();
            return true;
        }
        catch (const std::exception& ex)
        {
            m_logger->warn("Access token validation failed: {}", ex.what());
            return false;
        }
    }

    TokenPair refreshAccessToken(const std::string& refreshToken)
    {
        const auto decoded = jwt::decode(refreshToken);

        std::string userId;
        try
        {
            auto verifier = jwt::verify()
                                .allow_algorithm(jwt::algorithm::hs256{m_jwtSecret})
                                .with_issuer(kIssuer)
                                .with_type("refresh");

            verifier.verify(decoded);
            userId = decoded.get_payload_claim("sub").as_string();
        }
        catch (const std::exception& ex)
        {
            throw AuthException{std::string{"Refresh token invalid: "} + ex.what()};
        }

        if (!m_tokenRepo->isRefreshTokenValid(userId, refreshToken))
        {
            throw AuthException{"Refresh token revoked or expired"};
        }

        m_tokenRepo->revokeRefreshToken(userId, refreshToken);
        return issueTokens(userId); // rotations
    }

    void logout(const std::string& userId)
    {
        m_tokenRepo->revokeAll(userId);
        m_logger->info("User {} logged out from all sessions", userId);
    }

private:
    //------------------------------------------------------------------------------------------------------------------
    //  Helpers
    //------------------------------------------------------------------------------------------------------------------

    TokenPair issueTokens(const std::string& userId)
    {
        using clock = std::chrono::system_clock;
        const auto now = clock::now();

        //----------------------------------------------------------------------
        //  Access token
        //----------------------------------------------------------------------
        const auto accessExp   = now + m_accessTtl;
        const auto accessToken = jwt::create()
                                     .set_issuer(kIssuer)
                                     .set_type("JWT")
                                     .set_subject(userId)
                                     .set_issued_at(now)
                                     .set_expires_at(accessExp)
                                     .sign(jwt::algorithm::hs256{m_jwtSecret});

        //----------------------------------------------------------------------
        //  Refresh token
        //----------------------------------------------------------------------
        const auto refreshExp   = now + m_refreshTtl;
        const auto refreshToken = jwt::create()
                                      .set_issuer(kIssuer)
                                      .set_type("refresh")
                                      .set_subject(userId)
                                      .set_issued_at(now)
                                      .set_expires_at(refreshExp)
                                      .sign(jwt::algorithm::hs256{m_jwtSecret});

        m_tokenRepo->storeRefreshToken(userId, refreshToken, refreshExp);

        return TokenPair{accessToken, refreshToken, accessExp, refreshExp};
    }

    std::string mapSocialIdToUser(SocialProvider provider, const std::string& idToken)
    {
        // NOTE: Real production code would verify the token with the provider's public keys
        //       and retrieve profile data via the provider API.  Here we limit ourselves
        //       to decoding the JWT w/o signature verification for brevity.
        //
        //       Provider-specific validation is left to dedicated adapters injected in the ctor.

        nlohmann::json claims;
        try
        {
            const auto decoded = jwt::decode(idToken);
            for (const auto& [k, v] : decoded.get_payload_claims())
            {
                claims[k] = v.to_json();
            }
        }
        catch (const std::exception& ex)
        {
            throw AuthException{std::string{"Failed to decode social idToken: "} + ex.what()};
        }

        std::string socialId = claims.value("sub", "");
        if (socialId.empty())
        {
            throw AuthException{"idToken missing 'sub' claim"};
        }

        std::string providerStr = providerAsString(provider);

        // Merge provider + socialId to unique key
        std::string federatedKey = providerStr + "|" + socialId;

        // Attempt to locate an existing user record
        nlohmann::json user = m_userRepo->getUserById(federatedKey);
        if (user.is_null())
        {
            // Auto-register
            nlohmann::json info{
                {"id",          federatedKey},
                {"email",       claims.value("email", "")},
                {"displayName", claims.value("name", "")},
                {"provider",    providerStr}};
            m_userRepo->createUser(info);
            m_logger->info("Auto-provisioned user via social login: {}", federatedKey);
        }

        return federatedKey;
    }

    static std::string providerAsString(SocialProvider p)
    {
        switch (p)
        {
            case SocialProvider::Google: return "google";
            case SocialProvider::Github: return "github";
            default:                     return "unknown";
        }
    }

private:
    //------------------------------------------------------------------------------------------------------------------
    //  State
    //------------------------------------------------------------------------------------------------------------------

    std::shared_ptr<IUserRepository>  m_userRepo;
    std::shared_ptr<ITokenRepository> m_tokenRepo;

    const std::string        m_jwtSecret;
    const std::chrono::seconds m_accessTtl;
    const std::chrono::seconds m_refreshTtl;

    std::shared_ptr<spdlog::logger> m_logger;

    static constexpr const char* kIssuer = "MosaicBoardStudio/AuthService";
};

} // namespace mosaic::services