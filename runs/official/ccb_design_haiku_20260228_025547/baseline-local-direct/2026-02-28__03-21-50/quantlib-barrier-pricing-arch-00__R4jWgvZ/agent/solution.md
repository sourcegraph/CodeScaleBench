# QuantLib Barrier Option Pricing Chain Analysis

## Files Examined

### Instrument/LazyObject Base Classes
- `ql/patterns/lazyobject.hpp` — Lazy evaluation pattern implementing calculation-on-demand with caching and observer notification
- `ql/instrument.hpp` — Base class for all instruments; NPV() entry point that invokes calculate() → performCalculations() → engine.calculate()
- `ql/pricingengine.hpp` — Abstract interface for pricing engines with arguments/results pattern

### Barrier Option Implementation
- `ql/instruments/barrieroption.hpp` — Barrier option instrument class; extends OneAssetOption
- `ql/instruments/barrieroption.cpp` — Implementation; setupArguments() populates engine arguments with barrier type, level, and rebate
- `ql/instruments/oneassetoption.hpp` — Base class for single-asset options; defines Greeks results structure
- `ql/option.hpp` — Base option class with payoff and exercise member variables

### Pricing Engines
- `ql/pricingengines/barrier/analyticbarrierengine.hpp` — Closed-form barrier option pricer using Haug's formulae
- `ql/pricingengines/barrier/analyticbarrierengine.cpp` — Queries process for spot, volatility, rates, dividends; computes analytic result
- `ql/pricingengines/barrier/mcbarrierengine.hpp` — Monte Carlo barrier pricer; inherits from McSimulation<SingleVariate,RNG,S>
- `ql/pricingengines/barrier/mcbarrierengine.cpp` — Implements pathGenerator() and pathPricer(); defines BarrierPathPricer and BiasedBarrierPathPricer

### Monte Carlo Framework
- `ql/pricingengines/mcsimulation.hpp` — Template base class for MC engines; provides calculate() → mcModel_->addSamples() loop
- `ql/methods/montecarlo/montecarlomodel.hpp` — Core MC model holding pathGenerator and pathPricer; addSamples() iterates: generate path → price path → accumulate
- `ql/methods/montecarlo/mctraits.hpp` — Traits classes: SingleVariate defines path_generator_type and path_pricer_type policies

### Path Generation
- `ql/methods/montecarlo/pathgenerator.hpp` — PathGenerator<GSG> template that generates sample paths:
  - Initializes path with x0() (current spot)
  - For each time step: calls process_->evolve(t, x, dt, dw) with Brownian increments
  - Optionally applies BrownianBridge variance reduction
- `ql/methods/montecarlo/brownianbridge.hpp` — Transforms uniform random numbers to correlated Brownian bridge increments

### Stochastic Process
- `ql/processes/blackscholesprocess.hpp` — GeneralizedBlackScholesProcess: 1D SDE solver implementing d(ln S) = (r-q-σ²/2)dt + σ dW_t
  - Methods: x0(), drift(), diffusion(), evolve(), stdDeviation()
  - Depends on: YieldTermStructure (risk-free and dividend), BlackVolTermStructure

### Term Structures
- `ql/termstructures/yieldtermstructure.hpp` — Abstract yield curve providing discount factors and zero rates at any maturity
- `ql/termstructures/volatility/equityfx/blackvoltermstructure.hpp` — Black volatility surface; provides blackVol(maturity, strike) and variance methods

### Random Number Generation
- `ql/math/randomnumbers/rngtraits.hpp` — Traits: PseudoRandom (MersenneTwister + InverseCumulativeNormal), LowDiscrepancy (Sobol + InverseCumulativeNormal)
- `ql/math/randomnumbers/mt19937uniformrng.hpp` — MersenneTwisterUniformRng for uniform [0,1) generation
- `ql/math/distributions/normaldistribution.hpp` — InverseCumulativeNormal transforms uniform to Gaussian

## Dependency Chain

