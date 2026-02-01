#include "domain/strategies/continuous_scan_strategy.h"

#include <spdlog/spdlog.h>

#include <chrono>
#include <exception>
#include <stdexcept>
#include <thread>
#include <utility>

#include "domain/events/scan_events.h"
#include "infra/clients/scanner_client.h"
#include "infra/messaging/event_bus.h"
#include "infra/policies/compliance_policy_evaluator.h"

namespace fortiledger360::domain::strategies {

using fortiledger360::infra::ScannerClient;
using fortiledger360::infra::EventBus;
using fortiledger360::infra::policies::CompliancePolicyEvaluator;
using namespace std::chrono_literals;

///
/// ContinuousScanStrategy
/// ---------------------
/// Implements a near-real-time vulnerability scanning loop for
/// subscribed tenants.  Ensures:
///  * Configurable, back-pressure aware scheduling
///  * Compliance pre-check before each scan cycle
///  * Publication of Domain events for Observers (audit, billing, etc.)
///
/// Thread-safety:
///  • Public interface is thread-safe.
///  • The internal worker thread owns all mutable state.
///
ContinuousScanStrategy::ContinuousScanStrategy(
    std::string tenantId,
    std::shared_ptr<ScannerClient> scannerClient,
    std::shared_ptr<EventBus> eventBus,
    std::shared_ptr<CompliancePolicyEvaluator> policyEvaluator,
    std::chrono::seconds scanInterval,
    std::chrono::seconds jitter)
    : _tenantId(std::move(tenantId)),
      _scannerClient(std::move(scannerClient)),
      _eventBus(std::move(eventBus)),
      _policyEvaluator(std::move(policyEvaluator)),
      _scanInterval(scanInterval),
      _jitter(jitter),
      _running(false) {
    if (!_scannerClient || !_eventBus || !_policyEvaluator) {
        throw std::invalid_argument(
            "ContinuousScanStrategy: dependencies must not be null");
    }

    if (_scanInterval < 10s) {
        throw std::invalid_argument(
            "ContinuousScanStrategy: scan interval below sane threshold");
    }
}

ContinuousScanStrategy::~ContinuousScanStrategy() { stop(); }

void ContinuousScanStrategy::start() {
    std::lock_guard<std::mutex> lk(_lifecycleMtx);
    if (_running.exchange(true)) {
        return;  // already running
    }

    spdlog::info("[ContinuousScanStrategy] Starting continuous scanning loop "
                 "for tenant '{}'",
                 _tenantId);

    _worker = std::thread([this] { this->run(); });
}

void ContinuousScanStrategy::stop() {
    {
        std::lock_guard<std::mutex> lk(_lifecycleMtx);
        if (!_running.exchange(false)) {
            return;  // not running
        }
    }

    if (_worker.joinable()) {
        _worker.join();
    }

    spdlog::info("[ContinuousScanStrategy] Stopped scanning loop for tenant "
                 "'{}'",
                 _tenantId);
}

void ContinuousScanStrategy::run() {
    auto nextSleep = _scanInterval;
    // Randomize first iteration to avoid thundering herd
    nextSleep += _calculateJitter();

    while (_running.load()) {
        std::this_thread::sleep_for(nextSleep);
        if (!_running.load()) break;

        try {
            auto allowed =
                _policyEvaluator->isScanAllowed(_tenantId, std::chrono::system_clock::now());
            if (!allowed) {
                spdlog::warn(
                    "[ContinuousScanStrategy] Scan skipped (policy violation) "
                    "for tenant '{}'",
                    _tenantId);
                publishPolicyViolation();
                // Exponential back-off on policy violation
                nextSleep = std::min(nextSleep * 2, 10 * _scanInterval);
                continue;
            }

            performScan();
            nextSleep = _scanInterval + _calculateJitter();  // reset
        } catch (const std::exception& ex) {
            spdlog::error(
                "[ContinuousScanStrategy] Unhandled exception during scan "
                "cycle for tenant '{}': {}",
                _tenantId, ex.what());
            publishScanFailure(ex.what());
            // Maintain resilience: wait a bit longer to reduce pressure
            nextSleep = std::min(nextSleep * 2, 5 * _scanInterval);
        }
    }
}

void ContinuousScanStrategy::performScan() {
    spdlog::debug("[ContinuousScanStrategy] Performing scan for tenant '{}'",
                  _tenantId);

    // 1. Gather the list of assets subject to scanning for this tenant.
    auto assets = _scannerClient->resolveAssets(_tenantId);
    if (assets.empty()) {
        spdlog::info("[ContinuousScanStrategy] No assets to scan for tenant '{}'",
                     _tenantId);
        return;
    }

    // 2. Issue scan request and collect results.
    auto scanId = _scannerClient->initiateScan(_tenantId, assets);
    publishScanStarted(scanId, assets.size());

    auto results = _scannerClient->awaitScanResults(scanId);

    // 3. Publish results to interested parties (billing, monitoring, etc.)
    publishScanCompleted(scanId, results);

    // 4. House-keeping: enforce post-scan hooks (e.g., billing metering)
    _scannerClient->postScanFinalize(_tenantId, scanId);
}

//
// Domain Event helpers
//
void ContinuousScanStrategy::publishScanStarted(const std::string& scanId,
                                                std::size_t assetCount) {
    events::ScanStarted evt{_tenantId, scanId, assetCount};
    _eventBus->publish(evt);
}

void ContinuousScanStrategy::publishScanCompleted(
    const std::string& scanId, const infra::ScanResults& results) {
    events::ScanCompleted evt{_tenantId, scanId, results};
    _eventBus->publish(evt);
}

void ContinuousScanStrategy::publishScanFailure(const std::string& reason) {
    events::ScanFailed evt{_tenantId, reason};
    _eventBus->publish(evt);
}

void ContinuousScanStrategy::publishPolicyViolation() {
    events::ScanPolicyViolation evt{_tenantId};
    _eventBus->publish(evt);
}

//
// Utility
//
std::chrono::seconds ContinuousScanStrategy::_calculateJitter() const {
    if (_jitter.count() == 0) return 0s;

    static thread_local std::mt19937 rng{
        static_cast<unsigned>(std::chrono::steady_clock::now().time_since_epoch().count())};
    std::uniform_int_distribution<int> dist(0, static_cast<int>(_jitter.count()));
    return std::chrono::seconds(dist(rng));
}

}  // namespace fortiledger360::domain::strategies