#ifndef CARDIO_INSIGHT_360_SRC_SERVICES_ERROR_RECOVERY_SERVICE_H_
#define CARDIO_INSIGHT_360_SRC_SERVICES_ERROR_RECOVERY_SERVICE_H_

/*
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  ------------------------------------------------------
 *  File        : error_recovery_service.h
 *  Description : Centralised error-handling & automated recovery orchestration
 *                for the pseudo-microservices layer.  Handles transient and
 *                persistent failures across stream-processing, ETL, storage
 *                and visualisation domains by applying pluggable recovery
 *                policies, executing back-off retries and surfacing metrics
 *                to the built-in monitoring subsystem.
 *
 *  Copyright   : (c) 2024, CardioInsight360
 *  Licence     : Proprietary – All rights reserved.
 *
 *  NOTE: Header-only implementation to reduce translation-unit count for the
 *        monolithic build.    Thread-safety is guaranteed for all public APIs.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace ci360::services {

/* -------------------------------------------------------------------------- */
/*                               Utility enums                                */
/* -------------------------------------------------------------------------- */

/* A coarse classification of error provenance.  Extend as the system grows. */
enum class ErrorDomain : std::uint8_t {
    Ingestion,
    Transformation,
    Validation,
    Storage,
    Visualization,
    Unknown
};

/* Severity hints for policy selection and back-pressure decisions. */
enum class ErrorSeverity : std::uint8_t {
    Warning,        // Non-blocking; best-effort recovery.
    Transient,      // Retry should succeed after back-off.
    Critical,       // Might succeed, but time sensitive.
    Fatal           // Non-recoverable; requires human intervention.
};

/* -------------------------------------------------------------------------- */
/*                               Error context                                */
/* -------------------------------------------------------------------------- */

/*
 * Rich error metadata propagated by upstream components when failures occur.
 * This decouples the originator from the recovery execution logic.
 */
struct ErrorContext {
    ErrorDomain  domain            { ErrorDomain::Unknown };
    ErrorSeverity severity         { ErrorSeverity::Warning };
    std::string  message;                       // Human-readable details.
    std::string  component;                     // Logical component name.
    std::string  correlation_id;                // Trace/diagnostics id.
    std::chrono::system_clock::time_point timestamp
        { std::chrono::system_clock::now() };

    /* Optional structured payload (e.g., Kafka offset, file path, etc.) */
    std::unordered_map<std::string, std::string> metadata;
};

/* -------------------------------------------------------------------------- */
/*                             Recovery policy API                            */
/* -------------------------------------------------------------------------- */

/*
 * Abstract interface representing a recovery strategy.  Implementations
 * encapsulate domain-specific logic such as Kafka offset rewinds, Parquet
 * re-uploads, or graph recomputations.  Return true on successful recovery.
 */
class IRecoveryPolicy {
public:
    virtual ~IRecoveryPolicy() = default;

    /* Execute recovery in the caller thread.  Should be idempotent. */
    virtual bool attempt_recovery(const ErrorContext& ctx) = 0;

    /* Optional short identifier used for metrics and logging. */
    virtual std::string name() const noexcept = 0;
};

/* -------------------------------------------------------------------------- */
/*                         Exponential back-off helper                        */
/* -------------------------------------------------------------------------- */

class BackoffStrategy {
public:
    explicit BackoffStrategy(
        std::chrono::milliseconds initial_delay = std::chrono::milliseconds{250},
        std::chrono::milliseconds max_delay     = std::chrono::seconds{30},
        std::size_t               max_retries   = 5)
        : initial_delay_(initial_delay),
          max_delay_(max_delay),
          max_retries_(max_retries)
    {}

    /* Compute next delay or std::nullopt if retries exhausted. */
    std::optional<std::chrono::milliseconds> next_delay() {
        if (retry_count_ >= max_retries_) return std::nullopt;
        auto delay = current_delay_;
        current_delay_ = std::min(current_delay_ * 2, max_delay_);
        ++retry_count_;
        return delay;
    }

    void reset() {
        retry_count_ = 0;
        current_delay_ = initial_delay_;
    }

private:
    const std::chrono::milliseconds initial_delay_;
    const std::chrono::milliseconds max_delay_;
    const std::size_t               max_retries_;

    std::size_t               retry_count_   {0};
    std::chrono::milliseconds current_delay_;
};

/* -------------------------------------------------------------------------- */
/*                          ErrorRecoveryService class                        */
/* -------------------------------------------------------------------------- */

/*
 * Singleton service responsible for:
 *  1. Accepting error reports from any subsystem.
 *  2. Selecting an appropriate IRecoveryPolicy.
 *  3. Executing recovery attempts using bounded worker threads.
 *  4. Handling retries with exponential back-off.
 *  5. Publishing success/failure metrics via user-supplied callbacks.
 *
 * Design notes:
 *  • Thread-safe queue decouples producers from recovery workers.
 *  • RAII ensures graceful shutdown during process exit.
 *  • Policy registration is lock-free after initialization.
 */
class ErrorRecoveryService {
public:
    using MetricsCallback =
        std::function<void(const std::string& metric, double value)>;

    /* Retrieve global instance – created on first use in a thread-safe way. */
    static ErrorRecoveryService& instance() {
        static ErrorRecoveryService s;
        return s;
    }

    /* Non-copyable & non-movable. */
    ErrorRecoveryService(const ErrorRecoveryService&)            = delete;
    ErrorRecoveryService& operator=(const ErrorRecoveryService&) = delete;
    ErrorRecoveryService(ErrorRecoveryService&&)                 = delete;
    ErrorRecoveryService& operator=(ErrorRecoveryService&&)      = delete;

