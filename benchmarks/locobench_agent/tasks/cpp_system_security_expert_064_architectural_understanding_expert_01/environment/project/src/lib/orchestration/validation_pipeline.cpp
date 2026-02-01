/**
 * FortiLedger360 - Enterprise Security Suite
 * Source: src/lib/orchestration/validation_pipeline.cpp
 *
 * Implementation of the Validation Pipeline that performs
 * multi-stage request validation in the Orchestration layer.
 *
 * The pipeline follows the classic Chain-of-Responsibility pattern:
 *
 *              +---------------+      +---------------+
 *  Request --->| QuotaValidator |----->| AuthValidator |--->
 *              +---------------+      +---------------+
 *                        |                    |
 *                        v                    v
 *                 +--------------+      +--------------+
 *                 | SLAValidator |----->| ...         |
 *                 +--------------+      +--------------+
 *
 * Each concrete validator inspects the ValidationContext and either
 * approves it or returns a ValidationError explaining the failure.
 *
 * The pipeline is thread-safe and re-usable across the process lifetime.
 */

#include <algorithm>
#include <chrono>
#include <exception>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

// External logging library (header-only)
// In production this would be <spdlog/spdlog.h> or similar.
#include "utils/log.hpp" // Fallback stub if spdlog not available.

namespace fortiledger360::orchestration {

// Forward declarations of domain objects that exist elsewhere
struct CommandEnvelope;
struct TenantProfile;
class PolicyService;

/**
 * Lightweight error-detail object returned by validators.
 */
struct ValidationError {
    std::string code;     // e.g., "AUTHZ_DENIED", "QUOTA_EXCEEDED"
    std::string message;  // Human-readable message
};

/**
 * The outcome of an individual validator execution.
 */
enum class ValidationStatus {
    Passed,
    Failed,
    Skipped  // validator determined itself not applicable (e.g., feature disabled)
};

/**
 * Aggregate result of running the entire pipeline.
 */
struct ValidationResult {
    ValidationStatus status {ValidationStatus::Passed};
    std::vector<ValidationError> errors;

    bool ok() const noexcept { return status == ValidationStatus::Passed; }

    void addError(ValidationError e) {
        status = ValidationStatus::Failed;
        errors.emplace_back(std::move(e));
    }

    std::string toString() const {
        std::ostringstream oss;
        switch (status) {
            case ValidationStatus::Passed: oss << "PASSED"; break;
            case ValidationStatus::Failed: oss << "FAILED"; break;
            case ValidationStatus::Skipped: oss << "SKIPPED"; break;
        }
        for (const auto& err : errors) {
            oss << "\n  [" << err.code << "] " << err.message;
        }
        return oss.str();
    }
};

/**
 * ValidationContext encapsulates all information that validators require.
 * It is intentionally immutable to prevent validators from leaking state.
 */
class ValidationContext {
public:
    ValidationContext(std::shared_ptr<const CommandEnvelope> command,
                      std::shared_ptr<const TenantProfile> tenant,
                      PolicyService* policySvc)
        : command_(std::move(command)),
          tenant_(std::move(tenant)),
          policyService_(policySvc)
    {}

    [[nodiscard]] const CommandEnvelope& command() const noexcept { return *command_; }
    [[nodiscard]] const TenantProfile& tenant()  const noexcept { return *tenant_; }
    [[nodiscard]] PolicyService&        policy() const noexcept { return *policyService_; }

private:
    std::shared_ptr<const CommandEnvelope> command_;
    std::shared_ptr<const TenantProfile>   tenant_;
    PolicyService*                         policyService_;
};

// --------------------------------------------------
// Chain-of-Responsibility base class
// --------------------------------------------------
class Validator : public std::enable_shared_from_this<Validator> {
public:
    virtual ~Validator() = default;

    /**
     * Validate current context and, if successful, forward to next validator.
     * Returns a combined ValidationResult.
     */
    ValidationResult validate(const ValidationContext& ctx) {
        ValidationResult result = doValidate(ctx);

        if (!result.ok() || !next_) {
            // Either failed or this is the tail of the chain.
            return result;
        }

        ValidationResult nextResult = next_->validate(ctx);
        // merge results
        result.errors.insert(result.errors.end(),
                             std::make_move_iterator(nextResult.errors.begin()),
                             std::make_move_iterator(nextResult.errors.end()));
        result.status =
            (result.status == ValidationStatus::Passed && nextResult.status == ValidationStatus::Passed)
            ? ValidationStatus::Passed
            : ValidationStatus::Failed;
        return result;
    }

