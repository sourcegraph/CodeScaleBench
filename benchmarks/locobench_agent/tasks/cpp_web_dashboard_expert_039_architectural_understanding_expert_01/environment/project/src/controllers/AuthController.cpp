```cpp
/**
 *  MosaicBoard Studio – AuthController.cpp
 *
 *  Description:
 *  -------------
 *  Handles all authentication-related HTTP endpoints:
 *      • POST /api/v1/auth/login
 *      • POST /api/v1/auth/logout
 *      • POST /api/v1/auth/refresh
 *      • POST /api/v1/auth/social/<provider>
 *
 *  The controller orchestrates between HTTP requests, domain services, and
 *  infrastructure components such as the rate-limiter and metrics collector.
 *
 *  NOTE:
 *  -----
 *  • This file purposefully relies on the MosaicBoard internal web framework
 *    abstractions (Router, Request, Response, etc.) which are implemented
 *    elsewhere in the codebase.
 *  • JWT implementation is delegated to TokenService.
 *  • The UserService encapsulates persistence/ORM details.
 */

#include <chrono>
#include <exception>
#include <memory>
#include <regex>
#include <string>
#include <utility>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include "controllers/AuthController.h"
#include "http/Router.h"
#include "middleware/RateLimiter.h"
#include "services/TokenService.h"
#include "services/UserService.h"
#include "utils/Error.h"

using json = nlohmann::json;

namespace mosaic::controllers
{

// ──────────────────────────────────────────────────────────────────────────────
//  Anonymous helpers
// ──────────────────────────────────────────────────────────────────────────────
namespace
{
constexpr std::chrono::minutes kAccessTokenTtl      = std::chrono::minutes{15};
constexpr std::chrono::hours   kRefreshTokenTtl     = std::chrono::hours{24};
constexpr char kAuthCookieName[]                    = "mbs_access_token";
constexpr char kRefreshCookieName[]                 = "mbs_refresh_token";

bool isEmail(const std::string& value)
{
    static const std::regex kEmailRegex(
        R"(^[\w.!#$%&’*+/=?`{|}~^-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$)",
        std::regex::icase);
    return std::regex_match(value, kEmailRegex);
}

void setSecureCookie(http::Response& res,
                     std::string_view name,
                     std::string_view value,
                     std::chrono::seconds maxAge,
                     bool httpOnly = true)
{
    res.setCookie(std::string{name}, std::string{value}, maxAge.count(), httpOnly,
                  /*secure =*/true, /*sameSite=*/"Strict", /*path =*/"/");
}

void removeCookie(http::Response& res, std::string_view name)
{
    // Setting an expired cookie instructs the browser to delete it.
    res.setCookie(std::string{name}, "",
                  /*maxAge=*/0, /*httpOnly=*/true, /*secure=*/true,
                  /*sameSite=*/"Strict", /*path=*/"/");
}

} // namespace

// ──────────────────────────────────────────────────────────────────────────────
//  ctor / route registration
// ──────────────────────────────────────────────────────────────────────────────

AuthController::AuthController(std::shared_ptr<services::UserService>  userSvc,
                               std::shared_ptr<services::TokenService> tokenSvc,
                               std::shared_ptr<middleware::RateLimiter> rl)
    : m_userService{std::move(userSvc)}
    , m_tokenService{std::move(tokenSvc)}
    , m_rateLimiter{std::move(rl)}
{
    if (!m_userService || !m_tokenService || !m_rateLimiter)
    {
        throw std::invalid_argument(
            "AuthController: service dependencies must not be null");
    }
}

void AuthController::registerRoutes(http::Router& router)
{
    router.post("/api/v1/auth/login",
                m_rateLimiter->wrap(
                    [this](const http::Request& req, http::Response& res)
                    { this->handleLogin(req, res); },
                    "auth_login"));

    router.post("/api/v1/auth/logout",
                [this](const http::Request& req, http::Response& res)
                { this->handleLogout(req, res); });

    router.post("/api/v1/auth/refresh",
                [this](const http::Request& req, http::Response& res)
                { this->handleRefresh(req, res); });

    router.post(
        R"(/api/v1/auth/social/:provider)",
        m_rateLimiter->wrap(
            [this](const http::Request& req, http::Response& res)
            { this->handleSocialLogin(req, res); },
            "auth_social"));
}

// ──────────────────────────────────────────────────────────────────────────────
//  Endpoints
// ──────────────────────────────────────────────────────────────────────────────

