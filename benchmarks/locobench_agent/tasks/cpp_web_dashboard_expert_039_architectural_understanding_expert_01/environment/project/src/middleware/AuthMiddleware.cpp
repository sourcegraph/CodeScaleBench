```cpp
// ─────────────────────────────────────────────────────────────────────────────
// File:    MosaicBoardStudio/src/middleware/AuthMiddleware.cpp
// Project: MosaicBoard Studio  (web_dashboard)
// Created: 2024-06-13
// Author:  MosaicBoard Core Team
//
// Description:
//  Runtime–discoverable authentication and authorization middleware used by
//  the REST API front-controller.  Performs JWT validation, role/permission
//  checks, silent token refresh, and injects a request-scoped security context
//  that downstream handlers (controllers, repositories, etc.) can query.
//
//  This component deliberately avoids any framework-specific APIs so that it
//  can be dropped into either the synchronous (Boost.Beast) or the async
//  (uWebSockets) front-ends used by MosaicBoard Studio.
//
//  Dependencies that are expected to exist elsewhere in the code base
//  ──────────────────────────────────────────────────────────────────────────
//   • core/http/HttpRequest.hpp      – immutable request abstraction
//   • core/http/HttpResponse.hpp     – mutable response abstraction
//   • core/http/MiddlewareChain.hpp  – continuation object
//   • security/TokenService.hpp      – JWT encode/decode helpers
//   • security/SecurityContext.hpp   – per-request security claims
//   • infra/Config.hpp               – global environment configuration
//   • infra/Logger.hpp               – spdlog-backed logging facade
//   • repository/UserRepository.hpp  – data-access/repository layer
//   • util/TimeUtils.hpp             – time helpers (chrono <-> unix)
// ─────────────────────────────────────────────────────────────────────────────

#include <chrono>
#include <exception>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "core/http/HttpRequest.hpp"
#include "core/http/HttpResponse.hpp"
#include "core/http/MiddlewareChain.hpp"
#include "infra/Config.hpp"
#include "infra/Logger.hpp"
#include "repository/UserRepository.hpp"
#include "security/SecurityContext.hpp"
#include "security/TokenService.hpp"
#include "util/TimeUtils.hpp"

namespace mosaic::middleware {

using core::http::HttpRequest;
using core::http::HttpResponse;
using core::http::MiddlewareChain;
using infra::Logger;
using repository::UserRepository;
using security::SecurityContext;
using security::TokenService;

namespace {

/* Small RAII helper that makes sure to clear the thread-local security context
 * even if an exception bubbles up before the request completes. */
class ScopedSecurityContextGuard final {
public:
    explicit ScopedSecurityContextGuard(SecurityContext* ctx) noexcept
        : ctx_(ctx) {}
    ~ScopedSecurityContextGuard() noexcept {
        if (ctx_) {
            ctx_->clear();
        }
    }
    ScopedSecurityContextGuard(ScopedSecurityContextGuard&&)            = delete;
    ScopedSecurityContextGuard& operator=(ScopedSecurityContextGuard&&) = delete;
    ScopedSecurityContextGuard(const ScopedSecurityContextGuard&)       = delete;
    ScopedSecurityContextGuard& operator=(const ScopedSecurityContextGuard&) = delete;

private:
    SecurityContext* ctx_;
};

// Common header names
constexpr std::string_view kAuthorizationHdr = "Authorization";
constexpr std::string_view kBearerPrefix     = "Bearer ";

// Some endpoints can be visited without authentication.  Patterns can include
// wildcards (naïve suffix match for now).  Ideally, this comes from Config or a
// dedicated ACL provider.
bool isPublicEndpoint(std::string_view path) {
    static const std::vector<std::string_view> kPublicPatterns = {
        "/api/v1/auth/login",
        "/api/v1/auth/social/*",
        "/api/v1/health",
        "/static/*",
    };

    for (auto pattern : kPublicPatterns) {
        if (pattern.ends_with('*')) {
            auto prefix = pattern.substr(0, pattern.size() - 1);
            if (path.starts_with(prefix)) { return true; }
        } else if (pattern == path) {
            return true;
        }
    }
    return false;
}

// Build a 401 response with RFC 6750 compliant WWW-Authenticate header.
void unauthorized(HttpResponse& res, std::string_view error = "invalid_token") {
    res.status(401)
       .header("WWW-Authenticate", std::string{"Bearer error=\""} + std::string{error} + '"')
       .json(R"({"error":")" + std::string{error} + R"("})");
}

}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  AuthMiddleware::handle()
// ─────────────────────────────────────────────────────────────────────────────
void AuthMiddleware::handle(HttpRequest& req,
                            HttpResponse& res,
                            MiddlewareChain next) try {
    Logger::trace("AuthMiddleware: Handling {}", req.uri());

    // ── 1. Short-circuit public endpoints ───────────────────────────────────
    if (isPublicEndpoint(req.uri())) {
        Logger::debug("AuthMiddleware: Public endpoint '{}'. Skipping auth.", req.uri());
        next(req, res);
        return;
    }

    // ── 2. Extract Bearer token ─────────────────────────────────────────────
    const auto authHdrOpt = req.header(kAuthorizationHdr);
    if (!authHdrOpt) {
        Logger::warn("AuthMiddleware: Missing Authorization header.");
        unauthorized(res, "token_absent");
        return;
    }

    std::string_view authHdr = *authHdrOpt;
    if (!authHdr.starts_with(kBearerPrefix)) {
        Logger::warn("AuthMiddleware: Authorization header is malformed.");
        unauthorized(res, "invalid_request");
        return;
    }
    std::string token{authHdr.substr(kBearerPrefix.size())};

    // ── 3. Validate/parse token ─────────────────────────────────────────────
    TokenService::DecodedToken decoded;
    try {
        decoded = TokenService::validate(token);
    } catch (const TokenService::ExpiredTokenError&) {
        Logger::info("AuthMiddleware: Expired JWT.");
        unauthorized(res, "token_expired");
        return;
    } catch (const TokenService::InvalidTokenError& e) {
        Logger::warn("AuthMiddleware: Invalid JWT – {}", e.what());
        unauthorized(res, "invalid_token");
        return;
    } catch (const std::exception& e) {
        Logger::error("AuthMiddleware: JWT validation threw {}", e.what());
        unauthorized(res, "invalid_token");
        return;
    }

    // ── 4. Hydrate security context (thread-local) ──────────────────────────
    SecurityContext securityCtx;
    ScopedSecurityContextGuard guard{&securityCtx};  // RAII cleanup
    securityCtx.setUserId(decoded.userId);
    securityCtx.setRoles(decoded.roles);
    securityCtx.setClaims(decoded.claims);

    // Optionally query user repository to pull fresh profile / status
    if (auto userOpt = UserRepository::instance().findById(decoded.userId); userOpt) {
        securityCtx.setUser(*userOpt);
    } else {
        Logger::warn("AuthMiddleware: User {} not found in DB.", decoded.userId);
    }

    // ── 5. Near-expiry silent refresh ───────────────────────────────────────
    const auto now       = util::TimeUtils::unixSecondsNow();
    const auto threshold = Config::get<int>("auth.refresh_threshold_seconds", 90);
    if (decoded.expiresAt - now < threshold) {
        try {
            std::string newToken = TokenService::refresh(token);
            res.header("X-Auth-Refresh", newToken);
            Logger::debug("AuthMiddleware: Issued silent token refresh.");
        } catch (const std::exception& e) {
            Logger::warn("AuthMiddleware: Failed to silently refresh token – {}", e.what());
        }
    }

    // ── 6. Role/permission check (if controller annotated) ──────────────────
    //   Controller can tag required roles via request attribute "requiredRoles"
    if (const auto requiredOpt = req.attribute<std::vector<std::string>>("requiredRoles")) {
        const auto& required = *requiredOpt;
        if (!securityCtx.hasAnyRole(required)) {
            Logger::warn("AuthMiddleware: Insufficient role for {}.", req.uri());
            res.status(403).json(R"({"error":"insufficient_role"})");
            return;
        }
    }

    // ── 7. Propagate context to downstream handlers ─────────────────────────
    req.setSecurityContext(&securityCtx);
    next(req, res);
    // (ScopedSecurityContextGuard will clear the context when leaving scope)

} catch (const std::exception& e) {
    Logger::error("AuthMiddleware: Uncaught exception in middleware – {}", e.what());
    res.status(500).json(R"({"error":"internal_error"})");
}

}  // namespace mosaic::middleware
```