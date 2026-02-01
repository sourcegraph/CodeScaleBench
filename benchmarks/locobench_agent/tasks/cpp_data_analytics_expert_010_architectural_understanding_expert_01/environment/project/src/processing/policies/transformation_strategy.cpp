/**************************************************************************************************
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  File        : cardio_insight_360/src/processing/policies/transformation_strategy.cpp
 *  License     : Proprietary – CardioInsight360 Inc. – All Rights Reserved
 *
 *  Description :
 *      Implements the TransformationStrategy base‐class registry and the built-in strategies
 *      for ECG, Blood-Pressure (IBP/NIBP) and SpO₂ signal modalities.  A TransformationStrategy
 *      converts a RawSignalFrame, received from the ingestion layer, into a CuratedSignalFrame
 *      that has been cleaned, resampled, validated and enriched with meta-data required by the
 *      downstream analytics / storage subsystems.
 *
 *      – Strategy Pattern enables dynamic selection of the proper transformation logic based on
 *        run-time modality & configuration (declared in hospital_site.json or via REST).
 *      – A lightweight registry maps modality-IDs to factory functors while guaranteeing
 *        thread-safe lazy initialization (std::call_once + std::shared_mutex).
 *      – Strategy implementations are performance-oriented (Intel TBB) yet isolated enough for
 *        per-modality CI/CD validation.  Exceptions are re-thrown as domain specific errors to
 *        ensure the error-recovery service can act accordingly.
 *
 *      NOTE:
 *          The header “transformation_strategy.hpp” exposes the abstract interface that other
 *          subsystems (ETL pipeline, Stream processor, Batch jobs) are compiled against.
 **************************************************************************************************/

#include "processing/policies/transformation_strategy.hpp"
#include "signal_processing/filters/butterworth.hpp"
#include "signal_processing/filters/moving_average.hpp"
#include "signal_processing/quality/arrhythmia_validator.hpp"
#include "signal_processing/quality/artifacts_detector.hpp"
#include "event_bus/event_publisher.hpp"
#include "common/ci360_exceptions.hpp"

#include <tbb/blocked_range.h>
#include <tbb/parallel_for.h>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <unordered_map>
#include <mutex>
#include <shared_mutex>
#include <utility>          // std::move
#include <sstream>          // error reporting


// -------------------------------------------------------------------------------------------------
// Anonymous namespace – internal helpers & built-in strategy implementations
// -------------------------------------------------------------------------------------------------
namespace {

using ci360::common::Uuid;
using ci360::domain::RawSignalFrame;
using ci360::domain::CuratedSignalFrame;
using ci360::processing::TransformationContext;
using ci360::processing::policies::TransformationStrategy;
using json = nlohmann::json;

/**************************************************************************************************
 * ECGTransformationStrategy – performs baseline wander removal,  resampling (250 Hz), 12-lead
 *                              normalization and quality checks (QRS detection, beats count).
 **************************************************************************************************/
class ECGTransformationStrategy final : public TransformationStrategy
{
public:
    explicit ECGTransformationStrategy(json config) :
        _hpCutoffHz  (config.value("high_pass_cutoff_hz", 0.5)),
        _resampleHz  (config.value("target_sample_rate_hz", 250)),
        _leadCount   (config.value("lead_count", 12u))
    {
        spdlog::debug("[ECG] Instantiated ECGTransformationStrategy – config ♥ {}", config.dump());
    }

    std::string id() const noexcept override { return "ecg"; }

