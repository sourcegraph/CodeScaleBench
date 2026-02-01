#ifndef CARDIO_INSIGHT_360_MONITORING_METRICS_REGISTRY_H
#define CARDIO_INSIGHT_360_MONITORING_METRICS_REGISTRY_H

/**
 *  cardio_insight_360/src/monitoring/metrics_registry.h
 *
 *  Copyright (c) 2024
 *  CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  A light-weight, thread-safe metric collection facility adopted across the
 *  CardioInsight360 code-base.  The implementation purposefully remains header-
 *  only to simplify integration with the monolithic build and to avoid symbol
 *  ordering issues caused by static initialization across separate translation
 *  units.  Metrics are exposed via an Observer Pattern so that run-time
 *  dashboards and health-checks can subscribe to live updates without
 *  entangling business logic with monitoring concerns.
 *
 *  Design goals:
 *     • Zero/low-allocation steady-state updates
 *     • Wait-free hot-path for Counter/Gauge increments
 *     • Minimal dependencies (C++17 STL only)
 *     • Prometheus-compatible exposition format
 */

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>

namespace ci360::monitoring {

// -----------------------------------------------------------------------------
// Utility helpers
// -----------------------------------------------------------------------------
namespace detail
{
    // RFC-3339 timestamp helper for exposition headers
    inline std::string rfc3339_now()
    {
        const auto now   = std::chrono::system_clock::now();
        const auto secs  = std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch());
        const auto micros =
            std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch() - secs);

        std::time_t tt = secs.count();
#if defined(_MSC_VER)
        std::tm tm;
        gmtime_s(&tm, &tt);
#else
        std::tm tm;
        gmtime_r(&tt, &tm);
#endif
        std::ostringstream oss;
        oss << std::put_time(&tm, "%FT%T") << "." << std::setfill('0') << std::setw(6)
            << micros.count() << "Z";
        return oss.str();
    }
} // namespace detail

// -----------------------------------------------------------------------------
// Metric base-class
// -----------------------------------------------------------------------------
class Metric
{
public:
    enum class Type { Counter, Gauge, Histogram };

    explicit Metric(std::string name, std::string help, Type type)
        : name_(std::move(name)), help_(std::move(help)), type_(type) {}
    Metric(const Metric&)            = delete;
    Metric& operator=(const Metric&) = delete;
    virtual ~Metric()               = default;

    const std::string& name()  const noexcept { return name_; }
    const std::string& help()  const noexcept { return help_; }
    Type               type()  const noexcept { return type_; }

    // Prometheus exposition line(s)
    virtual std::string to_prometheus() const = 0;

private:
    std::string name_;
    std::string help_;
    Type        type_;
};

// -----------------------------------------------------------------------------
// Counter
// -----------------------------------------------------------------------------
class Counter final : public Metric
{
public:
    explicit Counter(std::string name, std::string help = "")
        : Metric(std::move(name), std::move(help), Metric::Type::Counter)
        , value_{0}
    {}

    void inc(std::uint64_t amount = 1) noexcept { value_.fetch_add(amount, std::memory_order_relaxed); }

    std::uint64_t value() const noexcept { return value_.load(std::memory_order_relaxed); }

    std::string to_prometheus() const override
    {
        std::ostringstream oss;
        if (!help().empty())
            oss << "# HELP " << name() << ' ' << help() << '\n';
        oss << "# TYPE " << name() << " counter\n";
        oss << name() << ' ' << value() << '\n';
        return oss.str();
    }

private:
    std::atomic<std::uint64_t> value_;
};

// -----------------------------------------------------------------------------
// Gauge
// -----------------------------------------------------------------------------
class Gauge final : public Metric
{
public:
    explicit Gauge(std::string name, std::string help = "")
        : Metric(std::move(name), std::move(help), Metric::Type::Gauge)
        , value_{0}
    {}

    void inc(std::int64_t amount = 1) noexcept { value_.fetch_add(amount, std::memory_order_relaxed); }
    void dec(std::int64_t amount = 1) noexcept { value_.fetch_sub(amount, std::memory_order_relaxed); }
    void set(std::int64_t v) noexcept { value_.store(v, std::memory_order_relaxed); }

    std::int64_t value() const noexcept { return value_.load(std::memory_order_relaxed); }

    std::string to_prometheus() const override
    {
        std::ostringstream oss;
        if (!help().empty())
            oss << "# HELP " << name() << ' ' << help() << '\n';
        oss << "# TYPE " << name() << " gauge\n";
        oss << name() << ' ' << value() << '\n';
        return oss.str();
    }

private:
    std::atomic<std::int64_t> value_;
};

// -----------------------------------------------------------------------------
// Histogram (fixed bucket, Prometheus-style)
// -----------------------------------------------------------------------------
class Histogram final : public Metric
{
public:
    struct Bucket final
    {
        double             upper_bound;   // +inf allowed
        std::atomic<uint64_t> count {0};
    };

    Histogram(std::string name,
              std::vector<double> boundaries,  // Must be sorted, exclusive
              std::string                      help = "")
        : Metric(std::move(name), std::move(help), Metric::Type::Histogram)
        , sum_{0.0}
    {
        if (boundaries.empty() || !std::is_sorted(boundaries.begin(), boundaries.end()))
            throw std::invalid_argument("Histogram bucket boundaries must be sorted and non-empty");

        for (double b : boundaries) { buckets_.push_back(Bucket{b}); }
        buckets_.push_back(Bucket{std::numeric_limits<double>::infinity()}); // +Inf bucket
    }

