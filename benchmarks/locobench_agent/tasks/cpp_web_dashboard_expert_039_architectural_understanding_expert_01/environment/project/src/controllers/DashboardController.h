#pragma once
/**************************************************************************************************
 *  MosaicBoard Studio
 *  File:    src/controllers/DashboardController.h
 *  Author:  MosaicBoard Studio Team
 *
 *  Description:
 *      REST-MVC controller responsible for exposing CRUD endpoints for dashboard resources as well
 *      as a real-time websocket stream that allows connected clients to subscribe to server-side
 *      events.  The controller is intentionally kept stateless; business logic is delegated to
 *      service-layer abstractions that can be replaced or mocked during unit testing.
 *
 *  Copyright (c) 2024 MosaicBoard Studio
 **************************************************************************************************/
#include <chrono>
#include <future>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include <nlohmann/json.hpp>                    // 3rd-party JSON lib (https://github.com/nlohmann/json)
#include <spdlog/spdlog.h>                      // 3rd-party logging

// Forward declarations for HTTP / WebSocket primitives used by the networking layer.
// These types are decoupled from a particular framework (Boost.Beast, Crow, oatpp, etc.),
// enabling MosaicBoard to swap transport stacks without recompiling core controllers.
namespace net {
    struct HttpRequest;
    struct HttpResponse;
    struct WebSocketSession;
} // namespace net

// Project-wide common utilities.
#include "common/Status.h"
#include "common/Uuid.h"
#include "middleware/RequestContext.h"

// Service-layer interfaces.
#include "services/ICacheService.h"
#include "services/IAuthService.h"
#include "services/IDashboardService.h"
#include "services/IEventBus.h"

namespace mosaic::controllers {

/**************************************************************************************************
 * DashboardController
 *
 * Thread-safe, stateless controller that implements the REST endpoints required to manage
 * dashboards.  Instances are generally created once per application and reused, but the controller
 * does not maintain client-specific state, making it safe to share across threads.
 **************************************************************************************************/
class DashboardController : public std::enable_shared_from_this<DashboardController>
{
public:
    // Dependency injection Constructor -----------------------------------------------------------
    DashboardController(std::shared_ptr<services::IDashboardService>  dashboardSvc,
                        std::shared_ptr<services::ICacheService>      cacheSvc,
                        std::shared_ptr<services::IAuthService>       authSvc,
                        std::shared_ptr<services::IEventBus>          eventBus)
        : _dashboardSvc(std::move(dashboardSvc))
        , _cacheSvc(std::move(cacheSvc))
        , _authSvc(std::move(authSvc))
        , _eventBus(std::move(eventBus))
    {
        if (!_dashboardSvc || !_cacheSvc || !_authSvc || !_eventBus)
        {
            throw std::invalid_argument("DashboardController: Received null service dependency");
        }
    }

    DashboardController(const DashboardController&)            = delete;
    DashboardController& operator=(const DashboardController&) = delete;
    DashboardController(DashboardController&&)                 = default;
    DashboardController& operator=(DashboardController&&)      = default;
    ~DashboardController()                                     = default;

    // ---------------------------------------------------------------------------------------------
    // REST Endpoints (synchronous).  All endpoints follow the pattern:
    //
    //      /dashboards               GET    -> listDashboards
    //      /dashboards/{id}          GET    -> getDashboard
    //      /dashboards               POST   -> createDashboard
    //      /dashboards/{id}          PUT    -> updateDashboard
    //      /dashboards/{id}          DELETE -> deleteDashboard
    //
    // When an operation is successful, HTTP 2xx responses are returned.  Errors map to the Mosaic
    // Status codes, which determine the HTTP status and error payload structure.
    // ---------------------------------------------------------------------------------------------
    net::HttpResponse listDashboards     (const net::HttpRequest& req) const noexcept;
    net::HttpResponse getDashboard       (const net::HttpRequest& req) const noexcept;
    net::HttpResponse createDashboard    (const net::HttpRequest& req) const noexcept;
    net::HttpResponse updateDashboard    (const net::HttpRequest& req) const noexcept;
    net::HttpResponse deleteDashboard    (const net::HttpRequest& req) const noexcept;

    // ---------------------------------------------------------------------------------------------
    // Real-time WebSocket Stream
    //
    // Endpoint:  /dashboards/{id}/stream
    //
    // Opens a full-duplex channel in which the server pushes differential updates whenever the
    // backing dashboard model changes (e.g., tile addition, layout change, data refresh).  The
    // implementation is deferred to the transport layer; the controller prepares the session.
    // ---------------------------------------------------------------------------------------------
    std::shared_ptr<net::WebSocketSession> openDashboardStream(const net::HttpRequest& req) const;

private:
    // ---------------------------------------------------------------------------------------------
    // Helper Functions
    // ---------------------------------------------------------------------------------------------
    struct AuthorizationResult
    {
        bool  authorized;
        std::string userId;
        common::Status  status;
    };

    AuthorizationResult authorize(const middleware::RequestContext& ctx,
                                  std::string_view requiredScope) const noexcept;

    static std::optional<common::Uuid> extractUuidParam(const net::HttpRequest& req,
                                                        std::string_view pathToken);