    CuratedSignalFrame transform(const RawSignalFrame& raw,
                                 const TransformationContext& ctx) const override
    {
        if (raw.sample_rate_hz == 0.0) {
            CI360_THROW(ci360::common::InvalidArgument,
                        "Raw sample_rate_hz must be > 0 for ECG transformation");
        }

        //---------------------------------- 1. Baseline-Wander Removal ----------------------------
        auto filtered = ci360::signal_processing::filters::butterworth_high_pass(
            raw.samples, raw.sample_rate_hz, _hpCutoffHz, /*order*/2);

        //---------------------------------- 2. Resampling (if required) ----------------------------
        if (raw.sample_rate_hz != _resampleHz) {
            filtered = ci360::signal_processing::dsp::resample(filtered,
                                                               raw.sample_rate_hz,
                                                               _resampleHz);
        }

        //---------------------------------- 3. Quality Checks & Beat Validation -------------------
        auto validation = ci360::signal_processing::quality::run_arrhythmia_validation(filtered,
                                                                                       _resampleHz,
                                                                                       ctx.patient_meta);

        //---------------------------------- 4. Assemble Curated SignalFrame -----------------------
        CuratedSignalFrame curated;
        curated.uuid               = Uuid::random();
        curated.modality           = "ECG";
        curated.sample_rate_hz     = _resampleHz;
        curated.samples            = std::move(filtered);
        curated.quality_report     = std::move(validation.report);
        curated.ingestion_timestamp= raw.ingestion_timestamp;
        curated.processing_host    = ctx.host_name;
        curated.processing_epoch_ms= ci360::common::now_epoch_ms();

        return curated;
    }

private:
    double   _hpCutoffHz;
    double   _resampleHz;
    uint32_t _leadCount;
};

/**************************************************************************************************
 * BPTransformationStrategy – calibrates invasive / non-invasive BP wave-forms,  detects dicrotic
 *                            notch and extracts systolic/diastolic values per beat.
 **************************************************************************************************/
class BPTransformationStrategy final : public TransformationStrategy
{
public:
    explicit BPTransformationStrategy(json config)
        : _movingAvgWindow(config.value("moving_average_window", 8U))
    {
        spdlog::debug("[BP] Instantiated BPTransformationStrategy – config ♥ {}", config.dump());
    }

    std::string id() const noexcept override { return "bp"; }

    CuratedSignalFrame transform(const RawSignalFrame& raw,
                                 const TransformationContext& ctx) const override
    {
        //---------------------------------- 1. Smoothing ------------------------------------------
        auto smoothed = ci360::signal_processing::filters::moving_average(
            raw.samples, _movingAvgWindow);

        //---------------------------------- 2. Quality: artifact detection ------------------------
        auto artifactReport = ci360::signal_processing::quality::detect_waveform_artifacts(
            smoothed, raw.sample_rate_hz, /*artifact_threshold*/0.08);

        //---------------------------------- 3. Metrics extraction ---------------------------------
        auto metrics = ci360::signal_processing::quality::extract_bp_metrics(smoothed,
                                                                             raw.sample_rate_hz);

        //---------------------------------- 4. Build Curated frame --------------------------------
        CuratedSignalFrame curated;
        curated.uuid               = Uuid::random();
        curated.modality           = "BP";
        curated.sample_rate_hz     = raw.sample_rate_hz;
        curated.samples            = std::move(smoothed);
        curated.quality_report     = std::move(artifactReport);
        curated.derived_metrics    = std::move(metrics);
        curated.ingestion_timestamp= raw.ingestion_timestamp;
        curated.processing_host    = ctx.host_name;
        curated.processing_epoch_ms= ci360::common::now_epoch_ms();

        return curated;
    }

private:
    std::size_t _movingAvgWindow;
};

/**************************************************************************************************
 * SpO2TransformationStrategy – cleans up plethysmography waveform and computes oxygen saturation
 *                              and pulse-rate variability.
 **************************************************************************************************/
class SpO2TransformationStrategy final : public TransformationStrategy
{
public:
    explicit SpO2TransformationStrategy(json config)
        : _movingAvgWindow(config.value("moving_average_window", 5U))
    {
        spdlog::debug("[SpO2] Instantiated SpO2TransformationStrategy – config ♥ {}", config.dump());
    }

    std::string id() const noexcept override { return "spo2"; }

    CuratedSignalFrame transform(const RawSignalFrame& raw,
                                 const TransformationContext& ctx) const override
    {
        //---------------------------------- 1. Denoise --------------------------------------------
        std::vector<double> denoised = ci360::signal_processing::filters::moving_average(
            raw.samples, _movingAvgWindow);

        //---------------------------------- 2. Saturation & PRV -----------------------------------
        auto derivedMetrics =
            ci360::signal_processing::quality::extract_spo2_metrics(denoised, raw.sample_rate_hz);

        //---------------------------------- 3. Quality Check --------------------------------------
        auto quality = ci360::signal_processing::quality::detect_waveform_artifacts(
            denoised, raw.sample_rate_hz, 0.12);

        //---------------------------------- 4. Assemble curated frame -----------------------------
        CuratedSignalFrame curated;
        curated.uuid               = Uuid::random();
        curated.modality           = "SpO₂";
        curated.sample_rate_hz     = raw.sample_rate_hz;
        curated.samples            = std::move(denoised);
        curated.quality_report     = std::move(quality);
        curated.derived_metrics    = std::move(derivedMetrics);
        curated.ingestion_timestamp= raw.ingestion_timestamp;
        curated.processing_host    = ctx.host_name;
        curated.processing_epoch_ms= ci360::common::now_epoch_ms();

        return curated;
    }

private:
    std::size_t _movingAvgWindow;
};

} // <anonymous namespace>


