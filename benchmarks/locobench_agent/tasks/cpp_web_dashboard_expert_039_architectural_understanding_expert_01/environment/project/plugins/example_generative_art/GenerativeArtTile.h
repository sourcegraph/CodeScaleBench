#pragma once
/***************************************************************************************************
 *  File:        GenerativeArtTile.h
 *  Project:     MosaicBoard Studio – Example Generative-Art Plugin
 *
 *  Description: Declaration and inline implementation of the GenerativeArtTile component, a
 *               self-contained “tile” that renders GPU-friendly, generative artwork and can react
 *               to both data-bus events and user interaction.  The class follows the run-time
 *               plug-in protocol defined by the MosaicBoard core (ITilePlugin & EventBus::Subscriber)
 *               and is built for hot-reloading and safe multi-threaded rendering.
 *
 *  Copyright:   © 2024 MosaicBoard Studio
 ***************************************************************************************************/
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <random>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

// Forward declarations — provided by MosaicBoard runtime.
namespace mosaic::core
{
    class RenderContext;
    struct Event;
    class ITilePlugin;      // Basic tile interface (lifecycle, identification, rendering, etc.)
    class EventSubscriber;  // Interface for subscribing to the global event bus.
} // namespace mosaic::core

// MSVC requires explicit dllexport; other platforms default to visibility=default.
#if defined(_WIN32) || defined(_WIN64)
    #define MOSAIC_PLUGIN_API __declspec(dllexport)
#else
    #define MOSAIC_PLUGIN_API __attribute__((visibility("default")))
#endif

