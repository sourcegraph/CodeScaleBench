```cpp
/**********************************************************************************************************************
 * MosaicBoard Studio – DataChartTile
 * File path : plugins/example_data_chart/DataChartTile.cpp
 *
 * A plug-and-play “tile” that subscribes to a numeric data stream, aggregates the latest N points for each series,
 * and publishes a JSON payload that the front-end can render as a real-time line chart.
 *
 *  - Hot-swappable shared object discovered at run-time
 *  - Thread-safe, throttled publishing to avoid front-end saturation
 *  - Simple in-memory cache so identical payloads are not re-broadcast
 *
 * NOTE: Only project-local headers are referenced here; implementation details live elsewhere in the core.
 *********************************************************************************************************************/

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <functional>
#include <map>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

// 3rd-party, header-only
#include <nlohmann/json.hpp>

// Project core
#include "core/Cache.h"
#include "core/DataStream.h"
#include "core/EventBus.h"
#include "core/Logger.h"
#include "core/Tile.h"
#include "core/Timer.h"

using Json = nlohmann::json;

namespace mosaic::plugins::data_chart
{
/**********************************************************************************************************************
 * Helper types
 *********************************************************************************************************************/
constexpr std::size_t DEFAULT_MAX_POINTS     = 250;    // sliding window
constexpr std::chrono::milliseconds THROTTLE = std::chrono::milliseconds(33); // ~30fps

struct Series
{
    std::string          id;
    std::vector<double>  points;
    void push(double value, std::size_t max)
    {
        points.emplace_back(value);
        if (points.size() > max) { points.erase(points.begin()); }
    }
};

/**********************************************************************************************************************
 * DataChartTile
 *********************************************************************************************************************/
class DataChartTile final : public ::core::Tile
{
public:
    DataChartTile()                        = default;
    ~DataChartTile() override              = default;
    DataChartTile(const DataChartTile&)            = delete;
    DataChartTile& operator=(const DataChartTile&) = delete;

    // Tile interface ---------------------------------------------------------
    void initialize(const Json& config) override;
    void shutdown() override;
    std::string id() const noexcept override { return _id; }
    Json        currentState() const override;

private:
    // Internal callbacks
    void onDataPoint(const core::DataPacket& p);
    void publishIfNeeded();
    Json buildPayloadLocked() const;

    // Configuration ----------------------------------------------------------
    std::string                    _id          { "DataChartTile" };
    std::vector<std::string>       _streamKeys;        // e.g. ["cpu_temp","gpu_temp"]
    std::size_t                    _maxPoints   { DEFAULT_MAX_POINTS };

    // Runtime state ----------------------------------------------------------
    mutable std::mutex             _mutex;
    std::map<std::string, Series>  _series;
    std::string                    _lastPayloadHash;   // primitive cache key
    std::atomic<bool>              _alive { false };

    // Core services ----------------------------------------------------------
    core::SubscriptionHandle       _dataSub;
    core::TimerHandle              _throttleTimer;
};


void DataChartTile::initialize(const Json& config)
{
    _alive = true;
    // Parse configuration ------------------------------------------------------------------
    try
    {
        if (config.contains("id"))          { _id = config.at("id").get<std::string>(); }
        if (config.contains("maxPoints"))   { _maxPoints = config.at("maxPoints").get<std::size_t>(); }
        if (config.contains("streamKeys"))  { _streamKeys = config.at("streamKeys").get<std::vector<std::string>>(); }
    }
    catch (const std::exception& ex)
    {
        core::Logger::error("DataChartTile config parse error: {}", ex.what());
        throw; // fails fast – tile will be discarded by plugin loader
    }

    if (_streamKeys.empty())
    {
        core::Logger::warn("DataChartTile '{}' initialized without streamKeys – subscribing to global stream.", _id);
    }

    // Subscribe to data stream -------------------------------------------------------------
    _dataSub = core::DataStream::instance().subscribe(
        [this](const core::DataPacket& pkt) { onDataPoint(pkt); });

    // Throttle publisher – ensures UI updates only every N ms ------------------------------
    _throttleTimer = core::Timer::instance().repeat(
        [this]() { publishIfNeeded(); }, THROTTLE);

    core::Logger::info("DataChartTile '{}' started. Max points: {}", _id, _maxPoints);
}

void DataChartTile::shutdown()
{
    _alive = false;

    // Unregister subscription and timers
    _dataSub.cancel();
    _throttleTimer.cancel();

    // Optional: flush last state
    publishIfNeeded();

    core::Logger::info("DataChartTile '{}' shut down.", _id);
}

void DataChartTile::onDataPoint(const core::DataPacket& p)
{
    // Filter keys if configured
    if (!_streamKeys.empty() && std::find(_streamKeys.begin(), _streamKeys.end(), p.key) == _streamKeys.end())
        return;

    std::lock_guard lock(_mutex);
    auto& series = _series[p.key];         // will default-construct Series
    series.id    = p.key;
    series.push(p.value, _maxPoints);
}

Json DataChartTile::buildPayloadLocked() const
{
    Json out;
    out["id"] = _id;
    out["series"] = Json::array();
    for (const auto& [key, s] : _series)
    {
        Json obj;
        obj["id"]     = key;
        obj["points"] = s.points;
        out["series"].push_back(std::move(obj));
    }
    return out;
}

void DataChartTile::publishIfNeeded()
{
    if (!_alive) return;

    std::string outgoing;
    {
        std::lock_guard lock(_mutex);
        Json payload = buildPayloadLocked();
        outgoing     = payload.dump();
    }

    // Cheap payload change detection
    const std::size_t hash = std::hash<std::string>{}(outgoing);
    if (std::to_string(hash) == _lastPayloadHash) { return; } // identical – skip

    _lastPayloadHash = std::to_string(hash);

    // Broadcast via EventBus (decoupled from UI renderer or network layer)
    core::EventBus::instance().publish(core::Event{
        .topic   = "tile/update",
        .payload = std::move(outgoing)
    });
}

Json DataChartTile::currentState() const
{
    std::lock_guard lock(_mutex);
    return buildPayloadLocked();
}

} // namespace mosaic::plugins::data_chart

/**********************************************************************************************************************
 * Plugin entry points
 *********************************************************************************************************************/
#ifdef _WIN32
    #define MOSAICBOARD_EXPORT __declspec(dllexport)
#else
    #define MOSAICBOARD_EXPORT __attribute__((visibility("default")))
#endif

extern "C"
{
    MOSAICBOARD_EXPORT ::core::Tile* createPlugin()
    {
        try
        {
            return new mosaic::plugins::data_chart::DataChartTile();
        }
        catch (const std::exception& ex)
        {
            core::Logger::error("Failed to create DataChartTile plugin: {}", ex.what());
            return nullptr;
        }
    }

    MOSAICBOARD_EXPORT void destroyPlugin(::core::Tile* tile)
    {
        delete tile;
    }
}
```