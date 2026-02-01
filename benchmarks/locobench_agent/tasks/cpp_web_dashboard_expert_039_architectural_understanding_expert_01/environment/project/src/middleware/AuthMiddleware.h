```cpp
#pragma once
/**
 * MosaicBoard Studio – Authentication Middleware
 *
 * The AuthMiddleware is invoked for every HTTP/WebSocket request that targets a
 * protected endpoint.  It is responsible for:
 *   • Extracting the bearer token from the `Authorization` header, a cookie, or
 *     a fallback `?access_token=` query parameter.
 *   • Verifying the token with jwt-cpp and performing basic claim validation
 *     (exp, nbf, iat, iss, aud).
 *   • Loading the user profile from the UserService.
 *   • Caching session information in-memory to minimize repeated signature
 *     checks on high-traffic websockets.
 *   • Injecting the authenticated User object into the request context so that
 *     downstream controllers or tiles can perform fine-grained authorization.
 *
 * The middleware is written header-only for ease of integration with the
 * existing plug-in system, yet it avoids macros and remains testable by
 * isolating all side-effects behind the UserService and injectable Clock.
 */

#include <jwt-cpp/jwt.h>                // 3rd-party – https://github.com/Thalhammer/jwt-cpp
#include <nlohmann/json.hpp>            // 3rd-party – https://github.com/nlohmann/json
#include <spdlog/spdlog.h>              // 3rd-party – https://github.com/gabime/spdlog

#include <chrono>
#include <functional>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace mbs   // MosaicBoard Studio namespace
{

// -----------------------------------------------------------------------------
// Forward declarations of minimal framework abstractions.  In production these
// are provided by the web stack (e.g. Pistache, Crow, Boost.Beast, etc.).
// -----------------------------------------------------------------------------
namespace http
{
enum class Status : uint16_t
{
    ok                  = 200,
    unauthorized        = 401,
    forbidden           = 403,
    internal_server_err = 500
};

class Request
{
public:
    // Returns a header in canonical form, or std::nullopt if absent.
    virtual std::optional<std::string> header (const std::string& key) const = 0;

    // Returns the query string value or std::nullopt if absent.
    virtual std::optional<std::string> query  (const std::string& key) const = 0;

    // Persists a context value for downstream services.
    virtual void setContext                 (const std::string& key,
                                             const nlohmann::json& value)     = 0;

    virtual ~Request() = default;
};

class Response
{
public:
    virtual void setStatus (Status code)                 = 0;
    virtual void setBody   (const nlohmann::json& body)  = 0;
    virtual bool  sent() const                           = 0;
    virtual ~Response() = default;
};

} // namespace http

// -----------------------------------------------------------------------------
// Domain entities & services (stripped-down)
// -----------------------------------------------------------------------------
struct User final
{
    std::string  id;
    std::string  displayName;
    std::string  email;
    std::vector<std::string> roles;
    nlohmann::json customClaims;    // extra claims for plug-ins
};

class IUserService
{
public:
    // Retrieves a user from DB using the subject claim (‘sub’).
    virtual std::optional<User> fetchBySubject(const std::string& subject) = 0;
    virtual ~IUserService() = default;
};

// -----------------------------------------------------------------------------
// Time provider abstraction so we can mock the clock in tests.
// -----------------------------------------------------------------------------
class IClock
{
public:
    using time_point = std::chrono::system_clock::time_point;
    virtual time_point now() const = 0;
    virtual ~IClock() = default;
};

class SystemClock final : public IClock
{
public:
    time_point now() const override { return std::chrono::system_clock::now(); }
};

// -----------------------------------------------------------------------------
// AuthMiddleware
// -----------------------------------------------------------------------------
class AuthMiddleware final
{
public:
    using Next = std::function<void (http::Request&, http::Response&)>;

    explicit AuthMiddleware(std::shared_ptr<IUserService> userSvc,
                            std::string                   jwtSecret,
                            std::shared_ptr<IClock>       clock     = std::make_shared<SystemClock>(),
                            std::chrono::seconds          leeway    = std::chrono::seconds{30})
        : m_userSvc  { std::move(userSvc) }
        , m_secret   { std::move(jwtSecret) }
        , m_clock    { std::move(clock) }
        , m_leeway   { leeway }
    {
        if (!m_userSvc)
            throw std::invalid_argument("AuthMiddleware: IUserService must not be null");
        if (m_secret.empty())
            throw std::invalid_argument("AuthMiddleware: JWT secret must not be empty");
    }

    /**
     * Middleware entry-point.
     *
     * Throws on irrecoverable errors, otherwise writes an error response and
     * short-circuits the chain.
     */
    void operator()(http::Request&  req,
                    http::Response& res,
                    const Next&     next)
    {
        try
        {
            auto token = extractBearerToken(req);
            if (!token)
            {
                deny(res, "Missing bearer token", http::Status::unauthorized);
                return;
            }

            auto userOpt = authenticate(*token);
            if (!userOpt)
            {
                deny(res, "Authentication failed", http::Status::unauthorized);
                return;
            }

            // Inject into request context for downstream access.
            req.setContext("user", userToJson(*userOpt));

            // Continue down the chain.
            next(req, res);
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[AuthMiddleware] Unexpected error: {}", ex.what());
            if (!res.sent())
            {
                deny(res, "Internal authentication error",
                     http::Status::internal_server_err);
            }
        }
    }

private:
    // --------------- Internal helpers ---------------------------------------
    std::optional<std::string> extractBearerToken(const http::Request& req) const
    {
        // 1) Authorization: Bearer <token>
        if (auto hdr = req.header("Authorization"))
        {
            const std::string& h = *hdr;
            const std::string  prefix = "Bearer ";
            if (h.size() > prefix.size() &&
                std::equal(prefix.begin(), prefix.end(), h.begin(),
                           [](char a, char b){ return std::tolower(a) == std::tolower(b); }))
            {
                return h.substr(prefix.size());
            }
        }

        // 2) X-Access-Token header
        if (auto hdr = req.header("X-Access-Token"))
            return hdr;

        // 3) ?access_token= query
        if (auto q = req.query("access_token"))
            return q;

        return std::nullopt;
    }

    std::optional<User> authenticate(const std::string& token)
    {
        // Fast-path: in-memory cache.
        if (auto cached = findInCache(token); cached)
            return cached->user;

        // Decode & verify signature.
        auto decoded = jwt::decode(token);

        // Build verifier
        auto verifier = jwt::verify()
                            .allow_algorithm(jwt::algorithm::hs256{ m_secret })
                            .leeway(static_cast<std::size_t>(m_leeway.count()))
                            .with_issuer("MosaicBoardStudio")
                            .with_audience("MosaicBoardStudio::Dashboard");

        verifier.verify(decoded);

        // Basic time-based claims are handled by jwt-cpp itself, but we still
        // need to enforce not-before (nbf) manually if not compiled in.
        const auto nowSec = std::chrono::duration_cast<std::chrono::seconds>(
                                m_clock->now().time_since_epoch()).count();
        if (decoded.has_payload_claim("nbf"))
        {
            auto nbf = decoded.get_payload_claim("nbf").as_date();
            if (nowSec + m_leeway.count() < nbf)   // not yet valid
                throw std::runtime_error("Token not yet valid (nbf)");
        }

        auto subject = decoded.get_payload_claim("sub").as_string();

        // Hydrate user from DB.
        auto userOpt = m_userSvc->fetchBySubject(subject);
        if (!userOpt)
            return std::nullopt;

        // Attach custom claims.
        for (auto& [k, v] : decoded.get_payload_json().items())
        {
            if (standardClaims().count(k)) continue; // ignore std claims
            (*userOpt).customClaims[k] = v;
        }

        // Cache for subsequent requests (expiry = exp claim).
        if (decoded.has_payload_claim("exp"))
        {
            auto exp = decoded.get_payload_claim("exp").as_date();
            cache(token, *userOpt,
                  std::chrono::system_clock::time_point{ std::chrono::seconds{exp} });
        }

        return userOpt;
    }

    struct CacheEntry
    {
        User                                     user;
        std::chrono::system_clock::time_point    expiry;
    };

    std::optional<CacheEntry> findInCache(const std::string& token)
    {
        std::shared_lock lock(m_cacheMx);
        auto it = m_cache.find(token);
        if (it == m_cache.end())
            return std::nullopt;

        if (m_clock->now() >= it->second.expiry)
        {
            // Expired – do lazy eviction.
            lock.unlock();
            std::unique_lock uniq(m_cacheMx);
            m_cache.erase(token);
            return std::nullopt;
        }
        return it->second;
    }

    void cache(const std::string&                      token,
               const User&                             user,
               const std::chrono::system_clock::time_point& expiry)
    {
        std::unique_lock lock(m_cacheMx);
        m_cache[token] = CacheEntry{ user, expiry };
    }

    static void deny(http::Response& res,
                     const std::string& message,
                     http::Status      status)
    {
        if (res.sent()) return;

        nlohmann::json body {
            { "error", nlohmann::json {
                { "message", message },
                { "code",    static_cast<uint16_t>(status) }
            }}
        };

        res.setStatus(status);
        res.setBody(body);
    }

    static const std::unordered_set<std::string>& standardClaims()
    {
        static const std::unordered_set<std::string> claims {
            "iss","sub","aud","exp","nbf","iat","jti"
        };
        return claims;
    }

    nlohmann::json userToJson(const User& u) const
    {
        nlohmann::json j {
            { "id",           u.id },
            { "display_name", u.displayName },
            { "email",        u.email },
            { "roles",        u.roles },
            { "claims",       u.customClaims }
        };
        return j;
    }

    // --------------- Members -------------------------------------------------
    std::shared_ptr<IUserService>                   m_userSvc;
    std::string                                     m_secret;
    std::shared_ptr<IClock>                         m_clock;
    std::chrono::seconds                            m_leeway;

    mutable std::shared_mutex                       m_cacheMx;
    std::unordered_map<std::string, CacheEntry>     m_cache;
};

} // namespace mbs
```