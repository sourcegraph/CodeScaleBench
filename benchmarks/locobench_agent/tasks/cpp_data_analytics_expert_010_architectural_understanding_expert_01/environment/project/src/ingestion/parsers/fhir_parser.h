```cpp
/************************************************************************************
 *  File:    fhir_parser.h
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      High-level API for parsing HL7® FHIR® (Fast Healthcare Interoperability
 *      Resources) artifacts into CardioInsight360’s internal data-model.  The
 *      parser is capable of processing individual resources (Patient,
 *      Observation, Encounter, etc.) as well as full Bundle objects.  Output is
 *      returned as strongly-typed domain entities that can be forwarded to the
 *      ETL pipeline or directly published onto the in-process event bus.
 *
 *  Design notes:
 *      • Strategy Pattern — Allows registration of custom “resource strategies”
 *        for resource types that are cardiology-specific (e.g., ECG-waveform
 *        Observation or Cath-Lab Procedure).
 *      • Thread safety   — Instances are intended to be shared across TBB
 *        worker threads; all public APIs are therefore thread-safe.
 *      • Error handling  — Rich error context via FHIRParserError which
 *        carries JSON pointer location, offending value, and root cause.
 *
 *  © 2024 CardioInsight Healthcare Solutions.  All rights reserved.
 ************************************************************************************/

#pragma once

// STL
#include <cstdint>
#include <functional>
#include <istream>
#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <variant>
#include <vector>

// 3rd-party
#include <nlohmann/json.hpp>   // MIT license — https://github.com/nlohmann/json

// Forward declarations for domain model entities
namespace cardioinsight360::model {
class Patient;
class Observation;
class Encounter;
class Bundle;
} // namespace cardioinsight360::model

namespace cardioinsight360::ingestion::parsers {

/*======================================================
 *  class FHIRParserError
 *------------------------------------------------------
 *  A specialized exception type that offers granular
 *  insight into parsing failures.  The object captures:
 *      • Location   — JSON pointer (RFC 6901)
 *      • Offender   — Snippet of the raw JSON (truncated)
 *      • Severity   — Error / Warning
 *====================================================*/
class FHIRParserError final : public std::runtime_error
{
public:
    enum class Severity : std::uint8_t { Warning, Error };

    explicit FHIRParserError(std::string_view message,
                             std::string_view jsonPointer = "",
                             std::string_view offender     = "",
                             Severity        severity      = Severity::Error) noexcept
        : std::runtime_error(std::string(message))
        , m_pointer(jsonPointer)
        , m_offender(offender)
        , m_severity(severity)
    {}

    [[nodiscard]] std::string_view jsonPointer() const noexcept { return m_pointer; }
    [[nodiscard]] std::string_view offender()    const noexcept { return m_offender; }
    [[nodiscard]] Severity         severity()    const noexcept { return m_severity; }

private:
    std::string m_pointer;
    std::string m_offender;
    Severity    m_severity;
};


/*======================================================
 *  class FHIRParser
 *------------------------------------------------------
 *  Thread-safe façade for translating arbitrary FHIR
 *  resources into CI360 domain entities.
 *
 *  Example usage:
 *
 *      auto parser   = cardioinsight360::ingestion::parsers::FHIRParser::create();
 *      auto patient  = parser->parsePatient(jsonPayload);
 *      eventBus.publish(patient);  // real-time stream
 *====================================================*/
class FHIRParser : public std::enable_shared_from_this<FHIRParser>
{
public:
    using json                = nlohmann::json;
    using ResourceVariant     = std::variant<
        std::shared_ptr<model::Patient>,
        std::shared_ptr<model::Observation>,
        std::shared_ptr<model::Encounter>,
        std::shared_ptr<model::Bundle>>;

    /*--------------------------------------------------
     * Factory
     *------------------------------------------------*/
    static std::shared_ptr<FHIRParser> create();

    virtual ~FHIRParser() = default;

    /*--------------------------------------------------
     * High-level convenience methods
     *------------------------------------------------*/
    virtual std::shared_ptr<model::Patient>
    parsePatient(const std::string& jsonPayload) const = 0;

    virtual std::shared_ptr<model::Observation>
    parseObservation(const std::string& jsonPayload) const = 0;

    virtual std::shared_ptr<model::Bundle>
    parseBundle(const std::string& jsonPayload) const = 0;

    /*--------------------------------------------------
     * Generic API – dynamically detects resource type
     *------------------------------------------------*/
    virtual ResourceVariant
    parseResource(const std::string& jsonPayload) const = 0;

    /*--------------------------------------------------
     * Streaming API – parse from std::istream
     *------------------------------------------------*/
    virtual ResourceVariant
    parseResource(std::istream& inputStream) const = 0;

    /*--------------------------------------------------
     * Strategy registration
     *
     *  Allows injection of custom handlers for new /
     *  proprietary resource types.  Handlers are executed
     *  in a deterministic order (FIFO registration).
     *------------------------------------------------*/
    using StrategyHandler =
        std::function<ResourceVariant(const json& raw, const FHIRParser& ctx)>;

    virtual void registerStrategy(std::string_view resourceType,
                                  StrategyHandler   handler)             = 0;

    /*--------------------------------------------------
     * Parser configuration
     *------------------------------------------------*/
    struct Config
    {
        std::string         targetFhirVersion         { "4.0.1" };
        bool                validateSchema            { true  };
        bool                allowUnknownExtensions    { false };
        std::size_t         maxJsonByteSize           { 5 * 1024 * 1024 }; // 5 MB
        std::vector<std::string> whitelistProfiles    {};  // URIs

        // Helper: populate from environment variables
        static Config fromEnvironment();
    };

    virtual void setConfig(Config cfg)               = 0;
    [[nodiscard]] virtual const Config& config() const noexcept = 0;

protected:
    FHIRParser() = default;
};


/*======================================================
 *  class DefaultFHIRParser
 *------------------------------------------------------
 *  Production-grade implementation that leverages
 *  nlohmann::json for parsing and employs an internal
 *  LRU cache for compiled JSON schema artifacts.
 *
 *  Note: The implementation details reside in the .cpp
 *  translation unit to keep this header lightweight.
 *====================================================*/
class DefaultFHIRParser final : public FHIRParser
{
public:
    DefaultFHIRParser();
    ~DefaultFHIRParser() override;

    // Disable copy / move semantics (shared via factory)
    DefaultFHIRParser(const DefaultFHIRParser&)            = delete;
    DefaultFHIRParser& operator=(const DefaultFHIRParser&) = delete;
    DefaultFHIRParser(DefaultFHIRParser&&)                 = delete;
    DefaultFHIRParser& operator=(DefaultFHIRParser&&)      = delete;

    /*--------------------------------------------------
     * FHIRParser interface implementation
     *------------------------------------------------*/
    std::shared_ptr<model::Patient>
    parsePatient(const std::string& jsonPayload) const override;

    std::shared_ptr<model::Observation>
    parseObservation(const std::string& jsonPayload) const override;

    std::shared_ptr<model::Bundle>
    parseBundle(const std::string& jsonPayload) const override;

    ResourceVariant
    parseResource(const std::string& jsonPayload) const override;

    ResourceVariant
    parseResource(std::istream& inputStream) const override;

    void registerStrategy(std::string_view resourceType,
                          StrategyHandler   handler) override;

    void setConfig(Config cfg) override;
    [[nodiscard]] const Config& config() const noexcept override;

private:
    /*--------------------------------------------------
     * Internal helpers
     *------------------------------------------------*/
    ResourceVariant parseImpl(const json& j) const;
    void            validateAgainstSchema(const json& j) const;

    /*--------------------------------------------------
     * Data members
     *------------------------------------------------*/
    mutable std::recursive_mutex m_mutex;
    Config                       m_cfg;
    std::unordered_map<std::string, StrategyHandler> m_strategies;
};

} // namespace cardioinsight360::ingestion::parsers
```