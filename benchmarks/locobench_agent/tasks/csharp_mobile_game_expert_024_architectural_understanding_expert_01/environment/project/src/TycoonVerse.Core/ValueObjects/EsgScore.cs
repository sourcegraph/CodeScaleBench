using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Serialization;

namespace TycoonVerse.Core.ValueObjects
{
    /// <summary>
    /// Represents an immutable Environmental, Social, and Governance (ESG) score for an in-game company.
    /// ESG scores range from 0 to 100 and are divided into three equally–weighted pillars
    /// (Environmental, Social, Governance).  The value object encapsulates validation,
    /// comparison semantics, and helper APIs designed for analytics, leaderboards,
    /// and regulatory scenario modelling.
    /// </summary>
    public sealed class EsgScore : IEquatable<EsgScore>, IComparable<EsgScore>
    {
        public const int MinScore = 0;
        public const int MaxScore = 100;

        [JsonPropertyName("environmental")]
        public int Environmental { get; }

        [JsonPropertyName("social")]
        public int Social { get; }

        [JsonPropertyName("governance")]
        public int Governance { get; }

        /// <summary>
        /// Aggregate composite score (computed on-demand to guarantee immutability).
        /// </summary>
        [JsonIgnore]
        public decimal Composite => Math.Round(
            (Environmental + Social + Governance) / 3m,
            2,
            MidpointRounding.AwayFromZero);

        /// <summary>
        /// High-level rating bucket derived from <see cref="Composite"/>.
        /// The mapping follows the traditional MSCI methodology used in real-world finance.
        /// </summary>
        [JsonIgnore]
        public string Rating => GetRating(Composite);

        #region Construction helpers

        private EsgScore(int environmental, int social, int governance)
        {
            Environmental = ValidatePillar(environmental, nameof(environmental));
            Social        = ValidatePillar(social, nameof(social));
            Governance    = ValidatePillar(governance, nameof(governance));
        }

        /// <summary>
        /// Factory method for explicit pillar values.
        /// </summary>
        public static EsgScore FromPillars(int environmental, int social, int governance)
            => new(environmental, social, governance);

        /// <summary>
        /// Factory method that builds a new ESG score from a pre-weighted dictionary.
        /// The method expects a dictionary with the keys "E", "S", "G" (case-insensitive)
        /// and weights between 0 and 1 that sum up to 1.
        /// </summary>
        /// <exception cref="ArgumentNullException"/>
        /// <exception cref="ArgumentException"/>
        public static EsgScore FromWeightedValues(IReadOnlyDictionary<string, (int score, decimal weight)> weightedPillars)
        {
            if (weightedPillars == null) throw new ArgumentNullException(nameof(weightedPillars));
            if (weightedPillars.Count != 3)
                throw new ArgumentException("Dictionary must contain exactly three entries for keys E, S, and G.", nameof(weightedPillars));

            decimal weightSum = weightedPillars.Values.Sum(x => x.weight);
            if (Math.Abs(weightSum - 1m) > 0.0001m)
                throw new ArgumentException($"Pillar weights must sum to 1. Current sum: {weightSum}", nameof(weightedPillars));

            int environmental = 0, social = 0, governance = 0;

            foreach (var kvp in weightedPillars)
            {
                string key = kvp.Key.Trim().ToUpperInvariant();
                var (score, weight) = kvp.Value;

                ValidatePillar(score, $"weightedPillars['{key}'].score");

                switch (key)
                {
                    case "E":
                        environmental = WeightedScore(score, weight);
                        break;
                    case "S":
                        social = WeightedScore(score, weight);
                        break;
                    case "G":
                        governance = WeightedScore(score, weight);
                        break;
                    default:
                        throw new ArgumentException($"Unexpected pillar key '{kvp.Key}'. Allowed keys are E, S, and G (case-insensitive).", nameof(weightedPillars));
                }
            }

            return new EsgScore(environmental, social, governance);

            static int WeightedScore(int score, decimal weight)
                => (int)Math.Round(score * weight, MidpointRounding.AwayFromZero);
        }

        /// <summary>
        /// Generates a neutral ESG score (50 in each pillar). Useful for initial game states.
        /// </summary>
        public static readonly EsgScore Neutral = new(50, 50, 50);

        #endregion

        #region Operations

