/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * File: cardio_insight_360/src/services/alerting_service.cpp
 *
 * Description:
 *  A real-time alerting service that listens to curated, validated physiological
 *  signal streams, evaluates them against configurable rule sets, and emits
 *  actionable alerts to downstream consumers (nurse stations, dashboards, etc.).
 *
 *  The implementation uses:
 *   – Apache Kafka C++ client (librdkafka) for low-latency pub/sub
 *   – nlohmann::json for configuration and message envelopes
 *   – spdlog for structured, asynchronous logging
 *
 *  Thread-safety, RAII, and strong exception guarantees are observed throughout.
 *  The service can be started and stopped programmatically, making it suitable
 *  for embedding in the monolithic CI360 binary as a logically separated service
 *  (the so-called “pseudo-microservice” approach).
 *
 *  Copyright (c) 2024 CardioInsight360
 */

#include <atomic>
#include <chrono>
#include <csignal>
#include <functional>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <rdkafka/rdkafkacpp.h>

namespace ci360::services {

/* ---------- Utility Types ------------------------------------------------ */

enum class Severity : uint8_t
{
    Info,
    Warning,
    Critical
};

/* Fully-qualified alert message routed to nurse stations, etc. */
struct AlertMessage
{
    std::string patient_id;
    std::string rule_id;          // Identifier of the rule that triggered
    Severity    severity;
    std::string description;
    std::string timestamp_utc;    // ISO-8601
};

/* Callback signature for clients that wish to observe alerts. */
using AlertCallback = std::function<void(const AlertMessage&)>;

/* ---------- Alerting Service -------------------------------------------- */

class AlertingService final
{
public:
    explicit AlertingService(const nlohmann::json& config);
    ~AlertingService();

    AlertingService(const AlertingService&)            = delete;
    AlertingService& operator=(const AlertingService&) = delete;

    void start();
    void stop();

    /* Register an in-process observer. Thread-safe. */
    void registerObserver(AlertCallback cb);

private:
    /* -------------------- Rule Engine Internals ------------------------- */

    struct ThresholdRule
    {
        std::string  id;
        double       lower_bound;   // inclusive
        double       upper_bound;   // inclusive
        Severity     severity;      // default severity on violation
        std::string  description;
    };

    /* Parse configuration section “rules” into an in-memory map. */
    void loadRules(const nlohmann::json& config);

    /* Evaluate one numeric value against thresholds. */
    std::optional<AlertMessage>
    evaluate(const std::string& patient_id,
             const std::string& signal_id,
             double            value,
             const std::string& iso_ts) const;

    /* -------------------- Kafka Internals ------------------------------ */

    bool initKafka(const nlohmann::json& kafkaCfg);
    void processLoop(); /* Blocking loop executed on worker_ thread. */

    /* Emit alert both to Kafka “alerts” topic and to in-process observers. */
    void emitAlert(const AlertMessage& alert);

private:
    /* Kafka handles managed via smart pointers for RAII safety. */
    std::unique_ptr<RdKafka::KafkaConsumer> consumer_;
    std::unique_ptr<RdKafka::Producer>      producer_;

    std::string                              input_topic_;
    std::string                              output_topic_;

    /* Domain rules: signal_id −> rule. */
    std::unordered_map<std::string, ThresholdRule> rules_;

    /* Concurrency primitives. */
    std::vector<AlertCallback>        observers_;
    mutable std::shared_mutex         observers_mtx_;

    std::atomic_bool                  running_{false};
    std::thread                       worker_;

