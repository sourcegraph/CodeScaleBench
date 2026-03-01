# Implementation Guide: FxVanillaOption → FxEuropeanOption Refactoring

## Summary of Required Changes

This document provides detailed guidance on implementing the complete refactoring with exact code patterns for each category of file.

---

## Phase 1: Core Product Classes (4 Files)

### 1.1 FxVanillaOption → FxEuropeanOption
**File:** `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java`

**Rename to:** `FxEuropeanOption.java`

**Class-level changes:**
- Line 52: `public final class FxVanillaOption` → `public final class FxEuropeanOption`
- Line 53: `implements FxOptionProduct, Resolvable<ResolvedFxVanillaOption>, ImmutableBean, Serializable {`
  - Change to: `implements FxOptionProduct, Resolvable<ResolvedFxEuropeanOption>, ImmutableBean, Serializable {`

**Method-level changes:**
- Line 107-116: `public static FxVanillaOption of(...)` → `public static FxEuropeanOption of(...)`
- Line 133-164: `public static FxVanillaOption of(...)` → `public static FxEuropeanOption of(...)`
- Line 157-163: `return FxVanillaOption.builder()` → `return FxEuropeanOption.builder()`
- Line 202-208: `public ResolvedFxVanillaOption resolve(ReferenceData refData)` → `public ResolvedFxEuropeanOption resolve(ReferenceData refData)`
- Line 203-207: `ResolvedFxVanillaOption.builder()` → `ResolvedFxEuropeanOption.builder()`

**Meta-bean changes:**
- Line 212: `* The meta-bean for {@code FxVanillaOption}.` → `* The meta-bean for {@code FxEuropeanOption}.`
- Line 215: `public static FxVanillaOption.Meta meta()` → `public static FxEuropeanOption.Meta meta()`
- Line 216: `return FxVanillaOption.Meta.INSTANCE;` → `return FxEuropeanOption.Meta.INSTANCE;`
- Line 220: `MetaBean.register(FxVanillaOption.Meta.INSTANCE);` → `MetaBean.register(FxEuropeanOption.Meta.INSTANCE);`
- Line 232: `public static FxVanillaOption.Builder builder()` → `public static FxEuropeanOption.Builder builder()`
- Line 236: `private FxVanillaOption(` → `private FxEuropeanOption(`
- Line 256: `public FxVanillaOption.Meta metaBean()` → `public FxEuropeanOption.Meta metaBean()`
- Line 257: `return FxVanillaOption.Meta.INSTANCE;` → `return FxEuropeanOption.Meta.INSTANCE;`

**Equality/Hash/String changes:**
- Line 331: `FxVanillaOption other = (FxVanillaOption) obj;` → `FxEuropeanOption other = (FxEuropeanOption) obj;`
- Line 355: `buf.append("FxVanillaOption{");` → `buf.append("FxEuropeanOption{");`

