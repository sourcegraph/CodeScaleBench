# FxVanillaOption → FxEuropeanOption Refactoring Analysis

## Overview
Rename the `FxVanillaOption` type family to `FxEuropeanOption` throughout the OpenGamma Strata codebase to clarify that these classes represent European-exercise FX options.

## Files Examined

### Core Joda-Beans Classes (4 files)
- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java** → FxEuropeanOption.java
  - Reason: Main product class definition, needs class rename and all internal references
  - Dependencies: Used by FxVanillaOptionTrade, FxSingleBarrierOption, all pricers, all measure classes

- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java** → FxEuropeanOptionTrade.java
  - Reason: Trade wrapper for FxVanillaOption, needs class rename and reference updates
  - Dependencies: References FxVanillaOption, ResolvedFxVanillaOptionTrade; used by calculation functions

- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java** → ResolvedFxEuropeanOption.java
  - Reason: Resolved version of FxVanillaOption, needs class rename and references
  - Dependencies: Referenced by FxVanillaOption.resolve(), ResolvedFxSingleBarrierOption, all pricers

- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java** → ResolvedFxEuropeanOptionTrade.java
  - Reason: Resolved trade wrapper, needs class rename
  - Dependencies: Referenced by FxVanillaOptionTrade.resolve(), used in all pricers/calculations

### Pricer Classes (4 files)
- **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java** → BlackFxEuropeanOptionProductPricer.java
  - Reason: Black model pricer for FxVanillaOption products
  - Contains: DEFAULT static instance, pricing methods for ResolvedFxVanillaOption

- **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java** → BlackFxEuropeanOptionTradePricer.java
  - Reason: Black model pricer for FxVanillaOption trades
  - Contains: DEFAULT static instance, uses BlackFxVanillaOptionProductPricer

- **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java** → VannaVolgaFxEuropeanOptionProductPricer.java
  - Reason: Vanna Volga pricer for FxVanillaOption products

- **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java** → VannaVolgaFxEuropeanOptionTradePricer.java
  - Reason: Vanna Volga pricer for FxVanillaOption trades

### Measure Classes (4 files)
- **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java** → FxEuropeanOptionMeasureCalculations.java
  - Reason: Internal measure calculations for FxVanillaOption trades
  - References: BlackFxVanillaOptionTradePricer, VannaVolgaFxVanillaOptionTradePricer

- **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java** → FxEuropeanOptionTradeCalculations.java
  - Reason: Public calculations wrapper for trades
  - References: FxVanillaOptionMeasureCalculations

- **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java** → FxEuropeanOptionTradeCalculationFunction.java
  - Reason: Calculation function implementation for FxVanillaOptionTrade
  - Implements: CalculationFunction<FxVanillaOptionTrade>

- **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java** → FxEuropeanOptionMethod.java
  - Reason: Enumeration of calculation methods (BLACK, VANNA_VOLGA)

### Loader Plugin (1 file)
- **modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java** → FxEuropeanOptionTradeCsvPlugin.java
  - Reason: CSV parsing/writing plugin for FxVanillaOption trades
  - Contains: writeFxVanillaOption method → writeFxEuropeanOption

### Files With Internal References (6 files - update imports only)
- **modules/product/src/main/java/com/opengamma/strata/product/ProductType.java**
  - Change: Line 109: `FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");`
  - To: `FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");`
  - Note: Keep both if backward compatibility needed, but task says rename

- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java**
  - References: FxVanillaOption in property, imports, and docstrings
  - Changes needed: Update type references from FxVanillaOption to FxEuropeanOption

- **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java**
  - References: ResolvedFxVanillaOption in property and Meta field
  - Changes needed: Update all references

- **modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java**
  - References: FxVanillaOption in imports and methods
  - Changes needed: Update import and method calls

- **modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java**
  - References: FxVanillaOption in imports, writeFxVanillaOption method calls
  - Changes needed: Update import and method call

- **modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java**
  - References: Multiple test methods using FxVanillaOption
  - Changes needed: Update all references and test method names

## Dependency Chain

