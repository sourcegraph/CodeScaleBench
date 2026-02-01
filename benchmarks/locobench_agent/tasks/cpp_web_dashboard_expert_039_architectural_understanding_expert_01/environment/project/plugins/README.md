```markdown
# MosaicBoard Studio — Plugin Development Guide  
_Welcome to the beating heart of MosaicBoard Studio (MBS)._  
Everything that animates the dashboard is implemented as a **tile-plugin**—a hot-swappable
shared object that MBS discovers at runtime. This document shows you how to go from
zero to shipping a production-grade plug-in.

---

## 1. Directory Layout

```text
plugins/
├── README.md          ← *You are here*
├── cmake/             ← CMake helpers & toolchains
├── ThirdParty/        ← (Optional) Private third-party libs
└── <YourPlugin>/
    ├── CMakeLists.txt
    ├── include/
    │   └── <YourPlugin>.h
    ├── src/
    │   └── <YourPlugin>.cpp
    └── manifest.json  ← Metadata consumed by studio
```

Plugins are **completely sandboxed**; cross-plugin dependencies are prohibited unless they
are mediated through the official public interfaces shipped with the core SDK.

---

## 2. Quick-Start: “Hello-World” Tile

1. Copy the skeleton below into `plugins/HelloWorld/`.
2. Run `./bootstrap.sh --plugin=HelloWorld` from project root.
3. Refresh the web dashboard: the tile appears instantly—no restart required 🎉

<details>
<summary><strong>manifest.json</strong></summary>

```json
{
  "id"            : "com.yourcompany.helloworld",
  "name"          : "Hello World Tile",
  "version"       : "1.0.0",
  "entry"         : "libHelloWorld.so",
  "description"   : "Demonstrates the minimal MosaicBoard plugin.",
  "author"        : "Jane Developer",
  "license"       : "MIT",
  "minCoreApi"    : "2.5.0",
  "tags"          : ["example", "tutorial"]
}
```
</details>

<details>
<summary><strong>CMakeLists.txt</strong></summary>

```cmake
cmake_minimum_required(VERSION 3.23)

project(HelloWorld VERSION 1.0.0 LANGUAGES CXX)

# Tell CMake where the SDK lives
list(APPEND CMAKE_PREFIX_PATH ${MBS_SDK_DIR})

find_package(MosaicBoardSDK 2.5 REQUIRED COMPONENTS Core Tiles)

add_library(HelloWorld SHARED
    src/HelloWorld.cpp
)

target_link_libraries(HelloWorld
    PRIVATE
        MosaicBoard::Core
        MosaicBoard::Tiles
)

target_include_directories(HelloWorld
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

set_target_properties(HelloWorld PROPERTIES
    CXX_STANDARD 20
    OUTPUT_NAME "HelloWorld"
)
```
</details>

<details>
<summary><strong>include/HelloWorld.h</strong></summary>

```cpp
#pragma once
/**
 *  A ultra-simple tile that prints “Hello Mosaic!” to the event bus every 5s.
 *
 *  Lifecycle:
 *      • onInit   ‑ register timer and allocate resources
 *      • onRender ‑ emit frame (no visual content, just demonstration)
 *      • onDeinit ‑ clean-up
 */
#include <mbs/tiles/ITilePlugin.hpp>
#include <mbs/core/Timer.hpp>
#include <memory>

class HelloWorld final : public mbs::tiles::ITilePlugin
{
public:
    MBS_DECLARE_PLUGIN(HelloWorld)   // Macro exports create(), destroy()

    void onInit(const mbs::core::TileContext& ctx) override;
    void onRender(double deltaSeconds) override;
    void onDeinit() noexcept override;

private:
    std::unique_ptr<mbs::core::Timer> m_timer;
    void emitGreeting();
};
```
</details>

<details>
<summary><strong>src/HelloWorld.cpp</strong></summary>

```cpp
#include "HelloWorld.h"
#include <mbs/core/EventBus.hpp>
#include <mbs/core/Log.hpp>

namespace
{
    constexpr std::chrono::seconds kInterval{5};
}

void HelloWorld::onInit(const mbs::core::TileContext& ctx)
{
    mbs::log::info("[HelloWorld] Initializing (instance {}).", ctx.id());
    m_timer = std::make_unique<mbs::core::Timer>(kInterval, [this] {
        emitGreeting();
    });
}

void HelloWorld::onRender(double /*deltaSeconds*/)
{
    // Nothing to paint; could push pixels to FrameBuffer here.
}

void HelloWorld::onDeinit() noexcept
{
    m_timer.reset();
    mbs::log::info("[HelloWorld] Deinitialized.");
}

void HelloWorld::emitGreeting()
{
    mbs::core::EventBus::instance().broadcast("hello", "Hello Mosaic!");
    mbs::log::debug("[HelloWorld] Greeting emitted.");
}
```
</details>

---

## 3. Plugin Interface Reference (v2.5)

| Method           | When Called                       | Notes                                        |
|------------------|-----------------------------------|----------------------------------------------|
| `onInit`         | After shared library load         | Receive immutable `TileContext`.             |
| `onRender`       | Each frame (~60 Hz by default)    | Keep logic deterministic, avoid I/O.         |
| `onHandleEvent`  | When subscribed bus event fires   | Use `TileContext::bus()` to subscribe.       |
| `onResize`       | Viewport changes                  | Reallocate GPU buffers, layouts.             |
| `onDeinit`       | Before shared library is unloaded | Must be `noexcept` & never throw exceptions. |

Extensive API docs live at `docs/sdk/html/index.html`.

---

## 4. Hot-Reload Workflow

1. Compile plugin (`ninja HelloWorld`)  
2. MBS core watches `plugins/**/*.so` for inotify events.  
3. Upon change, core:  
   a. Unloads old instance via `destroy()`  
   b. Loads fresh `.so` and invokes `create()`  

Stateless design patterns are your friend—persist long-lived data in the cache or
the user’s session, **not** in static variables.

---

## 5. Safe Exception & Error Handling

Plugins must never leak exceptions across the shared-library ABI boundary.
Use the provided utility `MBS_TRY`/`MBS_CATCH` wrappers or follow this pattern:

```cpp
void MyTile::onRender(double dt)
{
    try
    {
        updatePhysics(dt);
    }
    catch (const std::exception& ex)
    {
        mbs::log::error("[{}] render failed: {}", id(), ex.what());
        requestSelfDestruct("Render failure");  // Notifies core to unload tile
    }
}
```

---

## 6. Best Practices Checklist

✓ Keep **render loop** deterministic—push work to async jobs.  
✓ Favor **immutable data** transfers; embrace `const`.  
✓ Gate heavy ops behind **feature flags** (core exposes user prefs).  
✓ Call `mbs::metrics::record()` for telemetry.  
✓ Remove all `assert()` in release builds (`NDEBUG`).  
✓ Minimize binary size: `-ffunction-sections -fdata-sections -Wl,--gc-sections`.

---

## 7. Example: Real-time CPU-Usage Tile

Need inspiration? Study `plugins/SysMon/`, which turns CPU statistics into a
radial bar chart that pulses with system load.

---

## 8. Publishing Your Plugin

1. Bump the `version` field following [SemVer].  
2. Ensure CI passes (`plugins-ci.yml`).  
3. `git tag v1.2.0 && git push --tags`.  
4. The pipeline uploads the artifact to the **Marketplace** and signs it.

---

Happy hacking, and welcome to the MosaicBoard ecosystem!  
Need help? Join `#plugins-dev` on Slack or file an issue.

```

