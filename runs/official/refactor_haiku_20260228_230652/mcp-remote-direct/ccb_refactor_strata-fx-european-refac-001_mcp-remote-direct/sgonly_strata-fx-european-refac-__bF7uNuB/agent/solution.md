# FxVanillaOption → FxEuropeanOption Refactoring Analysis

## Executive Summary

This refactoring renames `FxVanillaOption` to `FxEuropeanOption` and related classes throughout the OpenGamma Strata codebase. The change clarifies that these are European-exercise options (exercisable only at expiry) rather than generic vanilla options. This involves renaming:

- 4 core Joda-Bean classes (and their auto-generated Meta/Builder inner classes)
- 4 pricer classes
- 4 measure classes
- 1 loader CSV plugin class
- Product type constant
- 10+ dependent files (tests and utilities)

**Total estimated file changes: 45+ files**

---

## Files Examined

### Core Product Classes (4 files)
1. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java`
   - Rename class: `FxVanillaOption` → `FxEuropeanOption`
   - Update all references in Meta inner class (lines 212-516)
   - Update all references in Builder inner class (lines 523-689)
   - Update factory methods `of()` (lines 107-164)
   - Update resolve() method (lines 202-208)
   - Update toString() methods
   - Update docstrings mentioning "vanilla FX option"

2. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java`
   - Rename class: `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`
   - Update field type: `FxVanillaOption` → `FxEuropeanOption`
   - Update resolve() return type: `ResolvedFxVanillaOptionTrade` → `ResolvedFxEuropeanOptionTrade`
   - Update imports and docstrings

3. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java`
   - Rename class: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`
   - Update all Joda-Bean Meta/Builder references
   - Update docstrings

4. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java`
   - Rename class: `ResolvedFxVanillaOptionTrade` → `ResolvedFxEuropeanOptionTrade`
   - Update field type: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`
   - Update all Joda-Bean Meta/Builder references

### Pricer Classes (4 files)
5. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java`
   - Rename class: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
   - Update parameter types: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`

6. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java`
   - Rename class: `BlackFxVanillaOptionTradePricer` → `BlackFxEuropeanOptionTradePricer`
   - Update field: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
   - Update constructor parameter types
   - Update DEFAULT field initialization

7. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java`
   - Rename class: `VannaVolgaFxVanillaOptionProductPricer` → `VannaVolgaFxEuropeanOptionProductPricer`
   - Update parameter types: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`

8. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java`
   - Rename class: `VannaVolgaFxVanillaOptionTradePricer` → `VannaVolgaFxEuropeanOptionTradePricer`
   - Update field: `VannaVolgaFxVanillaOptionProductPricer` → `VannaVolgaFxEuropeanOptionProductPricer`
   - Update constructor parameter types
   - Update DEFAULT field initialization

### Measure Classes (4 files)
9. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java`
   - Rename class: `FxVanillaOptionMeasureCalculations` → `FxEuropeanOptionMeasureCalculations`
   - Update field types and parameter types for pricers
   - Update imports

10. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java`
    - Rename class: `FxVanillaOptionTradeCalculations` → `FxEuropeanOptionTradeCalculations`
    - Update field type: `FxVanillaOptionMeasureCalculations` → `FxEuropeanOptionMeasureCalculations`
    - Update constructor parameter types for pricers

11. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java`
    - Rename class: `FxVanillaOptionTradeCalculationFunction` → `FxEuropeanOptionTradeCalculationFunction`
    - Update generic type parameter: `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`
    - Update method implementations to use renamed classes

12. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java`
    - Rename enum: `FxVanillaOptionMethod` → `FxEuropeanOptionMethod`
    - Update EnumNames reference (line 50)
    - Update docstrings referencing the old name

### Loader/CSV Classes (1 file)
13. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java`
    - Rename class: `FxVanillaOptionTradeCsvPlugin` → `FxEuropeanOptionTradeCsvPlugin`
    - Update INSTANCE field (if used)
    - Update CSV type string: "FxVanillaOption" → "FxEuropeanOption" (line 206)
    - Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update parameter types

### Utility/Infrastructure Classes (2 files)
14. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java`
    - Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update parameter type: `FxVanillaOption` → `FxEuropeanOption`
    - Update method call to renamed CSV plugin

