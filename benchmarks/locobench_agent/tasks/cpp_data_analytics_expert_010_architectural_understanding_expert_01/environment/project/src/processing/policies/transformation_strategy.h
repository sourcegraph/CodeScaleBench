```cpp
/************************************************************************************
 *  CardioInsight360 – Unified Healthcare Analytics Engine                          *
 *                                                                                  *
 *  File: transformation_strategy.h                                                 *
 *  Path: cardio_insight_360/src/processing/policies/                               *
 *                                                                                  *
 *  Description:                                                                    *
 *  ----------------------------------------------------------------------------    *
 *  Interface and registration facilities for pluggable signal–transformation       *
 *  strategies.  A TransformationStrategy is responsible for converting raw,        *
 *  source–specific payloads (e.g., HL7 ORU^R01, IEEE 11073, proprietary binary)    *
 *  into an internal, schema-compliant representation that subsequent pipeline      *
 *  stages can consume.                                                             *
 *                                                                                  *
 *  Each concrete strategy advertises a processing Stage so the ETL Pipeline can    *
 *  organise execution order across ingestion, validation, normalisation, and       *
 *  feature-extraction phases.                                                      *
 *                                                                                  *
 *  Copyright (c) 2024 Hartmann Digital Health Systems.                             *
 *  SPDX-License-Identifier: Apache-2.0                                             *
 ************************************************************************************/

#pragma once

#include <cstddef>          // std::byte
#include <functional>       // std::function
#include <memory>           // std::unique_ptr
#include <shared_mutex>     // std::shared_mutex
#include <stdexcept>        // std::runtime_error
#include <string>           // std::string
#include <unordered_map>    // std::unordered_map
#include <utility>          // std::move
#include <vector>           // std::vector

namespace ci360::processing::policies
{

/**
 * Lightweight metadata object propagated alongside the signal buffer so that
 * transformation policies have contextual information (e.g., patient-id,
 * device-model, sampling-rate) without having to dereference global state.
 *
 * NOTE: Only a subset is shown here; the production version contains many more
 *       domain-specific fields but we intentionally keep it minimal in header.
 */
struct SignalMetadata
{
    std::string source_hospital_unit;
    std::string device_model;
    std::string patient_id;
    std::uint32_t nominal_sampling_rate_hz = 0;
};

/**
 * Base-class for all transformation strategies.
 *
 * Implementations must be:
 *   – Default constructible
 *   – Non-copyable / Non-movable (handled by unique_ptr wrapper)
 *   – Thread-safe for const member functions (invoked concurrently by TBB)
 */
class TransformationStrategy
{
public:
    enum class Stage : std::uint8_t
    {
        Ingestion = 0,      // Raw payload to canonical wire format
        PreValidation,      // Quick structural sanity checks
        Normalisation,      // Unit-conversion, re-sampling, filtering
        FeatureExtraction   // Derived metrics (QRS width, HRV, etc.)
    };

    virtual ~TransformationStrategy() = default;

    /**
     * Human-readable identifier.  Used both for logging and as primary key
     * within the factory-registry.  Must be unique across the application.
     */
    [[nodiscard]] virtual std::string name() const noexcept = 0;

    /**
     * Returns the processing point at which the strategy wants to be executed.
     * The ETL scheduler groups strategies per stage to maximise cache locality.
     */
    [[nodiscard]] virtual Stage stage() const noexcept = 0;

    /**
     * Core transformation routine.
     *
     * @param input     Immutable byte-buffer received from upstream component.
     * @param output    Target buffer that receives the transformed payload.
     * @param meta      Additional context for transformation; may be ignored.
     *
     * Implementations must throw only TransformationError derived exceptions.
     * On failure, the pipeline will route the original payload to quarantine.
     */
    virtual void transform(const std::vector<std::byte>& input,
                           std::vector<std::byte>&       output,
                           const SignalMetadata&         meta) const = 0;

    // Disallow copying to avoid slicing and accidental shared ownership.
    TransformationStrategy(const TransformationStrategy&)            = delete;
    TransformationStrategy& operator=(const TransformationStrategy&) = delete;
    TransformationStrategy(TransformationStrategy&&)                 = delete;
    TransformationStrategy& operator=(TransformationStrategy&&)      = delete;

protected:
    TransformationStrategy() = default;
};

/**
 * Exception type thrown by TransformationStrategy implementations to indicate a
 * recoverable failure that should be handled by the ETL error-recovery policy.
 */
class TransformationError : public std::runtime_error
{
    using std::runtime_error::runtime_error;
};

/**
 * Factory-registry that allows run-time discovery and instantiation of
 * TransformationStrategy implementations by name.
 *
 * The registry is header-only so that plugins can self-register via a static
 * initialiser block without additional linkage requirements.
 */
class TransformationStrategyRegistry
{
public:
    using Creator = std::function<std::unique_ptr<TransformationStrategy>()>;

    /**
     * Registers a Creator functor for the specified strategy name.
     *
     * @returns true if inserted, false if the name already existed.
     * @throws  std::invalid_argument if name is empty or Creator is null.
     */
    bool register_strategy(std::string name, Creator creator)
    {
        if (name.empty()) {
            throw std::invalid_argument{"TransformationStrategy name cannot be empty"};
        }
        if (!creator) {
            throw std::invalid_argument{"TransformationStrategy creator cannot be null"};
        }

        std::unique_lock lock{mutex_};
        auto [it, inserted] = creators_.try_emplace(std::move(name), std::move(creator));
        return inserted;
    }

    /**
     * Returns a newly created instance of the strategy requested.
     *
     * @throws std::out_of_range if strategy is not registered.
     */
    [[nodiscard]] std::unique_ptr<TransformationStrategy> create(const std::string& name) const
    {
        std::shared_lock lock{mutex_};
        auto it = creators_.find(name);
        if (it == creators_.end()) {
            throw std::out_of_range{"TransformationStrategy '" + name + "' is not registered"};
        }
        return (it->second)();
    }

    /**
     * Lists available strategy names.  Primarily for introspection/CLI help.
     */
    [[nodiscard]] std::vector<std::string> available() const
    {
        std::shared_lock lock{mutex_};
        std::vector<std::string> names;
        names.reserve(creators_.size());
        for (auto&& [name, _] : creators_) {
            names.emplace_back(name);
        }
        return names;
    }

    // Singleton access
    static TransformationStrategyRegistry& instance()
    {
        static TransformationStrategyRegistry registry;
        return registry;
    }

private:
    TransformationStrategyRegistry()  = default;
    ~TransformationStrategyRegistry() = default;

    mutable std::shared_mutex                     mutex_;
    std::unordered_map<std::string, Creator>      creators_;
};

/**
 * Helper macro that self-registers a concrete TransformationStrategy with the
 * global registry.  Usage:
 *
 *  class MyStrategy : public TransformationStrategy { … };
 *  CI360_REGISTER_TRANSFORMATION_STRATEGY("my-strategy", MyStrategy)
 */
#define CI360_REGISTER_TRANSFORMATION_STRATEGY(STRAT_NAME, STRAT_CLASS)               \
    static bool _ci360_register_##STRAT_CLASS()                                       \
    {                                                                                 \
        return ::ci360::processing::policies::TransformationStrategyRegistry::instance() \
            .register_strategy((STRAT_NAME), []() { return std::make_unique<STRAT_CLASS>(); }); \
    }                                                                                 \
    static const bool _ci360_registered_flag_##STRAT_CLASS = _ci360_register_##STRAT_CLASS()

} // namespace ci360::processing::policies
```