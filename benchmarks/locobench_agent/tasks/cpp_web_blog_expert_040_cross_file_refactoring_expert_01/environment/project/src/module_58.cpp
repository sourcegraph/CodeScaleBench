```cpp
/**********************************************************************************************
 *  IntraLedger BlogSuite – Search Index Synchronizer
 *
 *  File:        src/module_58.cpp
 *  Description: Background component that reacts to domain-level content events and keeps the
 *               search index in sync with persisted entities.  This translation unit contains
 *               a small, thread-safe task queue, an asynchronous worker, and a naive retry
 *               strategy with exponential back-off. Real-world code would register to an event
 *               bus; here we expose a public API that higher layers (Service / Controller) can
 *               call directly.
 *
 *  Copyright:   © 2024 IntraLedger
 *  License:     Proprietary – All Rights Reserved
 *********************************************************************************************/

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <list>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>                 // Logging (external dependency)
#include <spdlog/async.h>

namespace intraledger::blogsuite::search {

//-------------------------------------------------------------------------------------------------
// Utility types
//-------------------------------------------------------------------------------------------------

/**
 * Enumerates supported index mutation operations.
 */
enum class Operation : std::uint8_t
{
    AddOrUpdate,
    Remove
};

/**
 * Represents an outstanding task waiting to be processed by the background thread.
 */
struct IndexTask
{
    Operation                   op;
    std::string                 docId;
    std::optional<std::string>  content;   // Required for AddOrUpdate
    std::vector<std::string>    tags;      // Optional meta information
};

//-------------------------------------------------------------------------------------------------
// ISearchBackend – Abstracts the physical search backend (e.g., Xapian, Elastic, SQLite FTS).
//-------------------------------------------------------------------------------------------------

class ISearchBackend
{
public:
    virtual ~ISearchBackend() = default;

    virtual void addOrUpdate(std::string_view docId,
                             std::string_view document,
                             std::span<const std::string> tags) = 0;

    virtual void remove(std::string_view docId) = 0;

    virtual bool ping(std::chrono::milliseconds timeout) noexcept = 0;
};

//-------------------------------------------------------------------------------------------------
// DummySearchBackend – Minimal stub used when the real implementation is not linked in.
//-------------------------------------------------------------------------------------------------

class DummySearchBackend final : public ISearchBackend
{
public:
    void addOrUpdate(std::string_view docId,
                     std::string_view /*document*/,
                     std::span<const std::string> /*tags*/) override
    {
        spdlog::debug("DummyBackend: indexing/updating doc '{}'", docId);
    }

    void remove(std::string_view docId) override
    {
        spdlog::debug("DummyBackend: removing doc '{}'", docId);
    }

    bool ping(std::chrono::milliseconds /*timeout*/) noexcept override
    {
        return true;
    }
};

//-------------------------------------------------------------------------------------------------
// Thread-safe unbounded queue – minimalistic wrapper around std::queue.
//-------------------------------------------------------------------------------------------------

template <typename T>
class ConcurrentQueue
{
public:
    void push(T item)
    {
        {
            std::lock_guard<std::mutex> lock{m_mutex};
            m_queue.emplace(std::move(item));
        }
        m_cv.notify_one();
    }

    std::optional<T> tryPop()
    {
        std::lock_guard<std::mutex> lock{m_mutex};
        if (m_queue.empty())
            return std::nullopt;

        T tmp = std::move(m_queue.front());
        m_queue.pop();
        return tmp;
    }

    bool waitPop(T& out, std::chrono::milliseconds timeout)
    {
        std::unique_lock<std::mutex> lock{m_mutex};
        if (!m_cv.wait_for(lock, timeout, [this] { return !m_queue.empty() || m_terminate; }))
            return false;   // timeout

        if (m_queue.empty())
            return false;   // terminating

        out = std::move(m_queue.front());
        m_queue.pop();
        return true;
    }

    void terminate()
    {
        {
            std::lock_guard<std::mutex> lock{m_mutex};
            m_terminate = true;
        }
        m_cv.notify_all();
    }

private:
    std::queue<T>  m_queue;
    std::mutex     m_mutex;
    std::condition_variable m_cv;
    bool           m_terminate{false};
};

//-------------------------------------------------------------------------------------------------
// SearchIndexSynchronizer – public façade used by higher layers.
//-------------------------------------------------------------------------------------------------

class SearchIndexSynchronizer final
{
public:
    explicit SearchIndexSynchronizer(std::unique_ptr<ISearchBackend> backend =
                                         std::make_unique<DummySearchBackend>())
        : m_backend{std::move(backend)}
    {
        if (!m_backend)
            throw std::invalid_argument("backend must not be null");

        startWorker();
    }

    ~SearchIndexSynchronizer()
    {
        stopWorker();
    }

    /**
     * Queue an Add/Update operation. Content is copied because the caller might be transient
     * (e.g., HTTP controller stack).  In real-world code we might use shared_ptr with copy-on-
     * write or move semantics for efficiency.
     */
    void scheduleAddOrUpdate(std::string docId,
                             std::string content,
                             std::vector<std::string> tags = {})
    {
        IndexTask task{
            .op      = Operation::AddOrUpdate,
            .docId   = std::move(docId),
            .content = std::move(content),
            .tags    = std::move(tags)
        };
        m_queue.push(std::move(task));
    }

    /**
     * Queue a Remove operation.
     */
    void scheduleRemove(std::string docId)
    {
        IndexTask task{
            .op      = Operation::Remove,
            .docId   = std::move(docId),
            .content = std::nullopt
        };
        m_queue.push(std::move(task));
    }

    /**
     * For unit tests – blocks until the queue is empty or the timeout expires.
     */
    bool flush(std::chrono::milliseconds maxWait = std::chrono::seconds{10})
    {
        const auto timeoutPoint = std::chrono::steady_clock::now() + maxWait;
        while (std::chrono::steady_clock::now() < timeoutPoint)
        {
            if (!m_queue.tryPop().has_value())
                return true; // empty
            std::this_thread::sleep_for(std::chrono::milliseconds{25});
        }
        return false;
    }

private:
    // ------------------- Worker Thread Lifecycle ----------------------------------------------

    void startWorker()
    {
        m_worker = std::thread{[this] { workerLoop(); }};
        m_threadId = m_worker.get_id();
        spdlog::info("SearchIndexSynchronizer worker started (thread id: {})",
                     reinterpret_cast<std::uintptr_t>(&m_threadId));
    }

    void stopWorker()
    {
        m_queue.terminate();
        if (m_worker.joinable())
            m_worker.join();
        spdlog::info("SearchIndexSynchronizer worker stopped");
    }

    // ------------------- Core processing logic -------------------------------------------------

    void workerLoop()
    {
        using namespace std::chrono_literals;

        std::size_t      consecutiveFailures = 0U;
        constexpr auto   baseBackoff   = 250ms;
        constexpr auto   maxBackoff    = 10s;

        while (true)
        {
            IndexTask task;
            if (!m_queue.waitPop(task, 500ms))
            {
                // Check termination flag after timeout
                if (m_queue.waitPop(task, 0ms) == false && m_queue.tryPop() == std::nullopt)
                    break;
                continue;
            }

            try
            {
                if (!ensureBackendReady())
                    throw std::runtime_error("search backend unavailable");

                if (task.op == Operation::AddOrUpdate)
                {
                    m_backend->addOrUpdate(task.docId,
                                           task.content.value_or(""),
                                           task.tags);
                }
                else
                {
                    m_backend->remove(task.docId);
                }

                consecutiveFailures = 0; // reset
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Failed to process search index task for '{}': {}",
                              task.docId, ex.what());

                // Simple exponential back-off and re-queue
                ++consecutiveFailures;
                auto backoff = std::min(baseBackoff * (1u << consecutiveFailures), maxBackoff);
                std::this_thread::sleep_for(backoff);

                // Re-queue with best-effort; if terminate was requested we abandon.
                if (!m_queue.tryPop().has_value())
                    m_queue.push(std::move(task));
            }
        }
    }

    bool ensureBackendReady()
    {
        using namespace std::chrono_literals;

        constexpr auto pingTimeout = 1s;

        if (m_backend->ping(pingTimeout))
            return true;

        spdlog::warn("Search backend ping failed, attempting one reconnect");

        // Real implementation would try to re-initialise connection here.
        // We'll just wait and hope for the best.
        std::this_thread::sleep_for(250ms);
        return m_backend->ping(pingTimeout);
    }

    // ------------------- Data Members ----------------------------------------------------------

    std::unique_ptr<ISearchBackend> m_backend;
    ConcurrentQueue<IndexTask>      m_queue;
    std::thread                     m_worker;
    std::thread::id                 m_threadId;

    // Non-copyable, non-movable
    SearchIndexSynchronizer(const SearchIndexSynchronizer&)            = delete;
    SearchIndexSynchronizer& operator=(const SearchIndexSynchronizer&) = delete;
    SearchIndexSynchronizer(SearchIndexSynchronizer&&)                 = delete;
    SearchIndexSynchronizer& operator=(SearchIndexSynchronizer&&)      = delete;
};

//-------------------------------------------------------------------------------------------------
// Static instance – lazy initialisation using Meyers' singleton for global access inside the
// monolith.  For DI setups, prefer explicit instantiation.
//-------------------------------------------------------------------------------------------------

SearchIndexSynchronizer& searchIndexSynchronizer()
{
    static SearchIndexSynchronizer instance{};
    return instance;
}

} // namespace intraledger::blogsuite::search
```