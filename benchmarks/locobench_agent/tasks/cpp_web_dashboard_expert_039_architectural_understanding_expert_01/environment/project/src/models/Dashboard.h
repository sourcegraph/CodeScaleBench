#pragma once
/**
 *  MosaicBoard Studio
 *  File:   MosaicBoardStudio/src/models/Dashboard.h
 *
 *  Description:
 *      Dashboard model object representing a single dashboard session.
 *      Each dashboard is a container of hot-swappable “tiles” (plug-ins)
 *      discovered at runtime. The model is purposely agnostic of any view
 *      technology; it focuses purely on state, behaviour, and (de)serialisation.
 *
 *  Author: MosaicBoard Studio Core Team
 *  License: MIT
 */

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

// External — single-header JSON library (vendored in /third_party)
#include <nlohmann/json.hpp>

#if defined(_WIN32) && defined(MOSAICBOARD_STUDIO_BUILD_SHARED)
    #if defined(MOSAICBOARD_STUDIO_EXPORTS)
        #define MOSAICBOARD_API __declspec(dllexport)
    #else
        #define MOSAICBOARD_API __declspec(dllimport)
    #endif
#else
    #define MOSAICBOARD_API
#endif

namespace mb::core { class EventBus; }       // Forward-declared realtime event bus
namespace mb::plugins { class ITile; }       // Forward-declared tile plugin interface

namespace mb::models
{

/*───────────────────────────────────────────────────────────────────────────*\
|  Custom Exceptions                                                         |
\*───────────────────────────────────────────────────────────────────────────*/
struct DashboardError final : std::runtime_error
{
    using std::runtime_error::runtime_error;
};

/*───────────────────────────────────────────────────────────────────────────*\
|  Dashboard                                                                 |
\*───────────────────────────────────────────────────────────────────────────*/
class MOSAICBOARD_API Dashboard final
{
public:
    using Id        = std::string;
    using Clock     = std::chrono::system_clock;
    using Timestamp = Clock::time_point;

    enum class PersistencePolicy : std::uint8_t
    {
        Transient,   // Lives only in memory; never persisted to DB
        Ephemeral,   // Persisted but TTL-based clean-up by background jobs
        Persistent   // Persisted indefinitely until explicitly removed
    };

    struct Metadata
    {
        std::string                      title;
        std::string                      description;
        std::string                      owner;          // user id / name
        Timestamp                        created_at  = Clock::now();
        Timestamp                        updated_at  = Clock::now();
        std::unordered_set<std::string>  tags;

        bool operator==(const Metadata& rhs) const noexcept
        {
            return title == rhs.title &&
                   description == rhs.description &&
                   owner == rhs.owner &&
                   tags == rhs.tags;
        }
    };

public: /* Construction / Rule-of-5 */
    explicit Dashboard(Id id,
                       Metadata meta                       = {},
                       PersistencePolicy policy            = PersistencePolicy::Persistent);

    // Copy — performs deep copy of tile container but not tile internals
    Dashboard(const Dashboard& other);
    Dashboard& operator=(const Dashboard& rhs);

    // Move
    Dashboard(Dashboard&&) noexcept            = default;
    Dashboard& operator=(Dashboard&&) noexcept = default;

    ~Dashboard() = default;

public: /* Tile management */
    // Adds or replaces a tile. Throws if ptr == nullptr.
    void addTile(std::shared_ptr<plugins::ITile> tile);

    // Removes a tile by ID. Returns true if removed, false if not found.
    bool removeTile(std::string_view tileId);

    // Obtains immutable handle to a tile.
    std::shared_ptr<const plugins::ITile> tile(std::string_view tileId) const;

