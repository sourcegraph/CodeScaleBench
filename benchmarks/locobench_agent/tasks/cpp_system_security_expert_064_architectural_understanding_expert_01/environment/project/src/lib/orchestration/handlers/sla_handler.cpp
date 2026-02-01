```cpp
/**
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 *  File   : src/lib/orchestration/handlers/sla_handler.cpp
 *  Author : FortiLedger360 Orchestration Team
 *
 *  Description:
 *      Concrete orchestration handler responsible for enforcing
 *      Service-Level Agreements (SLAs).  The handler subscribes to the
 *      event-bus for “EnforceSLA” commands that originate from the
 *      Presentation/API tier.  For every command it
 *
 *          1. Retrieves the SLA-contract from the domain service
 *          2. Fetches a recent metrics snapshot via gRPC
 *          3. Evaluates whether the contract is satisfied
 *          4. Raises alerts + publishes a domain-event when violated
 *
 *      The implementation is deliberately stateless; all state that
 *      affects business-semantics is stored in the domain / infrastructure
 *      layers.  A small in-memory debounce-table prevents alert-flooding
 *      by suppressing repeat violations inside a grace-period.
 *
 *  Copyright:
 *      (c) 2024 FortiLedger360 Inc. — All rights reserved.
 */

#include "sla_handler.h"

// STL
#include <atomic>
#include <chrono>
#include <exception>
#include <future>
#include <mutex>
#include <unordered_map>

// 3rd-party
#include <fmt/format.h>
#include <grpcpp/grpcpp.h>
#include <spdlog/spdlog.h>

// Internal
#include <core/eventing/Command.h>
#include <core/eventing/Event.h>
#include <core/eventing/EventBus.h>
#include <lib/domain/sla/SLAContract.h>
#include <lib/domain/sla/SLAService.h>
#include <lib/infrastructure/grpc/AlertBrokerClient.h>
#include <lib/infrastructure/grpc/MetricsServiceClient.h>

namespace fortiledger::orchestration::handlers {

//--------------------------------------------------------------------------
//  Anon namespace — constants
//--------------------------------------------------------------------------
namespace {

using namespace std::chrono_literals;

constexpr auto kMetricsFetchTimeout     = 5s;   // gRPC deadline
constexpr auto kSlaViolationGracePeriod = 30s;  // debounce window

} // namespace

//--------------------------------------------------------------------------
//  Private implementation
//--------------------------------------------------------------------------
class SLAHandler::Impl final :
        public std::enable_shared_from_this<SLAHandler::Impl>
{
public:
    Impl(std::shared_ptr<core::eventing::EventBus>          bus,
         std::shared_ptr<domain::sla::SLAService>           slaService,
         std::shared_ptr<infra::grpc::MetricsServiceClient> metrics,
         std::shared_ptr<infra::grpc::AlertBrokerClient>    alert)
        : m_bus        { std::move(bus)        }
        , m_slaService { std::move(slaService) }
        , m_metrics    { std::move(metrics)    }
        , m_alert      { std::move(alert)      }
    {
        if (!m_bus || !m_slaService || !m_metrics || !m_alert)
            throw std::invalid_argument("SLAHandler::Impl received nullptr dependency");
    }

    ~Impl()
    {
        try
        {
            if (m_subscriptionId != 0ULL)
                m_bus->unsubscribe(m_subscriptionId);
        }
        catch (const std::exception& ex)
        {
            spdlog::warn("SLAHandler: error while unsubscribing: {}", ex.what());
        }
    }

    void bootstrap()
    {
        // Register for EnforceSLA commands on the event-bus
        m_subscriptionId = m_bus->subscribe<core::eventing::Command>(
            [weakSelf = weak_from_this()](const core::eventing::Command& cmd)
            {
                if (auto self = weakSelf.lock(); self)
                    self->onCommand(cmd);
            });

        spdlog::info("SLAHandler ready (subscriptionId={})", m_subscriptionId);
    }

private:
    // ------------------------------------------------------------
    //  Event-handler
    // ------------------------------------------------------------
    void onCommand(const core::eventing::Command& cmd)
    {
        if (cmd.type() != "EnforceSLA")
            return;         // not our business

        std::string tenantId   = cmd["tenant_id"].get<std::string>();
        std::string contractId = cmd["contract_id"].get<std::string>();

        // Dispatch asynchronously — keep event-thread unblocked
        std::async(std::launch::async,
                   [self = shared_from_this(), tenantId, contractId]
                   {
                       try       { self->enforce(tenantId, contractId); }
                       catch (...) {
                           spdlog::error("Unhandled exception while enforcing SLA "
                                         "(tenant={}, contract={})",
                                         tenantId, contractId);
                       }
                   });
    }

    // ------------------------------------------------------------
    //  SLA evaluation pipeline
    // ------------------------------------------------------------
    void enforce(const std::string& tenantId,
                 const std::string& contractId)
    {
        // 1) Load contract
        auto contractOpt = m_slaService->getContract(contractId);
        if (!contractOpt)
        {
            spdlog::warn("SLAHandler: contract '{}' not found (tenant='{}')",
                         contractId, tenantId);
            return;
        }
        const domain::sla::SLAContract& contract = *contractOpt;

        // 2) Pull metrics
        auto fut = m_metrics->asyncFetchMetrics(tenantId);
        if (fut.wait_for(kMetricsFetchTimeout) == std::future_status::timeout)
            throw std::runtime_error(
                fmt::format("Metrics fetch timeout for tenant '{}'", tenantId));

        infra::grpc::MetricsSnapshot snapshot = fut.get();

        // 3) Evaluate
        domain::sla::SlaEvaluationResult result = contract.evaluate(snapshot);
        spdlog::info("SLAHandler: tenant={} contract={} satisfied={}",
                     tenantId, contractId, result.satisfied);

        // 4) Violation?
        if (!result.satisfied && shouldRaiseViolation(tenantId, contractId))
            raiseViolation(tenantId, contract, result);
    }

    // ------------------------------------------------------------
    //  Debounce logic
    // ------------------------------------------------------------
    bool shouldRaiseViolation(const std::string& tenantId,
                              const std::string& contractId)
    {
        const auto now = std::chrono::steady_clock::now();
        const auto key = fmt::format("{}:{}", tenantId, contractId);

        std::lock_guard<std::mutex> lock { m_cacheMutex };

        const auto it = m_lastRaised.find(key);
        if (it != m_lastRaised.cend() &&
            (now - it->second) < kSlaViolationGracePeriod)
        {
            return false;   // inside grace-period
        }

        m_lastRaised[key] = now;
        return true;
    }

    // ------------------------------------------------------------
    //  Publish alert + domain-event
    // ------------------------------------------------------------
    void raiseViolation(const std::string&                tenantId,
                        const domain::sla::SLAContract&   contract,
                        const domain::sla::SlaEvaluationResult& eval)
    {
        // Build gRPC alert
        infra::grpc::SlaViolationAlert alert;
        alert.set_tenant_id   (tenantId);
        alert.set_contract_id (contract.id());
        alert.set_severity    (infra::grpc::SlaViolationAlert::CRITICAL);
        alert.set_details     (eval.toJson());   // human-readable JSON blob

        // Fire & forget
        m_alert->publish(alert);

        spdlog::warn("SLA violation raised (tenant={}, contract={})",
                     tenantId, contract.id());

        // Emit event for downstream processors (billing, dashboards, etc.)
        core::eventing::Event evt { "SlaViolationRaised" };
        evt["tenant_id"]   = tenantId;
        evt["contract_id"] = contract.id();
        evt["details"]     = eval.toJson();

        m_bus->publish(evt);
    }

private:
    //----------------------------------------------------------------------
    //  Dependencies
    //----------------------------------------------------------------------
    std::shared_ptr<core::eventing::EventBus>          m_bus;
    std::shared_ptr<domain::sla::SLAService>           m_slaService;
    std::shared_ptr<infra::grpc::MetricsServiceClient> m_metrics;
    std::shared_ptr<infra::grpc::AlertBrokerClient>    m_alert;

    //----------------------------------------------------------------------
    //  Runtime state
    //----------------------------------------------------------------------
    std::atomic<std::uint64_t> m_subscriptionId { 0ULL };

    std::mutex                                                     m_cacheMutex;
    std::unordered_map<std::string,
                       std::chrono::steady_clock::time_point>      m_lastRaised;
}; // class Impl

//--------------------------------------------------------------------------
//  Public facade
//--------------------------------------------------------------------------
SLAHandler::SLAHandler(std::shared_ptr<core::eventing::EventBus>          bus,
                       std::shared_ptr<domain::sla::SLAService>           slaService,
                       std::shared_ptr<infra::grpc::MetricsServiceClient> metrics,
                       std::shared_ptr<infra::grpc::AlertBrokerClient>    alert)
    : m_impl { std::make_shared<Impl>(std::move(bus),
                                      std::move(slaService),
                                      std::move(metrics),
                                      std::move(alert)) }
{
    m_impl->bootstrap();
}

SLAHandler::~SLAHandler() = default;

} // namespace fortiledger::orchestration::handlers
```