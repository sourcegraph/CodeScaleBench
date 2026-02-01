```cpp
/**
 * cardio_insight_360/tests/integration/test_full_etl_pipeline.cpp
 *
 * End-to-end integration test that exercises the *complete* ETL path for an
 * ECG signal—from raw HL7 payload ingestion through transformation, storage,
 * and final verification inside the curated lake.
 *
 * The test is written to compile against the *real* CardioInsight360 headers
 * when they are available.  When the full production codebase is not present
 * (e.g., when someone builds this file standalone or inside CI that does not
 * pull the entire monorepo), the test automatically falls back to in-file
 * stubs that mimic the public contracts of the production classes.
 *
 * GoogleTest is used as the test runner.
 */

#include <gtest/gtest.h>

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <random>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

/* ---------- Helper: RAII temporary directory ---------------------------- */

class TempDir
{
public:
    TempDir() : _path(fs::temp_directory_path() / fs::path("ci360_test_XXXXXX"))
    {
        // Create a unique directory
        std::string tmpl = _path.string();
#ifdef _WIN32
        _mktemp_s(&tmpl[0], tmpl.size() + 1);
#else
        mkdtemp(&tmpl[0]);
#endif
        _path = tmpl;
        fs::create_directories(_path);
    }

    ~TempDir()
    {
        std::error_code ec;
        fs::remove_all(_path, ec); // best-effort cleanup
    }

    const fs::path& path() const { return _path; }

private:
    fs::path _path;
};

/* =========================================================================
 *  SECTION: Attempt to include real production headers
 * ========================================================================= */

#if __has_include("ci360/etl/ETLPipeline.hpp") &&                        \
    __has_include("ci360/event/EventBus.hpp") &&                         \
    __has_include("ci360/datalake/DataLakeFacade.hpp") &&                \
    __has_include("ci360/synth/SyntheticSignalGenerator.hpp")

#    define CI360_HAS_PRODUCTION 1
#    include "ci360/etl/ETLPipeline.hpp"
#    include "ci360/event/EventBus.hpp"
#    include "ci360/datalake/DataLakeFacade.hpp"
#    include "ci360/synth/SyntheticSignalGenerator.hpp"

#else

/* =========================================================================
 *  SECTION: Lightweight test doubles for standalone builds
 * ========================================================================= */

#    define CI360_HAS_PRODUCTION 0

namespace ci360
{
    /* --------------- Dumb in-memory EventBus --------------------------- */
    class EventBus
    {
    public:
        using Handler = std::function<void(const std::string&)>;

        void subscribe(const std::string& topic, Handler h)
        {
            std::lock_guard<std::mutex> lk(_m);
            _subs[topic].push_back(std::move(h));
        }

        void publish(const std::string& topic, const std::string& msg)
        {
            std::lock_guard<std::mutex> lk(_m);
            auto it = _subs.find(topic);
            if (it == _subs.end()) return;
            for (auto& h : it->second) h(msg);
        }

    private:
        std::mutex _m;
        std::unordered_map<std::string, std::vector<Handler>> _subs;
    };

    /* --------------- Mock DataLake facade (writes newline-delimited file) */
    class DataLakeFacade
    {
    public:
        explicit DataLakeFacade(fs::path root) : _root(std::move(root))
        {
            fs::create_directories(curated_root());
        }

        fs::path curated_root() const { return _root / "curated"; }

        // Append record to curated store
        void append_record(const std::string& signal_type,
                           const std::string& record)
        {
            fs::path p = curated_root() / (signal_type + ".txt");
            std::ofstream out(p, std::ios::app | std::ios::binary);
            out << record << '\n';
        }

        std::size_t record_count(const std::string& signal_type) const
        {
            fs::path p = curated_root() / (signal_type + ".txt");
            if (!fs::exists(p)) return 0;

            std::ifstream in(p, std::ios::binary);
            std::size_t lines = 0;
            std::string dummy;
            while (std::getline(in, dummy)) ++lines;
            return lines;
        }

    private:
        fs::path _root;
    };

    /* --------------- Minimal ETL pipeline stub ------------------------- */
    class ETLPipeline
    {
    public:
        struct Config
        {
            std::string signal_type = "ECG";
        };

        ETLPipeline(Config cfg, EventBus& bus, DataLakeFacade& lake)
            : _cfg(std::move(cfg)), _bus(bus), _lake(lake)
        {
            _bus.subscribe("raw", [this](const std::string& msg) {
                transform_and_store(msg);
            });
        }

        void start() {}   // no-op
        void stop() {}    // no-op

    private:
        void transform_and_store(const std::string& raw)
        {
            // fake "transformation": reverse the payload
            std::string transformed(raw.rbegin(), raw.rend());
            _lake.append_record(_cfg.signal_type, transformed);
        }

        Config          _cfg;
        EventBus&       _bus;
        DataLakeFacade& _lake;
    };

    /* --------------- Synthetic ECG generator --------------------------- */
    class SyntheticSignalGenerator
    {
    public:
        explicit SyntheticSignalGenerator(std::uint32_t seed = 0)
            : _rnd(seed), _dist(0, 4095)
        {
        }

        std::string next_ecg_waveform()
        {
            std::ostringstream oss;
            oss << "HL7|ECG|";
            for (int i = 0; i < 64; ++i)
            {
                oss << _dist(_rnd);
                if (i + 1 != 64) oss << ',';
            }
            return oss.str();
        }

    private:
        std::mt19937 _rnd;
        std::uniform_int_distribution<int> _dist;
    };

} // namespace ci360
#endif // CI360_HAS_PRODUCTION

/* =========================================================================
 *  SECTION: Test Implementation
 * ========================================================================= */

using namespace std::chrono_literals;

class FullETLPipelineTest : public ::testing::Test
{
protected:
    void SetUp() override
    {
        _tempDir.emplace();
        _lake.emplace(_tempDir->path());

#if CI360_HAS_PRODUCTION
        // Production code may want to load JSON/YAML config; we inline.
        ci360::ETLPipeline::Config cfg;
        cfg.signal_type = "ECG";
#else
        ci360::ETLPipeline::Config cfg;
#endif

        _pipeline.emplace(cfg, _bus, *_lake);
        _pipeline->start();
    }

    void TearDown() override
    {
        _pipeline->stop();
        _pipeline.reset();
        _lake.reset();
        _tempDir.reset();
    }

    // Helper to wait for condition with timeout
    template <typename F>
    void waitFor(F&& predicate, std::chrono::milliseconds timeout) const
    {
        auto start = std::chrono::steady_clock::now();
        while (!predicate())
        {
            if (std::chrono::steady_clock::now() - start > timeout)
                throw std::runtime_error("timeout waiting for condition");
            std::this_thread::sleep_for(50ms);
        }
    }

    // Members
    ci360::EventBus                       _bus;
    std::optional<TempDir>                _tempDir;
    std::optional<ci360::DataLakeFacade>  _lake;
    std::optional<ci360::ETLPipeline>     _pipeline;
};

/* --------------- TEST CASE --------------------------------------------- */

TEST_F(FullETLPipelineTest, ECG_HL7_Message_Goes_Through_Full_Pipeline)
{
    constexpr std::size_t kMessagesToSend = 250;

#if CI360_HAS_PRODUCTION
    ci360::SyntheticSignalGenerator generator(/*seed=*/1234);
#else
    ci360::SyntheticSignalGenerator generator(1234);
#endif

    // Publish raw HL7 messages
    for (std::size_t i = 0; i < kMessagesToSend; ++i)
    {
        _bus.publish("raw", generator.next_ecg_waveform());
    }

    // Wait until everything flushes
    waitFor([this, &kMessagesToSend] {
        return _lake->record_count("ECG") >= kMessagesToSend;
    },
            5s);

    // ---------------------------------------------------------------------
    // ASSERTIONS
    // ---------------------------------------------------------------------
    std::size_t stored = _lake->record_count("ECG");
    EXPECT_GE(stored, kMessagesToSend)
        << "Not all records made it into curated store";

    // Spot-check that the very first record was transformed correctly
    fs::path curated_file =
        _lake->curated_root() / fs::path("ECG.txt");
    std::ifstream in(curated_file);
    ASSERT_TRUE(in) << "Unable to open curated ECG file";

    std::string first_line;
    std::getline(in, first_line);
    ASSERT_FALSE(first_line.empty());

    // Transformation in stub reverses payload; test that property
    // for production pipeline we just check non-empty
#if CI360_HAS_PRODUCTION
    EXPECT_FALSE(first_line.empty());
#else
    std::string reversed_again(first_line.rbegin(), first_line.rend());
    EXPECT_EQ(reversed_again.substr(0, 4), "HL7|") << "Transformation failed";
#endif
}
```