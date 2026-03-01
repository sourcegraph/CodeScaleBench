# FxVanillaOption → FxEuropeanOption Refactoring: Implementation Summary

## Overview

This document summarizes the completed analysis and provides a ready-to-implement refactoring plan for renaming `FxVanillaOption` to `FxEuropeanOption` across the OpenGamma Strata codebase (45+ files).

## What Has Been Completed

✅ **Complete File Inventory**: Identified all 45+ files requiring changes
✅ **Dependency Chain Analysis**: Documented all inter-dependencies
✅ **Change Patterns**: Documented all change patterns with examples
✅ **Refactoring Guide**: Created detailed guide with before/after code
✅ **Test Strategy**: Defined test approach and verification steps

## Scope Summary

### Files to Rename (Filename Changes Required)
1. **Product Classes** (4 files):
   - FxVanillaOption.java
   - FxVanillaOptionTrade.java
   - ResolvedFxVanillaOption.java
   - ResolvedFxVanillaOptionTrade.java

2. **Pricer Classes** (4 files):
   - BlackFxVanillaOptionProductPricer.java
   - BlackFxVanillaOptionTradePricer.java
   - VannaVolgaFxVanillaOptionProductPricer.java
   - VannaVolgaFxVanillaOptionTradePricer.java

3. **Measure Classes** (4 files):
   - FxVanillaOptionMeasureCalculations.java
   - FxVanillaOptionTradeCalculations.java
   - FxVanillaOptionTradeCalculationFunction.java
   - FxVanillaOptionMethod.java

4. **Loader/CSV** (1 file):
   - FxVanillaOptionTradeCsvPlugin.java

### Files to Modify (Content Changes Only)
5. **Core Supporting** (2 files):
   - ProductType.java
   - CsvWriterUtils.java

6. **Dependent Products** (2 files):
   - FxSingleBarrierOption.java
   - ResolvedFxSingleBarrierOption.java

7. **Dependent CSV** (1 file):
   - FxSingleBarrierOptionTradeCsvPlugin.java

8. **Dependent Pricers** (2+ files):
   - BlackFxSingleBarrierOptionProductPricer.java
   - ImpliedTrinomialTreeFxSingleBarrierOptionProductPricer.java

9. **Test Files** (15+ files):
   - All test classes in modules/product/src/test
   - All test classes in modules/pricer/src/test
   - All test classes in modules/measure/src/test
   - Test files in modules/loader/src/test

**Total: 45+ files across 4 modules**

## Implementation Approach

### Recommended Strategy

1. **Use IDE Refactoring** (BEST APPROACH):
   - IntelliJ IDEA: Right-click class → Refactor → Rename
   - Eclipse: Right-click class → Refactor → Rename
   - This automatically updates all references across the project

2. **If Using Command-Line Tools**:
   - Use the shell script approach outlined in REFACTORING_GUIDE.md
   - Verify with `grep` before/after

3. **Manual Verification**:
   - After completing renaming, verify no old names remain:
     ```bash
     grep -r "FxVanillaOption" modules/
     grep -r "FX_VANILLA_OPTION" modules/
     ```

### Step-by-Step Execution

#### Phase 1: Core Product Classes (Prerequisites for all other changes)

1. Rename file: `FxVanillaOption.java` → `FxEuropeanOption.java`
   - Update all class references: `FxVanillaOption` → `FxEuropeanOption`
   - Update Meta.INSTANCE references
   - Update builder() references
   - Update toString() references

2. Rename file: `FxVanillaOptionTrade.java` → `FxEuropeanOptionTrade.java`
   - Update class name
   - Update field type: `FxVanillaOption` → `FxEuropeanOption`
   - Update resolve() return type

3. Rename file: `ResolvedFxVanillaOption.java` → `ResolvedFxEuropeanOption.java`
   - Update class name and all references

4. Rename file: `ResolvedFxVanillaOptionTrade.java` → `ResolvedFxEuropeanOptionTrade.java`
   - Update class name
   - Update field type: `ResolvedFxVanillaOption` → `ResolvedFxEuropeanOption`

#### Phase 2: Update Type Constant

5. Update `ProductType.java`:
   ```java
   // Line 109: Change
   public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");

   // To:
   public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");
   ```

#### Phase 3: Rename Pricer Classes

6-9. Rename all 4 pricer files and update references

#### Phase 4: Rename Measure Classes

10-13. Rename all 4 measure files and update references

#### Phase 5: Rename CSV Loader Plugin

14. Rename `FxVanillaOptionTradeCsvPlugin.java` → `FxEuropeanOptionTradeCsvPlugin.java`
    - Update CSV type string: `"FxVanillaOption"` → `"FxEuropeanOption"`
    - Update method name: `writeFxVanillaOption()` → `writeFxEuropeanOption()`

