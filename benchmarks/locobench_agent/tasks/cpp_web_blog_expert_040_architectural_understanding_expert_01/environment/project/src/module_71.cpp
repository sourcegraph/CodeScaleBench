#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cctype>
#include <functional>
#include <iostream>
#include <mutex>
#include <numeric>
#include <queue>
#include <regex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

/**
 *  IntraLedger BlogSuite
 *  ---------------------
 *  src/module_71.cpp
 *
 *  This compilation unit contains a minimal yet production–grade
 *  full-text search micro-service living inside the monolith.
 *
 *  Responsibilities
 *  ----------------
 *   • Collect blog-post mutations (CREATE, UPDATE, DELETE)
 *   • Incrementally maintain an in-memory inverted index
 *   • Provide a thread-safe, low-latency query interface
 *
 *  The indexer is intentionally in-memory—should the dataset grow
 *  beyond the host capacity the project ships a swappable adapter
 *  that pushes identical messages onto an external search stack
 *  (e.g. OpenSearch).  Keeping the API identical allows us to
 *  remain vendor-agnostic while supporting small deployments.
 *
 *  NOTE
 *  ----
 *  This TU is header-only from the POV of the rest of the codebase.
 *  External modules simply   `#include "module_71.cpp"`
 *  which, while unusual, avoids the need for separate translation
 *  units in a single-binary deployment model.
 */

namespace ilbs       // IntraLedger BlogSuite
{
namespace search
{

// -----------------------------------------------------------------------------
//  Trivial Logger (placeholder until the real log façade kicks in)
// -----------------------------------------------------------------------------
enum class LogLevel { Debug, Info, Warn, Error };

inline void log(LogLevel lvl, const std::string &msg)
{
    // In production we would defer to the central logging bus.
    static const char *kLvlStr[] = {"DEBUG", "INFO", "WARN", "ERROR"};
    std::clog << "[" << kLvlStr[static_cast<int>(lvl)] << "] " << msg << '\n';
}

// -----------------------------------------------------------------------------
//  DTO representing the subset of fields required for indexing
// -----------------------------------------------------------------------------
struct PostDTO
{
    using PostId = std::uint64_t;

    PostId id              = 0;
    std::string slug       {};         // e.g. "/my-first-post"
    std::string title      {};
    std::string body       {};         // Markdown or HTML
    std::vector<std::string> tags {};

    bool operator==(const PostDTO &other) const noexcept { return id == other.id; }

