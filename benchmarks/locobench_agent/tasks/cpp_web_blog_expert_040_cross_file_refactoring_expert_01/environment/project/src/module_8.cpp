// -----------------------------------------------------------------------------
//  File: src/module_8.cpp
//  Project: IntraLedger BlogSuite (web_blog)
//  Description:
//      Full-text search indexing and query service. Responsible for maintaining
//      an in-memory inverted index that supports quick lookup of blog posts or
//      knowledge-base articles.  Index updates are processed asynchronously to
//      avoid blocking HTTP request/response cycles.
//
//      Thread-safe singleton implementation with background worker.
// -----------------------------------------------------------------------------
//  Copyright © IntraLedger.
// -----------------------------------------------------------------------------

#include <algorithm>
#include <atomic>
#include <cctype>
#include <condition_variable>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <shared_mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <spdlog/spdlog.h>

namespace intraledger::blog::search {

// -----------------------------------------------------------------------------
//  Type aliases & forward declarations
// -----------------------------------------------------------------------------
using DocumentId = std::uint64_t;

// Simple RAII guard that calls a functor on destruction
template <typename F>
class ScopedGuard {
public:
    explicit ScopedGuard(F f) noexcept : _f(std::move(f)) {}
    ~ScopedGuard() noexcept { _f(); }
    ScopedGuard(const ScopedGuard&) = delete;
    ScopedGuard& operator=(const ScopedGuard&) = delete;

private:
    F _f;
};

// -----------------------------------------------------------------------------
//  SearchIndexService
// -----------------------------------------------------------------------------
class SearchIndexService {
public:
    // Obtain singleton instance (thread-safe on C++11 and newer)
    static SearchIndexService& instance() {
        static SearchIndexService g_instance;
        return g_instance;
    }

    // Public API ---------------------------------------------------------------
    // Schedules a document to be (re)indexed asynchronously
    void scheduleIndexing(DocumentId id, std::string_view text) {
        {
            std::lock_guard<std::mutex> lock(_jobMutex);
            _jobQueue.emplace(Job{ id, std::string(text) });
        }
        _jobCv.notify_one();
    }

    // Executes a full-text search query. Returns top matching document IDs,
    // ordered by simple TF (term frequency) scoring.
    std::vector<DocumentId> search(std::string_view query, std::size_t limit = 25) const {
        if (query.empty() || limit == 0) { return {}; }

        // Tokenize once
        const auto tokens = tokenize(query);

        std::unordered_map<DocumentId, std::size_t> scoreTable;
        {
            std::shared_lock<std::shared_mutex> rlock(_indexMutex);

            for (const auto& token : tokens) {
                const auto it = _invertedIndex.find(token);
                if (it == _invertedIndex.end()) { continue; }
                for (const auto& docId : it->second) {
                    ++scoreTable[docId];  // simple TF score
                }
            }
        }

        // Transform map to vector and sort by score descending
        std::vector<std::pair<DocumentId, std::size_t>> ranked(scoreTable.begin(), scoreTable.end());
        std::sort(ranked.begin(), ranked.end(),
                  [](auto&& a, auto&& b) { return a.second > b.second; });

        if (ranked.size() > limit) { ranked.resize(limit); }

        std::vector<DocumentId> result;
        result.reserve(ranked.size());
        for (const auto& [docId, _] : ranked) { result.push_back(docId); }

        return result;
    }

    // Clean shutdown (useful for unit tests / graceful termination)
    void shutdown() {
        _terminate.store(true, std::memory_order_release);
        _jobCv.notify_one();
        if (_worker.joinable()) { _worker.join(); }
    }

    // Non-copyable / Non-movable
    SearchIndexService(const SearchIndexService&)            = delete;
    SearchIndexService(SearchIndexService&&)                 = delete;
    SearchIndexService& operator=(const SearchIndexService&) = delete;
    SearchIndexService& operator=(SearchIndexService&&)      = delete;

private:
    // Background job structure
    struct Job {
        DocumentId      id;
        std::string     text;
    };

    // Constructor / Destructor -------------------------------------------------
    SearchIndexService()
        : _terminate(false),
          _worker(&SearchIndexService::workerLoop, this) {
        spdlog::info("[SearchIndexService] Initialized.");
    }

