```cpp
/************************************************************************************
 * MosaicBoard Studio – Unit-Test Suite
 * File: tests/test_main.cpp
 *
 * This file contains a focused but representative set of unit-tests that exercise
 * critical infrastructure used by most runtime features: the plug-in discovery
 * mechanism and the real-time event bus.  The tests are written with Catch2 and
 * are fully self-contained; all helper utilities live in anonymous namespaces so
 * they will not collide with production symbols.  The code is C++17 compliant.
 *
 * To build:
 *     g++ -std=c++17 -Wall -Wextra -pedantic -pthread test_main.cpp -o test_main
 *
 * Dependencies:
 *     Catch2 single-header (https://github.com/catchorg/Catch2/releases)
 ************************************************************************************/

#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <future>
#include <mutex>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

/**********************************************************************
 * Helpers / Test Doubles
 *********************************************************************/
namespace
{

/* --------------------------------------------------------------------
 * Fake plugin-loader that mimics the production behavior (minus RTLD).
 * ------------------------------------------------------------------*/
class PluginLoader final
{
public:
    explicit PluginLoader(fs::path pluginsDir)
        : _pluginDir(std::move(pluginsDir))
    {
        if (!fs::exists(_pluginDir) || !fs::is_directory(_pluginDir))
        {
            std::ostringstream err;
            err << "Plugin directory '" << _pluginDir << "' is not valid.";
            throw std::runtime_error(err.str());
        }
    }

    struct PluginMeta
    {
        std::string  name;
        fs::path     path;
        std::uintmax_t size;
        std::chrono::system_clock::time_point timestamp;
    };

    /* Scans the directory and returns rich metadata for each .so/.dll.*/
    std::vector<PluginMeta> scan() const
    {
        std::vector<PluginMeta> out;
        for (auto const& entry : fs::directory_iterator(_pluginDir))
        {
            if (!entry.is_regular_file()) { continue; }

#ifdef _WIN32
            constexpr auto ext = ".dll";
#else
            constexpr auto ext = ".so";
#endif
            if (entry.path().extension() != ext) { continue; }

            PluginMeta meta;
            meta.name      = entry.path().stem().string();
            meta.path      = entry.path();
            meta.size      = entry.file_size();
            meta.timestamp = fs::last_write_time(entry);

            out.push_back(std::move(meta));
        }
        return out;
    }

private:
    fs::path _pluginDir;
};

/* --------------------------------------------------------------------
 * Minimal but thread-safe event bus for broadcasting domain messages.
 * ------------------------------------------------------------------*/
class EventBus
{
public:
    using EventId = std::size_t;
    using Callback = std::function<void(const std::string&)>;

    EventId subscribe(Callback cb)
    {
        std::scoped_lock lk(_mx);
        EventId id = ++_nextId;
        _subs.emplace(id, std::move(cb));
        return id;
    }

    void unsubscribe(EventId id)
    {
        std::scoped_lock lk(_mx);
        _subs.erase(id);
    }

    void publish(const std::string& payload) const
    {
        std::unordered_map<EventId, Callback> snapshot;
        {
            std::scoped_lock lk(_mx);
            snapshot = _subs; // copy on purpose (cheap, N small)
        }

        for (auto const& [id, cb] : snapshot)
        {
            try
            {
                cb(payload);
            }
            catch (...)
            {
                // Ensure one bad subscriber does not break the bus.
            }
        }
    }

    std::size_t subscriberCount() const
    {
        std::scoped_lock lk(_mx);
        return _subs.size();
    }

private:
    mutable std::mutex                        _mx;
    std::unordered_map<EventId, Callback>     _subs;
    std::atomic<EventId>                      _nextId{0};
};

/* --------------------------------------------------------------------
 * Utility: RAII temp directory that cleans itself up.
 * ------------------------------------------------------------------*/
class ScopedTempDir
{
public:
    ScopedTempDir()
        : _path(fs::temp_directory_path() /
                fs::path("mbs_test_XXXXXX").replace_extension())
    {
        fs::create_directory(_path);
    }

    ~ScopedTempDir()
    {
        std::error_code ec;
        fs::remove_all(_path, ec); // silent cleanup
    }

    const fs::path& path() const { return _path; }

    // Create a dummy file of given extension and size.
    fs::path touch(const std::string& baseName,
                   const std::string& ext,
                   std::size_t bytes = 128)
    {
        fs::path p = _path / (baseName + ext);
        std::ofstream ofs(p, std::ios::binary);
        std::vector<char> buffer(bytes, '0');
        ofs.write(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        return p;
    }

private:
    fs::path _path;
};

} // anonymous namespace

/**********************************************************************
 * Plugin Loader – Positive Scenarios
 *********************************************************************/
TEST_CASE("PluginLoader discovers all shared libraries", "[plugin][positive]")
{
    ScopedTempDir tmp;
#ifdef _WIN32
    constexpr auto ext = ".dll";
#else
    constexpr auto ext = ".so";
#endif
    // Create three dummy shared libs + one irrelevant file.
    tmp.touch("alpha", ext, 256);
    tmp.touch("beta",  ext, 512);
    tmp.touch("gamma", ext, 1024);
    tmp.touch("README", ".txt");

    PluginLoader loader(tmp.path());
    auto plugins = loader.scan();

    REQUIRE(plugins.size() == 3);

    std::vector<std::string> names;
    for (auto const& m : plugins) { names.push_back(m.name); }

    REQUIRE_THAT(names, Catch::Matchers::UnorderedEquals(
        std::vector<std::string>{"alpha", "beta", "gamma"}));
}

TEST_CASE("PluginLoader metadata fields are populated", "[plugin][meta]")
{
    ScopedTempDir tmp;
#ifdef _WIN32
    constexpr auto ext = ".dll";
#else
    constexpr auto ext = ".so";
#endif
    auto file = tmp.touch("delta", ext, 777);

    PluginLoader loader(tmp.path());
    auto plugins = loader.scan();
    REQUIRE(plugins.size() == 1);

    const auto& meta = plugins.front();
    REQUIRE(meta.name == "delta");
    REQUIRE(meta.path == file);
    REQUIRE(meta.size == 777);
    REQUIRE(meta.timestamp.time_since_epoch().count() > 0);
}

/**********************************************************************
 * Plugin Loader – Negative Scenarios
 *********************************************************************/
TEST_CASE("PluginLoader throws if directory is missing", "[plugin][negative]")
{
    fs::path bogus = fs::temp_directory_path() / "this_should_not_exist";

    REQUIRE_THROWS_AS(PluginLoader{bogus}, std::runtime_error);
}

/**********************************************************************
 * Event Bus – Subscription Lifecycle
 *********************************************************************/
TEST_CASE("EventBus delivers messages to all subscribers", "[eventbus]")
{
    EventBus bus;
    std::string recv1, recv2;

    auto id1 = bus.subscribe([&](auto msg){ recv1 = msg; });
    auto id2 = bus.subscribe([&](auto msg){ recv2 = msg; });

    bus.publish("hello world");

    REQUIRE(recv1 == "hello world");
    REQUIRE(recv2 == "hello world");
    REQUIRE(bus.subscriberCount() == 2);

    bus.unsubscribe(id1);
    bus.publish("again"); // only recv2 should change

    REQUIRE(recv1 == "hello world");
    REQUIRE(recv2 == "again");
    REQUIRE(bus.subscriberCount() == 1);
}

/**********************************************************************
 * Event Bus – Concurrency Stress-Test
 *********************************************************************/
TEST_CASE("EventBus remains stable under concurrent load", "[eventbus][concurrency]")
{
    constexpr std::size_t N_THREADS   = 32;
    constexpr std::size_t N_MESSAGES  = 100;
    constexpr std::size_t EXPECTED    = N_THREADS * N_MESSAGES;

    EventBus bus;
    std::atomic<std::size_t> total{0};

    // Each thread subscribes with its own callback.
    std::vector<EventBus::EventId> ids;
    ids.reserve(N_THREADS);

    for (std::size_t i = 0; i < N_THREADS; ++i)
    {
        ids.push_back(bus.subscribe([&](auto /*msg*/){ ++total; }));
    }

    std::vector<std::thread> workers;
    for (std::size_t i = 0; i < N_THREADS; ++i)
    {
        workers.emplace_back([&]{
            for (std::size_t n = 0; n < N_MESSAGES; ++n)
            {
                bus.publish("ping");
            }
        });
    }

    for (auto& th : workers) { th.join(); }

    // All subscribers should have seen every message.
    REQUIRE(total == EXPECTED);

    // Cleanup (not strictly necessary for test correctness)
    for (auto id : ids) { bus.unsubscribe(id); }
}

/**********************************************************************
 * Event Bus – Subscriber Exceptions
 *********************************************************************/
TEST_CASE("EventBus isolates subscriber exceptions", "[eventbus][robustness]")
{
    EventBus bus;
    std::atomic<bool> goodCalled{false};

    bus.subscribe([](auto){
        throw std::runtime_error("intentional");
    });
    bus.subscribe([&](auto){ goodCalled = true; });

    REQUIRE_NOTHROW(bus.publish("test"));
    REQUIRE(goodCalled.load());
}
```