#include "subscription.h"

#include <chrono>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace fl360::domain::entities
{

//------------------------------------------------------------------------------
//  Helpers
//------------------------------------------------------------------------------
namespace
{
    std::string timePointToIsoString(const std::chrono::system_clock::time_point& tp)
    {
        using namespace std::chrono;

        const auto timeT     = system_clock::to_time_t(tp);
        const auto millis    = duration_cast<milliseconds>(tp.time_since_epoch()) % 1000;

        std::tm utcTm {};
#if defined(_WIN32)
        gmtime_s(&utcTm, &timeT);
#else
        gmtime_r(&timeT, &utcTm);
#endif

        std::ostringstream oss;
        oss << std::put_time(&utcTm, "%Y-%m-%dT%H:%M:%S")
            << '.' << std::setfill('0') << std::setw(3) << millis.count()
            << 'Z';
        return oss.str();
    }

} // anonymous namespace

//------------------------------------------------------------------------------
//  Construction
//------------------------------------------------------------------------------
Subscription::Subscription(SubscriptionId             id,
                           TenantId                   tenantId,
                           Plan                       plan,
                           std::chrono::seconds       billingCycle,
                           std::chrono::system_clock::time_point startDateUtc,
                           std::optional<std::chrono::system_clock::time_point> endDateUtc)
    : m_id { std::move(id) }
    , m_tenantId { std::move(tenantId) }
    , m_plan { std::move(plan) }
    , m_billingCycle { billingCycle }
    , m_startUtc { startDateUtc }
    , m_endUtc { endDateUtc }
    , m_status { SubscriptionStatus::PendingActivation }
{
    validateInvariant();

    raiseDomainEvent<event::SubscriptionCreated>(m_id,
                                                 m_tenantId,
                                                 m_plan.code(),
                                                 m_startUtc,
                                                 m_endUtc);
}

//------------------------------------------------------------------------------
//  Status transitions
//------------------------------------------------------------------------------
void Subscription::activate()
{
    if (m_status != SubscriptionStatus::PendingActivation)
    {
        throwInvalidTransition("activate");
    }

    m_status    = SubscriptionStatus::Active;
    m_activated = std::chrono::system_clock::now();

    raiseDomainEvent<event::SubscriptionActivated>(m_id,
                                                   m_tenantId,
                                                   m_plan.code(),
                                                   *m_activated);
}

void Subscription::suspend(const std::string& reason)
{
    if (m_status != SubscriptionStatus::Active)
    {
        throwInvalidTransition("suspend");
    }

    m_status    = SubscriptionStatus::Suspended;
    m_suspended = std::chrono::system_clock::now();

    raiseDomainEvent<event::SubscriptionSuspended>(m_id, reason, *m_suspended);
}

void Subscription::resume()
{
    if (m_status != SubscriptionStatus::Suspended)
    {
        throwInvalidTransition("resume");
    }

    m_status = SubscriptionStatus::Active;

    raiseDomainEvent<event::SubscriptionResumed>(m_id,
                                                 std::chrono::system_clock::now());
}

void Subscription::cancel(CancelReason reason)
{
    if (m_status == SubscriptionStatus::Cancelled)
    {
        throwInvalidTransition("cancel");
    }

    m_status  = SubscriptionStatus::Cancelled;
    m_cancelledReason = reason;
    m_endUtc  = std::chrono::system_clock::now();

    raiseDomainEvent<event::SubscriptionCancelled>(m_id, toString(reason), *m_endUtc);
}

void Subscription::renew()
{
    if (m_status != SubscriptionStatus::Active)
    {
        throwInvalidTransition("renew");
    }

    const auto now = std::chrono::system_clock::now();
    m_startUtc     = now;
    m_endUtc       = now + m_billingCycle;

    raiseDomainEvent<event::SubscriptionRenewed>(m_id,
                                                 m_plan.code(),
                                                 m_startUtc,
                                                 *m_endUtc);
}

void Subscription::upgrade(const Plan& targetPlan)
{
    if (!targetPlan.isHigherTierThan(m_plan))
    {
        throw std::invalid_argument(
            "Subscription::upgrade(): target plan must be of higher tier.");
    }

    const auto now = std::chrono::system_clock::now();

    m_previousPlan = m_plan;
    m_plan         = targetPlan;
    m_status       = SubscriptionStatus::Active; // remains active

    raiseDomainEvent<event::SubscriptionUpgraded>(m_id,
                                                  m_previousPlan->code(),
                                                  m_plan.code(),
                                                  now);
}

void Subscription::downgrade(const Plan& targetPlan)
{
    if (!targetPlan.isLowerTierThan(m_plan))
    {
        throw std::invalid_argument(
            "Subscription::downgrade(): target plan must be of lower tier.");
    }

    // Business rule: Downgrade only at the end of current cycle.
    if (!m_endUtc.has_value())
    {
        throw std::logic_error(
            "Subscription::downgrade(): cannot downgrade perpetual subscription.");
    }

    m_pendingDowngradePlan = targetPlan;

    raiseDomainEvent<event::SubscriptionDowngradeScheduled>(m_id,
                                                            m_plan.code(),
                                                            targetPlan.code(),
                                                            *m_endUtc);
}

//------------------------------------------------------------------------------
//  Billing
//------------------------------------------------------------------------------
bool Subscription::isPaymentOverdue(const std::chrono::system_clock::time_point& now) const
{
    if (!m_nextPaymentDueUtc.has_value())
        return false;

    return now > *m_nextPaymentDueUtc;
}

void Subscription::markPaymentSuccessful(const Money& amount,
                                         const std::string& transactionId)
{
    // Business validations
    if (amount.currency() != m_plan.currency())
    {
        throw std::invalid_argument("currency mismatch for subscription payment");
    }
    if (amount < m_plan.cost())
    {
        throw std::invalid_argument("paid amount less than expected subscription cost");
    }

    m_nextPaymentDueUtc = std::chrono::system_clock::now() + m_billingCycle;

    raiseDomainEvent<event::SubscriptionPaymentCaptured>(m_id,
                                                         amount,
                                                         transactionId,
                                                         *m_nextPaymentDueUtc);
}

//------------------------------------------------------------------------------
//  Query helpers
//------------------------------------------------------------------------------
bool Subscription::isActiveAt(const std::chrono::system_clock::time_point& when) const
{
    if (m_status != SubscriptionStatus::Active)
        return false;

    const bool started   = when >= m_startUtc;
    const bool notEnded  = !m_endUtc.has_value() || when < *m_endUtc;

    return started && notEnded;
}

//------------------------------------------------------------------------------
//  Serialization / logging
//------------------------------------------------------------------------------
std::string Subscription::toJson() const
{
    std::ostringstream oss;
    oss << "{"
        << R"("id":")"          << m_id << "\","
        << R"("tenantId":")"    << m_tenantId << "\","
        << R"("plan":")"        << m_plan.code() << "\","
        << R"("status":")"      << toString(m_status) << "\","
        << R"("startUtc":")"    << timePointToIsoString(m_startUtc) << "\","
        << R"("endUtc":")"      << (m_endUtc ? timePointToIsoString(*m_endUtc) : "null") << "\""
        << "}";
    return oss.str();
}

//------------------------------------------------------------------------------
// Uncommitted events — Unit of Work extraction
//------------------------------------------------------------------------------
std::vector<std::unique_ptr<event::DomainEvent>> Subscription::pullUncommittedEvents()
{
    auto events = std::move(m_uncommittedEvents);
    m_uncommittedEvents.clear();
    return events;
}

//------------------------------------------------------------------------------
//  Private utils
//------------------------------------------------------------------------------
void Subscription::validateInvariant() const
{
    if (m_plan.empty())
    {
        throw std::invalid_argument("Subscription must have a plan");
    }
    if (m_billingCycle.count() <= 0)
    {
        throw std::invalid_argument("Billing cycle must be > 0 seconds");
    }
}

void Subscription::throwInvalidTransition(const char* action) const
{
    std::ostringstream oss;
    oss << "Subscription::" << action << "(): invalid transition from state "
        << toString(m_status);
    throw std::logic_error(oss.str());
}

} // namespace fl360::domain::entities