#pragma once
/**
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * File path : cardio_insight_360/src/domain/data_models.h
 *
 * This header aggregates the core *Domain* data-models used across the
 * analytics pipeline—covering patient identity, device meta-data, physiological
 * samples, and data-quality metrics.  All models are
 *  • Strongly-typed
 *  • JSON-serialisable (nlohmann::json)
 *  • Equipped with lightweight validation helpers
 *
 * NOTE:  The header is intentionally header-only because most models are
 *        Plain-Old-Data (POD) style structures that are shared across many
 *        translation units; keeping them header-only avoids redundant
 *        boiler-plate linkage code while still compiling quickly.
 */

#include <array>
#include <chrono>
#include <cstdint>
#include <exception>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>     // 3rd-party single-header JSON lib (MIT)

/*-----------------------------------------------------------------------------*
 * Helper macros / constants
 *-----------------------------------------------------------------------------*/
#if !defined(CI360_UNUSED)
#  define CI360_UNUSED(x) (void)(x)
#endif

namespace cardio_insight::domain
{

/*-----------------------------------------------------------------------------*
 * Common aliases
 *-----------------------------------------------------------------------------*/
using Timestamp = std::chrono::system_clock::time_point;

/*-----------------------------------------------------------------------------*
 * Enumerations
 *-----------------------------------------------------------------------------*/
enum class Sex : uint8_t
{
    Unknown = 0,
    Male,
    Female,
    Other
};

enum class DeviceType : uint8_t
{
    Unknown = 0,
    BedsideMonitor,
    WearableECG,
    ImagingArchive
};

enum class ArrhythmiaLabel : uint8_t
{
    None = 0,
    NormalSinus,
    AFib,
    VTach,
    VFib,
    PVC,
    Paced
};

/*-----------------------------------------------------------------------------*
 * Utility – time conversions
 *-----------------------------------------------------------------------------*/
inline std::string to_iso8601(const Timestamp& ts)
{
    using namespace std::chrono;
    std::time_t t = system_clock::to_time_t(ts);
    std::tm tm{};
#if defined(_MSC_VER)
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[32]{};
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return std::string{buf};
}

inline Timestamp from_iso8601(const std::string_view iso)
{
    std::tm tm{};
    if (strptime(iso.data(), "%Y-%m-%dT%H:%M:%SZ", &tm) == nullptr)
    {
        throw std::invalid_argument{"Invalid ISO-8601 date/time."};
    }
    std::time_t t = timegm(&tm);
    return std::chrono::system_clock::from_time_t(t);
}

/*-----------------------------------------------------------------------------*
 * Domain structs
 *-----------------------------------------------------------------------------*/
struct PatientIdentity
{
    std::string medical_record_number;   // MRN – globally unique per hospital
    std::string first_name;
    std::string last_name;
    std::string date_of_birth;           // ISO-8601 date; zero-padded (YYYY-MM-DD)
    Sex         sex{Sex::Unknown};

    [[nodiscard]] bool validate() const noexcept
    {
        return !medical_record_number.empty()
            && !date_of_birth.empty();
    }

    [[nodiscard]] std::string full_name() const
    {
        return first_name + " " + last_name;
    }
};

struct DeviceInfo
{
    std::string device_id;       // Usually serial number or UUID
    DeviceType  device_type{DeviceType::Unknown};
    std::string manufacturer;
    std::string firmware_version;

    [[nodiscard]] bool validate() const noexcept
    {
        return !device_id.empty()
            && device_type != DeviceType::Unknown;
    }
};

struct DataQualityMetrics
{
    double               signal_to_noise_ratio_db{0.0};
    double               lead_dropout_pct{0.0};
    bool                 passed{false};
    std::vector<std::string> messages;

    [[nodiscard]] bool validate() const noexcept
    {
        return signal_to_noise_ratio_db >= 0.0
            && lead_dropout_pct >= 0.0 && lead_dropout_pct <= 100.0;
    }
};

static constexpr std::size_t ECG_12_LEADS = 12;

struct ECGSample
{
    Timestamp                        timestamp;
    std::array<float, ECG_12_LEADS>  lead_mV{};   // milli-volt values per lead

