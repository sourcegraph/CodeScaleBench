```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="CompanyAcquiredEvent.cs" company="TycoonVerse">
//   © TycoonVerse. All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace TycoonVerse.Core.Events
{
    /// <summary>
    ///     Marker interface used by the domain to flag domain events.  The infrastructure layer contains
    ///     an <see cref="IDomainEventDispatcher" /> responsible for invoking domain and integration handlers.
    ///     This interface is intentionally minimal to avoid polluting the domain with infrastructure concerns.
    /// </summary>
    public interface IDomainEvent
    {
        /// <summary>
        ///     The UTC timestamp when the event was created.
        /// </summary>
        DateTimeOffset OccurredOn { get; }
    }

    /// <summary>
    ///     Dispatches domain events.  Implemented in the Infrastructure layer using reflection-based discovery
    ///     and async task scheduling to avoid blocking the main game loop.
    /// </summary>
    public interface IDomainEventDispatcher
    {
        void Dispatch(IDomainEvent domainEvent);
    }

    /// <summary>
    ///     Strongly-typed representation of money used throughout the domain.
    ///     Keeps arithmetic, currency, and formatting concerns in one place.
    /// </summary>
    public readonly struct Money : IEquatable<Money>, IFormattable
    {
        public Money(decimal amount, string currencyCode)
        {
            if (amount < 0)
                throw new ArgumentOutOfRangeException(nameof(amount), "Amount cannot be negative.");

            if (string.IsNullOrWhiteSpace(currencyCode))
                throw new ArgumentException("Currency code must be provided.", nameof(currencyCode));

            if (currencyCode.Length != 3)
                throw new ArgumentException("Currency code must be a valid ISO 4217 code.", nameof(currencyCode));

            Amount = decimal.Round(amount, 2, MidpointRounding.ToEven);
            CurrencyCode = currencyCode.ToUpperInvariant();
        }

        public decimal Amount { get; }

        public string CurrencyCode { get; }

        public override string ToString() => ToString("C", CultureInfo.CurrentCulture);

        public string ToString(string? format, IFormatProvider? formatProvider)
        {
            var culture = formatProvider as CultureInfo ?? CultureInfo.CurrentCulture;
            var numberFormat = (NumberFormatInfo)culture.NumberFormat.Clone();
            numberFormat.CurrencySymbol = CurrencyCode + " ";
            return Amount.ToString(format, numberFormat);
        }

        public override bool Equals(object? obj) => obj is Money money && Equals(money);

        public bool Equals(Money other) =>
            Amount.Equals(other.Amount) && string.Equals(CurrencyCode, other.CurrencyCode, StringComparison.Ordinal);

        public override int GetHashCode() => HashCode.Combine(Amount, CurrencyCode);

        public static bool operator ==(Money left, Money right) => left.Equals(right);

        public static bool operator !=(Money left, Money right) => !(left == right);
    }

    /// <summary>
    ///     Enumeration describing how the acquisition was executed.
    /// </summary>
    public enum AcquisitionMethod
    {
        /// <summary>
        ///     Acquirer purchased a controlling stake via stock purchase.
        /// </summary>
        EquityPurchase = 0,

        /// <summary>
        ///     Assets were purchased directly; liabilities remain with the seller.
        /// </summary>
        AssetPurchase = 1,

        /// <summary>
        ///     Friendly merger creating a new entity.
        /// </summary>
        Merger = 2,

        /// <summary>
        ///     Hostile takeover.
        /// </summary>
        HostileTakeover = 3
    }

    /// <summary>
    ///     Domain event emitted when one in-game company acquires another.
    ///     Listeners may react by updating leaderboards, adjusting synergies, recording analytics, etc.
    /// </summary>
    public sealed class CompanyAcquiredEvent : IDomainEvent
    {
        private CompanyAcquiredEvent(
            Guid acquirerCompanyId,
            Guid targetCompanyId,
            Money purchasePrice,
            AcquisitionMethod method,
            IReadOnlyDictionary<string, string> meta,
            DateTimeOffset occurredOnUtc)
        {
            AcquirerCompanyId = acquirerCompanyId;
            TargetCompanyId = targetCompanyId;
            PurchasePrice = purchasePrice;
            Method = method;
            Metadata = meta;
            OccurredOn = occurredOnUtc;
        }

        /// <summary>
        ///     Globally unique identifier for the acquiring company.
        /// </summary>
        public Guid AcquirerCompanyId { get; }

        /// <summary>
        ///     Globally unique identifier for the company that was acquired.
        /// </summary>
        public Guid TargetCompanyId { get; }

        /// <summary>
        ///     Final price paid by the acquirer.  Includes any premiums or asset mark-ups.
        /// </summary>
        public Money PurchasePrice { get; }

        /// <summary>
        ///     The strategy / mechanism through which the acquisition completed.
        /// </summary>
        public AcquisitionMethod Method { get; }

        /// <summary>
        ///     Additional data that may be useful for subscribers (e.g., "SynergyScore" or "BoardApproval:Yes").
        ///     Values are guaranteed to be immutable after construction.
        /// </summary>
        public IReadOnlyDictionary<string, string> Metadata { get; }

        /// <inheritdoc />
        public DateTimeOffset OccurredOn { get; }

        /// <summary>
        ///     Creates a <see cref="CompanyAcquiredEvent" /> ensuring argument validation and value-object safety.
        /// </summary>
        /// <exception cref="ArgumentException">When arguments fail validation.</exception>
        public static CompanyAcquiredEvent Create(
            Guid acquirerCompanyId,
            Guid targetCompanyId,
            Money purchasePrice,
            AcquisitionMethod method,
            IDictionary<string, string>? metadata = null)
        {
            if (acquirerCompanyId == Guid.Empty)
                throw new ArgumentException("Acquirer company id cannot be empty.", nameof(acquirerCompanyId));

            if (targetCompanyId == Guid.Empty)
                throw new ArgumentException("Target company id cannot be empty.", nameof(targetCompanyId));

            if (acquirerCompanyId == targetCompanyId)
                throw new ArgumentException("Acquirer and target cannot be the same.", nameof(targetCompanyId));

            if (purchasePrice.Amount <= 0)
                throw new ArgumentException("Purchase price must be greater than zero.", nameof(purchasePrice));

            var immutableMeta = (metadata ?? new Dictionary<string, string>())
                .ToDictionary(kvp => kvp.Key, kvp => kvp.Value, StringComparer.Ordinal);

            return new CompanyAcquiredEvent(
                acquirerCompanyId,
                targetCompanyId,
                purchasePrice,
                method,
                immutableMeta,
                DateTimeOffset.UtcNow);
        }

        /// <summary>
        ///     Converts the event into a plain object suitable for analytics pipelines that require
        ///     simple serialization formats (e.g., JSON).  No game-specific types leak outside.
        /// </summary>
        public object ToAnalyticsPayload() =>
            new
            {
                AcquirerId = AcquirerCompanyId,
                TargetId = TargetCompanyId,
                PurchasePrice = new
                {
                    PurchasePrice.Amount,
                    PurchasePrice.CurrencyCode
                },
                Method = Method.ToString(),
                Metadata,
                OccurredOn = OccurredOn.UtcDateTime
            };
    }
}
```