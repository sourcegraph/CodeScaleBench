#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <functional>
#include <future>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

/*
 *  file: src/module_6.cpp
 *  project: IntraLedger BlogSuite (web_blog)
 *
 *  Module-6: Generic Asynchronous Job Processor
 *  --------------------------------------------
 *  This source unit implements a lightweight, in-process job dispatcher that
 *  powers background tasks such as:
 *      • transactional e-mail and push notifications
 *      • full-text search index maintenance
 *      • image/video transcoding
 *      • cache warming / pre-rendering
 *
 *  The API exposes a type-erased, thread-safe scheduling interface modelled
 *  after std::packaged_task.  Any invocable that satisfies `void(JobContext&)`
 *  can be enqueued for immediate or delayed execution.  A bounded pool of
 *  worker threads provides cooperative multitasking with graceful shutdown.
 *
 *  NOTE:
 *  -----
 *  In the actual product this module sits behind a Service-Layer façade and
 *  receives tasks from MVC controllers and internal domain services.  For
 *  clarity, the module is self-contained and relies only on the C++17
 *  standard library.
 */

namespace blog::async {

// ---------------------------------------------------------------------------
// Logging helper – can be swapped out for spdlog or syslog in production.
// ---------------------------------------------------------------------------

enum class LogLevel { kDebug, kInfo, kWarning, kError, kFatal };

class Logger final
{
public:
    static void log(LogLevel lvl, std::string_view message) noexcept
    {
        std::lock_guard<std::mutex> lock(mutex_);
        std::clog << "[" << timestamp() << "] "
                  << level_string(lvl) << ' ' << message << '\n';
    }

private:
    static std::string timestamp()
    {
        using namespace std::chrono;
        const auto now   = system_clock::now();
        const auto tt    = system_clock::to_time_t(now);
        const auto ms    = duration_cast<milliseconds>(now.time_since_epoch()) %
                        1000;
        std::ostringstream oss;
    #ifdef _MSC_VER
        std::tm tm;
        localtime_s(&tm, &tt);
        oss << std::put_time(&tm, "%F %T");
    #else
        std::tm tm;
        localtime_r(&tt, &tm);
        oss << std::put_time(&tm, "%F %T");
    #endif
        oss << '.' << std::setfill('0') << std::setw(3) << ms.count();
        return oss.str();
    }

    static constexpr const char* level_string(LogLevel lvl) noexcept
    {
        switch (lvl) {
        case LogLevel::kDebug:   return "[DBG]";
        case LogLevel::kInfo:    return "[INF]";
        case LogLevel::kWarning: return "[WRN]";
        case LogLevel::kError:   return "[ERR]";
        case LogLevel::kFatal:   return "[FTL]";
        }
        return "[UNK]";
    }

    static std::mutex mutex_;
};

std::mutex Logger::mutex_;

// ---------------------------------------------------------------------------
// JobContext – runtime metadata available to each executing task.
// ---------------------------------------------------------------------------

struct JobContext
{
    std::size_t worker_id;                       // 0-based thread index
    std::chrono::system_clock::time_point start; // when the job started
};

// ---------------------------------------------------------------------------
// IJob – type-erased base class for all queued tasks.
// ---------------------------------------------------------------------------

class IJob
{
public:
    virtual ~IJob() = default;
    virtual void invoke(JobContext&) = 0;
};

using JobPtr = std::unique_ptr<IJob>;

// ---------------------------------------------------------------------------
// Job – template wrapper that accepts any invocable target.
// ---------------------------------------------------------------------------

template <typename Fn>
class Job final : public IJob
{
public:
    explicit Job(Fn&& fn)
        : fn_(std::forward<Fn>(fn)) {}

    void invoke(JobContext& ctx) override
    {
        fn_(ctx); // may throw; caught by worker
    }

private:
    Fn fn_;
};

// Convenience deduction guide
template <typename Fn> Job(Fn) -> Job<Fn>;


// ---------------------------------------------------------------------------
// ThreadSafeQueue – minimal blocking queue with shutdown signalling.
// ---------------------------------------------------------------------------

class ThreadSafeQueue
{
public:
    ThreadSafeQueue() = default;
    ThreadSafeQueue(const ThreadSafeQueue&)            = delete;
    ThreadSafeQueue& operator=(const ThreadSafeQueue&) = delete;

    // Enqueue a job with optional scheduled_at time point
    void push(JobPtr job,
              std::optional<std::chrono::steady_clock::time_point> scheduled_at =
                  std::nullopt)
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            queue_.emplace(std::move(job), scheduled_at);
        }
        cv_.notify_one();
    }

    // Pop the next job; blocks until a job is ready or shutdown is requested
    bool pop(JobPtr& out,
             std::optional<std::chrono::steady_clock::time_point>& scheduled_at)
    {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [&] { return shutdown_ || !queue_.empty(); });

        if (shutdown_ && queue_.empty())
            return false;

        std::tie(out, scheduled_at) = std::move(queue_.front());
        queue_.pop();
        return true;
    }

    void shutdown()
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            shutdown_ = true;
        }
        cv_.notify_all();
    }

private:
    std::queue<std::pair<JobPtr, std::optional<std::chrono::steady_clock::time_point>>> queue_;
    bool                                                                        shutdown_{ false };
    std::mutex                                                                  mutex_;
    std::condition_variable                                                     cv_;
};