### 1. Entry Point: Instrument.NPV() Call
```
BarrierOption::NPV()
  ↓ (inline in instrument.hpp:168-172)
  calls calculate()
```

### 2. Lazy Evaluation Mechanism: calculate() → performCalculations()
```
Instrument::calculate() [instrument.hpp:130-139]
  ├─ checks if expired() → if yes, calls setupExpired()
  └─ calls LazyObject::calculate() [lazyobject.hpp:255-266]
       └─ if not frozen and not calculated:
           └─ calls performCalculations()
               ↓
               Instrument::performCalculations() [instrument.hpp:147-154]
                 ├─ engine_->reset() — clears result cache
                 ├─ setupArguments(engine_->getArguments()) — populates BarrierOption::arguments with barrier, level, rebate
                 ├─ engine_->getArguments()->validate() — validates barrier parameters
                 ├─ engine_->calculate() — delegates to ACTUAL PRICING ENGINE
                 └─ fetchResults(engine_->getResults()) — extracts NPV_ and errorEstimate_
```

### 3a. Analytic Pricing Path: AnalyticBarrierEngine.calculate()
```
AnalyticBarrierEngine::calculate() [analyticbarrierengine.cpp:36-120+]
  ├─ process_->x0() — initial spot price from Quote
  ├─ process_->riskFreeRate()->discount(t) — YieldTermStructure query
  ├─ process_->dividendYield()->discount(t) — YieldTermStructure query
  ├─ process_->blackVolatility()->blackVol(t, K) — BlackVolTermStructure query
  ├─ Computes helper functions: A(), B(), C(), D(), E(), F() — closed-form barrier formulae
  └─ returns results_.value — single analytic price
```

**Process Integration**:
```
AnalyticBarrierEngine(GeneralizedBlackScholesProcess)
  └─ process_ holds:
       ├─ Handle<Quote> x0 (spot price)
       ├─ Handle<YieldTermStructure> dividendTS
       ├─ Handle<YieldTermStructure> riskFreeTS
       └─ Handle<BlackVolTermStructure> blackVolTS
```

### 3b. Monte Carlo Pricing Path: MCBarrierEngine → McSimulation
```
MCBarrierEngine<RNG, S>::calculate() [mcbarrierengine.hpp:78-89]
  └─ McSimulation<SingleVariate,RNG,S>::calculate(tolerance, samples, maxSamples)
      [mcsimulation.hpp:104-138]
       ├─ Creates mcModel_ : MonteCarloModel<SingleVariate,RNG,S>
       │   └─ Constructor takes pathGenerator() and pathPricer()
       │
       ├─ Convergence loop: while error > tolerance:
       │   └─ mcModel_->addSamples(batchSize)
       │       [montecarlomodel.hpp:92-107]
       │        └─ for each sample:
       │            ├─ path = pathGenerator_->next()
       │            ├─ price = (*pathPricer_)(path)
       │            └─ sampleAccumulator_.add(price)
       │
       └─ results_.value = sampleAccumulator_.mean()
```

### 4. Path Generation Pipeline: pathGenerator()
```
MCBarrierEngine::pathGenerator() [mcbarrierengine.hpp:94-101]
  └─ creates PathGenerator<RSG>(process_, timeGrid_, rsg, brownianBridge_)
      └─ PathGenerator<GSG>::next() [pathgenerator.hpp:122-154]
          ├─ Gets next Gaussian sequence from generator_
          │   └─ generator_.nextSequence() [RandomSequenceGenerator]
          │       └─ RNG::make_sequence_generator() [rngtraits.hpp:52-56]
          │           └─ PseudoRandom traits:
          │               ├─ RandomSequenceGenerator<MersenneTwisterUniformRng>
          │               └─ InverseCumulativeRsg<ursg, InverseCumulativeNormal>
          │                   └─ Transforms uniform → Gaussian
          │
          ├─ Optionally applies BrownianBridge transform
          │   └─ bb_.transform(sequence, temp)
          │
          └─ Evolves path forward:
              ├─ path[0] = process_->x0()
              └─ for i=1 to N:
                  └─ path[i] = process_->evolve(t, path[i-1], dt, dW_i)
                      [blackscholesprocess.cpp: implements SDE integration]
                       └─ Uses GeneralizedBlackScholesProcess::evolve(t, x, dt, dw)
                           ├─ drift(t, x) from risk-free rate and dividend yield
                           ├─ diffusion(t, x) from volatility term structure
                           └─ apply() formula: x_new = x_old * exp((drift - σ²/2)*dt + σ*dw)
```

