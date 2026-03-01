# CDS Tranche Implementation - Integration Guide

## Quick Start

This guide explains how to integrate the CDS Tranche product implementation into the OpenGamma Strata repository.

## Step 1: Copy Files to Repository

### Product Module Files
```bash
cp /workspace/CdsTranche.java \
   modules/product/src/main/java/com/opengamma/strata/product/credit/

cp /workspace/CdsTrancheTrade.java \
   modules/product/src/main/java/com/opengamma/strata/product/credit/

cp /workspace/ResolvedCdsTranche.java \
   modules/product/src/main/java/com/opengamma/strata/product/credit/

cp /workspace/ResolvedCdsTrancheTrade.java \
   modules/product/src/main/java/com/opengamma/strata/product/credit/
```

### Pricer Module Files
```bash
cp /workspace/IsdaCdsTranchePricer.java \
   modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/
```

### Measure Module Files
```bash
cp /workspace/CdsTrancheMeasureCalculations.java \
   modules/measure/src/main/java/com/opengamma/strata/measure/credit/

cp /workspace/CdsTrancheTradeCalculationFunction.java \
   modules/measure/src/main/java/com/opengamma/strata/measure/credit/
```

## Step 2: Register Calculation Function

The CalculationFunction needs to be registered in the service loader configuration:

### File: `modules/measure/src/main/resources/META-INF/services/com.opengamma.strata.calc.runner.CalculationFunction`

Add the following line (if not already present):
```
com.opengamma.strata.measure.credit.CdsTrancheTradeCalculationFunction
```

This enables automatic discovery of the calculation function by the framework.

## Step 3: Verify ProductType Enum (Optional)

Check if ProductType needs updating in:
```
modules/product/src/main/java/com/opengamma/strata/product/ProductType.java
```

If you need to add a CDS_TRANCHE product type:

```java
// In ProductType enum
/**
 * CDS tranche.
 */
CDS_TRANCHE("CDS Tranche", CdsTranche.class),
```

Typically this is not needed for internal product types, but may be required for serialization/deserialization.

## Step 4: Compile and Test

```bash
# Compile product module
mvn -pl modules/product clean compile

# Compile pricer module
mvn -pl modules/pricer clean compile

# Compile measure module
mvn -pl modules/measure clean compile

# Run all tests
mvn verify

# Or run tests for just the modified modules
mvn -pl modules/product,modules/pricer,modules/measure test
```

## Step 5: Create Unit Tests

Create corresponding test files in:

### Product Tests
File: `modules/product/src/test/java/com/opengamma/strata/product/credit/CdsTrancheTest.java`

```java
package com.opengamma.strata.product.credit;

import static org.assertj.core.api.Assertions.*;
import org.junit.jupiter.api.Test;

import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.StandardId;
import com.opengamma.strata.basics.currency.Currency;
import com.opengamma.strata.basics.date.DayCount;
import com.opengamma.strata.basics.date.DayCounts;
import com.opengamma.strata.basics.date.DaysAdjustment;
import com.opengamma.strata.basics.schedule.Frequency;
import com.opengamma.strata.basics.schedule.PeriodicSchedule;
import com.opengamma.strata.product.common.BuySell;

public class CdsTrancheTest {

  @Test
  public void test_builder() {
    CdsIndex index = CdsIndex.of(
        BuySell.BUY,
        StandardId.of("CDX", "CDX-IG-5Y"),
        // ... other params
    );

    CdsTranche tranche = CdsTranche.builder()
        .buySell(BuySell.BUY)
        .underlyingIndex(index)
        .attachmentPoint(0.03)
        .detachmentPoint(0.06)
        .currency(Currency.USD)
        .notional(1_000_000)
        .fixedRate(0.01)
        .paymentSchedule(/* ... */)
        .build();

    assertThat(tranche.getBuySell()).isEqualTo(BuySell.BUY);
    assertThat(tranche.getAttachmentPoint()).isEqualTo(0.03);
    assertThat(tranche.getDetachmentPoint()).isEqualTo(0.06);
  }

  @Test
  public void test_resolution() {
    // Test resolve() method
  }
}
```

File: `modules/product/src/test/java/com/opengamma/strata/product/credit/CdsTrancheTradeTest.java`

```java
// Similar test structure
```

### Pricer Tests
File: `modules/pricer/src/test/java/com/opengamma/strata/pricer/credit/IsdaCdsTranchePricerTest.java`

```java
// Test pricing calculations
```

### Measure Tests
File: `modules/measure/src/test/java/com/opengamma/strata/measure/credit/CdsTrancheTradeCalculationFunctionTest.java`

```java
// Test calculation function registration and routing
```

## Step 6: Verify Compilation

Run a complete build to ensure there are no compilation errors:

```bash
mvn clean package
```

Expected output: `BUILD SUCCESS`

## Step 7: Run Integration Tests

If you have integration tests:

```bash
mvn verify -DskipIntegrationTests=false
```

## Implementation Checklist

- [ ] Copy all 7 Java files to correct locations
- [ ] Update META-INF/services/CalculationFunction
- [ ] Update ProductType enum (if needed)
- [ ] Create unit test files
- [ ] Run mvn clean compile
- [ ] Run mvn test (existing tests)
- [ ] Run mvn verify
- [ ] Fix any compilation errors
- [ ] Fix any test failures
- [ ] Update module documentation
- [ ] Create usage examples
- [ ] Commit and push changes

## Verification Steps

### 1. Check Files Exist

```bash
# Verify product module
ls modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTranche*.java

# Verify pricer module
ls modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsTranche*.java

# Verify measure module
ls modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTranche*.java
```

### 2. Check Compilation

```bash
mvn clean compile -DskipTests
```

