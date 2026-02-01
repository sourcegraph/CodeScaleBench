```cpp
// ──────────────────────────────────────────────────────────────────────────────
//  File:    FortiLedger360/cmd/config_manager_svc/main.cpp
//  Project: FortiLedger360 Enterprise Security Suite – Configuration Manager
//
//  The Config-Manager service persists and distributes desired state across
//  FortiLedger360’s mesh. It exposes a gRPC surface for CRUD operations on
//  tenant-level configuration sets, publishes change events onto the event-bus,
//  and watches for configuration-drift signals emitted by Scanner / Metrics
//  nodes.
//
//  Build flags (example):
//      g++ -std=c++20 -O2 -Wall -Wextra \
//          -I./third_party \
//          -lgrpc++ -lprotobuf -lspdlog \
//          -lpthread -o bin/config_manager_svc \
//          cmd/config_manager_svc/main.cpp
// ──────────────────────────────────────────────────────────────────────────────
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <thread>
#include <unordered_map>

#include <grpcpp/grpcpp.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <cxxopts.hpp>

using json = nlohmann::json;
namespace fs = std::filesystem;

// ──────────────────────────────────────────────────────────────────────────────
//  Forward declarations of proto-generated artefacts (mocked for this file)
// ──────────────────────────────────────────────────────────────────────────────
namespace fortiledger::config {
class ConfigManager final : public grpc::Service
{
    // For brevity, all RPC handlers are mocked/no-ops.
};
} // namespace fortiledger::config

// ──────────────────────────────────────────────────────────────────────────────
//  Lightweight Event Bus stub (replaced by NATS / Kafka in production)
// ──────────────────────────────────────────────────────────────────────────────
class IEventBus
{
public:
    virtual ~IEventBus() = default;
    virtual void publish(std::string_view topic, const json& message) = 0;
};

class StdoutEventBus final : public IEventBus
{
public:
    void publish(std::string_view topic, const json& message) override
    {
        spdlog::info("[event-bus] Published to '{}': {}", topic, message.dump());
    }
};

// ──────────────────────────────────────────────────────────────────────────────
//  TLS Credential Loader
// ──────────────────────────────────────────────────────────────────────────────
grpc::SslServerCredentialsOptions load_server_tls_creds(const fs::path& cert_dir)
{
    grpc::SslServerCredentialsOptions ssl_opts;
    try
    {
        auto read_file = [](const fs::path& p) {
            std::ifstream f(p, std::ios::binary);
            if (!f)
                throw std::runtime_error("Unable to open " + p.string());
            return std::string(std::istreambuf_iterator<char>(f), {});
        };

        ssl_opts.pem_key_cert_pairs.emplace_back(
            grpc::SslServerCredentialsOptions::PemKeyCertPair{
                read_file(cert_dir / "server.key"), read_file(cert_dir / "server.crt")});

        ssl_opts.pem_root_certs = read_file(cert_dir / "ca.crt");

        ssl_opts.client_certificate_request = GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY;
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("TLS credential loading failed: {}", ex.what());
        std::exit(EXIT_FAILURE);
    }
    return ssl_opts;
}

// ──────────────────────────────────────────────────────────────────────────────
//  Configuration Loader
// ──────────────────────────────────────────────────────────────────────────────
struct RuntimeConfig
{
    std::string grpc_listen_uri = "0.0.0.0:5880";
    fs::path    tls_dir         = "./security/tls";
    std::string event_bus_topic = "config_changes";

    static RuntimeConfig from_file(const fs::path& path)
    {
        RuntimeConfig cfg;
        try
        {
            std::ifstream f(path);
            if (!f)
                throw std::runtime_error("Failed to open config file");

            json j;
            f >> j;

            if (j.contains("grpc_listen_uri"))
                cfg.grpc_listen_uri = j["grpc_listen_uri"].get<std::string>();
            if (j.contains("tls_dir"))
                cfg.tls_dir = j["tls_dir"].get<std::string>();
            if (j.contains("event_bus_topic"))
                cfg.event_bus_topic = j["event_bus_topic"].get<std::string>();
        }
        catch (const std::exception& ex)
        {
            spdlog::warn("Configuration parse error, falling back to defaults: {}", ex.what());
        }
        return cfg;
    }
};

// ──────────────────────────────────────────────────────────────────────────────
//  Service Orchestrator
// ──────────────────────────────────────────────────────────────────────────────
class ConfigManagerDaemon
{
public:
    ConfigManagerDaemon(RuntimeConfig cfg,
                        std::unique_ptr<IEventBus> bus)
        : _cfg(std::move(cfg))
        , _event_bus(std::move(bus))
        , _grpc_server(nullptr)
    {
    }

    void run()
    {
        // 1) Build gRPC server
        grpc::ServerBuilder builder;
        builder.AddListeningPort(_cfg.grpc_listen_uri,
                                 grpc::SslServerCredentials(load_server_tls_creds(_cfg.tls_dir)));

        builder.SetMaxReceiveMessageSize(8 * 1024 * 1024); // 8 MiB
        builder.RegisterService(&_svc_impl);

        _grpc_server = builder.BuildAndStart();
        if (!_grpc_server)
            throw std::runtime_error("Failed to start gRPC server");

        spdlog::info("Config-Manager listening on {}", _cfg.grpc_listen_uri);

        // 2) Async event-loop for drift-detection (mock)
        _worker_thread = std::thread([this] { drift_watch_loop(); });
    }

    void block_until_shutdown()
    {
        static std::atomic_bool signaled{false};

        auto shutdown = [this]() {
            if (signaled.exchange(true))
                return; // already shutting down

            spdlog::info("Shutdown signal received, terminating…");
            if (_grpc_server)
                _grpc_server->Shutdown();

            // Wake drift-watcher
            _terminate.store(true);
            if (_worker_thread.joinable())
                _worker_thread.join();
        };

        // Register signal handlers
        std::signal(SIGINT, [](int) { shutdown_instance(); });
        std::signal(SIGTERM, [](int) { shutdown_instance(); });

        // Keep pointer for static signal trampoline
        shutdown_instance = shutdown;

        if (_grpc_server)
            _grpc_server->Wait();
    }

private:
    void drift_watch_loop()
    {
        using namespace std::chrono_literals;
        while (!_terminate.load())
        {
            // Simulated periodic drift detection
            std::this_thread::sleep_for(5s);

            json msg = {{"type", "drift_watch_heartbeat"},
                        {"timestamp", std::time(nullptr)}};

            _event_bus->publish(_cfg.event_bus_topic, msg);
        }
    }

    static inline std::function<void()> shutdown_instance;

    RuntimeConfig                     _cfg;
    std::unique_ptr<IEventBus>        _event_bus;
    fortiledger::config::ConfigManager _svc_impl;

    std::unique_ptr<grpc::Server>     _grpc_server;
    std::thread                       _worker_thread;
    std::atomic_bool                  _terminate {false};
};

// ──────────────────────────────────────────────────────────────────────────────
//  Main
// ──────────────────────────────────────────────────────────────────────────────
int main(int argc, char** argv)
{
    // Setup colorful console logging
    auto logger = spdlog::stdout_color_mt("console");
    spdlog::set_pattern("[%Y-%m-%d %T.%e] [%^%l%$] %v");

    // ───── CLI parsing ────────────────────────────────────────────────────
    cxxopts::Options options("config_manager_svc",
                             "FortiLedger360 – Configuration-Manager daemon");
    options.add_options()
        ("c,config", "Path to runtime-config JSON", cxxopts::value<std::string>()->default_value("etc/config_manager.json"))
        ("v,verbose", "Increase log verbosity", cxxopts::value<bool>()->default_value("false"))
        ("h,help", "Show help");

    auto result = options.parse(argc, argv);

    if (result.count("help"))
    {
        std::cout << options.help() << std::endl;
        return EXIT_SUCCESS;
    }

    if (result["verbose"].as<bool>())
        spdlog::set_level(spdlog::level::debug);

    const fs::path cfg_path = result["config"].as<std::string>();
    spdlog::info("Loading configuration from {}", cfg_path.string());

    // ───── Bootstrap Daemon ──────────────────────────────────────────────
    try
    {
        RuntimeConfig cfg = RuntimeConfig::from_file(cfg_path);
        auto          bus = std::make_unique<StdoutEventBus>();

        ConfigManagerDaemon daemon(std::move(cfg), std::move(bus));
        daemon.run();
        daemon.block_until_shutdown();
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("Fatal error: {}", ex.what());
        return EXIT_FAILURE;
    }

    spdlog::info("Config-Manager terminated gracefully.");
    return EXIT_SUCCESS;
}
```