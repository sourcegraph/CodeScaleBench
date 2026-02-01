```cpp
/**********************************************************************************************
 *  MosaicBoard Studio – Example Data Chart Plugin
 *
 *  File:        plugins/example_data_chart/plugin_entry.cpp
 *  Description: Entry-point for the “ExampleDataChart” plugin.  The plugin registers a single
 *               tile type capable of visualising a live data stream as a line chart.
 *
 *  Notes:
 *      – All symbols intended to be visible outside of this translation unit are explicitly
 *        marked with MOSAIC_PLUGIN_API and are wrapped in `extern "C"` to guarantee a stable
 *        C ABI for the dynamic-loader.
 *      – The plugin makes heavy use of the core framework’s facilities (event-bus, JSON
 *        serialisation helpers, logging, etc.).  It therefore depends on the following public
 *        headers provided by MosaicBoard Studio:
 *
 *              <mosaic/plugin_api.hpp>
 *              <mosaic/event_bus.hpp>
 *              <mosaic/tile_base.hpp>
 *              <mosaic/log.hpp>
 *              <mosaic/json.hpp>         (nlohmann::json wrapper)
 *
 *  Copyright:
 *      © 2023-2024 MosaicBoard Studio authors.  Licensed under the Apache-2.0 licence.
 *********************************************************************************************/

#include <mosaic/plugin_api.hpp>
#include <mosaic/event_bus.hpp>
#include <mosaic/tile_base.hpp>
#include <mosaic/log.hpp>
#include <mosaic/json.hpp>

#include <atomic>
#include <memory>
#include <shared_mutex>
#include <utility>
#include <vector>
#include <string>
#include <deque>
#include <chrono>

/*================================================================================================
 *  Forward declarations – keep compile times low by avoiding unnecessary includes.
 *==============================================================================================*/

namespace mosaic
{
    class PluginHost;
    class DataPacket;
}

/*================================================================================================
 *  Internal helpers
 *==============================================================================================*/

namespace
{
    using json          = mosaic::json;
    using Timestamp     = std::chrono::time_point<std::chrono::system_clock>;
    using Duration      = std::chrono::duration<double, std::milli>;

    struct TimedValue
    {
        Timestamp stamp;
        double    value;
    };

    // Maximum number of data points kept in memory per tile
    constexpr std::size_t kMaxSamples = 1'024;
}

/*================================================================================================
 *  ExampleDataChartTile – Concrete implementation of a live-updating chart.
 *==============================================================================================*/

class ExampleDataChartTile final : public mosaic::TileBase
{
public:
    explicit ExampleDataChartTile(const json& initialConfig,
                                  mosaic::PluginHost& host) :
        TileBase { "ExampleDataChartTile", host },
        m_config { initialConfig }
    {
        validateConfig(m_config);
        subscribe();
        mosaic::log::debug("[ExampleDataChartTile] Created with endpoint: {}",
                           m_config.at("endpoint").get<std::string>());
    }

    ~ExampleDataChartTile() noexcept override
    {
        try
        {
            unsubscribe();
        }
        catch (const std::exception& ex)
        {
            // Make sure we never throw from a destructor, but log the problem.
            mosaic::log::error("[ExampleDataChartTile] Unsubscribe failed: {}", ex.what());
        }
    }

    void onRender(mosaic::RenderContext& ctx) override
    {
        // Thread-safe snapshot of the current sample vector.
        std::deque<TimedValue> samplesCopy;
        {
            std::shared_lock lock { m_samplesMutex };
            samplesCopy = m_samples; // copy
        }

        // Convert the sample vector into JSON and hand it off to the frontend.
        json payload;
        payload["series"] = json::array();
        for (const auto& tv : samplesCopy)
        {
            payload["series"].emplace_back(json{
                { "t", std::chrono::duration_cast<std::chrono::milliseconds>(tv.stamp.time_since_epoch()).count() },
                { "v", tv.value }
            });
        }

        ctx.sendJson(payload);
    }

    void onConfigurationChanged(const json& newConfig) override
    {
        validateConfig(newConfig);

        bool endpointChanged = newConfig.at("endpoint").get<std::string>() !=
                               m_config.at("endpoint").get<std::string>();

        m_config = newConfig;

        if (endpointChanged)
        {
            unsubscribe();
            subscribe();
            mosaic::log::info("[ExampleDataChartTile] Endpoint updated to {}",
                              m_config.at("endpoint").get<std::string>());
        }
    }

private:
    /*--------------------------------------------------------------------------------------------
     *  Event-bus subscription handling
     *------------------------------------------------------------------------------------------*/
    void subscribe()
    {
        const std::string endpoint = m_config.at("endpoint").get<std::string>();

        m_subscriptionToken = host().eventBus().subscribe(
            endpoint,                                            // topic
            [this](const mosaic::DataPacket& pkt) noexcept       // callback
            {
                handleData(pkt);
            });

        if (!m_subscriptionToken)
        {
            throw std::runtime_error("Failed to subscribe to endpoint: " + endpoint);
        }
    }

    void unsubscribe()
    {
        if (m_subscriptionToken)
        {
            host().eventBus().unsubscribe(m_subscriptionToken);
            m_subscriptionToken = {};
        }
    }

    /*--------------------------------------------------------------------------------------------
     *  Incoming data processing
     *------------------------------------------------------------------------------------------*/
    void handleData(const mosaic::DataPacket& pkt)
    {
        // The DataPacket is expected to carry a double value in its payload.
        double newValue = 0.0;

        try
        {
            newValue = pkt.payload().at("value").get<double>();
        }
        catch (const std::exception& ex)
        {
            mosaic::log::warn("[ExampleDataChartTile] Data parse error: {}", ex.what());
            return;     // ignore malformed packet
        }

        const auto   stamp = std::chrono::system_clock::now();
        TimedValue   tv { stamp, newValue };

        {
            std::unique_lock lock { m_samplesMutex };

            m_samples.emplace_back(std::move(tv));
            if (m_samples.size() > kMaxSamples)
            {
                m_samples.pop_front();
            }
        }

        // Trigger a re-render on the UI thread (debounced inside framework).
        host().requestRender(*this);
    }

    /*--------------------------------------------------------------------------------------------
     *  Configuration validation
     *------------------------------------------------------------------------------------------*/
    static void validateConfig(const json& cfg)
    {
        if (!cfg.contains("endpoint") || !cfg["endpoint"].is_string())
        {
            throw std::invalid_argument(
                "[ExampleDataChartTile] Mandatory string field `endpoint` missing in config.");
        }
    }

    /*--------------------------------------------------------------------------------------------
     *  Fields
     *------------------------------------------------------------------------------------------*/
    json                                  m_config;
    std::deque<TimedValue>                m_samples;
    mutable std::shared_mutex             m_samplesMutex;

    mosaic::SubscriptionToken             m_subscriptionToken;
};

/*================================================================================================
 *  ExampleDataChartPlugin – Registers the tile with the framework.
 *==============================================================================================*/

class ExampleDataChartPlugin final : public mosaic::Plugin
{
public:
    explicit ExampleDataChartPlugin(mosaic::PluginHost& host) :
        m_host { host }
    {
        // Register the tile factory with the host as soon as we are constructed.
        m_factoryId = m_host.registerTileFactory(
            "example_data_chart",
            [this](const mosaic::json& cfg) -> std::unique_ptr<mosaic::Tile>
            {
                return std::make_unique<ExampleDataChartTile>(cfg, m_host);
            });

        if (!m_factoryId)
        {
            throw std::runtime_error("Unable to register tile factory for ExampleDataChartPlugin");
        }

        mosaic::log::info("[ExampleDataChartPlugin] Tile factory registered (id={})", m_factoryId);
    }

    ~ExampleDataChartPlugin() noexcept override
    {
        try
        {
            if (m_factoryId)
            {
                m_host.unregisterTileFactory(m_factoryId);
            }
        }
        catch (const std::exception& ex)
        {
            mosaic::log::error("[ExampleDataChartPlugin] Failed to unregister factory: {}", ex.what());
        }
    }

    mosaic::string_view name()   const noexcept override { return "Example Data Chart"; }
    mosaic::string_view vendor() const noexcept override { return "MosaicBoard Studio"; }
    mosaic::string_view version()const noexcept override { return "1.1.0"; }

private:
    mosaic::PluginHost&  m_host;
    mosaic::FactoryId    m_factoryId {};
};

/*================================================================================================
 *  Shared-library entry points – C ABI
 *==============================================================================================*/

extern "C"
{
    MOSAIC_PLUGIN_API mosaic::Plugin* create_plugin(mosaic::PluginHost& host)
    {
        try
        {
            return new ExampleDataChartPlugin { host };
        }
        catch (const std::exception& ex)
        {
            mosaic::log::error("[ExampleDataChart] create_plugin() failed: {}", ex.what());
            return nullptr;
        }
    }

    MOSAIC_PLUGIN_API void destroy_plugin(mosaic::Plugin* plugin)
    {
        delete plugin;
    }
}
```