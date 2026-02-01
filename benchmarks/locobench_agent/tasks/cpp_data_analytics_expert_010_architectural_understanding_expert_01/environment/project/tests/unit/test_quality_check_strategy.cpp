```cpp
/**
 *  cardio_insight_360/tests/unit/test_quality_check_strategy.cpp
 *
 *  Copyright 2024 Midnight Illusions
 *
 *  Unit-tests for the pluggable Quality-Check strategies used throughout the
 *  CardioInsight360 analytics engine.  The tests exercise contractual behaviour
 *  rather than internal implementation details; i.e. they validate that each
 *  concrete strategy
 *
 *    • correctly classifies good/bad signal segments
 *    • is thread-safe and re-entrant
 *    • is discoverable through the central factory/registry
 *
 *  Build-system requirements
 *  -------------------------
 *  ‑ GoogleTest (gtest_main, gtest)
 *  ‑ C++17 or later
 *
 *  Example (CMake):
 *      add_executable(test_quality_check_strategy
 *          tests/unit/test_quality_check_strategy.cpp)
 *      target_link_libraries(test_quality_check_strategy
 *          PRIVATE
 *              gtest_main
 *              cardio_analytics)   # <-- production lib that defines strategies
 */

#include <gtest/gtest.h>

#include <future>
#include <random>
#include <thread>
#include <vector>

// Production headers ---------------------------------------------------------
#include <quality/quality_check_factory.hpp>   // Singleton factory
#include <quality/quality_check_strategy.hpp>  // Interface + enums
#include <quality/signal_segment.hpp>          // Domain model
// -----------------------------------------------------------------------------

using quality::IQualityCheckStrategy;
using quality::QualityCheckFactory;
using quality::QualityIssue;
using quality::SignalSegment;

// -----------------------------------------------------------------------------
// Helper utilities used by multiple test-cases
// -----------------------------------------------------------------------------

namespace {

SignalSegment
generateSyntheticECG(std::size_t sampleCount = 1'000,
                     double noiseAmplitude      = 0.0,
                     bool   flatLine            = false)
{
    SignalSegment seg;
    seg.sampling_rate_hz = 250.0;
    seg.channel          = "Lead-II";
    seg.timestamp_epoch_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count();

    seg.samples.reserve(sampleCount);

    // Simple synthetic waveform: sine with optional noise/baseline wander
    std::default_random_engine rng{std::random_device{}()};
    std::normal_distribution<double> noise(0.0, noiseAmplitude);

    for (std::size_t i = 0; i < sampleCount; ++i) {
        const double t = static_cast<double>(i) / seg.sampling_rate_hz;
        const double sample =
            flatLine ? 0.0 : std::sin(2.0 * M_PI * 1.0 * t) + noise(rng);
        seg.samples.push_back(sample);
    }

    return seg;
}

SignalSegment
generateSyntheticBP(const std::vector<double>& mmHg)
{
    SignalSegment seg;
    seg.sampling_rate_hz   = 125.0;
    seg.channel            = "IBP";
    seg.timestamp_epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                 std::chrono::system_clock::now().time_since_epoch())
                                 .count();
    seg.samples            = mmHg;
    return seg;
}

SignalSegment
generateSyntheticSpO2(std::size_t sampleCount = 50, double value = 98.7)
{
    SignalSegment seg;
    seg.sampling_rate_hz   = 1.0;
    seg.channel            = "SpO2";
    seg.timestamp_epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                 std::chrono::system_clock::now().time_since_epoch())
                                 .count();
    seg.samples.assign(sampleCount, value);
    return seg;
}

// Convenience predicate for issue search
bool hasIssue(const std::vector<QualityIssue>& issues, QualityIssue::Code code)
{
    return std::any_of(issues.begin(), issues.end(),
                       [code](const QualityIssue& i) { return i.code == code; });
}

} // namespace

// -----------------------------------------------------------------------------
// Test-suite 1: Basic functional expectations
// -----------------------------------------------------------------------------

TEST(QualityCheckStrategy, ECG_Flatline_IsRejected)
{
    auto strategy =
        QualityCheckFactory::instance().create("ECG"); // Polymorphic pointer
    ASSERT_NE(strategy, nullptr);

    const SignalSegment flatLine = generateSyntheticECG(1'000, 0.0, true);
    const auto          issues   = strategy->assess(flatLine);

    EXPECT_FALSE(issues.empty()) << "Flat-line ECG must trigger at least one "
                                    "quality issue";

    EXPECT_TRUE(hasIssue(issues, QualityIssue::Code::LOW_AMPLITUDE))
        << "Flat-line ECG expected to register LOW_AMPLITUDE issue";
}

TEST(QualityCheckStrategy, BP_PhysiologicallyImpossibleValues_AreRejected)
{
    auto strategy =
        QualityCheckFactory::instance().create("BP"); // Blood-pressure policy
    ASSERT_NE(strategy, nullptr);

    const SignalSegment bpSeg =
        generateSyntheticBP({120, 118, -15, 117, 119}); // −15 mmHg impossible
    const auto issues = strategy->assess(bpSeg);

    EXPECT_FALSE(issues.empty()) << "Negative BP must be rejected";
    EXPECT_TRUE(hasIssue(issues, QualityIssue::Code::OUT_OF_RANGE));
}

TEST(QualityCheckStrategy, SpO2_HighQualitySegment_Passes)
{
    auto strategy =
        QualityCheckFactory::instance().create("SpO2"); // Pulse-oximeter policy
    ASSERT_NE(strategy, nullptr);

    const SignalSegment spo2Seg = generateSyntheticSpO2(60, 99.1);
    const auto          issues  = strategy->assess(spo2Seg);

    EXPECT_TRUE(issues.empty()) << "Well-behaved SpO₂ segment should pass "
                                   "quality gate without any findings";
}

// -----------------------------------------------------------------------------
// Test-suite 2: Factory / Registry behaviour
// -----------------------------------------------------------------------------

TEST(QualityCheckStrategyFactory, ReturnsAllRegisteredStrategies)
{
    const auto available = QualityCheckFactory::instance().listRegistered();

    // These three are considered critical-path for CardioInsight360
    EXPECT_NE(std::find(available.begin(), available.end(), "ECG"),
              available.end());
    EXPECT_NE(std::find(available.begin(), available.end(), "BP"),
              available.end());
    EXPECT_NE(std::find(available.begin(), available.end(), "SpO2"),
              available.end());
}

// -----------------------------------------------------------------------------
// Test-suite 3: Concurrency ‑ Strategy instance must be thread-safe
// -----------------------------------------------------------------------------

TEST(QualityCheckStrategy, ThreadSafety_MultipleConcurrentAssessments)
{
    const auto strategy = QualityCheckFactory::instance().create("ECG");
    ASSERT_NE(strategy, nullptr);

    const auto workload = [&](int idx) -> bool {
        // Introduce slight variation per thread to avoid cache-hits
        const double noise = 0.05 * (idx + 1);
        const SignalSegment seg = generateSyntheticECG(4'000, noise);
        const auto           v  = strategy->assess(seg);

        // A moderately noisy ECG should still be deemed usable by the strategy
        // (implementation-dependent; here we accept up to WARN level issues)
        return !hasIssue(v, QualityIssue::Code::REJECT_SEGMENT);
    };

    // Fan-out 8 concurrent tasks
    std::vector<std::future<bool>> fut;
    for (int i = 0; i < 8; ++i) {
        fut.emplace_back(std::async(std::launch::async, workload, i));
    }

    // Verify that every invocation produced a consistent & acceptable result
    for (auto& f : fut) {
        EXPECT_TRUE(f.get());
    }
}

// -----------------------------------------------------------------------------
// main() is provided by gtest_main
// -----------------------------------------------------------------------------
```