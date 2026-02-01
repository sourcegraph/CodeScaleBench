```cpp
/**
 * cardio_insight_360/src/ingestion/parsers/fhir_parser.cpp
 *
 * Implementation of the FHIR-JSON bundle parser used by the CardioInsight360
 * ingestion subsystem.  The parser converts raw FHIR bundles into strongly-typed
 * internal domain events and publishes them on the in-process event bus.
 *
 * The implementation relies on a pluggable “Strategy” layer for resource-
 * specific parsing.  New strategies can be registered at runtime without
 * touching the core parser logic, making the component easily extensible for
 * additional FHIR resource types (e.g., Medication, DiagnosticReport, Imaging).
 *
 * Dependencies
 *   – nlohmann/json   :  Header-only JSON library for parsing.
 *   – spdlog          :  Robust logging.
 *   – C++17 STL       :  <memory>, <unordered_map>, <atomic>, <mutex>, …
 *
 * NOTE:
 *   In the full CardioInsight360 code-base the forward-declared entities
 *   (EventBusPublisher, ObservationEvent, etc.) live in their own translation
 *   units.  They are replicated here as minimal stubs so that this file is
 *   self-contained and can be compiled in isolation for demonstration purposes.
 */

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

using json = nlohmann::json;

/*───────────────────────────────────────────────────────────────────────────┐
│ Forward declarations / minimal stubs (real versions live elsewhere)       │
└───────────────────────────────────────────────────────────────────────────*/
namespace ci360::event
{
class Event
{
public:
    virtual ~Event() = default;
};
using EventPtr = std::shared_ptr<Event>;

/* Domain-specific event stubs */
class ObservationEvent final : public Event
{
public:
    std::string                             sourceId;
    std::string                             patientId;
    std::string                             encounterId;
    std::string                             code;
    std::string                             displayName;
    double                                  value           = 0.0;
    std::string                             unit;
    std::chrono::system_clock::time_point   effectiveTimestamp{};
    std::chrono::system_clock::time_point   receivedTimestamp{};
};

class PatientEvent final : public Event
{
public:
    std::string                             patientId;
    std::string                             givenName;
    std::string                             familyName;
    std::string                             sourceId;
    bool                                    active          = false;
    std::chrono::system_clock::time_point   receivedTimestamp{};
};
} // namespace ci360::event

/* Event-bus publisher interface stub */
namespace ci360::bus
{
class EventBusPublisher
{
public:
    virtual ~EventBusPublisher()                       = default;
    virtual void publish(const ci360::event::EventPtr& evt) = 0;
};
} // namespace ci360::bus

/* Context object describing where/how the bundle was received. */
namespace ci360::ingestion
{
struct IngestionContext
{
    std::string                             sourceId;
    std::chrono::system_clock::time_point   receivedTimestamp;
};
} // namespace ci360::ingestion

/*───────────────────────────────────────────────────────────────────────────┐
│                       FHIR Parser Implementation                           │
└───────────────────────────────────────────────────────────────────────────*/
namespace ci360::ingestion::parsers
{
/*----------------------------------------------------------------------+
| Resource-specific parsing strategy interface.                         |
+----------------------------------------------------------------------*/
class IResourceStrategy
{
public:
    virtual ~IResourceStrategy() = default;

    /* Parse a single FHIR resource and emit zero or more domain events. */
    virtual void parse(const json&                      resource,
                       const IngestionContext&          ctx,
                       bus::EventBusPublisher&          publisher) = 0;
};

/*----------------------------------------------------------------------+
| Observation-resource strategy.                                        |
+----------------------------------------------------------------------*/
class ObservationStrategy final : public IResourceStrategy
{
public:
    void parse(const json&                      resource,
               const IngestionContext&          ctx,
               bus::EventBusPublisher&          publisher) override
    {
        try
        {
            /* Basic schema validation. */
            if (!resource.contains("code") || !resource.contains("valueQuantity"))
                throw std::invalid_argument("Observation missing mandatory elements.");

            /* Build internal event. */
            auto evt                       = std::make_shared<event::ObservationEvent>();
            evt->sourceId                  = ctx.sourceId;
            evt->receivedTimestamp         = ctx.receivedTimestamp;
            evt->patientId                 = resource.value("subject", json{}).value("reference", "");
            evt->encounterId               = resource.value("encounter", json{}).value("reference", "");
            evt->code                      = resource["code"]["coding"].front().value("code", "");
            evt->displayName               = resource["code"]["coding"].front().value("display", "");
            evt->value                     = resource["valueQuantity"].value("value", 0.0);
            evt->unit                      = resource["valueQuantity"].value("unit", "");
            evt->effectiveTimestamp        = parseTimestamp(resource.value("effectiveDateTime", ""));

            publisher.publish(evt);
            metrics_.parsed.fetch_add(1, std::memory_order_relaxed);
        }
        catch (const std::exception& ex)
        {
            metrics_.failed.fetch_add(1, std::memory_order_relaxed);
            throw;      /* Propagate to caller for centralized handling. */
        }
    }

private:
    static std::chrono::system_clock::time_point parseTimestamp(const std::string& iso8601)
    {
        using namespace std::chrono;

        /* Extremely simplified ISO-8601 parser —
         *  real implementation uses `date::zoned_time` or a full parser. */
        if (iso8601.empty())
            return system_clock::now();

        try
        {
            const std::int64_t epochMs = std::stoll(iso8601);
            return system_clock::time_point{milliseconds{epochMs}};
        }
        catch (...)
        {
            return system_clock::now();
        }
    }

    struct
    {
        std::atomic_uint64_t parsed{0};
        std::atomic_uint64_t failed{0};
    } metrics_;
};

/*----------------------------------------------------------------------+
| Patient-resource strategy (simplified).                               |
+----------------------------------------------------------------------*/
class PatientStrategy final : public IResourceStrategy
{
public:
    void parse(const json&                      resource,
               const IngestionContext&          ctx,
               bus::EventBusPublisher&          publisher) override
    {
        if (!resource.contains("id"))
            throw std::invalid_argument("Patient missing id.");

        auto evt               = std::make_shared<event::PatientEvent>();
        evt->patientId         = resource.value("id", "");
        evt->sourceId          = ctx.sourceId;
        evt->receivedTimestamp = ctx.receivedTimestamp;
        evt->active            = resource.value("active", false);

        if (resource.contains("name") && !resource["name"].empty())
        {
            const json& name   = resource["name"].front();
            evt->familyName    = name.value("family", "");
            if (name.contains("given") && !name["given"].empty())
                evt->givenName = name["given"].front().get<std::string>();
        }

        publisher.publish(evt);
        metrics_.parsed.fetch_add(1, std::memory_order_relaxed);
    }

private:
    struct
    {
        std::atomic_uint64_t parsed{0};
    } metrics_;
};

/*----------------------------------------------------------------------+
| Main FhirParser facade.                                               |
+----------------------------------------------------------------------*/
class FhirParser
{
public:
    struct Metrics
    {
        std::atomic_uint64_t bundlesProcessed{0};
        std::atomic_uint64_t unsupportedResources{0};
        std::atomic_uint64_t resourceFailures{0};
    };

    explicit FhirParser(std::shared_ptr<bus::EventBusPublisher> publisher)
        : publisher_(std::move(publisher))
    {
        /* Register default strategies. */
        strategies_.emplace("Observation", std::make_unique<ObservationStrategy>());
        strategies_.emplace("Patient",     std::make_unique<PatientStrategy>());

        spdlog::info("FHIR parser initialized ({} strategies).", strategies_.size());
    }

    ~FhirParser() = default;

    /* Parse an entire FHIR bundle. */
    void parseBundle(std::string_view            payload,
                     const IngestionContext&     ctx)
    {
        json bundle;
        try
        {
            bundle = json::parse(payload);
        }
        catch (const json::parse_error& ex)
        {
            spdlog::error("JSON parse error: {}", ex.what());
            throw;
        }

        if (bundle.value("resourceType", "") != "Bundle")
            throw std::invalid_argument("Payload is not a FHIR Bundle.");

        if (!bundle.contains("entry") || !bundle["entry"].is_array())
        {
            spdlog::warn("FHIR Bundle contains no entries.");
            return;
        }

        /* Iterate over all resources. */
        std::shared_lock lock(strategyMutex_);
        for (const auto& entry : bundle["entry"])
        {
            if (!entry.contains("resource"))
                continue;

            const json&     resource = entry["resource"];
            const std::string rType  = resource.value("resourceType", "");

            auto it = strategies_.find(rType);
            if (it == strategies_.end())
            {
                metrics_.unsupportedResources.fetch_add(1, std::memory_order_relaxed);
                spdlog::debug("Unsupported resourceType '{}' — skipped.", rType);
                continue;
            }

            try
            {
                it->second->parse(resource, ctx, *publisher_);
            }
            catch (const std::exception& ex)
            {
                metrics_.resourceFailures.fetch_add(1, std::memory_order_relaxed);
                spdlog::warn("Failed to parse {}: {}", rType, ex.what());
            }
        }

        metrics_.bundlesProcessed.fetch_add(1, std::memory_order_relaxed);
    }

    /* Dynamically register a new strategy. */
    void registerStrategy(std::string                       resourceType,
                          std::unique_ptr<IResourceStrategy> strategy)
    {
        if (!strategy)
            throw std::invalid_argument("Strategy pointer must not be null.");

        std::unique_lock lock(strategyMutex_);
        if (auto [it, inserted] = strategies_.emplace(
                std::move(resourceType), std::move(strategy));
            !inserted)
        {
            spdlog::warn("Strategy for resourceType '{}' already exists — replaced.", it->first);
        }
    }

    [[nodiscard]] const Metrics& metrics() const noexcept { return metrics_; }

private:
    Metrics metrics_;

    std::unordered_map<std::string, std::unique_ptr<IResourceStrategy>> strategies_;
    std::shared_ptr<bus::EventBusPublisher>                             publisher_;
    mutable std::shared_mutex                                           strategyMutex_;
};

} // namespace ci360::ingestion::parsers
```