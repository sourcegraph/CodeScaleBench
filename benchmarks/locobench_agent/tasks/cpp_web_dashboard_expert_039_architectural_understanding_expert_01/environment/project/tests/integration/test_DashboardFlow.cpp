```cpp
/*
 *  test_DashboardFlow.cpp
 *  MosaicBoard Studio – Integration Tests
 *
 *  These tests exercise a realistic “happy-path” user flow that spans
 *  authentication, dynamic plug-in discovery, event propagation and
 *  dashboard life-cycle management.  Unlike unit tests, the goal here is to
 *  validate the interaction between multiple concrete components in the
 *  public API surface of MosaicBoard Studio.
 *
 *  Requirements:
 *      – GoogleTest / GoogleMock
 *      – A test-time plug-in bundle located under
 *        <project-root>/tests/fixtures/plugins
 */

#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include <chrono>
#include <filesystem>
#include <future>
#include <memory>
#include <string>
#include <thread>

// Project headers
#include "core/Config.h"
#include "core/EventBus.h"
#include "core/TileBase.h"
#include "core/TileRegistry.h"
#include "dashboard/DashboardSession.h"
#include "services/AuthService.h"
#include "services/Token.h"

namespace fs = std::filesystem;
using namespace std::chrono_literals;
using ::testing::_;
using ::testing::Invoke;
using ::testing::StrictMock;

/* ------------------------------------------------------------------------
 *  Test Fixtures
 * --------------------------------------------------------------------- */

class DashboardFlowTest : public ::testing::Test
{
protected:
    // Constants ----------------------------------------------------------------
    static constexpr const char* kTestUserId       = "integration_user_42@example.com";
    static constexpr const char* kOAuthProvider    = "github";
    static constexpr const char* kPluginFixtureDir = "tests/fixtures/plugins";

    // Members -------------------------------------------------------------------
    mb::Config                       m_config;
    std::shared_ptr<mb::EventBus>    m_bus;
    std::shared_ptr<mb::TileRegistry> m_registry;
    std::shared_ptr<mb::AuthService>  m_auth;

    void SetUp() override
    {
        // Realistic config values for an in-memory test run
        m_config.runMode         = mb::RunMode::Test;
        m_config.pluginDirectory = fs::canonical(kPluginFixtureDir).string();  // Will throw if path invalid.
        m_config.enableCaching   = false;

        // Concrete instances; we want an *integration* not a pure unit test.
        m_bus      = std::make_shared<mb::InMemoryEventBus>();
        m_registry = std::make_shared<mb::TileRegistry>(m_bus, m_config);
        m_auth     = std::make_shared<mb::AuthService>(m_config);

        // Most integration tests will want a clean registry
        ASSERT_NO_THROW(m_registry->loadPlugins());
        ASSERT_GT(m_registry->size(), 0u) << "No plug-ins were discovered in fixture directory";
    }

    void TearDown() override
    {
        // Give the event bus time to process any lingering async messages.
        m_bus->flush();
    }
};

/* ------------------------------------------------------------------------
 *  Custom Matcher Helpers
 * --------------------------------------------------------------------- */

MATCHER_P(HasLayoutName, expected, "")
{
    return arg.layoutName == expected;
}

/* ------------------------------------------------------------------------
 *  Tests
 * --------------------------------------------------------------------- */

// 1. Social login returns a valid token and we store session metadata.
TEST_F(DashboardFlowTest, SocialLogin_HappyPath)
{
    mb::Credentials creds;
    creds.userName = kTestUserId;
    creds.oauthToken = "dummy-oauth-token";

    // Attempt login
    mb::Token token;
    EXPECT_NO_THROW({ token = m_auth->loginWithProvider(kOAuthProvider, creds); });

    EXPECT_TRUE(token.isValid());
    EXPECT_EQ(token.userId(), kTestUserId);
    EXPECT_EQ(token.provider(), kOAuthProvider);
}

// 2. Plug-in registry dynamically discovers & loads tiles.
TEST_F(DashboardFlowTest, PluginDiscovery_LoadsExpectedTiles)
{
    // Example plug-ins shipped with tests: “RandomColor”, “Clock”, “AudioFFT”
    const std::vector<std::string> expected { "RandomColor", "Clock", "AudioFFT" };

    for (const auto& tileName : expected)
    {
        SCOPED_TRACE(tileName);
        EXPECT_TRUE(m_registry->contains(tileName)) << "Tile not found: " << tileName;
    }
}

// 3. EventBus properly propagates messages from publisher tile → subscriber tile.
TEST_F(DashboardFlowTest, EventBus_PropagatesTileStateChanges)
{
    // Choose 2 arbitrary tiles
    auto clock = m_registry->instantiate("Clock");
    auto fft   = m_registry->instantiate("AudioFFT");

    ASSERT_NE(clock, nullptr);
    ASSERT_NE(fft,   nullptr);

    // We’ll listen for a “tick” coming from Clock. Once FFT receives that
    // tick we set our promise.
    std::promise<void> receivedTick;
    auto fut = receivedTick.get_future();

    fft->onEvent("clock/tick", [&](const mb::EventPayload&)
    {
        receivedTick.set_value();
    });

    // Publish from “clock”
    clock->emit("clock/tick", {});

    // Wait for maximum 1 second; test fails on timeout.
    EXPECT_EQ(fut.wait_for(1s), std::future_status::ready);
}

// 4. Full dashboard session bootstraps with authenticated user & default layout.
TEST_F(DashboardFlowTest, DashboardSession_EndToEnd)
{
    // --------------------------------
    // 1) Login
    // --------------------------------
    mb::Credentials creds { kTestUserId, "dummy-oauth-token" };
    auto token = m_auth->loginWithProvider(kOAuthProvider, creds);
    ASSERT_TRUE(token.isValid());

    // --------------------------------
    // 2) Start dashboard session
    // --------------------------------
    mb::DashboardSession session(token, m_config, m_bus, m_registry);
    ASSERT_NO_THROW(session.start());

    // The session should have loaded its default layout:
    auto layout = session.currentLayout();
    ASSERT_TRUE(layout.has_value());
    EXPECT_THAT(*layout, HasLayoutName("default"));

    // --------------------------------
    // 3) Simulate a user gesture that triggers a tile swap
    // --------------------------------
    const std::string tileToRemove = "RandomColor";
    const std::string tileToAdd    = "CPUUsage";

    // Pre-conditions
    EXPECT_TRUE(session.containsTile(tileToRemove));
    EXPECT_FALSE(session.containsTile(tileToAdd));

    // Swap tiles (this should be an atomic operation)
    ASSERT_NO_THROW(session.replaceTile(tileToRemove, tileToAdd));

    // Post-conditions
    EXPECT_FALSE(session.containsTile(tileToRemove));
    EXPECT_TRUE(session.containsTile(tileToAdd));

    // --------------------------------
    // 4) Verify event bus metrics
    // --------------------------------
    auto metrics = m_bus->diagnostics();
    EXPECT_GT(metrics.messageCount, 0u);
    EXPECT_GT(metrics.subscriberCount, 0u);

    // --------------------------------
    // 5) Clean shutdown
    // --------------------------------
    ASSERT_NO_THROW(session.shutdown());
    EXPECT_TRUE(session.isTerminated());
}

/* ------------------------------------------------------------------------
 *  main()
 * --------------------------------------------------------------------- */
/*
 *  GoogleTest traditionally defines its own main().  Some projects prefer
 *  a hand-rolled main to do additional logging or runtime inspection.  We
 *  only provide one when GTEST_HAS_MAIN is *not* set.
 */
#ifndef GTEST_HAS_MAIN
int main(int argc, char* argv[])
{
    ::testing::InitGoogleTest(&argc, argv);

    // Print the resolved plugin fixture directory for debugging purposes.
    std::cout << "[ INFO ] Using plug-in fixture directory: "
              << fs::canonical(DashboardFlowTest::kPluginFixtureDir) << '\n';

    return RUN_ALL_TESTS();
}
#endif
```