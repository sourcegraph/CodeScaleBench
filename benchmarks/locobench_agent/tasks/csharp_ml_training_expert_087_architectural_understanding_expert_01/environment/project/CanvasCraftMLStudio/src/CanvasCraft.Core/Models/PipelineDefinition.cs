```csharp
using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.ComponentModel.DataAnnotations;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    /// Describes a reusable, version-controlled MLOps pipeline.
    /// A <see cref="PipelineDefinition"/> behaves like an immutable
    /// recipe that can be compiled into an executable runtime graph.
    /// </summary>
    [DebuggerDisplay("Pipeline: {Name} (v{Version})")]
    public sealed class PipelineDefinition : IEquatable<PipelineDefinition>, ICloneable
    {
        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            WriteIndented = true,
            Converters = { new JsonStringEnumConverter() }
        };

        #region Constructors

        [JsonConstructor]
        public PipelineDefinition(
            Guid id,
            SemanticVersion version,
            string name,
            string description,
            IEnumerable<PipelineStageDefinition> stages,
            IDictionary<string, string>? tags = null,
            DateTime? createdAt = null,
            DateTime? updatedAt = null)
        {
            Id          = id == Guid.Empty ? Guid.NewGuid() : id;
            Version     = version ?? throw new ArgumentNullException(nameof(version));
            Name        = string.IsNullOrWhiteSpace(name)
                              ? throw new ArgumentException("Name is required.", nameof(name))
                              : name.Trim();
            Description = description ?? string.Empty;

            // Make collections immutable for thread-safety
            Stages = stages?.ToImmutableArray() ?? ImmutableArray<PipelineStageDefinition>.Empty;
            Tags   = tags?.ToImmutableDictionary(StringComparer.OrdinalIgnoreCase)
                     ?? ImmutableDictionary<string, string>.Empty;

            CreatedAt = createdAt ?? DateTime.UtcNow;
            UpdatedAt = updatedAt ?? CreatedAt;
        }

        /// <summary>Creates a new pipeline definition with a single stage.</summary>
        public PipelineDefinition(string name, string description, PipelineStageDefinition firstStage)
            : this(Guid.NewGuid(),
                   new SemanticVersion(1, 0, 0),
                   name,
                   description,
                   new[] { firstStage })
        {
        }

        #endregion

        #region Properties

        /// <summary>Primary key for the pipeline.</summary>
        public Guid Id { get; }

        /// <summary>Semantic version, e.g. 1.2.0</summary>
        [Required]
        public SemanticVersion Version { get; }

        /// <summary>User-friendly pipeline name.</summary>
        [Required, MaxLength(128)]
        public string Name { get; }

        /// <summary>Free-form pipeline description.</summary>
        [MaxLength(1024)]
        public string Description { get; }

        /// <summary>Ordered collection of pipeline stages.</summary>
        [Required]
        public ImmutableArray<PipelineStageDefinition> Stages { get; }

        /// <summary>Arbitrary user metadata.</summary>
        public ImmutableDictionary<string, string> Tags { get; }

        /// <summary>UTC timestamp when pipeline was first authored.</summary>
        public DateTime CreatedAt { get; }

        /// <summary>UTC timestamp when pipeline was last modified.</summary>
        public DateTime UpdatedAt { get; }

        #endregion

        #region Factory helpers

        /// <summary>Deserialize a pipeline from JSON.</summary>
        public static PipelineDefinition FromJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
                throw new ArgumentException("JSON may not be null or empty.", nameof(json));

            var pipeline = JsonSerializer.Deserialize<PipelineDefinition>(json, JsonOptions)
                           ?? throw new InvalidOperationException("Unable to deserialize pipeline JSON.");

            return pipeline;
        }

        /// <summary>Serialize the pipeline to JSON.</summary>
        public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

        #endregion

        #region Pipeline manipulation (immutable)

        /// <summary>
        /// Returns a new <see cref="PipelineDefinition"/> with an additional
        /// stage appended to the end.
        /// </summary>
        public PipelineDefinition AddStage(PipelineStageDefinition stage)
        {
            if (stage == null) throw new ArgumentNullException(nameof(stage));

            return new PipelineDefinition(
                id:          Id,
                version:     Version.IncrementPatch(),
                name:        Name,
                description: Description,
                stages:      Stages.Add(stage),
                tags:        Tags,
                createdAt:   CreatedAt,
                updatedAt:   DateTime.UtcNow
            );
        }

        /// <summary>
        /// Returns a new <see cref="PipelineDefinition"/> with the specified
        /// tag added or updated.
        /// </summary>
        public PipelineDefinition WithTag(string key, string value)
        {
            if (string.IsNullOrWhiteSpace(key))   throw new ArgumentException("Tag key cannot be empty.",   nameof(key));
            if (string.IsNullOrWhiteSpace(value)) throw new ArgumentException("Tag value cannot be empty.", nameof(value));

            var newTags = Tags.SetItem(key.Trim(), value.Trim());
            return new PipelineDefinition(
                id:          Id,
                version:     Version,
                name:        Name,
                description: Description,
                stages:      Stages,
                tags:        newTags,
                createdAt:   CreatedAt,
                updatedAt:   DateTime.UtcNow
            );
        }

        #endregion

        #region Validation

        /// <summary>
        /// Validates the pipeline definition for structural and
        /// semantic correctness.
        /// </summary>
        public bool Validate(out IReadOnlyList<string> errors)
        {
            var list = new List<string>();

            if (Stages.IsDefaultOrEmpty)
                list.Add("Pipeline must contain at least one stage.");

            // Ensure stages are unique by Id
            var duplicateIds = Stages.GroupBy(s => s.Id)
                                     .Where(g => g.Count() > 1)
                                     .Select(g => g.Key)
                                     .ToArray();
            if (duplicateIds.Any())
                list.Add($"Duplicate stage Ids found: {string.Join(", ", duplicateIds)}");

            // Verify stage dependency graph is acyclic
            if (!IsAcyclic(Stages))
                list.Add("Stage dependency graph contains cycles.");

            errors = list;
            return errors.Count == 0;
        }

        private static bool IsAcyclic(IEnumerable<PipelineStageDefinition> stages)
        {
            var lookup = stages.ToDictionary(s => s.Id, s => s.DependsOn);
            var visited = new HashSet<Guid>();
            var stack   = new HashSet<Guid>();

            bool Dfs(Guid id)
            {
                if (stack.Contains(id))   return false; // cycle
                if (visited.Contains(id)) return true;  // already processed

                stack.Add(id);
                if (lookup.TryGetValue(id, out var deps))
                {
                    foreach (var dep in deps)
                    {
                        if (!lookup.ContainsKey(dep)) continue; // unknown deps allowed? optional

                        if (!Dfs(dep)) return false;
                    }
                }

                stack.Remove(id);
                visited.Add(id);
                return true;
            }

            return lookup.Keys.All(Dfs);
        }

        #endregion

        #region Interface implementations

        public object Clone() => FromJson(ToJson());

        public bool Equals(PipelineDefinition? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            return Id == other.Id &&
                   Version.Equals(other.Version) &&
                   Name == other.Name &&
                   Description == other.Description &&
                   Tags.SequenceEqual(other.Tags) &&
                   Stages.SequenceEqual(other.Stages);
        }

        public override bool Equals(object? obj) => Equals(obj as PipelineDefinition);

        public override int GetHashCode()
        {
            var hash = new HashCode();
            hash.Add(Id);
            hash.Add(Version);
            hash.Add(Name, StringComparer.Ordinal);
            foreach (var stage in Stages) hash.Add(stage);
            return hash.ToHashCode();
        }

        #endregion
    }

    /// <summary>
    /// Describes a single stage (node) within a pipeline.
    /// </summary>
    public sealed record PipelineStageDefinition
    {
        [JsonConstructor]
        public PipelineStageDefinition(
            Guid id,
            string name,
            StageKind kind,
            IEnumerable<Guid>? dependsOn = null,
            IDictionary<string, object>? parameters = null)
        {
            Id         = id == Guid.Empty ? Guid.NewGuid() : id;
            Name       = string.IsNullOrWhiteSpace(name)
                             ? throw new ArgumentException("Stage name is required.", nameof(name))
                             : name.Trim();
            Kind       = kind;
            DependsOn  = dependsOn?.ToImmutableHashSet() ?? ImmutableHashSet<Guid>.Empty;
            Parameters = parameters?.ToImmutableDictionary(StringComparer.OrdinalIgnoreCase)
                         ?? ImmutableDictionary<string, object>.Empty;
        }

        /// <summary>Stage identifier (unique within a pipeline).</summary>
        public Guid Id { get; }

        /// <summary>Human-readable label.</summary>
        public string Name { get; }

        /// <summary>What the stage actually does.</summary>
        public StageKind Kind { get; }

        /// <summary>Other stage IDs that this stage depends upon.</summary>
        public ImmutableHashSet<Guid> DependsOn { get; }

        /// <summary>Algorithm-specific or environment parameters.</summary>
        public ImmutableDictionary<string, object> Parameters { get; }
    }

    /// <summary>
    /// Enumeration of common pipeline stage types.
    /// Extend as necessary for domain-specific tasks.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum StageKind
    {
        Unknown = 0,
        DataIngestion,
        DataValidation,
        Preprocessing,
        FeatureEngineering,
        ModelTraining,
        HyperparameterTuning,
        Evaluation,
        ModelRegistration,
        Deployment
    }

    /// <summary>
    /// Lightweight semantic version representation.
    /// </summary>
    public sealed record SemanticVersion(int Major, int Minor, int Patch) : IComparable<SemanticVersion>
    {
        public int CompareTo(SemanticVersion? other)
        {
            if (other is null) return 1;
            var result = Major.CompareTo(other.Major);
            if (result != 0) return result;
            result = Minor.CompareTo(other.Minor);
            if (result != 0) return result;
            return Patch.CompareTo(other.Patch);
        }

        public override string ToString() => $"{Major}.{Minor}.{Patch}";

        public SemanticVersion IncrementPatch() => this with { Patch = Patch + 1 };
        public SemanticVersion IncrementMinor() => new(Major, Minor + 1, 0);
        public SemanticVersion IncrementMajor() => new(Major + 1, 0, 0);
    }
}
```