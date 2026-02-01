```cpp
#pragma once
/***************************************************************************************************
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  Module  : processing
 *  File    : batch_processor.h
 *
 *  Copyright (c) AcesoLabs.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
 *  in compliance with the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software distributed under the License
 *  is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
 *  or implied.  See the License for the specific language governing permissions and limitations
 *  under the License.
 *
 *  Description:
 *      BatchProcessor coordinates high-throughput batch ETL workloads executed on top of Intel TBB.
 *      It acts as the cornerstone for nightly cohort builds, retrospective analytics, and any other
 *      heavy-duty, latency-tolerant jobs within CardioInsight360.  The component implements:
 *
 *          • Dynamic registration of IBatchJob implementations (Strategy Pattern).
 *          • Parallel job execution & fault-tolerant supervision.
 *          • Lifecycle hooks for progress reporting & metrics (Observer Pattern).
 *          • Health-check, graceful shutdown, and back-pressure handling.
 *
 *      NOTE: This header is intentionally self-contained so downstream services can depend on it
 *      without pulling the entire processing/ implementation library.
 **************************************************************************************************/

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <tbb/concurrent_queue.h>
#include <tbb/parallel_for_each.h>
#include <tbb/task_group.h>

#include <spdlog/spdlog.h>

namespace ci360::processing {

/*--------------------------------------------------------------------------------------------------
 *  Exceptions
 *------------------------------------------------------------------------------------------------*/
class BatchProcessorError final : public std::runtime_error
{
public:
    explicit BatchProcessorError(std::string msg)
        : std::runtime_error{std::move(msg)}
    {}
};

/*--------------------------------------------------------------------------------------------------
 *  Observer interface for progress & health monitoring
 *------------------------------------------------------------------------------------------------*/
class IBatchObserver
{
public:
    virtual ~IBatchObserver() = default;

    virtual void onJobStarted(const std::string& jobId)                  noexcept = 0;
    virtual void onJobProgress(const std::string& jobId, float progress) noexcept = 0;  // [0–100]
    virtual void onJobFinished(const std::string& jobId,
                               std::chrono::milliseconds duration)       noexcept = 0;
    virtual void onJobFailed(const std::string& jobId, const std::string& reason) noexcept = 0;
};

/*--------------------------------------------------------------------------------------------------
 *  Core Job Strategy Interface
 *------------------------------------------------------------------------------------------------*/
class IBatchJob
{
public:
    virtual ~IBatchJob() = default;

    virtual std::string                     id()               const = 0;
    virtual std::string                     description()      const = 0;
    virtual std::chrono::milliseconds       estimatedDuration() const = 0;

    // Execution is expected to be synchronous from the caller’s perspective.
    virtual void execute(const std::atomic_bool& cancelled,
                         std::function<void(float)> progress_cb) = 0;
};

/*--------------------------------------------------------------------------------------------------
 *  BatchProcessor Configuration
 *------------------------------------------------------------------------------------------------*/
struct BatchProcessorConfig
{
    // Maximum number of concurrent jobs. 0 ⇒ use std::thread::hardware_concurrency().
    std::uint16_t concurrency = 0;

    // Maximum #jobs allowed to be enqueued. Exceeding this triggers back-pressure.
    std::uint32_t queue_capacity = 256;

    // Timeout for graceful shutdown.
    std::chrono::seconds shutdown_grace_period{30};

    // Verbose logging?
    bool verbose_logging = true;
};

/*--------------------------------------------------------------------------------------------------
 *  BatchProcessor
 *------------------------------------------------------------------------------------------------*/
class BatchProcessor final : public std::enable_shared_from_this<BatchProcessor>
{
public:
    using JobPtr      = std::shared_ptr<IBatchJob>;
    using ObserverPtr = std::shared_ptr<IBatchObserver>;

    explicit BatchProcessor(BatchProcessorConfig cfg = {});
    ~BatchProcessor();

    // Disable copy/move
    BatchProcessor(const BatchProcessor&)            = delete;
    BatchProcessor& operator=(const BatchProcessor&) = delete;

    /*-----------------------------------------------------------------------------
     *  Registration API
     *----------------------------------------------------------------------------*/
    void registerJob(const JobPtr& job);
    void unregisterJob(const std::string& jobId);

    /*-----------------------------------------------------------------------------
     *  Observer API
     *----------------------------------------------------------------------------*/
    void attachObserver(const ObserverPtr& obs);
    void detachObserver(const ObserverPtr& obs);

    /*-----------------------------------------------------------------------------
     *  Execution API
     *----------------------------------------------------------------------------*/
    // Enqueue by job-ids. Returns future that is fulfilled when ALL jobs complete.
    std::future<void> enqueue(const std::vector<std::string>& jobIds);

    // Convenience: enqueue every registered job once.
    std::future<void> enqueueAll();

    /*-----------------------------------------------------------------------------
     *  Lifecycle
     *----------------------------------------------------------------------------*/
    void shutdown();          // graceful
    bool isShuttingDown() const noexcept;

private:
    struct QueuedJob
    {
        JobPtr job;
        std::promise<void> promise;  // fulfilled on completion/failure.
    };

    // Worker loop running on a dedicated TBB task_group.
    void workerLoop();

    void notifyJobStarted(const std::string& id) const noexcept;
    void notifyJobProgress(const std::string& id, float p) const noexcept;
    void notifyJobFinished(const std::string& id,
                           std::chrono::milliseconds dur) const noexcept;
    void notifyJobFailed(const std::string& id, const std::string& reason) const noexcept;

    /*-----------------------------------------------------------------------------
     *  Data
     *----------------------------------------------------------------------------*/
    const BatchProcessorConfig cfg_;

    mutable std::shared_mutex          registry_mtx_;
    std::unordered_map<std::string, JobPtr> registry_;          // jobId → Job

    mutable std::shared_mutex          observers_mtx_;
    std::vector<ObserverPtr>           observers_;

    tbb::concurrent_bounded_queue<std::shared_ptr<QueuedJob>> queue_;
    tbb::task_group                    workers_;

    std::atomic_bool                   shutting_down_{false};
    std::atomic_bool                   worker_started_{false};
};

/*==================================================================================================
 *  Implementation
 *================================================================================================*/
inline BatchProcessor::BatchProcessor(BatchProcessorConfig cfg)
    : cfg_{cfg}
{
    queue_.set_capacity(cfg_.queue_capacity);
    // Launch worker tasks lazily (first enqueue) to avoid wasting threads.
}

inline BatchProcessor::~BatchProcessor()
{
    try
    {
        shutdown();
    }
    catch (...)
    {
        spdlog::error("Exception during BatchProcessor dtor. Forcing shutdown.");
    }
}

inline void BatchProcessor::registerJob(const JobPtr& job)
{
    if (!job) throw BatchProcessorError{"Attempt to register null BatchJob."};
    std::unique_lock lock{registry_mtx_};
    auto [_, inserted] = registry_.emplace(job->id(), job);
    if (!inserted)
        throw BatchProcessorError{"BatchJob [" + job->id() + "] already registered."};
}

inline void BatchProcessor::unregisterJob(const std::string& jobId)
{
    std::unique_lock lock{registry_mtx_};
    registry_.erase(jobId);
}

inline void BatchProcessor::attachObserver(const ObserverPtr& obs)
{
    if (!obs) return;
    std::unique_lock lock{observers_mtx_};
    observers_.push_back(obs);
}

inline void BatchProcessor::detachObserver(const ObserverPtr& obs)
{
    std::unique_lock lock{observers_mtx_};
    observers_.erase(std::remove(observers_.begin(), observers_.end(), obs), observers_.end());
}

inline std::future<void> BatchProcessor::enqueue(const std::vector<std::string>& jobIds)
{
    if (shutting_down_) throw BatchProcessorError{"BatchProcessor is shutting down."};

    std::vector<std::shared_ptr<QueuedJob>> local_jobs;
    local_jobs.reserve(jobIds.size());

    {
        std::shared_lock lock{registry_mtx_};
        for (const auto& id : jobIds)
        {
            auto it = registry_.find(id);
            if (it == registry_.end())
                throw BatchProcessorError{"Unknown BatchJob id: " + id};

            auto qj   = std::make_shared<QueuedJob>();
            qj->job   = it->second;
            local_jobs.push_back(qj);
        }
    }

    // Aggregate futures so caller only waits once.
    auto aggregate_promise = std::make_shared<std::promise<void>>();
    auto aggregate_future  = aggregate_promise->get_future();
    auto remaining         = std::make_shared<std::atomic_size_t>(local_jobs.size());

    // Worker loop is started lazily
    if (!worker_started_.exchange(true))
    {
        workers_.run([this] { workerLoop(); });
    }

    for (auto& qj : local_jobs)
    {
        auto fut = qj->promise.get_future();
        fut.then([aggregate_promise, remaining](auto&& f) {
            (void)f;  // ignore individual status; handled internally via observers
            if (remaining->fetch_sub(1) == 1)
                aggregate_promise->set_value();
        });

        queue_.push(qj);  // could block if at capacity → back-pressure
    }

    return aggregate_future;
}

inline std::future<void> BatchProcessor::enqueueAll()
{
    std::vector<std::string> ids;
    {
        std::shared_lock lock{registry_mtx_};
        ids.reserve(registry_.size());
        for (const auto& kv : registry_) ids.push_back(kv.first);
    }
    return enqueue(ids);
}

inline void BatchProcessor::shutdown()
{
    if (shutting_down_.exchange(true)) return;  // already shutting down

    spdlog::info("BatchProcessor received shutdown request.");

    // Allow workerLoop to exit
    queue_.invalidate();

    if (worker_started_)
    {
        if (!workers_.wait_for(cfg_.shutdown_grace_period))
        {
            spdlog::warn("BatchProcessor worker did not finish within grace period.");
        }
    }
}

inline bool BatchProcessor::isShuttingDown() const noexcept { return shutting_down_.load(); }

/*--------------------------------------------------------------------------------------------------
 *  Worker Loop – executes queued jobs until shutdown.
 *------------------------------------------------------------------------------------------------*/
inline void BatchProcessor::workerLoop()
{
    tbb::task_group tg;
    const std::size_t concurrency =
        cfg_.concurrency == 0 ? std::thread::hardware_concurrency() : cfg_.concurrency;

    spdlog::info("BatchProcessor workerLoop starting with concurrency={}.", concurrency);

    while (!shutting_down_)
    {
        std::shared_ptr<QueuedJob> qj;
        if (!queue_.pop(qj))
        {
            // queue invalidated or shutdown request.
            break;
        }

        tg.run([this, qj] {
            const auto start_tp = std::chrono::steady_clock::now();
            auto cancelled      = std::make_shared<std::atomic_bool>(false);

            notifyJobStarted(qj->job->id());

            try
            {
                qj->job->execute(*cancelled, [this, id = qj->job->id()](float p) {
                    notifyJobProgress(id, p);
                });

                auto dur = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - start_tp);

                notifyJobFinished(qj->job->id(), dur);

                qj->promise.set_value();
            }
            catch (const std::exception& ex)
            {
                notifyJobFailed(qj->job->id(), ex.what());
                qj->promise.set_exception(std::current_exception());
            }
            catch (...)
            {
                notifyJobFailed(qj->job->id(), "Unknown exception.");
                qj->promise.set_exception(std::current_exception());
            }
        });

        // Limit concurrency
        tg.wait();
    }

    spdlog::info("BatchProcessor workerLoop exiting.");
}

/*--------------------------------------------------------------------------------------------------
 *  Observer notifications (exception-safe)
 *------------------------------------------------------------------------------------------------*/
inline void BatchProcessor::notifyJobStarted(const std::string& id) const noexcept
{
    std::shared_lock lock{observers_mtx_};
    for (auto& o : observers_)
    {
        if (o) o->onJobStarted(id);
    }
}

inline void BatchProcessor::notifyJobProgress(const std::string& id, float p) const noexcept
{
    std::shared_lock lock{observers_mtx_};
    for (auto& o : observers_)
    {
        if (o) o->onJobProgress(id, p);
    }
}

inline void BatchProcessor::notifyJobFinished(const std::string& id,
                                              std::chrono::milliseconds dur) const noexcept
{
    std::shared_lock lock{observers_mtx_};
    for (auto& o : observers_)
    {
        if (o) o->onJobFinished(id, dur);
    }
}

inline void BatchProcessor::notifyJobFailed(const std::string& id,
                                            const std::string& reason) const noexcept
{
    std::shared_lock lock{observers_mtx_};
    for (auto& o : observers_)
    {
        if (o) o->onJobFailed(id, reason);
    }
}

}  // namespace ci360::processing
```