#ifndef MOSAICBOARDSTUDIO_CORE_PLUGINMANAGER_H
#define MOSAICBOARDSTUDIO_CORE_PLUGINMANAGER_H
/*
 *  MosaicBoard Studio
 *  File: PluginManager.h
 *
 *  Copyright (c) 2024
 *
 *  Description:
 *      Central runtime-loader for hot-swappable dashboard “tiles”.
 *      Discovers shared libraries in the /plugins directory, loads them,
 *      validates the exported interface, and keeps track of their lifecycle.
 *
 *      Thread–safe through a shared_mutex for read operations and a mutex
 *      for write operations. All resources are released automatically when
 *      PluginManager is destroyed or when plugins are explicitly unloaded.
 *
 *  Build-flags:
 *      Linux / macOS:    -ldl
 *      Windows:          link against kernel32.lib (default)
 */

#include <chrono>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#if defined(_WIN32)
    #include <Windows.h>
    using LibraryHandle = HMODULE;
#else
    #include <dlfcn.h>
    using LibraryHandle = void*;
#endif

namespace mbs::core {

/* --------------------------------------------------------------------------
 *  IPlugin ‑ Every shared library must implement this interface.            */
class IPlugin
{
public:
    virtual ~IPlugin() = default;

    /*  Metadata getters (null-terminated C-strings for C ABI friendliness) */
    virtual const char* name()    const noexcept = 0;
    virtual const char* version() const noexcept = 0;

    /*  Runtime hooks */
    virtual void start() = 0;     // called immediately after successful load
    virtual void stop()  = 0;     // called right before the plugin gets unloaded
};

/* Typedefs for the expected factory symbols */
using CreatePluginFn  = IPlugin* (*)();               //  extern "C" IPlugin* createPlugin();
using DestroyPluginFn = void      (*)(IPlugin*);       //  extern "C" void     destroyPlugin(IPlugin*);

/* --------------------------------------------------------------------------
 *  PluginManager                                                            */
class PluginManager
{
public:
    /*  Information structure that can be safely shared with the UI layer.   */
    struct PluginMeta
    {
        std::string                        name;
        std::string                        version;
        std::filesystem::path              path;
        std::chrono::system_clock::time_point loadTime;
    };

    /*  Retrieve the global manager. The instance is lazy-initialised in a
     *  thread-safe manner (since C++11 static local variable semantics).     */
    static PluginManager& instance()
    {
        static PluginManager inst;
        return inst;
    }

    /*  Prevent copying / moving (singleton semantics).                      */
    PluginManager(const PluginManager&)            = delete;
    PluginManager& operator=(const PluginManager&) = delete;
    PluginManager(PluginManager&&)                 = delete;
    PluginManager& operator=(PluginManager&&)      = delete;

    /* ----------------------------------------------------------------------
     *  Loading / unloading                                                   */

    /*
     *  loadAll:
     *      Scans the given directory for shared libraries (.so/.dylib/.dll)
     *      and attempts to load every plugin. Returns the number of plugins
     *      successfully initialised.
     */
    std::size_t loadAll(const std::filesystem::path& directory = std::filesystem::path("./plugins"))
    {
        if (!std::filesystem::exists(directory))
            return 0;

        std::size_t loaded = 0;
        for (const auto& entry : std::filesystem::directory_iterator(directory))
        {
            if (!entry.is_regular_file())
                continue;

            const auto& path = entry.path();
            if (!isSharedLibrary(path))
                continue;

            try
            {
                if (loadPlugin(path))
                    ++loaded;
            }
            catch (const std::exception& ex)
            {
                // In production you may route this to a central logger
                // rather than std::cerr.
                std::cerr << "PluginManager: failed to load \"" << path.string() << "\": "
                          << ex.what() << '\n';
            }
        }
        return loaded;
    }

