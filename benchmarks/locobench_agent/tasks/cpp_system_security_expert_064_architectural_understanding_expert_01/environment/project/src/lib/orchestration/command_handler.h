```cpp
#pragma once
/****************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File:        FortiLedger360/src/lib/orchestration/command_handler.h
 *  Description: Generic command–dispatching pipeline that wires the Event-Bus layer
 *               with the concrete service–mesh executors. The handler supports:
 *                  • Pluggable middleware (Chain-of-Responsibility)
 *                  • Runtime registration of command executors (Command-Pattern)
 *                  • Sync / async execution models with basic fault-tolerance
 *                  • Thread-safe registration & dispatch
 *
 *  Copyright
 *  ---------
 *  (c) 2023-2024 FortiLedger360 Inc. — All rights reserved.
 ****************************************************************************************/

#include <any>
#include <atomic>
#include <chrono>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <typeindex>
#include <unordered_map>
#include <utility>
#include <vector>

#ifndef FORTILEDGER_DISABLE_SPDLOG
    #include <spdlog/spdlog.h>
    #define FL360_LOG_ERROR(...)   spdlog::error(__VA_ARGS__)
    #define FL360_LOG_INFO(...)    spdlog::info(__VA_ARGS__)
#else
    #define FL360_LOG_ERROR(...)   (void)0
    #define FL360_LOG_INFO(...)    (void)0
#endif

namespace fortiledger::orchestration
{

//---------------------------------------------------------------------------------------------------------------------
// Domain-agnostic aliases & helpers
//---------------------------------------------------------------------------------------------------------------------
using Timestamp = std::chrono::system_clock::time_point;

/**
 * Lightweight metadata that accompanies every command travelling through the platform.
 */
struct CommandMetadata
{
    std::string command_id;       // Correlates retries / duplicates across services
    std::string tenant_id;        // Multi-tenant awareness
    Timestamp    created_at;
    std::string correlation_id;   // Tracing (Jaeger / Zipkin / etc.)
};

/**
 * Formal contract for every command in the platform. Concrete commands SHOULD inherit
 * from this interface and MUST remain trivially-copyable (or at least movable).
 */
class ICommand
{
public:
    virtual ~ICommand() = default;

    /**
     * Returns the immutable metadata associated with the command.
     */
    virtual const CommandMetadata& metadata() const noexcept = 0;

    /**
     * Human-readable identifier — mostly used in logs / metrics.
     */
    virtual std::string name() const = 0;
};

//---------------------------------------------------------------------------------------------------------------------
// Command execution life-cycle helpers
//---------------------------------------------------------------------------------------------------------------------
enum class CommandStatus
{
    Completed,
    Failed,
    Unauthorized,
    Invalid,
    Throttled
};

struct CommandResult
{
    CommandStatus status { CommandStatus::Completed };
    std::string   message;
};

//---------------------------------------------------------------------------------------------------------------------
// Middleware — Chain-of-Responsibility
//---------------------------------------------------------------------------------------------------------------------

/**
 * Mutable context shared by all stages (middleware + executor) in the pipeline.
 * Acts as a blackboard that allows decoupled stages to communicate.
 */
class CommandContext
{
public:
    explicit CommandContext(std::shared_ptr<ICommand> cmd)
        : command_(std::move(cmd))
    {}

    std::shared_ptr<ICommand> command() const noexcept { return command_; }

    template <typename T>
    void set(const std::string& key, T&& value)
    {
        std::unique_lock lock(m_);
        data_[key] = std::any(std::forward<T>(value));
    }

    template <typename T>
    T get(const std::string& key) const
    {
        std::shared_lock lock(m_);
        const auto it = data_.find(key);
        if (it == data_.end())
        {
            throw std::out_of_range("CommandContext: key '" + key + "' not found.");
        }
        return std::any_cast<T>(it->second);
    }

    bool contains(const std::string& key) const
    {
        std::shared_lock lock(m_);
        return data_.count(key) > 0;
    }

private:
    std::shared_ptr<ICommand>              command_;
    std::unordered_map<std::string, std::any> data_;
    mutable std::shared_mutex              m_;
};

/**
 * Single step in the validation/authorization/throttling pipeline.
 *
 * Implementations SHOULD:
 *   • Return `false` to short-circuit the pipeline (e.g., access denied).
 *   • Throw  exceptions on unrecoverable errors (they are caught & transformed into
 *     CommandResult by the handler).
 */
class ICommandMiddleware
{
public:
    virtual ~ICommandMiddleware() = default;
    virtual bool Handle(CommandContext& ctx) = 0;
};

using MiddlewarePtr = std::shared_ptr<ICommandMiddleware>;

//---------------------------------------------------------------------------------------------------------------------
// CommandHandler — heart of the orchestration layer
//---------------------------------------------------------------------------------------------------------------------

/**
 * Thread-safe, pluggable dispatcher that receives high-level commands and routes
 * them through middleware and into their concrete executors.
 *
 * Typical usage:
 *   auto handler = std::make_shared<CommandHandler>();
 *   handler->RegisterMiddleware(std::make_shared<AuthZMiddleware>());
 *   handler->RegisterExecutor<InitiateSecurityScanCmd>([](auto cmd, auto& ctx) { ... });
 *   handler->DispatchAsync(std::make_shared<InitiateSecurityScanCmd>(...));
 */
class CommandHandler : public std::enable_shared_from_this<CommandHandler>
{
public:
    CommandHandler()  = default;
    ~CommandHandler() = default;
    CommandHandler(const CommandHandler&)            = delete;
    CommandHandler& operator=(const CommandHandler&) = delete;

    //---------------------------------------------------------------------
    // Executor registration
    //---------------------------------------------------------------------
    template <typename CommandT>
    using ExecutorFunc = std::function<CommandResult(const std::shared_ptr<CommandT>&, CommandContext&)>;

    /**
     * Registers a concrete executor for a given Command-type.
     * Thread-safe and idempotent per CommandT.
     *
     * Throws: std::logic_error when an executor is already registered.
     */
    template <typename CommandT>
    void RegisterExecutor(ExecutorFunc<CommandT> executor);

    //---------------------------------------------------------------------
    // Middleware registration
    //---------------------------------------------------------------------
    void RegisterMiddleware(MiddlewarePtr middleware);

    //---------------------------------------------------------------------
    // Dispatch APIs
    //---------------------------------------------------------------------
    [[nodiscard]]
    CommandResult Dispatch(const std::shared_ptr<ICommand>& command);

    [[nodiscard]]
    std::future<CommandResult> DispatchAsync(const std::shared_ptr<ICommand>& command);

private:
    //---------------------------------------------------------------------
    // Internal type erasure for executors
    //---------------------------------------------------------------------
    struct IExecutorWrapper
    {
        virtual ~IExecutorWrapper() = default;
        virtual CommandResult Execute(const std::shared_ptr<ICommand>& cmd,
                                      CommandContext&                  ctx) = 0;
    };

    template <typename CommandT>
    struct ExecutorWrapper final : IExecutorWrapper
    {
        explicit ExecutorWrapper(ExecutorFunc<CommandT> fn)
            : fn_(std::move(fn))
        {}

        CommandResult Execute(const std::shared_ptr<ICommand>& cmd,
                              CommandContext&                  ctx) override
        {
            auto concrete = std::dynamic_pointer_cast<CommandT>(cmd);
            if (!concrete)
                throw std::bad_cast();

            return fn_(concrete, ctx);
        }

        ExecutorFunc<CommandT> fn_;
    };

    //---------------------------------------------------------------------
    // Data members
    //---------------------------------------------------------------------
    std::unordered_map<std::type_index, std::shared_ptr<IExecutorWrapper>> executors_;
    std::vector<MiddlewarePtr>                                             middleware_pipeline_;
    mutable std::mutex                                                     m_;
};

//=====================================================================================================================
//  Implementation  (header-only for ease of integration)
//=====================================================================================================================

template <typename CommandT>
void CommandHandler::RegisterExecutor(ExecutorFunc<CommandT> executor)
{
    if (!executor)
        throw std::invalid_argument("CommandHandler::RegisterExecutor – executor is nullptr.");

    std::lock_guard lock(m_);
    const std::type_index key(typeid(CommandT));

    if (executors_.contains(key))
        throw std::logic_error("CommandHandler::RegisterExecutor – executor already registered.");

    executors_[key] = std::make_shared<ExecutorWrapper<CommandT>>(std::move(executor));

    FL360_LOG_INFO("Executor registered for command type: {}", key.name());
}

inline void CommandHandler::RegisterMiddleware(MiddlewarePtr middleware)
{
    if (!middleware)
        throw std::invalid_argument("CommandHandler::RegisterMiddleware – middleware is nullptr.");

    std::lock_guard lock(m_);
    middleware_pipeline_.push_back(std::move(middleware));
}

inline CommandResult CommandHandler::Dispatch(const std::shared_ptr<ICommand>& command)
{
    if (!command)
        throw std::invalid_argument("CommandHandler::Dispatch – command is nullptr.");

    CommandContext ctx(command);

    // 1) Chain-of-Responsibility: middleware pipeline
    for (const auto& mw : middleware_pipeline_)
    {
        bool proceed = false;
        try
        {
            proceed = mw->Handle(ctx);
        }
        catch (const std::exception& ex)
        {
            FL360_LOG_ERROR("Middleware [{}] threw exception: {}", typeid(*mw).name(), ex.what());
            return { CommandStatus::Failed, ex.what() };
        }

        if (!proceed)
        {
            return { CommandStatus::Failed, "Middleware aborted execution." };
        }
    }

    // 2) Locate executor
    std::shared_ptr<IExecutorWrapper> executor;
    {
        std::lock_guard lock(m_);
        const std::type_index key(typeid(*command));
        const auto            it = executors_.find(key);
        if (it == executors_.end())
        {
            return { CommandStatus::Failed,
                     "No executor registered for command type: " + std::string(key.name()) };
        }
        executor = it->second;
    }

    // 3) Execute
    try
    {
        return executor->Execute(command, ctx);
    }
    catch (const std::exception& ex)
    {
        FL360_LOG_ERROR("Executor for [{}] threw exception: {}", command->name(), ex.what());
        return { CommandStatus::Failed, ex.what() };
    }
}

inline std::future<CommandResult> CommandHandler::DispatchAsync(const std::shared_ptr<ICommand>& command)
{
    // The captured shared_ptr (self) guarantees the handler's lifetime for the async task.
    auto self = shared_from_this();
    return std::async(std::launch::async, [self, command] { return self->Dispatch(command); });
}

} // namespace fortiledger::orchestration
```