    ~SearchIndexService() {
        shutdown();
        spdlog::info("[SearchIndexService] Destroyed.");
    }

    // Implementation details ---------------------------------------------------
    static std::vector<std::string> tokenize(std::string_view text) {
        std::vector<std::string> tokens;

        std::string token;
        token.reserve(32);

        auto flush = [&]() {
            if (!token.empty()) {
                std::transform(token.begin(), token.end(), token.begin(),
                               [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                tokens.emplace_back(std::move(token));
                token.clear();
            }
        };

        for (char ch : text) {
            if (std::isalnum(static_cast<unsigned char>(ch))) {
                token.push_back(ch);
            } else {
                flush();
            }
        }
        flush();
        return tokens;
    }

    void indexDocument(const Job& job) {
        const auto tokens = tokenize(job.text);

        // Rebuild per-document token set to avoid duplicates
        std::unordered_set<std::string> uniqueTokens(tokens.begin(), tokens.end());

        {
            std::unique_lock<std::shared_mutex> wlock(_indexMutex);

            // For simplicity, first remove previous references to this doc
            for (auto& [word, docset] : _invertedIndex)
                docset.erase(job.id);

            // Insert new references
            for (const auto& word : uniqueTokens)
                _invertedIndex[word].insert(job.id);
        }

        spdlog::debug("[SearchIndexService] Indexed document id={} ({} tokens).",
                      job.id, uniqueTokens.size());
    }

    void workerLoop() {
        spdlog::info("[SearchIndexService] Worker thread started.");
        while (!_terminate.load(std::memory_order_acquire)) {
            Job currentJob;

            {
                std::unique_lock<std::mutex> lock(_jobMutex);

                _jobCv.wait(lock, [this] {
                    return !_jobQueue.empty() || _terminate.load(std::memory_order_relaxed);
                });

                if (_terminate.load(std::memory_order_relaxed)) { break; }

                currentJob = std::move(_jobQueue.front());
                _jobQueue.pop();
            }

            // Process outside of lock to minimize contention
            auto guard = ScopedGuard([&] {
                // catch and log any thrown exception to prevent thread exit
                if (std::uncaught_exceptions() > 0) {
                    spdlog::error("[SearchIndexService] uncaught exception during indexing.");
                }
            });

            try {
                indexDocument(currentJob);
            } catch (const std::exception& ex) {
                spdlog::error("[SearchIndexService] Failed to index doc id={}, reason: {}",
                              currentJob.id, ex.what());
            } catch (...) {
                spdlog::error("[SearchIndexService] Unknown error while indexing doc id={}",
                              currentJob.id);
            }
        }
        spdlog::info("[SearchIndexService] Worker thread exiting.");
    }

    // State --------------------------------------------------------------------
    // Inverted index: word -> set<docId>
    std::unordered_map<std::string, std::unordered_set<DocumentId>> _invertedIndex;
    mutable std::shared_mutex _indexMutex;

    // Job queue
    std::queue<Job>  _jobQueue;
    std::mutex       _jobMutex;
    std::condition_variable _jobCv;

    // Worker
    std::atomic<bool> _terminate;
    std::thread       _worker;
};

// -----------------------------------------------------------------------------
//  Convenience free functions exposed to other translation units
// -----------------------------------------------------------------------------
void index_document_async(DocumentId id, std::string_view text) {
    SearchIndexService::instance().scheduleIndexing(id, text);
}

std::vector<DocumentId> query_documents(std::string_view query,
                                        std::size_t limit = 25) {
    return SearchIndexService::instance().search(query, limit);
}

// -----------------------------------------------------------------------------
//  Example manual test (will be compiled out in release builds)
// -----------------------------------------------------------------------------
#if defined(ILBS_SEARCH_SELFTEST) && !defined(NDEBUG)
#include <iostream>
int main() {
    index_document_async(1, "Hello World, this is a test document.");
    index_document_async(2, "Another document says hello!");

    // Give the worker a chance to process
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    auto hits = query_documents("hello");
    std::cout << "Hits for 'hello': ";
    for (auto h : hits) std::cout << h << " ";
    std::cout << std::endl;

    SearchIndexService::instance().shutdown();
}
#endif

} // namespace intraledger::blog::search