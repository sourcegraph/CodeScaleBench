#ifndef FORTILEDGER360_DOMAIN_ENTITIES_TENANT_H_
#define FORTILEDGER360_DOMAIN_ENTITIES_TENANT_H_

/*
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  domain/entities/tenant.h
 *
 *  Purpose:
 *      Core domain object that represents a single customer tenant.
 *      The tenant acts as the aggregate-root for subscription, usage, and
 *      security-posture strategies.  It is a thread-safe, observable entity
 *      whose state transitions are validated against business invariants
 *      before mutations are committed.
 *
 *  Design Notes:
 *      • Strategy Pattern:  Exchangeable SecurityScanStrategy per tenant.
 *      • Observer Pattern:  Interested parties (billing, metrics, etc.)
 *        can subscribe to TenantEvents without creating hard dependencies.
 *      • Strong Exception Safety:  Public mutators provide transactional
 *        semantics; on any failure the tenant object remains unchanged.
 *      • Thread Safety:  Read-heavy workloads are protected by a shared
 *        mutex; exclusive writes are guarded by std::unique_lock.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fortiledger::domain::entities
{

// ---------------------------------------------------------------------------
// Forward declarations
// ---------------------------------------------------------------------------
class SecurityScanStrategy;

// ---------------------------------------------------------------------------
// Utility types
// ---------------------------------------------------------------------------

using Timestamp = std::chrono::system_clock::time_point;
using FeatureFlags = std::unordered_map<std::string, bool>;

// Custom strong‐typed identifier
class TenantId
{
public:
    explicit TenantId(std::string uuid) : _value(std::move(uuid))
    {
        if (_value.empty())
        {
            throw std::invalid_argument("TenantId cannot be empty");
        }
    }

    [[nodiscard]] const std::string &value() const noexcept { return _value; }

    bool operator==(const TenantId &other) const noexcept { return _value == other._value; }
    bool operator!=(const TenantId &other) const noexcept { return !(*this == other); }

private:
    std::string _value;
};

// ---------------------------------------------------------------------------
// SubscriptionTier
// ---------------------------------------------------------------------------
enum class SubscriptionTier : std::uint8_t
{
    BASIC = 0,
    ADVANCED,
    PREMIUM,
    ENTERPRISE
};

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------
enum class TenantEventType : std::uint8_t
{
    PLAN_CHANGED = 0,
    CAPACITY_UPDATED,
    SUSPENDED,
    REACTIVATED,
    DELETED
};

struct TenantEvent
{
    TenantEventType type;
    Timestamp       timestamp;
    std::string     message;
};

// ---------------------------------------------------------------------------
// SecurityScanStrategy (Strategy Pattern)
// ---------------------------------------------------------------------------
class SecurityScanStrategy
{
public:
    virtual ~SecurityScanStrategy() = default;

    // Return the cron expression or scheduling hints for orchestrators.
    [[nodiscard]] virtual std::string schedule() const                               = 0;

    // Compute estimated resource consumption, used for billing & capacity planning
    [[nodiscard]] virtual std::uint64_t estimatedComputeUnits() const noexcept       = 0;

    // Human readable name
    [[nodiscard]] virtual std::string name() const                                   = 0;

    // Clone support – each tenant owns its own copy
    [[nodiscard]] virtual std::unique_ptr<SecurityScanStrategy> clone() const        = 0;
};

// Default pay-as-you-go scan strategy
class PayAsYouGoScanStrategy final : public SecurityScanStrategy
{
public:
    std::string schedule() const override { return "@on-demand"; }
    std::uint64_t estimatedComputeUnits() const noexcept override { return 0; }
    std::string name() const override { return "Pay-As-You-Go"; }
    std::unique_ptr<SecurityScanStrategy> clone() const override
    {
        return std::make_unique<PayAsYouGoScanStrategy>(*this);
    }
};

// Continuous scan strategy
class ContinuousScanStrategy final : public SecurityScanStrategy
{
public:
    explicit ContinuousScanStrategy(std::chrono::minutes interval = std::chrono::minutes{15})
        : _interval(interval) {}

    std::string schedule() const override
    {
        return "*/" + std::to_string(_interval.count()) + " * * * *";
    }

    std::uint64_t estimatedComputeUnits() const noexcept override
    {
        // naive estimate: 1 CU per minute
        return static_cast<std::uint64_t>(_interval.count());
    }

    std::string name() const override { return "Continuous " + std::to_string(_interval.count()) + "m"; }

    std::unique_ptr<SecurityScanStrategy> clone() const override
    {
        return std::make_unique<ContinuousScanStrategy>(*this);
    }

