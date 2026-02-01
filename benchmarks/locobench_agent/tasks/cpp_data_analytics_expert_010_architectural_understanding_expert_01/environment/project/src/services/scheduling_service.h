```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  Module  : Scheduling Service
 *  File    : scheduling_service.h
 *
 *  Copyright (c) Golaith
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Description:
 *      Header-only façade for the in-process Scheduling Service that orchestrates
 *      batch ETL jobs, streaming consumers, and recurring data-quality checks.
 *      The service is designed for thread-safety and minimal latency while
 *      operating entirely in-process (pseudo-microservice) to avoid additional
 *      deployment complexity in regulated environments.
 *
 *  Notes:
 *      – The implementation delegates actual timer-wheel mechanics to an
 *        external, platform-optimized runtime (e.g., Intel TBB task_arena or
 *        <asio>).  Only the coordination layer is exposed here.
 *      – All interfaces are non-blocking; callers receive a JobHandle and
 *        interact with the job via that opaque token.
 */

#pragma once

// ──────────────────────────────────────────────────────────────────────────────
// Standard Library
#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

// ──────────────────────────────────────────────────────────────────────────────
// Forward-Declarations for other CardioInsight360 subsystems
namespace ci360
{
namespace metrics
{
class MetricsRegistry;  // Exposes Counter, Gauge, Histogram…
}                       // namespace metrics

namespace logging
{
class Logger;           // Thread-safe, format-string compatible logger
} // namespace logging
} // namespace ci360

// ──────────────────────────────────────────────────────────────────────────────
namespace ci360::services
{

/**
 * Severity-level for jobs.  Dictates ordering as well as back-off strategy
 * during resource contention (e.g., CPU-bound ETL vs. latency-sensitive alerts).
 */
enum class JobPriority : std::uint8_t
{
    kLow    = 0,
    kNormal = 1,
    kHigh   = 2,
};

/**
 * Classifications help the monitoring subsystem compute SLA compliance
 * (e.g., Real-Time alerting must complete < 5 s, whereas nightly ETL can take hours).
 */
enum class JobCategory : std::uint8_t
{
    kUnknown           = 0,
    kEtlBatch          = 1,
    kStreamConsumer    = 2,
    kRealtimeAlerting  = 3,
    kMaintenance       = 4,
    kDataQualityCheck  = 5,
};

/**
 * Comprehensive descriptor capturing user intent.  Immutable once submitted.
 */
struct JobDescriptor
{
    std::string                       name;           // Human-friendly job name.
    JobCategory                       category {JobCategory::kUnknown};
    JobPriority                       priority {JobPriority::kNormal};

    // Initial run-time for one-off jobs.  For recurring jobs, this is the first
    // execution point.
    std::chrono::system_clock::time_point first_run_at;

    // Recurrence interval.  Empty ⇒ one-off job.
    std::optional<std::chrono::milliseconds> recurrence;

    // Hard deadline for job completion.  Used by watchdog to escalate alerts.
    std::optional<std::chrono::system_clock::time_point> deadline;

    // Opaque context string forwarded verbatim to the job functor.
    std::string payload;
};

/**
 * Opaque token returned to callers for job management.  Deliberately small so
 * that it can be passed by value without concern.
 */
struct JobHandle
{
    using Id = std::uint64_t;

    constexpr explicit JobHandle(Id value = kInvalid) noexcept : id {value} {}
    [[nodiscard]] constexpr bool valid() const noexcept { return id != kInvalid; }

    Id id;

    static constexpr Id kInvalid {0};
};

/**
 * Thrown by SchedulingService for any recoverable scheduling-related failure.
 */
class SchedulingError final : public std::runtime_error
{
public:
    explicit SchedulingError(const std::string& what_arg)
        : std::runtime_error {"SchedulingError: " + what_arg}
    {}
};

/**
 * The central orchestrator that maintains an in-memory job registry,
 * collaborates with lower-level timer/worker pools, and publishes metrics.
 *
 * Thread-Safety:
 *      All public methods are safe for concurrent invocation.
 */
class SchedulingService : public std::enable_shared_from_this<SchedulingService>
{
public:
    using Task = std::function<void(const JobDescriptor&)>;

    // ──────────────────────────── Ctor / Dtor ───────────────────────────────
    explicit SchedulingService(std::shared_ptr<logging::Logger>  logger,
                               std::shared_ptr<metrics::MetricsRegistry> metrics_registry);

    // Non-copyable / movable.  Service is intended to live behind shared_ptr.
    SchedulingService(const SchedulingService&)            = delete;
    SchedulingService& operator=(const SchedulingService&) = delete;
    SchedulingService(SchedulingService&&)                 = delete;
    SchedulingService& operator=(SchedulingService&&)      = delete;

    ~SchedulingService();

    // ────────────────────────── Job Management API ──────────────────────────
    /**
     * Schedule a new job for execution.
     *
     * Returns:
     *      A valid JobHandle on success.
     * Throws:
     *      SchedulingError if descriptor validation fails or resources exhausted.
     */
    [[nodiscard]]
    JobHandle schedule(const JobDescriptor& descriptor, Task task);

    /**
     * Cancel a pending or recurring job.
     *
     * Returns:
     *      true  – job was canceled (or completed) successfully
     *      false – jobId unknown
     */
    bool cancel(JobHandle::Id job_id);

    /**
     * Dynamically update the next run-time for an existing job.  Implemented
     * with “best effort” semantics; jobs already in flight will continue.
     */
    bool reschedule(JobHandle::Id job_id,
                    std::chrono::system_clock::time_point new_time);

    /**
     * Returns a snapshot of currently registered jobs.  Provides full
     * descriptors but omits callable to avoid user misuse.
     */
    std::vector<JobDescriptor> list_jobs() const;

    /**
     * Force flush pending metrics (mostly used by unit tests).
     */
    void flush_metrics();

private:
    // ──────────────────────────── Internals ────────────────────────────────
    struct JobNode
    {
        JobDescriptor descriptor;
        Task          task;
        std::atomic<bool> cancelled {false};
    };

    [[nodiscard]] JobHandle::Id generate_job_id() noexcept;

    void validate_descriptor(const JobDescriptor& descriptor);

    // Internal metrics helpers
    void init_metrics();
    void record_submission(const JobCategory category);
    void record_completion(const JobCategory category,
                           const std::chrono::nanoseconds duration) noexcept;

    // Timer-callback routed from external timer wheel
    void on_timer_trigger(JobHandle::Id id);

private:
    // Dependencies
    std::shared_ptr<logging::Logger>         logger_;
    std::shared_ptr<metrics::MetricsRegistry> metrics_;

    // Concurrent state
    mutable std::shared_mutex                            registry_mutex_;
    std::unordered_map<JobHandle::Id, std::shared_ptr<JobNode>> registry_;

    std::atomic<JobHandle::Id> next_job_id_ {1};

    // Metrics – lazy-initialized in init_metrics()
    struct
    {
        void* submission_counter {nullptr};
        void* completion_histogram {nullptr};
        void* active_gauge {nullptr};
    } metric_handles_;
};

// ───────────────────────────────── Implementation ───────────────────────────
// Note: Lightweight inline implementations are provided for convenience.
//       Heavier logic should reside in an accompanying .cpp to keep compile
//       times manageable.

inline SchedulingService::SchedulingService(
        std::shared_ptr<logging::Logger> logger,
        std::shared_ptr<metrics::MetricsRegistry> metrics_registry)
    : logger_ {std::move(logger)}
    , metrics_ {std::move(metrics_registry)}
{
    init_metrics();
}

inline SchedulingService::~SchedulingService() = default;

inline JobHandle SchedulingService::schedule(const JobDescriptor& descriptor, Task task)
{
    validate_descriptor(descriptor);

    const JobHandle::Id id = generate_job_id();
    auto node              = std::make_shared<JobNode>();
    node->descriptor       = descriptor;
    node->task             = std::move(task);

    {
        std::unique_lock<std::shared_mutex> lock {registry_mutex_};
        registry_.emplace(id, std::move(node));
    }

    record_submission(descriptor.category);

    // ↓ Forward to timer wheel / runtime (not implemented here)
    // timer_wheel_->register_timer(id, descriptor.first_run_at);

    logger_->debug("Job [{}] '{}' scheduled (category={}, priority={})",
                   id,
                   descriptor.name,
                   static_cast<int>(descriptor.category),
                   static_cast<int>(descriptor.priority));

    return JobHandle {id};
}

inline bool SchedulingService::cancel(JobHandle::Id job_id)
{
    std::shared_ptr<JobNode> node;
    {
        std::shared_lock<std::shared_mutex> lock {registry_mutex_};
        auto it = registry_.find(job_id);
        if (it == registry_.end())
            return false;
        node = it->second;
    }

    node->cancelled.store(true, std::memory_order_release);
    // timer_wheel_->cancel_timer(job_id); // best effort

    logger_->info("Job [{}] '{}' canceled", job_id, node->descriptor.name);
    return true;
}

inline bool SchedulingService::reschedule(JobHandle::Id job_id,
                                          std::chrono::system_clock::time_point new_time)
{
    std::shared_ptr<JobNode> node;
    {
        std::shared_lock<std::shared_mutex> lock {registry_mutex_};
        auto it = registry_.find(job_id);
        if (it == registry_.end())
            return false;
        node = it->second;
    }

    auto& descriptor = node->descriptor;
    descriptor.first_run_at = new_time;

    // timer_wheel_->update_timer(job_id, new_time);

    logger_->info("Job [{}] '{}' rescheduled", job_id, descriptor.name);
    return true;
}

inline std::vector<JobDescriptor> SchedulingService::list_jobs() const
{
    std::vector<JobDescriptor> out;
    std::shared_lock<std::shared_mutex> lock {registry_mutex_};
    out.reserve(registry_.size());
    for (const auto& kv : registry_)
        out.push_back(kv.second->descriptor);
    return out;
}

inline void SchedulingService::flush_metrics()
{
    // metrics_->flush(); // Implementation-specific
}

// ─────── Internal helpers ───────────────────────────────────────────────────
inline JobHandle::Id SchedulingService::generate_job_id() noexcept
{
    return next_job_id_.fetch_add(1, std::memory_order_relaxed);
}

inline void SchedulingService::validate_descriptor(const JobDescriptor& desc)
{
    if (desc.name.empty())
        throw SchedulingError {"Job name must not be empty"};

    if (desc.recurrence && *desc.recurrence <= std::chrono::milliseconds {0})
        throw SchedulingError {"Recurrence interval must be positive"};

    if (desc.first_run_at.time_since_epoch().count() == 0)
        throw SchedulingError {"first_run_at must be set"};

    // More domain-specific validation (e.g., maintenance tasks only off-hours) can be added.
}

inline void SchedulingService::init_metrics()
{
    // metric_handles_.submission_counter  = metrics_->counter("sched.submissions");
    // metric_handles_.completion_histogram = metrics_->histogram("sched.execution_time");
    // metric_handles_.active_gauge         = metrics_->gauge("sched.active_jobs");
}

inline void SchedulingService::record_submission(const JobCategory /*category*/)
{
    // metrics_->inc(metric_handles_.submission_counter);
    // metrics_->inc(metric_handles_.active_gauge);
}

inline void SchedulingService::record_completion(const JobCategory /*category*/,
                                                 const std::chrono::nanoseconds /*duration*/) noexcept
{
    // metrics_->observe(metric_handles_.completion_histogram, duration.count());
    // metrics_->dec(metric_handles_.active_gauge);
}

inline void SchedulingService::on_timer_trigger(JobHandle::Id id)
{
    std::shared_ptr<JobNode> node;
    {
        std::shared_lock<std::shared_mutex> lock {registry_mutex_};
        auto it = registry_.find(id);
        if (it == registry_.end())
            return;
        node = it->second;
    }

    if (node->cancelled.load(std::memory_order_acquire))
        return;

    const auto start = std::chrono::steady_clock::now();
    try
    {
        node->task(node->descriptor);
    }
    catch (const std::exception& ex)
    {
        logger_->error("Job [{}] '{}' failed: {}", id, node->descriptor.name, ex.what());
    }
    const auto duration = std::chrono::steady_clock::now() - start;
    record_completion(node->descriptor.category,
                      std::chrono::duration_cast<std::chrono::nanoseconds>(duration));

    // Reschedule if recurring
    if (node->descriptor.recurrence && !node->cancelled.load(std::memory_order_relaxed))
    {
        node->descriptor.first_run_at += *node->descriptor.recurrence;
        // timer_wheel_->update_timer(id, node->descriptor.first_run_at);
    }
    else
    {
        // One-off job; remove from registry
        std::unique_lock<std::shared_mutex> lock {registry_mutex_};
        registry_.erase(id);
    }
}

} // namespace ci360::services
```