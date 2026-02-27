# QuantLib Barrier Option Pricing Chain Architecture

## Files Examined

### Core Instrument and LazyObject Pattern
- **ql/instrument.hpp** — Abstract base class implementing lazy evaluation via LazyObject; defines NPV(), performCalculations(), and the pricing engine interface
- **ql/patterns/lazyobject.hpp** — Framework for calculation-on-demand and result caching; implements Observer pattern to track dependencies
- **ql/instruments/oneassetoption.hpp** — Base class for single-asset options; provides Greeks and results aggregation
- **ql/instruments/barrieroption.hpp** — Barrier option instrument; defines BarrierOption::arguments and BarrierOption::engine interface

### Pricing Engines
- **ql/pricingengines/barrier/analyticbarrierengine.hpp/cpp** — Analytic closed-form pricing using Haug's formulas; requires GeneralizedBlackScholesProcess
- **ql/pricingengines/barrier/mcbarrierengine.hpp/cpp** — Monte Carlo pricing with Brownian bridge correction for barrier monitoring
- **ql/pricingengine.hpp** — Base PricingEngine interface and GenericEngine template

### Monte Carlo Framework
- **ql/pricingengines/mcsimulation.hpp** — McSimulation base class that orchestrates the Monte Carlo simulation; creates MonteCarloModel and manages convergence
- **ql/methods/montecarlo/montecarlomodel.hpp** — MonteCarloModel template that iterates samples, calling pathGenerator() and pathPricer()
- **ql/methods/montecarlo/pathgenerator.hpp** — PathGenerator that evolves paths using a StochasticProcess; applies optional Brownian bridge
- **ql/methods/montecarlo/pathpricer.hpp** — Abstract PathPricer interface; BarrierPathPricer implements barrier monitoring and payoff

### Stochastic Process and Term Structures
- **ql/stochasticprocess.hpp** — Abstract StochasticProcess base class; defines drift(), diffusion(), evolve() interface and discretization strategy
- **ql/processes/blackscholesprocess.hpp** — GeneralizedBlackScholesProcess: implements d ln S = (r - q - σ²/2) dt + σ dW; holds Handles to term structures
- **ql/termstructures/yieldtermstructure.hpp** — Base class for interest rate curves; provides discount factors and rate lookups
- **ql/termstructures/voltermstructure.hpp** — Base class for volatility term structures; provides volatility and strike range validation
- **ql/termstructure.hpp** — Base TermStructure class; implements Observer/Observable pattern for date changes
- **ql/exercise.hpp** — Exercise types (European, American, Bermudan); defines exercise dates

---

## Dependency Chain

### Entry Point and Lazy Evaluation
```
1. Client calls: option.NPV()
   ↓
2. Instrument::NPV() [ql/instrument.hpp:168]
   → calls calculate()
   ↓
3. Instrument::calculate() [ql/instrument.hpp:130]
   → if !isExpired() && !calculated_:
      calls LazyObject::calculate()
   ↓
4. LazyObject::calculate() [ql/patterns/lazyobject.hpp:255]
   → if !frozen_:
      calls performCalculations()
   ↓
5. Instrument::performCalculations() [ql/instrument.hpp:147]
   → engine_->reset()
   → setupArguments(engine_->getArguments())
   → engine_->getArguments()->validate()
   → engine_->calculate()
   → fetchResults(engine_->getResults())
```

### Analytic Engine Path (Closed-Form)
```
6a. AnalyticBarrierEngine::calculate() [ql/pricingengines/barrier/analyticbarrierengine.cpp:36]
    → Extracts payoff and exercise from arguments_
    → Gets current spot: spot = process_->x0()
    → Checks barrier not triggered: triggered(spot)
    → Queries term structures via process:
       • process_->riskFreeRate()->discount(T)
       • process_->dividendYield()->discount(T)
       • process_->blackVolatility()->blackVol(T, strike)
    → Computes Black-Scholes Greeks (drift, volatility, discount factors)
    → Applies barrier formula [A, B, C, D, E, F methods]
    → Sets results_.value
```

