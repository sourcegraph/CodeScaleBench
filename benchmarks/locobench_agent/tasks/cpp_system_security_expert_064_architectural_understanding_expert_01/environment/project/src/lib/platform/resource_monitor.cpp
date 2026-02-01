#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

/*
 * FortiLedger360 Enterprise Security Suite
 * Platform Layer – Resource Monitor
 *
 * This compilation unit provides a lightweight, thread–safe resource monitor
 * that periodically samples host-level CPU, memory and network utilisation
 * from the Linux /proc pseudo-filesystem.  Fresh samples are delivered to
 * interested parties via an Observer-style callback registry, allowing higher
 * layers (Metrics service, Alerting engine, Prometheus exporter, …) to react
 * in near real-time without tight coupling to the sampling logic.
 *
 * The implementation is self-contained so that no header is required.
 * This is deliberate: ResourceMonitor is consumed only inside the Platform
 * layer and does not form part of any public API exposed to upper layers.
 *
 * The code adheres to C++17 and is warning-clean under ‑Wall ‑Wextra ‑pedantic.
 */

namespace fortiledger::platform
{

//----------------------------------------------------------------------
// Utility: minimal logger (compile-time switch to spdlog if present)
//----------------------------------------------------------------------

#if defined(FORTILEDGER_USE_SPDLOG)
    #include <spdlog/spdlog.h>
    #define FL360_LOG_INFO(...)  spdlog::info(__VA_ARGS__)
    #define FL360_LOG_WARN(...)  spdlog::warn(__VA_ARGS__)
    #define FL360_LOG_ERROR(...) spdlog::error(__VA_ARGS__)
#else
namespace detail
{
    template <typename... Args>
    void log_impl(const char* level, const char* fmt, Args&&... args)
    {
        std::ostringstream oss;
        (oss << ... << std::forward<Args>(args));
        std::lock_guard<std::mutex> lk{log_mtx()};
        std::cerr << "[" << timestamp() << "] [" << level << "] " << oss.str()
                  << '\n';
    }

    inline std::mutex& log_mtx()
    {
        static std::mutex m;
        return m;
    }
    inline std::string timestamp()
    {
        const auto now   = std::chrono::system_clock::now();
        const auto tt    = std::chrono::system_clock::to_time_t(now);
        std::tm tm_buf{};
        localtime_r(&tt, &tm_buf);

        std::ostringstream oss;
        oss << std::put_time(&tm_buf, "%F %T");
        return oss.str();
    }
} // namespace detail

#define FL360_LOG_INFO(...)  ::fortiledger::platform::detail::log_impl("INFO", __VA_ARGS__)
#define FL360_LOG_WARN(...)  ::fortiledger::platform::detail::log_impl("WARN", __VA_ARGS__)
#define FL360_LOG_ERROR(...) ::fortiledger::platform::detail::log_impl("ERROR", __VA_ARGS__)
#endif // FORTILEDGER_USE_SPDLOG

//----------------------------------------------------------------------
// Resource types
//----------------------------------------------------------------------

struct ResourceSample
{
    std::chrono::system_clock::time_point timestamp;

    // CPU: percentage utilisation [0-100]
    double cpu_usage_percent = 0.0;

    // Memory: kilobytes
    std::uint64_t mem_total_kb = 0;
    std::uint64_t mem_used_kb  = 0;

    // Network: cumulative bytes since boot
    std::uint64_t net_rx_bytes = 0;
    std::uint64_t net_tx_bytes = 0;
};

inline std::ostream& operator<<(std::ostream& os, const ResourceSample& s)
{
    const auto time_t = std::chrono::system_clock::to_time_t(s.timestamp);
    std::tm tm_buf{};
    localtime_r(&time_t, &tm_buf);

    char time_buf[32];
    strftime(time_buf, sizeof time_buf, "%F %T", &tm_buf);

    os << "[@" << time_buf << "] CPU=" << s.cpu_usage_percent << "%, "
       << "Mem=" << s.mem_used_kb << " / " << s.mem_total_kb << " KiB, "
       << "NetRx=" << s.net_rx_bytes << " B, "
       << "NetTx=" << s.net_tx_bytes << " B";
    return os;
}

//----------------------------------------------------------------------
// Observer interface (type-erased via std::function)
//----------------------------------------------------------------------

using ObserverCallback = std::function<void(const ResourceSample&)>;

//----------------------------------------------------------------------
// Configuration
//----------------------------------------------------------------------

struct ResourceMonitorConfig
{
    std::chrono::milliseconds sampling_interval{1000};

