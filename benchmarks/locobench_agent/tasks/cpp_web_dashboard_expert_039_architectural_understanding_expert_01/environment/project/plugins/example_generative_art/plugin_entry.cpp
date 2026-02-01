```cpp
/***************************************************************************************************
 * File:    plugin_entry.cpp
 * Project: MosaicBoard Studio – Example Generative-Art Tile
 *
 * Copyright (c) 2024
 * Author:  MosaicBoard Studio Contributors
 *
 * Description:
 * ------------
 * This shared-library acts as the entry-point for the “example_generative_art” plugin.  It exposes
 * a single “GenerativeArtTile” that procedurally generates SVG artwork in real-time and publishes
 * state changes through the global event-bus.  The plugin is discovered at runtime by the
 * PluginRegistry and can be hot-swapped without restarting the host application.
 *
 * Key responsibilities:
 *   • Provide a concrete Tile implementation (GenerativeArtTile).
 *   • Register the tile with the core PluginRegistry.
 *   • Gracefully handle configuration, runtime errors, and version mismatches.
 *
 **************************************************************************************************/

// ──────────────────────────────────────────────────────
// System / standard-library headers
// ──────────────────────────────────────────────────────
#include <cmath>
#include <chrono>
#include <cstdint>
#include <exception>
#include <memory>
#include <random>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

// ──────────────────────────────────────────────────────
// Third-party headers
// ──────────────────────────────────────────────────────
#include <nlohmann/json.hpp>  // https://github.com/nlohmann/json

// ──────────────────────────────────────────────────────
// MosaicBoard Studio SDK headers
// ──────────────────────────────────────────────────────
#include <mbs/core/BuildConfig.hpp>       // Contains cross-platform export macros.
#include <mbs/core/EventBus.hpp>          // Real-time intra-process event bus.
#include <mbs/core/Logger.hpp>            // Lightweight structured logger.
#include <mbs/core/Tile.hpp>              // Base class every plug-in tile must implement.
#include <mbs/core/Version.hpp>           // Semantic versioning utilities.
#include <mbs/plugin/PluginRegistry.hpp>  // Host-application plug-in registry.

// ──────────────────────────────────────────────────────
// Convenience using-declarations
// ──────────────────────────────────────────────────────
using json          = nlohmann::json;
using Event         = mbs::core::Event;
using EventBus      = mbs::core::EventBus;
using Version       = mbs::core::Version;
using Logger        = mbs::core::Logger;
using Severity      = mbs::core::Severity;
using Tile          = mbs::core::Tile;
using TilePtr       = std::unique_ptr<Tile>;
using HighResClock  = std::chrono::high_resolution_clock;
using Milliseconds  = std::chrono::milliseconds;

namespace mbs::plugins::generative_art
{
// =================================================================================================
// Internal helpers – lightweight 1-D value noise implementation
// =================================================================================================
namespace
{
class ValueNoise
{
public:
    explicit ValueNoise(std::uint32_t seed = std::random_device{}())
        : m_seed(seed),
          m_distribution(0.0f, 1.0f)
    {
        m_rng.seed(m_seed);
    }

    // Generates smooth pseudo-random value between 0 and 1 for a given position.
    // Uses simple linear interpolation of two hashed lattice points.
    float operator()(float x)
    {
        const int   xi0 = static_cast<int>(std::floor(x));
        const int   xi1 = xi0 + 1;
        const float xf  = x - static_cast<float>(xi0);

        const float v0 = lattice(xi0);
        const float v1 = lattice(xi1);

        // Smoothstep interpolation
        const float t  = xf * xf * (3.f - 2.f * xf);
        return lerp(v0, v1, t);
    }

private:
    float lattice(int xi)
    {
        std::mt19937 rng(static_cast<std::uint32_t>(xi) ^ m_seed);
        return m_distribution(rng);
    }

    static float lerp(float a, float b, float t) { return a + (b - a) * t; }

    std::uint32_t                     m_seed;
    std::mt19937                      m_rng;
    std::uniform_real_distribution<float> m_distribution;
};
} // anonymous-namespace

// =================================================================================================
// GenerativeArtTile – concrete plug-in tile
// =================================================================================================
class GenerativeArtTile final : public Tile
{
public:
    GenerativeArtTile()
        : m_logger(Logger::acquire("GenerativeArtTile")),
          m_eventBus(EventBus::instance()),
          m_rng(std::random_device{}()),
          m_colourDist(0, 255)
    {
        m_logger->info("GenerativeArtTile instantiated.");
    }

    ~GenerativeArtTile() noexcept override
    {
        m_logger->info("GenerativeArtTile destroyed.");
    }

    // ---------------------------------------------------------------------------------------------
    // Tile lifecycle
    // ---------------------------------------------------------------------------------------------
    void prepare(const json& config) override
    {
        // Parse configuration with fallback values.
        try
        {
            m_width       = config.value("width",  800);
            m_height      = config.value("height", 600);
            m_seed        = config.value("seed",  static_cast<std::uint32_t>(std::random_device{}()));
            m_frameRate   = config.value("fps",   30);
            m_paletteName = config.value("palette", "default");

            m_valueNoise  = std::make_unique<ValueNoise>(m_seed);

            m_logger->info("Tile prepared – size = {}x{}, fps = {}, seed = {}, palette = {}",
                           m_width, m_height, m_frameRate, m_seed, m_paletteName);
        }
        catch (const std::exception& ex)
        {
            m_logger->error("Failed to parse configuration: {}", ex.what());
            throw;  // Rethrow – host is responsible for bubbling up initialization failures.
        }
    }

    json render() override
    {
        // Build an SVG string on the fly.
        const auto startTime = HighResClock::now();

        std::ostringstream oss;
        oss << "<svg xmlns='http://www.w3.org/2000/svg' width='" << m_width
            << "' height='" << m_height << "' viewBox='0 0 " << m_width << " " << m_height << "'>";
        oss << "<rect width='100%' height='100%' fill='black'/>";

        const std::size_t lines = 120;
        const float       step  = static_cast<float>(m_width) / static_cast<float>(lines - 1);

        for (std::size_t i = 0; i < lines; ++i)
        {
            const float t  = static_cast<float>(i) / static_cast<float>(lines);
            const float y  = m_height * m_valueNoise->operator()(t * 3.0f);

            const std::uint8_t r = static_cast<std::uint8_t>(m_colourDist(m_rng));
            const std::uint8_t g = static_cast<std::uint8_t>(m_colourDist(m_rng));
            const std::uint8_t b = static_cast<std::uint8_t>(m_colourDist(m_rng));

            oss << "<line x1='" << i * step << "' y1='" << y
                << "' x2='" << (i + 1) * step << "' y2='" << m_height - y
                << "' stroke='rgb(" << static_cast<int>(r) << ","
                                    << static_cast<int>(g) << ","
                                    << static_cast<int>(b) << ")' "
                << "stroke-width='2' stroke-linecap='round'/>";
        }

        oss << "</svg>";

        const auto endTime = HighResClock::now();
        const auto durationMs =
            std::chrono::duration_cast<Milliseconds>(endTime - startTime).count();

        // Publish render-time metric.
        m_eventBus.publish(Event{
            .topic   = "tile.metrics.render_time",
            .payload = json{
                {"tile_id", id()},
                {"duration_ms", durationMs}
            }
        });

        return json{
            {"type", "svg"},
            {"content", oss.str()},
            {"render_time_ms", durationMs}
        };
    }

    void onEvent(const Event& event) override
    {
        if (event.topic == "global.ping")
        {
            m_logger->debug("Responding to global ping – tile_id={}", id());
            m_eventBus.publish(Event{
                .topic   = "tile.pong",
                .payload = json{{"tile_id", id()}}
            });
        }
        else if (event.topic == "tile.control.shuffle_palette" &&
                 event.payload.value("tile_id", id()) == id())
        {
            shufflePalette();
        }
    }

    // ---------------------------------------------------------------------------------------------
    // Metadata
    // ---------------------------------------------------------------------------------------------
    std::string name() const noexcept override   { return "Generative Art Tile"; }
    std::string category() const noexcept override { return "Generative"; }
    Version     version() const noexcept override { return Version{1, 2, 0}; }

private:
    // Randomly changes colour distribution to create a new palette.
    void shufflePalette()
    {
        std::uniform_int_distribution<std::uint32_t> seedDist;
        m_seed = seedDist(m_rng);
        m_valueNoise = std::make_unique<ValueNoise>(m_seed);

        m_logger->info("Palette shuffled – new seed = {}", m_seed);

        m_eventBus.publish(Event{
            .topic   = "tile.state.palette_changed",
            .payload = json{{"tile_id", id()}, {"seed", m_seed}}
        });
    }

    // ---------------------------------------------------------------------------------------------
    // Data members
    // ---------------------------------------------------------------------------------------------
    Logger                         m_logger;
    EventBus&                      m_eventBus;

    // Configurable parameters
    int                            m_width       = 800;
    int                            m_height      = 600;
    std::uint32_t                  m_seed        = 0;
    int                            m_frameRate   = 30;
    std::string                    m_paletteName = "default";

    // Runtime objects
    std::unique_ptr<ValueNoise>    m_valueNoise;
    std::mt19937                   m_rng;
    std::uniform_int_distribution<int> m_colourDist;
};

// =================================================================================================
// Plug-in registration
// =================================================================================================

// Cross-platform export macro (falls back to C linkage)
#ifndef MBS_PLUGIN_API
#   if defined(_WIN32)
#       define MBS_PLUGIN_API extern "C" __declspec(dllexport)
#   else
#       define MBS_PLUGIN_API extern "C" __attribute__((visibility("default")))
#   endif
#endif

// Called automatically by the host when the shared library is loaded.
MBS_PLUGIN_API void register_plugin(mbs::plugin::PluginRegistry& registry)
{
    static const std::string kPluginName = "example_generative_art";
    Logger logger = Logger::acquire("GenerativeArtPluginEntry");

    try
    {
        registry.addPlugin({
            .name        = kPluginName,
            .version     = Version{1, 0, 0},
            .description = "Procedurally generates SVG lines based on value noise.",
            .author      = "MosaicBoard Studio",
            .repository  = "https://github.com/mosaicboard-studio/example_generative_art"
        });

        registry.registerTileFactory(
            kPluginName,
            []() -> TilePtr {
                return std::make_unique<GenerativeArtTile>();
            });

        logger->info("Plugin '{}' registered successfully.", kPluginName);
    }
    catch (const std::exception& ex)
    {
        logger->critical("Failed to register plugin '{}': {}", kPluginName, ex.what());
        throw;  // Fatal – host will unload the shared library.
    }
}

}  // namespace mbs::plugins::generative_art
```