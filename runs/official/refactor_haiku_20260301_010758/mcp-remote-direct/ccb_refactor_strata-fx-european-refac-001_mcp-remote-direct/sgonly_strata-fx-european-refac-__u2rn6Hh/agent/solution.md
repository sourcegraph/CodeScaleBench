# Refactoring: Rename FxVanillaOption to FxEuropeanOption

## Summary
This refactoring renames the `FxVanillaOption` type family to `FxEuropeanOption` throughout the OpenGamma Strata codebase to clarify that the option uses European-style exercise (only on expiry date). The refactoring includes renaming 4 core Joda-Beans classes, 4 pricer classes, 4 measure classes, 1 loader plugin, updating 1 ProductType constant, and updating all dependent files.

---

## Files Examined

### Core Product Classes (MUST RENAME FILES)
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java` → `FxEuropeanOption.java` - Core vanilla option class, European-style exercise only
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java` → `FxEuropeanOptionTrade.java` - Trade wrapper for vanilla option
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java` → `ResolvedFxEuropeanOption.java` - Resolved form of vanilla option
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java` → `ResolvedFxEuropeanOptionTrade.java` - Resolved form of vanilla option trade

### Pricer Classes (MUST RENAME FILES)
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java` → `BlackFxEuropeanOptionProductPricer.java` - Black model pricer for vanilla option product
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java` → `BlackFxEuropeanOptionTradePricer.java` - Black model pricer for vanilla option trade
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java` → `VannaVolgaFxEuropeanOptionProductPricer.java` - Vanna-Volga pricer for vanilla option product
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java` → `VannaVolgaFxEuropeanOptionTradePricer.java` - Vanna-Volga pricer for vanilla option trade

### Measure Classes (MUST RENAME FILES)
- `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java` → `FxEuropeanOptionMeasureCalculations.java` - Measure calculations for vanilla option
- `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java` → `FxEuropeanOptionTradeCalculations.java` - High-level trade calculations
- `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java` → `FxEuropeanOptionTradeCalculationFunction.java` - Calculation function for trade analysis
- `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java` → `FxEuropeanOptionMethod.java` - Enum for pricing methods

### Loader/CSV Plugin (MUST RENAME FILE)
- `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java` → `FxEuropeanOptionTradeCsvPlugin.java` - CSV import/export plugin

