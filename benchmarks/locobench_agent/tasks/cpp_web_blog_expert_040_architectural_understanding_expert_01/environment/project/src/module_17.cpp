```cpp
//  SPDX-License-Identifier: MIT
//  File:        src/module_17.cpp
//  Project:     IntraLedger BlogSuite (web_blog)
//  Description: ContentSearchIndexer – asynchronous, thread–safe component that
//               converts blog–posts into a vector–space representation and feeds
//               the central SearchIndexService.  Designed to be wired into the
//               domain–event bus (PostPublished, PostUpdated, PostUnpublished).
//
//  NOTE: This translation unit purposefully avoids any external dependencies
//        beyond the C++ Standard Library.  All project-specific types that are
//        referenced (Repository, SearchIndexService, Logger …) are forward-
//        declared to make the file self–contained and compile-time complete.
//        In the real code-base they live in their dedicated headers and offer
//        richer functionality.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

// ──────────────────────────────────────────────────────────────────────────────
// Forward-declarations of project-level infrastructure
// ──────────────────────────────────────────────────────────────────────────────
namespace util
{
class Logger
{
public:
    static void info(const std::string& msg) noexcept { std::clog << "[INFO]  " << msg << '\n'; }
    static void warn(const std::string& msg) noexcept { std::clog << "[WARN]  " << msg << '\n'; }
    static void error(const std::string& msg) noexcept { std::clog << "[ERROR] " << msg << '\n'; }
};
} // namespace util

namespace model
{
struct Post
{
    std::uint64_t id          {};
    std::string   title       {};
    std::string   body        {};
    std::string   locale      {"en_US"};
    bool          published   {false};
};
} // namespace model

namespace orm
{
template <typename T>
class Repository  // <-- real implementation lives elsewhere
{
public:
    virtual ~Repository() = default;
    virtual std::optional<T>       findById(std::uint64_t id)                = 0;
    virtual std::vector<T>         fetchAllPublished()                       = 0;
    virtual std::vector<std::uint64_t> fetchRecentlyChangedIds(std::size_t max) = 0;
};
} // namespace orm

namespace services
{
class SearchIndexService  // <-- actual implementation depends on dedicated search backend
{
public:
    virtual ~SearchIndexService() = default;
    virtual void indexDocument(
        std::uint64_t                                     id,
        const std::string&                                locale,
        const std::unordered_map<std::string, double>&    termWeights) = 0;

    virtual void removeDocument(std::uint64_t id) = 0;
};
} // namespace services
// ──────────────────────────────────────────────────────────────────────────────



namespace intraledger::blogsuite::search
{

// Utility: simple *very* naïve tokenizer that splits on ASCII word boundaries
static std::vector<std::string> tokenize(std::string_view text)
{
    static const std::regex wordRegex{R"(\b[\w']+\b)", std::regex::icase};
    std::sregex_iterator   begin(text.begin(), text.end(), wordRegex);
    std::sregex_iterator   end;
    std::vector<std::string> result;
    for (auto it = begin; it != end; ++it) {
        result.emplace_back(it->str());
    }
    return result;
}

// Convert token list into a map <token, tf> (term-frequency)
// In a production search-pipeline we would apply stemming, stop-word elimination,
// language-specific rules, tf-idf weighting, etc.  The purpose here is to keep
// the example tractable yet realistic.
static std::unordered_map<std::string, double> computeTermWeights(
    const std::vector<std::string>& tokens)
{
    std::unordered_map<std::string, std::uint32_t> counts;
    for (const auto& t : tokens) {
        ++counts[t];
    }

    const double total = static_cast<double>(tokens.size());
    std::unordered_map<std::string, double> weights;
    weights.reserve(counts.size());

    for (const auto& [token, freq] : counts) {
        weights[token] = static_cast<double>(freq) / total;  // plain TF
    }
    return weights;
}



// ──────────────────────────────────────────────────────────────────────────────
//  ContentSearchIndexer – asynchronous background component
// ──────────────────────────────────────────────────────────────────────────────
class ContentSearchIndexer final
{
public:
    ContentSearchIndexer(std::shared_ptr<orm::Repository<model::Post>>     repo,
                         std::shared_ptr<services::SearchIndexService>     indexSvc,
                         std::size_t                                       workerThreadCount = std::thread::hardware_concurrency())
        : m_repository{std::move(repo)}
        , m_indexService{std::move(indexSvc)}
    {
        if (!m_repository)  { throw std::invalid_argument{"ContentSearchIndexer: repository is null"}; }
        if (!m_indexService){ throw std::invalid_argument{"ContentSearchIndexer: search index service is null"}; }

        // At least one thread; fall back to 1 if HW concurrency not defined.
        if (workerThreadCount == 0) workerThreadCount = 1;

        m_workers.reserve(workerThreadCount);
        for (std::size_t i = 0; i < workerThreadCount; ++i) {
            m_workers.emplace_back(&ContentSearchIndexer::workerLoop, this);
        }

        util::Logger::info("ContentSearchIndexer started with " +
                           std::to_string(workerThreadCount) + " worker thread(s)");
    }

    // Non-copyable
    ContentSearchIndexer(const ContentSearchIndexer&)            = delete;
    ContentSearchIndexer& operator=(const ContentSearchIndexer&) = delete;

    ~ContentSearchIndexer()
    {
        {
            std::lock_guard<std::mutex> lk{m_mutex};
            m_stopping = true;
        }
        m_cv.notify_all();
        for (auto& th : m_workers) {
            if (th.joinable()) {
                th.join();
            }
        }
        util::Logger::info("ContentSearchIndexer gracefully shut down");
    }

    // Public API ────────────────────────────────────────────────────────────

    // Queue indexing of a single post.  Input may come from a synchronous HTTP
    // request (e.g. author hit “Publish”) or from the event bus.
    void scheduleIndexing(std::uint64_t postId) { enqueue(Task{Type::Index, postId}); }

    // When a post gets unpublished or deleted.
    void scheduleRemoval(std::uint64_t postId)  { enqueue(Task{Type::Remove, postId}); }

    // Administrative operation: rebuild entire index.  The function returns as
    // soon as the tasks are queued; processing runs in the background.
    void reindexAll()
    {
        util::Logger::info("ContentSearchIndexer: scheduling full re-index");

        try {
            auto posts = m_repository->fetchAllPublished();
            for (const auto& p : posts) {
                enqueue(Task{Type::Index, p.id});
            }
        }
        catch (const std::exception& ex) {
            util::Logger::error(std::string{"ContentSearchIndexer: reindexAll failed – "} + ex.what());
        }
    }

private:
    enum class Type : std::uint8_t { Index, Remove };

    struct Task
    {
        Type          type;
        std::uint64_t postId;
    };

    void enqueue(Task task)
    {
        {
            std::lock_guard<std::mutex> lk{m_mutex};
            m_queue.push(std::move(task));
        }
        m_cv.notify_one();
    }

    // Main worker loop that lives on each background thread
    void workerLoop()
    {
        while (true)
        {
            Task task;
            {
                std::unique_lock<std::mutex> lk{m_mutex};
                m_cv.wait(lk, [&]{ return m_stopping || !m_queue.empty(); });

                if (m_stopping && m_queue.empty()) {
                    return;  // time to exit
                }
                task = std::move(m_queue.front());
                m_queue.pop();
            }

            try {
                if (task.type == Type::Index) {
                    processIndexTask(task.postId);
                } else {
                    m_indexService->removeDocument(task.postId);
                }
            }
            catch (const std::exception& ex) {
                std::ostringstream oss;
                oss << "ContentSearchIndexer: failed to process task for post #" << task.postId
                    << " – " << ex.what();
                util::Logger::error(oss.str());
            }
        }
    }

    // Fetch post, tokenize and feed the SearchIndexService
    void processIndexTask(std::uint64_t postId)
    {
        auto maybePost = m_repository->findById(postId);
        if (!maybePost) {
            util::Logger::warn("ContentSearchIndexer: post #" + std::to_string(postId) + " not found");
            m_indexService->removeDocument(postId); // ensure dangling documents are purged
            return;
        }

        const auto& post = *maybePost;
        if (!post.published) {
            util::Logger::info("ContentSearchIndexer: post #" + std::to_string(postId) +
                               " is not published – removing from index");
            m_indexService->removeDocument(postId);
            return;
        }

        // Combine title + body; in production we’d weigh title higher, but such
        // heuristics are better handled inside the search backend.
        const std::string combined = post.title + ' ' + post.body;

        // Tokenize and compute term weights
        auto tokens  = tokenize(combined);
        if (tokens.empty()) {
            util::Logger::warn("ContentSearchIndexer: post #" + std::to_string(postId) +
                               " produced no tokens – skipping");
            return;
        }

        auto weights = computeTermWeights(tokens);
        m_indexService->indexDocument(post.id, post.locale, weights);

        util::Logger::info("ContentSearchIndexer: indexed post #" + std::to_string(postId) +
                           " (" + std::to_string(tokens.size()) + " tokens)");
    }

    // Members
    std::shared_ptr<orm::Repository<model::Post>>  m_repository;
    std::shared_ptr<services::SearchIndexService>  m_indexService;

    std::vector<std::thread>           m_workers;
    std::queue<Task>                   m_queue;
    std::mutex                         m_mutex;
    std::condition_variable            m_cv;
    std::atomic<bool>                  m_stopping{false};
};


// ──────────────────────────────────────────────────────────────────────────────
//  Factory helper – nice ergonomics for dependency injection
// ──────────────────────────────────────────────────────────────────────────────
std::unique_ptr<ContentSearchIndexer>
makeContentSearchIndexer(std::shared_ptr<orm::Repository<model::Post>> repo,
                         std::shared_ptr<services::SearchIndexService> svc,
                         std::size_t                                   workers = 0)
{
    return std::make_unique<ContentSearchIndexer>(std::move(repo),
                                                  std::move(svc),
                                                  workers);
}

} // namespace intraledger::blogsuite::search
```