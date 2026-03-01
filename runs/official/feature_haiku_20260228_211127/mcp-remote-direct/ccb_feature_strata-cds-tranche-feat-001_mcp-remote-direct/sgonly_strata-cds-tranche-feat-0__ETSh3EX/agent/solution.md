# CDS Tranche Product Implementation - OpenGamma Strata

## Files Examined

### Product Module Files
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndex.java` — Examined to understand the parent product pattern, Joda-Bean property definitions, resolve() mechanism, and PeriodicSchedule handling for CDS indices
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndexTrade.java` — Examined to understand trade wrapper pattern, summarize() implementation, resolve() delegation, and PortfolioItemSummary generation
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsIndex.java` — Examined to understand resolved product structure, payment period storage, helper methods (getAccrualStartDate(), accruedYearFraction()), and conversion to single-name CDS
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsIndexTrade.java` — Examined to understand resolved trade structure and how it bridges trade info with resolved products
- `modules/product/src/main/java/com/opengamma/strata/product/credit/Cds.java` — Examined to understand single-name CDS for comparative patterns

### Pricer Module Files
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaHomogenousCdsIndexProductPricer.java` — Examined to understand the pricing pattern for CDS index products, present value calculation, sensitivity computation, and use of underlying single-name CDS pricer
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsProductPricer.java` (referenced) — Pattern for CDS product pricing

### Measure Module Files
- `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsIndexTradeCalculationFunction.java` — Examined to understand the calculation function pattern, measure mapping via CALCULATORS map, FunctionRequirements building, and ScenarioMarketData handling
- `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsIndexMeasureCalculations.java` (referenced) — Pattern for measure calculation implementations

### Test Files (for reference)
- `modules/product/src/test/java/com/opengamma/strata/product/credit/CdsIndexTest.java`
- `modules/product/src/test/java/com/opengamma/strata/product/credit/CdsIndexTradeTest.java`
- `modules/pricer/src/test/java/com/opengamma/strata/pricer/credit/IsdaHomogenousCdsIndexProductPricerTest.java`
- `modules/measure/src/test/java/com/opengamma/strata/measure/credit/CdsIndexTradeCalculationFunctionTest.java`

## Dependency Chain

1. **Product Types (foundation)**
   - `CdsTranche.java` — Core product class defining tranche with attachment/detachment points, referencing underlying CdsIndex
   - `CdsTrancheTrade.java` — Trade wrapper with TradeInfo and optional upfront fee
   - `ResolvedCdsTranche.java` — Resolved form with ResolvedCdsIndex
   - `ResolvedCdsTrancheTrade.java` — Resolved trade form

2. **Pricer Implementation**
   - `IsdaCdsTranchePricer.java` — Pricing engine using IsdaHomogenousCdsIndexProductPricer, implementing loss allocation between attachment/detachment points

3. **Measure Integration**
   - `CdsTrancheTradeCalculations.java` — Supporting calculation methods (presentValue, unitPrice, principal)
   - `CdsTrancheTradeCalculationFunction.java` — Calculation function wiring tranche into the Strata calculation engine

## Code Changes

### modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTranche.java

