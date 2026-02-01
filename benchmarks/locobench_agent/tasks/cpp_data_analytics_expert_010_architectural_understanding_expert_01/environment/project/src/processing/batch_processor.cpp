```cpp
/*
 *  cardio_insight_360/src/processing/batch_processor.cpp
 *
 *  Copyright (c) CardioInsight360
 *
 *  A high–throughput, fault-tolerant batch–processing engine that consumes
 *  previously persisted raw data files, applies domain-specific ETL
 *  transformations, and stores curated datasets back to the Data-Lake.
 *
 *  The implementation leverages:
 *      • Intel TBB (Threading Building Blocks) for coarse-grained parallelism
 *      • Strategy Pattern for pluggable transformation logic
 *      • Observer Pattern hooks to surface run-time metrics
 *      • Modern C++17 idioms, RAII, and strong exception-safety guarantees
 *
 *  NOTE: For the sake of compilation in isolation, several dependencies are
 *  forward-declared or lightly stubbed.  In the full CardioInsight360 code-base
 *  these are provided by their respective translation units.
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>
#include <utility>
#include <vector>

// ---- 3rd-Party -------------------------------------------------------------
#include <tbb/task_group.h>
#include <tbb/concurrent_queue.h>

#ifdef CI360_HAVE_SPDLOG
    #include <spdlog/spdlog.h>
    namespace ci360_log = spdlog;
#else
    // Minimal fallback logger
    #include <iostream>
    namespace ci360_log
    {
        template <typename... Args>
        void info(Args&&... args)  { ((std::cout << std::forward<Args>(args)), ...); std::cout << '\n'; }

        template <typename... Args>
        void warn(Args&&... args)  { ((std::cerr << std::forward<Args>(args)), ...); std::cerr << '\n'; }

        template <typename... Args>
        void error(Args&&... args) { ((std::cerr << std::forward<Args>(args)), ...); std::cerr << '\n'; }
    }
#endif

// ---- Stubs for External CI360 Interfaces ----------------------------------
namespace ci360
{
    // Lightweight representation of a decoded, column-oriented data frame.
    struct DataFrame
    {
        std::string                     modality;   // ECG, BP, SpO2 ...
        std::vector<std::string>        columns;
        std::vector<std::vector<float>> rows;       // Row-major for simplicity
    };

    // Raw file plus metadata
    struct RawFile
    {
        std::filesystem::path path;
        std::string           modalityHint;
    };

    // Strategy Pattern – transformation from RawFile → DataFrame
    class ITransformationStrategy
    {
    public:
        virtual ~ITransformationStrategy() noexcept = default;
        virtual DataFrame transform(const RawFile&) = 0;
    };

    using TransformationStrategyPtr = std::shared_ptr<ITransformationStrategy>;

    // Registry that maps modality → strategy
    class TransformationRegistry
    {
    public:
        std::optional<TransformationStrategyPtr> findStrategy(std::string_view modality) const
        {
            std::shared_lock lock(mutex_);
            auto it = map_.find(std::string{modality});
            if (it == map_.end()) return std::nullopt;
            return it->second;
        }

        void registerStrategy(std::string modality, TransformationStrategyPtr strategy)
        {
            std::unique_lock lock(mutex_);
            map_.emplace(std::move(modality), std::move(strategy));
        }

    private:
        mutable std::shared_mutex                                                 mutex_;
        std::unordered_map<std::string, TransformationStrategyPtr> map_;
    };

    // Data-Lake façade
    class DataLakeWriter
    {
    public:
        virtual ~DataLakeWriter() noexcept = default;

        // Persist DataFrame at <root>/<modality>/<YYYY-MM-DD>/file.parquet
        virtual void write(const DataFrame& df,
                           const std::chrono::system_clock::time_point& timestamp) = 0;
    };

    // Observer Pattern interface for metrics
    class IProcessingObserver
    {
    public:
        virtual ~IProcessingObserver() noexcept = default;
        virtual void onBatchStart(std::string_view batchId, std::size_t nFiles)                     = 0;
        virtual void onFileProcessed(std::string_view batchId, const std::filesystem::path& file)   = 0;
        virtual void onBatchComplete(std::string_view batchId, std::size_t success, std::size_t fail)= 0;
    };
} // namespace ci360


// ---- Actual BatchProcessor Implementation ---------------------------------
namespace ci360::processing
{
    // Domain-specific exception type
    class BatchProcessingError : public std::runtime_error
    {
    public:
        using std::runtime_error::runtime_error;
    };

    // Describes an offline batch consisting of raw file paths and metadata.
    struct BatchRequest
    {
        std::string                     batchId;   // Unique identifier for audit trail
        std::vector<RawFile>            files;
        std::chrono::system_clock::time_point createdAt { std::chrono::system_clock::now() };
    };

    class BatchProcessor : public std::enable_shared_from_this<BatchProcessor>
    {
    public:
        struct Options
        {
            std::size_t                               maxConcurrency           = std::thread::hardware_concurrency();
            bool                                      enableMetrics            = true;
            std::chrono::milliseconds                 progressUpdateInterval   = std::chrono::milliseconds{2'000};
            std::chrono::milliseconds                 shutdownGracePeriod      = std::chrono::milliseconds{10'000};
        };

        BatchProcessor(std::shared_ptr<DataLakeWriter>          lakeWriter,
                       std::shared_ptr<TransformationRegistry>  registry,
                       std::shared_ptr<IProcessingObserver>     observer,
                       Options                                  opts = {})
            : lakeWriter_{std::move(lakeWriter)}
            , registry_{std::move(registry)}
            , observer_{std::move(observer)}
            , options_{opts}
        {
            if (!lakeWriter_ || !registry_)
                throw std::invalid_argument("BatchProcessor ctor: null dependency");

            workerThread_ = std::thread(&BatchProcessor::workerLoop, this);
            ci360_log::info("[BatchProcessor] Started worker thread with concurrency=", options_.maxConcurrency);
        }

        BatchProcessor(const BatchProcessor&) = delete;
        BatchProcessor& operator=(const BatchProcessor&) = delete;

        ~BatchProcessor()
        {
            shutdown();
        }

        // Equivalent to “fire-and-forget” – non-blocking
        void enqueueBatch(BatchRequest batch)
        {
            if (stopped_.load())
                throw std::runtime_error("BatchProcessor is shutting down");

            requestQueue_.push(std::move(batch));
        }

        // Blocks until queue is empty and all current jobs are finished
        void drain()
        {
            while (!requestQueue_.empty())
                std::this_thread::sleep_for(std::chrono::milliseconds{200});
        }

        // Initiates a graceful shutdown.  Multiple calls are idempotent.
        void shutdown()
        {
            bool expected = false;
            if (stopped_.compare_exchange_strong(expected, true))
            {
                ci360_log::info("[BatchProcessor] Shutting down …");
                if (workerThread_.joinable())
                    workerThread_.join();
            }
        }

    private:
        // Pulls BatchRequests from queue and processes them using TBB
        void workerLoop()
        {
            tbb::task_group tg;

            while (!stopped_.load() || !requestQueue_.empty())
            {
                BatchRequest req;
                if (requestQueue_.try_pop(req))
                {
                    // Capturing shared_ptr to keep this alive during async processing
                    auto self = shared_from_this();
                    tg.run([this, self, r = std::move(req)]() mutable
                    {
                        processBatch(std::move(r));
                    });

                    // Throttle the # of outstanding tasks
                    while (tg.is_canceling() == false &&
                           tg.is_idle()       == false &&
                           outstandingTasks_.load() >= options_.maxConcurrency)
                    {
                        std::this_thread::sleep_for(std::chrono::milliseconds{100});
                    }
                }
                else
                {
                    std::this_thread::sleep_for(std::chrono::milliseconds{100});
                }
            }

            // Wait for in-flight tasks
            tg.wait();
            ci360_log::info("[BatchProcessor] Worker loop terminated.");
        }

        void processBatch(BatchRequest batch)
        {
            const auto batchId  = batch.batchId;
            const auto nFiles   = batch.files.size();
            std::size_t success = 0;
            std::size_t failure = 0;

            observerSafe([&](auto o){ o->onBatchStart(batchId, nFiles); });
            ci360_log::info("[BatchProcessor][", batchId, "] Processing ", nFiles, " files");

            outstandingTasks_.fetch_add(1);

            auto finishGuard = gsl::finally([&]
            {
                observerSafe([&](auto o){ o->onBatchComplete(batchId, success, failure); });
                outstandingTasks_.fetch_sub(1);
            });

            for (const auto& raw : batch.files)
            {
                try
                {
                    auto df = transformFile(raw);
                    lakeWriter_->write(df, batch.createdAt);
                    success++;
                    observerSafe([&](auto o){ o->onFileProcessed(batchId, raw.path); });
                }
                catch (const std::exception& ex)
                {
                    ci360_log::error("[BatchProcessor][", batchId, "] Failed to process ",
                                     raw.path.string(), " – ", ex.what());
                    failure++;
                }
            }
        }

        DataFrame transformFile(const RawFile& raw)
        {
            auto strategyOpt = registry_->findStrategy(raw.modalityHint);
            if (!strategyOpt)
                throw BatchProcessingError("Unknown modality: " + raw.modalityHint);

            const auto& strategy = *strategyOpt;
            if (!strategy)
                throw BatchProcessingError("Transformation strategy is null for modality: "
                                           + raw.modalityHint);

            try
            {
                return strategy->transform(raw);
            }
            catch (const std::exception& ex)
            {
                throw BatchProcessingError(std::string{"Strategy error: "} + ex.what());
            }
        }

        // Helper that checks observer_ before calling
        template <typename Fn>
        void observerSafe(Fn&& fn)
        {
            if (observer_ && options_.enableMetrics)
            {
                try
                {
                    fn(observer_);
                }
                catch (const std::exception& ex)
                {
                    ci360_log::warn("[BatchProcessor] Observer callback failed: ", ex.what());
                }
            }
        }

    private:
        std::shared_ptr<DataLakeWriter>         lakeWriter_;
        std::shared_ptr<TransformationRegistry> registry_;
        std::shared_ptr<IProcessingObserver>    observer_;

        Options                                 options_;

        tbb::concurrent_queue<BatchRequest>     requestQueue_;
        std::atomic_bool                        stopped_{false};
        std::atomic<std::size_t>                outstandingTasks_{0};

        std::thread                             workerThread_;
    };
} // namespace ci360::processing
```
