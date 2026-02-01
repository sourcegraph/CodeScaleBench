```csharp
using System;
using System.Globalization;

namespace TycoonVerse.Core.Events
{
    /// <summary>
    /// Marker interface for domain-level events that are broadcast through the in-process
    /// event dispatcher (Observer pattern) and, if required, persisted for eventual outbox
    /// integration.  Each event must expose the point in time it was raised so that
    /// consumers (e.g., projections, analytics) can reason about ordering.
    /// </summary>
    public interface IDomainEvent
    {
        /// <summary>
        /// UTC timestamp when the event was created.
        /// </summary>
        DateTimeOffset OccurredOnUtc { get; }
    }

    /// <summary>
    /// Immutable event raised whenever a market-tracked item’s unit price changes.
    /// Down-stream handlers typically update UI widgets, refresh cached leaderboards,
    /// or schedule A/B telemetry checkpoints.
    /// </summary>
    /// <remarks>
    /// This event is intentionally verbose so that it can serve multiple bounded contexts
    /// (e.g., Supply Chain, Accounting) without the need for fragile up-casting.
    /// </remarks>
    [Serializable]
    public sealed class MarketPriceChangedEvent : IDomainEvent, IEquatable<MarketPriceChangedEvent>
    {
        /// <summary>The item or commodity identifier that experienced the price change.</summary>
        public Guid ItemId { get; }

        /// <summary>Human-readable name of the item as captured at event creation.</summary>
        public string ItemName { get; }

        /// <summary>Region code in ISO-3166 format (e.g., <c>US</c>, <c>JP</c>).</summary>
        public string RegionCode { get; }

        /// <summary>Currency code in ISO-4217 format (e.g., <c>USD</c>, <c>JPY</c>).</summary>
        public string CurrencyCode { get; }

        /// <summary>Previous unit price before the change.</summary>
        public decimal OldPrice { get; }

        /// <summary>New unit price after the change.</summary>
        public decimal NewPrice { get; }

        /// <summary>Computed delta (<c>NewPrice − OldPrice</c>).</summary>
        public decimal AbsoluteChange { get; }

        /// <summary>Computed percentage change relative to <see cref="OldPrice" />.</summary>
        public decimal PercentageChange { get; }

        /// <inheritdoc />
        public DateTimeOffset OccurredOnUtc { get; }

        #region ctor & factory members

        /// <summary>
        /// Creates a new <see cref="MarketPriceChangedEvent" /> instance.
        /// </summary>
        /// <exception cref="ArgumentOutOfRangeException">
        /// Thrown when <paramref name="oldPrice" /> or <paramref name="newPrice" /> is negative.
        /// </exception>
        /// <exception cref="ArgumentException">
        /// Thrown when required string parameters are null or whitespace, or when they do not conform
        /// to expected ISO formats.
        /// </exception>
        public MarketPriceChangedEvent(
            Guid itemId,
            string itemName,
            decimal oldPrice,
            decimal newPrice,
            string currencyCode,
            string regionCode,
            DateTimeOffset? occurredOnUtc = null)
        {
            if (oldPrice < 0)
                throw new ArgumentOutOfRangeException(nameof(oldPrice), oldPrice,
                    "Old price cannot be negative.");

            if (newPrice < 0)
                throw new ArgumentOutOfRangeException(nameof(newPrice), newPrice,
                    "New price cannot be negative.");

            if (string.IsNullOrWhiteSpace(itemName))
                throw new ArgumentException("Item name is required.", nameof(itemName));

            if (string.IsNullOrWhiteSpace(currencyCode))
                throw new ArgumentException("Currency code is required.", nameof(currencyCode));

            if (string.IsNullOrWhiteSpace(regionCode))
                throw new ArgumentException("Region code is required.", nameof(regionCode));

            if (!IsValidIso4217(currencyCode))
                throw new ArgumentException("Currency code must be a valid ISO-4217 value.", nameof(currencyCode));

            if (!IsValidIso3166(regionCode))
                throw new ArgumentException("Region code must be a valid ISO-3166 value.", nameof(regionCode));

            ItemId           = itemId;
            ItemName         = itemName.Trim();
            OldPrice         = oldPrice;
            NewPrice         = newPrice;
            CurrencyCode     = currencyCode.ToUpperInvariant();
            RegionCode       = regionCode.ToUpperInvariant();
            AbsoluteChange   = newPrice - oldPrice;
            PercentageChange = oldPrice == 0M ? 100M : (AbsoluteChange / oldPrice) * 100M;
            OccurredOnUtc    = occurredOnUtc?.UtcDateTime ?? DateTimeOffset.UtcNow;
        }

        #endregion

        #region equality members

        public bool Equals(MarketPriceChangedEvent? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            // Identity is defined by the tuple (ItemId, OccurredOnUtc)
            return ItemId == other.ItemId && OccurredOnUtc.Equals(other.OccurredOnUtc);
        }

        public override bool Equals(object? obj) => Equals(obj as MarketPriceChangedEvent);

        public override int GetHashCode() => HashCode.Combine(ItemId, OccurredOnUtc);

        #endregion

        public override string ToString() =>
            $"{ItemName} price changed from {OldPrice.ToString("C", CultureInfo.InvariantCulture)} " +
            $"to {NewPrice.ToString("C", CultureInfo.InvariantCulture)} " +
            $"({PercentageChange:F2}% in {CurrencyCode}, {RegionCode}) at {OccurredOnUtc:u}.";

        #region ISO validation helpers

        private static bool IsValidIso4217(string code)
        {
            // A more exhaustive check would consult an embedded resource or configuration file
            // containing all valid ISO-4217 codes.  For brevity, we do a simple length check here.
            return code.Length == 3 && IsAllLetters(code);
        }

        private static bool IsValidIso3166(string code)
        {
            // ISO-3166 alpha-2 codes are always exactly 2 letters.
            return code.Length == 2 && IsAllLetters(code);
        }

        private static bool IsAllLetters(ReadOnlySpan<char> span)
        {
            foreach (var c in span)
            {
                if (!char.IsLetter(c))
                    return false;
            }

            return true;
        }

        #endregion
    }
}
```