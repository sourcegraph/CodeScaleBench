```cpp
/**
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * File: cardio_insight_360/src/main.cpp
 *
 * The main entry-point boot-straps the monolithic analytics engine,
 * configures all sub-systems, and blocks the foreground thread until
 * an OS signal requests a graceful shutdown.
 *
 * Build:
 *   g++ -std=c++17 -O2 -pthread main.cpp -ltbb -lspdlog
 */

#include <atomic>
#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <future>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

// 3rd-party, header-only
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <tbb/flow_graph.h>

// ──────────────────────────────────────────────────────────────────────────────
// Utility helpers
// ──────────────────────────────────────────────────────────────────────────────
namespace util {

[[nodiscard]] std::string read_file(const std::filesystem::path& p) {
    std::ifstream ifs(p, std::ios::in | std::ios::binary);
    if (!ifs)
        throw std::runtime_error("Failed to open file: " + p.string());

    return {std::istreambuf_iterator<char>{ifs}, std::istreambuf_iterator<char>{}};
}

} // namespace util

// ──────────────────────────────────────────────────────────────────────────────
// Configuration
// ──────────────────────────────────────────────────────────────────────────────
class Config final {
public:
    static std::shared_ptr<Config> load(const std::filesystem::path& path) {
        auto cfg = std::shared_ptr<Config>(new Config());
        cfg->raw_ = nlohmann::json::parse(util::read_file(path));
        cfg->path_ = path;
        return cfg;
    }

    [[nodiscard]] const nlohmann::json& raw() const noexcept { return raw_; }

    template <typename T>
    [[nodiscard]] T value_or(const std::string& key, T default_value) const {
        return raw_.contains(key) ? raw_.at(key).get<T>() : default_value;
    }

    [[nodiscard]] const std::filesystem::path& source_path() const noexcept {
        return path_;
    }

private:
    Config() = default;
    nlohmann::json             raw_;
    std::filesystem::path      path_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Event Bus – thin wrapper around librdkafka (mocked here)
// ──────────────────────────────────────────────────────────────────────────────
class EventBus final {
public:
    explicit EventBus(const nlohmann::json& cfg) {
        (void)cfg; // would pass settings to librdkafka
        spdlog::info("EventBus initialized [mock]");
    }

    void publish(const std::string& topic, const std::string& payload) {
        spdlog::trace("[EventBus] → {} | {} bytes", topic, payload.size());
        // librdkafka producer would push here
    }

    void subscribe(const std::string& topic,
                   std::function<void(const std::string&)> cb) {
        // In a real implementation we'd spin a consumer thread
        // Only stubbed for illustration
        spdlog::info("[EventBus] Subscribed to topic '{}'", topic);
        callbacks_.push_back(std::move(cb));
    }

    void tick_mock() {
        for (auto& cb : callbacks_) cb("{\"mock\":true}");
    }

private:
    std::vector<std::function<void(const std::string&)>> callbacks_;
};

// ──────────────────────────────────────────────────────────────────────────────
// DataLake façade – persists raw & curated data (mock)
// ──────────────────────────────────────────────────────────────────────────────
class DataLake final {
public:
    explicit DataLake(const nlohmann::json& cfg) {
        root_ = cfg.value("root_dir", "/var/lib/cardioinsight360/datalake");
        std::filesystem::create_directories(root_);
        spdlog::info("DataLake mounted at {}", root_);
    }

    void write_raw(const std::string& feed, std::string_view bytes) {
        auto p = std::filesystem::path(root_) / "raw" / feed;
        std::filesystem::create_directories(p.parent_path());
        std::ofstream ofs(p, std::ios::binary | std::ios::app);
        ofs.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    }

    void write_curated(const std::string& cohort, const nlohmann::json& obj) {
        auto p = std::filesystem::path(root_) / "curated" / (cohort + ".json");
        std::filesystem::create_directories(p.parent_path());
        std::ofstream ofs(p, std::ios::app);
        ofs << obj.dump() << '\n';
    }

private:
    std::string root_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Strategy Pattern – signal transformation policies
// ──────────────────────────────────────────────────────────────────────────────
class TransformationStrategy {
public:
    virtual ~TransformationStrategy() = default;
    virtual nlohmann::json transform(const nlohmann::json&) = 0;
};

class ECGTransformation final : public TransformationStrategy {
public:
    nlohmann::json transform(const nlohmann::json& in) override {
        nlohmann::json out = in;
        // Perform domain-specific transformation (mock)
        out["transformed"] = true;
        spdlog::debug("ECGTransformation applied");
        return out;
    }
};

class StrategyRegistry {
public:
    static StrategyRegistry& instance() {
        static StrategyRegistry inst;
        return inst;
    }

    void register_strategy(const std::string& signal,
                           std::unique_ptr<TransformationStrategy> strat) {
        registry_[signal] = std::move(strat);
    }

    TransformationStrategy* get(const std::string& signal) {
        if (registry_.count(signal)) return registry_[signal].get();
        return nullptr;
    }

private:
    StrategyRegistry() = default;
    std::unordered_map<std::string, std::unique_ptr<TransformationStrategy>>
        registry_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Observer Pattern – runtime metrics
// ──────────────────────────────────────────────────────────────────────────────
struct MetricEvent {
    std::string name;
    double      value;
};

class MetricsObserver {
public:
    virtual ~MetricsObserver()            = default;
    virtual void on_metric(MetricEvent e) = 0;
};

class MetricsHub {
public:
    void subscribe(std::shared_ptr<MetricsObserver> obs) {
        observers_.push_back(std::move(obs));
    }

    void publish(MetricEvent e) const {
        for (auto& o : observers_) o->on_metric(e);
    }

private:
    std::vector<std::shared_ptr<MetricsObserver>> observers_;
};

// Simple console metrics sink
class ConsoleMetricsObserver final : public MetricsObserver {
public:
    void on_metric(MetricEvent e) override {
        spdlog::info("[Metric] {} = {}", e.name, e.value);
    }
};

// ──────────────────────────────────────────────────────────────────────────────
// ETL Pipeline – built on Intel TBB flow_graph
// ──────────────────────────────────────────────────────────────────────────────
class ETLPipeline {
public:
    ETLPipeline(EventBus& bus, DataLake& lake, MetricsHub& mh)
        : bus_{bus}, lake_{lake}, metrics_{mh}, g_{} {

        using namespace tbb::flow;

        receiver_node<std::string> source{g_,
            [this](const std::string& payload) -> continue_msg {
                // store raw
                lake_.write_raw("ECG", payload);
                metrics_.publish({"raw_bytes", static_cast<double>(payload.size())});
                return {};
            }
        };

        function_node<continue_msg, nlohmann::json> transform{g_, unlimited,
            [this](const continue_msg&) {
                // mock JSON payload
                nlohmann::json in    = {{"lead", "II"}, {"samples", {1, 2, 3, 4}}};
                auto* strat          = StrategyRegistry::instance().get("ECG");
                auto  transformed    = strat ? strat->transform(in) : in;
                metrics_.publish({"transformed_records", 1.0});
                return transformed;
            }
        };

        function_node<nlohmann::json> sink{g_, unlimited,
            [this](const nlohmann::json& obj) {
                // Persist curated data
                lake_.write_curated("daily_ecg", obj);
            }
        };

        make_edge(source, transform);
        make_edge(transform, sink);

        // Subscribe bus to trigger graph
        bus_.subscribe("ecg.raw", [this, &source](const std::string& payload) {
            source.try_put(payload);
            g_.wait_for_all();
        });
    }

private:
    EventBus&               bus_;
    DataLake&               lake_;
    MetricsHub&             metrics_;
    tbb::flow::graph        g_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Pseudo-Microservices – logical components
// ──────────────────────────────────────────────────────────────────────────────
class Service {
public:
    virtual ~Service()            = default;
    virtual void start()          = 0;
    virtual void shutdown()       = 0;
    [[nodiscard]] virtual bool healthy() const = 0;
};

class SchedulerService final : public Service {
public:
    void start() override {
        worker_ = std::thread([this] {
            spdlog::info("[Scheduler] started");
            while (running_) {
                std::this_thread::sleep_for(std::chrono::seconds{60});
                spdlog::debug("[Scheduler] 60-second heartbeat");
            }
        });
    }

    void shutdown() override {
        running_ = false;
        if (worker_.joinable()) worker_.join();
        spdlog::info("[Scheduler] stopped");
    }

    bool healthy() const override { return running_; }

private:
    std::atomic_bool running_{true};
    std::thread      worker_;
};

// ──────────────────────────────────────────────────────────────────────────────
// Application Orchestrator
// ──────────────────────────────────────────────────────────────────────────────
class Application {
public:
    explicit Application(std::filesystem::path cfg_path)
        : config_{Config::load(cfg_path)} {
        spdlog::info("Loading CardioInsight360 configuration from {}",
                     config_->source_path().string());
    }

    void init() {
        // 1. Logging profile
        spdlog::set_pattern("[%Y-%m-%d %T.%e] [%^%l%$] %v");

        // 2. Strategy registry
        StrategyRegistry::instance().register_strategy("ECG",
            std::make_unique<ECGTransformation>());

        // 3. Sub-systems
        event_bus_  = std::make_unique<EventBus>(config_->raw()["event_bus"]);
        data_lake_  = std::make_unique<DataLake>(config_->raw()["data_lake"]);
        metrics_hub_ = std::make_unique<MetricsHub>();
        metrics_hub_->subscribe(std::make_shared<ConsoleMetricsObserver>());

        // 4. ETL
        etl_ = std::make_unique<ETLPipeline>(*event_bus_, *data_lake_, *metrics_hub_);

        // 5. Services
        scheduler_ = std::make_unique<SchedulerService>();
        scheduler_->start();

        spdlog::info("Initialization complete");
    }

    void run() {
        // In lieu of a real run-loop, we simulate inbound messages
        std::thread producer([this] {
            spdlog::info("Mock producer starting");
            for (int i = 0; i < 10 && running_; ++i) {
                event_bus_->publish("ecg.raw", R"({"mock":"payload"})");
                event_bus_->tick_mock();
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
            }
        });

        // Wait until a signal sets running_ to false
        while (running_) std::this_thread::sleep_for(std::chrono::milliseconds(100));

        if (producer.joinable()) producer.join();
    }

    void stop() {
        running_ = false;
        if (scheduler_) scheduler_->shutdown();
        spdlog::info("Application shutdown complete");
    }

    static void install_signal_handlers(Application& app) {
        ::signal(SIGINT,  [](int) { instance_flag().store(false); });
        ::signal(SIGTERM, [](int) { instance_flag().store(false); });

        // Link flag into the application
        app.running_.store(true);
        app.linked_flag_ = &instance_flag();
    }

private:
    static std::atomic_bool& instance_flag() {
        static std::atomic_bool flag{true};
        return flag;
    }

    std::shared_ptr<Config>        config_;
    std::unique_ptr<EventBus>      event_bus_;
    std::unique_ptr<DataLake>      data_lake_;
    std::unique_ptr<MetricsHub>    metrics_hub_;
    std::unique_ptr<ETLPipeline>   etl_;
    std::unique_ptr<SchedulerService> scheduler_;

    std::atomic_bool*              linked_flag_{nullptr};
    std::atomic_bool               running_{false};
};

// ──────────────────────────────────────────────────────────────────────────────
// Main
// ──────────────────────────────────────────────────────────────────────────────
int main(int argc, char* argv[]) try {
    auto cfg_path = argc > 1 ? argv[1] : "config.json";
    if (!std::filesystem::exists(cfg_path)) {
        std::cerr << "Config file not found: " << cfg_path << '\n';
        return EXIT_FAILURE;
    }

    Application app{cfg_path};
    Application::install_signal_handlers(app);

    app.init();
    app.run();
    app.stop();

    return EXIT_SUCCESS;
} catch (const std::exception& ex) {
    spdlog::critical("Fatal error: {}", ex.what());
    return EXIT_FAILURE;
} catch (...) {
    spdlog::critical("Unknown fatal error");
    return EXIT_FAILURE;
}
```
