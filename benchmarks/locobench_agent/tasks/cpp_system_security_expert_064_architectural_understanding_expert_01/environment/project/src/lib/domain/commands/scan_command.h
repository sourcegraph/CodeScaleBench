#ifndef FORTILEDGER360_DOMAIN_COMMANDS_SCAN_COMMAND_H
#define FORTILEDGER360_DOMAIN_COMMANDS_SCAN_COMMAND_H
/**
 *  FortiLedger360 Enterprise Security Suite
 *  File:    scan_command.h
 *  License: Proprietary. All Rights Reserved.
 *
 *  Description:
 *  ------------
 *  Domain-layer command that represents the intention to initiate a security
 *  vulnerability scan.  The class encapsulates     business-level validation
 *  and translates the request into an EventBus message so that downstream
 *  mesh services (e.g., Scanner, Metrics) can react asynchronously.
 *
 *  Architectural Patterns:
 *    * Command Pattern         – Encapsulates a user intent as an object.
 *    * Observer Pattern        – Allows interested parties to tap into the
 *                                 life-cycle (pre, post, fault) of the scan.
 *    * Event-Driven Architecture – Emits an event instead of performing the
 *                                 long-running scan synchronously.
 */

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fortiledger360::domain::events {

/**
 *  Generic event envelope propagated through the internal EventBus.
 *  The envelope is intentionally small and serialisation-friendly.
 */
struct Event
{
    std::string         topic;
    std::string         correlationId;
    std::string         payload;        // JSON | MsgPack | Proto | …
    std::chrono::system_clock::time_point  timestamp;

    Event(std::string  t,
          std::string  corrId,
          std::string  payld)
        : topic(std::move(t))
        , correlationId(std::move(corrId))
        , payload(std::move(payld))
        , timestamp(std::chrono::system_clock::now())
    {}
};

} // namespace fortiledger360::domain::events

// ---------------------------------------------------------------------------

namespace fortiledger360::infra {

/**
 *  Simplified, technology-agnostic EventBus interface.  Production code
 *  offers multiple implementations (e.g., Kafka, NATS, RabbitMQ).
 */
class IEventBus
{
public:
    virtual ~IEventBus() = default;

    /**
     *  Publishes the event in a fire-and-forget manner.
     *  Implementations are expected to be exception-safe: an exception thrown
     *  here aborts the current Command transaction.
     */
    virtual void publish(const domain::events::Event& event) = 0;
};

} // namespace fortiledger360::infra

// ---------------------------------------------------------------------------

