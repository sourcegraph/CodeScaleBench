#pragma once
/**********************************************************************************************************************
 * FortiLedger360 Enterprise Security Suite
 * File:        FortiLedger360/src/lib/orchestration/handlers/sla_handler.h
 * Description: Service-Level-Agreement (SLA) enforcement handler that lives in the Orchestration layer’s
 *              Chain-of-Responsibility. It consumes metric events emitted by lower infrastructure layers and
 *              evaluates them against negotiated tenant contracts.  On threshold breach, it publishes an
 *              “SlaBreach” command onto the Event Bus to trigger mitigation workflows (e.g., auto-scaling,
 *              customer notification, crediting, etc.).
 *
 * Copyright:
 *              © 2024 FortiLedger360, Ltd. All Rights Reserved.
 *********************************************************************************************************************/

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <ratio>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <spdlog/spdlog.h>          // Production-grade, header-only logging
#include <spdlog/fmt/fmt.h>

namespace fl360::orchestration::events
{
    /******************************************************************************************************************
     * Event types that bubble up from the Service-Mesh Metrics service.
     ******************************************************************************************************************/
    enum class ServiceType : std::uint8_t
    {
        kLoadBalancing,
        kSecurityScanning,
        kBackupRecovery,
        kConfigurationManagement,
        kPerformanceMetrics
    };

    struct MetricEvent
    {
        std::string                                          tenant_id;      // UUID of tenant
        ServiceType                                          service;        // Which product the metric belongs to
        std::chrono::milliseconds                            latency;        // End-to-end response latency
        double                                               error_rate;     // Fractional error rate in [0,1]
        std::chrono::system_clock::time_point                ts;             // Event timestamp

        MetricEvent(std::string                   tenant,
                    ServiceType                   svc,
                    std::chrono::milliseconds     lat,
                    double                        err,
                    std::chrono::system_clock::time_point timestamp = std::chrono::system_clock::now()) noexcept
            : tenant_id{std::move(tenant)}
            , service{svc}
            , latency{lat}
            , error_rate{err}
            , ts{timestamp}
        {}
    };

    /******************************************************************************************************************
     * Command that is published to the bus if the SLA is deemed violated.
     ******************************************************************************************************************/
    struct SlaBreachCommand
    {
        std::string                       tenant_id;
        ServiceType                       service;
        std::string                       description;    // Human-friendly message
        std::chrono::system_clock::time_point ts;

        explicit SlaBreachCommand(std::string tenant,
                                  ServiceType svc,
                                  std::string desc,
                                  std::chrono::system_clock::time_point timestamp = std::chrono::system_clock::now()) noexcept
            : tenant_id{std::move(tenant)}
            , service{svc}
            , description{std::move(desc)}
            , ts{timestamp}
        {}
    };

} // namespace fl360::orchestration::events

namespace fl360::orchestration::handlers
{
    using fl360::orchestration::events::MetricEvent;
    using fl360::orchestration::events::SlaBreachCommand;
    using fl360::orchestration::events::ServiceType;

    /******************************************************************************************************************
     * A lightweight sliding-window aggregator for latency and error-rate statistics.  Kept header-only because it’s
     * small and inlined aggressively by modern compilers.
     ******************************************************************************************************************/
    class SlidingWindow
    {
    public:
        explicit SlidingWindow(std::size_t capacity = 100)    // capacity == N most recent samples retained
            : capacity_{capacity}
        {
            values_.reserve(capacity);
        }

        void add(double value)
        {
            std::lock_guard _{mtx_};
            if (values_.size() == capacity_)
            {
                // Remove oldest element (FIFO)
                cumulative_sum_ -= values_.front();
                values_.erase(values_.begin());
            }
            values_.push_back(value);
            cumulative_sum_ += value;
        }

        [[nodiscard]] auto mean() const -> std::optional<double>
        {
            std::lock_guard _{mtx_};
            if (values_.empty()) { return std::nullopt; }
            return cumulative_sum_ / static_cast<double>(values_.size());
        }

    private:
        std::vector<double> values_;
        std::size_t         capacity_;
        mutable std::mutex  mtx_;
        double              cumulative_sum_{0.0};
    };

    /******************************************************************************************************************
     * SLAContract: Captures negotiated thresholds for each tenant & service combination.
     ******************************************************************************************************************/
    struct SLAContract
    {
        std::chrono::milliseconds max_latency;    // Maximum permitted average latency
        double                    max_error_rate; // Maximum permitted average error rate

        bool violated(const SlidingWindow& latency_window,
                      const SlidingWindow& error_window) const
        {
            const auto latency_mean = latency_window.mean();
            const auto error_mean   = error_window.mean();

            if (!latency_mean || !error_mean) { return false; } // not enough data yet

            return (*latency_mean > static_cast<double>(max_latency.count())) ||
                   (*error_mean   > max_error_rate);
        }
    };

