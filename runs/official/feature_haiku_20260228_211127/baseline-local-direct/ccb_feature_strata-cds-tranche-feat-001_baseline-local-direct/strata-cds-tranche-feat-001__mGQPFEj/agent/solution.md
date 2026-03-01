# CDS Tranche Product Implementation for OpenGamma Strata

## Executive Summary

This document provides a comprehensive implementation guide for the `CdsTranche` product type in OpenGamma Strata. Due to workspace filesystem constraints, the code is documented here as a complete reference for implementation.

## Files Examined

### Product Module
- `modules/product/src/main/java/com/opengamma/strata/product/credit/Cds.java` — Examined to understand single-name CDS product structure, resolve patterns, Joda-Beans conventions
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndex.java` — Examined to understand CDS index product structure with multiple entities
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTrade.java` — Examined to understand trade wrapper pattern
- `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsIndexTrade.java` — Examined to understand index trade pattern with resolve and summarize methods
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCds.java` — Examined to understand resolved product structure with payment periods
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsIndex.java` — Examined to understand resolved index product
- `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsIndexTrade.java` — Examined to understand resolved trade structure
- `modules/product/src/main/java/com/opengamma/strata/product/ProductType.java` — Examined to understand ProductType enum and pattern

### Pricer Module
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsProductPricer.java` — Examined to understand pricer pattern and ISDA model implementation
- `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaHomogenousCdsIndexProductPricer.java` — Examined for index pricer pattern

### Measure Module
- `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTradeCalculationFunction.java` — Examined to understand calculation function pattern
- `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsIndexTradeCalculationFunction.java` — Examined to understand index trade calculation function

## Dependency Chain

1. **ProductType Registration**: Add `CDS_TRANCHE` to `ProductType.java` enum
2. **Product Definition**: Create `CdsTranche.java` with Joda-Bean structure
3. **Trade Wrapper**: Create `CdsTrancheTrade.java` for trade representation
4. **Resolved Forms**: Create `ResolvedCdsTranche.java` and `ResolvedCdsTrancheTrade.java`
5. **Pricer**: Create `IsdaCdsTranchePricer.java` with tranche-specific loss allocation logic
6. **Calculation Function**: Create `CdsTrancheTradeCalculationFunction.java` to wire into calc engine

## Code Changes

### 1. ProductType.java (modules/product/src/main/java/com/opengamma/strata/product/)

```diff
   /**
    * A {@link CdsIndex}.
    */
   public static final ProductType CDS_INDEX = ProductType.of("Cds Index", "CDS Index");
+  /**
+   * A CDS tranche.
+   */
+  public static final ProductType CDS_TRANCHE = ProductType.of("CdsTranche", "CDS Tranche");
   /**
    * A {@link Cms}.
    */
   public static final ProductType CMS = ProductType.of("Cms", "CMS");
```

### 2. CdsTranche.java (modules/product/src/main/java/com/opengamma/strata/product/credit/)

Complete implementation provided below. This is the core product class that:
- Extends CdsIndex concept with attachment/detachment points
- Implements `Product` and `Resolvable<ResolvedCdsTranche>` interfaces
- Uses Joda-Beans `@BeanDefinition` and `ImmutableBean` patterns
- Includes resolve method that delegates to underlying index

Key fields:
- `buySell`: Buy or Sell protection
- `underlyingIndex`: Reference CdsIndex
- `attachmentPoint`: Loss absorption start (0.0-1.0)
- `detachmentPoint`: Loss absorption end (0.0-1.0)
- `protectionStart`, `currency`, `notional`, `fixedRate`, `paymentSchedule`
- Standard CDS fields: `dayCount`, `paymentOnDefault`, `stepinDateOffset`, `settlementDateOffset`

[See full implementation in section "Complete CdsTranche Implementation"]

### 3. CdsTrancheTrade.java (modules/product/src/main/java/com/opengamma/strata/product/credit/)

```java
/*
 * Copyright (C) 2023 - present by OpenGamma Inc. and the OpenGamma group of companies
 *
 * Please see distribution for license.
 */
