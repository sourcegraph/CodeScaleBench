```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  Source file: src/lib/domain/strategies/payg_scan_strategy.cpp
 *
 *  Description:
 *      Implementation of the Pay-As-You-Go (PAYG) vulnerability–scanning
 *      strategy.  A PAYG tenant is billed only for the scans they actually
 *      execute.  This strategy performs four high–level steps:
 *
 *          1. Validation      – Confirm that the tenant is active and that the
 *                               request complies with contractual limits.
 *          2. Billing         – Pre-authorise usage credits (optimistic billing)
 *                               so that scans can be rejected early when the
 *                               budget is exhausted.
 *          3. Scheduling      – Delegate the scan job to the ScanScheduler,
 *                               which decides when and where the scan will
 *                               run inside the service-mesh.
 *          4. Event Emission  – Emit an InitiateSecurityScan command onto the
 *                               domain event-bus so that downstream services
 *                               (Scanner, AlertBroker, Metrics, …) can react.
 *
 *      The strategy is thread-safe and exception-safe.  Whenever an error
 *      occurs after a successful billing reservation, a compensating action
 *      is triggered to roll back the reserved credits.
 *
 *  Build Notes:
 *      •  Header-only interfaces (ILogger, IBillingService, IEventBus, …) are
 *         provided by sibling modules and are therefore included rather than
 *         forward-declared.
 *      •  This file purposefully keeps implementation details private while
 *         exposing only behaviour that belongs to the IScanStrategy contract.
 */

#include "payg_scan_strategy.hpp"

#include <chrono>
#include <iomanip>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

using namespace fortiledger::domain;
using namespace fortiledger::domain::strategies;

/* --------------------------------------------------------------------------
 *  Helpers / Internal (anonymous namespace)
 * -------------------------------------------------------------------------- */
namespace
{
    // Returns an RFC-4122 compliant, randomly generated UUIDv4.
    static std::string generate_uuid4()
    {
        static thread_local std::mt19937_64 rng{ std::random_device{}() };

        std::uniform_int_distribution<uint64_t> dist(0, std::numeric_limits<uint64_t>::max());
        uint64_t high = dist(rng);
        uint64_t low  = dist(rng);

        // Set the UUID version/fmt bits (version 4, variant 1):
        high &= 0xFFFFFFFFFFFF0FFFULL;
        high |= 0x0000000000004000ULL;
        low  &= 0x3FFFFFFFFFFFFFFFULL;
        low  |= 0x8000000000000000ULL;

        std::ostringstream oss;
        oss << std::hex << std::setfill('0')
            << std::setw(8)  << (high >> 32)
            << '-' << std::setw(4) << ((high >> 16) & 0xFFFF)
            << '-' << std::setw(4) << (high & 0xFFFF)
            << '-' << std::setw(4) << (low >> 48)
            << '-' << std::setw(12) << (low & 0xFFFFFFFFFFFFULL);
        return oss.str();
    }

    // Convenience: converts chrono::system_clock::time_point to ISO-8601 string.
    static std::string to_iso8601(const std::chrono::system_clock::time_point& tp)
    {
        std::time_t    t  = std::chrono::system_clock::to_time_t(tp);
        std::tm        tm = *gmtime(&t);
        char           buf[32]{};

        strftime(buf, sizeof(buf), "%FT%TZ", &tm);
        return buf;
    }
} // namespace

/* --------------------------------------------------------------------------
 *  ctor / dtor
 * -------------------------------------------------------------------------- */

PayGScanStrategy::PayGScanStrategy(std::shared_ptr<IScanScheduler> scheduler,
                                   std::shared_ptr<IBillingService> billing,
                                   std::shared_ptr<IEventBus>       eventBus,
                                   std::shared_ptr<utils::ILogger>  logger)
    : m_scheduler (std::move(scheduler))
    , m_billing   (std::move(billing))
    , m_eventBus  (std::move(eventBus))
    , m_logger    (std::move(logger))
{
    if (!m_scheduler || !m_billing || !m_eventBus || !m_logger)
        throw std::invalid_argument("PayGScanStrategy: Missing mandatory dependency.");

    m_logger->debug("[PayGScanStrategy] Instantiated.");
}

PayGScanStrategy::~PayGScanStrategy() = default;

/* --------------------------------------------------------------------------
 *  Public API
 * -------------------------------------------------------------------------- */

void PayGScanStrategy::initiateScan(const TenantContext& tenant,
                                    const ScanRequest&  request,
                                    const utils::CancellationToken& token)
{
    const auto now = std::chrono::system_clock::now();

    /*  1. Validation
     *  -------------------------------------------------- */
    if (token.isCancellationRequested())
        throw std::runtime_error("Scan was cancelled before it started.");

    if (!tenant.isActive())
        throw std::runtime_error("Inactive tenant.");

    if (!request.validate())
        throw std::invalid_argument("ScanRequest validation error.");

    /*  2. Calculate cost & pre-authorise billing
     *  -------------------------------------------------- */
    const double costUsd = estimateCost(request);

    BillingReservation reservation =
        m_billing->reserveCredits(tenant.id(),
                                  costUsd,
                                  BillingReservation::Purpose::SecurityScan);

    /*  3. Schedule the scan job
     *  -------------------------------------------------- */
    ScheduledJob scheduledJob;
    try
    {
        scheduledJob = m_scheduler->scheduleScan(tenant, request);
    }
    catch (...)
    {
        performCompensation(reservation);
        throw;
    }

    /*  4. Emit domain command (Event-Driven)
     *  -------------------------------------------------- */
    InitiateSecurityScan cmd;
    cmd.commandId   = generate_uuid4();
    cmd.timestamp   = to_iso8601(now);
    cmd.tenantId    = tenant.id();
    cmd.scanJobId   = scheduledJob.id;
    cmd.severity    = request.severity();
    cmd.fullSweep   = request.fullSweep();

    try
    {
        m_eventBus->publish(cmd);
        m_logger->info("[PAYG] Scan initiated for tenant '{}', job '{}', cost ${:.2f}",
                       tenant.id(), scheduledJob.id, costUsd);
    }
    catch (...)
    {
        performCompensation(reservation);
        throw;
    }
}

/* --------------------------------------------------------------------------
 *  Private helpers
 * -------------------------------------------------------------------------- */

double PayGScanStrategy::estimateCost(const ScanRequest& req) const
{
    // Basic heuristics: base price + per-target premium + deep-inspection premium
    constexpr double kBase             = 0.75;  // USD
    constexpr double kPerTarget        = 0.05;  // USD
    constexpr double kDeepInspection   = 2.50;  // USD
    constexpr double kFullSweepFactor  = 1.20;  // x1.2

    double cost = kBase +
                  (kPerTarget * static_cast<double>(req.targets().size()));

    if (req.deepInspection())
        cost += kDeepInspection;

    if (req.fullSweep())
        cost *= kFullSweepFactor;

    return cost;
}

void PayGScanStrategy::performCompensation(const BillingReservation& reservation) noexcept
{
    try
    {
        m_billing->rollbackReservation(reservation);
        m_logger->warn("[PAYG] Compensation executed for reservation '{}'.",
                       reservation.reservationId());
    }
    catch (const std::exception& ex)
    {
        // At this point we log but must not re-throw (no-except context).
        m_logger->error("[PAYG] Compensation failed! Manual intervention may be required: {}",
                        ex.what());
    }
}
```