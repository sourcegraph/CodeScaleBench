```cpp
/*
 *  IntraLedger BlogSuite
 *  File: src/module_5.cpp
 *
 *  Description:
 *      SearchIndexService – lightweight, asynchronous, in-memory full-text
 *      search engine used by BlogSuite to index and search Blog Articles.
 *
 *  Responsibilities:
 *      • Maintain an inverted index of all indexed documents
 *      • Provide thread-safe, lock-free(ish) enqueue interface for index jobs
 *      • Spawn one or more background workers to process index/remove tasks
 *      • Offer synchronous query API for fast look-ups (used by REST layer)
 *
 *  Notes:
 *      – The implementation is intentionally self-contained and dependency-free
 *        to avoid coupling with the remainder of BlogSuite’s code base. In the
 *        real project, Article objects would come from the ORM and logging
 *        would be wired into the core logger. Inter-module communication is
 *        limited to avoid circular dependencies.
 *
 *  Copyright:
 *      © 2024 IntraLedger, LLC.  All rights reserved.
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <condition_variable>
#include <exception>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace blogsuite {

/* ------------------------------------------------------------------------- */
/*                               Helper Types                                */
/* ------------------------------------------------------------------------- */

struct Article {
    std::int64_t id          = 0;
    std::string  title       = {};
    std::string  content     = {};
    std::string  languageIso = "en";
    std::vector<std::string> tags;

    bool operator==(const Article& other) const noexcept { return id == other.id; }
};

/* A tiny logger replacement. In production, replace with proper logging API */
enum class LogLevel { Debug, Info, Warn, Error };

inline void log(LogLevel lvl, std::string_view msg) noexcept
{
    static const char* levelStr[] = { "DEBUG", "INFO", "WARN", "ERROR" };
    std::cerr << "[" << levelStr[static_cast<int>(lvl)] << "] " << msg << std::endl;
}

/* ------------------------------------------------------------------------- */
/*                           SearchIndexBackend                              */
/* ------------------------------------------------------------------------- */

/*
 * An in-memory inverted index map<token, set<ArticleId>>
 * Tokenizer strategy: lowercase words, strip punctuation, whitespace split.
 * The class is *not* thread-safe; callers synchronize externally.
 */
class SearchIndexBackend final
{
public:
    using ArticleId  = std::int64_t;
    using Token      = std::string;
    using PostingSet = std::unordered_set<ArticleId>;

    void index(const Article& article)
    {
        remove(article.id); // Re-index if it already exists

        for (const auto& token : tokenize(article)) {
            m_invertedIndex[token].insert(article.id);
        }
    }

    void remove(ArticleId id)
    {
        for (auto& [token, set] : m_invertedIndex) {
            set.erase(id);
        }
    }

    std::vector<ArticleId> search(const std::string& term, std::size_t limit = 20) const
    {
        const auto& set      = m_invertedIndex.find(normalizeToken(term));
        std::vector<ArticleId> result;

        if (set != m_invertedIndex.end()) {
            result.reserve(std::min(limit, set->second.size()));
            for (const auto id : set->second) {
                result.push_back(id);
                if (result.size() == limit) break;
            }
        }
        return result;
    }

private:
    static std::string normalizeToken(std::string token)
    {
        std::transform(token.begin(), token.end(), token.begin(), ::tolower);
        token.erase(std::remove_if(token.begin(), token.end(),
                                   [](char c) { return std::ispunct(static_cast<unsigned char>(c)); }),
                    token.end());
        return token;
    }

    static std::vector<Token> tokenize(const Article& article)
    {
        std::vector<Token> tokens;
        auto pushTokens = [&](const std::string& text) {
            std::string buff;
            for (char c : text) {
                if (std::isspace(static_cast<unsigned char>(c))) {
                    if (!buff.empty()) {
                        tokens.push_back(normalizeToken(buff));
                        buff.clear();
                    }
                } else {
                    buff.push_back(c);
                }
            }
            if (!buff.empty()) tokens.push_back(normalizeToken(buff));
        };

        pushTokens(article.title);
        pushTokens(article.content);
        for (const auto& tag : article.tags) {
            pushTokens(tag);
        }

        return tokens;
    }

    std::unordered_map<Token, PostingSet> m_invertedIndex;
};

/* ------------------------------------------------------------------------- */
/*                   SearchIndexService – Public Interface                   */
/* ------------------------------------------------------------------------- */

class SearchIndexService
{
public:
    explicit SearchIndexService(std::size_t workerThreads = std::thread::hardware_concurrency());
    ~SearchIndexService();

    // Disable copying; allow moving
    SearchIndexService(const SearchIndexService&)            = delete;
    SearchIndexService& operator=(const SearchIndexService&) = delete;
    SearchIndexService(SearchIndexService&&)                 = default;
    SearchIndexService& operator=(SearchIndexService&&)      = default;

    /* ---------------------------------- API ---------------------------------- */

    // Enqueue index or remove operations; returns future for completion tracking.
    std::future<void> enqueueIndex(Article article);
    std::future<void> enqueueRemove(std::int64_t articleId);

    // Synchronous query, thread-safe
    std::vector<std::int64_t> search(std::string term, std::size_t limit = 20) const;

private:
    enum class CommandType { Index, Remove, Shutdown };

    struct Command {
        CommandType               type;
        std::optional<Article>    article;
        std::optional<std::int64_t> articleId;
        std::promise<void>        promise;
    };

    /* --------------------------------- Worker -------------------------------- */

    void workerLoop(std::size_t workerId);

    /* ---------------------------- Internal Members --------------------------- */

    mutable std::shared_mutex            m_indexMutex;  // Protects m_backend
    SearchIndexBackend                   m_backend;

    std::queue<std::unique_ptr<Command>> m_queue;
    mutable std::mutex                   m_queueMutex;
    std::condition_variable              m_cv;

    std::vector<std::thread>             m_workers;
    std::atomic<bool>                    m_stop{false};
};

/* ------------------------------------------------------------------------- */
/*                    SearchIndexService – Implementation                     */
/* ------------------------------------------------------------------------- */

SearchIndexService::SearchIndexService(std::size_t workerThreads)
{
    if (workerThreads == 0) workerThreads = 1;

    log(LogLevel::Info, "SearchIndexService starting with " + std::to_string(workerThreads) + " workers");

    m_workers.reserve(workerThreads);
    for (std::size_t i = 0; i < workerThreads; ++i) {
        m_workers.emplace_back([this, i] { workerLoop(i); });
    }
}

SearchIndexService::~SearchIndexService()
{
    // Enqueue shutdown commands, one per worker
    {
        std::lock_guard<std::mutex> lock(m_queueMutex);
        for (std::size_t i = 0; i < m_workers.size(); ++i) {
            auto cmd   = std::make_unique<Command>();
            cmd->type  = CommandType::Shutdown;
            m_queue.push(std::move(cmd));
        }
    }
    m_cv.notify_all();
    for (auto& w : m_workers) {
        if (w.joinable()) w.join();
    }
    log(LogLevel::Info, "SearchIndexService stopped");
}

std::future<void> SearchIndexService::enqueueIndex(Article article)
{
    auto cmd      = std::make_unique<Command>();
    auto fut      = cmd->promise.get_future();
    cmd->type     = CommandType::Index;
    cmd->article  = std::move(article);

    {
        std::lock_guard<std::mutex> lock(m_queueMutex);
        m_queue.push(std::move(cmd));
    }
    m_cv.notify_one();
    return fut;
}

std::future<void> SearchIndexService::enqueueRemove(std::int64_t articleId)
{
    auto cmd        = std::make_unique<Command>();
    auto fut        = cmd->promise.get_future();
    cmd->type       = CommandType::Remove;
    cmd->articleId  = articleId;

    {
        std::lock_guard<std::mutex> lock(m_queueMutex);
        m_queue.push(std::move(cmd));
    }
    m_cv.notify_one();
    return fut;
}

std::vector<std::int64_t> SearchIndexService::search(std::string term, std::size_t limit) const
{
    std::shared_lock<std::shared_mutex> lock(m_indexMutex);
    return m_backend.search(term, limit);
}

void SearchIndexService::workerLoop(std::size_t workerId)
{
    try {
        while (!m_stop.load(std::memory_order_relaxed)) {
            std::unique_ptr<Command> cmd;

            {
                std::unique_lock<std::mutex> lock(m_queueMutex);
                m_cv.wait(lock, [this] { return !m_queue.empty(); });

                cmd = std::move(m_queue.front());
                m_queue.pop();
            }

            if (!cmd) continue;

            switch (cmd->type) {
                case CommandType::Index: {
                    if (!cmd->article) {
                        cmd->promise.set_exception(std::make_exception_ptr(std::runtime_error("Missing Article")));
                        break;
                    }
                    {
                        std::unique_lock<std::shared_mutex> lock(m_indexMutex);
                        m_backend.index(*cmd->article);
                    }
                    log(LogLevel::Debug,
                        "Worker " + std::to_string(workerId) +
                            " indexed article #" + std::to_string(cmd->article->id));
                    cmd->promise.set_value();
                    break;
                }
                case CommandType::Remove: {
                    {
                        std::unique_lock<std::shared_mutex> lock(m_indexMutex);
                        m_backend.remove(cmd->articleId.value_or(0));
                    }
                    log(LogLevel::Debug,
                        "Worker " + std::to_string(workerId) +
                            " removed article #" + std::to_string(cmd->articleId.value_or(-1)));
                    cmd->promise.set_value();
                    break;
                }
                case CommandType::Shutdown: {
                    m_stop.store(true, std::memory_order_relaxed);
                    cmd->promise.set_value();
                    break;
                }
            }
        }
    } catch (const std::exception& ex) {
        log(LogLevel::Error, std::string("SearchIndexService worker exception: ") + ex.what());
        // Worker dies; service keeps running with remaining workers
    }
}

/* ------------------------------------------------------------------------- */
/*                               Unit Testing                                */
/* ------------------------------------------------------------------------- */
/*  To keep this module self-contained we include a minimal test routine that
 *  only compiles when this file is built as a standalone translation unit.
 *  Usage: g++ -std=c++20 -pthread src/module_5.cpp -DSEARCH_MODULE_STANDALONE && ./a.out
 */
#ifdef SEARCH_MODULE_STANDALONE
int main()
{
    blogsuite::SearchIndexService service(2);

    blogsuite::Article a1{ 1, "Hello World", "Welcome to the new BlogSuite!", "en", { "intro", "welcome" } };
    blogsuite::Article a2{ 2, "C++20 Coroutines", "Deep dive into coroutines in modern C++.", "en",
                           { "c++", "coroutines", "programming" } };

    auto f1 = service.enqueueIndex(a1);
    auto f2 = service.enqueueIndex(a2);

    f1.wait();
    f2.wait();

    auto results = service.search("c++");
    for (auto id : results) {
        std::cout << "Found Article #" << id << '\n';
    }

    return 0;
}
#endif /* SEARCH_MODULE_STANDALONE */

} // namespace blogsuite
```