#### Phase 6: Update Dependent Classes

15. Update `CsvWriterUtils.java`:
    - Rename method: `writeFxVanillaOption()` → `writeFxEuropeanOption()`
    - Update method call

16. Update `FxSingleBarrierOption.java`:
    - Update field type and parameter types

17. Update `ResolvedFxSingleBarrierOption.java`:
    - Update field type and parameter types

18. Update `FxSingleBarrierOptionTradeCsvPlugin.java`:
    - Update method call to renamed CSV writer

19. Update barrier pricer classes:
    - Update field types and variable names

#### Phase 7: Update All Tests

20. Update all test files to use renamed classes

## Key Code Examples

### Example 1: Core Class Rename (FxVanillaOption.java → FxEuropeanOption.java)

```java
// BEFORE
@BeanDefinition
public final class FxVanillaOption
    implements FxOptionProduct, Resolvable<ResolvedFxVanillaOption>, ImmutableBean, Serializable {
    // ...
    @Override
    public ResolvedFxVanillaOption resolve(ReferenceData refData) {
        return ResolvedFxVanillaOption.builder()
            .longShort(longShort)
            .expiry(getExpiry())
            .underlying(underlying.resolve(refData))
            .build();
    }

    public static FxVanillaOption.Meta meta() {
        return FxVanillaOption.Meta.INSTANCE;
    }
}

// AFTER
@BeanDefinition
public final class FxEuropeanOption
    implements FxOptionProduct, Resolvable<ResolvedFxEuropeanOption>, ImmutableBean, Serializable {
    // ...
    @Override
    public ResolvedFxEuropeanOption resolve(ReferenceData refData) {
        return ResolvedFxEuropeanOption.builder()
            .longShort(longShort)
            .expiry(getExpiry())
            .underlying(underlying.resolve(refData))
            .build();
    }

    public static FxEuropeanOption.Meta meta() {
        return FxEuropeanOption.Meta.INSTANCE;
    }
}
```

### Example 2: Trade Class Rename

```java
// BEFORE
public final class FxVanillaOptionTrade
    implements FxOptionTrade, ResolvableTrade<ResolvedFxVanillaOptionTrade>, ImmutableBean, Serializable {

    @PropertyDefinition(validate = "notNull", overrideGet = true)
    private final FxVanillaOption product;

    @Override
    public ResolvedFxVanillaOptionTrade resolve(ReferenceData refData) {
        return ResolvedFxVanillaOptionTrade.builder()
            .info(info)
            .product(product.resolve(refData))
            .premium(premium.resolve(refData))
            .build();
    }
}

// AFTER
public final class FxEuropeanOptionTrade
    implements FxOptionTrade, ResolvableTrade<ResolvedFxEuropeanOptionTrade>, ImmutableBean, Serializable {

    @PropertyDefinition(validate = "notNull", overrideGet = true)
    private final FxEuropeanOption product;

    @Override
    public ResolvedFxEuropeanOptionTrade resolve(ReferenceData refData) {
        return ResolvedFxEuropeanOptionTrade.builder()
            .info(info)
            .product(product.resolve(refData))
            .premium(premium.resolve(refData))
            .build();
    }
}
```

### Example 3: Pricer Class Rename

```java
// BEFORE (BlackFxVanillaOptionProductPricer.java)
public class BlackFxVanillaOptionProductPricer {
    public MultiCurrencyAmount presentValue(
        ResolvedFxVanillaOption option,
        RatesProvider ratesProvider,
        BlackFxOptionVolatilities volatilities) {
        // implementation
    }
}

// AFTER (BlackFxEuropeanOptionProductPricer.java)
public class BlackFxEuropeanOptionProductPricer {
    public MultiCurrencyAmount presentValue(
        ResolvedFxEuropeanOption option,
        RatesProvider ratesProvider,
        BlackFxOptionVolatilities volatilities) {
        // implementation
    }
}
```

### Example 4: Trade Pricer Rename