    static net::HttpResponse buildErrorResponse(common::Status status,
                                                std::string_view message,
                                                std::optional<nlohmann::json> extra = std::nullopt);

    // ---------------------------------------------------------------------------------------------
    // Dependency references
    // ---------------------------------------------------------------------------------------------
    std::shared_ptr<services::IDashboardService> _dashboardSvc;
    std::shared_ptr<services::ICacheService>     _cacheSvc;
    std::shared_ptr<services::IAuthService>      _authSvc;
    std::shared_ptr<services::IEventBus>         _eventBus;
};

// =================================================================================================
// Inline Implementations
// =================================================================================================
namespace detail {

// Map Mosaic status to HTTP status code
inline int toHttpStatus(common::Status code) noexcept
{
    using common::Status;
    switch (code)
    {
        case Status::Ok:                    return 200;
        case Status::InvalidArgument:       return 400;
        case Status::Unauthenticated:       return 401;
        case Status::PermissionDenied:      return 403;
        case Status::NotFound:              return 404;
        case Status::AlreadyExists:         return 409;
        case Status::Internal:              return 500;
        case Status::Unavailable:           return 503;
        default:                            return 520; // Unknown Error
    }
}

} // namespace detail

inline net::HttpResponse
DashboardController::buildErrorResponse(common::Status status,
                                        std::string_view message,
                                        std::optional<nlohmann::json> extra)
{
    nlohmann::json body{
        { "status",  static_cast<int>(status) },
        { "message", message               }
    };

    if (extra.has_value())
    {
        body["details"] = *extra;
    }

    net::HttpResponse res;
    res.statusCode = detail::toHttpStatus(status);
    res.body       = std::move(body).dump();
    return res;
}

inline DashboardController::AuthorizationResult
DashboardController::authorize(const middleware::RequestContext& ctx,
                               std::string_view requiredScope) const noexcept
{
    AuthorizationResult result{ false, {}, common::Status::Unauthenticated };

    auto authHeader = ctx.request().header("Authorization");
    if (!authHeader.has_value())
    {
        result.status = common::Status::Unauthenticated;
        return result;
    }

    auto tokenStatus = _authSvc->verifyToken(*authHeader, requiredScope);
    if (!tokenStatus.ok())
    {
        result.status = tokenStatus.code();
        return result;
    }

    result.authorized = true;
    result.userId     = tokenStatus.value();
    result.status     = common::Status::Ok;
    return result;
}

inline std::optional<common::Uuid>
DashboardController::extractUuidParam(const net::HttpRequest& req,
                                      std::string_view pathToken)
{
    auto uuidStr = req.pathParam(pathToken);
    if (!uuidStr.has_value())
    {
        return std::nullopt;
    }

    try
    {
        return common::Uuid::fromString(*uuidStr);
    }
    catch (const std::exception& ex)
    {
        spdlog::warn("Invalid UUID received: {} ({})", *uuidStr, ex.what());
        return std::nullopt;
    }
}

// -------------------------------------------------------------------------------------------------
// Example Implementation: getDashboard
//
// NOTE: Implementation details for remaining endpoints would follow a similar structure —
// extracting path / query parameters, performing authorization, calling the service layer,
// marshalling result to JSON, updating cache when needed, and finally returning an HttpResponse.
// -------------------------------------------------------------------------------------------------
inline net::HttpResponse
DashboardController::getDashboard(const net::HttpRequest& req) const noexcept
{
    middleware::RequestContext ctx{ req };

    // 1) Authorization -----------------------------------------------------
    auto authRes = authorize(ctx, "dashboard.read");
    if (!authRes.authorized)
    {
        return buildErrorResponse(authRes.status, "Unauthorized");
    }

    // 2) Path Parameter Extraction -----------------------------------------
    auto idOpt = extractUuidParam(req, "id");
    if (!idOpt)
    {
        return buildErrorResponse(common::Status::InvalidArgument,
                                  "Missing or invalid dashboard id");
    }

    const auto& dashboardId = *idOpt;

    // 3) Caching Lookup -----------------------------------------------------
    if (auto cached = _cacheSvc->get("dashboard:" + dashboardId.toString()); cached)
    {
        net::HttpResponse res;
        res.statusCode = 200;
        res.body       = *cached;
        return res;
    }

    // 4) Service Call -------------------------------------------------------
    auto dashboardOr = _dashboardSvc->getDashboard(dashboardId, authRes.userId);
    if (!dashboardOr.ok())
    {
        return buildErrorResponse(dashboardOr.code(), dashboardOr.message());
    }

    const auto& dto = dashboardOr.value();
    nlohmann::json payload = dto; // IDashboardService converts DTO to JSON via to_json()

    // 5) Store in Cache -----------------------------------------------------
    _cacheSvc->put("dashboard:" + dashboardId.toString(),
                   payload.dump(),
                   std::chrono::minutes{ 10 });

    // 6) Build Response -----------------------------------------------------
    net::HttpResponse res;
    res.statusCode = 200;
    res.body       = std::move(payload).dump();
    return res;
}

// The rest of the CRUD/WebSocket functions are declared but provided in the .cpp to keep the header
// lightweight.  Only small, trivial functions are defined inline here.

} // namespace mosaic::controllers