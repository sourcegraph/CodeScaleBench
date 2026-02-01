```cpp
#ifndef CARDIO_INSIGHT_360_SRC_PROCESSING_POLICIES_QUALITY_CHECK_STRATEGY_H
#define CARDIO_INSIGHT_360_SRC_PROCESSING_POLICIES_QUALITY_CHECK_STRATEGY_H

/*
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  quality_check_strategy.h
 *
 *  Abstract interfaces and utilities for run-time–pluggable signal-quality
 *  validation strategies (e.g., ECG, arterial BP, SpO₂).  Concrete
 *  implementations live in
 *      cardio_insight_360/src/processing/policies/{ecg,bp,spo2}/
 *
 *  © CardioInsight360 Consortium – All rights reserved.
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

namespace ci360::model
{
    class SignalPacket;     // Forward declaration (defined in core data-model).
}

namespace ci360::processing::policies
{
//--------------------------------------------------------------------------
// Domain-level diagnostics
//--------------------------------------------------------------------------

/**
 * Enumeration of well-known quality issues a validation strategy can
 * discover.  Values are intentionally compact so they can be stored inside
 * telemetry messages without inflating payload size.
 */
enum class QualityIssue : std::uint8_t
{
    None            = 0,
    MissingSamples  = 1,
    OutOfRange      = 2,
    NoiseDetected   = 3,
    LeadOffDetected = 4,
    TimestampDrift  = 5,
    UnsupportedLead = 6,
    Unknown         = 255
};

/**
 * Fine-grained description for a single quality issue.
 */
struct QualityDetail
{
    QualityIssue                     issue       = QualityIssue::None;
    std::string                      message;        // Human-readable
    std::optional<std::uint32_t>     sampleIndex;    // Sample that triggered the issue (if any)
};

/**
 * Aggregated report returned by every QualityCheckStrategy.
 */
struct QualityReport
{
    bool                                              pass        = true; // Overall status
    std::vector<QualityDetail>                        details;            // Per-issue breakdown
    std::chrono::system_clock::time_point             analyzedAt  =
        std::chrono::system_clock::now();                              // Audit stamp

    void addIssue(QualityIssue issue,
                  std::string_view msg,
                  std::optional<std::uint32_t> idx = std::nullopt)
    {
        pass = false;
        details.emplace_back(QualityDetail{issue, std::string{msg}, idx});
    }
};

//--------------------------------------------------------------------------
// Strategy interface
//--------------------------------------------------------------------------

/**
 * Pure virtual interface for all signal-quality validation algorithms.
 *
 * Implementations MUST be:
 *   • stateless (or internally synchronized) because instances are shared
 *     across the multi-threaded ETL pipeline.
 *   • trivially constructible so that static registration macros work.
 */
class QualityCheckStrategy
{
public:
    virtual ~QualityCheckStrategy() = default;

    // Non-copyable
    QualityCheckStrategy(const QualityCheckStrategy&)            = delete;
    QualityCheckStrategy& operator=(const QualityCheckStrategy&) = delete;

    // Movable
    QualityCheckStrategy(QualityCheckStrategy&&)                 = default;
    QualityCheckStrategy& operator=(QualityCheckStrategy&&)      = default;

    /**
     * Execute validation logic.
     *
     * @param packet  immutable reference to a raw or partially-processed
     *                signal container.
     * @return        populated QualityReport.  Implementations MUST NOT throw;
     *                they should instead record issues in the report.
     */
    [[nodiscard]]
    virtual QualityReport validate(const ci360::model::SignalPacket& packet) const noexcept = 0;

    /**
     * Human-readable identifier used for configuration & logging.
     * Example: “ecg_rpeak_consistency_v1”
     */
    [[nodiscard]]
    virtual std::string_view name() const noexcept = 0;
};

//--------------------------------------------------------------------------
// Factory & static registration helpers
//--------------------------------------------------------------------------

/**
 * Run-time factory that creates QualityCheckStrategy instances by name.
 * Automatically populated via the CI360_REGISTER_QUALITY_STRATEGY macro.
 */
class QualityCheckStrategyFactory final
{
public:
    using CreatorFn = std::unique_ptr<QualityCheckStrategy>(*)();

    /**
     * Insert a creator into the registry.  Intended to be called from
     * static initializers only (see macro below).
     *
     * @return true  if the strategy was inserted successfully,
     *         false if the name already existed and the new registration
     *               was ignored (an INFO log is emitted by the caller).
     */
    static bool registerStrategy(std::string_view strategyName, CreatorFn creator)
    {
        auto& map = registry();
        const auto [it, inserted] =
            map.emplace(std::string{strategyName}, std::move(creator));
        return inserted;
    }

    /**
     * Create a strategy instance by its canonical name.
     *
     * @throws std::invalid_argument if the requested name does not exist.
     */
    [[nodiscard]]
    static std::unique_ptr<QualityCheckStrategy> create(std::string_view strategyName)
    {
        const auto& map = registry();
        const auto it   = map.find(std::string{strategyName});
        if (it == map.end())
        {
            throw std::invalid_argument{"QualityCheckStrategyFactory: unknown strategy '" +
                                        std::string{strategyName} + "'"};
        }
        return (it->second)(); // Invoke creator fn
    }

private:
    using Registry = std::unordered_map<std::string, CreatorFn>;

    static Registry& registry()
    {
        // Meyers‐singleton – guaranteed thread-safe since C++11
        static Registry instance;
        return instance;
    }
};

/**
 * Macro that registers a concrete QualityCheckStrategy with the global
 * factory at static initialization time.
 *
 * Usage:
 *      class MyStrategy final : public QualityCheckStrategy { … };
 *      CI360_REGISTER_QUALITY_STRATEGY(MyStrategy)
 */
#define CI360_REGISTER_QUALITY_STRATEGY(STRATEGY_CLASS)                                \
    namespace                                                                          \
    {                                                                                  \
        /* NOLINTNEXTLINE(bugprone-reserved-identifier) – internal linkage */          \
        const bool _ci360_quality_reg_##STRATEGY_CLASS =                               \
            ::ci360::processing::policies::QualityCheckStrategyFactory::registerStrategy( \
                STRATEGY_CLASS{}.name(),                                               \
                []() -> std::unique_ptr<::ci360::processing::policies::QualityCheckStrategy> \
                {                                                                      \
                    return std::make_unique<STRATEGY_CLASS>();                         \
                });                                                                    \
    }                                                                                  \
    static_assert(true, "force semicolon")

} // namespace ci360::processing::policies

#endif // CARDIO_INSIGHT_360_SRC_PROCESSING_POLICIES_QUALITY_CHECK_STRATEGY_H
```