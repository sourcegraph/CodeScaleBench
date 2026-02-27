# QuantLib Barrier Option Pricing Chain: Comprehensive Architecture Analysis

## Files Examined

### Instrument Framework & Lazy Evaluation
- **ql/patterns/lazyobject.hpp** — Framework for calculation on demand and result caching. Defines the Observable/Observer pattern with deferred calculation semantics and state management (calculated_, frozen_).
- **ql/instrument.hpp** — Abstract Instrument base class deriving from LazyObject. Implements NPV() → calculate() → performCalculations() chain, coordinates with PricingEngine.
- **ql/pricingengine.hpp** — PricingEngine interface defining contract: reset(), getArguments(), getResults(), calculate(). GenericEngine template bridges Arguments/Results with PricingEngine.

### Barrier Option Components
- **ql/instruments/barrieroption.hpp** — Concrete BarrierOption class extending OneAssetOption. Defines BarrierOption::arguments (barrierType, barrier, rebate) and BarrierOption::engine base class.
- **ql/instruments/oneassetoption.hpp** — Base class for single-asset options extending Option. Introduces Greeks computation framework and OneAssetOption::results with Greek sensitivities.
- **ql/option.hpp** — Superclass defining payoff and exercise members, inherited by OneAssetOption.

### Pricing Engines
- **ql/pricingengines/barrier/analyticbarrierengine.hpp** — Closed-form analytic pricing for barrier options using Haug's formulas. Implements calculate() with direct mathematical evaluation (no simulation).
- **ql/pricingengines/barrier/mcbarrierengine.hpp** — Monte Carlo pricing engine. Key template class MCBarrierEngine<RNG, S> extending both BarrierOption::engine and McSimulation. Includes BarrierPathPricer and BiasedBarrierPathPricer path pricers.
- **ql/pricingengines/mcsimulation.hpp** — McSimulation<MC, RNG, S> framework managing Monte Carlo sampling loop. Defines virtual methods: timeGrid(), pathGenerator(), pathPricer(). Implements calculate(tolerance, samples, maxSamples) with convergence criteria.

### Monte Carlo Framework
- **ql/methods/montecarlo/montecarlomodel.hpp** — MonteCarloModel<MC, RNG, S> template encapsulating one path generator and one path pricer. addSamples() loop: generates path via pathGenerator_→next(), prices via (*pathPricer_)(path.value), accumulates statistics. Supports antithetic variates and control variates.
- **ql/methods/montecarlo/pathgenerator.hpp** — PathGenerator<GSG> template generates sample_type (Sample<Path>) by evolving StochasticProcess1D using Gaussian sequence generator (GSG). Handles Brownian Bridge construction for correlated time steps.
- **ql/methods/montecarlo/mctraits.hpp** — Trait classes defining policy:
  - SingleVariate<RNG>: path_type=Path, path_pricer_type=PathPricer<Path>, path_generator_type=PathGenerator<rsg_type>
  - MultiVariate<RNG>: path_type=MultiPath, path_pricer_type=PathPricer<MultiPath>, path_generator_type=MultiPathGenerator<rsg_type>
- **ql/methods/montecarlo/pathpricer.hpp** — PathPricer<PathType, ValueType> abstract template. Returns value of option on given path via operator()(const PathType&).

### Stochastic Process & Term Structures
- **ql/processes/blackscholesprocess.hpp** — GeneralizedBlackScholesProcess extends StochasticProcess1D. Core process implementing:
  - State evolution: d ln S = (r(t) - q(t) - σ²/2) dt + σ dW
  - Methods: x0(), drift(t,x), diffusion(t,x), evolve(t0,x0,dt,dw)
  - Composition: riskFreeRate() [Handle<YieldTermStructure>], dividendYield() [Handle<YieldTermStructure>], blackVolatility() [Handle<BlackVolTermStructure>]
- **ql/stochasticprocess.hpp** — StochasticProcess base defining discretization interface and pure virtuals size(), drift(), diffusion(), expectation(), variance(), evolve().
- **ql/termstructures/yieldtermstructure.hpp** — YieldTermStructure abstract class extending TermStructure. Provides discount(Date/Time) and zeroRate() interfaces for discounting cash flows.
- **ql/termstructures/voltermstructure.hpp** — VolatilityTermStructure abstract class. Defines interface minStrike(), maxStrike(), impliedVol() queries by derived classes.
- **ql/termstructures/blackvoltermstructure.hpp** (referenced) — BlackVolTermStructure extending VolatilityTermStructure. Provides volatility(time, strike) for option pricing.

## Dependency Chain

### Entry Point: User Code Calls NPV()

