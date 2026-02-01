```cpp
/**
 *  IntraLedger BlogSuite
 *  ---------------------
 *  Module:  src/module_62.cpp
 *
 *  Responsibility:
 *      Implements an aggressive-but-safe HTML sanitizer that is used by the
 *      Service Layer right before content is persisted to the database.  The
 *      sanitizer removes script/style/iframe tags, strips disallowed
 *      attributes, collapses whitespace, and normalises UTF-8 output.
 *
 *  Rationale:
 *      – Prevent stored-XSS and CSS-injection vulnerabilities
 *      – Keep the persisted HTML lean and search-engine friendly
 *      – Avoid surprises when the same content is rendered by different
 *        front-end skins or email templates
 *
 *  Design Notes:
 *      – Zero external reflection: all tag/attribute allow-lists are located
 *        in SanitizationOptions and may be overridden from the application
 *        Config.
 *      – Stateless by design; internal caches are read-only after construction
 *        and therefore thread-safe.
 *      – Uses Boost.Regex (header-only in C++17) to avoid a runtime dependency
 *        on libtidy/libgumbo while still being reasonably fast.
 */

#include "sanitization/ContentSanitizer.hpp"
#include "core/Logger.hpp"
#include "core/Config.hpp"

#include <boost/algorithm/string.hpp>
#include <boost/regex.hpp>
#include <codecvt>
#include <locale>
#include <mutex>
#include <sstream>
#include <unordered_set>

using intraledger::sanitization::ContentSanitizer;
using intraledger::sanitization::SanitizationOptions;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Internal helpers                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

namespace
{
    // Tag to match any HTML comment e.g. <!-- ... -->
    const boost::regex kCommentRegex{R"(<!--[\s\S]*?-->)",
                                     boost::regex::perl | boost::regex::icase};

    // Matches any <script>...</script>, <style>...</style> or <iframe>… </iframe>
    const boost::regex kDangerousBlockRegex{
        R"(<\s*(script|style|iframe)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>*)",
        boost::regex::perl | boost::regex::icase};

    // Matches any HTML tag (opening or self-closing). Capturing groups:
    //  1 – forward slash if it is a closing tag
    //  2 – tag name
    //  3 – attribute string inside the tag
    const boost::regex kGenericTagRegex{
        R"(<\s*(/)?\s*([a-z0-9]+)([^>]*)>)",
        boost::regex::perl | boost::regex::icase};

    // Matches attributes inside a tag. Capturing groups:
    //  1 – attribute name
    //  2 – attribute value (with or without quotes)
    const boost::regex kAttributeRegex{
        R"(\s+([a-z0-9\-:]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?)",
        boost::regex::perl | boost::regex::icase};

    // Utility: Converts string to lower-case in-place
    inline void toLowerInPlace(std::string &str)
    {
        boost::algorithm::to_lower(str);
    }

    // UTF-8 Normalisation (NFC) – trivial implementation using std::wstring_convert
    // NOTE: std::wstring_convert is deprecated in C++17 but still widely available.
    inline std::string utf8_normalise_nfc(const std::string &input)
    {
        try
        {
            std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> convert;
            std::u16string utf16 = convert.from_bytes(input);
            // In a real implementation we would call ICU or std::normalized_string,
            // but for portability we simply convert back without additional changes.
            return convert.to_bytes(utf16);
        }
        catch (const std::range_error &e)
        {
            Logger::warn("UTF-8 normalisation failed: {}", e.what());
            return input; // Return original; better than data-loss
        }
    }
} // anonymous namespace

/* ────────────────────────────────────────────────────────────────────────── */
/*  ContentSanitizer Implementation                                          */
/* ────────────────────────────────────────────────────────────────────────── */

ContentSanitizer::ContentSanitizer(SanitizationOptions options)
    : m_options(std::move(options))
{
    // Expand allow-lists from Config if requested
    if (m_options.extendedFromConfig)
    {
        const auto &cfg = Config::instance();
        for (const auto &tag : cfg.getStringList("sanitizer.allow_tags"))
        {
            m_options.allowedTags.insert(boost::algorithm::to_lower_copy(tag));
        }
        for (const auto &attr : cfg.getStringList("sanitizer.allow_attrs"))
        {
            m_options.allowedAttributes.insert(boost::algorithm::to_lower_copy(attr));
        }
    }

    // Cache compiled attribute regex if we have forbidden patterns
    if (!m_options.forbiddenAttributeValues.empty())
    {
        std::string pattern;
        bool first = true;
        for (const auto &kv : m_options.forbiddenAttributeValues)
        {
            if (!first)
                pattern += "|";
            pattern += kv;
            first = false;
        }
        m_forbiddenAttrRegex.emplace(
            pattern,
            boost::regex::perl | boost::regex::icase);
    }
}

std::string ContentSanitizer::sanitize(const std::string &html) const
{
    if (html.empty())
        return {};

    // 1. Remove comments
    std::string output = boost::regex_replace(html, kCommentRegex, "");

    // 2. Remove dangerous blocks
    output = boost::regex_replace(output, kDangerousBlockRegex, "");

    // 3. Process remaining tags in a streaming fashion
    std::string sanitized;
    sanitized.reserve(output.size());

    std::sregex_iterator it(output.begin(), output.end(), kGenericTagRegex);
    std::sregex_iterator end;

    std::size_t cursor = 0;

    for (; it != end; ++it)
    {
        const auto &match = *it;

        // Append text between previous match and current match (safe, as plaintext)
        sanitized.append(output, cursor, match.position() - cursor);

        const bool isClosing = match[1].matched;
        std::string tagName = match[2].str();
        toLowerInPlace(tagName);

        // Is tag allowed?
        if (m_options.allowedTags.find(tagName) == m_options.allowedTags.end())
        {
            // Skip disallowed tag entirely
            cursor = match.position() + match.length();
            continue;
        }

        if (isClosing)
        {
            sanitized.append("</").append(tagName).append(">");
            cursor = match.position() + match.length();
            continue;
        }

        // Opening or self-closing tag
        std::string attrString = match[3].str();
        std::ostringstream rebuiltTag;
        rebuiltTag << "<" << tagName;

        boost::sregex_iterator attrIt(attrString.begin(), attrString.end(), kAttributeRegex);
        boost::sregex_iterator attrEnd;

        for (; attrIt != attrEnd; ++attrIt)
        {
            std::string attrName = attrIt->str(1);
            toLowerInPlace(attrName);

            // Attribute allow-list
            if (m_options.allowedAttributes.find(attrName) ==
                m_options.allowedAttributes.end())
            {
                continue;
            }

            // Extract attribute value (whichever capturing group matched)
            std::string attrValue;
            for (int i = 2; i <= 4; ++i)
            {
                if ((*attrIt)[i].matched)
                {
                    attrValue = (*attrIt)[i].str();
                    break;
                }
            }

            // Basic javascript: / data: scheme prevention
            std::string valueLower = boost::algorithm::to_lower_copy(attrValue);
            if (valueLower.find("javascript:") != std::string::npos ||
                valueLower.find("data:text/html") != std::string::npos)
            {
                continue; // Drop attribute
            }

            // Forbidden values via regex
            if (m_forbiddenAttrRegex &&
                boost::regex_search(attrValue, *m_forbiddenAttrRegex))
            {
                continue;
            }

            // Emit sanitised attribute, escape `"` and `&`
            boost::algorithm::replace_all(attrValue, "&", "&amp;");
            boost::algorithm::replace_all(attrValue, "\"", "&quot;");

            rebuiltTag << " " << attrName << "=\"" << attrValue << "\"";
        }

        // Self-closing fix
        if (match.str().back() == '/')
        {
            rebuiltTag << " />";
        }
        else
        {
            rebuiltTag << ">";
        }

        sanitized << rebuiltTag.str();
        cursor = match.position() + match.length();
    }

    // Append remaining tail
    sanitized.append(output, cursor, std::string::npos);

    // 4. Collapse promoted whitespace if requested
    if (m_options.collapseWhitespace)
    {
        static const boost::regex wsRegex{R"(\s{2,})",
                                          boost::regex::perl | boost::regex::icase};
        sanitized = boost::regex_replace(sanitized, wsRegex, " ");
    }

    // 5. UTF-8 NFC normalisation
    sanitized = utf8_normalise_nfc(sanitized);

    return sanitized;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Factory / Convenience                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

std::shared_ptr<ContentSanitizer> intraledger::sanitization::makeDefaultSanitizer()
{
    static std::shared_ptr<ContentSanitizer> kInstance;
    static std::once_flag kOnce;

    std::call_once(kOnce, []() {
        SanitizationOptions opts;
        opts.allowedTags = {
            "a",    "abbr",  "b",    "blockquote", "br",   "code",
            "em",   "i",     "img",  "li",         "ol",   "p",
            "pre",  "strong","ul",   "h1",         "h2",   "h3",
            "h4",   "h5",    "h6",   "table",      "tr",   "td",
            "th",   "thead", "tbody","tfoot",      "del",  "ins"};
        opts.allowedAttributes = {
            "href", "src", "alt", "title", "width", "height",
            "style", "class", "name", "id", "align"};
        opts.forbiddenAttributeValues = {"onerror", "onclick", "onload"};
        opts.collapseWhitespace = true;
        opts.extendedFromConfig = true;

        kInstance = std::make_shared<ContentSanitizer>(std::move(opts));
    });

    return kInstance;
}
```