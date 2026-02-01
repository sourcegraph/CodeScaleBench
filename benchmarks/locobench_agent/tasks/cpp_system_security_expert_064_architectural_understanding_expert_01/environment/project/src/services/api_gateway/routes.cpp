```cpp
/****************************************************************************************
 *  FortiLedger360 Enterprise Security Suite                                             *
 *                                                                                      *
 *  File:        src/services/api_gateway/routes.cpp                                    *
 *  Description: Central API Gateway route registry & request handling. Translates      *
 *               external HTTP/JSON requests into internal Command events, performs     *
 *               authentication / authorization, validation, rate-limiting and emits    *
 *               domain-level messages onto the asynchronous EventBus.                  *
 *                                                                                      *
 *  Copyright:   © 2024 FortiLedger360 Inc. All rights reserved.                        *
 ****************************************************************************************/

#include <chrono>
#include <memory>
#include <string>
#include <utility>
#include <random>

#include <pistache/endpoint.h>
#include <pistache/router.h>
#include <pistache/http.h>
#include <pistache/net.h>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include "event_bus/EventBus.hpp"            // Internal non-blocking message bus abstraction
#include "middleware/AuthMiddleware.hpp"      // JWT / mTLS assertions
#include "middleware/RateLimiter.hpp"         // Token-bucket per tenant
#include "validators/RequestValidator.hpp"    // JSON-schema & domain-rule validation
#include "utils/Chrono.hpp"                   // ISO-8601 helpers
#include "utils/Tracing.hpp"                  // OpenTelemetry wrapper
#include "errors/HttpError.hpp"               // Strongly typed HTTP errors

using json = nlohmann::json;
using namespace Pistache;

namespace fl360::gateway {

namespace {

/*-------------------------------------------------
 * Helpers
 *------------------------------------------------*/

std::string generateCorrelationId()
{
    static thread_local std::mt19937_64 rng{ std::random_device{}() };
    static constexpr char digits[] =
        "0123456789abcdef"; // 16-char representation similar to UUIDv4 sans dashes

    std::string id(16, '0');
    for (auto& c : id) { c = digits[rng() % 16]; }
    return id;
}

/**
 * Utility to serialise an error and send the HTTP response.
 */
void sendError(const Http::Request& req,
               Http::ResponseWriter   resp,
               const errors::HttpError& err)
{
    json body{
        { "timestamp", utils::chrono::to_iso8601(std::chrono::system_clock::now()) },
        { "path",      req.resource() },
        { "correlationId", req.headers().tryGetRaw("X-Correlation-Id").value_or("") },
        { "status",    err.statusCode() },
        { "error",     err.description() }
    };

    resp.headers()
        .add<Http::Header::ContentType>(MIME(Application, Json))
        .add<Http::Header::Server>("FortiLedger360/APIGateway");

    resp.send(err.statusCode(), body.dump());
}

/**
 * Wrap business handler with standard cross-cutting logic:
 *  - Tracing span creation
 *  - Correlation-Id propagation
 *  - Global exception handling
 */
template<typename Func>
Rest::Route::Handler withContext(Func&& fn)
{
    return [fn = std::forward<Func>(fn)](const Http::Request& req, Http::ResponseWriter resp) {
        std::string corrId = req.headers().tryGetRaw("X-Correlation-Id").value_or("");
        if (corrId.empty()) {
            corrId = generateCorrelationId();
            resp.headers().addRaw("X-Correlation-Id", corrId);
        }

        auto span = utils::tracing::start_server_span("api_gateway", req.resource(), corrId);

        try {
            fn(req, std::move(resp), corrId);
        }
        catch (const errors::HttpError& err) {
            spdlog::warn("HttpError [{}]: {}", err.statusCode(), err.what());
            sendError(req, std::move(resp), err);
        }
        catch (const std::exception& ex) {
            errors::HttpError err(Http::Code::Internal_Server_Error,
                                  "Internal server error");
            spdlog::error("Unhandled exception: {}", ex.what());
            sendError(req, std::move(resp), err);
        }
    };
}

} // namespace (anonymous)

/*-------------------------------------------------
 *  ApiGatewayRoutes implementation
 *------------------------------------------------*/

class ApiGatewayRoutes
{
public:
    explicit ApiGatewayRoutes(std::shared_ptr<fl360::bus::EventBus> bus)
        : bus_(std::move(bus))
    {}

    /**
     * Register all API endpoints into the provided router.
     */
    void registerRoutes(Rest::Router& router)
    {
        using namespace Rest;

        Routes::Get(router, "/health",
                    Routes::bind(&ApiGatewayRoutes::health, this));

        Routes::Post(router, "/v1/tenants",
                     withContext([this](const Http::Request& req,
                                        Http::ResponseWriter resp,
                                        const std::string& corrId) {
                         this->createTenant(req, std::move(resp), corrId);
                     }));

        Routes::Post(router, "/v1/security/scan",
                     withContext([this](const Http::Request& req,
                                        Http::ResponseWriter resp,
                                        const std::string& corrId) {
                         this->initiateScan(req, std::move(resp), corrId);
                     }));

        Routes::Post(router, "/v1/backup/schedule",
                     withContext([this](const Http::Request& req,
                                        Http::ResponseWriter resp,
                                        const std::string& corrId) {
                         this->scheduleBackup(req, std::move(resp), corrId);
                     }));
    }

private:
    /********************* ROUTE HANDLERS ************************/

    void health(const Rest::Request&, Http::ResponseWriter resp)
    {
        json body{
            { "status", "UP" },
            { "timestamp", utils::chrono::to_iso8601(std::chrono::system_clock::now()) }
        };

        resp.headers()
            .add<Http::Header::ContentType>(MIME(Application, Json))
            .add<Http::Header::Server>("FortiLedger360/APIGateway");

        resp.send(Http::Code::Ok, body.dump());
    }

    /**
     * POST /v1/tenants
     * Body:
     * {
     *   "tenantName": "Acme Corp",
     *   "adminEmail": "security@acme.test"
     * }
     */
    void createTenant(const Http::Request& req,
                      Http::ResponseWriter resp,
                      const std::string& corrId)
    {
        ensureAuthenticated(req);

        json body = parseJson(req);
        validators::RequestValidator::validateTenantCreation(body);

        bus_ ->publish("TenantOnboardingRequested", {
                { "correlationId", corrId },
                { "tenantName",    body.at("tenantName") },
                { "adminEmail",    body.at("adminEmail") },
                { "requestedBy",   getSubject(req) }
            });

        resp.headers()
            .add<Http::Header::ContentType>(MIME(Application, Json));

        resp.send(Http::Code::Accepted, json{
            { "message", "Tenant onboarding initiated" },
            { "correlationId", corrId }
        }.dump());
    }

    /**
     * POST /v1/security/scan
     */
    void initiateScan(const Http::Request& req,
                      Http::ResponseWriter resp,
                      const std::string& corrId)
    {
        const auto tenantId = ensureAuthenticated(req);

        rateLimiter_.acquireToken(tenantId, "security.scan");

        json payload = parseJson(req);
        validators::RequestValidator::validateScanRequest(payload);

        auto dispatchResult = bus_->publish("InitiateSecurityScan", {
            { "correlationId", corrId },
            { "tenantId",      tenantId },
            { "scanDepth",     payload.at("scanDepth") },
            { "targets",       payload.at("targets") }
        });

        if (!dispatchResult) {
            throw errors::HttpError(Http::Code::Service_Unavailable,
                                    "Unable to queue security scan at this time");
        }

        resp.send(Http::Code::Accepted, json{
            { "message", "Security scan queued" },
            { "correlationId", corrId }
        }.dump());
    }

    /**
     * POST /v1/backup/schedule
     */
    void scheduleBackup(const Http::Request& req,
                        Http::ResponseWriter resp,
                        const std::string& corrId)
    {
        const auto tenantId = ensureAuthenticated(req);
        rateLimiter_.acquireToken(tenantId, "backup.schedule");

        json payload = parseJson(req);
        validators::RequestValidator::validateBackupSchedule(payload);

        bus_->publish("ScheduleClusterBackup", {
            { "correlationId", corrId },
            { "tenantId",      tenantId },
            { "window",        payload.at("window") }
        });

        resp.send(Http::Code::Accepted, json{
            { "message", "Backup scheduling queued" },
            { "correlationId", corrId }
        }.dump());
    }

    /********************* SUPPORT FUNCTIONS ************************/

    /**
     * Ensure JWT / mTLS credential presence and validity. Returns tenantId when OK.
     * Throws HttpError otherwise.
     */
    std::string ensureAuthenticated(const Http::Request& req)
    {
        auto token = req.headers().tryGet<Http::Header::Authorization>();
        if (!token) {
            throw errors::HttpError(Http::Code::Unauthorized, "Missing Authorization header");
        }

        auto claims = auth_.verify(token->value());
        return claims.tenantId;
    }

    std::string getSubject(const Http::Request& req) const
    {
        return auth_.lastVerifiedSubject();
    }

    json parseJson(const Http::Request& req)
    {
        try {
            return json::parse(req.body());
        }
        catch (const json::parse_error& ex) {
            throw errors::HttpError(Http::Code::Bad_Request, "Malformed JSON body");
        }
    }

private:
    std::shared_ptr<fl360::bus::EventBus> bus_;
    middleware::AuthMiddleware            auth_;
    middleware::RateLimiter               rateLimiter_;
};

/*-------------------------------------------------
 *  Router bootstrap entry (called by main.cpp)
 *------------------------------------------------*/

void registerGatewayRoutes(Rest::Router& router,
                           std::shared_ptr<fl360::bus::EventBus> bus)
{
    ApiGatewayRoutes{ std::move(bus) }.registerRoutes(router);
}

} // namespace fl360::gateway
```