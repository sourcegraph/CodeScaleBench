#ifndef CARDIO_INSIGHT_360_CORE_PATTERNS_STRATEGY_H_
#define CARDIO_INSIGHT_360_CORE_PATTERNS_STRATEGY_H_

/*
 * CardioInsight360 – Unified Healthcare Analytics Engine
 * ------------------------------------------------------
 * File   : strategy.h
 * Author : CardioInsight360 Core Team
 * Date   : 2023-2024
 *
 * Description:
 *   Generic, header-only implementation of the Strategy Pattern used across the
 *   analytics engine to provide pluggable data-transformation and
 *   data-validation policies for various physiological signal types (ECG, BP,
 *   SpO₂, …).  The implementation offers:
 *
 *     • An abstract, strongly-typed strategy interface (IStrategy)
 *     • A run-time strategy registry/factory with thread-safe access
 *     • RAII-based auto-registration helpers for seamless plug-in of new
 *       strategies within shared libraries or within the monolithic binary
 *     • Robust error handling with domain-specific exceptions
 *     • Zero external dependencies (pure C++17); logging can be wired in by
 *       clients via the optional ILogger adapter.
 *
 * Usage Example:
 *
 *   // Define a concrete strategy somewhere in your module:
 *   class EcgBeatTransform final
 *       : public ci360::core::patterns::Strategy<RawEcgBeat, CuratedEcgBeat> {
 *   public:
 *       CuratedEcgBeat operator()(const RawEcgBeat& in) const override;
 *   };
 *
 *   // Register it with a human-readable key:
 *   static const auto kReg =
 *         ci360::core::patterns::Registrar<EcgBeatTransform>("ecg.beat.transform");
 *
 *   // Retrieve and execute at run-time:
 *   auto strategy = ci360::core::patterns::StrategyRegistry::instance()
 *                      .create<RawEcgBeat, CuratedEcgBeat>("ecg.beat.transform");
 *   CuratedEcgBeat out = (*strategy)(raw);
 *
 * NOTE:
 *   Strategies are intended to be small objects; factories always return
 *   std::unique_ptr to keep ownership explicit while avoiding slicing.
 */

#include <atomic>
#include <exception>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <typeindex>
#include <typeinfo>
#include <utility>

namespace ci360 {
namespace core {
namespace patterns {

/* ------------------------------------------------------------------------- */
/*                                   Errors                                   */
/* ------------------------------------------------------------------------- */

class StrategyError : public std::runtime_error {
public:
    explicit StrategyError(const std::string& what)
        : std::runtime_error("StrategyError: " + what) {}
};

class StrategyNotFoundError : public StrategyError {
public:
    explicit StrategyNotFoundError(const std::string& key)
        : StrategyError("Strategy with key '" + key + "' does not exist.") {}
};

class StrategyKeyCollisionError : public StrategyError {
public:
    explicit StrategyKeyCollisionError(const std::string& key)
        : StrategyError("Strategy with key '" + key + "' already registered.") {}
};

/* ------------------------------------------------------------------------- */
/*                           Strategy Interface                              */
/* ------------------------------------------------------------------------- */

/*
 * Generic strategy interface.
 *
 *   In  –  input data type
 *   Out –  output data type
 *
 * Implementations override operator() (call-operator). The operator is `const`
 * to allow stateless functors; however, internal mutability (e.g., caches) can
 * be achieved via `mutable` or internal synchronization.
 */
template <typename In, typename Out>
class Strategy {
public:
    using input_type  = In;
    using output_type = Out;

    virtual ~Strategy() = default;

    // Non-copyable (strategies are obtained via factory)
    Strategy(const Strategy&)            = delete;
    Strategy& operator=(const Strategy&) = delete;
    // Movable
    Strategy(Strategy&&) noexcept            = default;
    Strategy& operator=(Strategy&&) noexcept = default;

    /*
     * Execute the strategy.
     *
     * @throws std::exception Implementations should document thrown types.
     */
    virtual Out operator()(const In& input) const = 0;
};

/* ------------------------------------------------------------------------- */
/*                          Registry / Factory                               */
/* ------------------------------------------------------------------------- */

/*
 * Internal helper base for type-erased factories.
 */
class IAnyFactory {
public:
    virtual ~IAnyFactory()                                                   = default;
    virtual std::unique_ptr<void, void(*)(void*)> create_raw() const         = 0;
    virtual std::type_index               input_type() const                 = 0;
    virtual std::type_index               output_type() const                = 0;
};

/*
 * Concrete type-aware factory implementation.
 */
template <typename S>
class AnyFactory final : public IAnyFactory {
public:
    using StrategyT   = S;
    using In          = typename S::input_type;
    using Out         = typename S::output_type;

