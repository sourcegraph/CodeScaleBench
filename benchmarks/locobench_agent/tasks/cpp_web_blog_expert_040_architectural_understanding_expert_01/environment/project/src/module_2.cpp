```cpp
// ─────────────────────────────────────────────────────────────────────────────
//  File      : src/module_2.cpp
//  Project   : IntraLedger BlogSuite (web_blog)
//  Copyright : © 2024 IntraLedger
//  License   : Proprietary, all rights reserved.
// ─────────────────────────────────────────────────────────────────────────────
//
//  Description:
//  ------------
//  SearchIndexService
//  ------------------
//  This compilation unit contains a production-ready implementation of an
//  in-process full-text search index tailored for IntraLedger BlogSuite. The
//  service exposes a narrow API that is used by Controllers, Services, and
//  asynchronous Jobs to:
//
//      • Re-index the complete article corpus (sync or async)
//      • Incrementally add / update / remove a single article
//      • Execute ranked boolean / tf-idf style searches
//
//  NOTE: In the actual application the concrete repository and job-scheduler
//  implementations are provided by higher-level components.  To keep this
//  source file self-contained we only rely on forward-declared interfaces.
// ─────────────────────────────────────────────────────────────────────────────

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <exception>
#include <future>
#include <iostream>
#include <locale>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// ─────────────────────────────────────────────────────────────────────────────
// Forward declarations of cross-module contracts that exist elsewhere in the
// code base.  They are intentionally lightweight so that this compilation unit
// remains buildable in isolation while still demonstrating realistic coupling.
// ─────────────────────────────────────────────────────────────────────────────
namespace intraledger::blogsuite
{
struct Article final
{
    std::uint64_t                        id           = 0;
    std::string                          title;
    std::string                          body;
    std::chrono::system_clock::time_point publishedAt {};
    bool                                 isPublished  = false;
};

class IArticleRepository
{
public:
    virtual ~IArticleRepository() = default;

    // Returns ALL published articles in the system.
    virtual std::vector<Article> fetchAllPublished() = 0;

    // Single article lookup (drafts and soft-deleted entities are excluded).
    virtual std::optional<Article> findById(std::uint64_t id) = 0;
};

class IJobScheduler
{
public:
    virtual ~IJobScheduler() = default;

    // Schedule an arbitrary functor for future execution.  Implementations
    // normally wrap a thread-pool or event-loop.
    virtual void schedule(std::function<void()> job,
                          std::chrono::milliseconds delay) = 0;
};

} // namespace intraledger::blogsuite

// ─────────────────────────────────────────────────────────────────────────────
//  Module implementation
// ─────────────────────────────────────────────────────────────────────────────
namespace intraledger::blogsuite::search
{
using intraledger::blogsuite::Article;
using intraledger::blogsuite::IArticleRepository;
using intraledger::blogsuite::IJobScheduler;

// Lightweight DTO returned to callers.
struct SearchResult final
{
    std::uint64_t id     = 0;
    std::string   title;
    std::string   snippet;
    double        score  = 0.0;
};

// ─────────────────────────────────────────────────────────────────────────────
//  SearchIndexService
// ─────────────────────────────────────────────────────────────────────────────
class SearchIndexService final
{
public:
    explicit SearchIndexService(IArticleRepository& repo,
                                IJobScheduler&      scheduler);

    // Cold-starts the internal index synchronously.
    void warmUp();

    // Queue a full corpus re-index.  Returns immediately.
    void reindexAllAsync();

    // Incremental operations
    void indexOrUpdate(std::uint64_t articleId);
    void remove(std::uint64_t articleId);

    // Query API
    [[nodiscard]]
    std::vector<SearchResult>
    search(const std::string& query,
           std::size_t         limit   = 10,
           std::size_t         offset  = 0) const;

private:
    void doReindexAll();

    // Helpers
    static std::vector<std::string> tokenize(const std::string& text);
    static std::string              makeSnippet(const std::string& body,
                                                const std::vector<std::string>& terms);

private:
    IArticleRepository& m_repo;
    IJobScheduler&      m_scheduler;

    mutable std::shared_mutex                     m_guard;
    std::unordered_map<std::uint64_t, Article>    m_articles;

    // term           -> (articleId -> hitCount)
    std::unordered_map<std::string,
                       std::unordered_map<std::uint64_t, std::size_t>> m_inverted;

    std::atomic_bool m_warmedUp {false};
};

// ─────────────────────────────────────────────────────────────────────────────
//  ctor
// ─────────────────────────────────────────────────────────────────────────────
SearchIndexService::SearchIndexService(IArticleRepository& repo,
                                       IJobScheduler&      scheduler)
    : m_repo {repo}
    , m_scheduler {scheduler}
{}

// ─────────────────────────────────────────────────────────────────────────────
//  Public API
// ─────────────────────────────────────────────────────────────────────────────
void SearchIndexService::warmUp()
{
    if (m_warmedUp.load(std::memory_order_acquire)) { return; }
    doReindexAll();
    m_warmedUp.store(true, std::memory_order_release);
}

void SearchIndexService::reindexAllAsync()
{
    m_scheduler.schedule(
        [this]
        {
            try
            {
                doReindexAll();
            }
            catch (const std::exception& ex)
            {
                std::cerr << "[SearchIndexService] async reindex failed: "
                          << ex.what() << '\n';
            }
        },
        std::chrono::milliseconds {0});
}

void SearchIndexService::indexOrUpdate(std::uint64_t articleId)
{
    const auto maybe = m_repo.findById(articleId);
    if (!maybe || !maybe->isPublished) { return; }

    const Article& article = *maybe;

    std::unique_lock lock {m_guard};

    // Remove previous entries if they exist
    remove(articleId);

    // Re-insert
    m_articles[articleId] = article;
    const auto tokens = tokenize(article.title + ' ' + article.body);

    for (const auto& token : tokens)
    {
        m_inverted[token][articleId] += 1;
    }
}

void SearchIndexService::remove(std::uint64_t articleId)
{
    std::unique_lock lock {m_guard};

    m_articles.erase(articleId);
    for (auto it = m_inverted.begin(); it != m_inverted.end();)
    {
        auto& map = it->second;
        map.erase(articleId);
        if (map.empty())
        {
            it = m_inverted.erase(it);
        }
        else
        {
            ++it;
        }
    }
}

std::vector<SearchResult>
SearchIndexService::search(const std::string& query,
                           std::size_t        limit,
                           std::size_t        offset) const
{
    if (query.empty()) { return {}; }

    const auto tokens = tokenize(query);

    std::shared_lock lock {m_guard};

    // Aggregate hit counts
    std::unordered_map<std::uint64_t, double> scores;
    for (const auto& token : tokens)
    {
        const auto termIt = m_inverted.find(token);
        if (termIt == m_inverted.end()) { continue; }

        const auto& articleMap = termIt->second;
        for (const auto& [articleId, hitCount] : articleMap)
        {
            // Simple tf scoring
            scores[articleId] += static_cast<double>(hitCount);
        }
    }

    // Convert to vector
    std::vector<SearchResult> results;
    results.reserve(scores.size());

    for (const auto& [articleId, score] : scores)
    {
        const auto artIt = m_articles.find(articleId);
        if (artIt == m_articles.end()) { continue; }

        results.push_back(
            SearchResult {
                .id      = artIt->second.id,
                .title   = artIt->second.title,
                .snippet = makeSnippet(artIt->second.body, tokens),
                .score   = score,
            });
    }

    // Sort and paginate
    std::sort(results.begin(), results.end(),
              [](const SearchResult& a, const SearchResult& b)
              {
                  return a.score > b.score;
              });

    if (offset >= results.size()) { return {}; }

    const std::size_t end = std::min(results.size(), offset + limit);
    return {results.begin() + static_cast<std::ptrdiff_t>(offset),
            results.begin() + static_cast<std::ptrdiff_t>(end)};
}

// ─────────────────────────────────────────────────────────────────────────────
//  Private helpers
// ─────────────────────────────────────────────────────────────────────────────
void SearchIndexService::doReindexAll()
{
    std::vector<Article> corpus = m_repo.fetchAllPublished();

    std::unordered_map<std::uint64_t, Article>    newArticles;
    std::unordered_map<std::string,
                       std::unordered_map<std::uint64_t, std::size_t>> newIndex;

    for (const auto& article : corpus)
    {
        newArticles.emplace(article.id, article);

        const auto tokens = tokenize(article.title + ' ' + article.body);
        for (const auto& tok : tokens)
        {
            newIndex[tok][article.id] += 1;
        }
    }

    // Commit in one shot for minimal lock contention.
    {
        std::unique_lock lock {m_guard};
        m_articles.swap(newArticles);
        m_inverted.swap(newIndex);
    }
}

std::vector<std::string> SearchIndexService::tokenize(const std::string& text)
{
    std::vector<std::string> tokens;
    std::string              current;

    auto flush = [&]()
    {
        if (!current.empty())
        {
            tokens.push_back(current);
            current.clear();
        }
    };

    for (const char ch : text)
    {
        if (std::isalnum(static_cast<unsigned char>(ch)))
        {
            current.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
        }
        else
        {
            flush();
        }
    }
    flush();

    return tokens;
}

std::string SearchIndexService::makeSnippet(const std::string& body,
                                            const std::vector<std::string>& terms)
{
    constexpr std::size_t kMaxLen = 180;

    // Naïve implementation: first sentence that contains any term.
    std::istringstream iss {body};
    std::string         line;
    while (std::getline(iss, line, '.'))
    {
        const auto lowerLineTokens = tokenize(line);
        for (const auto& token : lowerLineTokens)
        {
            if (std::find(terms.begin(), terms.end(), token) != terms.end())
            {
                if (line.size() > kMaxLen)
                {
                    line.resize(kMaxLen);
                    line.append("…");
                }
                return line;
            }
        }
    }

    // Fallback: plain truncated body
    if (body.size() <= kMaxLen) { return body; }

    return body.substr(0, kMaxLen) + "…";
}

} // namespace intraledger::blogsuite::search
```