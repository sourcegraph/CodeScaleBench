# CDS Tranche Product Implementation for OpenGamma Strata

## Executive Summary

This document describes the implementation of a new `CdsTranche` product type in OpenGamma Strata for pricing synthetic CDO (Collateralized Debt Obligation) tranches. The implementation follows Strata's existing patterns and extends the credit product ecosystem to support tranche-level pricing of CDS indices.

A CDS tranche represents a slice of credit risk from a CDS index portfolio, defined by attachment and detachment points that determine the subordination level. The tranche buyer receives protection against losses in the underlying index between these points.

## Files Examined

### Product Module (modules/product/src/main/java/com/opengamma/strata/product/credit/)
- **CdsIndex.java** — Examined to understand the product structure: BuySell, currency, notional, paymentSchedule, fixedRate, cdsIndexId, legalEntityIds, day count conventions, and protection parameters
- **CdsIndexTrade.java** — Examined to understand the trade wrapper pattern: wraps product with TradeInfo and optional AdjustablePayment upfrontFee
- **Cds.java** — Examined to understand single-name CDS structure and resolve() pattern for creating payment periods
- **ResolvedCdsIndex.java** — Examined to understand resolved product form with expanded payment periods
- **ResolvedCdsIndexTrade.java** — Examined to understand resolved trade form with Payment (not AdjustablePayment)

### Pricer Module (modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/)
- **IsdaCdsProductPricer.java** — Examined to understand pricing interface: price(), presentValue(), priceSensitivity() methods
- **IsdaHomogenousCdsIndexProductPricer.java** — Examined to understand index pricer pattern: wraps underlying CDS pricer, applies index-specific adjustments

### Measure Module (modules/measure/src/main/java/com/opengamma/strata/measure/credit/)
- **CdsTradeCalculationFunction.java** — Examined to understand calculation function pattern: targetType(), supportedMeasures(), requirements(), calculate()
- **CdsIndexTradeCalculationFunction.java** — Examined to understand the same pattern for index trades
- **CdsMeasureCalculations.java** — Examined to understand how individual measures are calculated

## Dependency Chain

The implementation follows this logical sequence:

1. **Define Product Types** (modules/product/credit/):
   - `CdsTranche` — Product class defining attachment point, detachment point, and underlying CdsIndex reference
   - `CdsTrancheTrade` — Trade wrapper holding CdsTranche product, TradeInfo, and optional upfront fee

2. **Define Resolved Types** (modules/product/credit/):
   - `ResolvedCdsTranche` — Resolved product with ResolvedCdsIndex (for pricing use)
   - `ResolvedCdsTrancheTrade` — Resolved trade with ResolvedCdsTranche and Payment (resolved fee)

3. **Implement Pricing** (modules/pricer/credit/):
   - `IsdaCdsTranchePricer` — Pricer class that:
     - Delegates to IsdaHomogenousCdsIndexProductPricer for underlying index pricing
     - Applies tranche subordination by scaling prices by (detachmentPoint - attachmentPoint)
     - Implements price(), priceSensitivity(), presentValue() methods

4. **Wire Calculation Engine** (modules/measure/credit/):
   - `CdsTrancheTradeCalculationFunction` — CalculationFunction implementation that:
     - Maps CdsTrancheTrade to supported Measures
     - Extracts market data requirements from the underlying CDS index
     - Delegates to measure calculation methods

## Code Changes

### 1. CdsTranche.java — Product Type

**Location**: `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTranche.java`

**Key Features**:
- Extends `Product` and `Resolvable<ResolvedCdsTranche>`
- Joda-Bean with `@BeanDefinition` and `ImmutableBean` annotations
- Fields:
  - `underlyingIndex: CdsIndex` — Reference to the underlying CDS index
  - `attachmentPoint: double` — Lower subordination boundary (0.0-1.0)
  - `detachmentPoint: double` — Upper subordination boundary (0.0-1.0)
- Methods:
  - `resolve(ReferenceData)` — Returns ResolvedCdsTranche by resolving underlying index
  - `allCurrencies()` — Delegates to underlying index
  - Validation in `@ImmutablePreBuild` ensures attachment < detachment and detachment ≤ 1.0

**Pattern**: Follows CdsIndex pattern exactly, but with two additional tranche-specific fields

