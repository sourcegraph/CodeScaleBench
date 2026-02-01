#pragma once
/**
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 * Orchestration :: ComplianceHandler
 *
 * The compliance handler sits in the Chain-of-Responsibility pipeline and
 * blocks or allows commands based on tenant-specific regulatory policies.
 *
 * Copyright (c) FortiLedger360
 */

#include <chrono>
#include <memory>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace FortiLedger360 {

// ---------------------------------------------------------------------------
// Orchestration-level primitives
// ---------------------------------------------------------------------------
namespace Orchestration {

/**
 * Lightweight context bag allowing handlers to exchange data without tight
 * coupling.  Thread-local lifetime; therefore no internal synchronisation.
 */
class OrchestrationContext
{
public:
    void set(const std::string& key, const std::string& value)
    {
        m_bag[key] = value;
    }

    bool has(const std::string& key) const noexcept
    {
        return m_bag.find(key) != m_bag.end();
    }

    const std::string& get(const std::string& key) const
    {
        return m_bag.at(key);
    }

private:
    std::unordered_map<std::string, std::string> m_bag;
};

/**
 * Generic command envelope emitted by the presentation layer.
 */
struct RequestCommand
{
    std::string                         tenantId;
    std::string                         commandName;
    std::string                         payload;        // e.g., JSON or CBOR
    std::chrono::system_clock::time_point timestamp
        { std::chrono::system_clock::now() };
    std::string                         correlationId;
};

} // namespace Orchestration

// ---------------------------------------------------------------------------
// Domain-level primitives
// ---------------------------------------------------------------------------
namespace Domain {

/**
 * Describes a policy that the incoming request is violating.
 */
struct PolicyViolation
{
    std::string policyId;
    std::string description;
    std::string severity; // INFO / LOW / MEDIUM / HIGH / CRITICAL
};

/**
 * Abstract policy engine implemented in the domain layer.
 */
class PolicyEngine
{
public:
    virtual ~PolicyEngine() = default;

    /**
     * Evaluates the supplied command and returns the list of violated policies.
     * An empty vector indicates full compliance.
     */
    virtual std::vector<PolicyViolation>
    evaluate(const Orchestration::RequestCommand& command) = 0;
};

} // namespace Domain

// ---------------------------------------------------------------------------
// Infrastructure-level primitives
// ---------------------------------------------------------------------------
namespace Infrastructure {

/**
 * Audit sink for compliance decisions.
 */
class AuditLogger
{
public:
    virtual ~AuditLogger() = default;

    virtual void writeComplianceDecision(
        const std::string&                       tenantId,
        const std::string&                       commandName,
        const std::string&                       correlationId,
        bool                                     allowed,
        const std::vector<Domain::PolicyViolation>& violations,
        std::chrono::system_clock::time_point    ts) = 0;
};

} // namespace Infrastructure

// ---------------------------------------------------------------------------
// Orchestration :: Handlers
// ---------------------------------------------------------------------------
namespace Orchestration::Handlers {

/**
 * Base interface for all handlers participating in the orchestration chain.
 */
class IRequestHandler
{
public:
    virtual ~IRequestHandler() = default;

    /**
     * Processes a request. Returns `true` when the request is allowed to
     * continue down the pipeline, or `false` when processing must be aborted.
     */
    virtual bool handle(const RequestCommand& command,
                        OrchestrationContext& context) = 0;

    /**
     * Appends the next handler and returns it, enabling fluent chains:
     *     handlerA->setNext(handlerB)->setNext(handlerC);
     */
    virtual std::shared_ptr<IRequestHandler>
    setNext(std::shared_ptr<IRequestHandler> next) = 0;
};

/**
 * Concrete compliance handler.
 *
 * This class is thread-safe and can be reused between requests.
 */
class ComplianceHandler final : public IRequestHandler,
                                public std::enable_shared_from_this<ComplianceHandler>
{
public:
    ComplianceHandler(std::shared_ptr<Domain::PolicyEngine>       policyEngine,
                      std::shared_ptr<Infrastructure::AuditLogger> auditLogger)
        : m_policyEngine(std::move(policyEngine))
        , m_auditLogger(std::move(auditLogger))
    {}

    // Non-copyable
    ComplianceHandler(const ComplianceHandler&)            = delete;
    ComplianceHandler& operator=(const ComplianceHandler&) = delete;

    // IRequestHandler --------------------------------------------------------
    bool handle(const RequestCommand& command,
                OrchestrationContext& context) override
    {
        std::vector<Domain::PolicyViolation> violations;
        const bool allowed = isCompliant(command, violations);

        logDecision(command, violations, allowed);

        if (!allowed)
        {
            // Early exit – command is blocked due to policy violations
            return false;
        }

        // Acquire the next handler under a shared lock and forward the request.
        std::shared_ptr<IRequestHandler> nextCopy;
        {
            std::shared_lock lock(m_chainMutex);
            nextCopy = m_next;
        }

        return nextCopy ? nextCopy->handle(command, context) : true;
    }

    std::shared_ptr<IRequestHandler>
    setNext(std::shared_ptr<IRequestHandler> next) override
    {
        std::unique_lock lock(m_chainMutex);
        m_next = std::move(next);
        return m_next;
    }

private:
    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------
    bool isCompliant(const RequestCommand&               command,
                     std::vector<Domain::PolicyViolation>& outViolations) const
    {
        if (!m_policyEngine)
        {
            // No policy engine configured – default to allow.
            return true;
        }

        try
        {
            outViolations = m_policyEngine->evaluate(command);
        }
        catch (const std::exception& ex)
        {
            // Fail-open or fail-close is subject to business requirements.
            // Here we opt for fail-close for maximum security.
            Domain::PolicyViolation runtimeError{
                "RuntimeError",
                ex.what(),
                "CRITICAL"
            };
            outViolations.emplace_back(std::move(runtimeError));
        }

        return outViolations.empty();
    }

    void logDecision(const RequestCommand&                 command,
                     const std::vector<Domain::PolicyViolation>& violations,
                     bool                                   allowed) const
    {
        if (!m_auditLogger)
            return;

        try
        {
            m_auditLogger->writeComplianceDecision(
                command.tenantId,
                command.commandName,
                command.correlationId,
                allowed,
                violations,
                command.timestamp);
        }
        catch (...)
        {
            // Swallow logging exceptions – we must never block main flow.
        }
    }

private:
    std::shared_ptr<Domain::PolicyEngine>        m_policyEngine;
    std::shared_ptr<Infrastructure::AuditLogger> m_auditLogger;

    mutable std::shared_mutex                    m_chainMutex;
    std::shared_ptr<IRequestHandler>             m_next;
};

} // namespace Orchestration::Handlers
} // namespace FortiLedger360