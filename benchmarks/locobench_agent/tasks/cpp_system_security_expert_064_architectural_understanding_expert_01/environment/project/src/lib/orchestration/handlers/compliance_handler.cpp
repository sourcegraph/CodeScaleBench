```cpp
/**
 * FortiLedger360 Enterprise Security Suite
 * system_security – Orchestration Layer
 *
 * File: src/lib/orchestration/handlers/compliance_handler.cpp
 *
 * Description:
 *   Implements the ComplianceHandler—one of the links in the
 *   Chain-of-Responsibility that validates incoming Command objects
 *   against tenant-specific compliance policies (PCI-DSS, HIPAA, SOC 2,
 *   etc.). The handler keeps a short-lived in-memory cache for policy
 *   documents, performs thread-safe look-ups, and emits structured
 *   diagnostic logs via spdlog. If the command passes evaluation, it is
 *   forwarded to the next handler in the chain; otherwise an error is
 *   propagated back to the caller through the shared ExecutionContext.
 */

#include "orchestration/handlers/compliance_handler.h"

#include "common/clock.h"
#include "common/tenant_id.h"
#include "domain/policy/policy_evaluator.h"
#include "domain/policy/policy_repository.h"
#include "infrastructure/telemetry/metrics.h"

#include <spdlog/spdlog.h>
#include <spdlog/sinks/rotating_file_sink.h>

#include <chrono>
#include <shared_mutex>
#include <unordered_map>

using namespace fortiledger::common;
using namespace fortiledger::domain::policy;
using namespace fortiledger::infrastructure::telemetry;

namespace fortiledger::orchestration::handlers {

// -----------------------------------------------------------------------------
// Internal helpers
// -----------------------------------------------------------------------------

namespace
{
    // Cache expiry interval for an in-memory policy document.
    constexpr std::chrono::minutes kPolicyTtl{10};
}

// -----------------------------------------------------------------------------
// ComplianceHandler Implementation
// -----------------------------------------------------------------------------

ComplianceHandler::ComplianceHandler(std::shared_ptr<IRequestHandler> nextHandler,
                                     std::shared_ptr<PolicyRepository>           repository,
                                     std::shared_ptr<PolicyEvaluator>           evaluator)
    : IRequestHandler(std::move(nextHandler))
    , repository_(std::move(repository))
    , evaluator_(std::move(evaluator))
    , log_(spdlog::get("core"))
{
    if (!log_) // First instantiation in the process creates the logger.
    {
        log_ = spdlog::rotating_logger_mt("core",
                                          "logs/fortiledger-core.log",
                                          /*max_file_size*/ 10_MiB,
                                          /*max_files*/ 3);
        log_->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] [%t] %v");
    }

    if (!repository_ || !evaluator_)
    {
        throw std::invalid_argument(
            "ComplianceHandler requires non-null repository and evaluator");
    }
}

bool ComplianceHandler::Handle(const Command& cmd, ExecutionContext& ctx)
{
    const auto& tenantId = cmd.tenant();
    const auto correlationId = ctx.correlation_id();

    // ---------------------------------------------------------------------
    // 1. Fetch policy—prefer cached version; otherwise query repository.
    // ---------------------------------------------------------------------
    PolicyDocument policy;
    try
    {
        policy = FetchPolicy(tenantId);
    }
    catch (const std::exception& ex)
    {
        ctx.SetError(ErrorCode::kPolicyRepositoryUnavailable,
                     fmt::format("Could not fetch policy for tenant {}: {}",
                                 tenantId.str(), ex.what()));
        log_->error("[corr:{}][tenant:{}] Policy fetch failure: {}",
                    correlationId, tenantId.str(), ex.what());
        return false;
    }

    // ---------------------------------------------------------------------
    // 2. Evaluate command vs. policy.
    // ---------------------------------------------------------------------
    try
    {
        if (!evaluator_->Evaluate(policy, cmd))
        {
            ctx.SetError(ErrorCode::kComplianceViolation,
                         fmt::format("Command {} violates compliance policy",
                                     cmd.name()));
            Metrics::Instance().Increment("compliance.violation");
            log_->warn("[corr:{}][tenant:{}] Compliance violation for command {}",
                       correlationId, tenantId.str(), cmd.name());
            return false;
        }
    }
    catch (const std::exception& ex)
    {
        ctx.SetError(ErrorCode::kPolicyEvaluationFailure,
                     fmt::format("Policy evaluation failed: {}", ex.what()));
        log_->error("[corr:{}][tenant:{}] Evaluation error: {}",
                    correlationId, tenantId.str(), ex.what());
        return false;
    }

    // ---------------------------------------------------------------------
    // 3. Forward to next handler.
    // ---------------------------------------------------------------------
    if (auto next = Next())
    {
        return next->Handle(cmd, ctx);
    }

    return true; // Terminal link in the chain.
}

// -----------------------------------------------------------------------------
// Private helpers
// -----------------------------------------------------------------------------

PolicyDocument ComplianceHandler::FetchPolicy(const TenantId& tenantId)
{
    const auto now = Clock::Now();

    // 1. Check read-side of the cache under a shared lock.
    {
        std::shared_lock lock(cacheMutex_);
        auto it = policyCache_.find(tenantId);
        if (it != policyCache_.end() &&
            now - it->second.timestamp <= kPolicyTtl)
        {
            Metrics::Instance().Increment("compliance.cache.hit");
            return it->second.policy;
        }
    }

    Metrics::Instance().Increment("compliance.cache.miss");

    // 2. Upgrade to exclusive lock—Double-Check pattern to avoid
    //    thundering-herd problem on cache miss.
    std::unique_lock lock(cacheMutex_);
    auto it = policyCache_.find(tenantId);
    if (it != policyCache_.end() &&
        now - it->second.timestamp <= kPolicyTtl)
    {
        Metrics::Instance().Increment("compliance.cache.hit_race");
        return it->second.policy;
    }

    // 3. Load from repository (may throw).
    auto policy = repository_->GetPolicyForTenant(tenantId);

    // 4. Insert / update cache.
    policyCache_[tenantId] = CachedEntry{policy, now};
    return policy;
}

} // namespace fortiledger::orchestration::handlers
```