    /* Logger handle shared across service. */
    std::shared_ptr<spdlog::logger>   log_;
};

/* ======================================================================== */
/*                            IMPLEMENTATION                                */
/* ======================================================================== */

namespace {

/* Convert Severity enum to string for logging or serialization. */
std::string to_string(Severity s)
{
    switch (s)
    {
    case Severity::Info:     return "INFO";
    case Severity::Warning:  return "WARNING";
    case Severity::Critical: return "CRITICAL";
    }
    return "UNKNOWN";
}

/* Make ISO-8601 timestamp for “now”. */
std::string iso8601_now()
{
    using namespace std::chrono;
    auto now   = system_clock::now();
    auto itt   = system_clock::to_time_t(now);
    auto tm    = *std::gmtime(&itt);
    char buf[32];
    strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return buf;
}

} // anonymous namespace

/* -------------------- ctor / dtor --------------------------------------- */

AlertingService::AlertingService(const nlohmann::json& config)
{
    /* Configure structured console logger (colorized). */
    log_ = spdlog::stdout_color_mt("AlertingService");
    log_->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");

    try
    {
        loadRules(config.at("rules"));
        if (!initKafka(config.at("kafka")))
        {
            throw std::runtime_error("Failed to initialize Kafka subsystem");
        }
    }
    catch (const std::exception& ex)
    {
        log_->critical("Configuration error: {}", ex.what());
        throw; // propagate — service cannot run without valid config
    }
}

AlertingService::~AlertingService()
{
    stop(); /* Ensure worker is stopped before destruction. */
}

/* -------------------- Public API ---------------------------------------- */

void AlertingService::start()
{
    if (running_.exchange(true))
    {
        log_->warn("Attempt to start AlertingService while already running");
        return;
    }
    log_->info("Starting AlertingService worker thread");
    worker_ = std::thread(&AlertingService::processLoop, this);
}

void AlertingService::stop()
{
    if (!running_.exchange(false))
        return; // not running

    log_->info("Stopping AlertingService …");
    if (worker_.joinable())
        worker_.join();

    if (consumer_)
        consumer_->close();

    /* Flush outstanding alerts before exit (up to 5 seconds). */
    if (producer_)
        producer_->flush(5'000);

    log_->info("AlertingService cleanly stopped");
}

void AlertingService::registerObserver(AlertCallback cb)
{
    if (!cb) return;
    std::unique_lock lock(observers_mtx_);
    observers_.push_back(std::move(cb));
}

/* -------------------- Configuration Helpers ----------------------------- */

void AlertingService::loadRules(const nlohmann::json& rulesCfg)
{
    if (!rulesCfg.is_array())
        throw std::invalid_argument("config.rules must be array");

    for (const auto& j : rulesCfg)
    {
        ThresholdRule rule;
        rule.id          = j.at("id").get<std::string>();
        rule.lower_bound = j.value("lower", std::numeric_limits<double>::lowest());
        rule.upper_bound = j.value("upper", std::numeric_limits<double>::max());
        rule.severity    = static_cast<Severity>(j.value("severity", 1)); // default Warning
        rule.description = j.value("description", "");

        auto signal_id   = j.at("signal_id").get<std::string>();
        rules_.emplace(signal_id, std::move(rule));
    }

    log_->info("Loaded {} threshold rules", rules_.size());
}

/* -------------------- Kafka Setup --------------------------------------- */

bool AlertingService::initKafka(const nlohmann::json& kafkaCfg)
{
    std::string brokers       = kafkaCfg.value("brokers",  "localhost:9092");
    input_topic_              = kafkaCfg.value("input_topic",  "ci360.clinical.signals");
    output_topic_             = kafkaCfg.value("output_topic", "ci360.alerts");

    /* Consumer configuration. */
    std::unique_ptr<RdKafka::Conf, std::function<void(RdKafka::Conf*)>>
        conf(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL),
             [](RdKafka::Conf* p){ delete p; });

    if (!conf)
    {
        log_->error("Failed to allocate Kafka global config");
        return false;
    }

    std::string errstr;
    conf->set("bootstrap.servers", brokers, errstr);
    conf->set("group.id",          "ci360_alerting", errstr);
    conf->set("enable.auto.commit","true",           errstr);
    conf->set("auto.offset.reset", "earliest",       errstr);

    consumer_.reset(RdKafka::KafkaConsumer::create(conf.get(), errstr));
    if (!consumer_)
    {
        log_->error("KafkaConsumer creation failed: {}", errstr);
        return false;
    }

    /* Producer configuration. */
    std::unique_ptr<RdKafka::Conf, std::function<void(RdKafka::Conf*)>>
        prodConf(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL),
                 [](RdKafka::Conf* p){ delete p; });

    prodConf->set("bootstrap.servers", brokers, errstr);
    producer_.reset(RdKafka::Producer::create(prodConf.get(), errstr));
    if (!producer_)
    {
        log_->error("KafkaProducer creation failed: {}", errstr);
        return false;
    }

    /* Subscribe to the input topic. */
    RdKafka::ErrorCode rc = consumer_->subscribe({input_topic_});
    if (rc != RdKafka::ERR_NO_ERROR)
    {
        log_->error("Failed to subscribe to {}: {}", input_topic_, RdKafka::err2str(rc));
        return false;
    }

    log_->info("Kafka initialized: listening on '{}', producing to '{}'", input_topic_, output_topic_);
    return true;
}

/* -------------------- Processing Loop ----------------------------------- */