    // Whether to emit samples to the internal log as well
    bool log_samples = false;
};

//----------------------------------------------------------------------
// ResourceMonitor
//----------------------------------------------------------------------

class ResourceMonitor
{
public:
    explicit ResourceMonitor(ResourceMonitorConfig cfg = {})
        : cfg_{cfg}
    {
    }

    ~ResourceMonitor() { stop(); }

    // Non-copyable / non-movable
    ResourceMonitor(const ResourceMonitor&)            = delete;
    ResourceMonitor& operator=(const ResourceMonitor&) = delete;

    // Register an observer; returns a token that can later be used to unsubscribe.
    // Thread-safe.
    std::size_t subscribe(ObserverCallback cb)
    {
        std::lock_guard<std::mutex> lock{obs_mtx_};
        const auto id = ++last_id_;
        observers_.emplace(id, std::move(cb));
        return id;
    }

    // Unregister an observer; no-op if id is invalid. Thread-safe.
    void unsubscribe(std::size_t id)
    {
        std::lock_guard<std::mutex> lock{obs_mtx_};
        observers_.erase(id);
    }

    // Launch background sampling thread. Safe to call multiple times; subsequent
    // calls are ignored until stop() is invoked.
    void start()
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true))
            return; // already running

        worker_ = std::thread([this] { run(); });
    }

    // Stop background thread and block until it exits.
    void stop()
    {
        bool expected = true;
        if (!running_.compare_exchange_strong(expected, false))
            return; // not running

        if (worker_.joinable())
            worker_.join();
    }

