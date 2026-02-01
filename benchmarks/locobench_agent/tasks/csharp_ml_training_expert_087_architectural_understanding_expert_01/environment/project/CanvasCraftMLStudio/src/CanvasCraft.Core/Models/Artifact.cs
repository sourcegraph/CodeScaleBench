```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    ///     Represents a persisted data artifact in the ML-Studio. 
    ///     An artifact can be anything from a raw dataset snapshot to a trained 
    ///     model checkpoint or engineered feature table.
    /// </summary>
    public sealed class Artifact : IAuditableEntity, IHasDomainEvents
    {
        #region Constructors

        // Required by EF Core
        private Artifact() { }

        private Artifact(
            Guid id,
            string name,
            ArtifactType type,
            SemanticVersion version,
            string contentUri,
            string hash,
            string? description,
            IDictionary<string, string>? metadata,
            IEnumerable<string>? tags,
            string createdBy)
        {
            Id          = id;
            Name        = name;
            Type        = type;
            Version     = version;
            ContentUri  = contentUri;
            Hash        = hash;
            Description = description;
            CreatedAt   = DateTimeOffset.UtcNow;
            CreatedBy   = createdBy;
            UpdatedAt   = CreatedAt;
            UpdatedBy   = createdBy;

            if (metadata is { Count: > 0 })
            {
                MetadataInternal = JsonSerializer.Serialize(metadata, SerializerOptions);
            }

            if (tags is { Count: > 0 })
            {
                TagsInternal = string.Join(TagDelimiter, tags);
            }

            _domainEvents.Add(new ArtifactCreatedDomainEvent(this));
        }

        #endregion

        #region Static Factory API

        public static Artifact CreateNew(
            string name,
            ArtifactType type,
            SemanticVersion version,
            string contentUri,
            string hash,
            string? description,
            IDictionary<string, string>? metadata,
            IEnumerable<string>? tags,
            string createdBy)
        {
            ValidateString(name, nameof(name));
            ValidateString(contentUri, nameof(contentUri));
            ValidateString(hash, nameof(hash));
            ValidateString(createdBy, nameof(createdBy));

            return new Artifact(
                id: Guid.NewGuid(),
                name: name,
                type: type,
                version: version,
                contentUri: contentUri,
                hash: hash,
                description: description,
                metadata: metadata,
                tags: tags,
                createdBy: createdBy);
        }

        #endregion

        #region Public Members

        /// <summary>Unique identifier for the artifact.</summary>
        [Key]
        public Guid Id { get; private init; }

        /// <summary>Human-readable artifact name.</summary>
        [Required]
        [MaxLength(256)]
        public string Name { get; private set; } = string.Empty;

        /// <summary>Category of artifact.</summary>
        [Required]
        public ArtifactType Type { get; init; }

        /// <summary>Semantic version of the artifact (e.g. 1.0.3-alpha).</summary>
        [Required]
        public SemanticVersion Version { get; private set; } = SemanticVersion.Initial;

        /// <summary>URI to the content blob in the backing store.</summary>
        [Required]
        [MaxLength(2048)]
        public string ContentUri { get; private set; } = string.Empty;

        /// <summary>Optional textual description.</summary>
        [MaxLength(1024)]
        public string? Description { get; private set; }

        /// <summary>Strong hash of the content. Used for de-duping and integrity checks.</summary>
        [Required]
        [MaxLength(128)]
        public string Hash { get; private set; } = string.Empty;

        /// <summary>Created timestamp (UTC).</summary>
        [Required]
        public DateTimeOffset CreatedAt { get; private init; }

        /// <summary>User that created the artifact.</summary>
        [Required]
        [MaxLength(256)]
        public string CreatedBy { get; private init; } = string.Empty;

        /// <summary>Last updated timestamp (UTC).</summary>
        public DateTimeOffset UpdatedAt { get; private set; }

        /// <summary>User that last modified the artifact.</summary>
        [MaxLength(256)]
        public string UpdatedBy { get; private set; } = string.Empty;

        /// <summary>Concurrency token for optimistic locking.</summary>
        [Timestamp]
        public byte[]? RowVersion { get; private set; }

        /// <summary>Additional metadata as key/value pairs.</summary>
        [NotMapped]
        public IReadOnlyDictionary<string, string>? Metadata =>
            string.IsNullOrWhiteSpace(MetadataInternal)
                ? null
                : JsonSerializer.Deserialize<Dictionary<string, string>>(MetadataInternal, SerializerOptions);

        /// <summary>Set of tags associated with artifact.</summary>
        [NotMapped]
        public IReadOnlyCollection<string> Tags =>
            string.IsNullOrWhiteSpace(TagsInternal)
                ? Array.Empty<string>()
                : TagsInternal.Split(TagDelimiter, StringSplitOptions.RemoveEmptyEntries)
                              .Select(t => t.Trim())
                              .ToArray();

        /// <summary>Returns a stable external-facing identifier.</summary>
        public string GetGlobalId() => $"{Type}:{Name}:{Version}";

        #endregion

        #region Commands (Behavior)

        public void Revise(
            [NotNull] string newContentUri,
            [NotNull] string newHash,
            SemanticVersion newVersion,
            string updatedBy,
            string? description = null,
            IDictionary<string, string>? metadata = null,
            IEnumerable<string>? tags = null)
        {
            ValidateString(newContentUri, nameof(newContentUri));
            ValidateString(newHash, nameof(newHash));
            ValidateString(updatedBy, nameof(updatedBy));

            ContentUri  = newContentUri;
            Hash        = newHash;
            Version     = newVersion;
            Description = description ?? Description;
            UpdatedAt   = DateTimeOffset.UtcNow;
            UpdatedBy   = updatedBy;

            if (metadata != null)
            {
                MetadataInternal = JsonSerializer.Serialize(metadata, SerializerOptions);
            }

            if (tags != null)
            {
                TagsInternal = string.Join(TagDelimiter, tags);
            }

            _domainEvents.Add(new ArtifactRevisedDomainEvent(this));
        }

        public void Rename(string newName, string updatedBy)
        {
            ValidateString(newName, nameof(newName));
            ValidateString(updatedBy, nameof(updatedBy));

            Name       = newName;
            UpdatedAt  = DateTimeOffset.UtcNow;
            UpdatedBy  = updatedBy;

            _domainEvents.Add(new ArtifactRenamedDomainEvent(this));
        }

        public void Deprecate(string updatedBy)
        {
            ValidateString(updatedBy, nameof(updatedBy));

            IsDeprecated = true;
            UpdatedAt    = DateTimeOffset.UtcNow;
            UpdatedBy    = updatedBy;

            _domainEvents.Add(new ArtifactDeprecatedDomainEvent(this));
        }

        #endregion

        #region Persistence Backing Fields

        // Backing field for serialized metadata
        [Column("MetadataJson")]
        [JsonIgnore]
        private string? MetadataInternal { get; set; }

        // Backing field for serialized tags
        [Column("Tags")]
        [JsonIgnore]
        private string? TagsInternal { get; set; }

        // Indicates deprecation state
        public bool IsDeprecated { get; private set; }

        #endregion

        #region Domain Events

        private readonly List<IDomainEvent> _domainEvents = new();

        [NotMapped]
        public IReadOnlyCollection<IDomainEvent> DomainEvents => _domainEvents.AsReadOnly();

        public void ClearDomainEvents() => _domainEvents.Clear();

        #endregion

        #region Private Helpers

        private const char TagDelimiter = ';';

        private static readonly JsonSerializerOptions SerializerOptions =
            new()
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented        = false,
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
            };

        private static void ValidateString(string? value, string paramName)
        {
            if (string.IsNullOrWhiteSpace(value))
                throw new ArgumentException($"'{paramName}' cannot be null or empty.", paramName);
        }

        #endregion
    }

    #region Supporting Types

    /// <summary>Enumeration of artifact types supported by the platform.</summary>
    public enum ArtifactType
    {
        Dataset          = 0,
        FeatureTable     = 1,
        ModelCheckpoint  = 2,
        EvaluationReport = 3,
        MediaAsset       = 4
    }

    /// <summary>Minimalistic semantic version implementation.</summary>
    public readonly record struct SemanticVersion : IComparable<SemanticVersion>
    {
        public int Major { get; init; }
        public int Minor { get; init; }
        public int Patch { get; init; }
        public string? PreRelease { get; init; }

        public static SemanticVersion Initial => new(1, 0, 0);

        [JsonConstructor]
        public SemanticVersion(int major, int minor, int patch, string? preRelease = null)
        {
            if (major < 0 || minor < 0 || patch < 0)
                throw new ArgumentOutOfRangeException("Version components must be non-negative.");

            Major      = major;
            Minor      = minor;
            Patch      = patch;
            PreRelease = preRelease;
        }

        public override string ToString() =>
            PreRelease is { Length: > 0 }
                ? $"{Major}.{Minor}.{Patch}-{PreRelease}"
                : $"{Major}.{Minor}.{Patch}";

        public int CompareTo(SemanticVersion other)
        {
            var majorCmp = Major.CompareTo(other.Major);
            if (majorCmp != 0) return majorCmp;

            var minorCmp = Minor.CompareTo(other.Minor);
            if (minorCmp != 0) return minorCmp;

            var patchCmp = Patch.CompareTo(other.Patch);
            if (patchCmp != 0) return patchCmp;

            return string.Compare(PreRelease, other.PreRelease, StringComparison.Ordinal);
        }

        public static bool operator >(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) > 0;
        public static bool operator <(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) < 0;
        public static bool operator >=(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) >= 0;
        public static bool operator <=(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) <= 0;
    }

    #endregion

    #region Domain-Driven Interfaces

    public interface IAuditableEntity
    {
        DateTimeOffset CreatedAt { get; }
        string CreatedBy         { get; }
        DateTimeOffset UpdatedAt { get; }
        string UpdatedBy         { get; }
    }

    public interface IDomainEvent { }

    public interface IHasDomainEvents
    {
        IReadOnlyCollection<IDomainEvent> DomainEvents { get; }
        void ClearDomainEvents();
    }

    #endregion

    #region Domain Event Implementations

    public sealed record ArtifactCreatedDomainEvent(Artifact Artifact)  : IDomainEvent;
    public sealed record ArtifactRevisedDomainEvent(Artifact Artifact)  : IDomainEvent;
    public sealed record ArtifactRenamedDomainEvent(Artifact Artifact)  : IDomainEvent;
    public sealed record ArtifactDeprecatedDomainEvent(Artifact Artifact) : IDomainEvent;

    #endregion
}
```