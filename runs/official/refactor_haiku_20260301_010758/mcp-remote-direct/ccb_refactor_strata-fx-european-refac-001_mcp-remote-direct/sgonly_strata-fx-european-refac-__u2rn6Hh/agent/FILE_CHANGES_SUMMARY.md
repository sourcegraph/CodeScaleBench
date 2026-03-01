# Complete File Changes Summary

## Files to RENAME (13 files)

These files must be renamed and their internal class names updated.

### Core Product Classes (4 files)
1. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java`
   → `FxEuropeanOption.java`

2. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java`
   → `FxEuropeanOptionTrade.java`

3. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java`
   → `ResolvedFxEuropeanOption.java`

4. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java`
   → `ResolvedFxEuropeanOptionTrade.java`

### Pricer Classes (4 files)
5. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java`
   → `BlackFxEuropeanOptionProductPricer.java`

6. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java`
   → `BlackFxEuropeanOptionTradePricer.java`

7. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java`
   → `VannaVolgaFxEuropeanOptionProductPricer.java`

8. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java`
   → `VannaVolgaFxEuropeanOptionTradePricer.java`

### Measure Classes (4 files)
9. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java`
   → `FxEuropeanOptionMeasureCalculations.java`

10. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java`
    → `FxEuropeanOptionTradeCalculations.java`

11. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java`
    → `FxEuropeanOptionTradeCalculationFunction.java`

12. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java`
    → `FxEuropeanOptionMethod.java`

### Loader/CSV Plugin (1 file)
13. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java`
    → `FxEuropeanOptionTradeCsvPlugin.java`

---

## Files to UPDATE (20+ files)

These files need import statements, type references, and method calls updated but are NOT renamed.

### Product Files (4 files)
1. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java`
   - Change field type: `FxVanillaOption underlyingOption` → `FxEuropeanOption underlyingOption`
   - Update imports
   - Update method parameters

2. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOptionTrade.java`
   - Update imports
   - Update field types in wrapper

3. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java`
   - Change field type: `ResolvedFxVanillaOption underlyingOption` → `ResolvedFxEuropeanOption underlyingOption`
   - Update imports
   - Update method parameters

4. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOptionTrade.java`
   - Update imports
   - Update field types in wrapper

### Pricer Files (2 files)
5. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricer.java`
   - Update import: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
   - Update field name/type: `VANILLA_OPTION_PRICER` field
   - Update references to pricer instance

6. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionTradePricer.java`
   - Update import: `BlackFxVanillaOptionTradePricer` → `BlackFxEuropeanOptionTradePricer`
   - Update field declarations

### Measure Files (2 files)
7. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionMeasureCalculations.java`
   - Update imports if it references vanilla pricers
   - Update field declarations

8. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationFunction.java`
   - Update imports
   - Update type references

### Constant and Utility Files (2 files)
9. `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java`
   - Rename constant: `FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`
   - Update ProductType string: `"FxVanillaOption"` → `"FxEuropeanOption"`
   - Update display string: `"FX Vanilla Option"` → `"FX European Option"`

10. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java`
    - Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update parameter type: `FxVanillaOption` → `FxEuropeanOption`
    - Update import and delegation to renamed plugin

### Loader Files (2 files)
11. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java`
    - Update import: `FxVanillaOption` → `FxEuropeanOption`
    - Update method calls if delegating to vanilla option CSV plugin

12. `modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java`
    - Update imports
    - Update test method calls
    - Update helper method calls (e.g., `expectedFxVanillaOption()` → `expectedFxEuropeanOption()`)

### Barrier Option CSV Plugin (1 file)
13. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java`
    - Update to work with renamed FxEuropeanOption

---

## Test Files to RENAME (14 files)

### Product Tests (4 files)
1. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTest.java`
   → `FxEuropeanOptionTest.java`

2. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTradeTest.java`
   → `FxEuropeanOptionTradeTest.java`

3. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTest.java`
   → `ResolvedFxEuropeanOptionTest.java`

4. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTradeTest.java`
   → `ResolvedFxEuropeanOptionTradeTest.java`

### Pricer Tests (4 files)
5. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricerTest.java`
   → `BlackFxEuropeanOptionProductPricerTest.java`

6. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricerTest.java`
   → `BlackFxEuropeanOptionTradePricerTest.java`

7. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricerTest.java`
   → `VannaVolgaFxEuropeanOptionProductPricerTest.java`

(Note: VannaVolgaFxVanillaOptionTradePricerTest may not exist as separate file)

### Measure Tests (4 files)
8. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethodTest.java`
   → `FxEuropeanOptionMethodTest.java`

9. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationsTest.java`
   → `FxEuropeanOptionTradeCalculationsTest.java`

10. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunctionTest.java`
    → `FxEuropeanOptionTradeCalculationFunctionTest.java`

---

## Test Files to UPDATE (10+ files)

These test files import from renamed files but are NOT renamed themselves.

### Product Tests
1. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOptionTest.java`
2. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOptionTradeTest.java`
3. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOptionTest.java`
4. `modules/product/src/test/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOptionTradeTest.java`

### Pricer Tests
5. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricerTest.java`
6. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionTradePricerTest.java`
7. `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxSingleBarrierOptionProductPricerTest.java`

### Measure Tests
8. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionMethodTest.java`
9. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationsTest.java`
10. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationFunctionTest.java`
11. `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxOptionVolatilitiesMarketDataFunctionTest.java`

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Files to rename (main code) | 13 |
| Files to rename (tests) | 14 |
| Total files to rename | 27 |
| Files to update (main code) | 12 |
| Files to update (tests) | 11 |
| Total files to update | 23 |
| **Total files affected** | **~50** |

---

## Implementation Order (Recommended)

### Step 1: Rename Core Classes (4 files)
Rename the core product classes first as all other classes depend on them:
- FxVanillaOption.java
- FxVanillaOptionTrade.java
- ResolvedFxVanillaOption.java
- ResolvedFxVanillaOptionTrade.java

### Step 2: Rename Pricer Classes (4 files)
Rename pricer classes that directly use the core classes:
- BlackFxVanillaOptionProductPricer.java
- BlackFxVanillaOptionTradePricer.java
- VannaVolgaFxVanillaOptionProductPricer.java
- VannaVolgaFxVanillaOptionTradePricer.java

### Step 3: Update Barrier Option Classes (4 files)
Update files that wrap the core/pricer classes:
- FxSingleBarrierOption.java (update type, imports)
- ResolvedFxSingleBarrierOption.java (update type, imports)
- FxSingleBarrierOptionTrade.java (update imports)
- ResolvedFxSingleBarrierOptionTrade.java (update imports)

### Step 4: Rename Measure Classes (4 files)
Rename measure classes that depend on renamed pricers:
- FxVanillaOptionMeasureCalculations.java
- FxVanillaOptionTradeCalculations.java
- FxVanillaOptionTradeCalculationFunction.java
- FxVanillaOptionMethod.java

### Step 5: Update ProductType and CSV (2 files)
Update constants and utilities:
- ProductType.java (rename constant)
- CsvWriterUtils.java (rename method)

### Step 6: Rename CSV Plugin (1 file)
- FxVanillaOptionTradeCsvPlugin.java

### Step 7: Update CSV-related Files (2 files)
- FxSingleBarrierOptionTradeCsvPlugin.java
- TradeCsvLoaderTest.java

### Step 8: Rename Test Files (14 files)
Rename all test files to match renamed classes

### Step 9: Update Test Imports (11 files)
Update imports in tests that reference renamed classes

### Step 10: Verify
- Compile all affected modules
- Run full test suite
- Check for any remaining references to old names

---

## Key Points

1. **Joda-Beans Inner Classes**: Inner `Meta` and `Builder` classes don't need renaming (they're nested), but all references to the outer class name must be updated.

2. **Method Names**: In addition to class names, update all method names that include the old class name (e.g., `writeFxVanillaOption()` → `writeFxEuropeanOption()`).

3. **Constants**: Update both the constant name (`FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`) and its string value (`"FxVanillaOption"` → `"FxEuropeanOption"`).

4. **Documentation**: Update Javadoc comments, class documentation strings, and any comments that refer to "vanilla" to say "European" for consistency.

5. **Test Data**: Check CSV test files for hardcoded product type strings that need updating.

6. **Service Loader**: Check `META-INF/services/` for any plugin registrations that may need updating.

---

## Affected Modules

- `modules/product` - Core product definitions
- `modules/pricer` - Pricing models
- `modules/measure` - Measurement and calculation functions
- `modules/loader` - CSV loading and writing