// -------------------------------------------------------------------------------------------------
//  Registry Implementation – TransformationStrategy (ci360::processing::policies)
// -------------------------------------------------------------------------------------------------
namespace ci360::processing::policies {

namespace {

/* Registry data structure ─ key = modality (lower-case)  value = factory functor */
using StrategyFactory = std::function<std::unique_ptr<TransformationStrategy>(const json&)>;
using RegistryMap     = std::unordered_map<std::string, StrategyFactory>;

RegistryMap& registry_instance()
{
    static RegistryMap map;
    return map;
}

/* Thread-safety primitives */
std::once_flag               _registration_once_flag;
mutable std::shared_mutex    _registry_mutex;

/* Helper – registers all built-in strategies exactly once */
void register_builtin_strategies()
{
    auto& registry = registry_instance();

    registry.emplace("ecg",  [](const json& cfg)
                     { return std::make_unique<ECGTransformationStrategy>(cfg); });
    registry.emplace("bp",   [](const json& cfg)
                     { return std::make_unique<BPTransformationStrategy>(cfg); });
    registry.emplace("spo2", [](const json& cfg)
                     { return std::make_unique<SpO2TransformationStrategy>(cfg); });

    spdlog::info("TransformationStrategy registry initialized – {} built-in strategies",
                 registry.size());
}

} // namespace (inner)

/**************************************************************************************************
 * TransformationStrategy::make
 *
 *      Factory entry point that returns an owning pointer to the requested strategy.  This is
 *      the only publicly visible method from the registry – all internal plumbing is hidden.
 *
 *  @param modality     Case-insensitive modality identifier (e.g. “ECG”, “bp”, “SpO₂”)
 *  @param cfg          Site / pipeline specific configuration parameters.
 *
 *  @throws UnsupportedModalityError if no strategy has been registered for the given modality.
 **************************************************************************************************/
std::unique_ptr<TransformationStrategy>
TransformationStrategy::make(std::string modality, const json& cfg)
{
    // Normalize modality to lower case
    std::transform(modality.begin(), modality.end(),
                   modality.begin(), [](unsigned char c){ return std::tolower(c); });

    /* Lazy initialization of built-in strategies */
    std::call_once(_registration_once_flag, register_builtin_strategies);

    std::shared_lock guard(_registry_mutex);
    const auto& registry = registry_instance();
    auto it = registry.find(modality);

    if (it == registry.end()) {
        std::stringstream ss;
        ss << "Unsupported or unregistered modality: [" << modality << "]";
        spdlog::error(ss.str());
        CI360_THROW(ci360::common::UnsupportedModalityError, ss.str());
    }

    try {
        return (it->second)(cfg);      // Invoke factory functor
    }
    catch (const std::exception& ex) {
        spdlog::error("Failed to instantiate TransformationStrategy for modality '{}' – {}",
                      modality, ex.what());
        throw;  // propagate
    }
}

/**************************************************************************************************
 * TransformationStrategy::register_custom
 *
 *      API for plugin authors to register their own strategy implementation at run-time.
 *
 *  @param modality      Unique, lower-case modality identifier.
 *  @param factory       Functor that returns a std::unique_ptr<TransformationStrategy>.
 *
 *  @returns true if registration succeeded, false if the modality ID is already in use.
 **************************************************************************************************/
bool TransformationStrategy::register_custom(std::string modality,
                                             StrategyFactory factory)
{
    std::transform(modality.begin(), modality.end(),
                   modality.begin(), [](unsigned char c){ return std::tolower(c); });

    std::unique_lock guard(_registry_mutex);
    auto& registry = registry_instance();

    auto [it, inserted] = registry.emplace(std::move(modality), std::move(factory));
    if (!inserted) {
        spdlog::warn("Cannot register custom TransformationStrategy – modality '{}' already exists",
                     it->first);
    } else {
        spdlog::info("Custom TransformationStrategy for modality '{}' registered", it->first);
    }
    return inserted;
}

} // namespace ci360::processing::policies