#ifndef FORTILEGDER360_LIB_INFRASTRUCTURE_GRPC_CLIENT_FACTORY_H_
#define FORTILEGDER360_LIB_INFRASTRUCTURE_GRPC_CLIENT_FACTORY_H_

/*
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 * gRPC Client Factory
 *
 *  - Creates/caches secured gRPC channels
 *  - Produces typed service stubs on demand
 *  - Thread-safe, supports hot-reload of endpoints & TLS material
 *
 * Owners: infra-platform@fortiledger360.io
 */

#include <grpcpp/grpcpp.h>

#include <optional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>

#ifdef FLEDGER_USE_SPDLOG
// Optional: compile with -DFLEDGER_USE_SPDLOG to enable structured logging
#include <spdlog/spdlog.h>
#define FL360_LOG_TRACE(...)  SPDLOG_TRACE(__VA_ARGS__)
#define FL360_LOG_INFO(...)   SPDLOG_INFO(__VA_ARGS__)
#define FL360_LOG_WARN(...)   SPDLOG_WARN(__VA_ARGS__)
#define FL360_LOG_ERROR(...)  SPDLOG_ERROR(__VA_ARGS__)
#else
#define FL360_LOG_TRACE(...)
#define FL360_LOG_INFO(...)
#define FL360_LOG_WARN(...)
#define FL360_LOG_ERROR(...)
#endif

namespace fortiledger::infrastructure::grpc {

/*
 * Enum representing first-class mesh services.
 * Extend this list as the service mesh evolves.
 */
enum class ServiceType : std::uint8_t
{
    kScanner         = 0,
    kMetrics         = 1,
    kConfigManager   = 2,
    kBackupNode      = 3,
    kAlertBroker     = 4,
};

/*
 * TLS configuration required for mTLS channels.
 * The strings are expected to contain PEM-encoded material.
 */
struct TlsConfig
{
    std::string root_ca;      // Trust anchor(s)
    std::string client_cert;  // Client certificate chain
    std::string client_key;   // Private key for |client_cert|
};

/*
 * Hash for enum class to use it as a key in unordered_map.
 */
struct EnumClassHash
{
    template <typename T>
    std::size_t operator()(T t) const noexcept
    {
        return static_cast<std::size_t>(t);
    }
};

/*
 * ClientFactory is a central facility that provisions secured gRPC stubs.
 *
 * It caches channels per unique endpoint (authority), honoring the underlying
 * connection pooling & multiplexing provided by gRPC Core.  All public APIs
 * are thread-safe.
 *
 * Usage:
 *   ClientFactory::instance().registerEndpoint(ServiceType::kScanner,
 *                                              "scanner.mesh:443");
 *
 *   auto scanner = ClientFactory::instance().create<MyScanner::Stub>(
 *                                              ServiceType::kScanner);
 */
class ClientFactory final
{
public:
    // Singleton accessor (Meyers-style)
    static ClientFactory& instance()
    {
        static ClientFactory _self;
        return _self;
    }

    ClientFactory(const ClientFactory&)            = delete;
    ClientFactory& operator=(const ClientFactory&) = delete;

    /*
     * Registers/overrides an endpoint for |service|.
     * Thread-safe; allows hot-reload of service discovery results.
     */
    void registerEndpoint(ServiceType service, std::string endpoint)
    {
        {
            std::unique_lock lock(_registry_mtx_);
            _registry_[service] = std::move(endpoint);
        }
        // Invalidate any cached channel so next call will re-create it.
        flushChannel(endpoint);
    }

    /*
     * Returns an immutable snapshot of the current registry. Useful for
     * diagnostics & exporting metrics.
     */
    std::unordered_map<ServiceType, std::string, EnumClassHash> registrySnapshot() const
    {
        std::shared_lock lock(_registry_mtx_);
        return _registry_;
    }

    /*
     * Produces a stub for a registered |service|.
     * Will throw std::runtime_error if the service is unknown.
     */
    template <typename Stub>
    std::unique_ptr<Stub> create(ServiceType service,
                                 std::optional<TlsConfig> tls = std::nullopt)
    {
        return Stub::NewStub(resolveChannel(service, std::move(tls)));
    }

