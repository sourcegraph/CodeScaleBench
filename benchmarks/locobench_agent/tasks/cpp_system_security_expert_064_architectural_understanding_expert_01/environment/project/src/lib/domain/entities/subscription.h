// FortiLedger360/src/lib/domain/entities/subscription.h
// Copyright
// SPDX-License-Identifier: BUSL-1.1
//
// Core business entity that represents a tenant’s subscription to the FortiLedger360
// catalogue of security services.
//
// NOTE:  This header is intentionally self-contained – the Subscription aggregate is
//        shared across multiple micro-services (Billing, CRM, Provisioning, Analytics),
//        so a header-only implementation lowers integration friction.  All mutations
//        are guarded by a mutex to make the class safe for concurrent access.
//
//        Down-stream services normally interact with the entity only through the
//        exposed invariants;  publishing raw references is disallowed.

#pragma once

// STL
#include <chrono>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <mutex>

// 3rd-party
#include <nlohmann/json.hpp>

namespace fl360::domain::entities
{
// ──────────────────────────────────────────────────────────────────────────────
//  Value types / enums
// ──────────────────────────────────────────────────────────────────────────────
enum class SubscriptionStatus
{
    PendingActivation,
    Active,
    Suspended,
    Cancelled,
    Expired
};

enum class BillingCycle
{
    Monthly,
    Quarterly,
    Yearly
};

enum class RenewalPolicy
{
    AutoRenew,
    ManualRenew
};

// Helper for (de)serialization / logging
inline constexpr std::string_view to_string(SubscriptionStatus s) noexcept
{
    switch (s)
    {
    case SubscriptionStatus::PendingActivation: return "PendingActivation";
    case SubscriptionStatus::Active:            return "Active";
    case SubscriptionStatus::Suspended:         return "Suspended";
    case SubscriptionStatus::Cancelled:         return "Cancelled";
    case SubscriptionStatus::Expired:           return "Expired";
    default:                                    return "Unknown";
    }
}

inline constexpr std::string_view to_string(BillingCycle c) noexcept
{
    switch (c)
    {
    case BillingCycle::Monthly:   return "Monthly";
    case BillingCycle::Quarterly: return "Quarterly";
    case BillingCycle::Yearly:    return "Yearly";
    default:                      return "Unknown";
    }
}

inline constexpr std::string_view to_string(RenewalPolicy p) noexcept
{
    switch (p)
    {
    case RenewalPolicy::AutoRenew:  return "AutoRenew";
    case RenewalPolicy::ManualRenew:return "ManualRenew";
    default:                        return "Unknown";
    }
}

// ──────────────────────────────────────────────────────────────────────────────
//  Exceptions
// ──────────────────────────────────────────────────────────────────────────────
class SubscriptionError : public std::runtime_error
{
public:
    explicit SubscriptionError(std::string  msg)
        : std::runtime_error(std::move(msg)) {}
};

class InvalidTransitionError : public SubscriptionError
{
public:
    using SubscriptionError::SubscriptionError;
};

class EntitlementError : public SubscriptionError
{
public:
    using SubscriptionError::SubscriptionError;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Subscription aggregate root
// ──────────────────────────────────────────────────────────────────────────────
class Subscription
{
public:
    using Clock     = std::chrono::system_clock;
    using TimePoint = Clock::time_point;

    // Factory -----------------------------------------------------------------
    static Subscription CreateNew(
        std::string                        id,
        std::string                        tenantId,
        std::string                        planCode,
        BillingCycle                       cycle,
        RenewalPolicy                      policy,
        std::unordered_set<std::string>    entitlements,
        TimePoint                          startsAt = Clock::now())
    {
        return Subscription(
            std::move(id),
            std::move(tenantId),
            std::move(planCode),
            SubscriptionStatus::PendingActivation,
            cycle,
            policy,
            std::move(entitlements),
            startsAt,
            std::nullopt,
            std::nullopt);
    }

    // Observers ---------------------------------------------------------------
    const std::string&             id()             const noexcept { return id_; }
    const std::string&             tenant_id()      const noexcept { return tenantId_; }
    const std::string&             plan_code()      const noexcept { return planCode_; }
    SubscriptionStatus             status()         const noexcept { return status_; }
    BillingCycle                   billing_cycle()  const noexcept { return billingCycle_; }
    RenewalPolicy                  renewal_policy() const noexcept { return renewalPolicy_; }
    const TimePoint&               starts_at()      const noexcept { return startsAt_; }
    const std::optional<TimePoint>&ends_at()        const noexcept { return endsAt_; }
    const std::optional<TimePoint>&last_renewal()   const noexcept { return lastRenewalAt_; }
    const std::unordered_set<std::string>& entitlements() const noexcept { return entitlements_; }

    bool is_active() const noexcept
    {
        return status_ == SubscriptionStatus::Active;
    }

    bool has_entitlement(const std::string& feature) const
    {
        std::lock_guard<std::mutex> g(mtx_);
        return entitlements_.find(feature) != entitlements_.end();
    }

    // Mutations --------------------------------------------------------------
    // Activate the subscription; idempotent.
    void activate()
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (status_ == SubscriptionStatus::Active)
            return;

