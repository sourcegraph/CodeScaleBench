# big-code-strata-feat-001: Implement CDS Tranche Product in OpenGamma Strata

## Task

Implement a new `CdsTranche` product type for pricing synthetic CDO (Collateralized Debt Obligation) tranches in OpenGamma Strata. A CDS tranche represents a slice of credit risk from a CDS index portfolio, defined by attachment and detachment points that determine the subordination level.

Strata already has CDS (`Cds`, `CdsTrade`, `ResolvedCds`) and CDS Index (`CdsIndex`, `CdsIndexTrade`, `ResolvedCdsIndex`) product types in `modules/product/src/main/java/com/opengamma/strata/product/credit/`. The tranche product extends this by adding loss absorption boundaries.

The implementation must follow Strata's Joda-Beans pattern and span across the product, pricer, and measure modules:

1. **Product module** (`modules/product/src/main/java/com/opengamma/strata/product/credit/`):
   - Create `CdsTranche.java` — Joda-Bean with fields: `underlyingIndex` (CdsIndex reference), `attachmentPoint` (double 0.0-1.0), `detachmentPoint` (double 0.0-1.0), `protectionStart`, `buySell`, `currency`, `notional`, `fixedRate`, `paymentSchedule`
   - Create `CdsTrancheTrade.java` — Trade wrapper following `CdsIndexTrade` pattern
   - Create `ResolvedCdsTranche.java` — Resolved form with expanded payment periods

2. **Pricer module** (`modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/`):
   - Create `IsdaCdsTranchePricer.java` — Pricer following `IsdaCdsProductPricer` pattern, computing present value with tranche-specific loss allocation (expected loss between attachment/detachment points)

3. **Measure module** (`modules/measure/src/main/java/com/opengamma/strata/measure/credit/`):
   - Create `CdsTrancheTradeCalculationFunction.java` — Calculation function wiring the tranche into Strata's calc engine, following `CdsTradeCalculationFunction` pattern

## Context

- **Repository**: OpenGamma/Strata (Java, ~500K LOC)
- **Category**: Feature Implementation
- **Difficulty**: hard
- **Subsystem Focus**: modules/product/credit, modules/pricer/credit, modules/measure/credit

## Requirements

1. Identify all files that need modification to implement this feature
2. Follow existing patterns and conventions in the codebase (Joda-Beans `@BeanDefinition`, `ImmutableBean`, `Serializable`)
3. Implement the feature with actual code changes
4. Ensure the implementation compiles and doesn't break existing functionality

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```markdown
## Files Examined
- path/to/file1.ext — examined to understand [pattern/API/convention]
- path/to/file2.ext — modified to add [feature component]
...

## Dependency Chain
1. Define types/interfaces: path/to/types.ext
2. Implement core logic: path/to/impl.ext
3. Wire up integration: path/to/integration.ext
4. Add tests: path/to/tests.ext
...

## Code Changes
### path/to/file1.ext
```diff
- old code
+ new code
```

### path/to/file2.ext
```diff
- old code
+ new code
```

## Analysis
[Explanation of implementation strategy, design decisions, and how the feature
integrates with existing architecture]
```

## Evaluation Criteria

- Compilation: Does the code compile after changes?
- File coverage: Did you modify all necessary files?
- Pattern adherence: Do changes follow existing codebase conventions?
- Feature completeness: Is the feature fully implemented?
