# big-code-strata-refac-001: Rename FxVanillaOption to FxEuropeanOption in OpenGamma Strata

## Task

Rename the `FxVanillaOption` type family to `FxEuropeanOption` throughout the OpenGamma Strata codebase. The `FxVanillaOption` class in `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java` represents a European-exercise FX option, but the name "vanilla" is ambiguous. Rename it to `FxEuropeanOption` to clearly communicate the exercise style.

The refactoring includes:
1. Rename 4 core Joda-Beans classes: `FxVanillaOption` → `FxEuropeanOption`, `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`, `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`, `ResolvedFxVanillaOptionTrade` → `ResolvedFxEuropeanOptionTrade`
2. Rename 4 pricer classes: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`, etc.
3. Rename 4 measure classes: `FxVanillaOptionMeasureCalculations` → `FxEuropeanOptionMeasureCalculations`, etc.
4. Rename the loader plugin: `FxVanillaOptionTradeCsvPlugin` → `FxEuropeanOptionTradeCsvPlugin`
5. Update the `ProductType.FX_VANILLA_OPTION` constant and its string value
6. Update all dependent files: `FxSingleBarrierOption` (wraps `FxVanillaOption`), barrier pricers, CSV utilities, trade resolvers
7. Update Joda-Beans auto-generated Meta/Builder inner classes in all renamed files

## Context

- **Repository**: OpenGamma/Strata (Java, ~500K LOC)
- **Category**: Cross-File Refactoring
- **Difficulty**: hard
- **Subsystem Focus**: modules/product/fxopt, modules/pricer/fxopt, modules/measure/fxopt, modules/loader/csv

## Requirements

1. Identify ALL files that need modification for this refactoring
2. Document the complete dependency chain showing why each file is affected
3. Implement the changes (or describe them precisely if the scope is too large)
4. Verify that no references to the old API/name remain

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — why this file needs changes
- path/to/file2.ext — why this file needs changes
...

## Dependency Chain
1. Definition: path/to/definition.ext (original definition)
2. Direct usage: path/to/user1.ext (imports/references the symbol)
3. Transitive: path/to/user2.ext (uses a type that depends on the symbol)
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
[Explanation of the refactoring strategy, affected areas, and verification approach]
```

## Evaluation Criteria

- File coverage: Did you identify ALL files that need modification?
- Completeness: Were all references updated (no stale references)?
- Compilation: Does the code still compile after changes?
- Correctness: Do the changes preserve the intended behavior?
