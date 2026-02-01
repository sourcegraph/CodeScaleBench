#include "core/PluginManager.hpp"

#include "core/EventBus.hpp"
#include "core/MBSException.hpp"
#include "core/Telemetry.hpp"
#include "utils/Platform.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <mutex>

#ifdef MBS_PLATFORM_WINDOWS
    #include <windows.h>
#else
    #include <dlfcn.h>
#endif


namespace mbs::core
{
using json                         = nlohmann::json;
using clock                        = std::chrono::steady_clock;
static constexpr char PLUGIN_DIR[] = "plugins";

namespace fs = std::filesystem;

/* -------------------------------------------------------------------------- */
/*                             Internal Structures                            */
/* -------------------------------------------------------------------------- */
struct PluginManager::PluginHandle final
{
    void*              dlHandle               = nullptr;     // OS handle (dlopen / LoadLibrary)
    std::unique_ptr<IPlugin> instance          = nullptr;    // Owning pointer to plugin instance
    PluginMetadata          metadata;                        // Cached metadata
    clock::time_point       loadTimestamp{};                 // For hot-reload & telemetry
};

/* -------------------------------------------------------------------------- */
/*                                C API hooks                                 */
/* -------------------------------------------------------------------------- */
namespace
{
    using CreatePluginFn = IPlugin* (*)();
    using DestroyPluginFn = void (*)(IPlugin*);
    constexpr char CREATE_FN_NAME[]  = "mbsCreatePlugin";
    constexpr char DESTROY_FN_NAME[] = "mbsDestroyPlugin";

    // Wrapper to safely get a symbol and cast it
    template <typename T>
    T loadSymbol(void* handle, const char* name)
    {
#ifdef MBS_PLATFORM_WINDOWS
        auto* symbol = reinterpret_cast<T>(GetProcAddress(static_cast<HMODULE>(handle), name));
#else
        auto* symbol = reinterpret_cast<T>(dlsym(handle, name));
#endif
        if (!symbol)
        {
#ifdef MBS_PLATFORM_WINDOWS
            throw MBSException(
                fmt::format("Unable to resolve symbol '{}' in plugin: GetLastError={}", name, GetLastError()));
#else
            throw MBSException(
                fmt::format("Unable to resolve symbol '{}' in plugin: {}", name, dlerror()));
#endif
        }
        return symbol;
    }

    // Platform specific dlopen wrapper
    void* openLibrary(const fs::path& libPath)
    {
#ifdef MBS_PLATFORM_WINDOWS
        auto* handle = LoadLibraryW(libPath.wstring().c_str());
        if (!handle)
        {
            throw MBSException(fmt::format("Failed to load plugin '{}'. Error code={}", libPath.string(), GetLastError()));
        }
        return handle;
#else
        auto* handle = dlopen(libPath.c_str(), RTLD_NOW);
        if (!handle)
        {
            throw MBSException(fmt::format("Failed to load plugin '{}'. {}", libPath.string(), dlerror()));
        }
        return handle;
#endif
    }

    void closeLibrary(void* handle) noexcept
    {
        if (!handle) return;
#ifdef MBS_PLATFORM_WINDOWS
        FreeLibrary(static_cast<HMODULE>(handle));
#else
        dlclose(handle);
#endif
    }