### Monte Carlo Engine Path (Simulation)
```
6b. MCBarrierEngine::calculate() [ql/pricingengines/barrier/mcbarrierengine.hpp:78]
    → Validates spot price and barrier not triggered
    → Calls McSimulation<SingleVariate,RNG,S>::calculate(
        requiredTolerance, requiredSamples, maxSamples)
    ↓
7. McSimulation::calculate() [ql/pricingengines/mcsimulation.hpp:159]
    → Creates MonteCarloModel:
       mcModel_ = new MonteCarloModel(
         pathGenerator(),      // from MCBarrierEngine::pathGenerator()
         pathPricer(),         // from MCBarrierEngine::pathPricer()
         stats_type(),
         antitheticVariate_)
    → Calls value(tolerance) or valueWithSamples(samples)
    ↓
8. McSimulation::value() [ql/pricingengines/mcsimulation.hpp:106]
    → Initializes with minSamples (1023)
    → Iteratively calls mcModel_->addSamples(nextBatch)
    → Checks errorEstimate() against tolerance
    → Continues until convergence
    ↓
9. MonteCarloModel::addSamples() [ql/methods/montecarlo/montecarlomodel.hpp:92]
    Loop for each sample:
    ↓
10. PathGenerator::next() [ql/methods/montecarlo/pathgenerator.hpp:111]
    → Gets next random sequence from generator
    → Applies Brownian bridge correction (if enabled)
    → Initializes path[0] = process_->x0()
    → For each time step i in [1, path.length()):
       Time t = timeGrid[i-1]
       Time dt = timeGrid.dt(i-1)
       path[i] = process_->evolve(t, path[i-1], dt, dW)
       ↓
       (inside process_->evolve):
       • Computes drift = (r - q - σ²/2) * dt
       • Computes stdDev = σ * √dt
       • Returns path[i-1] + drift + stdDev * dW
       • Drift and σ queried from term structures
    ↓
    → Returns Sample<Path> with weight
    ↓
11. BarrierPathPricer::operator() [ql/pricingengines/barrier/mcbarrierengine.cpp:45]
    → Iterates through path nodes [0, n-1]
    → For each interval:
       • Queries process_->diffusion(t, asset_price) for volatility
       • Uses Brownian bridge formula to detect if barrier was hit
       • Tracks barrier hit event
    → If option is active (not knocked out):
       return payoff_(final_asset_price) * discounts_.back()
    → Else:
       return rebate_ * discounts_.back()
    ↓
12. Back to MonteCarloModel::addSamples():
    result_type price = (*pathPricer_)(path.value)
    → Adds price to sampleAccumulator_ (statistics object)

    (If antitheticVariate enabled):
    → Gets antithetic path with negated random numbers
    → Prices antithetic path
    → Averages both prices for better variance reduction
    ↓
13. Back to McSimulation::value():
    → Returns sampleAccumulator_.mean() as final price
    ↓
14. Back to MCBarrierEngine::calculate():
    results_.value = this->mcModel_->sampleAccumulator().mean()
    (optionally sets errorEstimate if RNG supports it)
```

---

## Design Patterns and Component Responsibilities

### 1. **LazyObject Pattern (Lazy Evaluation)**
**Location**: ql/patterns/lazyobject.hpp

The LazyObject implements **lazy evaluation with result caching** and **observer-based invalidation**.

- **calculate()**: Entry point that checks `calculated_` flag and calls performCalculations() only once
- **update()**: Called when observed objects (term structures, quotes) change; sets `calculated_ = false`
- **performCalculations()**: Pure virtual; implemented by derived classes (Instrument, specific engines)
- **freeze()/unfreeze()**: Allow applications to lock cached results temporarily

**Role in chain**: Ensures pricing is only recomputed when inputs change (e.g., interest rate curves, volatility surfaces)

### 2. **Generic Engine Template (Strategy Pattern)**
**Location**: ql/pricingengine.hpp

```cpp
template<class ArgumentsType, class ResultsType>
class GenericEngine : public PricingEngine, public Observer
```

