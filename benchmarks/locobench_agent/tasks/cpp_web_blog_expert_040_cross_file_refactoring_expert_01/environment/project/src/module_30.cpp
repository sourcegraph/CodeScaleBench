```cpp
/**
 *  IntraLedger BlogSuite – Search Module
 *  File:        src/module_30.cpp
 *
 *  Description:
 *      Implements parsing of user-supplied search queries and generation of
 *      text snippets with match highlighting.  The code lives in the
 *      `blog::search` namespace and is deliberately self-contained so that
 *      it can be reused by both the HTTP REST controller and the asynchronous
 *      background workers that populate and refresh the search index.
 *
 *  Copyright:
 *      © 2024 IntraLedger Corp.  All rights reserved.
 */

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

#if __has_include(<fmt/core.h>)
    /* Prefer {fmt} for high-performance, i18n-ready string formatting. */
    #include <fmt/core.h>
    #define BS_FMT(...) ::fmt::format(__VA_ARGS__)
#else
    #define BS_FMT(...) (::blog::search::detail::basic_format(__VA_ARGS__))
#endif

namespace blog::search {

/* ---------------------------------------------------*
 *                 Forward Declarations               *
 *----------------------------------------------------*/

struct QueryToken;
struct SearchQuery;
class  SearchQueryParser;
class  SnippetHighlighter;

/* ---------------------------------------------------*
 *                     Utilities                      *
 *----------------------------------------------------*/

namespace detail
{
    /**
     *  Fallback formatter used only when libfmt is not available.
     *  NOTE: This is a very naïve replacement!
     */
    template <typename... Args>
    std::string basic_format(std::string_view fmt, Args&&... args)
    {
        std::ostringstream oss;
        ((oss << args), ...);
        return oss.str();
    }

    /* ---- Unicode-aware, ASCII-only fast-path helpers ---- */

    inline bool is_ascii(char c) noexcept { return static_cast<unsigned char>(c) < 0x80; }

    inline char ascii_tolower(char c) noexcept
    {
        return (c >= 'A' && c <= 'Z') ? static_cast<char>(c + 32) : c;
    }

    /**
     *  Fast case-fold for ASCII.  UTF-8 multibyte chars are left unchanged.
     */
    std::string to_lower_ascii(std::string_view sv)
    {
        std::string out;
        out.reserve(sv.size());
        for (char c : sv)
            out.push_back(is_ascii(c) ? ascii_tolower(c) : c);
        return out;
    }

    /* ---- Trim helpers ----------------------------------------------------- */

    constexpr bool is_space(char c) noexcept
    {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
               c == '\f' || c == '\v';
    }

    inline std::string_view ltrim(std::string_view sv)
    {
        std::size_t start = 0;
        while (start < sv.size() && is_space(sv[start])) ++start;
        return sv.substr(start);
    }

    inline std::string_view rtrim(std::string_view sv)
    {
        std::size_t end = sv.size();
        while (end > 0 && is_space(sv[end - 1])) --end;
        return sv.substr(0, end);
    }

    inline std::string_view trim(std::string_view sv)
    {
        return rtrim(ltrim(sv));
    }

    /* ---------------------------------------------------------------------- */

} // namespace detail

/* ---------------------------------------------------*
 *                      Logging                       *
 *----------------------------------------------------*/

/**
 *  Minimalistic logging macro.  In real production code this is routed
 *  through the project-wide structured logger (spdlog + OpenTelemetry).
 */
#ifndef BS_LOG_LEVEL
    #define BS_LOG_LEVEL 3        /* 0-OFF, 1-ERROR, 2-WARN, 3-INFO, 4-DEBUG */
#endif

#if BS_LOG_LEVEL >= 4
    #define BS_LOG_DEBUG(msg, ...)   puts(BS_FMT("DEBUG: " msg, __VA_ARGS__).c_str())
#else
    #define BS_LOG_DEBUG(msg, ...)   ((void)0)
#endif

#if BS_LOG_LEVEL >= 3
    #define BS_LOG_INFO(msg, ...)    puts(BS_FMT("INFO : " msg, __VA_ARGS__).c_str())
#else
    #define BS_LOG_INFO(msg, ...)    ((void)0)
#endif

#if BS_LOG_LEVEL >= 2
    #define BS_LOG_WARN(msg, ...)    puts(BS_FMT("WARN : " msg, __VA_ARGS__).c_str())
#else
    #define BS_LOG_WARN(msg, ...)    ((void)0)
#endif

#if BS_LOG_LEVEL >= 1
    #define BS_LOG_ERROR(msg, ...)   puts(BS_FMT("ERROR: " msg, __VA_ARGS__).c_str())
#else
    #define BS_LOG_ERROR(msg, ...)   ((void)0)
#endif

/* ---------------------------------------------------*
 *                   Core Structures                  *
 *----------------------------------------------------*/

/**
 *  QueryToken
 *  ----------
 *  Represents a single token extracted from the raw user query.
 */
struct QueryToken
{
    std::string raw;       // Preserves original case
    std::string folded;    // Lower-cased ASCII for faster matching
    bool         negated {false};
    bool         quoted  {false};

    explicit QueryToken(std::string_view word, bool neg = false, bool quote = false)
        : raw(word), folded(detail::to_lower_ascii(word)), negated(neg), quoted(quote)
    {}
};

/**
 *  SearchQuery
 *  -----------
 *  Holds all tokens as well as optional filters parsed out from a query.
 */
struct SearchQuery
{
    std::vector<QueryToken> tokens;

    /* Optional structured filters, e.g. `author:alice tag:cpp` */
    std::optional<std::string> author;
    std::unordered_set<std::string> tags;
    std::optional<std::pair<std::uint64_t, std::uint64_t>> dateRange; // epoch ms

    [[nodiscard]]
    bool empty() const noexcept { return tokens.empty() && !author && tags.empty(); }
};

/* ---------------------------------------------------*
 *                SearchQueryParser                   *
 *----------------------------------------------------*/

/**
 *  SearchQueryParser
 *  -----------------
 *  Stateless utility class that parses a free-form user string into a
 *  structured SearchQuery.
 *
 *  Grammar (simplified):
 *      query      := [ term | filter ]*
 *      term       := ['-']? ( QUOTED | WORD )
 *      filter     := key ':' value
 *      QUOTED     := '"' .*? '"'
 *      WORD       := [^ \t\n\r\f\v]+
 */
class SearchQueryParser
{
public:
    SearchQuery parse(std::string_view input) const
    {
        BS_LOG_DEBUG("Parsing query: '{}'", input);

        SearchQuery q;
        std::size_t idx  = 0;
        const auto len   = input.size();

        auto consume_space = [&]()
        {
            while (idx < len && detail::is_space(input[idx])) ++idx;
        };

        while (idx < len)
        {
            consume_space();
            if (idx >= len) break;

            bool negated = false;
            if (input[idx] == '-')
            {
                negated = true;
                ++idx;
            }

            if (input[idx] == '"')            /* Quoted phrase ------------------- */
            {
                const std::size_t start = ++idx;   // skip opening quote
                while (idx < len && input[idx] != '"') ++idx;

                if (idx >= len)
                    throw std::runtime_error("Unterminated quoted string in search query");

                auto phrase = input.substr(start, idx - start);
                ++idx;                           // skip closing quote

                q.tokens.emplace_back(phrase, negated, /*quoted=*/true);
            }
            else                                /* Word or filter ----------------- */
            {
                const std::size_t start = idx;
                while (idx < len && !detail::is_space(input[idx]))
                    ++idx;

                auto word = input.substr(start, idx - start);
                const auto colonPos = word.find(':');

                if (colonPos != std::string_view::npos && !negated)
                {
                    /* ---- Handle filter key:value -------------------------------- */
                    const auto key   = word.substr(0, colonPos);
                    const auto value = word.substr(colonPos + 1);

                    if (key == "author")
                    {
                        q.author = std::string(value);
                    }
                    else if (key == "tag" || key == "tags")
                    {
                        q.tags.insert(std::string(value));
                    }
                    else if (key == "date")
                    {
                        parseDateRange(value, q);
                    }
                    else
                    {
                        BS_LOG_WARN("Unknown filter ignored: '{}'", key);
                    }
                }
                else if (!word.empty())
                {
                    q.tokens.emplace_back(word, negated, /*quoted=*/false);
                }
            }
        }

        BS_LOG_DEBUG("Parsed {} tokens, {} tag filters, author set? {}",
                     q.tokens.size(), q.tags.size(), q.author.has_value());

        return q;
    }

private:
    /* date=FROM-TO, where each part is YYYYMMDD (local time). */
    static void parseDateRange(std::string_view value, SearchQuery& q)
    {
        const auto dash = value.find('-');
        if (dash == std::string_view::npos)
        {
            BS_LOG_WARN("Invalid date range '{}', expected FROM-TO", value);
            return;
        }

        const auto fromStr = value.substr(0, dash);
        const auto toStr   = value.substr(dash + 1);

        auto yyyymmdd_to_epoch = [](std::string_view s) -> std::optional<std::uint64_t>
        {
            if (s.size() != 8) return std::nullopt;
            int y{}, m{}, d{};
            if (std::from_chars(s.data(), s.data() + 4, y).ec != std::errc{} ||
                std::from_chars(s.data() + 4, s.data() + 6, m).ec != std::errc{} ||
                std::from_chars(s.data() + 6, s.data() + 8, d).ec != std::errc{})
                return std::nullopt;

            std::tm t {};
            t.tm_year = y - 1900;
            t.tm_mon  = m - 1;
            t.tm_mday = d;
            t.tm_isdst = -1;

            std::time_t epoch = timegm(&t);               // UTC
            if (epoch == -1) return std::nullopt;

            return static_cast<std::uint64_t>(epoch) * 1000ULL;
        };

        const auto fromEpoch = yyyymmdd_to_epoch(fromStr);
        const auto toEpoch   = yyyymmdd_to_epoch(toStr);

        if (fromEpoch && toEpoch && *fromEpoch <= *toEpoch)
            q.dateRange = std::pair{*fromEpoch, *toEpoch};
        else
            BS_LOG_WARN("Invalid date filter '{}'", value);
    }
};

/* ---------------------------------------------------*
 *                SnippetHighlighter                  *
 *----------------------------------------------------*/

/**
 *  SnippetHighlighter
 *  ------------------
 *  Produces a context snippet from a source text with HTML-escaped highlighting
 *  of matched tokens.  Portions are ellipsised (…) if the snippet would exceed
 *  the requested length.
 *
 *  Example:
 *      source :  "The quick brown fox jumps over the lazy dog"
 *      tokens :  [ "quick", "fox" ]
 *      output :  "... <b>quick</b> brown <b>fox</b> jumps ..."
 */
class SnippetHighlighter
{
public:
    explicit SnippetHighlighter(std::size_t desiredLen = 160)
        : m_desiredLen(desiredLen)
    {}

    std::string makeSnippet(std::string_view source,
                            const std::vector<QueryToken>& tokens) const
    {
        if (source.empty() || tokens.empty())
            return escapeHtml(source.substr(0, m_desiredLen));

        // Pre-compute folded query tokens for case-insensitive search.
        std::vector<std::string> needles;
        needles.reserve(tokens.size());
        for (const auto& tk : tokens)
        {
            if (!tk.negated)   // Highlight only positive tokens
                needles.emplace_back(tk.folded);
        }
        if (needles.empty())
            return escapeHtml(source.substr(0, m_desiredLen));

        /* ---- Locate the earliest match ------------------------------------ */
        const auto foldedSrc = detail::to_lower_ascii(source);
        std::size_t firstPos = std::string::npos;
        std::size_t firstLen = 0;
        for (const auto& needle : needles)
        {
            const auto pos = foldedSrc.find(needle);
            if (pos != std::string::npos && (pos < firstPos || firstPos == std::string::npos))
            {
                firstPos = pos;
                firstLen = needle.length();
            }
        }
        if (firstPos == std::string::npos)
            return escapeHtml(source.substr(0, m_desiredLen)); // No match at all

        /* ---- Determine snippet start -------------------------------------- */
        const std::size_t context = m_desiredLen / 4;   // Expose some leading context
        std::size_t start = (firstPos > context) ? firstPos - context : 0;
        std::size_t end   = std::min(start + m_desiredLen, source.size());

        std::string snippet;
        if (start > 0)
            snippet.append("… ");

        /* ---- Build snippet with HTML escaping & highlighting -------------- */
        std::size_t idx = start;
        const auto push_escaped = [&](char c) { snippet.append(escapeHtmlChar(c)); };

        while (idx < end)
        {
            bool matched = false;
            for (const auto& needle : needles)
            {
                if (idx + needle.size() <= source.size() &&
                    foldedSrc.compare(idx, needle.size(), needle) == 0)
                {
                    snippet.append("<b>");
                    for (std::size_t k = 0; k < needle.size(); ++k)
                        push_escaped(source[idx + k]);
                    snippet.append("</b>");
                    idx += needle.size();
                    matched = true;
                    break;
                }
            }

            if (!matched)
            {
                push_escaped(source[idx]);
                ++idx;
            }
        }

        if (end < source.size())
            snippet.append(" …");

        return snippet;
    }

private:
    std::size_t m_desiredLen;

    /* ---------------------------------------------------------------------- */
    /*                      HTML-escaping helpers                             */
    /* ---------------------------------------------------------------------- */

    static std::string escapeHtml(std::string_view sv)
    {
        std::string out;
        out.reserve(sv.size());
        for (char c : sv)
            out.append(escapeHtmlChar(c));
        return out;
    }

    static std::string_view escapeHtmlChar(char c)
    {
        switch (c)
        {
            case '&':  return "&amp;";
            case '<':  return "&lt;";
            case '>':  return "&gt;";
            case '"':  return "&quot;";
            case '\'': return "&#x27;";
            case '/':  return "&#x2F;";
            default:   return std::string_view(&c, 1);
        }
    }
};

/* ---------------------------------------------------*
 *                     Unit Tests                     *
 *----------------------------------------------------*/
/*  NOTE: For brevity, we embed lightweight assertions.
 *        In production a full Catch2 / GoogleTest suite is used.
 *-------------------------------------------------------------------------*/
#ifdef MODULE_30_SELFTEST
#include <cassert>

static void selftest()
{
    SearchQueryParser parser;
    SearchQuery q = parser.parse(R"(quick fox tag:animals author:alice -lazy)");

    assert(q.tokens.size() == 3);
    assert(q.author.value() == "alice");
    assert(q.tags.contains("animals"));

    SnippetHighlighter hi(40);
    std::string sn = hi.makeSnippet("The quick brown fox jumps over the lazy dog", q.tokens);
    assert(sn.find("<b>quick</b>") != std::string::npos);
    assert(sn.find("<b>fox</b>") != std::string::npos);
    assert(sn.size() <= 45);
}

int main()
{
    selftest();
    puts("module_30.cpp self-test OK");
}
#endif

} // namespace blog::search
```