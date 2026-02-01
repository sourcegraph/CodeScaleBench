#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

// External dependencies
#include <nlohmann/json.hpp>                 // MIT-licensed JSON library
#include <rdkafka/rdkafkacpp.h>              // Apache Kafka C/C++ client
#include <tbb/concurrent_queue.h>
#include <tbb/task_group.h>

namespace cardio::processing {

/********************************************************************
 *  Utility helpers
 ********************************************************************/

namespace detail {
inline std::string nowUtcIso8601()
{
    auto now        = std::chrono::system_clock::now();
    auto secs       = std::chrono::time_point_cast<std::chrono::seconds>(now);
    auto micros     = std::chrono::duration_cast<std::chrono::microseconds>(now - secs);
    std::time_t tt  = std::chrono::system_clock::to_time_t(now);

    std::tm tm{};
#ifdef _MSC_VER
    gmtime_s(&tm, &tt);
#else
    gmtime_r(&tt, &tm);
#endif
    std::ostringstream oss;
    oss << std::put_time(&tm, "%FT%T") << "." << std::setw(6) << std::setfill('0') << micros.count() << "Z";
    return oss.str();
}
} // namespace detail

/********************************************************************
 *  Domain contracts
 ********************************************************************/

struct KafkaConfig
{
    std::string brokers          = "localhost:9092";
    std::string groupId          = "cardioinsight-default";
    std::string inputTopic       = "raw-signals";
    std::string outputTopic      = "transformed-signals";
    // Optional security settings (SASL/SSL)
    std::string securityProtocol = "";
    std::string saslMechanisms   = "";
    std::string saslUsername     = "";
    std::string saslPassword     = "";
};

class MetricsSink
{
public:
    virtual ~MetricsSink()                                   = default;
    virtual void recordMetric(const std::string& name,
                              double              value)     = 0;
};

/********************************************************************
 *  Transformation Strategy Pattern
 ********************************************************************/

class TransformationStrategy
{
public:
    virtual ~TransformationStrategy()                                                    = default;
    virtual std::string                                   name() const                  = 0;
    virtual nlohmann::json                                transform(const nlohmann::json& in) = 0;
    virtual bool                                          supports(const std::string& signalType) const = 0;
};

/********************************************************************
 *  Example concrete strategies
 *  In real project these would live in dedicated translation units.
 ********************************************************************/

class ECGTransformer : public TransformationStrategy
{
public:
    std::string name() const override { return "ECGTransformer"; }

    bool supports(const std::string& signalType) const override
    {
        return signalType == "ECG";
    }

    nlohmann::json transform(const nlohmann::json& in) override
    {
        auto out            = in;
        out["processing"]   = {{"algorithm", "QRS-detector"}, {"version", "1.2.4"}};
        // Pretend we run actual ECG signal processing...
        std::this_thread::sleep_for(std::chrono::milliseconds(3));
        return out;
    }
};

class BPTransformer : public TransformationStrategy
{
public:
    std::string name() const override { return "BPTransformer"; }

    bool supports(const std::string& signalType) const override
    {
        return signalType == "BP";
    }

    nlohmann::json transform(const nlohmann::json& in) override
    {
        auto out          = in;
        out["processing"] = {{"algorithm", "MAP-calculator"}, {"version", "0.9.1"}};
        // Simulate compute
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        return out;
    }
};

/********************************************************************
 *  StreamProcessor – orchestrates continuous ingestion / transformation
 ********************************************************************/

class StreamProcessor
{
public:
    explicit StreamProcessor(KafkaConfig config,
                             std::size_t parallelism = std::thread::hardware_concurrency());
    ~StreamProcessor();

    StreamProcessor(StreamProcessor const&)            = delete;
    StreamProcessor& operator=(StreamProcessor const&) = delete;

    void start();
    void stop();
    void wait();

    void registerStrategy(std::unique_ptr<TransformationStrategy> strat);
    void registerMetricsSink(std::shared_ptr<MetricsSink> sink);

private:
    using Json      = nlohmann::json;
    using Clock     = std::chrono::steady_clock;
    using TimePoint = Clock::time_point;

    void consumeLoop();
    void asyncTransform(const std::string& payload,
                        const std::optional<std::string>& key);

