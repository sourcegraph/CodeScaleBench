```cpp
#pragma once
/**
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * File  : src/core/patterns/pipeline_stage.h
 * Author: CardioInsight360 Core Team
 *
 * A generic, thread-safe PipelineStage abstraction that follows the
 *  Pipeline Pattern (aka Pipes-and-Filters).  Each stage is responsible
 *  for ingesting an element of type `In`, applying a synchronous or
 *  asynchronous transformation, and yielding a result of type `Out`.
 *
 *  ┌──────────────┐   push()   ┌──────────────┐  pop()   ┌──────────────┐
 *  │  Upstream    │ ─────────►│  This Stage  │─────────►│  Downstream  │
 *  └──────────────┘            └──────────────┘          └──────────────┘
 *
 * Features
 * --------
 *  • Thread-safe, lock-free queues based on Intel TBB
 *  • Cooperative cancellation & graceful drain/flush
 *  • Built-in metrics (throughput, latency, error count)
 *  • Observer hooks for real-time monitoring dashboards
 *  • Strategy-friendly design: override `transform()` in subclasses
 *
 * Usage
 * -----
 *  class QRSDetectorStage final :
 *      public PipelineStage<RawEcgFrame, BeatAnnotations>
 *  {
 *      protected:
 *          BeatAnnotations transform(RawEcgFrame &&frame) override;
 *  };
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <tbb/concurrent_queue.h>
#include <tbb/task_group.h>
#include <vector>

#include <spdlog/spdlog.h>

namespace ci360::core::patterns
{

//------------------------------------------------------------------------------
// Helper: High-resolution clock alias
//------------------------------------------------------------------------------
using Clock         = std::chrono::high_resolution_clock;
using TimePoint     = Clock::time_point;
using Nanoseconds   = std::chrono::nanoseconds;

//------------------------------------------------------------------------------
// PipelineStageError
//------------------------------------------------------------------------------
class PipelineStageError : public std::runtime_error
{
public:
    explicit PipelineStageError(const std::string& what_)
        : std::runtime_error{what_}
    {}
};

//------------------------------------------------------------------------------
// PipelineStage
//------------------------------------------------------------------------------
enum class StageState : uint8_t
{
    Created,
    Initialized,
    Running,
    Stopping,
    Stopped,
    Aborted
};

struct Metrics
{
    std::atomic<uint64_t> total_in  {0};
    std::atomic<uint64_t> total_out {0};
    std::atomic<uint64_t> total_err {0};

    // Average latency (EMA) in nanoseconds.
    std::atomic<double>   latency_ns {0.0};

    void reset() noexcept
    {
        total_in.store(0, std::memory_order_relaxed);
        total_out.store(0, std::memory_order_relaxed);
        total_err.store(0, std::memory_order_relaxed);
        latency_ns.store(0.0, std::memory_order_relaxed);
    }
};

template <typename In, typename Out>
class PipelineStage : public std::enable_shared_from_this<PipelineStage<In, Out>>
{
public:
    using self_type             = PipelineStage<In, Out>;
    using ptr                   = std::shared_ptr<self_type>;
    using upstream_ptr          = std::weak_ptr<self_type>;
    using downstream_ptr        = std::weak_ptr<PipelineStage<Out, void>>; // can be ignored if last stage
    using TransformFn           = std::function<Out(In&&)>;

    // We deliberately allow the last stage to terminate the pipeline by having Out = void.
    static_assert(!std::is_same_v<In, void>,  "Input type cannot be void");

    //------------------------------------------------------------------------
    // Constructor / Destructor
    //------------------------------------------------------------------------
    explicit PipelineStage(std::string name,
                           std::size_t queue_capacity        = 1'024,
                           std::size_t concurrency_hint      = std::thread::hardware_concurrency())
        : m_name              {std::move(name)}
        , m_queue_capacity    {queue_capacity}
        , m_concurrency_hint  {std::max<std::size_t>(1, concurrency_hint)}
        , m_state             {StageState::Created}
        , m_in_queue          {static_cast<int>(queue_capacity)}
    {}

    virtual ~PipelineStage()
    {
        try {
            stop(/*drain=*/false);
        } catch (...) {
            spdlog::error("[{}] Exception in destructor during stop().", m_name);
        }
    }

    //------------------------------------------------------------------------
    // Non-copyable, movable
    //------------------------------------------------------------------------
    PipelineStage(const PipelineStage&)            = delete;
    PipelineStage& operator=(const PipelineStage&) = delete;

    PipelineStage(PipelineStage&&)                 = delete;
    PipelineStage& operator=(PipelineStage&&)      = delete;

    //------------------------------------------------------------------------
    // Public API
    //------------------------------------------------------------------------

    // Initialize any prerequisite resources
    virtual void init()
    {
        expect_state(StageState::Created);

        m_state.store(StageState::Initialized, std::memory_order_release);
        spdlog::info("[{}] Initialized (queue_capacity = {}, concurrency_hint = {})",
                     m_name, m_queue_capacity, m_concurrency_hint);
    }

    // Start background workers
    virtual void start()
    {
        expect_state(StageState::Initialized);
        m_state.store(StageState::Running, std::memory_order_release);

        m_cancel_token.store(false, std::memory_order_relaxed);

        for (std::size_t i = 0; i < m_concurrency_hint; ++i) {
            m_workers.run([self = this->shared_from_this()] {
                self->worker_loop();
            });
        }
        spdlog::info("[{}] Started with {} worker(s).", m_name, m_concurrency_hint);
    }

    // Graceful stop (optionally drain)
    virtual void stop(bool drain = true)
    {
        const auto expected = StageState::Running;
        if (!m_state.compare_exchange_strong(const_cast<StageState&>(expected),
                                             StageState::Stopping,
                                             std::memory_order_acq_rel))
        {
            return; // Already stopped or never started.
        }

        m_cancel_token.store(true, std::memory_order_relaxed);

        if (!drain) {
            // Purge incoming queue
            In tmp;
            while (m_in_queue.try_pop(tmp)) { /* discard */ }
        }

        m_workers.wait();
        m_state.store(StageState::Stopped, std::memory_order_release);
        spdlog::info("[{}] Stopped (drain = {})", m_name, drain);
    }

    // Immediate abort (unrecoverable error)
    virtual void abort(const std::string& reason)
    {
        spdlog::error("[{}] Aborting pipeline stage: {}", m_name, reason);
        m_state.store(StageState::Aborted, std::memory_order_release);
        m_cancel_token.store(true, std::memory_order_relaxed);

        // drain quickly
        In tmp;
        while (m_in_queue.try_pop(tmp)) { /* discard */ }

        m_workers.wait();
    }

    // Upstream pushes items into this stage.
    bool push(In&& in)
    {
        auto st = m_state.load(std::memory_order_acquire);
        if (st != StageState::Running && st != StageState::Stopping) {
            spdlog::warn("[{}] Cannot push() item while stage is not running.", m_name);
            return false;
        }

        if (!m_in_queue.try_push(std::move(in))) {
            spdlog::warn("[{}] Queue full; push() failed.", m_name);
            return false;
        }
        m_metrics.total_in.fetch_add(1, std::memory_order_relaxed);
        return true;
    }

    // Link downstream consumer for automatic chaining
    template<typename DownStage>
    void attach_downstream(const std::shared_ptr<DownStage>& downstream)
    {
        static_assert(std::is_same_v<Out, typename DownStage::input_type>,
                      "Downstream stage input type mismatch.");
        m_downstream = downstream;
    }

    // Metrics snapshot (thread-safe)
    Metrics snapshot_metrics() const noexcept
    {
        return m_metrics;
    }

    StageState state() const noexcept
    {
        return m_state.load(std::memory_order_acquire);
    }

    const std::string& name() const noexcept
    {
        return m_name;
    }

    using input_type  = In;
    using output_type = Out;

protected:
    //------------------------------------------------------------------------
    // Derived classes override this to implement their business logic
    //------------------------------------------------------------------------
    virtual Out transform(In&& in) = 0;

    // If this is the last stage (Out == void), specialization below will handle it
    virtual void emit_downstream(Out&& out)
    {
        if (auto ds = m_downstream.lock()) {
            ds->push(std::move(out));
        }
    }

private:
    //------------------------------------------------------------------------
    // Worker loop
    //------------------------------------------------------------------------
    void worker_loop()
    {
        try {
            In item;
            while (!m_cancel_token.load(std::memory_order_relaxed))
            {
                if (!m_in_queue.try_pop(item)) {
                    // No work; sleep briefly to avoid busy-spin
                    std::this_thread::sleep_for(std::chrono::milliseconds{1});
                    continue;
                }

                const auto ts_start = Clock::now();
                try {
                    Out result = transform(std::move(item));
                    const auto ts_end = Clock::now();

                    emit_downstream(std::move(result));

                    m_metrics.total_out.fetch_add(1, std::memory_order_relaxed);
                    update_latency(std::chrono::duration_cast<Nanoseconds>(ts_end - ts_start).count());
                }
                catch (const std::exception& ex) {
                    m_metrics.total_err.fetch_add(1, std::memory_order_relaxed);
                    spdlog::error("[{}] transform() threw: {}", m_name, ex.what());
                    if (m_error_policy == ErrorPolicy::AbortOnException)
                        abort(ex.what());
                }
            }
        } catch (const std::exception& ex) {
            spdlog::critical("[{}] Unhandled exception in worker_loop: {}", m_name, ex.what());
            abort(ex.what());
        }
    }

    //------------------------------------------------------------------------
    // Latency calculation (Exponential Moving Average)
    //------------------------------------------------------------------------
    void update_latency(uint64_t latest_ns)
    {
        constexpr double alpha = 0.10;
        double prev = m_metrics.latency_ns.load(std::memory_order_relaxed);
        double next = (prev == 0.0)
                          ? static_cast<double>(latest_ns)
                          : (alpha * static_cast<double>(latest_ns) + (1.0 - alpha) * prev);
        m_metrics.latency_ns.store(next, std::memory_order_relaxed);
    }

    //------------------------------------------------------------------------
    // Utilities
    //------------------------------------------------------------------------
    void expect_state(StageState expected)
    {
        auto s = m_state.load(std::memory_order_acquire);
        if (s != expected) {
            throw PipelineStageError{
                "[" + m_name + "] Invalid state: expected " +
                std::to_string(static_cast<int>(expected)) + ", got " +
                std::to_string(static_cast<int>(s))
            };
        }
    }

    enum class ErrorPolicy { ContinueOnException, AbortOnException };
    //------------------------------------------------------------------------
    // Members
    //------------------------------------------------------------------------
    const std::string        m_name;
    const std::size_t        m_queue_capacity;
    const std::size_t        m_concurrency_hint;

    std::atomic<StageState>  m_state;
    std::atomic<bool>        m_cancel_token {false};

    tbb::concurrent_bounded_queue<In> m_in_queue;
    tbb::task_group                    m_workers;

    Metrics                            m_metrics;
    ErrorPolicy                        m_error_policy { ErrorPolicy::AbortOnException };

    downstream_ptr                     m_downstream;
};

//------------------------------------------------------------------------------
// Partial specialization for terminal stage (Out == void).
//------------------------------------------------------------------------------
template <typename In>
class PipelineStage<In, void> : public std::enable_shared_from_this<PipelineStage<In, void>>
{
public:
    using self_type             = PipelineStage<In, void>;
    using ptr                   = std::shared_ptr<self_type>;

    explicit PipelineStage(std::string name,
                           std::size_t queue_capacity        = 1'024,
                           std::size_t concurrency_hint      = std::thread::hardware_concurrency())
        : m_name              {std::move(name)}
        , m_queue_capacity    {queue_capacity}
        , m_concurrency_hint  {std::max<std::size_t>(1, concurrency_hint)}
        , m_state             {StageState::Created}
        , m_in_queue          {static_cast<int>(queue_capacity)}
    {}

    virtual ~PipelineStage()
    {
        try {
            stop(/*drain=*/false);
        } catch (...) {
            spdlog::error("[{}] Exception in destructor during stop().", m_name);
        }
    }

    PipelineStage(const PipelineStage&)            = delete;
    PipelineStage& operator=(const PipelineStage&) = delete;
    PipelineStage(PipelineStage&&)                 = delete;
    PipelineStage& operator=(PipelineStage&&)      = delete;

    // Public API (similar to generic version)
    void init()
    {
        expect_state(StageState::Created);
        m_state.store(StageState::Initialized, std::memory_order_release);
    }

    void start()
    {
        expect_state(StageState::Initialized);
        m_state.store(StageState::Running, std::memory_order_release);

        m_cancel_token.store(false, std::memory_order_relaxed);

        for (std::size_t i = 0; i < m_concurrency_hint; ++i) {
            m_workers.run([self = this->shared_from_this()] { self->worker_loop(); });
        }
    }

    void stop(bool drain = true)
    {
        const auto expected = StageState::Running;
        if (!m_state.compare_exchange_strong(const_cast<StageState&>(expected),
                                             StageState::Stopping,
                                             std::memory_order_acq_rel))
        {
            return;
        }

        m_cancel_token.store(true, std::memory_order_relaxed);
        if (!drain) {
            In tmp;
            while (m_in_queue.try_pop(tmp)) { /* discard */ }
        }
        m_workers.wait();
        m_state.store(StageState::Stopped, std::memory_order_release);
    }

    void abort(const std::string& reason)
    {
        spdlog::error("[{}] Terminal stage aborted: {}", m_name, reason);
        m_state.store(StageState::Aborted, std::memory_order_release);
        m_cancel_token.store(true, std::memory_order_relaxed);
        m_workers.wait();
    }

    bool push(In&& in)
    {
        auto st = m_state.load(std::memory_order_acquire);
        if (st != StageState::Running && st != StageState::Stopping) {
            return false;
        }
        if (!m_in_queue.try_push(std::move(in))) {
            return false;
        }
        m_metrics.total_in.fetch_add(1, std::memory_order_relaxed);
        return true;
    }

    Metrics snapshot_metrics() const noexcept { return m_metrics; }
    StageState state() const noexcept { return m_state.load(std::memory_order_acquire); }
    const std::string& name() const noexcept { return m_name; }

    using input_type  = In;
    using output_type = void;

protected:
    virtual void consume(In&& in) = 0;

private:
    void worker_loop()
    {
        try {
            In item;
            while (!m_cancel_token.load(std::memory_order_relaxed))
            {
                if (!m_in_queue.try_pop(item)) {
                    std::this_thread::sleep_for(std::chrono::milliseconds{1});
                    continue;
                }

                const auto ts_start = Clock::now();
                try {
                    consume(std::move(item));
                    const auto ts_end = Clock::now();
                    m_metrics.total_out.fetch_add(1, std::memory_order_relaxed);
                    update_latency(std::chrono::duration_cast<Nanoseconds>(ts_end - ts_start).count());
                }
                catch (const std::exception& ex) {
                    m_metrics.total_err.fetch_add(1, std::memory_order_relaxed);
                    spdlog::error("[{}] consume() threw: {}", m_name, ex.what());
                    if (m_error_policy == ErrorPolicy::AbortOnException)
                        abort(ex.what());
                }
            }
        } catch (const std::exception& ex) {
            spdlog::critical("[{}] Unhandled exception in worker_loop: {}", m_name, ex.what());
            abort(ex.what());
        }
    }

    void update_latency(uint64_t latest_ns)
    {
        constexpr double alpha = 0.10;
        double prev = m_metrics.latency_ns.load(std::memory_order_relaxed);
        double next = (prev == 0.0)
                          ? static_cast<double>(latest_ns)
                          : (alpha * static_cast<double>(latest_ns) + (1.0 - alpha) * prev);
        m_metrics.latency_ns.store(next, std::memory_order_relaxed);
    }

    void expect_state(StageState expected)
    {
        auto s = m_state.load(std::memory_order_acquire);
        if (s != expected) {
            throw PipelineStageError{
                "[" + m_name + "] Invalid state: expected " +
                std::to_string(static_cast<int>(expected)) + ", got " +
                std::to_string(static_cast<int>(s))
            };
        }
    }

    enum class ErrorPolicy { ContinueOnException, AbortOnException };

    // Member fields
    const std::string                      m_name;
    const std::size_t                      m_queue_capacity;
    const std::size_t                      m_concurrency_hint;

    std::atomic<StageState>                m_state;
    std::atomic<bool>                      m_cancel_token {false};

    tbb::concurrent_bounded_queue<In>      m_in_queue;
    tbb::task_group                        m_workers;

    Metrics                                m_metrics;
    ErrorPolicy                            m_error_policy { ErrorPolicy::AbortOnException };
};

} // namespace ci360::core::patterns
```