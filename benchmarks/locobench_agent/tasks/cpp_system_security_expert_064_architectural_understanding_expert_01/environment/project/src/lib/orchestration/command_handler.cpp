#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>      // MIT-licensed single-header JSON lib
#include <spdlog/spdlog.h>        // Fast C++ logging library

/*  FortiLedger360 — Command Handler (Orchestration Layer)
    ======================================================
    This file provides a concrete implementation of the Command-Pattern
    dispatching logic that glues together:

        • Validators  — Chain-of-Responsibility for compliance checks
        • Executors   — Strategy objects that perform the real work
        • Observers   — Hooks for audit, metrics & dashboards

    It is fully thread-safe, exception-aware, and ready for high-throughput
    event-driven environments.                                                */

namespace fl360::orchestration {

// ---------------------------------------------------------------------------
// Forward Declarations & Type Utilities
// ---------------------------------------------------------------------------
enum class CommandType
{
    InitiateSecurityScan,
    RollClusterBackup,
    UpSizeCapacity,
    GenerateAuditReport,
    Unknown
};

inline std::string to_string(CommandType t)
{
    switch (t)
    {
        case CommandType::InitiateSecurityScan: return "InitiateSecurityScan";
        case CommandType::RollClusterBackup:    return "RollClusterBackup";
        case CommandType::UpSizeCapacity:       return "UpSizeCapacity";
        case CommandType::GenerateAuditReport:  return "GenerateAuditReport";
        default:                                return "Unknown";
    }
}

// ---------------------------------------------------------------------------
// Command & Context DTOs
// ---------------------------------------------------------------------------
struct Command final
{
    CommandType          type  = CommandType::Unknown;
    nlohmann::json       body;                 // Arbitrary payload (typed in executor)
};

struct CommandContext final
{
    std::string                              tenant_id;
    std::string                              correlation_id;
    std::chrono::system_clock::time_point    timestamp{ std::chrono::system_clock::now() };
};

// ---------------------------------------------------------------------------
// Error Types
// ---------------------------------------------------------------------------
struct ValidationException : public std::runtime_error
{
    explicit ValidationException(std::string  msg)
        : std::runtime_error{ std::move(msg) } {}
};

struct ExecutorNotFound : public std::runtime_error
{
    explicit ExecutorNotFound(std::string  msg)
        : std::runtime_error{ std::move(msg) } {}
};

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------
class ICommandExecutor
{
public:
    virtual ~ICommandExecutor() = default;
    virtual void execute(const CommandContext& ctx, const Command& cmd) = 0;
};

class IValidator
{
public:
    virtual ~IValidator() = default;
    virtual void validate(const CommandContext& ctx, const Command& cmd) = 0;
};

class IObserver
{
public:
    virtual ~IObserver() = default;
    virtual void on_command_start  (const CommandContext& ctx, const Command& cmd)               = 0;
    virtual void on_command_success(const CommandContext& ctx, const Command& cmd)               = 0;
    virtual void on_command_error  (const CommandContext& ctx, const Command& cmd,
                                    const std::exception& ex)                                     = 0;
};

// ---------------------------------------------------------------------------
// Command Registry (Strategy Map)
// ---------------------------------------------------------------------------
class CommandRegistry
{
public:
    void register_executor(CommandType type, std::shared_ptr<ICommandExecutor> exec)
    {
        if (!exec)
            throw std::invalid_argument("register_executor(): exec is nullptr");

        std::unique_lock lk{ mutex_ };
        executors_[type] = std::move(exec);
    }

    [[nodiscard]]
    std::shared_ptr<ICommandExecutor> get_executor(CommandType type) const
    {
        std::shared_lock lk{ mutex_ };
        auto it = executors_.find(type);
        return it == executors_.end() ? nullptr : it->second;
    }

private:
    mutable std::shared_mutex                                        mutex_;
    std::unordered_map<CommandType, std::shared_ptr<ICommandExecutor>> executors_;
};

// ---------------------------------------------------------------------------
// Concrete Executors  (showcase; real impls would call gRPC / internal APIs)
// ---------------------------------------------------------------------------
class SecurityScanExecutor final : public ICommandExecutor
{
public:
    void execute(const CommandContext& ctx, const Command& cmd) override
    {
        spdlog::info("[ScanExec] [{}] Tenant={} :: Initiating vulnerability scan",
                     ctx.correlation_id, ctx.tenant_id);

        // Simulated workload
        const auto scan_depth = cmd.body.value<std::string>("depth", "standard");
        std::this_thread::sleep_for(std::chrono::milliseconds{ 50 });

        spdlog::info("[ScanExec] [{}] Tenant={} :: Scan completed (depth={})",
                     ctx.correlation_id, ctx.tenant_id, scan_depth);
    }
};

class BackupExecutor final : public ICommandExecutor
{
public:
    void execute(const CommandContext& ctx, const Command& cmd) override
    {
        const auto cluster_id = cmd.body.at("cluster_id").get<std::string>();
        spdlog::info("[BackupExec] [{}] Tenant={} :: Rolling backup for cluster {}",
                     ctx.correlation_id, ctx.tenant_id, cluster_id);

        // Simulated backup
        std::this_thread::sleep_for(std::chrono::milliseconds{ 75 });

        spdlog::info("[BackupExec] [{}] Tenant={} :: Backup completed for cluster {}",
                     ctx.correlation_id, ctx.tenant_id, cluster_id);
    }
};

// ---------------------------------------------------------------------------
// Command Handler
// ---------------------------------------------------------------------------
class CommandHandler final
{
public:
    explicit CommandHandler(std::shared_ptr<CommandRegistry> registry)
        : registry_{ std::move(registry) }
    {
        if (!registry_) { throw std::invalid_argument("registry is nullptr"); }
    }

