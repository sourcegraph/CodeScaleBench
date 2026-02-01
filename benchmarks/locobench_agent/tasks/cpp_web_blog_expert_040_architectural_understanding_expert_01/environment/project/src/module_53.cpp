```cpp
/*
 *  IntraLedger BlogSuite – Audit Trail Recording Module
 *  ----------------------------------------------------
 *  File:            src/module_53.cpp
 *  Description:     Implements the AuditService used across the
 *                   application to persist audit-trail events and
 *                   dispatch background notifications.  The module
 *                   sits inside the Service Layer and uses a
 *                   Repository abstraction plus an asynchronous job
 *                   queue to keep responsibilities clearly separated.
 *
 *  Build Notes:
 *      – Depends on the single-header ‘nlohmann/json’ library.
 *      – Relies on C++20 <chrono> literals.
 *      – External interfaces (AuditLogRepository, AsyncJobQueue)
 *        are forward declared here so that the component
 *        compiles stand-alone in isolation tests. The concrete
 *        definitions live elsewhere in the code-base.
 *
 *  Copyright:
 *      © 2024 IntraLedger Ltd.  All rights reserved.
 */

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#include "nlohmann/json.hpp"       // External dependency: https://github.com/nlohmann/json

using json = nlohmann::json;
using namespace std::chrono_literals;

namespace intraledger::blogsuite::audit
{

/* ===========================================================
 *  Forward Declarations – Repository & Queue Abstractions
 * ===========================================================
 *  The actual implementations are supplied by their respective
 *  packages (Database_ORM, JobWorker).  We declare the minimal
 *  surface here to avoid circular dependencies.
 */

class AuditLogRepository
{
public:
    virtual ~AuditLogRepository() = default;

    // Persists the JSON representation of an audit event.
    // Throws on irrecoverable database errors.
    virtual void save(json event, std::chrono::milliseconds timeout) = 0;
};

class AsyncJobQueue
{
public:
    virtual ~AsyncJobQueue() = default;

    // Publishes a job payload under a channel/route name.
    // Throws on queue connectivity errors.
    virtual void publish(std::string_view route, json payload) = 0;
};

/* ===========================================================
 *  Enumerations & Value Objects
 * ===========================================================
 */

enum class Severity : uint8_t
{
    Info = 0,
    Warning,
    Error,
    Critical
};

inline std::string_view toString(Severity s) noexcept
{
    switch (s)
    {
        case Severity::Info:     return "info";
        case Severity::Warning:  return "warning";
        case Severity::Error:    return "error";
        case Severity::Critical: return "critical";
        default:                 return "unknown";
    }
}

// A lightweight container for user identity, intended
// to remain simple and serializable.
struct Subject
{
    std::string id;       // UUID or numeric ID as string
    std::string username; // Display name / handle
    std::string ip;       // IPv4/IPv6 address

    json toJson() const
    {
        return json{
            {"id", id},
            {"username", username},
            {"ip", ip}
        };
    }
};

// Primary domain object for an audit event.
struct AuditEvent
{
    std::string   correlationId; // Could be a ULID / UUID
    std::string   action;        // e.g. "USER_LOGIN", "ARTICLE_PUBLISH"
    Severity      severity;
    Subject       subject;
    json          meta;          // Arbitrary metadata
    std::chrono::system_clock::time_point timestamp;

    json toJson() const
    {
        json j;
        j["correlation_id"] = correlationId;
        j["action"]         = action;
        j["severity"]       = toString(severity);
        j["subject"]        = subject.toJson();
        j["meta"]           = meta;
        j["timestamp"]      = std::chrono::duration_cast<std::chrono::milliseconds>(
                                  timestamp.time_since_epoch()).count();
        return j;
    }
};

/* ===========================================================
 *  AuditService – Public API
 * ===========================================================
 */

class AuditService
{
public:
    struct Config
    {
        bool                        enableConsoleFallback = false;
        bool                        enableFileFallback    = true;
        std::filesystem::path       fileFallbackPath      = "/var/log/intraledger/audit_fallback.log";
        std::chrono::milliseconds   dbTimeout            = 1500ms;
        std::string                 asyncRoute           = "audit.event.created";
    };

    AuditService(std::shared_ptr<AuditLogRepository> repo,
                 std::shared_ptr<AsyncJobQueue>      queue,
                 Config                              cfg = {})
        : m_repo(std::move(repo))
        , m_queue(std::move(queue))
        , m_cfg(std::move(cfg))
    {
        if (!m_repo)
            throw std::invalid_argument("AuditService requires a non-null AuditLogRepository");
        if (!m_queue)
            throw std::invalid_argument("AuditService requires a non-null AsyncJobQueue");
    }

    // Records an audit event synchronously; internal failures
    // are captured and logged through fallback mechanisms rather
    // than propagating up to business logic callers.
    void recordEvent(AuditEvent event) noexcept
    {
        json payload = event.toJson();

        try
        {
            m_repo->save(payload, m_cfg.dbTimeout);
        }
        catch (const std::exception& ex)
        {
            safeFallback("repository", ex.what(), payload.dump());
        }

        // Best-effort async dispatch; any exceptions are captured
        // internally in identical fashion.
        try
        {
            m_queue->publish(m_cfg.asyncRoute, payload);
        }
        catch (const std::exception& ex)
        {
            safeFallback("queue", ex.what(), payload.dump());
        }
    }

private:
    std::shared_ptr<AuditLogRepository> m_repo;
    std::shared_ptr<AsyncJobQueue>      m_queue;
    Config                              m_cfg;
    std::mutex                          m_fileMutex; // protects fallback file writes

    /* -------------------------------------------------------
     *  safeFallback()
     *  ---------------
     *  Provides robust, low-tech logging in case primary
     *  outputs fail.  Keeps the calling thread alive and
     *  guarantees no-throw in all circumstances.
     */
    void safeFallback(std::string_view system,
                      std::string_view errorMsg,
                      std::string_view payload) noexcept
    {
        try
        {
            if (m_cfg.enableConsoleFallback)
            {
                std::cerr << "[AuditService] " << system
                          << " failure: "      << errorMsg
                          << "\nPayload: "     << payload << '\n';
            }

            if (m_cfg.enableFileFallback)
            {
                std::scoped_lock lock(m_fileMutex);

                // Ensure the directory exists (best attempt).
                std::error_code ec;
                std::filesystem::create_directories(
                    m_cfg.fileFallbackPath.parent_path(), ec);

                std::ofstream ofs(m_cfg.fileFallbackPath,
                                  std::ios::out | std::ios::app);
                if (ofs)
                {
                    auto now = std::chrono::system_clock::now();
                    auto t   = std::chrono::system_clock::to_time_t(now);

                    ofs << std::put_time(std::localtime(&t), "%F %T")
                        << " | system=" << system
                        << " | error="  << errorMsg
                        << " | payload="<< payload << '\n';
                }
            }
        }
        catch (...)
        {
            // Swallow any exception to preserve noexcept guarantee
        }
    }
};

} // namespace intraledger::blogsuite::audit
```