### Files That Wrap FxVanillaOption (UPDATE IMPORTS/TYPES)
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java` - Wraps FxVanillaOption as underlying
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java` - Wraps ResolvedFxVanillaOption as underlying
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOptionTrade.java` - Contains FxSingleBarrierOption
- `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOptionTrade.java` - Contains ResolvedFxSingleBarrierOption

### Barrier Option Pricers (UPDATE IMPORTS/FIELD NAMES)
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricer.java` - Uses BlackFxVanillaOptionProductPricer
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionTradePricer.java` - Uses BlackFxVanillaOptionTradePricer

### CSV/Utility Files (UPDATE METHOD/CONSTANT REFERENCES)
- `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java` - Update FX_VANILLA_OPTION constant name and value
- `modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java` - Update writeFxVanillaOption method
- `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java` - Imports and method references

### Test Files (50+ files need updates)
All test files in these directories need class name updates in imports, variable declarations, and method calls:
- `modules/product/src/test/java/com/opengamma/strata/product/fxopt/`
- `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/`
- `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/`
- `modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java`

---

## Dependency Chain

### Level 1: Core Definitions
1. `FxVanillaOption` (class definition) - base vanilla option product
2. `FxVanillaOptionTrade` (class definition) - wraps FxVanillaOption in a trade
3. `ResolvedFxVanillaOption` (class definition) - resolved form of FxVanillaOption
4. `ResolvedFxVanillaOptionTrade` (class definition) - resolved form of FxVanillaOptionTrade

### Level 2: Pricer Classes (depend on Level 1)
5. `BlackFxVanillaOptionProductPricer` - prices ResolvedFxVanillaOption
6. `BlackFxVanillaOptionTradePricer` - prices ResolvedFxVanillaOptionTrade
7. `VannaVolgaFxVanillaOptionProductPricer` - prices ResolvedFxVanillaOption
8. `VannaVolgaFxVanillaOptionTradePricer` - prices ResolvedFxVanillaOptionTrade

### Level 3: Barrier Option Classes (depend on Level 1)
9. `FxSingleBarrierOption` - contains `FxVanillaOption underlyingOption` field
10. `ResolvedFxSingleBarrierOption` - contains `ResolvedFxVanillaOption underlyingOption` field
11. `FxSingleBarrierOptionTrade` - contains `FxSingleBarrierOption product` field
12. `ResolvedFxSingleBarrierOptionTrade` - contains `ResolvedFxSingleBarrierOption product` field

### Level 4: Barrier Option Pricers (depend on Level 2)
13. `BlackFxSingleBarrierOptionProductPricer` - uses BlackFxVanillaOptionProductPricer
14. `BlackFxSingleBarrierOptionTradePricer` - uses BlackFxVanillaOptionTradePricer

### Level 5: Measure Calculations (depend on Level 2)
15. `FxVanillaOptionMeasureCalculations` - uses BlackFxVanillaOptionTradePricer and VannaVolgaFxVanillaOptionTradePricer
16. `FxVanillaOptionTradeCalculations` - wraps FxVanillaOptionMeasureCalculations
17. `FxVanillaOptionTradeCalculationFunction` - uses FxVanillaOptionTrade and ResolvedFxVanillaOptionTrade
18. `FxVanillaOptionMethod` - enum for measurement methods (no direct dependency but used alongside pricers)

### Level 6: CSV Plugin (depend on Level 1)
19. `FxVanillaOptionTradeCsvPlugin` - parses/writes FxVanillaOptionTrade

### Level 7: Constants and Utilities (depend on Level 1)
20. `ProductType.FX_VANILLA_OPTION` constant - references FxVanillaOption class name
21. `CsvWriterUtils.writeFxVanillaOption()` - utility for writing FxVanillaOption
22. `FxSingleBarrierOptionTradeCsvPlugin` - imports and references FxVanillaOption

### Level 8: Tests (depend on Levels 1-7)
- 50+ test files in product, pricer, and measure modules

---

## Changes Required

### Change Type 1: File Renames (13 core files)

These files must be renamed and their internal class names updated:

```
FxVanillaOption.java → FxEuropeanOption.java
FxVanillaOptionTrade.java → FxEuropeanOptionTrade.java
ResolvedFxVanillaOption.java → ResolvedFxEuropeanOption.java
ResolvedFxVanillaOptionTrade.java → ResolvedFxEuropeanOptionTrade.java

BlackFxVanillaOptionProductPricer.java → BlackFxEuropeanOptionProductPricer.java
BlackFxVanillaOptionTradePricer.java → BlackFxEuropeanOptionTradePricer.java
VannaVolgaFxVanillaOptionProductPricer.java → VannaVolgaFxEuropeanOptionProductPricer.java
VannaVolgaFxVanillaOptionTradePricer.java → VannaVolgaFxEuropeanOptionTradePricer.java

FxVanillaOptionMeasureCalculations.java → FxEuropeanOptionMeasureCalculations.java
FxVanillaOptionTradeCalculations.java → FxEuropeanOptionTradeCalculations.java
FxVanillaOptionTradeCalculationFunction.java → FxEuropeanOptionTradeCalculationFunction.java
FxVanillaOptionMethod.java → FxEuropeanOptionMethod.java

FxVanillaOptionTradeCsvPlugin.java → FxEuropeanOptionTradeCsvPlugin.java
```

Within each renamed file:
- Update class name: `FxVanillaOption` → `FxEuropeanOption`
- Update all internal references to class name
- Update Meta.INSTANCE references
- Update Builder references
- Update documentation mentioning class name

### Change Type 2: Type Replacements in Product Files

In `FxSingleBarrierOption.java` and `ResolvedFxSingleBarrierOption.java`:
- Replace `FxVanillaOption underlyingOption` → `FxEuropeanOption underlyingOption`
- Replace `ResolvedFxVanillaOption underlyingOption` → `ResolvedFxEuropeanOption underlyingOption`
- Update import statements
- Update method parameter types
- Update builder field references

### Change Type 3: Pricer Import Updates

In barrier option pricers:
- Replace `import com.opengamma.strata.pricer.fxopt.BlackFxVanillaOptionProductPricer;` with `BlackFxEuropeanOptionProductPricer`
- Replace `import com.opengamma.strata.pricer.fxopt.BlackFxVanillaOptionTradePricer;` with `BlackFxEuropeanOptionTradePricer`
- Update field declarations: `private static final BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
- Update object instantiations: `BlackFxVanillaOptionProductPricer.DEFAULT` → `BlackFxEuropeanOptionProductPricer.DEFAULT`

