#include "tenant.hpp"

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#ifdef _MSC_VER
#    pragma warning(push)
#    pragma warning(disable : 26444) //  Disable msvc 'prefer nullptr' etc. for third-party libs
#endif

namespace fortiledger360::domain {

using namespace std::chrono_literals;

/* ────────────────────────────────────────────────────────────
 * Local helpers
 * ────────────────────────────────────────────────────────── */
namespace {

constexpr double dollars(double v) noexcept { return v; }

double tierBaseCost(SubscriptionTier tier) noexcept
{
    switch (tier)
    {
    case SubscriptionTier::Free: return dollars(0.0);
    case SubscriptionTier::Basic: return dollars(249.0);
    case SubscriptionTier::Premium: return dollars(899.0);
    case SubscriptionTier::Enterprise: return dollars(3299.0);
    default: return dollars(0.0);
    }
}

double featureCost(FeatureFlag flag) noexcept
{
    static const std::unordered_map<FeatureFlag, double> kCost{
        {FeatureFlag::LoadBalancing, dollars(199.0)},
        {FeatureFlag::SecurityScanning, dollars(299.0)},
        {FeatureFlag::PerformanceMetrics, dollars(149.0)},
        {FeatureFlag::BackupRecovery, dollars(499.0)},
        {FeatureFlag::ConfigurationManagement, dollars(99.0)}};
    const auto it = kCost.find(flag);
    return it != kCost.cend() ? it->second : 0.0;
}

std::string to_string(FeatureFlag flag)
{
    switch (flag)
    {
    case FeatureFlag::LoadBalancing: return "LoadBalancing";
    case FeatureFlag::SecurityScanning: return "SecurityScanning";
    case FeatureFlag::PerformanceMetrics: return "PerformanceMetrics";
    case FeatureFlag::BackupRecovery: return "BackupRecovery";
    case FeatureFlag::ConfigurationManagement: return "ConfigurationManagement";
    default: return "UnknownFeature";
    }
}

std::string to_string(SubscriptionTier tier)
{
    switch (tier)
    {
    case SubscriptionTier::Free: return "Free";
    case SubscriptionTier::Basic: return "Basic";
    case SubscriptionTier::Premium: return "Premium";
    case SubscriptionTier::Enterprise: return "Enterprise";
    default: return "UnknownTier";
    }
}

std::string iso_timestamp(std::chrono::system_clock::time_point tp)
{
    std::time_t tt = std::chrono::system_clock::to_time_t(tp);
#if defined(_MSC_VER)
    std::tm tm;
    gmtime_s(&tm, &tt);
#else
    std::tm tm;
    gmtime_r(&tt, &tm);
#endif
    std::ostringstream oss;
    oss << std::put_time(&tm, "%FT%TZ");
    return oss.str();
}

} // namespace

/* ────────────────────────────────────────────────────────────
 * Tenant ctor / dtor
 * ────────────────────────────────────────────────────────── */
Tenant::Tenant(TenantId id,
               std::string_view name,
               SubscriptionTier tier /* = SubscriptionTier::Free */)
    : id_{std::move(id)}
    , name_{name}
    , tier_{tier}
    , createdAt_{std::chrono::system_clock::now()}
    , updatedAt_{createdAt_}
    , status_{TenantStatus::Active}
{
    if (id_.empty())
        throw std::invalid_argument("TenantId must not be empty.");
    if (name_.empty())
        throw std::invalid_argument("Tenant name must not be empty.");

    // Free tier comes with basic performance metrics only
    if (tier_ == SubscriptionTier::Free)
    {
        features_.insert(FeatureFlag::PerformanceMetrics);
    }
}

/* ────────────────────────────────────────────────────────────
 * Public accessors
 * ────────────────────────────────────────────────────────── */
const TenantId& Tenant::id() const noexcept
{
    return id_;
}

std::string Tenant::name() const
{
    std::shared_lock lock(mutex_);
    return name_;
}

SubscriptionTier Tenant::tier() const noexcept
{
    std::shared_lock lock(mutex_);
    return tier_;
}

TenantStatus Tenant::status() const noexcept
{
    std::shared_lock lock(mutex_);
    return status_;
}

bool Tenant::isFeatureEnabled(FeatureFlag f) const
{
    std::shared_lock lock(mutex_);
    return features_.contains(f);
}

/* ────────────────────────────────────────────────────────────
 * Mutators
 * ────────────────────────────────────────────────────────── */
void Tenant::rename(std::string_view newName)
{
    if (newName.empty())
        throw std::invalid_argument("Tenant name must not be empty.");

    {
        std::unique_lock lock(mutex_);
        if (name_ == newName)
            return;

        name_ = newName;
        touch_unsafe();
    }

    recordEvent(std::make_shared<evt::TenantRenamed>(id_, std::string(newName)));
}

void Tenant::changeStatus(TenantStatus sts)
{
    std::unique_lock lock(mutex_);
    if (status_ == sts)
        return;

    const auto previous = status_;
    status_ = sts;
    touch_unsafe();

    recordEvent(std::make_shared<evt::TenantStatusChanged>(id_, previous, sts));
}

void Tenant::upgradeSubscription(SubscriptionTier newTier)
{
    std::unique_lock lock(mutex_);
    if (newTier == tier_)
        return;

    if (newTier < tier_)
        throw std::logic_error("Downgrading subscription tier is not supported by business policy.");

    const auto previous = tier_;
    tier_ = newTier;
    touch_unsafe();

    lock.unlock(); // Avoid holding mutex while pushing events

    recordEvent(std::make_shared<evt::SubscriptionUpgraded>(id_, previous, newTier));
}

void Tenant::enableFeature(FeatureFlag flag)
{
    std::unique_lock lock(mutex_);
    const bool inserted = features_.insert(flag).second;
    if (!inserted)
        return; // No change
    touch_unsafe();

    lock.unlock();

    recordEvent(std::make_shared<evt::FeatureEnabled>(id_, flag));
}

void Tenant::disableFeature(FeatureFlag flag)
{
    std::unique_lock lock(mutex_);
    const bool erased = features_.erase(flag);
    if (!erased)
        return;
    touch_unsafe();

    lock.unlock();

    recordEvent(std::make_shared<evt::FeatureDisabled>(id_, flag));
}

/* ────────────────────────────────────────────────────────────
 * Forecasting / analytics
 * ────────────────────────────────────────────────────────── */
double Tenant::forecastMonthlyCost() const
{
    std::shared_lock lock(mutex_);
    double cost = tierBaseCost(tier_);
    for (const auto& f : features_)
        cost += featureCost(f);

    // Dynamic discount for enterprise (fictional business rule)
    if (tier_ == SubscriptionTier::Enterprise && features_.size() >= 3)
        cost *= 0.90; // 10% discount

    return cost;
}

/* ────────────────────────────────────────────────────────────
 * Domain event outward-queue
 * ────────────────────────────────────────────────────────── */
std::vector<std::shared_ptr<DomainEvent>> Tenant::pullDomainEvents()
{
    std::vector<std::shared_ptr<DomainEvent>> out;
    {
        std::lock_guard lock(eventsMutex_);
        out.swap(pendingEvents_);
    }
    return out;
}

void Tenant::recordEvent(const std::shared_ptr<DomainEvent>& evt)
{
    std::lock_guard lock(eventsMutex_);
    pendingEvents_.push_back(evt);
}

/* ────────────────────────────────────────────────────────────
 * Internal ‑ helpers
 * ────────────────────────────────────────────────────────── */
void Tenant::touch_unsafe()
{
    updatedAt_ = std::chrono::system_clock::now();
}

/* ────────────────────────────────────────────────────────────
 * Pretty-printing (for logging / debugging)
 * ────────────────────────────────────────────────────────── */
std::string Tenant::toJson() const
{
    std::ostringstream oss;
    {
        std::shared_lock lock(mutex_);
        oss << R"({"tenantId":")" << id_ << R"(",)"
            << R"("name":")" << name_ << R"(",)"
            << R"("subscriptionTier":")" << to_string(tier_) << R"(",)"
            << R"("status":")" << to_string(status_) << R"(",)"
            << R"("createdAt":")" << iso_timestamp(createdAt_) << R"(",)"
            << R"("updatedAt":")" << iso_timestamp(updatedAt_) << R"(",)"
            << R"("features":[)";

        for (auto it = features_.cbegin(); it != features_.cend(); ++it)
        {
            if (it != features_.cbegin())
                oss << ',';
            oss << '"' << to_string(*it) << '"';
        }
        oss << "]}";
    }
    return oss.str();
}

} // namespace fortiledger360::domain

#ifdef _MSC_VER
#    pragma warning(pop)
#endif