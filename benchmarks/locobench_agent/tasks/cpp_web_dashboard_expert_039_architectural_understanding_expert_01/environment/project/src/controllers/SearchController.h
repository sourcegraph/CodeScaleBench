#ifndef MOSAICBOARD_STUDIO_CONTROLLERS_SEARCHCONTROLLER_H
#define MOSAICBOARD_STUDIO_CONTROLLERS_SEARCHCONTROLLER_H

/*
 * MosaicBoard Studio
 * File:    SearchController.h
 * Author:  MosaicBoard Core Team
 *
 * Description:
 *   Exposes HTTP-level search endpoints that power the global dashboard search bar.
 *   Supports result caching, query normalization, and robust error handling in order
 *   to provide low-latency, fault-tolerant search results for both UI widgets and
 *   public REST clients.
 *
 *   The controller is entirely header-only so that plugins can include it without
 *   worrying about link-time dependencies.
 *
 *   Usage:
 *      auto searchController = std::make_shared<SearchController>(searchService);
 *      searchController->registerEndpoints(router);
 */

#include <memory>
#include <string>
#include <vector>
#include <unordered_map>
#include <optional>
#include <mutex>
#include <chrono>
#include <algorithm>
#include <cctype>
#include <stdexcept>

#include <nlohmann/json.hpp>

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations for framework-level types.
// In production these are provided by the HTTP server / router component.
// ──────────────────────────────────────────────────────────────────────────────
namespace web
{
    struct HttpRequest
    {
        std::string path;
        std::string queryString;
        std::string body;

        std::optional<std::string> getQueryParam(const std::string& key) const;
        // … additional members …
    };

    struct HttpResponse
    {
        int    status   = 200;
        std::string mimeType = "application/json";
        nlohmann::json jsonBody;

        explicit HttpResponse(int statusCode = 200) : status(statusCode) {}
        static HttpResponse makeError(int status, const std::string& msg)
        {
            HttpResponse res(status);
            res.jsonBody = {{"error", msg}};
            return res;
        }
    };

    class HttpRouter
    {
    public:
        // Register GET handler.
        using Handler = std::function<HttpResponse(const HttpRequest&)>;
        void GET(const std::string& route, Handler&& h);
        // … additional HTTP verbs …
    };
} // namespace web

// ──────────────────────────────────────────────────────────────────────────────
// Business-layer SearchService interface
// ──────────────────────────────────────────────────────────────────────────────
class SearchService
{
public:
    struct Result
    {
        std::string id;
        std::string title;
        std::string type; // e.g. "tile", "dashboard", "dataset"
        double      relevance = 0.0;
    };

    virtual ~SearchService() = default;

    // Performs full-text search over dashboards, tiles, & datasets
    virtual std::vector<Result> search(const std::string& query,
                                       std::size_t          limit,
                                       std::size_t          offset) = 0;
};

// ──────────────────────────────────────────────────────────────────────────────
// SearchController
// ──────────────────────────────────────────────────────────────────────────────
class SearchController
{
public:
    /*
     * Constructor
     *
     * Parameters:
     *   searchService  – Dependency-injected pointer to domain search service.
     *   ttl            – Per-entry cache time-to-live.
     *   maxCacheItems  – Maximum number of items to keep in the in-memory cache.
     */
    explicit SearchController(std::shared_ptr<SearchService>  searchService,
                              std::chrono::seconds            ttl           = std::chrono::seconds(15),
                              std::size_t                     maxCacheItems = 256)
        : _searchService(std::move(searchService))
        , _ttl(ttl)
        , _maxCacheItems(maxCacheItems)
    {
        if (!_searchService)
            throw std::invalid_argument("SearchController: searchService cannot be null");
    }

    /*
     * Registers all HTTP endpoints handled by this controller.
     */
    void registerEndpoints(web::HttpRouter& router)
    {
        router.GET("/api/v1/search",
                   [this](const web::HttpRequest& req)
                   {
                       return this->onSearch(req);
                   });
    }

private:
    // ──────────────────────────────────────────────────────────────────────────
    // Internal types & storage
    // ──────────────────────────────────────────────────────────────────────────
    struct CacheEntry
    {
        std::chrono::steady_clock::time_point expiresAt;
        nlohmann::json payload;
    };