### Change Type 4: ProductType Constant Update

In `ProductType.java`:
- Rename constant: `FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`
- Update string value: `"FxVanillaOption"` → `"FxEuropeanOption"`
- Update display name: `"FX Vanilla Option"` → `"FX European Option"` (optional for clarity)

### Change Type 5: CSV Utility Updates

In `CsvWriterUtils.java`:
- Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
- Update parameter type: `FxVanillaOption` → `FxEuropeanOption`
- Update delegation call to renamed plugin method

### Change Type 6: Measure Calculations

In `FxVanillaOptionMeasureCalculations.java`:
- Update import statements for renamed pricers
- Update field declarations
- Update Javadoc references

In `FxSingleBarrierOptionMeasureCalculations.java`:
- Update imports for renamed barrier pricers if referenced

### Change Type 7: Loader Plugin Integration

Update any registrations that reference the old class:
- Service loader files may need updates (check `META-INF/services/`)

### Change Type 8: All Test Files

Update 50+ test files:
- Rename test classes that follow pattern `FxVanillaOptionXxxTest` → `FxEuropeanOptionXxxTest`
- Update import statements
- Update variable declarations
- Update object creation calls
- Update method references
- Update Javadoc comments

---

## Implementation Strategy

### Phase 1: Rename Core 4 Classes
1. Rename FxVanillaOption.java → FxEuropeanOption.java and update internals
2. Rename FxVanillaOptionTrade.java → FxEuropeanOptionTrade.java and update internals
3. Rename ResolvedFxVanillaOption.java → ResolvedFxEuropeanOption.java and update internals
4. Rename ResolvedFxVanillaOptionTrade.java → ResolvedFxEuropeanOptionTrade.java and update internals

### Phase 2: Update Dependencies on Core 4
1. Update FxSingleBarrierOption.java (type, imports)
2. Update ResolvedFxSingleBarrierOption.java (type, imports)

### Phase 3: Rename Pricer Classes (4 files)
1. Rename BlackFxVanillaOptionProductPricer.java → BlackFxEuropeanOptionProductPricer.java
2. Rename BlackFxVanillaOptionTradePricer.java → BlackFxEuropeanOptionTradePricer.java
3. Rename VannaVolgaFxVanillaOptionProductPricer.java → VannaVolgaFxEuropeanOptionProductPricer.java
4. Rename VannaVolgaFxVanillaOptionTradePricer.java → VannaVolgaFxEuropeanOptionTradePricer.java

### Phase 4: Update Barrier Pricers that use Vanilla Pricers
1. Update BlackFxSingleBarrierOptionProductPricer.java imports and field types
2. Update BlackFxSingleBarrierOptionTradePricer.java imports and field types

### Phase 5: Rename Measure Classes (4 files)
1. Rename FxVanillaOptionMeasureCalculations.java
2. Rename FxVanillaOptionTradeCalculations.java
3. Rename FxVanillaOptionTradeCalculationFunction.java
4. Rename FxVanillaOptionMethod.java

### Phase 6: Update Measure Files that Reference Vanilla
1. Update FxSingleBarrierOptionMeasureCalculations.java if it references vanilla pricers
2. Update measure calculation function registrations

### Phase 7: Update ProductType
1. Rename constant and value in ProductType.java

### Phase 8: Update CSV Files
1. Rename FxVanillaOptionTradeCsvPlugin.java → FxEuropeanOptionTradeCsvPlugin.java
2. Update CsvWriterUtils.java method
3. Update FxSingleBarrierOptionTradeCsvPlugin.java imports

### Phase 9: Update All Tests
1. Update product tests
2. Update pricer tests
3. Update measure tests
4. Update loader tests

---

## Key Considerations

1. **Joda-Beans Inner Classes**: The Meta inner class and Builder inner class within each main class will automatically have their class names updated when the main class is renamed, but the class name string literals within them should remain the same (e.g., `DirectMetaProperty.ofImmutable(this, "property", FxEuropeanOption.class, ...)` - the property name stays the same, just the class reference changes).

2. **Documentation Strings**: Comments and Javadoc mentioning "vanilla" should be updated to "European" to be consistent with the class naming.

