```cpp
/***************************************************************************************
 *  FortiLedger360 – Enterprise Security Suite
 *  Module      : API Gateway
 *  File        : server.cpp
 *  Description : gRPC façade that fronts all external client traffic,
 *                validates it through a pluggable CoR pipeline, and publishes
 *                commands onto the internal event-bus.
 *
 *  Build       : Requires C++17, gRPC C++ libs, spdlog, and (optionally) kafka-cpp.
 *
 *  Copyright   : © 2024 FortiLedger Inc.
 ****************************************************************************************/

#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>
#include <grpcpp/security/server_credentials.h>

#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#ifdef USE_KAFKA_PRODUCER
#include <kafka/KafkaProducer.h>   // 3rd-party librdkafka C++ wrapper
#endif

#include "proto/api_gateway.grpc.pb.h"   // Generated from api_gateway.proto

// ------------------------------------------------------------------------------------------------
// Helper utilities
// ------------------------------------------------------------------------------------------------
namespace util {

std::string readFile(const std::filesystem::path& path)
{
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Unable to open file: " + path.string());

    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

std::shared_ptr<grpc::SslServerCredentialsOptions> buildTlsOptions(
        const std::filesystem::path& cert,
        const std::filesystem::path& key,
        const std::filesystem::path& ca)
{
    auto opts = std::make_shared<grpc::SslServerCredentialsOptions>();
    opts->force_client_auth = true;  // mTLS
    opts->pem_cert_chain = readFile(cert);
    opts->pem_private_key = readFile(key);
    opts->pem_root_certs = readFile(ca);
    return opts;
}

} // namespace util

// ------------------------------------------------------------------------------------------------
// Event Bus Publisher abstraction
// ------------------------------------------------------------------------------------------------
class IEventPublisher
{
public:
    virtual ~IEventPublisher() = default;
    virtual void publish(const std::string& topic, const std::string& payload) = 0;
};

#ifdef USE_KAFKA_PRODUCER
// Kafka implementation (compile with -DUSE_KAFKA_PRODUCER)
class KafkaPublisher final : public IEventPublisher
{
public:
    explicit KafkaPublisher(const std::string& brokers)
        : producer_({{"bootstrap.servers", brokers}}) {}

    void publish(const std::string& topic, const std::string& payload) override
    {
        kafka::ProducerRecord rec(topic, kafka::NullKey, payload);
        try {
            producer_.send(rec);
            producer_.flush();
        } catch (const kafka::KafkaException& ex) {
            spdlog::error("Kafka publish failed: {}", ex.what());
            throw;
        }
    }

private:
    kafka::KafkaProducer producer_;
};
#else
// Fallback dummy publisher for unit-tests & local dev
class LogPublisher final : public IEventPublisher
{
public:
    void publish(const std::string& topic, const std::string& payload) override
    {
        spdlog::info("[StubPublisher] Topic: {}, Payload: {}", topic, payload);
    }
};
#endif

// ------------------------------------------------------------------------------------------------
// Validation Chain-of-Responsibility
// ------------------------------------------------------------------------------------------------
class RequestContext
{
public:
    explicit RequestContext(const gateway::v1::CommandRequest& req) : request(req) {}
    const gateway::v1::CommandRequest& request;
};

class Validator
{
public:
    virtual ~Validator() = default;

    void setNext(std::shared_ptr<Validator> next)
    {
        next_ = std::move(next);
    }

    void validate(RequestContext& ctx)
    {
        this->doValidate(ctx);
        if (next_) next_->validate(ctx);
    }

private:
    virtual void doValidate(RequestContext& ctx) = 0;
    std::shared_ptr<Validator> next_;
};

class AuthValidator final : public Validator
{
private:
    void doValidate(RequestContext& ctx) override
    {
        // Very basic API-token assertion. Real-life variant integrates with IAM.
        if (ctx.request.auth_token().empty()) {
            throw std::runtime_error("Authentication token missing");
        }
    }
};

class ComplianceValidator final : public Validator
{
private:
    void doValidate(RequestContext& ctx) override
    {
        // Example: prevent “root” tenant from running destructive commands.
        if (ctx.request.tenant_id() == "root" &&
            ctx.request.command_type() == "RollClusterBackup") {
            throw std::runtime_error("Command forbidden for tenant: root");
        }
    }
};

// ------------------------------------------------------------------------------------------------
// ApiGateway Service Implementation
// ------------------------------------------------------------------------------------------------
class ApiGatewayService final : public gateway::v1::ApiGateway::Service
{
public:
    explicit ApiGatewayService(std::shared_ptr<IEventPublisher> publisher)
        : publisher_(std::move(publisher))
    {
        buildValidatorChain();
    }

    grpc::Status PublishCommand(grpc::ServerContext* context,
                                const gateway::v1::CommandRequest* request,
                                gateway::v1::CommandResponse* response) override
    {
        spdlog::info("Received command: type={} tenant={}", request->command_type(),
                     request->tenant_id());

        try {
            RequestContext ctx(*request);
            rootValidator_->validate(ctx);
        } catch (const std::exception& ex) {
            spdlog::warn("Validation failed: {}", ex.what());
            response->set_status(gateway::v1::CommandResponse::REJECTED);
            response->set_message(ex.what());
            return grpc::Status::OK;
        }

        // Pack message & dispatch onto event bus
        try {
            publisher_->publish("commands", request->SerializeAsString());
            response->set_status(gateway::v1::CommandResponse::ACCEPTED);
            response->set_message("Command queued for execution");
        } catch (const std::exception& ex) {
            spdlog::error("Publishing failed: {}", ex.what());
            return grpc::Status(grpc::StatusCode::INTERNAL, ex.what());
        }

        return grpc::Status::OK;
    }

private:
    void buildValidatorChain()
    {
        auto auth = std::make_shared<AuthValidator>();
        auto compliance = std::make_shared<ComplianceValidator>();

        auth->setNext(compliance);
        rootValidator_ = std::move(auth);
    }

    std::shared_ptr<IEventPublisher> publisher_;
    std::shared_ptr<Validator>        rootValidator_;
};

// ------------------------------------------------------------------------------------------------
// Graceful shutdown handling
// ------------------------------------------------------------------------------------------------
namespace {

std::atomic<bool> g_shutdown{false};

void handleSignal(int signum)
{
    spdlog::warn("Received signal {}, shutting down …", signum);
    g_shutdown.store(true);
}

} // anonymous namespace

// ------------------------------------------------------------------------------------------------
// main()
// ------------------------------------------------------------------------------------------------
int main(int argc, char* argv[])
{
    (void)argc;
    (void)argv;

    // 1) Prepare logger
    spdlog::set_level(spdlog::level::info);
    spdlog::set_pattern("[%H:%M:%S] [%^%L%$] %v");

    // 2) Capture POSIX signals for graceful stop
    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    try {
        // 3) Configuration (would typically be read from YAML/env)
        std::string listenAddr = "0.0.0.0:8443";
        std::filesystem::path certPath = "/etc/fortiledger360/certs/server.crt";
        std::filesystem::path keyPath  = "/etc/fortiledger360/certs/server.key";
        std::filesystem::path caPath   = "/etc/fortiledger360/certs/ca.crt";

        spdlog::info("Starting ApiGateway on {}", listenAddr);

        // 4) Dependency wiring
#ifdef USE_KAFKA_PRODUCER
        auto publisher = std::make_shared<KafkaPublisher>("broker-1:9092,broker-2:9092");
#else
        auto publisher = std::make_shared<LogPublisher>();
#endif
        ApiGatewayService service(publisher);

        // 5) Build TLS creds
        auto sslOpts = util::buildTlsOptions(certPath, keyPath, caPath);
        auto creds   = grpc::SslServerCredentials(*sslOpts);

        // 6) Build gRPC server
        grpc::ServerBuilder builder;
        builder.AddListeningPort(listenAddr, creds);
        builder.RegisterService(&service);
        builder.AddChannelArgument(GRPC_ARG_MAX_CONCURRENT_STREAMS, 64);

        std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
        spdlog::info("ApiGateway is ready 🚀");

        // 7) Block until termination requested
        while (!g_shutdown.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        server->Shutdown();
        spdlog::info("Server stopped gracefully");

    } catch (const std::exception& ex) {
        spdlog::critical("Fatal error: {}", ex.what());
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
```