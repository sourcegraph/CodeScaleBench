#include "ingestion/parsers/hl7_parser.hpp"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include <boost/algorithm/string.hpp>
#include <boost/lexical_cast.hpp>
#include <nlohmann/json.hpp>

#include "common/config/runtime_config.hpp"        // Centralized config singleton
#include "common/logging/logger.hpp"               // Thread-safe logger
#include "common/metrics/metrics_registry.hpp"     // Counter / Histogram
#include "ingestion/parsers/hl7_validation.hpp"    // Domain-specific validators

namespace ci360::ingestion::parsers
{

// ──────────────────────────────────────────────────────────────────────────────
//                               Helper Utilities
// ──────────────────────────────────────────────────────────────────────────────
namespace
{
constexpr char DEFAULT_SEGMENT_TERMINATOR{'\r'};
constexpr size_t MIN_MSH_LENGTH            = 9;   // “MSH|^~\&” + 1 extra char

std::string sanitize_input(std::string_view raw)
{
    // Remove any trailing newline characters (\r\n or \n)
    std::string cleaned{raw};
    boost::algorithm::trim_right_if(cleaned, [](char c) { return c == '\r' || c == '\n'; });
    return cleaned;
}

} // namespace

// ──────────────────────────────────────────────────────────────────────────────
//                         HL7Message – public interface
// ──────────────────────────────────────────────────────────────────────────────
const HL7Segment& HL7Message::get_segment(const std::string& name) const
{
    auto iter = segment_index_.find(name);
    if (iter == segment_index_.end())
    {
        throw HL7Exception{"Segment '" + name + "' not present in message"};
    }
    return *iter->second;
}

bool HL7Message::has_segment(const std::string& name) const noexcept
{
    return segment_index_.find(name) != segment_index_.end();
}

nlohmann::json HL7Message::to_json() const
{
    nlohmann::json j;
    for (const auto& segment : segments_)
    {
        j[segment.tag()] = segment.to_json();
    }
    return j;
}

// ──────────────────────────────────────────────────────────────────────────────
//                       HL7Parser – implementation details
// ──────────────────────────────────────────────────────────────────────────────
HL7Parser::HL7Parser()
    : metrics_{common::metrics::MetricsRegistry::instance()}
{
    // Pre-register metrics so that dashboards show zeros instead of N/A
    metrics_.counter("hl7_parser.messages_total");
    metrics_.counter("hl7_parser.messages_failed");
    metrics_.histogram("hl7_parser.segments_per_message");
}

HL7Message HL7Parser::parse(std::string_view raw_msg) const
{
    using namespace common::logging;
    auto& logger = Logger::instance();

    metrics_.counter("hl7_parser.messages_total").increment();

    std::string cleaned = sanitize_input(raw_msg);
    if (cleaned.size() < MIN_MSH_LENGTH)
    {
        metrics_.counter("hl7_parser.messages_failed").increment();
        throw HL7Exception{"Incoming payload too short to be a valid HL7 MSH segment"};
    }

    // ─── Parse delimiter characters from the MSH segment ────────────────────
    HL7Delimiter delimiter;
    delimiter.field       = cleaned.at(3);
    delimiter.component   = cleaned.at(4);
    delimiter.repetition  = cleaned.at(5);
    delimiter.escape      = cleaned.at(6);
    delimiter.subcomponent = cleaned.at(7);

    // ─── Split message into segments ────────────────────────────────────────
    std::vector<std::string> segments_raw;
    boost::algorithm::split(segments_raw, cleaned, [=](char c) { return c == DEFAULT_SEGMENT_TERMINATOR; },
                            boost::token_compress_on);

    if (segments_raw.empty() || !boost::algorithm::starts_with(segments_raw.front(), "MSH"))
    {
        metrics_.counter("hl7_parser.messages_failed").increment();
        throw HL7Exception{"MSH segment missing or malformed"};
    }

    HL7Message message{delimiter};
    message.segments_.reserve(segments_raw.size());

    try
    {
        for (auto& raw_segment : segments_raw)
        {
            if (raw_segment.empty()) continue;
            HL7Segment seg = parse_segment(raw_segment, delimiter);
            message.segment_index_[seg.tag()] = &message.segments_.emplace_back(std::move(seg));
        }
    }
    catch (const std::exception& ex)
    {
        metrics_.counter("hl7_parser.messages_failed").increment();
        logger.error("HL7Parser failure: {}", ex.what());
        throw; // Re-throw to caller
    }

    metrics_.histogram("hl7_parser.segments_per_message").observe(message.segments_.size());

    // Domain-specific validation (Strategy pattern internally dispatched)
    validators_.run_all(message);

    logger.debug("Successfully parsed HL7 message with {} segments", message.segments_.size());
    return message;
}

HL7Segment HL7Parser::parse_segment(const std::string& raw, const HL7Delimiter& delimiter) const
{
    using boost::algorithm::split;
    using boost::algorithm::is_any_of;

    std::vector<std::string> fields;
    split(fields, raw, is_any_of(std::string(1, delimiter.field)));

    if (fields.empty())
    {
        throw HL7Exception{"Encountered empty HL7 segment"};
    }

    HL7Segment segment(fields.front(), delimiter);
    segment.fields_.reserve(fields.size() - 1);

    // Note: MSH has special semantics—the first field is 'MSH' then the field separator
    const bool is_msh = (segment.tag() == "MSH");
    size_t start_idx  = is_msh ? 1 /* Keep the field separator char */ : 0;

    for (size_t i = start_idx; i < fields.size(); ++i)
    {
        segment.fields_.emplace_back(parse_field(fields[i], delimiter));
    }

    return segment;
}

HL7Component HL7Parser::parse_field(const std::string& raw, const HL7Delimiter& delimiter) const
{
    using boost::algorithm::split;
    using boost::algorithm::is_any_of;

    if (raw.empty()) return {};

    HL7Component field;

    std::vector<std::string> components;
    split(components, raw, is_any_of(std::string(1, delimiter.component)));

    field.components.reserve(components.size());
    for (auto& comp : components)
    {
        HL7SubComponent sc;
        boost::algorithm::split(sc.values, comp,
                                boost::algorithm::is_any_of(std::string(1, delimiter.subcomponent)));
        field.components.emplace_back(std::move(sc));
    }

    return field;
}

// ──────────────────────────────────────────────────────────────────────────────
//                     HL7Delimiter – to_string (debugging)
// ──────────────────────────────────────────────────────────────────────────────
std::string HL7Delimiter::to_string() const
{
    std::ostringstream oss;
    oss << "{field='" << field << "', component='" << component << "', repetition='"
        << repetition << "', escape='" << escape << "', subcomponent='" << subcomponent << "'}";
    return oss.str();
}

// ──────────────────────────────────────────────────────────────────────────────
//                             HL7Segment Helpers
// ──────────────────────────────────────────────────────────────────────────────
nlohmann::json HL7Segment::to_json() const
{
    nlohmann::json j;
    for (size_t i = 0; i < fields_.size(); ++i)
    {
        j[std::to_string(i + 1)] = fields_[i].to_json();
    }
    return j;
}

nlohmann::json HL7Component::to_json() const
{
    nlohmann::json j;
    for (size_t i = 0; i < components.size(); ++i)
    {
        j[std::to_string(i + 1)] = components[i].to_json();
    }
    return j;
}

nlohmann::json HL7SubComponent::to_json() const
{
    if (values.size() == 1) return values.front();
    return values;
}

// ──────────────────────────────────────────────────────────────────────────────
//                          Strategy Validator Registry
// ──────────────────────────────────────────────────────────────────────────────
HL7Parser::ValidatorRegistry::ValidatorRegistry()
{
    // Example registration; actual implementations reside elsewhere
    register_validator(std::make_unique<validators::MSHValidator>());
    register_validator(std::make_unique<validators::PIDValidator>());
}

void HL7Parser::ValidatorRegistry::register_validator(std::unique_ptr<validators::BaseValidator>&& validator)
{
    const auto tag = validator->segment_tag();
    validators_.emplace(tag, std::move(validator));
}

void HL7Parser::ValidatorRegistry::run_all(const HL7Message& msg) const
{
    for (const auto& [tag, validator] : validators_)
    {
        if (msg.has_segment(tag))
        {
            validator->validate(msg.get_segment(tag));
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
//                                    EOF
// ──────────────────────────────────────────────────────────────────────────────
} // namespace ci360::ingestion::parsers