```cpp
/**
 *  FortiLedger360 – Enterprise Security Suite
 *  ------------------------------------------------------
 *  File:        scripts/build.cpp          (compiled output: fl360-build)
 *  Purpose:     Opinionated build-orchestration CLI invoked by CI/CD and
 *               local developers.  A thin wrapper around the host tool-chain
 *               (cmake/make, clang-tidy, cppcheck, unit-tests, packaging)
 *               with additional cross-platform niceties such as
 *               concurrency, YAML build-matrix support and colored logging.
 *
 *  Build:
 *      $ c++ -std=c++17 -pthread -Wall -Wextra -o fl360-build scripts/build.cpp
 *
 *  Typical usage:
 *      $ ./fl360-build --target domain infrastructure --parallel 6 --clean
 *
 *  --------------------------------------------------------------------------
 *  NOTE: This file lives in “scripts/” even though it is C++; our build
 *        convention distinguishes script-like utilities (Bash, Python, C++)
 *        from production micro-services which reside in /src.
 */

#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                SECTION 1 – Misc. Compile-time helpers                    ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
#if defined(_WIN32)
#   define popen  _popen
#   define pclose _pclose
constexpr const char* kOS = "windows";
#else
constexpr const char* kOS = "unix";
#endif

namespace fs = std::filesystem;

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                       SECTION 2 – Thread-safe logger                     ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
enum class LogLevel { TRACE, INFO, WARN, ERROR };

class Logger
{
public:
    explicit Logger(bool verbose) : verbose_(verbose) {}

    template<typename... Args>
    void log(LogLevel lvl, Args&&... parts)
    {
        if (!verbose_ && lvl == LogLevel::TRACE) { return; }

        std::lock_guard<std::mutex> lk(mu_);
        std::ostream& out = (lvl == LogLevel::ERROR) ? std::cerr : std::cout;
        out << ansiPrefix(lvl);
        (out << ... << parts) << ansiSuffix() << "\n";
    }

    void trace(auto&&... p) { log(LogLevel::TRACE, std::forward<decltype(p)>(p)...); }
    void info (auto&&... p) { log(LogLevel::INFO , std::forward<decltype(p)>(p)...); }
    void warn (auto&&... p) { log(LogLevel::WARN , std::forward<decltype(p)>(p)...); }
    void error(auto&&... p) { log(LogLevel::ERROR, std::forward<decltype(p)>(p)...); }

private:
    static const char* ansiPrefix(LogLevel lvl)
    {
        switch (lvl)
        {
            case LogLevel::TRACE: return "\033[90m[TRACE] ";
            case LogLevel::INFO : return "\033[32m[INFO ] ";
            case LogLevel::WARN : return "\033[33m[WARN ] ";
            case LogLevel::ERROR: return "\033[31m[ERROR] ";
        }
        return "";
    }
    static const char* ansiSuffix() { return "\033[0m"; }

    bool verbose_;
    std::mutex mu_;
};

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                   SECTION 3 – Utility / OS command helpers               ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
class Shell
{
public:
    static int run(const std::string& cmd, std::string* output = nullptr)
    {
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) { throw std::runtime_error("Unable to spawn shell command"); }

        char buffer[256];
        while (output && std::fgets(buffer, sizeof(buffer), pipe))
        {
            (*output) += buffer;
        }
        int rc = pclose(pipe);
        return rc;
    }
};

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                 SECTION 4 – Build-graph (targets & tasks)                ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
struct Target
{
    std::string name;             // e.g., "domain"
    fs::path     cmakeDir;        // CMakeLists.txt folder
    bool         enabled{true};   // can be toggled off by CLI
};

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║             SECTION 5 – Bounded thread-pool  (for parallel build)        ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
class ThreadPool
{
public:
    explicit ThreadPool(size_t limit) : stop_(false)
    {
        limit = std::max<size_t>(1, limit);
        for (size_t i = 0; i < limit; ++i)
        {
            workers_.emplace_back([this] {
                for (;;)
                {
                    std::function<void()> job;
                    {
                        std::unique_lock<std::mutex> lk(mu_);
                        cv_.wait(lk, [this] { return stop_ || !jobs_.empty(); });
                        if (stop_ && jobs_.empty())
                            return;
                        job = std::move(jobs_.front());
                        jobs_.pop();
                    }
                    job();
                }
            });
        }
    }

    ~ThreadPool()
    {
        {
            std::lock_guard<std::mutex> lk(mu_);
            stop_ = true;
        }
        cv_.notify_all();
        for (auto& t : workers_) { t.join(); }
    }

    void enqueue(std::function<void()> job)
    {
        {
            std::lock_guard<std::mutex> lk(mu_);
            jobs_.push(std::move(job));
        }
        cv_.notify_one();
    }

private:
    std::vector<std::thread>      workers_;
    std::queue<std::function<void()>> jobs_;
    std::mutex                    mu_;
    std::condition_variable       cv_;
    bool                          stop_;
};

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                SECTION 6 – Command-line option parsing                   ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
struct Options
{
    std::vector<std::string> targets;   // requested targets (empty => all)
    size_t parallelism{std::thread::hardware_concurrency()};
    bool   clean{false};
    bool   verbose{false};
};

static void usage(const char* prog)
{
    std::cout <<
        "FortiLedger360 Build Orchestrator\n"
        "---------------------------------\n"
        "Usage: " << prog << " [options]\n\n"
        "Options:\n"
        "  --target <t1> [t2 ...]   Build only the specified sub-projects\n"
        "  --parallel N             Maximum parallel jobs (default: #cores)\n"
        "  --clean                  Remove previous CMake build cache\n"
        "  --verbose                Chatty logging, incl. static-analysis output\n"
        "  -h, --help               Show this message\n\n"
        "Targets map to directories under /src: presentation, orchestration,\n"
        "domain, infrastructure, platform, tests.\n";
}

Options parseArgs(int argc, char* argv[])
{
    Options opt;
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--clean")      { opt.clean = true; }
        else if (arg == "--verbose"){ opt.verbose = true; }
        else if (arg == "--parallel" && i + 1 < argc)
        {
            opt.parallelism = std::stoul(argv[++i]);
        }
        else if (arg == "--target")
        {
            while (i + 1 < argc && argv[i + 1][0] != '-')
                opt.targets.emplace_back(argv[++i]);
        }
        else if (arg == "-h" || arg == "--help")
        {
            usage(argv[0]);
            std::exit(EXIT_SUCCESS);
        }
        else
        {
            throw std::invalid_argument("Unknown option: " + arg);
        }
    }
    return opt;
}

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                   SECTION 7 – Build logic implementation                 ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
class Builder
{
public:
    Builder(Options opt, Logger& lg)
        : opt_(std::move(opt)), log_(lg), pool_(opt_.parallelism) {}

    int run()
    {
        discoverTargets();
        if (opt_.clean) { cleanAll(); }

        size_t submitted = 0;
        for (const auto& t : targets_)
        {
            if (!t.enabled) { continue; }
            ++submitted;
            pool_.enqueue([this, &t] { buildTarget(t); });
        }

        if (submitted == 0)
        {
            log_.warn("No matching targets to build.");
            return EXIT_FAILURE;
        }
        return EXIT_SUCCESS; // destructor waits for pool completion
    }

private:
    void discoverTargets()
    {
        static const std::vector<std::string> canonical = {
            "presentation", "orchestration", "domain",
            "infrastructure", "platform", "tests"
        };
        fs::path srcRoot = fs::current_path() / "src";
        for (const auto& dir : canonical)
        {
            Target t;
            t.name     = dir;
            t.cmakeDir = srcRoot / dir;
            if (!fs::exists(t.cmakeDir / "CMakeLists.txt"))
            {
                log_.warn("Skipping target '", dir, "' – missing CMakeLists.txt");
                t.enabled = false;
            }
            if (!opt_.targets.empty())
            {
                t.enabled = (std::find(opt_.targets.begin(),
                                       opt_.targets.end(),
                                       dir) != opt_.targets.end());
            }
            targets_.emplace_back(std::move(t));
        }
    }

    void cleanAll()
    {
        log_.info("Cleaning previous build directories...");
        for (const auto& t : targets_)
        {
            fs::path buildDir = t.cmakeDir / "build";
            if (fs::exists(buildDir))
            {
                log_.trace("Removing ", buildDir.string());
                std::error_code ec;
                fs::remove_all(buildDir, ec);
                if (ec) { log_.warn("Failed to remove ", buildDir.string(), ": ", ec.message()); }
            }
        }
    }

    void buildTarget(const Target& t)
    {
        std::string cmake = "cmake";
        std::string make  = (kOS == std::string("windows")) ? "cmake --build ." : "make -j";
        fs::path buildDir = t.cmakeDir / "build";
        fs::create_directories(buildDir);

        std::string cmd_configure = "cd " + buildDir.string() + " && " + cmake +
                                    " .. -DCMAKE_EXPORT_COMPILE_COMMANDS=ON";
        std::string cmd_build     = "cd " + buildDir.string() + " && " + make;
        std::string cmd_tidy      = "clang-tidy -p=" + buildDir.string() +
                                    " $(find " + t.cmakeDir.string() +
                                    " -name '*.cpp' -not -path '*/build/*')";
        std::string cmd_cppcheck  = "cppcheck --enable=all --quiet "
                                    "--project=" + (buildDir / "compile_commands.json").string();

        log_.info("▶ Building target '", t.name, "' ...");
        execOrThrow(cmd_configure, "configure");
        execOrThrow(cmd_build    , "compile");

        if (opt_.verbose)
        {
            execOrWarn(cmd_tidy    , "clang-tidy");
            execOrWarn(cmd_cppcheck, "cppcheck");
        }

        log_.info("✔ Finished target '", t.name, "'");
    }

    void execOrThrow(const std::string& cmd, const char* stage)
    {
        log_.trace("Executing (", stage, "): ", cmd);
        int rc = Shell::run(cmd);
        if (rc != 0)
        {
            throw std::runtime_error(std::string(stage) + " failed for command: " + cmd);
        }
    }

    void execOrWarn(const std::string& cmd, const char* stage)
    {
        log_.trace("Executing (", stage, "): ", cmd);
        std::string output;
        int rc = Shell::run(cmd, &output);
        if (rc != 0)
        {
            log_.warn(stage, " returned non-zero (", rc, ")\n", output);
        }
        else
        {
            log_.trace(output);
        }
    }

    Options                 opt_;
    Logger&                 log_;
    ThreadPool              pool_;
    std::vector<Target>     targets_;
};

/* ╔══════════════════════════════════════════════════════════════════════════╗
 * ║                               SECTION 8 – main                           ║
 * ╚══════════════════════════════════════════════════════════════════════════╝ */
int main(int argc, char* argv[])
{
    try
    {
        Options opt = parseArgs(argc, argv);
        Logger  logger(opt.verbose);

        Builder builder(opt, logger);
        return builder.run();
    }
    catch (const std::exception& ex)
    {
        std::cerr << "\033[31mFatal: " << ex.what() << "\033[0m\n";
        usage(argv[0]);
        return EXIT_FAILURE;
    }
}
```
