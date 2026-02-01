#include <gtest/gtest.h>

#include <chrono>
#include <condition_variable>
#include <future>
#include <iostream>
#include <mutex>
#include <nlohmann/json.hpp>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

/**
 * @file test_stream_to_alert.cpp
 *
 * Integration-level tests that verify the end-to-end path from an incoming
 * ECG/HL7 message placed on the streaming bus through to an alert emitted by
 * the AlertService.  The implementation uses an in-memory mock of the EventBus
 * so the test remains hermetic while still exercising asynchronous behaviour
 * and basic parsing/threshold logic.
 *
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * Copyright (c) 2024
 */

namespace ci360::test
{

/* -------------------------------------------------------------------------- */
/*                              Mock Event-Streaming                          */
/* -------------------------------------------------------------------------- */

/**
 * Very small, thread-safe, in-memory implementation of the engine’s event bus
 * semantics.  Enough to demonstrate publish/subscribe concurrency without a
 * real Kafka broker.
 */
class InMemoryEventBus final
{
public:
    using Payload  = std::string;
    using Callback = std::function<void(const Payload &)>;

    InMemoryEventBus()  = default;
    ~InMemoryEventBus() = default;

    // Non-copyable / non-movable – keeps life-cycle simple.
    InMemoryEventBus(const InMemoryEventBus &)            = delete;
    InMemoryEventBus &operator=(const InMemoryEventBus &) = delete;
    InMemoryEventBus(InMemoryEventBus &&)                 = delete;
    InMemoryEventBus &operator=(InMemoryEventBus &&)      = delete;

    /**
     * Publish a payload on the specified topic.  Delivery is asynchronous to
     * emulate the real Kafka client behaviour.
     */
    void publish(const std::string &topic, Payload payload)
    {
        std::shared_lock<std::shared_mutex> rd(lock_);
        const auto it = subscribers_.find(topic);
        if (it == subscribers_.end() || it->second.empty()) { return; }

        for (auto &cb : it->second)
        {
            // Dispatch on a detached thread so we do not block the caller.
            std::thread([cb, payload]() { cb(payload); }).detach();
        }
    }

    /**
     * Subscribe to a topic.  The callback receives every message in FIFO order
     * but ordering guarantees are *not* provided across multiple subscribers.
     */
    void subscribe(const std::string &topic, Callback cb)
    {
        std::unique_lock<std::shared_mutex> wr(lock_);
        subscribers_[topic].emplace_back(std::move(cb));
    }

private:
    std::unordered_map<std::string, std::vector<Callback>> subscribers_;
    mutable std::shared_mutex                               lock_;
};

/* -------------------------------------------------------------------------- */
/*                               Domain Models                                */
/* -------------------------------------------------------------------------- */

struct EcgSample
{
    std::string patientId;
    int         heartRate;
    int64_t     timestamp;

    nlohmann::json toJson() const
    {
        return {{"patient_id", patientId},
                {"heart_rate", heartRate},
                {"ts", timestamp}};
    }

    static EcgSample fromJson(const nlohmann::json &j)
    {
        return {j.at("patient_id").get<std::string>(),
                j.at("heart_rate").get<int>(),
                j.at("ts").get<int64_t>()};
    }
};

/* -------------------------------------------------------------------------- */
/*                               Alert Service                                */
/* -------------------------------------------------------------------------- */

/**
 * Listens for ECG_STREAM events, applies arrhythmia/threshold checks, and
 * emits alerts on ALERT topic when conditions are violated.
 */
class AlertService
{
public:
    explicit AlertService(InMemoryEventBus &bus, int hrThreshold = 120)
        : bus_(bus), hrThreshold_(hrThreshold)
    {
        // Register consumer for ECG stream
        bus_.subscribe(kEcgTopic,
                       [this](const std::string &payload) { onEcg(payload); });
    }

    static constexpr const char *kEcgTopic   = "ECG_STREAM";
    static constexpr const char *kAlertTopic = "ALERT";

private:
    void onEcg(const std::string &payload)
    {
        try
        {
            const auto sample = EcgSample::fromJson(nlohmann::json::parse(payload));

            if (sample.heartRate > hrThreshold_)
            {
                nlohmann::json alert = {{"type", "HR_HIGH"},
                                        {"value", sample.heartRate},
                                        {"patient_id", sample.patientId},
                                        {"ts", sample.timestamp}};

                bus_.publish(kAlertTopic, alert.dump());
            }
        }
        catch (const std::exception &ex)
        {
            std::cerr << "[AlertService] Failed to handle ECG payload: " << ex.what()
                      << '\n';
        }
    }

