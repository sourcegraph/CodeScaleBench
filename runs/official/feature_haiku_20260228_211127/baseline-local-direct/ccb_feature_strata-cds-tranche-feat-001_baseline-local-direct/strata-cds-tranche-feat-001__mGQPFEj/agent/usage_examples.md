# CdsTranche Usage Examples

This document provides concrete examples of how to use the CdsTranche product once implemented.

## Example 1: Creating a CdsTranche Product

```java
import com.opengamma.strata.basics.StandardId;
import com.opengamma.strata.basics.currency.Currency;
import com.opengamma.strata.basics.date.DaysAdjustment;
import com.opengamma.strata.basics.schedule.Frequency;
import com.opengamma.strata.basics.schedule.HolidayCalendarId;
import com.opengamma.strata.product.credit.CdsIndex;
import com.opengamma.strata.product.credit.CdsTranche;
import com.opengamma.strata.product.common.BuySell;
import java.time.LocalDate;

// Create the underlying CDS index
StandardId indexId = StandardId.of("CDS", "CDX-HY");
CdsIndex index = CdsIndex.of(
    BuySell.BUY,
    indexId,
    List.of(
        StandardId.of("LEI", "BBBBB1111111111111111"),
        StandardId.of("LEI", "CCCCC2222222222222222"),
        // ... more entities ...
    ),
    Currency.USD,
    1_000_000_000.0,  // $1B notional
    LocalDate.of(2023, 12, 20),
    LocalDate.of(2028, 12, 20),
    Frequency.QUARTERLY,
    HolidayCalendarId.of("USNY"),
    0.035  // 350bp fixed coupon
);

// Create equity tranche [0%-3%]
CdsTranche equityTranche = CdsTranche.builder()
    .buySell(BuySell.BUY)
    .underlyingIndex(index)
    .attachmentPoint(0.00)      // 0%
    .detachmentPoint(0.03)      // 3%
    .currency(Currency.USD)
    .notional(100_000_000.0)     // $100M notional for tranche
    .fixedRate(0.05)             // 500bp coupon for equity
    .paymentSchedule(index.getPaymentSchedule())
    .build();

// Create mezzanine tranche [3%-7%]
CdsTranche mezzzanineTranche = CdsTranche.builder()
    .buySell(BuySell.BUY)
    .underlyingIndex(index)
    .attachmentPoint(0.03)       // 3%
    .detachmentPoint(0.07)       // 7%
    .currency(Currency.USD)
    .notional(100_000_000.0)     // $100M notional for tranche
    .fixedRate(0.025)            // 250bp coupon for mezzanine
    .paymentSchedule(index.getPaymentSchedule())
    .build();

// Create senior tranche [7%-30%]
CdsTranche seniorTranche = CdsTranche.builder()
    .buySell(BuySell.BUY)
    .underlyingIndex(index)
    .attachmentPoint(0.07)       // 7%
    .detachmentPoint(0.30)       // 30%
    .currency(Currency.USD)
    .notional(920_000_000.0)     // $920M notional for tranche
    .fixedRate(0.005)            // 50bp coupon for senior
    .paymentSchedule(index.getPaymentSchedule())
    .build();
```

## Example 2: Creating a CdsTrancheTrade

```java
import com.opengamma.strata.basics.currency.AdjustablePayment;
import com.opengamma.strata.product.TradeInfo;
import com.opengamma.strata.product.credit.CdsTrancheTrade;
import java.time.LocalDate;

// Create trade info with trade date and settlement date
TradeInfo tradeInfo = TradeInfo.builder()
    .tradeDate(LocalDate.of(2024, 1, 15))
    .settlementDate(LocalDate.of(2024, 1, 18))
    .counterparty(StandardId.of("CPTY", "BANK001"))
    .build();

// Create the trade
CdsTrancheTrade trade = CdsTrancheTrade.builder()
    .info(tradeInfo)
    .product(equityTranche)
    .upfrontFee(AdjustablePayment.of(
        CurrencyAmount.of(Currency.USD, 500_000),  // $500k upfront payment
        LocalDate.of(2024, 1, 18)
    ))
    .build();

// Trade summarization (for display)
PortfolioItemSummary summary = trade.summarize();
// Output: "5Y Buy USD 100mm Tranche [0%-3%] / 5.0% : 20Dec23-20Dec28"
```

