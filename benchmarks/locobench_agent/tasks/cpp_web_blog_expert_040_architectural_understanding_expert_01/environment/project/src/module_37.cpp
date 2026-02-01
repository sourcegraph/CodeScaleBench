```cpp
/**
 *  File:        src/module_37.cpp
 *  Project:     IntraLedger BlogSuite  (web_blog)
 *
 *  Description:
 *      Implements an asynchronous job processor that is responsible for running
 *      background tasks such as full–text search (FTS) re-indexing, e-mail
 *      delivery, media conversions, and cache warming.  The processor is
 *      designed to be embedded in the monolith and observes RAII semantics so
 *      that it can be safely constructed on program start-up and gracefully
 *      destroyed during shutdown without additional plumbing.
 *
 *  Notes:
 *      • The surrounding codebase is large; therefore, only the interfaces that
 *        are strictly required here are declared locally and should be replaced
 *        by their canonical counterparts in the real project tree.
 *      • C++20 is assumed for <chrono> calendar extensions, coroutines, etc.
 *        No C++20-specific features are used here to remain maximally portable.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <ostream>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace intraledger::blogsuite
{
// ──────────────────────────────────────────────────────────────────────────────
//  Minimal logging facade – will eventually be backed by spdlog or similar.
// ──────────────────────────────────────────────────────────────────────────────
class Logger
{
public:
    enum class Level
    {
        Debug,
        Info,
        Warning,
        Error,
        Fatal
    };

    static Logger &instance()
    {
        static Logger inst;
        return inst;
    }

    void log(Level level, std::string_view msg) noexcept
    {
        try
        {
            auto ts = std::chrono::system_clock::now();
            auto tt = std::chrono::system_clock::to_time_t(ts);
            std::stringstream ss;
            ss << std::put_time(std::localtime(&tt), "%Y-%m-%d %H:%M:%S");

            std::lock_guard lk(_mtx);
            std::cerr << "[" << ss.str() << "]"
                      << '[' << to_string(level) << "] " << msg << '\n';
        }
        catch (...)
        {
            // Logging must never throw
        }
    }

private:
    Logger()                                     = default;
    Logger(const Logger &)                       = delete;
    Logger(Logger &&)                            = delete;
    Logger &operator=(const Logger &)            = delete;
    Logger &operator=(Logger &&)                 = delete;
    ~Logger()                                    = default;

    static constexpr std::string_view to_string(Level l) noexcept
    {
        switch (l)
        {
        case Level::Debug:
            return "DBG";
        case Level::Info:
            return "INF";
        case Level::Warning:
            return "WRN";
        case Level::Error:
            return "ERR";
        case Level::Fatal:
            return "FTL";
        default:
            return "UNK";
        }
    }

    std::mutex _mtx;
};

// Utility macro for brevity
#define BLOGSUITE_LOG(LEVEL, MSG) ::intraledger::blogsuite::Logger::instance().log(LEVEL, MSG)

// ──────────────────────────────────────────────────────────────────────────────
//  Interfaces representing other bounded contexts.
// ──────────────────────────────────────────────────────────────────────────────
struct IArticleRepository
{
    virtual ~IArticleRepository() = default;
    [[nodiscard]] virtual std::optional<std::string>
    fetchArticleContent(std::uint64_t articleId) const = 0;
};

struct ISearchIndexGateway
{
    virtual ~ISearchIndexGateway() = default;
    virtual void upsertDocument(std::uint64_t docId, std::string_view body) = 0;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Async Job infrastructure.
// ──────────────────────────────────────────────────────────────────────────────
class AsyncJob
{
public:
    explicit AsyncJob(std::string name) : _name(std::move(name)) {}
    virtual ~AsyncJob() = default;

    AsyncJob(const AsyncJob &)            = delete;
    AsyncJob &operator=(const AsyncJob &) = delete;

    [[nodiscard]] std::string_view name() const noexcept { return _name; }

    // Executed by worker threads
    virtual void run() = 0;

private:
    std::string _name;
};

/**
 *  Priority queue wrapper with FIFO tie-breaking.
 */
class JobQueue
{
public:
    enum class Priority : int
    {
        Background = 0,
        Normal     = 5,
        High       = 10
    };

    void push(std::shared_ptr<AsyncJob> job, Priority prio)
    {
        std::lock_guard lk(_mtx);
        _queue.emplace(Item{++_counter, prio, std::move(job)});
        _cv.notify_one();
    }

    std::shared_ptr<AsyncJob> waitAndPop()
    {
        std::unique_lock lk(_mtx);
        _cv.wait(lk, [&] { return !_queue.empty() || _shutdown; });

        if (_shutdown && _queue.empty())
            return nullptr;

        auto item = std::move(const_cast<Item &>(_queue.top()));
        _queue.pop();
        return std::move(item.job);
    }

    void shutdown()
    {
        {
            std::lock_guard lk(_mtx);
            _shutdown = true;
        }
        _cv.notify_all();
    }

private:
    struct Item
    {
        std::uint64_t                seq;
        Priority                     prio;
        std::shared_ptr<AsyncJob>    job;

        bool operator<(const Item &rhs) const noexcept
        {
            // Higher priority first; seq for FIFO tie-break
            if (prio != rhs.prio)
                return static_cast<int>(prio) < static_cast<int>(rhs.prio);
            return seq > rhs.seq;
        }
    };

    std::mutex                           _mtx;
    std::condition_variable              _cv;
    std::priority_queue<Item>            _queue;
    std::atomic<std::uint64_t>           _counter{0};
    bool                                 _shutdown{false};
};

/**
 *  Responsible for launching worker threads that continuously drain the queue.
 */
class AsyncJobProcessor
{
public:
    explicit AsyncJobProcessor(std::size_t numThreads = std::thread::hardware_concurrency())
        : _threads(numThreads > 0 ? numThreads : 2)
    {
        BLOGSUITE_LOG(Logger::Level::Info,
                      "Starting AsyncJobProcessor with " + std::to_string(_threads.size()) + " worker(s)");
        for (auto &t : _threads)
        {
            t = std::thread(&AsyncJobProcessor::workerLoop, this);
        }
    }

    ~AsyncJobProcessor()
    {
        BLOGSUITE_LOG(Logger::Level::Info, "Shutting down AsyncJobProcessor");
        _queue.shutdown();
        for (auto &t : _threads)
        {
            if (t.joinable())
                t.join();
        }
    }

    template <typename JobT, typename... Args>
    void submit(JobQueue::Priority prio, Args &&...args)
    {
        static_assert(std::is_base_of_v<AsyncJob, JobT>,
                      "JobT must derive from AsyncJob");

        auto job = std::make_shared<JobT>(std::forward<Args>(args)...);
        _queue.push(std::move(job), prio);
    }

private:
    void workerLoop()
    {
        while (auto job = _queue.waitAndPop())
        {
            BLOGSUITE_LOG(Logger::Level::Debug, "Running job: " + std::string(job->name()));
            try
            {
                auto started = std::chrono::steady_clock::now();
                job->run();
                auto elapsed = std::chrono::steady_clock::now() - started;

                BLOGSUITE_LOG(Logger::Level::Info,
                              "Job '" + std::string(job->name()) + "' finished in " +
                                  std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count()) +
                                  "ms");
            }
            catch (const std::exception &ex)
            {
                BLOGSUITE_LOG(Logger::Level::Error,
                              "Job '" + std::string(job->name()) + "' failed: " + ex.what());
            }
            catch (...)
            {
                BLOGSUITE_LOG(Logger::Level::Fatal,
                              "Job '" + std::string(job->name()) + "' failed with unknown exception");
            }
        }
    }

    JobQueue                _queue;
    std::vector<std::thread> _threads;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Sample job implementations.
// ──────────────────────────────────────────────────────────────────────────────
class ReindexArticleJob : public AsyncJob
{
public:
    ReindexArticleJob(std::shared_ptr<IArticleRepository> repo,
                      std::shared_ptr<ISearchIndexGateway> gateway,
                      std::uint64_t articleId)
        : AsyncJob("ReindexArticleJob#" + std::to_string(articleId))
        , _repo(std::move(repo))
        , _gateway(std::move(gateway))
        , _articleId(articleId)
    {
    }

    void run() override
    {
        if (!_repo || !_gateway)
            throw std::runtime_error("Repository or gateway dependency not set");

        auto contentOpt = _repo->fetchArticleContent(_articleId);
        if (!contentOpt)
            throw std::runtime_error("Article " + std::to_string(_articleId) + " does not exist");

        _gateway->upsertDocument(_articleId, *contentOpt);
    }

private:
    std::shared_ptr<IArticleRepository>  _repo;
    std::shared_ptr<ISearchIndexGateway> _gateway;
    std::uint64_t                        _articleId;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Mock objects for demonstration (to be replaced by real implementations).
// ──────────────────────────────────────────────────────────────────────────────
class InMemoryArticleRepository : public IArticleRepository
{
public:
    void addArticle(std::uint64_t id, std::string body)
    {
        std::lock_guard lk(_mtx);
        _storage[id] = std::move(body);
    }

    std::optional<std::string> fetchArticleContent(std::uint64_t articleId) const override
    {
        std::shared_lock lk(_mtx);
        auto it = _storage.find(articleId);
        if (it == _storage.end())
            return std::nullopt;
        return it->second;
    }

private:
    mutable std::shared_mutex                _mtx;
    std::unordered_map<std::uint64_t, std::string> _storage;
};

class DummySearchIndexGateway : public ISearchIndexGateway
{
public:
    void upsertDocument(std::uint64_t docId, std::string_view body) override
    {
        std::lock_guard lk(_mtx);
        _index[docId] = std::string(body);
        BLOGSUITE_LOG(Logger::Level::Debug,
                      "Indexed document " + std::to_string(docId) + " (" + std::to_string(body.size()) + "B)");
    }

private:
    std::mutex                                _mtx;
    std::unordered_map<std::uint64_t, std::string> _index;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Self-contained example so that the compilation unit can be unit-tested.
//  Remove main() when linking with the rest of the monolith.
// ──────────────────────────────────────────────────────────────────────────────
#ifdef BLOGSUITE_STANDALONE_TESTDRIVE

int main()
{
    using enum Logger::Level;

    auto repo    = std::make_shared<InMemoryArticleRepository>();
    auto gateway = std::make_shared<DummySearchIndexGateway>();

    repo->addArticle(1, "Hello World – IntraLedger BlogSuite!");
    repo->addArticle(2, "Modern C++ for high-performance backends.");

    AsyncJobProcessor processor;  // default worker count

    processor.submit<ReindexArticleJob>(JobQueue::Priority::High, repo, gateway, 1);
    processor.submit<ReindexArticleJob>(JobQueue::Priority::Normal, repo, gateway, 2);
    processor.submit<ReindexArticleJob>(JobQueue::Priority::Normal, repo, gateway, 42); // will throw

    // Give workers time to finish in this test harness
    std::this_thread::sleep_for(std::chrono::seconds(1));
    return 0;
}
#endif

} // namespace intraledger::blogsuite
```