namespace mosaic::plugins::generative_art
{

/**
 * GenerativeArtTile
 * -----------------
 * A plug-n-play dashboard component that produces procedural visuals by layering
 * shape primitives driven by a configurable PRNG and (optionally) real-time audio spectrum data.
 *
 * Thread Safety:
 *     Rendering is performed on the render thread while event callbacks may arrive on the
 *     bus thread.  Internal state that can be mutated from callbacks is protected by `_mutex`
 *     and the `_dirty` atomic flag schedules lightweight rebuilds without blocking frames.
 */
class MOSAIC_PLUGIN_API GenerativeArtTile final
    : public mosaic::core::ITilePlugin
    , public mosaic::core::EventSubscriber
{
public:
    // -------- Configuration ---------------------------------------------------------------------
    struct Config
    {
        uint32_t                          seed            = 1337u;
        std::size_t                       maxLayers       = 5u;
        bool                              audioReactive   = false;
        std::array<uint32_t, 5>           palette        {{0xFF1abc9c, 0xFFe74c3c, 0xFF9b59b6,
                                                           0xFFf1c40f, 0xFF2ecc71}};
        float                             refreshRateHz   = 30.f;  // Target update frequency.

        static Config fromJson(const nlohmann::json& j)
        {
            Config c;
            if (j.contains("seed"))           c.seed          = j["seed"].get<uint32_t>();
            if (j.contains("maxLayers"))      c.maxLayers     = j["maxLayers"].get<std::size_t>();
            if (j.contains("audioReactive"))  c.audioReactive = j["audioReactive"].get<bool>();
            if (j.contains("refreshRateHz"))  c.refreshRateHz = j["refreshRateHz"].get<float>();

            if (j.contains("palette") && j["palette"].is_array())
            {
                const auto& arr = j["palette"];
                for (std::size_t i = 0; i < c.palette.size() && i < arr.size(); ++i)
                    c.palette[i] = arr[i].get<uint32_t>();
            }
            return c;
        }
    };

    // -------- Construction / Destruction ---------------------------------------------------------
    explicit GenerativeArtTile(const Config& cfg = {}) :
        _dirty   {true},
        _config  {cfg},
        _rng     {cfg.seed},
        _id      {"GenerativeArtTile#" + std::to_string(reinterpret_cast<std::uintptr_t>(this))}
    {
        _lastRenderTs = std::chrono::steady_clock::now();
    }

    ~GenerativeArtTile() override = default;

    // -------- ITilePlugin Overrides --------------------------------------------------------------
    const char* id() const noexcept override { return _id.c_str(); }

    void onLoad() override
    {
        // Register for events we care about (e.g., audio spectrum frames).
        subscribe("*");  // Wild-card subscription; filter inside onEvent().
    }

    void onUnload() override
    {
        // Gracefully detach from the bus.
        unsubscribe("*");
    }

    void render(mosaic::core::RenderContext& ctx,
                std::chrono::milliseconds     deltaMs) override
    {
        using namespace std::chrono;

        // Respect configured refresh rate so we don’t flood the GPU.
        const auto now       = steady_clock::now();
        const auto elapsedMs = duration_cast<milliseconds>(now - _lastRenderTs);

        if (elapsedMs.count() < (1000.0f / _config.refreshRateHz))
            return;

        _lastRenderTs = now;

        // Lazy rebuild if configuration has changed.
        if (_dirty.exchange(false))
        {
            std::lock_guard<std::mutex> lk(_mutex);
            rebuildEngine();
        }

        // Render each layer.
        for (std::size_t i = 0; i < _config.maxLayers; ++i)
            generateLayer(ctx, i);
    }

    // -------- EventSubscriber Override -----------------------------------------------------------
    void onEvent(const mosaic::core::Event& ev) override
    {
        // Lightweight filtering — we only care about AUDIO_FRAME or CONFIG_UPDATE, for example.
        std::lock_guard<std::mutex> lk(_mutex);

        if (ev.type == "AUDIO_FRAME" && _config.audioReactive)
        {
            // Map amplitude to palette rotation (toy example).
            const float amplitude = ev.payload.value("amp", 0.0f);
            std::rotate(_config.palette.begin(),
                        _config.palette.begin() + static_cast<int>(amplitude * 5) % _config.palette.size(),
                        _config.palette.end());
            _dirty.store(true, std::memory_order_relaxed);
        }
        else if (ev.type == "CONFIG_UPDATE")
        {
            try
            {
                updateConfig(Config::fromJson(ev.payload));
            }
            catch (const std::exception& ex)
            {
                // Log but do not throw. We don’t want event thread to die.
                // log::error("GenerativeArtTile configuration error: {}", ex.what());
            }
        }
    }

    // -------- Public API -------------------------------------------------------------------------
    void updateConfig(const Config& newCfg)
    {
        std::lock_guard<std::mutex> lk(_mutex);
        _config        = newCfg;
        _rng.seed(_config.seed);
        _dirty.store(true, std::memory_order_relaxed);
    }

private:
    // -------- Internal Helpers -------------------------------------------------------------------
    void rebuildEngine()
    {
        // Placeholder for more complex GPU pipeline setups.
        // E.g., rebuild vertex buffers, shaders, FBOs according to current cfg.
    }

    uint32_t randomPaletteColor()
    {
        std::uniform_int_distribution<std::size_t> dist(0, _config.palette.size() - 1);
        return _config.palette[dist(_rng)];
    }

    void generateLayer(mosaic::core::RenderContext& ctx, std::size_t layerIdx)
    {
        // Simplified example: draw circles with random positions & sizes.
        std::uniform_real_distribution<float> pos(0.f, 1.f);
        std::uniform_real_distribution<float> radius(0.02f, 0.15f);

        const float  cx     = pos(_rng);
        const float  cy     = pos(_rng);
        const float  r      = radius(_rng);
        const auto   color  = randomPaletteColor();

        // ctx.drawCircleNormalized(cx, cy, r, color, /*blend=*/true);
        (void)ctx; (void)cx; (void)cy; (void)r; (void)color; // Remove when RenderContext is defined.
    }

    // -------- Data Members -----------------------------------------------------------------------
    std::atomic<bool>                   _dirty;
    mutable std::mutex                  _mutex;
    Config                              _config;
    std::mt19937                        _rng;
    std::string                         _id;
    std::chrono::steady_clock::time_point _lastRenderTs;
};

} // namespace mosaic::plugins::generative_art

#undef MOSAIC_PLUGIN_API