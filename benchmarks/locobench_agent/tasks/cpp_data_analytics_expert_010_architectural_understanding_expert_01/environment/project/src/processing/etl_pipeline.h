```cpp
/************************************************************************************
 *  File:    etl_pipeline.h
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      Header-only implementation of the generic ETL (Extract-Transform-Load)
 *      pipeline that powers CardioInsight360’s analytical back-end.  The pipeline
 *      is intentionally designed to be agnostic of underlying data formats
 *      (HL7, FHIR, proprietary) and execution modes (batch vs. streaming) while
 *      offering:
 *          • Pluggable stage strategies (Extract / Transform / Validate / Load)
 *          • Parallel execution via Intel® TBB flow-graph
 *          • First-class observability through a light-weight Observer pattern
 *          • Robust error handling and graceful shutdown semantics
 *
 *      The interface defined here is the primary contract between high-level
 *      orchestration code (Schedulers, REST/MQ Endpoints) and the low-level
 *      data-engineering primitives scattered across the code-base.
 *
 *  Copyright:
 *      © 2024 CardioInsight360.  All rights reserved.
 ************************************************************************************/

#pragma once

/* Standard C++17 */
#include <atomic>
#include <chrono>
#include <exception>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

/* Intel® Threading Building Blocks – single header installation (v2021+) */
#include <tbb/flow_graph.h>

/* Apache Kafka C/C++ client – forward declaration only (linkage in .cpp) */
struct rd_kafka_s;            // librdkafka opaque handle
struct rd_kafka_conf_s;

/* Logging façade (spdlog) */
#include <spdlog/spdlog.h>

namespace cardio_insight_360::processing
{
/*---------------------------------------------------------------------------*/
/*  Domain-agnostic data container                                            */
/*---------------------------------------------------------------------------*/

struct DataRecord
{
    std::string   source;         // e.g., “ICU-Bed-04”
    std::string   topic;          // Kafka topic / HL7 message type
    std::vector<std::byte> payload;
    std::chrono::system_clock::time_point timestamp;

    template <typename T>
    [[nodiscard]] T as() const;   //  Conversion helper – defined elsewhere
};

/*---------------------------------------------------------------------------*/
/*  Pipeline Exceptions                                                       */
/*---------------------------------------------------------------------------*/

class PipelineError : public std::runtime_error
{
public:
    using std::runtime_error::runtime_error;
};

class StageTimeoutError final : public PipelineError
{
public:
    using PipelineError::PipelineError;
};

class StageAbortedError final : public PipelineError
{
public:
    using PipelineError::PipelineError;
};

/*---------------------------------------------------------------------------*/
/*  Observer Pattern: real-time metrics / events                              */
/*---------------------------------------------------------------------------*/

enum class StageEvent
{
    kStarted,
    kCompleted,
    kFailed,
    kSkipped
};

struct Metrics
{
    std::string_view stage_name;
    StageEvent       event;
    std::chrono::nanoseconds latency;
    std::string_view error_message;
};

class IMetricsObserver
{
public:
    virtual ~IMetricsObserver() = default;
    virtual void on_metrics(const Metrics& m) noexcept = 0;
};

/*---------------------------------------------------------------------------*/
/*  Strategy Pattern: Stage behavior customization                            */
/*---------------------------------------------------------------------------*/

class IStageStrategy
{
public:
    virtual ~IStageStrategy() = default;

    //  Returns true  => Stage produced a DataRecord for downstream stages
    //          false => Stage indicates “skip / filter out”
    virtual bool execute(DataRecord& record) = 0;

    //  Human-readable name used in logs / metrics
    [[nodiscard]] virtual std::string_view name() const noexcept = 0;
};

/*---------------------------------------------------------------------------*/
/*  ETLStage – runtime node in the flow graph                                 */
/*---------------------------------------------------------------------------*/

class ETLStage
{
public:
    explicit ETLStage(std::unique_ptr<IStageStrategy> strategy,
                      std::chrono::milliseconds          timeout = std::chrono::minutes(2))
        : m_strategy(std::move(strategy))
        , m_timeout(timeout)
        , m_log(spdlog::get("etl") ? spdlog::get("etl") : spdlog::default_logger())
    {
        if (!m_strategy)
            throw PipelineError("ETLStage requires a non-null strategy implementation");
    }

    ETLStage(const ETLStage&)            = delete;
    ETLStage& operator=(const ETLStage&) = delete;
    ETLStage(ETLStage&&)                 = delete;
    ETLStage& operator=(ETLStage&&)      = delete;

    bool run(DataRecord& record) const
    {
        auto          start = std::chrono::steady_clock::now();
        const auto    name  = m_strategy->name();
        std::promise<bool> prom;
        std::future<bool>  fut = prom.get_future();

        std::thread worker([this, &prom, &record] {
            try
            {
                prom.set_value(m_strategy->execute(record));
            }
            catch (...)
            {
                try
                {
                    prom.set_exception(std::current_exception());
                }
                catch (...)
                {
                    // set_exception may throw if already satisfied – ignore
                }
            }
        });
        worker.detach();

        if (fut.wait_for(m_timeout) == std::future_status::ready)
        {
            auto finished = std::chrono::steady_clock::now();
            update_metrics(StageEvent::kCompleted, name, finished - start);
            return fut.get();
        }
        else
        {
            update_metrics(StageEvent::kFailed, name, std::chrono::steady_clock::now() - start,
                           "stage timeout");
            throw StageTimeoutError("Stage \"" + std::string(name) + "\" exceeded timeout");
        }
    }

    void attach(IMetricsObserver* obs) noexcept
    {
        std::unique_lock lock(m_obs_mtx);
        m_observers.push_back(obs);
    }

private:
    void update_metrics(StageEvent              e,
                        std::string_view        name,
                        std::chrono::nanoseconds latency,
                        std::string_view        err = {}) const noexcept
    {
        Metrics m{ name, e, latency, err };
        std::shared_lock lock(m_obs_mtx);
        for (auto* o : m_observers)
        {
            if (o)
                o->on_metrics(m);
        }

        switch (e)
        {
            case StageEvent::kCompleted:
                m_log->debug("Stage [{}] completed in {} µs", name, latency.count() / 1'000);
                break;
            case StageEvent::kFailed:
                m_log->error("Stage [{}] failed: {}", name, err);
                break;
            default:
                m_log->debug("Stage [{}] event {}", name, static_cast<int>(e));
        }
    }

    /* Data members */
    std::unique_ptr<IStageStrategy>        m_strategy;
    std::chrono::milliseconds              m_timeout;
    mutable std::vector<IMetricsObserver*> m_observers;
    mutable std::shared_mutex              m_obs_mtx;
    std::shared_ptr<spdlog::logger>        m_log;
};

/*---------------------------------------------------------------------------*/
/*  ETLPipeline – high-level orchestrator                                     */
/*---------------------------------------------------------------------------*/

class ETLPipeline : public IMetricsObserver
{
public:
    ETLPipeline() = default;

    explicit ETLPipeline(std::string id) : m_pipeline_id(std::move(id)) {}

    //  Adds a stage to the tail of the pipeline
    ETLPipeline& push_back(std::unique_ptr<IStageStrategy> stage_strategy,
                           std::chrono::milliseconds       timeout = std::chrono::minutes(2))
    {
        auto& stage = m_stages.emplace_back(std::make_unique<ETLStage>(
            std::move(stage_strategy), timeout));
        stage->attach(this);
        return *this;
    }

    //  Runs the pipeline over the provided DataRecord. Throws on error.
    void run(DataRecord record)
    {
        if (m_stages.empty())
            throw PipelineError("Cannot execute ETLPipeline with zero stages");

        tbb::flow::graph g;

        //  Source – single record node
        tbb::flow::source_node<DataRecord> src(
            g, [captured = std::move(record), first = true](DataRecord& out) mutable -> bool {
                if (first)
                {
                    out   = std::move(captured);
                    first = false;
                    return true;
                }
                return false;
            },
            /* is_active = */ false);

        //  Chain of function nodes
        std::vector<std::unique_ptr<tbb::flow::function_node<DataRecord, DataRecord>>> nodes;
        nodes.reserve(m_stages.size());

        for (auto& stg : m_stages)
        {
            nodes.push_back(std::make_unique<tbb::flow::function_node<DataRecord, DataRecord>>(
                g, tbb::flow::unlimited,
                [stg = stg.get()](DataRecord r) -> DataRecord {
                    if (!stg->run(r))
                    {
                        // Stage opted to skip record – mark by clearing payload
                        r.payload.clear();
                    }
                    return r;
                }));
        }

        //  Wire-up nodes
        if (!nodes.empty())
            tbb::flow::make_edge(src, *nodes.front());

        for (size_t i = 1; i < nodes.size(); ++i)
            tbb::flow::make_edge(*nodes[i - 1], *nodes[i]);

        //  Final sink – counts successfully processed records
        tbb::flow::function_node<DataRecord> sink(
            g, tbb::flow::serial, [this](const DataRecord& r) {
                if (!r.payload.empty())
                    ++m_success_counter;
            });

        if (!nodes.empty())
            tbb::flow::make_edge(*nodes.back(), sink);
        else
            tbb::flow::make_edge(src, sink);

        src.activate();
        g.wait_for_all();
    }

    void clear() { m_stages.clear(); }

    std::size_t success_count() const noexcept { return m_success_counter.load(); }

    /* IMetricsObserver */
    void on_metrics(const Metrics& m) noexcept override
    {
        std::unique_lock lock(m_metrics_mtx);
        m_metrics.emplace_back(m);
    }

    const std::vector<Metrics>& metrics() const noexcept { return m_metrics; }

private:
    std::string                                   m_pipeline_id{"default"};
    std::vector<std::unique_ptr<ETLStage>>        m_stages;
    std::atomic<std::size_t>                      m_success_counter{ 0 };
    mutable std::mutex                            m_metrics_mtx;
    std::vector<Metrics>                          m_metrics;
};

/*---------------------------------------------------------------------------*/
/*  Helper: Convenience builder                                               */
/*---------------------------------------------------------------------------*/

class ETLPipelineBuilder
{
public:
    explicit ETLPipelineBuilder(std::string id = "pipeline")
        : m_pipeline(std::make_unique<ETLPipeline>(std::move(id)))
    {}

    template <typename Strategy, typename... Args>
    ETLPipelineBuilder& add_stage(std::chrono::milliseconds timeout, Args&&... args)
    {
        m_pipeline->push_back(std::make_unique<Strategy>(std::forward<Args>(args)...), timeout);
        return *this;
    }

    std::unique_ptr<ETLPipeline> build() { return std::move(m_pipeline); }

private:
    std::unique_ptr<ETLPipeline> m_pipeline;
};

} // namespace cardio_insight_360::processing
```