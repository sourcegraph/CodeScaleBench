using System;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Numerics;
using System.Text.Json.Serialization;

namespace CanvasCraft.Shared.Dtos
{
    /// <summary>
    /// Enumerates the primitive kinds a feature value can represent.  
    /// Note: Complex types (e.g. images, audio) should be transported as
    /// references (URL, blob id) and therefore map to <see cref="Binary"/>.
    /// </summary>
    public enum FeatureValueKind
    {
        Numeric,
        Boolean,
        Categorical,
        Text,
        DateTime,
        Vector,
        Binary
    }

    /// <summary>
    /// Data-transfer object that represents the value of an engineered feature at a particular moment in time.
    /// The value is transported in its raw string form for wire-compatibility; helper methods are provided to
    /// safely access the strongly-typed representation.
    /// </summary>
    public sealed class FeatureValueDto : IEquatable<FeatureValueDto>
    {
        /// <summary>
        /// Name of the feature as registered in the Feature Store.
        /// </summary>
        [Required, MinLength(1)]
        public string FeatureName { get; init; } = null!;

        /// <summary>
        /// Raw (string) value of the feature.  This format is wire-friendly and agnostic to storage back-ends.
        /// Use <see cref="GetValue{T}()"/> or <see cref="TryGetValue{T}(out T?)"/> to retrieve the typed representation.
        /// </summary>
        [Required]
        public string RawValue { get; init; } = null!;

        /// <summary>
        /// Semantic kind of the feature (numeric, categorical, …).
        /// Guides the parsing logic when converting <see cref="RawValue"/> to a strongly-typed instance.
        /// </summary>
        [Required]
        public FeatureValueKind Kind { get; init; }

        /// <summary>
        /// Originating source of the feature (dataset id, upstream pipeline step, etc.).
        /// </summary>
        public string? Source { get; init; }

        /// <summary>
        /// Optional ISO-8601 timestamp associated with the originating event.
        /// </summary>
        public DateTimeOffset? EventTimestamp { get; init; }

        /// <summary>
        /// Optional quality or confidence score (0–1) attached by a data profiler or human curator.
        /// </summary>
        [Range(0, 1)]
        public double? QualityScore { get; init; }

        /// <summary>
        /// Version identifier for the feature definition (e.g., “v2” when the engineering logic changed).
        /// </summary>
        public string? FeatureVersion { get; init; }

        #region Construction helpers

        private FeatureValueDto() { /* needed for deserialization */ }

        /// <summary>
        /// Creates a <see cref="FeatureValueDto"/> from a typed value, inferring the <see cref="FeatureValueKind"/>.
        /// </summary>
        /// <exception cref="ArgumentException">Thrown when the provided value cannot be mapped to a supported kind.</exception>
        public static FeatureValueDto FromTyped<T>(
            string featureName,
            T value,
            string? source = null,
            DateTimeOffset? eventTimestamp = null,
            double? qualityScore = null,
            string? featureVersion = null)
        {
            if (featureName is null) throw new ArgumentNullException(nameof(featureName));
            if (value is null) throw new ArgumentNullException(nameof(value));

            var (kind, raw) = MapToRaw(value);

            return new FeatureValueDto
            {
                FeatureName = featureName,
                RawValue = raw,
                Kind = kind,
                Source = source,
                EventTimestamp = eventTimestamp,
                QualityScore = qualityScore,
                FeatureVersion = featureVersion
            };
        }

        private static (FeatureValueKind Kind, string Raw) MapToRaw<T>(T value)
        {
            return value switch
            {
                bool b              => (FeatureValueKind.Boolean, b.ToString(CultureInfo.InvariantCulture)),
                int or long or float or double or decimal or
                sbyte or byte or short or ushort or uint or ulong =>
                    (FeatureValueKind.Numeric, Convert.ToString(value, CultureInfo.InvariantCulture)!),

                string s            => (FeatureValueKind.Text, s),
                DateTime dt         => (FeatureValueKind.DateTime,
                                        dt.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture)),
                DateTimeOffset dto  => (FeatureValueKind.DateTime,
                                        dto.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture)),
                Vector<float> vf    => (FeatureValueKind.Vector,
                                        string.Join(',', vf.ToArray())),
                byte[] bytes        => (FeatureValueKind.Binary, Convert.ToBase64String(bytes)),

                _                   => throw new ArgumentException(
                    $"Unsupported feature value type: {typeof(T).Name}", nameof(value))
            };
        }

        #endregion

        #region Typed access helpers

        /// <summary>
        /// Attempts to parse the raw value into <typeparamref name="T"/>.
        /// </summary>
        /// <returns>True when parsing succeeded; otherwise false.</returns>
        public bool TryGetValue<T>(out T? value)
        {
            try
            {
                value = GetValue<T>();
                return true;
            }
            catch
            {
                value = default;
                return false;
            }
        }

        /// <summary>
        /// Parses the raw value into <typeparamref name="T"/>.
        /// </summary>
        /// <exception cref="InvalidOperationException">Thrown when the value cannot be parsed into the desired type.</exception>
        public T GetValue<T>()
        {
            object result = Kind switch
            {
                FeatureValueKind.Boolean when typeof(T) == typeof(bool) =>
                    bool.Parse(RawValue!),

                FeatureValueKind.Numeric => Convert.ChangeType(
                    RawValue,
                    typeof(T),
                    CultureInfo.InvariantCulture),

                FeatureValueKind.Text when typeof(T) == typeof(string) =>
                    RawValue,

                FeatureValueKind.Categorical when typeof(T) == typeof(string) =>
                    RawValue,

                FeatureValueKind.DateTime when typeof(T) == typeof(DateTime) =>
                    DateTime.Parse(RawValue, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind),

                FeatureValueKind.DateTime when typeof(T) == typeof(DateTimeOffset) =>
                    DateTimeOffset.Parse(RawValue, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind),

                FeatureValueKind.Vector when typeof(T) == typeof(Vector<float>) =>
                    new Vector<float>(Array.ConvertAll(RawValue.Split(','), float.Parse)),

                FeatureValueKind.Binary when typeof(T) == typeof(byte[]) =>
                    Convert.FromBase64String(RawValue),

                _ => throw new InvalidOperationException(
                    $"Cannot map feature value of kind '{Kind}' to '{typeof(T).Name}'.")
            };

            return (T)result;
        }

        #endregion

        #region Equality & HashCode

        public bool Equals(FeatureValueDto? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            return FeatureName == other.FeatureName
                   && RawValue == other.RawValue
                   && Kind == other.Kind
                   && Source == other.Source
                   && EventTimestamp.Equals(other.EventTimestamp)
                   && QualityScore.Equals(other.QualityScore)
                   && FeatureVersion == other.FeatureVersion;
        }

        public override bool Equals(object? obj) => Equals(obj as FeatureValueDto);

        public override int GetHashCode()
        {
            return HashCode.Combine(
                FeatureName,
                RawValue,
                Kind,
                Source,
                EventTimestamp,
                QualityScore,
                FeatureVersion);
        }

        #endregion
    }
}