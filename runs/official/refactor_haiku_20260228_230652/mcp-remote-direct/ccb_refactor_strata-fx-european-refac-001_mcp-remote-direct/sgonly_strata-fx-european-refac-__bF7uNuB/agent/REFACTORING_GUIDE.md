# FxVanillaOption → FxEuropeanOption Refactoring Guide

## Overview

This document provides a systematic guide for implementing the FxVanillaOption → FxEuropeanOption refactoring across 45+ files in the OpenGamma Strata codebase.

## Changes by Phase

### PHASE 1: Core Product Classes (4 files)

Files to modify:
1. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java`
2. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java`
3. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java`
4. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java`

#### Change Patterns:

**Class Declaration:**
```java
// Before
public final class FxVanillaOption implements FxOptionProduct, Resolvable<ResolvedFxVanillaOption>, ...

// After
public final class FxEuropeanOption implements FxOptionProduct, Resolvable<ResolvedFxEuropeanOption>, ...
```

**Factory Methods:**
```java
// Before (FxVanillaOption.java)
public static FxVanillaOption of(...) {
    return FxVanillaOption.builder()...
}

// After (FxEuropeanOption.java)
public static FxEuropeanOption of(...) {
    return FxEuropeanOption.builder()...
}
```

**Meta Inner Class:**
```java
// Before
public static FxVanillaOption.Meta meta() {
    return FxVanillaOption.Meta.INSTANCE;
}

// After
public static FxEuropeanOption.Meta meta() {
    return FxEuropeanOption.Meta.INSTANCE;
}
```

**Meta Inner Class Definition:**
```java
// Before
public static final class Meta extends DirectMetaBean {
    static final Meta INSTANCE = new Meta();
    private final MetaProperty<FxVanillaOption> product = DirectMetaProperty.ofImmutable(
        this, "product", FxVanillaOptionTrade.class, FxVanillaOption.class);

// After
public static final class Meta extends DirectMetaBean {
    static final Meta INSTANCE = new Meta();
    private final MetaProperty<FxEuropeanOption> product = DirectMetaProperty.ofImmutable(
        this, "product", FxEuropeanOptionTrade.class, FxEuropeanOption.class);
```

**Builder Inner Class:**
```java
// Before
public static final class Builder extends DirectFieldsBeanBuilder<FxVanillaOption> {
    private FxVanillaOption beanToCopy

// After
public static final class Builder extends DirectFieldsBeanBuilder<FxEuropeanOption> {
    private FxEuropeanOption beanToCopy
```

**Resolve Method:**
```java
// Before (FxVanillaOptionTrade.java)
public ResolvedFxVanillaOptionTrade resolve(ReferenceData refData) {
    return ResolvedFxVanillaOptionTrade.builder()...

// After (FxEuropeanOptionTrade.java)
public ResolvedFxEuropeanOptionTrade resolve(ReferenceData refData) {
    return ResolvedFxEuropeanOptionTrade.builder()...
```

**Field Types:**
```java
// Before (FxVanillaOptionTrade.java)
private final FxVanillaOption product;

// After (FxEuropeanOptionTrade.java)
private final FxEuropeanOption product;
```

**Docstrings:**
```java
// Before
/**
 * An FX option is a financial instrument that provides an option based on the future value of a foreign exchange. The
 * option is European, exercised only on the exercise date.
 */
public final class FxVanillaOption

// After
/**
 * An FX option is a financial instrument that provides an option based on the future value of a foreign exchange. The
 * option is European, exercised only on the exercise date.
 */
public final class FxEuropeanOption
```

### PHASE 2: Product Type Constant (1 file)

File: `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java`

```java
// Before (line 109)
public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");

// After
public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");

// Also update docstring:
// Before
/**
 * A {@link FxVanillaOption}.
 */

// After
/**
 * A {@link FxEuropeanOption}.
 */
```

Update usages throughout codebase:
```java
// Before
ProductType.FX_VANILLA_OPTION

// After
ProductType.FX_EUROPEAN_OPTION
```

### PHASE 3: Pricer Classes (4 files)