**Meta class changes:**
- Line 369: `public static final class Meta extends DirectMetaBean {` stays same (inner class name doesn't change)
- Line 379: `this, "longShort", FxVanillaOption.class, LongShort.class);` → `this, "longShort", FxEuropeanOption.class, LongShort.class);`
- Line 384: `this, "expiryDate", FxVanillaOption.class, LocalDate.class);` → `this, "expiryDate", FxEuropeanOption.class, LocalDate.class);`
- Line 389: `this, "expiryTime", FxVanillaOption.class, LocalTime.class);` → `this, "expiryTime", FxEuropeanOption.class, LocalTime.class);`
- Line 394: `this, "expiryZone", FxVanillaOption.class, ZoneId.class);` → `this, "expiryZone", FxEuropeanOption.class, ZoneId.class);`
- Line 399: `this, "underlying", FxVanillaOption.class, FxSingle.class);` → `this, "underlying", FxEuropeanOption.class, FxSingle.class);`
- Line 435-437: `public FxVanillaOption.Builder builder()` → `public FxEuropeanOption.Builder builder()`
- Line 440-441: `public Class<? extends FxVanillaOption> beanType()` → `public Class<? extends FxEuropeanOption> beanType()`
- Line 441: `return FxVanillaOption.class;` → `return FxEuropeanOption.class;`
- Line 495: `return ((FxVanillaOption) bean).getLongShort();` → `return ((FxEuropeanOption) bean).getLongShort();`
- Line 497: `return ((FxVanillaOption) bean).getExpiryDate();` → `return ((FxEuropeanOption) bean).getExpiryDate();`
- Line 499: `return ((FxVanillaOption) bean).getExpiryTime();` → `return ((FxEuropeanOption) bean).getExpiryTime();`
- Line 501: `return ((FxVanillaOption) bean).getExpiryZone();` → `return ((FxEuropeanOption) bean).getExpiryZone();`
- Line 503: `return ((FxVanillaOption) bean).getUnderlying();` → `return ((FxEuropeanOption) bean).getUnderlying();`

**Builder class changes:**
- Line 523: `public static final class Builder extends DirectFieldsBeanBuilder<FxVanillaOption> {` → `public static final class Builder extends DirectFieldsBeanBuilder<FxEuropeanOption> {`
- Line 541: `private Builder(FxVanillaOption beanToCopy) {` → `private Builder(FxEuropeanOption beanToCopy) {`
- Line 599-605: `public FxVanillaOption build() {` → `public FxEuropeanOption build() {`
- Line 600: `return new FxVanillaOption(` → `return new FxEuropeanOption(`
- Line 679: `buf.append("FxVanillaOption.Builder{");` → `buf.append("FxEuropeanOption.Builder{");`

### 1.2 FxVanillaOptionTrade → FxEuropeanOptionTrade
**File:** `modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java`

**Rename to:** `FxEuropeanOptionTrade.java`

**Key changes:**
- Line 46: `public final class FxVanillaOptionTrade` → `public final class FxEuropeanOptionTrade`
- Line 47: `implements FxOptionTrade, ResolvableTrade<ResolvedFxVanillaOptionTrade>, ImmutableBean, Serializable {` → `implements FxOptionTrade, ResolvableTrade<ResolvedFxEuropeanOptionTrade>, ImmutableBean, Serializable {`
- Line 62: `private final FxVanillaOption product;` → `private final FxEuropeanOption product;`
- Line 80-81: `public FxVanillaOptionTrade withInfo(PortfolioItemInfo info)` → `public FxEuropeanOptionTrade withInfo(PortfolioItemInfo info)`
- Line 81: `return new FxVanillaOptionTrade(TradeInfo.from(info), product, premium);` → `return new FxEuropeanOptionTrade(TradeInfo.from(info), product, premium);`
- Line 100: `this, ProductType.FX_VANILLA_OPTION, buf.toString(), currencyPair.getBase(), currencyPair.getCounter());` → `this, ProductType.FX_EUROPEAN_OPTION, buf.toString(), currencyPair.getBase(), currencyPair.getCounter());`
- Line 104: `public ResolvedFxVanillaOptionTrade resolve(ReferenceData refData)` → `public ResolvedFxEuropeanOptionTrade resolve(ReferenceData refData)`
- Line 105: `return ResolvedFxVanillaOptionTrade.builder()` → `return ResolvedFxEuropeanOptionTrade.builder()`
- Line 117-118: `public static FxVanillaOptionTrade.Meta meta()` and `return FxVanillaOptionTrade.Meta.INSTANCE;` → `FxEuropeanOptionTrade`
- Line 134-135: `public static FxVanillaOptionTrade.Builder builder()` → `public static FxEuropeanOptionTrade.Builder builder()`
- Line 138: `private FxVanillaOptionTrade(` → `private FxEuropeanOptionTrade(`
- Line 140: `FxVanillaOption product,` → `FxEuropeanOption product,`
- Line 151-152: `public FxVanillaOptionTrade.Meta metaBean()` → `public FxEuropeanOptionTrade.Meta metaBean()`
- Line 175: `public FxVanillaOption getProduct()` → `public FxEuropeanOption getProduct()`
- Line 206: `FxVanillaOptionTrade other = (FxVanillaOptionTrade) obj;` → `FxEuropeanOptionTrade other = (FxEuropeanOptionTrade) obj;`
- Line 226: `buf.append("FxVanillaOptionTrade{");` → `buf.append("FxEuropeanOptionTrade{");`
- Line 248: `this, "info", FxVanillaOptionTrade.class, TradeInfo.class);` → `this, "info", FxEuropeanOptionTrade.class, TradeInfo.class);`
- Line 252-253: `this, "product", FxVanillaOptionTrade.class, FxVanillaOption.class);` → `this, "product", FxEuropeanOptionTrade.class, FxEuropeanOption.class);`
- Line 257-258: `this, "premium", FxVanillaOptionTrade.class, AdjustablePayment.class);` → `this, "premium", FxEuropeanOptionTrade.class, AdjustablePayment.class);`
- Line 288-289: `public FxVanillaOptionTrade.Builder builder()` → `public FxEuropeanOptionTrade.Builder builder()`
- Line 293-294: `public Class<? extends FxVanillaOptionTrade> beanType()` → `public Class<? extends FxEuropeanOptionTrade> beanType()`
- Line 294: `return FxVanillaOptionTrade.class;` → `return FxEuropeanOptionTrade.class;`
- Line 332: `return ((FxVanillaOptionTrade) bean).getInfo();` → `return ((FxEuropeanOptionTrade) bean).getInfo();`
- Line 334: `return ((FxVanillaOptionTrade) bean).getProduct();` → `return ((FxEuropeanOptionTrade) bean).getProduct();`
- Line 336: `return ((FxVanillaOptionTrade) bean).getPremium();` → `return ((FxEuropeanOptionTrade) bean).getPremium();`
- Line 356: `public static final class Builder extends DirectFieldsBeanBuilder<FxVanillaOptionTrade> {` → `public static final class Builder extends DirectFieldsBeanBuilder<FxEuropeanOptionTrade> {`
- Line 359: `private FxVanillaOption product;` → `private FxEuropeanOption product;`
- Line 373: `private Builder(FxVanillaOptionTrade beanToCopy) {` → `private Builder(FxEuropeanOptionTrade beanToCopy) {`
- Line 401: `this.product = (FxVanillaOption) newValue;` → `this.product = (FxEuropeanOption) newValue;`
- Line 419: `public FxVanillaOptionTrade build() {` → `public FxEuropeanOptionTrade build() {`
- Line 420: `return new FxVanillaOptionTrade(` → `return new FxEuropeanOptionTrade(`
- Line 447: `public Builder product(FxVanillaOption product) {` → `public Builder product(FxEuropeanOption product) {`
- Line 471: `buf.append("FxVanillaOptionTrade.Builder{");` → `buf.append("FxEuropeanOptionTrade.Builder{");`

### 1.3 & 1.4 ResolvedFxVanillaOption & ResolvedFxVanillaOptionTrade

Apply the same pattern to these files, renaming class names and all references from `FxVanillaOption` to `FxEuropeanOption` and `ResolvedFxVanillaOption` to `ResolvedFxEuropeanOption`.

---

## Phase 2: Pricer Classes (4 Files)

### 2.1 BlackFxVanillaOptionProductPricer → BlackFxEuropeanOptionProductPricer

**File:** `modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java`

**Rename to:** `BlackFxEuropeanOptionProductPricer.java`

**Key changes:**
- Line 30: `public class BlackFxVanillaOptionProductPricer {` → `public class BlackFxEuropeanOptionProductPricer {`
- Line 35: `public static final BlackFxVanillaOptionProductPricer DEFAULT =` → `public static final BlackFxEuropeanOptionProductPricer DEFAULT =`
- Line 36: `new BlackFxVanillaOptionProductPricer(DiscountingFxSingleProductPricer.DEFAULT);` → `new BlackFxEuropeanOptionProductPricer(...)`
- Line 53: `public BlackFxVanillaOptionProductPricer(` → `public BlackFxEuropeanOptionProductPricer(`
- Line 70: `public CurrencyAmount parityValue(ResolvedFxVanillaOption option, RatesProvider ratesProvider)` → `public CurrencyAmount parityValue(ResolvedFxEuropeanOption option, RatesProvider ratesProvider)`
- All method parameters that take `ResolvedFxVanillaOption` should become `ResolvedFxEuropeanOption`

### 2.2 & 2.3 & 2.4 Other Pricer Classes

Apply the same pattern to:
- `BlackFxVanillaOptionTradePricer.java` → `BlackFxEuropeanOptionTradePricer.java`
- `VannaVolgaFxVanillaOptionProductPricer.java` → `VannaVolgaFxEuropeanOptionProductPricer.java`
- `VannaVolgaFxVanillaOptionTradePricer.java` → `VannaVolgaFxEuropeanOptionTradePricer.java`

---

## Phase 3: Measure Classes (4 Files)

### 3.1 FxVanillaOptionMeasureCalculations → FxEuropeanOptionMeasureCalculations

**Key changes:**
- Rename class and file
- Update all imports that reference renamed pricer classes
- Update field declarations

Example:
```java
// Before
private final BlackFxVanillaOptionTradePricer blackPricer;
private final VannaVolgaFxVanillaOptionTradePricer vannaVolgaPricer;

// After
private final BlackFxEuropeanOptionTradePricer blackPricer;
private final VannaVolgaFxEuropeanOptionTradePricer vannaVolgaPricer;
```

### 3.2, 3.3, 3.4 Other Measure Classes

Apply same pattern to:
- `FxVanillaOptionTradeCalculations.java` → `FxEuropeanOptionTradeCalculations.java`
- `FxVanillaOptionTradeCalculationFunction.java` → `FxEuropeanOptionTradeCalculationFunction.java`
- `FxVanillaOptionMethod.java` → `FxEuropeanOptionMethod.java`

---

## Phase 4: Update Files That Import Renamed Classes

### 4.1 FxSingleBarrierOption.java

**Changes needed:**
```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;

private final FxVanillaOption underlyingOption;

public static FxSingleBarrierOption of(FxVanillaOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;

private final FxEuropeanOption underlyingOption;

public static FxSingleBarrierOption of(FxEuropeanOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
```

### 4.2 ResolvedFxSingleBarrierOption.java

```java
// Before
import com.opengamma.strata.product.fxopt.ResolvedFxVanillaOption;

private final ResolvedFxVanillaOption underlyingOption;

public static ResolvedFxSingleBarrierOption of(ResolvedFxVanillaOption underlyingOption, ...

// After
import com.opengamma.strata.product.fxopt.ResolvedFxEuropeanOption;

private final ResolvedFxEuropeanOption underlyingOption;

public static ResolvedFxSingleBarrierOption of(ResolvedFxEuropeanOption underlyingOption, ...
```

### 4.3 BlackFxSingleBarrierOptionProductPricer.java

```java
// Before
import com.opengamma.strata.pricer.fxopt.BlackFxVanillaOptionProductPricer;

private static final BlackFxVanillaOptionProductPricer VANILLA_OPTION_PRICER =
    BlackFxVanillaOptionProductPricer.DEFAULT;

// After
import com.opengamma.strata.pricer.fxopt.BlackFxEuropeanOptionProductPricer;

private static final BlackFxEuropeanOptionProductPricer VANILLA_OPTION_PRICER =
    BlackFxEuropeanOptionProductPricer.DEFAULT;
```

### 4.4 Measure Files Importing Renamed Pricers

Update imports and field declarations in:
- `FxSingleBarrierOptionMeasureCalculations.java`
- All other measure files that reference vanilla pricer classes

---

## Phase 5: Update ProductType Constant

**File:** `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java`

```java
// Before (line ~109)
public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");

// After
public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");
```

---

## Phase 6: Update CSV Files

### 6.1 FxVanillaOptionTradeCsvPlugin.java → FxEuropeanOptionTradeCsvPlugin.java

**Changes:**
- Rename file and class
- Line 58: `class FxVanillaOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxVanillaOptionTrade>` → `class FxEuropeanOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxEuropeanOptionTrade>`
- Line 212: `protected void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product)` → `protected void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product)`
- Update all method implementations that work with FxVanillaOptionTrade

### 6.2 CsvWriterUtils.java

```java
// Before (line ~169)
public static void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {
  FxVanillaOptionTradeCsvPlugin.INSTANCE.writeFxVanillaOption(csv, product);
}

// After
public static void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
  FxEuropeanOptionTradeCsvPlugin.INSTANCE.writeFxEuropeanOption(csv, product);
}
```

Also update imports:
```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;
```

### 6.3 FxSingleBarrierOptionTradeCsvPlugin.java

```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;
```

Update any method calls that reference vanilla option CSV writing.

---

## Phase 7: Update Loader/CSV Plugin Registrations

Check `modules/loader/src/main/resources/META-INF/services/com.opengamma.strata.loader.csv.TradeCsvParserPlugin` for any references to:
- `com.opengamma.strata.loader.csv.FxVanillaOptionTradeCsvPlugin` → `com.opengamma.strata.loader.csv.FxEuropeanOptionTradeCsvPlugin`

---

## Phase 8: Update All Test Files

### 8.1 Test Files to Rename

In `modules/product/src/test/java/com/opengamma/strata/product/fxopt/`:
- `FxVanillaOptionTest.java` → `FxEuropeanOptionTest.java`
- `FxVanillaOptionTradeTest.java` → `FxEuropeanOptionTradeTest.java`
- `ResolvedFxVanillaOptionTest.java` → `ResolvedFxEuropeanOptionTest.java`
- `ResolvedFxVanillaOptionTradeTest.java` → `ResolvedFxEuropeanOptionTradeTest.java`

In `modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/`:
- `BlackFxVanillaOptionProductPricerTest.java` → `BlackFxEuropeanOptionProductPricerTest.java`
- `BlackFxVanillaOptionTradePricerTest.java` → `BlackFxEuropeanOptionTradePricerTest.java`
- `VannaVolgaFxVanillaOptionProductPricerTest.java` → `VannaVolgaFxEuropeanOptionProductPricerTest.java`

In `modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/`:
- `FxVanillaOptionMethodTest.java` → `FxEuropeanOptionMethodTest.java`
- `FxVanillaOptionTradeCalculationsTest.java` → `FxEuropeanOptionTradeCalculationsTest.java`
- `FxVanillaOptionTradeCalculationFunctionTest.java` → `FxEuropeanOptionTradeCalculationFunctionTest.java`

### 8.2 Test Method Updates

Example pattern for all test files:
```java
// Before
public class FxVanillaOptionTest {
  private static FxVanillaOption sut() {
    return FxVanillaOption.builder()...
  }

  public void test_builder() {
    FxVanillaOption test = sut();

// After
public class FxEuropeanOptionTest {
  private static FxEuropeanOption sut() {
    return FxEuropeanOption.builder()...
  }

  public void test_builder() {
    FxEuropeanOption test = sut();
```

### 8.3 Test Import Updates

All test files need import updates:
```java
// Before
import com.opengamma.strata.product.fxopt.FxVanillaOption;
import com.opengamma.strata.product.fxopt.FxVanillaOptionTrade;
import com.opengamma.strata.product.fxopt.ResolvedFxVanillaOption;
import com.opengamma.strata.product.fxopt.ResolvedFxVanillaOptionTrade;

// After
import com.opengamma.strata.product.fxopt.FxEuropeanOption;
import com.opengamma.strata.product.fxopt.FxEuropeanOptionTrade;
import com.opengamma.strata.product.fxopt.ResolvedFxEuropeanOption;
import com.opengamma.strata.product.fxopt.ResolvedFxEuropeanOptionTrade;
```

### 8.4 TradeCsvLoaderTest.java

In `modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java`:

```java
// Before (lines 411-417)
@Test
public void test_load_fx_vanilla_option() {
  TradeCsvLoader standard = TradeCsvLoader.standard();
  ...
  ValueWithFailures<List<FxVanillaOptionTrade>> loadedData = standard.parse(charSources, FxVanillaOptionTrade.class);

// After
@Test
public void test_load_fx_european_option() {
  TradeCsvLoader standard = TradeCsvLoader.standard();
  ...
  ValueWithFailures<List<FxEuropeanOptionTrade>> loadedData = standard.parse(charSources, FxEuropeanOptionTrade.class);
```

And:
```java
// Before (lines 1748-1753)
private FxVanillaOptionTrade expectedFxVanillaOption() {
  return FxVanillaOptionTrade.builder()
      .product(FxVanillaOption.builder()

// After
private FxEuropeanOptionTrade expectedFxEuropeanOption() {
  return FxEuropeanOptionTrade.builder()
      .product(FxEuropeanOption.builder()
```

Also:
```java
// Before (lines 1765-1776)
.product(FxSingleBarrierOption.of(
    expectedFxVanillaOption().getProduct(),

// After
.product(FxSingleBarrierOption.of(
    expectedFxEuropeanOption().getProduct(),
```

---

## Verification Commands

After implementing all changes, verify with:

```bash
# Compile core product module
mvn clean compile -pl modules/product -DskipTests

# Compile pricer module
mvn clean compile -pl modules/pricer -DskipTests

# Compile measure module
mvn clean compile -pl modules/measure -DskipTests

# Compile loader module
mvn clean compile -pl modules/loader -DskipTests

# Run tests for affected modules
mvn test -pl modules/product,modules/pricer,modules/measure,modules/loader
```

---

## Search and Replace Patterns

For efficient batch replacements in your IDE or from command line:

```
FxVanillaOption -> FxEuropeanOption
FxVanillaOptionTrade -> FxEuropeanOptionTrade
ResolvedFxVanillaOption -> ResolvedFxEuropeanOption
ResolvedFxVanillaOptionTrade -> ResolvedFxEuropeanOptionTrade

BlackFxVanillaOptionProductPricer -> BlackFxEuropeanOptionProductPricer
BlackFxVanillaOptionTradePricer -> BlackFxEuropeanOptionTradePricer
VannaVolgaFxVanillaOptionProductPricer -> VannaVolgaFxEuropeanOptionProductPricer
VannaVolgaFxVanillaOptionTradePricer -> VannaVolgaFxEuropeanOptionTradePricer

FxVanillaOptionMeasureCalculations -> FxEuropeanOptionMeasureCalculations
FxVanillaOptionTradeCalculations -> FxEuropeanOptionTradeCalculations
FxVanillaOptionTradeCalculationFunction -> FxEuropeanOptionTradeCalculationFunction
FxVanillaOptionMethod -> FxEuropeanOptionMethod

FxVanillaOptionTradeCsvPlugin -> FxEuropeanOptionTradeCsvPlugin

FX_VANILLA_OPTION -> FX_EUROPEAN_OPTION
"FxVanillaOption" -> "FxEuropeanOption"
"FX Vanilla Option" -> "FX European Option"
```

---

## Final Checklist

- [ ] All 4 core product classes renamed and content updated
- [ ] All 4 pricer classes renamed and content updated
- [ ] All 4 measure classes renamed and content updated
- [ ] FxVanillaOptionTradeCsvPlugin renamed to FxEuropeanOptionTradeCsvPlugin
- [ ] ProductType.FX_VANILLA_OPTION renamed to FX_EUROPEAN_OPTION
- [ ] All ProductType string values updated
- [ ] CsvWriterUtils method renamed
- [ ] FxSingleBarrierOption updated to use FxEuropeanOption
- [ ] ResolvedFxSingleBarrierOption updated to use ResolvedFxEuropeanOption
- [ ] FxSingleBarrierOptionTrade imports updated
- [ ] FxSingleBarrierOptionMeasureCalculations imports updated
- [ ] All 50+ test files renamed and updated
- [ ] All imports across all files updated
- [ ] No references to old names remain
- [ ] Code compiles without errors
- [ ] All tests pass