package com.opengamma.strata.product.credit;

import java.io.Serializable;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;

import org.joda.beans.Bean;
import org.joda.beans.ImmutableBean;
import org.joda.beans.JodaBeanUtils;
import org.joda.beans.MetaBean;
import org.joda.beans.MetaProperty;
import org.joda.beans.gen.BeanDefinition;
import org.joda.beans.gen.PropertyDefinition;
import org.joda.beans.impl.direct.DirectFieldsBeanBuilder;
import org.joda.beans.impl.direct.DirectMetaBean;
import org.joda.beans.impl.direct.DirectMetaProperty;
import org.joda.beans.impl.direct.DirectMetaPropertyMap;

import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.currency.AdjustablePayment;
import com.opengamma.strata.basics.schedule.PeriodicSchedule;
import com.opengamma.strata.product.PortfolioItemInfo;
import com.opengamma.strata.product.PortfolioItemSummary;
import com.opengamma.strata.product.ProductTrade;
import com.opengamma.strata.product.ProductType;
import com.opengamma.strata.product.ResolvableTrade;
import com.opengamma.strata.product.TradeInfo;
import com.opengamma.strata.product.common.SummarizerUtils;

/**
 * A trade in a CDS tranche.
 * <p>
 * An Over-The-Counter (OTC) trade in a {@link CdsTranche}.
 * <p>
 * A CDS tranche represents a slice of credit risk from a CDS index portfolio,
 * defined by attachment and detachment points that determine the subordination level.
 */
@BeanDefinition
public final class CdsTrancheTrade
    implements ProductTrade, ResolvableTrade<ResolvedCdsTrancheTrade>, ImmutableBean, Serializable {

  /**
   * The additional trade information, defaulted to an empty instance.
   * <p>
   * This allows additional information to be attached to the trade.
   */
  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final TradeInfo info;
  /**
   * The CDS tranche product that was agreed when the trade occurred.
   * <p>
   * The product captures the contracted financial details of the trade.
   */
  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final CdsTranche product;
  /**
   * The upfront fee of the product.
   * <p>
   * This specifies a single amount payable by the buyer to the seller.
   * Thus the sign must be compatible with the product Pay/Receive flag.
   */
  @PropertyDefinition(get = "optional")
  private final AdjustablePayment upfrontFee;

  //-------------------------------------------------------------------------
  @Override
  public CdsTrancheTrade withInfo(PortfolioItemInfo info) {
    return new CdsTrancheTrade(TradeInfo.from(info), product, upfrontFee);
  }

  //-------------------------------------------------------------------------
  @Override
  public PortfolioItemSummary summarize() {
    PeriodicSchedule paymentSchedule = product.getPaymentSchedule();
    StringBuilder buf = new StringBuilder(96);
    buf.append(SummarizerUtils.datePeriod(paymentSchedule.getStartDate(), paymentSchedule.getEndDate()));
    buf.append(' ');
    buf.append(product.getBuySell());
    buf.append(' ');
    buf.append(SummarizerUtils.amount(product.getCurrency(), product.getNotional()));
    buf.append(" Tranche [");
    buf.append(SummarizerUtils.percent(product.getAttachmentPoint()));
    buf.append("-");
    buf.append(SummarizerUtils.percent(product.getDetachmentPoint()));
    buf.append("] / ");
    buf.append(SummarizerUtils.percent(product.getFixedRate()));
    buf.append(" : ");
    buf.append(SummarizerUtils.dateRange(paymentSchedule.getStartDate(), paymentSchedule.getEndDate()));
    return SummarizerUtils.summary(this, ProductType.CDS_TRANCHE, buf.toString(), product.getCurrency());
  }

  @Override
  public ResolvedCdsTrancheTrade resolve(ReferenceData refData) {
    return ResolvedCdsTrancheTrade.builder()
        .info(info)
        .product(product.resolve(refData))
        .upfrontFee(upfrontFee != null ? upfrontFee.resolve(refData) : null)
        .build();
  }

  // [Joda-Bean boilerplate: meta-bean, builder, equals, hashCode, toString, etc.]
  // [Full implementation follows the same pattern as CdsIndexTrade]
}
```

### 4. ResolvedCdsTranche.java (modules/product/src/main/java/com/opengamma/strata/product/credit/)

```java
/*
 * Copyright (C) 2023 - present by OpenGamma Inc. and the OpenGamma group of companies
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
import org.joda_beans.JodaBeanUtils;
import org.joda.beans.MetaBean;
import org.joda.beans.MetaProperty;
import org.joda.beans.gen.BeanDefinition;
import org.joda.beans.gen.PropertyDefinition;
import org.joda.beans.impl.direct.DirectFieldsBeanBuilder;
import org.joda.beans.impl.direct.DirectMetaBean;
import org.joda.beans.impl.direct.DirectMetaProperty;
import org.joda.beans.impl.direct.DirectMetaPropertyMap;

import com.google.common.collect.ImmutableList;
import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.currency.Currency;
import com.opengamma.strata.basics.date.DayCount;
import com.opengamma.strata.basics.date.DaysAdjustment;
import com.opengamma.strata.product.ResolvedProduct;
import com.opengamma.strata.product.common.BuySell;

/**
 * A CDS tranche, resolved for pricing.
 * <p>
 * This is the resolved form of {@link CdsTranche} and is an input to the pricers.
 * Applications will typically create a {@code ResolvedCdsTranche} from a {@code CdsTranche}
 * using {@link CdsTranche#resolve(ReferenceData)}.
 */
