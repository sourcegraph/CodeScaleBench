# FxVanillaOption → FxEuropeanOption Refactoring Analysis

## Task Summary

Rename the `FxVanillaOption` type family to `FxEuropeanOption` throughout the OpenGamma Strata codebase. The refactoring includes:
- 4 core Joda-Beans product classes and their test files
- 4 pricer classes (Black and Vanna Volga)
- 4 measure/calculation classes
- 1 CSV loader plugin
- All dependent files that reference these classes

---

## Files Examined

### Core Product Classes (to rename)
1. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOption.java**
   - Core product definition implementing `FxOptionProduct`, `Resolvable<ResolvedFxVanillaOption>`, `ImmutableBean`
   - Requires: rename class to `FxEuropeanOption`, update resolve() return type to `ResolvedFxEuropeanOption`

2. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTrade.java**
   - Trade wrapper for FxVanillaOption
   - Requires: rename to `FxEuropeanOptionTrade`, update field type and resolve() return type

3. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOption.java**
   - Resolved (pricing-ready) version of the option
   - Requires: rename to `ResolvedFxEuropeanOption`

4. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxVanillaOptionTrade.java**
   - Resolved version of the trade
   - Requires: rename to `ResolvedFxEuropeanOptionTrade`, update field types

### Core Product Test Classes
5. **modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTest.java**
   - Test class for FxVanillaOption
   - Requires: rename to `FxEuropeanOptionTest`, update all imports and references

6. **modules/product/src/test/java/com/opengamma/strata/product/fxopt/FxVanillaOptionTradeTest.java**
   - Test class for FxVanillaOptionTrade
   - Requires: rename to `FxEuropeanOptionTradeTest`, update all imports and references

### Barrier Option Classes (depend on FxVanillaOption)
7. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOption.java**
   - Wraps `FxVanillaOption underlyingOption` field
   - Requires: update import, update field type to `FxEuropeanOption`, update method parameters

8. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOption.java**
   - Contains `ResolvedFxVanillaOption underlyingOption` field
   - Requires: update import, update field type to `ResolvedFxEuropeanOption`

9. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/FxSingleBarrierOptionTrade.java**
   - Inherits file reference, update imports only

10. **modules/product/src/main/java/com/opengamma/strata/product/fxopt/ResolvedFxSingleBarrierOptionTrade.java**
    - Update imports only

### ProductType Constant
11. **modules/product/src/main/java/com/opengamma/strata/product/ProductType.java**
    - Contains: `public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option")`
    - Requires: rename constant to `FX_EUROPEAN_OPTION` and update string value to `"FxEuropeanOption"` and `"FX European Option"`

### Pricer Classes - Black (to rename)
12. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricer.java**
    - Prices FX vanilla options using Black model
    - Requires: rename to `BlackFxEuropeanOptionProductPricer`

13. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricer.java**
    - Trade pricer wrapper for Black FX vanilla options
    - Requires: rename to `BlackFxEuropeanOptionTradePricer`, update all references to product pricer

### Pricer Classes - Vanna Volga (to rename)
14. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricer.java**
    - Prices FX vanilla options using Vanna-Volga model
    - Requires: rename to `VannaVolgaFxEuropeanOptionProductPricer`

15. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricer.java**
    - Trade pricer wrapper for Vanna-Volga FX vanilla options
    - Requires: rename to `VannaVolgaFxEuropeanOptionTradePricer`

### Barrier Pricer Classes (depend on vanilla pricers)
16. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricer.java**
    - Uses `BlackFxVanillaOptionProductPricer VANILLA_OPTION_PRICER` field
    - Requires: update import and field variable to `BlackFxEuropeanOptionProductPricer`

17. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionTradePricer.java**
    - Depends on vanilla trade pricer
    - Requires: update imports and references

### Additional Pricer Classes (use ResolvedFxVanillaOption)
18. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxOptionCalibrator.java**
    - Contains method `calibrateTrinomialTree(ResolvedFxVanillaOption option, ...)`
    - Requires: update parameter type to `ResolvedFxEuropeanOption`, update imports

19. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxSingleBarrierOptionProductPricer.java**
    - Uses `ResolvedFxVanillaOption underlyingOption` from barrier option
    - Requires: update imports (will be automatic through ResolvedFxSingleBarrierOption)

20. **modules/pricer/src/main/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxSingleBarrierOptionTradePricer.java**
    - Uses vanilla option through barrier option
    - Requires: update imports (will be automatic)

### Pricer Test Classes
21. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionProductPricerTest.java**
    - Requires: rename to `BlackFxEuropeanOptionProductPricerTest`

22. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxVanillaOptionTradePricerTest.java**
    - Requires: rename to `BlackFxEuropeanOptionTradePricerTest`

23. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionProductPricerTest.java**
    - Requires: rename to `VannaVolgaFxEuropeanOptionProductPricerTest`

24. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/VannaVolgaFxVanillaOptionTradePricerTest.java** (inferred)
    - Requires: rename to `VannaVolgaFxEuropeanOptionTradePricerTest`

25. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionProductPricerTest.java**
    - Update imports (references `BlackFxVanillaOptionProductPricer`)

26. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/BlackFxSingleBarrierOptionTradePricerTest.java**
    - Update imports

27. **modules/pricer/src/test/java/com/opengamma/strata/pricer/fxopt/ImpliedTrinomialTreeFxSingleBarrierOptionProductPricerTest.java**
    - Update imports if references vanilla pricer

### Measure Classes (to rename)
28. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMeasureCalculations.java**
    - Internal calculations class for measures
    - Requires: rename to `FxEuropeanOptionMeasureCalculations`

29. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculations.java**
    - Public calculations class for measures
    - Requires: rename to `FxEuropeanOptionTradeCalculations`, update internal class reference

30. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethod.java**
    - Enum defining calculation methods (BLACK, VANNA_VOLGA)
    - Requires: rename to `FxEuropeanOptionMethod`, update filter() method to check `FxEuropeanOptionTrade`

31. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunction.java**
    - CalculationFunction implementation
    - Requires: rename to `FxEuropeanOptionTradeCalculationFunction`, update type parameter

### Barrier Measure Classes
32. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionMeasureCalculations.java**
    - No direct rename needed, update imports if references vanilla calculations

33. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculations.java**
    - Update imports only

34. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionMethod.java**
    - Update imports only

35. **modules/measure/src/main/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationFunction.java**
    - Update imports only

### Measure Test Classes
36. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionMethodTest.java**
    - Requires: rename to `FxEuropeanOptionMethodTest`

37. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationsTest.java**
    - Requires: rename to `FxEuropeanOptionTradeCalculationsTest`

38. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxVanillaOptionTradeCalculationFunctionTest.java**
    - Requires: rename to `FxEuropeanOptionTradeCalculationFunctionTest`

39. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionMethodTest.java**
    - Update imports only

40. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationsTest.java**
    - Update imports only

41. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxSingleBarrierOptionTradeCalculationFunctionTest.java**
    - Update imports only

42. **modules/measure/src/test/java/com/opengamma/strata/measure/fxopt/FxOptionVolatilitiesMarketDataFunctionTest.java**
    - Update imports (references `BlackFxVanillaOptionTradePricer`)

### Loader/CSV Classes
43. **modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxVanillaOptionTradeCsvPlugin.java**
    - CSV plugin for loading/writing vanilla option trades
    - Requires: rename to `FxEuropeanOptionTradeCsvPlugin`, update all class references and trade type names

44. **modules/loader/src/main/java/com/opengamma/strata/loader/csv/FxSingleBarrierOptionTradeCsvPlugin.java**
    - Contains import of FxVanillaOption
    - Requires: update import to FxEuropeanOption

45. **modules/loader/src/main/java/com/opengamma/strata/loader/csv/CsvWriterUtils.java**
    - Contains `writeFxVanillaOption()` static method
    - Requires: update method to `writeFxEuropeanOption()`, update parameter type

