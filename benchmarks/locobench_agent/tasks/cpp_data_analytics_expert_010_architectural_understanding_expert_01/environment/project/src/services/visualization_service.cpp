```cpp
/**************************************************************************************************
 *  File:    visualization_service.cpp
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Description:
 *      Implementation of VisualizationService.  The service is responsible for transforming data
 *      coming from ETL-pipelines and/or the in-process event-streaming bus into lightweight
 *      artifacts that can be consumed by the built-in web UI (Qt/WebGL front-end) or exported via
 *      the “pseudo-micro-services” façade for 3rd-party BI tools.
 *
 *  Key responsibilities:
 *      • Produce aggregate and atomic visualization payloads on-demand or continuously.
 *      • Interface with the event bus (Kafka/librdkafka) for near-real-time updates.
 *      • Leverage Data-Lake façade for historical back-fills (Apache Parquet).
 *      • Publish run-time metrics to the monitoring subsystem (Observer Pattern).
 *
 *  Copyright:
 *      © 2024 Acrux Analytics.  All rights reserved.
 **************************************************************************************************/

#include "visualization_service.hpp"

// Third-party
#include <nlohmann/json.hpp>
#include <tbb/concurrent_unordered_map.h>
#include <tbb/parallel_for.h>
#include <librdkafka/rdkafkacpp.h>

// STL
#include <chrono>
#include <filesystem>
#include <future>
#include <iomanip>
#include <mutex>
#include <optional>
#include <sstream>
#include <thread>
#include <utility>

using namespace std::chrono_literals;
using json = nlohmann::json;

namespace cardio::visualization
{
/*==================================================================================================
 *  Anonymous helpers
 *================================================================================================*/

namespace
{
    // Utility: Convert std::chrono::system_clock::time_point to ISO-8601 (UTC) string.
    std::string to_iso8601(std::chrono::system_clock::time_point tp)
    {
        std::time_t t = std::chrono::system_clock::to_time_t(tp);
        std::tm      tm_utc;
#ifdef _WIN32
        gmtime_s(&tm_utc, &t);
#else
        gmtime_r(&t, &tm_utc);
#endif
        std::ostringstream oss;
        oss << std::put_time(&tm_utc, "%Y-%m-%dT%H:%M:%SZ");
        return oss.str();
    }

    // Utility: Compose Kafka consumer configuration
    RdKafka::ConfPtr make_kafka_conf(const std::string& client_id)
    {
        RdKafka::ConfPtr conf(RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL));

        std::string err;
        conf->set("bootstrap.servers", "localhost:9092", err);
        conf->set("enable.auto.commit", "false", err);
        conf->set("group.id", "CardioInsight360.Visualization." + client_id, err);
        conf->set("auto.offset.reset", "latest", err);
        conf->set("security.protocol", "PLAINTEXT", err);    // Overridden by security module

        return conf;
    }
} // namespace

/*==================================================================================================
 *  PIMPL (Implementation details)
 *================================================================================================*/

class VisualizationService::Impl
{
public:
    Impl(std::shared_ptr<bus::EventBus>           bus,
         std::shared_ptr<persistence::DataLake>   lake,
         std::shared_ptr<metrics::Registry>       metrics)
        : m_bus(std::move(bus))
        , m_lake(std::move(lake))
        , m_metrics(std::move(metrics))
        , m_running(false)
    {
        if (!m_bus || !m_lake || !m_metrics)
        {
            throw std::invalid_argument(
                "VisualizationService ctor received null dependency pointer");
        }
    }

    ~Impl() { stop(); }

    void start()
    {
        if (m_running.exchange(true))
        {
            return; // Already running.
        }

        // Start real-time Kafka consumer
        m_consumer =
            std::shared_ptr<RdKafka::KafkaConsumer>(RdKafka::KafkaConsumer::create(
                make_kafka_conf("RealtimeConsumer").get(), m_error));
        if (!m_consumer)
        {
            throw std::runtime_error(
                "Failed to create KafkaConsumer: " + (m_error.empty() ? "unknown" : m_error));
        }

        // Subscribe to vital-sign topics
        std::vector<std::string> topics = {"ecg", "spo2", "bp"};
        auto err = m_consumer->subscribe(topics);
        if (err != RdKafka::ERR_NO_ERROR)
        {
            throw std::runtime_error("Kafka subscribe failed: " + RdKafka::err2str(err));
        }

        m_worker = std::jthread([this] { consumer_loop(); });
    }

    void stop()
    {
        if (!m_running.exchange(false))
        {
            return; // Not running
        }

        if (m_consumer)
        {
            m_consumer->close();
        }

        // join is automatic with std::jthread destructor
    }

    // ---------------------------------------------------------------------
    // ONE-SHOT HISTORICAL QUERY
    // ---------------------------------------------------------------------
    std::future<json> dispatch_historical(const VisualizationQuery& q)
    {
        return std::async(std::launch::async, [this, q]() { return historical_task(q); });
    }

    // ---------------------------------------------------------------------
    // REAL-TIME STREAM SUBSCRIPTION
    // ---------------------------------------------------------------------
    void subscribe(const VisualizationSubscription& sub)
    {
        std::lock_guard guard(m_sub_mutex);
        m_subscriptions[sub.id] = sub;

        // Allocate per-subscription metric counter
        auto counter = m_metrics->counter(
            "viz.realtime.active_subscriptions", {{"patient_id", sub.patient_id}});

        counter.increment();
    }

    void unsubscribe(const std::string& id)
    {
        std::lock_guard guard(m_sub_mutex);
        m_subscriptions.erase(id);
    }

private:
    // ---------------------------------------------------------------------------------------------
    //  Kafka consumer loop (real-time ingestion)
    // ---------------------------------------------------------------------------------------------
    void consumer_loop()
    {
        RdKafka::Message* msg = nullptr;
        while (m_running)
        {
            msg = m_consumer->consume(100 /*ms*/);

            if (!msg)
            {
                continue;
            }

            switch (msg->err())
            {
            case RdKafka::ERR_NO_ERROR:
                handle_message(msg);
                break;
            case RdKafka::ERR__TIMED_OUT:
                break; // benign
            default:
                m_metrics->counter("viz.kafka.error")->increment();
                break;
            }

            delete msg;
        }
    }

    // ---------------------------------------------------------------------------------------------
    //  Handle a single Kafka message
    // ---------------------------------------------------------------------------------------------
    void handle_message(const RdKafka::Message* msg)
    {
        try
        {
            auto now = std::chrono::system_clock::now();
            json payload = json::parse(static_cast<const char*>(msg->payload()), nullptr,
                                       /*allow_exceptions=*/false);
            if (payload.is_discarded())
            {
                m_metrics->counter("viz.kafka.invalid_json")->increment();
                return;
            }

            // Dispatch to interested subscriptions
            std::lock_guard guard(m_sub_mutex);
            for (auto& [id, sub] : m_subscriptions)
            {
                if (!sub.predicate(payload))
                    continue;

                sub.callback(payload);
            }

            m_metrics->counter("viz.kafka.events_processed")->increment();
        }
        catch (const std::exception& ex)
        {
            m_metrics
                ->counter("viz.kafka.message_exception", {{"what", ex.what()}})
                ->increment();
        }
    }

    // ---------------------------------------------------------------------------------------------
    //  HISTORICAL QUERY EXECUTION
    // ---------------------------------------------------------------------------------------------
    json historical_task(const VisualizationQuery& q)
    {
        using persistence::ParquetReader;

        metrics::Timer timer(m_metrics, "viz.historical.query_time");

        json out;
        out["patient_id"]  = q.patient_id;
        out["series_name"] = q.series_name;
        out["from"]        = to_iso8601(q.interval.first);
        out["to"]          = to_iso8601(q.interval.second);

        std::vector<ParquetReader::Row> rows;

        try
        {
            // DataLake path resolution
            std::filesystem::path path = m_lake->resolve(q.patient_id, q.series_name);

            ParquetReader reader(path);

            reader.filter_by_time(q.interval.first, q.interval.second);
            reader.read_rows(
                [&](ParquetReader::Row&& r)
                {
                    rows.emplace_back(std::move(r));
                    return true; // continue
                });
        }
        catch (const std::exception& ex)
        {
            out["error"] = ex.what();
            return out;
        }

        // Parallel conversion to JSON using TBB
        std::vector<json> datapoints(rows.size());
        tbb::parallel_for(std::size_t{0}, rows.size(), [&](std::size_t i)
                          {
                              const auto& row   = rows[i];
                              datapoints[i]["t"] = row.timestamp; // human-readable
                              datapoints[i]["v"] = row.value;
                          });

        out["values"] = std::move(datapoints);
        out["count"]  = rows.size();
        return out;
    }

private:
    // Dependencies
    std::shared_ptr<bus::EventBus>         m_bus;
    std::shared_ptr<persistence::DataLake> m_lake;
    std::shared_ptr<metrics::Registry>     m_metrics;

    // Kafka consumer
    std::shared_ptr<RdKafka::KafkaConsumer> m_consumer;
    std::string                             m_error;

    // Real-time subscription book
    std::mutex                                   m_sub_mutex;
    tbb::concurrent_unordered_map<std::string,
                                  VisualizationSubscription> m_subscriptions;

    // Worker thread
    std::jthread m_worker;
    std::atomic_bool m_running;
};

/*==================================================================================================
 *  Public API (VisualizationService)
 *================================================================================================*/

VisualizationService::VisualizationService(std::shared_ptr<bus::EventBus>           bus,
                                           std::shared_ptr<persistence::DataLake>   lake,
                                           std::shared_ptr<metrics::Registry>       metrics)
    : m_impl(std::make_unique<Impl>(std::move(bus), std::move(lake), std::move(metrics)))
{
}

VisualizationService::~VisualizationService() = default;

void VisualizationService::start() { m_impl->start(); }
void VisualizationService::stop() { m_impl->stop(); }

std::future<json> VisualizationService::query_historical(const VisualizationQuery& q)
{
    return m_impl->dispatch_historical(q);
}

void VisualizationService::subscribe(const VisualizationSubscription& s)
{
    m_impl->subscribe(s);
}
void VisualizationService::unsubscribe(const std::string& id) { m_impl->unsubscribe(id); }

/*==================================================================================================
 *  Factory (helper for Service-Locator pattern)
 *================================================================================================*/

std::shared_ptr<VisualizationService> make_visualization_service(
    std::shared_ptr<bus::EventBus>           bus,
    std::shared_ptr<persistence::DataLake>   lake,
    std::shared_ptr<metrics::Registry>       metrics)
{
    return std::make_shared<VisualizationService>(std::move(bus), std::move(lake),
                                                  std::move(metrics));
}

} // namespace cardio::visualization
```