void AuthController::handleLogin(const http::Request& req, http::Response& res)
{
    try
    {
        const json body = json::parse(req.body());

        const std::string credential =
            body.at("credential").get<std::string>(); // email or username
        const std::string password = body.at("password").get<std::string>();

        if (credential.empty() || password.empty())
        {
            throw utils::BadRequestError("Missing credential or password");
        }

        const auto user =
            isEmail(credential)
                ? m_userService->findByEmailAndPassword(credential, password)
                : m_userService->findByUsernameAndPassword(credential, password);

        if (!user)
        {
            throw utils::UnauthorizedError("Invalid credentials");
        }

        // Generate short-lived access token and long-lived refresh token
        const auto now          = std::chrono::system_clock::now();
        const auto accessToken  = m_tokenService->sign(
            *user, now + kAccessTokenTtl, services::TokenService::Type::Access);
        const auto refreshToken = m_tokenService->sign(
            *user, now + kRefreshTokenTtl, services::TokenService::Type::Refresh);

        setSecureCookie(res, kAuthCookieName, accessToken,
                        std::chrono::duration_cast<std::chrono::seconds>(
                            kAccessTokenTtl));
        setSecureCookie(res, kRefreshCookieName, refreshToken,
                        std::chrono::duration_cast<std::chrono::seconds>(
                            kRefreshTokenTtl));

        json payload{
            {"user",
             {
                 {"id", user->id},
                 {"username", user->username},
                 {"email", user->email}},
            },
            {"accessToken", accessToken},
            {"expiresIn", std::chrono::duration_cast<std::chrono::seconds>(
                              kAccessTokenTtl)
                              .count()}};

        res.status(200).json(payload);
    }
    catch (const utils::HttpError& e)
    {
        spdlog::warn("Login failed: {}", e.what());
        res.status(e.code()).json({{"error", e.what()}});
    }
    catch (const std::exception& e)
    {
        spdlog::error("Login internal error: {}", e.what());
        res.status(500).json({{"error", "Internal server error"}});
    }
}

void AuthController::handleLogout(const http::Request& /*req*/,
                                  http::Response&      res) const
{
    // Stateless JWTs don't need server-side invalidation unless we implement a
    // revocation list. We simply instruct the client to delete cookies.
    removeCookie(res, kAuthCookieName);
    removeCookie(res, kRefreshCookieName);
    res.status(204); // No Content
}

void AuthController::handleRefresh(const http::Request& req,
                                   http::Response&      res)
{
    try
    {
        const auto refreshToken = req.cookie(kRefreshCookieName);
        if (!refreshToken)
        {
            throw utils::UnauthorizedError("Missing refresh token");
        }

        const auto verified =
            m_tokenService->verify(*refreshToken,
                                   services::TokenService::Type::Refresh);

        if (!verified)
        {
            throw utils::UnauthorizedError("Invalid refresh token");
        }

        // Issue new access token
        const auto user = m_userService->findById(verified->userId);
        if (!user)
        {
            throw utils::UnauthorizedError("User no longer exists");
        }

        const auto now         = std::chrono::system_clock::now();
        const auto newAccess   = m_tokenService->sign(
            *user, now + kAccessTokenTtl, services::TokenService::Type::Access);

        setSecureCookie(res, kAuthCookieName, newAccess,
                        std::chrono::duration_cast<std::chrono::seconds>(
                            kAccessTokenTtl));

        res.status(200).json(
            {{"accessToken", newAccess},
             {"expiresIn",
              std::chrono::duration_cast<std::chrono::seconds>(kAccessTokenTtl)
                  .count()}});
    }
    catch (const utils::HttpError& e)
    {
        spdlog::warn("Refresh failed: {}", e.what());
        res.status(e.code()).json({{"error", e.what()}});
    }
    catch (const std::exception& e)
    {
        spdlog::error("Refresh internal error: {}", e.what());
        res.status(500).json({{"error", "Internal server error"}});
    }
}

void AuthController::handleSocialLogin(const http::Request& req,
                                       http::Response&      res)
{
    const auto& provider = req.param("provider");

    try
    {
        // We expect the front-end to provide the OAuth2 authorization code
        // (or identity token for Google One-Tap, etc.) as JSON payload.
        json body = json::parse(req.body());
        const std::string authorizationCode =
            body.at("code").get<std::string>();

        if (authorizationCode.empty())
            throw utils::BadRequestError("Missing authorization code");

        // Delegate provider-specific exchange to UserService
        auto user = m_userService->authenticateViaOAuth(provider,
                                                        authorizationCode);
        if (!user)
            throw utils::UnauthorizedError("OAuth authentication failed");

        const auto now          = std::chrono::system_clock::now();
        const auto accessToken  = m_tokenService->sign(
            *user, now + kAccessTokenTtl, services::TokenService::Type::Access);
        const auto refreshToken = m_tokenService->sign(
            *user, now + kRefreshTokenTtl,
            services::TokenService::Type::Refresh);

        setSecureCookie(res, kAuthCookieName, accessToken,
                        std::chrono::duration_cast<std::chrono::seconds>(
                            kAccessTokenTtl));
        setSecureCookie(res, kRefreshCookieName, refreshToken,
                        std::chrono::duration_cast<std::chrono::seconds>(
                            kRefreshTokenTtl));

        res.status(200).json(
            {{"user",
              {{"id", user->id},
               {"username", user->username},
               {"email", user->email}}},
             {"accessToken", accessToken},
             {"expiresIn",
              std::chrono::duration_cast<std::chrono::seconds>(kAccessTokenTtl)
                  .count()}});
    }
    catch (const utils::HttpError& e)
    {
        spdlog::warn("Social login failed ({}): {}", provider, e.what());
        res.status(e.code()).json({{"error", e.what()}});
    }
    catch (const std::exception& e)
    {
        spdlog::error("Social login internal error ({}): {}", provider,
                      e.what());
        res.status(500).json({{"error", "Internal server error"}});
    }
}

} // namespace mosaic::controllers
```