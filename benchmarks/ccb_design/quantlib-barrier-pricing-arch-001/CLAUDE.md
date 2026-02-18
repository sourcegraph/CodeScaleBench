# big-code-quantlib-arch-001: QuantLib Barrier Option Pricing Chain

This repository is a quantitative finance C++ library (~450K LOC). The code uses heavy template metaprogramming and policy-based design patterns.

## Task Type: Architectural Understanding

Your goal is to trace the complete pricing pipeline for a barrier option. Focus on:

1. **Instrument layer**: BarrierOption → OneAssetOption → Option → Instrument → LazyObject
2. **Engine layer**: AnalyticBarrierEngine and MCBarrierEngine (Monte Carlo path)
3. **Term structures**: YieldTermStructure and BlackVolTermStructure provide rates and volatility
4. **Stochastic process**: GeneralizedBlackScholesProcess and BlackScholesMertonProcess
5. **Monte Carlo framework**: McSimulation → MonteCarloModel → PathGenerator

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `ql/instruments/barrieroption.hpp` (the instrument) and `ql/instrument.hpp` (base class with NPV/calculate)
- Explore `ql/pricingengines/barrier/` for AnalyticBarrierEngine and MCBarrierEngine
- Check `ql/pricingengines/mcsimulation.hpp` for the Monte Carlo framework
- Check `ql/methods/montecarlo/` for MonteCarloModel and PathGenerator
- Check `ql/processes/` for GeneralizedBlackScholesProcess
- Check `ql/termstructures/yield/` and `ql/termstructures/volatility/equityfx/` for term structures
- Use `find_references` to trace how Instrument.calculate() dispatches to engines
- Use `go_to_definition` to understand the template inheritance chain
