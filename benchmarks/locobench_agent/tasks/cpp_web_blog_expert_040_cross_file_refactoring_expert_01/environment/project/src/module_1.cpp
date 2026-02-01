/*
 *  IntraLedger BlogSuite — SearchIndexRebuilder
 *
 *  src/module_1.cpp
 *
 *  This file implements a background service responsible for
 *  incrementally rebuilding the full-text search index used by the
 *  public-facing API layer.  Whenever the scheduled interval elapses
 *  (or an explicit trigger is received), the service loads all
 *  “dirty” articles from the persistence layer and feeds them to the
 *  search provider.  The implementation is fully thread-safe, stops
 *  cooperatively, and logs diagnostic information via spdlog.
 *
 *  NOTE: Concrete implementations of PostRepository and SearchIndex
 *  live elsewhere in the code base; only the public interface is
 *  forward-declared here to keep the compilation unit focused.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>
#include <spdlog/fmt/ostr.h>

// ──────────────────────────────────────────────────────────────────────────────
// Forward declarations                                                         
// ──────────────────────────────────────────────────────────────────────────────
namespace blogsuite::repositories
{
class PostRepository;  // Provides article persistence abstraction
}  // namespace blogsuite::repositories

namespace blogsuite::search
{
class SearchIndex;     // Provides full-text search backend abstraction
}  // namespace blogsuite::search

// ──────────────────────────────────────────────────────────────────────────────
// Implementation                                                              
// ──────────────────────────────────────────────────────────────────────────────
namespace blogsuite::search
{

/*!
 *  SearchIndexRebuilder
 *
 *  Periodically scans the database for updated or newly created
 *  posts and refreshes the search index to keep it consistent with
 *  the authoritative data store.
 *
 *  The service starts a dedicated worker thread that sleeps for the
 *  configured interval.  It can be stopped at any time via stop(),
 *  and an immediate refresh can be initiated via trigger().
 *
 *  Example usage (service wiring):
 *
 *    auto rebuilder = std::make_unique<SearchIndexRebuilder>(
 *        serviceRegistry.get<PostRepository>(),
 *        serviceRegistry.get<SearchIndex>(),
 *        std::chrono::seconds{120});
 *
 *    rebuilder->start();
 */
class SearchIndexRebuilder
{
public:
    // Disable copy semantics — the worker owns resources that cannot
    // safely be duplicated.
    SearchIndexRebuilder(const SearchIndexRebuilder&) = delete;
    SearchIndexRebuilder& operator=(const SearchIndexRebuilder&) = delete;

    // Move operations are also disallowed for clarity; controlling
    // thread lifecycle across moves is error-prone.
    SearchIndexRebuilder(SearchIndexRebuilder&&)            = delete;
    SearchIndexRebuilder& operator=(SearchIndexRebuilder&&) = delete;

    SearchIndexRebuilder(std::shared_ptr<repositories::PostRepository> postRepo,
                         std::shared_ptr<SearchIndex> searchIndex,
                         std::chrono::seconds interval = std::chrono::seconds{60})
        : postRepo_(std::move(postRepo)),
          searchIndex_(std::move(searchIndex)),
          interval_(interval),
          running_(false)
    {
        if (!postRepo_)
            throw std::invalid_argument("postRepo is null");
        if (!searchIndex_)
            throw std::invalid_argument("searchIndex is null");
        if (interval_.count() <= 0)
            throw std::invalid_argument("interval must be positive");
    }

    ~SearchIndexRebuilder() { stop(); }

    /*!
     *  Starts the background worker.  Calling start() while already
     *  started is a no-op.
     */
    void start()
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true)) return;

        worker_ = std::thread([this] { this->workerLoop(); });
    }

    /*!
     *  Signals the worker to stop and waits for graceful shutdown.
     *  Safe to call multiple times.
     */
    void stop()
    {
        bool expected = true;
        if (!running_.compare_exchange_strong(expected, false)) return;

        {
            std::lock_guard<std::mutex> lock(mtx_);
            manualTrigger_ = true;  // Wake the loop ASAP
        }
        cv_.notify_all();

        if (worker_.joinable()) worker_.join();
    }

    /*!
     *  Forces an immediate rebuild outside the normal schedule.
     */
    void trigger()
    {
        {
            std::lock_guard<std::mutex> lock(mtx_);
            manualTrigger_ = true;
        }
        cv_.notify_all();
    }

    /*!
     *  Modifies the scheduled interval.  The new value will take
     *  effect after the currently executing cycle terminates.
     */
    void setInterval(std::chrono::seconds newInterval)
    {
        if (newInterval.count() <= 0)
            throw std::invalid_argument("newInterval must be positive");

        {
            std::lock_guard<std::mutex> lock(mtx_);
            interval_ = newInterval;
        }
        cv_.notify_all();
    }

