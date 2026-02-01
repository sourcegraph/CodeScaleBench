```csharp
#nullable enable
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Text.Json.Serialization;

namespace TycoonVerse.Application.DTOs
{
    /// <summary>
    /// Immutable Data-Transfer-Object that represents a snapshot of a company
    /// inside the TycoonVerse simulation.  
    ///
    /// The DTO purposefully contains no domain logic other than self-validation
    /// so that it can safely travel across layers (API ↔ local storage ↔ Unity UI).
    /// </summary>
    public sealed class CompanyDto : IValidatableObject
    {
        // ---------------------------------------------------------------------
        // Core Identity
        // ---------------------------------------------------------------------

        /// <summary>
        /// Stable identifier for the company, generated in the domain layer.
        /// </summary>
        [Required]
        public Guid Id { get; init; }

        /// <summary>
        /// Human-readable company name (2-100 characters).
        /// </summary>
        [Required, StringLength(100, MinimumLength = 2)]
        public string Name { get; init; } = string.Empty;

        /// <summary>
        /// Industry classification (e.g., "Software", "Consumer Goods").
        /// Stored as plain text for simplicity; the domain translates this to
        /// a NAICS code when needed.
        /// </summary>
        [Required, StringLength(50)]
        public string Industry { get; init; } = string.Empty;

        // ---------------------------------------------------------------------
        // Lifecycle Information
        // ---------------------------------------------------------------------

        /// <summary>
        /// Date the company was founded (UTC).
        /// Nullable because a new company might still be "in planning".
        /// </summary>
        [JsonPropertyName("founded")]
        public DateTime? FoundedDate { get; init; }

        /// <summary>
        /// Timestamp (UTC) when the domain last updated the snapshot.
        /// </summary>
        public DateTime LastUpdatedUtc { get; init; } = DateTime.UtcNow;

        // ---------------------------------------------------------------------
        // Quantitative Metrics
        // ---------------------------------------------------------------------

        [Range(0, int.MaxValue)]
        public int Employees { get; init; }

        [Range(0d, double.MaxValue)]
        public decimal Revenue { get; init; }

        /// <remarks>
        /// Profit may be negative, hence no <see cref="RangeAttribute"/>.
        /// </remarks>
        public decimal Profit { get; init; }

        [Range(0d, double.MaxValue)]
        public decimal Assets { get; init; }

        [Range(0d, double.MaxValue)]
        public decimal Liabilities { get; init; }

        // ---------------------------------------------------------------------
        // Market Details
        // ---------------------------------------------------------------------

        /// <summary>
        /// True when the company has completed an IPO and is actively traded.
        /// </summary>
        public bool IsPublic { get; init; }

        /// <summary>
        /// Stock market ticker (1-5 chars). Required only if <see cref="IsPublic"/> is true.
        /// </summary>
        [StringLength(5, MinimumLength = 1)]
        public string? StockTicker { get; init; }

        // ---------------------------------------------------------------------
        // Miscellaneous Presentation Data
        // ---------------------------------------------------------------------

        /// <summary>
        /// ISO-3166-1 alpha-2 country code for the corporate HQ.
        /// </summary>
        [Required, StringLength(2, MinimumLength = 2)]
        public string CountryCode { get; init; } = "US";

        /// <summary>
        /// CDN URL referencing the current logo texture.
        /// </summary>
        [Url]
        public string? LogoUrl { get; init; }

        // ---------------------------------------------------------------------
        // Computed Convenience Properties
        // ---------------------------------------------------------------------

        /// <summary>
        /// Book-value equity (Assets − Liabilities).
        /// </summary>
        [JsonIgnore]
        public decimal Equity => Assets - Liabilities;

        /// <summary>
        /// Debt-to-equity ratio (null when equity ≤ 0 to avoid division by zero).
        /// </summary>
        [JsonIgnore]
        public decimal? DebtToEquity
            => Equity <= 0 ? null : Liabilities / Equity;

        /// <summary>
        /// Indicates whether the company is economically solvent.
        /// </summary>
        [JsonIgnore]
        public bool IsSolvent => Assets >= Liabilities;

        // ---------------------------------------------------------------------
        // Validation
        // ---------------------------------------------------------------------

        /// <inheritdoc />
        public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
        {
            // IPO consistency check
            if (IsPublic && string.IsNullOrWhiteSpace(StockTicker))
            {
                yield return new ValidationResult(
                    "A publicly traded company must define a stock ticker.",
                    new[] { nameof(StockTicker) });
            }

            // Founded date must be UTC to avoid subtle timezone bugs when syncing
            if (FoundedDate is { Kind: not DateTimeKind.Utc })
            {
                yield return new ValidationResult(
                    "FoundedDate must be expressed in UTC.",
                    new[] { nameof(FoundedDate) });
            }

            // Balance sheet sanity
            if (Assets < Liabilities)
            {
                yield return new ValidationResult(
                    "Assets must be greater than or equal to Liabilities.",
                    new[] { nameof(Assets), nameof(Liabilities) });
            }
        }

        // ---------------------------------------------------------------------
        // Overrides
        // ---------------------------------------------------------------------

        public override string ToString() =>
            $"{Name} [{Industry}] — Rev: {Revenue:N0}cr, Profit: {Profit:N0}cr";
    }
}
```