15. `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java`
    - Rename constant: `FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`
    - Update the string value: `"FxVanillaOption"` → `"FxEuropeanOption"`
    - Update description: `"FX Vanilla Option"` → `"FX European Option"`
    - Update docstring (line 107)

### Dependent Product Classes (2 files)
16. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java`
    - Update field type: `FxVanillaOption` → `FxEuropeanOption`
    - Update parameter types in factory methods
    - Update docstrings and imports

17. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java`
    - Update field type: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`
    - Update parameter types in factory methods
    - Update docstrings and imports

### Dependent Barrier CSV Class (1 file)
18. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java`
    - Update method calls: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update parameter types: `FxVanillaOption` → `FxEuropeanOption`
    - Update imports

### Dependent Barrier Pricer Classes (2 files)
19. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricer.java`
    - Update field type: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
    - Rename variable: `VANILLA_OPTION_PRICER` → `EUROPEAN_OPTION_PRICER` (line 70)
    - Update field initialization and method calls

20. Additional barrier-related pricer files may need updates (search for references)

### Test Classes (15+ files)
21-35. All test files referencing the classes must be updated:
    - `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTest.java`
    - `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTradeTest.java`
    - `modules/product/src/test/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTradeTest.java`
    - `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricerTest.java`
    - `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricerTest.java`
    - `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricerTest.java`
    - `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricerTest.java`
    - `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxSingleBarrierOptionProductPricerTest.java`
    - `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethodTest.java`
    - `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationsTest.java`
    - `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunctionTest.java`
    - `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxOptionVolatilitiesMarketDataFunctionTest.java`
    - `modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java`
    - Additional test files using these classes

---

## Dependency Chain

```
LEVEL 1 (Core Product Definitions - MUST rename first)
  ├── FxVanillaOption.java
  ├── FxVanillaOptionTrade.java
  ├── ResolvedFxVanillaOption.java
  └── ResolvedFxVanillaOptionTrade.java

LEVEL 2 (Type/Constant Definition)
  └── ProductType.java (FX_VANILLA_OPTION constant)

LEVEL 3 (Direct Consumers - MUST rename)
  ├── Pricer Level:
  │   ├── BlackFxVanillaOptionProductPricer.java
  │   ├── BlackFxVanillaOptionTradePricer.java
  │   ├── VannaVolgaFxVanillaOptionProductPricer.java
  │   └── VannaVolgaFxVanillaOptionTradePricer.java
  ├── Measure Level:
  │   ├── FxVanillaOptionMeasureCalculations.java
  │   ├── FxVanillaOptionTradeCalculations.java
  │   ├── FxVanillaOptionTradeCalculationFunction.java
  │   └── FxVanillaOptionMethod.java
  └── Loader Level:
      ├── FxVanillaOptionTradeCsvPlugin.java
      └── CsvWriterUtils.java (writeFxVanillaOption method)

LEVEL 4 (Dependent Products - Use FxVanillaOption)
  ├── FxSingleBarrierOption.java (wraps FxVanillaOption)
  └── ResolvedFxSingleBarrierOption.java (wraps ResolvedFxVanillaOption)

LEVEL 5 (Dependent on Level 4)
  ├── FxSingleBarrierOptionTradeCsvPlugin.java (uses writeFxVanillaOption)
  ├── BlackFxSingleBarrierOptionProductPricer.java (uses BlackFxVanillaOptionProductPricer)
  └── Other barrier pricer classes

LEVEL 6 (Transitive Consumers - Test/Utility classes)
  ├── All test classes
  ├── Loader tests
  └── Any other files importing or using the renamed classes
