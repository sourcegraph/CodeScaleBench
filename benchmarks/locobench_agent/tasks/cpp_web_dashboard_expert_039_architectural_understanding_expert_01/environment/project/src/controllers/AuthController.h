#pragma once
/**
 *  MosaicBoard Studio — AuthController
 *  File path: MosaicBoardStudio/src/controllers/AuthController.h
 *
 *  This header contains both interface and lightweight in-header
 *  implementation for the AuthController component.  The controller
 *  wires the REST-router to the Authentication service layer while
 *  remaining agnostic of the underlying web-framework.  It focuses on:
 *
 *   • Local credentials authentication (e-mail / password)
 *   • JWT refresh-token rotation
 *   • Social OAuth callback handling
 *   • Logout / token revocation
 *
 *  Dependencies referenced here (IRouter, IRequest …) are forward-declared
 *  so that the header may be included without pulling heavyweight headers
 *  into every translation unit.  A single “auth” controller instance is
 *  expected to be created at application bootstrap and have its routes
 *  registered on the global router.
 *
 *  NOTE: All implementation code is intentionally kept trivial in order
 *  to stay header-only; real business logic belongs in a concrete
 *  IAuthService implementation residing in the service layer.
 */

#include <memory>
#include <string>
#include <chrono>
#include <stdexcept>
#include <unordered_map>
#include <functional>   // for std::bind / std::placeholders
#include <nlohmann/json.hpp>    // MIT-licensed JSON library
// ──────────────────────────────────────────────────────────────────────────────
namespace MosaicBoard
{
    // Forward declarations to decouple header from framework specifics.
    namespace Http {
        class IRequest;
        class IResponse;
        using Headers = std::unordered_map<std::string, std::string>;
    }

    namespace Rest {
        class IRouter; // Abstraction around the underlying HTTP router.
    }

    namespace Util {
        class ILogger;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // DTOs / Enumerations used by the controller
    // ──────────────────────────────────────────────────────────────────────────
    namespace DTO
    {
        /**
         * Container for access- & refresh-token payloads.
         */
        struct AuthTokens
        {
            std::string accessToken;
            std::string refreshToken;
            std::chrono::system_clock::time_point expiresAt;
        };
    } // namespace DTO

    enum class SocialProvider : uint8_t
    {
        Google,
        Github,
        Twitter
    };

    // ──────────────────────────────────────────────────────────────────────────
    // Domain-layer interfaces — part of the Service-Layer boundary
    // ──────────────────────────────────────────────────────────────────────────
    class IAuthService
    {
    public:
        virtual ~IAuthService() = default;

        virtual DTO::AuthTokens authenticate(const std::string& email,
                                             const std::string& password,
                                             const std::string& userAgent,
                                             const std::string& ip) = 0;

        virtual DTO::AuthTokens refresh(const std::string& refreshToken,
                                        const std::string& userAgent,
                                        const std::string& ip) = 0;

        virtual void logout(const std::string& accessToken) = 0;

        virtual DTO::AuthTokens socialAuthenticate(
            SocialProvider provider,
            const std::string& authCode,
            const std::string& userAgent,
            const std::string& ip) = 0;
    };

    // ──────────────────────────────────────────────────────────────────────────
    // Custom exceptions
    // ──────────────────────────────────────────────────────────────────────────
    class AuthException final : public std::runtime_error
    {
    public:
        explicit AuthException(const std::string& msg,
                               int httpStatus = 401)        // default: unauthorized
            : std::runtime_error{ msg }
            , m_httpStatus{ httpStatus }
        {}

        [[nodiscard]] int httpStatus() const noexcept { return m_httpStatus; }

    private:
        int m_httpStatus;
    };

    // ──────────────────────────────────────────────────────────────────────────
    // AuthController definition
    // ──────────────────────────────────────────────────────────────────────────
    namespace Controllers
    {
        class AuthController : public std::enable_shared_from_this<AuthController>
        {
        public:
            using json = nlohmann::json;

            AuthController(std::shared_ptr<IAuthService> authSvc,
                           std::shared_ptr<Util::ILogger> logger) noexcept;

            /**
             * Binds endpoints to the given Router instance.
             *   POST   /api/v1/auth/login
             *   POST   /api/v1/auth/refresh
             *   POST   /api/v1/auth/logout
             *   GET    /api/v1/auth/social/{provider}/callback
             */
            void registerRoutes(Rest::IRouter& router);

        private:
            // HTTP request handlers
            void login(Http::IRequest& req, Http::IResponse& res);
            void refreshToken(Http::IRequest& req, Http::IResponse& res);
            void logout(Http::IRequest& req, Http::IResponse& res);

            // e.g. /auth/social/google/callback?code=XYZ
            void socialCallback(Http::IRequest& req, Http::IResponse& res,
                                SocialProvider provider);

            // Helper utilities
            [[nodiscard]] static SocialProvider providerFromString(const std::string& str);
            void writeTokens(Http::IResponse& res, const DTO::AuthTokens& tokens) const;

            // Dependencies
            std::shared_ptr<IAuthService> m_auth;
            std::shared_ptr<Util::ILogger> m_logger;
        };

        // ──────────────────────────────────────────────────────────────────────
        // Inline implementation
        // ──────────────────────────────────────────────────────────────────────
        inline AuthController::AuthController(std::shared_ptr<IAuthService> authSvc,
                                              std::shared_ptr<Util::ILogger> logger) noexcept
            : m_auth{ std::move(authSvc) }
            , m_logger{ std::move(logger) }
        {
        }

