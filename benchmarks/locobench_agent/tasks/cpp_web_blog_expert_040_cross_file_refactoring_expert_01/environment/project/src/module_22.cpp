```cpp
/**
 *  File:        src/module_22.cpp
 *  Project:     IntraLedger BlogSuite (web_blog)
 *
 *  Description:
 *  -------------
 *  Asynchronous Job Processor
 *  --------------------------
 *  This module implements an internal asynchronous job-processing subsystem
 *  used across BlogSuite for non-blocking, out-of-band tasks such as
 *  e-mail delivery, image transformation and cache invalidation.  The design
 *  follows a producer/consumer model backed by a fixed-size thread-pool and a
 *  lock-free multi-producer/single-consumer queue guarded by a condition-variable
 *  for low-latency wake-ups.
 *
 *  The subsystem is *header-only* from the consumer’s perspective—projects
 *  simply include "job_dispatcher.hpp" to submit jobs—but its concrete
 *  implementation lives here to avoid ODR bloat.
 *
 *  Public API (excerpt):
 *
 *      using intraledger::jobs::JobDispatcher;
 *
 *      JobDispatcher dispatcher{std::thread::hardware_concurrency()};
 *
 *      dispatcher.submit<EmailJob>("to@example.com",
 *                                  "Password Reset",
 *                                  "Your reset code is 123456");
 *
 *      dispatcher.submit<ImageTransformJob>(imagePath, targetPath, 512, 512);
 *
 *      // When the application terminates
 *      dispatcher.shutdown();   // graceful stop; blocks until completion
 *
 *  Notes:
 *  ------
 *    • Thread-safe: Yes
 *    • Exception-safe: Jobs are executed inside try/catch blocks; unhandled
 *      exceptions are logged and do not crash worker threads.
 *    • Build flags: Requires C++17 or later.
 */

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <exception>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

namespace intraledger::util {

//------------------------------------------------------------------------------
// Lightweight logger (printf-style) ‑ replace with enterprise logger if needed
//------------------------------------------------------------------------------
enum class LogLevel { Debug, Info, Warning, Error, Fatal };

inline void log(LogLevel level, const std::string& message) {
    static constexpr const char* LevelStr[] = { "DEBUG", "INFO", "WARN", "ERR", "FATAL" };
    std::ostringstream oss;
    oss << "[JobDispatcher][" << LevelStr[static_cast<int>(level)] << "] " << message << '\n';
    (level >= LogLevel::Error ? std::cerr : std::cout) << oss.str();
}

} // namespace intraledger::util

namespace intraledger::jobs {

//==============================================================================
// Abstract Job Concept
//==============================================================================

class IJob {
public:
    IJob() = default;
    virtual ~IJob() = default;

    // Execute job. Must throw on unrecoverable error only.
    virtual void execute() noexcept = 0;
};

//------------------------------------------------------------------------------
// Concrete Job Examples
//------------------------------------------------------------------------------

class EmailJob final : public IJob {
public:
    EmailJob(std::string to, std::string subject, std::string body)
        : _to(std::move(to)), _subject(std::move(subject)), _body(std::move(body)) {}

    void execute() noexcept override
    {
        try {
            // Placeholder: Replace with actual SMTP client integration.
            std::this_thread::sleep_for(std::chrono::milliseconds(150));
            intraledger::util::log(util::LogLevel::Info,
                                   "E-mail sent to " + _to + " [subject: " + _subject + ']');
        } catch (const std::exception& ex) {
            intraledger::util::log(util::LogLevel::Error,
                                   "E-mail job failed: " + std::string(ex.what()));
        }
    }

private:
    std::string _to, _subject, _body;
};

class ImageTransformJob final : public IJob {
public:
    ImageTransformJob(std::string src,
                      std::string dst,
                      int width,
                      int height)
        : _src(std::move(src)),
          _dst(std::move(dst)),
          _width(width),
          _height(height) {}

    void execute() noexcept override
    {
        try {
            // Placeholder: Replace with actual ImageMagick/libvips logic.
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
            intraledger::util::log(util::LogLevel::Info,
                                   "Image transformed " + _src + " -> " + _dst + " (" +
                                   std::to_string(_width) + "x" + std::to_string(_height) + ')');
        } catch (const std::exception& ex) {
            intraledger::util::log(util::LogLevel::Error,
                                   "Image transform job failed: " + std::string(ex.what()));
        }
    }

private:
    std::string _src, _dst;
    int _width, _height;
};

//==============================================================================
// Job Queue – MPSC thread-safe queue
//==============================================================================

class JobQueue {
public:
    void push(std::unique_ptr<IJob>&& job)
    {
        {
            std::scoped_lock lk(_mtx);
            _queue.emplace(std::move(job));
        }
        _cv.notify_one();
    }

    // Pops a job or returns nullptr if shutting down and queue empty.
    std::unique_ptr<IJob> pop(bool shuttingDown)
    {
        std::unique_lock lk(_mtx);
        _cv.wait(lk, [&] { return shuttingDown || !_queue.empty(); });

        if (_queue.empty()) {
            return nullptr; // shutting down and no remaining job
        }

        auto job = std::move(_queue.front());
        _queue.pop();
        return job;
    }

    std::size_t size() const
    {
        std::scoped_lock lk(_mtx);
        return _queue.size();
    }

private:
    mutable std::mutex                       _mtx;
    std::condition_variable                  _cv;
    std::queue<std::unique_ptr<IJob>>        _queue;
};

//==============================================================================
// Job Dispatcher – Thread-pool + queue
//==============================================================================

class JobDispatcher {
public:
    explicit JobDispatcher(std::size_t concurrency = std::thread::hardware_concurrency())
        : _state(State::Running)
    {
        if (concurrency == 0U) {
            concurrency = 2U; // sane fallback
        }
        _workers.reserve(concurrency);
        for (std::size_t i = 0; i < concurrency; ++i) {
            _workers.emplace_back(&JobDispatcher::workerLoop, this);
        }
        intraledger::util::log(util::LogLevel::Info,
                               "JobDispatcher started with " + std::to_string(concurrency) +
                               " worker threads");
    }

    ~JobDispatcher() noexcept
    {
        try {
            shutdown();
        } catch (...) {
            // Destructor should never throw
        }
    }

    JobDispatcher(const JobDispatcher&)            = delete;
    JobDispatcher& operator=(const JobDispatcher&) = delete;
    JobDispatcher(JobDispatcher&&)                 = delete;
    JobDispatcher& operator=(JobDispatcher&&)      = delete;

    //------------------------------------------------------------------
    // Job submission API
    //------------------------------------------------------------------

    template <typename JobT, typename... Args,
              typename = std::enable_if_t<std::is_base_of_v<IJob, JobT>>>
    void submit(Args&&... args)
    {
        auto jobPtr = std::make_unique<JobT>(std::forward<Args>(args)...);
        _queue.push(std::move(jobPtr));
    }

    //------------------------------------------------------------------
    // Graceful shutdown
    //------------------------------------------------------------------
    void shutdown()
    {
        State expected = State::Running;
        if (!_state.compare_exchange_strong(expected, State::ShuttingDown)) {
            return; // already shutting down or stopped
        }

        // Wake up all waiting threads
        _queue.push(nullptr); // sentinel (makes at least one worker wake)
        {
            std::scoped_lock lk(_shutdownMtx);
            _shutdownCv.notify_all();
        }

        for (auto& t : _workers) {
            if (t.joinable()) {
                t.join();
            }
        }

        _state.store(State::Stopped);
        intraledger::util::log(util::LogLevel::Info, "JobDispatcher stopped");
    }

    //------------------------------------------------------------------
    // Health metrics
    //------------------------------------------------------------------
    std::size_t pendingJobs() const { return _queue.size(); }

private:
    enum class State { Running, ShuttingDown, Stopped };

    void workerLoop()
    {
        while (true) {
            bool shuttingDown = _state.load() != State::Running;
            auto job          = _queue.pop(shuttingDown);

            if (!job) {
                if (shuttingDown) {
                    break; // graceful exit
                }
                continue; // spurious pop; keep waiting
            }

            try {
                job->execute();
            } catch (const std::exception& ex) {
                intraledger::util::log(util::LogLevel::Error,
                                       std::string("Unhandled job exception: ") + ex.what());
            } catch (...) {
                intraledger::util::log(util::LogLevel::Error,
                                       "Unhandled non-std exception in job");
            }
        }
    }

    // Worker threads
    std::vector<std::thread> _workers;

    // Shared job queue
    JobQueue _queue;

    // Lifecycle state
    std::atomic<State> _state;

    // Shutdown helpers (unused but could be integrated with dynamic scaling)
    std::mutex              _shutdownMtx;
    std::condition_variable _shutdownCv;
};

//==============================================================================
// Example Usage (module-local test). Compile with -DIL_JOBS_DEMO to enable.
//==============================================================================
#ifdef IL_JOBS_DEMO
int main()
{
    using namespace intraledger::jobs;

    JobDispatcher dispatcher{4};

    dispatcher.submit<EmailJob>("alice@corp.tld", "Welcome", "Thanks for joining IntraLedger!");
    dispatcher.submit<ImageTransformJob>("source.jpg", "thumb.jpg", 128, 128);

    std::this_thread::sleep_for(std::chrono::seconds(1));

    dispatcher.shutdown();
    return 0;
}
#endif

} // namespace intraledger::jobs
```