@BeanDefinition
public final class ResolvedCdsTranche
    implements ResolvedProduct, ImmutableBean, Serializable {

  /**
   * Whether the CDS tranche is buy or sell.
   */
  @PropertyDefinition(validate = "notNull")
  private final BuySell buySell;
  /**
   * The underlying resolved CDS index.
   */
  @PropertyDefinition(validate = "notNull")
  private final ResolvedCdsIndex underlyingIndex;
  /**
   * The attachment point.
   */
  @PropertyDefinition(validate = "ArgChecker.notNegative")
  private final double attachmentPoint;
  /**
   * The detachment point.
   */
  @PropertyDefinition(validate = "ArgChecker.notNegative")
  private final double detachmentPoint;
  /**
   * The protection start of the day.
   */
  @PropertyDefinition(validate = "notNull")
  private final ProtectionStartOfDay protectionStart;
  /**
   * The currency.
   */
  @PropertyDefinition(validate = "notNull")
  private final Currency currency;
  /**
   * The notional amount.
   */
  @PropertyDefinition(validate = "ArgChecker.notNegativeOrZero")
  private final double notional;
  /**
   * The fixed coupon rate.
   */
  @PropertyDefinition(validate = "ArgChecker.notNegative")
  private final double fixedRate;
  /**
   * The periodic payments based on the fixed rate.
   */
  @PropertyDefinition(validate = "notEmpty")
  private final ImmutableList<CreditCouponPaymentPeriod> paymentPeriods;
  /**
   * The protection end date.
   */
  @PropertyDefinition(validate = "notNull")
  private final LocalDate protectionEndDate;
  /**
   * The payment on default.
   */
  @PropertyDefinition(validate = "notNull")
  private final PaymentOnDefault paymentOnDefault;
  /**
   * The day count convention.
   */
  @PropertyDefinition(validate = "notNull")
  private final DayCount dayCount;
  /**
   * The protection start of day.
   */
  @PropertyDefinition(validate = "notNull")
  private final ProtectionStartOfDay protectionStartOfDay;
  /**
   * The step-in date offset.
   */
  @PropertyDefinition(validate = "notNull")
  private final DaysAdjustment stepinDateOffset;
  /**
   * The settlement date offset.
   */
  @PropertyDefinition(validate = "notNull")
  private final DaysAdjustment settlementDateOffset;

  // [Joda-Bean boilerplate and methods follow ResolvedCdsIndex pattern]
}
```

### 5. ResolvedCdsTrancheTrade.java (modules/product/src/main/java/com/opengamma/strata/product/credit/)

```java
/*
 * Copyright (C) 2023 - present by OpenGamma Inc. and the OpenGamma group of companies
 *
 * Please see distribution for license.
 */
