```cpp
// ────────────────────────────────────────────────────────────────────────────────
// MosaicBoard Studio
// Source file: MosaicBoardStudio/src/controllers/SearchController.cpp
// Description: REST-layer controller responsible for user-initiated search
//              across tiles, dashboards and user-generated assets.
// Author      : MosaicBoard Studio Core Team
// License     : MIT
// ────────────────────────────────────────────────────────────────────────────────

#include "SearchController.hpp"                   // Public header for this class
#include "../core/http/Router.hpp"                // HTTP router abstraction
#include "../core/http/HttpCodes.hpp"             // HTTP status codes
#include "../core/http/HttpRequest.hpp"           // Request abstraction
#include "../core/http/HttpResponse.hpp"          // Response abstraction
#include "../core/cache/ICacheProvider.hpp"       // Cache interface
#include "../core/auth/IAuthManager.hpp"          // AuthN / AuthZ interface
#include "../services/search/ISearchService.hpp"  // Domain search service
#include "../utils/Stopwatch.hpp"                 // Simple time profiler
#include "../utils/Logger.hpp"                    // Logging facility (spdlog wrapper)

#include <nlohmann/json.hpp>                      // JSON serialization
#include <utility>                                // std::move
#include <regex>                                  // Input validation
#include <sstream>                                // o-string-stream for cache key
#include <iomanip>                                // std::put_time
#include <ctime>                                  // std::time_t
#include <thread>                                 // std::this_thread::sleep_for

using json = nlohmann::json;
namespace http  = mosaic::core::http;
namespace search= mosaic::services::search;

namespace mosaic::controllers {

namespace {
/* ──────────────────────────────────────────────────────────────────────────────
   Helpers
   ──────────────────────────────────────────────────────────────────────────── */

// Validate the user input to avoid ReDoS & path traversal attacks.
bool isQueryValid(std::string_view q) noexcept
{
    static const std::regex kPattern(R"(^[[:alnum:]\s\-\_\.\,]{1,128}$)",
                                     std::regex::optimize);
    return std::regex_match(q.begin(), q.end(), kPattern);
}

// A poor-man's ISO-8601 timestamp helper
static std::string isoTimestamp()
{
    std::ostringstream oss;
    const std::time_t  t = std::time(nullptr);
#if defined(_MSC_VER)
    std::tm tmSnapshot;
    gmtime_s(&tmSnapshot, &t);
    std::tm* tmP = &tmSnapshot;
#else
    std::tm* tmP = std::gmtime(&t);
#endif
    oss << std::put_time(tmP, "%FT%TZ");
    return oss.str();
}

} // namespace

/* ──────────────────────────────────────────────────────────────────────────────
   Constructor
   ──────────────────────────────────────────────────────────────────────────── */
SearchController::SearchController(std::shared_ptr<search::ISearchService>  searchSvc,
                                   std::shared_ptr<cache::ICacheProvider>   cache,
                                   std::shared_ptr<auth::IAuthManager>      auth,
                                   std::shared_ptr<utils::Logger>           logger)
    : m_searchSvc(std::move(searchSvc))
    , m_cache(std::move(cache))
    , m_auth(std::move(auth))
    , m_logger(std::move(logger))
{
    if (!m_searchSvc || !m_cache || !m_auth || !m_logger) {
        throw std::invalid_argument("SearchController requires non-null dependencies.");
    }
}

/* ──────────────────────────────────────────────────────────────────────────────
   Route registration
   ──────────────────────────────────────────────────────────────────────────── */
void SearchController::registerRoutes(http::Router& router)
{
    router.get("/api/v1/search",  [this](const http::HttpRequest&  req,
                                         http::HttpResponse&       res) {
        this->handleSearch(req, res);
    });

    router.get("/api/v1/search/suggestions", [this](const http::HttpRequest& req,
                                                    http::HttpResponse&      res) {
        this->handleSuggestions(req, res);
    });
}

/* ──────────────────────────────────────────────────────────────────────────────
   /api/v1/search
   ──────────────────────────────────────────────────────────────────────────── */
void SearchController::handleSearch(const http::HttpRequest& req,
                                    http::HttpResponse&      res)
{
    utils::Stopwatch sw; // latency profiler
    try {
        // 1. Authenticate & Authorize
        const auto user = m_auth->requireUser(req); // throws on failure
        m_logger->debug("[Search] user={} authenticated OK", user.id);

        // 2. Parse & validate query parameters
        const std::string query   = req.getQueryParam("q").value_or("");
        const std::size_t limit   = req.getQueryParamAs<size_t>("limit").value_or(25);
        const std::size_t offset  = req.getQueryParamAs<size_t>("offset").value_or(0);
        const bool includePrivate = req.getQueryParamAs<bool>("includePrivate").value_or(false);

        if (!isQueryValid(query) || query.empty()) {
            res.status(http::Status::BadRequest);
            res.json(json{{"error", "Invalid or missing query parameter 'q'."}});
            return;
        }
        if (limit == 0 || limit > 200) {
            res.status(http::Status::BadRequest);
            res.json(json{{"error", "'limit' must be between 1 and 200."}});
            return;
        }

        // 3. Resolve from cache if possible
        std::ostringstream cacheKeyBuilder;
        cacheKeyBuilder << "search:" << user.id << ":" << query << ":" << limit
                        << ":" << offset << ":" << includePrivate;
        const std::string cacheKey = cacheKeyBuilder.str();

        if (auto cached = m_cache->get(cacheKey); cached) {
            m_logger->debug("[Search] cache hit for key={}", cacheKey);
            res.status(http::Status::OK);
            res.setHeader("X-Cache", "HIT");
            res.setHeader("Content-Type", "application/json");
            res.body(std::move(*cached));
            return;
        }

        // 4. Execute domain search
        search::SearchQuery  q;
        q.text            = query;
        q.limit           = limit;
        q.offset          = offset;
        q.includePrivate  = includePrivate;
        q.requesterUserId = user.id;

        const auto results = m_searchSvc->search(q);

        // 5. Serialize
        json jRes = {
            {"timestamp", isoTimestamp()},
            {"query",     query},
            {"count",     results.items.size()},
            {"total",     results.total},
            {"data",      results.items}
        };

        std::string body = jRes.dump();

        // 6. Persist to cache asynchronously (avoid blocking response path)
        m_cache->setAsync(cacheKey, body, std::chrono::seconds{30});

        // 7. Finalise response
        res.status(http::Status::OK);
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("X-Cache", "MISS");
        res.body(std::move(body));

        m_logger->info("[Search] [user={}] query='{}' limit={} offset={} duration={}ms",
                       user.id, query, limit, offset, sw.elapsedMs());

    } catch (const auth::Unauthorized& e) {
        m_logger->warn("[Search] Unauthorized access: {}", e.what());
        res.status(http::Status::Unauthorized);
        res.json(json{{"error", "Unauthorized"}});
    } catch (const search::SearchException& e) {
        m_logger->error("[Search] Search service failure: {}", e.what());
        res.status(http::Status::ServiceUnavailable);
        res.json(json{{"error", "Search service unavailable"}});
    } catch (const std::exception& e) {
        m_logger->crit("[Search] Unhandled exception: {}", e.what());
        res.status(http::Status::InternalServerError);
        res.json(json{{"error", "Internal server error"}});
    }
}

/* ──────────────────────────────────────────────────────────────────────────────
   /api/v1/search/suggestions
   ──────────────────────────────────────────────────────────────────────────── */
void SearchController::handleSuggestions(const http::HttpRequest& req,
                                         http::HttpResponse&      res)
{
    utils::Stopwatch sw;

    try {
        m_auth->requireUser(req); // suggestions are public but we still capture identity for ML
        const std::string prefix = req.getQueryParam("prefix").value_or("");

        if (prefix.empty() || !isQueryValid(prefix)) {
            res.status(http::Status::BadRequest);
            res.json(json{{"error", "Invalid or missing query parameter 'prefix'."}});
            return;
        }

        const auto suggestions = m_searchSvc->autocomplete(prefix, /*max*/10);

        json jRes = {
            {"timestamp",   isoTimestamp()},
            {"prefix",      prefix},
            {"suggestions", suggestions}
        };

        res.status(http::Status::OK);
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.body(jRes.dump());

        m_logger->debug("[Search] suggestions for prefix='{}' served in {}ms",
                        prefix, sw.elapsedMs());
    }
    catch (const std::exception& e) {
        m_logger->error("[Search] suggestions failure: {}", e.what());
        res.status(http::Status::InternalServerError);
        res.json(json{{"error", "Internal server error"}});
    }
}

} // namespace mosaic::controllers
```