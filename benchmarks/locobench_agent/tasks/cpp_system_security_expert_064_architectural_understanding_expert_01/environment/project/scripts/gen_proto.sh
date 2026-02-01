```cpp
/*
 * FortiLedger360 Enterprise Security Suite
 * ----------------------------------------
 * File:    scripts/gen_proto.sh   (yes, despite the suffix this is C++)
 * Author:  Platform Engineering – Code-Automation Guild
 *
 * Purpose:
 *   Unified, cross-platform “protoc” wrapper that discovers all *.proto files
 *   under the repository, validates their dependencies, and emits language
 *   bindings (C++, Go, Python, TypeScript, …) with deterministic, hermetic
 *   builds.  The executable is intended to be invoked by CI/CD pipelines,
 *   local developers, or other build-orchestration scripts.
 *
 * Build:
 *   c++ -std=c++17 -O2 -Wall -Wextra -pedantic -o gen_proto scripts/gen_proto.sh
 *
 * Usage:
 *   ./gen_proto                                  # Default settings
 *   ./gen_proto --lang cpp --lang go             # Generate only specific langs
 *   ./gen_proto --proto-path ./idl --out build   # Override defaults
 *
 * Notes:
 *   • We purposefully ship C++ code in a file with “.sh” extension because
 *     certain legacy build steps treat everything inside /scripts as a shell
 *     script.  The she-bang below will seamlessly hand execution over to the
 *     compiled binary if it is already present; otherwise it will compile
 *     itself on-the-fly.
 *   • Dependencies: Only a C++17 compiler, “protoc”, and relevant language
 *     plugins (e.g., “protoc-gen-grpc-cpp”).
 *
 * SPDX-License-Identifier: BUSL-1.1
 */

/*
 * ────────────────────────────────────────────────────────────────────────────
 * Self-Compiling She-Bang
 * ────────────────────────────────────────────────────────────────────────────
 *
 * When executed directly (`bash scripts/gen_proto.sh`), the shell interprets
 * ONLY this short block until the terminating “EOF”.  It compiles the file
 * into a binary next to it and then executes the binary with the original
 * command-line arguments.  Any subsequent code is invisible to the shell.
 */
#ifdef __unix__
/*
 * The `:;` makes the rest of the line a no-op for the shell but valid C++.
 * The `exec` replaces the shell with the compiled binary.
 */
:; g++ -std=c++17 -O2 -Wall -Wextra -s "$0" -o "${0%.sh}" \
    && exec "${0%.sh}" "$@"
#endif
// EOF – end of shell section, beginning of real C++ =========================

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>
#include <unordered_map>
#include <vector>

#ifdef _WIN32
#    include <windows.h>
#endif

namespace fs = std::filesystem;

/* ────────────────────────────────────────────────────────────────────────── */
namespace fl360::proto_gen {

/***********************************************************************
 * Utility: Basic colourised logging
 ***********************************************************************/
enum class Level { INFO, WARN, ERROR, DEBUG };

class Logger {
public:
    static void log(Level lvl, const std::string &msg) {
        static const std::unordered_map<Level, std::string> kColour{
            {Level::INFO,  "\033[32m"},
            {Level::WARN,  "\033[33m"},
            {Level::ERROR, "\033[31m"},
            {Level::DEBUG, "\033[36m"}};

        static const std::unordered_map<Level, std::string> kLabel{
            {Level::INFO,  "INFO "},
            {Level::WARN,  "WARN "},
            {Level::ERROR, "ERROR"},
            {Level::DEBUG, "DEBUG"}};

        std::lock_guard<std::mutex> lock(mutex_);
        std::cerr << kColour.at(lvl)
                  << "[" << timeString() << "] "
                  << kLabel.at(lvl) << ": "
                  << msg
                  << "\033[0m" << '\n';
    }

    static void setVerbose(bool on) { verbose_ = on; }

private:
    static std::string timeString() {
        auto now   = std::chrono::system_clock::now();
        auto epoch = std::chrono::system_clock::to_time_t(now);

        std::ostringstream oss;
        oss << std::put_time(std::localtime(&epoch), "%F %T");
        return oss.str();
    }

    static std::mutex mutex_;
    static bool       verbose_;
};

std::mutex Logger::mutex_;
bool        Logger::verbose_ = false;

/***********************************************************************
 * Cross-platform `which` / `where` command
 ***********************************************************************/
std::optional<fs::path> findExecutable(const std::string &exeName) {
#ifdef _WIN32
    char *pathEnv = nullptr;
    size_t len    = 0;
    _dupenv_s(&pathEnv, &len, "PATH");
    std::string pathStr(pathEnv ? pathEnv : "");
    free(pathEnv);

    const char kPathSep = ';';
    const std::vector<std::string> extensions = {".exe", ".bat", ".cmd"};
#else
    std::string pathStr = std::getenv("PATH") ? std::getenv("PATH") : "";
    const char kPathSep = ':';
    const std::vector<std::string> extensions = {""};
#endif

    std::istringstream iss(pathStr);
    std::string        token;
    while (std::getline(iss, token, kPathSep)) {
        for (const auto &ext : extensions) {
            fs::path candidate = fs::path(token) / (exeName + ext);
            if (fs::exists(candidate) && fs::is_regular_file(candidate)) {
                return fs::canonical(candidate);
            }
        }
    }
    return std::nullopt;
}

/***********************************************************************
 * Simple argument parser
 ***********************************************************************/
struct Options {
    std::set<std::string> languages     = {"cpp", "grpc"};
    fs::path              protoPath     = "proto";
    fs::path              outputDir     = "build/generated";
    bool                  verifyOnly    = false;
    bool                  cleanOutput   = false;
    bool                  verbose       = false;
};

class ArgParseError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

Options parseArgs(int argc, char **argv) {
    Options opt;

    auto requireValue = [&](int &idx) {
        if (idx + 1 >= argc) {
            throw ArgParseError("Missing value for argument " +
                                std::string(argv[idx]));
        }
        return std::string(argv[++idx]);
    };

    for (int i = 1; i < argc; ++i) {
        std::string arg(argv[i]);

        if (arg == "--proto-path") {
            opt.protoPath = requireValue(i);
        } else if (arg == "--out" || arg == "-o") {
            opt.outputDir = requireValue(i);
        } else if (arg == "--lang") {
            opt.languages.insert(requireValue(i));
        } else if (arg == "--verify") {
            opt.verifyOnly = true;
        } else if (arg == "--clean") {
            opt.cleanOutput = true;
        } else if (arg == "--verbose" || arg == "-v") {
            opt.verbose = true;
        } else if (arg == "--help" || arg == "-h") {
            std::cout <<
                "FortiLedger360 Protocol Buffer Generator\n\n"
                "Options:\n"
                "  --proto-path <dir>  Root directory for .proto files  (default: proto)\n"
                "  --out, -o   <dir>   Output directory                (default: build/generated)\n"
                "  --lang      <lang>  Target language (repeatable). Valid: cpp, go, py, ts, grpc\n"
                "  --verify            Validate only; do not generate artifacts\n"
                "  --clean             Remove previous generated files before run\n"
                "  --verbose, -v       Verbose output\n"
                "  --help, -h          Show this message\n";
            std::exit(0);
        } else {
            throw ArgParseError("Unknown argument: " + arg);
        }
    }

    return opt;
}

/***********************************************************************
 * ProtocInvoker – orchestrates protoc commands in parallel
 ***********************************************************************/
class ProtocInvoker {
public:
    explicit ProtocInvoker(const Options &opt)
        : options_(opt)
    {
        if (auto exe = findExecutable("protoc")) {
            protocPath_ = *exe;
        } else {
            throw std::runtime_error("Unable to locate 'protoc' in PATH");
        }

        // Determine plugins if gRPC support requested
        if (options_.languages.count("grpc")) {
            if (auto plugin = findExecutable("grpc_cpp_plugin")) {
                grpcPluginPath_ = *plugin;
            } else {
                throw std::runtime_error("Unable to locate 'grpc_cpp_plugin' in PATH");
            }
        }
    }

    void run() {
        Logger::setVerbose(options_.verbose);

        if (!fs::exists(options_.protoPath))
            throw std::runtime_error("proto-path does not exist: " +
                                     options_.protoPath.string());

        collectProtoFiles();
        if (protoFiles_.empty()) {
            Logger::log(Level::WARN, "No .proto files found – nothing to do.");
            return;
        }

        if (options_.cleanOutput && fs::exists(options_.outputDir)) {
            Logger::log(Level::INFO, "Cleaning output directory: " +
                                     options_.outputDir.string());
            fs::remove_all(options_.outputDir);
        }

        if (options_.verifyOnly) {
            verify();
        } else {
            compile();
        }
    }

private:
    void collectProtoFiles() {
        Logger::log(Level::INFO,
                    "Scanning " + options_.protoPath.string() +
                    " for .proto files…");
        for (const auto &entry :
             fs::recursive_directory_iterator(options_.protoPath)) {
            if (entry.is_regular_file() &&
                entry.path().extension() == ".proto") {
                protoFiles_.push_back(fs::canonical(entry.path()));
            }
        }
        Logger::log(Level::INFO,
                    "Discovered " + std::to_string(protoFiles_.size()) +
                    " proto files.");
    }

    void verify() {
        Logger::log(Level::INFO, "Verifying proto compilation (dry-run)…");
        std::string cmd = buildCommand({}, /*verify=*/true);
        int         rc  = std::system(cmd.c_str());
        if (rc != 0) {
            throw std::runtime_error("protoc verification failed.");
        }
        Logger::log(Level::INFO, "All .proto files verified OK.");
    }

    void compile() {
        Logger::log(Level::INFO, "Generating artifacts…");

        // Create output dirs first
        fs::create_directories(options_.outputDir);

        // Build per-language command fragments
        std::vector<std::string> langFragments;

        for (const auto &lang : options_.languages) {
            if (lang == "cpp") {
                fs::path dir = options_.outputDir / "cpp";
                fs::create_directories(dir);
                langFragments.push_back("--cpp_out=" + dir.string());
            } else if (lang == "go") {
                fs::path dir = options_.outputDir / "go";
                fs::create_directories(dir);
                langFragments.push_back("--go_out=" + dir.string());
            } else if (lang == "py") {
                fs::path dir = options_.outputDir / "python";
                fs::create_directories(dir);
                langFragments.push_back("--python_out=" + dir.string());
            } else if (lang == "ts") {
                fs::path dir = options_.outputDir / "typescript";
                fs::create_directories(dir);
                langFragments.push_back("--js_out=import_style=commonjs,binary:" +
                                        dir.string());
                langFragments.push_back("--grpc-web_out=import_style=typescript,mode=grpcwebtext:" +
                                        dir.string());
            } else if (lang == "grpc") {
                fs::path dir = options_.outputDir / "cpp";
                fs::create_directories(dir);
                langFragments.push_back("--grpc_out=" + dir.string());
                langFragments.push_back("--plugin=protoc-gen-grpc=" +
                                        grpcPluginPath_.string());
            } else {
                Logger::log(Level::WARN, "Unknown language target: " + lang);
            }
        }

        // Build base command
        std::string baseCmd = buildCommand(langFragments, /*verify=*/false);

        // To speed things up we partition .proto files and run in parallel
        unsigned concurrency =
            std::min<unsigned>(std::thread::hardware_concurrency(), 8U);
        if (concurrency == 0) concurrency = 2;

        Logger::log(Level::DEBUG, "Using concurrency level: " +
                                  std::to_string(concurrency));

        std::vector<std::thread> workers;
        std::atomic_size_t       idx {0};

        auto worker = [&]() {
            while (true) {
                size_t i = idx.fetch_add(1);
                if (i >= protoFiles_.size()) break;

                std::string cmd = baseCmd + " " + protoFiles_[i].string();
                if (options_.verbose) {
                    Logger::log(Level::DEBUG, cmd);
                }
                int rc = std::system(cmd.c_str());
                if (rc != 0) {
                    Logger::log(Level::ERROR,
                                "protoc failed for file: " +
                                protoFiles_[i].string());
                    std::exit(rc);
                }
            }
        };

        for (unsigned t = 0; t < concurrency; ++t) {
            workers.emplace_back(worker);
        }
        for (auto &thr : workers) thr.join();

        Logger::log(Level::INFO, "Generation completed successfully.");
    }

    std::string buildCommand(const std::vector<std::string> &frag,
                             bool verify) const
    {
        std::ostringstream oss;
        oss << '"' << protocPath_.string() << '"';
        oss << " -I\"" << options_.protoPath.string() << '"';
        for (const auto &f : frag) {
            oss << " " << f;
        }
        if (verify) {
            // --dry_run is unofficial; instead redirect output to /dev/null
            oss << " --cpp_out=/dev/null";
        }
        return oss.str();
    }

    Options                options_;
    fs::path               protocPath_;
    fs::path               grpcPluginPath_;
    std::vector<fs::path>  protoFiles_;
};

} // namespace fl360::proto_gen

/* ────────────────────────────────────────────────────────────────────────── */
int main(int argc, char **argv) try {
    auto options = fl360::proto_gen::parseArgs(argc, argv);
    fl360::proto_gen::ProtocInvoker(options).run();
    return 0;
} catch (const fl360::proto_gen::ArgParseError &e) {
    fl360::proto_gen::Logger::log(fl360::proto_gen::Level::ERROR, e.what());
    return 64; // EX_USAGE
} catch (const std::exception &e) {
    fl360::proto_gen::Logger::log(fl360::proto_gen::Level::ERROR, e.what());
    return 1;
}
```
