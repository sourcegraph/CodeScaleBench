```csharp
// ---------------------------------------------------------------------------------------------
// CanvasCraft ML Studio
// File: CanvasCraft.Core/Models/FeatureDefinition.cs
// Description: Domain model representing a feature’s metadata inside the Feature Store.
// ---------------------------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    ///     Canonical representation of a feature in the CanvasCraft Feature Store.
    ///     Treats every attribute as a first-class citizen, enabling rich lineage tracking,
    ///     version control, and serialization for auditability and reproducibility.
    /// </summary>
    public sealed record FeatureDefinition : IEquatable<FeatureDefinition>
    {
        #region Factory helpers

        /// <summary>
        ///     Creates a new builder instance to fluently construct a <see cref="FeatureDefinition"/>.
        /// </summary>
        public static FeatureDefinitionBuilder Builder() => new();

        /// <summary>
        ///     Deserializes a JSON string into a <see cref="FeatureDefinition"/>.
        /// </summary>
        public static FeatureDefinition FromJson(string json, JsonSerializerOptions? options = null)
        {
            var definition = JsonSerializer.Deserialize<FeatureDefinition>(
                json,
                options ?? JsonOptions.Default);

            return definition ?? throw new InvalidDataException("Failed to deserialize FeatureDefinition.");
        }

        #endregion

        #region Core properties

        /// <summary>
        ///     Unique key in the Feature Store (snake_case recommended).
        /// </summary>
        [Required, MinLength(1)]
        public string Name { get; init; } = default!;

        /// <summary>
        ///     Readable label for dashboards. Defaults to <see cref="Name" /> if omitted.
        /// </summary>
        public string DisplayName { get; init; } = string.Empty;

        /// <summary>
        ///     Optional, longer description aimed at creative stakeholders.
        /// </summary>
        public string? Description { get; init; }

        /// <summary>
        ///     Logical type of the feature (numerical, categorical, etc.).
        /// </summary>
        [Required]
        public FeatureDataType DataType { get; init; }

        /// <summary>
        ///     Physical data source (e.g. "transactions.amount" or "images.*").
        /// </summary>
        public string? Source { get; init; }

        /// <summary>
        ///     Transformation expression, Spark/SQL fragment, or pipeline identifier that
        ///     derives the feature from raw data.
        /// </summary>
        public string? Transformation { get; init; }

        /// <summary>
        ///     Semantic version string for the feature definition.
        /// </summary>
        [RegularExpression(@"^\d+\.\d+\.\d+$")]
        public string Version { get; init; } = "1.0.0";

        /// <summary>
        ///     Creation timestamp (UTC).
        /// </summary>
        public DateTime CreatedAt { get; init; } = DateTime.UtcNow;

        /// <summary>
        ///     Last modification timestamp (UTC). Updated by <see cref="Touch"/>.
        /// </summary>
        public DateTime ModifiedAt { get; private set; } = DateTime.UtcNow;

        /// <summary>
        ///     Extended user-defined metadata (e.g. "palette": "vivid", "domain": "finance").
        /// </summary>
        [JsonConverter(typeof(ReadOnlyDictionaryConverter))]
        public IReadOnlyDictionary<string, string> Tags { get; init; } = new ReadOnlyDictionary<string, string>(
            new Dictionary<string, string>());

        /// <summary>
        ///     Statistical profile captured at materialization time.
        /// </summary>
        public FeatureStatistics? Statistics { get; init; }

        /// <summary>
        ///     Lineage map describing upstream dependencies:
        ///     key = upstream feature / data source, value = version or hash.
        /// </summary>
        [JsonConverter(typeof(ReadOnlyDictionaryConverter))]
        public IReadOnlyDictionary<string, string> Lineage { get; init; } = new ReadOnlyDictionary<string, string>(
            new Dictionary<string, string>());

        #endregion

        #region Behavioral members

        /// <summary>
        ///     Serializes the definition to JSON for persistence or network transport.
        /// </summary>
        public string ToJson(JsonSerializerOptions? options = null)
            => JsonSerializer.Serialize(this, options ?? JsonOptions.Default);

        /// <summary>
        ///     Updates <see cref="ModifiedAt"/> to <see cref="DateTime.UtcNow"/>.
        /// </summary>
        public FeatureDefinition Touch()
        {
            ModifiedAt = DateTime.UtcNow;
            return this;
        }

        /// <summary>
        ///     Performs domain validation and throws <see cref="ValidationException"/>
        ///     if any constraint is violated.
        /// </summary>
        public void Validate()
        {
            var context = new ValidationContext(this);
            Validator.ValidateObject(this, context, validateAllProperties: true);

            if (Tags.Count > 32)
            {
                throw new ValidationException("Feature must not have more than 32 tags.");
            }

            foreach (var (key, _) in Tags)
            {
                if (string.IsNullOrWhiteSpace(key))
                    throw new ValidationException("Tag keys must be non-empty.");

                if (key.Length > 32)
                    throw new ValidationException($"Tag key '{key}' exceeds 32 characters.");
            }
        }

        /// <inheritdoc/>
        public override string ToString() => $"{Name} ({DataType}) v{Version}";

        #endregion
    }

    #region Supporting types

    /// <summary>
    ///     Enum representing high-level feature data types.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum FeatureDataType
    {
        Numerical,
        Categorical,
        Text,
        Image,
        Audio,
        Video,
        Binary,
        Boolean,
        DateTime
    }

    /// <summary>
    ///     Statistical profile of a feature, agnostic to storage engine.
    /// </summary>
    public sealed record FeatureStatistics
    {
        public long Count { get; init; }
        public long Missing { get; init; }

        // Numerical statistics
        public double? Mean { get; init; }
        public double? StdDev { get; init; }
        public double? Min { get; init; }
        public double? Max { get; init; }

        // Categorical statistics
        public long? Cardinality { get; init; }

        /// <summary>
        ///     Instantiates a statistics object ensuring numeric coherence.
        /// </summary>
        public FeatureStatistics Validate()
        {
            if (Count < 0 || Missing < 0)
                throw new ValidationException("Count and Missing must be non-negative.");

            if (Missing > Count)
                throw new ValidationException("'Missing' must be less than or equal to 'Count'.");

            return this;
        }
    }

    /// <summary>
    ///     Fluent builder for <see cref="FeatureDefinition"/> to avoid massive constructors.
    /// </summary>
    public sealed class FeatureDefinitionBuilder
    {
        private readonly Dictionary<string, object?> _values = new(StringComparer.OrdinalIgnoreCase);

        public FeatureDefinitionBuilder WithName(string name)
        {
            _values[nameof(FeatureDefinition.Name)] = name;
            return this;
        }

        public FeatureDefinitionBuilder WithDisplayName(string displayName)
        {
            _values[nameof(FeatureDefinition.DisplayName)] = displayName;
            return this;
        }

        public FeatureDefinitionBuilder WithDescription(string? description)
        {
            _values[nameof(FeatureDefinition.Description)] = description;
            return this;
        }

        public FeatureDefinitionBuilder WithDataType(FeatureDataType dataType)
        {
            _values[nameof(FeatureDefinition.DataType)] = dataType;
            return this;
        }

        public FeatureDefinitionBuilder WithSource(string? source)
        {
            _values[nameof(FeatureDefinition.Source)] = source;
            return this;
        }

        public FeatureDefinitionBuilder WithTransformation(string? transformation)
        {
            _values[nameof(FeatureDefinition.Transformation)] = transformation;
            return this;
        }

        public FeatureDefinitionBuilder WithVersion(string version)
        {
            _values[nameof(FeatureDefinition.Version)] = version;
            return this;
        }

        public FeatureDefinitionBuilder WithTags(IDictionary<string, string> tags)
        {
            _values[nameof(FeatureDefinition.Tags)] =
                new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(tags));
            return this;
        }

        public FeatureDefinitionBuilder WithStatistics(FeatureStatistics stats)
        {
            _values[nameof(FeatureDefinition.Statistics)] = stats;
            return this;
        }

        public FeatureDefinitionBuilder WithLineage(IDictionary<string, string> lineage)
        {
            _values[nameof(FeatureDefinition.Lineage)] =
                new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(lineage));
            return this;
        }

        /// <summary>
        ///     Builds a validated <see cref="FeatureDefinition"/> instance.
        /// </summary>
        public FeatureDefinition Build()
        {
            var definition = new FeatureDefinition
            {
                Name = Get<string>(nameof(FeatureDefinition.Name)),
                DisplayName = Get<string>(nameof(FeatureDefinition.DisplayName)) ?? Get<string>(nameof(FeatureDefinition.Name)),
                Description = Get<string?>(nameof(FeatureDefinition.Description)),
                DataType = Get<FeatureDataType>(nameof(FeatureDefinition.DataType)),
                Source = Get<string?>(nameof(FeatureDefinition.Source)),
                Transformation = Get<string?>(nameof(FeatureDefinition.Transformation)),
                Version = Get<string>(nameof(FeatureDefinition.Version), "1.0.0"),
                CreatedAt = DateTime.UtcNow,
                ModifiedAt = DateTime.UtcNow,
                Tags = Get<IReadOnlyDictionary<string, string>>(nameof(FeatureDefinition.Tags),
                    new ReadOnlyDictionary<string, string>(new Dictionary<string, string>())),
                Statistics = Get<FeatureStatistics?>(nameof(FeatureDefinition.Statistics))?.Validate(),
                Lineage = Get<IReadOnlyDictionary<string, string>>(nameof(FeatureDefinition.Lineage),
                    new ReadOnlyDictionary<string, string>(new Dictionary<string, string>()))
            };

            definition.Validate();

            return definition;
        }

        private T Get<T>(string key, T? defaultValue = default)
            => _values.TryGetValue(key, out var value) ? (T)value! : defaultValue!;
    }

    /// <summary>
    ///     Custom JSON converter to keep <see cref="ReadOnlyDictionary{TKey,TValue}"/> immutable during serialization.
    /// </summary>
    internal sealed class ReadOnlyDictionaryConverter : JsonConverter<IReadOnlyDictionary<string, string>>
    {
        public override IReadOnlyDictionary<string, string>? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            var dict = JsonSerializer.Deserialize<Dictionary<string, string>>(ref reader, options);
            return dict == null
                ? null
                : new ReadOnlyDictionary<string, string>(dict);
        }

        public override void Write(Utf8JsonWriter writer, IReadOnlyDictionary<string, string> value, JsonSerializerOptions options)
        {
            JsonSerializer.Serialize(writer, value.ToDictionary(kv => kv.Key, kv => kv.Value), options);
        }
    }

    /// <summary>
    ///     Centralized JSON settings for model serialization.
    /// </summary>
    internal static class JsonOptions
    {
        public static readonly JsonSerializerOptions Default = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = false,
            Converters =
            {
                new JsonStringEnumConverter(JsonNamingPolicy.CamelCase)
            }
        };
    }

    #endregion
}
```