## Example 3: Resolving a Trade

```java
import com.opengamma.strata.basics.ReferenceData;
import com.opengamma.strata.product.credit.ResolvedCdsTrancheTrade;

// Resolve the trade (expands schedules to actual dates, applies business day conventions, etc.)
ReferenceData refData = ReferenceData.standard();
ResolvedCdsTrancheTrade resolvedTrade = trade.resolve(refData);

// Now you have access to:
// - resolvedTrade.getProduct().getPaymentPeriods() - actual payment periods with dates
// - resolvedTrade.getProduct().getProtectionEndDate() - exact end date
// - resolvedTrade.getProduct().getUnderlyingIndex() - resolved index details
```

## Example 4: Pricing with the Calculation Engine

```java
import com.opengamma.strata.calc.CalculationRules;
import com.opengamma.strata.calc.Measure;
import com.opengamma.strata.calc.Results;
import com.opengamma.strata.calc.runner.CalculationRunner;
import com.opengamma.strata.data.MarketData;
import com.opengamma.strata.measure.Measures;
import com.opengamma.strata.measure.credit.CreditRatesMarketDataLookup;
import java.time.LocalDate;

// Create market data provider
LocalDate valuationDate = LocalDate.of(2024, 1, 15);
CreditRatesMarketDataLookup lookup = CreditRatesMarketDataLookup.of(
    // ... market data mapping ...
);

// Set up calculation rules
CalculationRules rules = CalculationRules.of(
    Measures.PV01_CALIBRATED_SUM,
    Measures.PRESENT_VALUE,
    lookup
);

// Run calculation
CalculationRunner runner = CalculationRunner.default();
Results results = runner.calculate(
    rules,
    List.of(trade),
    List.of(
        Measures.PRESENT_VALUE,
        Measures.UNIT_PRICE,
        CreditMeasures.CS01_PARALLEL
    ),
    MarketData.of(valuationDate, fxRates, creditData)
);

// Extract results
double presentValue = results.get(0, 0).getValue();      // PV in USD
double unitPrice = results.get(0, 1).getValue();         // Price per unit notional
CurrencyAmount cs01 = results.get(0, 2).getValue();      // Credit spread 1bp sensitivity
```

## Example 5: Direct Pricer Access

```java
import com.opengamma.strata.pricer.credit.CreditRatesProvider;
import com.opengamma.strata.pricer.credit.IsdaCdsTranchePricer;
import com.opengamma.strata.pricer.credit.ImmutableCreditRatesProvider;

// Create pricer
IsdaCdsTranchePricer pricer = IsdaCdsTranchePricer.DEFAULT;

// Create rates provider with credit curves
CreditRatesProvider ratesProvider = ImmutableCreditRatesProvider.builder()
    .valuationDate(LocalDate.of(2024, 1, 15))
    .discountFactors(Currency.USD, discountCurve)
    .creditCurves(Map.of(
        StandardId.of("LEI", "BBBBB1111111111111111"), survivialCurve1,
        StandardId.of("LEI", "CCCCC2222222222222222"), survivialCurve2
        // ... more curves ...
    ))
    .build();

// Price the tranche
ResolvedCdsTranche resolvedProduct = equityTranche.resolve(ReferenceData.standard());
CurrencyAmount pv = pricer.presentValue(
    resolvedProduct,
    ratesProvider,
    LocalDate.of(2024, 1, 15)
);

System.out.println("Equity tranche PV: " + pv);
// Output: Equity tranche PV: USD 2,500,000.00
```

## Example 6: Tranche Comparison Analysis

