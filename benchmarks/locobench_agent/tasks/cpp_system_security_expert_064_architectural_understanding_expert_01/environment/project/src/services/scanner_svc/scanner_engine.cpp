```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  Module  : Scanner Service
 *  File    : scanner_engine.cpp
 *
 *  Description:
 *  ------------
 *  Implementation of the core vulnerability–scanner engine.  The engine
 *  consumes immutable scan–commands from the message–bus, determines the
 *  correct scanning strategy based on the tenant's subscription plan, and
 *  executes the workload on a cooperative thread–pool.  Observers are
 *  notified on state-changes which, in production, feed Grafana dashboards,
 *  Prometheus exporters, and long-term audit logs.
 *
 *  NOTE:
 *  -----
 *  This file purposefully avoids hard dependencies on the concrete Event-Bus
 *  or gRPC transport.  Those details live behind thin facades in the
 *  Infrastructure layer.  The engine solely focuses on domain behaviour.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

namespace fl360::scanner
{

// ---------------------------------------------------------------------------
// Logging Utility (placeholder until we wire in spdlog or similar)
// ---------------------------------------------------------------------------
enum class LogLevel { kDebug, kInfo, kWarn, kError };

class Logger
{
public:
    explicit Logger(std::ostream &out = std::clog) : out_(out) {}

    template <typename... Args>
    void log(LogLevel lvl, Args &&...args) noexcept
    {
        const char *lvlStr = nullptr;
        switch (lvl)
        {
        case LogLevel::kDebug: lvlStr = "DEBUG"; break;
        case LogLevel::kInfo:  lvlStr = "INFO "; break;
        case LogLevel::kWarn:  lvlStr = "WARN "; break;
        case LogLevel::kError: lvlStr = "ERROR"; break;
        }

        std::lock_guard lk(mu_);
        out_ << "[" << timestamp() << "] [" << lvlStr << "] ";
        (out_ << ... << std::forward<Args>(args)) << '\n';
        out_.flush();
    }

private:
    static std::string timestamp()
    {
        using namespace std::chrono;
        const auto now   = system_clock::now();
        const auto tm    = system_clock::to_time_t(now);
        const auto ms    = duration_cast<milliseconds>(now.time_since_epoch()) % 1000;
        std::ostringstream oss;
        oss << std::put_time(std::localtime(&tm), "%F %T") << '.' << std::setfill('0') << std::setw(3) << ms.count();
        return oss.str();
    }

    std::mutex  mu_;
    std::ostream &out_;
};

// ---------------------------------------------------------------------------
// Domain Model
// ---------------------------------------------------------------------------
enum class ScanIntensity { kLight, kDeep };

struct ScanCommand
{
    std::string  tenantId;
    std::string  resourceId;
    ScanIntensity intensity   {ScanIntensity::kLight};
    std::chrono::system_clock::time_point issuedAt {std::chrono::system_clock::now()};
};

struct ScanResult
{
    std::string  tenantId;
    std::string  resourceId;
    std::size_t  findings;        // Number of detected issues
    std::chrono::milliseconds duration;
    bool         success;
    std::string  failureReason;
};

// ---------------------------------------------------------------------------
// Observer Pattern
// ---------------------------------------------------------------------------
enum class EngineEvent
{
    kScanStarted,
    kScanFinished,
    kScanFailed
};

class IEngineObserver
{
public:
    virtual ~IEngineObserver()                                      = default;
    virtual void onEvent(EngineEvent ev, const ScanCommand &cmd,
                         const std::optional<ScanResult> &res) = 0;
};

// ---------------------------------------------------------------------------
// Strategy Pattern
// ---------------------------------------------------------------------------
class IScanStrategy
{
public:
    virtual ~IScanStrategy() = default;
    virtual ScanResult execute(const ScanCommand &cmd) = 0;
};

class LightScanStrategy final : public IScanStrategy
{
public:
    explicit LightScanStrategy(Logger &log) : log_(log) {}

    ScanResult execute(const ScanCommand &cmd) override
    {
        log_.log(LogLevel::kDebug, "[LightScan] Tenant=", cmd.tenantId, " Resource=", cmd.resourceId);
        auto begin = std::chrono::steady_clock::now();

        // Simulate a quick port scan & config diff
        std::this_thread::sleep_for(std::chrono::milliseconds(250 + rand() % 150));

        ScanResult res;
        res.tenantId  = cmd.tenantId;
        res.resourceId= cmd.resourceId;
        res.findings  = rand() % 3; // Few findings expected
        res.success   = true;
        res.duration  = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - begin);
        return res;
    }

private:
    Logger &log_;
};

class DeepScanStrategy final : public IScanStrategy
{
public:
    explicit DeepScanStrategy(Logger &log) : log_(log) {}

    ScanResult execute(const ScanCommand &cmd) override
    {
        log_.log(LogLevel::kDebug, "[DeepScan] Tenant=", cmd.tenantId, " Resource=", cmd.resourceId);
        auto begin = std::chrono::steady_clock::now();

        // Simulate heavy CVE DB lookup, full file system scan, etc.
        std::this_thread::sleep_for(std::chrono::seconds(1 + rand() % 2));

        ScanResult res;
        res.tenantId  = cmd.tenantId;
        res.resourceId= cmd.resourceId;
        res.findings  = 5 + rand() % 42;
        res.success   = true;
        res.duration  = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - begin);
        return res;
    }

private:
    Logger &log_;
};

// ---------------------------------------------------------------------------
// Thread-safe Queue
// ---------------------------------------------------------------------------
template <typename T>
class BlockingQueue
{
public:
    explicit BlockingQueue(std::size_t max) : capacity_(max) {}

    void push(T item)
    {
        std::unique_lock lk(mu_);
        cvFull_.wait(lk, [&] { return queue_.size() < capacity_; });
        queue_.push(std::move(item));
        cvEmpty_.notify_one();
    }

    bool pop(T &out)
    {
        std::unique_lock lk(mu_);
        cvEmpty_.wait(lk, [&] { return !queue_.empty() || terminated_; });
        if (queue_.empty()) return false; // terminated
        out = std::move(queue_.front());
        queue_.pop();
        cvFull_.notify_one();
        return true;
    }

    void terminate()
    {
        {
            std::lock_guard lg(mu_);
            terminated_ = true;
        }
        cvEmpty_.notify_all();
    }

private:
    std::size_t                capacity_;
    std::queue<T>              queue_;
    std::mutex                 mu_;
    std::condition_variable    cvFull_, cvEmpty_;
    bool                       terminated_ {false};
};

// ---------------------------------------------------------------------------
// Scanner Engine (Command, Strategy, Observer, Concurrency)
// ---------------------------------------------------------------------------
class ScannerEngine
{
public:
    explicit ScannerEngine(std::size_t workerCount = std::thread::hardware_concurrency())
        : queue_(1024), log_(), shuttingDown_(false)
    {
        workerCount = std::max<std::size_t>(1, workerCount);
        log_.log(LogLevel::kInfo, "Initializing ScannerEngine with ", workerCount, " workers.");

        for (std::size_t i = 0; i < workerCount; ++i)
        {
            workers_.emplace_back([this, i] { workerLoop(i); });
        }
    }

    ~ScannerEngine()
    {
        shutdown();
    }

    // Non-copyable
    ScannerEngine(const ScannerEngine &)            = delete;
    ScannerEngine &operator=(const ScannerEngine &) = delete;

    void submit(const ScanCommand &cmd)
    {
        if (shuttingDown_.load()) throw std::runtime_error("Engine is shutting down");
        queue_.push(cmd);
    }

    void registerObserver(std::shared_ptr<IEngineObserver> obs)
    {
        if (!obs) return;
        std::lock_guard lk(obsMu_);
        observers_.push_back(std::move(obs));
    }

    void shutdown()
    {
        bool expected = false;
        if (!shuttingDown_.compare_exchange_strong(expected, true))
            return; // already called

        log_.log(LogLevel::kInfo, "ScannerEngine shutting down...");
        queue_.terminate();

        for (auto &t : workers_)
            if (t.joinable()) t.join();

        log_.log(LogLevel::kInfo, "All worker threads joined.");
    }

private:
    void workerLoop(std::size_t idx)
    {
        try
        {
            while (true)
            {
                ScanCommand cmd;
                if (!queue_.pop(cmd)) break; // queue terminated

                notify(EngineEvent::kScanStarted, cmd, std::nullopt);

                auto strategy = makeStrategy(cmd.intensity);

                ScanResult res;
                try
                {
                    res = strategy->execute(cmd);
                    notify(EngineEvent::kScanFinished, cmd, res);
                }
                catch (const std::exception &ex)
                {
                    res.success       = false;
                    res.failureReason = ex.what();
                    notify(EngineEvent::kScanFailed, cmd, res);
                    log_.log(LogLevel::kError, "Worker#", idx, " failed: ", ex.what());
                }
            }
        }
        catch (const std::exception &e)
        {
            log_.log(LogLevel::kError, "Critical error in worker#", idx, ": ", e.what());
        }
    }

    std::unique_ptr<IScanStrategy> makeStrategy(ScanIntensity in)
    {
        switch (in)
        {
        case ScanIntensity::kLight: return std::make_unique<LightScanStrategy>(log_);
        case ScanIntensity::kDeep:  return std::make_unique<DeepScanStrategy>(log_);
        }
        throw std::invalid_argument("Unknown intensity");
    }

    void notify(EngineEvent ev, const ScanCommand &cmd,
                const std::optional<ScanResult> &res)
    {
        std::vector<std::shared_ptr<IEngineObserver>> snapshot;
        {
            std::lock_guard lg(obsMu_);
            snapshot = observers_;
        }
        for (auto &o : snapshot)
        {
            try
            {
                o->onEvent(ev, cmd, res);
            }
            catch (const std::exception &e)
            {
                log_.log(LogLevel::kWarn, "Observer threw: ", e.what());
            }
        }
    }

private:
    BlockingQueue<ScanCommand>                  queue_;
    std::vector<std::thread>                    workers_;
    std::vector<std::shared_ptr<IEngineObserver>> observers_;
    std::mutex                                  obsMu_;
    Logger                                      log_;
    std::atomic_bool                            shuttingDown_;
};

// ---------------------------------------------------------------------------
// Sample Observer(s) to demonstrate behaviour
// ---------------------------------------------------------------------------
class ConsoleObserver final : public IEngineObserver
{
public:
    explicit ConsoleObserver(Logger &log) : log_(log) {}

    void onEvent(EngineEvent ev, const ScanCommand &cmd,
                 const std::optional<ScanResult> &res) override
    {
        switch (ev)
        {
        case EngineEvent::kScanStarted:
            log_.log(LogLevel::kInfo, "[Observer] Scan started for ", cmd.resourceId);
            break;
        case EngineEvent::kScanFinished:
            log_.log(LogLevel::kInfo, "[Observer] Scan finished (", res->findings,
                     " findings, took ", res->duration.count(), "ms)");
            break;
        case EngineEvent::kScanFailed:
            log_.log(LogLevel::kWarn, "[Observer] Scan failed: ", res->failureReason);
            break;
        }
    }

private:
    Logger &log_;
};

// ---------------------------------------------------------------------------
// Public API (factory function)
// ---------------------------------------------------------------------------
std::unique_ptr<ScannerEngine> makeScannerEngine()
{
    return std::make_unique<ScannerEngine>();
}

} // namespace fl360::scanner

// ---------------------------------------------------------------------------
// If compiled standalone, provide a trivial main() for quick smoke test
// (Will be omitted/ignored when compiled as part of the overall suite.)
// ---------------------------------------------------------------------------
#ifdef FL360_SCANNER_STANDALONE
int main()
{
    using namespace fl360::scanner;

    auto engine = makeScannerEngine();
    Logger l;
    engine->registerObserver(std::make_shared<ConsoleObserver>(l));

    for (int i = 0; i < 5; ++i)
    {
        ScanCommand cmd;
        cmd.tenantId   = "tenant-" + std::to_string(i % 2);
        cmd.resourceId = "res-" + std::to_string(i);
        cmd.intensity  = (i % 2 == 0) ? ScanIntensity::kLight : ScanIntensity::kDeep;
        engine->submit(cmd);
    }

    std::this_thread::sleep_for(std::chrono::seconds(5));
    engine->shutdown();
}
#endif
```