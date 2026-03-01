# CdsTranche Implementation Guide for OpenGamma Strata

## Overview

This guide provides step-by-step instructions for implementing the CDS tranche product type in OpenGamma Strata. The implementation consists of creating 8 new Java classes and modifying 1 existing file across three modules: product, pricer, and measure.

## Files to Create

### Product Module (modules/product/src/main/java/com/opengamma/strata/product/credit/)

#### 1. CdsTranche.java
- **Lines**: ~1100 (including full Joda-Bean implementation)
- **Interfaces**: Product, Resolvable<ResolvedCdsTranche>, ImmutableBean, Serializable
- **Key Methods**:
  - `resolve(ReferenceData)`: Resolves to ResolvedCdsTranche by delegating underlying index resolution
  - `allCurrencies()`: Returns singleton set of the currency
- **Key Fields**:
  - `buySell`: Buy/Sell protection direction
  - `underlyingIndex`: Reference to CdsIndex
  - `attachmentPoint`: Loss absorption start (0.0-1.0)
  - `detachmentPoint`: Loss absorption end (0.0-1.0)
  - Standard CDS fields: `protectionStart`, `currency`, `notional`, `fixedRate`, `paymentSchedule`, `dayCount`, `paymentOnDefault`, `stepinDateOffset`, `settlementDateOffset`
- **Defaults** (@ImmutableDefaults):
  - `dayCount = DayCounts.ACT_360`
  - `paymentOnDefault = PaymentOnDefault.ACCRUED_PREMIUM`
  - `protectionStart = ProtectionStartOfDay.BEGINNING`
  - `stepinDateOffset = DaysAdjustment.ofCalendarDays(1)`
- **Pre-build Processing** (@ImmutablePreBuild):
  - Auto-populate `settlementDateOffset` from payment schedule calendar if not specified

#### 2. CdsTrancheTrade.java
- **Lines**: ~450 (including full Joda-Bean implementation)
- **Interfaces**: ProductTrade, ResolvableTrade<ResolvedCdsTrancheTrade>, ImmutableBean, Serializable
- **Key Methods**:
  - `summarize()`: Formats as "2Y Buy USD 1mm Tranche [3%-6%] / 1.5% : 21Jan18-21Jan20"
  - `resolve(ReferenceData)`: Returns ResolvedCdsTrancheTrade
  - `withInfo(PortfolioItemInfo)`: Creates copy with new TradeInfo
- **Key Fields**:
  - `info`: TradeInfo (trade metadata)
  - `product`: CdsTranche
  - `upfrontFee`: Optional AdjustablePayment

#### 3. ResolvedCdsTranche.java
- **Lines**: ~800 (including full Joda-Bean implementation)
- **Interfaces**: ResolvedProduct, ImmutableBean, Serializable
- **Key Fields**:
  - `buySell`: Buy/Sell direction
  - `underlyingIndex`: ResolvedCdsIndex
  - `attachmentPoint`, `detachmentPoint`: Tranche boundaries
  - `protectionStart`, `currency`, `notional`, `fixedRate`: Core parameters
  - `paymentPeriods`: ImmutableList<CreditCouponPaymentPeriod> (from underlying index)
  - `protectionEndDate`: LocalDate (from underlying index)
  - `dayCount`, `paymentOnDefault`: Standard CDS params
  - `stepinDateOffset`, `settlementDateOffset`: Date adjustments

#### 4. ResolvedCdsTrancheTrade.java
- **Lines**: ~450 (including full Joda-Bean implementation)
- **Interfaces**: ResolvedTrade, ImmutableBean, Serializable
- **Key Fields**:
  - `info`: TradeInfo
  - `product`: ResolvedCdsTranche
  - `upfrontFee`: Optional Payment
- **Defaults** (@ImmutableDefaults):
  - `info = TradeInfo.empty()`

### Pricer Module (modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/)

#### 5. IsdaCdsTranchePricer.java
- **Lines**: ~300-400
- **Key Methods**:
  - `presentValue(ResolvedCdsTranche, CreditRatesProvider, LocalDate, PriceType)`: Main pricer
    - Implements "loss on loss" methodology
    - PV = (PV at detachment) - (PV at attachment)
    - Represents expected loss absorption between attachment/detachment points
  - `price()`: Returns clean or dirty price
  - `pv01()`: Parallel shift sensitivity