```
1. FxVanillaOption (CORE)
   ↓ Used by ↓
   - FxVanillaOptionTrade (imports, "implements Resolvable<ResolvedFxVanillaOption>")
   - FxSingleBarrierOption (property type: "FxVanillaOption underlyingOption")
   - BlackFxVanillaOptionProductPricer (method parameters)
   - BlackFxVanillaOptionTradePricer (method parameters)
   - VannaVolgaFxVanillaOptionProductPricer (method parameters)
   - VannaVolgaFxVanillaOptionTradePricer (method parameters)
   - FxVanillaOptionTradeCsvPlugin (parsing/writing methods)
   - CsvWriterUtils (method call)

2. ResolvedFxVanillaOption (CORE)
   ↓ Used by ↓
   - FxVanillaOption.resolve() (return type)
   - ResolvedFxSingleBarrierOption (property type)
   - All pricers (method parameters)

3. FxVanillaOptionTrade (CORE)
   ↓ Used by ↓
   - FxVanillaOptionTradeCalculationFunction (implements CalculationFunction<FxVanillaOptionTrade>)
   - FxVanillaOptionMeasureCalculations (ResolvedFxVanillaOptionTrade parameter)
   - FxVanillaOptionTradeCalculations (public wrapper)
   - TradeCsvLoaderTest

4. ResolvedFxVanillaOptionTrade (CORE)
   ↓ Used by ↓
   - FxVanillaOptionTrade.resolve() (return type)
   - All measure calculations (parameter types)
   - All trade pricers (parameter types)

5. ProductType.FX_VANILLA_OPTION (CONSTANT)
   ↓ Referenced by ↓
   - FxVanillaOptionTrade.summarize() (line 100)

6. Pricers
   ↓ Used by ↓
   - FxVanillaOptionMeasureCalculations (fields: blackPricer, vannaVolgaPricer)
   - FxVanillaOptionTradeCalculations (constructor, delegation)
   - Test classes
```

## Implementation Strategy

### Phase 1: Rename Core Product Classes
1. Create FxEuropeanOption.java (rename from FxVanillaOption.java)
   - Update class name (FxVanillaOption → FxEuropeanOption)
   - Update all Joda-Beans references (Meta, Builder inner classes)
   - Update method references to ResolvedFxVanillaOption → ResolvedFxEuropeanOption
   - Update toString() output

2. Create ResolvedFxEuropeanOption.java (rename from ResolvedFxVanillaOption.java)
   - Update class name and references

3. Create FxEuropeanOptionTrade.java (rename from FxVanillaOptionTrade.java)
   - Update class name
   - Update imports: FxVanillaOption → FxEuropeanOption
   - Update type references: ResolvedFxVanillaOptionTrade → ResolvedFxEuropeanOptionTrade
   - Update ProductType.FX_VANILLA_OPTION constant reference

4. Create ResolvedFxEuropeanOptionTrade.java (rename from ResolvedFxVanillaOptionTrade.java)
   - Update class name
   - Update imports: ResolvedFxVanillaOption → ResolvedFxEuropeanOption

### Phase 2: Rename and Update Pricer Classes
5. Create BlackFxEuropeanOptionProductPricer.java
   - Update class name and Meta references

6. Create BlackFxEuropeanOptionTradePricer.java
   - Update class name
   - Update import: BlackFxVanillaOptionProductPricer → BlackFxEuropeanOptionProductPricer
   - Update method signatures: ResolvedFxVanillaOptionTrade → ResolvedFxEuropeanOptionTrade

7. Create VannaVolgaFxEuropeanOptionProductPricer.java
   - Update class name and Meta references

8. Create VannaVolgaFxEuropeanOptionTradePricer.java
   - Update class name
   - Update import: VannaVolgaFxVanillaOptionProductPricer → VannaVolgaFxEuropeanOptionProductPricer
   - Update method signatures

### Phase 3: Rename and Update Measure Classes
9. Create FxEuropeanOptionMeasureCalculations.java
   - Update class name
   - Update imports: BlackFxVanillaOption* → BlackFxEuropeanOption*
   - Update imports: VannaVolgaFxVanillaOption* → VannaVolgaFxEuropeanOption*

10. Create FxEuropeanOptionTradeCalculations.java
    - Update class name
    - Update imports: BlackFxVanillaOption* → BlackFxEuropeanOption*
    - Update imports: VannaVolgaFxVanillaOption* → VannaVolgaFxEuropeanOption*
    - Update class references in constructor

11. Create FxEuropeanOptionTradeCalculationFunction.java
    - Update class name
    - Update imports
    - Update CalculationFunction<FxVanillaOptionTrade> → CalculationFunction<FxEuropeanOptionTrade>

