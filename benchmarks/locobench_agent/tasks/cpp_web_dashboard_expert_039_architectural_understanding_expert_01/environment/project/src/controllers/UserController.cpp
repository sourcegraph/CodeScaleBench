#include "UserController.h"

#include <utility>
#include <chrono>
#include <future>
#include <iomanip>
#include <sstream>

#include <nlohmann/json.hpp>

#include "http/HttpRequest.h"
#include "http/HttpResponse.h"
#include "services/UserService.h"
#include "services/AuthService.h"
#include "services/SessionService.h"
#include "services/TelemetryService.h"
#include "utils/Chrono.h"
#include "utils/Logger.h"
#include "utils/ScopeExit.h"

using namespace mb;                   // MosaicBoard root namespace
using mb::http::HttpStatus;           // Common HTTP status enums
using mb::http::HttpRequest;
using mb::http::HttpResponse;

namespace {

/* Convenience function to write a JSON error payload. */
HttpResponse jsonError(HttpStatus status,
                       const std::string& message,
                       const std::string& internalCode = "internal_error")
{
    nlohmann::json err{
        { "error", {
            { "code",  internalCode },
            { "message", message }
        }}
    };
    return HttpResponse{ status, err.dump() }
        .setHeader("Content-Type", "application/json; charset=utf-8");
}

/* Validates e-mail address format with a very small check; a more
   sophisticated validation lives in UserService::isValidEmail,
   but we still perform a pre-flight filter here to avoid useless I/O. */
bool looksLikeEmail(std::string_view s)
{
    return s.size() >= 5 &&
           s.find('@') != std::string_view::npos &&
           s.find('.') != std::string_view::npos;
}

/* Serialises a user entity to JSON for client responses. */
nlohmann::json userToJson(const model::User& u)
{
    return {
        { "id",            u.id() },
        { "email",         u.email() },
        { "displayName",   u.displayName() },
        { "avatarUrl",     u.avatarUrl() },
        { "createdAt",     utils::chrono::toIsoString(u.createdAt()) },
        { "updatedAt",     utils::chrono::toIsoString(u.updatedAt()) }
    };
}

} // namespace (anonymous)

/* ===============================  UserController  =============================== */

UserController::UserController(std::shared_ptr<services::UserService>   userService,
                               std::shared_ptr<services::AuthService>   authService,
                               std::shared_ptr<services::SessionService> sessionService,
                               std::shared_ptr<services::TelemetryService> telemetry)
    : _userService   { std::move(userService)   }
    , _authService   { std::move(authService)   }
    , _sessionService{ std::move(sessionService) }
    , _telemetry     { std::move(telemetry)     }
{
    if (!_userService || !_authService || !_sessionService || !_telemetry)
        throw std::invalid_argument{ "UserController – missing dependency" };
}

void UserController::registerRoutes(http::IRouter& router)
{
    using mb::http::Method;

    router.route(Method::POST,   "/api/v1/users",         [this](auto&& req){ return onRegister(req); });
    router.route(Method::POST,   "/api/v1/sessions",      [this](auto&& req){ return onLogin(req); });
    router.route(Method::DELETE, "/api/v1/sessions/me",   [this](auto&& req){ return onLogout(req); });

    router.route(Method::GET,    "/api/v1/users/me",      [this](auto&& req){ return onGetProfile(req); });
    router.route(Method::PATCH,  "/api/v1/users/me",      [this](auto&& req){ return onUpdateProfile(req); });
    router.route(Method::DELETE, "/api/v1/users/me",      [this](auto&& req){ return onDeleteAccount(req); });
}