3. **ProductType String Value**: The string `"FxVanillaOption"` in `ProductType.of("FxVanillaOption", ...)` is part of the public API and database keys, so changing it may have implications for persistence/serialization. However, since the task explicitly requires this, we'll change it to `"FxEuropeanOption"`.

4. **CSV Headers**: The CSV loader may have hardcoded product type detection. Need to verify and update any CSV test data.

5. **Service Loader Files**: Check `modules/loader/src/main/resources/META-INF/services/` for any plugin registrations.

6. **Backwards Compatibility**: This is a breaking change. No deprecation period is mentioned, so we assume a major version bump is planned.

---

## Affected Areas Summary

| Category | Count | Impact |
|----------|-------|--------|
| Core product classes | 4 | Files renamed + internals updated |
| Pricer classes | 4 | Files renamed + internals updated |
| Measure classes | 4 | Files renamed + internals updated |
| CSV plugin | 1 | File renamed + internal updates |
| Files importing renamed classes | 20+ | Import statements updated |
| Test files | 50+ | Class references and imports updated |
| Constants | 1 | ProductType constant renamed |
| Methods | 1 | CsvWriterUtils.writeFxVanillaOption() renamed |
| **Total affected files** | **~85** | **All Java files in fxopt ecosystem** |

---

## Verification Checklist

- [ ] All 13 core files renamed and internal class names updated
- [ ] All imports updated in dependent files
- [ ] FxSingleBarrierOption updated to use FxEuropeanOption
- [ ] ResolvedFxSingleBarrierOption updated to use ResolvedFxEuropeanOption
- [ ] Barrier pricers updated to use renamed European option pricers
- [ ] ProductType.FX_VANILLA_OPTION renamed to FX_EUROPEAN_OPTION
- [ ] CsvWriterUtils updated with new method name
- [ ] FxVanillaOptionTradeCsvPlugin renamed to FxEuropeanOptionTradeCsvPlugin
- [ ] All test files updated (imports, class names, method references)
- [ ] Code compiles without errors
- [ ] No references to old names remain in codebase

---

## Expected Compilation Success Criteria

After implementing all changes:
- No compilation errors in any Java files
- No unresolved symbol references
- No broken Joda-Beans auto-generated code
- All imports resolve correctly
- Test suite compiles successfully

---

## Code Changes - Detailed Examples

See `/logs/agent/IMPLEMENTATION_GUIDE.md` for comprehensive line-by-line changes for each file type.

### Quick Reference Examples

**Core Product Class (FxVanillaOption.java → FxEuropeanOption.java):**
- Line 52: `public final class FxVanillaOption` → `public final class FxEuropeanOption`
- Line 53: `Resolvable<ResolvedFxVanillaOption>` → `Resolvable<ResolvedFxEuropeanOption>`
- Line 107: `public static FxVanillaOption of(...)` → `public static FxEuropeanOption of(...)`
- Line 157: `return FxVanillaOption.builder()` → `return FxEuropeanOption.builder()`
- Line 202: `public ResolvedFxVanillaOption resolve(...)` → `public ResolvedFxEuropeanOption resolve(...)`
- Lines 215-258: All `FxVanillaOption.Meta` → `FxEuropeanOption.Meta`
- Lines 236-523: All `FxVanillaOption` class references → `FxEuropeanOption`

**Wrapper Class (FxSingleBarrierOption.java):**
```diff
- import com.opengamma.strata.product.fxopt.FxVanillaOption;
- private final FxVanillaOption underlyingOption;
- public static FxSingleBarrierOption of(FxVanillaOption underlyingOption, ...) {
+ import com.opengamma.strata.product.fxopt.FxEuropeanOption;
+ private final FxEuropeanOption underlyingOption;
+ public static FxSingleBarrierOption of(FxEuropeanOption underlyingOption, ...) {
```

**Pricer Class (BlackFxVanillaOptionProductPricer.java → BlackFxEuropeanOptionProductPricer.java):**
```diff
- public class BlackFxVanillaOptionProductPricer {
+ public class BlackFxEuropeanOptionProductPricer {
-   public static final BlackFxVanillaOptionProductPricer DEFAULT =
-       new BlackFxVanillaOptionProductPricer(...);
+   public static final BlackFxEuropeanOptionProductPricer DEFAULT =
+       new BlackFxEuropeanOptionProductPricer(...);
- public CurrencyAmount parityValue(ResolvedFxVanillaOption option, ...)
+ public CurrencyAmount parityValue(ResolvedFxEuropeanOption option, ...)
```