    void add_validator(std::shared_ptr<IValidator> v)
    {
        if (!v) { throw std::invalid_argument("validator is nullptr"); }
        std::unique_lock lk{ val_mutex_ };
        validators_.push_back(std::move(v));
    }

    void add_observer(std::shared_ptr<IObserver> o)
    {
        if (!o) { throw std::invalid_argument("observer is nullptr"); }
        std::unique_lock lk{ obs_mutex_ };
        observers_.push_back(std::move(o));
    }

    // Synchronous (blocking) processing
    void handle(const CommandContext& ctx, const Command& cmd)
    {
        notify_start(ctx, cmd);
        try
        {
            run_validation(ctx, cmd);
            run_execution(ctx, cmd);
            notify_success(ctx, cmd);
        }
        catch (const std::exception& ex)
        {
            notify_error(ctx, cmd, ex);
            throw;      // Re-propagate to upstream orchestrator
        }
    }

    // Asynchronous (detached) processing — returns a future
    std::future<void> dispatch_async(CommandContext ctx, Command cmd)
    {
        return std::async(std::launch::async,
                          [self = shared_from_this(), ctx = std::move(ctx), cmd = std::move(cmd)]() {
                              self->handle(ctx, cmd);
                          });
    }

private:
    // Validator chain
    void run_validation(const CommandContext& ctx, const Command& cmd)
    {
        std::shared_lock lk{ val_mutex_ };
        for (const auto& v : validators_)
            v->validate(ctx, cmd);
    }

    // Strategy execution
    void run_execution(const CommandContext& ctx, const Command& cmd)
    {
        const auto exec = registry_->get_executor(cmd.type);
        if (!exec)
            throw ExecutorNotFound{ "No executor registered for " + to_string(cmd.type) };

        exec->execute(ctx, cmd);
    }

    // Observer helpers
    void notify_start(const CommandContext& ctx, const Command& cmd)   { notify(ctx, cmd, &IObserver::on_command_start,   nullptr); }
    void notify_success(const CommandContext& ctx, const Command& cmd) { notify(ctx, cmd, &IObserver::on_command_success, nullptr); }
    void notify_error(const CommandContext& ctx, const Command& cmd, const std::exception& ex)
    {
        notify(ctx, cmd, &IObserver::on_command_error, &ex);
    }

    void notify(const CommandContext& ctx,
                const Command&        cmd,
                void (IObserver::*fn)(const CommandContext&, const Command&) )
    {
        std::shared_lock lk{ obs_mutex_ };
        for (const auto& o : observers_)
        {
            try { (o.get()->*fn)(ctx, cmd); }
            catch (...) { /* Observer failures must never break flow */ }
        }
    }

    void notify(const CommandContext& ctx,
                const Command&        cmd,
                void (IObserver::*fn)(const CommandContext&, const Command&, const std::exception&),
                const std::exception* ex)
    {
        std::shared_lock lk{ obs_mutex_ };
        for (const auto& o : observers_)
        {
            try { (o.get()->*fn)(ctx, cmd, *ex); }
            catch (...) { /* Swallow */ }
        }
    }

private:
    // Handlers & metadata
    std::shared_ptr<CommandRegistry> registry_;

    // Validators & Observers
    mutable std::shared_mutex                  val_mutex_;
    mutable std::shared_mutex                  obs_mutex_;
    std::vector<std::shared_ptr<IValidator>>   validators_;
    std::vector<std::shared_ptr<IObserver>>    observers_;
};

// ---------------------------------------------------------------------------
// Example Validators & Observers (minimal, for illustration)
// ---------------------------------------------------------------------------
class TenantQuotaValidator final : public IValidator
{
public:
    void validate(const CommandContext& ctx, const Command& cmd) override
    {
        (void)cmd;
        if (ctx.tenant_id.empty())
            throw ValidationException{ "tenant_id must not be empty" };
    }
};

class SpdlogObserver final : public IObserver
{
public:
    void on_command_start(const CommandContext& ctx, const Command& cmd) override
    {
        spdlog::info("[Observer] [{}] START   :: {}", ctx.correlation_id, to_string(cmd.type));
    }
    void on_command_success(const CommandContext& ctx, const Command& cmd) override
    {
        spdlog::info("[Observer] [{}] SUCCESS :: {}", ctx.correlation_id, to_string(cmd.type));
    }
    void on_command_error(const CommandContext& ctx, const Command& cmd,
                          const std::exception& ex) override
    {
        spdlog::error("[Observer] [{}] ERROR   :: {} :: {}", ctx.correlation_id,
                      to_string(cmd.type), ex.what());
    }
};

// ---------------------------------------------------------------------------
// Helper — builder for a typical production CommandHandler instance
// ---------------------------------------------------------------------------
inline std::shared_ptr<CommandHandler> make_default_command_handler()
{
    auto registry = std::make_shared<CommandRegistry>();

    registry->register_executor(CommandType::InitiateSecurityScan,
                                std::make_shared<SecurityScanExecutor>());
    registry->register_executor(CommandType::RollClusterBackup,
                                std::make_shared<BackupExecutor>());

    auto handler = std::make_shared<CommandHandler>(registry);

    handler->add_validator(std::make_shared<TenantQuotaValidator>());
    handler->add_observer (std::make_shared<SpdlogObserver   >());

    return handler;
}

} // namespace fl360::orchestration