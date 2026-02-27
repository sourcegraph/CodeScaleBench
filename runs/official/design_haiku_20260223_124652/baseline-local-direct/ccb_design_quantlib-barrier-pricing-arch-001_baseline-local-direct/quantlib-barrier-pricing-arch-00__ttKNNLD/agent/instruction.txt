# big-code-quantlib-arch-001: QuantLib Barrier Option Pricing Chain

## Task

Trace the QuantLib pricing chain for a barrier option: instrument→pricing engine→term structure→stochastic process→path generator. Map how a call to BarrierOption.NPV() propagates through the Instrument/LazyObject calculate() mechanism, into the pricing engine (analytic or Monte Carlo), through the term structure queries, stochastic process evolution, and path generation.

## Context

- **Repository**: lballabio/QuantLib (C++, ~450K LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: ql/instruments/, ql/pricingengines/barrier/, ql/processes/, ql/termstructures/, ql/methods/montecarlo/

## Requirements

1. Identify all relevant components in the pricing chain from BarrierOption through to PathGenerator
2. Trace the dependency chain from NPV() through LazyObject.calculate() → Instrument.performCalculations() → engine.calculate()
3. Document how the McSimulation framework connects MonteCarloModel, PathGenerator, and PathPricer
4. Explain the term structure hierarchy (YieldTermStructure, BlackVolTermStructure) and how the stochastic process (GeneralizedBlackScholesProcess) uses them

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Entry point: path/to/entry.ext
2. Calls: path/to/next.ext (via function/method name)
3. Delegates to: path/to/impl.ext
...

## Analysis
[Detailed architectural analysis including:
- Design patterns identified
- Component responsibilities
- Data flow description
- Interface contracts between components]

## Summary
[Concise 2-3 sentence summary answering the task question]
```

## Evaluation Criteria

- File recall: Did you find the correct set of architecturally relevant files?
- Dependency accuracy: Did you trace the correct dependency/call chain?
- Architectural coherence: Did you correctly identify the design patterns and component relationships?
