#pragma once
/**
 * FortiLedger360 – API-Gateway
 * ---------------------------------------------
 * routes.h
 *
 * This header centralises all HTTP-route declarations used by the API-Gateway
 * façade for the FortiLedger360 security-suite.  The goal is to provide a
 * single source-of-truth that the front-end, the automated documentation
 * generator (OpenAPI), and the internal event-bus command dispatcher can rely
 * on.  The API-Gateway is intentionally stateless; each handler performs only
 * syntactic validation and subsequently publishes an intent to the event-bus.
 *
 * All route-handlers are intentionally lightweight ─ heavy business-logic
 * lives in downstream services that subscribe to the event-bus.  Nevertheless,
 * the gateway must still enforce authentication, RBAC, quota limits, and
 * shape the request into a canonical “Command” object.
 *
 * This file is header-only for compile-time registration convenience.
 */

#include <functional>
#include <optional>
#include <regex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>  // Single-header JSON (https://github.com/nlohmann/json)

//------------------------------------------------------------------------------

namespace fl360::api
{

/* ---------------------------------------------------------------------------
 * HTTP verb enumeration
 * ------------------------------------------------------------------------ */
enum class HttpVerb
{
    GET,
    POST,
    PUT,
    PATCH,
    DELETE_,
    OPTIONS
};

/* ---------------------------------------------------------------------------
 * Role-based access enumeration
 * ------------------------------------------------------------------------ */
enum class Role
{
    TenantAdmin,
    TenantReader,
    ProviderOperator,
    SystemAdmin
};

/* ---------------------------------------------------------------------------
 * Command pushed to the event-bus after the gateway validates the request.
 * ------------------------------------------------------------------------ */
struct CommandEnvelope
{
    std::string           commandName;   // e.g. "InitiateSecurityScan"
    std::string           tenantId;
    nlohmann::json        payload;       // Fully validated, canonical JSON
    std::string           correlationId; // Used for distributed tracing
};

/* ---------------------------------------------------------------------------
 * Request-context passed to every route-handler
 * ------------------------------------------------------------------------ */
struct RequestContext
{
    std::string                     path;
    HttpVerb                        verb;
    std::unordered_map<std::string,
                       std::string> headers;
    nlohmann::json                  body;
    Role                            callerRole;
    std::string                     tenantId;
    std::string                     correlationId;

    // Convenience helpers ----------------------------------------------------
    [[nodiscard]] bool hasHeader(std::string_view key) const
    {
        return headers.find(std::string(key)) != headers.cend();
    }

    [[nodiscard]] std::optional<std::string>
    header(std::string_view key) const
    {
        auto it = headers.find(std::string(key));
        if (it != headers.cend()) { return it->second; }
        return std::nullopt;
    }
};

/* ---------------------------------------------------------------------------
 * Route-handler type
 * ------------------------------------------------------------------------ */
using RouteHandler = std::function<CommandEnvelope(const RequestContext&)>;

/* ---------------------------------------------------------------------------
 * An individual route definition
 * ------------------------------------------------------------------------ */
struct Route
{
    std::string           name;           // Human-readable identifier
    HttpVerb              verb;
    std::regex            path;           // ^/tenants/([^/]+)/metrics$
    Role                  minimumRole;    // Minimum role required to invoke
    bool                  idempotent;     // Whether safe to retry
    RouteHandler          handler;

    // Matches incoming path against the route's regular expression
    [[nodiscard]] bool matches(const std::string_view incomingPath) const
    {
        return std::regex_match(incomingPath.cbegin(), incomingPath.cend(), path);
    }
};

/* ---------------------------------------------------------------------------
 * Route registry (singleton via Meyers)
 * ------------------------------------------------------------------------ */
class RouteRegistry
{
public:
    static RouteRegistry& instance()
    {
        static RouteRegistry registry;
        return registry;
    }

    void registerRoute(Route route)
    {
        if (m_routesByName.contains(route.name))
            throw std::runtime_error("Route already registered: " + route.name);

        m_routes.emplace_back(std::move(route));
        m_routesByName.emplace(m_routes.back().name, &m_routes.back());
    }

    [[nodiscard]] const std::vector<Route>& all() const noexcept
    {
        return m_routes;
    }

    // Returns the route that matches both method and path, or std::nullopt
    std::optional<const Route*> resolve(HttpVerb verb,
                                        const std::string_view path) const
    {
        for (const auto& r : m_routes)
            if (r.verb == verb && r.matches(path)) { return &r; }
        return std::nullopt;
    }

private:
    std::vector<Route>                       m_routes;
    std::unordered_map<std::string, Route*>  m_routesByName;

    RouteRegistry()  = default;
    ~RouteRegistry() = default;

