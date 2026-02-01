```cpp
/**
 *  FortiLedger360 Enterprise Security Suite
 *  File: cmd/metrics_svc/main.cpp
 *
 *  The Metrics Service is responsible for aggregating and exposing
 *  system-wide performance metrics over gRPC as well as through a
 *  Prometheus-compatible HTTP endpoint. It subscribes to the global
 *  event-bus, persists in-memory counters / gauges, and allows the
 *  FortiLedger360 observability stack to scrape real-time telemetry.
 *
 *  Author: FortiLedger360 Core Platform Team
 *  SPDX-License-Identifier: Apache-2.0
 */

#include <csignal>
#include <cstdlib>
#include <exception>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

#include <grpcpp/grpcpp.h>
#include <prometheus/counter.h>
#include <prometheus/exposer.h>
#include <prometheus/gauge.h>
#include <prometheus/registry.h>
#include <spdlog/spdlog.h>
#include <yaml-cpp/yaml.h>

#include <cxxopts.hpp>

// -----------------------------------------------------------------------------
// Generated from metrics.proto (not included in this snippet)
//
//  service Metrics {
//      rpc Report (MetricSample) returns (Ack);
//  }
//
//  message MetricSample {
//      string name      = 1;
//      double value     = 2;
//      enum Type { COUNTER = 0; GAUGE = 1; } // simplified
//      Type type        = 3;
//      map<string,string> labels = 4;
//  }
//
//  message Ack { bool ok = 1; }
//
// -----------------------------------------------------------------------------
#include "proto/metrics.grpc.pb.h"

namespace fl360::metrics {

// Forward declarations
class MetricsCollector;

// -----------------------------------------------------------------------------
// Utility: Process-wide shutdown flag
// -----------------------------------------------------------------------------
namespace {
std::atomic_bool g_shutdown{false};

void signal_handler(int signum) { g_shutdown.store(true); }
}  // namespace

// -----------------------------------------------------------------------------
// MetricsCollector
// -----------------------------------------------------------------------------
class MetricsCollector final {
public:
    explicit MetricsCollector(std::shared_ptr<prometheus::Registry> registry)
        : registry_{std::move(registry)} {}

    void incrementCounter(const std::string& name,
                          const std::map<std::string, std::string>& labels,
                          double value) {
        auto* ctr = getOrCreateCounter(name, labels);
        ctr->Increment(value);
    }

    void setGauge(const std::string& name,
                  const std::map<std::string, std::string>& labels,
                  double value) {
        auto* gauge = getOrCreateGauge(name, labels);
        gauge->Set(value);
    }

private:
    prometheus::Counter* getOrCreateCounter(
        const std::string& name,
        const std::map<std::string, std::string>& labels) {
        std::lock_guard<std::mutex> lk{mutex_};
        auto key = name + labelsKey(labels);
        auto it  = counters_.find(key);
        if (it != counters_.end()) return it->second;

        auto& family = prometheus::BuildCounter()
                           .Name(name)
                           .Help("Auto-generated counter")
                           .Register(*registry_);
        auto& ctr = family.Add(labels);
        auto* ptr = &ctr;
        counters_.emplace(key, ptr);
        return ptr;
    }

    prometheus::Gauge* getOrCreateGauge(
        const std::string& name,
        const std::map<std::string, std::string>& labels) {
        std::lock_guard<std::mutex> lk{mutex_};
        auto key = name + labelsKey(labels);
        auto it  = gauges_.find(key);
        if (it != gauges_.end()) return it->second;

        auto& family = prometheus::BuildGauge()
                           .Name(name)
                           .Help("Auto-generated gauge")
                           .Register(*registry_);
        auto& gauge = family.Add(labels);
        auto* ptr   = &gauge;
        gauges_.emplace(key, ptr);
        return ptr;
    }

    static std::string labelsKey(
        const std::map<std::string, std::string>& labels) {
        std::string key;
        for (auto&& [k, v] : labels) {
            key.append(k).append("=").append(v).append(";");
        }
        return key;
    }

    std::shared_ptr<prometheus::Registry> registry_;
    std::mutex                            mutex_;
    std::unordered_map<std::string, prometheus::Counter*> counters_;
    std::unordered_map<std::string, prometheus::Gauge*>   gauges_;
};

// -----------------------------------------------------------------------------
// gRPC Service Implementation
// -----------------------------------------------------------------------------
class MetricsServiceImpl final : public proto::Metrics::Service {
public:
    explicit MetricsServiceImpl(std::shared_ptr<MetricsCollector> collector)
        : collector_{std::move(collector)} {}

    grpc::Status Report(grpc::ServerContext* ctx,
                        const proto::MetricSample* req,
                        proto::Ack*                res) override {
        try {
            std::map<std::string, std::string> labels(req->labels().begin(),
                                                      req->labels().end());

            switch (req->type()) {
            case proto::MetricSample::COUNTER:
                collector_->incrementCounter(req->name(), labels, req->value());
                break;
            case proto::MetricSample::GAUGE:
                collector_->setGauge(req->name(), labels, req->value());
                break;
            default:
                return grpc::Status(
                    grpc::StatusCode::INVALID_ARGUMENT,
                    "Unknown metric type: " + std::to_string(req->type()));
            }

            res->set_ok(true);
            return grpc::Status::OK;
        } catch (const std::exception& ex) {
            spdlog::error("Report() failed: {}", ex.what());
            return grpc::Status(grpc::StatusCode::INTERNAL, ex.what());
        }
    }

private:
    std::shared_ptr<MetricsCollector> collector_;
};

// -----------------------------------------------------------------------------
// TLS Utilities
// -----------------------------------------------------------------------------
grpc::SslServerCredentialsOptions loadSslCreds(const YAML::Node& cfg) {
    grpc::SslServerCredentialsOptions ssl_opts;
    try {
        std::string cert =
            cfg["tls"]["cert"].as<std::string>("/etc/ssl/certs/server.crt");
        std::string key =
            cfg["tls"]["key"].as<std::string>("/etc/ssl/private/server.key");
        std::string ca =
            cfg["tls"]["ca"].as<std::string>("/etc/ssl/certs/ca.crt");

        std::string cert_str =
            std::string(std::istreambuf_iterator<char>(
                            std::ifstream(cert).rdbuf()),
                        std::istreambuf_iterator<char>());
        std::string key_str =
            std::string(std::istreambuf_iterator<char>(
                            std::ifstream(key).rdbuf()),
                        std::istreambuf_iterator<char>());
        std::string ca_str =
            std::string(std::istreambuf_iterator<char>(std::ifstream(ca).rdbuf()),
                        std::istreambuf_iterator<char>());

        ssl_opts.pem_root_certs   = ca_str;
        ssl_opts.pem_key_cert_pairs.push_back(
            {key_str, cert_str});  // { private key, cert chain }
    } catch (const std::exception& ex) {
        throw std::runtime_error(
            std::string("Failed loading TLS credentials: ") + ex.what());
    }
    return ssl_opts;
}

// -----------------------------------------------------------------------------
// main()
// -----------------------------------------------------------------------------
int main(int argc, char* argv[]) {
    try {
        // 1) ------------------- Parse Command-Line -------------------------
        cxxopts::Options options("fl360-metrics",
                                 "FortiLedger360 Metrics Service");
        options.add_options()("c,config", "Configuration file",
                              cxxopts::value<std::string>()->default_value(
                                  "/etc/fortiledger360/metrics_svc.yaml"))(
            "v,verbose", "Enable debug logging")("h,help", "Show help");
        auto result = options.parse(argc, argv);

        if (result.count("help")) {
            fmt::print("{}\n", options.help());
            return EXIT_SUCCESS;
        }

        if (result.count("verbose")) { spdlog::set_level(spdlog::level::debug); }

        // 2) ------------------- Load YAML Config ---------------------------
        const auto config_path = result["config"].as<std::string>();
        spdlog::info("Loading configuration from {}", config_path);

        YAML::Node cfg = YAML::LoadFile(config_path);

        const std::string grpc_addr =
            cfg["grpc"]["listen"].as<std::string>("0.0.0.0:50051");
        const std::string prom_addr =
            cfg["prometheus"]["listen"].as<std::string>("0.0.0.0:9100");

        // 3) ------------------- Setup Prometheus Exposer -------------------
        auto registry = std::make_shared<prometheus::Registry>();
        prometheus::Exposer exposer{prom_addr};
        exposer.RegisterCollectable(registry);
        spdlog::info("Prometheus exposer started on {}", prom_addr);

        // 4) ------------------- Initialize Metrics Collector --------------
        auto collector = std::make_shared<MetricsCollector>(registry);

        // 5) ------------------- Build gRPC Server -------------------------
        MetricsServiceImpl service{collector};

        grpc::ServerBuilder builder;
        builder.AddListeningPort(
            grpc_addr, grpc::SslServerCredentials(loadSslCreds(cfg)));
        builder.RegisterService(&service);
        std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
        spdlog::info("gRPC server listening on {}", grpc_addr);

        // 6) ------------------- Signal Handling ---------------------------
        std::signal(SIGINT, signal_handler);
        std::signal(SIGTERM, signal_handler);

        // 7) ------------------- Wait Until Shutdown -----------------------
        while (!g_shutdown.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        spdlog::info("Shutdown signal received; initiating graceful stop...");
        server->Shutdown();
        exposer.~Exposer();  // stop HTTP server (non-virtual destructor)
        spdlog::info("Metrics service stopped. Bye!");

    } catch (const std::exception& ex) {
        spdlog::critical("Fatal error: {}", ex.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}

}  // namespace fl360::metrics
```