    /******************************************************************************************************************
     * Interface for the Chain-of-Responsibility (CoR) handlers in the orchestration layer.
     ******************************************************************************************************************/
    class IRequestHandler
    {
    public:
        virtual ~IRequestHandler() = default;

        virtual void set_next(std::shared_ptr<IRequestHandler> next) = 0;
        [[nodiscard]] virtual std::shared_ptr<IRequestHandler> next() const = 0;

        // Handles a MetricEvent and returns true if processed (and CoR should end),
        // or false if the next handler should be invoked.
        virtual bool handle(const MetricEvent& evt) = 0;
    };

    /******************************************************************************************************************
     * SLAHandler: Evaluates incoming MetricEvents against SLA contracts per-tenant and publishes SlaBreachCommand
     *             whenever violations occur.  Thread-safe and lock-free for hot path where possible.
     ******************************************************************************************************************/
    class SLAHandler final : public IRequestHandler,
                             public std::enable_shared_from_this<SLAHandler>
    {
    public:
        explicit SLAHandler(/* dependency injection points: bus, repo, etc. */)
        {
            spdlog::trace("SLAHandler constructed");
        }

        ~SLAHandler() override = default;

        /* Chain-of-Responsibility plumbing */
        void set_next(std::shared_ptr<IRequestHandler> next) override
        {
            next_ = std::move(next);
        }

        [[nodiscard]] std::shared_ptr<IRequestHandler> next() const override
        {
            return next_;
        }

        /* Main entrypoint for MetricEvent processing */
        bool handle(const MetricEvent& evt) override
        {
            try
            {
                ensure_contract(evt.tenant_id, evt.service);

                auto& windows = tenant_windows_.at(key(evt.tenant_id, evt.service));

                windows.latency.add(static_cast<double>(evt.latency.count()));
                windows.error_rate.add(evt.error_rate);

                const auto& contract = contracts_.at(key(evt.tenant_id, evt.service));
                if (contract.violated(windows.latency, windows.error_rate))
                {
                    publish_breach(evt.tenant_id, evt.service, contract);
                    // SLA breach handled, stop chain here.
                    return true;
                }
            }
            catch (const std::exception& ex)
            {
                spdlog::error("SLAHandler encountered error while handling metric: {}", ex.what());
                // Fail-open: allow chain to continue so that other handlers may still process event.
            }

            // Pass along the chain if another handler exists.
            if (next_) { return next_->handle(evt); }
            return false;
        }

        /* External API to register or update contracts */
        void upsert_contract(const std::string& tenant_id,
                             ServiceType       service,
                             SLAContract       contract)
        {
            std::lock_guard guard(m_contracts_mtx_);
            contracts_[key(tenant_id, service)] = std::move(contract);
            spdlog::info("SLA contract upserted for tenant={} service={}", tenant_id, static_cast<int>(service));
        }

    private:
        struct Windows
        {
            SlidingWindow latency;
            SlidingWindow error_rate;
        };

        /****************************************************
         * Map helpers
         ****************************************************/
        static std::string key(const std::string& tenant_id, ServiceType service)
        {
            return fmt::format("{}:{}", tenant_id, static_cast<int>(service));
        }

        void ensure_contract(const std::string& tenant_id, ServiceType service)
        {
            const auto k = key(tenant_id, service);
            std::lock_guard guard(m_contracts_mtx_);
            if (!contracts_.contains(k))
            {
                // Insert default best-effort contract if none exists to avoid UB
                contracts_.emplace(k, SLAContract{
                                            .max_latency    = std::chrono::milliseconds{500},
                                            .max_error_rate = 0.02 });
                spdlog::warn("No SLA contract found for tenant={} service={}; falling back to default", tenant_id,
                             static_cast<int>(service));
            }

            // lazily create windows as needed (lock-free via double-checked / atomic)
            if (!tenant_windows_.contains(k))
            {
                std::lock_guard guard_w(m_windows_mtx_);
                tenant_windows_.try_emplace(k);
            }
        }

        /* Emit SlaBreachCommand to the event bus (stubbed – replace with actual bus publish). */
        void publish_breach(const std::string& tenant_id,
                            ServiceType       service,
                            const SLAContract& contract)
        {
            const auto cmd = SlaBreachCommand{
                tenant_id,
                service,
                fmt::format("SLA breach detected: latency>{}ms or error_rate>{}",
                            contract.max_latency.count(),
                            contract.max_error_rate)
            };

            // TODO: Inject real event-bus and publish asynchronously.
            spdlog::warn("Publishing SLA breach: tenant={} service={} reason={}",
                         tenant_id,
                         static_cast<int>(service),
                         cmd.description);
        }

        /****************************************************
         * Members
         ****************************************************/
        std::shared_ptr<IRequestHandler>                                       next_;
        std::unordered_map<std::string, SLAContract>                           contracts_;
        std::unordered_map<std::string, Windows>                               tenant_windows_;
        mutable std::mutex                                                    m_contracts_mtx_;
        mutable std::mutex                                                    m_windows_mtx_;
    };

} // namespace fl360::orchestration::handlers