12. Create FxEuropeanOptionMethod.java
    - Update class name and enum name references

### Phase 4: Rename and Update Loader Plugin
13. Create FxEuropeanOptionTradeCsvPlugin.java
    - Update class name
    - Update method names: writeFxVanillaOption → writeFxEuropeanOption
    - Update imports: FxVanillaOption → FxEuropeanOption

### Phase 5: Update Dependent Files
14. Update ProductType.java
    - Change: FX_VANILLA_OPTION → FX_EUROPEAN_OPTION
    - Update description: "FX Vanilla Option" → "FX European Option"

15. Update FxSingleBarrierOption.java
    - Update import: FxVanillaOption → FxEuropeanOption
    - Update property type and method signatures
    - Update docstrings and comments

16. Update ResolvedFxSingleBarrierOption.java
    - Update import: ResolvedFxVanillaOption → ResolvedFxEuropeanOption
    - Update property type and method signatures

17. Update FxSingleBarrierOptionTradeCsvPlugin.java
    - Update imports

18. Update CsvWriterUtils.java
    - Update import: FxVanillaOption → FxEuropeanOption
    - Update method call: writeFxVanillaOption → writeFxEuropeanOption

19. Update test files
    - All test files importing/using FxVanillaOption classes
    - Update method names: test_load_fx_vanilla_option → test_load_fx_european_option

## Code Changes

### Pattern 1: Class Rename (Example: FxVanillaOption → FxEuropeanOption)
```
OLD:
public final class FxVanillaOption
    implements FxOptionProduct, Resolvable<ResolvedFxVanillaOption>, ImmutableBean, Serializable {
  ...
  public static FxVanillaOption.Meta meta() {
    return FxVanillaOption.Meta.INSTANCE;
  }
  public static FxVanillaOption.Builder builder() {
    return new FxVanillaOption.Builder();
  }

NEW:
public final class FxEuropeanOption
    implements FxOptionProduct, Resolvable<ResolvedFxEuropeanOption>, ImmutableBean, Serializable {
  ...
  public static FxEuropeanOption.Meta meta() {
    return FxEuropeanOption.Meta.INSTANCE;
  }
  public static FxEuropeanOption.Builder builder() {
    return new FxEuropeanOption.Builder();
  }
```

### Pattern 2: Joda-Beans Meta Class
```
OLD: public static final class Meta extends DirectMetaBean { }
     public Class<? extends FxVanillaOption> beanType() {
       return FxVanillaOption.class;
     }

NEW: public static final class Meta extends DirectMetaBean { }
     public Class<? extends FxEuropeanOption> beanType() {
       return FxEuropeanOption.class;
     }
```

### Pattern 3: Builder Class
```
OLD: public static final class Builder extends DirectFieldsBeanBuilder<FxVanillaOption>
     public FxVanillaOption build() {
       return new FxVanillaOption(...);
     }

NEW: public static final class Builder extends DirectFieldsBeanBuilder<FxEuropeanOption>
     public FxEuropeanOption build() {
       return new FxEuropeanOption(...);
     }
```

### Pattern 4: Method Parameters and References
```
OLD: void method(ResolvedFxVanillaOptionTrade trade, ...)
NEW: void method(ResolvedFxEuropeanOptionTrade trade, ...)
```

## Files That Need Creation (16 files)

**Core Products (4):**
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxEuropeanOption.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxEuropeanOptionTrade.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxEuropeanOption.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxEuropeanOptionTrade.java

**Pricers (4):**
- modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxEuropeanOptionProductPricer.java
- modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxEuropeanOptionTradePricer.java
- modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxEuropeanOptionProductPricer.java
- modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxEuropeanOptionTradePricer.java

**Measures (4):**
- modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxEuropeanOptionMeasureCalculations.java
- modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxEuropeanOptionTradeCalculations.java
- modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxEuropeanOptionTradeCalculationFunction.java
- modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxEuropeanOptionMethod.java

**Loader (1):**
- modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxEuropeanOptionTradeCsvPlugin.java

## Files That Need Updates (6+ dependent files)
- ProductType.java
- FxSingleBarrierOption.java
- ResolvedFxSingleBarrierOption.java
- FxSingleBarrierOptionTradeCsvPlugin.java
- CsvWriterUtils.java
- TradeCsvLoaderTest.java
- (Plus other test files for renamed classes)

