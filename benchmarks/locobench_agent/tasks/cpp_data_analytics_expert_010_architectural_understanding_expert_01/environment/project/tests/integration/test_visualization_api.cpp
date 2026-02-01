```cpp
/**
 *  File: cardio_insight_360/tests/integration/test_visualization_api.cpp
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Purpose:
 *      Integration-level tests that exercise the Visualization pseudo-microservice
 *      in conjunction with the in-process Event-Streaming bus.  The tests verify
 *      that clinical data arriving on the bus is picked up by the
 *      VisualizationService, transformed into renderable snapshots, and exposed
 *      through its public API in a thread-safe and latency-bounded manner.
 *
 *  Note:
 *      The production code base provides concrete implementations for the message
 *      bus and the visualization service.  For the purpose of these integration
 *      tests, we include lightweight in-memory substitutes that preserve the
 *      public contracts while avoiding external dependencies such as librdkafka
 *      and the REST gateway.  The tests therefore remain fully self-contained
 *      and deterministic.
 */

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <future>
#include <mutex>
#include <random>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

using namespace std::chrono_literals;

/* ============================================================
 *  Domain model (trimmed for test purposes)
 * ============================================================*/

enum class SignalType
{
    ECG,
    SPO2,
    BLOOD_PRESSURE
};

struct ECGSample
{
    std::string patient_id;
    std::vector<double> lead_values;  // Simplified sample
    std::chrono::system_clock::time_point timestamp;
};

struct VisualizationSnapshot
{
    std::string patient_id;
    SignalType  signal;
    double      mean_value;           // Example derived metric
    size_t      sample_count;
    std::chrono::system_clock::time_point generated_at;
};

/* ============================================================
 *  In-memory Event Bus (subset of production interface)
 * ============================================================*/

class EventBus
{
public:
    using HandlerId = std::size_t;
    using Callback  = std::function<void(const ECGSample&)>;

    HandlerId subscribe(Callback cb)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const HandlerId id = next_id_++;
        subscribers_.emplace_back(id, std::move(cb));
        return id;
    }

    void unsubscribe(HandlerId id)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        subscribers_.erase(
            std::remove_if(subscribers_.begin(), subscribers_.end(),
                           [id](const auto& pair) { return pair.first == id; }),
            subscribers_.end());
    }

    void publish(const ECGSample& sample) const
    {
        std::vector<Callback> local_copy;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            for (auto& [_, cb] : subscribers_) { local_copy.emplace_back(cb); }
        }
        // Dispatch asynchronously to emulate production bus behaviour.
        for (auto& cb : local_copy)
        {
            std::thread{cb, sample}.detach();
        }
    }

private:
    mutable std::mutex                         mutex_;
    std::vector<std::pair<HandlerId, Callback>> subscribers_;
    HandlerId                                  next_id_{0};
};

/* ============================================================
 *  VisualizationService (simplified production-style logic)
 * ============================================================*/

class VisualizationService
{
public:
    explicit VisualizationService(EventBus& bus, std::chrono::milliseconds timeout = 250ms)
        : bus_(bus), transformation_timeout_(timeout)
    {
        // Subscribe to the bus as part of construction (RAII style).
        subscription_id_ = bus_.subscribe([this](const ECGSample& s) { on_sample(s); });
    }

    ~VisualizationService()
    {
        bus_.unsubscribe(subscription_id_);
        stop_requested_.store(true);
        if (worker_.joinable()) { worker_.join(); }
    }

    // API endpoint—blocking call that returns a const snapshot
    // Throws std::out_of_range if no snapshot exists.
    VisualizationSnapshot get_snapshot(const std::string& patient) const
    {
        std::shared_lock<std::shared_mutex> lock(data_mutex_);
        return snapshots_.at(patient);
    }

    // Non-blocking convenience used by tests to verify readiness
    bool has_snapshot(const std::string& patient) const
    {
        std::shared_lock<std::shared_mutex> lock(data_mutex_);
        return snapshots_.find(patient) != snapshots_.end();
    }

private:
    void on_sample(const ECGSample& sample)
    {
        // Push to internal queue for worker thread to consume
        {
            std::lock_guard<std::mutex> lock(queue_mutex_);
            work_queue_.push_back(sample);
        }
        queue_cv_.notify_one();

        // Lazy-start worker thread
        std::call_once(start_flag_, [this] { worker_ = std::thread(&VisualizationService::worker_loop, this); });
    }

    void worker_loop()
    {
        while (!stop_requested_.load())
        {
            ECGSample sample;
            {
                std::unique_lock<std::mutex> lock(queue_mutex_);
                queue_cv_.wait_for(lock, 10ms, [this] { return !work_queue_.empty() || stop_requested_.load(); });
                if (stop_requested_.load()) { break; }
                if (work_queue_.empty()) { continue; }

                sample = std::move(work_queue_.front());
                work_queue_.pop_front();
            }

            // Time-boxed transformation work (simulate DSP, FFT, etc.)
            auto start = std::chrono::steady_clock::now();
            double mean = 0.0;
            for (double v : sample.lead_values) { mean += v; }
            mean /= static_cast<double>(sample.lead_values.size());
            std::this_thread::sleep_for(5ms);  // simulate compute time
            if (std::chrono::steady_clock::now() - start > transformation_timeout_)
            {
                // Signal degradation metrics, omitted for brevity.
                continue;
            }

            VisualizationSnapshot snap;
            snap.patient_id    = sample.patient_id;
            snap.signal        = SignalType::ECG;
            snap.mean_value    = mean;
            snap.sample_count  = sample.lead_values.size();
            snap.generated_at  = std::chrono::system_clock::now();

            {
                std::unique_lock<std::shared_mutex> lock(data_mutex_);
                snapshots_[snap.patient_id] = std::move(snap);
            }
        }
    }

    EventBus&                              bus_;
    EventBus::HandlerId                    subscription_id_;
    std::chrono::milliseconds              transformation_timeout_;

    std::atomic<bool>                      stop_requested_{false};
    std::thread                            worker_;
    std::once_flag                         start_flag_;

    // Work queue
    mutable std::mutex                     queue_mutex_;
    std::condition_variable                queue_cv_;
    std::deque<ECGSample>                  work_queue_;

    // Snapshot store
    mutable std::shared_mutex              data_mutex_;
    std::unordered_map<std::string, VisualizationSnapshot> snapshots_;
};

/* ============================================================
 *  Test utilities
 * ============================================================*/

namespace
{
std::vector<double> generate_noisy_ecg(size_t n)
{
    std::vector<double> result(n);
    std::mt19937_64      rng{42};
    std::normal_distribution<double> noise{0.0, 0.05};

    for (size_t i = 0; i < n; ++i)
    {
        // Roughly simulate a sine wave + gaussian noise.
        double value = std::sin(2.0 * M_PI * (static_cast<double>(i) / n)) + noise(rng);
        result[i]    = value;
    }
    return result;
}
} // namespace

/* ============================================================
 *  Integration tests
 * ============================================================*/

class VisualizationServiceTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        service_ = std::make_unique<VisualizationService>(bus_);
    }

    void TearDown() override
    {
        service_.reset(); // ensure destructor joins thread
    }

    EventBus                            bus_;
    std::unique_ptr<VisualizationService> service_;
};

TEST_F(VisualizationServiceTest, SnapshotIsGeneratedAndAccessible)
{
    ECGSample sample;
    sample.patient_id  = "patient-001";
    sample.timestamp   = std::chrono::system_clock::now();
    sample.lead_values = generate_noisy_ecg(500);

    bus_.publish(sample);

    // Wait until snapshot becomes available or timeout.
    const auto deadline = std::chrono::steady_clock::now() + 2s;
    while (!service_->has_snapshot("patient-001") && std::chrono::steady_clock::now() < deadline)
    {
        std::this_thread::sleep_for(10ms);
    }

    ASSERT_TRUE(service_->has_snapshot("patient-001")) << "Snapshot was not generated in time.";

    auto snap = service_->get_snapshot("patient-001");
    EXPECT_EQ(snap.patient_id, "patient-001");
    EXPECT_EQ(snap.signal, SignalType::ECG);
    EXPECT_EQ(snap.sample_count, 500u);

    // Mean of sine wave should be approximately zero.
    EXPECT_NEAR(snap.mean_value, 0.0, 0.1);
}

TEST_F(VisualizationServiceTest, ConcurrentSamplesFromMultiplePatientsProduceIsolatedSnapshots)
{
    constexpr std::size_t kPatients = 5;
    constexpr std::size_t kSamples  = 300;

    std::vector<std::future<void>> futures;
    for (std::size_t p = 0; p < kPatients; ++p)
    {
        futures.emplace_back(std::async(std::launch::async, [&, id = p] {
            ECGSample s;
            s.patient_id  = "patient-" + std::to_string(id);
            s.timestamp   = std::chrono::system_clock::now();
            s.lead_values = generate_noisy_ecg(kSamples);
            bus_.publish(s);
        }));
    }
    for (auto& f : futures) { f.get(); }

    // Verify each patient has its own snapshot.
    const auto deadline = std::chrono::steady_clock::now() + 2s;
    for (std::size_t p = 0; p < kPatients; ++p)
    {
        const std::string pid = "patient-" + std::to_string(p);
        while (!service_->has_snapshot(pid) && std::chrono::steady_clock::now() < deadline)
        {
            std::this_thread::sleep_for(5ms);
        }
        ASSERT_TRUE(service_->has_snapshot(pid)) << "Missing snapshot for " << pid;
        auto snap = service_->get_snapshot(pid);
        EXPECT_EQ(snap.sample_count, kSamples);
    }
}

TEST_F(VisualizationServiceTest, GetSnapshotThrowsForUnknownPatient)
{
    EXPECT_THROW({ service_->get_snapshot("nonexistent"); }, std::out_of_range);
}

TEST_F(VisualizationServiceTest, TransformationTimeoutIsHonored)
{
    // Construct a service with an unrealistically low timeout to force failure
    VisualizationService fastFailService{bus_, 1ms};

    ECGSample heavy;
    heavy.patient_id  = "slow-patient";
    heavy.timestamp   = std::chrono::system_clock::now();
    heavy.lead_values = generate_noisy_ecg(10'000); // Large workload

    bus_.publish(heavy);

    std::this_thread::sleep_for(250ms);
    EXPECT_FALSE(fastFailService.has_snapshot("slow-patient"))
        << "Snapshot should have been discarded due to timeout.";
}
```