    std::unique_ptr<void, void(*)(void*)> create_raw() const override {
        // Custom deleter that knows the actual type
        auto deleter = [](void* ptr) noexcept { delete static_cast<StrategyT*>(ptr); };
        return std::unique_ptr<void, void(*)(void*)>(static_cast<void*>(new StrategyT{}), deleter);
    }

    std::type_index input_type() const override  { return typeid(In);  }
    std::type_index output_type() const override { return typeid(Out); }
};

/*
 * Thread-safe singleton registry.
 * (Meyers' singleton implementation is sufficient for this context.)
 */
class StrategyRegistry {
public:
    // Retrieve global instance
    static StrategyRegistry& instance() {
        static StrategyRegistry instance_;
        return instance_;
    }

    // Prevent copy
    StrategyRegistry(const StrategyRegistry&)            = delete;
    StrategyRegistry& operator=(const StrategyRegistry&) = delete;

    /*
     * Register a factory under a given key.
     *
     * @throws StrategyKeyCollisionError
     */
    template <typename StrategyT>
    void register_factory(const std::string& key) {
        std::lock_guard<std::mutex> lock(mutex_);

        if (factories_.count(key) != 0U) {
            throw StrategyKeyCollisionError{key};
        }
        factories_.emplace(key, std::make_unique<AnyFactory<StrategyT>>());
    }

    /*
     * Lookup a factory and create a strongly-typed strategy instance.
     *
     * @throws StrategyNotFoundError
     * @throws StrategyError         –  if type erasure mismatch
     */
    template <typename In, typename Out>
    std::unique_ptr<Strategy<In, Out>> create(const std::string& key) const {
        std::lock_guard<std::mutex> lock(mutex_);

        auto it = factories_.find(key);
        if (it == factories_.end()) {
            throw StrategyNotFoundError{key};
        }

        const IAnyFactory* any_factory = it->second.get();
        if (any_factory->input_type()  != typeid(In) ||
            any_factory->output_type() != typeid(Out)) {
            throw StrategyError("Type mismatch when creating strategy '" + key + "'");
        }

        auto raw = any_factory->create_raw();
        // Raw pointer is valid because deleter knows actual type
        return std::unique_ptr<Strategy<In, Out>>(
            static_cast<Strategy<In, Out>*>(raw.release())
        );
    }

    /*
     * Check whether a key is registered.
     */
    bool exists(const std::string& key) const {
        std::lock_guard<std::mutex> lock(mutex_);
        return factories_.count(key) != 0U;
    }

private:
    StrategyRegistry() = default;

    mutable std::mutex                                       mutex_;
    std::map<std::string, std::unique_ptr<IAnyFactory>>      factories_;
};

/* ------------------------------------------------------------------------- */
/*                           Registrar Helper                                */
/* ------------------------------------------------------------------------- */

/*
 * Registrar is an RAII helper that automatically registers a strategy factory
 * in the global registry at static-initialization time.
 *
 * Typical usage (at namespace scope):
 *
 *   static const auto kReg = ci360::core::patterns::Registrar<MyStrategy>("my.key");
 */
template <typename StrategyT>
class Registrar {
public:
    explicit Registrar(const std::string& key) {
        StrategyRegistry::instance().template register_factory<StrategyT>(key);
    }
};

/* ------------------------------------------------------------------------- */
/*                               Utilities                                   */
/* ------------------------------------------------------------------------- */

/*
 * Helper macro that hides template boilerplate.
 *
 * Example:
 *   struct MyStrategy : ci360::core::patterns::Strategy<In, Out> { … };
 *   REGISTER_CI360_STRATEGY(MyStrategy, "awesome.strategy");
 */
#define REGISTER_CI360_STRATEGY(STRATEGY_TYPE, KEY) \
    static const ::ci360::core::patterns::Registrar<STRATEGY_TYPE> \
        _ci360_registrar_##STRATEGY_TYPE { KEY }

} // namespace patterns
} // namespace core
} // namespace ci360

#endif /* CARDIO_INSIGHT_360_CORE_PATTERNS_STRATEGY_H_ */
