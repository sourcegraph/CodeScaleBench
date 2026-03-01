# QuantLib Barrier Option Pricing Chain: Architecture Analysis

## Files Examined

- `ql/instruments/barrieroption.hpp` — BarrierOption instrument class with engine interface
- `ql/instrument.hpp` — Base Instrument class with LazyObject integration and NPV calculation
- `ql/patterns/lazyobject.hpp` — LazyObject lazy-evaluation framework with caching and observer pattern
- `ql/option.hpp` — Base Option class with Payoff and Exercise
- `ql/instruments/oneassetoption.hpp` — Base class for single-asset options with Greeks
- `ql/processes/blackscholesprocess.hpp` — GeneralizedBlackScholesProcess and derivatives (drift, diffusion, volatility)
- `ql/termstructures/yieldtermstructure.hpp` — YieldTermStructure for discounting (referenced via Handle)
- `ql/termstructures/volatility/equityfx/blackvoltermstructure.hpp` — BlackVolTermStructure for volatility
- `ql/pricingengines/mcsimulation.hpp` — McSimulation template base class for Monte Carlo engines
- `ql/methods/montecarlo/montecarlomodel.hpp` — MonteCarloModel orchestrating path generation and pricing
- `ql/methods/montecarlo/pathgenerator.hpp` — PathGenerator template for generating sample paths
- `ql/pricingengines/barrier/analyticbarrierengine.hpp` — Analytic closed-form barrier pricing engine
- `ql/pricingengines/barrier/analyticbarrierengine.cpp` — Implementation of analytic formulas (Haug)
- `ql/pricingengines/barrier/mcbarrierengine.hpp` — Monte Carlo barrier option engine

## Dependency Chain

### 1. Entry Point: BarrierOption.NPV()
**File:** `ql/instrument.hpp:168`

```
BarrierOption::NPV()
  → Calls: calculate()  [inherited from Instrument]
```

The NPV() method is a simple inline that calls `calculate()` and returns the cached NPV value. This is the entry point into the pricing chain.

### 2. LazyObject Caching Mechanism
**Files:** `ql/patterns/lazyobject.hpp` and `ql/instrument.hpp`

```
Instrument::calculate()  [ql/instrument.hpp:130]
  → Checks if already calculated (caching)
  → If expired: setupExpired() → mark calculated = true
  → Else: Calls LazyObject::calculate()

LazyObject::calculate()  [ql/patterns/lazyobject.hpp:255]
  → If not calculated and not frozen:
    → performCalculations()
```

**Design Pattern:** Lazy evaluation with observer pattern. The LazyObject class:
- Inherits from Observable and Observer
- Caches calculation results with `calculated_` flag
- Forwards notifications from dependencies (term structures, quotes)
- Supports freeze() to prevent recalculation

### 3. Instrument.performCalculations() - Engine Delegation
**File:** `ql/instrument.hpp:147`

```
Instrument::performCalculations()
  → Requires engine_ is set
  → engine_->reset()
  → setupArguments(engine_->getArguments())
  → engine_->getArguments()->validate()
  → engine_->calculate()
  → fetchResults(engine_->getResults())
```

This delegates to the pricing engine. For BarrierOption:

```
BarrierOption::setupArguments(PricingEngine::arguments* args)
  → Populates BarrierOption::arguments struct:
    - barrierType_
    - barrier_
    - rebate_
    - payoff (from Option)
    - exercise (from Option)
    - underlyingSpot, riskFreeTS, dividendTS, blackVolTS
```

### 4a. Analytic Pricing Path

**File:** `ql/pricingengines/barrier/analyticbarrierengine.hpp:46`

```
AnalyticBarrierEngine::calculate()  [analyticbarrierengine.cpp:36]
  → Validate arguments (European exercise, positive strike)
  → Extract payoff type (Call/Put) and barrier type (DownIn, UpIn, DownOut, UpOut)
  → Switch on option type and barrier type
  → Call helper methods: A(), B(), C(), D(), E(), F() (analytic formulas)
  → Helpers query term structures:
    - process_->blackVolatility()->blackVol(exDate, strike)
    - process_->riskFreeRate()->zeroRate(exDate, ...)
    - process_->dividendYield()->zeroRate(exDate, ...)
  → Set results_.value = computed NPV
```

**Analytic Formulas:** Based on Haug's "Option pricing formulas", combining:
- Black-Scholes cumulative normal distribution N(d1), N(d2)
- Barrier and strike relationships
- Risk-free rate, dividend yield, volatility term structures

### 4b. Monte Carlo Pricing Path

**File:** `ql/pricingengines/barrier/mcbarrierengine.hpp:57`

