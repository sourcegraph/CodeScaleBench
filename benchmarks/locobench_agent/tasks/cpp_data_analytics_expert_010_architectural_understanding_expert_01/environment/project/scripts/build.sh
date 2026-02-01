/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * File:    scripts/build.sh    (but implemented in C++)
 * Author:  DevOps / Tooling Team
 * License: Apache-2.0
 *
 * Overview
 * ========
 * This utility is a modern C++17 “script” that replaces a fragile shell-script-style
 * build.sh with a cross-platform, strongly-typed implementation.  It drives the
 * full configure / build / test / package workflow while providing rich diagnostics,
 * parallel execution, and hardened error handling.  The binary is intended to live
 * inside `scripts/` but can be executed from anywhere inside the repository:
 *
 *      $ ./scripts/build.sh --type Release --jobs 16 --run-tests
 *
 * Rationale
 * =========
 *  • Cross-platform (Windows, macOS, Linux) without relying on bash.
 *  • Better error checking than ad-hoc shell commands.
 *  • Thread-safe, composable, and unit-testable.
 *
 * Notes
 * =====
 *  • Requires a C++17 compiler.
 *  • Uses only the standard library so the bootstrap path is minimal.
 */

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <future>
#include <iomanip>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <vector>

#if defined(_WIN32)
    #include <windows.h>
#endif

namespace fs = std::filesystem;

/* -------------------------------------------------- */
/*               Utility / Helper Classes             */
/* -------------------------------------------------- */

/**
 * exec() – Execute a shell command and capture its exit code.
 *
 * On Windows we go through `cmd /C` so that built-in commands (e.g. "dir")
 * work.  On Unix-like systems we spawn through `/bin/sh ‑c`.
 */
int exec(const std::string& cmd) {
#if defined(_WIN32)
    std::string systemCmd = "cmd /C \"" + cmd + "\"";
#else
    std::string systemCmd = "/bin/sh -c \"" + cmd + "\"";
#endif
    return std::system(systemCmd.c_str());
}

/**
 * log() – Thread-safe logger with basic severity levels.
 * We purposefully keep it stdout-only to avoid hidden log files
 * during the early bootstrap phase.
 */
enum class LogLevel { INFO, WARN, ERROR, FATAL };

void log(LogLevel lvl, const std::string& msg) {
    static std::mutex mtx;
    std::lock_guard<std::mutex> lock(mtx);

    auto timestamp = [] {
        using namespace std::chrono;
        auto now   = system_clock::now();
        auto tt    = system_clock::to_time_t(now);
        std::tm tm = *std::localtime(&tt);
        std::ostringstream oss;
        oss << std::put_time(&tm, "%F %T");
        return oss.str();
    };

    const char* levelStr =
        lvl == LogLevel::INFO  ? "INFO " :
        lvl == LogLevel::WARN  ? "WARN " :
        lvl == LogLevel::ERROR ? "ERROR" :
                                 "FATAL";

    std::cout << "[" << timestamp() << "] [" << levelStr << "] " << msg << '\n';
    if (lvl == LogLevel::FATAL) {
        std::exit(EXIT_FAILURE);
    }
}

/**
 * CommandLine – minimalistic CLI parser.
 */
class CommandLine {
public:
    explicit CommandLine(int argc, char** argv) {
        for (int i = 1; i < argc; ++i) {
            args_.emplace_back(argv[i]);
        }
    }

    bool hasFlag(const std::string& flag) const {
        return std::find(args_.begin(), args_.end(), flag) != args_.end();
    }

    std::optional<std::string> getOption(const std::string& option,
                                         const std::string& defaultVal = {}) const
    {
        auto it = std::find(args_.begin(), args_.end(), option);
        if (it != args_.end() && ++it != args_.end()) {
            return *it;
        }
        if (!defaultVal.empty()) { return defaultVal; }
        return std::nullopt;
    }

private:
    std::vector<std::string> args_;
};

/* -------------------------------------------------- */
/*                     Build Logic                    */
/* -------------------------------------------------- */

struct BuildConfig {
    std::string buildDir     = "build";
    std::string buildType    = "Debug";
    unsigned    parallelJobs = std::thread::hardware_concurrency();
    bool        runTests     = false;
    bool        runPackage   = false;
};

/**
 * configure() – generate build system (CMake) files.
 */