    std::shared_ptr<SearchService>                   _searchService;
    mutable std::mutex                              _cacheMtx;
    std::unordered_map<std::string, CacheEntry>      _cache;
    const std::chrono::seconds                       _ttl;
    const std::size_t                                _maxCacheItems;

    // ──────────────────────────────────────────────────────────────────────────
    // Endpoint Handlers
    // ──────────────────────────────────────────────────────────────────────────
    web::HttpResponse onSearch(const web::HttpRequest& req)
    {
        try
        {
            // 1. Extract query parameters.
            const std::string rawQuery  = req.getQueryParam("q").value_or("");
            const std::size_t limit     = parseParamOrDefault(req, "limit", 25, 1, 100);
            const std::size_t offset    = parseParamOrDefault(req, "offset", 0, 0, 10000);

            if (rawQuery.empty())
                return web::HttpResponse::makeError(400, "`q` query parameter is required");

            // 2. Normalize query: lowercase, trim, collapse whitespace.
            const std::string normalized = normalizeQuery(rawQuery);
            const std::string cacheKey   = normalized + "#" + std::to_string(limit) + "#" + std::to_string(offset);

            // 3. Attempt cache hit.
            if (auto cached = tryGetFromCache(cacheKey))
            {
                return makeSuccessResponse(*cached, /*fromCache=*/true);
            }

            // 4. Perform search via service layer.
            const auto results = _searchService->search(normalized, limit, offset);

            // 5. Transform results to JSON.
            nlohmann::json jsonResults = nlohmann::json::array();
            for (const auto& r : results)
            {
                jsonResults.push_back({
                    {"id",        r.id},
                    {"title",     r.title},
                    {"type",      r.type},
                    {"relevance", r.relevance}
                });
            }

            // 6. Cache response.
            putInCache(cacheKey, jsonResults);

            // 7. Return OK.
            return makeSuccessResponse(jsonResults, /*fromCache=*/false);
        }
        catch (const std::exception& ex)
        {
            return web::HttpResponse::makeError(500, ex.what());
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Helpers
    // ──────────────────────────────────────────────────────────────────────────
    static std::size_t parseParamOrDefault(const web::HttpRequest& req,
                                           const std::string&      key,
                                           std::size_t             defaultVal,
                                           std::size_t             minVal,
                                           std::size_t             maxVal)
    {
        try
        {
            const auto param = req.getQueryParam(key);
            if (!param) return defaultVal;

            std::size_t val = static_cast<std::size_t>(std::stoul(*param));
            if (val < minVal) val = minVal;
            if (val > maxVal) val = maxVal;
            return val;
        }
        catch (...)
        {
            return defaultVal;
        }
    }

    static std::string normalizeQuery(const std::string& q)
    {
        std::string out;
        out.reserve(q.size());
        bool prevWs = false;

        for (char ch : q)
        {
            if (std::isspace(static_cast<unsigned char>(ch)))
            {
                if (!prevWs)
                {
                    out.push_back(' ');
                    prevWs = true;
                }
            }
            else
            {
                out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
                prevWs = false;
            }
        }

        // Trim trailing space.
        if (!out.empty() && out.back() == ' ')
            out.pop_back();

        return out;
    }

    std::optional<nlohmann::json> tryGetFromCache(const std::string& key) const
    {
        std::scoped_lock lock(_cacheMtx);
        auto it = _cache.find(key);
        if (it == _cache.end())
            return std::nullopt;

        const auto now = std::chrono::steady_clock::now();
        if (now >= it->second.expiresAt)
        {
            // Expired -> erase.
            _cache.erase(it);
            return std::nullopt;
        }

        return it->second.payload;
    }

    void putInCache(const std::string& key, nlohmann::json&& payload)
    {
        std::scoped_lock lock(_cacheMtx);

        // Evict random entry if we exceed the cache size.
        if (_cache.size() >= _maxCacheItems)
        {
            _cache.erase(_cache.begin());
        }

        _cache[key] = {std::chrono::steady_clock::now() + _ttl,
                       std::move(payload)};
    }

    static web::HttpResponse makeSuccessResponse(const nlohmann::json& body, bool fromCache)
    {
        web::HttpResponse res(200);
        res.jsonBody = {
            {"cached",  fromCache},
            {"results", body}
        };
        return res;
    }
};

#endif // MOSAICBOARD_STUDIO_CONTROLLERS_SEARCHCONTROLLERR_H