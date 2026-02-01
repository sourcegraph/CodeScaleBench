#include <chrono>
#include <condition_variable>
#include <functional>
#include <future>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <tbb/task_group.h>
#include <spdlog/spdlog.h>

#include "../core/event_bus.hpp"       // In-process Kafka façade (librdkafka based)
#include "../core/metrics/metrics.hpp" // Observer subsystem
#include "../utils/uuid.hpp"           // RFC-4122 compliant UUID generator

/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * Scheduling Service
 *
 * The SchedulingService provides a cron-like facility for all in-process pseudo-microservices.
 * Components such as ETL pipelines, quality-check monitors, housekeeping, and metric snapshots
 * register a Task with an execution policy (fixed-rate or fixed-delay) and a period.
 *
 * Internally, a high-priority coordinator thread maintains a min-heap of next-fire timestamps,
 * while individual task executions are dispatched to TBB's task_group to leverage the global
 * worker pool without oversubscription.  All operations are thread-safe, exception-safe,
 * and emit observability events to the monitoring subsystem.
 */

namespace cardio::services {

enum class ExecutionMode
{
    FixedRate,  // task is re-scheduled relative to original start (even if previous run overruns)
    FixedDelay  // task is re-scheduled relative to actual completion time
};

/*--------------------------------------------------------*
 | Task Definition                                        |
 *--------------------------------------------------------*/
class ScheduledTask
{
public:
    ScheduledTask(std::string               id,
                  std::string               name,
                  std::chrono::milliseconds period,
                  ExecutionMode             mode,
                  std::function<void()>     fn)
        : _id{std::move(id)}
        , _name{std::move(name)}
        , _period{period}
        , _mode{mode}
        , _fn{std::move(fn)}
        , _nextFire{Clock::now() + _period}
    {
    }

    using Clock      = std::chrono::steady_clock;
    using TimePoint  = Clock::time_point;

    const std::string& id() const noexcept { return _id; }
    const std::string& name() const noexcept { return _name; }
    std::chrono::milliseconds period() const noexcept { return _period; }
    ExecutionMode mode() const noexcept { return _mode; }
    TimePoint nextFire() const noexcept { return _nextFire; }

    void dispatch(tbb::task_group& tg)
    {
        auto start_time = Clock::now();

        tg.run([this, start_time]() {
            try
            {
                _fn();
                metrics::incrementCounter("scheduler.task.success", {{"task", _name}});
            }
            catch (const std::exception& ex)
            {
                spdlog::error("Scheduled task '{}' failed: {}", _name, ex.what());
                metrics::incrementCounter("scheduler.task.failure", {{"task", _name}});

                // propagate to system-wide event bus for central error handling
                core::EventBus::instance().publish("internal.error",
                                                   {{"task", _name}, {"error", ex.what()}});
            }
        });

        // compute nextFire according to execution mode
        if (_mode == ExecutionMode::FixedRate)
        {
            _nextFire += _period; // relative to original start
        }
        else
        {
            auto completion_time = Clock::now();
            _nextFire            = completion_time + _period; // relative to completion
        }
    }

    bool operator>(const ScheduledTask& other) const noexcept
    {
        return _nextFire > other._nextFire;
    }

private:
    std::string               _id;
    std::string               _name;
    std::chrono::milliseconds _period;
    ExecutionMode             _mode;
    std::function<void()>     _fn;
    TimePoint                 _nextFire;
};

/*--------------------------------------------------------*
 | Priority queue wrapper                                 |
 *--------------------------------------------------------*/
class TaskQueue
{
public:
    void push(std::shared_ptr<ScheduledTask> task)
    {
        std::lock_guard<std::mutex> lk(_mtx);
        _pq.push(std::move(task));
        _cv.notify_one();
    }

    std::shared_ptr<ScheduledTask> pop()
    {
        std::lock_guard<std::mutex> lk(_mtx);
        if (_pq.empty())
            return nullptr;
        auto task = _pq.top();
        _pq.pop();
        return task;
    }

    std::shared_ptr<ScheduledTask> top()
    {
        std::lock_guard<std::mutex> lk(_mtx);
        if (_pq.empty())
            return nullptr;
        return _pq.top();
    }

    void waitForNextDue(std::unique_lock<std::mutex>& lk, std::chrono::steady_clock::time_point tp)
    {
        _cv.wait_until(lk, tp, [this, tp] {
            return _shutdown || _pq.empty() || _pq.top()->nextFire() < tp;
        });
    }

    bool empty()
    {
        std::lock_guard<std::mutex> lk(_mtx);
        return _pq.empty();
    }

    void shutdown()
    {
        {
            std::lock_guard<std::mutex> lk(_mtx);
            _shutdown = true;
        }
        _cv.notify_all();
    }

    bool isShutdown() const noexcept { return _shutdown; }

private:
    struct Cmp
    {
        bool operator()(const std::shared_ptr<ScheduledTask>& l,
                        const std::shared_ptr<ScheduledTask>& r) const noexcept
        {
            return *l > *r;
        }
    };

    std::priority_queue<std::shared_ptr<ScheduledTask>,
                        std::vector<std::shared_ptr<ScheduledTask>>,
                        Cmp>
        _pq;

    mutable std::mutex _mtx;
    std::condition_variable _cv;
    bool _shutdown{false};
};

/*--------------------------------------------------------*
 | SchedulingService Implementation                       |
 *--------------------------------------------------------*/
class SchedulingService
{
public:
    static SchedulingService& instance()
    {
        static SchedulingService inst;
        return inst;
    }