- **getArguments()**: Returns mutable arguments structure for the instrument to populate
- **getResults()**: Returns const results structure populated by calculate()
- **reset()**: Clears results before calculation
- **update()**: Called when engine's observed objects (processes, term structures) change

**Role in chain**: Decouples instruments from pricing logic; allows pluggable engines (analytic, MC, FD, etc.)

### 3. **Monte Carlo Framework (Template Method + Strategy)**
**Location**: ql/pricingengines/mcsimulation.hpp + ql/methods/montecarlo/

The McSimulation class uses **Template Method** to define the Monte Carlo algorithm:
1. Create MonteCarloModel with pathGenerator() and pathPricer()
2. Add samples until convergence
3. Return accumulated statistics

Subclasses (MCBarrierEngine) override:
- **pathGenerator()**: Returns configured PathGenerator with the stochastic process
- **pathPricer()**: Returns barrier-specific pricer (BarrierPathPricer or BiasedBarrierPathPricer)
- **timeGrid()**: Defines discretization schedule

**MonteCarloModel** couples:
- **path_generator_type** (PathGenerator<GSG>): Generates random paths
- **path_pricer_type** (BarrierPathPricer): Prices individual paths
- **stats_type** (Statistics): Accumulates sample statistics

**Role in chain**: Provides reusable Monte Carlo infrastructure; handles variance reduction (antithetic variates, control variates)

### 4. **Stochastic Process and Evolution**
**Location**: ql/stochasticprocess.hpp + ql/processes/blackscholesprocess.hpp

**GeneralizedBlackScholesProcess** holds:
```cpp
Handle<Quote> x0_;                                   // Current spot price
Handle<YieldTermStructure> riskFreeRate_;          // Risk-free discount curve
Handle<YieldTermStructure> dividendYield_;         // Dividend yield curve
Handle<BlackVolTermStructure> blackVolatility_;    // Implied volatility surface
```

**Discretization** (strategy for numerical path integration):
- EulerDiscretization (default): x_next = x_0 + drift·dt + σ·√dt·dW
- Can be overridden for specialized schemes (milstein, etc.)

**evolve()** uses the discretization:
```cpp
Real evolve(Time t0, Real x0, Time dt, Real dw) const
  → drift(t0, x0) = (r(t0) - q(t0) - σ(t0)²/2) · dt
  → diffusion(t0, x0) = σ(t0) · √dt · dw
  → return x0 + drift + diffusion
```

**Role in chain**: Bridges market data (curves, vols) to path generation; enables switching between processes (Black-Scholes, Heston, jump-diffusions)

### 5. **Term Structure Hierarchy**
**Location**: ql/termstructure.hpp + ql/termstructures/yieldtermstructure.hpp + ql/termstructures/voltermstructure.hpp

**TermStructure** (base):
- Observer/Observable pattern: notifies dependents when evaluation date changes
- Methods: referenceDate(), dayCounter() for date arithmetic

**YieldTermStructure**:
- discount(t): Returns DF(0, t)
- Implementations: Flat, bootstrapped, interpolated curves

**VolatilityTermStructure**:
- blackVol(t, strike): Returns σ(T, K)
- checkStrike(): Validates strike is in [minStrike, maxStrike]
- Implementations: Constant, surface, smile, SABR, etc.

**Role in chain**: Provides market-observed rates and volatilities; can be updated at runtime (market changes) triggering engine recalculation

### 6. **Barrier-Specific Pricing**
**Location**: ql/pricingengines/barrier/

**Analytic Engine**:
- Uses closed-form formulas from Haug's book (p. 69+)
- Helper methods A(), B(), C(), D(), E(), F() compute intermediate values
- Formulas depend only on current spot, strike, barrier, rates, vols, time to expiry
- Efficient but limited to European barriers with specific payoffs

**BarrierPathPricer**:
- Monitors if barrier is hit during path evolution
- Uses **Brownian bridge correction** (El Babsiri & Noel 1998):
  - Probability that path touched barrier between discrete points
  - More accurate than naive discrete monitoring
- Payoff is applied only if option remains active (not knocked in/out)
- Applies discount factor at maturity