    // Metrics helpers
    void emitMetric(const std::string& name, double value);

private:
    KafkaConfig                                       cfg_;
    std::unique_ptr<RdKafka::KafkaConsumer>           consumer_;
    std::unique_ptr<RdKafka::Producer>                producer_;

    // Concurrency
    std::atomic<bool>                                 running_{false};
    std::thread                                       worker_;

    tbb::task_group                                   taskGroup_;
    tbb::concurrent_queue<std::string>                deadLetterQueue_;
    const std::size_t                                 maxInFlight_;

    // Strategies & metrics
    std::mutex                                        stratMtx_;
    std::vector<std::unique_ptr<TransformationStrategy>> strategies_;

    std::mutex                                        metricsMtx_;
    std::vector<std::weak_ptr<MetricsSink>>           metricsSinks_;
};

/********************************************************************
 *  StreamProcessor implementation
 ********************************************************************/

namespace {

std::unique_ptr<RdKafka::Conf> buildKafkaConf(const KafkaConfig& cfg,
                                              const std::string&  confType)
{
    std::string errstr;
    std::unique_ptr<RdKafka::Conf> conf{RdKafka::Conf::create(confType.c_str())};

    auto set = [&](const std::string& key, const std::string& val) {
        if (val.empty()) return;
        if (conf->set(key, val, errstr) != RdKafka::Conf::CONF_OK) {
            throw std::runtime_error("Kafka config error [" + key + "]: " + errstr);
        }
    };

    set("bootstrap.servers", cfg.brokers);
    set("group.id", cfg.groupId);
    set("enable.auto.commit", "true");

    // Optional security (HIPAA)
    set("security.protocol", cfg.securityProtocol);
    set("sasl.mechanisms", cfg.saslMechanisms);
    set("sasl.username", cfg.saslUsername);
    set("sasl.password", cfg.saslPassword);

    return conf;
}

} // anonymous namespace

StreamProcessor::StreamProcessor(KafkaConfig config, std::size_t parallelism)
    : cfg_{std::move(config)}
    , maxInFlight_{parallelism == 0 ? 1 : parallelism}
{
    std::string errstr;

    auto consumerConf   = buildKafkaConf(cfg_, "consumer");
    consumerConf->set("auto.offset.reset", "latest", errstr);
    consumer_           = std::unique_ptr<RdKafka::KafkaConsumer>(
        RdKafka::KafkaConsumer::create(consumerConf.get(), errstr));
    if (!consumer_) throw std::runtime_error("Failed to create KafkaConsumer: " + errstr);

    auto producerConf   = buildKafkaConf(cfg_, "producer");
    producer_           = std::unique_ptr<RdKafka::Producer>(
        RdKafka::Producer::create(producerConf.get(), errstr));
    if (!producer_) throw std::runtime_error("Failed to create KafkaProducer: " + errstr);
}

StreamProcessor::~StreamProcessor()
{
    stop();
    wait();
}

void StreamProcessor::start()
{
    if (running_.exchange(true))
        return; // already running

    RdKafka::ErrorCode rc = consumer_->subscribe({cfg_.inputTopic});
    if (rc != RdKafka::ERR_NO_ERROR) {
        throw std::runtime_error("Failed to subscribe to topic '" + cfg_.inputTopic +
                                 "': " + RdKafka::err2str(rc));
    }

    worker_ = std::thread(&StreamProcessor::consumeLoop, this);
}

void StreamProcessor::stop()
{
    running_ = false;
}

void StreamProcessor::wait()
{
    if (worker_.joinable()) worker_.join();
    taskGroup_.wait();
}

void StreamProcessor::registerStrategy(std::unique_ptr<TransformationStrategy> strat)
{
    std::lock_guard<std::mutex> lk{stratMtx_};
    strategies_.emplace_back(std::move(strat));
}

void StreamProcessor::registerMetricsSink(std::shared_ptr<MetricsSink> sink)
{
    std::lock_guard<std::mutex> lk{metricsMtx_};
    metricsSinks_.emplace_back(std::move(sink));
}

void StreamProcessor::consumeLoop()
{
    while (running_) {
        std::unique_ptr<RdKafka::Message> msg{consumer_->consume(500)};
        if (!msg) continue;

        switch (msg->err()) {
        case RdKafka::ERR_NO_ERROR: {
            std::string payload{static_cast<const char*>(msg->payload()),
                                static_cast<std::size_t>(msg->len())};
            asyncTransform(payload, msg->key() ? std::optional<std::string>(*msg->key()) : std::nullopt);
            break;
        }
        case RdKafka::ERR__TIMED_OUT:
            // simply poll again
            break;
        default:
            std::cerr << "[StreamProcessor] Kafka error: " << msg->errstr() << "\n";
            break;
        }
    }
}

void StreamProcessor::asyncTransform(const std::string&               payload,
                                     const std::optional<std::string> key)
{
    taskGroup_.run([this, payload, key] {
        const auto start = Clock::now();
        try {
            Json in  = Json::parse(payload);
            auto it  = in.find("signal_type");
            if (it == in.end() || !it->is_string()) {
                throw std::runtime_error("Missing 'signal_type' field");
            }

            const std::string signalType = *it;

            std::unique_ptr<TransformationStrategy> *found = nullptr;
            {
                std::lock_guard<std::mutex> lk{stratMtx_};
                for (auto& strat : strategies_) {
                    if (strat->supports(signalType)) {
                        found = &strat;
                        break;
                    }
                }
            }

            if (!found) {
                throw std::runtime_error("No strategy for signal_type=" + signalType);
            }

            Json out         = (*found)->transform(in);
            out["timestamp"] = detail::nowUtcIso8601();

            std::string outPayload = out.dump();

            RdKafka::ErrorCode rc = producer_->produce(
                cfg_.outputTopic,
                RdKafka::Topic::PARTITION_UA,
                RdKafka::Producer::RK_MSG_COPY,
                const_cast<char*>(outPayload.data()),
                outPayload.size(),
                key ? &(*key) : nullptr,
                nullptr);

            if (rc != RdKafka::ERR_NO_ERROR) {
                throw std::runtime_error("Kafka produce failed: " + RdKafka::err2str(rc));
            }

            producer_->poll(0); // serve delivery cb

            const auto durMs =
                std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start).count();
            emitMetric("processing_latency_ms", static_cast<double>(durMs));
        }
        catch (const std::exception& ex) {
            std::cerr << "[StreamProcessor] Transformation error: " << ex.what() << "\n";
            deadLetterQueue_.push(payload);
            emitMetric("dead_letter_total", 1.0);
        }
    });
}

