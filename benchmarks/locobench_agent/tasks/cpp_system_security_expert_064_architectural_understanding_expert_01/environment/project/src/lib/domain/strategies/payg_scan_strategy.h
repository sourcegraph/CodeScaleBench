#pragma once
/***************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File        : payg_scan_strategy.h
 *  License     : Proprietary, All Rights Reserved
 *  Author      : FortiLedger360 Engineering
 *
 *  Description :
 *      Concrete Strategy that implements a “Pay-As-You-Go” (PAYG) billing
 *      model for on-demand vulnerability scans.  Each scan request is
 *      metered and immediately billed back to the tenant once the
 *      operation completes.  The strategy owns a light-weight worker pool
 *      that performs scans asynchronously and supports observers so
 *      that other bounded contexts (e.g. Alerting, Audit) can subscribe
 *      to life-cycle events without tight coupling.
 *
 *      This header is header-only and therefore fully self-contained.
 *      All member functions are defined `inline` to respect the One
 *      Definition Rule (ODR) across multiple translation units.
 ***************************************************************************/

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fortiledger360::domain::strategies
{

/*-------------------------------------------------------------------------*/
/*  General Scan Domain Types                                              */
/*-------------------------------------------------------------------------*/

/*  Priority of the scan request – could drive queue scheduling.           */
enum class ScanPriority : std::uint8_t
{
    Normal = 0,
    High   = 1,
};

/*  Global state of an individual scan operation.                          */
enum class ScanState : std::uint8_t
{
    Pending   = 0,
    Running   = 1,
    Succeeded = 2,
    Failed    = 3,
    Cancelled = 4,
};

/*  Simple POD describing a scan request flowing through the domain.       */
struct ScanRequest
{
    std::string                               tenantId;
    std::string                               assetId;
    std::chrono::system_clock::time_point     requestedAt;
    bool                                      deepScan {false};
    ScanPriority                              priority {ScanPriority::Normal};
};

/*  Outcome of the completed scan.                                          */
struct ScanResult
{
    std::string                           correlationId;
    std::string                           tenantId;
    std::string                           assetId;
    ScanState                             state        {ScanState::Succeeded};
    std::optional<std::string>            errorMessage {};
    std::chrono::milliseconds             duration     {0};
};

/*---------------------------------------------------------------------------*/
/*  Observer concept                                                          */
/*---------------------------------------------------------------------------*/
using ScanObserver = std::function<void (const ScanResult&)>;

/*---------------------------------------------------------------------------*/
/*  Strategy interface                                                        */
/*---------------------------------------------------------------------------*/
class SecurityScanStrategy
{
public:
    virtual ~SecurityScanStrategy() = default;

    /* Returns globally-unique identifier for the strategy (used in DI)  */
    [[nodiscard]] virtual std::string id() const = 0;

    /* Pushes a new scan onto the worker queue. Returns correlation ID.   */
    virtual std::string enqueueScan(const ScanRequest& request) = 0;

    /* Non-blocking poll of a completed result.                           */
    [[nodiscard]] virtual std::optional<ScanResult>
    pollResult(const std::string& correlationId) = 0;

    /* Attempts to cancel a running or queued scan.                       */
    virtual void cancelScan(const std::string& correlationId) = 0;

    /* Registers an observer that is invoked once a scan finishes.        */
    virtual void registerObserver(ScanObserver observer) = 0;
};

/*---------------------------------------------------------------------------*/
/*  Pay-As-You-Go Scan Strategy (header-only)                                 */
/*---------------------------------------------------------------------------*/
class PayGScanStrategy final : public SecurityScanStrategy
{
public:
    /*  Tunables that can be loaded from YAML/JSON at runtime.            */
    struct Config
    {
        std::chrono::milliseconds defaultTimeout  {std::chrono::seconds(30)};
        double                    pricePerDeepScan{0.25};  // USD
        double                    pricePerLightScan{0.10}; // USD
        std::size_t               maxConcurrentScans {4};
    };

    /*  Callback that bills the tenant once the scan completes.           */
    using BillingCallback =
        std::function<void (const std::string& tenantId, double amount)>;

    explicit PayGScanStrategy(
            Config                       cfg           = {},
            BillingCallback              billCb        = nullptr)
        : config_(cfg)
        , billingCb_(std::move(billCb))
        , shutdown_{false}
    {
        spawnWorkers(config_.maxConcurrentScans);
    }

    PayGScanStrategy(const PayGScanStrategy&)            = delete;
    PayGScanStrategy& operator=(const PayGScanStrategy&) = delete;
    PayGScanStrategy(PayGScanStrategy&&)                 = delete;
    PayGScanStrategy& operator=(PayGScanStrategy&&)      = delete;

    ~PayGScanStrategy() override
    {
        /* Graceful shutdown – notify workers, then join. */
        {
            std::lock_guard lock(queueMtx_);
            shutdown_ = true;
        }
        queueCv_.notify_all();
        for (auto &t : workers_) { if (t.joinable()) t.join(); }
    }

    /*-------------------------------------------------------------------*/
    /*  SecurityScanStrategy API                                         */
    /*-------------------------------------------------------------------*/
    [[nodiscard]] std::string id() const override
    {
        return "PAYG_SCANNER_V1";
    }

    std::string enqueueScan(const ScanRequest& request) override
    {
        /* Generate a deterministic UUID-like correlation id. */
        const auto cid = generateCorrelationId();

        {
            std::lock_guard lock(queueMtx_);
            if (shutdown_)
                throw std::runtime_error(
                        "Cannot enqueue scan: strategy shutting down.");
            pending_.emplace(QueueItem{cid, request});
        }
        queueCv_.notify_one();
        return cid;
    }

    std::optional<ScanResult>
    pollResult(const std::string& correlationId) override
    {
        std::lock_guard lock(resultMtx_);
        if (auto it = completed_.find(correlationId);
            it != completed_.end())
        {
            auto result = std::move(it->second);
            completed_.erase(it);
            return result;
        }
        return std::nullopt;
    }

    void cancelScan(const std::string& correlationId) override
    {
        {
            /* Quick pass – remove from pending queue if not yet started. */
            std::lock_guard lock(queueMtx_);
            if (cancelPendingLocked(correlationId))
            {
                return; // Already removed & notified observers.
            }
        }

        /* If already running, flag it for cancellation. */
        std::lock_guard lock(cancelMtx_);
        cancelled_.insert(correlationId);
    }

    void registerObserver(ScanObserver observer) override
    {
        std::lock_guard lock(obsMtx_);
        observers_.push_back(std::move(observer));
    }

private:
    /*-------------------------------------------------------------------*/
    /*  Internal Queue/Threading                                         */
    /*-------------------------------------------------------------------*/
    struct QueueItem
    {
        std::string correlationId;
        ScanRequest request;

        /* Highest priority first – normal > high => comparator reversed. */
        bool operator<(const QueueItem& rhs) const noexcept
        {
            return static_cast<int>(request.priority) <
                   static_cast<int>(rhs.request.priority);
        }
    };

    void spawnWorkers(std::size_t poolSize)
    {
        for (std::size_t i = 0; i < poolSize; ++i)
        {
            workers_.emplace_back([this] { workerLoop(); });
        }
    }

    void workerLoop()
    {
        while (true)
        {
            QueueItem item;
            {
                std::unique_lock lock(queueMtx_);
                queueCv_.wait(lock, [this]
                {
                    return shutdown_ || !pending_.empty();
                });

                if (shutdown_ && pending_.empty())
                    break;

                item = pending_.top();
                pending_.pop();
            }

            executeScan(item);
        }
    }

    /*-------------------------------------------------------------------*/
    /*  Scan Execution Logic                                              */
    /*-------------------------------------------------------------------*/
    void executeScan(const QueueItem& item)
    {
        const auto startedAt = std::chrono::steady_clock::now();
        ScanResult result;
        result.correlationId = item.correlationId;
        result.tenantId      = item.request.tenantId;
        result.assetId       = item.request.assetId;
        result.state         = ScanState::Running;

        /*  Simulated long-running scan; we simply sleep for demo.        */
        const auto simulatedDuration =
            item.request.deepScan ? std::chrono::seconds(5)
                                  : std::chrono::seconds(2);

        auto sleepUntil       = std::chrono::steady_clock::now()
                              + simulatedDuration;
        bool wasCancelled     = false;

        while (std::chrono::steady_clock::now() < sleepUntil)
        {
            {
                std::lock_guard lock(cancelMtx_);
                if (cancelled_.erase(item.correlationId) > 0)
                {
                    wasCancelled = true;
                    break;
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        /* Populate result. */
        result.duration = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - startedAt);

        if (wasCancelled)
        {
            result.state = ScanState::Cancelled;
            result.errorMessage = "Scan cancelled by user.";
        }
        else
        {
            /* 50/50 chance of “failure” to illustrate states. */
            if (randomBool(0.1))
            {
                result.state = ScanState::Failed;
                result.errorMessage = "Simulated vulnerability scan error.";
            }
            else
            {
                result.state = ScanState::Succeeded;
            }
        }

        /* Store into completed map for polling. */
        {
            std::lock_guard lock(resultMtx_);
            completed_.emplace(result.correlationId, result);
        }

        /* Trigger billing if applicable and succeeded. */
        if (billingCb_ && result.state == ScanState::Succeeded)
        {
            const double amount =
                item.request.deepScan ? config_.pricePerDeepScan
                                      : config_.pricePerLightScan;
            billingCb_(result.tenantId, amount);
        }

        /* Notify observers – executed outside locks. */
        notifyObservers(result);
    }

    /*-------------------------------------------------------------------*/
    /*  Utilities                                                         */
    /*-------------------------------------------------------------------*/
    static std::string generateCorrelationId()
    {
        thread_local std::mt19937_64 rng{std::random_device{}()};
        std::uniform_int_distribution<std::uint64_t> dist;
        std::uint64_t part1 = dist(rng);
        std::uint64_t part2 = dist(rng);
        char buffer[33];
        std::snprintf(buffer, sizeof(buffer), "%016llx%016llx",
                      static_cast<unsigned long long>(part1),
                      static_cast<unsigned long long>(part2));
        return {buffer, 32};
    }

    static bool randomBool(double trueProbability = 0.5)
    {
        thread_local std::mt19937 rng{std::random_device{}()};
        std::bernoulli_distribution dist{trueProbability};
        return dist(rng);
    }

    bool cancelPendingLocked(const std::string& correlationId)
    {
        /* Because std::priority_queue offers no iterator, rebuild pile. */
        std::priority_queue<QueueItem> newQueue;
        bool found = false;

        while (!pending_.empty())
        {
            auto item = pending_.top();
            pending_.pop();

            if (item.correlationId == correlationId)
            {
                /* Create immediate cancellation result. */
                ScanResult result;
                result.correlationId = item.correlationId;
                result.tenantId      = item.request.tenantId;
                result.assetId       = item.request.assetId;
                result.state         = ScanState::Cancelled;
                result.errorMessage  = "Scan cancelled before execution.";
                result.duration      = std::chrono::milliseconds{0};

                {
                    std::lock_guard lock(resultMtx_);
                    completed_.emplace(result.correlationId, result);
                }

                notifyObservers(result);
                found = true;
                continue;
            }
            newQueue.push(std::move(item));
        }
        std::swap(pending_, newQueue);
        return found;
    }

    void notifyObservers(const ScanResult& result)
    {
        std::vector<ScanObserver> snapshot;
        {
            std::lock_guard lock(obsMtx_);
            snapshot = observers_;
        }
        for (auto& obs : snapshot)
        {
            try
            {
                obs(result);
            }
            catch (...)
            {
                /* Observer must never crash the domain process. */
            }
        }
    }

    /*-------------------------------------------------------------------*/
    /*  Member Data                                                       */
    /*-------------------------------------------------------------------*/
    Config                    config_;
    BillingCallback           billingCb_;

    /* Worker pool. */
    std::vector<std::thread>  workers_;
    std::atomic<bool>         shutdown_;

    /* Pending queue (priority). */
    std::priority_queue<QueueItem> pending_;
    std::mutex                      queueMtx_;
    std::condition_variable         queueCv_;

    /* Completed map. */
    std::unordered_map<std::string, ScanResult> completed_;
    std::mutex                                 resultMtx_;

    /* Cancellation bookkeeping. */
    std::unordered_set<std::string> cancelled_;
    std::mutex                      cancelMtx_;

    /* Observers. */
    std::vector<ScanObserver> observers_;
    std::mutex                obsMtx_;
};

} // namespace fortiledger360::domain::strategies