    /*
     * Produces a stub for an arbitrary |endpoint|.
     * Caches by endpoint address (host:port).
     */
    template <typename Stub>
    std::unique_ptr<Stub> create(const std::string& endpoint,
                                 std::optional<TlsConfig> tls = std::nullopt)
    {
        return Stub::NewStub(getOrCreateChannel(endpoint, std::move(tls)));
    }

    /*
     * Explicitly evicts a single channel from the cache.
     */
    void flushChannel(const std::string& endpoint)
    {
        std::unique_lock lock(_channels_mtx_);
        _channels_.erase(endpoint);
    }

    /*
     * Drops the entire channel cache (e.g., during rotation of client certs).
     */
    void flushAll()
    {
        std::unique_lock lock(_channels_mtx_);
        _channels_.clear();
    }

private:
    ClientFactory() = default;
    ~ClientFactory() = default;

    /*
     * Resolves channel for |service|, throwing if service is not registered.
     */
    std::shared_ptr<grpc::Channel> resolveChannel(ServiceType service,
                                                  std::optional<TlsConfig> tls)
    {
        std::string endpoint;
        {
            std::shared_lock lock(_registry_mtx_);
            auto itr = _registry_.find(service);
            if (itr == _registry_.end())
            {
                throw std::runtime_error("ClientFactory: Service endpoint not registered");
            }
            endpoint = itr->second;
        }
        return getOrCreateChannel(endpoint, std::move(tls));
    }

    /*
     * Returns a cached channel if present and healthy, or creates a new one.
     */
    std::shared_ptr<grpc::Channel> getOrCreateChannel(const std::string& endpoint,
                                                      std::optional<TlsConfig> tls)
    {
        {
            std::shared_lock lock(_channels_mtx_);
            auto it = _channels_.find(endpoint);
            if (it != _channels_.end())
            {
                // Best-effort health check (non-blocking).
                if (it->second->GetState(false) != GRPC_CHANNEL_SHUTDOWN)
                {
                    FL360_LOG_TRACE("Reusing existing channel to {}", endpoint);
                    return it->second;
                }
            }
        }

        // Need to create a fresh channel
        auto channel = createChannel(endpoint, tls);
        {
            std::unique_lock lock(_channels_mtx_);
            _channels_[endpoint] = channel;
        }
        FL360_LOG_INFO("Created new gRPC channel to {}", endpoint);
        return channel;
    }

    /*
     * Builds a secure or insecure channel based on |tls|.
     */
    static std::shared_ptr<grpc::Channel> createChannel(
            const std::string& endpoint,
            const std::optional<TlsConfig>& tls)
    {
        std::shared_ptr<grpc::ChannelCredentials> creds;

        if (tls.has_value())
        {
            grpc::SslCredentialsOptions ssl_opts;
            ssl_opts.pem_root_certs      = tls->root_ca;
            ssl_opts.pem_cert_chain      = tls->client_cert;
            ssl_opts.pem_private_key     = tls->client_key;
            creds = grpc::SslCredentials(ssl_opts);
        }
        else
        {
            creds = grpc::InsecureChannelCredentials();
        }

        grpc::ChannelArguments args;
        // Encourage name-resolver re-resolution every minute.
        args.SetInt(GRPC_ARG_DNS_MIN_TIME_BETWEEN_RESOLUTIONS_MS, 60 * 1000);
        // Enable keep-alive pings to detect dead peers.
        args.SetInt(GRPC_ARG_KEEPALIVE_TIME_MS, 30 * 1000);
        args.SetInt(GRPC_ARG_KEEPALIVE_TIMEOUT_MS, 10 * 1000);

        return grpc::CreateCustomChannel(endpoint, std::move(creds), std::move(args));
    }

    // --- State ---

    // Endpoint registry: Service -> "authority:port"
    std::unordered_map<ServiceType, std::string, EnumClassHash> _registry_;
    mutable std::shared_mutex _registry_mtx_;

    // Channel pool: "authority:port" -> shared channel
    std::unordered_map<std::string, std::shared_ptr<grpc::Channel>> _channels_;
    mutable std::shared_mutex _channels_mtx_;
};

} // namespace fortiledger::infrastructure::grpc

#endif // FORTILEGDER360_LIB_INFRASTRUCTURE_GRPC_CLIENT_FACTORY_H_
