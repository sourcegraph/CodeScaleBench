#pragma once
/**************************************************************************************************
 *  FortiLedger360 Enterprise Security Suite
 *
 *  File:    server_builder.h
 *  Author:  Infrastructure – gRPC & Service-Mesh Team
 *  License: Proprietary, All Rights Reserved
 *
 *  Description:
 *      Small but opinionated wrapper around grpc::ServerBuilder that applies FortiLedger360-wide
 *      defaults (mTLS, health-check, reflection, histogram metrics, etc.) while still allowing
 *      per-service overrides through a fluent Builder API.
 *
 *      Example:
 *
 *          auto server = GrpcServerBuilder::Create()
 *              .WithListenAddress("0.0.0.0")
 *              .WithPort(8443)
 *              .WithTlsFromFiles("/etc/f360/certs/server.pem",
 *                                 "/etc/f360/certs/server.key",
 *                                 "/etc/f360/certs/ca-chain.pem")
 *              .AddService(&myGeneratedService)
 *              .AddInterceptor(MakeMyAuditInterceptor())
 *              .BuildAndStart();
 *
 *          // Keep running until SIGTERM.
 *          WaitForShutdownSignal();
 *          server->Shutdown();
 *
 **************************************************************************************************/

#include <cstdint>
#include <cstdlib>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <grpcpp/grpcpp.h>
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/health_check_service_interface.h>
#include <grpcpp/server_builder.h>
#include <grpcpp/support/server_interceptor.h>

// Compile-time flag that can be toggled via dedicated build types.
#ifndef FLEDGER_ENABLE_PROMETHEUS_METRICS
#define FLEDGER_ENABLE_PROMETHEUS_METRICS 1
#endif

#if FLEDGER_ENABLE_PROMETHEUS_METRICS
#include <grpcpp/opencensus.h>  // NOLINT
#endif

