#include <gtest/gtest.h>
#include <atomic>
#include <chrono>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "core/event/EventBus.hpp"   // Production header under test

using namespace mosaic::core::event;

// -----------------------------------------------------------------------------
// Fake domain-level events used in the test-suite
// -----------------------------------------------------------------------------
struct PriceTick
{
    std::string  symbol;
    double       value;
    std::int64_t timestamp{};
};

struct UserLoggedIn
{
    std::string userId;
};

// Base-class for inheritance/wild-card subscription test
struct DashboardEvent
{
    virtual ~DashboardEvent() = default;
};

// Derived event for inheritance test
struct DashboardResized : public DashboardEvent
{
    int width {};
    int height{};
};

// Helper alias for clean syntax
using HandlerId = EventBus::SubscriptionHandle;

// -----------------------------------------------------------------------------
// Test fixture
// -----------------------------------------------------------------------------
class EventBusTest : public ::testing::Test
{
protected:
    EventBus bus_;

    // In most prod builds EventBus is a singleton, but unit-tests prefer
    // an isolated instance to avoid cross-test interference.
    void SetUp() override
    {
        // Ensure fresh bus before each test
        bus_.reset();
    }
};

// -----------------------------------------------------------------------------
// TEST CASES
// -----------------------------------------------------------------------------

TEST_F(EventBusTest, PublishIsDeliveredToSingleSubscriber)
{
    std::promise<PriceTick>            done;
    const std::string                  expectedSymbol = "BTC/USD";

    HandlerId h = bus_.subscribe<PriceTick>(
        [&](const PriceTick& tick)
        {
            ASSERT_EQ(tick.symbol, expectedSymbol);
            done.set_value(tick);
        });

    // Publish should ultimately resolve the promise
    bus_.publish(PriceTick{expectedSymbol, 37'115.5, 0});
    PriceTick received = done.get_future().get();

    EXPECT_DOUBLE_EQ(received.value, 37'115.5);
    bus_.unsubscribe(h);   // Clean-up explicit for clarity
}

TEST_F(EventBusTest, MultipleSubscribersAllReceiveEvent)
{
    constexpr std::size_t subscriberCount = 8;
    std::atomic<std::size_t> counter{0};

    std::vector<HandlerId> handles;
    handles.reserve(subscriberCount);

    for (std::size_t i = 0; i < subscriberCount; ++i)
    {
        handles.push_back(
            bus_.subscribe<UserLoggedIn>(
                [&](const UserLoggedIn&)
                {
                    ++counter;
                }));
    }

    bus_.publish(UserLoggedIn{"alice"});
    // Wait a moment to allow async dispatch if EventBus is multi-threaded
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    EXPECT_EQ(counter.load(), subscriberCount);

    for (auto h : handles) { bus_.unsubscribe(h); }
}

TEST_F(EventBusTest, UnsubscribeStopsDelivery)
{
    std::atomic<int> hits{0};
    HandlerId h = bus_.subscribe<PriceTick>(
        [&](const PriceTick&) { ++hits; });

    bus_.publish(PriceTick{"ETH/USD", 1'900.0, 0});
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    EXPECT_EQ(hits.load(), 1);

    bus_.unsubscribe(h);

    bus_.publish(PriceTick{"ETH/USD", 1'901.0, 0});
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    EXPECT_EQ(hits.load(), 1); // Still 1, no further deliveries
}

TEST_F(EventBusTest, WildcardSubscriptionReceivesDerivedEvents)
{
    std::promise<void> delivery;

    HandlerId h = bus_.subscribe<DashboardEvent>(
        [&](const DashboardEvent& e)
        {
            auto* resized = dynamic_cast<const DashboardResized*>(&e);
            ASSERT_NE(resized, nullptr);
            ASSERT_EQ(resized->width, 1920);
            ASSERT_EQ(resized->height, 1080);
            delivery.set_value();
        });

    bus_.publish(DashboardResized{1920, 1080});
    ASSERT_EQ(delivery.get_future().wait_for(std::chrono::milliseconds(100)),
              std::future_status::ready);

    bus_.unsubscribe(h);
}

TEST_F(EventBusTest, ConcurrentPublishSafety)
{
    // This test spawns multiple publisher threads and verifies that all
    // published events are received exactly once per subscriber.
    constexpr std::size_t publishers     = 4;
    constexpr std::size_t eventsPerThread = 10'000;

    std::atomic<std::size_t> received{0};

    HandlerId h = bus_.subscribe<PriceTick>(
        [&](const PriceTick&) { ++received; });

    std::vector<std::thread> threads;
    for (std::size_t i = 0; i < publishers; ++i)
    {
        threads.emplace_back([&, i]
        {
            for (std::size_t n = 0; n < eventsPerThread; ++n)
            {
                PriceTick tick{"EUR/USD", 1.12, static_cast<std::int64_t>(n)};
                bus_.publish(tick);
            }
        });
    }

    for (auto& t : threads) t.join();

    // Allow async dispatch to flush
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    EXPECT_EQ(received.load(), publishers * eventsPerThread);
    bus_.unsubscribe(h);
}

TEST_F(EventBusTest, SubscriberCanPublishReentrantly)
{
    // Regression test: a subscriber publishes a new event while handling
    // another one. The bus must not deadlock or drop messages.
    std::promise<void> publishedTwice;

    HandlerId hTick = bus_.subscribe<PriceTick>(
        [&](const PriceTick&)
        {
            // Reentrantly publish inside the handler
            bus_.publish(UserLoggedIn{"bob"});
        });

    HandlerId hUser = bus_.subscribe<UserLoggedIn>(
        [&](const UserLoggedIn& ul)
        {
            if (ul.userId == "bob")
                publishedTwice.set_value();
        });

    bus_.publish(PriceTick{"BTC/USD", 38'000.0, 0});

    ASSERT_EQ(publishedTwice.get_future().wait_for(std::chrono::milliseconds(100)),
              std::future_status::ready);

    bus_.unsubscribe(hTick);
    bus_.unsubscribe(hUser);
}