```cpp
/**
 *  MosaicBoard Studio – Development Environment Bootstrap Utility
 *
 *  File            : scripts/setup_dev_env.cpp
 *  Description     : Cross-platform C++ utility that replaces the old shell
 *                    script for setting-up a local development environment.
 *                    – Verifies tool-chain requirements (git, cmake, ninja, …)
 *                    – Retrieves/updates git sub-modules
 *                    – Generates a build directory with the preferred
 *                      generator (Ninja/MSVC/Unix Makefiles)
 *                    – Writes a `.env` file containing helpful variables
 *                    – Pre-creates runtime folders such as `/plugins`
 *                      and `/cache`, making sure they are writable
 *
 *  Build           : c++ -std=c++20 -O2 -Wall -Wextra -pedantic
 *                    (requires C++20 for <filesystem> & <format>)
 *
 *  Usage           : ./setup_dev_env [--force] [--generator=<gen>]
 *
 *  Copyright
 *  ---------
 *  MIT License. See LICENSE file.
 */

#include <iostream>
#include <filesystem>
#include <vector>
#include <cstdlib>
#include <optional>
#include <format>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <array>

#if defined(_WIN32)
#   include <windows.h>
#   define DEFAULT_GENERATOR "Ninja"
#else
#   include <unistd.h>
#   define DEFAULT_GENERATOR "Unix Makefiles"
#endif

namespace fs = std::filesystem;

/* ---------------------------------------------------------
 *  Utility helpers
 * --------------------------------------------------------- */

namespace term {

inline void color(const char* code) { std::cout << code; }
inline void reset()                 { std::cout << "\033[0m"; }

constexpr const char* GREEN  = "\033[32m";
constexpr const char* RED    = "\033[31m";
constexpr const char* YELLOW = "\033[33m";
constexpr const char* CYAN   = "\033[36m";

} // namespace term

class ProcessError : public std::runtime_error
{
public:
    explicit ProcessError(const std::string& msg, int code)
        : std::runtime_error(msg), exitCode(code) {}
    int exitCode;
};

/**
 *  runProcess
 *  ----------
 *  Executes a command via std::system and throws on non-zero exit.
 */
static void runProcess(const std::string& cmd, bool verbose = true)
{
    if (verbose)
    {
        term::color(term::CYAN);
        std::cout << "$ " << cmd << std::endl;
        term::reset();
    }

    int exitCode = std::system(cmd.c_str());
    if (exitCode != 0)
    {
        throw ProcessError(
            std::format("Command '{}' failed (exit code {})", cmd, exitCode),
            exitCode);
    }
}

/**
 *  checkExecutable
 *  ---------------
 *  Determines whether an executable exists in PATH.
 */
static bool checkExecutable(const std::string& exe)
{
#if defined(_WIN32)
    std::string cmd = "where " + exe + " >nul 2>nul";
#else
    std::string cmd = "command -v " + exe + " >/dev/null 2>&1";
#endif
    return (std::system(cmd.c_str()) == 0);
}

/* ---------------------------------------------------------
 *  DevEnvSetup
 * --------------------------------------------------------- */

class DevEnvSetup
{
public:
    explicit DevEnvSetup(std::string generator,
                         bool force = false)
        : generator_(std::move(generator))
        , forceReconfigure_(force)
    {}

    void run()
    {
        header();

        verifyPrerequisites();
        ensureFolders();
        cloneSubmodules();
        generateCMakeBuild();
        writeDotEnv();
        configureGitHooks();

        footer();
    }

private:
    std::string generator_;
    bool        forceReconfigure_;

    void header() const
    {
        term::color(term::GREEN);
        std::cout << "\n=== MosaicBoard Studio – Dev Environment Setup ===\n";
        term::reset();
    }

    void footer() const
    {
        term::color(term::GREEN);
        std::cout << "\nSetup completed successfully. Happy hacking!\n";
        term::reset();
    }

    /* --------------------------------------------------- */
    /* Step 1 – Tool-chain validation                      */
    /* --------------------------------------------------- */

    void verifyPrerequisites() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[1/5] Verifying required tooling…\n";
        term::reset();

        struct Requirement { std::string exe; std::string friendlyName; };
        const std::vector<Requirement> reqs = {
            {"git",   "Git"},
            {"cmake", "CMake"},
            {"ninja", "Ninja ‑ optional (recommended)"},
        };

        for (const auto& r : reqs)
        {
            bool found = checkExecutable(r.exe);
            std::cout << "  • " << std::left << std::setw(8) << r.friendlyName
                      << ": " << (found ? "found" : "NOT found") << "\n";

            if (!found && r.exe != "ninja")
            {
                term::color(term::RED);
                throw std::runtime_error(r.friendlyName + " is required but not found in PATH.");
            }
        }
    }

    /* --------------------------------------------------- */
    /* Step 2 – Project folder structure                   */
    /* --------------------------------------------------- */

    void ensureFolders() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[2/5] Creating runtime folders…\n";
        term::reset();

        const std::vector<fs::path> folders = {
            "plugins",
            "cache",
            "logs",
            "build"
        };

        for (const fs::path& p : folders)
        {
            if (!fs::exists(p))
            {
                std::cout << "  • creating " << p << "\n";
                fs::create_directory(p);
            }
            else
            {
                std::cout << "  • " << p << " already present\n";
            }

            // simple write test
            std::ofstream testFile(p / ".touch", std::ios::out | std::ios::trunc);
            if (!testFile.is_open())
            {
                term::color(term::RED);
                throw std::runtime_error("Cannot write to directory: " + p.string());
            }
            testFile.close();
            fs::remove(p / ".touch");
        }
    }

    /* --------------------------------------------------- */
    /* Step 3 – Git sub-module handling                    */
    /* --------------------------------------------------- */

    void cloneSubmodules() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[3/5] Updating git submodules…\n";
        term::reset();

        runProcess("git submodule update --init --recursive");
    }

    /* --------------------------------------------------- */
    /* Step 4 – Build configuration                        */
    /* --------------------------------------------------- */

    void generateCMakeBuild() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[4/5] Configuring CMake project…\n";
        term::reset();

        fs::path buildDir = "build";
        fs::path cacheFile = buildDir / "CMakeCache.txt";

        if (fs::exists(cacheFile) && !forceReconfigure_)
        {
            std::cout << "  • build directory already configured – skipping (use --force to regenerate)\n";
            return;
        }

        std::string cmakeCmd = std::format(
            "cmake -S . -B {} -G \"{}\" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            buildDir.string(),
            generator_);

#if defined(_WIN32)
        cmakeCmd += " -DCMAKE_BUILD_TYPE=RelWithDebInfo";
#else
        cmakeCmd += " -DCMAKE_BUILD_TYPE=Debug";
#endif

        runProcess(cmakeCmd);
    }

    /* --------------------------------------------------- */
    /* Step 5 – .env file                                  */
    /* --------------------------------------------------- */

    void writeDotEnv() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[5/5] Writing .env file…\n";
        term::reset();

        std::ofstream env(".env", std::ios::out | std::ios::trunc);
        if (!env)
        {
            term::color(term::RED);
            throw std::runtime_error("Failed to create .env file.");
        }

        env << "# Auto-generated by setup_dev_env.cpp – DO NOT EDIT MANUALLY\n";
        env << "MOS_BOARD_ENV=development\n";
        env << "MOS_BOARD_CACHE_DIR=" << fs::absolute("cache").string() << "\n";
        env << "MOS_BOARD_PLUGIN_DIR=" << fs::absolute("plugins").string() << "\n";
        env << "MOS_BOARD_LOG_DIR=" << fs::absolute("logs").string() << "\n";
        env.close();

        std::cout << "  • .env written\n";
    }

    /* --------------------------------------------------- */
    /* Git hooks                                           */
    /* --------------------------------------------------- */

    void configureGitHooks() const
    {
        term::color(term::YELLOW);
        std::cout << "\n[+] Installing pre-commit hooks…\n";
        term::reset();

        fs::path hooksDir = ".git/hooks";
        fs::path hook     = hooksDir / "pre-commit";

        const std::string script =
            "#!/bin/sh\n"
            "echo \"Running clang-format on C++ source files…\"\n"
            "git diff --cached --name-only | grep -E '\\.(hpp|cpp|cc|cxx)$' | "
            "xargs clang-format -i\n"
            "git add $(git diff --cached --name-only | grep -E '\\.(hpp|cpp|cc|cxx)$')\n";

        if (!fs::exists(hooksDir))
        {
            term::color(term::RED);
            std::cerr << "  ! .git/hooks missing – are we in a git repository?\n";
            term::reset();
            return;
        }

        std::ofstream preCommit(hook, std::ios::out | std::ios::trunc);
        preCommit << script;
        preCommit.close();

#if defined(_WIN32)
        // Windows: rely on git's internal execution
#else
        fs::permissions(hook,
                        fs::perms::owner_exec | fs::perms::owner_write | fs::perms::owner_read |
                        fs::perms::group_exec | fs::perms::group_read |
                        fs::perms::others_exec | fs::perms::others_read,
                        fs::perm_options::add);
#endif
        std::cout << "  • pre-commit hook installed\n";
    }
};

/* ---------------------------------------------------------
 *  Main
 * --------------------------------------------------------- */

static void printUsage(const char* exe)
{
    std::cout << "Usage: " << exe << " [--force] [--generator=<gen>] [--help]\n\n"
              << "  --force               Regenerate the build directory even if it exists.\n"
              << "  --generator=<gen>     Pass a custom CMake generator (default: \""
              << DEFAULT_GENERATOR << "\").\n"
              << "  --help                Show this help message.\n";
}

int main(int argc, char* argv[])
{
    std::string generator = DEFAULT_GENERATOR;
    bool force = false;

    for (int i = 1; i < argc; ++i)
    {
        std::string arg(argv[i]);
        if (arg == "--help" || arg == "-h")
        {
            printUsage(argv[0]);
            return EXIT_SUCCESS;
        }
        else if (arg == "--force")
        {
            force = true;
        }
        else if (arg.starts_with("--generator="))
        {
            generator = arg.substr(std::string("--generator=").length());
        }
        else
        {
            std::cerr << "Unknown argument: " << arg << "\n";
            printUsage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    try
    {
        DevEnvSetup setup(generator, force);
        setup.run();
    }
    catch (const ProcessError& e)
    {
        term::color(term::RED);
        std::cerr << "\nProcess failed: " << e.what() << "\n";
        term::reset();
        return e.exitCode;
    }
    catch (const std::exception& e)
    {
        term::color(term::RED);
        std::cerr << "\nError: " << e.what() << "\n";
        term::reset();
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
```