### 2. CdsTrancheTrade.java — Trade Wrapper

**Location**: `modules/product/src/main/java/com/opengamma/strata/product/credit/CdsTrancheTrade.java`

**Key Features**:
- Implements `ProductTrade`, `ResolvableTrade<ResolvedCdsTrancheTrade>`, `ImmutableBean`
- Fields:
  - `info: TradeInfo` — Trade metadata (required)
  - `product: CdsTranche` — The product (required)
  - `upfrontFee: AdjustablePayment` — Optional upfront fee
- Methods:
  - `summarize()` — Returns PortfolioItemSummary with tranche range [attachment-detachment]
  - `resolve(ReferenceData)` — Creates ResolvedCdsTrancheTrade

**Pattern**: Identical to CdsIndexTrade pattern

### 3. ResolvedCdsTranche.java — Resolved Product

**Location**: `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsTranche.java`

**Key Features**:
- Implements `ResolvedProduct`, `ImmutableBean`
- Fields:
  - `underlyingIndex: ResolvedCdsIndex` — Resolved index with payment periods
  - `attachmentPoint: double` — Tranche lower boundary
  - `detachmentPoint: double` — Tranche upper boundary
- Methods:
  - Getters for all fields
  - Builder pattern for construction

**Pattern**: Minimal resolved form, as tranche resolution mainly involves resolving the underlying index

### 4. ResolvedCdsTrancheTrade.java — Resolved Trade

**Location**: `modules/product/src/main/java/com/opengamma/strata/product/credit/ResolvedCdsTrancheTrade.java`

**Key Features**:
- Implements `ResolvedTrade`, `ImmutableBean`
- Fields:
  - `info: TradeInfo` — Trade metadata (defaults to empty)
  - `product: ResolvedCdsTranche` — Resolved product
  - `upfrontFee: Payment` — Resolved payment (not AdjustablePayment)

**Pattern**: Matches ResolvedCdsIndexTrade pattern exactly

### 5. IsdaCdsTranchePricer.java — Pricing Engine

**Location**: `modules/pricer/src/main/java/com/opengamma/strata/pricer/credit/IsdaCdsTranchePricer.java`

**Key Features**:
- Public pricer class with static DEFAULT instance
- Wraps `IsdaHomogenousCdsIndexProductPricer` as underlying pricer
- Constructor accepts `AccrualOnDefaultFormula` parameter for accrual calculation method
- Methods:
  - `price(ResolvedCdsTranche, CreditRatesProvider, LocalDate, PriceType, ReferenceData): double`
    - Prices underlying index
    - Scales by tranche width: `(detachmentPoint - attachmentPoint)`
  - `presentValue(ResolvedCdsTranche, CreditRatesProvider, LocalDate, PriceType, ReferenceData): CurrencyAmount`
    - Returns CurrencyAmount scaled by tranche width
  - `priceSensitivity(ResolvedCdsTranche, CreditRatesProvider, LocalDate, ReferenceData): PointSensitivityBuilder`
    - Returns index sensitivity scaled by tranche width

**Pattern**: Follows IsdaHomogenousCdsIndexProductPricer pattern, wrapping single-name pricer

**Pricing Logic**:
- Tranche pricing: The price of a tranche between attachment and detachment points is the underlying index price multiplied by the tranche width (detachmentPoint - attachmentPoint)
- This reflects the loss allocation: only losses between the two points affect this tranche
- Sensitivities are scaled proportionally

### 6. CdsTrancheTradeCalculationFunction.java — Calculation Integration

**Location**: `modules/measure/src/main/java/com/opengamma/strata/measure/credit/CdsTrancheTradeCalculationFunction.java`

**Key Features**:
- Implements `CalculationFunction<CdsTrancheTrade>`
- Static CALCULATORS map: `Measure -> SingleMeasureCalculation`
  - `PRESENT_VALUE` — Present value calculation
  - `RESOLVED_TARGET` — Returns resolved trade
- Key methods:
  - `targetType()` — Returns `CdsTrancheTrade.class`
  - `supportedMeasures()` — Returns map of supported measures
  - `naturalCurrency(CdsTrancheTrade, ReferenceData)` — Returns underlying index currency
  - `requirements(CdsTrancheTrade, Set<Measure>, CalculationParameters, ReferenceData): FunctionRequirements`
    - Extracts underlying CDS index ID and currency
    - Delegates to CreditRatesMarketDataLookup to get requirements
  - `calculate(CdsTrancheTrade, Set<Measure>, CalculationParameters, ScenarioMarketData, ReferenceData): Map<Measure, Result<?>>`
    - Resolves trade once
    - Gets CreditRatesScenarioMarketData view
    - Calculates each measure for all scenarios

