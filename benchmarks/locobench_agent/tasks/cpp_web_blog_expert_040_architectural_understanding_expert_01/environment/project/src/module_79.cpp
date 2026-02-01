```cpp
/**
 *  src/module_79.cpp
 *  IntraLedger BlogSuite – Full-Text Indexing Service
 *
 *  Copyright (c) 2024
 *
 *  This source file is part of the IntraLedger BlogSuite monolith.
 *  It implements a lightweight, in-process full-text indexing layer
 *  that feeds data to the search module while decoupling the core
 *  application from any concrete search backend (e.g. ElasticSearch,
 *  OpenSearch, Xapian).  It is purposely naïve yet production-grade
 *  enough to serve as a stop-gap until a dedicated search appliance
 *  is wired-in through the Service Layer’s provider interface.
 *
 *  The component runs as a background worker that receives “indexing
 *  jobs” through an in-memory queue.  Jobs are generated whenever an
 *  article is created, updated, or deleted, and are idempotent by
 *  design.  The class is thread-safe and exception-aware.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <regex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace intraledger {
namespace search {

/**
 * @brief Lightweight DTO emitted by the domain when an article changes.
 */
struct IndexingJob
{
    enum class Action
    {
        Upsert,
        Remove
    };

    std::uint64_t articleId {};
    Action        action { Action::Upsert };

    [[nodiscard]] std::string toString() const
    {
        return "[IndexingJob id=" + std::to_string(articleId) +
               (action == Action::Upsert ? " action=UPSERT]" : " action=REMOVE]");
    }
};

/**
 * @brief Interface for the ArticleRepository used during indexing.
 *
 * The real implementation lives inside the Repository Layer and
 * knows how to materialise entities from the ORM.  We depend on it
 * through this narrow boundary to avoid fat transitive includes.
 */
class ArticleRepository
{
public:
    virtual ~ArticleRepository() noexcept = default;

    /**
     * @returns raw HTML content of the requested Article
     * @throws std::runtime_error if the article does not exist or the
     *         underlying data-source is unavailable.
     */
    [[nodiscard]] virtual std::string fetchHtmlBody(std::uint64_t articleId) = 0;
};

/**
 * @brief Internal representation of a text fragment stored in the index.
 */
struct IndexEntry
{
    std::string                                  plainText;
    std::chrono::system_clock::time_point        indexedAt;
};

/**
 * @class FullTextIndexerService
 *
 * Thread-safe background component responsible for translating domain
 * events into plain-text searchable artefacts.  Public members are
 * minimal: callers schedule a job, and consumers query the index.
 *
 * The class owns a worker thread that blocks on a condition variable
 * until jobs are available or the service is torn down.
 */
class FullTextIndexerService : public std::enable_shared_from_this<FullTextIndexerService>
{
public:
    explicit FullTextIndexerService(std::shared_ptr<ArticleRepository> repository)
        : repository_{ std::move(repository) }
        , stopRequested_{ false }
        , worker_{ &FullTextIndexerService::workerLoop, this }
    {
        if (!repository_) { throw std::invalid_argument("ArticleRepository must not be null"); }
    }

    FullTextIndexerService(const FullTextIndexerService&)            = delete;
    FullTextIndexerService& operator=(const FullTextIndexerService&) = delete;

    ~FullTextIndexerService()
    {
        {
            std::lock_guard<std::mutex> lock(queueMutex_);
            stopRequested_.store(true, std::memory_order_release);
        }
        queueCv_.notify_one();
        if (worker_.joinable())
        {
            worker_.join();
        }
    }

    /**
     * @brief Schedules a new indexing job.
     *
     * The method is exception-free and will never block longer than
     * necessary to push the job into the internal queue.
     */
    void scheduleJob(IndexingJob job)
    {
        {
            std::lock_guard<std::mutex> lock(queueMutex_);
            jobQueue_.emplace_back(std::move(job));
        }
        queueCv_.notify_one();
    }

    /**
     * @brief Runs a best-effort substring search against the local index.
     *
     * This implementation is intentionally simple: it scans the
     * indexed plain-text chunks and returns matching IDs if any.
     * A more sophisticated setup would delegate to a dedicated
     * IR engine (BM25, vector-based, etc.).
     *
     * @warning The call acquires a shared lock and therefore is
     *          compatible with parallel read-access but will block
     *          during bulk-update operations.
     */
    [[nodiscard]] std::vector<std::uint64_t> search(std::string_view needle) const
    {
        std::shared_lock<std::shared_mutex> readLock(indexMutex_);

        std::vector<std::uint64_t> results;
        results.reserve(index_.size());

        for (const auto& [id, entry] : index_)
        {
            if (entry.plainText.find(needle) != std::string::npos) { results.push_back(id); }
        }
        return results;
    }

private:
    // Dependencies
    std::shared_ptr<ArticleRepository> repository_;

    // Concurrency primitives & state
    mutable std::shared_mutex                   indexMutex_;   // protects |index_|
    std::unordered_map<std::uint64_t, IndexEntry> index_;

    std::mutex                 queueMutex_;
    std::condition_variable    queueCv_;
    std::vector<IndexingJob>   jobQueue_;
    std::atomic_bool           stopRequested_;
    std::thread                worker_;

    /**
     * @brief Main processing loop living in |worker_|.
     *
     * Picks jobs in FCFS order and executes them one after another.
     * The catch-all handler guarantees that one poisoned job will not
     * kill the thread—errors are dumped to stderr and processing goes
     * on.
     */
    void workerLoop() noexcept
    {
        while (true)
        {
            std::vector<IndexingJob> localBuffer;
            {
                std::unique_lock<std::mutex> lock(queueMutex_);
                queueCv_.wait(lock, [this] {
                    return stopRequested_.load(std::memory_order_acquire) || !jobQueue_.empty();
                });

                if (stopRequested_.load(std::memory_order_acquire) && jobQueue_.empty()) { break; }

                localBuffer.swap(jobQueue_); // move-out pending jobs
            }

            for (auto& job : localBuffer)
            {
                try
                {
                    processJob(job);
                }
                catch (const std::exception& ex)
                {
                    std::cerr << "[FullTextIndexerService] Failed to process "
                              << job.toString() << ": " << ex.what() << '\n';
                }
            }
        }
    }

    /**
     * @brief Executes a single job, updating the internal state.
     */
    void processJob(const IndexingJob& job)
    {
        switch (job.action)
        {
        case IndexingJob::Action::Upsert: upsert(job.articleId); break;
        case IndexingJob::Action::Remove: remove(job.articleId); break;
        default: throw std::logic_error("Unhandled IndexingJob::Action variant");
        }
    }

    /**
     * @brief Inserts or updates the index entry for an Article.
     *
     * Fetches raw HTML from the repository, sanitises it, and stores
     * the resulting plain-text payload within the internal map.
     */
    void upsert(std::uint64_t articleId)
    {
        const std::string html = repository_->fetchHtmlBody(articleId);
        const std::string text = htmlToPlainText(html);

        {
            std::unique_lock<std::shared_mutex> writeLock(indexMutex_);
            index_[articleId] = IndexEntry{ text, std::chrono::system_clock::now() };
        }
    }

    /**
     * @brief Deletes an Article’s entry from the index.
     */
    void remove(std::uint64_t articleId)
    {
        std::unique_lock<std::shared_mutex> writeLock(indexMutex_);
        index_.erase(articleId);
    }

    /**
     * @brief Very naïve HTML-to-text converter.
     *
     * Strips tags using a regular expression and collapses incidental
     * whitespace.  This is by no means suitable for perfect rendering
     * but suffices for indexing purposes.
     */
    static std::string htmlToPlainText(const std::string& html)
    {
        static const std::regex tagRe { R"(<[^>]+>)", std::regex::optimize };
        std::string             withoutTags = std::regex_replace(html, tagRe, " ");

        // Collapse consecutive whitespace characters
        static const std::regex wsRe { R"(\s+)", std::regex::optimize };
        std::string             collapsed = std::regex_replace(withoutTags, wsRe, " ");

        // Trim leading/trailing spaces
        const auto first = collapsed.find_first_not_of(' ');
        if (first == std::string::npos) { return {}; }
        const auto last = collapsed.find_last_not_of(' ');
        return collapsed.substr(first, last - first + 1);
    }
};

} // namespace search
} // namespace intraledger
```