# CdsTranche Architecture Overview

## System Context

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenGamma Strata                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            Product Module (Credit Domain)            │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  CDS Products:                                 │  │  │
│  │  │  • Cds, CdsTrade, ResolvedCds, ResolvedCdsTrade│  │  │
│  │  │  • CdsIndex, CdsIndexTrade, ResolvedCdsIndex  │  │  │
│  │  │  • CdsTranche, CdsTrancheTrade (NEW)          │  │  │
│  │  │    ResolvedCdsTranche, ResolvedCdsTrancheTrade│  │  │
│  │  │                                                 │  │  │
│  │  │  ProductType.CDS_TRANCHE (NEW)                 │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           Pricer Module (Credit Pricing)             │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  ISDA Pricers:                                │  │  │
│  │  │  • IsdaCdsProductPricer                       │  │  │
│  │  │  • IsdaHomogenousCdsIndexProductPricer        │  │  │
│  │  │  • IsdaCdsTranchePricer (NEW)                 │  │  │
│  │  │                                                │  │  │
│  │  │  Pricing Algorithm:                           │  │  │
│  │  │  ├─ For CdsTranche:                          │  │  │
│  │  │  │  PV = PV(index @ det point)              │  │  │
│  │  │  │       - PV(index @ attach point)          │  │  │
│  │  │  │                                            │  │  │
│  │  │  │  Loss allocation = (det - attach) * PV   │  │  │
│  │  │  └─ Uses underlying IsdaCdsProductPricer      │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Measure Module (Risk Calculation)            │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  Calculation Functions:                       │  │  │
│  │  │  • CdsTradeCalculationFunction                │  │  │
│  │  │  • CdsIndexTradeCalculationFunction           │  │  │
│  │  │  • CdsTrancheTradeCalculationFunction (NEW)   │  │  │
│  │  │                                                │  │  │
│  │  │  Measure Calculations:                        │  │  │
│  │  │  • CdsMeasureCalculations                     │  │  │
│  │  │  • CdsIndexMeasureCalculations                │  │  │
│  │  │  • CdsTrancheMeasureCalculations (NEW)        │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Class Hierarchy and Relationships

### Product Hierarchy
```
Product (interface)
├─ Cds
├─ CdsIndex
└─ CdsTranche (NEW)
   └─ Contains: CdsIndex (underlyingIndex)
```

### Trade Hierarchy
```
ProductTrade (interface)
├─ CdsTrade
├─ CdsIndexTrade
└─ CdsTrancheTrade (NEW)
   └─ Contains: CdsTranche
```

### Resolved Product Hierarchy
```
ResolvedProduct (interface)
├─ ResolvedCds
├─ ResolvedCdsIndex
└─ ResolvedCdsTranche (NEW)
   └─ Contains: ResolvedCdsIndex (underlyingIndex)
```

### Resolved Trade Hierarchy
```
ResolvedTrade (interface)
├─ ResolvedCdsTrade
├─ ResolvedCdsIndexTrade
└─ ResolvedCdsTrancheTrade (NEW)
   └─ Contains: ResolvedCdsTranche
```

## Composition Pattern

```
CdsTranche
├─ buySell: BuySell
├─ underlyingIndex: CdsIndex ────────────────┐
│                                           │
├─ attachmentPoint: double                  │
├─ detachmentPoint: double                  │
│                                           │
├─ currency: Currency                       │
├─ notional: double                         │
├─ fixedRate: double                        │
│                                           │
├─ paymentSchedule: PeriodicSchedule        │
├─ dayCount: DayCount                       │
├─ paymentOnDefault: PaymentOnDefault       │
├─ protectionStart: ProtectionStartOfDay    │
├─ stepinDateOffset: DaysAdjustment         │
└─ settlementDateOffset: DaysAdjustment     │
                                            │
     CdsIndex (underlying)                  │
     ├─ cdsIndexId: StandardId <───────────┘
     ├─ legalEntityIds: List<StandardId>
     ├─ paymentSchedule: PeriodicSchedule
     ├─ fixedRate: double
     ├─ notional: double
     └─ ... (other params)
```

