#pragma once
/*****************************************************************************************
 * File:   MosaicBoardStudio/plugins/example_data_chart/DataChartTile.h
 * Author: MosaicBoard Studio – Plugin Team
 *
 * MIT License
 *
 * Description:
 *   DataChartTile is a plug-and-play “tile” that fetches time-series data from a REST
 *   endpoint, performs lightweight caching, and publishes the parsed payload to the
 *   dashboard’s real-time event bus.  It demonstrates how to integrate network I/O,
 *   caching, threading, and robust error handling inside the MosaicBoard component
 *   architecture while keeping the tile entirely self-contained and hot-swappable.
 *
 * Usage:
 *   The shared object is discovered at run-time.  The engine calls create_plugin()
 *   to obtain an instance.  Configuration is provided through the TileConfiguration
 *   object, e.g.:
 *
 *     {
 *       "endpoint": "https://api.example.com/v2/metrics",
 *       "refresh_interval_ms": 5000,
 *       "cache_ttl_ms": 15000
 *     }
 *
 *****************************************************************************************/

#include <atomic>
#include <chrono>
#include <future>
#include <mutex>
#include <memory>
#include <optional>
#include <string>
#include <vector>

// Forward declarations of MosaicBoard core types to avoid hefty headers
namespace mosaic::core
{
    struct Event;
    struct TileContext;
    struct TileConfiguration;

    class  TilePlugin;

    namespace http   { class HttpClient;                   }
    namespace cache  { template<typename K, typename V> class TTLCache; }

} // namespace mosaic::core

// Lightweight fwd declaration for nlohmann::json without including full header
#include <nlohmann/json_fwd.hpp>

/*------------------------------------------------------------------------------
 * Symbol-export macro
 *----------------------------------------------------------------------------*/
#ifndef MOSAIC_PLUGIN_API
    #if defined(_WIN32) || defined(__CYGWIN__)
        #define MOSAIC_PLUGIN_API __declspec(dllexport)
    #else
        #define MOSAIC_PLUGIN_API __attribute__((visibility("default")))
    #endif
#endif

namespace mosaic::plugins::example_data_chart
{

/**
 * DataChartTile
 *
 * Responsibilities:
 *   1. Pull JSON data from a remote REST API on a configurable interval.
 *   2. Cache the response to avoid unncessary network traffic.
 *   3. Broadcast “data:update” events to interested subscribers.
 *   4. Surface errors in a user-visible but non-fatal manner.
 *
 * Thread-Safety:
 *   Public methods are invoked by the dashboard runtime and are therefore
 *   expected to be thread-safe.  Mutable shared state is guarded by _cacheMutex
 *   or made atomic where appropriate.
 */
class DataChartTile final : public mosaic::core::TilePlugin,
                            public std::enable_shared_from_this<DataChartTile>
{
public:
    using json         = nlohmann::json;
    using Clock        = std::chrono::steady_clock;
    using Milliseconds = std::chrono::milliseconds;

    /*----------------------------------------------------------------------------
     * Construction / Destruction
     *--------------------------------------------------------------------------*/
    explicit DataChartTile(const mosaic::core::TileConfiguration& cfg);
    ~DataChartTile() override;

    /*----------------------------------------------------------------------------
     * Lifecycle hooks (TilePlugin interface)
     *--------------------------------------------------------------------------*/
    void onInit(const mosaic::core::TileContext& ctx) override;
    void onActivate()   override;
    void onDeactivate() override;
    void onTick()       override;
    void onEvent(const mosaic::core::Event& event) override;

    /*----------------------------------------------------------------------------
     * Factory
     *--------------------------------------------------------------------------*/
    static std::shared_ptr<mosaic::core::TilePlugin>
        create(const mosaic::core::TileConfiguration& cfg);

private:
    /*----------------------------------------------------------------------------
     * Internal helpers
     *--------------------------------------------------------------------------*/
    void                scheduleRefresh();          // Dispatch async worker
    void                fetchDataAsync();           // Worker entry
    [[nodiscard]] std::optional<json>
                        getCachedPayload() const;   // Thread-safe read
    void                commitData(const json& js); // Publish to bus + cache
    void                pushError(const std::string& msg,
                                   const std::error_code& ec = {});

    /*----------------------------------------------------------------------------
     * Domain types
     *--------------------------------------------------------------------------*/
    struct DataPoint
    {
        Clock::time_point timestamp{};
        double            value{0.0};
    };

    /*----------------------------------------------------------------------------
     * Data members
     *--------------------------------------------------------------------------*/
    mosaic::core::TileContext                                       _ctx;
    std::unique_ptr<mosaic::core::http::HttpClient>                 _http;
    std::unique_ptr<mosaic::core::cache::TTLCache<std::string, json>> _cache;

    std::string         _endpoint;
    Milliseconds        _refreshInterval{5000};
    Milliseconds        _cacheTtl{15000};

    std::future<void>   _worker;
    std::atomic_bool    _active{false};

    mutable std::mutex  _cacheMutex;
};

} // namespace mosaic::plugins::example_data_chart

/*------------------------------------------------------------------------------
 * Plugin factory – required C interface
 *----------------------------------------------------------------------------*/
extern "C" MOSAIC_PLUGIN_API
std::shared_ptr<mosaic::core::TilePlugin>
create_plugin(const mosaic::core::TileConfiguration& cfg);
