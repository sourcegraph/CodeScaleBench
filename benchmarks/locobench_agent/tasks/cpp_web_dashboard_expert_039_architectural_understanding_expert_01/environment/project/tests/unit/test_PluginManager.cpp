```cpp
/*
 *  MosaicBoard Studio — Unit-tests for PluginManager
 *
 *  File: tests/unit/test_PluginManager.cpp
 *
 *  The real implementation of PluginManager is expected to live in
 *  “mosaic/core/plugin/PluginManager.hpp”.  The tests exercise happy-path
 *  discovery / hot-swap scenarios as well as various failure modes.  All
 *  external side-effects (filesystem access and shared-library loading)
 *  are mocked via GoogleMock so that the test-suite remains hermetic and
 *  lightning fast.
 *
 *  To build the tests you need GoogleTest / GoogleMock on your tool-chain
 *  (e.g. `find_package(GTest CONFIG REQUIRED)` in CMake).
 *
 *  The production PluginManager is assumed to be constructor-injectable
 *  with IFileSystem and ISharedLibraryLoader abstractions.  If this is not
 *  the case in your code-base, provide a thin adapter in the test tree.
 */

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <mutex>
#include <thread>

#include "mosaic/core/plugin/PluginManager.hpp"
#include "mosaic/core/plugin/IPlugin.hpp"
#include "mosaic/core/plugin/IFileSystem.hpp"
#include "mosaic/core/plugin/ISharedLibraryLoader.hpp"

using namespace ::testing;
using namespace mosaic::core;
using namespace std::chrono_literals;

/* ------------------------------------------------------------------ */
/* 1.  Mocks for the two external collaborators of PluginManager      */
/* ------------------------------------------------------------------ */

class MockFileSystem final : public plugin::IFileSystem
{
public:
    MOCK_METHOD(std::vector<std::filesystem::path>,
                listSharedLibraries,
                (const std::filesystem::path& directory),
                (const, override));

    MOCK_METHOD(std::filesystem::file_time_type,
                lastWriteTime,
                (const std::filesystem::path&),
                (const, override));

    MOCK_METHOD(bool,
                isRegularFile,
                (const std::filesystem::path&),
                (const, override));
};

class MockSharedLibraryLoader final : public plugin::ISharedLibraryLoader
{
public:
    MOCK_METHOD(ISharedLibraryLoader::Handle,
                open,
                (const std::filesystem::path&),
                (override));

    MOCK_METHOD(void, close, (Handle), (override));

    MOCK_METHOD(void*,
                resolveSymbol,
                (Handle, const std::string& symbol),
                (override));
};

/* ------------------------------------------------------------------ */
/* 2.  Test-helpers                                                   */
/* ------------------------------------------------------------------ */

// A tiny mock plugin that behaves like a real shared-library export.
class DummyPlugin : public plugin::IPlugin
{
public:
    explicit DummyPlugin(std::string id,
                         std::uint32_t version = 1,
                         std::string readable = {})
        : _id(std::move(id)), _version(version),
          _name(readable.empty() ? _id : std::move(readable))
    {}

    std::string id()        const noexcept override { return _id; }
    std::string name()      const noexcept override { return _name; }
    std::uint32_t version() const noexcept override { return _version; }

    void onLoad()   override { _loaded = true; }
    void onUnload() override { _loaded = false; }
    bool loaded()   const    { return _loaded; }

private:
    std::string  _id;
    std::string  _name;
    std::uint32_t _version;
    bool          _loaded {false};
};

/*
 *  Simulate a C-style plugin factory exported from a shared library:
 *      extern "C" IPlugin* createPlugin();
 */
using PluginFactory = plugin::IPlugin* (*)();

/* ------------------------------------------------------------------ */
/* 3.  Test Fixture                                                   */
/* ------------------------------------------------------------------ */

class PluginManagerTest : public Test
{
protected:
    void SetUp() override
    {
        fileSystem     = std::make_shared<StrictMock<MockFileSystem>>();
        libLoader      = std::make_shared<StrictMock<MockSharedLibraryLoader>>();

        // SUT – System Under Test
        manager        = std::make_unique<plugin::PluginManager>(fileSystem,
                                                                 libLoader);
    }

    void TearDown() override
    {
        manager.reset();
        libLoader.reset();
        fileSystem.reset();
    }

    std::shared_ptr<StrictMock<MockFileSystem>>    fileSystem;
    std::shared_ptr<StrictMock<MockSharedLibraryLoader>> libLoader;
    std::unique_ptr<plugin::PluginManager> manager;
};

/* ------------------------------------------------------------------ */
/* 4.  Positive test-cases                                            */
/* ------------------------------------------------------------------ */

TEST_F(PluginManagerTest, RefreshLoadsAllNewSharedLibraries)
{
    namespace fs = std::filesystem;

    const fs::path pluginsDir{"/plugins"};

    // 1) FS lists two shared libraries (.so / .dll) inside the directory.
    const std::vector<fs::path> dummyLibs {
        pluginsDir / "libChart.so",
        pluginsDir / "libWeather.so"
    };

    EXPECT_CALL(*fileSystem, listSharedLibraries(pluginsDir))
        .Times(AtLeast(1))
        .WillRepeatedly(Return(dummyLibs));

    // 2) For each library, the loader must open it and resolve the symbol.
    //    We model each handle as a std::uintptr_t for test convenience.
    plugin::ISharedLibraryLoader::Handle nextHandle = 1;

    for (const auto& lib : dummyLibs)
    {
        // open()
        EXPECT_CALL(*libLoader, open(lib))
            .WillOnce(Return(nextHandle));

        // resolveSymbol() – export factory.
        EXPECT_CALL(*libLoader,
                    resolveSymbol(nextHandle, "createPlugin"))
            .WillOnce([&](auto, auto)
            {
                static DummyPlugin chart("chart.widget");
                return reinterpret_cast<void*>(+[]() -> plugin::IPlugin* {
                    static DummyPlugin chart("chart.widget"); return &chart; });
            });

        // close() (executed during tear-down)
        EXPECT_CALL(*libLoader, close(nextHandle));
        ++nextHandle;
    }

    // 3) No write-time change for first refresh.
    EXPECT_CALL(*fileSystem, lastWriteTime(_))
        .WillRepeatedly(Return(std::filesystem::file_time_type::clock::now()));

    // Exercise: Trigger discovery.
    manager->setPluginDirectory(pluginsDir);
    manager->refresh();

    ASSERT_TRUE(manager->hasPlugin("chart.widget"));
    ASSERT_TRUE(manager->hasPlugin("weather.widget"));
    EXPECT_EQ(manager->loadedCount(), 2UL);
}

TEST_F(PluginManagerTest, IgnoresFilesThatAreNotRegularLibraries)
{
    namespace fs = std::filesystem;
    const fs::path pluginsDir{"/plugins"};

    const std::vector<fs::path> bogus{
        pluginsDir / "README.txt",
        pluginsDir / "random.doc"
    };

    EXPECT_CALL(*fileSystem, listSharedLibraries(pluginsDir))
        .WillOnce(Return(bogus));

    // listSharedLibraries already performs the filtering, therefore
    // PluginManager must not attempt to open any file.
    EXPECT_CALL(*libLoader, open(_)).Times(0);

    manager->setPluginDirectory(pluginsDir);
    manager->refresh();

    EXPECT_EQ(manager->loadedCount(), 0UL);
}

TEST_F(PluginManagerTest, HotSwappingReloadsUpdatedSharedLibrary)
{
    namespace fs = std::filesystem;
    const fs::path pluginsDir{"/plugins"};
    const fs::path libAudio = pluginsDir / "libAudioReactive.so";

    EXPECT_CALL(*fileSystem, listSharedLibraries(pluginsDir))
        .WillRepeatedly(Return(std::vector<fs::path>{libAudio}));

    // Initial open + resolve.
    plugin::ISharedLibraryLoader::Handle handle1 = 100;
    EXPECT_CALL(*libLoader, open(libAudio))
        .WillOnce(Return(handle1));

    EXPECT_CALL(*libLoader,
                resolveSymbol(handle1, "createPlugin"))
        .WillOnce(+[]([[maybe_unused]] auto, [[maybe_unused]] auto) {
            static DummyPlugin audio("audio.reactive", 1);
            return reinterpret_cast<void*>(+[]() -> plugin::IPlugin* {
                static DummyPlugin audio("audio.reactive", 1); return &audio; });
        });

    // close after first unload
    EXPECT_CALL(*libLoader, close(handle1));

    // File-time before and after the change.
    auto originalTime = fs::file_time_type::clock::now();
    auto changedTime  = originalTime + 5s;

    // First refresh -> originalTime
    EXPECT_CALL(*fileSystem, lastWriteTime(libAudio))
        .WillOnce(Return(originalTime));

    manager->setPluginDirectory(pluginsDir);
    manager->refresh();
    ASSERT_EQ(manager->getPlugin("audio.reactive")->version(), 1U);

    // Simulate external recompilation:
    plugin::ISharedLibraryLoader::Handle handle2 = 101;

    // Second refresh -> changedTime
    EXPECT_CALL(*fileSystem, lastWriteTime(libAudio))
        .WillOnce(Return(changedTime));

    EXPECT_CALL(*libLoader, open(libAudio))
        .WillOnce(Return(handle2));

    EXPECT_CALL(*libLoader,
                resolveSymbol(handle2, "createPlugin"))
        .WillOnce(+[]([[maybe_unused]] auto, [[maybe_unused]] auto) {
            static DummyPlugin audio("audio.reactive", 2);
            return reinterpret_cast<void*>(+[]() -> plugin::IPlugin* {
                static DummyPlugin audio("audio.reactive", 2); return &audio; });
        });

    EXPECT_CALL(*libLoader, close(handle2));

    manager->refresh();
    ASSERT_EQ(manager->getPlugin("audio.reactive")->version(), 2U);
}

/* ------------------------------------------------------------------ */
/* 5.  Negative test-cases                                            */
/* ------------------------------------------------------------------ */

TEST_F(PluginManagerTest, ContinuesLoadingWhenASinglePluginFails)
{
    namespace fs = std::filesystem;
    const fs::path pluginsDir{"/plugins"};

    const fs::path libOk   = pluginsDir / "libOK.so";
    const fs::path libFail = pluginsDir / "libBroken.so";

    EXPECT_CALL(*fileSystem, listSharedLibraries(pluginsDir))
        .WillOnce(Return(std::vector<fs::path>{libOk, libFail}));

    // The “ok” library works.
    plugin::ISharedLibraryLoader::Handle handleOk = 666;
    EXPECT_CALL(*libLoader, open(libOk))
        .WillOnce(Return(handleOk));

    EXPECT_CALL(*libLoader,
                resolveSymbol(handleOk, "createPlugin"))
        .WillOnce(+[]([[maybe_unused]] auto, [[maybe_unused]] auto) {
            static DummyPlugin ok("it.works");
            return reinterpret_cast<void*>(+[]() -> plugin::IPlugin* {
                static DummyPlugin ok("it.works"); return &ok; });
        });

    EXPECT_CALL(*libLoader, close(handleOk));

    // The “broken” library fails to open -> returns invalid handle (=0).
    EXPECT_CALL(*libLoader, open(libFail))
        .WillOnce(Return(plugin::ISharedLibraryLoader::Handle{}));

    // There should be no symbol resolution attempt on the broken handle.
    EXPECT_CALL(*libLoader,
                resolveSymbol(plugin::ISharedLibraryLoader::Handle{}, _))
        .Times(0);

    manager->setPluginDirectory(pluginsDir);
    EXPECT_NO_THROW(manager->refresh());

    EXPECT_TRUE(manager->hasPlugin("it.works"));
    EXPECT_FALSE(manager->hasPlugin("broken"));  // Not present
}

TEST_F(PluginManagerTest, ThreadSafeConcurrentReads)
{
    namespace fs = std::filesystem;
    const fs::path pluginsDir{"/plugins"};

    const fs::path libFoo = pluginsDir / "libFoo.so";
    EXPECT_CALL(*fileSystem, listSharedLibraries(pluginsDir))
        .WillRepeatedly(Return(std::vector<fs::path>{libFoo}));

    plugin::ISharedLibraryLoader::Handle handle = 42;
    EXPECT_CALL(*libLoader, open(libFoo))
        .WillOnce(Return(handle));

    EXPECT_CALL(*libLoader,
                resolveSymbol(handle, "createPlugin"))
        .WillOnce(+[]([[maybe_unused]] auto, [[maybe_unused]] auto) {
            static DummyPlugin foo("foo.bar");
            return reinterpret_cast<void*>(+[]() -> plugin::IPlugin* {
                static DummyPlugin foo("foo.bar"); return &foo; });
        });

    EXPECT_CALL(*libLoader, close(handle));

    manager->setPluginDirectory(pluginsDir);
    manager->refresh();

    // Fire 32 concurrent read-only calls to `getPlugin`.
    std::vector<std::thread> workers;
    std::atomic<size_t>      success{0};

    for (int i = 0; i < 32; ++i)
    {
        workers.emplace_back([&] {
            for (int j = 0; j < 1000; ++j)
            {
                auto plugin = manager->getPlugin("foo.bar");
                if (plugin && plugin->id() == "foo.bar") ++success;
            }
        });
    }

    for (auto& t : workers) t.join();
    EXPECT_EQ(success.load(), 32U * 1000U);
}

/* ------------------------------------------------------------------ */
/* 6.  Main entry-point (optional)                                    */
/* ------------------------------------------------------------------ */

#if !defined(MOSAIC_TESTS_RUNNER_EXTERN)
int main(int argc, char** argv)
{
    ::testing::InitGoogleMock(&argc, argv);
    return RUN_ALL_TESTS();
}
#endif
```