    // Returns snapshot of all tiles (weak coupling, immutable collection)
    std::vector<std::shared_ptr<const plugins::ITile>> tiles() const;

public: /* Metadata */
    [[nodiscard]] const Metadata& metadata() const noexcept;
    void                           updateMetadata(Metadata newMeta);

public: /* Identification / persistence */
    [[nodiscard]] const Id&            id()      const noexcept { return _id; }
    [[nodiscard]] PersistencePolicy    policy()  const noexcept { return _policy; }

public: /* State helpers */
    // Mark dashboard dirty — will trigger flush through repository layer.
    void markDirty() noexcept;

    // Returns current dirty flag value.
    [[nodiscard]] bool isDirty() const noexcept;

    // Clears dirty flag after successful synchronisation.
    void markClean() noexcept;

public: /* Serialisation */
    nlohmann::json      toJson() const;
    static Dashboard    fromJson(const nlohmann::json& j);

public: /* Event bus helpers */
    // Registers all tiles with given event-bus.
    void bindEventBus(core::EventBus& bus);

    // Detaches tiles (safely ignore if not bound).
    void unbindEventBus(core::EventBus& bus);

private:
    // Helper to clone tiles when copying dashboard.
    static std::unordered_map<std::string, std::shared_ptr<plugins::ITile>>
    cloneTiles(const std::unordered_map<std::string, std::shared_ptr<plugins::ITile>>&);

private:
    mutable std::shared_mutex                                             _mtx;
    Id                                                                    _id;
    Metadata                                                              _meta;
    PersistencePolicy                                                     _policy;
    std::unordered_map<std::string, std::shared_ptr<plugins::ITile>>      _tiles;
    bool                                                                  _dirty {false};
};

/*───────────────────────────────────────────────────────────────────────────*\
|  Inline / Template Implementation                                          |
\*───────────────────────────────────────────────────────────────────────────*/

inline Dashboard::Dashboard(Id id, Metadata meta, PersistencePolicy policy)
    : _id(std::move(id))
    , _meta(std::move(meta))
    , _policy(policy)
{
    if (_id.empty())
        throw DashboardError{"Dashboard ID may not be empty."};
}

inline Dashboard::Dashboard(const Dashboard& other)
{
    std::shared_lock lock(other._mtx);
    _id      = other._id;
    _meta    = other._meta;
    _policy  = other._policy;
    _tiles   = cloneTiles(other._tiles);
    _dirty   = other._dirty;
}

inline Dashboard& Dashboard::operator=(const Dashboard& rhs)
{
    if (this == &rhs) { return *this; }

    // Strong exception-safety: copy into temp then swap
    auto tmp = rhs;             // copy ctor
    {
        std::unique_lock lock(_mtx);
        std::swap(*this, tmp);
    }
    return *this;
}

/* Tile management */
inline void Dashboard::addTile(std::shared_ptr<plugins::ITile> tile)
{
    if (!tile)
        throw DashboardError{"Attempted to add null tile to Dashboard."};

    std::unique_lock lock(_mtx);
    const auto tileId = tile->id();
    _tiles[std::string{tileId}] = std::move(tile);
    _meta.updated_at            = Clock::now();
    _dirty                      = true;
}

inline bool Dashboard::removeTile(std::string_view tileId)
{
    std::unique_lock lock(_mtx);
    auto it = _tiles.find(std::string{tileId});
    if (it == _tiles.end()) return false;

    _tiles.erase(it);
    _meta.updated_at = Clock::now();
    _dirty           = true;
    return true;
}

inline std::shared_ptr<const plugins::ITile>
Dashboard::tile(std::string_view tileId) const
{
    std::shared_lock lock(_mtx);
    auto it = _tiles.find(std::string{tileId});
    if (it == _tiles.end()) return nullptr;
    return it->second;
}

inline std::vector<std::shared_ptr<const plugins::ITile>> Dashboard::tiles() const
{
    std::shared_lock lock(_mtx);
    std::vector<std::shared_ptr<const plugins::ITile>> out;
    out.reserve(_tiles.size());
    for (const auto& [_, t] : _tiles) { out.emplace_back(t); }
    return out;
}

/* Metadata */
inline const Dashboard::Metadata& Dashboard::metadata() const noexcept
{
    std::shared_lock lock(_mtx);
    return _meta;
}

inline void Dashboard::updateMetadata(Metadata newMeta)
{
    std::unique_lock lock(_mtx);
    _meta          = std::move(newMeta);
    _meta.updated_at = Clock::now();
    _dirty         = true;
}

/* State helpers */
inline void Dashboard::markDirty() noexcept
{
    std::unique_lock lock(_mtx);
    _dirty = true;
}

inline bool Dashboard::isDirty() const noexcept
{
    std::shared_lock lock(_mtx);
    return _dirty;
}

inline void Dashboard::markClean() noexcept
{
    std::unique_lock lock(_mtx);
    _dirty = false;
}

/* Serialisation */
inline nlohmann::json Dashboard::toJson() const
{
    std::shared_lock lock(_mtx);
    nlohmann::json j;
    j["id"]      = _id;
    j["policy"]  = static_cast<int>(_policy);
    j["dirty"]   = _dirty;

    j["meta"] = {
        {"title",       _meta.title},
        {"description", _meta.description},
        {"owner",       _meta.owner},
        {"created_at",  std::chrono::duration_cast<std::chrono::milliseconds>(
                        _meta.created_at.time_since_epoch()).count()},
        {"updated_at",  std::chrono::duration_cast<std::chrono::milliseconds>(
                        _meta.updated_at.time_since_epoch()).count()},
        {"tags",        std::vector<std::string>(_meta.tags.begin(), _meta.tags.end())}
    };

    // Delegate tile serialisation to tiles themselves.
    for (const auto& [id, tile] : _tiles)
    {
        j["tiles"].push_back(tile->toJson());
    }

    return j;
}

inline Dashboard Dashboard::fromJson(const nlohmann::json& j)
{
    if (!j.contains("id"))
        throw DashboardError{"Dashboard JSON missing mandatory field 'id'."};

    Metadata meta;
    const auto& jm          = j.at("meta");
    meta.title              = jm.value("title",       "");
    meta.description        = jm.value("description", "");
    meta.owner              = jm.value("owner",       "");
    meta.created_at         = Clock::time_point{std::chrono::milliseconds(
                                jm.value("created_at", 0LL))};
    meta.updated_at         = Clock::time_point{std::chrono::milliseconds(
                                jm.value("updated_at", 0LL))};
    meta.tags.insert(jm.at("tags").begin(), jm.at("tags").end());

    Dashboard dash{ j.at("id").get<std::string>(),
                    std::move(meta),
                    static_cast<PersistencePolicy>(j.value("policy", 0)) };

    if (j.contains("tiles"))
    {
        for (const auto& jt : j.at("tiles"))
        {
            // Plugin-loader will map JSON => ITile at runtime.
            auto tile = plugins::ITile::fromJson(jt); // static factory
            dash.addTile(std::move(tile));
        }
    }

    dash._dirty = j.value("dirty", false);
    return dash;
}

/* Event bus */
inline void Dashboard::bindEventBus(core::EventBus& bus)
{
    std::shared_lock lock(_mtx);
    for (auto& [_, tile] : _tiles)
    {
        tile->subscribe(bus);
    }
}

inline void Dashboard::unbindEventBus(core::EventBus& bus)
{
    std::shared_lock lock(_mtx);
    for (auto& [_, tile] : _tiles)
    {
        tile->unsubscribe(bus);
    }
}

/* static */ inline std::unordered_map<std::string, std::shared_ptr<plugins::ITile>>
Dashboard::cloneTiles(const std::unordered_map<std::string,
                                              std::shared_ptr<plugins::ITile>>& in)
{
    std::unordered_map<std::string, std::shared_ptr<plugins::ITile>> out;
    out.reserve(in.size());
    for (const auto& [id, tile] : in)
    {
        out.emplace(id, tile->clone()); // deep clone via virtual method
    }
    return out;
}

} // namespace mb::models