private:
    //=======================   Sampling loop   ========================//

    void run()
    {
        FL360_LOG_INFO("ResourceMonitor started (interval={} ms)",
                       cfg_.sampling_interval.count());

        try
        {
            while (running_)
            {
                const auto start = std::chrono::steady_clock::now();
                ResourceSample sample = collect_sample();
                notify_observers(sample);

                if (cfg_.log_samples)
                    FL360_LOG_INFO("{}", sample);

                const auto elapsed = std::chrono::steady_clock::now() - start;
                const auto sleep_for =
                    cfg_.sampling_interval -
                    std::chrono::duration_cast<std::chrono::milliseconds>(
                        elapsed);

                if (sleep_for.count() > 0)
                    std::this_thread::sleep_for(sleep_for);
            }
        }
        catch (const std::exception& ex)
        {
            FL360_LOG_ERROR("ResourceMonitor terminated abnormally: {}", ex.what());
        }
        catch (...)
        {
            FL360_LOG_ERROR("ResourceMonitor terminated due to unknown error");
        }

        FL360_LOG_INFO("ResourceMonitor stopped");
    }

    //=======================   Data acquisition   =====================//

    ResourceSample collect_sample()
    {
        ResourceSample s;
        s.timestamp          = std::chrono::system_clock::now();
        s.cpu_usage_percent  = sample_cpu_usage();
        std::tie(s.mem_total_kb, s.mem_used_kb) = sample_mem_usage();
        std::tie(s.net_rx_bytes, s.net_tx_bytes) = sample_net_usage();
        return s;
    }

    // CPU ----------------------------------------------------------------
    struct CpuTimes
    {
        std::uint64_t user   = 0;
        std::uint64_t nice   = 0;
        std::uint64_t system = 0;
        std::uint64_t idle   = 0;
        std::uint64_t iowait = 0;
        std::uint64_t irq    = 0;
        std::uint64_t softirq= 0;
        std::uint64_t steal  = 0;

        std::uint64_t total() const
        {
            return user + nice + system + idle + iowait + irq + softirq + steal;
        }

        std::uint64_t work() const
        {
            return user + nice + system + irq + softirq + steal;
        }
    };

    static std::optional<CpuTimes> read_cpu_times()
    {
        std::ifstream fs("/proc/stat");
        if (!fs)
            return std::nullopt;

        std::string cpu_label;
        CpuTimes t;
        fs >> cpu_label >> t.user >> t.nice >> t.system >> t.idle
           >> t.iowait >> t.irq >> t.softirq >> t.steal;
        if (cpu_label != "cpu")
            return std::nullopt;
        return t;
    }

    double sample_cpu_usage()
    {
        const auto now = read_cpu_times();
        if (!now)
        {
            FL360_LOG_WARN("Failed to read /proc/stat");
            return 0.0;
        }

        double usage = 0.0;
        {
            std::lock_guard<std::mutex> lock{cpu_mtx_};
            if (prev_cpu_)
            {
                const auto diff_total = now->total() - prev_cpu_->total();
                const auto diff_work  = now->work()  - prev_cpu_->work();

                if (diff_total != 0)
                    usage = 100.0 * diff_work / diff_total;
            }
            prev_cpu_ = *now;
        }
        return usage;
    }

    // Memory -----------------------------------------------------------
    static std::pair<std::uint64_t, std::uint64_t> sample_mem_usage()
    {
        std::ifstream fs("/proc/meminfo");
        if (!fs)
        {
            FL360_LOG_WARN("Failed to read /proc/meminfo");
            return {0, 0};
        }

        std::unordered_map<std::string, std::uint64_t> kv;
        std::string key;
        std::uint64_t value;
        std::string unit;
        while (fs >> key >> value >> unit)
        {
            // key contains trailing ':'
            key.pop_back();
            kv[key] = value; // values are in KiB
        }

        const auto total = kv["MemTotal"];
        const auto avail = kv["MemAvailable"];
        const auto used  = (avail > total) ? 0 : (total - avail);
        return {total, used};
    }

    // Network ----------------------------------------------------------
    static std::pair<std::uint64_t, std::uint64_t> sample_net_usage()
    {
        std::ifstream fs("/proc/net/dev");
        if (!fs)
        {
            FL360_LOG_WARN("Failed to read /proc/net/dev");
            return {0, 0};
        }

        std::string line;
        // skip headers (two lines)
        std::getline(fs, line);
        std::getline(fs, line);

        std::uint64_t rx = 0;
        std::uint64_t tx = 0;
        while (std::getline(fs, line))
        {
            std::istringstream iss(line);
            std::string iface;
            if (!(iss >> iface))
                continue;

            if (iface == "lo:" || iface.find("lo:") != std::string::npos)
                continue; // ignore loopback

            // iface string ends with ':'
            std::uint64_t iface_rx, iface_tx;
            // columns: Rx bytes packets errs drop fifo frame compressed multicast
            // then Tx bytes ...
            if (!(iss >> iface_rx))
                continue;

            // skip 7 columns
            for (int i = 0; i < 7; ++i)
                iss.ignore(std::numeric_limits<std::streamsize>::max(), ' ');

            if (!(iss >> iface_tx))
                continue;

            rx += iface_rx;
            tx += iface_tx;
        }
        return {rx, tx};
    }

    //==========================   Notify   =============================//

    void notify_observers(const ResourceSample& s)
    {
        std::lock_guard<std::mutex> lock{obs_mtx_};

        // Iterate on a copy to avoid iterator invalidation if observers unsubscribe
        const auto observers = observers_;
        for (const auto& [id, cb] : observers)
        {
            try
            {
                cb(s);
            }
            catch (const std::exception& ex)
            {
                FL360_LOG_WARN("Observer {} threw exception: {}", id, ex.what());
            }
            catch (...)
            {
                FL360_LOG_WARN("Observer {} threw unknown exception", id);
            }
        }
    }

    //==========================   Members   ============================//

    ResourceMonitorConfig cfg_;

    std::atomic<bool> running_{false};
    std::thread        worker_;

    std::mutex                                   obs_mtx_;
    std::unordered_map<std::size_t, ObserverCallback> observers_;
    std::atomic<std::size_t>                     last_id_{0};

    std::mutex       cpu_mtx_;
    std::optional<CpuTimes> prev_cpu_;
};

//----------------------------------------------------------------------
// Example usage (can be removed in production builds)
//----------------------------------------------------------------------

#ifdef FORTILEDGER_BUILD_DEMO_MAIN
int main()
{
    ResourceMonitorConfig cfg;
    cfg.sampling_interval = std::chrono::milliseconds{2000};
    cfg.log_samples       = true;

    fortiledger::platform::ResourceMonitor rm{cfg};

    // Push metrics to console
    const auto token = rm.subscribe(
        [](const ResourceSample& s) { std::cout << s << '\n'; });

    rm.start();

    std::this_thread::sleep_for(std::chrono::seconds{10});
    rm.unsubscribe(token);
    rm.stop();

    return 0;
}
#endif

} // namespace fortiledger::platform