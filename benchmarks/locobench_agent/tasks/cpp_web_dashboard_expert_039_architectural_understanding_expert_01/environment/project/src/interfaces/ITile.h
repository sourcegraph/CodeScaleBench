#pragma once
/**************************************************************************************************
 * File:    ITile.h
 * Project: MosaicBoard Studio (web_dashboard)
 *
 * Description:
 *   Public interface definition for a “Tile” plug-in.  Every visual, data, or interaction component
 *   that can be loaded at run-time MUST implement this interface in order to participate in the
 *   dashboard’s live mosaic.  The contract purposefully remains small but expressive enough to
 *   handle real-time updates, event routing, hot-reloading, and state persistence.  The interface
 *   is referenced by the core run-time, the dynamic plug-in loader, and the web-socket event bus.
 *
 *   ‑ 100 % header-only (pure virtual) to guarantee no ABI breakage across shared libraries.
 *   ‑ Uses modern C++ (C++17 and later) idioms and smart pointers.
 *   ‑ Provides a C-style factory macro (DECLARE_MOSAIC_TILE) for DSO/DLL exports.
 *
 * Copyright
 *   © MosaicBoard Studio Contributors.  Licensed under the MIT License.
 **************************************************************************************************/

#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>   // MIT-licensed, de-facto standard JSON for C++.
                               // Forward declarations are insufficient because
                               // we expose JSON in the public interface.

namespace mbs     // mbs = MosaicBoard Studio
{
namespace core
{

//-------------------------------------------------------------------------------------------------
// Forward declarations
//-------------------------------------------------------------------------------------------------
class IEventBus;
class IDataStream;

/**
 * API version that the plug-ins MUST target.  Bump this number any time the binary
 * compatibility of ITile changes.  The loader will refuse to load a shared object
 * compiled against a different version.
 */
constexpr std::uint32_t TILE_API_VERSION = 0x0100;   // 1.0.0

/**
 * Convenience alias for the JSON type used throughout the platform.  Exposed so plug-in authors
 * don’t need to hard-code the third-party namespace in their own code.
 */
using json = nlohmann::json;

/**
 * Simple, POD-style descriptor that is returned by every Tile to advertise its
 * capabilities before being instantiated.
 */
struct TileDescriptor
{
    std::string id;           // Globally unique (e.g. “com.acme.rss_feed”)
    std::string prettyName;   // Human-readable (“Live RSS Feed”)
    std::string version;      // Semantic (“2.3.1”)
    std::string author;       // (“Acme Corp”)
    std::string description;  // Free-form description / marketing copy

    // Capabilities: which optional behaviours does the tile support?
    bool supportsHotReload   {true};
    bool supportsPersistence {true};
    bool supportsTheming     {false};

    // Free-form metadata (icon paths, keywords, etc.)
    json  metadata           {};
};

/**
 * Runtime-generated context object handed to every Tile during construction.
 * (Think of it as “dependency injection light”.)  All pointers are non-owning.
 */
struct TileContext
{
    IEventBus*   eventBus   {nullptr};
    IDataStream* dataStream {nullptr};

    // Arbitrary user configuration supplied by the dashboard composer (may be empty).
    json         configuration {};
};

//-------------------------------------------------------------------------------------------------
// ITile – the pure virtual interface that *all* run-time plug-ins must implement.
//-------------------------------------------------------------------------------------------------
class ITile
{
public:
    // “Rule of zero” – virtual dtor only.  Implementations must be noexcept.
    virtual ~ITile() = default;

    // -------- Identification -------------------------------------------------------------------
    /**
     * Returns the static descriptor that was registered for this Tile.  The information
     * never changes for a given DLL, so the same instance may be safely cached.
     */
    virtual const TileDescriptor& descriptor() const noexcept = 0;

    // -------- Lifecycle ------------------------------------------------------------------------
    /**
     * Called exactly once after construction, giving the Tile a chance to allocate
     * external resources, subscribe to the event bus, etc.
     *
     * Throwing from this method signals that the Tile cannot be started and will
     * result in an automatic unload by the host.
     *
     * @param ctx  Runtime context with service pointers and user configuration.
     */
    virtual void initialize(const TileContext& ctx) = 0;

    /**
     * Called when the dashboard is about to shut down or the user removes the Tile.
     * Must be idempotent and NEVER throw.
     */
    virtual void shutdown() noexcept = 0;

    /**
     * Real-time update tick.  The host guarantees that updates are called from a
     * single thread in chronological order.
     *
     * @param delta  Time elapsed since the previous frame.
     */
    virtual void update(std::chrono::nanoseconds delta) = 0;

    // -------- Rendering / Data Output ----------------------------------------------------------
    /**
     * Render the Tile’s visual (or data) representation into a JSON blob that the
     * web-front-end understands.  The returned value is immediately serialized and sent
     * over the websocket, so avoid heavy objects in the DOM tree.
     *
     * @remarks  Should be side-effect free and may be called concurrently.
     */
    virtual json render() const = 0;

    // -------- Event Handling -------------------------------------------------------------------
    /**
     * Generic event entry point bridging the websocket with the Tile.  Payload is free-form
     * JSON to keep the interface stable even when new event types are introduced.
     *
     * @param eventName  Symbolic identifier (e.g. “pointer_down”, “custom.myEvent”).
     * @param payload    Event specific fields (may be empty object).
     */
    virtual void onEvent(std::string_view eventName, const json& payload) = 0;

    // -------- State Persistence ----------------------------------------------------------------
    /**
     * Serialise the complete, *self-contained* Tile state so that a session can be restored
     * later.  The JSON must not contain runtime references (raw pointers, file handles, ...).
     */
    virtual json saveState() const = 0;

    /**
     * Restore a previously saved state.  A well-behaved Tile validates the schema and
     * throws std::invalid_argument when the blob is malformed.
     */
    virtual void loadState(const json& state) = 0;
};

//-------------------------------------------------------------------------------------------------
// Plug-in export helpers
//-------------------------------------------------------------------------------------------------
/**
 * Tiles are loaded from a shared object and discovered through a C entry point to avoid
 * C++ name mangling issues.  Plug-ins implement factory functions with the following
 * signatures.  Use the helper macro below to avoid boiler-plate.
 */
using TileFactory     = ITile* (*)();                 // createTile()
using TileDeallocator = void   (*)(ITile*) noexcept;  // destroyTile(…)

/**
 * Macro for declaring a concrete Tile implementation in a shared library:
 *
 *    class MyTile : public mbs::core::ITile { … };
 *    DECLARE_MOSAIC_TILE(MyTile)
 */
#define DECLARE_MOSAIC_TILE(TILE_IMPL)                                        \
    extern "C" {                                                              \
        [[maybe_unused]]                                                      \
        ::mbs::core::ITile* createTile()                                      \
        {                                                                     \
            /* The host will call delete via destroyTile() on unload. */      \
            return new TILE_IMPL();                                           \
        }                                                                     \
                                                                              \
        [[maybe_unused]]                                                      \
        void destroyTile(::mbs::core::ITile* ptr) noexcept                    \
        {                                                                     \
            delete ptr;                                                       \
        }                                                                     \
                                                                              \
        [[maybe_unused]]                                                      \
        std::uint32_t tileApiVersion() noexcept                               \
        {                                                                     \
            return ::mbs::core::TILE_API_VERSION;                             \
        }                                                                     \
    }

} // namespace core
} // namespace mbs