        inline void AuthController::registerRoutes(Rest::IRouter& router)
        {
            using namespace std::placeholders;

            // Router wiring is intentionally abstract — the controller only
            // specifies HTTP verb, path & bound member function.

            router.post("/api/v1/auth/login",
                        std::bind(&AuthController::login, shared_from_this(), _1, _2));

            router.post("/api/v1/auth/refresh",
                        std::bind(&AuthController::refreshToken, shared_from_this(), _1, _2));

            router.post("/api/v1/auth/logout",
                        std::bind(&AuthController::logout, shared_from_this(), _1, _2));

            router.get("/api/v1/auth/social/google/callback",
                       std::bind(&AuthController::socialCallback, shared_from_this(), _1, _2,
                                 SocialProvider::Google));

            router.get("/api/v1/auth/social/github/callback",
                       std::bind(&AuthController::socialCallback, shared_from_this(), _1, _2,
                                 SocialProvider::Github));

            router.get("/api/v1/auth/social/twitter/callback",
                       std::bind(&AuthController::socialCallback, shared_from_this(), _1, _2,
                                 SocialProvider::Twitter));
        }

        // ──────────────────────────────────────────────────────────────────────
        // Endpoint implementations
        // ──────────────────────────────────────────────────────────────────────
        inline void AuthController::login(Http::IRequest& req, Http::IResponse& res)
        {
            try
            {
                const auto bodyJson = json::parse(req.body(), nullptr, true, /*allow_exceptions=*/true);

                const std::string email    = bodyJson.at("email").get<std::string>();
                const std::string password = bodyJson.at("password").get<std::string>();

                const auto tokens = m_auth->authenticate(email,
                                                         password,
                                                         req.header("User-Agent"),
                                                         req.remoteAddress());

                writeTokens(res, tokens);
            }
            catch (const json::exception& ex)
            {
                // Malformed JSON
                res.status(400).json({ { "error", "Invalid JSON payload" },
                                       { "details", ex.what() } });
            }
            catch (const AuthException& authErr)
            {
                res.status(authErr.httpStatus())
                   .json({ { "error", "Authentication failed" },
                           { "message", authErr.what() } });
            }
            catch (const std::exception& ex)
            {
                // Unexpected error path
                m_logger->error("[AuthController::login] {}", ex.what());
                res.status(500).json({ { "error", "Internal server error" } });
            }
        }

        inline void AuthController::refreshToken(Http::IRequest& req, Http::IResponse& res)
        {
            try
            {
                const auto bodyJson  = json::parse(req.body());
                const std::string rt = bodyJson.at("refresh_token").get<std::string>();

                const auto tokens = m_auth->refresh(rt,
                                                    req.header("User-Agent"),
                                                    req.remoteAddress());

                writeTokens(res, tokens);
            }
            catch (const AuthException& authErr)
            {
                res.status(authErr.httpStatus())
                   .json({ { "error", "Token refresh failed" },
                           { "message", authErr.what() } });
            }
            catch (const std::exception& ex)
            {
                m_logger->error("[AuthController::refreshToken] {}", ex.what());
                res.status(500).json({ { "error", "Internal server error" } });
            }
        }

        inline void AuthController::logout(Http::IRequest& req, Http::IResponse& res)
        {
            try
            {
                const std::string bearer = req.header("Authorization");
                if (bearer.rfind("Bearer ", 0) != 0)
                {
                    throw AuthException("Missing or malformed Authorization header", 400);
                }
                const std::string token = bearer.substr(7); // strip "Bearer "

                m_auth->logout(token);
                res.status(204); // No Content
            }
            catch (const AuthException& authErr)
            {
                res.status(authErr.httpStatus())
                   .json({ { "error", "Logout failed" },
                           { "message", authErr.what() } });
            }
            catch (const std::exception& ex)
            {
                m_logger->error("[AuthController::logout] {}", ex.what());
                res.status(500).json({ { "error", "Internal server error" } });
            }
        }

        inline void AuthController::socialCallback(Http::IRequest& req, Http::IResponse& res,
                                                   SocialProvider provider)
        {
            try
            {
                // OAuth 2.0 authorization code
                const std::string code = req.query("code");
                if (code.empty())
                {
                    throw AuthException("Missing OAuth authorization code", 400);
                }

                const auto tokens = m_auth->socialAuthenticate(provider,
                                                               code,
                                                               req.header("User-Agent"),
                                                               req.remoteAddress());

                writeTokens(res, tokens);
            }
            catch (const AuthException& authErr)
            {
                res.status(authErr.httpStatus())
                   .json({ { "error", "Social authentication failed" },
                           { "message", authErr.what() } });
            }
            catch (const std::exception& ex)
            {
                m_logger->error("[AuthController::socialCallback] {}", ex.what());
                res.status(500).json({ { "error", "Internal server error" } });
            }
        }

        // ──────────────────────────────────────────────────────────────────────
        // Utilities
        // ──────────────────────────────────────────────────────────────────────
        inline void AuthController::writeTokens(Http::IResponse& res,
                                                const DTO::AuthTokens& tokens) const
        {
            json data{
                { "access_token",  tokens.accessToken },
                { "refresh_token", tokens.refreshToken },
                { "expires_at",
                  std::chrono::duration_cast<std::chrono::seconds>(
                      tokens.expiresAt.time_since_epoch()).count() }
            };

            res.status(200).json(std::move(data));
        }

        inline SocialProvider AuthController::providerFromString(const std::string& str)
        {
            static const std::unordered_map<std::string, SocialProvider> lut{
                { "google",  SocialProvider::Google },
                { "github",  SocialProvider::Github },
                { "twitter", SocialProvider::Twitter }
            };
            if (auto it = lut.find(str); it != lut.end())
                return it->second;

            throw AuthException("Unsupported social provider: " + str, 400);
        }

    } // namespace Controllers
} // namespace MosaicBoard