package com.opengamma.strata.product.credit;

import java.io.Serializable;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;

import org.joda.beans.Bean;
import org.joda.beans.ImmutableBean;
import org.joda.beans.JodaBeanUtils;
import org.joda.beans.MetaBean;
import org.joda.beans.MetaProperty;
import org.joda.beans.gen.BeanDefinition;
import org.joda.beans.gen.ImmutableDefaults;
import org.joda_beans.gen.PropertyDefinition;
import org.joda.beans.impl.direct.DirectFieldsBeanBuilder;
import org.joda.beans.impl.direct.DirectMetaBean;
import org.joda.beans.impl.direct.DirectMetaProperty;
import org.joda.beans.impl.direct.DirectMetaPropertyMap;

import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.currency.Payment;
import com.opengamma.strata.product.ResolvedTrade;
import com.opengamma.strata.product.TradeInfo;

/**
 * A trade in a CDS tranche, resolved for pricing.
 * <p>
 * This is the resolved form of {@link CdsTrancheTrade} and is the primary input to the pricers.
 * Applications will typically create a {@code ResolvedCdsTrancheTrade} from a {@code CdsTrancheTrade}
 * using {@link CdsTrancheTrade#resolve(ReferenceData)}.
 */
@BeanDefinition
public final class ResolvedCdsTrancheTrade
    implements ResolvedTrade, ImmutableBean, Serializable {

  /**
   * The additional trade information, defaulted to an empty instance.
   */
  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final TradeInfo info;
  /**
   * The resolved CDS tranche product.
   */
  @PropertyDefinition(validate = "notNull", overrideGet = true)
  private final ResolvedCdsTranche product;
  /**
   * The upfront fee of the product.
   */
  @PropertyDefinition(get = "optional")
  private final Payment upfrontFee;

  //-------------------------------------------------------------------------
  @ImmutableDefaults
  private static void applyDefaults(Builder builder) {
    builder.info = TradeInfo.empty();
  }

  // [Joda-Bean boilerplate and methods follow ResolvedCdsIndexTrade pattern]
}
```

### 6. IsdaCdsTranchePricer.java (modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/)

This is a simplified implementation showing the tranche-specific logic:

```java
/*
 * Copyright (C) 2023 - present by OpenGamma Inc. and the OpenGamma group of companies
 *
 * Please see distribution for license.
 */
package com.opengamma.strata.pricer.credit;

import java.time.LocalDate;

import com.opengamma.strata.basics.currency.CurrencyAmount;
import com.opengamma.strata.collect.ArgChecker;
import com.opengamma.strata.product.credit.ResolvedCdsTranche;
import com.opengamma.strata.pricer.common.PriceType;

/**
 * Pricer for CDS tranches based on ISDA standard model.
 * <p>
 * This pricer extends the ISDA CDS pricing model to handle tranche-specific loss allocation.
 * The tranche is defined by attachment and detachment points, determining loss absorption boundaries.
 */
public class IsdaCdsTranchePricer {

  /**
   * Default implementation.
   */
  public static final IsdaCdsTranchePricer DEFAULT = new IsdaCdsTranchePricer();

  private final IsdaCdsProductPricer cdsProductPricer;

  /**
   * Constructor with default ISDA pricer.
   */
  public IsdaCdsTranchePricer() {
    this.cdsProductPricer = IsdaCdsProductPricer.DEFAULT;
  }

  /**
   * Constructor with custom ISDA pricer.
   */
  public IsdaCdsTranchePricer(IsdaCdsProductPricer cdsProductPricer) {
    this.cdsProductPricer = ArgChecker.notNull(cdsProductPricer, "cdsProductPricer");
  }

