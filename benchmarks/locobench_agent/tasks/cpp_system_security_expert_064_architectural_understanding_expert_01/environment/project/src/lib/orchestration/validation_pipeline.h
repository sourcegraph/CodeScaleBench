```cpp
#pragma once
/***************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  -----------------------------------------------------------
 *  File        : validation_pipeline.h
 *  License     : Proprietary – FortiLedger360 Inc.
 *
 *  Description :
 *      Header-only implementation of the orchestration-layer “Validation Pipeline”.  The pipeline
 *      materialises the Chain-of-Responsibility pattern and is responsible for enforcing compliance
 *      rules (PCI-DSS, CIS, SOC-2, …) before a user command (e.g. “InitiateSecurityScan”) is sent
 *      further downstream to domain services.
 *
 *      ┌────────────┐          ┌────────────┐          ┌────────────┐
 *      │  Command    │ ───────▶ │ Validation │ ───────▶ │ Orchestration│ ...
 *      └────────────┘          └────────────┘          └────────────┘
 *
 *      Each rule is hot-swappable at runtime and the pipeline is observable so that
 *      tracing/metrics systems (Prometheus, Jaeger, …) can attach themselves non-intrusively.
 *
 *  Thread-safety :
 *      • Rule registration is guarded by a RW lock (std::shared_mutex)
 *      • Pipeline execution is read-side, thus free of writer contention
 *
 ***************************************************************************************************/
#include <any>
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fl360::orchestration
{
/* =======================================================
 *  Diagnostics helpers
 * =====================================================*/
enum class Severity : uint8_t
{
    Info,
    Warning,
    Error,
    Fatal
};

struct ValidationIssue
{
    Severity        severity {Severity::Info};
    std::string     message;
    std::string     ruleName;       // which rule produced the issue?
    std::string     correlationId;  // external request id (for log search)
    std::chrono::nanoseconds   latency {0};

    explicit operator bool() const noexcept { return severity != Severity::Info; }
};

class ValidationResult
{
public:
    ValidationResult()              = default;
    ValidationResult(bool ok)       : m_ok(ok) {}

    bool                            ok()          const noexcept { return m_ok; }
    const std::vector<ValidationIssue>& issues()  const noexcept { return m_issues; }

    void addIssue(ValidationIssue iss)
    {
        if (iss.severity >= Severity::Error)
            m_ok = false;
        m_issues.emplace_back(std::move(iss));
    }

    // Merge another result into this one
    void merge(const ValidationResult& other)
    {
        m_ok &= other.m_ok;
        m_issues.insert(m_issues.end(), other.m_issues.begin(), other.m_issues.end());
    }

private:
    bool                    m_ok {true};
    std::vector<ValidationIssue>  m_issues;
};

/* =======================================================
 *  Validation Context (input data wrapper)
 * =====================================================*/
class ValidationContext
{
public:
    using Clock = std::chrono::steady_clock;

    explicit ValidationContext(std::string cmd, std::string tenant)
        : m_command(std::move(cmd)), m_tenantId(std::move(tenant)),
          m_timestamp(Clock::now())
    {}

    const std::string&  command()   const noexcept { return m_command; }
    const std::string&  tenantId()  const noexcept { return m_tenantId; }
    Clock::time_point   timestamp() const noexcept { return m_timestamp; }

    /* Generic key/value bag – avoids a combinatorial explosion of overloads */
    template<typename T>
    void set(const std::string& key, T value)
    {
        std::unique_lock lock(m_kvMutex);
        m_kv[key] = std::any(std::move(value));
    }

    template<typename T>
    std::optional<T> get(const std::string& key) const
    {
        std::shared_lock lock(m_kvMutex);
        auto it = m_kv.find(key);
        if (it == m_kv.end())
            return std::nullopt;
        try
        {
            return std::any_cast<T>(it->second);
        }
        catch (const std::bad_any_cast&)
        {
            return std::nullopt;
        }
    }

private:
    std::string                             m_command;
    std::string                             m_tenantId;
    Clock::time_point                       m_timestamp;
    mutable std::shared_mutex               m_kvMutex;
    std::unordered_map<std::string, std::any>   m_kv;
};

/* =======================================================
 *  Observer / Telemetry interface
 * =====================================================*/
struct PipelineObserver
{
    virtual ~PipelineObserver() = default;

    virtual void onRuleStart(const std::string& ruleName,
                             const ValidationContext& ctx)              noexcept = 0;
    virtual void onRuleEnd(const std::string& ruleName,
                           const ValidationContext& ctx,
                           const ValidationResult& result,
                           std::chrono::nanoseconds latency)            noexcept = 0;
    virtual void onPipelineEnd(const ValidationContext& ctx,
                               const ValidationResult& aggregate)       noexcept = 0;
};

/* =======================================================
 *  Validation Rule (Strategy)
 * =====================================================*/
class ValidationRule
{
public:
    virtual ~ValidationRule() = default;

    virtual std::string     name()      const = 0;
    virtual ValidationResult validate(const ValidationContext& ctx) const = 0;
};

/* =======================================================
 *  Validation Pipeline (Chain-of-Responsibility)
 * =====================================================*/
class ValidationPipeline
{
public:
    enum class ShortCircuit
    {
        None,               // run all rules
        OnError,            // stop on first Error/Fatal
        OnFatal            // stop on first Fatal
    };

    explicit ValidationPipeline(ShortCircuit policy = ShortCircuit::OnError)
        : m_policy(policy)
    {}

    void addRule(std::shared_ptr<ValidationRule> rule)
    {
        std::unique_lock lock(m_ruleMutex);
        m_rules.emplace_back(std::move(rule));
    }

    void removeRule(const std::string& ruleName)
    {
        std::unique_lock lock(m_ruleMutex);
        m_rules.erase(std::remove_if(m_rules.begin(),
                                     m_rules.end(),
                                     [&](const auto& r){ return r->name() == ruleName; }),
                      m_rules.end());
    }

    void clearRules()
    {
        std::unique_lock lock(m_ruleMutex);
        m_rules.clear();
    }

    void attachObserver(std::weak_ptr<PipelineObserver> obs)
    {
        std::unique_lock lock(m_observerMutex);
        m_observers.emplace_back(std::move(obs));
    }

    ValidationResult run(const ValidationContext& ctx) const
    {
        ValidationResult aggregate;
        std::vector<std::shared_ptr<ValidationRule>> snapshot;
        {
            std::shared_lock lock(m_ruleMutex);
            snapshot = m_rules; // copy shared_ptrs (cheap)
        }

        for (const auto& rule : snapshot)
        {
            notifyRuleStart(rule->name(), ctx);

            auto t0     = std::chrono::steady_clock::now();
            auto result = rule->validate(ctx);
            auto t1     = std::chrono::steady_clock::now();
            auto latency = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0);

            // Tag latency on any generated issues
            for (auto& issue : const_cast<std::vector<ValidationIssue>&>(result.issues()))
                issue.latency = latency;

            notifyRuleEnd(rule->name(), ctx, result, latency);

            aggregate.merge(result);

            if (shouldShortCircuit(aggregate))
                break;
        }

        notifyPipelineEnd(ctx, aggregate);
        return aggregate;
    }

private:
    bool shouldShortCircuit(const ValidationResult& r) const noexcept
    {
        if (m_policy == ShortCircuit::None)
            return false;

        for (const auto& iss : r.issues())
        {
            if (m_policy == ShortCircuit::OnError &&
                (iss.severity == Severity::Error || iss.severity == Severity::Fatal))
                return true;
            if (m_policy == ShortCircuit::OnFatal &&
                iss.severity == Severity::Fatal)
                return true;
        }
        return false;
    }

    void notifyRuleStart(const std::string& ruleName,
                         const ValidationContext& ctx) const noexcept
    {
        std::shared_lock lock(m_observerMutex);
        for (auto& weakObs : m_observers)
        {
            if (auto obs = weakObs.lock())
                obs->onRuleStart(ruleName, ctx);
        }
    }

    void notifyRuleEnd(const std::string& ruleName,
                       const ValidationContext& ctx,
                       const ValidationResult& res,
                       std::chrono::nanoseconds latency) const noexcept
    {
        std::shared_lock lock(m_observerMutex);
        for (auto& weakObs : m_observers)
        {
            if (auto obs = weakObs.lock())
                obs->onRuleEnd(ruleName, ctx, res, latency);
        }
    }

    void notifyPipelineEnd(const ValidationContext& ctx,
                           const ValidationResult& agg) const noexcept
    {
        std::shared_lock lock(m_observerMutex);
        for (auto& weakObs : m_observers)
        {
            if (auto obs = weakObs.lock())
                obs->onPipelineEnd(ctx, agg);
        }
    }

private:
    ShortCircuit                                     m_policy;
    mutable std::shared_mutex                        m_ruleMutex;
    std::vector<std::shared_ptr<ValidationRule>>     m_rules;

    mutable std::shared_mutex                        m_observerMutex;
    std::vector<std::weak_ptr<PipelineObserver>>     m_observers;
};

/* =======================================================
 *  Pre-built generic rules (examples)
 *  -------------------------------------------------------
 *  These illustrate how platform teams can contribute rules
 *  that will be dynamically registered by the IOC container.
 * =====================================================*/
namespace built_in
{

class TenantQuotaRule final : public ValidationRule
{
public:
    std::string name() const override { return "TenantQuotaRule"; }

    ValidationResult validate(const ValidationContext& ctx) const override
    {
        ValidationResult res;
        auto usedOpt  = ctx.get<size_t>("quota.used");
        auto limitOpt = ctx.get<size_t>("quota.limit");

        if (!usedOpt || !limitOpt)
        {
            ValidationIssue iss;
            iss.severity = Severity::Fatal;
            iss.message  = "Quota metadata missing in validation context.";
            iss.ruleName = name();
            res.addIssue(std::move(iss));
            return res;
        }

        if (*usedOpt > *limitOpt)
        {
            ValidationIssue iss;
            iss.severity = Severity::Error;
            std::ostringstream oss;
            oss << "Tenant exceeded quota: " << *usedOpt << " / " << *limitOpt;
            iss.message  = oss.str();
            iss.ruleName = name();
            res.addIssue(std::move(iss));
        }
        return res;
    }
};

class PCIComplianceRule final : public ValidationRule
{
public:
    std::string name() const override { return "PCIComplianceRule"; }

    ValidationResult validate(const ValidationContext& ctx) const override
    {
        ValidationResult res;

        // domain-specific example: protect card-holder data
        auto containsPII = ctx.get<bool>("payload.contains_pii").value_or(false);
        auto isEncrypted = ctx.get<bool>("payload.encrypted").value_or(false);

        if (containsPII && !isEncrypted)
        {
            ValidationIssue iss;
            iss.severity = Severity::Fatal;
            iss.message  = "PII detected in request without encryption. Denying request.";
            iss.ruleName = name();
            res.addIssue(std::move(iss));
        }

        return res;
    }
};

}   // namespace built_in
}   // namespace fl360::orchestration
```