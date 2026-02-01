#include <atomic>
#include <chrono>
#include <curl/curl.h>                 // libcurl (HTTP client)
#include <exception>
#include <iostream>
#include <memory>
#include <mutex>
#include <nlohmann/json.hpp>          // https://github.com/nlohmann/json
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

/*
 *  src/module_25.cpp
 *
 *  Module 25: ArticleSearchIndexer
 *  --------------------------------
 *  Periodically collects articles that need (re-)indexing and ships
 *  their textual representation to the configured full-text search
 *  engine (e.g. OpenSearch / Elasticsearch).  Runs in its own worker
 *  thread, supports graceful shutdown, basic retry semantics and
 *  liberal error handling so it can be embedded into the asynchronous
 *  job processor without compromising the main process.
 *
 *  Dependencies (forward declarations / abstract interfaces):
 *   - IArticleRepository         : Article data access
 *   - IConfiguration             : Runtime configuration access
 *   - IClock                     : Gives current time, overridable for tests
 *
 *  This file is intentionally self-contained so that the remaining
 *  application merely needs to provide concrete implementations of
 *  the interfaces defined herein.
 */

namespace blogsuite::common
{
    /* Simple logging façade — real implementation would multistream,
     * format timestamps, etc. */
    enum class LogLevel { Debug, Info, Warn, Error };

    inline void log(LogLevel lvl, const std::string& msg)
    {
        static std::mutex ioMutex;
        std::lock_guard<std::mutex> lock(ioMutex);

        const char* lvlStr = nullptr;
        switch (lvl) {
            case LogLevel::Debug: lvlStr = "DEBUG"; break;
            case LogLevel::Info:  lvlStr = "INFO "; break;
            case LogLevel::Warn:  lvlStr = "WARN "; break;
            case LogLevel::Error: lvlStr = "ERROR"; break;
        }
        std::cerr << "[" << lvlStr << "] " << msg << '\n';
    }
} // namespace blogsuite::common

/* ---------- Domain Model & Interfaces ---------------------------------- */

namespace blogsuite::domain
{
    using ArticleId = std::uint64_t;

    struct Article
    {
        ArticleId    id;
        std::string  title;
        std::string  content;
        std::string  languageIso;        // e.g. "en", "de", "fr"
        std::string  updatedAtIso8601;   // updated timestamp
    };

    class IArticleRepository
    {
    public:
        virtual ~IArticleRepository() = default;

        /* Returns a batch of articles that require indexing.  The
         * repository decides what constitutes “needs indexing”.
         */
        virtual std::vector<Article>
        fetchArticlesNeedingIndexing(std::size_t batchSize) = 0;

        /* Mark the given articles as being successfully indexed. */
        virtual void markIndexed(const std::vector<ArticleId>&) = 0;
    };

    class IConfiguration
    {
    public:
        virtual ~IConfiguration() = default;
        virtual std::string getString(const std::string& key,
                                      const std::string& defaultVal = "") const = 0;
        virtual std::uint32_t getUInt32(const std::string& key,
                                        std::uint32_t defaultVal = 0) const = 0;
    };

    class IClock
    {
    public:
        virtual ~IClock() = default;
        virtual std::chrono::system_clock::time_point now() const = 0;
    };

} // namespace blogsuite::domain

/* ---------- cURL RAII Helpers ------------------------------------------ */

namespace blogsuite::net
{
    class CurlGlobal
    {
    public:
        CurlGlobal()
        {
            if (auto code = curl_global_init(CURL_GLOBAL_DEFAULT); code != 0) {
                std::ostringstream oss;
                oss << "curl_global_init failed with code " << code;
                throw std::runtime_error(oss.str());
            }
        }
        ~CurlGlobal() { curl_global_cleanup(); }
        CurlGlobal(const CurlGlobal&)            = delete;
        CurlGlobal& operator=(const CurlGlobal&) = delete;
    };

    class CurlEasy
    {
    public:
        CurlEasy() : handle_(curl_easy_init())
        {
            if (!handle_)
                throw std::runtime_error("curl_easy_init returned null");
        }
        ~CurlEasy() { curl_easy_cleanup(handle_); }

        CURL* get() noexcept { return handle_; }

        // Disallow copy
        CurlEasy(const CurlEasy&)            = delete;
        CurlEasy& operator=(const CurlEasy&) = delete;

