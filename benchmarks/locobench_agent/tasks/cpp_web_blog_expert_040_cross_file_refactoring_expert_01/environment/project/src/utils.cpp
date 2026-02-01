```cpp
/**
 * utils.cpp
 * IntraLedger BlogSuite
 *
 * A collection of miscellaneous helpers that are used across the entire
 * application. All helpers are located under the
 * intraledger::blogsuite::utils namespace to avoid name clashes.  Whenever a
 * helper requires an external dependency, that dependency should already be
 * available in the global compilation unit (e.g. spdlog, fmt).
 */

#include "utils.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iterator>
#include <random>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

#include <fmt/format.h>   // External dependency (header-only)
#include <spdlog/spdlog.h> // External dependency (header-only)

#if defined(__linux__) || defined(__APPLE__)
    #include <unistd.h>
#elif defined(_WIN32)
    #include <windows.h>
    #include <bcrypt.h>
    #pragma comment(lib, "bcrypt.lib")
#endif


namespace intraledger::blogsuite::utils {

// -------------------------------------------------------------
// String helpers
// -------------------------------------------------------------

// Trim helpers (internal)
namespace {
    inline void ltrim_in_place(std::string& s)
    {
        s.erase(s.begin(),
                std::find_if(s.begin(), s.end(),
                             [](unsigned char c) { return !std::isspace(c); }));
    }

    inline void rtrim_in_place(std::string& s)
    {
        s.erase(std::find_if(s.rbegin(), s.rend(),
                             [](unsigned char c) { return !std::isspace(c); })
                    .base(),
                s.end());
    }
} // namespace

std::string trim(std::string_view input)
{
    std::string s{input};
    ltrim_in_place(s);
    rtrim_in_place(s);
    return s;
}

std::string to_lower(std::string_view input)
{
    std::string out{input};
    std::transform(out.begin(), out.end(), out.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

std::string generate_slug(std::string_view input)
{
    // Basic slug generator. Removes non-alphanumeric characters, collapses
    // whitespace into single hyphens, and converts to lowercase.
    //
    // Example:   "  Hello, World! " -> "hello-world"
    //
    std::string working = trim(input);
    working             = to_lower(working);

    // Replace all non-alphanumeric characters with spaces
    std::replace_if(working.begin(), working.end(),
                    [](unsigned char c) {
                        return !(std::isalnum(c) || c == ' ');
                    },
                    ' ');

    // Collapse sequences of whitespace into a single hyphen
    std::stringstream ss;
    bool               last_was_space = false;
    for (unsigned char c : working)
    {
        if (std::isspace(c))
        {
            if (!last_was_space)
            {
                ss << '-';
                last_was_space = true;
            }
        }
        else
        {
            ss << c;
            last_was_space = false;
        }
    }

    std::string result = ss.str();

    // Remove leading/trailing hyphens
    if (!result.empty() && result.front() == '-')
        result.erase(result.begin());
    if (!result.empty() && result.back() == '-')
        result.pop_back();

    return result;
}

// -------------------------------------------------------------
// Environment helpers
// -------------------------------------------------------------

std::string getenv_or(std::string_view key, std::string_view default_val)
{
    const char* val = std::getenv(std::string{key}.c_str());
    return val ? std::string{val} : std::string{default_val};
}

bool getenv_to_bool(std::string_view key, bool default_val)
{
    const auto raw = getenv_or(key, default_val ? "1" : "0");
    if (raw == "1" || raw == "true" || raw == "TRUE" || raw == "yes")
        return true;
    if (raw == "0" || raw == "false" || raw == "FALSE" || raw == "no")
        return false;
    spdlog::warn("Invalid boolean value for env var '{}': '{}', falling back to default ({})",
                 key, raw, default_val);
    return default_val;
}

// -------------------------------------------------------------
// Randomness helpers
// -------------------------------------------------------------

namespace {

    constexpr size_t UUID_NUM_BYTES = 16; // 128-bit UUID

    // Platform-specific cryptographically secure generator
    void secure_random_bytes(std::span<std::byte> buffer)
    {
#if defined(__linux__) || defined(__APPLE__)
        ssize_t read_bytes = ::getentropy(buffer.data(), buffer.size());
        if (read_bytes == -1)
            throw std::runtime_error("getentropy() failed to fetch random bytes");
#elif defined(_WIN32)
        if (BCryptGenRandom(nullptr,
                            reinterpret_cast<PUCHAR>(buffer.data()),
                            static_cast<ULONG>(buffer.size()),
                            BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
            throw std::runtime_error("BCryptGenRandom() failed to fetch random bytes");
#else
    #error "Secure random generator not implemented for this platform."
#endif
    }
} // namespace

std::array<std::byte, UUID_NUM_BYTES> random_bytes()
{
    std::array<std::byte, UUID_NUM_BYTES> buf{};
    secure_random_bytes(buf);
    return buf;
}

std::string uuid_v4()
{
    /*  RFC 4122 §4.4 (Algorithm)
        -------------------------------------------------
        - Set all the version bits to 0100
        - Set the variant bits to 10xx
    */

    auto bytes = random_bytes();

    // Set version (byte 6)
    bytes[6] &= static_cast<std::byte>(0x0F);
    bytes[6] |= static_cast<std::byte>(0x40);

    // Set variant (byte 8)
    bytes[8] &= static_cast<std::byte>(0x3F);
    bytes[8] |= static_cast<std::byte>(0x80);

    // Convert to canonical textual representation
    const uint8_t* d = reinterpret_cast<const uint8_t*>(bytes.data());
    return fmt::format("{:02x}{:02x}{:02x}{:02x}-"
                       "{:02x}{:02x}-"
                       "{:02x}{:02x}-"
                       "{:02x}{:02x}-"
                       "{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
                       d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8],
                       d[9], d[10], d[11], d[12], d[13], d[14], d[15]);
}

// -------------------------------------------------------------
// Time helpers
// -------------------------------------------------------------

std::string iso8601_now()
{
    using namespace std::chrono;

    auto        now      = system_clock::now();
    std::time_t now_time = system_clock::to_time_t(now);

    std::tm tm{};
#if defined(_WIN32)
    if (gmtime_s(&tm, &now_time) != 0)
        throw std::runtime_error("gmtime_s failed");
#else
    if (!gmtime_r(&now_time, &tm))
        throw std::runtime_error("gmtime_r failed");
#endif

    // Format: YYYY-MM-DDTHH:MM:SSZ
    char buf[32];
    if (std::strftime(buf, sizeof(buf), "%FT%TZ", &tm) == 0)
        throw std::runtime_error("strftime failed");

    return std::string{buf};
}

// -------------------------------------------------------------
// Filesystem helpers
// -------------------------------------------------------------

std::filesystem::path path_join(const std::filesystem::path& base,
                                std::initializer_list<std::string_view> segments)
{
    std::filesystem::path out = base;
    for (auto&& seg : segments)
        out /= seg;
    return out;
}

bool atomic_file_write(const std::filesystem::path& target,
                       std::string_view            data,
                       std::filesystem::perms      perms)
{
    // Write to a temporary file in the same directory, then rename.
    auto tmp = target.parent_path() /
               fmt::format(".{}.tmp-{}", target.filename().string(), uuid_v4());

    try
    {
        {
            std::ofstream ofs(tmp, std::ios::binary | std::ios::trunc);
            if (!ofs)
            {
                spdlog::error("Failed to open temp file for atomic write: {}", tmp.string());
                return false;
            }
            ofs.write(data.data(), static_cast<std::streamsize>(data.size()));
            ofs.flush();
            ofs.close();
            std::filesystem::permissions(tmp, perms, std::filesystem::perm_options::replace);
        }

        std::filesystem::rename(tmp, target);
        return true;
    }
    catch (const std::exception& ex)
    {
        spdlog::error("atomic_file_write failed (target={}): {}", target.string(), ex.what());
        // Best-effort cleanup
        std::error_code ec;
        std::filesystem::remove(tmp, ec);
        return false;
    }
}

// -------------------------------------------------------------
// Validation helpers
// -------------------------------------------------------------

bool is_valid_email(std::string_view email)
{
    static const std::regex pattern(
        R"(^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$)",
        std::regex::ECMAScript | std::regex::icase);

    return std::regex_match(email.begin(), email.end(), pattern);
}

} // namespace intraledger::blogsuite::utils
```