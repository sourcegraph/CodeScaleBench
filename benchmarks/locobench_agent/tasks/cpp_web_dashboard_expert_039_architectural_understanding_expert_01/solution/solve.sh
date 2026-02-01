#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The core of a correct solution involves creating a more comprehensive plugin interface and using the `PluginManager` as a mediator to prevent tight coupling between plugins and the server core.

1.  **Analysis:** The current system uses `PluginManager` to dynamically load shared libraries. It looks for a C-style factory function (e.g., `create_plugin()`) which returns an object that can create instances of `ITile`. The `PluginManager`'s responsibility is limited to managing the lifecycle of these tile-providing objects.

2.  **Proposed Design:**
    *   **New Interface:** Create a new `IPlugin.h` interface. The main class in a plugin's shared library will implement this. The `ITile` interface will remain for the visual components themselves.
        ```cpp
        // In a new IPlugin.h
        class IPlugin {
        public:
            virtual ~IPlugin() = default;
            // Called by PluginManager after loading
            virtual void initialize(const PluginContext& context) = 0;
            // Returns API endpoints for the Server to register
            virtual std::vector<RouteDefinition> getApiRoutes() = 0;
            // Returns factories for dashboard tiles
            virtual std::vector<std::shared_ptr<ITileFactory>> getTileFactories() = 0;
            virtual void shutdown() = 0;
        };
        ```
        The `PluginContext` struct would contain a reference to the `EventBus`: `struct PluginContext { EventBus& eventBus; };`

    *   **PluginManager Changes:** `PluginManager::loadPlugins()` must be updated. It will now expect the `create_plugin()` entry point in each `.so`/`.dll` to return a `std::unique_ptr<IPlugin>`. After creating the instance, it will:
        a. Create a `PluginContext` object containing a reference to the application's `EventBus`.
        b. Call `plugin->initialize(context)`. This allows the plugin to subscribe to events.
        c. Call `plugin->getApiRoutes()` and pass the returned `RouteDefinition` vector to the `Server`'s routing engine for registration.
        d. The `PluginManager` will now store `std::unique_ptr<IPlugin>` instead of the old tile factories.

    *   **Server Interaction:** The `Server` class does not need to know about plugins directly. It only needs a method like `registerRoutes(const std::vector<RouteDefinition>& routes)`. The `Application` or `main` function will orchestrate this by first letting `PluginManager` load plugins and collect routes, and then passing those routes to the `Server` instance before starting it.

This design correctly separates concerns, enhances plugin capabilities without exposing core server internals, and provides a clear, type-safe contract for future plugin development.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
