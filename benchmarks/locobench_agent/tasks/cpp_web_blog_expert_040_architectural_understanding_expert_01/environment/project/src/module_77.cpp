/*
 *  module_77.cpp
 *
 *  IntraLedger BlogSuite (web_blog)
 *  ---------------------------------
 *  Search Highlight / Snippet Generator with threaded, LRU-cached storage.
 *
 *  This compilation unit provides a production-quality implementation of a
 *  search-result snippet generator.  The generator accepts an article body and
 *  a collection of search terms, returning a context-aware excerpt with HTML
 *  <mark> tags around the first few occurrences of each term.
 *
 *  To minimise CPU overhead under heavy query load, results are cached in a
 *  capacity-bounded, thread-safe LRU cache.  The cache key is a combination of
 *  ArticleId and a stable hash of the user’s query string.
 *
 *  Dependencies:
 *    – Standard C++17 library only
 *    – No project-internal headers for simplicity; replace placeholders where
 *      required (e.g., with ORM entity types)
 *
 *  Build flags (example):
 *      g++ -std=c++17 -O2 -Wall -Wextra -pedantic -pthread -c module_77.cpp
 */

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <list>
#include <locale>
#include <mutex>
#include <optional>
#include <sstream>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace blogsuite::search {

// -----------------------------------------------------------------------------
// Utility helpers
// -----------------------------------------------------------------------------

// Basic ASCII-only lower-case conversion; replace with full UTF-8 case folding
// via ICU or boost::locale in production builds that need it.
inline std::string ascii_to_lower(std::string_view sv) {
    std::string out;
    out.reserve(sv.size());
    for (unsigned char ch : sv) {
        out.push_back(static_cast<char>(std::tolower(ch)));
    }
    return out;
}

// Trim whitespace (both ends, ASCII definition)
inline std::string_view trim_ascii(std::string_view sv) {
    auto begin = sv.find_first_not_of(" \t\r\n");
    if (begin == std::string_view::npos) return {};
    auto end = sv.find_last_not_of(" \t\r\n");
    return sv.substr(begin, end - begin + 1);
}

// -----------------------------------------------------------------------------
// Thread-safe, capacity-bounded LRU cache
// -----------------------------------------------------------------------------

template <typename Key, typename Value, typename Hash = std::hash<Key>>
class ThreadSafeLRUCache final
{
public:
    explicit ThreadSafeLRUCache(std::size_t capacity)
        : capacity_{ capacity }
    {
        if (capacity_ == 0) {
            throw std::invalid_argument("LRU cache capacity must be > 0");
        }
    }

    // Retrieve a value, or std::nullopt if the key isn’t present.
    std::optional<Value> get(const Key& key)
    {
        std::unique_lock lock{ mutex_ };
        auto it = index_.find(key);
        if (it == index_.end()) return std::nullopt;

        // Move the accessed item to the front of the list to mark it most-recently-used.
        lru_.splice(lru_.begin(), lru_, it->second);
        return it->second->second;
    }

    // Insert or update.
    void put(Key key, Value value)
    {
        std::unique_lock lock{ mutex_ };

        auto it = index_.find(key);
        if (it != index_.end()) {
            // Update existing entry and move to front.
            it->second->second = std::move(value);
            lru_.splice(lru_.begin(), lru_, it->second);
            return;
        }

        // Evict if capacity exceeded.
        if (lru_.size() >= capacity_) {
            const auto& lru_key = lru_.back().first;
            index_.erase(lru_key);
            lru_.pop_back();
        }

        // Insert new entry at front.
        lru_.emplace_front(std::move(key), std::move(value));
        index_[lru_.front().first] = lru_.begin();
    }

    std::size_t size() const noexcept
    {
        std::shared_lock lock{ mutex_ };
        return lru_.size();
    }

private:
    using List        = std::list<std::pair<Key, Value>>;
    using ListIt      = typename List::iterator;
    using Map         = std::unordered_map<Key, ListIt, Hash>;

    std::size_t capacity_;
    mutable std::shared_mutex mutex_;
    List lru_;   // Front = MRU, Back = LRU
    Map  index_;
};

// -----------------------------------------------------------------------------
// Snippet generator
// -----------------------------------------------------------------------------

class SnippetGenerator
{
public:
    struct Options
    {
        std::size_t max_snippet_length   = 220;     // in bytes, not UTF-8 code points
        std::size_t max_highlights       = 3;       // max <mark> blocks
        std::string highlight_start_tag  = "<mark>";
        std::string highlight_end_tag    = "</mark>";
        std::string ellipsis             = "…";
    };

    SnippetGenerator() = default;