### Loader Test Classes
46. **modules/loader/src/test/java/com/opengamma/strata/loader/csv/TradeCsvLoaderTest.java**
    - Contains test methods `test_load_fx_vanilla_option()` and `test_load_fx_vanilla_option_equivalent()`
    - Requires: rename methods to `test_load_fx_european_option()` and `test_load_fx_european_option_equivalent()`, update test data

---

## Dependency Chain

### Tier 1: Core Definitions (base classes)
```
FxVanillaOption (definition)
  └─ ResolvedFxVanillaOption (resolved version)

FxVanillaOptionTrade (definition)
  └─ ResolvedFxVanillaOptionTrade (resolved version)
```

### Tier 2: Barrier Options (depend on Tier 1)
```
FxSingleBarrierOption
  └─ uses FxVanillaOption

ResolvedFxSingleBarrierOption
  └─ uses ResolvedFxVanillaOption
```

### Tier 3: Pricers (Black)
```
BlackFxVanillaOptionProductPricer (definition)
  └─ BlackFxVanillaOptionTradePricer (trade wrapper)

BlackFxSingleBarrierOptionProductPricer (definition)
  └─ uses BlackFxVanillaOptionProductPricer
  └─ BlackFxSingleBarrierOptionTradePricer (trade wrapper)
     └─ uses BlackFxVanillaOptionTradePricer
```

### Tier 4: Pricers (Vanna Volga)
```
VannaVolgaFxVanillaOptionProductPricer (definition)
  └─ VannaVolgaFxVanillaOptionTradePricer (trade wrapper)
```

### Tier 5: Measures
```
FxVanillaOptionMeasureCalculations (definition)
  ├─ uses BlackFxVanillaOptionTradePricer
  └─ uses VannaVolgaFxVanillaOptionTradePricer

FxVanillaOptionTradeCalculations (definition)
  └─ uses FxVanillaOptionMeasureCalculations

FxVanillaOptionMethod (enum)
  └─ filters FxVanillaOptionTrade instances

FxVanillaOptionTradeCalculationFunction (definition)
  └─ accepts FxVanillaOptionTrade type parameter
```

### Tier 6: Barrier Measures
```
FxSingleBarrierOptionMeasureCalculations
  └─ uses Black/Trinomial pricers

FxSingleBarrierOptionTradeCalculations
  └─ uses FxSingleBarrierOptionMeasureCalculations
```

### Tier 7: CSV and Constants
```
ProductType.FX_VANILLA_OPTION (constant)
  └─ used by FxVanillaOptionTrade

FxVanillaOptionTradeCsvPlugin (definition)
  ├─ parses FxVanillaOptionTrade
  ├─ registers type names
  └─ uses ProductType.FX_VANILLA_OPTION

CsvWriterUtils.writeFxVanillaOption() (static method)
  └─ delegates to FxVanillaOptionTradeCsvPlugin

FxSingleBarrierOptionTradeCsvPlugin
  └─ imports FxVanillaOption for composition
```

---

## Refactoring Strategy

### Phase 1: Rename Core Product Classes
1. Rename `FxVanillaOption.java` → `FxEuropeanOption.java`
   - Update class declaration
   - Update `implements Resolvable<ResolvedFxEuropeanOption>`
   - Update all factory methods and documentation

2. Rename `ResolvedFxVanillaOption.java` → `ResolvedFxEuropeanOption.java`
   - Update class declaration
   - Update all references to `FxEuropeanOption`

3. Rename `FxVanillaOptionTrade.java` → `FxEuropeanOptionTrade.java`
   - Update class declaration
   - Update field: `FxVanillaOption product` → `FxEuropeanOption product`
   - Update `implements ResolvableTrade<ResolvedFxEuropeanOptionTrade>`
   - Update all factory methods

4. Rename `ResolvedFxVanillaOptionTrade.java` → `ResolvedFxEuropeanOptionTrade.java`
   - Update class declaration
   - Update field type: `ResolvedFxVanillaOption product` → `ResolvedFxEuropeanOption product`

