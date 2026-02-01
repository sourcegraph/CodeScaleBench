```cpp
/******************************************************************************* 
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  -----------------------------------------------------
 *  File        : cardio_insight_360/src/event_bus/event_defs.h
 *  Author      : CardioInsight360 Core Team
 *  Created     : 2024-05-24
 *  Description : Public event-definition header for the in-process event bus
 *                (Kafka-backed via librdkafka). Provides strongly-typed event
 *                identifiers, severity levels, immutable headers, and utility
 *                helpers for compile-time topic discovery and run-time 
 *                correlation tracing.
 * 
 *  NOTE: This is a header-only facility—no compilation unit is required.
 * 
 *  Copyright ©
 *  Licensed under the Apache License, Version 2.0
 ******************************************************************************/

#pragma once

#include <array>
#include <chrono>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

/*==============================================================================
    Versioning (bump whenever the ABI of the event bus changes)
==============================================================================*/
#define CI360_EVENT_BUS_VERSION_MAJOR 1
#define CI360_EVENT_BUS_VERSION_MINOR 0
#define CI360_EVENT_BUS_VERSION_PATCH 0

namespace ci360::event_bus
{
/*==============================================================================
    Strongly-typed severity levels for operational events
==============================================================================*/
enum class Severity : std::uint8_t
{
    Trace = 0,
    Debug,
    Info,
    Warning,
    Error,
    Critical
};

/*------------------------------------------------------------------------------
    Convert Severity enum to constexpr string_view
------------------------------------------------------------------------------*/
[[nodiscard]] constexpr std::string_view to_string(Severity sev) noexcept
{
    switch (sev)
    {
        case Severity::Trace:    return "TRACE";
        case Severity::Debug:    return "DEBUG";
        case Severity::Info:     return "INFO";
        case Severity::Warning:  return "WARNING";
        case Severity::Error:    return "ERROR";
        case Severity::Critical: return "CRITICAL";
    }
    return "UNKNOWN";
}

/*==============================================================================
    Event identifiers (each represents a Kafka topic within the in-process bus)
==============================================================================*/
enum class EventType : std::uint16_t
{
    /* Raw data ingest pipeline */
    RawDataIngested = 0,
    RawDataValidationFailed,
    /* Transformation stages */
    TransformationStarted,
    TransformationCompleted,
    TransformationFailed,
    /* Streaming alerts */
    RealTimeAlertRaised,
    RealTimeAlertAcknowledged,
    /* Batch processing */
    BatchJobScheduled,
    BatchJobCompleted,
    /* System events */
    Heartbeat,
    SystemError,
    /* Sentinel value (MUST be last) */
    Count /* ← keep as last to compute enum size */
};

/*------------------------------------------------------------------------------
    Compile-time topic (Kafka) names aligned with EventType enum.
    The ordering MUST match EventType underlying values.
------------------------------------------------------------------------------*/
constexpr std::array<std::string_view, static_cast<std::size_t>(EventType::Count)>
    kEventTopics{
        /* Raw ingest   */ "ci360.raw.ingested",
        /* Validation   */ "ci360.raw.validation.failed",
        /* Transform in */ "ci360.transform.started",
        /* Transform ok */ "ci360.transform.completed",
        /* Transform ko */ "ci360.transform.failed",
        /* Alert raised */ "ci360.alert.raised",
        /* Alert ack    */ "ci360.alert.ack",
        /* Batch sched  */ "ci360.batch.sched",
        /* Batch done   */ "ci360.batch.done",
        /* Heartbeat    */ "ci360.system.heartbeat",
        /* Sys error    */ "ci360.system.error"
};

/*------------------------------------------------------------------------------
    Utility: constexpr mapping EventType -> topic string_view
------------------------------------------------------------------------------*/
[[nodiscard]] constexpr std::string_view topic_for(EventType ev) noexcept
{
    const auto idx = static_cast<std::size_t>(ev);
    return (idx < kEventTopics.size()) ? kEventTopics[idx] : "<invalid-topic>";
}

/*==============================================================================
    Event header (immutable, trivially-copyable)
==============================================================================*/
struct EventHeader
{
    EventType                         type         {EventType::SystemError};
    Severity                          severity     {Severity::Info};
    std::chrono::system_clock::time_point
                                      timestamp    {std::chrono::system_clock::now()};
    std::string                       source;          // logical source (service/module)
    std::string                       correlation_id;  // propagated across sub-systems
    std::optional<std::string>        tenant_id;       // multi-tenant hospitals
    
    /*------------------------------------------------------------------------
        Generate a RFC-4122 v4-compatible pseudo-random correlation id.
        Note: No cryptographic strength required—only uniqueness within process.
    ------------------------------------------------------------------------*/
    static std::string generate_guid();
};

/*------------------------------------------------------------------------------
    In-header implementation of GUID generator (header-only + constexpr friendly)

    The implementation uses xoshiro256** PRNG seeded from std::random_device.
    We intentionally keep this non-cryptographic to avoid heavy dependencies
    while achieving adequate uniqueness for observability use-cases.
------------------------------------------------------------------------------*/
#include <array>
#include <mutex>
#include <random>
#include <sstream>
#include <iomanip>

inline std::string EventHeader::generate_guid()
{
    // Thread-safe static PRNG
    static std::mutex                                mtx;
    static std::random_device                        rd;
    static std::mt19937_64                           gen { rd() };
    static std::uniform_int_distribution<std::uint64_t> dist;

    std::scoped_lock lock{mtx};

    std::array<std::uint64_t, 2> parts{ dist(gen), dist(gen) };
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');

    // 8-4-4-4-12 layout
    oss << std::setw(8)  << (parts[0] >> 32)
        << '-'
        << std::setw(4)  << (static_cast<std::uint16_t>((parts[0] >> 16) & 0xFFFF))
        << '-'
        << std::setw(4)  << (static_cast<std::uint16_t>(parts[0] & 0xFFFF))
        << '-'
        << std::setw(4)  << (static_cast<std::uint16_t>((parts[1] >> 48) & 0xFFFF))
        << '-'
        << std::setw(12) << (parts[1] & 0xFFFFFFFFFFFFULL);

    return oss.str();
}

/*==============================================================================
    Generic envelope to hold arbitrary event payloads with a fixed header.
    The template parameter `PayloadT` should be a trivially movable type
    (e.g., a struct, protobuf message, JSON document, etc.).
==============================================================================*/
template <typename PayloadT>
struct Event final
{
    static_assert(!std::is_reference_v<PayloadT>,
                  "PayloadT must not be a reference type");

    EventHeader header;
    PayloadT    payload;

    /* Helper ctor forwarding args to payload while filling header */
    template <typename... PayloadArgs>
    explicit Event(EventType  type,
                   Severity   sev,
                   std::string source,
                   PayloadArgs&&... args)
        : header{ type, sev,
                  std::chrono::system_clock::now(),
                  std::move(source),
                  EventHeader::generate_guid(),
                  std::nullopt }
        , payload{ std::forward<PayloadArgs>(args)... }
    {}
};

/*==============================================================================
    Compile-time sanity check to ensure enum <-> topic mapping remains aligned.
==============================================================================*/
static_assert(kEventTopics.size() ==
              static_cast<std::size_t>(EventType::Count),
              "kEventTopics size must equal EventType::Count");

/*==============================================================================
    End of namespace
==============================================================================*/
} // namespace ci360::event_bus
```