void configure(const BuildConfig& cfg) {
    if (!fs::exists(cfg.buildDir)) {
        log(LogLevel::INFO, "Creating build directory: " + cfg.buildDir);
        fs::create_directory(cfg.buildDir);
    }

    std::ostringstream cmd;
    cmd << "cmake -S ."
        << " -B " << cfg.buildDir
        << " -DCMAKE_BUILD_TYPE=" << cfg.buildType
        << " -DCMAKE_EXPORT_COMPILE_COMMANDS=ON";

    log(LogLevel::INFO, "Configuring CMake project...");
    if (int rc = exec(cmd.str()); rc != 0) {
        throw std::runtime_error("CMake configure failed (exit code: " + std::to_string(rc) + ")");
    }
}

/**
 * build() – compile the entire project with parallel jobs.
 */
void build(const BuildConfig& cfg) {
    std::ostringstream cmd;
    cmd << "cmake --build " << cfg.buildDir << " --parallel " << cfg.parallelJobs;
    log(LogLevel::INFO, "Building sources (" + std::to_string(cfg.parallelJobs) + " jobs)...");
    if (int rc = exec(cmd.str()); rc != 0) {
        throw std::runtime_error("Build failed (exit code: " + std::to_string(rc) + ")");
    }
}

/**
 * test() – run ctest suite.
 */
void test(const BuildConfig& cfg) {
    log(LogLevel::INFO, "Running unit/integration tests...");
    std::ostringstream cmd;
    cmd << "ctest --test-dir " << cfg.buildDir << " --output-on-failure";
    if (int rc = exec(cmd.str()); rc != 0) {
        throw std::runtime_error("Some tests failed (exit code: " + std::to_string(rc) + ")");
    }
}

/**
 * package() – generate installable artifacts.
 * This step is optional and typically used by CI pipelines or release engineers.
 */
void package(const BuildConfig& cfg) {
    log(LogLevel::INFO, "Generating distributable package...");
    std::ostringstream cmd;
    cmd << "cpack --config " << cfg.buildDir << "/CPackConfig.cmake";
    if (int rc = exec(cmd.str()); rc != 0) {
        throw std::runtime_error("Packaging failed (exit code: " + std::to_string(rc) + ")");
    }
}

/* -------------------------------------------------- */
/*                      Entry Point                   */
/* -------------------------------------------------- */

int main(int argc, char** argv) try {
    CommandLine cli(argc, argv);

    if (cli.hasFlag("-h") || cli.hasFlag("--help")) {
        std::cout <<
            "Usage: build.sh [options]\n"
            "Options:\n"
            "  --type <Debug|Release|RelWithDebInfo|MinSizeRel>\n"
            "  --jobs <N>           Number of parallel compile jobs (default: hw threads)\n"
            "  --run-tests          Execute ctest after build\n"
            "  --package            Run CPack to generate distributables\n"
            "  -h, --help           Show this message and exit\n";
        return EXIT_SUCCESS;
    }

    BuildConfig cfg;
    if (auto type = cli.getOption("--type"); type) cfg.buildType = *type;
    if (auto jobs = cli.getOption("--jobs"); jobs) cfg.parallelJobs = std::stoul(*jobs);
    cfg.runTests   = cli.hasFlag("--run-tests");
    cfg.runPackage = cli.hasFlag("--package");

    // Validate build type
    static const std::array<std::string, 4> allowedTypes{
        "Debug", "Release", "RelWithDebInfo", "MinSizeRel"
    };
    if (std::find(allowedTypes.begin(), allowedTypes.end(), cfg.buildType) == allowedTypes.end()) {
        log(LogLevel::FATAL, "Invalid build type: " + cfg.buildType);
    }

    // Print summary
    std::ostringstream banner;
    banner << "CardioInsight360 Build Utility\n"
           << "  Build Type : " << cfg.buildType << '\n'
           << "  Jobs       : " << cfg.parallelJobs << '\n'
           << "  Run Tests  : " << (cfg.runTests ? "yes" : "no") << '\n'
           << "  Package    : " << (cfg.runPackage ? "yes" : "no");
    log(LogLevel::INFO, banner.str());

    // Run phases
    configure(cfg);
    build(cfg);
    if (cfg.runTests)   test(cfg);
    if (cfg.runPackage) package(cfg);

    log(LogLevel::INFO, "Build completed successfully.");
    return EXIT_SUCCESS;
}
catch (const std::exception& ex) {
    log(LogLevel::ERROR, ex.what());
    return EXIT_FAILURE;
}
catch (...) {
    log(LogLevel::FATAL, "Unknown fatal error.");
    return EXIT_FAILURE;
}