// ---------------------------------------------------------------------------
// Worker – dedicated thread that processes jobs until signalled to stop.
// ---------------------------------------------------------------------------

class Worker
{
public:
    Worker(std::size_t id, ThreadSafeQueue& q)
        : id_(id), queue_(q), thread_([this] { run(); }) {}

    ~Worker()
    {
        if (thread_.joinable())
            thread_.join();
    }

private:
    void run()
    {
        Logger::log(LogLevel::kInfo, "Worker#" + std::to_string(id_) + " started");

        JobPtr job;
        std::optional<std::chrono::steady_clock::time_point> scheduled;

        while (queue_.pop(job, scheduled)) {
            try {
                // honour delay until scheduled time
                if (scheduled && std::chrono::steady_clock::now() < *scheduled) {
                    std::this_thread::sleep_until(*scheduled);
                }
                JobContext ctx{ id_, std::chrono::system_clock::now() };
                job->invoke(ctx);
            } catch (const std::exception& ex) {
                Logger::log(LogLevel::kError,
                            "Worker#" + std::to_string(id_) + " uncaught exception: " +
                                ex.what());
            } catch (...) {
                Logger::log(LogLevel::kFatal,
                            "Worker#" + std::to_string(id_) + " encountered "
                            "non-standard exception");
            }
        }

        Logger::log(LogLevel::kInfo, "Worker#" + std::to_string(id_) + " stopped");
    }

    std::size_t       id_;
    ThreadSafeQueue&  queue_;
    std::thread       thread_;
};

// ---------------------------------------------------------------------------
// Scheduler – public interface consumed by the rest of the application.
// ---------------------------------------------------------------------------

class Scheduler
{
public:
    explicit Scheduler(std::size_t thread_count = std::thread::hardware_concurrency())
        : workers_(), queue_(), next_id_(0)
    {
        if (thread_count == 0)
            thread_count = 1;

        for (std::size_t i = 0; i < thread_count; ++i) {
            workers_.emplace_back(std::make_unique<Worker>(i, queue_));
        }

        Logger::log(LogLevel::kInfo,
                    "Scheduler booted with " + std::to_string(thread_count) + " worker(s)");
    }

    ~Scheduler()
    {
        shutdown();
    }

    // schedule for immediate execution
    template <typename Fn>
    void dispatch(Fn&& fn)
    {
        queue_.push(std::make_unique<Job<Fn>>(std::forward<Fn>(fn)));
    }

    // schedule for execution after `delay`
    template <typename Fn>
    void dispatch_after(std::chrono::milliseconds delay, Fn&& fn)
    {
        auto target_time = std::chrono::steady_clock::now() + delay;
        queue_.push(std::make_unique<Job<Fn>>(std::forward<Fn>(fn)), target_time);
    }

    // schedule for execution at absolute time point
    template <typename Clock, typename Duration, typename Fn>
    void dispatch_at(std::chrono::time_point<Clock, Duration> tp, Fn&& fn)
    {
        const auto now = Clock::now();
        auto        st = std::chrono::steady_clock::now() +
                  std::chrono::duration_cast<std::chrono::steady_clock::duration>(tp - now);
        queue_.push(std::make_unique<Job<Fn>>(std::forward<Fn>(fn)), st);
    }

    void shutdown()
    {
        bool expected = false;
        if (!shutdown_flag_.compare_exchange_strong(expected, true))
            return; // already shutdown

        Logger::log(LogLevel::kInfo, "Scheduler shutting down");
        queue_.shutdown();
        workers_.clear(); // join threads via destructor
    }

private:
    std::vector<std::unique_ptr<Worker>> workers_;
    ThreadSafeQueue                      queue_;
    std::atomic_bool                     shutdown_flag_{ false };
    std::size_t                          next_id_;
};

// ---------------------------------------------------------------------------
// Example Usage – to be removed or adapted in production code.
// ---------------------------------------------------------------------------

#ifdef BLOGSUITE_MODULE6_TESTDRIVE
// compile with -DBLOGSUITE_MODULE6_TESTDRIVE to run the demo
int main()
{
    using namespace std::chrono_literals;

    blog::async::Scheduler scheduler(4);

    scheduler.dispatch([](blog::async::JobContext& ctx) {
        blog::async::Logger::log(blog::async::LogLevel::kInfo,
                                 "Hello from immediate job on worker#" +
                                     std::to_string(ctx.worker_id));
    });

    scheduler.dispatch_after(1s, [](blog::async::JobContext& ctx) {
        blog::async::Logger::log(blog::async::LogLevel::kInfo,
                                 "Delayed job executed by worker#" +
                                     std::to_string(ctx.worker_id));
    });

    // long-running task
    scheduler.dispatch([](blog::async::JobContext& ctx) {
        blog::async::Logger::log(blog::async::LogLevel::kInfo,
                                 "Simulating CPU bound workload on worker#" +
                                     std::to_string(ctx.worker_id));
        std::this_thread::sleep_for(2s);
    });

    // give the workers some time
    std::this_thread::sleep_for(3s);
    scheduler.shutdown();
}
#endif // BLOGSUITE_MODULE6_TESTDRIVE

} // namespace blog::async