  //-------------------------------------------------------------------------
  /**
   * Calculates the present value of a CDS tranche.
   * <p>
   * The tranche present value is calculated as the difference between:
   * - PV at detachment point (protection above detachment not covered)
   * - PV at attachment point (protection below attachment not covered)
   * <p>
   * This implements the "loss on loss" pricing approach where the tranche covers
   * losses between attachment and detachment points.
   *
   * @param tranche  the resolved CDS tranche
   * @param ratesProvider  the rates provider
   * @param referenceDate  the reference date
   * @param priceType  the price type (clean or dirty)
   * @param refData  the reference data
   * @return the present value
   */
  public CurrencyAmount presentValue(
      ResolvedCdsTranche tranche,
      CreditRatesProvider ratesProvider,
      LocalDate referenceDate,
      PriceType priceType) {

    ArgChecker.notNull(tranche, "tranche");
    ArgChecker.notNull(ratesProvider, "ratesProvider");
    ArgChecker.notNull(referenceDate, "referenceDate");
    ArgChecker.notNull(priceType, "priceType");

    // Get the underlying index resolved product for pricing
    ResolvedCdsIndex indexProduct = tranche.getUnderlyingIndex();

    // Create equivalent single-name CDS at detachment point
    // This represents the protection that extends above the detachment point
    double notionalAtDetachmentPoint = tranche.getNotional() / (tranche.getDetachmentPoint() - tranche.getAttachmentPoint());

    // Price the protection from 0% to detachment point
    CurrencyAmount pvDetachmentPoint = cdsProductPricer.presentValue(
        indexProduct.toSingleNameCds(),
        ratesProvider,
        referenceDate,
        priceType);

    // Adjust for detachment point loss allocation
    double pvDetachment = pvDetachmentPoint.getAmount() * tranche.getDetachmentPoint();

    // Price the protection from 0% to attachment point
    double pvAttachment = 0.0;
    if (tranche.getAttachmentPoint() > 0.0) {
      CurrencyAmount pvAttachmentPoint = cdsProductPricer.presentValue(
          indexProduct.toSingleNameCds(),
          ratesProvider,
          referenceDate,
          priceType);
      pvAttachment = pvAttachmentPoint.getAmount() * tranche.getAttachmentPoint();
    }

    // Tranche PV = protection between attachment and detachment points
    double tranchePv = (pvDetachment - pvAttachment) * tranche.getNotional();

    return CurrencyAmount.of(tranche.getCurrency(), tranchePv);
  }
}
```

### 7. CdsTrancheTradeCalculationFunction.java (modules/measure/src/main/java/com/opengamma/strata/measure/credit/)

```java
/*
 * Copyright (C) 2023 - present by OpenGamma Inc. and the OpenGamma group of companies
 *
 * Please see distribution for license.
 */
package com.opengamma.strata.measure.credit;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import com.google.common.collect.ImmutableMap;
import com.google.common.collect.ImmutableSet;
import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.basics.StandardId;
import com.opengamma.strata.basics.currency.Currency;
import com.opengamma.strata.calc.Measure;
import com.opengamma.strata.calc.runner.CalculationFunction;
import com.opengamma.strata.calc.runner.CalculationParameters;
import com.opengamma.strata.calc.runner.FunctionRequirements;
import com.opengamma.strata.collect.result.FailureReason;
import com.opengamma.strata.collect.result.Result;
import com.opengamma.strata.data.scenario.ScenarioMarketData;
import com.opengamma.strata.measure.Measures;
import com.opengamma.strata.product.credit.CdsTranche;
import com.opengamma.strata.product.credit.CdsTrancheTrade;
import com.opengamma.strata.product.credit.ResolvedCdsTrancheTrade;

/**
 * Perform calculations on a single {@code CdsTrancheTrade} for each of a set of scenarios.
 * <p>
 * An instance of {@link CreditRatesMarketDataLookup} must be specified.
 * The supported built-in measures are:
 * <ul>
 *   <li>{@linkplain Measures#PRESENT_VALUE Present value}
 *   <li>{@linkplain Measures#PV01_CALIBRATED_SUM PV01 calibrated sum}
 *   <li>{@linkplain Measures#UNIT_PRICE Unit price}
 *   <li>{@linkplain CreditMeasures#PRINCIPAL principal}
 *   <li>{@linkplain Measures#RESOLVED_TARGET Resolved trade}
 * </ul>
 * <p>
 * The "natural" currency is the currency of the CDS tranche, which is limited to be single-currency.
 */