**Measure Class (FxVanillaOptionMeasureCalculations.java → FxEuropeanOptionMeasureCalculations.java):**
```diff
- import com.opengamma.strata.pricer.fxopt.BlackFxVanillaOptionTradePricer;
+ import com.opengamma.strata.pricer.fxopt.BlackFxEuropeanOptionTradePricer;
- private final BlackFxVanillaOptionTradePricer blackPricer;
+ private final BlackFxEuropeanOptionTradePricer blackPricer;
- public static final FxVanillaOptionMeasureCalculations DEFAULT =
-     new FxVanillaOptionMeasureCalculations(
-         BlackFxVanillaOptionTradePricer.DEFAULT,
+ public static final FxEuropeanOptionMeasureCalculations DEFAULT =
+     new FxEuropeanOptionMeasureCalculations(
+         BlackFxEuropeanOptionTradePricer.DEFAULT,
```

**ProductType Constant (ProductType.java):**
```diff
- public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");
+ public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");
```

**CSV Utility (CsvWriterUtils.java):**
```diff
- import com.opengamma.strata.product.fxopt.FxVanillaOption;
- public static void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {
-   FxVanillaOptionTradeCsvPlugin.INSTANCE.writeFxVanillaOption(csv, product);
+ import com.opengamma.strata.product.fxopt.FxEuropeanOption;
+ public static void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
+   FxEuropeanOptionTradeCsvPlugin.INSTANCE.writeFxEuropeanOption(csv, product);
```

**Test File Rename (FxVanillaOptionTest.java → FxEuropeanOptionTest.java):**
```diff
- public class FxVanillaOptionTest {
-   private static FxVanillaOption sut() {
-     return FxVanillaOption.builder()...
-   public void test_builder() {
-     FxVanillaOption test = sut();
+ public class FxEuropeanOptionTest {
+   private static FxEuropeanOption sut() {
+     return FxEuropeanOption.builder()...
+   public void test_builder() {
+     FxEuropeanOption test = sut();
```

For complete line-by-line guidance for all file types, see `IMPLEMENTATION_GUIDE.md`.

---

## Analysis

### Refactoring Strategy

This refactoring follows a **dependency-driven approach** to ensure compilation success at each step:

1. **Rename Core Classes First** - The 4 core Joda-Beans classes (`FxVanillaOption`, `FxVanillaOptionTrade`, `ResolvedFxVanillaOption`, `ResolvedFxVanillaOptionTrade`) form the foundation. Everything else depends on them.

2. **Rename Pricer Classes** - The 4 pricer classes depend directly on core classes. They're renamed second to maintain dependency order.

3. **Update Barrier Option Classes** - `FxSingleBarrierOption` and `ResolvedFxSingleBarrierOption` wrap the core classes, so field types are updated.

4. **Rename Measure Classes** - The 4 measure classes depend on the renamed pricers, so they're renamed third.

5. **Update Constants & Utilities** - `ProductType.FX_VANILLA_OPTION` constant and CSV utility methods are updated.

6. **Rename Tests Last** - All test files are renamed to match their classes and all imports updated.

### Why This Order Matters

```
Phase 1: Core Classes (4 files)
  ↓
Phase 2: Pricers (4 files) - depend on core
  ↓
Phase 3: Measure Classes (4 files) - depend on pricers
  ↓
Phase 4: Update dependent files (20+ files) - import the above
  ↓
Phase 5: Tests (25+ files) - import everything
```

If you attempt to rename measure classes before pricers, the imports will fail. If you rename core classes without updating barrier options, compilation breaks. This dependency chain ensures each phase compiles successfully.

### Areas Impacted

- **Product Module** - Core product classes and wrappers
- **Pricer Module** - Black/Vanna-Volga pricers and barrier pricers
- **Measure Module** - Calculations, functions, and method enums
- **Loader Module** - CSV plugin and utilities
- **Tests** - 50+ test files across all modules

### Backward Compatibility

This is a **breaking change**:
- Public type names change
- Method signatures change
- Constants are renamed
- CSV type strings change (affects persisted data)

This requires a major version bump and migration guide for users upgrading.