        if (status_ != SubscriptionStatus::PendingActivation && status_ != SubscriptionStatus::Suspended)
            throw InvalidTransitionError("Cannot activate subscription from current state: "
                                         + std::string(to_string(status_)));

        status_        = SubscriptionStatus::Active;
        lastRenewalAt_ = Clock::now();
    }

    // Suspend (soft-pause).  Can be re-activated later.
    void suspend(const std::string& reason)
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (status_ != SubscriptionStatus::Active)
            throw InvalidTransitionError("Suspension allowed only from Active state.");

        status_      = SubscriptionStatus::Suspended;
        suspendNote_ = reason;
    }

    // Permanently cancel – cannot be undone.
    void cancel(const std::string& reason)
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (status_ == SubscriptionStatus::Cancelled)
            return;

        if (status_ == SubscriptionStatus::Expired)
            throw InvalidTransitionError("Subscription already expired.");

        status_   = SubscriptionStatus::Cancelled;
        endsAt_   = Clock::now();
        cancelNote_ = reason;
    }

    // Plan (up|down)grade
    void switch_plan(const std::string& newPlanCode,
                     std::unordered_set<std::string> newEntitlements)
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (status_ != SubscriptionStatus::Active)
            throw InvalidTransitionError("Plan can be switched only when subscription is Active.");

        planCode_      = newPlanCode;
        entitlements_  = std::move(newEntitlements);
        // Emit event here in production code (omitted) ------------------------
    }

    // Renew and compute next billing date
    void renew()
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (status_ != SubscriptionStatus::Active)
            throw InvalidTransitionError("Renewal requires Active status.");

        lastRenewalAt_ = Clock::now();
    }

    TimePoint next_billing_date() const
    {
        std::lock_guard<std::mutex> g(mtx_);
        if (!lastRenewalAt_)
            return startsAt_;

        switch (billingCycle_)
        {
        case BillingCycle::Monthly:   return *lastRenewalAt_ + std::chrono::hours(24 * 30);
        case BillingCycle::Quarterly: return *lastRenewalAt_ + std::chrono::hours(24 * 90);
        case BillingCycle::Yearly:    return *lastRenewalAt_ + std::chrono::hours(24 * 365);
        default:                      return *lastRenewalAt_;
        }
    }

    // Serialize for event publishing -----------------------------------------
    nlohmann::json to_json() const
    {
        std::lock_guard<std::mutex> g(mtx_);
        nlohmann::json j;
        j["id"]            = id_;
        j["tenantId"]      = tenantId_;
        j["planCode"]      = planCode_;
        j["status"]        = std::string(to_string(status_));
        j["billingCycle"]  = std::string(to_string(billingCycle_));
        j["renewalPolicy"] = std::string(to_string(renewalPolicy_));
        j["startsAt"]      = std::chrono::duration_cast<std::chrono::seconds>(
                                 startsAt_.time_since_epoch()).count();

        j["endsAt"]        = endsAt_ ? std::optional<long long>{
                               std::chrono::duration_cast<std::chrono::seconds>(
                                   endsAt_->time_since_epoch()).count()} : std::nullopt;

        j["lastRenewal"]   = lastRenewalAt_ ? std::optional<long long>{
                               std::chrono::duration_cast<std::chrono::seconds>(
                                   lastRenewalAt_->time_since_epoch()).count()} : std::nullopt;

        j["entitlements"]  = entitlements_;
        return j;
    }

private:
    // Private Ctor – use factory
    Subscription(std::string                       id,
                 std::string                       tenantId,
                 std::string                       planCode,
                 SubscriptionStatus                status,
                 BillingCycle                      cycle,
                 RenewalPolicy                     policy,
                 std::unordered_set<std::string>   entitlements,
                 TimePoint                         startsAt,
                 std::optional<TimePoint>          endsAt,
                 std::optional<TimePoint>          lastRenewalAt)
        : id_(std::move(id))
        , tenantId_(std::move(tenantId))
        , planCode_(std::move(planCode))
        , status_(status)
        , billingCycle_(cycle)
        , renewalPolicy_(policy)
        , entitlements_(std::move(entitlements))
        , startsAt_(startsAt)
        , endsAt_(std::move(endsAt))
        , lastRenewalAt_(std::move(lastRenewalAt))
    {}

    // State -------------------------------------------------------------------
    std::string                     id_;
    std::string                     tenantId_;
    std::string                     planCode_;
    SubscriptionStatus              status_;
    BillingCycle                    billingCycle_;
    RenewalPolicy                   renewalPolicy_;
    std::unordered_set<std::string> entitlements_;

    TimePoint                       startsAt_;
    std::optional<TimePoint>        endsAt_;
    std::optional<TimePoint>        lastRenewalAt_;

    // Track last reasons for audit
    std::string                     suspendNote_;
    std::string                     cancelNote_;

    mutable std::mutex              mtx_;
};

// nlohmann ADL helpers --------------------------------------------------------
inline void to_json(nlohmann::json& j, const Subscription& s)
{
    j = s.to_json();
}

} // namespace fl360::domain::entities