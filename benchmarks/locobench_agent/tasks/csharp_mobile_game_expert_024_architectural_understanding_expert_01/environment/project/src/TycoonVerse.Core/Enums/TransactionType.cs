```csharp
// -----------------------------------------------------------------------------
//  TycoonVerse: Enterprise Empire Simulator
//  File:       TransactionType.cs
//  Project:    TycoonVerse.Core
//  Author:     TycoonVerse Team
//  -----------------------------------------------------------------------------
//  Description:
//  Enumerates every financial transaction that can occur inside the simulation.
//  The list purposefully mirrors real–world bookkeeping so that the
//  in–game financial statements (Cash-Flow, Balance Sheet, P&L) behave exactly
//  like their real counterparts.  Do NOT reorder values; the numeric identifiers
//  are persisted to local storage and remote analytics.
// -----------------------------------------------------------------------------

using System;
using System.Diagnostics;
using System.Runtime.Serialization;

namespace TycoonVerse.Core.Enums
{
    /// <summary>
    /// Represents the different kinds of financial transactions that can occur
    /// throughout the TycoonVerse simulation loop.
    /// </summary>
    [DataContract]
    public enum TransactionType
    {
        /// <summary>No transaction / placeholder.</summary>
        [EnumMember] None = 0,

        // ---------------------------------------------------------------------
        // Capital & Financing
        // ---------------------------------------------------------------------
        /// <summary>Player injects initial or additional capital into the company.</summary>
        [EnumMember] InitialCapitalInjection = 1,

        /// <summary>New shares are issued for cash consideration.</summary>
        [EnumMember] EquityIssue = 2,

        /// <summary>Company buys back its own shares from the market.</summary>
        [EnumMember] ShareRepurchase = 3,

        /// <summary>Company declares and pays a dividend.</summary>
        [EnumMember] DividendPayout = 4,

        /// <summary>Cash draw from a loan facility.</summary>
        [EnumMember] LoanDrawdown = 5,

        /// <summary>Repayment of loan principal.</summary>
        [EnumMember] LoanRepayment = 6,

        /// <summary>Interest expense associated with outstanding debt.</summary>
        [EnumMember] InterestExpense = 7,

        // ---------------------------------------------------------------------
        // Operating Revenues
        // ---------------------------------------------------------------------
        /// <summary>Cash sale of a manufactured product.</summary>
        [EnumMember] ProductSale = 20,

        /// <summary>Cash sale of a service.</summary>
        [EnumMember] ServiceSale = 21,

        /// <summary>In-app purchase that credits the player’s company balance.</summary>
        [EnumMember] InAppPurchaseCredit = 22,

        /// <summary>Promotional gift or reward granted by the system.</summary>
        [EnumMember] GiftReceived = 23,

        // ---------------------------------------------------------------------
        // Operating Expenses
        // ---------------------------------------------------------------------
        /// <summary>Purchase of raw materials or finished goods inventory.</summary>
        [EnumMember] InventoryPurchase = 40,

        /// <summary>Payment to supplier for previously received inventory.</summary>
        [EnumMember] SupplierPayment = 41,

        /// <summary>Wages and salaries for employees.</summary>
        [EnumMember] WagePayment = 42,

        /// <summary>Facility rental expense.</summary>
        [EnumMember] RentPayment = 43,

        /// <summary>Utilities (electricity, water, data, etc.).</summary>
        [EnumMember] UtilityPayment = 44,

        /// <summary>Insurance premiums.</summary>
        [EnumMember] InsurancePremium = 45,

        /// <summary>Research &amp; Development expenses.</summary>
        [EnumMember] ResearchAndDevelopment = 46,

        /// <summary>Marketing &amp; advertising spend.</summary>
        [EnumMember] Marketing = 47,

        /// <summary>Logistics &amp; shipping costs.</summary>
        [EnumMember] Logistics = 48,

        /// <summary>Legal settlement or lawsuit expense.</summary>
        [EnumMember] LegalSettlement = 49,

        /// <summary>Regulatory penalty or fine.</summary>
        [EnumMember] Penalty = 50,

        /// <summary>Gift or donation sent to another player or NPC.</summary>
        [EnumMember] GiftSent = 51,

        // ---------------------------------------------------------------------
        // Taxation
        // ---------------------------------------------------------------------
        /// <summary>Tax payment (VAT, corporate, import duties, etc.).</summary>
        [EnumMember] TaxPayment = 60,

        // ---------------------------------------------------------------------
        // Investing
        // ---------------------------------------------------------------------
        /// <summary>Acquisition of a long-term asset (e.g., factory, software license).</summary>
        [EnumMember] AssetAcquisition = 80,

        /// <summary>Disposal of a long-term asset for cash.</summary>
        [EnumMember] AssetDisposal = 81,

        /// <summary>Acquisition of another company.</summary>
        [EnumMember] CompanyAcquisition = 82,

        /// <summary>Direct costs associated with integrating an acquired company.</summary>
        [EnumMember] MergerIntegrationCost = 83,

        // ---------------------------------------------------------------------
        // Non-Cash Adjustments
        // ---------------------------------------------------------------------
        /// <summary>Non-cash depreciation entry.</summary>
        [EnumMember] DepreciationExpense = 100,

        /// <summary>Non-cash amortization entry.</summary>
        [EnumMember] AmortizationExpense = 101,

        /// <summary>Fair-value revaluation gain or loss.</summary>
        [EnumMember] ValuationAdjustment = 102
    }

    /// <summary>
    /// Categorizes the cash-flow direction of a <see cref="TransactionType"/>.
    /// </summary>
    public enum CashFlowDirection
    {
        Inflow,
        Outflow,
        NonCash
    }

    /// <summary>
    /// Extension helpers for <see cref="TransactionType"/>.
    /// </summary>
    public static class TransactionTypeExtensions
    {
        /// <summary>
        /// Gets the <see cref="CashFlowDirection"/> for a given transaction.
        /// </summary>
        /// <param name="type">The transaction type.</param>
        public static CashFlowDirection GetDirection(this TransactionType type) =>
            type switch
            {
                TransactionType.None => CashFlowDirection.NonCash,

                // Inflows
                TransactionType.InitialCapitalInjection or
                TransactionType.EquityIssue or
                TransactionType.LoanDrawdown or
                TransactionType.ProductSale or
                TransactionType.ServiceSale or
                TransactionType.AssetDisposal or
                TransactionType.CompanyAcquisition => CashFlowDirection.Inflow, // Sale of acquired subsidiary
                TransactionType.InAppPurchaseCredit or
                TransactionType.GiftReceived => CashFlowDirection.Inflow,

                // Outflows
                TransactionType.ShareRepurchase or
                TransactionType.DividendPayout or
                TransactionType.LoanRepayment or
                TransactionType.InterestExpense or
                TransactionType.InventoryPurchase or
                TransactionType.SupplierPayment or
                TransactionType.WagePayment or
                TransactionType.RentPayment or
                TransactionType.UtilityPayment or
                TransactionType.InsurancePremium or
                TransactionType.ResearchAndDevelopment or
                TransactionType.Marketing or
                TransactionType.Logistics or
                TransactionType.LegalSettlement or
                TransactionType.Penalty or
                TransactionType.GiftSent or
                TransactionType.TaxPayment or
                TransactionType.AssetAcquisition or
                TransactionType.CompanyAcquisition or
                TransactionType.MergerIntegrationCost => CashFlowDirection.Outflow,

                // Non-Cash
                TransactionType.DepreciationExpense or
                TransactionType.AmortizationExpense or
                TransactionType.ValuationAdjustment => CashFlowDirection.NonCash,

                // Fallback (should never occur)
                _ => throw new ArgumentOutOfRangeException(nameof(type), type,
                    $"Unhandled {nameof(TransactionType)} value.")
            };

        /// <summary>
        /// Converts the enum to a human-readable, localized string.
        /// </summary>
        /// <remarks>
        /// In production this would delegate to an I18N service, but the helper
        /// is kept lightweight here to avoid a hard dependency on localization
        /// infrastructure from the core library.
        /// </remarks>
        public static string ToDisplayString(this TransactionType type) =>
            type switch
            {
                TransactionType.None => "N/A",
                _ => SplitPascalCase(type.ToString())
            };

        /// <summary>
        /// Attempts to parse the given string into a <see cref="TransactionType"/>.
        /// </summary>
        /// <param name="value">Raw string value (case-insensitive).</param>
        /// <param name="type">Parsed enum value if successful.</param>
        /// <returns>True if parsing succeeded; otherwise, false.</returns>
        public static bool TryParse(string value, out TransactionType type)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                type = TransactionType.None;
                return false;
            }

            var success = Enum.TryParse(value.Trim(), ignoreCase: true, out type) &&
                          Enum.IsDefined(typeof(TransactionType), type);

            if (!success)
            {
                type = TransactionType.None;
            }

            return success;
        }

        #region — Private Helpers —

        private static string SplitPascalCase(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return string.Empty;

            // Use a simple algorithm to inject spaces before capital letters.
            // e.g. "InAppPurchaseCredit" -> "In App Purchase Credit"
            Span<char> buffer = stackalloc char[value.Length * 2]; // generous allocation
            var index = 0;

            for (var i = 0; i < value.Length; i++)
            {
                var c = value[i];
                if (i > 0 && char.IsUpper(c) && char.IsLower(value[i - 1]))
                {
                    buffer[index++] = ' ';
                }

                buffer[index++] = c;
            }

            return new string(buffer.Slice(0, index));
        }

        #endregion
    }
}
```