    InMemoryEventBus &bus_;
    const int         hrThreshold_;
};

/* -------------------------------------------------------------------------- */
/*                               HL7 Ingestor                                 */
/* -------------------------------------------------------------------------- */

/**
 * Highly simplified façade that accepts an already-serialised ECG payload
 * (stringified JSON) and republishes it onto the internal streaming bus.  In
 * production this class would parse true HL7/FHIR messages.
 */
class HL7Ingestor
{
public:
    explicit HL7Ingestor(InMemoryEventBus &bus) : bus_(bus) {}

    void ingest(const std::string &rawPayload)
    {
        // In a real implementation: HL7 → domain model → JSON for stream.
        bus_.publish(AlertService::kEcgTopic, rawPayload);
    }

private:
    InMemoryEventBus &bus_;
};

/* -------------------------------------------------------------------------- */
/*                              Test Fixture                                  */
/* -------------------------------------------------------------------------- */

class StreamToAlertIntegrationTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        // Wire mock event-bus and subsystems together.
        alertService_ = std::make_unique<AlertService>(bus_, hrThreshold_);
        ingestor_     = std::make_unique<HL7Ingestor>(bus_);
    }

    // Helper used by multiple tests to create ECG samples.
    static EcgSample makeSample(int heartRate)
    {
        return {"P12345",
                heartRate,
                std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch())
                    .count()};
    }

    // Member data
    static constexpr int hrThreshold_ = 120;
    InMemoryEventBus     bus_;
    std::unique_ptr<AlertService> alertService_;
    std::unique_ptr<HL7Ingestor>  ingestor_;
};

/* -------------------------------------------------------------------------- */
/*                               Test Cases                                   */
/* -------------------------------------------------------------------------- */

TEST_F(StreamToAlertIntegrationTest, HighHeartRateGeneratesAlert)
{
    std::promise<std::string> alertPromise;
    auto                      alertFuture = alertPromise.get_future();

    // Capture alert emitted by AlertService
    bus_.subscribe(AlertService::kAlertTopic,
                   [&alertPromise](const std::string &payload) {
                       try
                       {
                           alertPromise.set_value(payload);
                       }
                       catch (const std::future_error &)
                       {
                           // Promise already satisfied—ignore.
                       }
                   });

    const EcgSample sample = makeSample(/*heartRate=*/130);
    ingestor_->ingest(sample.toJson().dump());

    // Wait for alert or timeout.
    const auto status = alertFuture.wait_for(std::chrono::seconds(5));
    ASSERT_EQ(status, std::future_status::ready)
        << "Alert not generated within expected time-frame";

    const auto alertJson = nlohmann::json::parse(alertFuture.get());
    EXPECT_EQ(alertJson.at("type").get<std::string>(), "HR_HIGH");
    EXPECT_EQ(alertJson.at("value").get<int>(), 130);
    EXPECT_EQ(alertJson.at("patient_id").get<std::string>(), "P12345");
}

TEST_F(StreamToAlertIntegrationTest, NormalHeartRateDoesNotGenerateAlert)
{
    std::promise<void> alertTriggered;
    std::atomic<bool>  alertSeen{false};

    bus_.subscribe(AlertService::kAlertTopic,
                   [&](const std::string &) {
                       alertSeen.store(true);
                       alertTriggered.set_value();
                   });

    const EcgSample sample = makeSample(/*heartRate=*/80);
    ingestor_->ingest(sample.toJson().dump());

    const auto status = alertTriggered.get_future().wait_for(std::chrono::seconds(2));
    EXPECT_EQ(status, std::future_status::timeout)
        << "Alert should not be generated for heart-rate below threshold";
    EXPECT_FALSE(alertSeen.load());
}

TEST_F(StreamToAlertIntegrationTest, BurstOfMessagesGeneratesCorrectAlertCount)
{
    constexpr size_t totalMessages      = 10;
    constexpr size_t expectedAlertCount = 4;  // >120 bpm messages below
    std::atomic<size_t> alertCounter{0};
    std::promise<void>  allAlertsReceived;

    bus_.subscribe(AlertService::kAlertTopic,
                   [&](const std::string &) {
                       if (++alertCounter == expectedAlertCount)
                       {
                           allAlertsReceived.set_value();
                       }
                   });

    // Fire a burst of ECG samples with mixed heart-rates.
    for (size_t i = 0; i < totalMessages; ++i)
    {
        const int hr = (i % 3 == 0) ? 130  // alert
                                    : 90;  // normal
        ingestor_->ingest(makeSample(hr).toJson().dump());
    }

    auto status = allAlertsReceived.get_future().wait_for(std::chrono::seconds(5));
    ASSERT_EQ(status, std::future_status::ready)
        << "Did not receive expected number of alerts within timeout";
    EXPECT_EQ(alertCounter.load(), expectedAlertCount);
}

}  // namespace ci360::test