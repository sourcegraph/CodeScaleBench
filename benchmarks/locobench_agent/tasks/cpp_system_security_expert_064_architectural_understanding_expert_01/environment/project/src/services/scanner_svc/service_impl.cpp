#include "scanner_svc/service_impl.hpp"

#include <grpcpp/grpcpp.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <chrono>
#include <exception>
#include <future>
#include <random>
#include <stdexcept>
#include <utility>

#include "common/uuid.hpp"
#include "eventing/event_bus.hpp"
#include "observability/metrics.hpp"
#include "scanner_svc/policies/scan_strategy_registry.hpp"

namespace fl360::scanner {

using grpc::ServerContext;
using grpc::Status;

namespace {
constexpr std::chrono::milliseconds kLogStreamingInterval{500};

/* -------------------------------------------------------------
 * Helper: make_uuid()
 * ------------------------------------------------------------- */
std::string make_uuid() {
    return fl360::common::uuid::generate();
}

/* -------------------------------------------------------------
 * Helper: convert internal status -> proto status enum
 * ------------------------------------------------------------- */
proto::ScanStatus ToProtoStatus(ScanState state) {
    using proto::ScanStatus;
    switch (state) {
        case ScanState::kPending:
            return ScanStatus::PENDING;
        case ScanState::kRunning:
            return ScanStatus::RUNNING;
        case ScanState::kSucceeded:
            return ScanStatus::SUCCEEDED;
        case ScanState::kFailed:
            return ScanStatus::FAILED;
        default:
            return ScanStatus::FAILED;
    }
}
}  // namespace

/* =============================================================
 *  ServiceImpl  – public
 * ============================================================= */

ServiceImpl::ServiceImpl(std::shared_ptr<eventing::EventBus>            bus,
                         std::shared_ptr<policies::ScanStrategyRegistry> registry,
                         std::shared_ptr<observability::Metrics>        metrics)
    : event_bus_{std::move(bus)},
      strategy_registry_{std::move(registry)},
      metrics_{std::move(metrics)} {
    if (!event_bus_ || !strategy_registry_ || !metrics_) {
        throw std::invalid_argument("ServiceImpl: nullptr injection detected");
    }

    SPDLOG_INFO("Scanner ServiceImpl instantiated");
}

Status ServiceImpl::InitiateScan(ServerContext*                              ctx,
                                 const proto::InitiateScanRequest*           request,
                                 proto::InitiateScanResponse*                response) {
    if (ctx->IsCancelled()) { return Status::CANCELLED; }

    try {
        const std::string& tenant_id = request->tenant_id();
        const std::string  scan_type = request->scan_type();
        const auto&        assets    = request->asset_ids();

        if (tenant_id.empty() || scan_type.empty() || assets.empty()) {
            return Status{grpc::INVALID_ARGUMENT,
                          "tenant_id, scan_type and asset_ids cannot be empty"};
        }

        const std::string scan_id = make_uuid();
        SPDLOG_INFO("[{}] Initiating scan '{}'", tenant_id, scan_id);

        // -- Acquire strategy ------------------------------------------------
        auto strategy = strategy_registry_->get(scan_type);
        if (!strategy) {
            SPDLOG_WARN("Unknown scan_type '{}'", scan_type);
            return Status{grpc::INVALID_ARGUMENT, "unknown scan_type"};
        }

        {
            std::lock_guard lk{state_mtx_};
            scans_.emplace(scan_id, ScanContext{/*state*/ ScanState::kPending,
                                                /*started_at*/ Clock::now(),
                                                /*future*/ {}});
        }

        // -- Publish Domain Event -------------------------------------------
        event_bus_->publish(events::ScanStarted{
            .scan_id   = scan_id,
            .tenant_id = tenant_id,
            .policy    = scan_type,
            .asset_cnt = static_cast<std::uint32_t>(assets.size())});

        // -- Start Async task ------------------------------------------------
        auto future = std::async(std::launch::async,
                                 [this, scan_id, tenant_id, strategy, assets_vec = RepeatedToVector(assets)]() {
                                     RunScanTask(scan_id, tenant_id, *strategy, assets_vec);
                                 });

        {
            std::lock_guard lk{state_mtx_};
            scans_.at(scan_id).state  = ScanState::kRunning;
            scans_.at(scan_id).future = std::move(future);
        }

        metrics_->counter("scanner.scan_started").inc();

        response->set_scan_id(scan_id);
        return Status::OK;
    } catch (const std::exception& ex) {
        SPDLOG_ERROR("InitiateScan failed: {}", ex.what());
        return Status{grpc::INTERNAL, ex.what()};
    }
}

Status ServiceImpl::GetScanStatus(ServerContext*                      ctx,
                                  const proto::ScanStatusRequest*     request,
                                  proto::ScanStatusResponse*          response) {
    if (ctx->IsCancelled()) { return Status::CANCELLED; }

    const std::string& scan_id = request->scan_id();
    if (scan_id.empty()) {
        return Status{grpc::INVALID_ARGUMENT, "scan_id must be provided"};
    }

    std::lock_guard lk{state_mtx_};
    auto it = scans_.find(scan_id);
    if (it == scans_.end()) {
        return Status{grpc::NOT_FOUND, "scan_id not found"};
    }

    response->set_status(ToProtoStatus(it->second.state));
    return Status::OK;
}

Status ServiceImpl::StreamScanLogs(ServerContext*                               ctx,
                                   const proto::ScanLogStreamRequest*           request,
                                   grpc::ServerWriter<proto::ScanLogEnvelope>*  writer) {
    if (request->scan_id().empty()) {
        return Status{grpc::INVALID_ARGUMENT, "scan_id must be provided"};
    }

    auto last_idx_sent = std::size_t{0};

    while (!ctx->IsCancelled()) {
        std::vector<std::string> snapshot;
        {
            std::lock_guard lk{state_mtx_};
            auto it = scans_.find(request->scan_id());
            if (it == scans_.end()) { return Status{grpc::NOT_FOUND, "scan not found"}; }
            snapshot = it->second.logs;
            if (it->second.state == ScanState::kSucceeded || it->second.state == ScanState::kFailed) {
                // End stream when all logs sent after completion.
                if (last_idx_sent >= snapshot.size()) { break; }
            }
        }

        if (last_idx_sent < snapshot.size()) {
            for (; last_idx_sent < snapshot.size(); ++last_idx_sent) {
                proto::ScanLogEnvelope env;
                env.set_message(snapshot[last_idx_sent]);
                if (!writer->Write(env)) { break; }
            }
        }

        std::this_thread::sleep_for(kLogStreamingInterval);
    }

    return Status::OK;
}

/* =============================================================
 *  ServiceImpl  – private helpers
 * ============================================================= */

void ServiceImpl::RunScanTask(const std::string&               scan_id,
                              const std::string&               tenant_id,
                              policies::IScanStrategy&         strategy,
                              const std::vector<std::string>&  assets) {
    auto start_time = Clock::now();
    SPDLOG_INFO("[{}] Scan '{}' started ({} assets)", tenant_id, scan_id, assets.size());

    auto AppendLog = [this, &scan_id](std::string msg) {
        std::lock_guard lk{state_mtx_};
        auto& ctx = scans_.at(scan_id);
        ctx.logs.emplace_back(std::move(msg));
    };

    try {
        strategy.execute(tenant_id, assets,
                         /*progress_cb=*/
                         [&](std::string_view note) { AppendLog(std::string{note}); });

        {
            std::lock_guard lk{state_mtx_};
            scans_.at(scan_id).state = ScanState::kSucceeded;
        }

        metrics_->counter("scanner.scan_succeeded").inc();
        event_bus_->publish(events::ScanCompleted{.scan_id = scan_id, .tenant_id = tenant_id, .success = true});
        SPDLOG_INFO("[{}] Scan '{}' succeeded in {}ms", tenant_id, scan_id,
                    std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start_time).count());
    } catch (const std::exception& ex) {
        {
            std::lock_guard lk{state_mtx_};
            scans_.at(scan_id).state = ScanState::kFailed;
            scans_.at(scan_id).logs.emplace_back("ERROR: " + std::string{ex.what()});
        }

        metrics_->counter("scanner.scan_failed").inc();
        event_bus_->publish(events::ScanCompleted{.scan_id = scan_id, .tenant_id = tenant_id, .success = false});
        SPDLOG_ERROR("[{}] Scan '{}' failed: {}", tenant_id, scan_id, ex.what());
    }
}

std::vector<std::string> ServiceImpl::RepeatedToVector(const google::protobuf::RepeatedPtrField<std::string>& r) {
    return {r.begin(), r.end()};
}

}  // namespace fl360::scanner