**BiasedBarrierPathPricer**:
- Simpler: just checks if path endpoint crosses barrier (biased)
- Faster but less accurate; often acceptable with many time steps

---

## Data Flow: Request to Result

### 1. **User Input**
```
BarrierOption option(
  barrierType = Barrier::UpOut,
  barrier = 110.0,
  rebate = 5.0,
  payoff = PlainVanillaPayoff(Call, K=100),
  exercise = EuropeanExercise(T=1Y)
);

// Set pricing engine
option.setPricingEngine(
  MakeMCBarrierEngine(process)
    .withSteps(100)
    .withSamples(10000)
    .withBrownianBridge(true)
);

// Trigger pricing
Real npv = option.NPV();
```

### 2. **Lazy Evaluation Activation**
- NPV() → calculate() → performCalculations()
- If not frozen and not calculated, proceeds; otherwise returns cached value

### 3. **Engine Setup**
- setupArguments() populates BarrierOption::arguments:
  - Copies payoff, exercise, barrier, rebate, barrier type
- Engine validates arguments (strike > 0, barrier > 0, etc.)

### 4. **Process-Driven Path Evolution** (MC path)
- For each Monte Carlo sample:
  - TimeGrid: [t₀=0, t₁, t₂, ..., tₙ=T] (e.g., 100 steps for 1Y)
  - Path initialization: S₀ = x0() (from GeneralizedBlackScholesProcess)
  - For each step i = 1 to n:
    - t = tᵢ₋₁, dt = tᵢ - tᵢ₋₁
    - Fetch r(t) from riskFreeRate_->discount(t)
    - Fetch q(t) from dividendYield_->discount(t)
    - Fetch σ(t, Sᵢ₋₁) from blackVolatility_->blackVol(t, Sᵢ₋₁)
    - drift = (r - q - σ²/2) · dt
    - diffusion = σ · √dt · Z (Z ~ N(0,1) from RNG)
    - Sᵢ = Sᵢ₋₁ · exp(drift + diffusion)

### 5. **Barrier Monitoring**
- BarrierPathPricer iterates through path, checking:
  - For UpOut barrier: if any Sᵢ ≥ H, option knocked out
  - For DownIn barrier: if any Sᵢ ≤ H, option knocked in
  - Brownian bridge correction: probability barrier touched between steps
- Flag: isOptionActive = (final barrier state)

### 6. **Path Valuation**
```
if (isOptionActive) {
  // Barrier condition satisfied; apply payoff and discount
  value = payoff(S_final) · DF(T)
        = max(S_final - K, 0) · exp(-r·T)
} else {
  // Barrier condition not satisfied; return rebate
  value = rebate · DF(T)
}
```

### 7. **Sample Accumulation**
- All path values accumulate in sampleAccumulator_ (Statistics object)
- If antitheticVariate: also generate path with -Z, average both valuations
- Statistics tracks: mean, variance, standard error

### 8. **Convergence Check**
- After each batch: error estimate = std / √n
- If error < tolerance, stop
- Else: add more samples (conservative estimate: order = (σ/tol)²)
- Repeat until convergence or maxSamples reached

### 9. **Result Return**
```
results_.value = sampleAccumulator_.mean()   // E[V]
results_.errorEstimate = sampleAccumulator_.errorEstimate()  // σ / √n
return results_
```

---

## Architecture Summary: Component Interactions