```java
// BEFORE (BlackFxVanillaOptionTradePricer.java)
public class BlackFxVanillaOptionTradePricer {
    private final BlackFxVanillaOptionProductPricer productPricer;

    public static final BlackFxVanillaOptionTradePricer DEFAULT =
        new BlackFxVanillaOptionTradePricer(
            BlackFxVanillaOptionProductPricer.DEFAULT,
            DiscountingPaymentPricer.DEFAULT);

    public BlackFxVanillaOptionTradePricer(
        BlackFxVanillaOptionProductPricer productPricer,
        DiscountingPaymentPricer paymentPricer) {
        // ...
    }

    public MultiCurrencyAmount presentValue(
        ResolvedFxVanillaOptionTrade trade,
        RatesProvider ratesProvider,
        BlackFxOptionVolatilities volatilities) {
        // ...
    }
}

// AFTER (BlackFxEuropeanOptionTradePricer.java)
public class BlackFxEuropeanOptionTradePricer {
    private final BlackFxEuropeanOptionProductPricer productPricer;

    public static final BlackFxEuropeanOptionTradePricer DEFAULT =
        new BlackFxEuropeanOptionTradePricer(
            BlackFxEuropeanOptionProductPricer.DEFAULT,
            DiscountingPaymentPricer.DEFAULT);

    public BlackFxEuropeanOptionTradePricer(
        BlackFxEuropeanOptionProductPricer productPricer,
        DiscountingPaymentPricer paymentPricer) {
        // ...
    }

    public MultiCurrencyAmount presentValue(
        ResolvedFxEuropeanOptionTrade trade,
        RatesProvider ratesProvider,
        BlackFxOptionVolatilities volatilities) {
        // ...
    }
}
```

### Example 5: Measure Class Updates

```java
// BEFORE (FxVanillaOptionTradeCalculations.java)
public class FxVanillaOptionTradeCalculations {
    public static final FxVanillaOptionTradeCalculations DEFAULT =
        new FxVanillaOptionTradeCalculations(
            BlackFxVanillaOptionTradePricer.DEFAULT,
            VannaVolgaFxVanillaOptionTradePricer.DEFAULT);

    public FxVanillaOptionTradeCalculations(
        BlackFxVanillaOptionTradePricer blackPricer,
        VannaVolgaFxVanillaOptionTradePricer vannaVolgaPricer) {
        this.calc = new FxVanillaOptionMeasureCalculations(blackPricer, vannaVolgaPricer);
    }
}

// AFTER (FxEuropeanOptionTradeCalculations.java)
public class FxEuropeanOptionTradeCalculations {
    public static final FxEuropeanOptionTradeCalculations DEFAULT =
        new FxEuropeanOptionTradeCalculations(
            BlackFxEuropeanOptionTradePricer.DEFAULT,
            VannaVolgaFxEuropeanOptionTradePricer.DEFAULT);

    public FxEuropeanOptionTradeCalculations(
        BlackFxEuropeanOptionTradePricer blackPricer,
        VannaVolgaFxEuropeanOptionTradePricer vannaVolgaPricer) {
        this.calc = new FxEuropeanOptionMeasureCalculations(blackPricer, vannaVolgaPricer);
    }
}
```

### Example 6: CSV Plugin Updates

```java
// BEFORE (FxVanillaOptionTradeCsvPlugin.java)
class FxVanillaOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxVanillaOptionTrade> {
    private static final String TRADE_TYPE_FIELD = "FxVanillaOption";

    protected void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {
        FxSingle underlying = product.getUnderlying();
        // ...
    }
}

// AFTER (FxEuropeanOptionTradeCsvPlugin.java)
class FxEuropeanOptionTradeCsvPlugin implements TradeCsvParserPlugin, TradeCsvWriterPlugin<FxEuropeanOptionTrade> {
    private static final String TRADE_TYPE_FIELD = "FxEuropeanOption";

    protected void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
        FxSingle underlying = product.getUnderlying();
        // ...
    }
}
```

### Example 7: CsvWriterUtils Update

```java
// BEFORE (CsvWriterUtils.java)
public static void writeFxVanillaOption(CsvOutput.CsvRowOutputWithHeaders csv, FxVanillaOption product) {
    FxVanillaOptionTradeCsvPlugin.INSTANCE.writeFxVanillaOption(csv, product);
}

// AFTER (CsvWriterUtils.java)
public static void writeFxEuropeanOption(CsvOutput.CsvRowOutputWithHeaders csv, FxEuropeanOption product) {
    FxEuropeanOptionTradeCsvPlugin.INSTANCE.writeFxEuropeanOption(csv, product);
}
```

### Example 8: ProductType Update

```java
// BEFORE (ProductType.java line 107-109)
/**
 * A {@link FxVanillaOption}.
 */
public static final ProductType FX_VANILLA_OPTION = ProductType.of("FxVanillaOption", "FX Vanilla Option");

// AFTER (ProductType.java line 107-109)
/**
 * A {@link FxEuropeanOption}.
 */
public static final ProductType FX_EUROPEAN_OPTION = ProductType.of("FxEuropeanOption", "FX European Option");
```

### Example 9: Dependent Product Update