        /// <summary>
        /// Returns a new <see cref="EsgScore"/> that represents a blended value between this score and <paramref name="other"/>.
        /// The <paramref name="weightOnOther"/> parameter indicates how much influence the <paramref name="other"/> score
        /// should have, ranging from 0 (ignore <paramref name="other"/>) to 1 (use only <paramref name="other"/>).
        /// </summary>
        /// <exception cref="ArgumentNullException"/>
        /// <exception cref="ArgumentOutOfRangeException"/>
        public EsgScore BlendWith(EsgScore other, decimal weightOnOther)
        {
            if (other == null) throw new ArgumentNullException(nameof(other));
            if (weightOnOther < 0m || weightOnOther > 1m)
                throw new ArgumentOutOfRangeException(nameof(weightOnOther), "Weight must be between 0 and 1.");

            decimal inverse = 1m - weightOnOther;

            int e = (int)Math.Round((Environmental * inverse) + (other.Environmental * weightOnOther), MidpointRounding.AwayFromZero);
            int s = (int)Math.Round((Social        * inverse) + (other.Social        * weightOnOther), MidpointRounding.AwayFromZero);
            int g = (int)Math.Round((Governance    * inverse) + (other.Governance    * weightOnOther), MidpointRounding.AwayFromZero);

            return new EsgScore(e, s, g);
        }

        /// <summary>
        /// Calculates the absolute delta between two ESG scores on a per-pillar basis.
        /// </summary>
        /// <exception cref="ArgumentNullException"/>
        public (int environmental, int social, int governance) Diff(EsgScore other)
        {
            if (other == null) throw new ArgumentNullException(nameof(other));

            return (Math.Abs(Environmental - other.Environmental),
                    Math.Abs(Social        - other.Social),
                    Math.Abs(Governance    - other.Governance));
        }

        /// <summary>
        /// Returns <c>true</c> if this score meets or exceeds the provided <paramref name="minimum"/>.
        /// </summary>
        /// <exception cref="ArgumentNullException"/>
        public bool MeetsOrExceeds(EsgScore minimum)
        {
            if (minimum == null) throw new ArgumentNullException(nameof(minimum));

            return Environmental >= minimum.Environmental &&
                   Social        >= minimum.Social &&
                   Governance    >= minimum.Governance;
        }

        #endregion

        #region Equality & Comparisons

        public bool Equals(EsgScore? other)
        {
            if (ReferenceEquals(this, other)) return true;
            if (other is null) return false;
            return Environmental == other.Environmental &&
                   Social        == other.Social &&
                   Governance    == other.Governance;
        }

        public override bool Equals(object? obj) => Equals(obj as EsgScore);

        public override int GetHashCode() => HashCode.Combine(Environmental, Social, Governance);

        public static bool operator ==(EsgScore? left, EsgScore? right) => Equals(left, right);
        public static bool operator !=(EsgScore? left, EsgScore? right) => !Equals(left, right);

        public int CompareTo(EsgScore? other)
        {
            if (other == null) return 1;

            // Compare by composite score first, then by individual pillars as tiebreakers
            int compositeComparison = Composite.CompareTo(other.Composite);
            if (compositeComparison != 0) return compositeComparison;

            int envComparison = Environmental.CompareTo(other.Environmental);
            if (envComparison != 0) return envComparison;

            int socialComparison = Social.CompareTo(other.Social);
            if (socialComparison != 0) return socialComparison;

            return Governance.CompareTo(other.Governance);
        }

        public static bool operator >(EsgScore left, EsgScore right) => left.CompareTo(right) > 0;
        public static bool operator <(EsgScore left, EsgScore right) => left.CompareTo(right) < 0;
        public static bool operator >=(EsgScore left, EsgScore right) => left.CompareTo(right) >= 0;
        public static bool operator <=(EsgScore left, EsgScore right) => left.CompareTo(right) <= 0;

        #endregion

        #region Private helpers

        private static int ValidatePillar(int score, string paramName)
        {
            if (score < MinScore || score > MaxScore)
                throw new ArgumentOutOfRangeException(paramName, score,
                    $"Pillar score must be between {MinScore} and {MaxScore}.");

            return score;
        }

        private static string GetRating(decimal composite) => composite switch
        {
            >= 90m => "AAA",
            >= 80m => "AA",
            >= 70m => "A",
            >= 60m => "BBB",
            >= 50m => "BB",
            >= 40m => "B",
            >= 30m => "CCC",
            _      => "CC"
        };

        #endregion

        #region Debug & Diagnostics

        public override string ToString()
            => $"E={Environmental}, S={Social}, G={Governance}, Composite={Composite:F2}, Rating={Rating}";

        #endregion
    }
}