- **Implementation Strategy**:
  1. Get underlying index resolved product
  2. Calculate notional scaling factor = `1.0 / (detachmentPoint - attachmentPoint)`
  3. Price protection up to detachment point using underlying ISDA CDS pricer
  4. Price protection up to attachment point
  5. Return difference: `(pvDetachment - pvAttachment) * trancheNotional`

#### 6. CdsTrancheMeasureCalculations.java (Support Class)
- **Lines**: ~150
- **Location**: modules/measure/src/main/java/com/opengamma/strata/measure/credit/
- **Key Methods**:
  - `presentValue()`: Delegates to IsdaCdsTranchePricer
  - `unitPrice()`: PV / notional
  - `principal()`: Returns notional as CurrencyAmount
  - `ir01ParallelShift()`: Interest rate sensitivity
  - `cs01Parallel()`: Credit spread sensitivity

### Measure Module (modules/measure/src/main/java/com/opengamma/strata/measure/credit/)

#### 7. CdsTrancheTradeCalculationFunction.java
- **Lines**: ~350
- **Interfaces**: CalculationFunction<CdsTrancheTrade>
- **Key Methods**:
  - `targetType()`: Returns CdsTrancheTrade.class
  - `supportedMeasures()`: Returns set of Measure
  - `requirements()`: Specifies credit curve dependencies for entities in underlying index
  - `calculate()`: Delegates to CdsTrancheMeasureCalculations
- **Supported Measures**:
  - PRESENT_VALUE
  - UNIT_PRICE
  - PRINCIPAL
  - PV01_CALIBRATED_SUM / BUCKETED
  - IR01_CALIBRATED_PARALLEL / BUCKETED
  - CS01_PARALLEL / BUCKETED
  - RESOLVED_TARGET

### Existing File to Modify

#### ProductType.java
- **File**: modules/product/src/main/java/com/opengamma/strata/product/ProductType.java
- **Change**: Add one new constant
- **Location**: After CDS_INDEX (line ~77)

```java
  /**
   * A CDS tranche.
   */
  public static final ProductType CDS_TRANCHE = ProductType.of("CdsTranche", "CDS Tranche");
```

## Implementation Steps

### Step 1: Create Product Classes (Day 1)
1. Create CdsTranche.java following CdsIndex pattern
2. Create CdsTrancheTrade.java following CdsIndexTrade pattern
3. Create ResolvedCdsTranche.java following ResolvedCdsIndex pattern
4. Create ResolvedCdsTrancheTrade.java following ResolvedCdsIndexTrade pattern
5. Update ProductType.java to add CDS_TRANCHE

**Verification**:
```bash
cd modules/product
mvn clean compile -DskipTests
# Should compile without errors
```

### Step 2: Create Pricer (Day 2)
1. Create IsdaCdsTranchePricer.java with basic present value calculation
2. Implement loss allocation logic: `(pvDetachmentPoint - pvAttachmentPoint) * notional`
3. Add support methods for sensitivity calculations

**Verification**:
```bash
cd modules/pricer
mvn clean compile -DskipTests
# Should compile, may have warnings about unused methods initially
```

### Step 3: Create Measure Integration (Day 3)
1. Create CdsTrancheMeasureCalculations.java
2. Create CdsTrancheTradeCalculationFunction.java
3. Register calculation function (may require updates to measure module factory if applicable)

**Verification**:
```bash
cd modules/measure
mvn clean compile -DskipTests
# Should compile successfully
```

### Step 4: Integration Testing (Day 4)
1. Create test classes for each product class
2. Create pricer tests with benchmark values
3. Create measure calculation tests
4. Verify calculation function is discovered by Strata calc engine

**Verification**:
```bash
cd modules/product
mvn clean test -Dtest=CdsTrancheTest
cd modules/pricer
mvn clean test -Dtest=IsdaCdsTranchePricerTest
cd modules/measure
mvn clean test -Dtest=CdsTrancheTradeCalculationFunctionTest
```

