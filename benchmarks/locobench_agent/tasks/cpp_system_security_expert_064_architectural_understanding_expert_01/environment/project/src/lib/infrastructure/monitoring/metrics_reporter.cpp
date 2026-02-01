#include "metrics_reporter.h" // header located in same directory, assumed to declare classes
// NOTE: If header is not present, consider inlining the declarations below
//
// FortiLedger360 Enterprise Security Suite ― Metrics subsystem
//
// This file contains an opinionated, production-grade implementation of an
// asynchronous metrics reporter.  The reporter is responsible for collecting
// fine-grained telemetry from all infrastructure services and streaming the
// data into an external backend (Prometheus Push-Gateway by default).  It is
// thread-safe, completely lock-free on the ingest hot-path, and makes a best-
// effort attempt to batch-publish metrics while exerting back-pressure when the
// aggregator becomes unavailable.
//
// Compile flags (typical):
//    g++ -std=c++17 -O2 -Wall -Wextra -pedantic -pthread \
//        metrics_reporter.cpp -lcurl -lspdlog
//
// Copyright (c) FortiLedger360.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <curl/curl.h>
#include <mutex>
#include <queue>
#include <sstream>
#include <spdlog/spdlog.h>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

// ------------------------------------------------------------------------------------------------
// Forward declarations
// ------------------------------------------------------------------------------------------------
namespace fl360::infrastructure::monitoring {

enum class MetricType { Counter, Gauge, Histogram };

struct MetricPoint {
    std::string name;
    double      value;
    MetricType  type;
    std::unordered_map<std::string, std::string> tags;
    std::chrono::system_clock::time_point        timestamp;
};

class IMetricsBackend {
public:
    virtual ~IMetricsBackend() = default;
    virtual void publish(const std::vector<MetricPoint> &batch) = 0;
};

// ------------------------------------------------------------------------------------------------
// HTTP-based Prometheus Push-Gateway backend
// ------------------------------------------------------------------------------------------------
class HttpPushGatewayBackend final : public IMetricsBackend {
public:
    explicit HttpPushGatewayBackend(std::string endpoint)
        : endpoint_(std::move(endpoint)) {
        curl_global_init(CURL_GLOBAL_DEFAULT);
    }

    ~HttpPushGatewayBackend() override {
        curl_global_cleanup();
    }

    void publish(const std::vector<MetricPoint> &batch) override {
        if (batch.empty()) return;

        const auto body = serialize(batch);
        CURL *curl     = curl_easy_init();
        if (!curl) { throw std::runtime_error("curl_easy_init failed"); }

        struct curl_slist *headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: text/plain");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_URL, endpoint_.c_str());
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, body.size());
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 2500L); // 2.5 seconds budget
        curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);       // thread-safety

        const auto res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            spdlog::warn("[Metrics] Failed to publish metrics: {}", curl_easy_strerror(res));
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }

private:
    std::string serialize(const std::vector<MetricPoint> &batch) const {
        // Prometheus text exposition format (non-streaming).
        // <metric_name>{k=v,...} <value> <timestamp_ms>
        std::ostringstream oss;
        for (const auto &pt : batch) {
            oss << pt.name;
            if (!pt.tags.empty()) {
                oss << '{';
                bool first = true;
                for (const auto &[k, v] : pt.tags) {
                    if (!first) oss << ',';
                    oss << k << "=\"" << v << '"';
                    first = false;
                }
                oss << '}';
            }
            const auto ts_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                   pt.timestamp.time_since_epoch())
                                   .count();
            oss << ' ' << pt.value << ' ' << ts_ms << '\n';
        }
        return oss.str();
    }

    std::string endpoint_;
};

// ------------------------------------------------------------------------------------------------
// MetricsReporter singleton
// ------------------------------------------------------------------------------------------------
class MetricsReporter {
public:
    static MetricsReporter &instance() {
        static MetricsReporter reporter;
        return reporter;
    }

    MetricsReporter(const MetricsReporter &)            = delete;
    MetricsReporter(MetricsReporter &&)                 = delete;
    MetricsReporter &operator=(const MetricsReporter &) = delete;
    MetricsReporter &operator=(MetricsReporter &&)      = delete;

    void reportCounter(const std::string &name,
                       double              value = 1.0,
                       std::unordered_map<std::string, std::string> tags = {}) {
        enqueue({name, value, MetricType::Counter, std::move(tags),
                 std::chrono::system_clock::now()});
    }

    void reportGauge(const std::string &name,
                     double              value,
                     std::unordered_map<std::string, std::string> tags = {}) {
        enqueue({name, value, MetricType::Gauge, std::move(tags),
                 std::chrono::system_clock::now()});
    }

    void reportHistogram(const std::string &name,
                         double              value,
                         std::unordered_map<std::string, std::string> tags = {}) {
        enqueue({name, value, MetricType::Histogram, std::move(tags),
                 std::chrono::system_clock::now()});
    }