    // For std::unordered_* containers
    struct Hash
    {
        std::size_t operator()(const PostDTO &p) const noexcept { return std::hash<PostId>{}(p.id); }
    };
};

// -----------------------------------------------------------------------------
//  Internal helper: Tokenizer
//  Splits input text into lowercase alphanumeric tokens
// -----------------------------------------------------------------------------
class Tokenizer
{
public:
    static std::vector<std::string> tokenize(const std::string &text)
    {
        std::vector<std::string> tokens;
        std::string current;
        current.reserve(32);

        auto flush_token = [&]() {
            if (!current.empty())
            {
                std::transform(current.begin(), current.end(), current.begin(),
                               [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                tokens.emplace_back(std::move(current));
                current.clear();
                current.reserve(32);
            }
        };

        for (char ch : text)
        {
            if (std::isalnum(static_cast<unsigned char>(ch)))
            {
                current.push_back(ch);
            }
            else
            {
                flush_token();
            }
        }
        flush_token();
        return tokens;
    }
};

// -----------------------------------------------------------------------------
//  SearchIndexer
//  --------------
//  Asynchronous worker that processes index-update jobs.
//
//  Lifetime:
//    • Lazily instantiated on first use (Meyers singleton)
//    • Worker thread exits on shutdown()
// -----------------------------------------------------------------------------
class SearchIndexer
{
public:
    // Simplified for demonstrational purposes; a production system
    // would inject config, thread-pool handles, etc.
    static SearchIndexer &instance()
    {
        static SearchIndexer idx;
        return idx;
    }

    // Non-copyable
    SearchIndexer(const SearchIndexer &)            = delete;
    SearchIndexer &operator=(const SearchIndexer &) = delete;

    // ---------------------------------------------------------------------
    //  Public API
    // ---------------------------------------------------------------------
    void schedule_index(const PostDTO &post)
    {
        enqueue_job(Job{JobType::Upsert, post});
    }

    void schedule_remove(PostDTO::PostId id)
    {
        enqueue_job(Job{JobType::Erase, PostDTO{id}});
    }

    // Blocking search.  Returns up to `max_results` matching post-ids,
    // sorted by simple TF-IDF-like relevance.
    std::vector<PostDTO::PostId> search(const std::string &query, std::size_t max_results = 25) const
    {
        const auto tokens = Tokenizer::tokenize(query);
        if (tokens.empty())
            return {};

        std::unordered_map<PostDTO::PostId, double> scores;
        {
            // Read-side lock
            std::shared_lock<std::shared_mutex> lk(_indexMutex);
            for (const auto &token : tokens)
            {
                auto it = _inverted.find(token);
                if (it == _inverted.end())
                    continue;

                const double idf = 1.0 / static_cast<double>(it->second.size());
                for (auto postId : it->second)
                {
                    scores[postId] += idf; // naive tf-idf
                }
            }
        }

        // Order by score desc
        std::vector<std::pair<PostDTO::PostId, double>> sorted(scores.begin(), scores.end());
        std::sort(sorted.begin(), sorted.end(),
                  [](auto &a, auto &b) { return a.second > b.second; });

        std::vector<PostDTO::PostId> results;
        results.reserve(std::min(max_results, sorted.size()));
        for (std::size_t i = 0; i < sorted.size() && i < max_results; ++i)
            results.push_back(sorted[i].first);

        return results;
    }

    // Explicit global teardown (called from atexit within the monolith)
    void shutdown()
    {
        {
            std::lock_guard<std::mutex> lk(_queueMutex);
            _terminate = true;
        }
        _cv.notify_one();
        if (_worker.joinable())
            _worker.join();
    }

private:
    enum class JobType : std::uint8_t { Upsert, Erase };

    struct Job
    {
        JobType type;
        PostDTO payload; // Only .id used for Erase
    };

    // Constructor: spawn worker thread
    SearchIndexer()
    {
        _worker = std::thread(&SearchIndexer::worker_loop, this);
        log(LogLevel::Info, "SearchIndexer worker thread spawned");
    }

    ~SearchIndexer()
    {
        shutdown();
        log(LogLevel::Info, "SearchIndexer gracefully destroyed");
    }

    // ---------------------------------------------------------------------
    //  Threading & Synchronization
    // ---------------------------------------------------------------------
    void enqueue_job(Job &&job)
    {
        {
            std::lock_guard<std::mutex> lk(_queueMutex);
            _jobs.emplace(std::move(job));
        }
        _cv.notify_one();
    }

    void worker_loop()
    {
        try
        {
            while (true)
            {
                Job current;
                {
                    std::unique_lock<std::mutex> lk(_queueMutex);
                    _cv.wait(lk, [&] { return !_jobs.empty() || _terminate; });
                    if (_terminate && _jobs.empty())
                        break;
                    current = std::move(_jobs.front());
                    _jobs.pop();
                }

                if (current.type == JobType::Upsert)
                    index_post(current.payload);
                else
                    erase_post(current.payload.id);
            }
        }
        catch (const std::exception &ex)
        {
            log(LogLevel::Error, std::string("SearchIndexer worker_loop crashed: ") + ex.what());
        }
    }

    // ---------------------------------------------------------------------
    //  Index maintenance
    // ---------------------------------------------------------------------
    void index_post(const PostDTO &post)
    {
        std::unordered_set<std::string> unique_tokens;
        auto collect = [&](const std::string &text) {
            for (auto &tok : Tokenizer::tokenize(text))
                unique_tokens.insert(std::move(tok));
        };

        collect(post.title);
        collect(post.body);
        for (const auto &tag : post.tags)
            collect(tag);

        {
            // Writer lock
            std::unique_lock<std::shared_mutex> lk(_indexMutex);

            // Remove stale tokens for this post (if already exists)
            erase_post_locked(post.id, /*lockHeld=*/true);

            for (const auto &tok : unique_tokens)
                _inverted[tok].insert(post.id);
        }

        log(LogLevel::Debug, "Post " + std::to_string(post.id) + " indexed (" +
                                 std::to_string(unique_tokens.size()) + " tokens)");
    }

    void erase_post(PostDTO::PostId id)
    {
        std::unique_lock<std::shared_mutex> lk(_indexMutex);
        erase_post_locked(id, /*lockHeld=*/true);
        log(LogLevel::Debug, "Post " + std::to_string(id) + " removed from index");
    }

    void erase_post_locked(PostDTO::PostId id, bool /*lockHeld*/)
    {
        for (auto it = _inverted.begin(); it != _inverted.end();)
        {
            it->second.erase(id);
            if (it->second.empty())
                it = _inverted.erase(it);
            else
                ++it;
        }
    }

    // ---------------------------------------------------------------------
    //  Members
    // ---------------------------------------------------------------------
    // Inverted index: token -> set<postId>
    mutable std::shared_mutex _indexMutex;
    std::unordered_map<std::string, std::unordered_set<PostDTO::PostId>> _inverted;

    // Worker thread & job queue
    std::queue<Job> _jobs;
    std::mutex _queueMutex;
    std::condition_variable _cv;
    std::atomic<bool> _terminate{false};
    std::thread _worker;
};

} // namespace search
} // namespace ilbs

// -----------------------------------------------------------------------------
//  Simple self-test (compiled in non-Release builds)
// -----------------------------------------------------------------------------
#ifndef NDEBUG
#include <cassert>

namespace
{
void self_test()
{
    using namespace ilbs::search;
    auto &idx = SearchIndexer::instance();

    PostDTO p1{1, "hello-world", "Hello World",
               "Welcome to my first post about C++ and concurrency."};
    PostDTO p2{2, "second", "Advanced Topics",
               "In this entry we explore move semantics and perfect forwarding."};
    idx.schedule_index(p1);
    idx.schedule_index(p2);

    // Allow worker to catch up
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    auto res = idx.search("concurrency c++");
    assert(!res.empty() && res.front() == 1);

    idx.schedule_remove(1);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    res = idx.search("concurrency");
    assert(res.empty());

    idx.shutdown();
}
} // namespace

int main()
{
    self_test();
    std::cout << "SearchIndexer self-test PASSED\n";
    return 0;
}
#endif