## Verification Approach

1. **Compilation Check**: Ensure no compilation errors after all changes
2. **Test Execution**: Run existing test suite to verify behavior is preserved
3. **Reference Validation**: Use grep/keyword search to ensure no orphaned references to old names
4. **Search Results**: Verify ProductType constant usage is updated everywhere

## Risk Assessment

- **High Complexity**: Multiple interdependent classes across packages
- **Scope**: 16 core classes + 6+ dependent files + test files
- **Risk Mitigation**: Systematic rename with thorough import updates
- **Backward Compatibility**: No attempt to maintain dual names; full rename required

## Expected Outcome

All references to `FxVanillaOption` and related classes will be renamed to `FxEuropeanOption`, making the exercise style explicit in the class names. The public API of the classes remains unchanged; only names are affected.

## Implementation Progress

### Completed
1. ✅ Comprehensive refactoring analysis and dependency chain mapping
2. ✅ FxEuropeanOption.java created locally (example of core class refactoring)

### Implementation Strategy for Remaining Files

**Approach**: Use sed-based bulk replacement with systematic verification

**Pattern for all class renames**:
```bash
sed 's/FxVanillaOption/FxEuropeanOption/g;
     s/ResolvedFxVanillaOption/ResolvedFxEuropeanOption/g;
     s/BlackFxVanillaOption/BlackFxEuropeanOption/g;
     s/VannaVolgaFxVanillaOption/VannaVolgaFxEuropeanOption/g;
     s/FxVanillaOptionMethod/FxEuropeanOptionMethod/g;
     s/FX_VANILLA_OPTION/FX_EUROPEAN_OPTION/g' input.java > output.java
```

**Remaining Work**:
1. Create 3 more core product classes (ResolvedFxEuropeanOption, FxEuropeanOptionTrade, ResolvedFxEuropeanOptionTrade)
2. Create 4 pricer classes (Black and VannaVolga, product and trade versions)
3. Create 4 measure classes (Measure Calculations, Trade Calculations, Calculation Function, Method enum)
4. Create 1 loader plugin class
5. Update 6+ dependent files with import statements
6. Update test files (optional but recommended for validation)

### Critical Implementation Notes

1. **Joda-Beans Meta Classes**: Each class has inner `Meta` and `Builder` classes that auto-generate - all references to the class name must be updated
2. **String Constants**: `"FxVanillaOption"` → `"FxEuropeanOption"` in toString(), builder references
3. **Docstring Updates**: Update comments that reference "vanilla" to "European" for clarity
4. **Type References**: All method signatures with `ResolvedFxVanillaOption` parameters must be updated
5. **Import Statements**: All java package imports need to be updated

### Verification Checklist

After completing all file changes:
- [ ] No compilation errors in modules/product
- [ ] No compilation errors in modules/pricer
- [ ] No compilation errors in modules/measure
- [ ] No compilation errors in modules/loader
- [ ] All tests in fxopt packages pass
- [ ] grep -r "FxVanillaOption" modules/ returns only comments/docs or old backup files
- [ ] grep -r "ResolvedFxVanillaOption" modules/ returns only comments/docs or old backup files
- [ ] ProductType.FX_EUROPEAN_OPTION correctly referenced in FxEuropeanOptionTrade
- [ ] All measure calculation functions accept FxEuropeanOptionTrade parameters

### Critical File List for Testing

**Must compile after changes**:
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxEuropeanOption.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxEuropeanOptionTrade.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxEuropeanOption.java
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxEuropeanOptionTrade.java
- modules/product/src/main/java/com/opengamma/strata/product/ProductType.java

**Must correctly resolve**:
- modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java (import FxEuropeanOption)
- modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxEuropeanOptionProductPricer.java
- modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxEuropeanOptionTradeCalculationFunction.java

### Backward Compatibility Note

This refactoring does NOT maintain backward compatibility:
- Old `FxVanillaOption` class is removed entirely
- Old `FX_VANILLA_OPTION` constant is removed entirely
- All callers must migrate to new class names
- API is identical except for class/method names

## Summary

The refactoring renames 4 core Joda-Beans classes, 4 pricer classes, 4 measure classes, 1 loader plugin, and updates 6+ dependent files. All changes are mechanical name replacements that preserve functionality while clarifying the European exercise style in class names.
