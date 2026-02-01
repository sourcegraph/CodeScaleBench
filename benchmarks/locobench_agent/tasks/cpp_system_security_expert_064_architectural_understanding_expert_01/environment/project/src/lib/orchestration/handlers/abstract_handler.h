/*
 * FortiLedger360 - Enterprise Security Suite
 * ------------------------------------------
 * File:    src/lib/orchestration/handlers/abstract_handler.h
 * License: Proprietary, FortiLedger Inc. All rights reserved.
 *
 * Abstraction for the Chain-of-Responsibility pipeline living in the
 * Orchestration layer.  Every high-level Command (e.g., “InitiateSecurityScan”)
 * travels through a series of concrete handlers—quota checks, SLA validation,
 * compliance guardrails, and audit book-keeping—before it is dispatched to the
 * Domain layer.  This header defines the canonical base-class that each handler
 * must derive from, ensuring uniform diagnostics, structured logging, and
 * thread-safe chaining.
 */

#pragma once

// STL
#include <atomic>
#include <chrono>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

// 3rd-party (header-only spdlog is bundled with FortiLedger360)
#include <spdlog/spdlog.h>

// Forward declarations to decouple headers and speed up compilation.
namespace fl360::domain {
class Command;
}

namespace fl360::orchestration {
class RequestContext;   // Contains tenant-id, authZ claims, correlation-id, etc.
}  // namespace fl360::orchestration

namespace fl360::orchestration::handlers {

/**
 * @brief   Aggregate information yielded by a handler execution.
 *
 * All concrete handlers must return one of three *terminal* states:
 *   • Accepted  –  Handler processed the command and consumed it.  Chain stops.
 *   • Rejected  –  Handler denies the command.  Chain stops.
 *   • Skipped   –  Handler did not take ownership. Chain continues.
 *
 * `metadata` allows handlers to enrich the result with contextual hints
 * (e.g., why an SLA failed) that can be surfaced by the presentation layer.
 */
struct HandlerResult
{
    enum class State : uint8_t
    {
        Accepted,
        Rejected,
        Skipped,
    };

    State                                   state      {State::Skipped};
    std::optional<std::string>              metadata;          // Human-readable note.
    std::chrono::steady_clock::duration     elapsed     {};    // Latency spent inside handler.

    [[nodiscard]] bool is_terminal() const noexcept
    {
        return state == State::Accepted || state == State::Rejected;
    }

    static HandlerResult accepted(std::string note = {});
    static HandlerResult rejected(std::string note = {});
    static HandlerResult skipped ();
};

/**
 * @brief   Non-allocating RAII helper that measures latency & auto-logs on exit.
 */
class ScopedDiagnostics final
{
public:
    explicit ScopedDiagnostics(const std::string& handlerName,
                               const std::string& correlationId) noexcept
    : _handlerName{handlerName}
    , _correlationId{correlationId}
    , _start{std::chrono::steady_clock::now()}
    {
        spdlog::trace("↪ [{}] Enter Handler: {}", _correlationId, _handlerName);
    }

    ScopedDiagnostics(const ScopedDiagnostics&)            = delete;
    ScopedDiagnostics& operator=(const ScopedDiagnostics&) = delete;

    ~ScopedDiagnostics() noexcept
    {
        const auto elapsed = std::chrono::steady_clock::now() - _start;
        spdlog::trace("↩ [{}] Exit Handler: {} ({} µs)",
                      _correlationId,
                      _handlerName,
                      std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count());
    }

    std::chrono::steady_clock::duration elapsed() const noexcept
    {
        return std::chrono::steady_clock::now() - _start;
    }

private:
    const std::string                       _handlerName;
    const std::string                       _correlationId;
    const std::chrono::steady_clock::time_point _start;
};

/**
 * @brief   Interface for Chain-of-Responsibility handlers.
 *
 * Handlers are intended to be thread-safe and stateless.  If internal state is
 * required (i.e., caching, circuit-breaking), favour lock-free primitives or
 * confine the state to the owning thread (see `fl360::executor::TaskWorker`).
 */
class AbstractHandler :
        public std::enable_shared_from_this<AbstractHandler>
{
public:
    using Ptr = std::shared_ptr<AbstractHandler>;

    virtual ~AbstractHandler() = default;

    /**
     * @brief   Handle a command. Concrete handlers must implement this.
     *
     * Implementations should call `next()->execute(...)` when they wish to
     * continue the chain. Failure to do so will terminate the chain.
     *
     * @param cmd   The immutable domain command.
     * @param ctx   Per-request context (auth, tenant, correlation, timeout).
     */
    [[nodiscard]]
    virtual HandlerResult handle(const domain::Command& cmd,
                                 orchestration::RequestContext& ctx) = 0;

    /**
     * @brief   Execute wrapper that provides diagnostics and chain management.
     *
     * Do not override this method—override `handle`.  This wrapper enforces
     * timing, structured logging, and failsafe error handling.
     */
    [[nodiscard]]
    HandlerResult execute(const domain::Command& cmd,
                          orchestration::RequestContext& ctx)
    {
        const ScopedDiagnostics diag{name(), ctx.correlation_id()};

        try
        {
            HandlerResult result = handle(cmd, ctx);
            result.elapsed       = diag.elapsed();

            if (!result.is_terminal() && _next)
            {
                return _next.load()->execute(cmd, ctx);
            }
            return result;
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[{}] Handler '{}' threw: {}", ctx.correlation_id(), name(), ex.what());
            // Propagate a rejection up the chain—clients may decide to retry.
            return HandlerResult::rejected(std::string{"Unhandled exception: "} + ex.what());
        }
        catch (...)
        {
            spdlog::error("[{}] Handler '{}' threw an unknown exception",
                          ctx.correlation_id(),
                          name());
            return HandlerResult::rejected("Unhandled non-std exception");
        }
    }

    /**
     * @brief   Atomically sets the next handler in the chain.
     *
     * The method returns `*this` to allow fluent pipeline composition:
     *
     *     auto pipeline = quota->set_next(sla)->set_next(audit);
     */
    Ptr set_next(Ptr next) noexcept
    {
        _next.store(std::move(next));
        return shared_from_this();
    }

    /**
     * @brief Retrieve the chain node that succeeds the current handler.
     */
    [[nodiscard]]
    Ptr next() const noexcept { return _next.load(); }

    /**
     * @brief Human-readable, static handler name. Used in logs & metrics.
     */
    [[nodiscard]]
    virtual const char* name() const noexcept = 0;

protected:
    AbstractHandler() = default;

private:
    std::atomic<Ptr> _next {nullptr};  // Single-writer, multi-reader – lock-free.
};

/*──────────────────────────── Helper Factories ──────────────────────────────*/

inline HandlerResult HandlerResult::accepted(std::string note)
{
    return HandlerResult{State::Accepted, std::move(note), {}};
}

inline HandlerResult HandlerResult::rejected(std::string note)
{
    return HandlerResult{State::Rejected, std::move(note), {}};
}

inline HandlerResult HandlerResult::skipped()
{
    return HandlerResult{State::Skipped,  std::nullopt,        {}};
}

}  // namespace fl360::orchestration::handlers