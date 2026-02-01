/*
 *  MosaicBoard Studio
 *  File: StringUtils.h
 *
 *  A header-only collection of high-performance, UTF-8 aware* string utilities
 *  used across the MosaicBoard Studio code-base (web_dashboard).
 *
 *  *Most utilities operate on raw bytes and therefore work with UTF-8 as long
 *   as code-points are not split. Locale-specific semantics (upper/lower-case
 *   conversions, collation rules, etc.) are intentionally simplified for the
 *   purpose of predictable, cross-platform behaviour in server environments.
 *
 *  Copyright (c) MosaicBoard Studio.
 *  SPDX-License-Identifier: MIT
 */

#ifndef MOSAICBOARD_STUDIO_UTILS_STRING_UTILS_H
#define MOSAICBOARD_STUDIO_UTILS_STRING_UTILS_H

#include <algorithm>
#include <cctype>
#include <charconv>
#include <iomanip>
#include <locale>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#if __has_include(<openssl/sha.h>)
    #include <openssl/sha.h>
    #define MBS_STRINGUTILS_HAS_OPENSSL 1
#else
    #define MBS_STRINGUTILS_HAS_OPENSSL 0
#endif

namespace mbs::utils {

/*───────────────────────────────────────────────────────────────────────────*/
/* Helper traits                                                            */
/*───────────────────────────────────────────────────────────────────────────*/

namespace detail {

template <typename T>
using is_string_like = std::disjunction<
    std::is_same<std::decay_t<T>, std::string>,
    std::is_same<std::decay_t<T>, std::string_view>,
    std::is_same<std::decay_t<T>, const char*>>;

template <typename T>
constexpr bool is_string_like_v = is_string_like<T>::value;

} // namespace detail

/*───────────────────────────────────────────────────────────────────────────*/
/* Fundamental utilities                                                    */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::string ltrim(std::string_view sv) {
    size_t first = 0;
    while (first < sv.size() && std::isspace(static_cast<unsigned char>(sv[first]))) {
        ++first;
    }
    return std::string{sv.substr(first)};
}

[[nodiscard]] inline std::string rtrim(std::string_view sv) {
    if (sv.empty()) return std::string{};
    size_t last = sv.size() - 1;
    while (last != std::string_view::npos &&
           std::isspace(static_cast<unsigned char>(sv[last]))) {
        if (last == 0) {  // reached beginning
            return std::string{};
        }
        --last;
    }
    return std::string{sv.substr(0, last + 1)};
}

[[nodiscard]] inline std::string trim(std::string_view sv) {
    return rtrim(ltrim(sv));
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Case conversion / comparison                                             */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::string toLower(std::string_view sv) {
    std::string out(sv.size(), '\0');
    std::transform(sv.begin(), sv.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

[[nodiscard]] inline std::string toUpper(std::string_view sv) {
    std::string out(sv.size(), '\0');
    std::transform(sv.begin(), sv.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return out;
}

[[nodiscard]] inline bool iequals(std::string_view lhs, std::string_view rhs) {
    if (lhs.size() != rhs.size()) return false;
    for (size_t i = 0; i < lhs.size(); ++i) {
        if (std::tolower(static_cast<unsigned char>(lhs[i])) !=
            std::tolower(static_cast<unsigned char>(rhs[i]))) {
            return false;
        }
    }
    return true;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Prefix / Suffix                                                          */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline bool startsWith(std::string_view str,
                                     std::string_view prefix,
                                     bool caseSensitive = true) {
    if (prefix.size() > str.size()) return false;
    if (caseSensitive) {
        return str.compare(0, prefix.size(), prefix) == 0;
    }
    return iequals(str.substr(0, prefix.size()), prefix);
}

[[nodiscard]] inline bool endsWith(std::string_view str,
                                   std::string_view suffix,
                                   bool caseSensitive = true) {
    if (suffix.size() > str.size()) return false;
    size_t offset = str.size() - suffix.size();
    if (caseSensitive) {
        return str.compare(offset, suffix.size(), suffix) == 0;
    }
    return iequals(str.substr(offset, suffix.size()), suffix);
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Splitting / Joining                                                      */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::vector<std::string> split(std::string_view sv,
                                                    char delimiter,
                                                    bool skipEmpty = true) {
    std::vector<std::string> tokens;
    size_t start = 0;
    while (start <= sv.size()) {
        size_t end = sv.find(delimiter, start);
        std::string_view part = sv.substr(start, end - start);
        if (!part.empty() || !skipEmpty) {
            tokens.emplace_back(part);
        }
        if (end == std::string_view::npos) break;
        start = end + 1;
    }
    return tokens;
}

[[nodiscard]] inline std::string join(const std::vector<std::string>& parts,
                                      std::string_view delimiter) {
    if (parts.empty()) return {};
    size_t totalSize = (parts.size() - 1) * delimiter.size();
    for (const auto& p : parts) totalSize += p.size();
    std::string out;
    out.reserve(totalSize);
    for (size_t i = 0; i < parts.size(); ++i) {
        out.append(parts[i]);
        if (i + 1 < parts.size()) out.append(delimiter);
    }
    return out;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Replacement / Searching                                                  */
/*───────────────────────────────────────────────────────────────────────────*/

inline void replaceAll(std::string& inout,
                       std::string_view search,
                       std::string_view replace) {
    if (search.empty()) return;
    size_t pos = 0;
    while ((pos = inout.find(search, pos)) != std::string::npos) {
        inout.replace(pos, search.size(), replace);
        pos += replace.size();
    }
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Numeric conversion helpers                                               */
/*───────────────────────────────────────────────────────────────────────────*/

template <typename Int,
          typename = std::enable_if_t<std::is_integral_v<Int>>>
[[nodiscard]] inline std::string toString(Int value) {
    char buf[32] = {0};
    auto res = std::to_chars(std::begin(buf), std::end(buf), value);
    if (res.ec != std::errc()) {
        throw std::runtime_error("toString: failed to convert integer");
    }
    return std::string{buf, static_cast<size_t>(res.ptr - buf)};
}

template <typename Int,
          typename = std::enable_if_t<std::is_integral_v<Int>>>
[[nodiscard]] inline std::optional<Int> toInt(std::string_view sv, int base = 10) {
    Int value{};
    auto res = std::from_chars(sv.data(), sv.data() + sv.size(), value, base);
    if (res.ec == std::errc()) {
        return value;
    }
    return std::nullopt;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Slugification (safe for URLs, file names)                                */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::string slugify(std::string_view sv,
                                         char dash = '-',
                                         bool toLowerCase = true) {
    std::string out;
    out.reserve(sv.size());
    for (unsigned char c : sv) {
        if (std::isalnum(c)) {
            out.push_back(toLowerCase ? static_cast<char>(std::tolower(c)) : c);
        } else if (c == ' ' || c == '_' || c == '-' || c == '.') {
            if (!out.empty() && out.back() != dash) {
                out.push_back(dash);
            }
        }
        // ignore the rest
    }
    // Remove trailing dash
    if (!out.empty() && out.back() == dash) out.pop_back();
    return out;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Safe substring (no out_of_range thrown)                                  */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::string safeSubstr(std::string_view sv,
                                            std::size_t pos,
                                            std::size_t count = std::string::npos) {
    if (pos >= sv.size()) return {};
    if (count == std::string::npos || pos + count > sv.size()) {
        count = sv.size() - pos;
    }
    return std::string{sv.substr(pos, count)};
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Secure hashing (SHA-256)                                                 */
/*───────────────────────────────────────────────────────────────────────────*/

[[nodiscard]] inline std::string sha256(std::string_view data) {
#if MBS_STRINGUTILS_HAS_OPENSSL
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, data.data(), data.size());
    SHA256_Final(hash, &ctx);

    std::ostringstream oss;
    for (unsigned char byte : hash) {
        oss << std::hex << std::setw(2) << std::setfill('0')
            << static_cast<int>(byte);
    }
    return oss.str();
#else
    // Fallback to std::hash (not cryptographically secure, but always available)
    auto hashed = std::hash<std::string_view>{}(data);
    std::ostringstream oss;
    oss << std::hex << hashed;
    return oss.str();
#endif
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Compile-time concatenation (constexpr)                                   */
/*───────────────────────────────────────────────────────────────────────────*/

template <size_t N1, size_t N2>
struct ConstexprString {
    char data[N1 + N2 - 1] = {};

    constexpr ConstexprString(const char (&s1)[N1], const char (&s2)[N2]) {
        std::copy_n(s1, N1 - 1, data);
        std::copy_n(s2, N2, data + N1 - 1);
    }
};

template <size_t N1, size_t N2>
ConstexprString(const char (&)[N1], const char (&)[N2]) -> ConstexprString<N1, N2>;

/*───────────────────────────────────────────────────────────────────────────*/
/* String builder (fluent API)                                              */
/*───────────────────────────────────────────────────────────────────────────*/

class StringBuilder {
public:
    StringBuilder() = default;

    template <typename T,
              typename = std::enable_if_t<!std::is_same_v<std::decay_t<T>, StringBuilder>>>
    StringBuilder& append(T&& value) {
        using V = std::decay_t<T>;
        if constexpr (detail::is_string_like_v<V>) {
            stream_ << std::string_view(value);
        } else if constexpr (std::is_arithmetic_v<V>) {
            stream_ << value;
        } else {
            static_assert(sizeof(V) == 0, "Unsupported type for StringBuilder::append");
        }
        return *this;
    }

    [[nodiscard]] std::string str() const { return stream_.str(); }

    operator std::string() const { return str(); }

private:
    std::ostringstream stream_;
};

/*───────────────────────────────────────────────────────────────────────────*/
/* Macro helpers                                                            */
/*───────────────────────────────────────────────────────────────────────────*/

#define MBS_STR_CONCAT(lhs, rhs)                                              \
    ([]() constexpr {                                                         \
        constexpr auto concat =                                                \
            mbs::utils::ConstexprString{lhs, rhs};                            \
        return std::string_view{concat.data, sizeof(concat.data)};            \
    }())

} // namespace mbs::utils

#endif // MOSAICBOARD_STUDIO_UTILS_STRING_UTILS_H