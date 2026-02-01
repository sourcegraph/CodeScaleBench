```cpp
/**
 *  IntraLedger BlogSuite
 *  =====================
 *  Source file:  src/module_64.cpp
 *
 *  Module 64 – Full-Text Search Service & Async Index Job
 *  ------------------------------------------------------
 *  This translation unit provides the production-grade implementation for the
 *  platform’s full-text search service, together with the asynchronous job that
 *  keeps the search index in sync with the underlying data store.
 *
 *  Key responsibilities:
 *  •   Translate domain objects (e.g., Article) into search engine documents
 *  •   Perform scoped searches with role-based filtering
 *  •   Handle incremental re-indexing through the job-processor subsystem
 *
 *  NOTE:
 *  -----
 *  – The surrounding infrastructure (repositories, middleware, job runner,
 *    etc.) is assumed to be part of the project and therefore included only
 *    via forward declarations / headers.
 *  – The implementation adheres to C++17 and uses spdlog for structured
 *    logging. All heavy-weight dependencies (e.g., CLucene, Xapian…) are
 *    abstracted behind the ISearchEngine interface.
 */

#include <algorithm>
#include <chrono>
#include <memory>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>
#include <spdlog/fmt/ostr.h>

// ─────────────────────────────────────────────────────────────────────────────
// Project-internal headers (forward-declared where feasible)
// ─────────────────────────────────────────────────────────────────────────────
#include "core/Clock.hpp"
#include "core/DomainException.hpp"
#include "middleware/UserContext.hpp"
#include "persistence/ArticleRepository.hpp"
#include "search/ISearchEngine.hpp"
#include "job/IAsyncJob.hpp"

namespace intraledger::service {

// ─────────────────────────────────────────────────────────────────────────────
// Supporting data structures
// ─────────────────────────────────────────────────────────────────────────────

/**
 *  Lightweight, serialisable search result view.
 */
struct SearchResult {
    std::uint64_t articleId;
    std::string   title;
    std::string   snippet;
    double        score;

    bool operator<(const SearchResult& rhs) const noexcept {
        return score > rhs.score; // higher score first
    }
};

// ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

/**
 *  Exception type for all search service failures.
 */
class SearchServiceException final : public core::DomainException {
public:
    explicit SearchServiceException(std::string  msg,
                                    std::source_location where = std::source_location::current())
        : DomainException{ std::move(msg), where } {}
};

// ─────────────────────────────────────────────────────────────────────────────
// SearchService
// ─────────────────────────────────────────────────────────────────────────────

/**
 *  SearchService – stateless façade wrapping the configured search engine.
 *
 *  Thread-safety:
 *    • Public API is fully thread-safe.
 *    • Internal search engine instance is protected by shared_mutex.
 *
 *  Lifetime:
 *    • A single instance is expected to live for the duration of the
 *      application process (often via DI container).
 */
class SearchService final {
public:
    SearchService(std::shared_ptr<persistence::ArticleRepository> repo,
                  std::shared_ptr<search::ISearchEngine>         engine)
        : m_repo{ std::move(repo) }
        , m_engine{ std::move(engine) } {

        if (!m_repo || !m_engine) {
            throw SearchServiceException{ "SearchService requires non-null dependencies." };
        }
    }

    // ---------------------------------------------------------------------
    // Indexing API
    // ---------------------------------------------------------------------

    /**
     *  Re-indexes (creates or updates) the given article.
     */
    void reindexArticle(std::uint64_t articleId) {
        auto article = m_repo->findById(articleId);
        if (!article) {
            // Article might have been deleted after the job was queued.
            spdlog::warn("[SearchService] Article {} not found – skipping re-index.", articleId);
            return;
        }

        search::EngineDocument doc = makeDocument(*article);

        {
            std::unique_lock lock{ m_mutex };
            m_engine->indexDocument(doc);
        }

        spdlog::info("[SearchService] Re-indexed Article #{}", articleId);
    }

    /**
     *  Removes a document from the search index.
     */
    void dropArticle(std::uint64_t articleId) {
        std::unique_lock lock{ m_mutex };
        m_engine->removeDocument(articleId);
    }

    // ---------------------------------------------------------------------
    // Query API
    // ---------------------------------------------------------------------

    /**
     *  Executes a full-text query against the engine, taking into account
     *  user context (visibility, roles, etc.).
     */
    std::vector<SearchResult>
    search(std::string_view              query,
           const middleware::UserContext& userCtx,
           std::size_t                   limit  = 20,
           std::size_t                   offset = 0) const {

        if (query.empty()) { return {}; }

        // ‑-- Validate pagination
        constexpr std::size_t kMaxLimit = 100;
        limit                           = std::min(limit, kMaxLimit);

        // ‑-- Execute
        std::vector<search::EngineHit> rawHits;
        {
            std::shared_lock lock{ m_mutex };
            rawHits = m_engine->search(query, limit, offset);
        }

        // ‑-- Post-filter based on ACL
        std::vector<SearchResult> results;
        results.reserve(rawHits.size());

        for (const auto& hit : rawHits) {
            if (!userCtx.mayReadArticle(hit.articleId)) { continue; }

            SearchResult r;
            r.articleId = hit.articleId;
            r.title     = hit.title;
            r.snippet   = highlightSnippet(hit.content, query);
            r.score     = hit.score;
            results.push_back(std::move(r));
        }

        std::sort(results.begin(), results.end()); // sort by score descending
        return results;
    }

private:
    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------

    static constexpr std::size_t kSnippetRadius = 60;

    /**
     *  Converts an Article domain object into an EngineDocument.
     */
    static search::EngineDocument makeDocument(const domain::Article& article) {
        search::EngineDocument doc;
        doc.articleId = article.id();
        doc.title     = article.title();
        doc.content   = article.markdownBody();
        doc.locale    = article.locale();
        doc.published = article.isPublished();
        doc.timestamp = article.lastUpdatedUtc();

        return doc;
    }

    /**
     *  Produces a short excerpt around the first match of the query.
     *  This implementation is intentionally simple and can be replaced
     *  with a more sophisticated algorithm (e.g., BM25-based fragmenter).
     */
    static std::string
    highlightSnippet(std::string_view text, std::string_view queryTerm) {

        if (text.empty() || queryTerm.empty()) { return {}; }

        // Case-insensitive search
        std::string hayStack{ text };
        std::string needle{ queryTerm };
        std::transform(hayStack.begin(), hayStack.end(), hayStack.begin(), ::tolower);
        std::transform(needle.begin(), needle.end(), needle.begin(), ::tolower);

        auto pos = hayStack.find(needle);
        if (pos == std::string::npos) { pos = 0; }

        // Compute slice boundaries
        auto start = (pos > kSnippetRadius) ? pos - kSnippetRadius : 0;
        auto end   = std::min(pos + needle.size() + kSnippetRadius, text.size());

        std::string snippet{ text.substr(start, end - start) };
        if (start != 0) { snippet.insert(0, "..."); }
        if (end != text.size()) { snippet.append("..."); }

        // Cheap highlighting
        std::regex rgx{ std::string{ queryTerm }, std::regex::icase };
        snippet = std::regex_replace(snippet, rgx, "[$&]");

        return snippet;
    }

    // ---------------------------------------------------------------------
    // Data members
    // ---------------------------------------------------------------------

    std::shared_ptr<persistence::ArticleRepository> m_repo;
    std::shared_ptr<search::ISearchEngine>          m_engine;

    mutable std::shared_mutex m_mutex; // protects m_engine
};

// ─────────────────────────────────────────────────────────────────────────────
// Async Job for Incremental Re-Indexing
// ─────────────────────────────────────────────────────────────────────────────

class ReindexArticleJob final : public job::IAsyncJob {
public:
    ReindexArticleJob(std::uint64_t                articleId,
                      std::shared_ptr<SearchService> searchSvc)
        : m_articleId{ articleId }
        , m_searchSvc{ std::move(searchSvc) } {

        if (!m_searchSvc) { throw std::invalid_argument{ "searchSvc must not be null" }; }
    }

    job::JobId id() const noexcept override { return job::hash("ReindexArticleJob", m_articleId); }

    /**
     *  Entry point consumed by the job runner.
     */
    void run() override {
        try {
            m_searchSvc->reindexArticle(m_articleId);
        } catch (const std::exception& ex) {
            spdlog::error("[ReindexArticleJob] Failed to index Article #{}: {}",
                          m_articleId,
                          ex.what());
            throw; // rethrow for retry/back-off policies
        }
    }

private:
    std::uint64_t                 m_articleId;
    std::shared_ptr<SearchService> m_searchSvc;
};

// ─────────────────────────────────────────────────────────────────────────────
// Service factory (used by DI container / Service Locator)
// ─────────────────────────────────────────────────────────────────────────────

std::shared_ptr<SearchService>
makeSearchService(const std::shared_ptr<persistence::ArticleRepository>& repo,
                  const std::shared_ptr<search::ISearchEngine>&          engine) {
    static auto instance = std::make_shared<SearchService>(repo, engine);
    return instance;
}

} // namespace intraledger::service
```