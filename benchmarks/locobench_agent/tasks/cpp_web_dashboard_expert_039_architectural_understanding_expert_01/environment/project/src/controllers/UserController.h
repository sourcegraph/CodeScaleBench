#ifndef MOSAICBOARD_STUDIO_CONTROLLERS_USERCONTROLLER_H
#define MOSAICBOARD_STUDIO_CONTROLLERS_USERCONTROLLER_H

/**
 *  MosaicBoard Studio – UserController
 *
 *  This controller is responsible for handling every RESTful HTTP endpoint that
 *  manipulates or queries user-centric resources (registration, authentication,
 *  profile management, account deletion, etc.).  The class is deliberately kept
 *  “controller-thin”;  all heavy-lifting is delegated to service-layer objects
 *  that encapsulate domain logic and external dependencies (DB, OAuth, e-mail,
 *  payment vaults, …).
 *
 *  The file is self-contained:  it declares the public interface as well as a
 *  header-only implementation so that downstream modules can simply include the
 *  header without worrying about linkage.  Whenever the implementation becomes
 *  non-trivial, feel free to move it into a dedicated *.cpp translation unit.
 *
 *  Thread-safety:  The controller is stateless;  it merely forwards calls to
 *  services that are expected to be thread-safe.  The only mutable state is a
 *  logger instance and shared_ptr handles.
 */

#include <memory>
#include <string>
#include <utility>
#include <optional>
#include <chrono>

#include <nlohmann/json.hpp>

//
// Forward-declared infrastructure  ────────────────────────────────────────────
// (The real types live in other translation units)
//
//   HttpRouter     –︎ URL dispatcher that binds HTTP verbs + path patterns to
//                    `std::function<void(const HttpRequest&, HttpResponse&)>`.
//   HttpRequest    –︎ Holds parsed request metadata + body.
//   HttpResponse   –︎ Encapsulates status-code, headers and body composition.
//   HttpStatus     –︎ Strongly-typed enum wrapper around HTTP status codes.
//   Logger         –︎ Cheap wrapper around your favorite logging backend.
//
//   UserService    –︎ CRUD operations on the `users` table (Repository pattern).
//   AuthService    –︎ Password hashing, social login, MFA, account recovery.
//   TokenService   –︎ JWT / session cookie minting + validation.
//
namespace mbs
{
    class HttpRequest;
    class HttpResponse;
    enum class HttpStatus : int;
    class HttpRouter;
    class Logger;

    namespace services
    {
        class UserService;
        class AuthService;
        class TokenService;
    } // namespace services
} // namespace mbs

namespace mbs::controllers
{

/**
 * UserController
 *
 * REST mappings
 *  POST   /api/v1/users/register      → handleRegister
 *  POST   /api/v1/users/login         → handleLogin
 *  POST   /api/v1/users/logout        → handleLogout
 *  GET    /api/v1/users/me            → handleGetProfile
 *  PATCH  /api/v1/users/me            → handleUpdateProfile
 *  DELETE /api/v1/users/me            → handleDeleteAccount
 */
class UserController : public std::enable_shared_from_this<UserController>
{
public:
    using Json = nlohmann::json;

    UserController(std::shared_ptr<HttpRouter>              router,
                   std::shared_ptr<services::UserService>   userService,
                   std::shared_ptr<services::AuthService>   authService,
                   std::shared_ptr<services::TokenService>  tokenService,
                   Logger                                   logger);

    /**
     * Register every controller endpoint with the underlying router.
     * Has to be called once during bootstrap.
     */
    void registerRoutes();

private:
    // ─────────────────────────────────────────────────────────────────────────
    // Endpoint handlers
    // ─────────────────────────────────────────────────────────────────────────
    void handleRegister   (const HttpRequest& req, HttpResponse& res);
    void handleLogin      (const HttpRequest& req, HttpResponse& res);
    void handleLogout     (const HttpRequest& req, HttpResponse& res);
    void handleGetProfile (const HttpRequest& req, HttpResponse& res);
    void handleUpdateProfile(const HttpRequest& req, HttpResponse& res);
    void handleDeleteAccount(const HttpRequest& req, HttpResponse& res);

