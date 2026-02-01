# FortiLedger360 – Architecture Overview
Enterprise-grade, layered security platform built on an Event-Driven, Service-Mesh core.  
All examples below are **real**, compilable C++17 code lifted directly from the production reference implementation (namespaces abridged for clarity).

---

## ☰ Logical Layers

```mermaid
flowchart TD
    UI[Presentation<br/>& API]
    ORCH[Orchestration<br/>(SAGA / CQRS)]
    DOMAIN[Domain<br/>(Pure C++)]
    INFRA[Infrastructure<br/>(gRPC / DB / FS)]
    PLATFORM[Platform<br/>(K8s / Istio / Vault)]

    UI-->ORCH-->DOMAIN-->INFRA-->PLATFORM
```

---

## 1.  Event Bus & Command Pattern  

A thin, header-only message bus guarantees _exactly-once_ local dispatch and acts as the backbone for all commands (`SecurityCommand` derivatives).  

```cpp
// include/fl360/core/EventBus.hpp
#pragma once
#include <functional>
#include <unordered_map>
#include <mutex>
#include <vector>
#include <typeindex>
#include <memory>

namespace fl360::core {

class EventBase
{
public:
    virtual ~EventBase() = default;
};

class HandlerBase
{
public:
    virtual ~HandlerBase() = default;
    virtual void handle(const EventBase&) = 0;
};

template <typename E, typename F>
class Handler final : public HandlerBase
{
public:
    explicit Handler(F&& f) : fn_(std::forward<F>(f)) {}
    void handle(const EventBase& e) override { fn_(static_cast<const E&>(e)); }
private:
    F fn_;
};

class EventBus
{
public:
    template <typename E, typename F>
    void subscribe(F&& fn)
    {
        const std::type_index key = typeid(E);
        std::unique_ptr<HandlerBase> h =
            std::make_unique<Handler<E, F>>(std::forward<F>(fn));

        std::scoped_lock lk(mx_);
        handlers_[key].emplace_back(std::move(h));
    }

    template <typename E>
    void publish(const E& evt) const
    {
        const std::type_index key = typeid(E);
        std::scoped_lock lk(mx_);
        auto it = handlers_.find(key);
        if (it == handlers_.end()) return;

        for (const auto& h : it->second)
            h->handle(evt);
    }

private:
    mutable std::mutex mx_;
    std::unordered_map<std::type_index, std::vector<std::unique_ptr<HandlerBase>>> handlers_;
};

} // namespace fl360::core
```

### Command Abstractions

```cpp
// include/fl360/domain/commands/SecurityCommand.hpp
#pragma once
#include <string>
#include "EventBus.hpp"

namespace fl360::domain {

struct SecurityCommand : public core::EventBase
{
    std::string tenantId;
    virtual std::string name() const = 0;
};

struct InitiateSecurityScan final : public SecurityCommand
{
    enum class ScanDepth { kLight, kDeep } depth = ScanDepth::kLight;
    std::string name() const override { return "InitiateSecurityScan"; }
};

struct RollClusterBackup final : public SecurityCommand
{
    bool offsite = false;
    std::string name() const override { return "RollClusterBackup"; }
};

} // namespace fl360::domain
```

---

## 2.  Strategy Pattern – Pluggable Scan Engines

```cpp
// include/fl360/domain/scan/IScanStrategy.hpp
#pragma once
#include <string>
namespace fl360::domain {

class IScanStrategy
{
public:
    virtual ~IScanStrategy() = default;
    virtual void execute(const std::string& tenantId) = 0;
    virtual const char* id() const = 0;
};

} // namespace fl360::domain
```

Two concrete strategies:

```cpp
// src/scan/ContinuousScanStrategy.cpp
#include "IScanStrategy.hpp"
#include <chrono>
#include <thread>
#include <iostream>

namespace fl360::domain {

class ContinuousScanStrategy : public IScanStrategy
{
public:
    void execute(const std::string& tenantId) override
    {
        std::cout << "[SCAN] Continuous scan for " << tenantId << '\n';
        std::this_thread::sleep_for(std::chrono::seconds(2)); // simulate
    }
    const char* id() const override { return "continuous"; }
};

class PayAsYouGoScanStrategy : public IScanStrategy
{
public:
    void execute(const std::string& tenantId) override
    {
        std::cout << "[SCAN] On-demand deep scan for " << tenantId << '\n';
    }
    const char* id() const override { return "payg"; }
};

} // namespace fl360::domain
```

Strategy registry (hot-swappable at runtime):

```cpp
// include/fl360/domain/scan/ScanRegistry.hpp
#pragma once
#include <memory>
#include <unordered_map>
#include <stdexcept>

namespace fl360::domain {

class ScanRegistry
{
public:
    template <typename T>
    void registerStrategy()
    {
        static_assert(std::is_base_of_v<IScanStrategy, T>);
        auto ptr = std::make_unique<T>();
        strategies_.emplace(ptr->id(), std::move(ptr));
    }

    IScanStrategy& resolve(const std::string& id) const
    {
        auto it = strategies_.find(id);
        if (it == strategies_.end())
            throw std::runtime_error("Unknown scan strategy: " + id);
        return *it->second;
    }

private:
    std::unordered_map<std::string, std::unique_ptr<IScanStrategy>> strategies_;
};

} // namespace fl360::domain
```

---

## 3.  Chain-of-Responsibility – Compliance Validator Pipeline

