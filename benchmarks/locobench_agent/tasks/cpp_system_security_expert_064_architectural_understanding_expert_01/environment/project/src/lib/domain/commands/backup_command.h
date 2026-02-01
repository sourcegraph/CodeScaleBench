```cpp
/************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  Module      : Domain :: Commands
 *  File        : backup_command.h
 *
 *  Copyright   : Copyright (c) 2023-2024
 *  License     : Proprietary — All rights reserved.
 *
 *  Description :
 *      Domain-level “BackupCommand” used by the BackupNode mesh-service to
 *      orchestrate cluster-wide backups.  The command encapsulates all business
 *      semantics required to initiate a backup, while remaining agnostic to the
 *      transport mechanism (gRPC, Kafka, etc.).  It is designed to be serialized
 *      over the event-bus and reconstructed by downstream services.
 *
 *  NOTE:
 *      Header-only implementation for ergonomic inclusion in Command dispatchers.
 ************************************************************************************/

#pragma once

// STL
#include <chrono>
#include <cstdint>
#include <exception>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

// Third-party — single-header JSON library (shipped with platform)
#include <nlohmann/json.hpp>

namespace fl360::domain::commands
{
/* ====================================================================================
 *  Errors
 * ====================================================================================*/
class CommandValidationError final : public std::runtime_error
{
public:
    explicit CommandValidationError(const std::string& msg)
        : std::runtime_error("Command validation failed: " + msg) {}
};

/* ====================================================================================
 *  Command Base Interface
 * ====================================================================================*/
class ICommand
{
public:
    virtual ~ICommand() = default;

    // A short, unique identifier used by the event-bus router.
    [[nodiscard]] virtual std::string name() const noexcept = 0;

    // Validates semantic correctness; throws CommandValidationError on failure.
    virtual void validate() const = 0;

    // Serializes the command into JSON payload ready for the message-bus.
    [[nodiscard]] virtual nlohmann::json to_json() const = 0;
};

/* ====================================================================================
 *  Domain Specific Types
 * ====================================================================================*/
enum class BackupScope : std::uint8_t
{
    kCluster     = 0,
    kNode        = 1,
    kDatabase    = 2,
    kConfiguration = 3
};

enum class BackupMode : std::uint8_t
{
    kFull          = 0,
    kIncremental   = 1,
    kDifferential  = 2
};

// Human-readable mapping helpers — handy for telemetry & debugging.
inline const char* to_string(BackupScope scope) noexcept
{
    switch (scope)
    {
        case BackupScope::kCluster:       return "Cluster";
        case BackupScope::kNode:          return "Node";
        case BackupScope::kDatabase:      return "Database";
        case BackupScope::kConfiguration: return "Configuration";
        default:                          return "Unknown";
    }
}

inline const char* to_string(BackupMode mode) noexcept
{
    switch (mode)
    {
        case BackupMode::kFull:         return "Full";
        case BackupMode::kIncremental:  return "Incremental";
        case BackupMode::kDifferential: return "Differential";
        default:                        return "Unknown";
    }
}

/* ====================================================================================
 *  BackupCommand — Concrete implementation
 * ====================================================================================*/
class BackupCommand final : public ICommand
{
public:
    // Public “fluent” builder for convenience
    class Builder
    {
    public:
        Builder& tenant_id(std::string id)
        {
            tenant_id_ = std::move(id);
            return *this;
        }

        Builder& scope(BackupScope scope)
        {
            scope_ = scope;
            return *this;
        }

        Builder& mode(BackupMode mode)
        {
            mode_ = mode;
            return *this;
        }

        Builder& include_nodes(std::vector<std::string> nodes)
        {
            include_nodes_ = std::move(nodes);
            return *this;
        }

        Builder& schedule_at(std::chrono::system_clock::time_point tp)
        {
            scheduled_at_ = tp;
            return *this;
        }

        Builder& correlation_id(std::string cid)
        {
            correlation_id_ = std::move(cid);
            return *this;
        }

        BackupCommand build() const
        {
            BackupCommand cmd(
                tenant_id_,
                scope_,
                mode_,
                include_nodes_,
                scheduled_at_,
                correlation_id_);
            cmd.validate(); // Fail-fast on construction
            return cmd;
        }

    private:
        std::string                                       tenant_id_;
        BackupScope                                       scope_ {BackupScope::kCluster};
        BackupMode                                        mode_  {BackupMode::kFull};
        std::vector<std::string>                          include_nodes_;
        std::optional<std::chrono::system_clock::time_point> scheduled_at_;
        std::optional<std::string>                        correlation_id_;
    };

    /* ----------------------------------------------------------------------
     *  Constructors
     * --------------------------------------------------------------------*/
    BackupCommand(std::string                                       tenantId,
                  BackupScope                                       scope,
                  BackupMode                                        mode,
                  std::vector<std::string>                          includeNodes,
                  std::optional<std::chrono::system_clock::time_point> scheduledAt,
                  std::optional<std::string>                        correlationId)
        : tenant_id_(std::move(tenantId))
        , scope_(scope)
        , mode_(mode)
        , include_nodes_(std::move(includeNodes))
        , scheduled_at_(scheduledAt.value_or(std::chrono::system_clock::now()))
        , correlation_id_(std::move(correlationId).value_or(generate_uuid_()))
    {}

    /* ----------------------------------------------------------------------
     *  ICommand overrides
     * --------------------------------------------------------------------*/
    [[nodiscard]] std::string name() const noexcept override
    {
        return "BackupCommand";
    }

    void validate() const override
    {
        if (tenant_id_.empty())
        {
            throw CommandValidationError("tenant_id must not be empty");
        }

        if (mode_ == BackupMode::kIncremental && scope_ == BackupScope::kConfiguration)
        {
            throw CommandValidationError(
                "Incremental backups for configuration scope are not supported");
        }

        if (scope_ == BackupScope::kNode && include_nodes_.empty())
        {
            throw CommandValidationError(
                "Scope is 'Node' but include_nodes list is empty");
        }
    }

    [[nodiscard]] nlohmann::json to_json() const override
    {
        nlohmann::json j;
        j["command_name"]   = name();
        j["tenant_id"]      = tenant_id_;
        j["scope"]          = to_string(scope_);
        j["mode"]           = to_string(mode_);
        j["include_nodes"]  = include_nodes_;
        j["scheduled_at"]   = std::chrono::duration_cast<std::chrono::milliseconds>(
                                  scheduled_at_.time_since_epoch()).count();
        j["correlation_id"] = correlation_id_;
        return j;
    }

    /* ----------------------------------------------------------------------
     *  Getters
     * --------------------------------------------------------------------*/
    [[nodiscard]] const std::string& tenant_id()  const noexcept { return tenant_id_;  }
    [[nodiscard]] BackupScope        scope()      const noexcept { return scope_;      }
    [[nodiscard]] BackupMode         mode()       const noexcept { return mode_;       }

    [[nodiscard]] const std::vector<std::string>& include_nodes() const noexcept
    { return include_nodes_; }

    [[nodiscard]] std::chrono::system_clock::time_point scheduled_at() const noexcept
    { return scheduled_at_; }

    [[nodiscard]] const std::string& correlation_id() const noexcept
    { return correlation_id_; }

private:
    /* ----------------------------------------------------------------------
     *  Implementation helpers
     * --------------------------------------------------------------------*/
    static std::string generate_uuid_()
    {
        // Very light, pseudo-random UUID v4 generator — replace with stronger
        // implementation (e.g., Boost.Uuid) for production deployments.
        static constexpr char hex[] = "0123456789abcdef";
        std::stringstream ss;
        std::random_device rd;
        std::uniform_int_distribution<int> dis(0, 15);

        int lengths[] = {8, 4, 4, 4, 12};
        for (size_t i = 0; i < 5; ++i)
        {
            if (i != 0) ss << '-';
            for (int j = 0; j < lengths[i]; ++j)
                ss << hex[dis(rd)];
        }
        return ss.str();
    }

    /* ----------------------------------------------------------------------
     *  Data Members
     * --------------------------------------------------------------------*/
    std::string                                       tenant_id_;
    BackupScope                                       scope_;
    BackupMode                                        mode_;
    std::vector<std::string>                          include_nodes_;
    std::chrono::system_clock::time_point             scheduled_at_;
    std::string                                       correlation_id_;
};

/* ====================================================================================
 *  JSON (de)serialization helpers — enables “transparent” conversions when commands
 *  are embedded in larger event envelopes.
 * ====================================================================================*/
inline void to_json(nlohmann::json& j, const BackupCommand& cmd)
{
    j = cmd.to_json();
}

inline void from_json(const nlohmann::json& j, BackupCommand& cmd)
{
    // Robust deserialization with defaulting & validation
    BackupCommand::Builder builder;

    if (!j.contains("tenant_id") || j.at("tenant_id").get<std::string>().empty())
        throw CommandValidationError("JSON payload missing 'tenant_id'");

    builder.tenant_id(j.at("tenant_id").get<std::string>());

    if (j.contains("scope"))
    {
        const auto& s = j.at("scope").get<std::string>();
        if (s == "Cluster")       builder.scope(BackupScope::kCluster);
        else if (s == "Node")     builder.scope(BackupScope::kNode);
        else if (s == "Database") builder.scope(BackupScope::kDatabase);
        else if (s == "Configuration") builder.scope(BackupScope::kConfiguration);
        else throw CommandValidationError("Invalid 'scope' value: " + s);
    }

    if (j.contains("mode"))
    {
        const auto& m = j.at("mode").get<std::string>();
        if (m == "Full")          builder.mode(BackupMode::kFull);
        else if (m == "Incremental") builder.mode(BackupMode::kIncremental);
        else if (m == "Differential") builder.mode(BackupMode::kDifferential);
        else throw CommandValidationError("Invalid 'mode' value: " + m);
    }

    if (j.contains("include_nodes"))
        builder.include_nodes(j.at("include_nodes").get<std::vector<std::string>>());

    if (j.contains("scheduled_at"))
    {
        auto ms_since_epoch = j.at("scheduled_at").get<long long>();
        builder.schedule_at(std::chrono::system_clock::time_point(
            std::chrono::milliseconds(ms_since_epoch)));
    }

    if (j.contains("correlation_id"))
        builder.correlation_id(j.at("correlation_id").get<std::string>());

    cmd = builder.build();
}

} // namespace fl360::domain::commands
```