    RouteRegistry(const RouteRegistry&)            = delete;
    RouteRegistry& operator=(const RouteRegistry&) = delete;
};

/* ---------------------------------------------------------------------------
 * Helper macro to ease route-registration at static-initialisation time.
 * ------------------------------------------------------------------------ */
#define FL360_REGISTER_ROUTE(UniqueName, Verb, Regex, MinRole, Idempotent, HandlerLambda) \
    namespace                                                                               \
    {                                                                                       \
        const bool UniqueName##_registered [[maybe_unused]] = [] {                          \
            ::fl360::api::RouteRegistry::instance().registerRoute(                          \
                {                                                                           \
                    #UniqueName,                                                            \
                    Verb,                                                                   \
                    std::regex{Regex, std::regex::ECMAScript | std::regex::optimize},       \
                    MinRole,                                                                \
                    Idempotent,                                                             \
                    HandlerLambda                                                           \
                });                                                                         \
            return true;                                                                    \
        }();                                                                                \
    }                                                                                       \
    static_assert(true, "Require semicolon after FL360_REGISTER_ROUTE") // NOLINT

/* ---------------------------------------------------------------------------
 * Convenience: convert string → HttpVerb (case-insensitive)
 * ------------------------------------------------------------------------ */
inline HttpVerb toVerb(std::string_view v)
{
    if (v == "GET") return HttpVerb::GET;
    if (v == "POST") return HttpVerb::POST;
    if (v == "PUT") return HttpVerb::PUT;
    if (v == "PATCH") return HttpVerb::PATCH;
    if (v == "DELETE") return HttpVerb::DELETE_;
    if (v == "OPTIONS") return HttpVerb::OPTIONS;
    throw std::invalid_argument("Unsupported HTTP verb: " + std::string(v));
}

/* ---------------------------------------------------------------------------
 * Pre-defined handlers (keep minimal ‑ heavy logic is downstream)
 * ------------------------------------------------------------------------ */

// Handler for initiating an on-demand vulnerability scan
inline const RouteHandler InitiateSecurityScanHandler =
    [](const RequestContext& ctx) -> CommandEnvelope
{
    // Basic sanity validation – ensure JSON payload has “scanDepth”
    if (!ctx.body.contains("scanDepth") || !ctx.body["scanDepth"].is_string())
    {
        throw std::invalid_argument(
            "Missing mandatory field 'scanDepth' in request payload.");
    }

    // Forge the event-bus command
    CommandEnvelope cmd;
    cmd.commandName   = "InitiateSecurityScan";
    cmd.tenantId      = ctx.tenantId;
    cmd.payload       = ctx.body;
    cmd.correlationId = ctx.correlationId;

    return cmd;
};

// Handler for scheduling a cluster backup
inline const RouteHandler ScheduleBackupHandler =
    [](const RequestContext& ctx) -> CommandEnvelope
{
    if (!ctx.body.contains("backupWindow") || !ctx.body["backupWindow"].is_string())
    {
        throw std::invalid_argument("Field 'backupWindow' must be provided.");
    }
    CommandEnvelope cmd;
    cmd.commandName   = "ScheduleClusterBackup";
    cmd.tenantId      = ctx.tenantId;
    cmd.payload       = ctx.body;
    cmd.correlationId = ctx.correlationId;
    return cmd;
};

// Handler for retrieving tenant-wide metrics (read-only)
inline const RouteHandler FetchMetricsHandler =
    [](const RequestContext& ctx) -> CommandEnvelope
{
    CommandEnvelope cmd;
    cmd.commandName   = "FetchTenantMetrics";
    cmd.tenantId      = ctx.tenantId;
    cmd.payload       = nlohmann::json::object(); // No body required
    cmd.correlationId = ctx.correlationId;
    return cmd;
};

/* ---------------------------------------------------------------------------
 * Auto-register all canonical routes using the helper macro
 * ------------------------------------------------------------------------ */
FL360_REGISTER_ROUTE(
    InitiateSecurityScan,
    HttpVerb::POST,
    R"(^/tenants/([A-Za-z0-9\-]+)/scan$)",
    Role::TenantAdmin,
    false, // NOT idempotent
    InitiateSecurityScanHandler);

FL360_REGISTER_ROUTE(
    ScheduleBackup,
    HttpVerb::POST,
    R"(^/tenants/([A-Za-z0-9\-]+)/backup/schedule$)",
    Role::TenantAdmin,
    false,
    ScheduleBackupHandler);

FL360_REGISTER_ROUTE(
    FetchTenantMetrics,
    HttpVerb::GET,
    R"(^/tenants/([A-Za-z0-9\-]+)/metrics$)",
    Role::TenantReader,
    true, // Safe to retry
    FetchMetricsHandler);

/* ---------------------------------------------------------------------------
 * Example utility for OpenAPI generation (optional)
 * ------------------------------------------------------------------------ */
inline nlohmann::json toOpenApi(const Route& r)
{
    nlohmann::json pathItem;
    auto& method = pathItem[ // Convert enum -> lowercase string
        (r.verb == HttpVerb::GET) ? "get" :
        (r.verb == HttpVerb::POST) ? "post" :
        (r.verb == HttpVerb::PUT) ? "put" :
        (r.verb == HttpVerb::PATCH) ? "patch" :
        (r.verb == HttpVerb::DELETE_) ? "delete" : "options"];

    method["summary"]     = r.name;
    method["operationId"] = r.name;
    method["tags"]        = {"FortiLedger360"};
    method["x-minRole"]   = static_cast<int>(r.minimumRole);
    method["x-idempotent"] = r.idempotent;

    return pathItem;
}

} // namespace fl360::api