void AlertingService::processLoop()
{
    const int POLL_TIMEOUT_MS = 500;

    while (running_)
    {
        std::unique_ptr<RdKafka::Message, std::function<void(RdKafka::Message*)>>
            msg(consumer_->consume(POLL_TIMEOUT_MS), [](RdKafka::Message* m){ delete m; });

        if (!msg) continue;

        switch (msg->err())
        {
        case RdKafka::ERR_NO_ERROR:
        {
            /* Parse JSON payload. Example message:
             * { "patient_id":"1234",
             *   "signal_id":"ECG_HR",
             *   "value":95.0,
             *   "ts":"2024-03-05T10:35:00Z" }
             */
            try
            {
                nlohmann::json payload = nlohmann::json::parse(
                    static_cast<const char*>(msg->payload()),
                    static_cast<const char*>(msg->payload()) + msg->len());

                std::string patient_id = payload.at("patient_id").get<std::string>();
                std::string signal_id  = payload.at("signal_id").get<std::string>();
                double      value      = payload.at("value").get<double>();
                std::string ts         = payload.value("ts", iso8601_now());

                if (auto alertOpt = evaluate(patient_id, signal_id, value, ts))
                {
                    emitAlert(*alertOpt);
                }
            }
            catch (const std::exception& ex)
            {
                log_->error("Failed to process message: {}", ex.what());
            }
            break;
        }
        case RdKafka::ERR__TIMED_OUT:
            /* Normal — no message within timeout. */
            break;
        default:
            log_->warn("Kafka consume error: {}", msg->errstr());
            break;
        }
    }
}

/* -------------------- Rule Evaluation ----------------------------------- */

std::optional<AlertMessage>
AlertingService::evaluate(const std::string& patient_id,
                          const std::string& signal_id,
                          double            value,
                          const std::string& iso_ts) const
{
    auto it = rules_.find(signal_id);
    if (it == rules_.end())
        return std::nullopt; // No rule for this signal

    const ThresholdRule& rule = it->second;
    if (value < rule.lower_bound || value > rule.upper_bound)
    {
        AlertMessage alert;
        alert.patient_id  = patient_id;
        alert.rule_id     = rule.id;
        alert.severity    = rule.severity;
        alert.description = rule.description.empty()
                                ? "Threshold violation on " + signal_id
                                : rule.description;
        alert.timestamp_utc = iso_ts;
        return alert;
    }
    return std::nullopt;
}

/* -------------------- Alert Propagation --------------------------------- */

void AlertingService::emitAlert(const AlertMessage& alert)
{
    /* Serialize to JSON for Kafka. */
    nlohmann::json j{
        {"patient_id", alert.patient_id},
        {"rule_id",    alert.rule_id},
        {"severity",   to_string(alert.severity)},
        {"description",alert.description},
        {"ts",         alert.timestamp_utc}
    };

    std::string payload = j.dump();

    RdKafka::ErrorCode rc = producer_->produce(
        output_topic_, RdKafka::Topic::PARTITION_UA,
        RdKafka::Producer::RK_MSG_COPY /* Copy payload */,
        const_cast<char*>(payload.data()), payload.size(),
        nullptr, 0, 0, nullptr);

    if (rc != RdKafka::ERR_NO_ERROR)
    {
        log_->error("Failed to enqueue alert for patient {}: {}",
                    alert.patient_id, RdKafka::err2str(rc));
    }
    else
    {
        log_->info("Alert emitted for patient {} (severity {})",
                   alert.patient_id, to_string(alert.severity));
    }

    /* Flush producer queue in background thread. */
    producer_->poll(0);

    /* Notify in-process observers. */
    std::shared_lock lock(observers_mtx_);
    for (const auto& cb : observers_)
    {
        try
        {
            cb(alert);
        }
        catch (const std::exception& ex)
        {
            log_->warn("Observer callback threw: {}", ex.what());
        }
    }
}

} // namespace ci360::services

/* ====================== Graceful Shutdown Handler ======================== */
/* The following allows Ctrl-C graceful stop when run as standalone.        */

#ifdef CI360_ALERTING_SERVICE_STANDALONE

#include <iostream>

/* Simple entry point to exercise the service without the entire CI360 stack.
 * Requires a minimal JSON configuration file passed as argv[1].
 */
int main(int argc, char* argv[])
{
    if (argc < 2)
    {
        std::cerr << "Usage: alerting_service <config.json>\n";
        return EXIT_FAILURE;
    }

    try
    {
        nlohmann::json cfg = nlohmann::json::parse(std::ifstream(argv[1]));

        ci360::services::AlertingService svc(cfg);

        /* Example observer that just prints alerts. */
        svc.registerObserver([](const ci360::services::AlertMessage& a){
            spdlog::info("[OBSERVER] Patient {} – {}",
                         a.patient_id, a.description);
        });

        svc.start();

        std::signal(SIGINT, [](int){ spdlog::info("SIGINT received"); });
        std::signal(SIGTERM,[](int){ spdlog::info("SIGTERM received"); });

        /* Run until killed. */
        while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("Fatal: {}", ex.what());
        return EXIT_FAILURE;
    }
}

#endif  /* CI360_ALERTING_SERVICE_STANDALONE */