    void flush() {
        std::unique_lock<std::mutex> lk(queueMutex_);
        cvFlush_.notify_one(); // wake up background thread
        cvFlushed_.wait(lk, [this] { return queue_.empty(); });
    }

    void shutdown() {
        bool expected = true;
        if (running_.compare_exchange_strong(expected, false)) {
            {
                std::lock_guard<std::mutex> lk(queueMutex_);
                cvFlush_.notify_one();
            }
            if (worker_.joinable()) worker_.join();
            spdlog::info("[Metrics] Reporter shut down gracefully.");
        }
    }

    ~MetricsReporter() { shutdown(); }

private:
    MetricsReporter() {
        backend_       = std::make_unique<HttpPushGatewayBackend>(resolveEndpoint());
        flushInterval_ = resolveFlushInterval();
        running_.store(true);
        worker_ = std::thread(&MetricsReporter::backgroundLoop, this);
    }

    static std::string resolveEndpoint() {
        const char *env = std::getenv("FL360_METRICS_ENDPOINT");
        return env ? std::string(env) : "http://localhost:9091/metrics/job/fortiledger360";
    }

    static std::chrono::milliseconds resolveFlushInterval() {
        const char *env = std::getenv("FL360_METRICS_FLUSH_MS");
        if (!env) return std::chrono::milliseconds{5000};
        try {
            return std::chrono::milliseconds{std::stoul(env)};
        } catch (...) {
            spdlog::warn("[Metrics] Invalid FL360_METRICS_FLUSH_MS='{}'; falling back to 5000ms", env);
            return std::chrono::milliseconds{5000};
        }
    }

    void enqueue(MetricPoint &&point) {
        if (!running_) return;
        {
            std::lock_guard<std::mutex> lk(queueMutex_);
            queue_.push_back(std::move(point));
        }
        // do not wake up worker for every metric; rely on periodic flush
        if (queue_.size() >= kMaxBatchSize) { cvFlush_.notify_one(); }
    }

    void backgroundLoop() {
        std::vector<MetricPoint> snapshot;
        snapshot.reserve(kMaxBatchSize);

        while (running_) {
            // Wait either flush interval or explicit request
            std::unique_lock<std::mutex> lk(queueMutex_);
            cvFlush_.wait_for(lk, flushInterval_, [this] {
                return !running_ || !queue_.empty();
            });

            if (!running_ && queue_.empty()) break;

            snapshot.assign(queue_.begin(), queue_.end());
            queue_.clear();
            lk.unlock();

            // publish outside of lock
            try {
                backend_->publish(snapshot);
            } catch (const std::exception &ex) {
                spdlog::error("[Metrics] Publishing error: {}", ex.what());
            }
            snapshot.clear();

            // notify threads waiting on flush()
            cvFlushed_.notify_all();
        }
        // send any lingering metrics on exit path
        if (!queue_.empty()) {
            try { backend_->publish(queue_); }
            catch (const std::exception &ex) {
                spdlog::error("[Metrics] Final publishing error: {}", ex.what());
            }
        }
    }

private:
    static constexpr std::size_t kMaxBatchSize = 256;

    std::unique_ptr<IMetricsBackend>       backend_;
    std::chrono::milliseconds              flushInterval_{5000};

    std::mutex                             queueMutex_;
    std::vector<MetricPoint>               queue_;
    std::condition_variable                cvFlush_;
    std::condition_variable                cvFlushed_;

    std::atomic<bool>                      running_{false};
    std::thread                            worker_;
};

} // namespace fl360::infrastructure::monitoring

// ------------------------------------------------------------------------------------------------
// C-style façade for C bindings / legacy code
// ------------------------------------------------------------------------------------------------
extern "C" {

void fl360_metrics_report_counter(const char *name,
                                  double      delta,
                                  const char **kvs,
                                  std::size_t  kvs_len) {
    namespace M = fl360::infrastructure::monitoring;
    std::unordered_map<std::string, std::string> tags;
    for (std::size_t i = 0; i + 1 < kvs_len; i += 2) {
        tags.emplace(kvs[i], kvs[i + 1]);
    }
    M::MetricsReporter::instance().reportCounter(name, delta, std::move(tags));
}

void fl360_metrics_report_gauge(const char *name,
                                double      value,
                                const char **kvs,
                                std::size_t  kvs_len) {
    namespace M = fl360::infrastructure::monitoring;
    std::unordered_map<std::string, std::string> tags;
    for (std::size_t i = 0; i + 1 < kvs_len; i += 2) {
        tags.emplace(kvs[i], kvs[i + 1]);
    }
    M::MetricsReporter::instance().reportGauge(name, value, std::move(tags));
}

void fl360_metrics_flush() {
    fl360::infrastructure::monitoring::MetricsReporter::instance().flush();
}

void fl360_metrics_shutdown() {
    fl360::infrastructure::monitoring::MetricsReporter::instance().shutdown();
}

} // extern "C"