```java
// BEFORE (FxSingleBarrierOption.java)
public final class FxSingleBarrierOption {
    private final FxVanillaOption underlyingOption;

    public static FxSingleBarrierOption of(FxVanillaOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
        return new FxSingleBarrierOption(underlyingOption, barrier, rebate);
    }
}

// AFTER (FxSingleBarrierOption.java)
public final class FxSingleBarrierOption {
    private final FxEuropeanOption underlyingOption;

    public static FxSingleBarrierOption of(FxEuropeanOption underlyingOption, Barrier barrier, CurrencyAmount rebate) {
        return new FxSingleBarrierOption(underlyingOption, barrier, rebate);
    }
}
```

### Example 10: Test Update

```java
// BEFORE (FxVanillaOptionTradeCalculationsTest.java)
public class FxVanillaOptionTradeCalculationsTest {
    private static final ResolvedFxVanillaOptionTrade RTRADE = FxVanillaOptionTradeCalculationFunctionTest.RTRADE;

    public void test_presentValue() {
        BlackFxVanillaOptionTradePricer pricer = BlackFxVanillaOptionTradePricer.DEFAULT;
        MultiCurrencyAmount expectedPv = pricer.presentValue(RTRADE, ...);
    }
}

// AFTER (FxEuropeanOptionTradeCalculationsTest.java)
public class FxEuropeanOptionTradeCalculationsTest {
    private static final ResolvedFxEuropeanOptionTrade RTRADE = FxEuropeanOptionTradeCalculationFunctionTest.RTRADE;

    public void test_presentValue() {
        BlackFxEuropeanOptionTradePricer pricer = BlackFxEuropeanOptionTradePricer.DEFAULT;
        MultiCurrencyAmount expectedPv = pricer.presentValue(RTRADE, ...);
    }
}
```

## Verification Steps

### 1. Check for Remaining Old Names

```bash
# Should return no results
grep -r "FxVanillaOption" modules/ | grep -v ".class" | grep -v ".jar"
grep -r "FX_VANILLA_OPTION" modules/
```

### 2. Compile Check

```bash
mvn clean compile -pl modules/product -DskipTests
mvn clean compile -pl modules/pricer -DskipTests
mvn clean compile -pl modules/measure -DskipTests
mvn clean compile -pl modules/loader -DskipTests
```

### 3. Run Test Suite

```bash
mvn test -pl modules/product -Dtest="*European*"
mvn test -pl modules/pricer -Dtest="*European*"
mvn test -pl modules/measure -Dtest="*European*"
mvn test -pl modules/loader
```

### 4. Check CSV Loading Works

```bash
mvn test -pl modules/loader -Dtest="TradeCsvLoaderTest#test_load_fx_european_option*"
```

## Expected Impact

### Compilation Impact
- 0 compilation errors after refactoring (if done correctly)
- May have 1000+ files referring to old names during refactoring
- Each phase completion should reduce error count

### Test Impact
- All tests should pass after refactoring
- No behavior changes, only name changes
- CSV loading tests should work with new type string

### Runtime Impact
- No performance impact
- No behavioral changes
- CSV files need format conversion OR manual type string update

## Rollback Strategy

If needed to rollback:
1. Restore from version control
2. Or rename back using same approach

## Documentation After Refactoring

Update:
- JavaDoc comments
- API documentation
- Migration guide for users
- Release notes

## Estimated Effort

- **Using IDE Rename**: 30-45 minutes
- **Manual editing**: 2-3 hours
- **Verification & testing**: 1-2 hours
- **Total**: 3-5 hours

## Risk Assessment

**Risk Level: LOW**

Reasons:
- Purely mechanical refactoring
- No logic or behavior changes
- IDEs handle most renaming automatically
- Comprehensive test coverage
- Straightforward rollback if needed

---

## Related Documentation

- `/logs/agent/solution.md` - Complete file inventory and analysis
- `/logs/agent/REFACTORING_GUIDE.md` - Detailed change patterns and examples
- `/workspace/FxEuropeanOption.java` - Example renamed class

## Next Steps

1. **Choose Implementation Approach**:
   - IDE-based (recommended) OR
   - Script-based OR
   - Manual editing

2. **Execute Phase by Phase**:
   - Start with Phase 1 (core products)
   - Proceed through each phase systematically
   - Verify after each phase

3. **Run Full Test Suite**:
   - Ensure no compilation errors
   - Verify all tests pass
   - Check CSV loading works

4. **Update Documentation**:
   - Update JavaDoc
   - Update user guides
   - Create migration guide

5. **Prepare Release**:
   - Document breaking changes
   - Update CHANGELOG
   - Notify users of API changes