### 5. Process Evolution: GeneralizedBlackScholesProcess
```
GeneralizedBlackScholesProcess::evolve(t, x, dt, dw)
  ├─ drift(t, x) = r(t) - q(t) - σ²(t,x)/2
  │   └─ queries riskFreeRate_->zeroRate(t)
  │   └─ queries dividendYield_->zeroRate(t)
  │   └─ queries blackVolatility_->sigma(t, S)
  │
  ├─ diffusion(t, x) = σ(t, x)
  │   └─ queries blackVolatility_->blackVol(t, S)
  │
  └─ apply(x, dx) — Euler-Milstein integration:
      └─ x_new = x * exp((μ - σ²/2)*dt + σ*dw)
```

### 6. Path Pricing: BarrierPathPricer
```
MCBarrierEngine::pathPricer() [mcbarrierengine.hpp:233-270]
  └─ creates BarrierPathPricer or BiasedBarrierPathPricer

      BarrierPathPricer::operator()(path) [mcbarrierengine.cpp]
        ├─ Checks barrier trigger during path evolution:
        │   └─ if barrier touched: return rebate * discount
        │
        └─ if not touched: return payoff(S_T) * discount
            └─ PlainVanillaPayoff::operator()(spot) = max(ω*(S-K), 0)
                (ω = +1 for call, -1 for put)
            └─ discount = process_->riskFreeRate()->discount(T)
```

## Analysis

### Design Patterns Identified

1. **Lazy Object Pattern** (`ql/patterns/lazyobject.hpp`):
   - Instruments cache calculation results
   - Recalculation triggered by observable changes (rates, volatility)
   - Supports freeze/unfreeze for batch operations
   - Observer pattern for dependency notification

2. **Strategy Pattern** (Pricing Engines):
   - BarrierOption::engine is abstract base
   - Multiple implementations: AnalyticBarrierEngine, MCBarrierEngine, FdBarrierEngine
   - Runtime selection via setPricingEngine()
   - Compatible arguments/results structures

3. **Template Method Pattern** (McSimulation):
   - McSimulation::calculate() defines algorithm structure
   - Subclasses implement abstract methods: pathGenerator(), pathPricer(), timeGrid()
   - Allows composition of MC engines with different:
     - RNG policies (PseudoRandom, LowDiscrepancy)
     - Variance reduction (antithetic, control variate)
     - Statistics accumulators

4. **Traits Pattern** (RNG, MC policies):
   - Compile-time customization via template traits
   - SingleVariate vs MultiVariate path policies
   - PseudoRandom vs LowDiscrepancy RNG
   - Orthogonal policy composition

5. **Handle/Body Idiom** (Term Structures):
   - Handle<YieldTermStructure> provides non-owning reference semantics
   - Allows sharing and switching of term structure implementations
   - Observable updates propagate through handle

### Component Responsibilities