    private:
        CURL* handle_;
    };

    struct CurlResponse
    {
        long        httpCode = 0;
        std::string body;
        std::string error;
    };

    /* Blocking HTTP POST w/ JSON payload */
    inline CurlResponse httpPostJson(const std::string& url,
                                     const std::string& jsonBody,
                                     const std::string& apiKey,
                                     long timeoutSeconds = 5)
    {
        static CurlGlobal curlGuard; // ensure global init exactly once

        CurlEasy curl;
        CurlResponse resp;

        curl_easy_setopt(curl.get(), CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_POST, 1L);
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDS, jsonBody.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDSIZE, jsonBody.size());
        curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, timeoutSeconds);

        // Disable Expect: 100-continue delays
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        if (!apiKey.empty()) {
            headers = curl_slist_append(headers,
                                        ("Authorization: Bearer " + apiKey).c_str());
        }
        curl_easy_setopt(curl.get(), CURLOPT_HTTPHEADER, headers);

        // Capture response body
        curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION,
                         +[](char* ptr, size_t size, size_t nmemb, void* userdata) -> size_t {
                             auto* s = static_cast<std::string*>(userdata);
                             s->append(ptr, size * nmemb);
                             return size * nmemb;
                         });
        curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, &resp.body);

        // Perform request
        CURLcode code = curl_easy_perform(curl.get());
        if (code != CURLE_OK) {
            resp.error = curl_easy_strerror(code);
        } else {
            curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &resp.httpCode);
        }

        curl_slist_free_all(headers);
        return resp;
    }

} // namespace blogsuite::net

/* ---------- SearchIndexer ---------------------------------------------- */

namespace blogsuite::service
{
    using namespace blogsuite::domain;
    using blogsuite::common::log;
    using blogsuite::common::LogLevel;
    using nlohmann::json;
    using blogsuite::net::CurlResponse;
    using blogsuite::net::httpPostJson;

    class ArticleSearchIndexer
    {
    public:
        ArticleSearchIndexer(std::shared_ptr<IArticleRepository> repo,
                             std::shared_ptr<IConfiguration>    cfg,
                             std::shared_ptr<IClock>            clock)
            : repo_(std::move(repo))
            , cfg_(std::move(cfg))
            , clock_(std::move(clock))
            , isRunning_(false)
        {
            if (!repo_ || !cfg_ || !clock_)
                throw std::invalid_argument("Null dependency passed to ArticleSearchIndexer");

            batchSize_        = cfg_->getUInt32("search.indexer.batchSize", 100);
            pollIntervalSec_  = cfg_->getUInt32("search.indexer.pollInterval", 10);
            searchApiUrl_     = cfg_->getString("search.engine.url");
            searchApiKey_     = cfg_->getString("search.engine.apiKey");

            if (searchApiUrl_.empty())
                throw std::runtime_error("Configuration key 'search.engine.url' is required");
        }

        ~ArticleSearchIndexer() { stop(); }

        /* Start background worker thread (non-blocking) */
        void start()
        {
            bool expected = false;
            if (!isRunning_.compare_exchange_strong(expected, true))
                return; // already running

            worker_ = std::thread([this] { this->runLoop(); });
        }

        /* Stop the worker thread gracefully */
        void stop()
        {
            bool expected = true;
            if (!isRunning_.compare_exchange_strong(expected, false))
                return; // already stopped

            if (worker_.joinable())
                worker_.join();
        }

    private:
        void runLoop()
        {
            log(LogLevel::Info, "ArticleSearchIndexer started");

            while (isRunning_) {
                try {
                    processBatch();
                } catch (const std::exception& ex) {
                    log(LogLevel::Error,
                        std::string("Unhandled exception in indexer loop: ") + ex.what());
                }

                std::unique_lock<std::mutex> lk(sleepMx_);
                sleepCv_.wait_for(
                    lk, std::chrono::seconds(pollIntervalSec_),
                    [this] { return !isRunning_; });
            }

            log(LogLevel::Info, "ArticleSearchIndexer stopped");
        }

