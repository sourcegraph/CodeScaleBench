```cpp
/**
 *  FortiLedger360 – Alert-Broker micro-service
 *  --------------------------------------------------
 *  cmd/alert_broker_svc/main.cpp
 *
 *  This process is responsible for:
 *    • Subscribing to the FortiLedger360 internal event-bus for
 *      Alert* domain-events (SecurityBreachDetected, SLABreachImminent …).
 *    • Enriching & normalising the events.
 *    • Routing the alert to the proper notification back-ends
 *      (e-mail, Slack, PagerDuty, Splunk, etc.) based on tenant SLA.
 *    • Persisting a lightweight audit-trail for post-mortem analysis.
 *
 *  The implementation below purposefully hides the heavy-weight
 *  integrations behind narrow interfaces, keeping main() focused on
 *  composition, life-cycle management and coarse error-handling.
 *
 *  Build (example):
 *      g++ -std=c++20 -O2 -pthread main.cpp -o alert_broker_svc
 *
 *  External single-header dependencies:
 *      • spdlog (https://github.com/gabime/spdlog)
 *      • nlohmann::json (https://github.com/nlohmann/json)
 *
 *  Both are header-only; simply make sure the headers are available
 *  on the compiler’s include path.
 */

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <random>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>

using json = nlohmann::json;
using namespace std::chrono_literals;

/* ────────────────────────────────────────────────────────────────────────── */
/*                                Domain Types                               */
/* ────────────────────────────────────────────────────────────────────────── */

enum class Severity : std::uint8_t
{
    Info = 0,
    Warning,
    Error,
    Critical
};

std::string_view to_string(Severity s) noexcept
{
    switch (s)
    {
        case Severity::Info:     return "INFO";
        case Severity::Warning:  return "WARN";
        case Severity::Error:    return "ERROR";
        case Severity::Critical: return "CRITICAL";
    }
    return "UNKNOWN";
}

struct AlertEvent
{
    std::string   id;          // ULID/UUID
    std::string   tenantId;
    Severity      severity;
    std::string   category;    // e.g., "SecurityScan", "Backup"
    std::string   description;
    std::int64_t  epochMs;
    json          metadata;    // free-form
};

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Notification API                             */
/* ────────────────────────────────────────────────────────────────────────── */

class INotifier
{
public:
    virtual ~INotifier()                                    = default;
    virtual std::string_view name()                 const   = 0;
    virtual void send(const AlertEvent& evt)                = 0;
};

using NotifierPtr = std::unique_ptr<INotifier>;

/* Dummy e-mail delivery */
class EmailNotifier final : public INotifier
{
public:
    explicit EmailNotifier(std::string smtpEndpoint)
        : _smtpEndpoint(std::move(smtpEndpoint)) {}

    std::string_view name() const noexcept override { return "email"; }

    void send(const AlertEvent& evt) override
    {
        // In production this method would push on an SMTP relay queue
        spdlog::info("[EMAIL]  ➜  Tenant={} Sev={} ‑ {}", evt.tenantId,
                     to_string(evt.severity), evt.description);
        _simulate_network_latency();
    }

private:
    void _simulate_network_latency() { std::this_thread::sleep_for(50ms); }

    std::string _smtpEndpoint;
};

class SlackNotifier final : public INotifier
{
public:
    explicit SlackNotifier(std::string apiToken)
        : _apiToken(std::move(apiToken)) {}

    std::string_view name() const noexcept override { return "slack"; }

    void send(const AlertEvent& evt) override
    {
        spdlog::info("[SLACK]  ➜  Tenant={} Sev={} ‑ {}", evt.tenantId,
                     to_string(evt.severity), evt.description);
        _simulate_network_latency();
    }

private:
    void _simulate_network_latency() { std::this_thread::sleep_for(40ms); }

    std::string _apiToken;
};

class PagerDutyNotifier final : public INotifier
{
public:
    explicit PagerDutyNotifier(std::string routingKey)
        : _routingKey(std::move(routingKey)) {}

    std::string_view name() const noexcept override { return "pagerduty"; }

    void send(const AlertEvent& evt) override
    {
        spdlog::info("[PDUTY]  ➜  Tenant={} Sev={} ‑ {}", evt.tenantId,
                     to_string(evt.severity), evt.description);
        _simulate_network_latency();
    }

private:
    void _simulate_network_latency() { std::this_thread::sleep_for(70ms); }

    std::string _routingKey;
};

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Configuration                                */
/* ────────────────────────────────────────────────────────────────────────── */

struct TenantProfile
{
    std::string                    id;
    std::vector<std::string>       channels;     // ex: { "email", "slack" }
    Severity                       minSeverity;  // threshold
};

struct BrokerConfig
{
    std::string                                instanceName;
    std::unordered_map<std::string, TenantProfile> tenants; // tenantId -> profile
    std::unordered_map<std::string, json>      notifierCfg; // "email" -> { cfg… }
};

BrokerConfig loadConfig(const std::filesystem::path& path)
{
    if (!std::filesystem::exists(path))
        throw std::runtime_error("Configuration file not found: " + path.string());

    std::ifstream in(path);
    if (!in.is_open())
        throw std::runtime_error("Cannot open configuration file: " + path.string());

    json root = json::parse(in, nullptr, true, true);

    BrokerConfig cfg;
    cfg.instanceName = root.value("instance", "alert-broker-dev");

    // Load notifiers
    if (root.contains("notifiers"))
    {
        for (auto&& [k, v] : root["notifiers"].items())
        {
            cfg.notifierCfg.emplace(k, v);
        }
    }

    // Load tenant profiles
    if (root.contains("tenants"))
    {
        for (auto&& jTenant : root["tenants"])
        {
            TenantProfile p;
            p.id          = jTenant.at("id").get<std::string>();
            p.channels    = jTenant.at("channels").get<std::vector<std::string>>();
            p.minSeverity = static_cast<Severity>(jTenant.value("minSeverity", 0U));

            cfg.tenants.emplace(p.id, std::move(p));
        }
    }

    return cfg;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                Repository                                 */
/* ────────────────────────────────────────────────────────────────────────── */

class IAlertAuditRepository
{
public:
    virtual ~IAlertAuditRepository()                                = default;
    virtual void save(const AlertEvent& evt)                        = 0;
};

/* naïve in-memory audit-trail – production system would write to Postgres */
class InMemoryAuditRepository final : public IAlertAuditRepository
{
public:
    void save(const AlertEvent& evt) override
    {
        std::scoped_lock lk(_mtx);
        _events.emplace_back(evt);
    }

    std::size_t size() const
    {
        std::scoped_lock lk(_mtx);
        return _events.size();
    }

private:
    mutable std::mutex      _mtx;
    std::vector<AlertEvent> _events;
};

/* ────────────────────────────────────────────────────────────────────────── */
/*                                 Bus Stub                                  */
/* ────────────────────────────────────────────────────────────────────────── */

/**
 * Very thin wrapper that mocks an async event-bus subscription.
 * In integration/production this would bind to NATS / Kafka / AMQP.
 */
class MockEventBus
{
public:
    using Callback = std::function<void(const AlertEvent&)>;

    explicit MockEventBus(Callback cb)
        : _callback(std::move(cb)), _running(false)
    {}

    void start()
    {
        _running.store(true);
        _worker = std::thread([this] { this->_produceLoop(); });
    }

    void stop()
    {
        _running.store(false);
        if (_worker.joinable())
            _worker.join();
    }

private:
    void _produceLoop()
    {
        std::mt19937_64 prng{ std::random_device{}() };
        std::uniform_int_distribution<int> sevDist(0, 3);
        std::uniform_int_distribution<int> tenantDist(1, 3);
        std::uniform_int_distribution<int> sleepMs(100, 500);

        while (_running.load())
        {
            AlertEvent evt;
            evt.id          = std::to_string(prng());
            evt.tenantId    = "tenant-" + std::to_string(tenantDist(prng));
            evt.severity    = static_cast<Severity>(sevDist(prng));
            evt.category    = "MockCategory";
            evt.description = "Simulated event from bus";
            evt.epochMs     = static_cast<std::int64_t>(
                                std::chrono::duration_cast<std::chrono::milliseconds>(
                                    std::chrono::system_clock::now().time_since_epoch()).count());

            _callback(evt);

            std::this_thread::sleep_for(std::chrono::milliseconds(sleepMs(prng)));
        }
    }

    Callback            _callback;
    std::atomic_bool    _running;
    std::thread         _worker;
};

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Application                                 */
/* ────────────────────────────────────────────────────────────────────────── */

class AlertBrokerService
{
public:
    explicit AlertBrokerService(BrokerConfig cfg)
        : _config(std::move(cfg)),
          _auditRepo(std::make_unique<InMemoryAuditRepository>())
    {
        _initNotifiers();
    }

    void start()
    {
        spdlog::info("Starting Alert-Broker instance '{}'", _config.instanceName);
        _bus = std::make_unique<MockEventBus>(
            [this](const AlertEvent& evt) { this->handleEvent(evt); });
        _bus->start();
    }

    void stop()
    {
        spdlog::info("Stopping Alert-Broker …");
        if (_bus) _bus->stop();
        spdlog::info("Flushing audit-trail ({} events).", _auditRepo->size());
    }

    /* Consumes alerts as they arrive from the Event-Bus */
    void handleEvent(const AlertEvent& evt)
    {
        auto tenantIt = _config.tenants.find(evt.tenantId);
        if (tenantIt == _config.tenants.end())
        {
            spdlog::warn("No tenant-profile found for '{}'; dropping alert.", evt.tenantId);
            return;
        }

        const TenantProfile& profile = tenantIt->second;
        if (static_cast<std::uint8_t>(evt.severity) < static_cast<std::uint8_t>(profile.minSeverity))
        {
            spdlog::debug("Alert under threshold for tenant '{}'; skipped.", evt.tenantId);
            return;
        }

        // Persist before fan-out
        _auditRepo->save(evt);

        // Dispatch
        for (const std::string& channel : profile.channels)
        {
            auto it = _notifiers.find(channel);
            if (it == _notifiers.end())
            {
                spdlog::error("No notifier configured for channel '{}'", channel);
                continue;
            }

            try
            {
                it->second->send(evt);
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Notifier '{}' failed: {}", channel, ex.what());
            }
        }
    }

private:
    void _initNotifiers()
    {
        for (const auto& [channel, cfg] : _config.notifierCfg)
        {
            if (channel == "email")
            {
                std::string smtp = cfg.value("smtp", "localhost");
                _notifiers.emplace(channel, std::make_unique<EmailNotifier>(smtp));
            }
            else if (channel == "slack")
            {
                std::string token = cfg.value("token", "");
                _notifiers.emplace(channel, std::make_unique<SlackNotifier>(token));
            }
            else if (channel == "pagerduty")
            {
                std::string key = cfg.value("routingKey", "");
                _notifiers.emplace(channel, std::make_unique<PagerDutyNotifier>(key));
            }
            else
            {
                spdlog::warn("Unknown notifier type '{}'; ignored.", channel);
            }
        }
    }

    BrokerConfig                                          _config;
    std::unordered_map<std::string, NotifierPtr>          _notifiers;
    std::unique_ptr<MockEventBus>                         _bus;
    std::unique_ptr<IAlertAuditRepository>                _auditRepo;
};

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Main Routine                                */
/* ────────────────────────────────────────────────────────────────────────── */

namespace
{
    std::atomic_bool g_terminate = false;

    void signalHandler(int signum)
    {
        spdlog::info("Received signal {}; shutting down …", signum);
        g_terminate.store(true);
    }
}

int main(int argc, char* argv[])
{
    try
    {
        // ── Set-up logger ---------------------------------------------------
        auto logger = spdlog::stdout_color_mt("console");
        spdlog::set_level(spdlog::level::info);
        spdlog::set_pattern("%^[%Y-%m-%d %T.%e] [%l] %v%$");

        // ── Parse CLI args --------------------------------------------------
        const std::filesystem::path cfgPath =
            (argc > 1) ? argv[1] : "./alert-broker.json";

        spdlog::info("Loading configuration from '{}'", cfgPath.string());
        BrokerConfig cfg = loadConfig(cfgPath);

        // ── Compose application --------------------------------------------
        AlertBrokerService svc{ std::move(cfg) };

        // ── OS signal handling ---------------------------------------------
        std::signal(SIGINT,  signalHandler);
        std::signal(SIGTERM, signalHandler);

        // ── Run -------------------------------------------------------------
        svc.start();
        while (!g_terminate.load()) {
            std::this_thread::sleep_for(200ms);
        }
        svc.stop();
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("Fatal: {}", ex.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
```