    // Load optional sidecar metadata file (plugin_name.json)
    std::optional<PluginMetadata> loadSidecarMetadata(const fs::path& libraryPath)
    {
        const fs::path jsonPath = libraryPath.replace_extension(".json");
        if (!fs::exists(jsonPath))
            return std::nullopt;

        try
        {
            std::ifstream file(jsonPath);
            json j;
            file >> j;

            PluginMetadata meta;
            meta.id          = j.value("id", libraryPath.stem().string());
            meta.name        = j.value("name", libraryPath.stem().string());
            meta.version     = j.value("version", "0.0.0");
            meta.description = j.value("description", "");
            meta.author      = j.value("author", "");
            meta.capabilities= j.value("capabilities", std::vector<std::string>{});

            return meta;
        }
        catch (std::exception& ex)
        {
            spdlog::warn("Failed to load metadata for '{}': {}", libraryPath.string(), ex.what());
            return std::nullopt;
        }
    }
} // namespace

/* -------------------------------------------------------------------------- */
/*                            PluginManager Impl                              */
/* -------------------------------------------------------------------------- */

PluginManager::PluginManager(EventBus& bus) : _eventBus(bus)
{
    spdlog::debug("PluginManager created");
}

PluginManager::~PluginManager()
{
    try
    {
        unloadAll();
    }
    catch (std::exception& ex)
    {
        spdlog::error("Exception during PluginManager shutdown: {}", ex.what());
    }
}

void PluginManager::discoverAndLoad()
{
    std::scoped_lock lk(_mutex);

    if (!fs::exists(PLUGIN_DIR))
        fs::create_directory(PLUGIN_DIR);

    const auto ext = mbs::utils::dynamicLibraryExtension(); // ".so" or ".dll"
    std::vector<fs::path> candidates;

    std::copy_if(fs::directory_iterator{PLUGIN_DIR}, fs::directory_iterator{},
                 std::back_inserter(candidates),
                 [&ext](const fs::directory_entry& e) { return e.path().extension() == ext; });

    for (const auto& libPath : candidates)
    {
        if (isLoaded(libPath))
            continue;

        try
        {
            loadPlugin(libPath);
        }
        catch (std::exception& ex)
        {
            spdlog::error("Failed to load plugin '{}' : {}", libPath.string(), ex.what());
        }
    }
}

void PluginManager::loadPlugin(const std::filesystem::path& libPath)
{
    if (!fs::exists(libPath))
        throw MBSException(fmt::format("Plugin library '{}' does not exist", libPath.string()));

    spdlog::info("Loading plugin '{}'", libPath.string());

    auto handle = std::make_unique<PluginHandle>();
    handle->dlHandle = openLibrary(libPath);

    // Resolve factory functions
    auto createFn  = loadSymbol<CreatePluginFn>(handle->dlHandle, CREATE_FN_NAME);
    auto destroyFn = loadSymbol<DestroyPluginFn>(handle->dlHandle, DESTROY_FN_NAME);

    // Create plugin instance
    std::unique_ptr<IPlugin> pluginPtr(createFn());
    if (!pluginPtr)
        throw MBSException(fmt::format("Factory returned nullptr for plugin '{}'", libPath.string()));

    // Bind custom deleter for smart pointer
    pluginPtr = std::unique_ptr<IPlugin>(pluginPtr.release(), [destroyFn](IPlugin* p) {
        if (!p) return;
        try
        {
            destroyFn(p);
        }
        catch (...)
        {
            spdlog::warn("Exception thrown from plugin destroy function");
        }
    });

    // Retrieve metadata, falling back to sidecar json, then IPlugin::metadata()
    auto sidecar                 = loadSidecarMetadata(libPath);
    handle->metadata             = sidecar.value_or(pluginPtr->metadata());
    handle->instance             = std::move(pluginPtr);
    handle->loadTimestamp        = clock::now();

    // Register with event bus
    handle->instance->subscribe(_eventBus);

    // Telemetry
    Telemetry::instance().emit("plugin.loaded", {
        {"id", handle->metadata.id},
        {"version", handle->metadata.version}
    });

    spdlog::info("Plugin '{}' (v{}) successfully loaded", handle->metadata.name, handle->metadata.version);
    _handles.emplace_back(std::move(handle));
}

void PluginManager::unloadPlugin(const std::string& pluginId)
{
    std::scoped_lock lk(_mutex);

    const auto it = std::find_if(_handles.begin(), _handles.end(),
                                 [&pluginId](const auto& h) { return h->metadata.id == pluginId; });

    if (it == _handles.end())
        throw MBSException(fmt::format("No plugin with id '{}' is loaded", pluginId));

    auto& handle = *it;

    spdlog::info("Unloading plugin '{}'", handle->metadata.name);

    // Unsubscribe from bus first (prevent dangling callbacks)
    handle->instance->unsubscribe(_eventBus);

    // Destroy plugin instance (unique_ptr deleter)
    handle->instance.reset();

    // Close dynamic library
    closeLibrary(handle->dlHandle);
    handle->dlHandle = nullptr;

    Telemetry::instance().emit("plugin.unloaded", {
        {"id", pluginId}
    });

    _handles.erase(it);
}

void PluginManager::unloadAll()
{
    std::scoped_lock lk(_mutex);
    while (!_handles.empty())
        unloadPlugin(_handles.front()->metadata.id);
}

bool PluginManager::isLoaded(const std::filesystem::path& libPath) const
{
    const auto canonicalized = fs::weakly_canonical(libPath);

    return std::any_of(_handles.begin(), _handles.end(), [&](const auto& h) {
        return fs::weakly_canonical(h->metadata.libraryPath) == canonicalized;
    });
}

std::vector<PluginMetadata> PluginManager::loadedPlugins() const
{
    std::scoped_lock lk(_mutex);
    std::vector<PluginMetadata> metas;
    metas.reserve(_handles.size());
    for (const auto& h : _handles)
        metas.push_back(h->metadata);
    return metas;
}

/* -------------------------------------------------------------------------- */
/*                               Hot Reloading                                */
/* -------------------------------------------------------------------------- */

bool PluginManager::reloadIfChanged()
{
    std::scoped_lock lk(_mutex);
    bool anyReloaded = false;

    for (auto& handle : _handles)
    {
        const auto now          = fs::last_write_time(handle->metadata.libraryPath);
        const auto loadedAt     = handle->loadTimestamp;

        if (now > loadedAt)
        {
            spdlog::info("Change detected in plugin '{}', reloading...", handle->metadata.name);
            const auto id = handle->metadata.id;
            try
            {
                unloadPlugin(id);
                loadPlugin(handle->metadata.libraryPath);
                anyReloaded = true;
            }
            catch (std::exception& ex)
            {
                spdlog::error("Hot-reload failed for plugin '{}': {}", id, ex.what());
            }
        }
    }
    return anyReloaded;
}

} // namespace mbs::core