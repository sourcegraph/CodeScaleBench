```cpp
/**
 * FortiLedger360 – ConfigManager Service Implementation
 *
 * File:   FortiLedger360/src/services/config_manager_svc/service_impl.cpp
 * Author: FortiLedger360 Engineering Team
 *
 * Description:
 *   gRPC service‐layer implementation responsible for configuration
 *   lifecycle management (CRUD, drift-detection, versioning) per tenant.
 *   The service collaborates with:
 *      • ConfigRepository (etcd / postgres / in-mem fallback)
 *      • EventPublisher   (Kafka / NATS event-bus abstraction)
 *      • PolicyValidator  (Chain-of-Responsibility compliance guard)
 *
 *   The implementation is intentionally stateless toward callers; it
 *   maintains an internal LRU cache for hot tenants to reduce latency
 *   and lower repository round-trips.
 *
 *   Thread-safety: all public operations are re-entrant and guarded
 *   by fine-grained mutexes.
 */

#include "service_impl.h"                  // Interface/proto-generated stub
#include "domain/policy/policy_validator.h"
#include "infrastructure/event/event_publisher.h"
#include "infrastructure/repository/config_repository.h"

#include <spdlog/spdlog.h>
#include <nlohmann/json.hpp>

#include <openssl/sha.h>                   // SHA-256
#include <absl/strings/str_format.h>
#include <absl/container/flat_hash_map.h>

#include <chrono>
#include <mutex>
#include <shared_mutex>

using namespace std::chrono_literals;
using nlohmann::json;

namespace system_security::config_manager {

namespace  // anonymous helpers
{
/**
 * Compute SHA-256 fingerprint for versioning / drift-detection.
 */
static std::string computeHash(std::string_view payload)
{
    unsigned char hash[SHA256_DIGEST_LENGTH] = {0};
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, payload.data(), payload.size());
    SHA256_Final(hash, &ctx);

    std::string hex;
    hex.reserve(SHA256_DIGEST_LENGTH * 2);
    char buf[3] = {0};
    for (auto c: hash)
    {
        std::snprintf(buf, sizeof(buf), "%02x", c);
        hex.append(buf);
    }
    return hex;
}

/**
 * Small RAII timer for request tracing.
 */
class ScopedTimer
{
public:
    explicit ScopedTimer(const std::string& label)
        : label_{label}, start_{std::chrono::steady_clock::now()}
    {
        spdlog::trace("⏱️  [{}] – started", label_);
    }
    ~ScopedTimer()
    {
        const auto end = std::chrono::steady_clock::now();
        const auto dur = std::chrono::duration_cast<std::chrono::milliseconds>(end - start_).count();
        spdlog::debug("⏱️  [{}] – done in {} ms", label_, dur);
    }

private:
    std::string                          label_;
    std::chrono::steady_clock::time_point start_;
};
} // namespace


/***********************************************************************
 * Constructor / Destructor
 **********************************************************************/
ConfigManagerServiceImpl::ConfigManagerServiceImpl(
        std::shared_ptr<infrastructure::ConfigRepository> repo,
        std::shared_ptr<infrastructure::EventPublisher>   publisher,
        std::shared_ptr<domain::policy::PolicyValidator>  validator,
        std::chrono::minutes                              cacheTtl)
        : repository_{std::move(repo)},
          eventPublisher_{std::move(publisher)},
          policyValidator_{std::move(validator)},
          cacheTtl_{cacheTtl}
{
    if (!repository_ || !eventPublisher_ || !policyValidator_)
        throw std::invalid_argument("ConfigManagerServiceImpl ‑ dependencies must not be null");

    spdlog::info("ConfigManagerService ready (cache TTL={} mins)", cacheTtl_.count());
}

ConfigManagerServiceImpl::~ConfigManagerServiceImpl()
{
    try {
        std::unique_lock lock(cacheMutex_);
        cache_.clear();
    } catch (...) {
        // noexcept dtor
    }
}


/***********************************************************************
 * gRPC Methods
 **********************************************************************/
grpc::Status ConfigManagerServiceImpl::GetConfig(::grpc::ServerContext* context,
                                                 const proto::GetConfigRequest* request,
                                                 proto::GetConfigResponse*      response)
{
    ScopedTimer t{"GetConfig"};

    const auto& tenantId = request->tenant_id();
    if (tenantId.empty())
    {
        spdlog::warn("GetConfig ‑ missing tenant_id");
        return {grpc::StatusCode::INVALID_ARGUMENT, "tenant_id is required"};
    }

    // Check cache first
    {
        std::shared_lock rlock(cacheMutex_);
        auto it = cache_.find(tenantId);
        if (it != cache_.end() && !isCacheExpired(it->second))
        {
            *response->mutable_config() = it->second.proto;  // deep copy
            response->set_etag(it->second.etag);
            response->set_from_cache(true);
            return grpc::Status::OK;
        }
    }

    // Fetch from repository
    try
    {
        auto domainCfg = repository_->fetchConfig(tenantId);
        if (!domainCfg)
            return {grpc::StatusCode::NOT_FOUND, "configuration not found"};

        // Transform to proto
        proto::Config protoCfg;
        repository_->toProto(*domainCfg, &protoCfg);

        auto etag = computeHash(protoCfg.SerializeAsString());

        // Populate response
        *response->mutable_config() = protoCfg;
        response->set_etag(etag);
        response->set_from_cache(false);

        // Update cache
        addToCache(tenantId, protoCfg, etag);

        return grpc::Status::OK;
    }
    catch (const std::exception& ex)
    {
        spdlog::error("GetConfig ‑ {}", ex.what());
        return {grpc::StatusCode::INTERNAL, "internal error while fetching configuration"};
    }
}

grpc::Status ConfigManagerServiceImpl::UpdateConfig(::grpc::ServerContext* context,
                                                    const proto::UpdateConfigRequest* request,
                                                    proto::UpdateConfigResponse*      response)
{
    ScopedTimer t{"UpdateConfig"};

    const auto& tenantId = request->tenant_id();
    const auto& newCfg   = request->config();
    if (tenantId.empty())
        return {grpc::StatusCode::INVALID_ARGUMENT, "tenant_id is required"};

    // --- Policy Validation ------------------------------------------------
    if (auto result = policyValidator_->validateUpdate(tenantId, newCfg); !result.ok)
    {
        spdlog::warn("UpdateConfig ‑ policy validation failed: {}", result.message);
        return {grpc::StatusCode::PERMISSION_DENIED, result.message};
    }

    // --- Persist & Versioning ---------------------------------------------
    try
    {
        repository_->persistConfig(tenantId, newCfg);
        const auto etag = computeHash(newCfg.SerializeAsString());

        // Invalidate / update cache
        addToCache(tenantId, newCfg, etag);

        // --- Event Publication -------------------------------------------
        json evt = {
            {"event",  "ConfigUpdated"},
            {"tenant", tenantId},
            {"etag",   etag},
            {"ts",     std::chrono::duration_cast<std::chrono::milliseconds>(
                           std::chrono::system_clock::now().time_since_epoch()).count()}
        };
        eventPublisher_->publish("config.events", evt.dump());

        response->set_etag(etag);
        return grpc::Status::OK;
    }
    catch (const std::exception& ex)
    {
        spdlog::error("UpdateConfig ‑ {}", ex.what());
        return {grpc::StatusCode::INTERNAL, "could not persist configuration"};
    }
}

grpc::Status ConfigManagerServiceImpl::DetectDrift(::grpc::ServerContext* context,
                                                   const proto::DetectDriftRequest* request,
                                                   proto::DetectDriftResponse*      response)
{
    ScopedTimer t{"DetectDrift"};

    const auto& tenantId = request->tenant_id();
    if (tenantId.empty())
        return {grpc::StatusCode::INVALID_ARGUMENT, "tenant_id is required"};

    try
    {
        // 1) Desired (persisted) configuration
        auto desiredCfg = repository_->fetchConfig(tenantId);
        if (!desiredCfg)
            return {grpc::StatusCode::NOT_FOUND, "desired configuration not found"};

        // 2) Live (running) configuration from external discovery
        auto liveCfg = repository_->fetchLiveConfig(tenantId);
        if (!liveCfg)
            return {grpc::StatusCode::NOT_FOUND, "live configuration not found"};

        // 3) Compute drift
        json desiredJson = repository_->toJson(*desiredCfg);
        json liveJson    = repository_->toJson(*liveCfg);

        auto diff = json::diff(desiredJson, liveJson);   // uses nlohmann/json patch diff
        bool hasDrift = !diff.empty();

        response->set_has_drift(hasDrift);
        response->set_drift_patch(diff.dump());

        if (hasDrift)
        {
            // Publish event for observers (AlertBroker, Dashboard, etc.)
            json evt = {
                {"event",     "ConfigDriftDetected"},
                {"tenant",    tenantId},
                {"drift",     diff},
                {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                                   std::chrono::system_clock::now().time_since_epoch()).count()}
            };
            eventPublisher_->publish("config.events", evt.dump());
        }

        return grpc::Status::OK;
    }
    catch (const std::exception& ex)
    {
        spdlog::error("DetectDrift ‑ {}", ex.what());
        return {grpc::StatusCode::INTERNAL, "error while performing drift detection"};
    }
}


/***********************************************************************
 * Internal – Cache Helpers
 **********************************************************************/
bool ConfigManagerServiceImpl::isCacheExpired(const CacheEntry& entry) const noexcept
{
    return std::chrono::steady_clock::now() - entry.cachedAt > cacheTtl_;
}

void ConfigManagerServiceImpl::addToCache(const std::string& tenantId,
                                          const proto::Config& protoCfg,
                                          const std::string& etag)
{
    std::unique_lock wlock(cacheMutex_);
    CacheEntry entry;
    entry.proto    = protoCfg;
    entry.etag     = etag;
    entry.cachedAt = std::chrono::steady_clock::now();

    cache_[tenantId] = std::move(entry);

    // Simple LRU eviction – keep top 1k tenants hot.
    constexpr size_t kMaxEntries = 1024;
    if (cache_.size() > kMaxEntries)
        pruneStaleEntries();
}

void ConfigManagerServiceImpl::pruneStaleEntries()
{
    // O(n). Acceptable due to small size.
    for (auto it = cache_.begin(); it != cache_.end();) {
        if (isCacheExpired(it->second))
            it = cache_.erase(it);
        else
            ++it;
    }
}


/***********************************************************************
 * Misc – Service health probe
 **********************************************************************/
grpc::Status ConfigManagerServiceImpl::Ping(::grpc::ServerContext*,
                                            const proto::PingRequest*,
                                            proto::PingResponse* resp)
{
    resp->set_message("pong");
    resp->set_uptime_seconds(
        std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::steady_clock::now() - startTime_).count());
    resp->set_cache_size(cache_.size());
    return grpc::Status::OK;
}

} // namespace system_security::config_manager
```