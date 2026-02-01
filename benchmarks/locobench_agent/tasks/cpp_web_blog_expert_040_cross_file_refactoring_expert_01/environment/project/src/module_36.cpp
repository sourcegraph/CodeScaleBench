```cpp
/**
 *  IntraLedger BlogSuite
 *  ---------------------
 *  File:        src/module_36.cpp
 *  Author:      IntraLedger Dev Team
 *  Description: Production-grade Search-Index module. Provides an
 *               asynchronous service that (re)indexes blog-posts into the
 *               platform’s full-text search backend.  Thread-safe, exception
 *               aware, and designed to integrate with the existing Repository
 *               and Job Processor layers.
 *
 *  NOTE: This file purposefully avoids tight coupling with concrete storage
 *        or queue implementations; stub classes are provided for clarity and
 *        can be wired to the project’s actual components during linkage.
 *
 *  C++ Standard: C++17
 */

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <filesystem>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

// Third-party logging library (header-only in BlogSuite vendor/ tree)
#include <spdlog/spdlog.h>

namespace intraledger::search {

// ---------------------------------------------------------
// Domain Model
// ---------------------------------------------------------
struct Post final
{
    std::string                               id;           // GUID
    std::string                               slug;
    std::string                               title;
    std::string                               body;
    std::string                               language;
    std::chrono::system_clock::time_point     published_at;
    std::chrono::system_clock::time_point     last_updated;
};


// ---------------------------------------------------------
// SearchDocument – representation for backend
// ---------------------------------------------------------
struct SearchDocument
{
    std::string                               id;
    std::string                               title;
    std::string                               body;
    std::string                               language;
    std::chrono::system_clock::time_point     timestamp;
};


// ---------------------------------------------------------
// Abstract SearchBackend
// ---------------------------------------------------------
class SearchBackend
{
public:
    virtual ~SearchBackend() = default;

    // Index or update documents.
    virtual void upsert(const std::vector<SearchDocument>& docs) = 0;

    // Remove documents by ID.
    virtual void remove(const std::vector<std::string>& ids) = 0;

    // Health-probe, throws when backend is unavailable.
    virtual void ping() = 0;
};

// ---------------------------------------------------------
// Lightweight JSON-Flat-File backend (default fallback).
// Pragmatic, for development and testing only.
// ---------------------------------------------------------
class JsonFileBackend final : public SearchBackend
{
    std::filesystem::path m_path;
    std::mutex            m_ioMutex;

public:
    explicit JsonFileBackend(std::filesystem::path path = "search_index.json")
        : m_path{std::move(path)}
    {
        try
        {
            if (!std::filesystem::exists(m_path))
            {
                std::ofstream ofs(m_path);
                ofs << "{}";
            }
        }
        catch (const std::exception& ex)
        {
            spdlog::error("JsonFileBackend ctor error: {}", ex.what());
            throw;
        }
    }

    void upsert(const std::vector<SearchDocument>& docs) override
    {
        std::scoped_lock lk{m_ioMutex};
        std::unordered_map<std::string, std::string> jsonStore = readInternal();

        for (const auto& d : docs)
        {
            jsonStore[d.id] = d.title + "|" + d.body; // Horribly naive, but fine for PoC.
        }
        writeInternal(jsonStore);
    }

    void remove(const std::vector<std::string>& ids) override
    {
        std::scoped_lock lk{m_ioMutex};
        auto store = readInternal();
        for (const auto& id : ids)
            store.erase(id);
        writeInternal(store);
    }

    void ping() override
    {
        // Ensure file is reachable.
        if (!std::filesystem::is_regular_file(m_path))
            throw std::runtime_error("search index file missing");
    }

private:
    std::unordered_map<std::string, std::string> readInternal()
    {
        std::ifstream ifs(m_path);
        std::unordered_map<std::string, std::string> result;

        if (!ifs.is_open()) return result;

        std::string line;
        while (std::getline(ifs, line))
        {
            // format: id:payload
            auto pos = line.find(':');
            if (pos == std::string::npos) continue;
            result.emplace(line.substr(0, pos), line.substr(pos + 1));
        }
        return result;
    }

    void writeInternal(const std::unordered_map<std::string, std::string>& store)
    {
        std::ofstream ofs(m_path, std::ios::trunc);
        for (const auto& [k, v] : store)
        {
            ofs << k << ":" << v << '\n';
        }
    }
};

// ---------------------------------------------------------
// PostRepository – simplified interface to ORM layer.
// ---------------------------------------------------------
class PostRepository
{
public:
    virtual ~PostRepository() = default;

    // Retrieve N posts requiring (re)indexing.
    virtual std::vector<Post> fetchPending(std::size_t limit) = 0;

    // Mark posts as indexed.
    virtual void markIndexed(const std::vector<std::string>& ids) = 0;
};


// ---------------------------------------------------------
// Thread-Pool util – minimal fixed-size pool.
// ---------------------------------------------------------
class ThreadPool
{
public:
    explicit ThreadPool(std::size_t threads)
        : m_stop{false}
    {
        threads = std::max<std::size_t>(1, threads);

        for (std::size_t i = 0; i < threads; ++i)
        {
            m_workers.emplace_back([this] {
                while (true)
                {
                    std::function<void()> task;
                    {
                        std::unique_lock lk{m_mutex};
                        m_cv.wait(lk, [this] { return m_stop || !m_tasks.empty(); });
                        if (m_stop && m_tasks.empty()) return;
                        task = std::move(m_tasks.front());
                        m_tasks.pop();
                    }
                    try
                    {
                        task();
                    }
                    catch (const std::exception& ex)
                    {
                        spdlog::error("ThreadPool task exception: {}", ex.what());
                    }
                }
            });
        }
    }

    ~ThreadPool()
    {
        {
            std::lock_guard lk{m_mutex};
            m_stop = true;
        }
        m_cv.notify_all();
        for (auto& w : m_workers) w.join();
    }

    template <typename F, typename... Args>
    auto submit(F&& f, Args&&... args)
        -> std::future<std::invoke_result_t<F, Args...>>
    {
        using Ret = std::invoke_result_t<F, Args...>;
        auto task =
            std::make_shared<std::packaged_task<Ret()>>(
                std::bind(std::forward<F>(f), std::forward<Args>(args)...));

        std::future<Ret> res = task->get_future();
        {
            std::lock_guard lk{m_mutex};
            if (m_stop) throw std::runtime_error("submit on stopped ThreadPool");
            m_tasks.emplace([task] { (*task)(); });
        }
        m_cv.notify_one();
        return res;
    }

private:
    std::vector<std::thread>          m_workers;
    std::queue<std::function<void()>> m_tasks;

    std::mutex                        m_mutex;
    std::condition_variable           m_cv;
    bool                              m_stop;
};

// ---------------------------------------------------------
// IndexServiceConfig
// ---------------------------------------------------------
struct IndexServiceConfig
{
    std::size_t poolSize      = std::thread::hardware_concurrency();
    std::size_t batchSize     = 25;
    std::chrono::milliseconds idleSleep{ 3'000 }; // 3 seconds
};


// ---------------------------------------------------------
// SearchIndexService – orchestrates asynchronous indexing
// ---------------------------------------------------------
class SearchIndexService final
{
public:
    SearchIndexService(std::unique_ptr<PostRepository> repo,
                       std::unique_ptr<SearchBackend> backend,
                       IndexServiceConfig cfg = {})
        : m_repo{ std::move(repo) }
        , m_backend{ std::move(backend) }
        , m_cfg{ std::move(cfg) }
        , m_pool{ m_cfg.poolSize }
    {
        if (!m_repo || !m_backend) throw std::invalid_argument("Null deps");
        m_backend->ping();
    }

    // Non-copyable
    SearchIndexService(const SearchIndexService&)            = delete;
    SearchIndexService& operator=(const SearchIndexService&) = delete;

    // Graceful shutdown
    ~SearchIndexService()
    {
        stop();
    }

    void start()
    {
        bool expected = false;
        if (!m_running.compare_exchange_strong(expected, true))
            return; // already running

        m_coordThread = std::thread([this] { coordinatorLoop(); });
        spdlog::info("SearchIndexService started");
    }

    void stop()
    {
        if (!m_running.exchange(false)) return;
        {
            std::lock_guard lk{ m_triggerMutex };
            m_triggerCv.notify_all();
        }
        if (m_coordThread.joinable()) m_coordThread.join();
        spdlog::info("SearchIndexService stopped");
    }

    // External systems (e.g., Web Admin) can trigger an immediate re-index.
    void triggerNow()
    {
        std::lock_guard lk{ m_triggerMutex };
        m_triggerCv.notify_one();
    }

private:
    std::unique_ptr<PostRepository>          m_repo;
    std::unique_ptr<SearchBackend>           m_backend;
    IndexServiceConfig                       m_cfg;

    ThreadPool                               m_pool;

    std::atomic_bool                         m_running{ false };
    std::thread                              m_coordThread;

    std::mutex                               m_triggerMutex;
    std::condition_variable                  m_triggerCv;

    // -----------------------------------------------------
    // Coordinator logic: fetch ➔ transform ➔ submit
    // -----------------------------------------------------
    void coordinatorLoop()
    {
        while (m_running)
        {
            try
            {
                auto pending = m_repo->fetchPending(m_cfg.batchSize);
                if (pending.empty())
                {
                    // Wait for next trigger / idle sleep
                    std::unique_lock lk{ m_triggerMutex };
                    m_triggerCv.wait_for(lk, m_cfg.idleSleep, [this] { return !m_running; });
                    continue;
                }

                auto fut = m_pool.submit([this, posts = std::move(pending)]() {
                    processBatch(posts);
                });

                // We don't block on the future; exceptions are logged within the ThreadPool.
                (void)fut;
            }
            catch (const std::exception& ex)
            {
                spdlog::error("CoordinatorLoop exception: {}", ex.what());
            }
        }
    }

    // -----------------------------------------------------
    // Convert and push to backend
    // -----------------------------------------------------
    void processBatch(const std::vector<Post>& posts)
    {
        std::vector<SearchDocument> docs;
        docs.reserve(posts.size());
        std::transform(posts.begin(), posts.end(), std::back_inserter(docs),
                       [](const Post& p) {
                           return SearchDocument{
                               p.id, p.title, p.body, p.language, p.last_updated
                           };
                       });

        try
        {
            m_backend->upsert(docs);

            std::vector<std::string> ids;
            ids.reserve(posts.size());
            std::transform(posts.begin(), posts.end(), std::back_inserter(ids),
                           [](const Post& p) { return p.id; });

            m_repo->markIndexed(ids);

            spdlog::info("Indexed {} posts", posts.size());
        }
        catch (const std::exception& ex)
        {
            spdlog::error("processBatch failed: {}", ex.what());
        }
    }
};


// ---------------------------------------------------------
// Mock Implementations (wired during runtime in production)
// ---------------------------------------------------------
namespace mock {

// A trivial in-memory repository for development / unit tests.
class InMemoryPostRepository final : public PostRepository
{
    std::vector<Post>                m_store;
    std::mutex                       m_mutex;

public:
    explicit InMemoryPostRepository(std::vector<Post> seed = {})
        : m_store{ std::move(seed) }
    {}

    std::vector<Post> fetchPending(std::size_t limit) override
    {
        std::lock_guard lk{ m_mutex };
        std::vector<Post> out;
        auto it = std::remove_if(m_store.begin(), m_store.end(),
            [&out, limit](const Post& p)
            {
                if (out.size() >= limit) return false;
                // Simulate "needs indexing" if published less than 1 minute ago.
                auto now = std::chrono::system_clock::now();
                if (now - p.last_updated < std::chrono::minutes{60})
                {
                    out.emplace_back(p);
                    return false;
                }
                return false;
            });
        return out;
    }

    void markIndexed(const std::vector<std::string>& ids) override
    {
        std::lock_guard lk{ m_mutex };
        for (const auto& id : ids)
        {
            auto it = std::find_if(m_store.begin(), m_store.end(),
                                   [&id](const Post& p) { return p.id == id; });
            if (it != m_store.end())
            {
                // Move last_updated forward so it won't be re-picked.
                it->last_updated -= std::chrono::hours(24);
            }
        }
    }
};

} // namespace mock


// ---------------------------------------------------------
// Self-contained test harness (compiled only in unit builds)
// ---------------------------------------------------------
#ifdef INTRALEDGER_SEARCH_TEST_MAIN
int main()
{
    using namespace std::chrono_literals;
    std::vector<Post> seed = {
        {"1", "hello-world", "Hello World", "Body A", "en",
         std::chrono::system_clock::now() - 30min,
         std::chrono::system_clock::now() - 2min},
        {"2", "bonjour", "Bonjour Monde", "Corps B", "fr",
         std::chrono::system_clock::now() - 20min,
         std::chrono::system_clock::now() - 2min}
    };

    auto repo    = std::make_unique<mock::InMemoryPostRepository>(seed);
    auto backend = std::make_unique<JsonFileBackend>("test_index.json");

    SearchIndexService service(
        std::move(repo), std::move(backend),
        IndexServiceConfig{ .poolSize = 2, .batchSize = 10, .idleSleep = 1s });

    service.start();
    std::this_thread::sleep_for(5s);
    service.triggerNow();
    std::this_thread::sleep_for(2s);
    service.stop();
}
#endif

} // namespace intraledger::search
```