```
1. User calls: BarrierOption.NPV()
   ↓
2. ql/instrument.hpp:168 — Instrument::NPV() inline method
   calls calculate() [const]
   ↓
3. ql/instrument.hpp:130-139 — Instrument::calculate() override
   checks if !calculated_:
   - if isExpired(): setupExpired(), set calculated_=true
   - else: LazyObject::calculate()
   ↓
4. ql/patterns/lazyobject.hpp:255-266 — LazyObject::calculate()
   if (!calculated_ && !frozen_):
     set calculated_=true
     call performCalculations()
   ↓
5. ql/instrument.hpp:147-154 — Instrument::performCalculations() override
   QL_REQUIRE(engine_)
   engine_→reset()
   setupArguments(engine_→getArguments())
   engine_→getArguments()→validate()
   engine_→calculate()  ← CRITICAL CALL TO ENGINE
   fetchResults(engine_→getResults())
   ↓
6. NPV_ = results→value
```

### Engine.calculate() Dispatch: Two Paths

#### Path A: Analytic Engine (AnalyticBarrierEngine)

```
ql/pricingengines/barrier/analyticbarrierengine.hpp:49
AnalyticBarrierEngine::calculate() const override
  ↓
Direct mathematical evaluation using Haug formulas:
- Retrieves underlying(), strike(), volatility(), barrier(), rebate()
- FROM process_: x0(), riskFreeRate()→discount(t),
               dividendYield()→discount(t),
               blackVolatility()→volatility(t,strike)
- Computes analytical formulae: A(phi), B(phi), C(eta,phi), D(eta,phi), E(eta), F(eta)
- Sets results_.value directly (no iteration)
  ↓
results object filled with NPV value
```

#### Path B: Monte Carlo Engine (MCBarrierEngine<RNG, S>)

```
ql/pricingengines/barrier/mcbarrierengine.hpp:78-89
MCBarrierEngine<RNG,S>::calculate() const override
  ↓
1. Validate spot = process_→x0() > 0
2. Call McSimulation<SingleVariate,RNG,S>::calculate(tolerance, samples, maxSamples)
   ↓
3. ql/pricingengines/mcsimulation.hpp:65-67
   McSimulation::calculate(Real tolerance, Size requiredSamples, Size maxSamples)
   ↓
   Creates MonteCarloModel<MC,RNG,S> via:
   - mcModel_ = shared_ptr<MonteCarloModel>(..., pathGenerator(), pathPricer(), ...)
   ↓
4. ql/pricingengines/mcsimulation.hpp (value() method)
   Loop: while (error > tolerance):
     sampleNumber += nextBatch
     mcModel_→addSamples(nextBatch)
   ↓
5. ql/methods/montecarlo/montecarlomodel.hpp:92-125
   MonteCarloModel::addSamples(Size samples)
   for j=1 to samples:
     path = pathGenerator_→next()           ← GENERATE ONE PATH
     price = (*pathPricer_)(path.value)     ← PRICE ONE PATH
     sampleAccumulator_.add(price)
   ↓
6. results_.value = mcModel_→sampleAccumulator().mean()
```

### Path Generator Chain (Monte Carlo)

```
MCBarrierEngine::pathGenerator() override
  ql/pricingengines/barrier/mcbarrierengine.hpp:94-101
  ↓
Creates PathGenerator<RNG::rsg_type>:
  - process_ [GeneralizedBlackScholesProcess]
  - TimeGrid from process_→time(exercise→lastDate())
  - RNG sequence generator
  - brownianBridge_ flag
  ↓
PathGenerator<GSG>::next() const
  ql/methods/montecarlo/pathgenerator.hpp (template implementation)
  ↓
For each time step in TimeGrid:
  - Get next Gaussian random vector from GSG
  - Call process_→evolve(t0, x, dt, dW)
    ↓
    GeneralizedBlackScholesProcess::evolve(t0, x0, dt, dw)
      d ln S = (r(t) - q(t) - σ²/2) dt + σ dW
      new_state = old_state + drift*dt + diffusion*sqrt(dt)*dw

      Queries term structures:
      - riskFreeRate()→forwardRate(t0, t0+dt)
      - dividendYield()→forwardRate(t0, t0+dt)
      - blackVolatility()→volatility(t0+dt/2, strike)

  - Store in Path[i] = new log-price
  ↓
Returns Sample<Path> = (Path with prices at all times, weight=1.0)
```

### Path Pricer Chain (Monte Carlo)

```
MCBarrierEngine::pathPricer() override
  ql/pricingengines/barrier/mcbarrierengine.hpp:234-270
  ↓
Returns either BarrierPathPricer or BiasedBarrierPathPricer
  ↓
BarrierPathPricer::operator()(const Path& path) const override
  ql/pricingengines/barrier/mcbarrierengine.hpp
  ↓
For each path:
  1. Check if barrier triggered: loop over path times, test if spot crosses barrier
  2. If triggered: return rebate (discounted)
  3. If not triggered: return option payoff at maturity
     payoff_(path[T]) = max(spot - strike, 0) for call
     payoff_(path[T]) = max(strike - spot, 0) for put
  4. Discount to present using discount factors from term structure
     discount_factor = riskFreeRate()→discount(maturity_time)
  ↓
Returns Real price for this single path
```