/* ------------------------------  POST /users  ------------------------------ */
HttpResponse UserController::onRegister(const HttpRequest& req)
{
    utils::ScopeExit latency([&] {
        _telemetry->track("user.register.latency",
                          utils::chrono::now() - req.timestamp());
    });

    nlohmann::json body;
    try {
        body = nlohmann::json::parse(req.body());
    } catch (const nlohmann::json::parse_error& e) {
        return jsonError(HttpStatus::BadRequest, "Invalid JSON", "bad_json");
    }

    const std::string email        = body.value("email", "");
    const std::string password     = body.value("password", "");
    const std::string displayName  = body.value("displayName", "");

    if (!looksLikeEmail(email))
        return jsonError(HttpStatus::BadRequest, "E-mail address appears invalid", "invalid_email");

    if (password.size() < 8)
        return jsonError(HttpStatus::BadRequest,
                         "Password must be at least 8 characters long",
                         "weak_password");

    try {
        auto user = _userService->createUser(email, password, displayName);
        _telemetry->increment("user.register.success");

        return HttpResponse{ HttpStatus::Created, userToJson(user).dump() }
                .setHeader("Content-Type", "application/json; charset=utf-8");
    }
    catch (const services::UserService::DuplicateEmailException&) {
        _telemetry->increment("user.register.duplicate_email");
        return jsonError(HttpStatus::Conflict, "E-mail already in use", "duplicate_email");
    }
    catch (const std::exception& ex) {
        log::error("UserController::onRegister – {}", ex.what());
        _telemetry->increment("user.register.failure");
        return jsonError(HttpStatus::InternalServerError, "Unable to create user");
    }
}

/* ------------------------------  POST /sessions  ------------------------------ */
HttpResponse UserController::onLogin(const HttpRequest& req)
{
    nlohmann::json body;
    try {
        body = nlohmann::json::parse(req.body());
    } catch (...) {
        return jsonError(HttpStatus::BadRequest, "Invalid JSON", "bad_json");
    }

    const auto email    = body.value("email", "");
    const auto password = body.value("password", "");

    if (email.empty() || password.empty())
        return jsonError(HttpStatus::BadRequest, "Missing credentials", "missing_credentials");

    try {
        auto user = _authService->authenticate(email, password);

        // Create session token
        auto sessionToken = _sessionService->openSession(user.id());

        nlohmann::json payload = {
            { "token",       sessionToken.token },
            { "expiresAt",   utils::chrono::toIsoString(sessionToken.expiresAt) },
            { "user",        userToJson(user) }
        };

        // Audit log (fire-and-forget)
        std::async(std::launch::async, [this, user] {
            _telemetry->track("auth.login", { { "userId", std::to_string(user.id()) } });
        });

        return HttpResponse{ HttpStatus::OK, payload.dump() }
                .setHeader("Content-Type", "application/json; charset=utf-8")
                .setHeader("Set-Cookie",
                           "mbs.sid=" + sessionToken.token +
                           "; HttpOnly; Path=/; SameSite=Strict; Secure");
    }
    catch (const services::AuthService::InvalidCredentials&) {
        _telemetry->increment("auth.login.invalid_credentials");
        return jsonError(HttpStatus::Unauthorized, "Invalid credentials", "invalid_credentials");
    }
    catch (const std::exception& ex) {
        log::error("UserController::onLogin – {}", ex.what());
        return jsonError(HttpStatus::InternalServerError, "Login failed");
    }
}

/* ------------------------------  DELETE /sessions/me  ------------------------------ */
HttpResponse UserController::onLogout(const HttpRequest& req)
{
    const auto sid = req.cookies().valueOr("mbs.sid", "");

    if (sid.empty()) {
        return jsonError(HttpStatus::Unauthorized, "Not logged in", "no_session");
    }

    try {
        _sessionService->closeSession(sid);
        _telemetry->increment("auth.logout.success");

        return HttpResponse{ HttpStatus::NoContent, "" }
                .setHeader("Set-Cookie",
                           "mbs.sid=; Path=/; HttpOnly; Expires=Thu, 01 Jan 1970 00:00:00 GMT");
    } catch (const std::exception& ex) {
        log::error("UserController::onLogout – {}", ex.what());
        return jsonError(HttpStatus::InternalServerError, "Logout failed");
    }
}

