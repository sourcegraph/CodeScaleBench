# big-code-strata-feat-001: Implement CDS Tranche Product

This repository is large (~500K LOC). Use comprehensive search to understand existing patterns before implementing.

## Task Type: Feature Implementation

Your goal is to implement a new feature that touches multiple subsystems. Focus on:

1. **Pattern discovery**: Find existing CDS and CDS Index implementations to understand conventions
2. **File identification**: Identify ALL files that need creation or modification
3. **Implementation**: Write code that follows existing Joda-Beans patterns and conventions
4. **Verification**: Ensure the implementation compiles and doesn't break existing tests

## Key Reference Files

- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndex.java` — primary pattern for product definition
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndexTrade.java` — trade wrapper pattern
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsIndex.java` — resolved form pattern
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsProductPricer.java` — pricer pattern
- `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTradeCalculationFunction.java` — calc function pattern

## Strata Conventions

- All product types use `@BeanDefinition` annotation and implement `ImmutableBean`, `Serializable`
- Trade types wrap products and add `TradeInfo`
- Resolved types expand schedules into concrete payment periods
- Pricers use `CreditRatesProvider` for market data access
- Calculation functions implement `CalculationFunction<T>` with `requirements()` and `calculate()` methods

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — examined to understand [pattern/API/convention]

## Dependency Chain
1. Define types/interfaces: path/to/types.ext
2. Implement core logic: path/to/impl.ext
3. Wire up integration: path/to/integration.ext
4. Add tests: path/to/tests.ext

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Implementation strategy, design decisions, integration approach]
```

## Search Strategy

- Search for `CdsIndex` to understand the existing CDS Index product pattern
- Search for `@BeanDefinition` in credit package to see all bean-pattern classes
- Use `find_references` on `CdsTradeCalculationFunction` to understand calc engine wiring
- Search for `IsdaCdsProductPricer` to understand pricer architecture
