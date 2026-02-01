```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File:    src/lib/orchestration/handlers/authentication_handler.cpp
 *  Author:  FortiLedger360 Engineering
 *
 *  Description:
 *      Concrete implementation of the AuthenticationHandler used by the
 *      orchestration layer.  The handler is invoked by the Command-Bus each
 *      time an “AuthenticateTenant” command is published by the Presentation
 *      or API layer.  The class is responsible for:
 *
 *          • Validating the structure of the request (e.g., JWT, API-Key, OAuth).
 *          • Delegating credential verification to the underlying
 *            security-infrastructure service through gRPC.
 *          • Short-circuiting any further processing in the Chain-Of-Responsibility
 *            if the request is unauthenticated.
 *          • Publishing domain events (AuthenticationSucceeded /
 *            AuthenticationFailed) onto the Event-Bus for downstream consumers
 *            like AuditLog, MetricsCollector, or AlertBroker.
 *
 *      The implementation follows best practices regarding resource
 *      management (RAII), exception safety, observability, and resiliency.
 */

#include <chrono>
#include <regex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "orchestration/handlers/authentication_handler.hpp"
#include "orchestration/common/command_bus.hpp"
#include "orchestration/common/event_bus.hpp"

#include "infrastructure/grpc/auth_service_client.hpp"
#include "infrastructure/logging/logger.hpp"
#include "infrastructure/metrics/metrics_collector.hpp"

#include "domain/events/authentication_events.hpp"

namespace fortiledger360::orchestration::handlers
{

using namespace std::chrono_literals;
namespace metrics = fortiledger360::infrastructure::metrics;
namespace logging = fortiledger360::infrastructure::logging;
namespace grpc    = fortiledger360::infrastructure::grpc;

/* -------------------------------------------------------------------------- */
/*                               Local Helpers                                */
/* -------------------------------------------------------------------------- */

/**
 *  Validate the shape of a JWT using a simplified RFC-7519-compliant regex.
 *
 *  NOTE:
 *      This does NOT perform cryptographic validation.  It merely guards
 *      against malformed tokens before they hit the gRPC layer.
 */
static bool isLikelyJwt(const std::string& token)
{
    static const std::regex kJwtRegex(R"(^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_.+/=]*$)",
                                      std::regex_constants::ECMAScript);
    return std::regex_match(token, kJwtRegex);
}

/* -------------------------------------------------------------------------- */
/*                          AuthenticationHandler Impl                        */
/* -------------------------------------------------------------------------- */

AuthenticationHandler::AuthenticationHandler(
    std::shared_ptr<grpc::AuthServiceClient> auth_client,
    std::shared_ptr<orchestration::EventBus> event_bus)
    : auth_client_(std::move(auth_client)),
      event_bus_(std::move(event_bus))
{
    if (!auth_client_)
        throw std::invalid_argument("auth_client must not be null");
    if (!event_bus_)
        throw std::invalid_argument("event_bus must not be null");
}

void AuthenticationHandler::handle(const commands::AuthenticateTenant& cmd)
{
    using metrics::Timer;

    // 1. Observability ‑ kick-off metrics timer.
    Timer timer(metrics::MetricId::kAuthLatency);

    // 2. Preliminary sanity checks.
    if (cmd.tenant_id.empty())
    {
        publishFailure(cmd, AuthFailureReason::kEmptyTenantId);
        return;
    }

    if (cmd.credential.empty())
    {
        publishFailure(cmd, AuthFailureReason::kEmptyCredential);
        return;
    }

    // 3. Structural validation (cheap fail-fast).
    if (!isLikelyJwt(cmd.credential) && cmd.method == AuthMethod::kJwt)
    {
        publishFailure(cmd, AuthFailureReason::kMalformedJwt);
        return;
    }

    // 4. Perform remote verification with retry logic.
    try
    {
        constexpr std::size_t kMaxRetries   = 3;
        constexpr auto        kBackoffStep  = 200ms;

        std::size_t attempt = 0;
        for (;;)
        {
            attempt++;
            const auto result = auth_client_->verify(cmd);

            if (result.success)
            {
                publishSuccess(cmd.tenant_id, result.user_id, result.scopes);
                return; // success path
            }

            if (attempt >= kMaxRetries || !result.retryable)
            {
                // Non-retryable or max attempts exceeded.
                publishFailure(cmd, result.reason);
                return;
            }

            std::this_thread::sleep_for(kBackoffStep * attempt); // linear backoff
        }
    }
    catch (const std::exception& ex)
    {
        logging::Logger::instance().error("Unhandled exception during authentication: {}", ex.what());
        publishFailure(cmd, AuthFailureReason::kInternalError);
    }
}

/* -------------------------------------------------------------------------- */
/*                              Private Helpers                               */
/* -------------------------------------------------------------------------- */

void AuthenticationHandler::publishSuccess(const std::string& tenant_id,
                                           const std::string& user_id,
                                           std::vector<std::string> scopes) const
{
    // Increment success counter.
    metrics::MetricsCollector::instance().increment(metrics::MetricId::kAuthSucceeded);

    // Emit AuthenticationSucceeded event.
    domain::events::AuthenticationSucceeded evt{tenant_id, user_id, std::move(scopes)};
    event_bus_->publish(evt);

    logging::Logger::instance().info("Authenticated tenant '{}' as user '{}'", tenant_id, user_id);
}

void AuthenticationHandler::publishFailure(const commands::AuthenticateTenant& cmd,
                                           AuthFailureReason                     reason) const
{
    // Increment failure counter.
    metrics::MetricsCollector::instance().increment(metrics::MetricId::kAuthFailed);

    // Emit AuthenticationFailed event.
    domain::events::AuthenticationFailed evt{
        cmd.tenant_id, reason, cmd.correlation_id};
    event_bus_->publish(evt);

    logging::Logger::instance().warn("Authentication failed for tenant '{}': {}",
                                     cmd.tenant_id,
                                     to_string(reason));
}

} // namespace fortiledger360::orchestration::handlers
```