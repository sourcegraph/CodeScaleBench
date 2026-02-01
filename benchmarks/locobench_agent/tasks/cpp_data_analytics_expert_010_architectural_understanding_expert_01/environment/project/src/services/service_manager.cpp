```cpp
/**
 * File: cardio_insight_360/src/services/service_manager.cpp
 *
 * Description:
 *  A central orchestrator responsible for the lifecycle management of all
 *  in-process “pseudo-microservices” (Scheduling, Error-Recovery, Visualization, etc.)
 *  compiled into CardioInsight360’s monolithic binary.
 *
 *  The ServiceManager transparently handles:
 *    • Dependency injection & lazy instantiation of services
 *    • Concurrent start-up / shut-down sequencing
 *    • Health-check polling and automatic restart policies
 *    • Thread-safe access and metric emission hooks
 *
 *  NOTE:
 *  In the real code-base, concrete service implementations live in dedicated
 *  translation units (e.g. scheduling_service.cpp).  For demonstration purposes,
 *  minimal skeletons are provided here behind feature-guard
 *  CI360_SERVICE_MANAGER_DEMO to keep this file self-contained.
 */

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>  // Production-grade logging

//------------------------------------------------------------------------------
//  Namespace
//------------------------------------------------------------------------------
namespace ci360 {

//==============================================================================
//  Interface: IService
//==============================================================================
class IService
{
public:
    IService()          = default;
    virtual ~IService() = default;

    // Service display name (unique, human-readable)
    virtual const std::string& name() const noexcept = 0;

    // Called during initialization – must return quickly
    virtual void start()                                         = 0;

    // Graceful shutdown – may block until resources released
    virtual void stop()                                          = 0;

    // Indicates operational state (thread-safe)
    virtual bool isRunning() const noexcept                      = 0;

    // Lightweight health-check (<= 50 ms) – throws on failure
    virtual void ping()                                          = 0;
};

//==============================================================================
//  Forward declarations of concrete services (demo stubs)
//==============================================================================
#ifdef CI360_SERVICE_MANAGER_DEMO

class SchedulingService final : public IService
{
public:
    SchedulingService() : _running(false) {}

    const std::string& name() const noexcept override
    {
        static const std::string kName { "SchedulingService" };
        return kName;
    }

    void start() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (_running) return;

        _running = true;
        _worker  = std::thread([this] {
            spdlog::info("[{}] started", name());
            while (_running)
            {
                std::this_thread::sleep_for(std::chrono::seconds(1)); // placeholder
            }
        });
    }

    void stop() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (!_running) return;

        _running = false;
        if (_worker.joinable()) _worker.join();
        spdlog::info("[{}] stopped", name());
    }

    bool isRunning() const noexcept override { return _running.load(); }

    void ping() override
    {
        if (!_running) throw std::runtime_error(name() + " not running");
    }

private:
    std::atomic<bool> _running;
    std::thread       _worker;
    mutable std::mutex _mtx;
};

class ErrorRecoveryService final : public IService
{
public:
    ErrorRecoveryService() : _running(false) {}

    const std::string& name() const noexcept override
    {
        static const std::string kName { "ErrorRecoveryService" };
        return kName;
    }

    void start() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (_running) return;
        _running = true;
        _worker  = std::thread([this] {
            spdlog::info("[{}] started", name());
            while (_running)
            {
                std::this_thread::sleep_for(std::chrono::seconds(2));
            }
        });
    }

    void stop() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (!_running) return;
        _running = false;
        if (_worker.joinable()) _worker.join();
        spdlog::info("[{}] stopped", name());
    }

    bool isRunning() const noexcept override { return _running.load(); }

    void ping() override
    {
        if (!_running) throw std::runtime_error(name() + " not running");
    }

private:
    std::atomic<bool> _running;
    std::thread       _worker;
    mutable std::mutex _mtx;
};

class VisualizationService final : public IService
{
public:
    VisualizationService() : _running(false) {}

    const std::string& name() const noexcept override
    {
        static const std::string kName { "VisualizationService" };
        return kName;
    }

    void start() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (_running) return;
        _running = true;
        _worker  = std::thread([this] {
            spdlog::info("[{}] started", name());
            while (_running)
            {
                std::this_thread::sleep_for(std::chrono::seconds(3));
            }
        });
    }

    void stop() override
    {
        std::lock_guard<std::mutex> lock(_mtx);
        if (!_running) return;
        _running = false;
        if (_worker.joinable()) _worker.join();
        spdlog::info("[{}] stopped", name());
    }

    bool isRunning() const noexcept override { return _running.load(); }

    void ping() override
    {
        if (!_running) throw std::runtime_error(name() + " not running");
    }

private:
    std::atomic<bool> _running;
    std::thread       _worker;
    mutable std::mutex _mtx;
};

#endif // CI360_SERVICE_MANAGER_DEMO

//==============================================================================
//  Class: ServiceManager
//==============================================================================
class ServiceManager
{
public:
    ServiceManager()  = default;
    ~ServiceManager() { safeShutdown(); }

    ServiceManager(const ServiceManager&)            = delete;
    ServiceManager& operator=(const ServiceManager&) = delete;
    ServiceManager(ServiceManager&&)                 = delete;
    ServiceManager& operator=(ServiceManager&&)      = delete;

    // Register a service factory – ownership transferred to ServiceManager
    template <typename TService, typename... TArgs>
    void registerService(TArgs&&... args)
    {
        static_assert(std::is_base_of<IService, TService>::value,
                      "TService must implement IService");

        auto svc = std::make_unique<TService>(std::forward<TArgs>(args)...);
        const auto& svcName = svc->name();

        std::unique_lock<std::shared_mutex> lock(_rwMtx);
        if (_services.count(svcName))
        {
            throw std::logic_error("Service already registered: " + svcName);
        }

        _services.emplace(svcName, std::move(svc));
        spdlog::debug("Service [{}] registered", svcName);
    }

    // Start all registered services concurrently
    void startAll()
    {
        std::shared_lock<std::shared_mutex> readLock(_rwMtx);
        spdlog::info("Starting {} services ...", _services.size());

        std::vector<std::future<void>> futures;
        futures.reserve(_services.size());

        for (auto& kv : _services)
        {
            futures.emplace_back(std::async(std::launch::async, [&kv] {
                try
                {
                    kv.second->start();
                }
                catch (const std::exception& ex)
                {
                    spdlog::error("Failed to start [{}]: {}", kv.first, ex.what());
                }
            }));
        }

        for (auto& f : futures) f.wait();
        spdlog::info("All services started");
    }

    // Stop all services concurrently
    void stopAll()
    {
        std::shared_lock<std::shared_mutex> readLock(_rwMtx);
        spdlog::info("Stopping all services ...");
        std::vector<std::future<void>> futures;
        futures.reserve(_services.size());

        for (auto& kv : _services)
        {
            futures.emplace_back(std::async(std::launch::async, [&kv] {
                try
                {
                    kv.second->stop();
                }
                catch (const std::exception& ex)
                {
                    spdlog::error("Failed to stop [{}]: {}", kv.first, ex.what());
                }
            }));
        }

        for (auto& f : futures) f.wait();
        spdlog::info("All services stopped");
    }

    // Health-check loop (non-blocking) – returns unhealthy service names
    std::vector<std::string> pollHealth() const
    {
        std::shared_lock<std::shared_mutex> readLock(_rwMtx);

        std::vector<std::string> unhealthy;
        unhealthy.reserve(_services.size());

        for (auto& kv : _services)
        {
            try
            {
                kv.second->ping();
            }
            catch (const std::exception&)
            {
                unhealthy.push_back(kv.first);
            }
        }
        return unhealthy;
    }

    // Attempt to restart a single service by name
    void restart(const std::string& serviceName)
    {
        std::shared_lock<std::shared_mutex> readLock(_rwMtx);

        auto it = _services.find(serviceName);
        if (it == _services.end())
            throw std::invalid_argument("Unknown service: " + serviceName);

        spdlog::warn("Restarting [{}] ...", serviceName);
        try
        {
            it->second->stop();
            it->second->start();
            spdlog::info("[{}] successfully restarted", serviceName);
        }
        catch (const std::exception& ex)
        {
            spdlog::error("[{}] restart failed: {}", serviceName, ex.what());
            throw; // propagate for higher-level handling
        }
    }

    // Provides read-only pointer for external observers/metrics
    std::shared_ptr<const IService> getService(const std::string& serviceName) const
    {
        std::shared_lock<std::shared_mutex> readLock(_rwMtx);

        auto it = _services.find(serviceName);
        if (it == _services.end()) return {};

        // Wrap raw pointer in shared_ptr with no-op deleter (caller holds non-owning ref)
        return { it->second.get(), [](const IService*) {} };
    }

private:
    void safeShutdown() noexcept
    {
        try
        {
            stopAll();
        }
        catch (const std::exception& ex)
        {
            spdlog::critical("ServiceManager destructor caught exception: {}", ex.what());
        }
    }

    mutable std::shared_mutex                                _rwMtx;  // protects _services
    std::unordered_map<std::string, std::unique_ptr<IService>> _services;
};

//==============================================================================
//  Entry point for demo / unit tests (remove for production build)
//==============================================================================
#ifdef CI360_SERVICE_MANAGER_DEMO
int main()
{
    spdlog::set_level(spdlog::level::debug);

    ServiceManager mgr;
    mgr.registerService<SchedulingService>();
    mgr.registerService<ErrorRecoveryService>();
    mgr.registerService<VisualizationService>();

    mgr.startAll();

    // Simulate runtime loop
    for (int i = 0; i < 5; ++i)
    {
        auto unhealthy = mgr.pollHealth();
        if (!unhealthy.empty())
        {
            for (auto& name : unhealthy) mgr.restart(name);
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    mgr.stopAll();
    return 0;
}
#endif // CI360_SERVICE_MANAGER_DEMO

} // namespace ci360
```