```
┌─────────────────────────────────────────────────────────────┐
│                    Barrier Option (Instrument)              │
│  - Inherits LazyObject (lazy evaluation with caching)       │
│  - Holds references to payoff, exercise, process, engine    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ NPV() → calculate() → performCalculations()
                     │
        ┌────────────▼──────────────┬─────────────────────┐
        │   PricingEngine           │  (Strategy Pattern)  │
        │   (pluggable)             │                      │
        │                           │                      │
    ┌───┴──────────────┬───────────┴──────────────┐
    │                  │                          │
    ▼                  ▼                          ▼
┌──────────────┐   ┌──────────────┐    ┌─────────────────┐
│  Analytic    │   │  MC Engine   │    │  FD Engine      │
│  Barrier     │   │  Barrier     │    │  (Not shown)    │
│  Engine      │   │              │    │                 │
│              │   └──────┬───────┘    │                 │
│ Uses         │          │            │                 │
│ Closed-form  │   McSimulation        │                 │
│ Formulas     │   Framework           │                 │
└──────┬───────┘          │            │                 │
       │                  │            │                 │
       │    ┌─────────────┴──────────┐ │
       │    │ GeneralizedBlackScholes│ │
       │    │ Process                │ │
       │    │                        │ │
       │    │ ┌────────────────────┐ │ │
       │    │ │ YieldTermStructure │ │ │
       │    │ │ (risk-free rate)   │ │ │
       │    │ │ (dividend yield)   │ │ │
       │    │ └────────────────────┘ │ │
       │    │ ┌────────────────────┐ │ │
       │    │ │ BlackVolTermStruct │ │ │
       │    │ │ (volatility surf)  │ │ │
       │    │ └────────────────────┘ │ │
       │    │                        │ │
       │    └────────┬───────────────┘ │
       │             │                  │
       │    ┌────────▼────────────┐    │
       │    │ PathGenerator       │    │
       │    │ (Evolution)         │    │
       │    │                     │    │
       │    │ ┌─────────────────┐ │    │
       │    │ │ Discretization  │ │    │
       │    │ │ (EulerDelta)    │ │    │
       │    │ └─────────────────┘ │    │
       │    │ ┌─────────────────┐ │    │
       │    │ │ BrownianBridge  │ │    │
       │    │ │ (variance red.) │ │    │
       │    │ └─────────────────┘ │    │
       │    └──────────┬──────────┘    │
       │               │                │
       │    ┌──────────▼────────────┐  │
       │    │ BarrierPathPricer     │  │
       │    │ (Per-path valuation)  │  │
       │    │                       │  │
       │    │ - Barrier monitoring  │  │
       │    │ - Brownian correction │  │
       │    │ - Payoff & discount   │  │
       │    └───────────┬──────────┘  │
       │                │              │
       │    ┌───────────▼──────────┐  │
       │    │ MonteCarloModel      │  │
       │    │ (Sample aggregation) │  │
       │    │ - Antithetic pairs   │  │
       │    │ - Statistics         │  │
       │    │ - Error tracking     │  │
       │    └───────────┬──────────┘  │
       │                │              │
       │    ┌───────────▼──────────┐  │
       │    │ Convergence Loop     │  │
       │    │ (Adaptive sampling)  │  │
       │    └──────────────────────┘  │
       │                               │
       └───────────────┬───────────────┘
                       │
                   results_
                       │
        ┌──────────────▼──────────────┐
        │   Instrument::results       │
        │  - value (NPV)              │
        │  - errorEstimate (MC only)  │
        │  - valuationDate            │
        │  - additionalResults (Greeks)
        └─────────────────────────────┘
```

---

## Summary

**QuantLib's barrier option pricing chain elegantly separates concerns through design patterns:**

1. **Instrument layer** (BarrierOption) uses **LazyObject** to cache results and invalidate on market data changes.

2. **Pricing engines** (analytic vs. Monte Carlo) implement the **Strategy pattern**, allowing runtime selection via a common interface.

3. **Monte Carlo framework** (McSimulation + MonteCarloModel) uses **Template Method** and **composition** to decouple path generation from path pricing.

4. **Stochastic process** (GeneralizedBlackScholesProcess) bridges market data (term structures) to path evolution via a **pluggable discretization** strategy.

5. **Term structures** (YieldTermStructure, BlackVolTermStructure) leverage the **Observer pattern** to propagate market data changes through the computation graph, enabling interactive re-pricing.

6. **Barrier-specific logic** (BarrierPathPricer) monitors barrier activation and applies sophisticated **Brownian bridge corrections** to improve accuracy on discrete paths.

The architecture is **extensible**: adding new barrier types, processes, term structures, or discretization schemes requires minimal changes to existing code—demonstrating strong adherence to Open/Closed and Dependency Inversion principles.