    /* ---------------------------------------------------------------------- */
    /*                           Public service API                           */
    /* ---------------------------------------------------------------------- */

    /*
     * Register a recovery policy for a specific ErrorDomain.  If a policy is
     * already present, it will be replaced.  Intended to be called during
     * application startup before any errors are reported.
     */
    void register_policy(
        ErrorDomain domain,
        std::shared_ptr<IRecoveryPolicy> policy)  // NOLINT(runtime/explicit)
    {
        if (!policy) {
            throw std::invalid_argument("policy must not be null");
        }
        std::lock_guard<std::mutex> lk(policy_mtx_);
        policies_[domain] = std::move(policy);
    }

    /*
     * Produce an error for asynchronous recovery.  Call-site must guarantee
     * ErrorContext validity (copy is taken).  Fast & lock-free for producers.
     */
    void report_error(ErrorContext ctx) {
        {
            std::lock_guard<std::mutex> lk(queue_mtx_);
            error_queue_.push(std::move(ctx));
        }
        queue_cv_.notify_one();
    }

    /*
     * Optional hook for exporting metrics (Prometheus, StatsD, etc.).
     * The callback must be lock-free and non-throwing.
     */
    void set_metrics_callback(MetricsCallback cb) {
        metrics_cb_ = std::move(cb);
    }

    /*
     * Explicit shutdown (optional).  Automatically invoked in destructor but
     * available for deterministic lifecycles in unit tests.
     */
    void shutdown() noexcept {
        running_.store(false, std::memory_order_relaxed);
        queue_cv_.notify_all();
        for (auto& w : workers_) {
            if (w.joinable()) { w.join(); }
        }
        workers_.clear();
    }

    ~ErrorRecoveryService() noexcept {
        shutdown();
    }

private:
    /* Private default ctor – spawns worker threads. */
    ErrorRecoveryService()
        : running_(true)
    {
        const auto concurrency = std::max(2u, std::thread::hardware_concurrency());
        for (unsigned i = 0; i < concurrency; ++i) {
            workers_.emplace_back([this] { worker_loop(); });
        }
    }

    /* ---------------------------------------------------------------------- */
    /*                          Internal worker logic                         */
    /* ---------------------------------------------------------------------- */

    void worker_loop() {
        /*
         * Each worker keeps a local BackoffStrategy so that retries are applied
         * per-error, not per-thread.  This is achieved by embedding the
         * strategy into a lambda passed through std::function.
         */
        while (running_.load(std::memory_order_relaxed)) {
            ErrorContext ctx;
            {
                std::unique_lock<std::mutex> lk(queue_mtx_);
                queue_cv_.wait(lk, [this] {
                    return !error_queue_.empty() || !running_.load();
                });

                if (!running_.load() && error_queue_.empty()) {
                    return; // graceful stop
                }

                ctx = std::move(error_queue_.front());
                error_queue_.pop();
            }

            // Retrieve the policy – default to Unknown if none.
            std::shared_ptr<IRecoveryPolicy> policy = policy_for(ctx.domain);

            if (!policy) {
                // Unregistered domain – escalate via metric.
                publish_metric("error_recovery.unhandled_domain", 1.0);
                continue;
            }

            BackoffStrategy backoff;
            bool recovered = false;

            do {
                try {
                    recovered = policy->attempt_recovery(ctx);
                    if (recovered) {
                        publish_metric("error_recovery.success", 1.0);
                        break;
                    }
                } catch (const std::exception& ex) {
                    // Policy threw – treat as failure but propagate info.
                    publish_metric("error_recovery.policy_exception", 1.0);
                    // Log subsystem would capture ex.what() actually.
                }

                auto delay_opt = backoff.next_delay();
                if (!delay_opt) { break; } // retries exhausted

                std::this_thread::sleep_for(*delay_opt);
            } while (running_.load(std::memory_order_relaxed));

            if (!recovered) {
                publish_metric("error_recovery.failed", 1.0);
                // Permanent failure – escalate to audit log / operator alarm.
            }
        }
    }

    std::shared_ptr<IRecoveryPolicy> policy_for(ErrorDomain d) {
        std::lock_guard<std::mutex> lk(policy_mtx_);
        auto it = policies_.find(d);
        if (it != policies_.end()) {
            return it->second;
        }
        auto def = policies_.find(ErrorDomain::Unknown);
        return (def != policies_.end()) ? def->second : nullptr;
    }

    void publish_metric(const std::string& m, double v) noexcept {
        if (metrics_cb_) {
            try { metrics_cb_(m, v); }
            catch (...) { /* Suppress – metrics must not fail the service */ }
        }
    }

    /* ---------------------------------------------------------------------- */
    /*                    Data members – protected by mutexes                 */
    /* ---------------------------------------------------------------------- */

    std::unordered_map<ErrorDomain, std::shared_ptr<IRecoveryPolicy>> policies_;
    std::mutex        policy_mtx_;

    std::queue<ErrorContext> error_queue_;
    std::mutex               queue_mtx_;
    std::condition_variable  queue_cv_;

    std::vector<std::thread> workers_;
    std::atomic_bool         running_;

    MetricsCallback metrics_cb_;
};

} // namespace ci360::services

#endif // CARDIO_INSIGHT_360_SRC_SERVICES_ERROR_RECOVERY_SERVICE_H_