Files:
1. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java`
2. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java`
3. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java`
4. `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java`

**Class Renaming:**
```java
// BlackFxVanillaOptionProductPricer.java
// Before
public class BlackFxVanillaOptionProductPricer {
    public MultiCurrencyAmount presentValue(
        ResolvedFxVanillaOption option, ...

// After
public class BlackFxEuropeanOptionProductPricer {
    public MultiCurrencyAmount presentValue(
        ResolvedFxEuropeanOption option, ...
```

**Trade Pricer:**
```java
// BlackFxVanillaOptionTradePricer.java
// Before
public class BlackFxVanillaOptionTradePricer {
    private final BlackFxVanillaOptionProductPricer productPricer;
    public static final BlackFxVanillaOptionTradePricer DEFAULT = new BlackFxVanillaOptionTradePricer(
        BlackFxVanillaOptionProductPricer.DEFAULT, ...

// After
public class BlackFxEuropeanOptionTradePricer {
    private final BlackFxEuropeanOptionProductPricer productPricer;
    public static final BlackFxEuropeanOptionTradePricer DEFAULT = new BlackFxEuropeanOptionTradePricer(
        BlackFxEuropeanOptionProductPricer.DEFAULT, ...
```

**Method Signatures:**
```java
// Before
public MultiCurrencyAmount presentValue(
    ResolvedFxVanillaOptionTrade trade,
    RatesProvider ratesProvider, ...

// After
public MultiCurrencyAmount presentValue(
    ResolvedFxEuropeanOptionTrade trade,
    RatesProvider ratesProvider, ...
```

### PHASE 4: Measure Classes (4 files)

Files:
1. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java`
2. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java`
3. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java`
4. `modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java`

**Class Renaming:**
```java
// FxVanillaOptionMeasureCalculations.java
// Before
final class FxVanillaOptionMeasureCalculations {
    private final BlackFxVanillaOptionTradePricer blackPricer;
    private final VannaVolgaFxVanillaOptionTradePricer vannaVolgaPricer;

// After
final class FxEuropeanOptionMeasureCalculations {
    private final BlackFxEuropeanOptionTradePricer blackPricer;
    private final VannaVolgaFxEuropeanOptionTradePricer vannaVolgaPricer;
```

**TradeCalculations:**
```java
// FxVanillaOptionTradeCalculations.java
// Before
public class FxVanillaOptionTradeCalculations {
    public static final FxVanillaOptionTradeCalculations DEFAULT = new FxVanillaOptionTradeCalculations(
        BlackFxVanillaOptionTradePricer.DEFAULT,
        VannaVolgaFxVanillaOptionTradePricer.DEFAULT);

    public FxVanillaOptionTradeCalculations(
        BlackFxVanillaOptionTradePricer blackPricer,
        VannaVolgaFxVanillaOptionTradePricer vannaVolgaPricer) {
        this.calc = new FxVanillaOptionMeasureCalculations(blackPricer, vannaVolgaPricer);
    }

// After
public class FxEuropeanOptionTradeCalculations {
    public static final FxEuropeanOptionTradeCalculations DEFAULT = new FxEuropeanOptionTradeCalculations(
        BlackFxEuropeanOptionTradePricer.DEFAULT,
        VannaVolgaFxEuropeanOptionTradePricer.DEFAULT);

    public FxEuropeanOptionTradeCalculations(
        BlackFxEuropeanOptionTradePricer blackPricer,
        VannaVolgaFxEuropeanOptionTradePricer vannaVolgaPricer) {
        this.calc = new FxEuropeanOptionMeasureCalculations(blackPricer, vannaVolgaPricer);
    }
```

**TradeCalculationFunction:**
```java
// FxVanillaOptionTradeCalculationFunction.java
// Before
public class FxVanillaOptionTradeCalculationFunction
    implements CalculationFunction<FxVanillaOptionTrade> {

    private FxVanillaOptionTradeCalculations calculations;

// After
public class FxEuropeanOptionTradeCalculationFunction
    implements CalculationFunction<FxEuropeanOptionTrade> {

    private FxEuropeanOptionTradeCalculations calculations;
```

**Enum:**
```java
// FxVanillaOptionMethod.java
// Before
public enum FxVanillaOptionMethod implements NamedEnum, CalculationParameter {
    BLACK,
    VANNA_VOLGA;

    private static final EnumNames<FxVanillaOptionMethod> NAMES = EnumNames.of(FxVanillaOptionMethod.class);

// After
public enum FxEuropeanOptionMethod implements NamedEnum, CalculationParameter {
    BLACK,
    VANNA_VOLGA;

    private static final EnumNames<FxEuropeanOptionMethod> NAMES = EnumNames.of(FxEuropeanOptionMethod.class);
```

**Method Parameter Types:**
```java
// In FxVanillaOptionTradeCalculations and FxVanillaOptionMeasureCalculations
// Before
public MultiCurrencyAmount presentValue(
    ResolvedFxVanillaOptionTrade trade,
    RatesScenarioMarketData ratesMarketData,
    FxVanillaOptionMethod method) {

// After
public MultiCurrencyAmount presentValue(
    ResolvedFxEuropeanOptionTrade trade,
    RatesScenarioMarketData ratesMarketData,
    FxEuropeanOptionMethod method) {
```

### PHASE 5: Loader/CSV Classes (2 files)

Files:
1. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java`
2. `modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java`

**CSV Plugin Class:**
```java
// FxVanillaOptionTradeCsvPlugin.java
// Before
class FxVanillaOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxVanillaOptionTrade> {
    private static final String TRADE_TYPE_FIELD = "FxVanillaOption";
    protected void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {

// After
class FxEuropeanOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxEuropeanOptionTrade> {
    private static final String TRADE_TYPE_FIELD = "FxEuropeanOption";
    protected void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
```

**CsvWriterUtils:**
```java
// CsvWriterUtils.java
// Before
public static void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {
    FxVanillaOptionTradeCsvPlugin.INSTANCE.writeFxVanillaOption(csv, product);
}

// After
public static void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
    FxEuropeanOptionTradeCsvPlugin.INSTANCE.writeFxEuropeanOption(csv, product);
}
```

### PHASE 6: Dependent Product Classes (2 files)

Files:
1. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java`
2. `modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java`

**Field Types:**
```java
// FxSingleBarrierOption.java
// Before
private final FxVanillaOption underlyingOption;
public static FxSingleBarrierOption of(FxVanillaOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {

// After
private final FxEuropeanOption underlyingOption;
public static FxSingleBarrierOption of(FxEuropeanOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
```

**Resolved Barrier:**
```java
// ResolvedFxSingleBarrierOption.java
// Before
private final ResolvedFxVanillaOption underlyingOption;
public static ResolvedFxSingleBarrierOption of(
    ResolvedFxVanillaOption underlyingOption,

// After
private final ResolvedFxEuropeanOption underlyingOption;
public static ResolvedFxSingleBarrierOption of(
    ResolvedFxEuropeanOption underlyingOption,
```

### PHASE 7: Dependent CSV Plugin (1 file)

File: `modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java`

```java
// Before
CsvWriterUtils.writeFxVanillaOption(csv, product.getUnderlyingOption());

// After
CsvWriterUtils.writeFxEuropeanOption(csv, product.getUnderlyingOption());
```

Also update import:
```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;
```

### PHASE 8: Dependent Barrier Pricers (2+ files)

File: `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricer.java`

```java
// Before
private static final BlackFxVanillaOptionProductPricer VANILLA_OPTION_PRICER =
    BlackFxVanillaOptionProductPricer.DEFAULT;

// After
private static final BlackFxEuropeanOptionProductPricer EUROPEAN_OPTION_PRICER =
    BlackFxEuropeanOptionProductPricer.DEFAULT;
```

### PHASE 9: Update Test Files (15+ files)

All test files referencing the renamed classes need updates:

**Test Class Names (optional, but recommended for clarity):**
- `FxVanillaOptionTest` → `FxEuropeanOptionTest`
- `FxVanillaOptionTradeTest` → `FxEuropeanOptionTradeTest`
- `ResolvedFxVanillaOptionTradeTest` → `ResolvedFxEuropeanOptionTradeTest`
- `BlackFxVanillaOptionProductPricerTest` → `BlackFxEuropeanOptionProductPricerTest`
- `BlackFxVanillaOptionTradePricerTest` → `BlackFxEuropeanOptionTradePricerTest`
- etc.

**Within Test Files:**
```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;
import com.opengamma.strata.product.fxopt.FxVanillaOptionTrade;

private static final FxVanillaOption PRODUCT = FxVanillaOptionTest.sut();
FxVanillaOptionTrade test = sut();

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;
import com.opengamma.strata.product.fxopt.FxEuropeanOptionTrade;

private static final FxEuropeanOption PRODUCT = FxEuropeanOptionTest.sut();
FxEuropeanOptionTrade test = sut();
```

## String Replacements Summary

### Global Find and Replace Operations (in order):

1. **Class names (exact match)**:
   - `FxVanillaOption.Meta` → `FxEuropeanOption.Meta`
   - `FxVanillaOption.Builder` → `FxEuropeanOption.Builder`
   - `class FxVanillaOption` → `class FxEuropeanOption`
   - `class FxVanillaOptionTrade` → `class FxEuropeanOptionTrade`
   - `class ResolvedFxVanillaOption` → `class ResolvedFxEuropeanOption`
   - `class ResolvedFxVanillaOptionTrade` → `class ResolvedFxEuropeanOptionTrade`
   - `class BlackFxVanillaOptionProductPricer` → `class BlackFxEuropeanOptionProductPricer`
   - `class BlackFxVanillaOptionTradePricer` → `class BlackFxEuropeanOptionTradePricer`
   - `class VannaVolgaFxVanillaOptionProductPricer` → `class VannaVolgaFxEuropeanOptionProductPricer`
   - `class VannaVolgaFxVanillaOptionTradePricer` → `class VannaVolgaFxEuropeanOptionTradePricer`
   - `class FxVanillaOptionMeasureCalculations` → `class FxEuropeanOptionMeasureCalculations`
   - `class FxVanillaOptionTradeCalculations` → `class FxEuropeanOptionTradeCalculations`
   - `class FxVanillaOptionTradeCalculationFunction` → `class FxEuropeanOptionTradeCalculationFunction`
   - `enum FxVanillaOptionMethod` → `enum FxEuropeanOptionMethod`
   - `class FxVanillaOptionTradeCsvPlugin` → `class FxEuropeanOptionTradeCsvPlugin`

2. **Method names**:
   - `writeFxVanillaOption` → `writeFxEuropeanOption`

3. **Constant names**:
   - `FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`

4. **String literals**:
   - `"FxVanillaOption"` → `"FxEuropeanOption"` (in CSV type field, ProductType.of() calls)
   - `"FX Vanilla Option"` → `"FX European Option"`

5. **Generic type parameters and imports**:
   - `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption` (in angle brackets)
   - `ResolvedFxVanillaOptionTrade` → `ResolvedFxEuropeanOptionTrade`
   - `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`
   - `FxVanillaOption` → `FxEuropeanOption`

## Variable Renaming

Consider renaming variables for clarity (optional but recommended):
- `VANILLA_OPTION_PRICER` → `EUROPEAN_OPTION_PRICER`
- `vanillaOptionPricer` → `europeanOptionPricer`
- `RTRADE` in FxVanillaOptionTradeCalculationFunctionTest uses generic name, can stay

## Verification Steps

1. Search for remaining `FxVanillaOption` (should return 0)
2. Search for remaining `FX_VANILLA_OPTION` constant (should return 0)
3. Verify all imports updated
4. Run compilation check
5. Run test suite
6. Verify CSV loading still works

## Files Checklist

### Core Product (4)
- [ ] FxVanillaOption.java → FxEuropeanOption.java
- [ ] FxVanillaOptionTrade.java → FxEuropeanOptionTrade.java
- [ ] ResolvedFxVanillaOption.java → ResolvedFxEuropeanOption.java
- [ ] ResolvedFxVanillaOptionTrade.java → ResolvedFxEuropeanOptionTrade.java

### ProductType (1)
- [ ] ProductType.java

### Pricers (4)
- [ ] BlackFxVanillaOptionProductPricer.java → BlackFxEuropeanOptionProductPricer.java
- [ ] BlackFxVanillaOptionTradePricer.java → BlackFxEuropeanOptionTradePricer.java
- [ ] VannaVolgaFxVanillaOptionProductPricer.java → VannaVolgaFxEuropeanOptionProductPricer.java
- [ ] VannaVolgaFxVanillaOptionTradePricer.java → VannaVolgaFxEuropeanOptionTradePricer.java

### Measures (4)
- [ ] FxVanillaOptionMeasureCalculations.java → FxEuropeanOptionMeasureCalculations.java
- [ ] FxVanillaOptionTradeCalculations.java → FxEuropeanOptionTradeCalculations.java
- [ ] FxVanillaOptionTradeCalculationFunction.java → FxEuropeanOptionTradeCalculationFunction.java
- [ ] FxVanillaOptionMethod.java → FxEuropeanOptionMethod.java

### Loaders (2)
- [ ] FxVanillaOptionTradeCsvPlugin.java → FxEuropeanOptionTradeCsvPlugin.java
- [ ] CsvWriterUtils.java (update method)

### Dependent Products (2)
- [ ] FxSingleBarrierOption.java
- [ ] ResolvedFxSingleBarrierOption.java

### Dependent CSV (1)
- [ ] FxSingleBarrierOptionTradeCsvPlugin.java

### Dependent Pricers (2+)
- [ ] BlackFxSingleBarrierOptionProductPricer.java
- [ ] ImpliedTrinomialTreeFxSingleBarrierOptionProductPricer.java (verify)

### Tests (15+)
- [ ] FxVanillaOptionTest.java → FxEuropeanOptionTest.java
- [ ] FxVanillaOptionTradeTest.java → FxEuropeanOptionTradeTest.java
- [ ] ResolvedFxVanillaOptionTradeTest.java → ResolvedFxEuropeanOptionTradeTest.java
- [ ] BlackFxVanillaOptionProductPricerTest.java → BlackFxEuropeanOptionProductPricerTest.java
- [ ] BlackFxVanillaOptionTradePricerTest.java → BlackFxEuropeanOptionTradePricerTest.java
- [ ] VannaVolgaFxVanillaOptionProductPricerTest.java → VannaVolgaFxEuropeanOptionProductPricerTest.java
- [ ] VannaVolgaFxVanillaOptionTradePricerTest.java → VannaVolgaFxEuropeanOptionTradePricerTest.java
- [ ] FxVanillaOptionMethodTest.java → FxEuropeanOptionMethodTest.java
- [ ] FxVanillaOptionTradeCalculationsTest.java → FxEuropeanOptionTradeCalculationsTest.java
- [ ] FxVanillaOptionTradeCalculationFunctionTest.java → FxEuropeanOptionTradeCalculationFunctionTest.java
- [ ] TradeCsvLoaderTest.java (update method calls and assertions)
- [ ] FxOptionVolatilitiesMarketDataFunctionTest.java (update test data)
- [ ] FxSingleBarrierOptionTest.java (update field references)
- [ ] FxSingleBarrierOptionTradeTest.java (update field references)
- [ ] BlackFxSingleBarrierOptionProductPricerTest.java
- [ ] ImpliedTrinomialTreeFxSingleBarrierOptionProductPricerTest.java

## Tools and Approach

### IDE-Based Approach (Recommended)
Use IDE "Rename" functionality:
1. Open IntelliJ IDEA / Eclipse
2. For each class, use "Refactor → Rename"
3. This automatically updates all references across the project

### Script-Based Approach
Create a shell script with multiple sed/grep operations:
```bash
#!/bin/bash

# Phase 1: Core classes
find modules/product -name "FxVanillaOption.java" -exec rename 's/FxVanillaOption/FxEuropeanOption/' {} \;
find modules/product -name "FxVanillaOptionTrade.java" -exec rename 's/FxVanillaOptionTrade/FxEuropeanOptionTrade/' {} \;
# ... etc for other classes

# Phase 2: Update content in all renamed files
sed -i 's/class FxVanillaOption/class FxEuropeanOption/g' modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxEuropeanOption.java
# ... etc for all files

# Phase 3: Update references in dependent files
sed -i 's/FxVanillaOption/FxEuropeanOption/g' modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java
# ... etc for all dependent files
```

### Manual Approach
For maximum control, manually edit each file:
1. Copy the pattern examples from this guide
2. Apply to each file systematically
3. Verify changes with grep before and after

## Potential Issues and Mitigations

### Issue: Joda-Bean Code Generation
**Problem**: Joda-Bean auto-generates Meta and Builder classes
**Mitigation**: Manually update all references to these classes in the generated code sections (lines marked AUTOGENERATED)

### Issue: Type Erasure in Generics
**Problem**: `ResolvedFxVanillaOption` appears as generic type parameter
**Mitigation**: Search for `<Resolved` and `<FxVanillaOption` patterns to catch all occurrences

### Issue: String Constants in CSV Loading
**Problem**: CSV files reference `"FxVanillaOption"` as trade type
**Mitigation**: Update `FxVanillaOptionTradeCsvPlugin` to use `"FxEuropeanOption"` string

### Issue: Test Fixtures
**Problem**: Tests create test objects of renamed classes
**Mitigation**: Update all builder calls and test method creation code

### Issue: Transitive Dependencies
**Problem**: Classes dependent on barrier option pricers also need updates
**Mitigation**: Verify all direct and transitive imports/usages are updated

## Expected Test Results

After completing the refactoring, all tests should pass:
```
mvn test -pl modules/product -Dtest="FxEuropeanOption*"
mvn test -pl modules/pricer -Dtest="*FxEuropeanOption*"
mvn test -pl modules/measure -Dtest="*FxEuropeanOption*"
mvn test -pl modules/loader -Dtest="*TradeCsvLoaderTest"
```

## Backward Compatibility Notes

This is a **breaking API change**:
- All public class names have changed
- All method signatures using these classes have changed
- Existing client code must be updated to use new names

**No automatic migration** is possible due to the scope of changes.

## Performance Considerations

- No performance impact (purely mechanical refactoring)
- No behavior changes
- Same object sizes and memory footprints

## Documentation Updates Needed

- Update API documentation
- Update migration guide for users
- Update architectural diagrams if they reference FxVanillaOption
