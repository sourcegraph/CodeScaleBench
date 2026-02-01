#pragma once
/***************************************************************************************************
 *  File:         authentication_handler.h
 *  Project:      FortiLedger360 – Enterprise Security Suite
 *  Component:    Orchestration :: Chain-of-Responsibility Handlers
 *
 *  Description:
 *      The AuthenticationHandler is the first link in the orchestration pipeline that every
 *      incoming command traverses. It validates the caller’s credentials (JWT, mutual-TLS client
 *      cert, API key, etc.) and enriches the CommandContext with an AuthContext that is consumed by
 *      downstream business logic. The handler is implemented as a classic Chain-of-Responsibility
 *      link: upon successful authentication it forwards the request to the next handler, otherwise
 *      it raises an AuthenticationException or returns false (depending on the consuming workflow).
 *
 *  Notes:
 *      • Thread-safe: designed to be shared across worker threads inside a stateless micro-service.
 *      • Hot-swappable: public UpdateTokenValidator() allows live rotation of signing keys /
 *        certificates without a process restart.
 *      • Lightweight metrics counters facilitate integration with the platform’s Prom-exporter.
 *
 *  Copyright:
 *      © 2023-2024 FortiLedger360 Corp. – All rights reserved.
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>

namespace fortiledger360 {

// ──────────────────────────────────────────────────────────────────────────────
// Forward Declarations (cross-layer, to keep header self-contained)
// ──────────────────────────────────────────────────────────────────────────────
namespace domain
{
    class CommandContext;   // Rich, immutable request envelope propagated by the pipeline.
    struct AuthContext;     // Normalized authentication & authorization artefacts.
} // namespace domain

namespace security
{
    // Strategy interface implemented by concrete validators (JWT, mTLS, API-Key, …).
    class ITokenValidator;
} // namespace security

namespace infra
{
    class ILogger;          // Thin wrapper around structured-logging backend.
} // namespace infra

// ──────────────────────────────────────────────────────────────────────────────
// Orchestration Layer
// ──────────────────────────────────────────────────────────────────────────────
namespace orchestration
{

// Base Chain-of-Responsibility contract. Other handlers (rate-limiter, quota checker,
// SLA transformer, etc.) derive from the same interface.
class IHandler
{
public:
    virtual ~IHandler() = default;

    // Returns true if the command has been handled. When returning false, the caller is
    // expected to stop traversal and surface an error to API‐layer.
    virtual bool Handle(const domain::CommandContext& ctx) = 0;

    // Sets the next handler in the chain. Thread-unsafe by design: the chain is assumed
    // to be built during service start-up.
    virtual void SetNext(std::shared_ptr<IHandler> next) = 0;
};

// Raised when authentication irrevocably fails (e.g., expired cert, tampered JWT,
// missing signature, etc.).
class AuthenticationException final : public std::runtime_error
{
public:
    explicit AuthenticationException(const std::string& msg)
        : std::runtime_error("Authentication failure: " + msg)
    {}
};

// Concrete authentication gatekeeper.
class AuthenticationHandler final : public IHandler,
                                    public std::enable_shared_from_this<AuthenticationHandler>
{
public:
    // Basic counters – scraped by Prometheus-compatible exporter.
    struct Metrics
    {
        std::atomic<uint64_t> tokens_validated{0};
        std::atomic<uint64_t> tokens_rejected{0};

        void Reset() noexcept
        {
            tokens_validated.store(0, std::memory_order_relaxed);
            tokens_rejected.store(0, std::memory_order_relaxed);
        }
    };

    // DI-friendly ctor. nullptr arguments will throw std::invalid_argument.
    AuthenticationHandler(std::shared_ptr<security::ITokenValidator> tokenValidator,
                          std::shared_ptr<infra::ILogger>             logger)
        : _tokenValidator(std::move(tokenValidator))
        , _logger(std::move(logger))
    {
        if (!_tokenValidator || !_logger)
        {
            throw std::invalid_argument(
                "AuthenticationHandler – tokenValidator and logger must not be nullptr");
        }
    }

    // IHandler API (thread-safe).
    bool Handle(const domain::CommandContext& ctx) override;
    void SetNext(std::shared_ptr<IHandler> next) override
    {
        _nextHandler = std::move(next);
    }

    // Snapshot copy – uses relaxed ordering (good enough for metrics).
    [[nodiscard]] Metrics GetMetricsSnapshot() const
    {
        return _metrics;
    }

    // Hot-swap signing keys / trust-stores at runtime.
    void UpdateTokenValidator(std::shared_ptr<security::ITokenValidator> validator)
    {
        if (!validator) { throw std::invalid_argument("New validator must not be nullptr"); }
        std::unique_lock lock(_mutex);
        _tokenValidator = std::move(validator);
    }

private:
    domain::AuthContext PerformAuthentication(const domain::CommandContext& ctx);
    void                LogAudit(const domain::CommandContext& ctx,
                                 const domain::AuthContext&    authCtx,
                                 bool                         success) const;

    mutable std::shared_mutex                  _mutex;
    std::shared_ptr<security::ITokenValidator> _tokenValidator;  // Guarded by _mutex.
    std::shared_ptr<infra::ILogger>            _logger;
    std::shared_ptr<IHandler>                  _nextHandler;
    Metrics                                    _metrics;
};

// ------------------------------------------------------------------------------------------------
// Inline Implementations
// ------------------------------------------------------------------------------------------------
inline bool AuthenticationHandler::Handle(const domain::CommandContext& ctx)
{
    // 1) Authenticate
    domain::AuthContext authCtx;
    bool                success = false;
    try
    {
        authCtx = PerformAuthentication(ctx);
        success  = true;
        ++_metrics.tokens_validated;
    }
    catch (const AuthenticationException&)
    {
        ++_metrics.tokens_rejected;
        LogAudit(ctx, authCtx, /*success=*/false);
        // Bubble up – higher layer will translate to 401/403.
        throw;
    }

    LogAudit(ctx, authCtx, /*success=*/true);

    // 2) Forward to next handler if present
    if (_nextHandler)
    {
        return _nextHandler->Handle(ctx);
    }

    // Leaf handler – nothing else to do, command considered handled.
    return true;
}

inline domain::AuthContext
AuthenticationHandler::PerformAuthentication(const domain::CommandContext& ctx)
{
    std::shared_ptr<security::ITokenValidator> validatorSnapshot;
    {
        std::shared_lock lock(_mutex);
        validatorSnapshot = _tokenValidator;
    }

    // Defensive: should never happen thanks to ctor & UpdateTokenValidator checks.
    if (!validatorSnapshot)
    {
        throw AuthenticationException("TokenValidator is not configured");
    }

    // validatorSnapshot may throw ValidationError; we convert to AuthenticationException
    // to maintain orchestration-level abstraction.
    if (auto authCtxOpt = validatorSnapshot->Validate(ctx); authCtxOpt.has_value())
    {
        return authCtxOpt.value();
    }

    throw AuthenticationException("Invalid or missing credentials");
}

inline void AuthenticationHandler::LogAudit(const domain::CommandContext& ctx,
                                            const domain::AuthContext&    authCtx,
                                            bool                         success) const
{
    // Compose structured log record.
    std::ostringstream oss;
    oss << "tenant=" << ctx.TenantId()
        << " subject=" << authCtx.Subject()
        << " trace=" << ctx.TraceId()
        << " success=" << std::boolalpha << success;

    if (success)
    {
        _logger->Info("AUTH_PASS", oss.str());
    }
    else
    {
        _logger->Warn("AUTH_FAIL", oss.str());
    }
}

} // namespace orchestration
} // namespace fortiledger360