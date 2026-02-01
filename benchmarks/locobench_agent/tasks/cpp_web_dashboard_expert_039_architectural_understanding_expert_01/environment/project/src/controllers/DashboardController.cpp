```cpp
/*
 * MosaicBoard Studio
 * File: MosaicBoardStudio/src/controllers/DashboardController.cpp
 *
 * Implementation of REST controller responsible for the CRUD-style
 * endpoints that operate on a single dashboard instance.  The controller
 * hides all HTTP / authentication details from the business-logic layer
 * (DashboardService) and adds cross-cutting concerns such as caching,
 * metrics, and structured logging.
 *
 * Dependencies (headers are part of the code-base unless otherwise noted):
 *  - spdlog                         (external, MIT)
 *  - nlohmann/json.hpp              (external, MIT)
 *  - pistache/http.h & router.h     (external, Apache-2)
 *  - core/EventBus.hpp              (in-house)
 *  - services/DashboardService.hpp  (in-house)
 *  - services/ShareLinkService.hpp  (in-house)
 *  - security/AuthManager.hpp       (in-house)
 *  - cache/ICacheProvider.hpp       (in-house)
 */

#include "controllers/DashboardController.hpp"

#include <pistache/http.h>
#include <pistache/router.h>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <utility>

using json = nlohmann::json;

namespace mosaic::web
{

// --------------------------- Ctor / Dtor ----------------------------------

DashboardController::DashboardController(
        Pistache::Rest::Router&                    router,
        std::shared_ptr<service::DashboardService> dashboardService,
        std::shared_ptr<service::ShareLinkService> shareLinkService,
        std::shared_ptr<security::AuthManager>     authManager,
        std::shared_ptr<cache::ICacheProvider>     cacheProvider,
        std::shared_ptr<core::EventBus>            eventBus)
    : m_dashboardService{ std::move(dashboardService) }
    , m_shareLinkService{ std::move(shareLinkService) }
    , m_authManager{ std::move(authManager) }
    , m_cache{ std::move(cacheProvider) }
    , m_eventBus{ std::move(eventBus) }
{
    initRoutes(router);
}

// ----------------------------- Routes -------------------------------------

void DashboardController::initRoutes(Pistache::Rest::Router& router)
{
    using namespace Pistache::Rest;

    Routes::Get(router, "/api/v1/dashboard",
        Routes::bind(&DashboardController::handleGetDashboard, this));

    Routes::Put(router, "/api/v1/dashboard/layout",
        Routes::bind(&DashboardController::handlePutLayout, this));

    Routes::Post(router, "/api/v1/dashboard/share",
        Routes::bind(&DashboardController::handlePostShareLink, this));
}

// --------------------------- Route Handlers -------------------------------

void DashboardController::handleGetDashboard(
        const Pistache::Rest::Request& request,
        Pistache::Http::ResponseWriter response)
{
    try
    {
        const std::string  userId        = authenticatedUserId(request, response);
        const std::string  cacheKey      = userId + "::dashboard";
        constexpr uint64_t CACHE_TTL_SEC = 15;

        // 1. Try cache first (tiny JSON blobs – cheap).
        if (auto cached = m_cache->get(cacheKey); cached)
        {
            spdlog::debug("Cache hit: {}", cacheKey);
            response.send(Pistache::Http::Code::Ok, *cached, MIME(Application, Json));
            return;
        }

        // 2. Fallback to domain service.
        spdlog::debug("Cache miss: {}", cacheKey);
        auto dto = m_dashboardService->fetchDashboard(userId);
        json body = dto;                    // DashboardDTO has to_json() defined.

        // 3. Persist to cache – fire-and-forget.
        m_cache->put(cacheKey, body.dump(), std::chrono::seconds(CACHE_TTL_SEC));

        // 4. Send response.
        response.send(Pistache::Http::Code::Ok, body.dump(),
                      MIME(Application, Json));
    }
    catch (const std::exception& ex)
    {
        spdlog::error("handleGetDashboard: {}", ex.what());
        sendError(response, Pistache::Http::Code::Internal_Server_Error,
                  "Unable to load dashboard at this time.");
    }
}

void DashboardController::handlePutLayout(
        const Pistache::Rest::Request& request,
        Pistache::Http::ResponseWriter response)
{
    try
    {
        const std::string userId = authenticatedUserId(request, response);

        json payload;
        try
        {
            payload = json::parse(request.body());
        }
        catch (const std::exception& ex)
        {
            sendError(response, Pistache::Http::Code::Bad_Request,
                      "Malformed JSON payload.");
            return;
        }

        // Simple schema validation (production code would delegate to a schema lib).
        if (!payload.contains("tiles") || !payload["tiles"].is_array())
        {
            sendError(response, Pistache::Http::Code::Bad_Request,
                      "Field `tiles` (array) is required.");
            return;
        }

        m_dashboardService->updateLayout(userId, payload);

        // Invalidate cache so subsequent GET sees fresh layout.
        m_cache->invalidate(userId + "::dashboard");

        // Broadcast change to any connected real-time sessions.
        m_eventBus->publish(core::Event{
            .topic   = "dashboard.layout.updated",
            .payload = payload.dump(),
            .userId  = userId
        });

        response.send(Pistache::Http::Code::No_Content);
    }
    catch (const std::exception& ex)
    {
        spdlog::error("handlePutLayout: {}", ex.what());
        sendError(response, Pistache::Http::Code::Internal_Server_Error,
                  "Failed to update layout.");
    }
}

void DashboardController::handlePostShareLink(
        const Pistache::Rest::Request& request,
        Pistache::Http::ResponseWriter response)
{
    try
    {
        const std::string userId = authenticatedUserId(request, response);

        json payload;
        try
        {
            payload = json::parse(request.body());
        }
        catch (const std::exception& ex)
        {
            sendError(response, Pistache::Http::Code::Bad_Request,
                      "Malformed JSON payload.");
            return;
        }

        // Optional expiration in minutes; default 60.
        const auto   expiresIn   = payload.value("expiresIn", 60);
        const auto   permissions = payload.value("permissions", "r"); // r, rw

        auto link =
            m_shareLinkService->generateLink(userId, expiresIn, permissions);

        json body{
            { "shareUrl", link.url  },
            { "expiresAt", link.expirationIso8601 }
        };

        response.send(Pistache::Http::Code::Created, body.dump(),
                      MIME(Application, Json));
    }
    catch (const std::exception& ex)
    {
        spdlog::error("handlePostShareLink: {}", ex.what());
        sendError(response, Pistache::Http::Code::Internal_Server_Error,
                  "Could not create share link.");
    }
}

// --------------------------- Helper Methods -------------------------------

std::string DashboardController::authenticatedUserId(
        const Pistache::Rest::Request& request,
        Pistache::Http::ResponseWriter& response) const
{
    auto authHeader = request.headers()
                          .getRaw("Authorization")
                          .value_or(std::string{});

    security::AuthContext ctx;
    if (!m_authManager->validateBearer(authHeader, ctx))
    {
        sendError(response, Pistache::Http::Code::Unauthorized, "Unauthorized");
        throw std::runtime_error("unauthorized");
    }
    return ctx.userId;
}

void DashboardController::sendError(
        Pistache::Http::ResponseWriter& response,
        Pistache::Http::Code               code,
        std::string_view                   message) const
{
    json body{
        { "error", message },
        { "statusCode", static_cast<int>(code) }
    };
    response.send(code, body.dump(), MIME(Application, Json));
}

} // namespace mosaic::web
```