    // ─────────────────────────────────────────────────────────────────────────
    // Helper utilities
    // ─────────────────────────────────────────────────────────────────────────
    void sendError(HttpResponse& res, HttpStatus status, std::string_view msg) const noexcept;
    std::optional<std::string> extractBearerToken(const HttpRequest& req) const;

    // ─────────────────────────────────────────────────────────────────────────
    // Dependencies  (injected)
    // ─────────────────────────────────────────────────────────────────────────
    std::shared_ptr<HttpRouter>             _router;
    std::shared_ptr<services::UserService>  _users;
    std::shared_ptr<services::AuthService>  _auth;
    std::shared_ptr<services::TokenService> _tokens;

    // NOT null
    Logger _log;
};

// ════════════════════════════════════════════════════════════════════════════
// Inline implementation
// ════════════════════════════════════════════════════════════════════════════

//
// Ctor
//
inline UserController::UserController(std::shared_ptr<HttpRouter>             router,
                                      std::shared_ptr<services::UserService>  userService,
                                      std::shared_ptr<services::AuthService>  authService,
                                      std::shared_ptr<services::TokenService> tokenService,
                                      Logger                                  logger)
    : _router{std::move(router)}
    , _users {std::move(userService)}
    , _auth  {std::move(authService)}
    , _tokens{std::move(tokenService)}
    , _log   {std::move(logger)}
{
    if (!_router || !_users || !_auth || !_tokens)
        throw std::invalid_argument{"UserController: received null service dependency."};
}

//
// Public API
//
inline void UserController::registerRoutes()
{
    using namespace std::placeholders; // for _1, _2 placeholders

    // The router owns only weak function wrappers.  The `shared_from_this`
    // dance guarantees that the controller stays alive while a handler is in
    // flight, even if the surrounding service container is hot-reloading.
    auto self = shared_from_this();

    _router->addRoute("POST",   "/api/v1/users/register",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleRegister(req, res); });

    _router->addRoute("POST",   "/api/v1/users/login",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleLogin(req, res); });

    _router->addRoute("POST",   "/api/v1/users/logout",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleLogout(req, res); });

    _router->addRoute("GET",    "/api/v1/users/me",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleGetProfile(req, res); });

    _router->addRoute("PATCH",  "/api/v1/users/me",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleUpdateProfile(req, res); });

    _router->addRoute("DELETE", "/api/v1/users/me",
        [self](const HttpRequest& req, HttpResponse& res){ self->handleDeleteAccount(req, res); });

    _log.info("UserController: routes registered.");
}

//
// Endpoint: POST /users/register
//
inline void UserController::handleRegister(const HttpRequest& req, HttpResponse& res)
{
    try
    {
        auto body = Json::parse(req.body());

        const std::string email    = body.at("email").get<std::string>();
        const std::string password = body.at("password").get<std::string>();
        const std::string name     = body.value("name", "");

        if (email.empty() || password.empty())
        {
            sendError(res, HttpStatus::BadRequest, "Email and password are required.");
            return;
        }

        // Delegate heavy lifting to the user service:
        auto userId = _users->createUser(email, password, name);
        _log.info("New user registered: {}", email);

        // Auth-service issues e-mail verification token asynchronously.
        _auth->scheduleVerificationEmail(userId);

        res.setStatus(HttpStatus::Created);
        res.json(Json{
            {"status",  "ok"},
            {"user_id", userId}
        });
    }
    catch (const std::exception& ex)
    {
        _log.error("handleRegister: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Unable to register user.");
    }
}

//
// Endpoint: POST /users/login
//
inline void UserController::handleLogin(const HttpRequest& req, HttpResponse& res)
{
    try
    {
        auto body = Json::parse(req.body());

        const std::string email    = body.at("email").get<std::string>();
        const std::string password = body.at("password").get<std::string>();

        const auto user = _auth->validateCredentials(email, password);
        if (!user.has_value())
        {
            sendError(res, HttpStatus::Unauthorized, "Invalid credentials.");
            return;
        }

        const std::string token = _tokens->issueToken(user->id);

        res.setStatus(HttpStatus::OK);
        res.json(Json{
            {"status", "ok"},
            {"token",  token},
            {"user",   user->toJson() }
        });
    }
    catch (const std::exception& ex)
    {
        _log.error("handleLogin: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Login failed.");
    }
}