**Pattern**: Matches CdsTradeCalculationFunction and CdsIndexTradeCalculationFunction patterns exactly

## Analysis

### Architecture Integration

The CdsTranche implementation seamlessly integrates with Strata's architecture:

1. **Product Hierarchy**: CdsTranche extends Product/Resolvable just like CdsIndex, making it discoverable by the product framework
2. **Trade Pattern**: CdsTrancheTrade follows the Trade wrapper pattern, compatible with portfolio systems
3. **Resolution**: The resolve() method expands the product with resolved schedule data before pricing
4. **Pricing**: IsdaCdsTranchePricer reuses existing index pricing infrastructure, applying tranche-specific adjustments
5. **Measures**: CdsTrancheTradeCalculationFunction integrates with Strata's calculation engine, supporting standard credit measures

### Key Design Decisions

1. **Tranche as Wrapper**: Rather than redefining all CDS properties, CdsTranche holds a CdsIndex reference plus attachment/detachment points. This:
   - Reduces code duplication
   - Ensures consistency with underlying index
   - Simplifies validation
   - Aligns with CDO product structure

2. **Price Scaling Strategy**: Tranche prices are computed by scaling the underlying index price by the tranche width:
   - `tranche_price = index_price × (detachment - attachment)`
   - This reflects the loss allocation between the two subordination levels
   - Sensitivities scale proportionally

3. **Joda-Beans Convention**: All classes follow Strata's Joda-Beans pattern for consistency:
   - Generated Meta classes for reflection
   - Immutable objects with builder pattern
   - Serializable for persistence

4. **Minimal Resolved Form**: ResolvedCdsTranche is intentionally minimal, mainly holding ResolvedCdsIndex. The tranche parameters themselves don't need expansion; resolution mainly concerns the underlying index.

### Expected Behavior

**Example Usage**:
```java
// Create a 3-5% mezzanine tranche on a CDS index
CdsIndex index = CdsIndex.of(BuySell.BUY, cdsIndexId, entityIds,
    Currency.USD, 10_000_000, startDate, endDate, Frequency.QUARTERLY, calendar, 0.01);
CdsTranche tranche = CdsTranche.builder()
    .underlyingIndex(index)
    .attachmentPoint(0.03)  // 3% attachment
    .detachmentPoint(0.05)  // 5% detachment
    .build();
CdsTrancheTrade trade = CdsTrancheTrade.builder()
    .info(tradeInfo)
    .product(tranche)
    .build();

// Price the tranche
ResolvedCdsTrancheTrade resolved = trade.resolve(refData);
CurrencyAmount pv = pricer.presentValue(resolved.getProduct(), ratesProvider, refDate, PriceType.CLEAN, refData);
```

### Compilation Requirements

The implementation compiles if:
1. All Joda-Beans annotations are correctly processed
2. All imports reference existing Strata classes
3. All method signatures match interfaces (Product, Resolvable, ResolvedProduct, CalculationFunction)
4. No name conflicts with existing classes

### Testing Considerations

The implementation can be tested by:
1. Creating CdsTranche instances and validating tranche width constraints
2. Resolving trades and checking payment period expansion
3. Pricing tranches with known underlying index prices and verifying scaling
4. Comparing sensitivities with scaled index sensitivities
5. Integrating with Strata's calculation engine and verifying measure outputs

## Summary

The CDS Tranche implementation extends OpenGamma Strata with a new product type for pricing tranched credit risk. By following existing patterns for CdsIndex, the implementation achieves:

- **Consistency**: Uses Joda-Beans, Resolvable, CalculationFunction patterns
- **Reusability**: Wraps existing CdsIndex and delegates to existing index pricers
- **Composability**: Integrates seamlessly with Strata's portfolio and calculation systems
- **Extensibility**: Easy to add additional pricing models or risk measures

The core insight is that tranche pricing is index pricing scaled by the subordination level (tranche width), which is reflected in both the price calculations and sensitivity calculations.