```java
// Compare different tranches from same underlying index
List<CdsTranche> tranches = List.of(equityTranche, mezzzanineTranche, seniorTranche);

for (CdsTranche tranche : tranches) {
    ResolvedCdsTranche resolved = tranche.resolve(ReferenceData.standard());
    CurrencyAmount pv = pricer.presentValue(resolved, ratesProvider, valuationDate);

    double attachment = tranche.getAttachmentPoint() * 100;
    double detachment = tranche.getDetachmentPoint() * 100;
    double rate = tranche.getFixedRate() * 10000;  // in basis points

    System.out.printf(
        "[%.1f%%-%.1f%%]: Rate=%5.0fbps, PV=%s, Price=%.2f%%%n",
        attachment,
        detachment,
        rate,
        pv,
        pv.getAmount() / tranche.getNotional()
    );
}

// Output:
// [0.0%-3.0%]: Rate= 500bps, PV=USD 2,500,000.00, Price=2.50%
// [3.0%-7.0%]: Rate= 250bps, PV=USD 1,800,000.00, Price=1.80%
// [7.0%-30.0%]: Rate=  50bps, PV=  USD 800,000.00, Price=0.09%
```

## Example 7: Loss Allocation Verification

```java
// Verify that sum of all tranches equals the full index

// Price full index
ResolvedCds indexAsFullProtection = equityTranche.getUnderlyingIndex()
    .toSingleNameCds();
ResolvedCds resolvedIndex = indexAsFullProtection.resolve(refData);
CurrencyAmount indexPv = cdsProductPricer.presentValue(
    resolvedIndex,
    ratesProvider,
    valuationDate
);

// Sum tranches
CurrencyAmount totalTranchePv = tranches.stream()
    .map(t -> pricer.presentValue(t.resolve(refData), ratesProvider, valuationDate))
    .reduce(CurrencyAmount.of(Currency.USD, 0), CurrencyAmount::plus);

System.out.println("Index PV: " + indexPv);
System.out.println("Sum of tranches: " + totalTranchePv);
System.out.println("Difference: " + indexPv.minus(totalTranchePv).getAmount());

// Verify they match (accounting for rounding)
assert Math.abs(indexPv.getAmount() - totalTranchePv.getAmount()) < 1000;
```

## Example 8: Sensitivity Analysis

```java
// Calculate credit spread sensitivities (CS01)

double baseSpread = 0.035;
double bumpSize = 0.0001;  // 1 basis point

// Price at base
ResolvedCdsTranche resolved = equityTranche.resolve(refData);
CurrencyAmount basePv = pricer.presentValue(resolved, ratesProvider, valuationDate);

// Price with spread bumped up
CreditRatesProvider bumpedRatesProvider = bumpCreditSpreads(ratesProvider, bumpSize);
CurrencyAmount bumpedPv = pricer.presentValue(resolved, bumpedRatesProvider, valuationDate);

// Calculate CS01 (change in PV per 1bp move in spreads)
double cs01 = bumpedPv.getAmount() - basePv.getAmount();

System.out.printf("Equity tranche CS01: $%.2f per 1bp move%n", cs01);
// Output: Equity tranche CS01: $-50,000.00 per 1bp move
//         (Negative: when spreads widen, protection becomes cheaper)
```

## Example 9: Portfolio Analytics

```java
// Analyze a portfolio of different tranches

Map<String, CdsTrancheTrade> portfolio = Map.of(
    "Equity", equityTrade,
    "Mezzanine", mezzanineTrade,
    "Senior", seniorTrade
);

double totalNotional = 0;
double totalPv = 0;
double weightedRate = 0;

for (Map.Entry<String, CdsTrancheTrade> entry : portfolio.entrySet()) {
    String name = entry.getKey();
    CdsTrancheTrade trade = entry.getValue();
    CdsTranche product = trade.getProduct();

    ResolvedCdsTranche resolved = product.resolve(refData);
    CurrencyAmount pv = pricer.presentValue(resolved, ratesProvider, valuationDate);

    double notional = product.getNotional();
    double rate = product.getFixedRate();

    totalNotional += notional;
    totalPv += pv.getAmount();
    weightedRate += rate * notional;

    System.out.printf("%10s: Notional=$%,12.0f, Rate=%6.2f%%, PV=$%,12.0f%n",
        name, notional, rate * 100, pv.getAmount());
}

double portfolioPrice = totalPv / totalNotional;
double avgRate = weightedRate / totalNotional;

System.out.printf("%n%-20s: $%,12.0f%n", "Total Notional", totalNotional);
System.out.printf("%-20s: $%,12.0f%n", "Total PV", totalPv);
System.out.printf("%-20s: %.2f%%%n", "Portfolio Price", portfolioPrice * 100);
System.out.printf("%-20s: %.2f%%%n", "Weighted Avg Rate", avgRate * 100);
```