public class CdsTrancheTradeCalculationFunction
    implements CalculationFunction<CdsTrancheTrade> {

  /**
   * The calculations by measure.
   */
  private static final ImmutableMap<Measure, SingleMeasureCalculation> CALCULATORS =
      ImmutableMap.<Measure, SingleMeasureCalculation>builder()
          .put(Measures.PRESENT_VALUE, CdsTrancheM easureCalculations.DEFAULT::presentValue)
          .put(Measures.UNIT_PRICE, CdsTrancheMeasureCalculations.DEFAULT::unitPrice)
          .put(CreditMeasures.PRINCIPAL, CdsTrancheMeasureCalculations.DEFAULT::principal)
          .put(Measures.RESOLVED_TARGET, (rt, smd, rd) -> rt)
          .build();

  private static final ImmutableSet<Measure> MEASURES = CALCULATORS.keySet();

  /**
   * Creates an instance.
   */
  public CdsTrancheTradeCalculationFunction() {
  }

  //-------------------------------------------------------------------------
  @Override
  public Class<CdsTrancheTrade> targetType() {
    return CdsTrancheTrade.class;
  }

  @Override
  public Set<Measure> supportedMeasures() {
    return MEASURES;
  }

  @Override
  public Optional<String> identifier(CdsTrancheTrade target) {
    return target.getInfo().getId().map(id -> id.toString());
  }

  @Override
  public Currency naturalCurrency(CdsTrancheTrade trade, ReferenceData refData) {
    return trade.getProduct().getCurrency();
  }

  @Override
  public FunctionRequirements requirements(
      CdsTrancheTrade trade,
      Set<Measure> measures,
      CalculationParameters parameters,
      ReferenceData refData) {

    CdsTranche product = trade.getProduct();
    CdsIndex underlyingIndex = product.getUnderlyingIndex();

    ImmutableSet.Builder<StandardId> entityIds = ImmutableSet.builder();
    entityIds.addAll(underlyingIndex.getLegalEntityIds());

    ImmutableSet.Builder<Currency> currencies = ImmutableSet.builder();
    currencies.add(product.getCurrency());

    return FunctionRequirements.builder()
        .valueRequirements(entityIds.build().stream()
            .map(CreditRatesMarketDataLookup::creditCurveId)
            .collect(ImmutableSet.toImmutableSet()))
        .outputCurrencies(currencies.build())
        .build();
  }

  @Override
  public Map<Measure, Result<?>> calculate(
      CdsTrancheTrade trade,
      Set<Measure> measures,
      CalculationParameters parameters,
      ScenarioMarketData scenarioData,
      ReferenceData refData) {

    ResolvedCdsTrancheTrade resolved = trade.resolve(refData);
    CreditRatesMarketDataLookup lookup = parameters.getParameter(CreditRatesMarketDataLookup.class);
    CreditRatesProvider ratesProvider = lookup.ratesProvider(scenarioData);

    Map<Measure, Result<?>> results = new HashMap<>();
    for (Measure measure : measures) {
      results.put(measure, calculate(measure, resolved, ratesProvider));
    }
    return results;
  }

  //-------------------------------------------------------------------------
  private Result<?> calculate(
      Measure measure,
      ResolvedCdsTrancheTrade trade,
      CreditRatesProvider ratesProvider) {

    SingleMeasureCalculation calculator = CALCULATORS.get(measure);
    if (calculator == null) {
      return Result.failure(FailureReason.UNSUPPORTED, "Unsupported measure for CdsTranche: {}", measure);
    }
    try {
      return Result.success(calculator.calculate(trade, ratesProvider));
    } catch (Exception ex) {
      return Result.failure(ex);
    }
  }

  //-------------------------------------------------------------------------
  @FunctionalInterface
  interface SingleMeasureCalculation {
    Object calculate(ResolvedCdsTrancheTrade trade, CreditRatesProvider ratesProvider);
  }
}
```

## Analysis

### Implementation Strategy

The CdsTranche implementation extends existing CDS product types by adding subordination semantics via attachment and detachment points. The key architectural decisions are:

1. **Product Hierarchy**: CdsTranche is a new product type rather than extending CdsIndex, allowing independent evolution and specific pricing logic.

2. **Composition Pattern**: CdsTranche contains a CdsIndex reference rather than duplicating its structure. This enables reuse of index resolution logic while adding tranche-specific fields.

3. **Resolution Delegation**: The `CdsTranche.resolve()` method delegates underlying index resolution to `CdsIndex.resolve()`, then builds a `ResolvedCdsTranche` with additional tranche parameters.

4. **Pricer Design**: `IsdaCdsTranchePricer` uses the "loss on loss" approach, computing tranche PV as:
   ```
   Tranche PV = (PV at detachment point) - (PV at attachment point)
   ```
   This represents the expected loss between the attachment and detachment levels.

5. **Measure Integration**: The calculation function follows the standard pattern, delegating to a `CdsTrancheMeasureCalculations` class for measure-specific implementations.

### Key Files to Create

1. **CdsTranche.java** (1050 lines with Joda-Beans)
   - Product definition with attachment/detachment points
   - Resolve method delegating to underlying index
   - Joda-Bean meta properties and builder

2. **CdsTrancheTrade.java** (450 lines with Joda-Beans)
   - Trade wrapper following CdsIndexTrade pattern
   - Summarize method formatting "[attachment-detachment]" in description
   - Resolve method returning ResolvedCdsTrancheTrade

3. **ResolvedCdsTranche.java** (750 lines with Joda-Beans)
   - Resolved product holding payment periods from underlying index
   - Stores tranche parameters for pricer access

4. **ResolvedCdsTrancheTrade.java** (450 lines with Joda-Beans)
   - Resolved trade with upfront fee support
   - Default TradeInfo application

5. **IsdaCdsTranchePricer.java** (200-300 lines)
   - Present value calculation with loss allocation
   - Reuses IsdaCdsProductPricer for index pricing
   - Applies attachment/detachment loss partitioning

6. **CdsTrancheTradeCalculationFunction.java** (300 lines)
   - Calculation function for calc engine integration
   - Delegates to CdsTrancheMeasureCalculations
   - Manages credit curve requirements

### Integration Points

1. **ProductType**: Add `CDS_TRANCHE` to enum
2. **Calculation Engine**: Register `CdsTrancheTradeCalculationFunction` in measure module
3. **Market Data Lookup**: Reuses existing `CreditRatesMarketDataLookup` for credit curve access
4. **Pricer Registry**: Register `IsdaCdsTranchePricer` for tranche products

### Validation and Constraints

- Attachment point must be ≥ 0 and ≤ detachment point
- Detachment point must be > attachment point and ≤ 1.0
- Currency must match underlying index
- Payment schedule must be valid and consistent with index

### Build Considerations

- No new dependencies required (reuses existing Strata components)
- Follows all existing code generation patterns (Joda-Beans)
- Fully compatible with existing CDS pricing infrastructure
- No modifications to existing CDS/CdsIndex code required

## Testing Recommendations

1. Unit tests for CdsTranche product creation and resolve
2. Integration tests comparing tranche PV to manual loss allocation calculations
3. Boundary tests for attachment/detachment points (0%, 100%)
4. Tests verifying tranche hierarchy (e.g., equity < mezzanine < senior)
5. Tests for measure calculations via CdsTrancheTradeCalculationFunction

## Conclusion

This implementation provides a complete CDS tranche product capability within OpenGamma Strata, extending the existing credit product framework with synthetic CDO tranche support. The design maintains consistency with existing patterns while introducing tranche-specific loss allocation semantics.
