using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Reflection;
using System.Text.Json.Serialization;

namespace TycoonVerse.Core.Enums
{
    /// <summary>
    /// Specifies the broad industry classifications available for player-owned
    /// companies within TycoonVerse.  The enum is annotated with rich metadata
    /// so that simulation engines can reason about default EBITDA margins and
    /// market-specific volatility without hardcoding magic numbers.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))] // Ensures enum is serialized as a string.
    public enum IndustryType
    {
        [IndustryMetadata(0.08, 0.25)]
        Agriculture = 1,

        [IndustryMetadata(0.12, 0.40)]
        Mining = 2,

        [IndustryMetadata(0.15, 0.30)]
        Manufacturing = 3,

        [IndustryMetadata(0.10, 0.20)]
        Logistics = 4,

        [IndustryMetadata(0.06, 0.18)]
        Retail = 5,

        [IndustryMetadata(0.07, 0.22)]
        Hospitality = 6,

        [IndustryMetadata(0.30, 0.35)]
        Technology = 7,

        [IndustryMetadata(0.25, 0.20)]
        Healthcare = 8,

        [IndustryMetadata(0.20, 0.45)]
        Energy = 9,

        [IndustryMetadata(0.28, 0.30)]
        FinancialServices = 10,

        [IndustryMetadata(0.40, 0.25)]
        RealEstate = 11,

        [IndustryMetadata(0.22, 0.35)]
        Telecommunications = 12,

        [IndustryMetadata(0.12, 0.30)]
        Media = 13,

        [IndustryMetadata(0.18, 0.50)]
        Aerospace = 14,

        [IndustryMetadata(0.12, 0.35)]
        Automotive = 15,

        [IndustryMetadata(0.32, 0.25)]
        Pharmaceuticals = 16,

        [IndustryMetadata(0.08, 0.15)]
        FoodAndBeverage = 17,

        [IndustryMetadata(0.25, 0.10)]
        Utilities = 18,

        [IndustryMetadata(0.07, 0.35)]
        Construction = 19,

        [IndustryMetadata(0.09, 0.30)]
        ECommerce = 20,

        [IndustryMetadata(0.35, 0.50)]
        Gaming = 21,

        [IndustryMetadata(0.40, 0.60)]
        ArtificialIntelligence = 22,

        [IndustryMetadata(0.42, 0.65)]
        Blockchain = 23,

        [IndustryMetadata(0.33, 0.40)]
        CloudComputing = 24,

        [IndustryMetadata(0.37, 0.50)]
        CyberSecurity = 25,

        [IndustryMetadata(0.25, 0.20)]
        Consulting = 26,

        [IndustryMetadata(0.08, 0.15)]
        Education = 27,

        [IndustryMetadata(0.25, 0.25)]
        Insurance = 28,

        [IndustryMetadata(0.06, 0.30)]
        Tourism = 29,

        [IndustryMetadata(0.12, 0.20)]
        WasteManagement = 30
    }

    /// <summary>
    /// Provides financial heuristics for each <see cref="IndustryType"/>.
    /// Values are expressed as ratios (0–1) to keep units consistent across
    /// the simulation layers.
    /// </summary>
    [AttributeUsage(AttributeTargets.Field)]
    public sealed class IndustryMetadataAttribute : Attribute
    {
        public double AverageEbitdaMargin { get; }
        public double Volatility { get; }

        public IndustryMetadataAttribute(double averageEbitdaMargin, double volatility)
        {
            if (averageEbitdaMargin < 0 || averageEbitdaMargin > 1)
                throw new ArgumentOutOfRangeException(nameof(averageEbitdaMargin),
                    "EBITDA margin must be expressed as a value between 0 and 1.");

            if (volatility < 0)
                throw new ArgumentOutOfRangeException(nameof(volatility),
                    "Volatility must be zero or a positive value.");

            AverageEbitdaMargin = averageEbitdaMargin;
            Volatility = volatility;
        }
    }

    /// <summary>
    /// Extension helpers that expose strongly-typed access to
    /// <see cref="IndustryMetadataAttribute"/> and perform basic calculations
    /// used by the economic engine.
    /// </summary>
    public static class IndustryTypeExtensions
    {
        private static readonly ConcurrentDictionary<IndustryType, IndustryMetadataAttribute> _metadataCache =
            new ConcurrentDictionary<IndustryType, IndustryMetadataAttribute>();

        /// <summary>
        /// Returns the metadata attached to the enum value.  If no metadata is
        /// declared (should never happen in production), a neutral default is
        /// returned so that callers do not have to guard against nulls.
        /// </summary>
        public static IndustryMetadataAttribute Metadata(this IndustryType industry)
        {
            return _metadataCache.GetOrAdd(industry, key =>
            {
                var member = typeof(IndustryType).GetMember(key.ToString()).FirstOrDefault();
                var attribute = member?.GetCustomAttribute<IndustryMetadataAttribute>();

                // Fail-soft approach: provide sane defaults if metadata is missing.
                return attribute ?? new IndustryMetadataAttribute(0.10, 0.50);
            });
        }

        /// <summary>
        /// Calculates the expected EBITDA for an amount of revenue given the
        /// industry's average margin.  This is intentionally simplistic;
        /// higher-fidelity calculations belong in the financial domain layer.
        /// </summary>
        /// <param name="industry">The industry whose margin to apply.</param>
        /// <param name="revenue">Revenue in in-game currency units.</param>
        /// <returns>Projected EBITDA in the same currency.</returns>
        /// <exception cref="ArgumentOutOfRangeException">
        /// Thrown when revenue is negative.
        /// </exception>
        public static double ExpectedEbitda(this IndustryType industry, double revenue)
        {
            if (revenue < 0)
                throw new ArgumentOutOfRangeException(nameof(revenue), "Revenue cannot be negative.");

            var margin = industry.Metadata().AverageEbitdaMargin;
            return revenue * margin;
        }

        /// <summary>
        /// Provides a crude risk-adjusted return metric that the AI opponents
        /// use when evaluating acquisition targets.
        /// </summary>
        /// <param name="industry">Industry to evaluate.</param>
        /// <param name="revenue">Projected annual revenue.</param>
        public static double RiskAdjustedReturn(this IndustryType industry, double revenue)
        {
            var ebitda = industry.ExpectedEbitda(revenue);
            var volatility = industry.Metadata().Volatility; // Higher volatility => greater discount.
            return ebitda * (1.0 - volatility);
        }
    }
}