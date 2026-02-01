```csharp
#nullable enable
using System;
using System.Globalization;

namespace TycoonVerse.Core.ValueObjects
{
    /// <summary>
    ///     Represents a parcel of common stock owned by the player.
    ///     StockShare is a Domain-Driven-Design “Value Object”—it is immutable
    ///     and equality is determined by the value of its properties rather
    ///     than object identity.
    /// </summary>
    public sealed class StockShare : IEquatable<StockShare>
    {
        /// <summary>
        ///     Ticker symbol (ISO-10383 MIC + company code), e.g. “NASDAQ:TSLA”.
        ///     In TycoonVerse every virtual company receives a unique ticker
        ///     once it files an IPO in the in-game exchange.
        /// </summary>
        public string Ticker { get; }

        /// <summary>
        ///     Number of shares held.
        ///     Always a positive integer. Zero-share parcels are illegal and
        ///     prevented by factory and modifiers.
        /// </summary>
        public int Quantity { get; }

        /// <summary>
        ///     Average cost basis per share at the time of purchase.
        ///     Affects capital-gain calculations when the player sells.
        /// </summary>
        public decimal CostBasisPerShare { get; }

        /// <summary>
        ///     Total cost basis = Quantity × CostBasisPerShare.
        /// </summary>
        public decimal TotalCostBasis => Math.Round(Quantity * CostBasisPerShare, 2, MidpointRounding.AwayFromZero);

        #region Ctor / Factory

        private StockShare(string ticker, int quantity, decimal costBasisPerShare)
        {
            Ticker             = ticker;
            Quantity           = quantity;
            CostBasisPerShare  = costBasisPerShare;
        }

        /// <summary>
        ///     Creates a new StockShare value object after validating input.
        /// </summary>
        /// <exception cref="ArgumentException">If validation fails.</exception>
        public static StockShare Create(string ticker, int quantity, decimal costBasisPerShare)
        {
            GuardAgainstInvalidTicker(ticker);
            GuardAgainstNonPositive(quantity, nameof(quantity));
            GuardAgainstNonPositive(costBasisPerShare, nameof(costBasisPerShare));

            return new StockShare(ticker.ToUpperInvariant(), quantity, RoundMoney(costBasisPerShare));
        }

        #endregion

        #region Behavioural Modifiers (All Return New Instances)

        /// <summary>
        ///     Returns a new instance that combines the current parcel with an
        ///     additional purchase.
        /// </summary>
        public StockShare AddShares(int additionalQuantity, decimal purchasePricePerShare)
        {
            GuardAgainstNonPositive(additionalQuantity, nameof(additionalQuantity));
            GuardAgainstNonPositive(purchasePricePerShare, nameof(purchasePricePerShare));

            // Weighted-average cost basis
            var newTotalShares = Quantity + additionalQuantity;
            var combinedCost   = TotalCostBasis + additionalQuantity * purchasePricePerShare;
            var newAvgCost     = RoundMoney(combinedCost / newTotalShares);

            return new StockShare(Ticker, newTotalShares, newAvgCost);
        }

        /// <summary>
        ///     Returns a new instance representing a partial sale.
        /// </summary>
        /// <param name="sellQuantity">Number of shares to remove.</param>
        /// <exception cref="InvalidOperationException">
        ///     When attempting to sell more shares than owned.
        /// </exception>
        public StockShare RemoveShares(int sellQuantity)
        {
            GuardAgainstNonPositive(sellQuantity, nameof(sellQuantity));

            if (sellQuantity > Quantity)
                throw new InvalidOperationException(
                    $"Cannot sell {sellQuantity} shares of {Ticker}; only {Quantity} owned.");

            var remaining = Quantity - sellQuantity;

            if (remaining == 0)
                throw new InvalidOperationException(
                    $"Selling all shares would remove the parcel entirely. " +
                    $"Use the portfolio repository to delete the holding instead.");

            return new StockShare(Ticker, remaining, CostBasisPerShare);
        }

        /// <summary>
        ///     Applies a corporate stock split.
        ///     For example, <paramref name="splitRatio"/> = 2 means a 2-for-1 split,
        ///     doubling share count and halving cost basis per share.
        /// </summary>
        public StockShare ApplySplit(decimal splitRatio)
        {
            GuardAgainstNonPositive(splitRatio, nameof(splitRatio));

            var newQuantity = (int)Math.Round(Quantity * splitRatio, MidpointRounding.AwayFromZero);
            var newCost     = RoundMoney(CostBasisPerShare / splitRatio);

            if (newQuantity == 0)
                throw new InvalidOperationException("Split operation resulted in zero shares, which is not allowed.");

            return new StockShare(Ticker, newQuantity, newCost);
        }

        #endregion

        #region Domain Calculations

        /// <summary>
        ///     Current market value at a given price.
        /// </summary>
        public decimal MarketValue(decimal marketPricePerShare) =>
            RoundMoney(Quantity * marketPricePerShare);

        /// <summary>
        ///     Unrealized gain (or loss) at the given market price.
        /// </summary>
        public decimal UnrealizedGain(decimal marketPricePerShare) =>
            RoundMoney(MarketValue(marketPricePerShare) - TotalCostBasis);

        #endregion

        #region Equality

        public bool Equals(StockShare? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            return Ticker == other.Ticker &&
                   Quantity == other.Quantity &&
                   CostBasisPerShare == other.CostBasisPerShare;
        }

        public override bool Equals(object? obj) => Equals(obj as StockShare);

        public override int GetHashCode() =>
            HashCode.Combine(Ticker, Quantity, CostBasisPerShare);

        public static bool operator ==(StockShare? left, StockShare? right) => Equals(left, right);
        public static bool operator !=(StockShare? left, StockShare? right) => !Equals(left, right);

        #endregion

        #region Utility Helpers

        private static void GuardAgainstNonPositive<T>(T value, string paramName) where T : struct, IComparable<T>
        {
            if (value.CompareTo(default) <= 0)
                throw new ArgumentException($"{paramName} must be positive.", paramName);
        }

        private static void GuardAgainstInvalidTicker(string? ticker)
        {
            if (string.IsNullOrWhiteSpace(ticker))
                throw new ArgumentException("Ticker must be a non-empty string.", nameof(ticker));

            // Very light validation: must have at least one ':' separating MIC and code.
            if (!ticker.Contains(':', StringComparison.Ordinal))
                throw new ArgumentException(
                    "Ticker must be in format \"<MIC>:<SYMBOL>\", e.g., \"NASDAQ:TSLA\".",
                    nameof(ticker));
        }

        private static decimal RoundMoney(decimal value) =>
            Math.Round(value, 4, MidpointRounding.AwayFromZero);

        public override string ToString()
        {
            return string.Create(CultureInfo.InvariantCulture,
                $"[{Ticker}] Qty={Quantity:N0}, Cost/Share={CostBasisPerShare:C}, Cost Total={TotalCostBasis:C}");
        }

        #endregion
    }
}
```