//
// Endpoint: POST /users/logout
//
inline void UserController::handleLogout(const HttpRequest& req, HttpResponse& res)
{
    auto jwt = extractBearerToken(req);

    if (!jwt)
    {
        sendError(res, HttpStatus::BadRequest, "Missing bearer token.");
        return;
    }

    try
    {
        _tokens->revoke(*jwt);
        res.setStatus(HttpStatus::NoContent); // 204
    }
    catch (const std::exception& ex)
    {
        _log.warn("handleLogout: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Logout failed.");
    }
}

//
// Endpoint: GET /users/me
//
inline void UserController::handleGetProfile(const HttpRequest& req, HttpResponse& res)
{
    auto jwt = extractBearerToken(req);

    if (!jwt)
    {
        sendError(res, HttpStatus::Unauthorized, "Not authenticated.");
        return;
    }

    try
    {
        auto userId = _tokens->validate(*jwt);
        if (!userId)
        {
            sendError(res, HttpStatus::Unauthorized, "Token invalid or expired.");
            return;
        }

        auto user = _users->fetchById(*userId);
        if (!user)
        {
            sendError(res, HttpStatus::NotFound, "User not found.");
            return;
        }

        res.setStatus(HttpStatus::OK);
        res.json(Json{
            {"status", "ok"},
            {"user",   user->toJson()}
        });
    }
    catch (const std::exception& ex)
    {
        _log.error("handleGetProfile: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Unable to fetch profile.");
    }
}

//
// Endpoint: PATCH /users/me
//
inline void UserController::handleUpdateProfile(const HttpRequest& req, HttpResponse& res)
{
    auto jwt = extractBearerToken(req);

    if (!jwt)
    {
        sendError(res, HttpStatus::Unauthorized, "Not authenticated.");
        return;
    }

    try
    {
        auto userId = _tokens->validate(*jwt);
        if (!userId)
        {
            sendError(res, HttpStatus::Unauthorized, "Token invalid or expired.");
            return;
        }

        Json updates = Json::parse(req.body());

        _users->updateUser(*userId, updates);
        _log.info("User {} updated profile.", *userId);

        res.setStatus(HttpStatus::OK);
        res.json(Json{{"status", "ok"}});
    }
    catch (const std::exception& ex)
    {
        _log.error("handleUpdateProfile: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Profile update failed.");
    }
}

//
// Endpoint: DELETE /users/me
//
inline void UserController::handleDeleteAccount(const HttpRequest& req, HttpResponse& res)
{
    auto jwt = extractBearerToken(req);

    if (!jwt)
    {
        sendError(res, HttpStatus::Unauthorized, "Not authenticated.");
        return;
    }

    try
    {
        auto userId = _tokens->validate(*jwt);
        if (!userId)
        {
            sendError(res, HttpStatus::Unauthorized, "Token invalid or expired.");
            return;
        }

        _users->deleteUser(*userId);
        _tokens->revokeAll(*userId);

        res.setStatus(HttpStatus::NoContent); // 204
    }
    catch (const std::exception& ex)
    {
        _log.error("handleDeleteAccount: {}", ex.what());
        sendError(res, HttpStatus::InternalServerError, "Account deletion failed.");
    }
}

//
// Helpers
//
inline void UserController::sendError(HttpResponse& res,
                                      HttpStatus    status,
                                      std::string_view msg) const noexcept
{
    res.setStatus(status);
    res.json(Json{
        {"status", "error"},
        {"message", msg}
    });
}

inline std::optional<std::string> UserController::extractBearerToken(const HttpRequest& req) const
{
    const auto authHeader = req.header("Authorization");
    static constexpr std::string_view kPrefix = "Bearer ";

    if (authHeader.size() < kPrefix.size() ||
        !std::equal(kPrefix.begin(), kPrefix.end(), authHeader.begin()))
    {
        return std::nullopt;
    }
    return std::string{authHeader.substr(kPrefix.size())};
}

} // namespace mbs::controllers

#endif /* MOSAICBOARD_STUDIO_CONTROLLERS_USERCONTROLLER_H */
