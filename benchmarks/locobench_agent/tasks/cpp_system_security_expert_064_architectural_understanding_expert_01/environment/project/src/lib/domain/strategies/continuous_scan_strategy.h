```cpp
#pragma once
/*****************************************************************************************
 * File:        continuous_scan_strategy.h
 * Project:     FortiLedger360 Enterprise Security Suite
 * Component:   Domain ▸ Strategies
 *
 * Description:
 *   Implementation of a “continuous” vulnerability–scanning strategy.  Tenants that
 *   subscribe to this tier expect assets to be scanned in near-real-time, and any
 *   discovered vulnerabilities to be published on the platform’s event bus so that
 *   downstream services (AlertBroker, Metrics, Billing, etc.) can react.
 *
 *   The strategy spins up a dedicated background worker that performs scans at a
 *   configurable cadence.  All interactions are non-blocking for the caller; thread
 *   safety and graceful shutdown semantics are fully encapsulated in this component.
 *
 * Usage:
 *   auto strategy = std::make_shared<ContinuousScanStrategy>(
 *                      tenantId,
 *                      std::chrono::seconds{30},
 *                      scannerService,
 *                      eventBus);
 *   strategy->start();
 *   …
 *   strategy->stop();
 *
 * Author:      FortiLedger360 Core Team
 *****************************************************************************************/

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <exception>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace fortiledger::domain::strategies
{

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations of cross-domain abstractions.
// Note: Real implementations live in their own translation units; they are kept
// opaque here to preserve layering boundaries.
// ──────────────────────────────────────────────────────────────────────────────

struct ScanResult
{
    bool        success         {false};
    std::string details;
    std::vector<std::string> discoveredVulnerabilities;

    std::string toJson() const
    {
        std::ostringstream oss;
        oss << R"({"success":)" << (success ? "true" : "false")
            << R"(,"details":")" << details << "\""
            << R"(,"vulnerabilities":[)";
        for (size_t i = 0; i < discoveredVulnerabilities.size(); ++i)
        {
            oss << '"' << discoveredVulnerabilities[i] << '"';
            if (i + 1 < discoveredVulnerabilities.size()) { oss << ','; }
        }
        oss << "]}";
        return oss.str();
    }
};

class IScannerService
{
public:
    virtual ~IScannerService() = default;
    virtual ScanResult scanOnce(const std::string& tenantId) = 0;
};

class IEventBus
{
public:
    virtual ~IEventBus() = default;
    virtual void publish(const std::string& topic,
                         const std::string& payload) = 0;
};

// ──────────────────────────────────────────────────────────────────────────────
// IScanStrategy — minimal interface for all scanning strategies.
// ──────────────────────────────────────────────────────────────────────────────
class IScanStrategy
{
public:
    virtual ~IScanStrategy() = default;
    virtual void start()               = 0;
    virtual void stop()                = 0;
    virtual bool isRunning() const     = 0;
    virtual std::string name() const   = 0;
};

// ──────────────────────────────────────────────────────────────────────────────
// ContinuousScanStrategy — concrete implementation.
// ──────────────────────────────────────────────────────────────────────────────
class ContinuousScanStrategy final : public IScanStrategy,
                                     public std::enable_shared_from_this<ContinuousScanStrategy>
{
public:
    // Construction ------------------------------------------------------------
    ContinuousScanStrategy(std::string                      tenantId,
                           std::chrono::milliseconds        cadence,
                           std::shared_ptr<IScannerService> scanner,
                           std::shared_ptr<IEventBus>       bus)
        : tenantId_(std::move(tenantId))
        , cadence_(cadence)
        , scanner_(std::move(scanner))
        , bus_(std::move(bus))
    {
        if (!scanner_) { throw std::invalid_argument{"scanner service is null"}; }
        if (!bus_)     { throw std::invalid_argument{"event bus is null"}; }
        if (cadence_ < std::chrono::milliseconds{1000})
        {
            throw std::invalid_argument{"cadence must be >= 1s for system-safety"};
        }
    }

    // Rule of 5 — disallow copy; enable move ----------------------------------
    ContinuousScanStrategy(const ContinuousScanStrategy&)            = delete;
    ContinuousScanStrategy& operator=(const ContinuousScanStrategy&) = delete;
    ContinuousScanStrategy(ContinuousScanStrategy&&)                 = default;
    ContinuousScanStrategy& operator=(ContinuousScanStrategy&&)      = default;
    ~ContinuousScanStrategy() override { stop(); }

    // IScanStrategy -----------------------------------------------------------
    void start() override
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true))
        {
            return; // Already running, silently ignore.
        }

        workerThread_ = std::thread([self = shared_from_this()] { self->runLoop(); });
    }

    void stop() override
    {
        bool expected = true;
        if (!running_.compare_exchange_strong(expected, false))
        {
            return; // Not running, nothing to do.
        }

        {
            std::lock_guard<std::mutex> lk(cvMutex_);
            // Unlock quickly after notifying to avoid potential deadlocks.
        }
        cv_.notify_all();

        if (workerThread_.joinable())
        {
            workerThread_.join();
        }
    }

    bool isRunning() const override { return running_.load(); }

    std::string name() const override { return "ContinuousScanStrategy"; }

    // Public API --------------------------------------------------------------
    void changeCadence(std::chrono::milliseconds newCadence)
    {
        if (newCadence < std::chrono::milliseconds{1000})
        {
            throw std::invalid_argument{"cadence must be >= 1s for system-safety"};
        }
        {
            std::lock_guard<std::mutex> lk(cvMutex_);
            cadence_ = newCadence;
        }
        cv_.notify_all(); // Wake up worker so new cadence takes effect promptly.
    }

private:
    // Internal run-loop --------------------------------------------------------
    void runLoop()
    {
        while (running_)
        {
            const auto now = std::chrono::steady_clock::now();
            executeOneScanSafely();

            std::unique_lock<std::mutex> lk(cvMutex_);
            // Wait until either stop() is invoked or the cadence elapses.
            cv_.wait_until(lk, now + cadence_, [this] { return !running_; });
        }
    }

    void executeOneScanSafely()
    {
        try
        {
            const auto result = scanner_->scanOnce(tenantId_);
            publishScanOutcome(result);
        }
        catch (const std::exception& ex)
        {
            publishScanFailure(ex);
        }
        catch (...)
        {
            publishScanFailure(std::runtime_error{"Unknown scanning error"});
        }
    }

    void publishScanOutcome(const ScanResult& result) const
    {
        const std::string topic   = "Scanner.ScanCompleted";
        const std::string payload = result.toJson();
        bus_->publish(topic, payload);
    }

    void publishScanFailure(const std::exception& ex) const
    {
        std::ostringstream oss;
        oss << R"({"success":false,"error":")" << ex.what() << "\"}";
        bus_->publish("Scanner.ScanFailed", oss.str());
    }

private:
    // State -------------------------------------------------------------------
    const std::string               tenantId_;
    std::chrono::milliseconds       cadence_;
    std::shared_ptr<IScannerService> scanner_;
    std::shared_ptr<IEventBus>       bus_;

    std::atomic<bool>  running_ {false};
    mutable std::mutex cvMutex_;
    std::condition_variable cv_;
    std::thread        workerThread_;
};

} // namespace fortiledger::domain::strategies
```