### Phase 2: Update ProductType Constant
5. Update `ProductType.java`
   - Rename constant: `FX_VANILLA_OPTION` → `FX_EUROPEAN_OPTION`
   - Update string value: `"FxVanillaOption"` → `"FxEuropeanOption"`
   - Update description: `"FX Vanilla Option"` → `"FX European Option"`
   - Update JavaDoc comment to reference `FxEuropeanOption`

### Phase 3: Rename Pricer Classes
6. Rename `BlackFxVanillaOptionProductPricer.java` → `BlackFxEuropeanOptionProductPricer.java`

7. Rename `BlackFxVanillaOptionTradePricer.java` → `BlackFxEuropeanOptionTradePricer.java`
   - Update constructor parameter: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
   - Update DEFAULT instance

8. Rename `VannaVolgaFxVanillaOptionProductPricer.java` → `VannaVolgaFxEuropeanOptionProductPricer.java`

9. Rename `VannaVolgaFxVanillaOptionTradePricer.java` → `VannaVolgaFxEuropeanOptionTradePricer.java`
   - Update constructor parameter types

### Phase 4: Update Barrier Pricer Classes
10. Update `BlackFxSingleBarrierOptionProductPricer.java`
    - Update import: `BlackFxVanillaOptionProductPricer` → `BlackFxEuropeanOptionProductPricer`
    - Update field: `VANILLA_OPTION_PRICER` type

11. Update `BlackFxSingleBarrierOptionTradePricer.java`
    - Update imports

12. Similar updates for `ImpliedTrinomialTreeFxSingleBarrierOption*` pricers

### Phase 5: Rename Measure Classes
13. Rename `FxVanillaOptionMeasureCalculations.java` → `FxEuropeanOptionMeasureCalculations.java`
    - Update constructor parameters to use Black/VannaVolga European pricers
    - Update DEFAULT instance

14. Rename `FxVanillaOptionTradeCalculations.java` → `FxEuropeanOptionTradeCalculations.java`
    - Update internal class reference: `FxVanillaOptionMeasureCalculations` → `FxEuropeanOptionMeasureCalculations`
    - Update constructor parameters
    - Update DEFAULT instance

15. Rename `FxVanillaOptionMethod.java` → `FxEuropeanOptionMethod.java`
    - Update enum class name
    - Update filter() method: `target instanceof FxVanillaOptionTrade` → `target instanceof FxEuropeanOptionTrade`
    - Update EnumNames helper

16. Rename `FxVanillaOptionTradeCalculationFunction.java` → `FxEuropeanOptionTradeCalculationFunction.java`
    - Update `implements CalculationFunction<FxEuropeanOptionTrade>`
    - Update references to `FxVanillaOptionMethod` → `FxEuropeanOptionMethod`

### Phase 6: Update Barrier Measure Classes
17. Update barrier measure classes to import from renamed European classes

### Phase 7: Rename CSV and Utility Classes
18. Rename `FxVanillaOptionTradeCsvPlugin.java` → `FxEuropeanOptionTradeCsvPlugin.java`
    - Update class declaration
    - Update `tradeTypeNames()` to return `"FXEUROPEANOPTION"`, `"FX EUROPEAN OPTION"` (or map both old/new for backwards compatibility)
    - Update `writeCsv()` method: `csv.writeCell(TRADE_TYPE_FIELD, "FxEuropeanOption")`
    - Update imports: `FxVanillaOption` → `FxEuropeanOption`, `FxVanillaOptionTrade` → `FxEuropeanOptionTrade`
    - Update method reference: `writeFxEuropeanOption()` instead of `writeFxVanillaOption()`
    - Update INSTANCE singleton reference

19. Update `CsvWriterUtils.java`
    - Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update parameter type: `FxVanillaOption` → `FxEuropeanOption`
    - Update plugin reference: `FxVanillaOptionTradeCsvPlugin` → `FxEuropeanOptionTradeCsvPlugin`
    - Update JavaDoc