## Resolution Flow

```
CdsTrancheTrade (unresolved)
    ↓
trade.resolve(refData)
    ↓
ResolvedCdsTrancheTrade
    ├─ info: TradeInfo
    └─ product: ResolvedCdsTranche
        ├─ buySell, attachmentPoint, detachmentPoint, ...
        └─ underlyingIndex: ResolvedCdsIndex
            ├─ paymentPeriods: List<CreditCouponPaymentPeriod>
            ├─ protectionEndDate: LocalDate
            ├─ cdsIndexId, legalEntityIds
            └─ ... (standard fields)
```

## Pricing Flow

```
ResolvedCdsTrancheTrade
    ↓
IsdaCdsTranchePricer.presentValue()
    ├─ Step 1: Resolve underlying CdsIndex to ResolvedCdsIndex
    │
    ├─ Step 2: Calculate "notional at detachment point"
    │          = tranche.notional / (detachment - attachment)
    │
    ├─ Step 3: Price protection up to detachment point
    │          using IsdaCdsProductPricer
    │          pvDetachment = cdsProductPricer.price(...)
    │
    ├─ Step 4: If attachment > 0, price protection up to attachment point
    │          pvAttachment = cdsProductPricer.price(...)
    │
    ├─ Step 5: Apply loss allocation
    │          tranchePV = (pvDetachment - pvAttachment)
    │                    * (detachment - attachment)
    │                    * tranche.notional
    │
    └─ Step 6: Return CurrencyAmount with currency and PV
```

## Loss Allocation Semantics

### Example: CDX HY Tranche Structure

```
Index Portfolio (100 entities, $1B)
│
├─ Equity Tranche [0%-3%]      ← First to absorb losses
│  └─ Attachment: 0%, Detachment: 3%
│  └─ Covers: $0M to $30M in cumulative defaults
│
├─ Mezzanine Tranche [3%-7%]   ← Second to absorb losses
│  └─ Attachment: 3%, Detachment: 7%
│  └─ Covers: $30M to $70M in cumulative defaults
│
├─ Senior Tranche [7%-15%]      ← Third to absorb losses
│  └─ Attachment: 7%, Detachment: 15%
│  └─ Covers: $70M to $150M in cumulative defaults
│
└─ Super-Senior [15%-30%]       ← Last to absorb losses
   └─ Attachment: 15%, Detachment: 30%
   └─ Covers: $150M to $300M in cumulative defaults
```

### Pricing Example

Given:
- Index spread: 100bp
- Notional: $1M
- Equity tranche [0%-3%]: attachment=0.0, detachment=0.03

Calculation:
```
PV(index @ 3%) = price of protection up to 3% of losses
PV(index @ 0%) = price of protection up to 0% of losses (=0)

Equity PV = (PV(3%) - PV(0%)) = PV(3%)
```

Higher attachment = lower PV (less protection covers this portion)

## Field Mapping Between Levels

```
CdsTranche                    ResolvedCdsTranche
├─ underlyingIndex: CdsIndex  ├─ underlyingIndex: ResolvedCdsIndex
│                             │  └─ includes paymentPeriods
│                             │  └─ includes protectionEndDate
├─ paymentSchedule            (not in resolved - derived from index)
├─ fixedRate                  ├─ fixedRate (passed through)
├─ notional                   ├─ notional (passed through)
├─ currency                   ├─ currency (passed through)
├─ dayCount                   ├─ dayCount (passed through)
├─ paymentOnDefault           ├─ paymentOnDefault (passed through)
├─ protectionStart            ├─ protectionStart (passed through)
├─ stepinDateOffset           ├─ stepinDateOffset (passed through)
├─ settlementDateOffset       └─ settlementDateOffset (passed through)
└─ attachmentPoint            └─ attachmentPoint (passed through)
                              └─ detachmentPoint (passed through)
```

## Measure Calculation Flow