private:
    std::chrono::minutes _interval;
};

// ---------------------------------------------------------------------------
// Tenant entity
// ---------------------------------------------------------------------------
class Tenant final
{
public:
    // Observer callback signature
    using Observer = std::function<void(const Tenant &, const TenantEvent &)>;

    // Builder for controlled construction
    class Builder
    {
    public:
        explicit Builder(TenantId id) : _id(std::move(id)) {}

        Builder &with_display_name(std::string name)
        {
            _displayName = std::move(name);
            return *this;
        }

        Builder &with_subscription(SubscriptionTier tier)
        {
            _subscriptionTier = tier;
            return *this;
        }

        Builder &with_capacity_quota(std::uint64_t quota)
        {
            _capacityQuota = quota;
            return *this;
        }

        Builder &with_feature_flags(FeatureFlags flags)
        {
            _featureFlags = std::move(flags);
            return *this;
        }

        Builder &with_scan_strategy(std::unique_ptr<SecurityScanStrategy> strategy)
        {
            if (!strategy)
            {
                throw std::invalid_argument("Strategy must not be null");
            }
            _scanStrategy = std::move(strategy);
            return *this;
        }

        Tenant build()
        {
            // Provide sensible defaults
            if (!_scanStrategy) { _scanStrategy = std::make_unique<PayAsYouGoScanStrategy>(); }
            if (_displayName.empty()) { _displayName = "unnamed-tenant"; }

            return Tenant(_id,
                          std::move(_displayName),
                          _subscriptionTier,
                          _capacityQuota,
                          std::move(_featureFlags),
                          std::move(_scanStrategy));
        }

    private:
        TenantId                               _id;
        std::string                            _displayName;
        SubscriptionTier                       _subscriptionTier = SubscriptionTier::BASIC;
        std::uint64_t                          _capacityQuota    = 0; // in compute units
        FeatureFlags                           _featureFlags {};
        std::unique_ptr<SecurityScanStrategy>  _scanStrategy;
    };

    // Copy / Move
    Tenant(const Tenant &other)
        : _id(other._id)
        , _displayName(other._displayName)
        , _subscriptionTier(other._subscriptionTier.load())
        , _capacityQuota(other._capacityQuota.load())
        , _featureFlags(other._featureFlags)          // guarded by read-lock – safe in ctor
        , _scanStrategy(other._scanStrategy->clone())
    {
        // observers intentionally not copied
    }

    Tenant &operator=(const Tenant &other)
    {
        if (this == &other) { return *this; }

        std::unique_lock write_lock(_mutex);

        _displayName       = other._displayName;
        _subscriptionTier.store(other._subscriptionTier.load());
        _capacityQuota.store(other._capacityQuota.load());
        _featureFlags      = other._featureFlags;
        _scanStrategy      = other._scanStrategy->clone();

        return *this;
    }

    Tenant(Tenant &&) noexcept            = default;
    Tenant &operator=(Tenant &&) noexcept = default;

    ~Tenant() = default;

    // ---------------------------------------------------------------------
    // Read API – no locks escaped
    // ---------------------------------------------------------------------
    [[nodiscard]] const TenantId &id() const noexcept               { return _id; }
    [[nodiscard]] std::string   displayName() const                 { std::shared_lock l(_mutex); return _displayName; }
    [[nodiscard]] SubscriptionTier subscriptionTier() const noexcept{ return _subscriptionTier.load(); }
    [[nodiscard]] std::uint64_t capacityQuota() const noexcept      { return _capacityQuota.load(); }
    [[nodiscard]] FeatureFlags  featureFlags() const                { std::shared_lock l(_mutex); return _featureFlags; }

    [[nodiscard]] const SecurityScanStrategy &scanStrategy() const noexcept
    {
        std::shared_lock l(_mutex);
        return *_scanStrategy;
    }

    [[nodiscard]] bool hasFeature(const std::string &key) const
    {
        std::shared_lock l(_mutex);
        auto it = _featureFlags.find(key);
        return it != _featureFlags.end() && it->second;
    }