namespace fortiledger::infrastructure::grpc {

/**
 * Read an entire file into a std::string.
 * Designed for small-to-medium sized PEM files ( < 32 KiB ).
 *
 * @throws std::runtime_error if the file cannot be opened/read
 */
inline std::string ReadFile(const std::string& path) {
    std::ifstream in(path, std::ios::in | std::ios::binary);
    if (!in) {
        throw std::runtime_error("Unable to open file: " + path);
    }
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

/**
 * Light wrapper around grpc::SslServerCredentialsOptions to make it easier
 * to reason about the FortiLedger360 "sane defaults".
 */
struct TlsConfig {
    std::string server_cert_chain;
    std::string server_private_key;
    std::string root_cert_authority;

    // If true, the server will reject any client without a trusted cert.
    bool require_client_authentication = true;

    grpc::SslServerCredentialsOptions ToGrpcOpts() const {
        grpc::SslServerCredentialsOptions opts;
        opts.pem_root_certs = root_cert_authority;
        opts.client_certificate_request =
            require_client_authentication
                ? GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY
                : GRPC_SSL_DONT_REQUEST_CLIENT_CERTIFICATE;

        opts.pem_key_cert_pairs.push_back(
            {server_private_key.c_str(), server_cert_chain.c_str()});
        return opts;
    }
};

/**
 * Thread-safe, chainable builder for grpc::Server with FortiLedger360 defaults.
 */
class GrpcServerBuilder final {
public:
    using InterceptorFactory =
        std::unique_ptr<grpc::experimental::ServerInterceptorFactoryInterface>;

    /**
     * Factory method–explicit use to prohibit stack allocation and enforce
     * ownership semantics via unique_ptr.
     */
    static GrpcServerBuilder Create() { return GrpcServerBuilder(); }

    // Non-copyable but movable.
    GrpcServerBuilder(GrpcServerBuilder&&) noexcept = default;
    GrpcServerBuilder& operator=(GrpcServerBuilder&&) noexcept = default;

    // Chainable configuration methods -----------------------------------------------------------//
    GrpcServerBuilder& WithListenAddress(std::string_view address) {
        listen_address_ = address;
        return *this;
    }

    GrpcServerBuilder& WithPort(uint16_t port) {
        port_ = port;
        return *this;
    }

    GrpcServerBuilder& WithMaxMessageSize(size_t bytes) {
        max_message_size_ = bytes;
        return *this;
    }

    GrpcServerBuilder& WithThreadPoolSize(size_t threads) {
        thread_pool_size_ = threads;
        return *this;
    }

    GrpcServerBuilder& WithTls(const TlsConfig& cfg) {
        tls_config_ = cfg;
        return *this;
    }

    GrpcServerBuilder& WithTlsFromFiles(const std::string& cert_chain_path,
                                       const std::string& private_key_path,
                                       const std::string& ca_path,
                                       bool require_client_auth = true) {
        TlsConfig cfg{};
        cfg.server_cert_chain           = ReadFile(cert_chain_path);
        cfg.server_private_key          = ReadFile(private_key_path);
        cfg.root_cert_authority         = ReadFile(ca_path);
        cfg.require_client_authentication = require_client_auth;
        return WithTls(cfg);
    }

    GrpcServerBuilder& EnableGrpcReflection(bool enable = true) {
        reflection_enabled_ = enable;
        return *this;
    }

    GrpcServerBuilder& EnableHealthCheck(bool enable = true) {
        health_check_enabled_ = enable;
        return *this;
    }

#if FLEDGER_ENABLE_PROMETHEUS_METRICS
    GrpcServerBuilder& EnableOpencensusMetrics(bool enable = true) {
        opencensus_metrics_enabled_ = enable;
        return *this;
    }
#endif

    GrpcServerBuilder& AddService(grpc::Service* service) {
        services_.push_back(service);
        return *this;
    }

    GrpcServerBuilder& AddInterceptor(InterceptorFactory factory) {
        interceptors_.push_back(std::move(factory));
        return *this;
    }

    /**
     * Build and start the server. Throws std::runtime_error on configuration errors
     * (e.g., missing port, TLS files not found, etc.).
     */
    [[nodiscard]]
    std::unique_ptr<::grpc::Server> BuildAndStart() {
        ValidateOrThrow();

        grpc::ServerBuilder builder;
        ApplyCoreSettings(builder);
        ApplyTls(builder);
        ApplyInterceptors(builder);
        ApplyServices(builder);

        auto server = builder.BuildAndStart();
        if (!server) {
            throw std::runtime_error("grpc::ServerBuilder::BuildAndStart failed");
        }

        return server;
    }

private:
    // Private ctor forces clients to use Create()
    GrpcServerBuilder() = default;

    void ValidateOrThrow() const {
        if (!port_.has_value()) {
            throw std::runtime_error("gRPC server port was not set");
        }
        if (tls_config_.has_value()) {
            if (tls_config_->server_cert_chain.empty() ||
                tls_config_->server_private_key.empty()) {
                throw std::runtime_error("TLS cert/key cannot be empty");
            }
        }
    }

    // Internal helpers -------------------------------------------------------------------------//
    void ApplyCoreSettings(::grpc::ServerBuilder& builder) const {
        // Mandatory address: <listen>:<port>
        const auto address = listen_address_.value_or("0.0.0.0") + ":" +
                             std::to_string(port_.value());
        builder.AddListeningPort(address,
                                 tls_config_ ? nullptr
                                             : ::grpc::InsecureServerCredentials());

        builder.SetMaxReceiveMessageSize(
            static_cast<int>(max_message_size_.value_or(8 * 1024 * 1024))); // 8 MiB default
        builder.SetSyncServerOption(::grpc::ServerBuilder::SyncServerOption::
                                        NUM_CQS,
                                    static_cast<int>(thread_pool_size_.value_or(2)));
        builder.SetSyncServerOption(::grpc::ServerBuilder::SyncServerOption::
                                        MIN_POLLERS,
                                    1);
        builder.SetSyncServerOption(::grpc::ServerBuilder::SyncServerOption::
                                        MAX_POLLERS,
                                    static_cast<int>(thread_pool_size_.value_or(2)));

        if (health_check_enabled_) {
            ::grpc::HealthCheckServiceInterface::EnableDefaultHealthCheckService(true);
        }

        if (reflection_enabled_) {
            ::grpc::reflection::InitProtoReflectionServerBuilderPlugin();
        }

#if FLEDGER_ENABLE_PROMETHEUS_METRICS
        if (opencensus_metrics_enabled_) {
            ::grpc::RegisterOpenCensusPlugin();
            ::grpc::OpenCensusRegisterAllViews();  // Create default histograms
            // NOTE: We expect a separate Prometheus exporter to scrape these.
        }
#endif
    }

    void ApplyTls(::grpc::ServerBuilder& builder) const {
        if (tls_config_) {
            builder.AddListeningPort(
                listen_address_.value_or("0.0.0.0") + ":" + std::to_string(port_.value()),
                ::grpc::SslServerCredentials(tls_config_->ToGrpcOpts()));
        }
    }

    void ApplyInterceptors(::grpc::ServerBuilder& builder) const {
        if (!interceptors_.empty()) {
            builder.experimental().SetInterceptorCreators(interceptors_);
        }
    }

    void ApplyServices(::grpc::ServerBuilder& builder) const {
        for (auto* svc : services_) {
            builder.RegisterService(svc);
        }
    }

    // Member data ------------------------------------------------------------------------------//
    std::optional<std::string>                       listen_address_;
    std::optional<uint16_t>                          port_;
    std::optional<size_t>                            max_message_size_;
    std::optional<size_t>                            thread_pool_size_;
    std::optional<TlsConfig>                         tls_config_;

    bool reflection_enabled_       = true;
    bool health_check_enabled_     = true;
#if FLEDGER_ENABLE_PROMETHEUS_METRICS
    bool opencensus_metrics_enabled_ = true;
#endif

    std::vector<::grpc::Service*>                    services_;
    std::vector<InterceptorFactory>                  interceptors_;
};

} // namespace fortiledger::infrastructure::grpc