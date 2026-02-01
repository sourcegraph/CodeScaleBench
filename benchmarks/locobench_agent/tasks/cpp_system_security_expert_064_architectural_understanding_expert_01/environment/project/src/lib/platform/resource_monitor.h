#ifndef FORTILEDGER360_PLATFORM_RESOURCE_MONITOR_H_
#define FORTILEDGER360_PLATFORM_RESOURCE_MONITOR_H_

/*
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  Resource Monitor (platform layer)
 *
 *  The ResourceMonitor provides an event-driven, thread-safe wrapper around low-level
 *  OS statistics such as CPU, Memory, and Network I/O.  Collected snapshots are
 *  propagated to interested parties (e.g., Metrics micro-service, SLA watchdogs,
 *  capacity-planning engines) via an Observer interface.
 *
 *  Design highlights
 *  -----------------
 *  • Non-blocking – sampling is performed on a dedicated worker thread.
 *  • Observer pattern – zero or more observers can be attached/detached at run-time.
 *  • Exception safety – RAII, scope guards, strong exception guarantee for public API.
 *  • Cross-platform ready – default implementation targets Linux (/proc/*); stubs for
 *    other OSes are provided for graceful degradation.
 *
 *  Copyright 2024 FortiLedger
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <exception>
#include <fstream>
#include <iomanip>
#include <ios>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

namespace fortiledger::platform {

/* ==========================================================================================
 *  Diagnostic helpers
 * ========================================================================================*/

/*!
 * Utility: system_clock to ISO-8601 UTC string
 */
inline std::string to_iso_utc(const std::chrono::system_clock::time_point& tp)
{
    std::time_t t = std::chrono::system_clock::to_time_t(tp);
    std::tm utc_tm;
#if defined(_WIN32)
    gmtime_s(&utc_tm, &t);
#else
    gmtime_r(&t, &utc_tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &utc_tm);
    return buf;
}

/* ==========================================================================================
 *  Public DTO
 * ========================================================================================*/

/*!
 * ResourceSnapshot
 * A lightweight, immutable structure that represents a point-in-time view
 * of local system utilisation metrics.
 */
struct ResourceSnapshot
{
    std::chrono::system_clock::time_point timestamp;
    double                               cpu_percent;     // [0, 100]
    double                               mem_percent;     // [0, 100]
    std::uint64_t                        net_rx_bytes;    // cumulative
    std::uint64_t                        net_tx_bytes;    // cumulative

    std::string to_string() const
    {
        std::ostringstream oss;
        oss << "Snapshot{"
            << "ts=" << to_iso_utc(timestamp)
            << ", cpu=" << std::fixed << std::setprecision(2) << cpu_percent << '%'
            << ", mem=" << mem_percent << '%'
            << ", rx=" << net_rx_bytes
            << ", tx=" << net_tx_bytes
            << '}';
        return oss.str();
    }
};

/* ==========================================================================================
 *  Observer interface
 * ========================================================================================*/

/*!
 * IResourceObserver
 * Clients implement this interface to receive snapshot updates.
 *
 * Implementation note: observers are held via std::weak_ptr in the monitor
 * to avoid reference cycles and to allow automatic deregistration when the
 * client goes out of scope.
 */
class IResourceObserver
{
public:
    virtual ~IResourceObserver()                                  = default;
    virtual void on_resource_update(const ResourceSnapshot& snap) = 0;
};

/* ==========================================================================================
 *  ResourceMonitor
 * ========================================================================================*/

class ResourceMonitor
{
public:
    using milliseconds = std::chrono::milliseconds;

    explicit ResourceMonitor(milliseconds interval = milliseconds{1'000})
        : polling_interval_{interval}
        , running_{false}
    {
        if (interval.count() <= 0)
            throw std::invalid_argument("Polling interval must be > 0 ms");
    }

    ~ResourceMonitor() { stop(); }

    ResourceMonitor(const ResourceMonitor&)            = delete;
    ResourceMonitor& operator=(const ResourceMonitor&) = delete;

    /* ----------------------------------------------------------------------
     *  Lifecycle
     * --------------------------------------------------------------------*/
    void start()
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true))
            return;  // already running

