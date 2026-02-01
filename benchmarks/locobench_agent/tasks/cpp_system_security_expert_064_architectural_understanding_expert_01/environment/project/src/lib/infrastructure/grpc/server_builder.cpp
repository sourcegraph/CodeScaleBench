#include "server_builder.h"

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>

#if __has_include(<filesystem>)
#include <filesystem>
namespace fs = std::filesystem;
#else
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;
#endif

namespace fortiledger::infrastructure::grpc {

namespace {

/**
 * Read entire file content into a string.
 *
 * Throws std::runtime_error when the file cannot be opened or read.
 */
std::string ReadFile(const fs::path& path) {
    std::ifstream ifs(path, std::ios::in | std::ios::binary);
    if (!ifs) {
        throw std::runtime_error("Unable to open file: " + path.string());
    }

    std::ostringstream oss;
    oss << ifs.rdbuf();
    if (ifs.fail()) {
        throw std::runtime_error("Error while reading file: " + path.string());
    }

    return oss.str();
}

/**
 * Helper that builds ServerCredentials according to a given configuration.
 * Supports insecure (plaintext) and mTLS.
 */
std::shared_ptr<::grpc::ServerCredentials>
CreateCredentials(const GrpcServerConfig& cfg) {
    if (!cfg.enable_tls) {
        return ::grpc::InsecureServerCredentials();
    }

    if (cfg.server_cert_path.empty() || cfg.server_key_path.empty() ||
        cfg.root_ca_path.empty()) {
        throw std::runtime_error(
            "TLS is enabled but certificate, key or ca path is missing.");
    }

    const std::string cert = ReadFile(cfg.server_cert_path);
    const std::string key  = ReadFile(cfg.server_key_path);
    const std::string ca   = ReadFile(cfg.root_ca_path);

    ::grpc::SslServerCredentialsOptions::PemKeyCertPair key_cert_pair = {key,
                                                                         cert};
    ::grpc::SslServerCredentialsOptions ssl_opts;
    ssl_opts.pem_root_certs = ca;
    ssl_opts.pem_key_cert_pairs.push_back(std::move(key_cert_pair));
    ssl_opts.client_certificate_request =
        cfg.require_client_auth ? GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY
                                : GRPC_SSL_DONT_REQUEST_CLIENT_CERTIFICATE;

    return ::grpc::SslServerCredentials(ssl_opts);
}

}  // namespace

// -----------------------  ServerBuilder implementation  -------------------- //

FortiLedgerServerBuilder::FortiLedgerServerBuilder(GrpcServerConfig cfg)
    : config_(std::move(cfg)) {}

FortiLedgerServerBuilder& FortiLedgerServerBuilder::WithHealthCheckService(
    bool enable) {
    enable_health_ = enable;
    return *this;
}

FortiLedgerServerBuilder& FortiLedgerServerBuilder::WithReflectionService(
    bool enable) {
    enable_reflection_ = enable;
    return *this;
}

FortiLedgerServerBuilder& FortiLedgerServerBuilder::WithInterceptors(
    std::vector<
        std::unique_ptr<::grpc::experimental::ServerInterceptorFactoryInterface>>
        interceptors) {
    interceptor_factories_ = std::move(interceptors);
    return *this;
}

std::unique_ptr<::grpc::Server> FortiLedgerServerBuilder::BuildAndStart(
    const std::vector<::grpc::Service*>& services) const {
    ::grpc::ServerBuilder builder;

    // Listener address
    builder.AddListeningPort(config_.endpoint,
                             CreateCredentials(config_), /*selected_port=*/nullptr);

    // Resource limits
    builder.SetMaxReceiveMessageSize(config_.max_recv_message_size_bytes);
    builder.SetMaxSendMessageSize(config_.max_send_message_size_bytes);

    // Completion queues (optional thread-pool tuning)
    if (config_.completion_queue_count > 0) {
        for (std::size_t i = 0; i < config_.completion_queue_count; ++i) {
            builder.AddCompletionQueue(
                /*shutdown_callback=*/nullptr,
                /*reserved=*/nullptr,
                ::grpc::ServerBuilder::CQ_DEFAULT);
        }
    }

    // Register all provided services
    for (auto* svc : services) {
        if (!svc) {
            throw std::invalid_argument(
                "Nullptr provided in services vector passed to BuildAndStart");
        }
        builder.RegisterService(svc);
    }

    // Optional built-in health check service
    if (enable_health_) {
        ::grpc::HealthCheckServiceInterface* health_svc =
            ::grpc::HealthCheckServiceInterface::GetHealthCheckService();
        if (health_svc) {
            health_svc->SetServingStatus(true);
        }
    } else {
        ::grpc::DisableHealthCheckService();
    }

    // Reflection
    if (enable_reflection_) {
        ::grpc::reflection::InitProtoReflectionServerBuilderPlugin();
    }

    // Interceptors
    if (!interceptor_factories_.empty()) {
        builder.experimental().SetInterceptorCreators(
            std::move(interceptor_factories_));
    }

    // Build and start the server
    std::unique_ptr<::grpc::Server> server(builder.BuildAndStart());
    if (!server) {
        throw std::runtime_error(
            "Failed to build and start gRPC server on endpoint: " +
            config_.endpoint);
    }

    return server;
}

}  // namespace fortiledger::infrastructure::grpc