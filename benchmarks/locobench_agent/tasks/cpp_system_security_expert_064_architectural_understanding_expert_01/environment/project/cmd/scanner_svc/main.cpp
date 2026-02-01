```cpp
/**
 * FortiLedger360 – Scanner Service (scanner_svc)
 *
 * This is the entry-point executable that bootstraps the vulnerability
 * scanning micro-service.  Responsibilities:
 *
 *  1. Parse CLI flags & configuration files.
 *  2. Initialise structured logging.
 *  3. Bring-up gRPC server (mTLS) and expose the Scanner RPC API.
 *  4. Wire-up background worker pool and Event-Bus publisher.
 *  5. Provide graceful shutdown via POSIX signals.
 *
 *  The implementation purposefully avoids leaking *platform* specifics
 *  (container runtime, scheduler, etc.) to remain portable across bare-metal,
 *  Kubernetes, and serverless deployments.
 */

#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include <yaml-cpp/yaml.h>

#include "cxxopts.hpp"     // Light-weight CLI parsing library.
#include "spdlog/spdlog.h"  // Fast, modern C++ logging.

/*--------------------------------------------------------------------
 * Forward declarations for protobuf generated types.
 *-------------------------------------------------------------------*/
namespace fl360::scanner {

class ScanRequest;   // message ScanRequest {...}
class ScanReply;     // message ScanReply {...}
class HealthCheckRequest;
class HealthCheckReply;

/**
 * RPC service definition generated from scanner.proto
 *
 * service ScannerSvc {
 *   rpc StartScan(ScanRequest) returns (ScanReply);
 *   rpc StopScan(ScanRequest)  returns (ScanReply);
 *   rpc Health(HealthCheckRequest) returns (HealthCheckReply);
 * }
 */
class ScannerSvc final : public ::grpc::Service
{
public:
    // Generated interface methods we need to implement:
    virtual ::grpc::Status StartScan(::grpc::ServerContext*,
                                     const ScanRequest*,
                                     ScanReply*) = 0;
    virtual ::grpc::Status StopScan(::grpc::ServerContext*,
                                    const ScanRequest*,
                                    ScanReply*) = 0;
    virtual ::grpc::Status Health(::grpc::ServerContext*,
                                  const HealthCheckRequest*,
                                  HealthCheckReply*) = 0;
};

} // namespace fl360::scanner

/*--------------------------------------------------------------------
 * Domain layer – Scanning engine stub
 *-------------------------------------------------------------------*/
namespace fl360::scanner {

struct ScanTask
{
    std::string tenant_id;
    std::string target_uri;
    std::chrono::system_clock::time_point requested_at;
};

class Engine final
{
public:
    explicit Engine(std::size_t worker_threads)
        : stop_flag_{false}
    {
        SPDLOG_INFO("Bootstrapping scanning engine with {} workers …", worker_threads);
        for (std::size_t i = 0; i < worker_threads; ++i)
        {
            workers_.emplace_back([this, i] { loop(i); });
        }
    }

    ~Engine()
    {
        shutdown();
    }

    void enqueue(ScanTask task)
    {
        {
            std::lock_guard lk(queue_mtx_);
            queue_.emplace_back(std::move(task));
        }
        cv_.notify_one();
    }

    void shutdown()
    {
        bool expected = false;
        if (!stop_flag_.compare_exchange_strong(expected, true))
            return;  // Already shutting down

        cv_.notify_all();
        for (std::thread& t : workers_)
            if (t.joinable())
                t.join();
        SPDLOG_INFO("Scanning engine exited gracefully.");
    }

private:
    void loop(std::size_t id)
    {
        while (!stop_flag_)
        {
            std::optional<ScanTask> maybe;
            {
                std::unique_lock lk(queue_mtx_);
                cv_.wait(lk, [this] { return stop_flag_ || !queue_.empty(); });
                if (stop_flag_) break;
                maybe = std::move(queue_.front());
                queue_.pop_front();
            }

            if (maybe)
                performScan(*maybe, id);
        }
    }

    void performScan(const ScanTask& t, std::size_t worker_id)
    {
        SPDLOG_INFO("[worker {}] Starting scan for tenant={} target={}",
                    worker_id, t.tenant_id, t.target_uri);

        // Simulate I/O-bound scanning workload
        std::this_thread::sleep_for(std::chrono::seconds(2));

        // TODO: Send result to Event-Bus
        SPDLOG_INFO("[worker {}] Completed scan for target={}", worker_id, t.target_uri);
    }

    std::atomic_bool stop_flag_;
    std::condition_variable cv_;
    std::mutex queue_mtx_;
    std::deque<ScanTask> queue_;
    std::vector<std::thread> workers_;
};

} // namespace fl360::scanner

/*--------------------------------------------------------------------
 * Infrastructure layer – gRPC service implementation
 *-------------------------------------------------------------------*/
namespace fl360::scanner {

class ScannerServiceImpl final : public ScannerSvc
{
public:
    explicit ScannerServiceImpl(std::shared_ptr<Engine> engine)
        : engine_{std::move(engine)}
    {}

    ::grpc::Status StartScan(::grpc::ServerContext*,
                             const ScanRequest* req,
                             ScanReply* rep) override
    {
        if (!req)
            return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, "null request");

        ScanTask task{
            /*tenant_id=*/req->tenant_id(),
            /*target_uri=*/req->target_uri(),
            /*requested_at=*/std::chrono::system_clock::now()
        };

        engine_->enqueue(std::move(task));
        rep->set_ack(true);

        SPDLOG_DEBUG("Enqueued scan request for tenant_id={}", req->tenant_id());
        return ::grpc::Status::OK;
    }

    ::grpc::Status StopScan(::grpc::ServerContext*,
                            const ScanRequest*,
                            ScanReply* rep) override
    {
        // Not supported in stub implementation
        rep->set_ack(false);
        return ::grpc::Status(::grpc::StatusCode::UNIMPLEMENTED, "StopScan not implemented");
    }

    ::grpc::Status Health(::grpc::ServerContext*,
                          const HealthCheckRequest*,
                          HealthCheckReply* rep) override
    {
        rep->set_status(HealthCheckReply::SERVING);
        return ::grpc::Status::OK;
    }

private:
    std::shared_ptr<Engine> engine_;
};

} // namespace fl360::scanner

/*--------------------------------------------------------------------
 * Configuration model
 *-------------------------------------------------------------------*/
struct AppConfig
{
    std::string listen_addr             = "0.0.0.0";
    std::uint16_t listen_port           = 50051;
    std::size_t  worker_threads         = std::thread::hardware_concurrency();
    std::filesystem::path tls_cert_path = "scanner.crt";
    std::filesystem::path tls_key_path  = "scanner.key";
};

static AppConfig loadConfig(const std::filesystem::path& file)
{
    AppConfig cfg;
    if (file.empty())
        return cfg;

    try
    {
        YAML::Node root = YAML::LoadFile(file.string());
        if (root["listen_addr"])
            cfg.listen_addr = root["listen_addr"].as<std::string>();
        if (root["listen_port"])
            cfg.listen_port = root["listen_port"].as<uint16_t>();
        if (root["worker_threads"])
            cfg.worker_threads = root["worker_threads"].as<std::size_t>();
        if (root["tls_cert"])
            cfg.tls_cert_path = root["tls_cert"].as<std::string>();
        if (root["tls_key"])
            cfg.tls_key_path = root["tls_key"].as<std::string>();
    }
    catch (const YAML::Exception& ex)
    {
        SPDLOG_WARN("Failed to parse config file {}: {}", file.string(), ex.what());
    }
    return cfg;
}

/*--------------------------------------------------------------------
 * Global shutdown flag used by signal handlers
 *-------------------------------------------------------------------*/
static std::atomic_bool g_terminate{false};

static void handleSignal(int signo)
{
    SPDLOG_WARN("Received signal {}, initiating shutdown …", signo);
    g_terminate = true;
}

/*--------------------------------------------------------------------
 * Helpers
 *-------------------------------------------------------------------*/
static std::shared_ptr<::grpc::ServerCredentials>
buildServerCredentials(const AppConfig& cfg)
{
    // Load key/cert into string
    std::ifstream cert_in(cfg.tls_cert_path, std::ios::binary);
    std::ifstream key_in(cfg.tls_key_path,  std::ios::binary);

    if (!cert_in || !key_in)
    {
        SPDLOG_ERROR("Failed to read TLS cert/key files – falling back to insecure creds!");
        return ::grpc::InsecureServerCredentials();
    }

    std::string cert((std::istreambuf_iterator<char>(cert_in)), {});
    std::string key((std::istreambuf_iterator<char>(key_in)), {});

    ::grpc::SslServerCredentialsOptions::PemKeyCertPair pkcp{key, cert};
    ::grpc::SslServerCredentialsOptions ssl_ops;
    ssl_ops.pem_key_cert_pairs.push_back(pkcp);
    ssl_ops.client_certificate_request =
        GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERT_BUT_DONT_VERIFY;

    return ::grpc::SslServerCredentials(ssl_ops);
}

/*--------------------------------------------------------------------
 * Main
 *-------------------------------------------------------------------*/
int main(int argc, char* argv[])
{
    // -------------------- CLI parsing --------------------
    cxxopts::Options options("scanner_svc",
                             "FortiLedger360 – Real-time Vulnerability Scanner");
    options.add_options()
        ("c,config",    "Path to YAML config file", cxxopts::value<std::string>())
        ("log-level",   "Log level (trace|debug|info|warn|error)",
                        cxxopts::value<std::string>()->default_value("info"))
        ("h,help",      "Print usage");

    auto result = options.parse(argc, argv);

    if (result.count("help"))
    {
        fmt::print("{}\n", options.help());
        return EXIT_SUCCESS;
    }

    const auto log_level = spdlog::level::from_str(result["log-level"].as<std::string>());
    spdlog::set_level(log_level);

    // -------------------- Load configuration --------------------
    std::filesystem::path cfg_file;
    if (result.count("config"))
        cfg_file = result["config"].as<std::string>();

    AppConfig cfg = loadConfig(cfg_file);

    SPDLOG_INFO("Listen on {}:{}", cfg.listen_addr, cfg.listen_port);
    SPDLOG_INFO("Worker threads: {}", cfg.worker_threads);

    // -------------------- Boot scanning engine --------------------
    auto engine = std::make_shared<fl360::scanner::Engine>(cfg.worker_threads);

    // -------------------- Build gRPC server --------------------
    const std::string addr = fmt::format("{}:{}", cfg.listen_addr, cfg.listen_port);

    fl360::scanner::ScannerServiceImpl svc(engine);
    ::grpc::ServerBuilder builder;
    builder.AddListeningPort(addr, buildServerCredentials(cfg));
    builder.RegisterService(&svc);

    std::unique_ptr<::grpc::Server> server(builder.BuildAndStart());
    if (!server)
    {
        SPDLOG_CRITICAL("Failed to start gRPC server. Exiting …");
        return EXIT_FAILURE;
    }
    SPDLOG_INFO("Scanner service started and awaiting requests.");

    // -------------------- Setup signal handling --------------------
    std::signal(SIGINT,  handleSignal);
    std::signal(SIGTERM, handleSignal);

    // Block until termination signal
    while (!g_terminate)
        std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // Stop gRPC server
    SPDLOG_INFO("Shutting down gRPC server …");
    server->Shutdown();
    // Wait until all RPCs have completed
    server->Wait();

    // Stop engine
    engine->shutdown();

    SPDLOG_INFO("Scanner service shutdown complete.");
    return EXIT_SUCCESS;
}
```