#ifndef FORTILEDGER360_SRC_LIB_DOMAIN_COMMANDS_BASE_COMMAND_H_
#define FORTILEDGER360_SRC_LIB_DOMAIN_COMMANDS_BASE_COMMANDS_BASE_COMMAND_H_

/*
 *  FortiLedger360 – Enterprise Security Suite
 *  ------------------------------------------
 *  Base Command Abstraction
 *
 *  Commands are the heart of the event–driven core.  Each concrete command
 *  captures a complete intent that will be executed by a downstream domain
 *  service.  This file defines the common contract, validation hooks, metadata,
 *  and (de)serialization helpers that every command must provide.
 *
 *  Author : FortiLedger360 Platform Team
 *  License: Proprietary – All Rights Reserved
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <memory>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>

#include <nlohmann/json.hpp>          // MIT-licensed single-header JSON library

// ===================================================================================
//  NAMESPACE HIERARCHY
// ===================================================================================
namespace fortiledger::domain::commands {

// ===================================================================================
//  EXCEPTIONS
// ===================================================================================

/**
 * CommandError – all command-layer errors funnel through this specialised
 * runtime_error allowing upper layers to catch & handle domain-specific issues.
 */
class CommandError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

// ===================================================================================
//  BASE COMMAND – CONTRACT
// ===================================================================================

/**
 * BaseCommand
 *
 *  Abstract interface implemented by every domain command (e.g.,
 *  InitiateSecurityScan, RollClusterBackup, etc.).
 *
 *  – Provides rich metadata (tenant-id, correlation-id, etc.) for tracing.
 *  – Supplies validation and (de)serialisation hooks.
 *  – Includes a small registry enabling dynamic reconstruction from JSON
 *    without string-based switch/case blocks scattered around the code base.
 */
class BaseCommand
{
public:
    // ---------------------------------------------------------------------------
    //  Type aliases & public data structures
    // ---------------------------------------------------------------------------

    /**
     * Metadata block attached to every command instance.
     */
    struct Metadata
    {
        std::string                                command_id;      // strong unique id for the command itself
        std::string                                correlation_id;  // id propagated through bounded context for tracing
        std::string                                tenant_id;       // multi-tenant isolation
        std::chrono::system_clock::time_point      created_at;      // command creation timestamp (UTC)
        std::size_t                                schema_version;  // payload schema version
    };

    using json    = nlohmann::json;
    using Creator = std::unique_ptr<BaseCommand>(*)(const json& payload, const Metadata&);

    // ---------------------------------------------------------------------------
    //  Construction / Destruction
    // ---------------------------------------------------------------------------

    // Explicit, metadata-aware c’tor
    explicit BaseCommand(Metadata meta);

    // Convenience c’tor (auto-generates command_id & created_at)
    explicit BaseCommand(std::string  tenant_id,
                         std::string  correlation_id = GenerateUUID(),
                         std::size_t  schema_version = 1);

    // Non-virtual because we opt-in to the rule-of-zero for move semantics
    virtual ~BaseCommand() = default;

    // ---------------------------------------------------------------------------
    //  Non-copyable, movable
    // ---------------------------------------------------------------------------
    BaseCommand(const BaseCommand&)            = delete;
    BaseCommand& operator=(const BaseCommand&) = delete;
    BaseCommand(BaseCommand&&)                 = default;
    BaseCommand& operator=(BaseCommand&&)      = default;

    // ---------------------------------------------------------------------------
    //  Introspection helpers
    // ---------------------------------------------------------------------------
    const Metadata& metadata() const noexcept { return meta_; }
    bool            executed() const noexcept { return executed_.load(std::memory_order_acquire); }

    // ---------------------------------------------------------------------------
    //  Core API – must be implemented by concrete commands
    // ---------------------------------------------------------------------------
    virtual std::string_view name() const noexcept = 0;  // "InitiateSecurityScan", etc.

    /**
     * validate()
     *   Pure virtual – Derived class must implement domain specific invariants.
     *   Throw CommandError on failure.
     */
    virtual void validate() const = 0;

    /**
     * payload_to_json / payload_from_json
     *   Derived class serialises only its payload (without metadata shell).
     */
    virtual json payload_to_json() const              = 0;
    virtual void payload_from_json(const json& json_) = 0;

    // ---------------------------------------------------------------------------
    //  Serialization helpers
    // ---------------------------------------------------------------------------
    json to_json() const;
    static std::unique_ptr<BaseCommand> FactoryFromJson(const json& root);

    // ---------------------------------------------------------------------------
    //  Idempotency helpers
    // ---------------------------------------------------------------------------
    void mark_executed();   // throw when called twice

    // ---------------------------------------------------------------------------
    //  Registry – dynamic reconstruction & open/closed principle
    // ---------------------------------------------------------------------------
    static void Register(std::string_view name, Creator creator);

protected:
    // ---------------------------------------------------------------------------
    //  UUID generation – header-only helper for simplicity
    // ---------------------------------------------------------------------------
    static std::string GenerateUUID();

private:
    // Fetch or create registry (Meyers singleton)
    static std::unordered_map<std::string, Creator>& Registry();

