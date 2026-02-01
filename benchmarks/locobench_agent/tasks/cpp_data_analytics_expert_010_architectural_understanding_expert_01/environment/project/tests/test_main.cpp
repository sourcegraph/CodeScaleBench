```cpp
// cardio_insight_360/tests/test_main.cpp
//
// Unit- and integration-tests for a subset of the CardioInsight360
// analytics engine.  The tests exercise a miniature—but realistic—
// in-process Event-Bus, an ETL-Pipeline skeleton, and a Strategy
// implementation for ECG signal-quality evaluation.
//
// The real codebase ships fully-fledged versions of these building
// blocks; here we provide lightweight test doubles that respect the
// production interfaces closely enough to validate external behaviour.
//
// Compile with (example):
//    g++ -std=c++17 -pthread test_main.cpp -lgtest -ltbb -o ci360_tests
// ---------------------------------------------------------------------

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <future>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <tbb/parallel_for.h>
#include <tbb/task_group.h>

// ──────────────────────────────────────────────────────────────────────
// Mock / Test-Double implementations
// ──────────────────────────────────────────────────────────────────────
namespace ci360::storage {

class IDataLake
{
public:
    virtual ~IDataLake()                                                = default;
    virtual bool                         write(const std::string& path,
                                               const std::vector<std::uint8_t>& buffer) = 0;
    virtual std::vector<std::uint8_t>    read(const std::string& path)                = 0;
};

class MockDataLake final : public IDataLake
{
public:
    bool write(const std::string& path,
               const std::vector<std::uint8_t>& buffer) override
    {
        std::scoped_lock lk(_mtx);
        _storage[path] = buffer;
        return true;
    }

    std::vector<std::uint8_t> read(const std::string& path) override
    {
        std::scoped_lock lk(_mtx);
        auto it = _storage.find(path);
        if (it == _storage.end()) { return {}; }
        return it->second;
    }

    std::size_t object_count() const
    {
        std::scoped_lock lk(_mtx);
        return _storage.size();
    }

private:
    mutable std::mutex                                            _mtx;
    std::unordered_map<std::string, std::vector<std::uint8_t>>    _storage;
};

} // namespace ci360::storage

// ──────────────────────────────────────────────────────────────────────
namespace ci360::streaming {

struct Event
{
    std::string                                   topic;
    std::vector<std::uint8_t>                     payload;
    std::chrono::steady_clock::time_point         timestamp{std::chrono::steady_clock::now()};
};

class IEventBus
{
public:
    using Handler = std::function<void(const Event&)>;
    virtual ~IEventBus()                                      = default;
    virtual void publish(const Event& e)                      = 0;
    virtual void subscribe(const std::string& topic, Handler) = 0;
};

class MockEventBus final : public IEventBus
{
public:
    void publish(const Event& e) override
    {
        std::vector<Handler> local_copy;
        {
            std::shared_lock lk(_mtx);
            auto it = _subscribers.find(e.topic);
            if (it != _subscribers.end()) { local_copy = it->second; }
        }
        // invoke outside lock
        for (auto& h : local_copy) { h(e); }
    }

    void subscribe(const std::string& topic, Handler h) override
    {
        std::unique_lock lk(_mtx);
        _subscribers[topic].push_back(std::move(h));
    }

private:
    std::shared_mutex                                                       _mtx;
    std::unordered_map<std::string, std::vector<Handler>>                   _subscribers;
};

} // namespace ci360::streaming

// ──────────────────────────────────────────────────────────────────────
// Strategy for ECG quality validation
// ──────────────────────────────────────────────────────────────────────
namespace ci360::quality {

class IECGQualityStrategy
{
public:
    virtual ~IECGQualityStrategy() = default;
    virtual bool is_quality_good(const std::vector<int>& signal) const = 0;
};

// Very simple amplitude-range validation strategy.
// Good quality = every sample within ±4 mV (assuming integer value == milli-volts)
class AmplitudeRangeStrategy final : public IECGQualityStrategy
{
public:
    explicit AmplitudeRangeStrategy(int max_mv = 4000) : _max(std::abs(max_mv)) {}

    bool is_quality_good(const std::vector<int>& signal) const override
    {
        return std::all_of(signal.begin(), signal.end(),
                           [this](int v) { return std::abs(v) <= _max; });
    }

private:
    int _max;
};

} // namespace ci360::quality

// ──────────────────────────────────────────────────────────────────────
// Miniature ETL Pipeline skeleton using the above test doubles
// ──────────────────────────────────────────────────────────────────────
namespace ci360::etl {

struct RawEcgMessage
{
    std::string         patient_id;
    std::vector<int>    samples;   // μVolts
    std::uint64_t       tick;
};

// Simple transform function: compress raw ints to bytes (µ-law style toy example)
inline std::vector<std::uint8_t> transform(const std::vector<int>& in)
{
    std::vector<std::uint8_t> out;
    out.reserve(in.size());
    for (int v : in)
    {
        int clipped = std::max(std::min(v, 8191), -8192); // toy µ-law clip
        std::uint8_t packed = static_cast<std::uint8_t>((clipped + 8192) / 64);
        out.push_back(packed);
    }
    return out;
}

class MiniEtlPipeline
{
public:
    MiniEtlPipeline(std::shared_ptr<ci360::storage::IDataLake> lake,
                    std::shared_ptr<ci360::streaming::IEventBus> bus,
                    std::shared_ptr<ci360::quality::IECGQualityStrategy> qc)
        : _lake(std::move(lake))
        , _bus(std::move(bus))
        , _quality(std::move(qc))
    { }

    // runs synchronously for the purpose of the unit-test
    bool run(const RawEcgMessage& msg)
    {
        if (!_quality->is_quality_good(msg.samples))
        {
            ci360::streaming::Event evt {
                .topic = "etl.qc_failed",
                .payload = {'B', 'A', 'D'}
            };
            _bus->publish(evt);
            return false;
        }

        const auto transformed = transform(msg.samples);
        const std::string path = "/curated/" + msg.patient_id + "/" + std::to_string(msg.tick) + ".bin";

        bool ok = _lake->write(path, transformed);
        if (ok)
        {
            ci360::streaming::Event evt {
                .topic = "etl.curated_ready",
                .payload = {'O', 'K'}
            };
            _bus->publish(evt);
        }
        return ok;
    }

private:
    std::shared_ptr<ci360::storage::IDataLake>           _lake;
    std::shared_ptr<ci360::streaming::IEventBus>         _bus;
    std::shared_ptr<ci360::quality::IECGQualityStrategy> _quality;
};

} // namespace ci360::etl

// ──────────────────────────────────────────────────────────────────────
//                             Test Cases
// ──────────────────────────────────────────────────────────────────────

// Helper to generate a clean test fixture
class PipelineFixture : public ::testing::Test
{
protected:
    void SetUp() override
    {
        lake      = std::make_shared<ci360::storage::MockDataLake>();
        bus       = std::make_shared<ci360::streaming::MockEventBus>();
        strategy  = std::make_shared<ci360::quality::AmplitudeRangeStrategy>();
        pipeline  = std::make_unique<ci360::etl::MiniEtlPipeline>(lake, bus, strategy);
    }

    std::shared_ptr<ci360::storage::MockDataLake>                    lake;
    std::shared_ptr<ci360::streaming::MockEventBus>                  bus;
    std::shared_ptr<ci360::quality::AmplitudeRangeStrategy>          strategy;
    std::unique_ptr<ci360::etl::MiniEtlPipeline>                     pipeline;
};

// -------------------------- ETL pipeline test ------------------------
TEST_F(PipelineFixture, StoresCuratedDataInDataLake)
{
    ci360::etl::RawEcgMessage msg {
        .patient_id = "P123",
        .samples    = {120, 220, -300, 400},
        .tick       = 42
    };

    const bool ok = pipeline->run(msg);
    ASSERT_TRUE(ok);
    EXPECT_EQ(lake->object_count(), 1);

    // Confirm payload round-trip
    const auto stored = lake->read("/curated/P123/42.bin");
    ASSERT_EQ(stored.size(), msg.samples.size());
}

// ---------------------- QC Failure branch test ----------------------
TEST_F(PipelineFixture, PublishesEventOnBadQuality)
{
    std::promise<void> signal;
    auto future = signal.get_future();

    bus->subscribe("etl.qc_failed",
                   [&signal](const ci360::streaming::Event&) { signal.set_value(); });

    ci360::etl::RawEcgMessage msg {
        .patient_id = "P999",
        .samples    = {5500, 0, -10000},  // out of ±4 mV range
        .tick       = 100
    };

    const bool ok = pipeline->run(msg);
    EXPECT_FALSE(ok);

    // Should have emitted qc_failed event in a timely manner
    ASSERT_EQ(future.wait_for(std::chrono::milliseconds(50)), std::future_status::ready);
}

// --------------- EventBus latency & correctness test ----------------
TEST(EventBus, PublishesAndReceivesEventsUnderThreshold)
{
    auto bus = std::make_shared<ci360::streaming::MockEventBus>();

    const std::string topic = "telemetry.latency_probe";
    std::promise<std::chrono::microseconds> prom;
    auto fut = prom.get_future();

    bus->subscribe(topic,
                   [&prom](const ci360::streaming::Event& e) {
                       auto now   = std::chrono::steady_clock::now();
                       auto delta = std::chrono::duration_cast<std::chrono::microseconds>(now - e.timestamp);
                       prom.set_value(delta);
                   });

    ci360::streaming::Event probe { topic, {}, std::chrono::steady_clock::now() };
    bus->publish(probe);

    auto latency = fut.get(); // blocking
    EXPECT_LT(latency.count(), 500); // < 500 µs is comfortably within intra-process target
}

// ------------- Parameterised test for QC strategy thresholds --------
class QualityStrategyTest
    : public ::testing::TestWithParam<std::tuple<std::vector<int>, bool>>
{ };

TEST_P(QualityStrategyTest, AmplitudeRangeValidation)
{
    const auto& [samples, expected] = GetParam();
    ci360::quality::AmplitudeRangeStrategy strat(4000);
    EXPECT_EQ(strat.is_quality_good(samples), expected);
}

INSTANTIATE_TEST_SUITE_P(
    VariousSignals,
    QualityStrategyTest,
    ::testing::Values(
        std::make_tuple(std::vector<int>{0, 100, -200}, true),
        std::make_tuple(std::vector<int>{3999, -3999, 0}, true),
        std::make_tuple(std::vector<int>{4500}, false),
        std::make_tuple(std::vector<int>{0, -8000, 10}, false)));

// ---------------- EventBus concurrency / thread-safety --------------
TEST(EventBus, IsThreadSafeUnderHighConcurrency)
{
    constexpr std::size_t publisher_threads  = 64;
    constexpr std::size_t events_per_thread  = 128;
    constexpr std::size_t expected_total     = publisher_threads * events_per_thread;

    auto bus          = std::make_shared<ci360::streaming::MockEventBus>();
    std::atomic<std::size_t> received{0};
    bus->subscribe("stress.topic",
                   [&received](const ci360::streaming::Event&) { ++received; });

    tbb::task_group tg;
    for (std::size_t t = 0; t < publisher_threads; ++t)
    {
        tg.run([bus]() {
            for (std::size_t i = 0; i < events_per_thread; ++i)
            {
                ci360::streaming::Event evt { "stress.topic", { static_cast<std::uint8_t>(i & 0xFF) } };
                bus->publish(evt);
            }
        });
    }
    tg.wait(); // Wait for all publishers
    // Allow some time for final dispatch
    std::this_thread::sleep_for(std::chrono::milliseconds(30));

    EXPECT_EQ(received.load(), expected_total);
}

// ──────────────────────────────────────────────────────────────────────
// GoogleTest entry-point
// ──────────────────────────────────────────────────────────────────────
int main(int argc, char** argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
```