```
MCBarrierEngine<RNG,S>::calculate()  [line 78]
  → Inherits from McSimulation<SingleVariate,RNG,S>
  → Calls: McSimulation<SingleVariate,RNG,S>::calculate(
      requiredTolerance_, requiredSamples_, maxSamples_)
  → Sets results_.value = mcModel_->sampleAccumulator().mean()
```

**McSimulation Framework:**
**File:** `ql/pricingengines/mcsimulation.hpp:159`

```
McSimulation::calculate(tolerance, samples, maxSamples)
  → Creates MonteCarloModel<MC,RNG,S> with:
    - pathGenerator() — provided by engine subclass
    - pathPricer() — provided by engine subclass
    - stats_type accumulator
    - antitheticVariate, controlVariate flags
  → Calls: value(tolerance, maxSamples) or valueWithSamples(samples)
```

### 5. Path Generation

**File:** `ql/methods/montecarlo/pathgenerator.hpp:45`

```
PathGenerator<GSG>::pathGenerator()  [MCBarrierEngine line 94]
  → Constructs with:
    - stochasticProcess (GeneralizedBlackScholesProcess)
    - timeGrid (from exercise maturity)
    - Gaussian sequence generator (GSG) from RNG policy
    - brownianBridge flag
```

**Path Generation Loop:**
**File:** `ql/methods/montecarlo/pathgenerator.hpp:123`

```
PathGenerator::next(bool antithetic)
  → Gets next random sequence from generator_
  → Applies brownian bridge if enabled
  → Initializes path with process_->x0() (initial spot)
  → For each time step i:
    → Calls process_->evolve(t, x, dt, dw)
      [where dw is the random increment]
    → Updates path[i] with evolved value
  → Returns Sample<Path> with weight
```

**Stochastic Process Evolution:**
**File:** `ql/processes/blackscholesprocess.hpp:54`

```
GeneralizedBlackScholesProcess::evolve(t, x, dt, dw)
  → Queries term structures at time t:
    - drift(t, x) = (r(t) - q(t) - σ(t,x)²/2)
    - diffusion(t, x) = σ(t,x)
  → Returns: apply(x, drift*dt + diffusion*dw)
    which computes log-space evolution:
    x_new = exp(log(x) + (r-q-σ²/2)*dt + σ*dw)
```

**Term Structure Queries:**
```
YieldTermStructure::discount(date)
  → Interpolates zero curve to return discount factor
  → Used in: drift calculation, path pricing

BlackVolTermStructure::blackVariance(date, strike)
BlackVolTermStructure::blackVol(date, strike)
  → Interpolates volatility surface
  → Used in: drift, diffusion, payoff valuation
```

### 6. Path Pricing

**File:** `ql/methods/montecarlo/montecarlomodel.hpp:92`

```
MonteCarloModel::addSamples(samples)
  → For each sample:
    → path = pathGenerator_->next()
    → price = pathPricer_(path)  [BarrierPathPricer or BiasedBarrierPathPricer]
    → If antitheticVariate:
      → atPath = pathGenerator_->antithetic()
      → price2 = pathPricer_(atPath)
      → average: (price + price2) / 2
    → Accumulate in sampleAccumulator_
```

**BarrierPathPricer:**
**File:** `ql/pricingengines/barrier/mcbarrierengine.hpp:140`

```
BarrierPathPricer::operator()(const Path& path)
  → Check if barrier was touched during path:
    for each time in path:
      if (barrierType in {DownIn, DownOut} and path < barrier) → triggered
      if (barrierType in {UpIn, UpOut} and path > barrier) → triggered
  → If barrier triggered:
    → return rebate * discount(triggerTime)
  → Else (for In-barriers, barrier never triggered):
    → return 0.0  (In-option expires worthless)
  → Else (for Out-barriers, barrier never triggered):
    → payoff(path.back()) * discount(maturity)
```

Includes Brownian bridge correction for accurate barrier detection between discrete time steps.

### 7. Statistical Accumulation

**File:** `ql/math/statistics/statistics.hpp`

```
Statistics<Real>::add(price, weight=1.0)
  → Accumulates sample values
  → Computes running mean, variance, error estimate

Statistics::mean()
  → Returns estimate of option price

Statistics::errorEstimate()
  → Returns standard error sqrt(variance/samples)
```

### 8. Results Propagation

```
Instrument::fetchResults(engine_->getResults())
  → Casts results to Instrument::results*
  → Copies:
    - value → NPV_
    - errorEstimate → errorEstimate_
    - valuationDate → valuationDate_
    - additionalResults → additionalResults_
```

## Analysis

### Design Patterns Identified

1. **Lazy Evaluation Pattern (Observer/Observable)**
   - LazyObject delays calculations until needed
   - Caches results and invalidates on input changes
   - Instruments observe market data (quotes, curves)
   - Reduces redundant calculations in complex dependency graphs