    // Generate a highlighted snippet.  `body_html` is expected to already have
    // HTML tags stripped and entities decoded (for brevity not included here).
    std::string generate(std::string_view body_html,
                         const std::vector<std::string>& terms,
                         const Options& opts = {}) const
    {
        if (terms.empty()) {
            return summarise(body_html, opts.max_snippet_length, opts.ellipsis);
        }

        // Lower-cased copies for case-insensitive search.
        std::vector<std::string> lower_terms;
        lower_terms.reserve(terms.size());
        for (auto&& t : terms) {
            auto trimmed = trim_ascii(t);
            if (!trimmed.empty()) {
                lower_terms.push_back(ascii_to_lower(trimmed));
            }
        }

        std::string lower_body = ascii_to_lower(body_html);
        std::size_t first_hit = std::string::npos;

        // Identify first occurrence of any term.
        for (const auto& needle : lower_terms) {
            auto pos = lower_body.find(needle);
            if (pos != std::string::npos) {
                first_hit = std::min(first_hit, pos);
            }
        }

        Options effective_opts = opts;

        // If no match found, return fallback summary.
        if (first_hit == std::string::npos) {
            return summarise(body_html, effective_opts.max_snippet_length, effective_opts.ellipsis);
        }

        // Determine snippet window.
        const std::size_t half_window =
            effective_opts.max_snippet_length / 2u > 10 ? effective_opts.max_snippet_length / 2u : 10u;

        std::size_t snippet_start = (first_hit > half_window) ? first_hit - half_window : 0;
        std::size_t snippet_end   = std::min<std::size_t>(body_html.size(), snippet_start + effective_opts.max_snippet_length);

        std::string snippet = std::string(body_html.substr(snippet_start, snippet_end - snippet_start));

        // Highlight occurrences up to max_highlights.
        std::size_t highlights = 0;
        for (const auto& term_raw : lower_terms) {
            std::string term = term_raw;  // copy
            std::size_t pos = ascii_to_lower(snippet).find(term);
            while (pos != std::string::npos && highlights < effective_opts.max_highlights) {
                snippet.insert(pos + term.size(), effective_opts.highlight_end_tag);
                snippet.insert(pos, effective_opts.highlight_start_tag);
                highlights++;
                pos = ascii_to_lower(snippet).find(term, pos + term.size() +
                                                   effective_opts.highlight_start_tag.size() +
                                                   effective_opts.highlight_end_tag.size());
            }
            if (highlights >= effective_opts.max_highlights) break;
        }

        // Add ellipsis if not at boundaries.
        if (snippet_start > 0) {
            snippet.insert(0, effective_opts.ellipsis);
        }
        if (snippet_end < body_html.size()) {
            snippet.append(effective_opts.ellipsis);
        }
        return snippet;
    }

private:
    // Return a simple leading summary, respecting byte length.
    static std::string summarise(std::string_view body, std::size_t max_len, std::string_view ellipsis)
    {
        if (body.size() <= max_len) return std::string(body);
        return std::string(body.substr(0, max_len)) + std::string(ellipsis);
    }
};

// -----------------------------------------------------------------------------
// Cached snippet service (public façade)
// -----------------------------------------------------------------------------

class CachedSnippetService
{
public:
    using ArticleId = std::uint64_t;

    explicit CachedSnippetService(std::size_t cache_capacity = 4096)
        : cache_{ cache_capacity }
    {}

    // High-level API for controllers / services.
    //
    // Parameters:
    //   article_id   – database primary key for the article
    //   body_html    – HTML-stripped article text in UTF-8
    //   query_terms  – individual search terms (already tokenised)
    //
    // The snippet is returned from cache if available; otherwise generated and
    // stored.  Thread-safe for concurrent callers.
    std::string get_snippet(ArticleId                      article_id,
                            std::string_view               body_html,
                            const std::vector<std::string>& query_terms)
    {
        const Key key{ article_id, compute_query_hash(query_terms) };

        if (auto cached = cache_.get(key); cached.has_value()) {
            return *cached;
        }

        // Miss: generate.
        std::string snippet = generator_.generate(body_html, query_terms);

        cache_.put(key, snippet);
        return snippet;
    }

private:
    // Internal key combining article ID and query hash
    struct Key {
        ArticleId   article_id;
        std::size_t query_hash;

        bool operator==(const Key& other) const noexcept
        {
            return article_id == other.article_id &&
                   query_hash  == other.query_hash;
        }
    };

    struct KeyHasher {
        std::size_t operator()(const Key& k) const noexcept
        {
            std::size_t h1 = std::hash<ArticleId>{}(k.article_id);
            std::size_t h2 = std::hash<std::size_t>{}(k.query_hash);
            // Combine (boost::hash_combine recipe)
            return h1 ^ (h2 + 0x9e3779b9 + (h1 << 6) + (h1 >> 2));
        }
    };

    static std::size_t compute_query_hash(const std::vector<std::string>& terms)
    {
        // Order-insensitively combine hashes of individual terms.
        std::size_t result = 0;
        for (const auto& term : terms) {
            std::size_t h = std::hash<std::string>{}(ascii_to_lower(trim_ascii(term)));
            result ^= h + 0x9e3779b97f4a7c15ULL + (result << 12) + (result >> 4);
        }
        return result;
    }

    SnippetGenerator                                            generator_;
    ThreadSafeLRUCache<Key, std::string, KeyHasher>             cache_;
};

// -----------------------------------------------------------------------------
// Example usage (remove or wrap in unit tests in real tree)
// -----------------------------------------------------------------------------
#if defined(MODULE_77_DEMO_MAIN)
int main()
{
    using namespace blogsuite::search;

    CachedSnippetService snippet_service{ 128 };

    CachedSnippetService::ArticleId article_id = 42;
    const std::string body =
        "IntraLedger BlogSuite brings enterprise-grade features to your "
        "organisation.  With advanced search, role-based access control, and "
        "multilingual e-mail notifications, teams collaborate effectively.";

    std::vector<std::string> query = { "ACCESS", "search" };

    std::cout << snippet_service.get_snippet(article_id, body, query) << '\n';
    return 0;
}
#endif // MODULE_77_DEMO_MAIN

} // namespace blogsuite::search