| Component | Responsibility |
|-----------|-----------------|
| **BarrierOption** | Manages option parameters (barrier, rebate, payoff, exercise); setupArguments() marshals to engine |
| **Instrument** | NPV() entry point; calculate() orchestrates lazy evaluation; performCalculations() calls engine |
| **LazyObject** | Caching, observer pattern, freeze/unfreeze mechanism |
| **AnalyticBarrierEngine** | Closed-form pricing; queries process for parameters; applies Haug formulae |
| **MCBarrierEngine** | Delegate to McSimulation; implements pathGenerator(), pathPricer(), timeGrid() |
| **McSimulation** | MC algorithm: convergence loop, sample aggregation, error estimation |
| **MonteCarloModel** | Path generation/pricing loop; statistics accumulation |
| **PathGenerator** | Converts RNG sequences to asset paths; calls process.evolve() for each step |
| **GeneralizedBlackScholesProcess** | SDE implementation; drift/diffusion extraction from term structures; evolve() integration |
| **YieldTermStructure** | Discount curve; provides zero rates and discount factors at any maturity |
| **BlackVolTermStructure** | Volatility surface; provides σ(T, K) for any strike and maturity |
| **BarrierPathPricer** | Checks barrier touch; returns rebate or payoff; applies discount factor |
| **RNG Traits** | Gaussian sequence generation; supports pseudo-random or low-discrepancy |

### Data Flow Description

**Call Chain for BarrierOption.NPV()**:
1. User calls `option.NPV()`
2. Instrument::NPV() → calculate() checks expiry
3. LazyObject::calculate() → performCalculations() if not cached
4. Instrument::performCalculations() populates engine arguments via setupArguments()
5. Engine::calculate() dispatches to specific pricer

**Analytic Flow**:
1. AnalyticBarrierEngine::calculate() queries process for spot (x0)
2. Queries YieldTermStructure for interest rates
3. Queries BlackVolTermStructure for volatility
4. Applies Haug's closed-form formulae
5. Returns single price in results_.value

**Monte Carlo Flow**:
1. MCBarrierEngine::calculate() invokes McSimulation::calculate()
2. McSimulation creates MonteCarloModel with pathGenerator() and pathPricer()
3. Convergence loop: addSamples() until error < tolerance
4. Each sample:
   - pathGenerator_->next() evolves path:
     - PathGenerator uses RNG → Gaussian sequence → BrownianBridge transform
     - For each timestep: process_->evolve() computes spot based on drift, diffusion, dW
       - drift() and diffusion() extracted from GeneralizedBlackScholesProcess
       - Which queries YieldTermStructure and BlackVolTermStructure
   - pathPricer_(path) evaluates barrier condition and payoff
   - sampleAccumulator accumulates price + weight
5. Returns mean price as results_.value

### Interface Contracts Between Components

1. **Instrument ↔ PricingEngine**:
   ```cpp
   engine_->reset();  // clear results
   setupArguments(engine_->getArguments());  // populate args
   engine_->calculate();  // compute
   fetchResults(engine_->getResults());  // extract
   ```

2. **Engine ↔ Process**:
   - Engine queries process for spot: `process_->x0()`
   - Engine queries process for evolution: `process_->evolve(t, x, dt, dw)`
   - Process accesses term structures via Handles

3. **PathGenerator ↔ Process**:
   - PathGenerator calls: `process_->evolve(t, x, dt, dw)` for each step
   - Process reads from internal YieldTermStructure and BlackVolTermStructure

4. **RNG ↔ PathGenerator**:
   - PathGenerator calls: `generator_.nextSequence()` or `generator_.lastSequence()`
   - Returns Sample<Vector<Real>> with weights

5. **Term Structures ↔ Process**:
   - Process queries via Handles:
     - `riskFreeRate()->zeroRate(T)`
     - `dividendYield()->zeroRate(T)`
     - `blackVolatility()->blackVol(T, K)` or `sigma(T, S)`

## Summary

The QuantLib barrier option pricing chain exemplifies compositional financial engineering: a BarrierOption delegates to either an AnalyticBarrierEngine (direct formula evaluation) or MCBarrierEngine (path simulation). Both paths funnel through a GeneralizedBlackScholesProcess that queries a term structure hierarchy (YieldTermStructure for discounting/drift, BlackVolTermStructure for diffusion). The Monte Carlo path uses a PathGenerator that transforms pseudorandom numbers through inverse transforms and Brownian bridge correlation into asset paths evolved via process-supplied SDE dynamics. The lazy evaluation pattern ensures caching and observer-driven recalculation when market data changes, while traits-based design enables compile-time RNG and variance-reduction policy selection.
