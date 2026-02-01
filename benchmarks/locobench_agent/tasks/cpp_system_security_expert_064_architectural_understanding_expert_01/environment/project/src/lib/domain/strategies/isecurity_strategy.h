#pragma once
/******************************************************************************
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 * File:        isecurity_strategy.h
 * Created:     2024-06-10
 * License:     Proprietary – FortiLedger360 Inc. – All Rights Reserved.
 *
 * Description:
 *   Contract for pluggable, run-time selectable security strategies that
 *   govern how a tenant’s security posture is enforced.  The Strategy Pattern
 *   lets the platform swap concrete implementations (e.g. pay-as-you-go deep
 *   scans vs. continuous scans) without recompilation or service interruption.
 *
 *   Domain-layer services accept a std::unique_ptr<ISecurityStrategy> that is
 *   resolved by a factory based on the tenant’s subscription, compliance
 *   profile, and SLA requirements.
 *
 *   NOTE:  This is a pure interface (a.k.a. “ABC” – Abstract Base Class).  It
 *   contains no implementation logic so that build dependencies stay minimal
 *   and compilation units remain decoupled.
 ******************************************************************************/

#include <chrono>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_map>
#include <vector>

namespace fl360::domain
{
    // Forward declaration to avoid dragging the whole event model into the
    // header.  Concrete strategy implementations will include the real type.
    struct SecurityEvent;

    /**
     * @brief Run-time contract for security posture strategies.
     *
     * A concrete strategy is expected to be:
     *   • Stateless  – or at least not maintain tenant-specific state across
     *                 instances (state is kept in the persistence layer).
     *   • Exception-safe – it must never throw beyond its public boundary.
     *   • Thread-safe – domain services fan-out work across workers.
     */
    class ISecurityStrategy
    {
    public:
        /**
         * @brief Contextual details about the command or action currently
         *        under evaluation.  A cheap, by-value object.
         */
        struct CommandContext
        {
            std::string_view                     tenantId;       // canonical UUID/GUID
            std::string_view                     command;        // e.g. “InitiateSecurityScan”
            std::string_view                     correlationId;  // tracing / observability
            std::chrono::system_clock::time_point timestamp;    // wall-clock time
            std::unordered_map<std::string, std::string> metadata; // opaque kv-bag (may be empty)
        };

        virtual ~ISecurityStrategy() noexcept = default;

        /**
         * @return Short human-readable identifier (logging / dashboards).
         */
        [[nodiscard]] virtual std::string_view name() const noexcept = 0;

        /**
         * Runs pre-flight authorization and compliance checks.
         *
         * @param ctx Current command context.
         * @return std::error_code – `{}`
         *         when allowed; a domain-specific error otherwise.
         *
         * The method MUST be noexcept; recoverable issues are reported through
         * std::error_code.  The concrete strategy decides whether or not to
         * log, rate-limit, or gate the request according to its own rules.
         */
        [[nodiscard]] virtual std::error_code authorize(
            const CommandContext& ctx) const noexcept = 0;

        /**
         * Applies the strategy by producing domain events to be dispatched to
         * the Event Bus.  The caller is responsible for publishing the events
         * transactionally once this method returns.
         *
         * @note  Implementations are encouraged to keep hard work (I/O,
         *        cryptography, …) out of this call and instead delegate heavy
         *        tasks to worker services through events.
         *
         * @throws (never)  – must not propagate exceptions.
         */
        [[nodiscard]] virtual std::vector<SecurityEvent> enforce(
            const CommandContext& ctx) = 0;

        /**
         * Heart-beat hook invoked by the scheduler every N seconds.  Allows
         * the strategy to emit scheduled or catch-up events (e.g. overdue
         * follow-up scan, SLA enforcement reminder).
         *
         * @param now        Monotonic reference time passed by the scheduler.
         * @param eventSink  Safe callback to push new events back to the bus.
         */
        virtual void onTimerTick(
            std::chrono::system_clock::time_point now,
            const std::function<void(SecurityEvent&&)>& eventSink) = 0;

        /**
         * Polymorphic deep-copy.  Needed by factories that cache prototypes
         * and clone per tenant for isolation.
         *
         * @return Ownership of a new, identical strategy instance.
         */
        [[nodiscard]] virtual std::unique_ptr<ISecurityStrategy> clone() const = 0;
    };

} // namespace fl360::domain