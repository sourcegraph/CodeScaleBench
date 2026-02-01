```cpp
// tests/test_utils.cpp
//
// Unit–tests for several low–level helpers that power the
// IntraLedger BlogSuite core.
//
// These utilities do not expose any application specific
// state and are therefore re-implemented inside the test
// translation unit to keep the sample self-contained and
// fully compilable.
//
// The tests are written with Catch2 v3 (single-header).
// ----------------------------------------------------------------------------

#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iterator>
#include <optional>
#include <random>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_set>
#include <vector>

namespace utils {

// -----------------------------------------------------------------------------
// slugify
// -----------------------------------------------------------------------------
/**
 * Convert a human-readable title into an SEO-friendly slug.
 *
 * Rules:
 *  • Lower-case ASCII letters and digits are kept unchanged.
 *  • Upper-case ASCII letters are lower-cased.
 *  • Any other character becomes a hyphen (‘-’).
 *  • Multiple successive hyphens are collapsed.
 *  • Leading/trailing hyphens are trimmed.
 *
 * Thread-safe and allocation-free (aside from the std::string result).
 */
inline std::string slugify(std::string_view input) {
    std::string out;
    out.reserve(input.size());

    auto push_hyphen = [&]() {
        if (!out.empty() && out.back() != '-') { out.push_back('-'); }
    };

    for (char ch : input) {
        if (std::isalnum(static_cast<unsigned char>(ch))) {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
        } else {
            push_hyphen();
        }
    }
    // Trim trailing hyphens
    while (!out.empty() && out.back() == '-') { out.pop_back(); }
    // Trim leading hyphens
    if (!out.empty() && out.front() == '-') { out.erase(out.begin()); }

    return out;
}

// -----------------------------------------------------------------------------
// Constant-time string comparison
// -----------------------------------------------------------------------------
/**
 * Perform constant-time comparison of two byte strings.
 * Returns true when equal, false otherwise.
 */
inline bool safe_compare(std::string_view a, std::string_view b) noexcept {
    if (a.size() != b.size()) { return false; }
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        diff |= static_cast<unsigned char>(a[i]) ^ static_cast<unsigned char>(b[i]);
    }
    return diff == 0;
}

// -----------------------------------------------------------------------------
// URL encode / decode
// -----------------------------------------------------------------------------
inline bool is_unreserved(unsigned char c) {
    return std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~';
}

inline std::string url_encode(std::string_view plain) {
    std::ostringstream oss;
    oss << std::hex << std::uppercase;
    for (unsigned char c : plain) {
        if (is_unreserved(c)) {
            oss << c;
        } else {
            oss << '%' << std::setw(2) << std::setfill('0') << static_cast<int>(c);
        }
    }
    return oss.str();
}

inline std::optional<std::string> url_decode(std::string_view encoded) {
    std::string out;
    out.reserve(encoded.size());
    for (size_t i = 0; i < encoded.size();) {
        char c = encoded[i];
        if (c == '%') {
            if (i + 2 >= encoded.size()) { return std::nullopt; }
            int value = 0;
            std::from_chars(encoded.data() + i + 1, encoded.data() + i + 3, value, 16);
            out.push_back(static_cast<char>(value));
            i += 3;
        } else {
            out.push_back(c);
            ++i;
        }
    }
    return out;
}

// -----------------------------------------------------------------------------
// Base64 encode / decode (RFC 4648, no padding optional decode)
// -----------------------------------------------------------------------------
namespace detail {
static constexpr std::string_view b64_table =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
} // namespace detail

inline std::string base64_encode(std::string_view input) {
    std::string out;
    size_t i = 0;
    const auto tbl = detail::b64_table;
    while (i < input.size()) {
        uint32_t octet_a = i < input.size() ? static_cast<unsigned char>(input[i++]) : 0;
        uint32_t octet_b = i < input.size() ? static_cast<unsigned char>(input[i++]) : 0;
        uint32_t octet_c = i < input.size() ? static_cast<unsigned char>(input[i++]) : 0;

        uint32_t triple = (octet_a << 16) | (octet_b << 8) | octet_c;

        out.push_back(tbl[(triple >> 18) & 0x3F]);
        out.push_back(tbl[(triple >> 12) & 0x3F]);
        out.push_back(i - 2 < input.size() ? tbl[(triple >> 6) & 0x3F] : '=');
        out.push_back(i - 1 < input.size() ? tbl[triple & 0x3F] : '=');
    }
    return out;
}

inline std::optional<std::string> base64_decode(std::string_view input) {
    if (input.size() % 4 != 0) { return std::nullopt; }

    auto decode_char = [](char c) -> int {
        if ('A' <= c && c <= 'Z') { return c - 'A'; }
        if ('a' <= c && c <= 'z') { return c - 'a' + 26; }
        if ('0' <= c && c <= '9') { return c - '0' + 52; }
        if (c == '+') { return 62; }
        if (c == '/') { return 63; }
        return -1;
    };

    std::string out;
    out.reserve((input.size() * 3) / 4);

    for (size_t i = 0; i < input.size(); i += 4) {
        int a = decode_char(input[i]);
        int b = decode_char(input[i + 1]);
        if (a < 0 || b < 0) { return std::nullopt; }

        int c = (input[i + 2] == '=') ? 0 : decode_char(input[i + 2]);
        int d = (input[i + 3] == '=') ? 0 : decode_char(input[i + 3]);

        if (c < 0 || d < 0) { return std::nullopt; }

        uint32_t triple = (a << 18) | (b << 12) | (c << 6) | d;

        out.push_back(static_cast<char>((triple >> 16) & 0xFF));
        if (input[i + 2] != '=') {
            out.push_back(static_cast<char>((triple >> 8) & 0xFF));
        }
        if (input[i + 3] != '=') {
            out.push_back(static_cast<char>(triple & 0xFF));
        }
    }
    return out;
}

// -----------------------------------------------------------------------------
// Token generator (non-cryptographic, suitable for tests only).
// -----------------------------------------------------------------------------
inline std::string random_token(size_t len = 32) {
    static thread_local std::mt19937_64 rng{
        static_cast<uint64_t>(std::chrono::steady_clock::now().time_since_epoch().count()) ^
        reinterpret_cast<uintptr_t>(&rng)};
    static constexpr std::array<char, 62> alphabet = {
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"};
    std::uniform_int_distribution<size_t> dist(0, alphabet.size() - 1);
    std::string out(len, '\0');
    std::generate(out.begin(), out.end(), [&]() { return alphabet[dist(rng)]; });
    return out;
}

} // namespace utils

// ============================================================================
//                                  Tests
// ============================================================================
TEST_CASE("Slugify converts complex titles into URL-friendly slugs", "[utils][slugify]") {
    using utils::slugify;

    SECTION("Plain ASCII letters") {
        REQUIRE(slugify("Hello World") == "hello-world");
    }

    SECTION("Removes punctuation and trims hyphens") {
        REQUIRE(slugify("  --C++ & The Art of Coding!!  ") == "c-the-art-of-coding");
    }

    SECTION("Collapses consecutive separators") {
        REQUIRE(slugify("one---two___three   four") == "one-two-three-four");
    }

    SECTION("Empty string returns empty slug") {
        REQUIRE(slugify("").empty());
    }
}

TEST_CASE("URL encode/decoders operate symmetrically", "[utils][url]") {
    using utils::url_decode;
    using utils::url_encode;

    const std::string original =
        "email=foo+bar@example.com&title=Hello World!&tags=c++ std::string";

    const auto encoded = url_encode(original);
    const auto decoded = url_decode(encoded);

    REQUIRE(decoded.has_value());
    REQUIRE(*decoded == original);

    // Spot check that spaces and special characters are percent-encoded.
    REQUIRE(encoded.find("%20") != std::string::npos);
    REQUIRE(encoded.find("@") == std::string::npos);
}

TEST_CASE("Base64 encode/decoders round-trip arbitrary binary blobs", "[utils][b64]") {
    using utils::base64_decode;
    using utils::base64_encode;

    std::vector<uint8_t> binary_blob(256);
    std::iota(binary_blob.begin(), binary_blob.end(), 0);

    const std::string_view data{
        reinterpret_cast<const char*>(binary_blob.data()), binary_blob.size()};

    auto encoded = base64_encode(data);
    auto decoded = base64_decode(encoded);

    REQUIRE(decoded.has_value());
    REQUIRE(decoded->size() == data.size());
    REQUIRE(std::equal(decoded->begin(), decoded->end(), data.begin()));
}

TEST_CASE("safe_compare operates in constant-time for identical lengths", "[utils][secure]") {
    using utils::safe_compare;

    const std::string a = "secret-value-1";
    const std::string b = "secret-value-1";
    const std::string c = "secret-value-2";

    REQUIRE(safe_compare(a, b));
    REQUIRE_FALSE(safe_compare(a, c));
}

TEST_CASE("random_token yields unique strings across threads", "[utils][token][thread]") {
    constexpr size_t kThreadCount   = 8;
    constexpr size_t kTokensPerThread = 1000;

    std::vector<std::thread> workers;
    std::mutex               mtx;
    std::unordered_set<std::string> tokens;
    tokens.reserve(kThreadCount * kTokensPerThread);

    auto worker_fn = [&](size_t) {
        for (size_t i = 0; i < kTokensPerThread; ++i) {
            auto tok = utils::random_token();
            std::lock_guard<std::mutex> lk(mtx);
            tokens.insert(std::move(tok));
        }
    };

    for (size_t t = 0; t < kThreadCount; ++t) {
        workers.emplace_back(worker_fn, t);
    }
    for (auto& th : workers) { th.join(); }

    // Expect no collisions.
    REQUIRE(tokens.size() == kThreadCount * kTokensPerThread);
}
```