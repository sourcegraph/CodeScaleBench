/*
 *  IntraLedger BlogSuite — Content Sanitizer Service
 *  --------------------------------------------------
 *  Production-grade HTML sanitization utility used prior to content persistence
 *  and rendering.  Relies on Gumbo (HTML5) for robust parsing and rejects any
 *  tag/attribute combination that is not strictly allowed.  Makes an extremely
 *  conservative pass on inline styles/JS and neutralises XSS vectors such as
 *  “javascript:” or “data:” URL schemes.
 *
 *  SPDX-License-Identifier: MIT
 */

#include <algorithm>
#include <cctype>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

// Third-party dependencies
#include <gumbo.h>              // https://github.com/google/gumbo-parser
#include <spdlog/spdlog.h>      // https://github.com/gabime/spdlog

namespace intraledger::blogsuite::service {

// ---------------------------------------------------------------------------
// ContentSanitizerService
// ---------------------------------------------------------------------------

class ContentSanitizerService {
public:
    struct Options {
        bool   allowImages        = true;   // Allow <img> tags
        bool   allowIframes       = false;  // Allow <iframe> tags
        size_t maxPlainTextLength = 0;      // For extractPlainText(); 0 == unlimited
    };

    // Thread-safe singleton accessor
    static ContentSanitizerService& instance()
    {
        static ContentSanitizerService singleton;
        return singleton;
    }

    // Sanitize the supplied HTML, returning a safe string
    std::string sanitize(const std::string& rawHtml,
                         const Options&    opts = Options{}) const;

    // Convenience helper that extracts plain text from HTML
    std::string extractPlainText(const std::string& rawHtml,
                                 size_t             maxLen = 0) const;

private:
    ContentSanitizerService()  = default;
    ~ContentSanitizerService() = default;

    ContentSanitizerService(const ContentSanitizerService&)            = delete;
    ContentSanitizerService(ContentSanitizerService&&)                 = delete;
    ContentSanitizerService& operator=(const ContentSanitizerService&) = delete;
    ContentSanitizerService& operator=(ContentSanitizerService&&)      = delete;

    //-----------------------------------------------------------------------
    // Implementation helpers
    //-----------------------------------------------------------------------
    static std::string escapeHtmlEntities(const std::string& text);
    static void        extractPlainTextRec(const GumboNode* node, std::string& out);

    static std::string sanitizeNode(const GumboNode*                                                node,
                                    const Options&                                                  opts,
                                    const std::unordered_set<GumboTag>&                            allowedTags,
                                    const std::unordered_map<GumboTag,
                                                             std::unordered_set<std::string>>&      allowedAttr);

    static std::string sanitizeAttributes(const GumboElement*                                       elem,
                                          const std::unordered_map<GumboTag,
                                                                   std::unordered_set<std::string>>& allowedAttr);

    // Pre-built immutable tag/attribute white-lists
    const std::unordered_set<GumboTag>& defaultAllowedTags() const;
    const std::unordered_map<GumboTag,
                             std::unordered_set<std::string>>& defaultAllowedAttributes() const;