### 3. Check Service Registration

```bash
grep CdsTrancheTradeCalculationFunction \
  modules/measure/src/main/resources/META-INF/services/com.opengamma.strata.calc.runner.CalculationFunction
```

Should return:
```
com.opengamma.strata.measure.credit.CdsTrancheTradeCalculationFunction
```

### 4. Run Basic Test

```bash
mvn test -Dtest=CdsTrancheTest
```

## Troubleshooting

### Compilation Errors

**Error**: Cannot find symbol `SchedulePeriod`
**Solution**: Ensure import is present: `import com.opengamma.strata.basics.schedule.SchedulePeriod;`

**Error**: Cannot find symbol `IsdaHomogenousCdsIndexProductPricer`
**Solution**: Ensure pricer module is compiled before measure module

**Error**: Service registration not found
**Solution**: Check META-INF/services file exists and contains correct class name

### Test Failures

**Error**: Test cannot find CreditRatesProvider
**Solution**: Ensure credit rates test data is set up in test fixtures

**Error**: ReferenceData not found
**Solution**: Use `ReferenceData.standard()` for tests

**Error**: CdsIndex not available
**Solution**: Create test CdsIndex using existing builder pattern

## Common Usage Examples

### Creating a CDS Tranche

```java
// Create underlying CDS index
CdsIndex index = CdsIndex.of(
    BuySell.BUY,
    StandardId.of("CDX", "CDX-IG-5Y"),
    ImmutableList.of(/* entity IDs */),
    Currency.USD,
    10_000_000,
    LocalDate.of(2024, 1, 15),
    LocalDate.of(2029, 1, 15),
    Frequency.QUARTERLY,
    HolidayCalendarIds.USNY,
    0.01);

// Create the tranche
CdsTranche tranche = CdsTranche.builder()
    .buySell(BuySell.BUY)
    .underlyingIndex(index)
    .attachmentPoint(0.03)        // 3%
    .detachmentPoint(0.06)         // 6%
    .currency(Currency.USD)
    .notional(1_000_000)
    .fixedRate(0.02)
    .paymentSchedule(index.getPaymentSchedule())
    .dayCount(DayCounts.ACT_360)
    .paymentOnDefault(PaymentOnDefault.ACCRUED_PREMIUM)
    .protectionStart(ProtectionStartOfDay.BEGINNING)
    .stepinDateOffset(DaysAdjustment.ofCalendarDays(1))
    .settlementDateOffset(DaysAdjustment.ofBusinessDays(3, HolidayCalendarIds.USNY))
    .build();

// Create a trade
CdsTrancheTrade trade = CdsTrancheTrade.builder()
    .info(TradeInfo.builder()
        .id(StandardId.of("TRADE", "12345"))
        .counterparty(StandardId.of("CPARTY", "ABC"))
        .settlementDate(LocalDate.of(2024, 1, 18))
        .build())
    .product(tranche)
    .build();
```

### Pricing a CDS Tranche

```java
ReferenceData refData = ReferenceData.standard();
ResolvedCdsTrancheTrade resolved = trade.resolve(refData);

IsdaCdsTranchePricer pricer = IsdaCdsTranchePricer.DEFAULT;
CreditRatesProvider ratesProvider = /* obtained from market data */;

CurrencyAmount pv = pricer.presentValue(
    resolved.getProduct(),
    ratesProvider,
    LocalDate.now(ZoneId.of("UTC")),
    PriceType.DIRTY);

System.out.println("Present Value: " + pv);
```

### Using the Calculation Framework

```java
CdsTrancheTrade trade = /* created above */;
ScenarioMarketData marketData = /* from market data provider */;
ReferenceData refData = ReferenceData.standard();

CalculationFunction<CdsTrancheTrade> function =
    new CdsTrancheTradeCalculationFunction();

Result<?> pvResult = function.calculate(
    trade,
    Measures.PRESENT_VALUE,
    CalculationParameters.empty(),
    marketData,
    refData);

if (pvResult.isSuccess()) {
    CurrencyAmount pv = (CurrencyAmount) pvResult.getValue();
    System.out.println("PV: " + pv);
} else {
    System.err.println("Error: " + pvResult.getFailure());
}
```

## Module Dependencies

The implementation respects the following dependency hierarchy:

```
measure
  └─ depends on → pricer, product

pricer
  └─ depends on → product, basics

product
  └─ depends on → basics

basics (core types, no dependencies on others)
```

This ensures clean separation of concerns and avoids circular dependencies.

## Additional Resources

- [OpenGamma Strata Documentation](https://github.com/OpenGamma/Strata)
- [ISDA CDS Model Specification](https://www.isda.org/)
- [Joda-Beans Framework](https://www.joda.org/joda-beans/)
- [Strata Product Design](https://github.com/OpenGamma/Strata/wiki/Products)

## Support and Questions

For issues or questions:
1. Check existing test cases for usage patterns
2. Review similar implementations (CDS, CDS Index)
3. Consult Strata documentation
4. Review commit history for related changes

## Rollback Procedure

If integration fails, rollback is simple:

```bash
# Remove the files
rm modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTranche*.java
rm modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsTranche*.java
rm modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTranche*.java

# Revert META-INF/services changes
git checkout modules/measure/src/main/resources/META-INF/services/

# Clean and rebuild
mvn clean compile
```

## Success Criteria

The integration is successful when:

✓ All 7 Java files compile without errors
✓ All existing tests pass
✓ New unit tests pass
✓ CdsTrancheTradeCalculationFunction is discoverable via ServiceLoader
✓ CdsTranche can be created and resolved
✓ CdsTrancheTrade can be priced via CalculationFunction
✓ No circular dependencies introduced
✓ Javadoc generates without warnings
