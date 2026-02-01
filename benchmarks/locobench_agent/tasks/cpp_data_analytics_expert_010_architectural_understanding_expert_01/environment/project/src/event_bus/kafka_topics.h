```cpp
/***************************************************************************************
 *  CardioInsight360 – Unified Healthcare Analytics Engine (data_analytics)
 *  ------------------------------------------------------------------------------------
 *  File:    cardio_insight_360/src/event_bus/kafka_topics.h
 *  Author:  CardioInsight360 Core Team
 *
 *  Description:
 *      Centralised, compile-time registry of the Kafka topics used by the in-process
 *      event-streaming subsystem (built on top of librdkafka).  The registry provides:
 *        • Type-safe enumeration of all topics
 *        • Compile-time metadata (name, partition-count, retention policy, etc.)
 *        • Helpers for string↔enum conversion
 *        • Safe accessors for topic metadata with validation
 *
 *      Keeping topic definitions in one place helps:
 *        • Enforce naming conventions across the codebase
 *        • Prevent “stringly-typed” mistakes
 *        • Provide a single-source-of-truth for DevOps automation (Terraform, Ansible,
 *          etc.) that create / configure topics in non-production environments.
 *
 *  Build requirements:
 *      C++17 or later
 *
 *  ------------------------------------------------------------------------------------
 *  Copyright (c) 2024, CardioInsight360
 *  All rights reserved.  Licensed under the Apache License, Version 2.0.
 ***************************************************************************************/

#pragma once

#include <array>
#include <cstdint>
#include <string_view>
#include <stdexcept>
#include <unordered_map>

namespace ci360::event_bus
{

/* -------------------------------------------------------------------------------------------------
 *  Topic enumeration
 * ------------------------------------------------------------------------------------------------*/
enum class Topic : std::uint16_t
{
    // ----------------------------------------------------------------------------------------------
    // NOTE: When adding a new topic, *always* update kTopicRegistry below, or the static_assert that
    // checks for completeness will fail.
    // ----------------------------------------------------------------------------------------------
    RawHL7                    = 0,   // Raw HL7/FHIR messages ingested from hospital systems
    ParsedECG                 = 1,   // JSON representation of parsed ECG wave forms
    VitalSignsQualityAlerts   = 2,   // Quality / validation errors pushed by QC pipeline
    AnalyticsResults          = 3,   // High-level analytics output for dashboards
    Heartbeat                 = 4,   // Internal liveness pings (used by health monitor)
    AuditLogs                 = 5    // Audit / compliance logs (HIPAA)
};

/* -------------------------------------------------------------------------------------------------
 *  Topic metadata
 * ------------------------------------------------------------------------------------------------*/
enum class RetentionPolicy : std::uint8_t
{
    Delete,   // Default Kafka delete policy (time-based retention)
    Compact,  // Kafka log compaction
    Forever   // Retain indefinitely (used for compliance logs, etc.)
};

struct KafkaTopicInfo
{
    Topic               id;
    std::string_view    name;              // Kafka topic string literal
    std::uint16_t       partitions;        // Planned partition count (dev/prod may differ)
    RetentionPolicy     retentionPolicy;
    std::string_view    description;       // Human-readable description

    constexpr bool isCompacted()   const noexcept { return retentionPolicy == RetentionPolicy::Compact; }
    constexpr bool isForever()     const noexcept { return retentionPolicy == RetentionPolicy::Forever; }
};

/* -------------------------------------------------------------------------------------------------
 *  Compile-time registry
 * ------------------------------------------------------------------------------------------------*/
inline constexpr std::array<KafkaTopicInfo, 6> kTopicRegistry
{
    KafkaTopicInfo{
        Topic::RawHL7,
        "ci360.raw_hl7",
        12,
        RetentionPolicy::Delete,
        "Raw HL7/FHIR messages ingested from external hospital systems"
    },
    KafkaTopicInfo{
        Topic::ParsedECG,
        "ci360.parsed_ecg",
        24,
        RetentionPolicy::Delete,
        "Parsed ECG waveforms published by the ECG-ETL pipeline"
    },
    KafkaTopicInfo{
        Topic::VitalSignsQualityAlerts,
        "ci360.vitals.quality_alerts",
        6,
        RetentionPolicy::Delete,
        "Quality / validation alerts generated during signal QC"
    },
    KafkaTopicInfo{
        Topic::AnalyticsResults,
        "ci360.analytics.results",
        12,
        RetentionPolicy::Delete,
        "High-level analytics output consumed by dashboards and alerting services"
    },
    KafkaTopicInfo{
        Topic::Heartbeat,
        "ci360.internal.heartbeat",
        3,
        RetentionPolicy::Compact,
        "Internal liveness probes used by the health-monitoring subsystem"
    },
    KafkaTopicInfo{
        Topic::AuditLogs,
        "ci360.audit_logs",
        3,
        RetentionPolicy::Forever,
        "Audit / compliance logs stored for HIPAA / GDPR requirements"
    }
};

/* -------------------------------------------------------------------------------------------------
 *  Lookup helpers
 * ------------------------------------------------------------------------------------------------*/

/**
 * Convert Topic enum → string-view.
 *
 * Throws std::logic_error if the Topic is not present in the registry (should never happen
 * unless the registry is out of sync with the enum list).
 */
[[nodiscard]] inline constexpr std::string_view to_string(Topic topic)
{
    for (const auto& info : kTopicRegistry)
    {
        if (info.id == topic) { return info.name; }
    }
    throw std::logic_error{"ci360::event_bus::to_string – Unknown Topic enum value"};
}

/**
 * Lookup metadata for a given topic.
 *
 * Complexity: O(N) with small, fixed N. For runtime hotpaths we additionally cache lookups
 * in an unordered_map (lazy initialised) to achieve O(1) average complexity.
 */
[[nodiscard]] inline const KafkaTopicInfo& get_topic_info(Topic topic)
{
    // Fast path: static cache initialised on first use
    static const std::unordered_map<Topic, const KafkaTopicInfo*, std::hash<std::uint16_t>> kCache = [] {
        std::unordered_map<Topic, const KafkaTopicInfo*, std::hash<std::uint16_t>> map;
        for (const auto& entry : kTopicRegistry) { map.emplace(entry.id, &entry); }
        return map;
    }();

    auto it = kCache.find(topic);
    if (it == kCache.end())
    {
        throw std::logic_error{"ci360::event_bus::get_topic_info – Unknown Topic enum value"};
    }
    return *(it->second);
}

/**
 * Convert string-view → Topic enum.
 *
 * Throws std::invalid_argument if the name is not registered.
 */
[[nodiscard]] inline Topic parse_topic(std::string_view name)
{
    for (const auto& entry : kTopicRegistry)
    {
        if (entry.name == name) { return entry.id; }
    }
    throw std::invalid_argument{"ci360::event_bus::parse_topic – Unknown Kafka topic name"};
}

/* -------------------------------------------------------------------------------------------------
 *  Compile-time defence: ensure registry completeness.
 * ------------------------------------------------------------------------------------------------*/
static_assert([] {
    // Ensure every enum value appears exactly once in the registry
    std::array<bool, static_cast<std::size_t>(Topic::AuditLogs) + 1> seen{};
    for (const auto& entry : kTopicRegistry)
    {
        auto idx = static_cast<std::size_t>(entry.id);
        if (idx >= seen.size() || seen[idx]) { return false; }
        seen[idx] = true;
    }
    for (auto v : seen) { if (!v) return false; }
    return true;
}(), "kTopicRegistry is either missing a Topic or contains duplicates");

} // namespace ci360::event_bus
```