    // ---------------------------------------------------------------------------
    //  Instance data
    // ---------------------------------------------------------------------------
    Metadata            meta_;
    std::atomic_bool    executed_{false};
    mutable std::mutex  mutex_;    // guards any mutable state a subclass might introduce
};

// ===================================================================================
//  INLINE / HEADER-ONLY IMPLEMENTATION
// ===================================================================================

// ---------------------------------------------------------------------------
//  UUID – RFC-4122 v4 compliant-ish (pseudo-random)
// ---------------------------------------------------------------------------
inline std::string BaseCommand::GenerateUUID()
{
    static thread_local std::mt19937_64 rng{ std::random_device{}() };
    std::uniform_int_distribution<uint64_t> dist{ 0, std::numeric_limits<uint64_t>::max() };

    auto rand64 = [&] { return dist(rng); };

    uint64_t hi = rand64();
    uint64_t lo = rand64();

    // Set the four most significant bits of the 7th byte to 0100’b (version 4)
    hi &= 0xFFFFFFFFFFFF0FFFULL;
    hi |= 0x0000000000004000ULL;

    // Set the two most significant bits of the 9th byte to 10’b (variant 1)
    lo &= 0x3FFFFFFFFFFFFFFFULL;
    lo |= 0x8000000000000000ULL;

    std::ostringstream oss;
    oss << std::hex << std::setfill('0')
        << std::setw(8)  << (hi >> 32)
        << '-'
        << std::setw(4)  << ((hi >> 16) & 0xFFFFULL)
        << '-'
        << std::setw(4)  << (hi & 0xFFFFULL)
        << '-'
        << std::setw(4)  << (lo >> 48)
        << '-'
        << std::setw(12) << (lo & 0xFFFFFFFFFFFFULL);
    return oss.str();
}

// ---------------------------------------------------------------------------
//  Constructors
// ---------------------------------------------------------------------------
inline BaseCommand::BaseCommand(Metadata meta)
    : meta_{ std::move(meta) }
{}

inline BaseCommand::BaseCommand(std::string  tenant_id,
                                std::string  correlation_id,
                                std::size_t  schema_version)
    : meta_{ GenerateUUID(),
             std::move(correlation_id),
             std::move(tenant_id),
             std::chrono::system_clock::now(),
             schema_version }
{}

// ---------------------------------------------------------------------------
//  mark_executed – idempotency guard
// ---------------------------------------------------------------------------
inline void BaseCommand::mark_executed()
{
    bool expected = false;
    if (!executed_.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
        throw CommandError{ "Command already marked as executed: " + meta_.command_id };
}

// ---------------------------------------------------------------------------
//  Serialization
// ---------------------------------------------------------------------------
inline BaseCommand::json BaseCommand::to_json() const
{
    json root;
    root["name"] = std::string{ name() };

    root["metadata"] = {
        { "command_id",        meta_.command_id },
        { "correlation_id",    meta_.correlation_id },
        { "tenant_id",         meta_.tenant_id },
        { "created_at_epoch_ms",
          std::chrono::duration_cast<std::chrono::milliseconds>(
              meta_.created_at.time_since_epoch()).count()
        },
        { "schema_version",    meta_.schema_version }
    };

    root["payload"] = payload_to_json();
    return root;
}

// ---------------------------------------------------------------------------
//  Registry helpers
// ---------------------------------------------------------------------------
inline std::unordered_map<std::string, BaseCommand::Creator>& BaseCommand::Registry()
{
    static std::unordered_map<std::string, Creator> instance;
    return instance;
}

inline void BaseCommand::Register(std::string_view name, Creator creator)
{
    auto& reg = Registry();
    const auto [it, ok] = reg.emplace(std::string{ name }, creator);
    if (!ok)
        throw CommandError{ "Command already registered: " + std::string{ name } };
}

// ---------------------------------------------------------------------------
//  FactoryFromJson – dynamic rebuild from wire-format
// ---------------------------------------------------------------------------
inline std::unique_ptr<BaseCommand> BaseCommand::FactoryFromJson(const json& root)
{
    if (!root.contains("name") || !root.contains("metadata") || !root.contains("payload"))
        throw CommandError{ "Malformed command JSON" };

    const auto& name = root.at("name").get_ref<const std::string&>();
    const auto& meta_json = root.at("metadata");

    Metadata meta{
        meta_json.at("command_id").get<std::string>(),
        meta_json.at("correlation_id").get<std::string>(),
        meta_json.at("tenant_id").get<std::string>(),
        std::chrono::system_clock::time_point{
            std::chrono::milliseconds( meta_json.at("created_at_epoch_ms").get<int64_t>() )
        },
        meta_json.at("schema_version").get<std::size_t>()
    };

    const auto& reg = Registry();
    auto it = reg.find(name);
    if (it == reg.end())
        throw CommandError{ "Unknown command encountered: " + name };

    return it->second(root.at("payload"), meta);
}

}   // namespace fortiledger::domain::commands

#endif /* FORTILEDGER360_SRC_LIB_DOMAIN_COMMANDS_BASE_COMMAND_H_ */