    /*
     *  loadPlugin:
     *      Attempts to load a single shared library.
     *      Returns true on success, false if the plugin is already loaded.
     *      Throws std::runtime_error on failure.
     */
    bool loadPlugin(const std::filesystem::path& libPath)
    {
        std::unique_lock lock(_mutex);

        const auto canonicalPath = std::filesystem::weakly_canonical(libPath);

        // Already loaded?
        for (const auto& [name, record] : _plugins)
        {
            if (record.meta.path == canonicalPath)
                return false;
        }

        LibraryHandle handle = openLibrary(canonicalPath);
        if (!handle)
        {
            throw std::runtime_error("Unable to open shared library: " + canonicalPath.string());
        }

        auto create = reinterpret_cast<CreatePluginFn>(resolveSymbol(handle, "createPlugin"));
        auto destroy = reinterpret_cast<DestroyPluginFn>(resolveSymbol(handle, "destroyPlugin"));

        if (!create || !destroy)
        {
            closeLibrary(handle);
            throw std::runtime_error("Plugin does not expose required factories: " + canonicalPath.string());
        }

        // Wrap the raw pointer into a unique_ptr with custom deleter
        IPlugin* rawPtr = create();
        if (!rawPtr)
        {
            closeLibrary(handle);
            throw std::runtime_error("createPlugin() returned nullptr: " + canonicalPath.string());
        }

        std::unique_ptr<IPlugin, std::function<void(IPlugin*)>> instance{
            rawPtr,
            [destroy](IPlugin* p) {
                try { destroy(p); } catch (...) { /* swallow */ }
            }
        };

        // Gather metadata
        PluginMeta meta;
        meta.name      = instance->name();
        meta.version   = instance->version();
        meta.path      = canonicalPath;
        meta.loadTime  = std::chrono::system_clock::now();

        // Start the plugin (may throw)
        instance->start();

        _plugins.emplace(meta.name, PluginRecord{ std::move(instance), handle, meta });
        return true;
    }

    /*
     *  unloadPlugin:
     *      Gracefully stops and unloads the plugin with the given name.
     *      No-op if the plugin isn't loaded. Throws std::runtime_error on errors.
     */
    void unloadPlugin(const std::string& pluginName)
    {
        std::unique_lock lock(_mutex);

        auto it = _plugins.find(pluginName);
        if (it == _plugins.end())
            return;

        try
        {
            it->second.instance->stop();
        }
        catch (...)
        {
            // Never allow plugin exceptions to escape to the host application.
            // Instead, log and continue.
            std::cerr << "PluginManager: plugin \"" << pluginName
                      << "\" threw during stop(). Forcing unload.\n";
        }

        // Explicitly reset the unique_ptr first so that destroyPlugin is called
        it->second.instance.reset();

        // Then close the shared library
        closeLibrary(it->second.library);

        _plugins.erase(it);
    }

    /*
     *  unloadAll: attempts to unload every plugin, ignoring individual errors.
     */
    void unloadAll()
    {
        std::unique_lock lock(_mutex);
        for (auto it = _plugins.begin(); it != _plugins.end();)
        {
            try
            {
                it->second.instance->stop();
            }
            catch (...) { /* swallow */ }

            it->second.instance.reset();
            closeLibrary(it->second.library);
            it = _plugins.erase(it);
        }
    }

    /*
     *  listLoaded
     *      Returns a snapshot of currently loaded plugins. Thread-safe.
     */
    std::vector<PluginMeta> listLoaded() const
    {
        std::shared_lock lock(_mutex);
        std::vector<PluginMeta> out;
        out.reserve(_plugins.size());
        for (const auto& [_, rec] : _plugins)
            out.push_back(rec.meta);
        return out;
    }

    /* ----------------------------------------------------------------------
     *  Destructor                                                            */
    ~PluginManager()
    {
        try { unloadAll(); } catch (...) { /* swallow */ }
    }

private:
    PluginManager() = default;

    /* ----------------------------------------------------------------------
     *  Internal helpers                                                      */

    struct PluginRecord
    {
        std::unique_ptr<IPlugin, std::function<void(IPlugin*)>> instance;
        LibraryHandle                                          library;
        PluginMeta                                             meta;
    };

    mutable std::shared_mutex                      _mutex;
    std::unordered_map<std::string, PluginRecord>  _plugins;

    static bool isSharedLibrary(const std::filesystem::path& p)
    {
#if defined(_WIN32)
        return p.extension() == ".dll";
#elif defined(__APPLE__)
        return p.extension() == ".dylib";
#else
        return p.extension() == ".so";
#endif
    }

    /*  Cross-platform dynamic library handling                              */
    static LibraryHandle openLibrary(const std::filesystem::path& path)
    {
#if defined(_WIN32)
        return ::LoadLibraryW(path.wstring().c_str());
#else
        return ::dlopen(path.c_str(), RTLD_NOW);
#endif
    }

    static void* resolveSymbol(LibraryHandle handle, const char* symbol)
    {
#if defined(_WIN32)
        return reinterpret_cast<void*>(::GetProcAddress(handle, symbol));
#else
        return ::dlsym(handle, symbol);
#endif
    }

    static void closeLibrary(LibraryHandle handle)
    {
        if (!handle) return;
#if defined(_WIN32)
        ::FreeLibrary(handle);
#else
        ::dlclose(handle);
#endif
    }
};

} // namespace mbs::core

#endif // MOSAICBOARDSTUDIO_CORE_PLUGINMANAGER_H