    void observe(double value) noexcept
    {
        sum_.fetch_add(value, std::memory_order_relaxed);
        for (auto& bucket : buckets_)
        {
            if (value <= bucket.upper_bound)
            {
                bucket.count.fetch_add(1, std::memory_order_relaxed);
                break;
            }
        }
    }

    std::string to_prometheus() const override
    {
        std::ostringstream oss;
        if (!help().empty())
            oss << "# HELP " << name() << ' ' << help() << '\n';
        oss << "# TYPE " << name() << " histogram\n";

        uint64_t cumulative = 0;
        for (const auto& bucket : buckets_)
        {
            cumulative += bucket.count.load(std::memory_order_relaxed);
            oss << name() << "_bucket{le=\"";
            if (std::isinf(bucket.upper_bound))
                oss << "+Inf";
            else
                oss << bucket.upper_bound;
            oss << "\"} " << cumulative << '\n';
        }
        oss << name() << "_sum " << sum_.load(std::memory_order_relaxed) << '\n';
        oss << name() << "_count "
            << buckets_.back().count.load(std::memory_order_relaxed) /* +Inf bucket holds total */
            << '\n';
        return oss.str();
    }

private:
    std::vector<Bucket>            buckets_;
    std::atomic<double>            sum_;
};

// -----------------------------------------------------------------------------
// MetricsRegistry (Singleton)
// -----------------------------------------------------------------------------
class MetricsRegistry
{
public:
    using MetricPtr = std::shared_ptr<Metric>;

    static MetricsRegistry& instance()
    {
        static MetricsRegistry inst;
        return inst;
    }

    // Factory helpers ---------------------------------------------------------
    template <class MetricT, class... Args>
    std::shared_ptr<MetricT> create(Args&&... args)
    {
        static_assert(std::is_base_of<Metric, MetricT>::value, "MetricT must derive from Metric");

        auto metric = std::make_shared<MetricT>(std::forward<Args>(args)...);

        {
            std::unique_lock lock(mutex_);
            auto [it, ok] = metrics_.try_emplace(metric->name(), metric);
            if (!ok)
            {
                throw std::invalid_argument("Metric \"" + metric->name() + "\" already exists");
            }
        }
        notify_subscribers(metric);
        return metric;
    }

    // Lookup existing metric; returns nullptr if absent
    MetricPtr find(const std::string& name) const
    {
        std::shared_lock lock(mutex_);
        auto             it = metrics_.find(name);
        return it == metrics_.end() ? nullptr : it->second;
    }

    // Takes snapshot of all metrics in Prometheus exposition format
    std::string snapshot_prometheus() const
    {
        std::ostringstream oss;
        oss << "# Snap-time: " << detail::rfc3339_now() << "\n\n";

        std::vector<MetricPtr> copy;
        {
            std::shared_lock lock(mutex_);
            copy.reserve(metrics_.size());
            for (const auto& kv : metrics_) copy.push_back(kv.second);
        }
        std::sort(copy.begin(), copy.end(),
                  [](const MetricPtr& a, const MetricPtr& b) { return a->name() < b->name(); });

        for (const auto& m : copy)
            oss << m->to_prometheus() << '\n';

        return oss.str();
    }

    // Observer API ------------------------------------------------------------
    using SubscriberFn = std::function<void(const MetricPtr&)>;

    void subscribe(SubscriberFn fn)
    {
        if (!fn) return;
        std::unique_lock lock(sub_mutex_);
        subscribers_.push_back(std::move(fn));
    }

private:
    // Must be singleton
    MetricsRegistry()  = default;
    ~MetricsRegistry() = default;

    MetricsRegistry(const MetricsRegistry&)            = delete;
    MetricsRegistry& operator=(const MetricsRegistry&) = delete;

    void notify_subscribers(const MetricPtr& metric)
    {
        std::vector<SubscriberFn> copy;
        {
            std::shared_lock lock(sub_mutex_);
            copy = subscribers_;
        }
        for (auto& fn : copy)
            fn(metric);
    }

    mutable std::shared_mutex                         mutex_;
    std::unordered_map<std::string, MetricPtr>        metrics_;

    mutable std::shared_mutex                         sub_mutex_;
    std::vector<SubscriberFn>                         subscribers_;
};

// -----------------------------------------------------------------------------
// Convenience macros
// -----------------------------------------------------------------------------
#define CI360_COUNTER(NAME, HELP)                                                                         \
    static auto NAME = ::ci360::monitoring::MetricsRegistry::instance().create<                           \
        ::ci360::monitoring::Counter>(#NAME, HELP);

#define CI360_GAUGE(NAME, HELP)                                                                           \
    static auto NAME = ::ci360::monitoring::MetricsRegistry::instance().create<                           \
        ::ci360::monitoring::Gauge>(#NAME, HELP);

#define CI360_HISTOGRAM(NAME, BOUNDARIES, HELP)                                                           \
    static auto NAME = ::ci360::monitoring::MetricsRegistry::instance().create<                           \
        ::ci360::monitoring::Histogram>(#NAME, BOUNDARIES, HELP);

} // namespace ci360::monitoring

#endif // CARDIO_INSIGHT_360_MONITORING_METRICS_REGISTRY_H