```
CdsTrancheTradeCalculationFunction
    ↓
requirements()
    ├─ Extracts legal entity IDs from underlying index
    └─ Returns credit curve requirements for those entities

calculate()
    ├─ Resolves trade
    ├─ Gets CreditRatesProvider from market data
    └─ Delegates to CdsTrancheMeasureCalculations

CdsTrancheMeasureCalculations
    ├─ presentValue()
    │  └─ IsdaCdsTranchePricer.presentValue()
    ├─ unitPrice()
    │  └─ presentValue() / notional
    ├─ principal()
    │  └─ notional as CurrencyAmount
    ├─ cs01Parallel()
    │  └─ Credit spread sensitivity
    └─ ir01Parallel()
       └─ Interest rate sensitivity
```

## Integration Points with Strata Calc Engine

```
Strata Calc Engine
    ↓
CalculationFunctionRegistry
    ├─ Discovers CdsTradeCalculationFunction
    ├─ Discovers CdsIndexTradeCalculationFunction
    └─ Discovers CdsTrancheTradeCalculationFunction (NEW)
        ↓
        CdsTrancheTradeCalculationFunction.calculate()
            ↓
            CdsTrancheMeasureCalculations
                ↓
                IsdaCdsTranchePricer
```

## Data Flow for a Tranche Trade Calculation

```
User Input: CdsTrancheTrade
     ↓
[Calc Engine]
     ├─ Calls CdsTrancheTradeCalculationFunction.requirements()
     │  └─ Returns: credit curves for [Bank A, Bank B, Bank C, ...]
     │
     ├─ Retrieves market data (credit curves, discount curves)
     │  └─ Builds CreditRatesProvider
     │
     ├─ Calls CdsTrancheTradeCalculationFunction.calculate()
     │  └─ Resolves CdsTrancheTrade → ResolvedCdsTrancheTrade
     │  └─ Calls CdsTrancheMeasureCalculations methods
     │     └─ Calls IsdaCdsTranchePricer methods
     │        └─ Uses CreditRatesProvider to get survival probabilities
     │           and discount factors
     │
     └─ Returns results
        ├─ PresentValue: CurrencyAmount
        ├─ UnitPrice: double
        ├─ Principal: CurrencyAmount
        ├─ CS01Parallel: CurrencyAmount
        └─ ... (other measures)
```

## Key Design Decisions

### 1. Composition over Inheritance
- CdsTranche contains CdsIndex rather than extending it
- Allows independent evolution of tranche pricing logic
- Cleaner separation of concerns

### 2. Loss-on-Loss Pricing
- Tranche PV = Expected loss between attachment and detachment points
- Computed as difference of index prices at key loss levels
- Aligns with market convention for CDO tranche pricing

### 3. Resolution Pattern Consistency
- Follows existing Cds/CdsIndex patterns
- Lazy resolution: Product → Trade → Resolved forms
- Reference data applied at resolution time

### 4. Measure Delegation
- Calculation function delegates to measure calculations class
- Measure calculations class delegates to pricer
- Pricer delegates to underlying ISDA CDS pricer where appropriate
- Clean separation of concerns across layers

### 5. Immutability
- All product and resolved classes are immutable
- All trades are immutable
- Builders used for construction
- Thread-safe throughout

## Extension Points for Future Enhancement

1. **Synthetic CDO Portfolio Analytics**
   - Add portfolio-level tranche risk calculations
   - Correlation effects between tranches

2. **Advanced Tranche Pricing Models**
   - Gaussian copula models for portfolio loss distribution
   - Stochastic default intensity models
   - One-factor models vs. multi-factor models

3. **Tranche Valuation Adjustments**
   - Credit valuation adjustment (CVA)
   - Debit valuation adjustment (DVA)
   - Funding valuation adjustment (FVA)

4. **Market Data Support**
   - Tranche quote parsers (base correlation, compound spread)
   - Tranche volatility models
   - Term structure of attachment/detachment points

5. **Trade Analytics**
   - Hedge effectiveness analysis
   - Tranche-specific Greeks
   - Roll-down and carry analysis