    // ---------------------------------------------------------------------
    // Mutators – enforce invariants and notify observers
    // ---------------------------------------------------------------------
    void changeSubscriptionTier(SubscriptionTier newTier)
    {
        auto current = _subscriptionTier.load();
        if (current == newTier) { return; }

        _subscriptionTier.store(newTier);
        _emitEvent({ TenantEventType::PLAN_CHANGED,
                     std::chrono::system_clock::now(),
                     "Subscription tier changed" });
    }

    void updateCapacityQuota(std::uint64_t newQuota)
    {
        if (newQuota == 0)
        {
            throw std::invalid_argument("Quota cannot be zero");
        }
        _capacityQuota.store(newQuota);

        _emitEvent({ TenantEventType::CAPACITY_UPDATED,
                     std::chrono::system_clock::now(),
                     "Capacity quota updated" });
    }

    void setFeatureFlag(std::string key, bool enabled)
    {
        {
            std::unique_lock l(_mutex);
            _featureFlags[std::move(key)] = enabled;
        }
        // Non-critical, no event needed
    }

    void setScanStrategy(std::unique_ptr<SecurityScanStrategy> strategy)
    {
        if (!strategy)
        {
            throw std::invalid_argument("Strategy must not be null");
        }
        {
            std::unique_lock l(_mutex);
            _scanStrategy = std::move(strategy);
        }
        // treat as capacity updated: new estimate
        _emitEvent({ TenantEventType::CAPACITY_UPDATED,
                     std::chrono::system_clock::now(),
                     "Scan strategy updated" });
    }

    // ---------------------------------------------------------------------
    // Observer management
    // ---------------------------------------------------------------------
    std::size_t addObserver(Observer cb)
    {
        if (!cb) { throw std::invalid_argument("Observer callback must be valid"); }

        const std::size_t token = ++_observerIdCounter;
        std::unique_lock l(_mutex);
        _observers.emplace(token, std::move(cb));
        return token;
    }

    void removeObserver(std::size_t token)
    {
        std::unique_lock l(_mutex);
        _observers.erase(token);
    }

private:
    // Private ctor used by Builder
    Tenant(TenantId                                 id,
           std::string                              displayName,
           SubscriptionTier                         tier,
           std::uint64_t                            capacityQuota,
           FeatureFlags                             flags,
           std::unique_ptr<SecurityScanStrategy>    strategy)
        : _id(std::move(id))
        , _displayName(std::move(displayName))
        , _subscriptionTier(tier)
        , _capacityQuota(capacityQuota)
        , _featureFlags(std::move(flags))
        , _scanStrategy(std::move(strategy))
    {
        if (!_scanStrategy)
        {
            throw std::invalid_argument("Scan strategy must not be null");
        }
    }

    void _emitEvent(TenantEvent event)
    {
        // Snapshot observers under lock, then notify outside to avoid deadlock
        std::vector<Observer> snapshot;
        {
            std::shared_lock l(_mutex);
            for (auto &[_, cb] : _observers) { snapshot.emplace_back(cb); }
        }

        for (auto &cb : snapshot)
        {
            try
            {
                cb(*this, event);
            }
            catch (...)
            {
                // Swallow exceptions – observer failures must never compromise core logic
            }
        }
    }

    // ---------------------------------------------------------------------
    // State
    // ---------------------------------------------------------------------
    TenantId                                    _id;

    // Mutable shared fields guarded by _mutex OR atomic where relevant
    mutable std::shared_mutex                   _mutex;

    std::string                                 _displayName;      // protected by _mutex
    std::atomic<SubscriptionTier>               _subscriptionTier; // atomic for cheap reads
    std::atomic<std::uint64_t>                  _capacityQuota;    // atomic for cheap reads
    FeatureFlags                                _featureFlags;     // protected by _mutex
    std::unique_ptr<SecurityScanStrategy>       _scanStrategy;     // protected by _mutex

    // Observer registry
    std::unordered_map<std::size_t, Observer>   _observers;        // protected by _mutex
    std::atomic<std::size_t>                    _observerIdCounter { 0 };
};

} // namespace fortiledger::domain::entities

#endif // FORTILEDGER360_DOMAIN_ENTITIES_TENANT_H_