## Term Structure Hierarchy

```
TermStructure (base)
  ├─→ YieldTermStructure
  │   - discount(Date d) : DiscountFactor
  │   - discount(Time t) : DiscountFactor
  │   - zeroRate(Date, DayCounter, Compounding, Frequency)
  │   - forwardRate(Date1, Date2)
  │   Used by: GeneralizedBlackScholesProcess
  │   For: Risk-free rate r(t), Dividend yield q(t)
  │
  └─→ VolatilityTermStructure
      ├─→ BlackVolTermStructure
      │   - volatility(Time, Strike) : Real
      │   Used by: GeneralizedBlackScholesProcess
      │   For: Instantaneous volatility σ(t,S) in SDE
      │
      └─→ LocalVolTermStructure (advanced)
          - localVol(Time, Spot) : Real
          Used by: Deterministic local volatility models
```

### Handle Pattern for Term Structures

```
GeneralizedBlackScholesProcess stores:
  Handle<YieldTermStructure> riskFreeRate_
  Handle<YieldTermStructure> dividendYield_
  Handle<BlackVolTermStructure> blackVolatility_

Handle<T>:
  - Smart pointer (reference counting)
  - Observes underlying TermStructure for updates
  - When term structure changes, observer notification propagates
  - Lazy object marks calculated_=false to retrigger pricing
  - Supports defensive copying and relinking
```

## Analysis

### Design Patterns Identified

1. **Lazy Evaluation Pattern (LazyObject)**
   - Defers expensive calculations until needed
   - Caches results with calculated_ flag
   - Observable/Observer coordination: dependent objects notify invalidation
   - Freeze mechanism prevents recalculation when intermediate quotes change
   - Critical for performance: avoid redundant pricing

2. **Strategy Pattern (PricingEngine)**
   - Instrument decoupled from pricing method via setPricingEngine()
   - Same BarrierOption can use AnalyticBarrierEngine OR MCBarrierEngine
   - Engine interface: arguments/results contract
   - Allows runtime selection of pricing method based on problem characteristics

3. **Template Method with Traits (McSimulation + MonteCarloModel)**
   - McSimulation defines Monte Carlo sampling loop structure
   - Derived engines override: timeGrid(), pathGenerator(), pathPricer()
   - MonteCarloModel instantiated with concrete path types via SingleVariate/MultiVariate traits
   - Separates statistical framework from path generation policy

4. **Template Specialization (PathGenerator<GSG>)**
   - GSG = Gaussian Sequence Generator (can be pseudo-random, Sobol, etc.)
   - Compile-time binding of RNG algorithm to path evolution
   - Enables algorithm swapping without runtime dispatch

5. **Handle Pattern (Observability)**
   - Term structures wrapped in Handle<T> with notification cascade
   - When YieldTermStructure or BlackVolTermStructure updates:
     - GeneralizedBlackScholesProcess receives notification (Observer)
     - Notifies dependent pricing engines
     - Lazy objects invalidate cached results

6. **Arguments/Results Pattern**
   - Separates input parameters (BarrierOption::arguments) from output (Instrument::results)
   - Allows PricingEngine to be generic without knowing instrument details
   - Results include additionalResults map for Greeks and auxiliary data

### Component Responsibilities

**Instrument Layer:**
- BarrierOption: Validates barrier parameters, passes them to engine via setupArguments()
- Manages exercise type and payoff definition
- Inherits NPV() mechanism from Instrument
- Lazy evaluation ensures pricing happens once until market data changes

**Engine Layer:**
- AnalyticBarrierEngine: Closed-form solution using Haug's formulas. Fast, precise for vanilla barriers.
- MCBarrierEngine: Monte Carlo simulation. Flexible for path-dependent features (soft barriers, rebates).
- Both implement PricingEngine interface: reset(), getArguments(), getResults(), calculate()

**Stochastic Process Layer:**
- GeneralizedBlackScholesProcess: Encapsulates SDE parameters
  - x0() → Quote (spot price)
  - riskFreeRate() → Handle<YieldTermStructure>
  - dividendYield() → Handle<YieldTermStructure>
  - blackVolatility() → Handle<BlackVolTermStructure>
- evolve() method: discretizes SDE using EulerDiscretization
  - Updates state: d ln S = μ dt + σ dW
  - Queries term structures at each time step (dynamic rates/vols)

**Path Generator Layer:**
- PathGenerator<GSG>: Time-stepped evolution
  - Generates Gaussian randoms from GSG (e.g., MersenneTwisterUniformRng)
  - Evolves process along TimeGrid
  - Returns Path object with log-prices at discrete times
  - Optional Brownian Bridge correction for early exercise/barrier monitoring accuracy