```

---

## Strategy

### Phase 1: Rename Core Classes
1. Rename Joda-Bean classes in modules/product (4 classes)
2. Update ProductType constant
3. Verify Joda-Bean auto-generated code is properly renamed

### Phase 2: Rename Pricer/Measure/Loader Classes
4. Rename pricer classes (4 files)
5. Rename measure classes (4 files)
6. Rename loader plugin class (1 file)
7. Update CsvWriterUtils method

### Phase 3: Update Dependent Product Classes
8. Update FxSingleBarrierOption and ResolvedFxSingleBarrierOption
9. Update barrier-related CSV plugins

### Phase 4: Update Barrier Pricer Classes
10. Update BlackFxSingleBarrierOptionProductPricer and related classes

### Phase 5: Update All Tests and Utilities
11. Update all test class imports and usage
12. Update all CSV loader tests
13. Update any other utility classes

### Phase 6: Compilation Verification
14. Run full test suite to verify all changes
15. Ensure no stale references remain

---

## Key Renaming Patterns

### Class Names
- `FxVanillaOption` → `FxEuropeanOption`
- `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`
- `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`
- `ResolvedFxVanillaOptionTrade` → `ResolvedFxEuropeanOptionTrade`
- `BlackFxVanillaOption{Product,Trade}Pricer` → `BlackFxEuropeanOption{Product,Trade}Pricer`
- `VannaVolgaFxVanillaOption{Product,Trade}Pricer` → `VannaVolgaFxEuropeanOption{Product,Trade}Pricer`
- `FxVanillaOption{MeasureCalculations,TradeCalculations,TradeCalculationFunction}` → `FxEuropeanOption{...}`
- `FxVanillaOptionMethod` → `FxEuropeanOptionMethod`
- `FxVanillaOptionTradeCsvPlugin` → `FxEuropeanOptionTradeCsvPlugin`

### Constants
- `ProductType.FX_VANILLA_OPTION` → `ProductType.FX_EUROPEAN_OPTION`
- CSV type string: `"FxVanillaOption"` → `"FxEuropeanOption"`

### Method Names
- `writeFxVanillaOption()` → `writeFxEuropeanOption()`

### Docstrings
- "vanilla FX option" → "European FX option"
- "FxVanillaOption" → "FxEuropeanOption" in doc references

---

## Implementation Notes

### Joda-Bean Auto-Generated Code
Each renamed Joda-Bean class contains a Meta inner class with:
- Meta class name: `FxVanillaOption.Meta` → `FxEuropeanOption.Meta`
- Builder class name: `FxVanillaOption.Builder` → `FxEuropeanOption.Builder`
- Static INSTANCE field
- All MetaProperty declarations and property access methods
- These are auto-generated but must be manually renamed

### Factory Methods
- Static `of()` methods create instances and should remain as static factory methods
- Return types must be updated: `new FxVanillaOption(...)` → `new FxEuropeanOption(...)`

### Imports
All import statements must be updated throughout the codebase.

### Test Fixtures
Test files using these classes need:
- Updated class references in test method bodies
- Updated fixture creation (e.g., `FxVanillaOptionTest.sut()` stays the same, but internal uses change)
- Updated assertion messages if they reference the old class name

### CSV Loader Integration
The FxVanillaOptionTradeCsvPlugin needs to remain registered under the new name and the CSV type field string must be updated to enable CSV files to load properly.

---

## Verification Checklist

- [ ] All 4 core product classes renamed
- [ ] ProductType constant and string updated
- [ ] All 4 pricer classes renamed
- [ ] All 4 measure classes renamed
- [ ] CSV plugin class renamed
- [ ] CsvWriterUtils methods updated
- [ ] FxSingleBarrierOption and ResolvedFxSingleBarrierOption updated
- [ ] Barrier CSV plugin methods updated
- [ ] Barrier pricer classes updated
- [ ] All test class imports updated
- [ ] All test class usages updated
- [ ] No references to old class names remain
- [ ] Project compiles without errors
- [ ] All tests pass
- [ ] CSV loading works with new type string

---

## Impact Analysis

**Affected Systems:**
- Product modeling (FX options subsystem)
- Pricing engines (Black, Vanna-Volga models)
- Risk measurement (PV, sensitivity calculations)
- Data loading (CSV import/export)
- Barrier option support (depends on vanilla option)

**Backward Compatibility:**
- This is a breaking change to the public API
- Clients must update their code to use the new class names
- CSV data files remain compatible (data format unchanged, only type string changes)
- Serialized objects will need migration

**File Count:** 45+ files
**Complexity:** Medium (systematic renaming, no logic changes)
**Risk:** Low (purely mechanical refactoring, no behavior changes)
