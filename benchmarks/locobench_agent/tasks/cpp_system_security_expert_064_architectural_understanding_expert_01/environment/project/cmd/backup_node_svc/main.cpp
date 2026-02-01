```cpp
/*****************************************************************************************
 *  FortiLedger360 Enterprise Security Suite – BackupNode Service
 *  ----------------------------------------------------------------------------
 *  File:        cmd/backup_node_svc/main.cpp
 *  Author:      FortiLedger360 Core Team
 *  License:     Proprietary – All Rights Reserved
 *
 *  Entry-point for the BackupNode micro-service.  Responsible for:
 *    • Loading configuration (YAML, env-vars, CLI flags)
 *    • Initialising TLS credentials & gRPC server
 *    • Registering service implementation & interceptors
 *    • Wiring health-checks, metrics, and graceful-shutdown handlers
 *
 *  Build:
 *      g++ main.cpp -std=c++20 -lgrpc++ -lprotobuf -lyaml-cpp -lpthread -o backup_node_svc
 *
 *****************************************************************************************/

#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/impl/codegen/interceptor.h>

#include <yaml-cpp/yaml.h>

#include <csignal>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>

namespace fs = std::filesystem;
using grpc::Status;
using grpc::StatusCode;

constexpr char kDefaultConfigPath[] = "/etc/fortiledger360/backup_node.yml";
constexpr char kDefaultListenAddr[] = "0.0.0.0";
constexpr int  kDefaultPort        = 5152;

/* =======================================================================================
 *  Domain Protos – Forward Declarations
 *     Real implementation lives in generated back_up_node.pb.h|cc
 *     (We forward-declare only to satisfy the compiler when headers are unavailable
 *      within the context of this example.)
 * =====================================================================================*/
namespace fortiledger             { namespace backupnode {
class RollBackupRequest  {};
class RollBackupResponse {};
class BackupStatusRequest {};
class BackupStatusReply  {};

class BackupNodeService final
{
public:
    class Service : public grpc::Service
    {
    public:
        virtual Status RollBackup(grpc::ServerContext*,
                                  const RollBackupRequest*,
                                  RollBackupResponse*)     { return Status::OK; }

        virtual Status GetBackupStatus(grpc::ServerContext*,
                                       const BackupStatusRequest*,
                                       BackupStatusReply*)  { return Status::OK; }
    };
};
}} // namespace fortiledger::backupnode

/* =======================================================================================
 *  Config Model & Loader
 * =====================================================================================*/
struct ServiceConfig
{
    std::string listen_addr  = kDefaultListenAddr;
    uint16_t    listen_port  = kDefaultPort;

    bool        tls_enabled  = false;
    fs::path    tls_cert;           // server.crt
    fs::path    tls_key;            // server.key
    fs::path    tls_root_ca;        // ca.crt  (optional for mTLS)

    // Misc
    uint16_t    metrics_port = 9095;
    std::string api_key;            // simple shared secret for demo purposes
};

class ConfigLoader
{
public:
    static ServiceConfig load(const std::string& cfgFile)
    {
        ServiceConfig cfg;
        YAML::Node root = YAML::LoadFile(cfgFile);

        // Required
        const auto& server = root["server"];
        if (server)
        {
            cfg.listen_addr = server["listen_addr"].as<std::string>(kDefaultListenAddr);
            cfg.listen_port = server["port"].as<uint16_t>(kDefaultPort);
        }

        // TLS
        const auto& tls = root["tls"];
        if (tls && tls["enabled"].as<bool>(false))
        {
            cfg.tls_enabled = true;
            cfg.tls_cert    = tls["cert"].as<std::string>();
            cfg.tls_key     = tls["key"].as<std::string>();
            cfg.tls_root_ca = tls["root_ca"].as<std::string>("");
        }

        // Metrics
        cfg.metrics_port = root["metrics"]["port"].as<uint16_t>(9095);

        // Auth
        cfg.api_key = root["auth"]["api_key"].as<std::string>("");

        return cfg;
    }
};

/* =======================================================================================
 *  gRPC Interceptors
 * =====================================================================================*/
class LoggingInterceptor final : public grpc::experimental::Interceptor
{
public:
    explicit LoggingInterceptor(grpc::experimental::ServerRpcInfo* info) : info_(info) {}

    void Intercept(grpc::experimental::InterceptorBatchMethods* methods) override
    {
        if (methods->QueryInterceptionHookPoint(
                grpc::experimental::InterceptionHookPoints::PRE_RECV_INITIAL_METADATA))
        {
            std::cout << "[RPC] <" << info_->method() << "> invoked from "
                      << methods->GetServerContext()->peer() << '\n';
        }
        methods->Proceed();
    }

private:
    grpc::experimental::ServerRpcInfo* info_;
};

class AuthInterceptor final : public grpc::experimental::Interceptor
{
public:
    AuthInterceptor(grpc::experimental::ServerRpcInfo* info,
                    const std::string& sharedKey)
        : info_(info), shared_key_(sharedKey) {}

    void Intercept(grpc::experimental::InterceptorBatchMethods* methods) override
    {
        if (!methods->QueryInterceptionHookPoint(
                grpc::experimental::InterceptionHookPoints::PRE_RECV_INITIAL_METADATA))
        {
            methods->Proceed();
            return;
        }

        auto* ctx = methods->GetServerContext();
        const auto& metadata = ctx->client_metadata();
        auto it = metadata.find("x-api-key");
        if (it == metadata.end() || it->second != shared_key_)
        {
            methods->SendInitialMetadata(&ctx->trailing_metadata());
            methods->Finish(Status(StatusCode::UNAUTHENTICATED, "Invalid API key"));
            return;
        }
        methods->Proceed();
    }

private:
    grpc::experimental::ServerRpcInfo* info_;
    std::string                         shared_key_;
};

class InterceptorFactory : public grpc::experimental::ServerInterceptorFactoryInterface
{
public:
    explicit InterceptorFactory(const std::string& sharedKey) : key_(sharedKey) {}

    grpc::experimental::Interceptor* CreateServerInterceptor(
        grpc::experimental::ServerRpcInfo* info) override
    {
        // Chain: Auth -> Logging
        static const std::unordered_set<std::string> kHealthExcludedMethods = {
            "/grpc.health.v1.Health/Check", "/grpc.health.v1.Health/Watch"};

        if (kHealthExcludedMethods.contains(info->method()))
        {
            return new LoggingInterceptor(info); // no auth on health
        }

        // Compose custom interceptors manually
        return new AuthInterceptor(info, key_);
    }

private:
    std::string key_;
};

/* =======================================================================================
 *  Service Implementation – BackupNode
 * =====================================================================================*/
class BackupNodeServiceImpl final
        : public fortiledger::backupnode::BackupNodeService::Service
{
public:
    explicit BackupNodeServiceImpl() = default;
    ~BackupNodeServiceImpl() override = default;

    Status RollBackup(grpc::ServerContext* ctx,
                      const fortiledger::backupnode::RollBackupRequest* /*req*/,
                      fortiledger::backupnode::RollBackupResponse*      /*resp*/) override
    {
        (void)ctx;
        std::cout << "[BackupNode] RollBackup triggered.\n";
        return Status::OK;
    }

    Status GetBackupStatus(grpc::ServerContext* ctx,
                           const fortiledger::backupnode::BackupStatusRequest* /*req*/,
                           fortiledger::backupnode::BackupStatusReply*         /*resp*/) override
    {
        (void)ctx;
        std::cout << "[BackupNode] GetBackupStatus called.\n";
        return Status::OK;
    }
};

/* =======================================================================================
 *  TLS / Credential Helpers
 * =====================================================================================*/
std::shared_ptr<grpc::ServerCredentials>
makeServerCredentials(const ServiceConfig& cfg)
{
    if (!cfg.tls_enabled)
    {
        return grpc::InsecureServerCredentials();
    }

    grpc::SslServerCredentialsOptions::PemKeyCertPair keycert;
    std::ifstream cert(cfg.tls_cert), key(cfg.tls_key);
    if (!cert.good() || !key.good())
        throw std::runtime_error("Failed to load TLS cert/key");

    keycert.private_key.assign(std::istreambuf_iterator<char>(key), {});
    keycert.cert_chain .assign(std::istreambuf_iterator<char>(cert), {});

    grpc::SslServerCredentialsOptions opts;
    opts.pem_key_cert_pairs.push_back(std::move(keycert));

    if (!cfg.tls_root_ca.empty())
    {
        std::ifstream root(cfg.tls_root_ca);
        opts.pem_root_certs.assign(std::istreambuf_iterator<char>(root), {});
        opts.force_client_auth = true; // mTLS
    }

    return grpc::SslServerCredentials(opts);
}

/* =======================================================================================
 *  Graceful Shutdown Utilities
 * =====================================================================================*/
namespace
{
    std::mutex              g_shutdownMutex;
    std::condition_variable g_shutdownCv;
    bool                    g_shutdownRequested = false;

    void signalHandler(int signum)
    {
        std::cout << "\n[Signal] Caught signal " << signum << ", requesting graceful shutdown..."
                  << std::endl;
        {
            std::lock_guard lk(g_shutdownMutex);
            g_shutdownRequested = true;
        }
        g_shutdownCv.notify_all();
    }
}

/* =======================================================================================
 *  Main
 * =====================================================================================*/
int main(int argc, char* argv[])
{
    std::ios::sync_with_stdio(false);

    // -------------------------------------------------------------
    // CLI flags
    // -------------------------------------------------------------
    std::string configPath = kDefaultConfigPath;
    for (int i = 1; i < argc; ++i)
    {
        std::string_view arg(argv[i]);
        if (arg == "--config" && i + 1 < argc)
        {
            configPath = argv[++i];
        }
        else if (arg == "--help" || arg == "-h")
        {
            std::cout << "Usage: backup_node_svc [--config <path>]\n";
            return 0;
        }
    }

    // -------------------------------------------------------------
    // Load configuration
    // -------------------------------------------------------------
    ServiceConfig cfg;
    try
    {
        cfg = ConfigLoader::load(configPath);
    }
    catch (const std::exception& ex)
    {
        std::cerr << "[Fatal] Failed to load config: " << ex.what() << '\n';
        return EXIT_FAILURE;
    }

    // -------------------------------------------------------------
    // Initialise gRPC
    // -------------------------------------------------------------
    grpc::EnableDefaultHealthCheckService(true);
    grpc::reflection::InitProtoReflectionServerBuilderPlugin();

    BackupNodeServiceImpl serviceImpl;

    grpc::ServerBuilder builder;
    const std::string bindAddr =
        cfg.listen_addr + ":" + std::to_string(cfg.listen_port);

    builder.AddListeningPort(bindAddr, makeServerCredentials(cfg));
    builder.RegisterService(&serviceImpl);

    // Interceptors
    std::vector<std::unique_ptr<grpc::experimental::ServerInterceptorFactoryInterface>>
        interceptorFactories;
    interceptorFactories.emplace_back(
        std::make_unique<InterceptorFactory>(cfg.api_key));

    builder.experimental().SetInterceptorCreators(
        std::move(interceptorFactories));

    // Build & start server
    std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
    if (!server)
    {
        std::cerr << "[Fatal] Failed to start gRPC server." << std::endl;
        return EXIT_FAILURE;
    }

    std::cout << "[Startup] BackupNode Service listening on: " << bindAddr
              << (cfg.tls_enabled ? " (TLS enabled)" : " (insecure)") << '\n';

    // -------------------------------------------------------------
    // Register signal handlers
    // -------------------------------------------------------------
    std::signal(SIGINT,  signalHandler);
    std::signal(SIGTERM, signalHandler);

    // -------------------------------------------------------------
    // Wait until a shutdown signal is received
    // -------------------------------------------------------------
    {
        std::unique_lock lk(g_shutdownMutex);
        g_shutdownCv.wait(lk, [] { return g_shutdownRequested; });
    }

    std::cout << "[Shutdown] Initiating graceful shutdown..." << std::endl;
    server->Shutdown(std::chrono::system_clock::now() +
                     std::chrono::seconds(5));
    server->Wait();
    std::cout << "[Shutdown] Completed." << std::endl;
    return 0;
}
```