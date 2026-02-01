```csharp
#nullable enable
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;

namespace TycoonVerse.Application.DTOs
{
    /// <summary>
    ///     Immutable Data-Transfer Object that represents an In-App-Purchase (IAP) product
    ///     as surfaced by the catalog service and consumed by the application layer.
    /// </summary>
    [DebuggerDisplay("{Title} ({StoreSku})")]
    public sealed record IapProductDto
    {
        /// <summary>Unique identifier inside TycoonVerse’s catalog.</summary>
        [JsonPropertyName("id")]
        public Guid Id { get; init; }

        /// <summary>Native identifier assigned by the mobile storefront (Google Play / App Store).</summary>
        [JsonPropertyName("storeSku")]
        public string StoreSku { get; init; } = string.Empty;

        /// <summary>User-facing product name.</summary>
        [JsonPropertyName("title")]
        public string Title { get; init; } = string.Empty;

        /// <summary>Long-form description presented in the storefront.</summary>
        [JsonPropertyName("description")]
        public string Description { get; init; } = string.Empty;

        /// <summary>
        ///     Price in <b>minor</b> units (e.g. cents).  
        ///     Using <c>long</c> prevents rounding issues in currency math.
        /// </summary>
        [JsonPropertyName("priceMinor")]
        public long PriceInMinorUnits { get; init; }

        /// <summary>ISO-4217 currency code, e.g. <c>"USD"</c>, <c>"EUR"</c>.</summary>
        [JsonPropertyName("currency")]
        public string CurrencyCode { get; init; } = string.Empty;

        /// <summary><c>true</c> when the product is a renewable subscription.</summary>
        [JsonPropertyName("isSubscription")]
        public bool IsSubscription { get; init; }

        /// <summary>
        ///     Additional subscription metadata (<c>null</c> when <see cref="IsSubscription"/> is <c>false</c>).
        /// </summary>
        [JsonPropertyName("subscription")]
        public SubscriptionMeta? Subscription { get; init; }

        /// <summary>
        ///     Determines if the product is currently available for purchase.
        ///     Allows back-office teams to stage catalog entries without re-publishing builds.
        /// </summary>
        [JsonPropertyName("isActive")]
        public bool IsActive { get; init; }

        /// <summary>
        ///     Opaque list of key/value pairs used for quick filtering in telemetry, A/B tests, etc.
        /// </summary>
        [JsonPropertyName("tags")]
        public IReadOnlyDictionary<string, string> Tags { get; init; } = new Dictionary<string, string>();

        #region Convenience Members

        /// <summary>
        ///     Formats the price into a locale-specific string (e.g. <c>$4.99</c>).  
        ///     The caller may override the <paramref name="culture"/>; otherwise the current UI culture is used.
        /// </summary>
        public string GetFormattedPrice(CultureInfo? culture = null)
        {
            culture ??= CultureInfo.CurrentUICulture;

            // NOTE: Most currencies have two decimals; a few (JPY, KRW) have zero.
            // RegionInfo does not expose decimal digits; instead we maintain a hard-coded
            // whitelist of zero-decimal currencies for correct formatting.
            const string ZeroDecimalCurrencies = "BIF,CLP,DJF,GNF,JPY,KMF,KRW,LAK,PYG,RWF,VUV,XAF,XOF,XPF";

            var isZeroDecimal = ZeroDecimalCurrencies.Contains(CurrencyCode, StringComparison.OrdinalIgnoreCase);
            var divisor       = isZeroDecimal ? 1M : 100M;

            var majorUnits = PriceInMinorUnits / divisor;
            var region     = TryGetRegion(CurrencyCode);

            var symbol = region?.CurrencySymbol ?? CurrencyCode.ToUpperInvariant();
            return string.Format(culture, "{0}{1:N" + (isZeroDecimal ? "0" : "2") + "}", symbol, majorUnits);
        }

        /// <summary>Performs defensive validation; throws when inconsistencies are found.</summary>
        /// <exception cref="InvalidOperationException"></exception>
        public void EnsureIsValid()
        {
            if (Id == Guid.Empty)
                ThrowValidation("Product Id must be a non-empty GUID.");

            if (string.IsNullOrWhiteSpace(StoreSku))
                ThrowValidation("Store SKU cannot be null or whitespace.");

            if (string.IsNullOrWhiteSpace(Title))
                ThrowValidation("Title cannot be null or whitespace.");

            if (PriceInMinorUnits <= 0)
                ThrowValidation("Price must be greater than zero minor units.");

            if (!CurrencyCode.IsValidIso4217())
                ThrowValidation($"Invalid currency code: {CurrencyCode}.");

            if (IsSubscription && Subscription is null)
                ThrowValidation("Subscription details must be supplied for subscription products.");

            if (!IsSubscription && Subscription is not null)
                ThrowValidation("Subscription details should be null for one-off purchase products.");

            Subscription?.EnsureIsValid();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void ThrowValidation(string message)
            => throw new InvalidOperationException($"[IapProductDto] {message}");

        private static RegionInfo? TryGetRegion(string isoCurrency)
        {
            try
            {
                return new RegionInfo(isoCurrency.ToUpperInvariant());
            }
            catch (ArgumentException)
            {
                return null;
            }
        }

        #endregion

        #region Nested Types

        /// <summary>Additional metadata associated with renewable subscriptions.</summary>
        public sealed record SubscriptionMeta
        {
            /// <summary>Length of the billing period.</summary>
            public ushort PeriodLength { get; init; }

            /// <summary>Time unit of the billing period.</summary>
            public BillingPeriodUnit PeriodUnit { get; init; }

            /// <summary>Number of free-trial days granted before the first charge (0 when no trial).</summary>
            public ushort TrialDays { get; init; }

            /// <summary>Optional introductory price (minor units); <c>null</c> when not applicable.</summary>
            public long? IntroPriceInMinorUnits { get; init; }

            /// <summary>
            ///     Returns the billing cycle’s <b>approximate</b> duration in days
            ///     (used for analytics; not displayed to the user).
            /// </summary>
            [JsonIgnore]
            public int TotalPeriodInDays => PeriodUnit switch
            {
                BillingPeriodUnit.Day   => PeriodLength,
                BillingPeriodUnit.Week  => PeriodLength * 7,
                BillingPeriodUnit.Month => PeriodLength * 30,
                BillingPeriodUnit.Year  => PeriodLength * 365,
                _                       => throw new ArgumentOutOfRangeException(nameof(PeriodUnit), PeriodUnit, null)
            };

            internal void EnsureIsValid()
            {
                if (PeriodLength == 0)
                    throw new InvalidOperationException("[SubscriptionMeta] Period length must be greater than zero.");

                if (IntroPriceInMinorUnits is not null && IntroPriceInMinorUnits <= 0)
                    throw new InvalidOperationException("[SubscriptionMeta] Intro price, when supplied, must be positive minor units.");
            }
        }

        /// <summary>Units that define subscription billing intervals.</summary>
        public enum BillingPeriodUnit
        {
            Day   = 0,
            Week  = 1,
            Month = 2,
            Year  = 3
        }

        #endregion
    }

    #region Helper Extensions

    internal static class CurrencyCodeExtensions
    {
        /// <summary>
        ///     Checks whether the supplied value is a valid three-letter ISO-4217 currency code.
        /// </summary>
        public static bool IsValidIso4217(this string? value)
        {
            if (string.IsNullOrWhiteSpace(value) || value.Length != 3)
                return false;

            try
            {
                _ = new RegionInfo(value.ToUpperInvariant());
                return true;
            }
            catch (ArgumentException)
            {
                // RegionInfo throws when the currency code is unknown.
                return false;
            }
        }
    }

    #endregion
}
```