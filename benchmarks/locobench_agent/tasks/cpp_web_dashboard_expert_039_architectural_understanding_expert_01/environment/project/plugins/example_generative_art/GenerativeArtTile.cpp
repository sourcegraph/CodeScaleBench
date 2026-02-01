```cpp
/******************************************************************************************
 *  File:      MosaicBoardStudio/plugins/example_generative_art/GenerativeArtTile.cpp
 *  Project:   MosaicBoard Studio (web_dashboard)
 *
 *  Description:
 *      Example “Generative Art” tile that renders a continuously-evolving piece of
 *      algorithmic artwork.  The tile is hot-swappable at runtime and illustrates
 *      how a plugin can:
 *          • Receive configuration from the dashboard
 *          • Subscribe to live events via the global event-bus
 *          • Produce RGBA pixel data each frame
 *          • Expose a C-ABI factory for the host to load/unload the shared library
 *
 *  The implementation purposefully avoids external dependencies (other than the core
 *  SDK) so that the file can be dropped into the plugin directory and built in a
 *  default C++17 tool-chain.
 *
 *  Author:    Example Developer <dev@example.com>
 ******************************************************************************************/

#include <cmath>
#include <cstdint>
#include <chrono>
#include <mutex>
#include <random>
#include <string>
#include <vector>

// 3rd-party; bundled with MosaicBoard Studio SDK
#include <nlohmann/json.hpp>  // MIT-licensed single-header JSON parser

// MosaicBoard Studio core SDK
#include "MosaicSDK.hpp"  // ← Provides ITile, IRenderer, EventBus, Logging utilities, etc.

//-------------------------------------------------------------------------------------------------
// Forward declarations (defined at bottom for C linkage)
//-------------------------------------------------------------------------------------------------
extern "C" MOSAIC_PLUGIN_API Mosaic::ITile* createTile();
extern "C" MOSAIC_PLUGIN_API void          destroyTile(Mosaic::ITile* tile);

//-------------------------------------------------------------------------------------------------
// GenerativeArtTile – concrete implementation of ITile
//-------------------------------------------------------------------------------------------------
class GenerativeArtTile final
    : public Mosaic::ITile                // Main interface the dashboard relies on
    , public Mosaic::IEventSubscriber     // Enables subscription to EventBus topics
{
public:
    GenerativeArtTile();
    ~GenerativeArtTile() override;

    // ITile interface ---------------------------------------------------------
    const char*          id()       const noexcept override { return "example.generative_art"; }
    const char*          name()     const noexcept override { return "Generative Art (Example)"; }
    const char*          version()  const noexcept override { return "1.0.0"; }

    bool init(const Mosaic::TileInitContext& ictx) override;
    void shutdown() override;

    void onConfiguration(const nlohmann::json& cfg) override;
    void onResize(uint32_t width, uint32_t height) override;

    // Called once per render frame on the render thread
    void update(double dt) override;
    void render(Mosaic::IRenderer& renderer) override;

    // IEventSubscriber interface ---------------------------------------------
    void onEvent(const Mosaic::Event& evt) noexcept override;

private:
    // Internal helpers --------------------------------------------------------
    void               regeneratePalette();
    uint32_t           samplePalette(float t) const;
    float              pseudoNoise(float x, float y) const;
    void               generateFrame(double time);

    // State -------------------------------------------------------------------
    struct Config
    {
        bool      reactToAudio = false;
        double    speed        = 0.25;      // Movement speed multiplier
        uint32_t  palette[5]   = {};        // 5-color palette (sRGBA 8-bit)
        int       seed         = 1337;      // RNG seed
    };

    Config                          m_cfg;
    uint32_t                        m_width         = 0;
    uint32_t                        m_height        = 0;
    std::vector<uint32_t>           m_pixelBuffer;              // sRGBA 8-8-8-8
    std::mutex                      m_bufferMutex;              // Protects m_pixelBuffer
    std::mt19937                    m_rng;                      // For palette generation
    std::uniform_real_distribution<float> m_01 { 0.f, 1.f };

    double                          m_elapsedTime   = 0.0;      // Seconds since init()
    float                           m_audioLevel    = 0.f;      // Last audio amplitude (0..1)

    Mosaic::EventBus*               m_eventBus      = nullptr;  // Not owned
};

//=================================================================================================
//  Constructor / Destructor
//=================================================================================================
GenerativeArtTile::GenerativeArtTile()
{
    // Set a deterministic seed until config is parsed
    m_rng.seed(m_cfg.seed);
    regeneratePalette();
}

GenerativeArtTile::~GenerativeArtTile() = default;

//=================================================================================================
//  ITile – initialization / shutdown
//=================================================================================================
bool GenerativeArtTile::init(const Mosaic::TileInitContext& ictx)
{
    MOSAIC_LOG_INFO("[GenerativeArtTile] Initializing...");

    m_eventBus = ictx.eventBus;
    if (!m_eventBus)
    {
        MOSAIC_LOG_ERROR("[GenerativeArtTile] EventBus unavailable – cannot continue.");
        return false;
    }

    // Subscribe to audio spectrum events if desired
    m_eventBus->subscribe("audio.spectrum", this);

    // Initial size provided by host
    onResize(ictx.initialWidth, ictx.initialHeight);

    m_elapsedTime = 0.0;
    return true;
}

void GenerativeArtTile::shutdown()
{
    MOSAIC_LOG_INFO("[GenerativeArtTile] Shutting down...");
    if (m_eventBus)
    {
        m_eventBus->unsubscribe("audio.spectrum", this);
        m_eventBus = nullptr;
    }
    std::lock_guard<std::mutex> lock(m_bufferMutex);
    m_pixelBuffer.clear();
}

//=================================================================================================
//  Configuration & Resize
//=================================================================================================
void GenerativeArtTile::onConfiguration(const nlohmann::json& cfg)
{
    MOSAIC_LOG_DEBUG("[GenerativeArtTile] Applying configuration: {}", cfg.dump());

    // Defensive parsing (with fallback to defaults)
    try
    {
        if (cfg.contains("reactToAudio"))
            m_cfg.reactToAudio = cfg.at("reactToAudio").get<bool>();

        if (cfg.contains("speed"))
            m_cfg.speed = std::clamp(cfg.at("speed").get<double>(), 0.05, 3.0);

        if (cfg.contains("seed"))
        {
            m_cfg.seed = cfg.at("seed").get<int>();
            m_rng.seed(static_cast<uint32_t>(m_cfg.seed));
        }

        if (cfg.contains("palette") && cfg.at("palette").is_array() &&
            cfg.at("palette").size() == 5)
        {
            for (size_t i = 0; i < 5; ++i)
                m_cfg.palette[i] = cfg.at("palette")[i].get<uint32_t>();
        }
        else
        {
            regeneratePalette();
        }
    }
    catch (const std::exception& ex)
    {
        MOSAIC_LOG_WARN("[GenerativeArtTile] Failed to parse configuration: {}", ex.what());
    }
}

void GenerativeArtTile::onResize(uint32_t width, uint32_t height)
{
    std::lock_guard<std::mutex> lock(m_bufferMutex);
    m_width       = std::max(1u, width);
    m_height      = std::max(1u, height);
    m_pixelBuffer.assign(static_cast<size_t>(m_width) * m_height, 0xFF000000); // opaque black
    MOSAIC_LOG_INFO("[GenerativeArtTile] Resized to {}×{}", m_width, m_height);
}

//=================================================================================================
//  Update & Render
//=================================================================================================
void GenerativeArtTile::update(double dt)
{
    m_elapsedTime += dt;
    generateFrame(m_elapsedTime);
}

void GenerativeArtTile::render(Mosaic::IRenderer& renderer)
{
    std::lock_guard<std::mutex> lock(m_bufferMutex);
    renderer.blitRGBA32(m_pixelBuffer.data(), m_width, m_height);
}

//=================================================================================================
//  Event handling
//=================================================================================================
void GenerativeArtTile::onEvent(const Mosaic::Event& evt) noexcept
{
    if (!m_cfg.reactToAudio) return;

    if (evt.channel == "audio.spectrum")
    {
        try
        {
            // Expecting JSON payload: { "rms": float, "bands": [float...] }
            float rms = evt.payload.at("rms").get<float>();
            m_audioLevel = std::clamp(rms, 0.f, 1.f);
        }
        catch (...)
        {
            // Swallow errors; malformed audio packet
        }
    }
}

//=================================================================================================
//  Internal helpers
//=================================================================================================
void GenerativeArtTile::regeneratePalette()
{
    // Simple hue-based palette generator
    for (uint32_t& col : m_cfg.palette)
    {
        float h = m_01(m_rng);            // Hue [0,1]
        float s = 0.6f + 0.35f * m_01(m_rng); // Saturation
        float v = 0.7f + 0.3f  * m_01(m_rng); // Value

        // Convert HSV→RGB (sRGB)
        float r, g, b;
        int   hi = static_cast<int>(h * 6.f);
        float f  = h * 6.f - hi;
        float p  = v * (1.f - s);
        float q  = v * (1.f - f * s);
        float t  = v * (1.f - (1.f - f) * s);

        switch (hi % 6)
        {
            case 0: r=v; g=t; b=p; break;
            case 1: r=q; g=v; b=p; break;
            case 2: r=p; g=v; b=t; break;
            case 3: r=p; g=q; b=v; break;
            case 4: r=t; g=p; b=v; break;
            case 5: r=v; g=p; b=q; break;
            default: r=g=b=0; break;
        }

        auto to8 = [](float c){ return static_cast<uint32_t>(std::round(c * 255.f)); };
        col = 0xFF000000
              | (to8(r) << 16)
              | (to8(g) << 8)
              | (to8(b));
    }
}

uint32_t GenerativeArtTile::samplePalette(float t) const
{
    // Quintic interpolation across 5-color palette
    t = std::clamp(t, 0.f, 1.f);
    float pos    = t * 4.f;
    int   idx    = static_cast<int>(pos);
    float frac   = pos - idx;

    uint32_t c1  = m_cfg.palette[idx];
    uint32_t c2  = m_cfg.palette[std::min(4, idx + 1)];

    auto lerp8 = [&](uint32_t a, uint32_t b, float f) -> uint8_t
    {
        return static_cast<uint8_t>(std::round(
            (1.f - f) * static_cast<float>((a & 0xFF)) +
            f          * static_cast<float>((b & 0xFF))
        ));
    };

    uint8_t r = lerp8((c1 >> 16) & 0xFF, (c2 >> 16) & 0xFF, frac);
    uint8_t g = lerp8((c1 >>  8) & 0xFF, (c2 >>  8) & 0xFF, frac);
    uint8_t b = lerp8((c1 >>  0) & 0xFF, (c2 >>  0) & 0xFF, frac);

    return 0xFF000000 | (r << 16) | (g << 8) | b;
}

// Very cheap pseudo-noise; good enough for hypnotic visuals
float GenerativeArtTile::pseudoNoise(float x, float y) const
{
    return 0.5f + 0.5f * std::sin(x * 2.1f + 0.3f * std::cos(y) + 0.35f * std::sin(x + y));
}

void GenerativeArtTile::generateFrame(double time)
{
    const double speed      = m_cfg.speed;
    const double t          = time * speed;
    const float  audioBoost = m_cfg.reactToAudio ? (0.3f + 0.7f * m_audioLevel) : 1.f;

    const float  scaleX     = 3.25f / static_cast<float>(m_width);
    const float  scaleY     = 3.25f / static_cast<float>(m_height);

    std::lock_guard<std::mutex> lock(m_bufferMutex);

    uint32_t* dst = m_pixelBuffer.data();
    for (uint32_t y = 0; y < m_height; ++y)
    {
        for (uint32_t x = 0; x < m_width; ++x, ++dst)
        {
            float nx = (x - m_width  * 0.5f) * scaleX;
            float ny = (y - m_height * 0.5f) * scaleY;

            float n  = pseudoNoise(nx + t * 0.5f, ny - t * 0.4f);
            n        = std::pow(n, 1.5f) * audioBoost;          // Amplify lights
            uint32_t col = samplePalette(n);
            *dst = col;
        }
    }
}

//=================================================================================================
//  C-ABI factory – required for dynamic loading
//=================================================================================================
extern "C" MOSAIC_PLUGIN_API Mosaic::ITile* createTile()
{
    try
    {
        return new GenerativeArtTile();
    }
    catch (const std::exception& ex)
    {
        MOSAIC_LOG_ERROR("[GenerativeArtTile] Failed to create instance: {}", ex.what());
        return nullptr;
    }
}

extern "C" MOSAIC_PLUGIN_API void destroyTile(Mosaic::ITile* tile)
{
    delete tile;
}
```