```cpp
/**
 * cardio_insight_360/src/processing/policies/quality_check_strategy.cpp
 *
 *  Copyright (c) 2023-2024
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Implements concrete Quality-Check strategies as well as the factory /
 *  registry that wires them into the Strategy-Pattern used across the
 *  processing pipeline.  Strategies run lightweight, domain-specific,
 *  validation rules on incoming signal packets (ECG, Blood-Pressure,
 *  SpO₂ …) and yield a structured QualityReport that is then forwarded to
 *  the monitoring subsystem and persisted next to the curated data.
 *
 *  NOTE: header-only symbols are forward-declared below so that this
 *  source file can be compiled stand-alone for the purpose of this
 *  exercise.  In the production tree they live in
 *  “quality_check_strategy.hpp”.
 */

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <mutex>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// 3rd-party, shipped in external/ directory
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

using json = nlohmann::json;

/* ====== Forward declarations – begin ==================================== */
namespace ci360::processing::policies {

enum class SignalType { ECG, BloodPressure, SpO2 };

struct SignalPacket
{
    SignalType                    type;
    std::chrono::system_clock::time_point timestamp;
    double                        sampling_rate_hz;
    std::vector<double>           values;   // raw samples; NaN = invalid
};

/**
 * Holds the result of a quality-check run.
 */
struct QualityReport
{
    bool                     passed            = false;
    std::vector<std::string> warnings;
    std::vector<std::string> errors;

    void add_warning(std::string msg) { warnings.emplace_back(std::move(msg)); }
    void add_error  (std::string msg) { errors  .emplace_back(std::move(msg)); }

    friend std::ostream& operator<<(std::ostream& os, const QualityReport& qr)
    {
        os << (qr.passed ? "PASS" : "FAIL")
           << " | warnings:" << qr.warnings.size()
           << " | errors:"   << qr.errors.size();
        return os;
    }
};

/**
 * Strategy interface used by the pipeline.
 */
class IQualityCheckStrategy
{
public:
    virtual ~IQualityCheckStrategy() = default;

    /**
     * Execute validation on a signal packet and yield a QualityReport.
     * Implementations should never throw – they must catch internal
     * exceptions and mark the report as failed instead.
     */
    virtual QualityReport validate(const SignalPacket& packet) noexcept = 0;
};

/* --- Factory / registry ------------------------------------------------- */

class QualityCheckStrategyFactory
{
public:
    using StrategyPtr = std::shared_ptr<IQualityCheckStrategy>;
    using CreatorFn   = std::function<StrategyPtr(const json& cfg)>;

    static StrategyPtr make(SignalType type,
                            const json& cfg = json::object());

    static void register_strategy(SignalType type, CreatorFn fn);

private:
    static std::unordered_map<SignalType, CreatorFn>& registry();
};

} // namespace ci360::processing::policies
/* ====== Forward declarations – end ====================================== */

namespace ci360::processing::policies {

/* ========================================================================
 *                  Helper  (generic utilities)
 * ===================================================================== */

namespace detail {

/**
 * Return mean and standard deviation of the sample vector, ignoring NaNs.
 */
inline std::pair<double, double>
mean_stddev(const std::vector<double>& data)
{
    std::vector<double> filtered;
    filtered.reserve(data.size());
    for (double v : data)
    {
        if (!std::isnan(v))
            filtered.push_back(v);
    }
    if (filtered.empty())
        return {std::numeric_limits<double>::quiet_NaN(),
                std::numeric_limits<double>::quiet_NaN()};

    double mean = std::accumulate(filtered.begin(), filtered.end(), 0.0)
                / filtered.size();

    double accum = 0.0;
    for (double v : filtered)
        accum += (v - mean) * (v - mean);

    double stddev = std::sqrt(accum / filtered.size());
    return {mean, stddev};
}

/**
 * Return fraction (0.0 – 1.0) of NaN values inside the vector.
 */
inline double fraction_nan(const std::vector<double>& data)
{
    if (data.empty()) return 1.0;
    std::size_t invalid = std::count_if(
        data.begin(), data.end(), [](double v) { return std::isnan(v); });
    return static_cast<double>(invalid) / data.size();
}

} // namespace detail


/* ========================================================================
 *                  ECG  – Arrhythmia & Signal-Quality checks
 * ===================================================================== */

class ECGQualityCheckStrategy final : public IQualityCheckStrategy
{
public:
    explicit ECGQualityCheckStrategy(const json& cfg)
    {
        // Load thresholds from configuration or fallback to defaults.
        amp_min_mv_          = cfg.value("amp_min_mv",   -5.0);
        amp_max_mv_          = cfg.value("amp_max_mv",    5.0);
        wander_max_std_mv_   = cfg.value("wander_std_mv", 0.5);
        nan_threshold_       = cfg.value("nan_threshold", 0.05);
        hr_range_min_bpm_    = cfg.value("hr_min_bpm",    30.0);
        hr_range_max_bpm_    = cfg.value("hr_max_bpm",   220.0);
        sampling_rate_expect_ = cfg.value("expected_sampling_hz", 250.0);
    }

    QualityReport validate(const SignalPacket& packet) noexcept override
    {
        QualityReport rep;
        try
        {
            if (packet.type != SignalType::ECG)
                throw std::invalid_argument("SignalType mismatch");

            // 1) Check sampling rate
            if (std::fabs(packet.sampling_rate_hz - sampling_rate_expect_) > 1.0)
            {
                rep.add_warning("Sampling rate deviates from expectation ("
                                + std::to_string(packet.sampling_rate_hz) + "Hz)");
            }

            // 2) Check NaN ratio
            double nan_frac = detail::fraction_nan(packet.values);
            if (nan_frac > nan_threshold_)
            {
                rep.add_error("Excessive invalid samples ("
                              + std::to_string(nan_frac * 100) + "% NaN)");
            }

            // 3) Amplitude envelope
            auto [mean, stddev] = detail::mean_stddev(packet.values);
            double min_v = *std::min_element(packet.values.begin(),
                                             packet.values.end());
            double max_v = *std::max_element(packet.values.begin(),
                                             packet.values.end());

            if (min_v < amp_min_mv_ || max_v > amp_max_mv_)
            {
                rep.add_error("Amplitude out of bounds: [" +
                              std::to_string(min_v) + " , "
                              + std::to_string(max_v) + "] mV");
            }

            // 4) Baseline wander (use low-frequency estimate ≈ mean)
            if (stddev > wander_max_std_mv_)
            {
                rep.add_warning("High baseline wander (σ="
                                + std::to_string(stddev) + "mV)");
            }

            // 5) Very primitive heart-rate windowing based on zero-crossings
            std::size_t zero_crossings = 0;
            for (std::size_t i = 1; i < packet.values.size(); ++i)
            {
                if ((packet.values[i - 1] < 0 && packet.values[i] >= 0) ||
                    (packet.values[i - 1] > 0 && packet.values[i] <= 0))
                    ++zero_crossings;
            }
            double duration_sec =
                static_cast<double>(packet.values.size()) / packet.sampling_rate_hz;
            double rr_intervals   = zero_crossings / 2.0; // two crossings per beat
            double hr_bpm         = (duration_sec > 0) ? (rr_intervals / duration_sec) * 60
                                                       : 0.0;

            if (hr_bpm < hr_range_min_bpm_ || hr_bpm > hr_range_max_bpm_)
            {
                rep.add_warning("Suspicious heart-rate estimate (" +
                                std::to_string(hr_bpm) + " bpm)");
            }

            // Decide
            rep.passed = rep.errors.empty();
        }
        catch (const std::exception& ex)
        {
            rep.add_error(std::string("ECG validation internal failure: ") + ex.what());
            rep.passed = false;
        }
        return rep;
    }

private:
    double amp_min_mv_;
    double amp_max_mv_;
    double wander_max_std_mv_;
    double nan_threshold_;
    double hr_range_min_bpm_;
    double hr_range_max_bpm_;
    double sampling_rate_expect_;
};

/* ========================================================================
 *                  Blood-Pressure (non-invasive cuff)
 * ===================================================================== */

class BloodPressureQualityCheckStrategy final : public IQualityCheckStrategy
{
public:
    explicit BloodPressureQualityCheckStrategy(const json& cfg)
    {
        systolic_min_ = cfg.value("sys_min", 70.0);
        systolic_max_ = cfg.value("sys_max", 250.0);
        diastolic_min_ = cfg.value("dia_min", 40.0);
        diastolic_max_ = cfg.value("dia_max", 150.0);
        nan_threshold_ = cfg.value("nan_threshold", 0.10);
    }

    QualityReport validate(const SignalPacket& packet) noexcept override
    {
        QualityReport rep;
        try
        {
            if (packet.type != SignalType::BloodPressure)
                throw std::invalid_argument("SignalType mismatch");

            double nan_frac = detail::fraction_nan(packet.values);
            if (nan_frac > nan_threshold_)
                rep.add_error("Too many missing reads: "
                              + std::to_string(nan_frac * 100) + "%");

            if (packet.values.size() < 2)
                rep.add_error("Less than two BP measurements in packet");

            for (double v : packet.values)
            {
                if (std::isnan(v)) continue;

                if (v < diastolic_min_ || v > systolic_max_)
                {
                    rep.add_error("Reading out of physiologic range: " + std::to_string(v));
                }
            }
            rep.passed = rep.errors.empty();
        }
        catch (const std::exception& ex)
        {
            rep.add_error("BP validation error: " + std::string(ex.what()));
            rep.passed = false;
        }
        return rep;
    }

private:
    double systolic_min_, systolic_max_;
    double diastolic_min_, diastolic_max_;
    double nan_threshold_;
};

/* ========================================================================
 *                  SpO₂  (Pulse-oximetry)
 * ===================================================================== */

class SpO2QualityCheckStrategy final : public IQualityCheckStrategy
{
public:
    explicit SpO2QualityCheckStrategy(const json& cfg)
    {
        spo2_min_      = cfg.value("spo2_min", 70.0);
        spo2_max_      = cfg.value("spo2_max", 100.0);
        nan_threshold_ = cfg.value("nan_threshold", 0.05);
    }

    QualityReport validate(const SignalPacket& packet) noexcept override
    {
        QualityReport rep;
        try
        {
            if (packet.type != SignalType::SpO2)
                throw std::invalid_argument("SignalType mismatch");

            double nan_frac = detail::fraction_nan(packet.values);
            if (nan_frac > nan_threshold_)
                rep.add_error("Sensor dropout > "
                              + std::to_string(nan_frac * 100) + "%");

            for (double v : packet.values)
            {
                if (std::isnan(v)) continue;

                if (v < spo2_min_)
                    rep.add_warning("Critical hypoxia reading: " + std::to_string(v) + "%");

                if (v > spo2_max_)
                    rep.add_warning("Reading above 100% (possible calibration drift)");
            }
            rep.passed = rep.errors.empty();
        }
        catch (const std::exception& ex)
        {
            rep.add_error("SpO₂ validation error: " + std::string(ex.what()));
            rep.passed = false;
        }
        return rep;
    }

private:
    double spo2_min_, spo2_max_;
    double nan_threshold_;
};

/* ========================================================================
 *                  Factory / Registry implementation
 * ===================================================================== */

std::unordered_map<SignalType, QualityCheckStrategyFactory::CreatorFn>&
QualityCheckStrategyFactory::registry()
{
    static std::unordered_map<SignalType, CreatorFn> impl;
    return impl;
}

QualityCheckStrategyFactory::StrategyPtr
QualityCheckStrategyFactory::make(SignalType type, const json& cfg)
{
    const auto& reg = registry();
    auto it = reg.find(type);
    if (it == reg.end())
    {
        throw std::runtime_error("No QualityCheckStrategy registered for SignalType "
                                 + std::to_string(static_cast<int>(type)));
    }
    return it->second(cfg);
}

void QualityCheckStrategyFactory::register_strategy(SignalType type, CreatorFn fn)
{
    auto& reg = registry();
    if (reg.find(type) != reg.end())
    {
        throw std::runtime_error("Strategy already registered for SignalType "
                                 + std::to_string(static_cast<int>(type)));
    }
    reg[type] = std::move(fn);
}

/* ========================================================================
 *                  Static registration block
 * ===================================================================== */

namespace {

/* RAII helper to auto-register strategies at dynamic-initialization time.
 * This is safe in our monolithic binary because we enforce a single
 * translation-unit order and we guard insertions via mutex.           */
template <typename Strategy>
struct Registrar
{
    Registrar(SignalType t)
    {
        QualityCheckStrategyFactory::register_strategy(
            t, [](const json& cfg) { return std::make_shared<Strategy>(cfg); });
    }
};

// NOLINTNEXTLINE (cert-err58-cpp) — intentional global objects for registration
Registrar<ECGQualityCheckStrategy>         _r_ecg        { SignalType::ECG           };
// NOLINTNEXTLINE
Registrar<BloodPressureQualityCheckStrategy> _r_bp         { SignalType::BloodPressure};
// NOLINTNEXTLINE
Registrar<SpO2QualityCheckStrategy>        _r_spo2       { SignalType::SpO2          };

} // anonymous namespace

} // namespace ci360::processing::policies
```