```cpp
/*****************************************************************************************
 *  File:    cardio_insight_360/src/ingestion/connectors/fhir_http_listener.cpp
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      Lightweight HTTP listener for ingesting FHIR-compliant resources (JSON) via REST.
 *      The component validates minimal FHIR semantics, forwards the payload to the internal
 *      Kafka-backed event bus, and publishes runtime metrics to the monitoring subsystem.
 *
 *  Dependencies:
 *      – C++17 Standard Library
 *      – cpp-httplib      (https://github.com/yhirose/cpp-httplib)          – HTTP server
 *      – nlohmann/json    (https://github.com/nlohmann/json)               – JSON parsing
 *      – spdlog           (https://github.com/gabime/spdlog)               – Logging
 *      – librdkafka++     (https://github.com/edenhill/librdkafka)         – Kafka client
 *
 *  Build flags (example):
 *      g++ -std=c++17 -Wall -Wextra -pedantic -pthread \
 *          fhir_http_listener.cpp -lrdkafka++ -lrdkafka -o fhir_listener
 *****************************************************************************************/

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <future>
#include <memory>
#include <regex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>

#include <httplib.h>                   // cpp-httplib (single-header)
#include <nlohmann/json.hpp>           // nlohmann::json
#include <rdkafkacpp.h>                // librdkafka C++ API
#include <spdlog/spdlog.h>             // spdlog

namespace ci360::ingestion::connectors {

// ------------------------------------------------------------------------------------------------
//          Utility Types
// ------------------------------------------------------------------------------------------------
using json = nlohmann::json;

struct ListenerConfig {
    std::string bind_address  = "0.0.0.0";
    uint16_t    port          = 8080;
    size_t      http_threads  = std::thread::hardware_concurrency();
    std::string kafka_brokers = "localhost:9092";
    std::string kafka_topic   = "fhir_raw_ingest";
    std::chrono::seconds graceful_timeout { 10 };
};

// ------------------------------------------------------------------------------------------------
//          Kafka Producer Wrapper with RAII
// ------------------------------------------------------------------------------------------------
class KafkaProducer final {
public:
    explicit KafkaProducer(const ListenerConfig& cfg)
    {
        // Global configuration
        std::string errstr;
        std::unique_ptr<RdKafka::Conf, void (*)(RdKafka::Conf*)> conf(
            RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL), [](RdKafka::Conf* c) { delete c; });

        if (!conf) throw std::runtime_error("Failed to create Kafka global conf");

        if (conf->set("bootstrap.servers", cfg.kafka_brokers, errstr) != RdKafka::Conf::CONF_OK) {
            throw std::runtime_error("Kafka config error: " + errstr);
        }
        if (conf->set("enable.idempotence", "true", errstr) != RdKafka::Conf::CONF_OK) {
            spdlog::warn("Unable to enable idempotence: {}", errstr);
        }

        producer_.reset(RdKafka::Producer::create(conf.get(), errstr));
        if (!producer_) {
            throw std::runtime_error("Failed to create Kafka producer: " + errstr);
        }

        topic_ = cfg.kafka_topic;
        spdlog::info("Kafka producer initialized (brokers='{}', topic='{}')",
                     cfg.kafka_brokers,
                     topic_);
    }

    ~KafkaProducer()
    {
        if (producer_) {
            spdlog::info("Flushing Kafka producer…");
            producer_->flush(10'000);
        }
    }

    // Non-copyable, Movable
    KafkaProducer(const KafkaProducer&) = delete;
    KafkaProducer& operator=(const KafkaProducer&) = delete;
    KafkaProducer(KafkaProducer&&) noexcept       = default;
    KafkaProducer& operator=(KafkaProducer&&) noexcept = default;

    bool publish(const std::string& key, const std::string& payload) noexcept
    {
        if (!producer_) return false;

        auto err = producer_->produce(topic_,
                                      RdKafka::Topic::PARTITION_UA,
                                      RdKafka::Producer::RK_MSG_COPY /* message flags */,
                                      const_cast<char*>(payload.data()),
                                      payload.size(),
                                      key.empty() ? nullptr : &key,
                                      key.empty() ? 0 : key.size(),
                                      0,
                                      nullptr);
        if (err != RdKafka::ErrorCode::ERR_NO_ERROR) {
            spdlog::error("Kafka delivery error: {}", RdKafka::err2str(err));
            return false;
        }
        producer_->poll(0); // Serve delivery reports
        return true;
    }

private:
    std::unique_ptr<RdKafka::Producer> producer_;
    std::string                        topic_;
};

// ------------------------------------------------------------------------------------------------
//          FHIR HTTP Listener
// ------------------------------------------------------------------------------------------------
class FhirHttpListener {
public:
    explicit FhirHttpListener(ListenerConfig cfg)
        : cfg_(std::move(cfg))
        , kafka_(cfg_)
        , server_(std::make_unique<httplib::Server>())
    {
        configure_routes();
        server_->new_task_queue = [this] {
            return new httplib::ThreadPool(cfg_.http_threads);
        };
    }

    // Start listener – blocks until stop() is called from another thread
    void start()
    {
        spdlog::info("Starting FHIR HTTP Listener at {}:{}", cfg_.bind_address, cfg_.port);
        running_.store(true);
        // Run server (blocking)
        if (!server_->listen(cfg_.bind_address.c_str(), cfg_.port)) {
            running_.store(false);
            throw std::runtime_error("Failed to bind HTTP listener to address");
        }
    }

    // Stop listener gracefully
    void stop()
    {
        if (!running_.exchange(false)) return; // already stopped
        spdlog::info("Stopping FHIR HTTP Listener …");
        server_->stop();
        // Allow time for in-flight requests
        std::this_thread::sleep_for(cfg_.graceful_timeout);
        spdlog::info("FHIR HTTP Listener stopped");
    }

private:
    // ----------------------------------------------------------------------------------------
    //      Internal Helpers
    // ----------------------------------------------------------------------------------------
    void configure_routes()
    {
        using namespace std::placeholders;

        // Generic endpoint for any FHIR resource type
        server_->Post(R"(/fhir/([A-Za-z]+))",
                      std::bind(&FhirHttpListener::handle_fhir_post,
                                this,
                                _1, _2, _3)); // req, res, resourceType

        // Liveness / readiness
        server_->Get("/health", [](const httplib::Request&, httplib::Response& res) {
            res.set_content(R"({"status":"ok"})", "application/json");
        });

        // Metrics endpoint – minimalistic Prometheus exposition format
        server_->Get("/metrics", [this](const httplib::Request&, httplib::Response& res) {
            res.set_content(build_metrics_payload(), "text/plain; version=0.0.4");
        });
    }

    void handle_fhir_post(const httplib::Request& req,
                          httplib::Response&      res,
                          const std::string&      resource_type)
    {
        // Basic Content-Type checks
        auto content_type = req.get_header_value("Content-Type");
        if (content_type.find("application/json") == std::string::npos) {
            res.status = 415; // Unsupported Media Type
            return;
        }

        try {
            json payload = json::parse(req.body);

            // Minimal FHIR validation
            if (!payload.contains("resourceType") ||
                payload.at("resourceType").get<std::string>() != resource_type) {
                res.status      = 400;
                res.reason      = "Invalid resourceType";
                metrics_.invalid_requests++;
                return;
            }

            // Extract natural key (when available) for Kafka partitioning
            std::string key;
            if (payload.contains("id")) {
                key = payload.at("id").get<std::string>();
            }

            // Publish to Kafka
            if (!kafka_.publish(key, req.body)) {
                res.status      = 500;
                res.reason      = "Internal Kafka error";
                metrics_.kafka_failures++;
                return;
            }

            res.status           = 202;
            res.set_content(R"({"status":"accepted"})", "application/json");
            metrics_.accepted_requests++;
        } catch (const json::parse_error& e) {
            spdlog::warn("JSON parsing error: {}", e.what());
            res.status           = 400;
            res.reason           = "Malformed JSON";
            metrics_.invalid_requests++;
        } catch (const std::exception& e) {
            spdlog::error("Unhandled exception in handler: {}", e.what());
            res.status           = 500;
            metrics_.internal_errors++;
        }
    }

    // Build simple Prometheus metrics exposition
    std::string build_metrics_payload() const
    {
        std::ostringstream oss;
        oss << "# HELP fhir_listener_requests_total Total number of HTTP POST /fhir requests\n"
            << "# TYPE fhir_listener_requests_total counter\n"
            << "fhir_listener_requests_total{status=\"accepted\"} "
            << metrics_.accepted_requests.load() << '\n'
            << "fhir_listener_requests_total{status=\"invalid\"} "
            << metrics_.invalid_requests.load() << '\n'
            << "fhir_listener_requests_total{status=\"kafka_failure\"} "
            << metrics_.kafka_failures.load() << '\n'
            << "fhir_listener_requests_total{status=\"internal_error\"} "
            << metrics_.internal_errors.load() << '\n';
        return oss.str();
    }

private:
    ListenerConfig                cfg_;
    KafkaProducer                 kafka_;
    std::unique_ptr<httplib::Server> server_;
    std::atomic<bool>             running_ { false };

    struct Metrics {
        std::atomic<uint64_t> accepted_requests  { 0 };
        std::atomic<uint64_t> invalid_requests   { 0 };
        std::atomic<uint64_t> kafka_failures     { 0 };
        std::atomic<uint64_t> internal_errors    { 0 };
    } metrics_;
};

// ------------------------------------------------------------------------------------------------
//          Convenience launcher (optional)
// ------------------------------------------------------------------------------------------------
#if defined(FHIR_LISTENER_STANDALONE)
int main(int argc, char* argv[])
{
    try {
        ListenerConfig cfg;

        if (const char* env = std::getenv("FHIR_LISTENER_PORT"))
            cfg.port = static_cast<uint16_t>(std::stoi(env));
        if (const char* env = std::getenv("FHIR_KAFKA_BROKERS"))
            cfg.kafka_brokers = env;
        if (const char* env = std::getenv("FHIR_KAFKA_TOPIC"))
            cfg.kafka_topic = env;

        ci360::ingestion::connectors::FhirHttpListener listener(cfg);

        // Run in separate thread so we can handle SIGINT for graceful shutdown
        std::promise<void> exit_signal;
        auto               server_thread = std::thread([&] {
            listener.start();
            exit_signal.set_value();
        });

        // Handle ^C
        std::signal(SIGINT, +[](int) {
            spdlog::info("SIGINT received, shutting down…");
        });

        // Block until server stopped
        exit_signal.get_future().wait();
        server_thread.join();
    } catch (const std::exception& e) {
        spdlog::critical("Fatal error: {}", e.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
#endif

} // namespace ci360::ingestion::connectors
```