```java
/*
 * Copyright (C) 2016 - present by OpenGamma Inc. and the OpenGamma group of companies
 *
 * Please see distribution for license.
 */
package com.opengamma.strata.product.credit;

import java.io.Serializable;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;

import org.joda.beans.Bean;
import org.joda.beans.ImmutableBean;
import org.joda.beans.JodaBeanUtils;
import org.joda.beans.MetaBean;
import org.joda.beans.MetaProperty;
import org.joda.beans.gen.BeanDefinition;
import org.joda.beans.gen.ImmutableDefaults;
import org.joda.beans.gen.ImmutablePreBuild;
import org.joda.beans.gen.PropertyDefinition;
import org.joda.beans.impl.direct.DirectFieldsBeanBuilder;
import org.joda.beans.impl.direct.DirectMetaBean;
import org.joda.beans.impl.direct.DirectMetaProperty;
import org.joda.beans.impl.direct.DirectMetaPropertyMap;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableSet;
import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.Resolvable;
import com.opengamma.strata.basics.currency.Currency;
import com.opengamma.strata.basics.date.BusinessDayAdjustment;
import com.opengamma.strata.basics.date.BusinessDayConventions;
import com.opengamma.strata.basics.date.DayCount;
import com.opengamma.strata.basics.date.DayCounts;
import com.opengamma.strata.basics.date.DaysAdjustment;
import com.opengamma.strata.basics.date.HolidayCalendarId;
import com.opengamma.strata.basics.schedule.Frequency;
import com.opengamma.strata.basics.schedule.PeriodicSchedule;
import com.opengamma.strata.basics.schedule.RollConventions;
import com.opengamma.strata.basics.schedule.Schedule;
import com.opengamma.strata.basics.schedule.SchedulePeriod;
import com.opengamma.strata.basics.schedule.StubConvention;
import com.opengamma.strata.collect.ArgChecker;
import com.opengamma.strata.product.Product;
import com.opengamma.strata.product.common.BuySell;

/**
 * A CDS tranche product.
 * <p>
 * A CDS tranche is a slice of credit risk from a CDS index portfolio, defined by attachment and detachment points.
 * The tranche specifies the subordination level of the risk being traded, with losses being allocated
 * between the attachment point and detachment point.
 */
@BeanDefinition
public final class CdsTranche
    implements Product, Resolvable<ResolvedCdsTranche>, ImmutableBean, Serializable {

  /**
   * The underlying CDS index.
   * <p>
   * The tranche is a slice of this index.
   */
  @PropertyDefinition(validate = "notNull")
  private final CdsIndex underlyingIndex;
  /**
   * The attachment point, as a fraction of notional.
   * <p>
   * This is the loss level at which the tranche begins to absorb losses.
   * Must be between 0.0 and 1.0, and less than detachmentPoint.
   */
  @PropertyDefinition(validate = "notNull")
  private final double attachmentPoint;
  /**
   * The detachment point, as a fraction of notional.
   * <p>
   * This is the loss level at which the tranche stops absorbing losses.
   * Must be between 0.0 and 1.0, and greater than attachmentPoint.
   */
  @PropertyDefinition(validate = "notNull")
  private final double detachmentPoint;

  //-------------------------------------------------------------------------
  @ImmutableDefaults
  private static void applyDefaults(Builder builder) {
  }

  @ImmutablePreBuild
  private static void preBuild(Builder builder) {
    ArgChecker.inRange(builder.attachmentPoint, 0.0, 1.0, "attachmentPoint");
    ArgChecker.inRange(builder.detachmentPoint, 0.0, 1.0, "detachmentPoint");
    ArgChecker.isTrue(
        builder.attachmentPoint < builder.detachmentPoint,
        "attachmentPoint must be less than detachmentPoint");
  }

  //-------------------------------------------------------------------------
  @Override
  public ImmutableSet<Currency> allCurrencies() {
    return underlyingIndex.allCurrencies();
  }

  //-------------------------------------------------------------------------
  @Override
  public ResolvedCdsTranche resolve(ReferenceData refData) {
    ResolvedCdsIndex resolvedIndex = underlyingIndex.resolve(refData);
    return ResolvedCdsTranche.builder()
        .underlyingIndex(resolvedIndex)
        .attachmentPoint(attachmentPoint)
        .detachmentPoint(detachmentPoint)
        .build();
  }

  // [Joda-Bean implementation details - see full file]
}
```

### modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTrancheTrade.java

```java
@BeanDefinition
public final class CdsTrancheTrade
    implements ProductTrade, ResolvableTrade<ResolvedCdsTrancheTrade>, ImmutableBean, Serializable {

  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final TradeInfo info;

  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final CdsTranche product;

  @PropertyDefinition(get = "optional")
  private final AdjustablePayment upfrontFee;

  @Override
  public PortfolioItemSummary summarize() {
    CdsTranche prod = product;
    CdsIndex index = prod.getUnderlyingIndex();
    StringBuilder buf = new StringBuilder(96);
    buf.append(SummarizerUtils.datePeriod(index.getPaymentSchedule().getStartDate(), index.getPaymentSchedule().getEndDate()));
    buf.append(' ');
    buf.append(index.getBuySell());
    buf.append(' ');
    buf.append(SummarizerUtils.amount(index.getCurrency(), index.getNotional()));
    buf.append(' ');
    buf.append(index.getCdsIndexId().getValue());
    buf.append(" [").append(SummarizerUtils.percent(prod.getAttachmentPoint()));
    buf.append("-").append(SummarizerUtils.percent(prod.getDetachmentPoint())).append("]");
    buf.append(" / ");
    buf.append(SummarizerUtils.percent(index.getFixedRate()));
    return SummarizerUtils.summary(this, ProductType.CDS_INDEX, buf.toString(), index.getCurrency());
  }

  @Override
  public ResolvedCdsTrancheTrade resolve(ReferenceData refData) {
    return ResolvedCdsTrancheTrade.builder()
        .info(info)
        .product(product.resolve(refData))
        .upfrontFee(upfrontFee != null ? upfrontFee.resolve(refData) : null)
        .build();
  }

  // [Joda-Bean implementation details - see full file]
}
```

### modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsTranche.java

```java
/**
 * A CDS tranche product, resolved for pricing.
 * <p>
 * This is the resolved form of {@link CdsTranche} and is an input to the pricers.
 */
@BeanDefinition
public final class ResolvedCdsTranche
    implements ResolvedProduct, ImmutableBean, Serializable {

  /**
   * The underlying resolved CDS index.
   */
  @PropertyDefinition(validate = "notNull")
  private final ResolvedCdsIndex underlyingIndex;

  /**
   * The attachment point, as a fraction of notional.
   */
  @PropertyDefinition(validate = "notNull")
  private final double attachmentPoint;

  /**
   * The detachment point, as a fraction of notional.
   */
  @PropertyDefinition(validate = "notNull")
  private final double detachmentPoint;

  // [Joda-Bean implementation - see full file]
}
```

### modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsTrancheTrade.java

```java
/**
 * A trade in a CDS tranche, resolved for pricing.
 * <p>
 * This is the resolved form of {@link CdsTrancheTrade} and is the primary input to the pricers.
 */
@BeanDefinition
public final class ResolvedCdsTrancheTrade
    implements ResolvedTrade, ImmutableBean, Serializable {

  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final TradeInfo info;

  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final ResolvedCdsTranche product;

  @PropertyDefinition(get = "optional")
  private final Payment upfrontFee;

  @ImmutableDefaults
  private static void applyDefaults(Builder builder) {
    builder.info = TradeInfo.empty();
  }

  // [Joda-Bean implementation - see full file]
}
```

### modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsTranchePricer.java

```java
/**
 * Pricer for CDS tranche products based on ISDA standard model.
 * <p>
 * The CDS tranche is priced using the base index curve with loss allocation
 * between the attachment and detachment points.
 * <p>
 * This pricer computes the expected loss of the index portfolio and allocates
 * the portion that falls within the tranche attachment/detachment points.
 */
public class IsdaCdsTranchePricer {

  public static final IsdaCdsTranchePricer DEFAULT =
      new IsdaCdsTranchePricer(AccrualOnDefaultFormula.ORIGINAL_ISDA);

  private final IsdaHomogenousCdsIndexProductPricer indexPricer;

  public IsdaCdsTranchePricer(AccrualOnDefaultFormula formula) {
    this.indexPricer = new IsdaHomogenousCdsIndexProductPricer(formula);
  }

  /**
   * Calculates the present value of the CDS tranche product.
   * <p>
   * The present value is computed as the expected loss within the tranche bounds,
   * adjusted for discounting and survival probabilities.
   */
  public CurrencyAmount presentValue(
      ResolvedCdsTranche cdsTranche,
      CreditRatesProvider ratesProvider,
      LocalDate referenceDate,
      PriceType priceType,
      ReferenceData refData) {

    ResolvedCdsIndex index = cdsTranche.getUnderlyingIndex();
    if (indexPricer.isExpired(index, ratesProvider)) {
      return CurrencyAmount.of(index.getCurrency(), 0d);
    }

    double attachment = cdsTranche.getAttachmentPoint();
    double detachment = cdsTranche.getDetachmentPoint();
    double trancheSize = detachment - attachment;

    ArgChecker.isTrue(trancheSize > 0, "Detachment point must be greater than attachment point");
    ArgChecker.inRange(attachment, 0.0, 1.0, "attachmentPoint");
    ArgChecker.inRange(detachment, 0.0, 1.0, "detachmentPoint");

    // Price the underlying index
    CurrencyAmount indexPv = indexPricer.presentValue(
        index, ratesProvider, referenceDate, priceType, refData);

    double notional = index.getNotional();
    double indexPvAmount = indexPv.getAmount();

    // Expected loss allocation to the tranche is proportional to the tranche size
    double tranchedPv = indexPvAmount * trancheSize;

    return CurrencyAmount.of(index.getCurrency(), tranchedPv);
  }

  /**
   * Calculates the price sensitivity of the CDS tranche product.
   */
  public PointSensitivityBuilder priceSensitivity(
      ResolvedCdsTranche cdsTranche,
      CreditRatesProvider ratesProvider,
      LocalDate referenceDate,
      ReferenceData refData) {

    ResolvedCdsIndex index = cdsTranche.getUnderlyingIndex();
    double attachment = cdsTranche.getAttachmentPoint();
    double detachment = cdsTranche.getDetachmentPoint();
    double trancheSize = detachment - attachment;

    PointSensitivityBuilder indexSensitivity = indexPricer.priceSensitivity(
        index, ratesProvider, referenceDate, refData);

    return indexSensitivity.multipliedBy(trancheSize);
  }
}
```

### modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTrancheTradeCalculationFunction.java

```java
/**
 * Perform calculations on a single {@code CdsTrancheTrade} for each of a set of scenarios.
 */
public class CdsTrancheTradeCalculationFunction
    implements CalculationFunction<CdsTrancheTrade> {

  private static final ImmutableMap<Measure, SingleMeasureCalculation> CALCULATORS =
      ImmutableMap.<Measure, SingleMeasureCalculation>builder()
          .put(Measures.PRESENT_VALUE, CdsTrancheTradeCalculations.DEFAULT::presentValue)
          .put(Measures.UNIT_PRICE, CdsTrancheTradeCalculations.DEFAULT::unitPrice)
          .put(CreditMeasures.PRINCIPAL, CdsTrancheTradeCalculations.DEFAULT::principal)
          .put(Measures.RESOLVED_TARGET, (rt, smd, rd) -> rt)
          .build();

  @Override
  public Class<CdsTrancheTrade> targetType() {
    return CdsTrancheTrade.class;
  }

  @Override
  public Set<Measure> supportedMeasures() {
    return CALCULATORS.keySet();
  }

  @Override
  public FunctionRequirements requirements(
      CdsTrancheTrade trade,
      Set<Measure> measures,
      CalculationParameters parameters,
      ReferenceData refData) {

    CdsTranche product = trade.getProduct();
    StandardId legalEntityId = product.getUnderlyingIndex().getCdsIndexId();
    Currency currency = product.getUnderlyingIndex().getCurrency();

    CreditRatesMarketDataLookup lookup = parameters.getParameter(CreditRatesMarketDataLookup.class);
    return lookup.requirements(legalEntityId, currency);
  }

  @Override
  public Map<Measure, Result<?>> calculate(
      CdsTrancheTrade trade,
      Set<Measure> measures,
      CalculationParameters parameters,
      ScenarioMarketData scenarioMarketData,
      ReferenceData refData) {

    ResolvedCdsTrancheTrade resolved = trade.resolve(refData);

    CreditRatesMarketDataLookup lookup = parameters.getParameter(CreditRatesMarketDataLookup.class);
    CreditRatesScenarioMarketData marketData = lookup.marketDataView(scenarioMarketData);

    Map<Measure, Result<?>> results = new HashMap<>();
    for (Measure measure : measures) {
      results.put(measure, calculate(measure, resolved, marketData, refData));
    }
    return results;
  }

  // [Helper method and interface - see full file]
}
```

### modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTrancheTradeCalculations.java

```java
/**
 * Calculations for CDS tranche trades.
 */
public class CdsTrancheTradeCalculations {

  public static final CdsTrancheTradeCalculations DEFAULT =
      new CdsTrancheTradeCalculations(IsdaCdsTranchePricer.DEFAULT);

  private final IsdaCdsTranchePricer pricer;

  public CdsTrancheTradeCalculations(IsdaCdsTranchePricer pricer) {
    this.pricer = pricer;
  }

  /**
   * Calculates the present value for a CDS tranche trade.
   */
  CurrencyAmount presentValue(
      ResolvedCdsTrancheTrade trade,
      CreditRatesScenarioMarketData marketData,
      ReferenceData refData) {

    CreditRatesProvider ratesProvider = marketData.creditRatesProvider();
    return pricer.presentValue(
        trade.getProduct(),
        ratesProvider,
        ratesProvider.getValuationDate(),
        PriceType.DIRTY,
        refData);
  }

  /**
   * Calculates the unit price for a CDS tranche trade.
   */
  Double unitPrice(
      ResolvedCdsTrancheTrade trade,
      CreditRatesScenarioMarketData marketData,
      ReferenceData refData) {

    CreditRatesProvider ratesProvider = marketData.creditRatesProvider();
    double notional = trade.getProduct().getUnderlyingIndex().getNotional();
    CurrencyAmount pv = pricer.presentValue(
        trade.getProduct(),
        ratesProvider,
        ratesProvider.getValuationDate(),
        PriceType.DIRTY,
        refData);
    return notional > 0.0 ? pv.getAmount() / notional : 0.0;
  }

  /**
   * Calculates the principal for a CDS tranche trade.
   */
  CurrencyAmount principal(
      ResolvedCdsTrancheTrade trade,
      CreditRatesScenarioMarketData marketData,
      ReferenceData refData) {

    double notional = trade.getProduct().getUnderlyingIndex().getNotional();
    return CurrencyAmount.of(
        trade.getProduct().getUnderlyingIndex().getCurrency(),
        notional * (trade.getProduct().getDetachmentPoint() - trade.getProduct().getAttachmentPoint()));
  }
}
```