20. Update `FxSingleBarrierOptionTradeCsvPlugin.java`
    - Update import: `FxVanillaOption` → `FxEuropeanOption`

### Phase 8: Update All Dependent Files
21. Update `FxSingleBarrierOption.java`
    - Update import: `FxVanillaOption` → `FxEuropeanOption`
    - Update field: `FxVanillaOption underlyingOption` → `FxEuropeanOption underlyingOption`
    - Update method parameters
    - Update JavaDoc

22. Update `ResolvedFxSingleBarrierOption.java`
    - Update import: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`
    - Update field: `ResolvedFxVanillaOption underlyingOption` → `ResolvedFxEuropeanOption underlyingOption`
    - Update factory method parameters

23. Update all test files similarly

---

## Code Changes - Key Examples

### Example 1: FxVanillaOption → FxEuropeanOption

**Before (FxVanillaOption.java, lines 51-53):**
```java
@BeanDefinition
public final class FxVanillaOption
    implements FxOptionProduct, Resolvable<ResolvedFxVanillaOption>, ImmutableBean, Serializable {
```

**After (FxEuropeanOption.java, lines 51-53):**
```java
@BeanDefinition
public final class FxEuropeanOption
    implements FxOptionProduct, Resolvable<ResolvedFxEuropeanOption>, ImmutableBean, Serializable {
```

### Example 2: FxVanillaOptionTrade → FxEuropeanOptionTrade

**Before (FxVanillaOptionTrade.java, lines 45-47):**
```java
@BeanDefinition
public final class FxVanillaOptionTrade
    implements FxOptionTrade, ResolvableTrade<ResolvedFxVanillaOptionTrade>, ImmutableBean, Serializable {
```

**After (FxEuropeanOptionTrade.java, lines 45-47):**
```java
@BeanDefinition
public final class FxEuropeanOptionTrade
    implements FxOptionTrade, ResolvableTrade<ResolvedFxEuropeanOptionTrade>, ImmutableBean, Serializable {
```

**Before (FxVanillaOptionTrade.java, lines 138-141):**
```java
  private FxVanillaOptionTrade(
      TradeInfo info,
      FxVanillaOption product,
      AdjustablePayment premium) {
```

**After (FxEuropeanOptionTrade.java, lines 138-141):**
```java
  private FxEuropeanOptionTrade(
      TradeInfo info,
      FxEuropeanOption product,
      AdjustablePayment premium) {
```

### Example 3: ProductType Constant

**Before (ProductType.java, lines 106-109):**
```java
  /**
   * A {@link FxVanillaOption}.
   */
  public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");
```

**After (ProductType.java, lines 106-109):**
```java
  /**
   * A {@link FxEuropeanOption}.
   */
  public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");
```

### Example 4: FxSingleBarrierOption Updates

**Before (FxSingleBarrierOption.java, lines 56-59):**
```java
  /**
   * The underlying FX vanilla option.
   */
  @PropertyDefinition(validate = "notNull")
  private final FxVanillaOption underlyingOption;
```

**After (FxSingleBarrierOption.java, lines 56-59):**
```java
  /**
   * The underlying FX European option.
   */
  @PropertyDefinition(validate = "notNull")
  private final FxEuropeanOption underlyingOption;
```

**Before (FxSingleBarrierOption.java, lines 89-90):**
```java
  public static FxSingleBarrierOption of(FxVanillaOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
    return new FxSingleBarrierOption(underlyingOption, barrier, rebate);
```

**After (FxSingleBarrierOption.java, lines 89-90):**
```java
  public static FxSingleBarrierOption of(FxEuropeanOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
    return new FxSingleBarrierOption(underlyingOption, barrier, rebate);
```

### Example 5: FxVanillaOptionTradeCsvPlugin → FxEuropeanOptionTradeCsvPlugin

**Before (FxVanillaOptionTradeCsvPlugin.java, lines 55-63):**
```java
/**
 * Handles the CSV file format for FX vanilla option trades.
 */
class FxVanillaOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxVanillaOptionTrade> {

  /**
   * The singleton instance of the plugin.
   */
  public static final FxVanillaOptionTradeCsvPlugin INSTANCE = new FxVanillaOptionTradeCsvPlugin();
```

**After (FxEuropeanOptionTradeCsvPlugin.java, lines 55-63):**
```java
/**
 * Handles the CSV file format for FX European option trades.
 */
class FxEuropeanOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxEuropeanOptionTrade> {

  /**
   * The singleton instance of the plugin.
   */
  public static final FxEuropeanOptionTradeCsvPlugin INSTANCE = new FxEuropeanOptionTradeCsvPlugin();
```

**Before (FxVanillaOptionTradeCsvPlugin.java, lines 88-90):**
```java
  @Override
  public Set<String> tradeTypeNames() {
    return ImmutableSet.of("FXVANILLAOPTION", "FX VANILLA OPTION");
```

**After (FxEuropeanOptionTradeCsvPlugin.java, lines 88-90):**
```java
  @Override
  public Set<String> tradeTypeNames() {
    return ImmutableSet.of("FXEUROPEANOPTION", "FX EUROPEAN OPTION");
```

**Before (FxVanillaOptionTradeCsvPlugin.java, lines 204-208):**
```java
  @Override
  public void writeCsv(CsvRowOutputWithHeaders csv, FxVanillaOptionTrade trade) {
    csv.writeCell(TRADE_TYPE_FIELD, "FxVanillaOption");
    writeFxVanillaOption(csv, trade.getProduct());
    CsvWriterUtils.writePremiumFields(csv, trade.getPremium());
```

**After (FxEuropeanOptionTradeCsvPlugin.java, lines 204-208):**
```java
  @Override
  public void writeCsv(CsvRowOutputWithHeaders csv, FxEuropeanOptionTrade trade) {
    csv.writeCell(TRADE_TYPE_FIELD, "FxEuropeanOption");
    writeFxEuropeanOption(csv, trade.getProduct());
    CsvWriterUtils.writePremiumFields(csv, trade.getPremium());
```

### Example 6: Measure Class Updates

**Before (FxVanillaOptionTradeCalculations.java, lines 28-35):**
```java
/**
 * <p>
 * Each method takes a {@link ResolvedFxVanillaOptionTrade}, whereas application code will
 * typically work with {@link FxVanillaOptionTrade}. Call
 * {@link FxVanillaOptionTrade#resolve(com.opengamma.strata.basics.ReferenceData) FxVanillaOptionTrade::resolve(ReferenceData)}
 * to convert {@code FxVanillaOptionTrade} to {@code ResolvedFxVanillaOptionTrade}.
 */
public class FxVanillaOptionTradeCalculations {
```

**After (FxEuropeanOptionTradeCalculations.java, lines 28-35):**
```java
/**
 * <p>
 * Each method takes a {@link ResolvedFxEuropeanOptionTrade}, whereas application code will
 * typically work with {@link FxEuropeanOptionTrade}. Call
 * {@link FxEuropeanOptionTrade#resolve(com.opengamma.strata.basics.ReferenceData) FxEuropeanOptionTrade::resolve(ReferenceData)}
 * to convert {@code FxEuropeanOptionTrade} to {@code ResolvedFxEuropeanOptionTrade}.
 */
public class FxEuropeanOptionTradeCalculations {
```

---

## Analysis

### Refactoring Scope

This refactoring is **comprehensive and touches 45+ files** across 4 major subsystems:

1. **Product Module (8 files)**: Core class definitions and constants
2. **Pricer Module (19+ files)**: Pricing implementations and tests
3. **Measure Module (14+ files)**: Risk calculations and measure functions
4. **Loader Module (4+ files)**: CSV serialization and persistence

### Key Characteristics

1. **Joda-Beans Integration**: All `@BeanDefinition` annotated classes will automatically regenerate their `Meta` inner classes and `Builder` classes. The Joda-Beans generator will handle:
   - Meta property declarations
   - Builder field initializations
   - Equals/hashCode/toString implementations
   - Property getters/setters

2. **Cascading Dependencies**: Changes must follow dependency order:
   - Core product classes must be renamed first
   - Then barrier products that depend on them
   - Then pricers
   - Finally measures and loaders

3. **Test Files**: All test classes must be renamed to match their respective main classes:
   - `FxVanillaOptionTest` → `FxEuropeanOptionTest`
   - `FxVanillaOptionTradeTest` → `FxEuropeanOptionTradeTest`
   - etc.

4. **Backward Compatibility Considerations**:
   - CSV trade type names can be updated to support both old and new names if needed
   - The `ProductType.FX_VANILLA_OPTION` constant should be changed (no backward compatibility)

### Implementation Strategy

**Order of Changes** (bottom-up dependency approach):

1. **Rename core product classes** (files 1-4)
   - Compile and verify no immediate errors
2. **Update ProductType constant** (file 11)
3. **Rename all pricer classes** (files 12-15)
4. **Update barrier product classes** (files 7-10)
5. **Update barrier pricer classes** (files 16-19)
6. **Rename all measure classes** (files 27-30)
7. **Update barrier measure classes** (files 31-34)
8. **Rename CSV plugin and utilities** (files 42-44)
9. **Update all test files** (files 5-6, 20-26, 35-41, 45)

### Verification Approach

1. **Compilation**: Run `mvn clean compile` on affected modules to verify no compilation errors
2. **Test Suite**: Run `mvn test` on all affected modules to verify behavior is preserved
3. **Import Analysis**: Use IDE "Find All References" on each renamed class to catch any missed references
4. **String References**: Search for hardcoded strings like "FxVanillaOption" in configuration files, documentation, or resource bundles

### Risk Assessment

**Low Risk**:
- Clear class renames with compiler feedback
- Joda-Beans auto-generation handles boilerplate
- Existing tests can be adapted

**Moderate Risk**:
- CSV serialization format changes (mitigation: version handling in plugins)
- Multiple files to update (mitigation: systematic file-by-file approach)

**Verification Success Criteria**:
- Zero compilation errors after full refactoring
- All unit tests pass
- No dangling references to old class names
- CSV load/save roundtrips work correctly

---

## Files Summary

| Category | Count | Status |
|----------|-------|--------|
| Product Classes (to rename) | 4 | Core |
| Product Test Classes | 2 | Test |
| Barrier Product Classes | 4 | Dependent |
| ProductType Constants | 1 | Update |
| Pricer Classes (to rename) | 4 | Core |
| Barrier/Other Pricer Classes | 5 | Dependent |
| Pricer Test Classes | 7 | Test |
| Measure Classes (to rename) | 4 | Core |
| Barrier Measure Classes | 4 | Dependent |
| Measure Test Classes | 7 | Test |
| CSV/Loader Classes | 3 | Core |
| Loader Test Classes | 1 | Test |
| **TOTAL** | **~46** | **Multiple subsystems** |

---

## Expected Outcomes

After successful refactoring:

1. **API Change**: Public classes renamed:
   - `com.opengamma.strata.product.fxopt.FxVanillaOption` → `com.opengamma.strata.product.fxopt.FxEuropeanOption`
   - `com.opengamma.strata.product.fxopt.FxVanillaOptionTrade` → `com.opengamma.strata.product.fxopt.FxEuropeanOptionTrade`
   - And all associated Resolved* variants

2. **Semantic Improvement**:
   - "European" exercise style now explicit in type name
   - Disambiguates from potential future American/Bermudan options
   - Improves code clarity and API discoverability

3. **No Functional Changes**:
   - Behavior remains identical
   - All pricing calculations preserved
   - CSV format can remain compatible with versioning

---

## Notes

- This is a **breaking change** for any code that imports or uses these classes
- The refactoring should be applied as a **single atomic commit** to maintain consistency
- CSV backward compatibility can be achieved by supporting both old and new trade type names during parsing
- Consider updating any external documentation or user guides that reference `FxVanillaOption`