    /**
     * Append a validator to the chain and return the head (this).
     */
    std::shared_ptr<Validator> setNext(std::shared_ptr<Validator> next) {
        next_ = std::move(next);
        return shared_from_this();
    }

protected:
    // Derived classes implement actual logic here.
    virtual ValidationResult doValidate(const ValidationContext& ctx) = 0;

private:
    std::shared_ptr<Validator> next_;
};

// --------------------------------------------------
// Concrete Validators
// --------------------------------------------------

/**
 * AuthorizationValidator ensures that the caller is allowed to execute the command.
 */
class AuthorizationValidator final : public Validator {
protected:
    ValidationResult doValidate(const ValidationContext& ctx) override;
};

/**
 * QuotaValidator enforces tenant quota limitations.
 */
class QuotaValidator final : public Validator {
protected:
    ValidationResult doValidate(const ValidationContext& ctx) override;
};

/**
 * SLAValidator validates that requested operation doesn't break SLA restrictions.
 */
class SLAValidator final : public Validator {
protected:
    ValidationResult doValidate(const ValidationContext& ctx) override;
};

/**
 * ComplianceValidator ensures the command meets compliance policies (e.g., PCI-DSS).
 */
class ComplianceValidator final : public Validator {
protected:
    ValidationResult doValidate(const ValidationContext& ctx) override;
};

// --------------------------------------------------
// Validator Implementations (pseudo-business logic)
// --------------------------------------------------

namespace {

/**
 * Dummy helpers mimicking system services.
 */
bool userHasPermission(const CommandEnvelope& cmd, const TenantProfile& tenant);
bool quotaWillBeExceeded(const CommandEnvelope& cmd, const TenantProfile& tenant);
bool slaViolationDetected(const CommandEnvelope& cmd, PolicyService& svc);
std::vector<std::string> complianceViolations(const CommandEnvelope& cmd, PolicyService& svc);

} // anonymous namespace

ValidationResult AuthorizationValidator::doValidate(const ValidationContext& ctx) {
    ValidationResult res;

    if (!userHasPermission(ctx.command(), ctx.tenant())) {
        res.addError({"AUTHZ_DENIED",
                      "User is not authorized to perform requested operation."});
    }
    return res;
}

ValidationResult QuotaValidator::doValidate(const ValidationContext& ctx) {
    ValidationResult res;

    if (quotaWillBeExceeded(ctx.command(), ctx.tenant())) {
        res.addError({"QUOTA_EXCEEDED",
                      "Tenant quota will be exceeded by executing this command."});
    }
    return res;
}

ValidationResult SLAValidator::doValidate(const ValidationContext& ctx) {
    ValidationResult res;
    if (slaViolationDetected(ctx.command(), ctx.policy())) {
        res.addError({"SLA_BLOCK",
                      "Requested action would violate the tenant's Service Level Agreement."});
    }
    return res;
}

ValidationResult ComplianceValidator::doValidate(const ValidationContext& ctx) {
    ValidationResult res;
    auto violations = complianceViolations(ctx.command(), ctx.policy());
    for (auto& v : violations) {
        res.addError({"COMPLIANCE_VIOLATION", v});
    }
    return res;
}

// --------------------------------------------------
// Validation Pipeline builder (thread-safe singleton)
// --------------------------------------------------

class ValidationPipeline {
public:
    static ValidationPipeline& instance() {
        static ValidationPipeline pipeline;
        return pipeline;
    }

    ValidationResult run(const ValidationContext& ctx) {
        // Lazily build chain once, afterwards re-use it.
        std::call_once(chainOnceFlag_, [this]() { buildChain(); });
        std::shared_lock lock(chainMutex_);
        return head_->validate(ctx);
    }

private:
    ValidationPipeline()  = default;
    ~ValidationPipeline() = default;

    void buildChain() {
        std::unique_lock lock(chainMutex_);
        head_ = std::make_shared<QuotaValidator>();
        head_
            ->setNext(std::make_shared<AuthorizationValidator>())
            ->setNext(std::make_shared<SLAValidator>())
            ->setNext(std::make_shared<ComplianceValidator>());
    }

    std::shared_ptr<Validator> head_;
    std::shared_mutex          chainMutex_;
    std::once_flag             chainOnceFlag_;
};

// --------------------------------------------------
// Public API
// --------------------------------------------------

/**
 * Validate a command within the given orchestration context.
 *
 * Throws std::runtime_error if validation fails.
 */
void validateCommand(const std::shared_ptr<CommandEnvelope>& cmd,
                     const std::shared_ptr<TenantProfile>& tenant,
                     PolicyService* policyService)
{
    ValidationContext ctx(cmd, tenant, policyService);
    ValidationResult result = ValidationPipeline::instance().run(ctx);

    if (!result.ok()) {
        utils::log::error("Validation failed for command {}: {}",
                          /*cmd->id*/ "UNKNOWN",
                          result.toString());
        throw std::runtime_error(result.toString());
    }

    utils::log::info("Validation succeeded for command {}", /*cmd->id*/ "UNKNOWN");
}

// --------------------------------------------------
// ------------- Dummy helper implementations -------
// --------------------------------------------------

namespace {

bool userHasPermission(const CommandEnvelope&, const TenantProfile&) {
    // TODO: integrate with RBAC service
    return true;
}
bool quotaWillBeExceeded(const CommandEnvelope&, const TenantProfile&) {
    // TODO: integrate with Billing service
    return false;
}
bool slaViolationDetected(const CommandEnvelope&, PolicyService&) {
    // TODO: integrate with SLA engine
    return false;
}
std::vector<std::string> complianceViolations(const CommandEnvelope&, PolicyService&) {
    // TODO: integrate with Compliance module
    return {};
}

} // anonymous namespace

} // namespace fortiledger360::orchestration