    [[nodiscard]] bool validate() const noexcept
    {
        // Simple SNR-type heuristic: ensure all leads are finite
        for (auto v : lead_mV)
        {
            if (!std::isfinite(v)) return false;
        }
        return true;
    }
};

struct ECGRecord
{
    std::string                      session_id;      // Unique per acquisition
    PatientIdentity                  patient;
    DeviceInfo                       device;
    std::uint32_t                    sampling_rate_hz{0};
    std::vector<ECGSample>           samples;
    std::optional<ArrhythmiaLabel>   annotation;
    DataQualityMetrics               quality;

    [[nodiscard]] bool validate() const noexcept
    {
        return !session_id.empty()
            && sampling_rate_hz > 0
            && patient.validate()
            && device.validate()
            && quality.validate()
            && !samples.empty();
    }
};

/*-----------------------------------------------------------------------------*
 * JSON Serialisation – nlohmann
 *-----------------------------------------------------------------------------*/
using nlohmann::json;

namespace detail
{
template <typename Enum>
constexpr std::string_view enum_to_string(Enum e) noexcept
{
    switch (e)
    {
        case Sex::Male:   return "Male";
        case Sex::Female: return "Female";
        case Sex::Other:  return "Other";
        case Sex::Unknown: default: return "Unknown";
    }
}

template <>
constexpr std::string_view enum_to_string<DeviceType>(DeviceType e) noexcept
{
    switch (e)
    {
        case DeviceType::BedsideMonitor:  return "BedsideMonitor";
        case DeviceType::WearableECG:     return "WearableECG";
        case DeviceType::ImagingArchive:  return "ImagingArchive";
        case DeviceType::Unknown: default: return "Unknown";
    }
}

template <>
constexpr std::string_view enum_to_string<ArrhythmiaLabel>(ArrhythmiaLabel a) noexcept
{
    switch (a)
    {
        case ArrhythmiaLabel::NormalSinus: return "NormalSinus";
        case ArrhythmiaLabel::AFib:        return "AFib";
        case ArrhythmiaLabel::VTach:       return "VTach";
        case ArrhythmiaLabel::VFib:        return "VFib";
        case ArrhythmiaLabel::PVC:         return "PVC";
        case ArrhythmiaLabel::Paced:       return "Paced";
        case ArrhythmiaLabel::None: default: return "None";
    }
}

template <typename Enum>
Enum string_to_enum(const std::string& s);

template <>
inline Sex string_to_enum<Sex>(const std::string& s)
{
    static const std::unordered_map<std::string, Sex> map{
        {"Male", Sex::Male}, {"Female", Sex::Female},
        {"Other", Sex::Other}, {"Unknown", Sex::Unknown}};
    auto it = map.find(s);
    return it == map.end() ? Sex::Unknown : it->second;
}

template <>
inline DeviceType string_to_enum<DeviceType>(const std::string& s)
{
    static const std::unordered_map<std::string, DeviceType> map{
        {"BedsideMonitor", DeviceType::BedsideMonitor}, {"WearableECG", DeviceType::WearableECG},
        {"ImagingArchive", DeviceType::ImagingArchive}, {"Unknown", DeviceType::Unknown}};
    auto it = map.find(s);
    return it == map.end() ? DeviceType::Unknown : it->second;
}

template <>
inline ArrhythmiaLabel string_to_enum<ArrhythmiaLabel>(const std::string& s)
{
    static const std::unordered_map<std::string, ArrhythmiaLabel> map{
        {"NormalSinus", ArrhythmiaLabel::NormalSinus}, {"AFib", ArrhythmiaLabel::AFib},
        {"VTach", ArrhythmiaLabel::VTach}, {"VFib", ArrhythmiaLabel::VFib},
        {"PVC", ArrhythmiaLabel::PVC}, {"Paced", ArrhythmiaLabel::Paced},
        {"None", ArrhythmiaLabel::None}};
    auto it = map.find(s);
    return it == map.end() ? ArrhythmiaLabel::None : it->second;
}

} // namespace detail

/*--------------------------------- PatientIdentity --------------------------*/
inline void to_json(json& j, const PatientIdentity& p)
{
    j = json{{"mrn", p.medical_record_number},
             {"first_name", p.first_name},
             {"last_name",  p.last_name},
             {"dob",        p.date_of_birth},
             {"sex",        detail::enum_to_string(p.sex)}};
}

inline void from_json(const json& j, PatientIdentity& p)
{
    j.at("mrn").get_to(p.medical_record_number);
    j.at("first_name").get_to(p.first_name);
    j.at("last_name").get_to(p.last_name);
    j.at("dob").get_to(p.date_of_birth);
    p.sex = detail::string_to_enum<Sex>(j.value("sex", "Unknown"));
}

/*--------------------------------- DeviceInfo -------------------------------*/
inline void to_json(json& j, const DeviceInfo& d)
{
    j = json{{"device_id",        d.device_id},
             {"device_type",      detail::enum_to_string(d.device_type)},
             {"manufacturer",     d.manufacturer},
             {"firmware_version", d.firmware_version}};
}

inline void from_json(const json& j, DeviceInfo& d)
{
    j.at("device_id").get_to(d.device_id);
    d.device_type = detail::string_to_enum<DeviceType>(j.value("device_type", "Unknown"));
    j.at("manufacturer").get_to(d.manufacturer);
    j.at("firmware_version").get_to(d.firmware_version);
}

/*--------------------------------- DataQualityMetrics -----------------------*/
inline void to_json(json& j, const DataQualityMetrics& m)
{
    j = json{{"snr_db",            m.signal_to_noise_ratio_db},
             {"lead_dropout_pct",  m.lead_dropout_pct},
             {"passed",            m.passed},
             {"messages",          m.messages}};
}

inline void from_json(const json& j, DataQualityMetrics& m)
{
    j.at("snr_db").get_to(m.signal_to_noise_ratio_db);
    j.at("lead_dropout_pct").get_to(m.lead_dropout_pct);
    j.at("passed").get_to(m.passed);
    j.at("messages").get_to(m.messages);
}

/*--------------------------------- ECGSample --------------------------------*/
inline void to_json(json& j, const ECGSample& s)
{
    j = json{{"timestamp", to_iso8601(s.timestamp)},
             {"lead_mV",   s.lead_mV}};
}

inline void from_json(const json& j, ECGSample& s)
{
    s.timestamp = from_iso8601(j.at("timestamp").get<std::string>());
    j.at("lead_mV").get_to(s.lead_mV);
}

/*--------------------------------- ECGRecord --------------------------------*/
inline void to_json(json& j, const ECGRecord& r)
{
    j = json{
        {"session_id",     r.session_id},
        {"patient",        r.patient},
        {"device",         r.device},
        {"sampling_rate",  r.sampling_rate_hz},
        {"samples",        r.samples},
        {"annotation",     r.annotation ? detail::enum_to_string(*r.annotation) : "None"},
        {"quality",        r.quality}};
}

inline void from_json(const json& j, ECGRecord& r)
{
    j.at("session_id").get_to(r.session_id);
    j.at("patient").get_to(r.patient);
    j.at("device").get_to(r.device);
    j.at("sampling_rate").get_to(r.sampling_rate_hz);
    j.at("samples").get_to(r.samples);
    const std::string ann = j.value("annotation", "None");
    ArrhythmiaLabel label = detail::string_to_enum<ArrhythmiaLabel>(ann);
    if (label != ArrhythmiaLabel::None)
        r.annotation = label;
    j.at("quality").get_to(r.quality);
}

/*-----------------------------------------------------------------------------*
 * Misc. helpers
 *-----------------------------------------------------------------------------*/
template <typename T>
inline json to_pretty_json(const T& obj)
{
    return json(obj).dump(2);   // indent = 2
}

/*-----------------------------------------------------------------------------*
 * Hash specialisations — enable use in unordered containers
 *-----------------------------------------------------------------------------*/
} // namespace cardio_insight::domain

namespace std
{
template <>
struct hash<cardio_insight::domain::PatientIdentity>
{
    size_t operator()(const cardio_insight::domain::PatientIdentity& p) const noexcept
    {
        return std::hash<std::string>{}(p.medical_record_number);
    }
};
} // namespace std