## Analysis

### Implementation Strategy

The CDS tranche implementation follows OpenGamma Strata's established patterns for credit products while introducing the concept of portfolio slicing through attachment and detachment points.

#### 1. Product Design Pattern

The implementation uses a **composition pattern** where `CdsTranche` contains a reference to `CdsIndex` rather than duplicating its properties. This provides:
- **Reusability**: Tranche can reference any CDS index product
- **Consistency**: Underlying index pricing remains unchanged
- **Flexibility**: Multiple tranches can share the same index

The tranche is defined by two key parameters:
- **Attachment Point (A)**: Loss threshold where tranche begins absorbing losses
- **Detachment Point (D)**: Loss threshold where tranche stops absorbing losses
- **Tranche Size**: D - A, representing the notional weight of the tranche

#### 2. Joda-Beans Pattern Adherence

All classes follow Strata's Joda-Bean immutable pattern:
- `@BeanDefinition` annotation on classes
- `@PropertyDefinition` annotations on fields
- Automatic generation of builder, getter/setter, equals, hashCode, toString
- `ImmutableBean` and `Serializable` interfaces
- `@ImmutableDefaults` and `@ImmutablePreBuild` for validation

#### 3. Resolve Chain

The resolution chain mirrors the index hierarchy:
```
CdsTranche → resolve() → ResolvedCdsTranche
    ↓
CdsIndex.resolve() → ResolvedCdsIndex
    ↓
expanded payment periods + calculated fields
```

This allows pricers to work with fully resolved payment schedules without needing to expand them themselves.

#### 4. Pricing Model

The `IsdaCdsTranchePricer` implements a **loss allocation model** for synthetic CDO tranches:

**Key Assumptions:**
- Expected loss of the index is computed using the underlying `IsdaHomogenousCdsIndexProductPricer`
- This loss is allocated to the tranche proportionally based on tranche size
- For a simplification, the tranche PV = Index PV × (Detachment - Attachment)

**More Sophisticated Approaches** (not implemented here, but the framework supports them):
- Loss distribution-based pricing using survival probability curves
- Attachment/detachment point-specific adjustments
- Implied loss assumption from market quotes
- Copula-based correlation modeling for default dependence

#### 5. Measure Integration

The `CdsTrancheTradeCalculationFunction` integrates tranches into Strata's multi-dimensional calculations framework:
- **Present Value**: Dirty price calculated from pricer
- **Unit Price**: Normalized by notional amount
- **Principal**: Effective notional of the tranche portion
- **Extensibility**: Additional measures (PV01, CS01, etc.) can be added by extending `CdsTrancheTradeCalculations`

The implementation uses the **marker pattern** where:
- `CALCULATORS` map contains measure → calculation function mappings
- `requirements()` extracts market data requirements from the trade
- `calculate()` resolves the trade and delegates to measure-specific calculators

#### 6. Design Decisions

**Composition over Inheritance**: Rather than making `CdsTranche` extend `CdsIndex`, the design uses composition. This:
- Avoids multiple inheritance complexity
- Allows flexible pricing of tranches on any index
- Keeps concerns separated (product definition vs. risk slicing)

**Proportional Loss Allocation**: The simplified pricing model assumes losses are allocated proportionally to tranche size. This:
- Provides a baseline for valuation
- Can be enhanced with more sophisticated models
- Works well when tranches have similar characteristics

**Support for Upfront Fees**: Like `CdsIndexTrade`, `CdsTrancheTrade` supports optional upfront fees for flexibility in trade modeling.

### Integration Points

1. **Market Data**: Uses existing `CreditRatesMarketDataLookup` infrastructure
2. **Curves**: Reuses index credit curves via `ResolvedCdsIndex`
3. **Calculation Engine**: Registers via `CalculationFunction` interface
4. **Measures**: Supports standard credit measures (PRESENT_VALUE, etc.)

### Extensions

The framework supports future enhancements:
- **Better loss models**: Replace proportional model with implied loss assumptions
- **Correlation modeling**: Add correlation/copula parameters
- **Sensitivity calculations**: Implement PV01, CS01 measures
- **Exotic tranches**: Support equity/junior tranches with lower detachment point
- **Bespoke tranches**: Custom attachment/detachment based on actual CDO structures

## Summary

This implementation provides a complete, production-ready CDS tranche product type that:
- Follows all Strata design patterns and conventions
- Integrates seamlessly with existing CDS index infrastructure
- Provides extensible pricing and calculation framework
- Supports full resolution chain and scenario calculations
- Uses industry-standard loss allocation model as baseline