/* ------------------------------  GET /users/me  ------------------------------ */
HttpResponse UserController::onGetProfile(const HttpRequest& req)
{
    auto userId = authorize(req);
    if (!userId) {
        return jsonError(HttpStatus::Unauthorized, "Invalid or expired session", "unauthorized");
    }

    try {
        auto user = _userService->getUserById(*userId);
        return HttpResponse{ HttpStatus::OK, userToJson(user).dump() }
                .setHeader("Content-Type", "application/json; charset=utf-8");
    }
    catch (const services::UserService::NotFound&) {
        return jsonError(HttpStatus::NotFound, "User not found", "not_found");
    }
    catch (const std::exception& ex) {
        log::error("UserController::onGetProfile – {}", ex.what());
        return jsonError(HttpStatus::InternalServerError, "Unable to retrieve profile");
    }
}

/* ------------------------------  PATCH /users/me  ------------------------------ */
HttpResponse UserController::onUpdateProfile(const HttpRequest& req)
{
    auto userId = authorize(req);
    if (!userId)
        return jsonError(HttpStatus::Unauthorized, "Not logged in", "unauthorized");

    nlohmann::json body;
    try {
        body = nlohmann::json::parse(req.body());
    } catch (...) {
        return jsonError(HttpStatus::BadRequest, "Invalid JSON", "bad_json");
    }

    services::UserService::UpdatePayload changes;
    if (body.contains("displayName"))
        changes.displayName = body["displayName"].get<std::string>();

    if (body.contains("avatarUrl"))
        changes.avatarUrl = body["avatarUrl"].get<std::string>();

    if (changes.empty()) {
        return jsonError(HttpStatus::BadRequest,
                         "Nothing to update",
                         "empty_update");
    }

    try {
        auto updatedUser = _userService->updateUser(*userId, changes);
        _telemetry->increment("user.profile.updated");
        return HttpResponse{ HttpStatus::OK, userToJson(updatedUser).dump() }
                .setHeader("Content-Type", "application/json; charset=utf-8");
    }
    catch (const services::UserService::NotFound&) {
        return jsonError(HttpStatus::NotFound, "User not found", "not_found");
    }
    catch (const services::UserService::ValidationError& e) {
        return jsonError(HttpStatus::BadRequest, e.what(), "validation_error");
    }
    catch (const std::exception& ex) {
        log::error("UserController::onUpdateProfile – {}", ex.what());
        return jsonError(HttpStatus::InternalServerError, "Update failed");
    }
}

/* ------------------------------  DELETE /users/me  ------------------------------ */
HttpResponse UserController::onDeleteAccount(const HttpRequest& req)
{
    auto userId = authorize(req);
    if (!userId)
        return jsonError(HttpStatus::Unauthorized, "Not logged in", "unauthorized");

    try {
        _userService->deleteUser(*userId);
        _sessionService->closeAllSessionsForUser(*userId);
        _telemetry->increment("user.deleted");

        return HttpResponse{ HttpStatus::NoContent, "" };
    }
    catch (const services::UserService::NotFound&) {
        return jsonError(HttpStatus::NotFound, "User not found", "not_found");
    }
    catch (const std::exception& ex) {
        log::error("UserController::onDeleteAccount – {}", ex.what());
        return jsonError(HttpStatus::InternalServerError, "Delete failed");
    }
}

/* ------------------------------  Private helpers ------------------------------ */
std::optional<model::UserId> UserController::authorize(const HttpRequest& req) const
{
    const auto sid = req.cookies().valueOr("mbs.sid", "");
    if (sid.empty())
        return std::nullopt;

    try {
        return _sessionService->userIdFromSession(sid);
    } catch (const services::SessionService::SessionNotFound&) {
        return std::nullopt;
    } catch (const std::exception& ex) {
        log::warn("UserController::authorize – {}", ex.what());
        return std::nullopt;
    }
}