void StreamProcessor::emitMetric(const std::string& name, double value)
{
    std::lock_guard<std::mutex> lk{metricsMtx_};
    for (auto it = metricsSinks_.begin(); it != metricsSinks_.end();) {
        if (auto sink = it->lock()) {
            sink->recordMetric(name, value);
            ++it;
        }
        else {
            it = metricsSinks_.erase(it);
        }
    }
}

/********************************************************************
 *  Example console metrics sink
 ********************************************************************/

class ConsoleMetricsSink : public MetricsSink
{
public:
    void recordMetric(const std::string& name, double value) override
    {
        std::cout << "[Metrics] " << name << " = " << value << "\n";
    }
};

/********************************************************************
 *  Minimal integration test harness (optional)
 ********************************************************************/

#ifdef CARDIOINSIGHT360_STREAM_PROCESSOR_MAIN
int main()
{
    try {
        KafkaConfig cfg;
        cfg.brokers    = "localhost:9092";
        cfg.inputTopic = "raw-signals";
        cfg.outputTopic = "transformed-signals";

        StreamProcessor processor(cfg);
        processor.registerStrategy(std::make_unique<ECGTransformer>());
        processor.registerStrategy(std::make_unique<BPTransformer>());
        processor.registerMetricsSink(std::make_shared<ConsoleMetricsSink>());

        processor.start();

        // Simple shutdown handler
        std::signal(SIGINT, [](int) {
            std::cout << "SIGINT received, shutting down...\n";
            RdKafka::Producer::flush(5000);
            std::exit(0);
        });

        processor.wait();
    }
    catch (const std::exception& ex) {
        std::cerr << "Fatal: " << ex.what() << "\n";
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
#endif

} // namespace cardio::processing