2. **Strategy Pattern (Pricing Engine)**
   - Instrument is agnostic to calculation method
   - Engine strategy can be swapped (analytic, Monte Carlo, finite difference, binomial)
   - Arguments/Results structure provides clean interface

3. **Template Method Pattern**
   - McSimulation defines calculate() skeleton
   - Subclasses implement pathPricer(), pathGenerator(), timeGrid()
   - Decouples MC algorithm from specific instruments

4. **Policy-Based Design (Templates)**
   - MC engines templated on:
     - `MC`: Single/Multi-variate traits (SingleVariate, MultiVariate)
     - `RNG`: Random number generator policy (PseudoRandom, LowDiscrepancy)
     - `S`: Statistics accumulator (Statistics, IncrementalStatistics)
   - Allows compile-time specialization without runtime polymorphism

5. **Handle/Body Pattern**
   - Term structures held via Handle<YieldTermStructure>
   - Defers ownership/lifetime management
   - Enables quote/curve relinking without recreating process

### Component Responsibilities

| Component | Responsibility |
|-----------|-----------------|
| **Instrument (BarrierOption)** | Owns payoff, exercise, barrier parameters; orchestrates calculation via LazyObject |
| **LazyObject** | Caching, dirty-flag logic, observer notification forwarding |
| **PricingEngine** | Core valuation algorithm; reads arguments, writes results |
| **GeneralizedBlackScholesProcess** | SDE evolution (drift/diffusion); delegates to term structures for rates/vols |
| **YieldTermStructure** | Manages zero curve; provides discount factors and rates |
| **BlackVolTermStructure** | Manages vol surface; provides Black volatility at any date/strike |
| **McSimulation** | MC framework: tolerance/sample logic, control variates, antithetic sampling |
| **MonteCarloModel** | Orchestrates loop: pathGenerator → pathPricer → statistics accumulator |
| **PathGenerator** | Generates sample paths using random sequences and Brownian bridge |
| **BarrierPathPricer** | Checks barrier condition; applies payoff and discounting |

### Data Flow Description

1. **Setup Phase**
   - User creates BarrierOption with payoff, exercise, barrier parameters
   - User creates stochastic process with spot quote, yield curves, vol surface
   - User sets pricing engine on instrument

2. **Calculation Trigger**
   - NPV() called on instrument
   - calculate() inherited from Instrument/LazyObject
   - Engine's calculate() is invoked via performCalculations()

3. **Analytic Path (Closed-form)**
   - Engine reads barrier arguments
   - Queries term structures at option maturity once
   - Applies closed-form formula (combination of Black-Scholes with barrier adjustments)
   - Returns NPV directly

4. **Monte Carlo Path**
   - Engine creates timeGrid from exercise date
   - McSimulation::calculate() creates MonteCarloModel with pathGenerator and pathPricer
   - Loop: Generate N paths
     - PathGenerator evolves process forward in time
     - Each evolution queries process drift/diffusion (which queries term structures)
     - BarrierPathPricer checks barrier condition on evolved path
     - Applies payoff and discounting
   - Statistics accumulator computes mean and error estimate
   - Returns NPV ± confidence interval

### Interface Contracts

**Instrument ↔ PricingEngine**
- Instrument populates arguments_ struct via setupArguments()
- Engine reads arguments_, computes, populates results_
- Instrument reads results_ via fetchResults()

**Engine ↔ Process (for MC)**
- Engine queries process->x0() (initial value)
- Engine calls process->evolve(t, x, dt, dw) in loop
- Process queries drift(), diffusion() which delegate to term structures

**Process ↔ Term Structures**
- Process holds Handles to YieldTermStructure (discounting), BlackVolTermStructure (volatility)
- On each evolve() call, queries term structures at specific dates/strikes
- Term structures interpolate internal curves on demand

**McSimulation ↔ Engine Subclass**
- Engine subclass must implement:
  - pathPricer() → returns PathPricer<Path>
  - pathGenerator() → returns PathGenerator
  - timeGrid() → returns TimeGrid for simulation
- McSimulation calls these to construct MonteCarloModel and run simulation loop

## Summary

QuantLib's barrier option pricing chains through a **lazy-evaluated instrument** that **delegates to pluggable pricing engines**. For **analytic pricing**, the engine queries term structures once and applies closed-form formulas. For **Monte Carlo**, the engine orchestrates a multi-layer framework: **McSimulation** creates a **MonteCarloModel** that repeatedly calls a **PathGenerator** (which evolves the stochastic process forward in time by querying its drift/diffusion and underlying term structures) and **PathPricer** (which checks barrier conditions and applies the payoff), accumulating statistics until convergence. This design achieves modularity, efficiency via caching, and flexibility in switching between pricing methods.