    SchedulingService(const SchedulingService&)            = delete;
    SchedulingService& operator=(const SchedulingService&) = delete;

    /*
     * Register a new periodic task.
     *
     * @param name   Human-readable identifier.
     * @param fn     Callable to execute.
     * @param period Task interval.
     * @param mode   FixedRate or FixedDelay.
     *
     * @return Task UUID for later cancellation.
     */
    std::string registerTask(const std::string&               name,
                             std::function<void()>            fn,
                             std::chrono::milliseconds        period,
                             ExecutionMode                    mode = ExecutionMode::FixedRate)
    {
        if (period.count() <= 0)
            throw std::invalid_argument("SchedulingService: period must be > 0");

        auto id   = utils::uuid::generate();
        auto task = std::make_shared<ScheduledTask>(id, name, period, mode, std::move(fn));

        {
            std::lock_guard<std::mutex> lk(_mapMtx);
            if (_tasks.find(id) != _tasks.end())
                throw std::logic_error("SchedulingService: duplicate task id generated");

            _tasks.emplace(id, task);
        }

        _queue.push(task);
        spdlog::info("SchedulingService: registered task '{}' ({}ms)", name, period.count());
        metrics::incrementCounter("scheduler.task.registered");

        return id;
    }

    /*
     * Cancel an existing task.
     */
    void cancelTask(const std::string& taskId)
    {
        std::lock_guard<std::mutex> lk(_mapMtx);
        auto it = _tasks.find(taskId);
        if (it != _tasks.end())
        {
            it->second->dispatch(_noopGroup); // ensure not referenced
            _tasks.erase(it);
            spdlog::info("SchedulingService: canceled task {}", taskId);
            metrics::incrementCounter("scheduler.task.canceled");
        }
    }

    /*
     * Start coordinator thread (idempotent).
     */
    void start()
    {
        std::lock_guard<std::mutex> lk(_stateMtx);
        if (_running)
            return;

        _running   = true;
        _coordinatorThread = std::thread([this]() { coordinatorLoop(); });

        spdlog::info("SchedulingService started");
    }

    /*
     * Graceful shutdown. Blocks until all executing tasks complete.
     */
    void shutdown()
    {
        {
            std::lock_guard<std::mutex> lk(_stateMtx);
            if (!_running)
                return;
            _running = false;
        }

        _queue.shutdown();
        if (_coordinatorThread.joinable())
            _coordinatorThread.join();

        _taskGroup.wait();

        spdlog::info("SchedulingService stopped");
        metrics::setGauge("scheduler.state", 0);
    }

    bool isRunning() const noexcept
    {
        std::lock_guard<std::mutex> lk(_stateMtx);
        return _running;
    }

private:
    SchedulingService()  = default;
    ~SchedulingService() { shutdown(); }

    void coordinatorLoop()
    {
        metrics::setGauge("scheduler.state", 1);
        spdlog::debug("SchedulingService coordinator loop entered");

        std::unique_lock<std::mutex> lock(_sleepMtx);

        while (true)
        {
            if (_queue.isShutdown())
                break;

            auto nextTask = _queue.top();
            if (!nextTask)
            {
                // nothing scheduled, wait until new task arrives or shutdown
                _queue.waitForNextDue(lock, std::chrono::steady_clock::time_point::max());
                continue;
            }

            auto now      = ScheduledTask::Clock::now();
            auto fireTime = nextTask->nextFire();

            if (fireTime > now)
            {
                // sleep until next fire time or earlier if new task is inserted
                _queue.waitForNextDue(lock, fireTime);
                continue;
            }

            // Pop & execute
            _queue.pop();

            // Dispatch asynchronously; TBB handles pooling
            nextTask->dispatch(_taskGroup);

            // Push back for next round
            _queue.push(std::move(nextTask));
        }
    }

    std::unordered_map<std::string, std::shared_ptr<ScheduledTask>> _tasks;
    std::mutex                                                      _mapMtx;

    TaskQueue       _queue;
    tbb::task_group _taskGroup;
    tbb::task_group _noopGroup; // used for cancel cleanup

    std::thread _coordinatorThread;
    std::mutex  _sleepMtx; // used with TaskQueue CV

    mutable std::mutex _stateMtx;
    bool               _running{false};
};

/*--------------------------------------------------------*
 | Convenience Registration Helpers                       |
 *--------------------------------------------------------*/
namespace detail {

inline void registerHousekeepingJobs()
{
    auto& scheduler = SchedulingService::instance();

    scheduler.registerTask("metric.flush",
                           [] { metrics::flush(); },            // lambda executed
                           std::chrono::seconds(30),            // every 30 seconds
                           ExecutionMode::FixedDelay);
    scheduler.registerTask("etl.daily.batch",
                           [] {
                               core::EventBus::instance().publish("pipeline.trigger", {{"job", "daily_batch_etl"}});
                           },
                           std::chrono::hours(24),              // once a day
                           ExecutionMode::FixedRate);
}

} // namespace detail

/*--------------------------------------------------------*
 | Public Service Bootstrap                               |
 *--------------------------------------------------------*/
void bootstrapSchedulingService()
{
    auto& scheduler = SchedulingService::instance();
    scheduler.start();

    detail::registerHousekeepingJobs();

    spdlog::info("SchedulingService bootstrap complete");
}

} // namespace cardio::services