        worker_ = std::thread(&ResourceMonitor::run_loop, this);
    }

    void stop()
    {
        bool expected = true;
        if (!running_.compare_exchange_strong(expected, false))
            return;  // already stopped

        if (worker_.joinable())
            worker_.join();
    }

    /* ----------------------------------------------------------------------
     *  Observer registration
     * --------------------------------------------------------------------*/
    void add_observer(const std::shared_ptr<IResourceObserver>& obs)
    {
        if (!obs)
            throw std::invalid_argument("null observer");

        std::lock_guard lk(obs_mtx_);
        observers_.insert(obs);
    }

    void remove_observer(const std::shared_ptr<IResourceObserver>& obs)
    {
        std::lock_guard lk(obs_mtx_);
        auto it = observers_.find(obs);
        if (it != observers_.end())
            observers_.erase(it);
    }

    /* ----------------------------------------------------------------------
     *  Introspection
     * --------------------------------------------------------------------*/
    milliseconds polling_interval() const noexcept { return polling_interval_; }
    ResourceSnapshot last_snapshot() const noexcept
    {
        std::lock_guard lk(snap_mtx_);
        return last_snapshot_;
    }

private:
    /* ----------------------------------------------------------------------
     *  Core sampling loop
     * --------------------------------------------------------------------*/
    void run_loop() noexcept
    {
        while (running_)
        {
            try
            {
                auto snap = capture_snapshot();
                {
                    std::lock_guard lk(snap_mtx_);
                    last_snapshot_ = snap;
                }
                dispatch_snapshot(snap);
            }
            catch (const std::exception& ex)
            {
                // As a platform component we must never throw; log & continue.
                // In production this should route to a logging facility.
                std::cerr << "ResourceMonitor sampling error: " << ex.what() << '\n';
            }

            std::this_thread::sleep_for(polling_interval_);
        }
    }

    /* ----------------------------------------------------------------------
     *  Snapshot dispatch
     * --------------------------------------------------------------------*/
    void dispatch_snapshot(const ResourceSnapshot& snap)
    {
        std::vector<std::shared_ptr<IResourceObserver>> strong_refs;

        {
            std::lock_guard lk(obs_mtx_);
            // Elevate weak_ptrs to shared_ptrs while pruning expired
            for (auto it = observers_.begin(); it != observers_.end();)
            {
                if (auto sp = it->lock())
                {
                    strong_refs.emplace_back(std::move(sp));
                    ++it;
                }
                else
                {
                    it = observers_.erase(it);
                }
            }
        }

        for (auto& obs : strong_refs)
            obs->on_resource_update(snap);
    }

    /* ----------------------------------------------------------------------
     *  Snapshot acquisition
     * --------------------------------------------------------------------*/
    ResourceSnapshot capture_snapshot()
    {
#if defined(__linux__)
        auto ts = std::chrono::system_clock::now();
        double cpu = read_cpu_percent();
        double mem = read_mem_percent();
        auto   [rx, tx] = read_network_bytes();

        return ResourceSnapshot{ts, cpu, mem, rx, tx};
#else
        throw std::runtime_error("Resource monitoring is currently implemented only for Linux.");
#endif
    }

