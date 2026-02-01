```cpp
/**
 *  @file   test_config_manager.cpp
 *  @brief  Unit–tests for the CardioInsight360 ConfigManager subsystem.
 *
 *  These test–cases validate behaviour that is critical for the rest of the
 *  analytics engine:
 *      • Correct parsing of on–disk configuration (JSON / YAML)
 *      • Environment variable interpolation (HIPAA paths, secrets, …)
 *      • Run-time overrides for integration-testing & hot-reconfiguration
 *      • Strong-exception guarantees on malformed input
 *      • Thread-safe, lock-free reads under massive parallelism
 *
 *  The tests are written with GoogleTest and require that ConfigManager itself
 *  has already been built into the test-runner.  The ConfigManager interface is
 *  intentionally thin so that higher layers are oblivious to the underlying
 *  storage format.
 */

#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <future>
#include <nlohmann/json.hpp>
#include <random>
#include <thread>

#include "config/ConfigManager.hpp"   // Project header

namespace fs  = std::filesystem;
using json    = nlohmann::json;
using ci360cm = ci360::config::ConfigManager;

// -------------------------------------------------------------------------------------------------
//                                                    Helpers
// -------------------------------------------------------------------------------------------------

namespace
{
/**
 * Creates a unique temporary file, writes the supplied content, and returns the path.
 */
fs::path createTemporaryFile(const std::string& stem,
                             const std::string& ext,
                             const std::string& content)
{
    const auto temp_dir = fs::temp_directory_path();
    const auto file =
        temp_dir /
        (stem + "_" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) +
         "." + ext);

    std::ofstream ofs(file, std::ios::out | std::ios::trunc);
    if (!ofs)
    {
        throw std::runtime_error("Failed to create temporary config file at " + file.string());
    }
    ofs << content;
    ofs.close();
    return file;
}

/**
 * Cross-platform environment setter that overwrites an existing variable.
 */
void setEnv(const std::string& key, const std::string& val)
{
#ifdef _WIN32
    _putenv_s(key.c_str(), val.c_str());
#else
    setenv(key.c_str(), val.c_str(), 1);
#endif
}
}   // namespace

// -------------------------------------------------------------------------------------------------
//                                           Test-Fixture
// -------------------------------------------------------------------------------------------------

class ConfigManagerTest : public ::testing::Test
{
protected:
    void SetUp() override { ci360cm::instance().reset(); }

    void TearDown() override { ci360cm::instance().reset(); }
};

// -------------------------------------------------------------------------------------------------
//                                                 Tests
// -------------------------------------------------------------------------------------------------

TEST_F(ConfigManagerTest, CanLoadValidJsonFile)
{
    const std::string kJson = R"json(
        {
          "engine": {
            "thread_pool_size": 16,
            "log_level": "INFO"
          },
          "etl": {
            "batch_window_sec": 300
          }
        })json";

    const fs::path cfgPath = createTemporaryFile("ci360_valid", "json", kJson);

    EXPECT_NO_THROW(ci360cm::instance().loadFromFile(cfgPath.string()));

    const auto& raw = ci360cm::instance().getRaw();
    EXPECT_TRUE(raw.contains("engine"));
    EXPECT_EQ(ci360cm::instance().get<int>("engine.thread_pool_size"), 16);
    EXPECT_EQ(ci360cm::instance().get<std::string>("engine.log_level"), "INFO");
    EXPECT_EQ(ci360cm::instance().get<int>("etl.batch_window_sec"), 300);

    fs::remove(cfgPath);
}

TEST_F(ConfigManagerTest, LoadThrowsOnMalformedJson)
{
    const std::string kMalformed = R"json({  "foo": 123   // missing closing brace)json";
    const fs::path   cfgPath     = createTemporaryFile("ci360_malformed", "json", kMalformed);

    EXPECT_THROW(ci360cm::instance().loadFromFile(cfgPath.string()), std::runtime_error);

    fs::remove(cfgPath);
}

TEST_F(ConfigManagerTest, EnvironmentVariableInterpolation)
{
    setEnv("CI360_TEST_DATA_ROOT", "/var/ci360/data");

    const std::string kJson = R"json(
        {
          "storage": {
            "root": "$(CI360_TEST_DATA_ROOT)/hospital_a"
          }
        })json";

    const fs::path cfgPath = createTemporaryFile("ci360_env", "json", kJson);
    ci360cm::instance().loadFromFile(cfgPath.string());

    EXPECT_EQ(ci360cm::instance().get<std::string>("storage.root"),
              "/var/ci360/data/hospital_a");

    fs::remove(cfgPath);
}

TEST_F(ConfigManagerTest, RuntimeOverrideTakesPrecedence)
{
    const std::string kJson = R"json(
        {
          "streaming": {
            "kafka_brokers": "kafka01:9092",
            "consumer_parallelism": 4
          }
        })json";

    const fs::path cfgPath = createTemporaryFile("ci360_override", "json", kJson);
    ci360cm::instance().loadFromFile(cfgPath.string());

    // Override the number of consumer threads for an isolated test run
    ci360cm::instance().set("streaming.consumer_parallelism", 1);

    EXPECT_EQ(ci360cm::instance().get<int>("streaming.consumer_parallelism"), 1);
    EXPECT_EQ(ci360cm::instance().get<std::string>("streaming.kafka_brokers"), "kafka01:9092");

    fs::remove(cfgPath);
}

TEST_F(ConfigManagerTest, ReloadingUpdatesConfigurationTree)
{
    // First version
    const std::string v1 = R"json({ "etl": { "batch_window_sec": 300 } })json";
    const fs::path     f1 = createTemporaryFile("ci360_reload_v1", "json", v1);
    ci360cm::instance().loadFromFile(f1.string());

    EXPECT_EQ(ci360cm::instance().get<int>("etl.batch_window_sec"), 300);

    // Second version, changing the batch window and adding a new key
    const std::string v2 = R"json(
        {
          "etl": { "batch_window_sec": 600 },
          "alerts": { "enabled": true }
        })json";

    const fs::path f2 = createTemporaryFile("ci360_reload_v2", "json", v2);
    ci360cm::instance().loadFromFile(f2.string());

    EXPECT_EQ(ci360cm::instance().get<int>("etl.batch_window_sec"), 600);
    EXPECT_TRUE(ci360cm::instance().has("alerts.enabled"));
    EXPECT_TRUE(ci360cm::instance().get<bool>("alerts.enabled"));

    fs::remove(f1);
    fs::remove(f2);
}

TEST_F(ConfigManagerTest, ThreadSafeConcurrentReads)
{
    const std::string kJson = R"json(
        {
          "engine": { "thread_pool_size": 8 },
          "db": {
            "host": "127.0.0.1",
            "port": 5432,
            "user": "ci360",
            "password": "secret"
          }
        })json";

    const fs::path cfgPath = createTemporaryFile("ci360_concurrency", "json", kJson);
    ci360cm::instance().loadFromFile(cfgPath.string());

    // Spin up a bunch of reader threads that will hammer the ConfigManager
    constexpr std::size_t kReaders = 128;
    std::vector<std::future<void>> futures;
    futures.reserve(kReaders);

    for (std::size_t i = 0; i < kReaders; ++i)
    {
        futures.emplace_back(std::async(std::launch::async, []
        {
            for (int j = 0; j < 1'000; ++j)
            {
                EXPECT_EQ(ci360cm::instance().get<int>("engine.thread_pool_size"), 8);
                EXPECT_EQ(ci360cm::instance().get<std::string>("db.user"), "ci360");
            }
        }));
    }

    for (auto& f : futures) { f.get(); }

    fs::remove(cfgPath);
}
```