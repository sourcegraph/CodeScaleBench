```cpp
/**
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *  Module      : src/processing/etl_pipeline.cpp
 *  Description : Parallel ETL pipeline implementation that ingests raw HL7/FHIR
 *                messages from Kafka, applies configurable transformation and
 *                data-quality strategies, and stores curated records into the
 *                Data-Lake façade.  Real-time pipeline metrics are published to
 *                the monitoring subsystem via the Observer pattern.
 *
 *  Build Note  : The file is self-contained except for external runtime
 *                libraries (librdkafka, Intel TBB).  When those are not
 *                available, compile with -DCI360_STUB_EXTERNAL to build the
 *                lightweight stubs provided below.
 *
 *  Author      : CardioInsight360 Engineering
 *  Copyright   : © CardioInsight360 LLC
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

// -----------------------------------------------------------------------------
// Optional third-party dependencies
// -----------------------------------------------------------------------------
#ifndef CI360_STUB_EXTERNAL
    #include <librdkafka/rdkafka.h>
    #include <tbb/flow_graph.h>
#else
    // ──────────────────────────────────────────────────────────────────────────
    // Minimal stub replacements for CI360_STUB_EXTERNAL build.
    // ──────────────────────────────────────────────────────────────────────────
    namespace tbb
    {
    namespace flow
    {
        struct graph
        {
            void wait_for_all() {}
        };

        template <typename T>
        class function_node
        {
        public:
            using output_type = T;
            template <typename F>
            function_node(graph&, std::size_t /*concurrency*/, F&& f)
                : fn_(std::forward<F>(f))
            {
            }
            void try_put(const output_type& v) { fn_(v); }
            void try_put(output_type&& v) { fn_(std::move(v)); }

        private:
            std::function<void(output_type)> fn_;
        };
    } // namespace flow
    } // namespace tbb

    using rd_kafka_t               = struct rd_kafka_s;
    using rd_kafka_conf_t          = struct rd_kafka_conf_s;
    using rd_kafka_message_t       = struct rd_kafka_message_s;
    using rd_kafka_topic_partition_list_t = struct rd_kafka_topic_partition_list_s;

    // Tiny stub implementations
    static inline const char* rd_kafka_err2str(int) { return "STUB_KAFKA"; }
    static inline rd_kafka_conf_t* rd_kafka_conf_new() { return nullptr; }
    static inline rd_kafka_t* rd_kafka_new(int /*type*/, rd_kafka_conf_t*, char*, size_t) { return nullptr; }
    static inline void rd_kafka_destroy(rd_kafka_t*) {}
    static inline int rd_kafka_poll(rd_kafka_t*, int) { std::this_thread::sleep_for(std::chrono::milliseconds(10)); return 0; }
    static inline rd_kafka_message_t* rd_kafka_consumer_poll(rd_kafka_t*, int) { return nullptr; }
    static inline void rd_kafka_message_destroy(rd_kafka_message_t*) {}
#endif // CI360_STUB_EXTERNAL

// -----------------------------------------------------------------------------
// Namespace hierarchy for the CardioInsight360 project
// -----------------------------------------------------------------------------
namespace ci360::processing {

// -----------------------------------------------------------------------------
// Domain model
// -----------------------------------------------------------------------------
struct PatientDataRecord
{
    std::string                                patient_id;
    std::chrono::system_clock::time_point      timestamp;
    std::unordered_map<std::string, double>    vitals;     // ECG, BP, SpO₂ etc.
};

// Convenience pretty printer (debug only)
inline std::ostream& operator<<(std::ostream& os, const PatientDataRecord& rec)
{
    auto ts = std::chrono::system_clock::to_time_t(rec.timestamp);
    os << "PatientDataRecord{patient_id=" << rec.patient_id << ", ts="
       << std::put_time(std::gmtime(&ts), "%F %T") << ", vitals=[";
    for (auto it = rec.vitals.begin(); it != rec.vitals.end(); ++it)
    {
        os << it->first << '=' << it->second;
        if (std::next(it) != rec.vitals.end()) os << ", ";
    }
    os << "]}";
    return os;
}

// -----------------------------------------------------------------------------
// Strategy Interfaces
// -----------------------------------------------------------------------------
class IDataExtractor
{
public:
    virtual ~IDataExtractor() = default;
    virtual bool extract(std::vector<PatientDataRecord>& outBatch) = 0; // returns false on end-of-stream
};

class IDataTransformer
{
public:
    virtual ~IDataTransformer() = default;
    virtual void transform(std::vector<PatientDataRecord>& batch) = 0;
};

class IDataValidator
{
public:
    virtual ~IDataValidator() = default;
    virtual bool validate(const std::vector<PatientDataRecord>& batch,
                          std::string&                          reason) = 0;
};

class IDataLoader
{
public:
    virtual ~IDataLoader() = default;
    virtual void load(const std::vector<PatientDataRecord>& batch) = 0;
};

// -----------------------------------------------------------------------------
// Observer Interface for Metrics
// -----------------------------------------------------------------------------
struct PipelineMetrics
{
    std::uint64_t records_processed = 0;
    std::uint64_t batches_success   = 0;
    std::uint64_t batches_failed    = 0;
};

class IMetricsObserver
{
public:
    virtual ~IMetricsObserver() = default;
    virtual void onMetrics(const PipelineMetrics& metrics) = 0;
};

// -----------------------------------------------------------------------------
// Config object
// -----------------------------------------------------------------------------
struct ETLConfig
{
    std::size_t  transformer_concurrency = std::thread::hardware_concurrency();
    std::size_t  batch_size              = 512;
    std::chrono::milliseconds poll_timeout{100};
};

// -----------------------------------------------------------------------------
// Concrete Strategy Implementations
// -----------------------------------------------------------------------------
class HL7KafkaExtractor final : public IDataExtractor
{
public:
    explicit HL7KafkaExtractor(const std::string& brokers,
                               const std::string& topic,
                               const ETLConfig&  cfg)
        : cfg_{cfg}
    {
#ifndef CI360_STUB_EXTERNAL
        char errstr[512];
        auto* rdconf = rd_kafka_conf_new();
        rd_kafka_conf_set(rdconf, "metadata.broker.list", brokers.c_str(), errstr, sizeof(errstr));
        // Enable auto commit etc. (omitted for brevity)

        kafka_.reset(
            rd_kafka_new(RD_KAFKA_CONSUMER, rdconf, errstr, sizeof(errstr)),
            [](rd_kafka_t* k) { rd_kafka_destroy(k); });

        if (!kafka_)
        {
            throw std::runtime_error("rd_kafka_new failed: " + std::string(errstr));
        }

        // More setup (topic subscription, rebalance cb etc.)
        // rd_kafka_subscribe(kafka_.get(), ...)
#endif
        (void)topic; // avoid unused-variable in stub build
    }

    bool extract(std::vector<PatientDataRecord>& outBatch) override
    {
        outBatch.clear();
        outBatch.reserve(cfg_.batch_size);

#ifndef CI360_STUB_EXTERNAL
        while (outBatch.size() < cfg_.batch_size)
        {
            if (auto* msg = rd_kafka_consumer_poll(kafka_.get(),
                                                   static_cast<int>(cfg_.poll_timeout.count())))
            {
                if (msg->err)
                {
                    if (msg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF)
                    {
                        rd_kafka_message_destroy(msg);
                        return false; // End-of-partition, treat as EOS for demo
                    }
                    rd_kafka_message_destroy(msg);
                    continue;
                }

                // Parse HL7 bytes in msg->payload into domain model
                outBatch.emplace_back(mockRecord()); // Placeholder parsing
                rd_kafka_message_destroy(msg);
            }
            else
            {
                break; // poll timeout, yield to pipeline
            }
        }
#else
        // Stubbed random batch
        std::this_thread::sleep_for(cfg_.poll_timeout);
        for (std::size_t i = 0; i < cfg_.batch_size; ++i)
        {
            outBatch.emplace_back(mockRecord());
        }
#endif
        return !outBatch.empty();
    }

private:
    PatientDataRecord mockRecord()
    {
        static std::uint64_t id = 0;
        return {
            "P" + std::to_string(++id),
            std::chrono::system_clock::now(),
            {{"ECG_HR",     60.0 + (id % 5)},
             {"BP_SYS",    120.0 + (id % 3)},
             {"SpO2",       98.0}}
        };
    }

    ETLConfig cfg_;
#ifndef CI360_STUB_EXTERNAL
    std::unique_ptr<rd_kafka_t, void (*)(rd_kafka_t*)> kafka_{nullptr, nullptr};
#endif
};

class ECGTransformer final : public IDataTransformer
{
public:
    void transform(std::vector<PatientDataRecord>& batch) override
    {
        for (auto& rec : batch)
        {
            // Example: add derived field "ECG_RR_INT"
            auto hrIter = rec.vitals.find("ECG_HR");
            if (hrIter != rec.vitals.end() && hrIter->second > 0)
            {
                rec.vitals["ECG_RR_INT"] = 60'000.0 / hrIter->second; // ms
            }
        }
    }
};

class VitalSignsValidator final : public IDataValidator
{
public:
    bool validate(const std::vector<PatientDataRecord>& batch,
                  std::string& reason) override
    {
        for (const auto& rec : batch)
        {
            const auto& vitals = rec.vitals;
            if (auto it = vitals.find("ECG_HR"); it != vitals.end())
            {
                if (it->second < 20 || it->second > 250)
                {
                    reason = "ECG_HR out of range";
                    return false;
                }
            }
        }
        return true;
    }
};

class ParquetLoader final : public IDataLoader
{
public:
    explicit ParquetLoader(std::string outputDir)
        : outputDir_{std::move(outputDir)}
    {}

    void load(const std::vector<PatientDataRecord>& batch) override
    {
        // Production build would leverage Apache Arrow / Parquet writer API.
        // For now, we simply serialize each batch as JSON lines.
        const auto timestamp = std::chrono::system_clock::to_time_t(
            std::chrono::system_clock::now());
        std::ostringstream filePath;
        filePath << outputDir_ << "/ci360_batch_" << timestamp << ".json";

        std::ofstream ofs(filePath.str());
        if (!ofs.is_open())
        {
            throw std::runtime_error("Failed to open output file: " + filePath.str());
        }
        for (const auto& rec : batch)
        {
            ofs << toJson(rec) << '\n';
        }
    }

private:
    static std::string toJson(const PatientDataRecord& rec)
    {
        std::ostringstream os;
        os << "{\"patient_id\":\"" << rec.patient_id << "\",\"vitals\":{";
        for (auto it = rec.vitals.begin(); it != rec.vitals.end(); ++it)
        {
            os << '"' << it->first << "\":" << it->second;
            if (std::next(it) != rec.vitals.end()) os << ',';
        }
        os << "}}";
        return os.str();
    }

    std::string outputDir_;
};

// -----------------------------------------------------------------------------
// ETL Pipeline Orchestrator
// -----------------------------------------------------------------------------
class ETLPipeline : public std::enable_shared_from_this<ETLPipeline>
{
public:
    ETLPipeline(std::unique_ptr<IDataExtractor>  extractor,
                std::unique_ptr<IDataTransformer> transformer,
                std::unique_ptr<IDataValidator>   validator,
                std::unique_ptr<IDataLoader>      loader,
                const ETLConfig&                  config)
        : extractor_{std::move(extractor)}
        , transformer_{std::move(transformer)}
        , validator_{std::move(validator)}
        , loader_{std::move(loader)}
        , cfg_{config}
    {}

    ~ETLPipeline() { stop(); }

    void addObserver(std::weak_ptr<IMetricsObserver> obs)
    {
        std::lock_guard<std::mutex> lg(obsMtx_);
        observers_.push_back(std::move(obs));
    }

    void start()
    {
        if (running_.exchange(true))
            return; // already running

        worker_ = std::thread([self = shared_from_this()] { self->runLoop(); });
    }

    void stop()
    {
        if (!running_.exchange(false))
            return;

        if (worker_.joinable()) worker_.join();
    }

private:
    void runLoop()
    {
        tbb::flow::graph g;

        using Batch = std::vector<PatientDataRecord>;

        tbb::flow::function_node<Batch> transformNode(
            g,
            cfg_.transformer_concurrency,
            [this](Batch batch) {
                transformer_->transform(batch);
                std::string reason;
                if (!validator_->validate(batch, reason))
                {
                    metrics_.batches_failed++;
                    notify();
                    return; // drop invalid batch
                }
                loader_->load(batch);
                metrics_.records_processed += batch.size();
                metrics_.batches_success++;
                notify();
            });

        while (running_)
        {
            Batch batch;
            if (!extractor_->extract(batch))
            {
                // End-of-stream: drain graph then break
                running_ = false;
                break;
            }
            transformNode.try_put(std::move(batch));
        }

        g.wait_for_all();
    }

    void notify()
    {
        std::lock_guard<std::mutex> lg(obsMtx_);
        for (auto it = observers_.begin(); it != observers_.end();)
        {
            if (auto obs = it->lock())
            {
                obs->onMetrics(metrics_);
                ++it;
            }
            else
            {
                it = observers_.erase(it); // remove expired
            }
        }
    }

    // Members
    std::unique_ptr<IDataExtractor>   extractor_;
    std::unique_ptr<IDataTransformer> transformer_;
    std::unique_ptr<IDataValidator>   validator_;
    std::unique_ptr<IDataLoader>      loader_;
    ETLConfig                         cfg_;

    std::atomic_bool                  running_{false};
    std::thread                       worker_;

    PipelineMetrics                   metrics_;
    std::mutex                        obsMtx_;
    std::vector<std::weak_ptr<IMetricsObserver>> observers_;
};

// -----------------------------------------------------------------------------
// Example Metrics Observer (prints to std::cout)
// -----------------------------------------------------------------------------
class ConsoleMetricsObserver final : public IMetricsObserver
{
public:
    void onMetrics(const PipelineMetrics& m) override
    {
        std::cout << "[METRICS] records=" << m.records_processed
                  << " batches_ok=" << m.batches_success
                  << " batches_failed=" << m.batches_failed << '\n';
    }
};

// -----------------------------------------------------------------------------
// Factory Helper
// -----------------------------------------------------------------------------
inline std::shared_ptr<ETLPipeline> makeDefaultETLPipeline()
{
    ETLConfig cfg;
    cfg.batch_size = 256;

    auto extractor  = std::make_unique<HL7KafkaExtractor>("localhost:9092", "HL7", cfg);
    auto transformer= std::make_unique<ECGTransformer>();
    auto validator  = std::make_unique<VitalSignsValidator>();
    auto loader     = std::make_unique<ParquetLoader>("./data_lake/curated");

    auto pipeline   = std::make_shared<ETLPipeline>(std::move(extractor),
                                                   std::move(transformer),
                                                   std::move(validator),
                                                   std::move(loader),
                                                   cfg);
    return pipeline;
}

// -----------------------------------------------------------------------------
// Main (only for local testing; not linked in production builds)
// -----------------------------------------------------------------------------
#ifdef CI360_ETL_MAIN
int main()
{
    auto pipeline = makeDefaultETLPipeline();
    auto consoleObs = std::make_shared<ConsoleMetricsObserver>();
    pipeline->addObserver(consoleObs);
    pipeline->start();

    std::this_thread::sleep_for(std::chrono::seconds(5));
    pipeline->stop();
    return 0;
}
#endif

} // namespace ci360::processing
```