## Design Patterns to Follow

### 1. Joda-Bean Pattern
All product and trade classes should follow this pattern:

```java
@BeanDefinition
public final class MyClass implements ImmutableBean, Serializable {

  @PropertyDefinition(validate = "notNull")
  private final String myProperty;

  // Getters generated
  public String getMyProperty() { return myProperty; }

  // Joda-Bean boilerplate
  public static Meta meta() { return Meta.INSTANCE; }
  public static Builder builder() { return new Builder(); }
  // ... etc
}
```

### 2. Validation
Use property validators:
- `validate = "notNull"` - Required field
- `validate = "ArgChecker.notNegative"` - Non-negative numbers
- Custom validators as needed

### 3. Defaults
Apply with `@ImmutableDefaults`:
```java
@ImmutableDefaults
private static void applyDefaults(Builder builder) {
  builder.dayCount = DayCounts.ACT_360;
  // ...
}
```

### 4. Pre-build Hooks
Execute before object construction with `@ImmutablePreBuild`:
```java
@ImmutablePreBuild
private static void preBuild(Builder builder) {
  if (builder.field == null && builder.otherField != null) {
    builder.field = computeDefault(builder.otherField);
  }
}
```

## Testing Strategy

### Unit Tests
- CdsTrancheTest: Product creation, resolve, validation
- CdsTranch eTradeTest: Trade wrapping, summarize
- ResolvedCdsTrancheTest: Resolved product structure
- ResolvedCdsTrancheTradeTest: Resolved trade structure

### Integration Tests
- IsdaCdsTranchePricerTest: PV calculations with known values
- CdsTrancheMeasureCalculationsTest: Measure calculations
- CdsTrancheTradeCalculationFunctionTest: Calc engine integration

### Benchmark Tests
Create test fixtures with known tranche characteristics:
- Equity tranche [0%-3%]
- Mezzanine tranche [3%-7%]
- Senior tranche [7%-15%]
- Super-senior tranche [15%-30%]

Verify PV is consistent with underlying index allocation:
```
Sum of all tranches PV ≈ Full index PV
```

## Common Issues and Solutions

### Issue: Circular Dependencies
**Solution**: Ensure ResolvedCdsTranche doesn't reference CdsTranche (only vice-versa)

### Issue: Joda-Bean Compilation Errors
**Solution**: Ensure all `@PropertyDefinition` fields are private final, and @BeanDefinition is on the class

### Issue: Missing Meta Bean Registration
**Solution**: Add `MetaBean.register(SomeClass.Meta.INSTANCE);` in static block

### Issue: Validation Not Applied
**Solution**: Validation happens in builder, not constructor. Check Builder implementation

## Performance Considerations

1. **Caching**: Consider caching loss allocation factors between attachment/detachment points
2. **Index Reuse**: Underlying index is resolved once and reused for all tranches from same index
3. **Parallel Calculation**: CreditRatesProvider supports parallel scenario calculations

## Backward Compatibility

- No changes to existing CDS, CdsIndex, or Cds trade classes
- New ProductType constant is additive
- No modifications to core pricing engines
- Fully compatible with existing Strata codebase

## Documentation Requirements

- JavaDoc for all public classes and methods
- Include examples of tranche creation in class-level docs
- Document attachment/detachment point semantics
- Include references to CDX/iTraxx tranche conventions

## Success Criteria

✅ Code compiles without errors or warnings
✅ All product/trade classes follow Joda-Bean pattern
✅ Pricer calculates loss allocation correctly
✅ Calculation function integrates with Strata calc engine
✅ Tests demonstrate tranche-specific behavior
✅ Documentation is complete and clear
✅ No modifications to existing CDS classes required

## Next Steps After Implementation

1. Add CdsTranche support to trade parsers (XML/JSON)
2. Implement tranche-specific analytics (PV by payment period, etc.)
3. Add synthetic CDO portfolio analytics (aggregate tranche exposures)
4. Create market data conventions for tranche quotes
5. Develop scenario analysis tools for tranche sensitivities