**Path Pricer Layer:**
- BarrierPathPricer: Monitors path against barrier at discrete times
  - Detects knock-out: spot crosses barrier level
  - Computes payoff if alive at maturity: max(S - K, 0) for call
  - Applies rebate if knocked out
  - Discounts using term structure's discount factors

**Statistics/Aggregation Layer:**
- Statistics accumulator: mean, variance, error estimate
- MonteCarloModel::addSamples() runs convergence loop
- Error estimation (if RNG supports): |error| < tolerance → exit loop

### Data Flow Description

```
User Input:
  barrier level, rebate, payoff (call/put/strike), exercise dates
  ↓
BarrierOption object created with payoff, exercise
  ↓
Pricing engine set: e.g., MCBarrierEngine with process (GeneralizedBlackScholesProcess)
  ↓
NPV() called → calculate() → LazyObject::performCalculations()
  ↓
FOR Analytic Path:
  AnalyticBarrierEngine::calculate()
    Queries: process_→x0() [spot]
             process_→riskFreeRate()→volatility(T)
             process_→dividendYield()→rates
             process_→blackVolatility()→volatility(T, K)
    Computes direct formula
    Returns: results_.value = closed-form NPV
  ↓
FOR Monte Carlo Path:
  McSimulation::calculate()
    FOR each sample:
      PathGenerator→next():
        FOR each time step t0→t1:
          dW ~ N(0, dt)
          evolve(): Queries r(t), q(t), σ(t)
          Updates path[i] = ln S(t)
      PathPricer→operator():
        Check: path crosses barrier?
        Compute: payoff at T or rebate if early
        Discount: to t=0
      Accumulate: price in statistics
    UNTIL: error < tolerance
    Returns: results_.value = sample mean
  ↓
Instrument::fetchResults() copies results_.value to NPV_
  ↓
NPV() returns NPV_ to user
```

### Interface Contracts Between Components

1. **Instrument ↔ PricingEngine**
   - Instrument::setupArguments(PricingEngine::arguments*) — populates arguments
   - Engine::calculate() must populate results_ via PricingEngine::results
   - Instrument::fetchResults() reads results back

2. **Engine ↔ StochasticProcess**
   - Process provides: x0(), drift(), diffusion(), evolve(), riskFreeRate(), dividendYield(), blackVolatility()
   - Engine queries process state and term structure handles
   - Process notifies engine of updates (Observable pattern)

3. **PathGenerator ↔ StochasticProcess**
   - Generator calls process→evolve(t0, state, dt, dW) repeatedly
   - Process implements SDE discretization
   - Generator manages TimeGrid and Brownian Bridge construction

4. **PathGenerator ↔ GSG (Random Number Generator)**
   - Generator calls GSG→nextSequence() for Gaussian vector
   - GSG provides dimension() matching number of time steps
   - Supports antithetic variates: GSG→antithetic()

5. **MonteCarloModel ↔ PathGenerator**
   - Model calls pathGenerator_→next() returning Sample<Path>
   - Model extracts path.value and weight

6. **MonteCarloModel ↔ PathPricer**
   - Model calls (*pathPricer_)(path.value) for each sample
   - Pricer returns Real (option value on this path)

7. **PathPricer ↔ StochasticProcess**
   - Pricer may query process for intermediate calculations
   - BarrierPathPricer queries riskFreeRate()→discount(t) for all times

8. **StochasticProcess ↔ TermStructures**
   - Process holds Handle<YieldTermStructure> and Handle<BlackVolTermStructure>
   - Queries discount(Date), forwardRate(Date1, Date2)
   - Queries volatility(Time, Strike)
   - Observes for notifications on market data changes

## Summary

The QuantLib barrier option pricing chain exemplifies a sophisticated object-oriented framework balancing encapsulation, extensibility, and performance. The **Lazy Evaluation pattern** with Observable/Observer notification enables efficient caching of expensive calculations while responding to market data updates. The **Strategy pattern** permits runtime selection between closed-form analytic pricing (AnalyticBarrierEngine) and flexible Monte Carlo simulation (MCBarrierEngine). The **Template Method + Traits pattern** in McSimulation and MonteCarloModel separates the Monte Carlo statistical framework from specific path generation and pricing policies, allowing plug-and-play algorithms. The **Handle pattern** for term structures (YieldTermStructure, BlackVolTermStructure) decouples the pricing engine from concrete interest rate and volatility implementations, supporting dynamic market data updates. Data flows from user-specified barrier/payoff parameters through the Instrument→Engine→Process→PathGenerator→PathPricer layers, with each component respecting clean interfaces and delegating specialized concerns, culminating in a vectorized sample mean (or analytic value) returned to NPV().
