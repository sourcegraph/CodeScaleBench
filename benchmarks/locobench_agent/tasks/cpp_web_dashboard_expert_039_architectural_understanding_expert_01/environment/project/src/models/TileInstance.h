#pragma once
/**
 * MosaicBoard Studio
 * ------------------
 *  TileInstance.h
 *
 *  A TileInstance represents a single, live instantiation of a tile plugin that
 *  has been loaded into a MosaicBoard dashboard at runtime.  The class is
 *  responsible for:
 *
 *   •  Lifecycle management (Created → Initialized → Active → Suspended → Destroyed)
 *   •  Thread-safe state and configuration handling
 *   •  Runtime introspection utilities for the orchestrator & monitoring tools
 *   •  Bookkeeping for positioning inside the mosaic grid
 *
 *  NOTE: An implementation (.cpp) is intentionally omitted—many functions are
 *        header-only to avoid ABI issues in plugin contexts and to facilitate
 *        fast, in-place compilation. Heavier logic belongs in the .cpp file.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>

#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <boost/uuid/random_generator.hpp>
#include <nlohmann/json.hpp>

namespace mosaic::event
{
    class IEventBus; // Forward declaration to break dependency-cycle.
} // namespace mosaic::event

namespace mosaic::models
{
    //-------------------------------------------------------------------------//
    //  Tile-level Exception Hierarchy
    //-------------------------------------------------------------------------//
    class TileInstanceError : public std::runtime_error
    {
    public:
        explicit TileInstanceError(std::string msg)
            : std::runtime_error(std::move(msg)) {}
    };

    //-------------------------------------------------------------------------//
    //  Lightweight Geometry Helpers
    //-------------------------------------------------------------------------//
    struct GridPosition final
    {
        std::uint32_t row     {0};
        std::uint32_t column  {0};
    };

    struct GridSpan final
    {
        std::uint32_t rows    {1};
        std::uint32_t columns {1};
    };

    //-------------------------------------------------------------------------//
    //  TileInstance Declaration
    //-------------------------------------------------------------------------//
    class TileInstance : public std::enable_shared_from_this<TileInstance>
    {
    public:
        using TileId = boost::uuids::uuid;
        using Clock  = std::chrono::steady_clock;
        using Json   = nlohmann::json;

        enum class LifecycleState : std::uint8_t
        {
            Created     = 0,
            Initialized = 1,
            Active      = 2,
            Suspended   = 3,
            Destroyed   = 4
        };

        // Factory method to enforce shared_ptr construction
        template <typename... Args>
        static std::shared_ptr<TileInstance> create(Args&&... args)
        {
            return std::shared_ptr<TileInstance>(
                new TileInstance(std::forward<Args>(args)...)
            );
        }

        ~TileInstance() noexcept;

        //------------------------------------------------------------------------//
        //  Introspection / Accessors
        //------------------------------------------------------------------------//
        const TileId&          id()              const noexcept { return m_id;               }
        std::string            idString()        const { return boost::uuids::to_string(m_id); }

        const std::string&     pluginName()      const noexcept { return m_pluginName;       }
        const std::string&     pluginVersion()   const noexcept { return m_pluginVersion;    }

        LifecycleState         lifecycleState()  const noexcept { return m_state.load();     }
        GridPosition           position()        const noexcept { return m_position;         }
        GridSpan               span()            const noexcept { return m_span;             }

        Json                   configCopy()      const;
        Json                   stateSnapshot()   const;

        std::chrono::milliseconds uptime() const;

        //------------------------------------------------------------------------//
        //  Lifecycle API ­– thread-safe, idempotent
        //------------------------------------------------------------------------//
        void initialize();
        void activate();
        void suspend();
        void destroy();

        //------------------------------------------------------------------------//
        //  Configuration / State Management
        //------------------------------------------------------------------------//
        void updateConfig(Json newCfg);
        void mergePartialConfig(const Json& delta);
        void publishState(Json newState);

        //------------------------------------------------------------------------//
        //  Event-Bus Convenience Helpers
        //------------------------------------------------------------------------//
        void subscribe(const std::string& topic);
        void unsubscribe(const std::string& topic);

        bool isSubscribed(const std::string_view topic) const;

    private:
        // Only factory may instantiate
        explicit TileInstance(std::string  pluginName,
                              std::string  pluginVersion,
                              GridPosition position,
                              GridSpan     span,
                              Json         userConfig,
                              mosaic::event::IEventBus& eventBus);

        // Internal helpers
        void transitionTo(LifecycleState next);
        void assertState(LifecycleState expected, std::string_view caller) const;

        //------------------------------------------------------------------------//
        //  Data Members
        //------------------------------------------------------------------------//
        const TileId                m_id { boost::uuids::random_generator()() };

        std::string                 m_pluginName;
        std::string                 m_pluginVersion;

        std::atomic<LifecycleState> m_state { LifecycleState::Created };

        GridPosition                m_position;
        GridSpan                    m_span;

        Json                        m_configuration;
        Json                        m_runtimeState;

        mosaic::event::IEventBus&   m_eventBus;

        Clock::time_point           m_createdAt { Clock::now() };

        // Guard mutable members for multi-threaded access
        mutable std::mutex          m_mutex;

        // Cached subscriptions for quick lookup
        std::unordered_set<std::string> m_subscriptions;
    };

    //=========================================================================//
    //  Inline Implementations
    //=========================================================================//
    inline TileInstance::TileInstance(std::string  pluginName,
                                      std::string  pluginVersion,
                                      GridPosition position,
                                      GridSpan     span,
                                      Json         userConfig,
                                      mosaic::event::IEventBus& eventBus)
        : m_pluginName(std::move(pluginName))
        , m_pluginVersion(std::move(pluginVersion))
        , m_position(position)
        , m_span(span)
        , m_configuration(std::move(userConfig))
        , m_eventBus(eventBus)
    {
        // Nothing else—heavy lifting deferred to initialize()
    }

    inline TileInstance::~TileInstance() noexcept
    {
        try
        {
            if (m_state.load() != LifecycleState::Destroyed)
            {
                destroy();
            }
        }
        catch (...) { /* swallow in destructor */ }
    }

    inline void TileInstance::assertState(LifecycleState expected,
                                          std::string_view caller) const
    {
        if (m_state.load() != expected)
        {
            throw TileInstanceError{
                std::string(caller) + ": invalid lifecycle state transition."
            };
        }
    }

    inline void TileInstance::transitionTo(LifecycleState next)
    {
        m_state.store(next);
    }

    //------------------------------------------------------------------------//
    //  Thread-safe Getters
    //------------------------------------------------------------------------//
    inline TileInstance::Json TileInstance::configCopy() const
    {
        std::scoped_lock lock{m_mutex};
        return m_configuration;
    }

    inline TileInstance::Json TileInstance::stateSnapshot() const
    {
        std::scoped_lock lock{m_mutex};
        return m_runtimeState;
    }

    inline std::chrono::milliseconds TileInstance::uptime() const
    {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            Clock::now() - m_createdAt
        );
    }

    //------------------------------------------------------------------------//
    //  Lifecycle Functions
    //------------------------------------------------------------------------//
    inline void TileInstance::initialize()
    {
        std::scoped_lock lock{m_mutex};
        assertState(LifecycleState::Created, "initialize");
        // TODO: Dynamic-load symbol tables, wire input/output pins, etc.
        transitionTo(LifecycleState::Initialized);
    }

    inline void TileInstance::activate()
    {
        std::scoped_lock lock{m_mutex};
        assertState(LifecycleState::Initialized, "activate");
        // TODO: Register on event-bus, start animation timers, etc.
        transitionTo(LifecycleState::Active);
    }

    inline void TileInstance::suspend()
    {
        std::scoped_lock lock{m_mutex};
        assertState(LifecycleState::Active, "suspend");
        // TODO: Pause timers, flush buffers, etc.
        transitionTo(LifecycleState::Suspended);
    }

    inline void TileInstance::destroy()
    {
        std::scoped_lock lock{m_mutex};
        if (m_state.load() == LifecycleState::Destroyed)
            return; // idempotent

        // TODO: Unload shared libs, remove event subscriptions, free resources.
        m_subscriptions.clear();
        transitionTo(LifecycleState::Destroyed);
    }

    //------------------------------------------------------------------------//
    //  Configuration / State
    //------------------------------------------------------------------------//
    inline void TileInstance::updateConfig(Json newCfg)
    {
        std::scoped_lock lock{m_mutex};
        m_configuration = std::move(newCfg);
        // TODO: notify plugin of new config
    }

    inline void TileInstance::mergePartialConfig(const Json& delta)
    {
        std::scoped_lock lock{m_mutex};
        m_configuration.merge_patch(delta);
        // TODO: propagate deltas
    }

    inline void TileInstance::publishState(Json newState)
    {
        {
            std::scoped_lock lock{m_mutex};
            m_runtimeState = std::move(newState);
        }
        // Fan out state object over event-bus (non-blocking)
        // m_eventBus.publish(...);
    }

    //------------------------------------------------------------------------//
    //  Subscription Helpers
    //------------------------------------------------------------------------//
    inline void TileInstance::subscribe(const std::string& topic)
    {
        if (topic.empty())
            throw TileInstanceError("subscribe: topic must not be empty");

        std::scoped_lock lock{m_mutex};
        m_subscriptions.insert(topic);
        // m_eventBus.subscribe(...);
    }

    inline void TileInstance::unsubscribe(const std::string& topic)
    {
        std::scoped_lock lock{m_mutex};
        m_subscriptions.erase(topic);
        // m_eventBus.unsubscribe(...);
    }

    inline bool TileInstance::isSubscribed(const std::string_view topic) const
    {
        std::scoped_lock lock{m_mutex};
        return m_subscriptions.find(std::string(topic)) != m_subscriptions.end();
    }

} // namespace mosaic::models