private:
    void workerLoop()
    {
        spdlog::info("[SearchIndexRebuilder] Worker thread started.");

        std::unique_lock<std::mutex> lk(mtx_);
        while (running_)
        {
            // Wait for either timeout or manual trigger
            cv_.wait_for(lk, interval_, [this] { return manualTrigger_ || !running_; });

            if (!running_) break;

            manualTrigger_ = false;  // clear the flag
            lk.unlock();             // Release lock during heavy work

            try
            {
                rebuild();
            }
            catch (const std::exception& ex)
            {
                spdlog::error("[SearchIndexRebuilder] Rebuild failed: {}", ex.what());
            }
            catch (...)
            {
                spdlog::critical("[SearchIndexRebuilder] Rebuild threw unknown exception.");
            }

            lk.lock();
        }

        spdlog::info("[SearchIndexRebuilder] Worker thread exiting.");
    }

    /*!
     *  Core logic: collect dirty posts from the repository and push
     *  them to the search index.  Exceptions are propagated to the
     *  caller (workerLoop), which logs and continues.
     */
    void rebuild()
    {
        using Clock = std::chrono::steady_clock;
        const auto start = Clock::now();

        // Step 1: Load IDs of posts that require re-indexing
        std::vector<std::string> dirtyIds = fetchDirtyPostIds();
        if (dirtyIds.empty())
        {
            spdlog::info("[SearchIndexRebuilder] Nothing to index.");
            return;
        }
        spdlog::info("[SearchIndexRebuilder] Found {} posts to index.", dirtyIds.size());

        // Step 2: Batch-load full entities
        std::vector<PostDTO> posts = fetchPostsByIds(dirtyIds);

        // Step 3: Send to search backend (this may use bulk API)
        searchIndex_->bulkUpsert(posts);

        // Step 4: Mark posts as clean to avoid redundant work
        postRepo_->markIndexed(dirtyIds);

        const auto durationMs =
            std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start).count();

        spdlog::info("[SearchIndexRebuilder] Indexed {} posts in {} ms.",
                     posts.size(),
                     durationMs);
    }

    // The PostRepository interface works with data-transfer objects
    // (DTOs) defined elsewhere.  For illustrative purposes, we
    // forward-declare a lightweight view here.
    struct PostDTO
    {
        std::string id;
        std::string title;
        std::string content;
        std::vector<std::string> tags;
        std::chrono::system_clock::time_point publishedAt;
        std::chrono::system_clock::time_point updatedAt;
    };

    // Helper wrappers around repository calls; they translate
    // repository exceptions into runtime_error to maintain a uniform
    // error surface.
    std::vector<std::string> fetchDirtyPostIds()
    {
        try
        {
            return postRepo_->findDirtyIds();
        }
        catch (const std::exception& ex)
        {
            throw std::runtime_error(
                fmt::format("Failed to fetch dirty IDs from repository: {}", ex.what()));
        }
    }

    std::vector<PostDTO> fetchPostsByIds(const std::vector<std::string>& ids)
    {
        try
        {
            return postRepo_->findByIds(ids);
        }
        catch (const std::exception& ex)
        {
            throw std::runtime_error(
                fmt::format("Failed to fetch posts by IDs: {}", ex.what()));
        }
    }

    // ────────────────────────────────────────────────────────────────
    // Data members                                                   
    // ────────────────────────────────────────────────────────────────
    std::shared_ptr<repositories::PostRepository> postRepo_;
    std::shared_ptr<SearchIndex>                  searchIndex_;

    std::chrono::seconds interval_;
    std::thread          worker_;
    std::atomic<bool>    running_;

    std::mutex              mtx_;
    std::condition_variable cv_;
    bool                    manualTrigger_ = false;
};

}  // namespace blogsuite::search


// ──────────────────────────────────────────────────────────────────────────────
// Extensible factory function (optional convenience)                           
// ──────────────────────────────────────────────────────────────────────────────
namespace blogsuite
{

/*!
 *  Convenience helper that constructs and starts a SearchIndexRebuilder
 *  in one call.  Useful for service bootstrapping code.
 */
std::unique_ptr<search::SearchIndexRebuilder> makeSearchIndexRebuilder(
    const std::shared_ptr<repositories::PostRepository>& repo,
    const std::shared_ptr<search::SearchIndex>&          index,
    std::chrono::seconds                                 interval = std::chrono::seconds{60})
{
    auto svc = std::make_unique<search::SearchIndexRebuilder>(repo, index, interval);
    svc->start();
    return svc;
}

}  // namespace blogsuite