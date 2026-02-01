#include "scan_command.hpp"

#include <chrono>
#include <exception>
#include <future>
#include <memory>
#include <string>
#include <utility>

#include "domain/events/scan_events.hpp"
#include "infrastructure/bus/event_bus.hpp"
#include "infrastructure/logger/logger.hpp"
#include "infrastructure/metrics/timer.hpp"
#include "infrastructure/uuid/uuid.hpp"
#include "services/scanner/iscanner_service.hpp"
#include "services/validator/compliance_validator.hpp"

namespace fortiledger::domain::commands {

using namespace std::chrono_literals;

/**************************************************************************************************
 * Helpers & internal details
 **************************************************************************************************/

namespace
{
constexpr std::chrono::seconds kDefaultScanTimeout = 5min;

/*!
 * Compute a per-tenant SLA timeout based on subscription plan and scan depth.
 * Fallbacks to `kDefaultScanTimeout` when no override exists or invalid input is provided.
 */
[[nodiscard]] std::chrono::seconds
resolve_timeout_for_tenant(const TenantId& tenant,
                           const ScanParameters& params,
                           const ISlaRepository&  sla_repo) noexcept
{
    try
    {
        const auto tier   = sla_repo.get_subscription_tier(tenant);
        const auto factor = sla_repo.get_timeout_factor(tier, params.depth);

        return std::chrono::seconds{
            static_cast<long long>(static_cast<double>(kDefaultScanTimeout.count()) * factor)};
    }
    catch (const std::exception& ex)
    {
        FLEDGER_LOG_WARN("Timeout resolution failed for tenant {}: {} – using default",
                         tenant, ex.what());
        return kDefaultScanTimeout;
    }
}

/*!
 * Publish a domain event with unified error handling.
 */
template <typename Event>
void publish_event(IEventBus& bus, Event&& evt) noexcept
{
    try
    {
        bus.publish(std::forward<Event>(evt));
    }
    catch (const std::exception& ex)
    {
        FLEDGER_LOG_ERROR("Failed to publish event ({}): {}", typeid(Event).name(), ex.what());
    }
}

} // namespace

/**************************************************************************************************
 * ScanCommand implementation
 **************************************************************************************************/

ScanCommand::ScanCommand(std::shared_ptr<IScannerService>       scanner,
                         std::shared_ptr<IEventBus>             bus,
                         std::shared_ptr<ComplianceValidator>   validator,
                         std::shared_ptr<ISlaRepository>        sla_repo)
    : m_scanner{std::move(scanner)}
    , m_bus{std::move(bus)}
    , m_validator{std::move(validator)}
    , m_sla_repo{std::move(sla_repo)}
{
    if (!m_scanner || !m_bus || !m_validator || !m_sla_repo)
    {
        throw std::invalid_argument("ScanCommand: dependencies must not be null");
    }
}

ScanResult ScanCommand::execute(const CommandContext& ctx, const ScanParameters& params)
{
    const auto exec_id  = uuid::generate();
    const auto tenant   = ctx.tenant_id;
    const auto corr_id  = ctx.correlation_id;

    FLEDGER_LOG_INFO("ScanCommand[{}] – Tenant={} Correlation={}", exec_id, tenant, corr_id);

    infrastructure::metrics::Timer timer{"command.scan.execute"};

    // ----- 1. Compliance validation -------------------------------------------------------------
    if (auto violations = m_validator->validate(tenant, params); !violations.empty())
    {
        publish_event(*m_bus,
                      events::ScanRejected{
                          .execution_id  = exec_id,
                          .tenant_id     = tenant,
                          .correlation_id= corr_id,
                          .violations    = std::move(violations)});

        return {.success = false,
                .execution_id = exec_id,
                .message      = "Compliance validation failed"};
    }

    publish_event(*m_bus,
                  events::ScanAccepted{.execution_id  = exec_id,
                                       .tenant_id     = tenant,
                                       .correlation_id= corr_id});

    // ----- 2. Determine SLA timeout --------------------------------------------------------------
    const auto timeout = resolve_timeout_for_tenant(tenant, params, *m_sla_repo);

    // ----- 3. Kick off the scan asynchronously ---------------------------------------------------
    std::packaged_task<ScanOutcome()> task{[svc = m_scanner, tenant, params]() {
        return svc->start_scan(tenant, params);
    }};

    auto future = task.get_future();
    std::thread{std::move(task)}.detach();

    if (future.wait_for(timeout) == std::future_status::ready)
    {
        auto outcome = future.get();

        if (outcome.success)
        {
            publish_event(*m_bus,
                          events::ScanCompleted{.execution_id   = exec_id,
                                                .tenant_id      = tenant,
                                                .correlation_id = corr_id,
                                                .report_uri     = outcome.report_uri});

            return {.success      = true,
                    .execution_id = exec_id,
                    .message      = "Scan completed",
                    .report_uri   = outcome.report_uri};
        }
        else
        {
            publish_event(*m_bus,
                          events::ScanFailed{.execution_id   = exec_id,
                                             .tenant_id      = tenant,
                                             .correlation_id = corr_id,
                                             .reason         = outcome.error});

            return {.success      = false,
                    .execution_id = exec_id,
                    .message      = "Scan failed: " + outcome.error};
        }
    }
    // ----- 4. SLA timeout ------------------------------------------------------------------------
    else
    {
        publish_event(*m_bus,
                      events::ScanTimedOut{.execution_id   = exec_id,
                                           .tenant_id      = tenant,
                                           .correlation_id = corr_id,
                                           .timeout        = timeout});

        return {.success      = false,
                .execution_id = exec_id,
                .message      = "Scan timed out after " +
                             std::to_string(timeout.count()) + " seconds"};
    }
}

} // namespace fortiledger::domain::commands