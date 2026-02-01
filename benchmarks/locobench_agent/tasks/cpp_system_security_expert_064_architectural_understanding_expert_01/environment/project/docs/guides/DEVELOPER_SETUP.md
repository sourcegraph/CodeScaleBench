```markdown
# FortiLedger360 • Developer Workstation Setup Guide
*File: `docs/guides/DEVELOPER_SETUP.md`*

Welcome to the FortiLedger360 Enterprise Security Suite!  
This guide helps new contributors spin up a **C++20**‐ready workstation capable of compiling, testing, and debugging every layer—from the presentation façade all the way down to the infrastructure adapters.

---

## 1. Prerequisites

| Requirement               | Recommended Version | Notes                                                                    |
|---------------------------|---------------------|--------------------------------------------------------------------------|
| OS                        | Ubuntu 22.04 / macOS 13 | Windows is supported via WSL-2                                           |
| Compiler                  | `clang++` 15+ or `g++` 12+ | Must support the C++20 standard and coroutines                           |
| Build System              | CMake ≥ 3.26         | Toolchain files target Clang/GCC, Apple Clang, MSVC                      |
| Package Manager           | Conan 2.x            | Used for gRPC, spdlog, googletest, fmt…                                  |
| gRPC & Protobuf           | 1.57+               | Pulled automatically by Conan                                            |
| Python (tooling)          | 3.10 +              | Code-gen, custom linters, CLI helpers                                    |
| Docker & Docker-Compose   | 24.x                | Spin up service mesh test cluster locally                                |

---

## 2. Clone & Bootstrap

```bash
git clone --recurse-submodules git@github.com:FortiLedger360/system_security.git
cd system_security
./scripts/bootstrap.sh            # installs conan profiles, commit hooks, git-submodules
conan profile show default        # verify that the profile matches your compiler
```

The `bootstrap.sh` script is idempotent—you can safely re-run it after pulling new commits.

---

## 3. Configure Conan & Build

1. **Install third-party libraries**  
   ```bash
   conan install . --output-folder=build --build=missing -pr:h default -pr:b default
   ```

2. **Generate project files**  
   ```bash
   cmake -S . -B build \
         -DCMAKE_BUILD_TYPE=Debug \
         -DFL360_ENABLE_CLANG_TIDY=ON \
         -DFL360_ENABLE_CPPCHECK=ON
   ```

3. **Compile**  
   ```bash
   cmake --build build -j $(nproc)
   ```

4. **Run the full test suite**  
   ```bash
   ctest --test-dir build --output-on-failure
   ```

---

## 4. Quick Validation Program

After the first successful build, verify that the event-bus and gRPC stubs link correctly by compiling the following minimal program:

```cpp
// file: sandbox/quick_start.cpp
// Purpose: Validate core runtime & third-party linkage

#include <chrono>
#include <iostream>
#include <fl360/core/event_bus.hpp>
#include <fl360/core/log.hpp>

int main() {
    using namespace std::chrono_literals;
    try {
        fl360::core::EventBus bus;
        bus.publish<fl360::events::SystemBootCompleted>({});
        fl360::core::log::info("🎉 FortiLedger360 Runtime OK!");
        std::this_thread::sleep_for(150ms);
        return EXIT_SUCCESS;
    } catch (const std::exception& ex) {
        fl360::core::log::error("Runtime validation failed: {}", ex.what());
        return EXIT_FAILURE;
    }
}
```

Compile directly:

```bash
clang++ -std=c++20 -I./include \
        sandbox/quick_start.cpp \
        -Lbuild/lib -lfl360_core -lprotobuf -lpthread -o quick_start

./quick_start   # Expect: 🎉 FortiLedger360 Runtime OK!
```

---

## 5. IDE Integration

### VS Code

```jsonc
// .vscode/settings.json
{
  "cmake.configureArgs": [
    "-DFL360_ENABLE_CLANG_TIDY=ON",
    "-DFL360_ENABLE_CPPCHECK=ON"
  ],
  "cmake.generator": "Ninja",
  "conan.cmakefile": "conanfile.py",
  "C_Cpp.clang_format_style": "file"
}
```

Run `Ctrl+Shift+P → CMake: Configure` to auto-detect include paths and enable semantic IntelliSense.

### CLion

1. File → Settings → Build, Execution, Deployment → CMake  
   - Set **Profile** → *Debug*  
   - CMake options:  
     ```
     -DFL360_ENABLE_CLANG_TIDY=ON -DFL360_ENABLE_CPPCHECK=ON
     ```
2. Enable the **Conan** plugin and select *conanfile.py* in the project root.

---

## 6. Running the Local Service Mesh

Spin up a fully wired test cluster—complete with **PostgreSQL**, **NATS JetStream**, and **Jaeger** tracing—using Docker Compose:

```bash
docker compose -f infra/compose/dev.yml up -d
docker compose logs -f mesh-gateway
```

The `mesh-gateway` proxy will emit logs once gRPC health-checks succeed.

---

## 7. Git Hooks & Static Analysis

`./scripts/install-hooks.sh` installs staged checks:

- `clang-format` (auto-fixes style)
- `clang-tidy` (static analysis)
- `cppcheck`
- `cmake-format`
- License header validation

A failing hook blocks the commit; override with `git commit --no-verify` **sparingly**.

---

## 8. Frequently Asked Questions

**Q: Build is stuck at 0% while “Checking Build System”**  
A: Delete `build/CMakeCache.txt`, run `conan clean`, then configure again.

**Q: gRPC code-gen fails with `protoc: command not found`**  
A: Ensure Conan downloaded the toolchain; `which protoc` should point inside your user cache: `~/.conan2/p/…/bin/protoc`.

**Q: Tests crash on start-up with `ECONNREFUSED`**  
A: The mesh cluster may not be running; execute `docker compose ps` and ensure `nats` is healthy.

---

## 9. Updating Third-Party Dependencies

```bash
conan lock create . --lockfile-out=conan.lock --profile=default
conan lock build conan.lock --update
```

Commit the refreshed `conan.lock` to guarantee reproducible CI builds.

---

## 10. Next Steps

• Read `docs/guides/CONTRIBUTING.md` for branching strategy and coding standards  
• Explore sample adapters in `src/adapters/` to learn about the Event Bus & Observer hooks  
• Join the **#fortiledger-dev** channel on Slack for support

Happy hacking!  
*— The FortiLedger360 Core Team*
```