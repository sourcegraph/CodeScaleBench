#include "constants.hpp"

#include <cstdlib>              // std::getenv
#include <ctime>                // std::time, std::tm, localtime_r/s
#include <filesystem>           // std::filesystem::path
#include <iomanip>              // std::put_time
#include <mutex>                // std::call_once, std::once_flag
#include <sstream>              // std::ostringstream
#include <string>               // std::string
#include <string_view>          // std::string_view

namespace web_blog::constants {

// -----------------------------------------------------------------------------
// Version information
// -----------------------------------------------------------------------------
Version::Version(int maj, int min, int pat, std::string build_meta)
    : major(maj)
    , minor(min)
    , patch(pat)
    , build(std::move(build_meta)) {}

std::string Version::toString() const
{
    std::ostringstream oss;
    oss << major << '.' << minor << '.' << patch;
    if (!build.empty()) {
        oss << '-' << build;
    }
    return oss.str();
}

// NOTE: Update these three integers and optional build string on every release.
const Version kVersion{1, 0, 0, ""};

// -----------------------------------------------------------------------------
// Compile-time string constants
// -----------------------------------------------------------------------------
constexpr std::string_view kAppName       = "IntraLedger BlogSuite";
constexpr std::string_view kAppCodename   = "web_blog";
constexpr std::string_view kCompanyName   = "IntraLedger";

constexpr std::string_view kDefaultLocale  = "en_US";
constexpr std::string_view kDefaultCharset = "UTF-8";

// Environment variable keys
constexpr std::string_view kEnvConfigDir = "BLOGSUITE_CONFIG_DIR";
constexpr std::string_view kEnvLogLevel  = "BLOGSUITE_LOG_LEVEL";
constexpr std::string_view kEnvDbUrl     = "BLOGSUITE_DB_URL";
constexpr std::string_view kEnvSecretKey = "BLOGSUITE_SECRET_KEY";

// HTTP headers & MIME types
constexpr std::string_view kHeaderAuthorization = "Authorization";
constexpr std::string_view kHeaderContentType   = "Content-Type";
constexpr std::string_view kMimeJSON            = "application/json";

// Input validation patterns (ECMA-262 compatible)
constexpr std::string_view kEmailPattern = R"(^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$)";
constexpr std::string_view kSlugPattern  = R"(^[a-z0-9]+(?:-[a-z0-9]+)*$)";

// -----------------------------------------------------------------------------
// Internal helpers
// -----------------------------------------------------------------------------
namespace {

// Computes the configuration base directory, considering platform and user
// overrides.
inline std::filesystem::path computeConfigHome()
{
    // 1. Explicit override via environment variable
    if (const char* env_dir = std::getenv(std::string(kEnvConfigDir).c_str());
        env_dir && *env_dir) {
        return std::filesystem::path{env_dir};
    }

#if defined(_WIN32)
    // 2. Windows default: %USERPROFILE%\AppData\Local\web_blog
    const char* home = std::getenv("USERPROFILE");
    std::filesystem::path base = home ? home : std::filesystem::temp_directory_path();
    return base / "AppData" / "Local" / std::string(kAppCodename);
#else
    // 2. POSIX default: $HOME/.config/web_blog
    const char* home = std::getenv("HOME");
    std::filesystem::path base = home ? home : std::filesystem::temp_directory_path();
    return base / ".config" / std::string(kAppCodename);
#endif
}

} // anonymous namespace

// -----------------------------------------------------------------------------
// Publicly exposed helpers
// -----------------------------------------------------------------------------
const std::filesystem::path& configHome()
{
    static std::once_flag init_flag;
    static std::filesystem::path cached;

    std::call_once(init_flag, [] {
        try {
            cached = computeConfigHome();
            std::filesystem::create_directories(cached);
        } catch (const std::exception&) {
            // Fallback to system temp directory if creation failed
            cached = std::filesystem::temp_directory_path() / std::string(kAppCodename);
        }
    });

    return cached;
}

const std::filesystem::path& defaultConfigFile()
{
    static std::once_flag init_flag;
    static std::filesystem::path cached;

    std::call_once(init_flag, [] {
        cached = configHome() / "config.yaml";
    });

    return cached;
}

const std::string& userAgent()
{
    static std::string cached = [] {
        std::ostringstream oss;
        oss << kAppCodename << '/' << kVersion.toString();

        // Append build date for traceability
        std::time_t now = std::time(nullptr);
        std::tm tm {};
#if defined(_WIN32)
        localtime_s(&tm, &now);
#else
        localtime_r(&now, &tm);
#endif
        oss << " (" << std::put_time(&tm, "%Y-%m-%d") << ')';
        return oss.str();
    }();

    return cached;
}

} // namespace web_blog::constants