        void processBatch()
        {
            auto articles = repo_->fetchArticlesNeedingIndexing(batchSize_);
            if (articles.empty()) {
                log(LogLevel::Debug, "No articles to index");
                return;
            }

            json payload = json::array();
            for (const auto& art : articles) {
                payload.push_back({
                    {"id",         art.id},
                    {"title",      art.title},
                    {"content",    art.content},
                    {"lang",       art.languageIso},
                    {"updated_at", art.updatedAtIso8601},
                });
            }

            CurlResponse resp = httpPostJson(searchApiUrl_, payload.dump(), searchApiKey_);

            if (!resp.error.empty()) {
                std::ostringstream oss;
                oss << "Failed to POST to search engine: " << resp.error;
                log(LogLevel::Error, oss.str());
                return; // leave articles un-marked; retry next round
            }

            if (resp.httpCode >= 200 && resp.httpCode < 300) {
                std::vector<ArticleId> ids;
                ids.reserve(articles.size());
                for (const auto& a : articles) ids.push_back(a.id);
                repo_->markIndexed(ids);
                log(LogLevel::Info,
                    "Indexed batch of " + std::to_string(articles.size()) + " articles");
            } else {
                std::ostringstream oss;
                oss << "Search engine responded with HTTP " << resp.httpCode
                    << " — body: " << resp.body.substr(0, 256);
                log(LogLevel::Error, oss.str());
            }
        }

    private:
        std::shared_ptr<IArticleRepository> repo_;
        std::shared_ptr<IConfiguration>     cfg_;
        std::shared_ptr<IClock>             clock_;

        std::size_t batchSize_       = 100;
        std::uint32_t pollIntervalSec_ = 10;

        std::string searchApiUrl_;
        std::string searchApiKey_;

        std::thread               worker_;
        std::condition_variable   sleepCv_;
        std::mutex                sleepMx_;
        std::atomic_bool          isRunning_;
    };

} // namespace blogsuite::service

/* ---------- Example Stub Implementations -------------------------------
 * The following section is ONLY to demonstrate the module's completeness
 * and is not intended for production.  In the real application these
 * would live elsewhere and be substantially more complex.               */

#if defined(BLOGSUITE_SEARCH_INDEXER_STANDALONE_DEMO)

#include <deque>
#include <random>

namespace
{
    /* Trivial in-memory repository for demonstration */
    class MemoryArticleRepository : public blogsuite::domain::IArticleRepository
    {
    public:
        MemoryArticleRepository()
        {
            // seed with some fake data
            for (std::uint64_t i = 1; i <= 250; ++i) {
                articles_.push_back({
                    i,
                    "Title #" + std::to_string(i),
                    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "en",
                    "2023-07-15T12:34:56Z"
                });
            }
        }

        std::vector<blogsuite::domain::Article>
        fetchArticlesNeedingIndexing(std::size_t batchSize) override
        {
            std::lock_guard<std::mutex> lock(mx_);
            std::vector<blogsuite::domain::Article> out;
            while (!articles_.empty() && out.size() < batchSize) {
                out.push_back(articles_.front());
                articles_.pop_front();
            }
            return out;
        }

        void markIndexed(const std::vector<blogsuite::domain::ArticleId>&) override
        {
            // no-op for demo
        }

    private:
        std::deque<blogsuite::domain::Article> articles_;
        std::mutex                              mx_;
    };

    class EnvConfiguration : public blogsuite::domain::IConfiguration
    {
        std::string getString(const std::string& key,
                              const std::string& defaultVal = "") const override
        {
            if (auto* val = std::getenv(key.c_str()); val) return val;
            return defaultVal;
        }
        std::uint32_t getUInt32(const std::string& key,
                                std::uint32_t defaultVal = 0) const override
        {
            std::string s = getString(key);
            if (s.empty()) return defaultVal;
            return static_cast<std::uint32_t>(std::stoul(s));
        }
    };

    class SystemClock : public blogsuite::domain::IClock
    {
        std::chrono::system_clock::time_point now() const override
        {
            return std::chrono::system_clock::now();
        }
    };

} // namespace

int main()
{
    using namespace blogsuite;

    auto repo  = std::make_shared<MemoryArticleRepository>();
    auto cfg   = std::make_shared<EnvConfiguration>();
    auto clock = std::make_shared<SystemClock>();

    service::ArticleSearchIndexer indexer(repo, cfg, clock);
    indexer.start();

    std::this_thread::sleep_for(std::chrono::seconds(5));
    indexer.stop();
}
#endif  // BLOGSUITE_SEARCH_INDEXER_STANDALONE_DEMO