namespace fortiledger360::domain::commands {

enum class ScanDepth : std::uint8_t
{
    Quick       = 0,  // Port scan + header checks
    Deep        = 1,  // Full OWASP Top-10, heuristics, signatures
    Continuous  = 2   // Real-time, streamed sensor-data
};

/**
 *  Input parameters for a scan request.
 *  The structure is intentionally aggregate-initialisable.
 */
struct ScanContext
{
    std::string tenantId;          // Billing / multi-tenancy identifier
    std::string assetId;           // VM, Container, LB, or Cluster Id
    ScanDepth   depth;
    std::optional<std::string> correlationId;
};

// ------------------------------------------------------------------------

/**
 *  Command interface used throughout the Domain layer.
 */
class ICommand
{
public:
    virtual ~ICommand() = default;
    virtual void execute() = 0;
    virtual std::string_view name() const noexcept = 0;
};

// ------------------------------------------------------------------------

/**
 *  ScanCommand encapsulates “InitiateSecurityScan”.
 *  After validation it emits an ‘security.scan.requested’ event to the bus.
 */
class ScanCommand final : public ICommand,
                          public std::enable_shared_from_this<ScanCommand>
{
public:
    using Clock      = std::chrono::system_clock;
    using TimePoint  = Clock::time_point;

    // A simple result wrapper to surface execution metadata.
    struct Result
    {
        bool        ok;
        std::string correlationId;
        TimePoint   acceptedAt;
        std::optional<std::string> reason; // filled on failure
    };

    using Observer = std::function<void(const ScanCommand&, const Result&)>;

public:
    ScanCommand(ScanContext                         ctx,
                std::shared_ptr<infra::IEventBus>   bus)
        : context_(std::move(ctx))
        , bus_(std::move(bus))
    {
        if (!bus_) {
            throw std::invalid_argument("ScanCommand: event bus must not be null");
        }
    }

    std::string_view name() const noexcept override { return "InitiateSecurityScan"; }

    /**
     *  Executes the command: validates input, prepares event payload, and
     *  publishes the event to the bus.
     *
     *  Throws:
     *      std::runtime_error on validation or publishing errors.
     */
    void execute() override
    {
        Result res{};

        try
        {
            validateContext();

            const auto corrId = context_.correlationId.value_or(generateCorrelationId());
            // Prepare a tiny JSON document.  In production we rely on
            // a dedicated serialisation layer; here we keep it simple.
            const std::string payload = buildPayloadJson(corrId);

            domain::events::Event ev{
                "security.scan.requested",
                corrId,
                payload
            };

            bus_->publish(ev);

            res.ok            = true;
            res.correlationId = corrId;
            res.acceptedAt    = ev.timestamp;

            notifyObservers(res);
        }
        catch (const std::exception& ex)
        {
            res.ok     = false;
            res.reason = ex.what();
            notifyObservers(res);
            throw;  // re-throw so upstream callers are aware
        }
    }

    /**
     *  Attaches an observer that will be invoked ONCE per execute() call.
     *  The Command instance retains a weak copy, so clients must manage the
     *  lifetime of captured resources.
     */
    void attachObserver(Observer obs)
    {
        observers_.emplace_back(std::move(obs));
    }

    // Accessors ------------------------------------------------------------
    const ScanContext& context() const noexcept { return context_; }

private:
    // ---------------------------------------------------------------------
    // Validation helpers
    // ---------------------------------------------------------------------
    void validateContext()
    {
        if (context_.tenantId.empty()) {
            throw std::runtime_error("ScanCommand: tenantId cannot be empty");
        }
        if (context_.assetId.empty()) {
            throw std::runtime_error("ScanCommand: assetId cannot be empty");
        }
        // Additional rule: Continuous scans are available only for premium tenants
        if (context_.depth == ScanDepth::Continuous &&
            !isPremiumTenant(context_.tenantId))
        {
            throw std::runtime_error(
                "ScanCommand: Continuous scans require a premium subscription");
        }
    }

    static bool isPremiumTenant(std::string_view tenantId)
    {
        // In a real application this would query billing or subscription service.
        // For demonstration, we treat tenant IDs starting with “PRM-” as premium.
        return tenantId.rfind("PRM-", 0) == 0;
    }

    // ---------------------------------------------------------------------
    // Serialisation helpers
    // ---------------------------------------------------------------------
    std::string buildPayloadJson(std::string_view corrId) const
    {
        // VERY simplistic JSON composition.  Escaping omitted for brevity.
        std::string json;
        json.reserve(256);
        json += "{";
        json += "\"tenantId\":\""      + context_.tenantId + "\",";
        json += "\"assetId\":\""       + context_.assetId  + "\",";
        json += "\"scanDepth\":\""     + depthToString(context_.depth) + "\",";
        json += "\"correlationId\":\"" + std::string(corrId) + "\"";
        json += "}";
        return json;
    }

    static std::string depthToString(ScanDepth depth)
    {
        switch (depth)
        {
            case ScanDepth::Quick:       return "quick";
            case ScanDepth::Deep:        return "deep";
            case ScanDepth::Continuous:  return "continuous";
            default:                     return "unknown";
        }
    }

    // ---------------------------------------------------------------------
    // Correlation-ID helpers
    // ---------------------------------------------------------------------
    static std::string generateCorrelationId()
    {
        // UUID v4 stub—replace with a full UUID generator in production.
        static constexpr char hex[] = "0123456789abcdef";
        std::string uuid(36, '0');
        int         rnd  = 0;
        int         bits = 0;

        for (std::size_t i = 0; i < uuid.size(); ++i)
        {
            switch (i)
            {
                case 8: case 13: case 18: case 23:
                    uuid[i] = '-';
                    break;
                case 14:
                    uuid[i] = '4';                    // version 4
                    break;
                case 19:
                    uuid[i] = hex[(randomByte() & 0x3) | 0x8]; // variant
                    break;
                default:
                    if (bits < 4)
                    {
                        rnd  = randomByte();
                        bits = 8;
                    }
                    uuid[i] = hex[(rnd >> (bits -= 4)) & 0xf];
            }
        }
        return uuid;
    }

    static int randomByte()
    {
        // Thread-local pseudo-random byte.  In production use <random> or
        // OS-supplied CSPRNG for cryptographic quality.
        thread_local uint32_t state =
            static_cast<uint32_t>(std::chrono::high_resolution_clock::now()
                                      .time_since_epoch()
                                      .count());
        state = state * 1664525u + 1013904223u;
        return static_cast<int>((state >> 24) & 0xFF);
    }

    // ---------------------------------------------------------------------
    // Observer helpers
    // ---------------------------------------------------------------------
    void notifyObservers(const Result& r)
    {
        for (auto& obs : observers_) {
            if (obs) { obs(*this, r); }
        }
    }

private:
    ScanContext                             context_;
    std::shared_ptr<infra::IEventBus>       bus_;
    std::vector<Observer>                   observers_;
};

} // namespace fortiledger360::domain::commands

#endif  // FORTILEDGER360_DOMAIN_COMMANDS_SCAN_COMMAND_H