    mutable std::once_flag _initFlag;
    mutable std::unordered_set<GumboTag>                       _defaultTags;
    mutable std::unordered_map<GumboTag,
                               std::unordered_set<std::string>> _defaultAttributes;
};

// ---------------------------------------------------------------------------
// Public interface implementation
// ---------------------------------------------------------------------------

std::string ContentSanitizerService::sanitize(const std::string& rawHtml,
                                              const Options&     opts) const
{
    if (rawHtml.empty())
        return {};

    // Parse HTML
    std::unique_ptr<GumboOutput, decltype(&gumbo_destroy_output)> output{
        gumbo_parse_with_options(&kGumboDefaultOptions, rawHtml.c_str(), rawHtml.length()),
        [](GumboOutput* o) { gumbo_destroy_output(&kGumboDefaultOptions, o); }};

    if (!output) {
        spdlog::error("Gumbo failed to parse HTML payload — returning empty string for safety.");
        return {};
    }

    // Merge default allowed tags with optional media tags
    std::unordered_set<GumboTag> allowedTags = defaultAllowedTags();
    if (opts.allowImages)  allowedTags.insert(GUMBO_TAG_IMG);
    if (opts.allowIframes) allowedTags.insert(GUMBO_TAG_IFRAME);

    try {
        return sanitizeNode(output->root, opts, allowedTags, defaultAllowedAttributes());
    } catch (const std::exception& ex) {
        spdlog::error("HTML sanitization failed: {}", ex.what());
        return {};
    }
}

std::string ContentSanitizerService::extractPlainText(const std::string& rawHtml,
                                                      size_t             maxLen) const
{
    if (rawHtml.empty())
        return {};

    std::unique_ptr<GumboOutput, decltype(&gumbo_destroy_output)> output{
        gumbo_parse(rawHtml.c_str()), [](GumboOutput* o) { gumbo_destroy_output(&kGumboDefaultOptions, o); }};

    if (!output) {
        spdlog::error("Gumbo failed to parse HTML for plain-text extraction.");
        return {};
    }

    std::string out;
    out.reserve(rawHtml.size());

    extractPlainTextRec(output->root, out);

    // Collapse consecutive whitespace
    out.erase(std::unique(out.begin(), out.end(), [](char a, char b) {
                  return std::isspace(static_cast<unsigned char>(a)) &&
                         std::isspace(static_cast<unsigned char>(b));
              }),
              out.end());

    // Trim leading/trailing whitespace
    const auto  notSpace = [](int ch) { return !std::isspace(ch); };
    out.erase(out.begin(), std::find_if(out.begin(), out.end(), notSpace));
    out.erase(std::find_if(out.rbegin(), out.rend(), notSpace).base(), out.end());

    // Enforce maximum length
    if (maxLen && out.length() > maxLen)
        out = out.substr(0, maxLen) + "...";

    return out;
}

// ---------------------------------------------------------------------------
// Static helpers
// ---------------------------------------------------------------------------

std::string ContentSanitizerService::escapeHtmlEntities(const std::string& text)
{
    std::string out;
    out.reserve(text.size());

    for (char ch : text) {
        switch (ch) {
        case '&': out += "&amp;";  break;
        case '<': out += "&lt;";   break;
        case '>': out += "&gt;";   break;
        case '\"': out += "&quot;"; break;
        case '\'': out += "&#x27;"; break;
        default:  out += ch;       break;
        }
    }
    return out;
}

void ContentSanitizerService::extractPlainTextRec(const GumboNode* node, std::string& out)
{
    if (!node) return;

    switch (node->type) {
    case GUMBO_NODE_TEXT:
    case GUMBO_NODE_WHITESPACE:
        out.append(node->v.text.text);
        out.push_back(' ');
        break;
    case GUMBO_NODE_ELEMENT: {
        const GumboElement* elem = &node->v.element;

        // Skip potentially malicious or non-visible nodes
        if (elem->tag == GUMBO_TAG_SCRIPT || elem->tag == GUMBO_TAG_STYLE)
            return;

        const GumboVector* children = &elem->children;
        for (unsigned int i = 0; i < children->length; ++i)
            extractPlainTextRec(static_cast<GumboNode*>(children->data[i]), out);

        // Append line break after block elements to preserve readability
        switch (elem->tag) {
        case GUMBO_TAG_P:
        case GUMBO_TAG_BR:
        case GUMBO_TAG_DIV:
        case GUMBO_TAG_LI:
        case GUMBO_TAG_TR:
            out.push_back('\n');
            break;
        default:
            break;
        }
    } break;
    default:
        break;
    }
}

std::string ContentSanitizerService::sanitizeNode(
    const GumboNode*                                                node,
    const Options&                                                  opts,
    const std::unordered_set<GumboTag>&                            allowedTags,
    const std::unordered_map<GumboTag,
                             std::unordered_set<std::string>>&      allowedAttr)
{
    if (!node) return {};

    switch (node->type) {
    case GUMBO_NODE_TEXT:
    case GUMBO_NODE_WHITESPACE:
        return escapeHtmlEntities(node->v.text.text);

    case GUMBO_NODE_COMMENT:
        // Strip HTML comments completely
        return {};

    case GUMBO_NODE_ELEMENT: {
        const GumboElement* elem = &node->v.element;
        GumboTag            tag  = elem->tag;

        // Ignore black-listed tags entirely (script/style etc.)
        if (tag == GUMBO_TAG_SCRIPT || tag == GUMBO_TAG_STYLE)
            return {};

        const bool allowed = allowedTags.find(tag) != allowedTags.end();

        std::ostringstream html;

        if (allowed) {
            const char* tagName = gumbo_normalized_tagname(tag);

            html << '<' << tagName
                 << sanitizeAttributes(elem, allowedAttr)
                 << '>';
        }

        // Serialize children
        const GumboVector* children = &elem->children;
        for (unsigned int i = 0; i < children->length; ++i)
            html << sanitizeNode(static_cast<GumboNode*>(children->data[i]),
                                 opts, allowedTags, allowedAttr);

        // Close tag for non-void elements
        static const std::unordered_set<GumboTag> voidTags = {
            GUMBO_TAG_AREA,   GUMBO_TAG_BASE, GUMBO_TAG_BR,  GUMBO_TAG_COL,
            GUMBO_TAG_EMBED,  GUMBO_TAG_HR,   GUMBO_TAG_IMG, GUMBO_TAG_INPUT,
            GUMBO_TAG_LINK,   GUMBO_TAG_META, GUMBO_TAG_PARAM,
            GUMBO_TAG_SOURCE, GUMBO_TAG_TRACK, GUMBO_TAG_WBR};

        if (allowed && voidTags.find(tag) == voidTags.end())
            html << "</" << gumbo_normalized_tagname(tag) << '>';

        return html.str();
    }

    default:
        return {};
    }
}

std::string ContentSanitizerService::sanitizeAttributes(
    const GumboElement* elem,
    const std::unordered_map<GumboTag,
                             std::unordered_set<std::string>>& allowedAttr)
{
    std::ostringstream out;
    const auto         attrIt   = allowedAttr.find(elem->tag);
    const bool         hasAttrs = attrIt != allowedAttr.end();

    const GumboVector* attrs = &elem->attributes;
    for (unsigned int i = 0; i < attrs->length; ++i) {
        GumboAttribute* attr = static_cast<GumboAttribute*>(attrs->data[i]);
        std::string     name = attr->name;
        std::string     val  = attr->value;

        // Skip event handlers & inline JS
        if (name.rfind("on", 0) == 0) continue;

        // Whitelist filter
        if (hasAttrs && attrIt->second.find(name) == attrIt->second.end())
            continue;

        // Neutralise dangerous URL schemes
        if ((name == "href" || name == "src") &&
            (val.rfind("javascript:", 0) == 0 || val.rfind("data:", 0) == 0))
            continue;

        // Convert double quotes to single quotes inside attribute values
        std::replace(val.begin(), val.end(), '\"', '\'');

        out << ' ' << name << "=\"" << val << '"';
    }
    return out.str();
}

// ---------------------------------------------------------------------------
// Lazy initialization of immutable white-lists
// ---------------------------------------------------------------------------

const std::unordered_set<GumboTag>& ContentSanitizerService::defaultAllowedTags() const
{
    std::call_once(_initFlag, [this]() {
        _defaultTags = {
            GUMBO_TAG_A,          GUMBO_TAG_P,      GUMBO_TAG_DIV,
            GUMBO_TAG_SPAN,       GUMBO_TAG_STRONG, GUMBO_TAG_EM,
            GUMBO_TAG_I,          GUMBO_TAG_U,      GUMBO_TAG_UL,
            GUMBO_TAG_OL,         GUMBO_TAG_LI,     GUMBO_TAG_BR,
            GUMBO_TAG_H1,         GUMBO_TAG_H2,     GUMBO_TAG_H3,
            GUMBO_TAG_H4,         GUMBO_TAG_H5,     GUMBO_TAG_H6,
            GUMBO_TAG_BLOCKQUOTE, GUMBO_TAG_CODE,   GUMBO_TAG_PRE};
    });
    return _defaultTags;
}

const std::unordered_map<GumboTag,
                         std::unordered_set<std::string>>&
ContentSanitizerService::defaultAllowedAttributes() const
{
    std::call_once(_initFlag, [this]() {
        _defaultAttributes = {
            {GUMBO_TAG_A, {"href", "title", "rel", "target"}},
            {GUMBO_TAG_IMG, {"src", "alt", "title", "width", "height"}},
            {GUMBO_TAG_IFRAME,
             {"src", "width", "height", "title", "allowfullscreen",
              "frameborder"}},
            {GUMBO_TAG_DIV, {"class", "style"}},
            {GUMBO_TAG_SPAN, {"class", "style"}},
        };
    });
    return _defaultAttributes;
}

} // namespace intraledger::blogsuite::service

// ---------------------------------------------------------------------------
// Convenience global accessor
// ---------------------------------------------------------------------------

namespace intraledger::blogsuite {

inline intraledger::blogsuite::service::ContentSanitizerService&
contentSanitizer()
{
    return service::ContentSanitizerService::instance();
}

} // namespace intraledger::blogsuite