#if defined(__linux__)
    /* ========================================
     *  Linux-specific metrics
     * ======================================*/

    /*
     * CPU utilisation algorithm
     * -------------------------
     * We sample /proc/stat twice (t0 & t1) 100 ms apart and compute the delta,
     * then scale to percentage.  This yields a near real-time CPU utilisation
     * figure without requiring jiffies configuration knowledge.
     */
    double read_cpu_percent()
    {
        CpuSnapshot s0 = read_proc_stat();
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        CpuSnapshot s1 = read_proc_stat();

        auto delta_used  = (s1.user + s1.nice + s1.system) - (s0.user + s0.nice + s0.system);
        auto delta_total = s1.total() - s0.total();
        if (delta_total == 0)
            return 0.0;

        return 100.0 * static_cast<double>(delta_used) / static_cast<double>(delta_total);
    }

    double read_mem_percent()
    {
        std::ifstream meminfo("/proc/meminfo");
        if (!meminfo)
            throw std::runtime_error("Failed to open /proc/meminfo");

        std::string   key;
        std::uint64_t value = 0;
        std::string   unit;
        std::uint64_t mem_total = 0;
        std::uint64_t mem_free  = 0;
        std::uint64_t buffers   = 0;
        std::uint64_t cached    = 0;

        while (meminfo >> key >> value >> unit)
        {
            if (key == "MemTotal:")
                mem_total = value;
            else if (key == "MemFree:")
                mem_free = value;
            else if (key == "Buffers:")
                buffers = value;
            else if (key == "Cached:")
                cached = value;
        }

        if (mem_total == 0)
            return 0.0;

        auto used = mem_total - (mem_free + buffers + cached);
        return 100.0 * static_cast<double>(used) / static_cast<double>(mem_total);
    }

    std::pair<std::uint64_t, std::uint64_t> read_network_bytes()
    {
        std::ifstream netdev("/proc/net/dev");
        if (!netdev)
            throw std::runtime_error("Failed to open /proc/net/dev");

        std::string line;
        // Skip first two header lines
        std::getline(netdev, line);
        std::getline(netdev, line);

        std::uint64_t rx_total = 0, tx_total = 0;

        while (std::getline(netdev, line))
        {
            auto colon_pos = line.find(':');
            if (colon_pos == std::string::npos)
                continue;

            std::istringstream iss(line.substr(colon_pos + 1));
            std::uint64_t rx_bytes = 0, tx_bytes = 0;
            iss >> rx_bytes;   // Receive bytes
            // Skip fields we don't care about
            for (int i = 0; i < 7; ++i) iss >> std::ws >> line;
            iss >> tx_bytes;   // Transmit bytes

            rx_total += rx_bytes;
            tx_total += tx_bytes;
        }

        return {rx_total, tx_total};
    }

    /* ---------- helper struct ---------*/
    struct CpuSnapshot
    {
        std::uint64_t user = 0;
        std::uint64_t nice = 0;
        std::uint64_t system = 0;
        std::uint64_t idle = 0;
        std::uint64_t iowait = 0;
        std::uint64_t irq = 0;
        std::uint64_t softirq = 0;
        std::uint64_t steal = 0;
        std::uint64_t guest = 0;
        std::uint64_t guest_nice = 0;

        std::uint64_t total() const
        {
            return user + nice + system + idle + iowait + irq + softirq + steal + guest +
                   guest_nice;
        }
    };

    CpuSnapshot read_proc_stat()
    {
        std::ifstream stat("/proc/stat");
        if (!stat)
            throw std::runtime_error("Failed to open /proc/stat");

        std::string line;
        CpuSnapshot snap;
        while (std::getline(stat, line))
        {
            if (line.rfind("cpu ", 0) == 0)
            {
                std::istringstream iss(line);
                std::string cpu_label;
                iss >> cpu_label >> snap.user >> snap.nice >> snap.system >> snap.idle >>
                    snap.iowait >> snap.irq >> snap.softirq >> snap.steal >> snap.guest >>
                    snap.guest_nice;
                break;
            }
        }
        return snap;
    }
#endif  // __linux__

    /* ----------------------------------------------------------------------
     *  Members
     * --------------------------------------------------------------------*/
    milliseconds polling_interval_;

    std::atomic<bool> running_;
    std::thread       worker_;

    mutable std::mutex snap_mtx_;
    ResourceSnapshot   last_snapshot_;

    mutable std::mutex                                              obs_mtx_;
    std::unordered_set<std::weak_ptr<IResourceObserver>,
                       std::owner_less<std::weak_ptr<IResourceObserver>>>
        observers_;
};

}  // namespace fortiledger::platform

#endif  // FORTILEDGER360_PLATFORM_RESOURCE_MONITOR_H_
