```cpp
/**
 *  IntraLedger BlogSuite – web_blog
 *  --------------------------------
 *  File:        src/module_19.cpp
 *  Description: Ad-hoc, in-process full-text search indexing service.
 *
 *  The SearchIndexService keeps an in-memory, language-agnostic inverted index
 *  up-to-date with article mutations signaled from the Repository/Service layer.
 *  The component is designed to be relatively small yet thread-safe and fast
 *  enough for medium-sized deployments where an external search appliance
 *  (e.g. ElasticSearch, Solr) would be overkill.
 *
 *  Copyright (c) 2024
 *  IntraLedger Technologies GmbH
 *
 *  Licensed under the Business Source License 1.1
 *  (see accompanying file LICENSE).
 *
 *  NOTE: Production builds should compile with -std=c++20 or later.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <future>
#include <locale>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

// ───── Forward Declarations from other project components ────────────
namespace intraledger::domain
{
    struct Article
    {
        std::uint64_t            id;
        std::string              slug;
        std::string              title;
        std::string              body;   // UTF-8 encoded markdown.
        std::optional<std::string> lang; // Optional ISO-639 language code.
    };
} // namespace intraledger::domain

namespace intraledger::service
{
    struct ArticleRepository
    {
        /**
         *  Fetches the article with its latest persisted content.
         *
         *  Throws std::runtime_error on DB failure, not-found, etc.
         */
        [[nodiscard]] intraledger::domain::Article byId(std::uint64_t id) const;

        /**
         *  Retrieves up to <limit> articles whose IDs appear in |ids|.
         */
        [[nodiscard]] std::vector<intraledger::domain::Article>
        fetchBatch(const std::vector<std::uint64_t>& ids, std::size_t limit) const;
    };
} // namespace intraledger::service

namespace intraledger::common
{
    /* Lightweight logging façade. Real implementation writes to journald + rolling file. */
    enum class LogLevel : int { Trace, Debug, Info, Warn, Error };

    inline void log(LogLevel level, std::string_view component, std::string_view msg) noexcept
    {
        static const char* lvl[] = {"TRACE", "DEBUG", "INFO", "WARN", "ERROR"};
        std::fprintf(stderr, "[%s] %s: %.*s\n",
                     lvl[static_cast<int>(level)], component.data(),
                     static_cast<int>(msg.size()), msg.data());
    }
} // namespace intraledger::common

// ───── Implementation Details for SearchIndexService ─────────────────
namespace intraledger::search
{
    using namespace std::chrono_literals;

    namespace
    {
        /* Simple tokenizer that lower-cases and splits on ASCII whitespace/punct. */
        std::vector<std::string> tokenize(std::string_view src)
        {
            std::vector<std::string> tokens;
            std::string              current;
            current.reserve(32);

            auto flush = [&]()
            {
                if (!current.empty())
                {
                    tokens.emplace_back(std::move(current));
                    current.clear();
                }
            };

            for (unsigned char ch : src)
            {
                if (std::isalnum(ch))
                {
                    current.push_back(static_cast<char>(std::tolower(ch)));
                }
                else
                {
                    flush();
                }
            }
            flush();
            return tokens;
        }
    } // namespace

    /**
     *  Thread-safe, in-memory inverted index.
     *
     *  Each token maps to a set of article IDs containing that token.
     *  The implementation favors read performance—most calls are searches.
     *  Updates happen on a single dedicated worker thread to avoid write
     *  contention and to defer expensive tokenizations off the hot path.
     */
    class SearchIndexService final
    {
    public:
        struct QueryResult
        {
            std::uint64_t id{};
            double        score{}; // Very naive TF score for demonstration.
        };

        SearchIndexService(std::shared_ptr<service::ArticleRepository> repo,
                           std::size_t                              softLimit = 50'000)
            : _repo(std::move(repo))
            , _softLimit(softLimit)
            , _running(true)
            , _worker(&SearchIndexService::consumeQueue, this)
        {
            if (!_repo)
                throw std::invalid_argument("ArticleRepository may not be null");
        }

        ~SearchIndexService()
        {
            stop();
        }

        SearchIndexService(const SearchIndexService&)            = delete;
        SearchIndexService& operator=(const SearchIndexService&) = delete;

        /**
         *  Enqueues an article for (re)indexing.
         *  The caller should *not* hold DB locks.
         */
        void scheduleReindex(std::uint64_t articleId)
        {
            {
                const std::lock_guard lock(_queueMutex);
                _queue.emplace_back(articleId);
            }
            _queueCV.notify_one();
        }

        /**
         *  Drops an article from the index (e.g. deletion or unpublish).
         */
        void dropFromIndex(std::uint64_t articleId)
        {
            {
                const std::unique_lock lock(_indexMutex);
                for (auto& [token, ids] : _inverted)
                    ids.erase(articleId);
            }
            {
                const std::lock_guard<std::mutex> lock(_metaMutex);
                _lengths.erase(articleId);
            }
        }

        /**
         *  Executes a simple AND full-text search.
         */
        [[nodiscard]] std::vector<QueryResult> search(std::string_view query,
                                                      std::size_t      limit  = 25,
                                                      std::size_t      offset = 0) const
        {
            auto tokens = tokenize(query);
            if (tokens.empty())
                return {};

            std::shared_lock shared(_indexMutex);

            // Intersect sets of article IDs for each token
            std::unordered_map<std::uint64_t, std::size_t> docFrequency;
            for (const auto& t : tokens)
            {
                auto it = _inverted.find(t);
                if (it == _inverted.end())
                    return {}; // No hits for this token, early exit.

                for (auto id : it->second)
                {
                    ++docFrequency[id];
                }
            }

            std::vector<QueryResult> results;
            results.reserve(docFrequency.size());
            {
                std::shared_lock metaLock(_metaMutex);
                for (auto [id, matchedTokens] : docFrequency)
                {
                    if (matchedTokens == tokens.size()) // Appears in all tokens
                    {
                        const double len  = static_cast<double>(_lengths.at(id));
                        const double tf   = matchedTokens / len;
                        results.push_back({id, tf});
                    }
                }
            }

            std::sort(results.begin(), results.end(),
                      [](const auto& a, const auto& b)
                      { return a.score > b.score; });

            if (offset >= results.size())
                return {};

            auto beginIt = results.begin() + static_cast<ptrdiff_t>(offset);
            auto endIt   = (limit == 0)
                             ? results.end()
                             : beginIt +
                                   static_cast<ptrdiff_t>(std::min(limit, results.size() - offset));
            return {beginIt, endIt};
        }

        /**
         *  Gracefully stop background worker. Idempotent.
         */
        void stop()
        {
            bool expected = true;
            if (_running.compare_exchange_strong(expected, false))
            {
                _queueCV.notify_one();
                if (_worker.joinable())
                    _worker.join();
            }
        }

    private:
        //-------------------------  Private Data  ------------------------
        std::shared_ptr<service::ArticleRepository>        _repo;
        const std::size_t                                  _softLimit;

        mutable std::shared_mutex                          _indexMutex; // protects _inverted
        std::unordered_map<std::string,
                           std::unordered_set<std::uint64_t>> _inverted; // token -> docIDs

        // Store doc lengths for rudimentary scoring
        mutable std::shared_mutex                          _metaMutex;
        std::unordered_map<std::uint64_t, std::size_t>     _lengths;

        // -------------------------------- Queue machinery
        std::vector<std::uint64_t>                         _queue; // Pending article IDs
        std::mutex                                         _queueMutex;
        std::condition_variable                            _queueCV;
        std::atomic<bool>                                  _running;
        std::thread                                        _worker;

        //----------------------  Background Processing  -----------------
        void consumeQueue()
        try
        {
            while (_running.load())
            {
                std::uint64_t id = 0;

                {
                    std::unique_lock lock(_queueMutex);
                    _queueCV.wait(lock, [this] { return !_queue.empty() || !_running.load(); });

                    if (!_running && _queue.empty())
                        break;

                    id = _queue.back();
                    _queue.pop_back();
                }

                indexSingle(id);
            }
        }
        catch (const std::exception& ex)
        {
            common::log(common::LogLevel::Error, "SearchIndexService",
                        std::string{"Background worker terminated: "} + ex.what());
        }

        void indexSingle(std::uint64_t articleId)
        {
            using common::LogLevel;
            try
            {
                domain::Article art = _repo->byId(articleId);

                // Extract tokens
                auto tokens = tokenize(art.title);
                auto bodyTokens = tokenize(art.body);
                tokens.insert(tokens.end(),
                              std::make_move_iterator(bodyTokens.begin()),
                              std::make_move_iterator(bodyTokens.end()));

                if (tokens.empty())
                    return;

                // Safeguard memory footprint
                if (_lengths.size() > _softLimit)
                {
                    common::log(LogLevel::Warn, "SearchIndexService",
                                "Soft limit reached; refusing to index additional articles.");
                    return;
                }

                // Update inverted index
                {
                    const std::unique_lock lock(_indexMutex);
                    // Remove previous tokens
                    for (auto& [token, ids] : _inverted)
                        ids.erase(articleId);
                    // Re-add
                    for (const auto& tok : tokens)
                        _inverted[tok].insert(articleId);
                }

                // Update metadata
                {
                    const std::unique_lock metaLock(_metaMutex);
                    _lengths[articleId] = tokens.size();
                }

                common::log(LogLevel::Debug, "SearchIndexService",
                            "Indexed article #" + std::to_string(articleId));
            }
            catch (const std::exception& ex)
            {
                common::log(LogLevel::Error, "SearchIndexService",
                            std::string{"Failed to index article "} +
                                std::to_string(articleId) + ": " + ex.what());
            }
        }
    };

} // namespace intraledger::search

// ───── Module Entry Point for DI Container (pseudo-code) ─────────────
// The application’s IoC container (e.g., Boost.DI) would instantiate and
// register SearchIndexService here, wiring dependencies automatically.
//
// BOOST_DI_INJECTOR(
//      std::shared_ptr<intraledger::search::SearchIndexService>
// ) create_search_index_service()
// {
//      return std::make_shared<intraledger::search::SearchIndexService>(
//          injector.create<std::shared_ptr<intraledger::service::ArticleRepository>>());
// }
```