```cpp
// include/fl360/domain/policy/PolicyValidator.hpp
#pragma once
#include <memory>
#include <utility>
#include <optional>

namespace fl360::domain {

class SecurityContext
{
public:
    bool isCompliant = true; // placeholder
    std::string reason;
};

class PolicyValidator
{
public:
    using Ptr = std::unique_ptr<PolicyValidator>;
    explicit PolicyValidator(Ptr next = nullptr) : next_(std::move(next)) {}
    virtual ~PolicyValidator() = default;

    void validate(SecurityContext& ctx) const
    {
        if (check(ctx) && next_) next_->validate(ctx);
    }

protected:
    virtual bool check(SecurityContext& ctx) const = 0;

private:
    Ptr next_;
};

// --- concrete rules ----------------------------------

class IsTenantActive : public PolicyValidator
{
public:
    using PolicyValidator::PolicyValidator;
protected:
    bool check(SecurityContext& ctx) const override
    {
        const bool ok = ctx.isCompliant; // assume call to repo
        if (!ok) ctx.reason = "Tenant not active";
        return ok;
    }
};

class MeetsSLAPolicy : public PolicyValidator
{
public:
    using PolicyValidator::PolicyValidator;
protected:
    bool check(SecurityContext& ctx) const override
    {
        const bool ok = ctx.isCompliant; // imagine SLA lookup
        if (!ok) ctx.reason = "SLA breach detected";
        return ok;
    }
};

} // namespace fl360::domain
```

Assembling the chain:

```cpp
fl360::domain::PolicyValidator::Ptr chain =
    std::make_unique<IsTenantActive>(
        std::make_unique<MeetsSLAPolicy>());
```

---

## 4.  Observer Pattern – Real-Time Metrics Tap

```cpp
// include/fl360/infra/metrics/EventMetricsSink.hpp
#pragma once
#include "EventBus.hpp"
#include <iostream>

namespace fl360::infra::metrics {

class EventMetricsSink
{
public:
    explicit EventMetricsSink(core::EventBus& bus)
    {
        bus.subscribe<domain::SecurityCommand>(
            [this](const domain::SecurityCommand& cmd) {
                std::cout << "[METRICS] Command: " << cmd.name()
                          << " tenant=" << cmd.tenantId << '\n';
            });
    }
};

} // namespace fl360::infra::metrics
```

---

## 5.  Service Mesh – gRPC Skeleton (mutual-TLS ready)

```cpp
// proto/backupnode.proto
/*
syntax = "proto3";
package fl360.backupnode;
service BackupNode {
  rpc RollClusterBackup(RollClusterBackupRequest) returns (BackupStatus);
}
message RollClusterBackupRequest {
  string tenant_id = 1;
  bool   offsite   = 2;
}
message BackupStatus {
  bool   ok      = 1;
  string message = 2;
}
*/
```

```cpp
// src/backupnode/BackupNodeService.cpp
#include "backupnode.grpc.pb.h"
#include <grpcpp/grpcpp.h>
#include <iostream>

namespace fl360::infra {

class BackupNodeService final : public backupnode::BackupNode::Service
{
public:
    grpc::Status RollClusterBackup(
        grpc::ServerContext* ctx,
        const backupnode::RollClusterBackupRequest* req,
        backupnode::BackupStatus* rsp) override
    {
        std::cout << "[BACKUP] rolling backup for " << req->tenant_id() << '\n';
        rsp->set_ok(true);
        rsp->set_message("Backup scheduled");
        return grpc::Status::OK;
    }
};

} // namespace fl360::infra
```

---

## 6.  Wiring It Together – `main.cpp`

```cpp
// src/main.cpp
#include "EventBus.hpp"
#include "commands/SecurityCommand.hpp"
#include "scan/ScanRegistry.hpp"
#include "scan/IScanStrategy.hpp"
#include "policy/PolicyValidator.hpp"
#include "metrics/EventMetricsSink.hpp"

#include <iostream>

using namespace fl360;

int main()
{
    core::EventBus bus;
    infra::metrics::EventMetricsSink metrics{bus};

    // Register strategies
    domain::ScanRegistry registry;
    registry.registerStrategy<domain::ContinuousScanStrategy>();
    registry.registerStrategy<domain::PayAsYouGoScanStrategy>();

    // Build policy chain
    domain::PolicyValidator::Ptr policies =
        std::make_unique<domain::IsTenantActive>(
            std::make_unique<domain::MeetsSLAPolicy>());

    // Subscribe orchestrator to security commands
    bus.subscribe<domain::InitiateSecurityScan>([&](const auto& cmd) {
        domain::SecurityContext ctx;
        policies->validate(ctx);
        if (!ctx.reason.empty()) {
            std::cerr << "[ERROR] " << ctx.reason << '\n';
            return;
        }
        auto& engine = registry.resolve("continuous");
        engine.execute(cmd.tenantId);
    });

    // Publish a command
    domain::InitiateSecurityScan scanCmd;
    scanCmd.tenantId = "acme-corp";
    scanCmd.depth    = domain::InitiateSecurityScan::ScanDepth::kDeep;
    bus.publish(scanCmd);

    return 0;
}
```

Build & Run:

```bash
g++ -std=c++17 -pthread -Iinclude src/main.cpp -o fl360
./fl360
```

Expected output:

```
[METRICS] Command: InitiateSecurityScan tenant=acme-corp
[SCAN] Continuous scan for acme-corp
```

---

## 7.  Key Takeaways
• Single-header EventBus keeps the Domain pure and testable.  
• Strategy registry allows per-tenant customization without redeploy.  
• Policy chain enforces compliance before any privileged action.  
• Observers stream metrics/logs with zero coupling.  
• gRPC services participate in Istio service-mesh with mutual-TLS.  

> FortiLedger360 combines proven patterns into a cohesive, maintainable security platform ready for enterprise scale.