## Example 10: Custom Trade Info

```java
// Create tranche trade with detailed trade information

TradeInfo detailedInfo = TradeInfo.builder()
    .tradeDate(LocalDate.of(2024, 1, 15))
    .settlementDate(LocalDate.of(2024, 1, 18))
    .counterparty(StandardId.of("CPTY", "JP MORGAN"))
    .instrument(StandardId.of("ISIN", "US123456789"))
    .venue(StandardId.of("EXCH", "OTC"))
    .convention(StandardId.of("CONVENTION", "CDX-HY"))
    .putAttribute("strategy", "hedge")
    .putAttribute("client", "ACME Corp")
    .build();

CdsTrancheTrade strategyTrade = CdsTrancheTrade.builder()
    .info(detailedInfo)
    .product(equityTranche)
    .upfrontFee(AdjustablePayment.of(
        CurrencyAmount.of(Currency.USD, 250_000),
        LocalDate.of(2024, 1, 18)
    ))
    .build();

// Access trade attributes later
String strategy = strategyTrade.getInfo().getAttribute("strategy").get();
System.out.println("Trade strategy: " + strategy);  // Output: hedge
```

## Key Patterns and Best Practices

### Pattern 1: Builder Construction
Always use builder for creating products and trades:
```java
CdsTranche tranche = CdsTranche.builder()
    .buySell(BuySell.BUY)
    .underlyingIndex(index)
    .attachmentPoint(0.03)
    .detachmentPoint(0.07)
    // ... complete all required fields
    .build();
```

### Pattern 2: Lazy Resolution
Resolve trades only when needed (expensive operation):
```java
CdsTrancheTrade trade = ...;  // Unresolved

// Later, when pricing is needed:
ResolvedCdsTrancheTrade resolved = trade.resolve(refData);
CurrencyAmount pv = pricer.presentValue(...);
```

### Pattern 3: Market Data Injection
Use dependency injection for rates provider:
```java
CreditRatesProvider ratesProvider = ...;  // Injected
CurrencyAmount pv = pricer.presentValue(resolved, ratesProvider, valuationDate);
```

### Pattern 4: Immutability
Products and trades are immutable - create new ones for modifications:
```java
// ❌ WRONG:
trade.setNotional(200_000_000);

// ✅ RIGHT:
CdsTrancheTrade modifiedTrade = CdsTrancheTrade.builder()
    .info(trade.getInfo())
    .product(CdsTranche.builder()
        .from(trade.getProduct())
        .notional(200_000_000)
        .build())
    .upfrontFee(trade.getUpfrontFee().orElse(null))
    .build();
```

## Performance Considerations

- **Reuse Resolved Forms**: Don't resolve the same trade multiple times
- **Parallel Pricing**: Use parallel streams for portfolios
- **Curve Caching**: Cache credit curves across multiple pricings
- **Batch Calculations**: Use calc engine for scenario analysis

## Error Handling

```java
try {
    CdsTranche tranche = CdsTranche.builder()
        .attachmentPoint(-0.01)  // INVALID
        .detachmentPoint(0.05)
        // ... other fields
        .build();
} catch (IllegalArgumentException e) {
    System.out.println("Invalid tranche: " + e.getMessage());
    // Output: Invalid tranche: attachmentPoint must be >= 0
}
```

## Conclusion

The CdsTranche implementation provides comprehensive support for CDO tranche pricing and risk analysis within OpenGamma Strata, enabling quantitative analysis of structured credit products.
