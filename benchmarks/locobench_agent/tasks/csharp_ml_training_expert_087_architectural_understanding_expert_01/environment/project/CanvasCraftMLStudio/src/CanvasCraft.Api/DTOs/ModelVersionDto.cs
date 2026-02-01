```csharp
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Runtime.Serialization;
using System.Text.Json.Serialization;

namespace CanvasCraft.Api.DTOs
{
    /// <summary>
    /// Data-transfer object that represents a single, immutable version of a model
    /// that has been registered in the CanvasCraft Model Registry.
    ///
    /// ModelVersionDto is deliberately designed to be serialization-friendly and free
    /// of domain behavior.  Any mapping or richer business logic should live in a
    /// dedicated mapper class (e.g., ModelVersionMapper) or the application layer.
    /// </summary>
    [DataContract]
    public sealed record ModelVersionDto : IValidatableObject
    {
        /// <summary>
        /// Globally unique identifier assigned by the Model Registry.
        /// </summary>
        [DataMember(Order = 1)]
        [JsonPropertyName("id")]
        [Required]
        public Guid Id { get; init; }

        /// <summary>
        /// Human-readable model name (e.g., "StableCanvasXL").
        /// This is redundant but helps avoid extra lookups when querying by version.
        /// </summary>
        [DataMember(Order = 2)]
        [JsonPropertyName("modelName")]
        [Required, StringLength(128)]
        public string ModelName { get; init; } = default!;

        /// <summary>
        /// Semantic version string (e.g., "2.1.0-beta+exp.sha.5114f85").
        /// CanvasCraft enforces SemVer compliance at the application boundary.
        /// </summary>
        [DataMember(Order = 3)]
        [JsonPropertyName("version")]
        [Required, RegularExpression(@"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[\da-z\-]+(?:\.[\da-z\-]+)*)?(?:\+[\da-z\-]+(?:\.[\da-z\-]+)*)?$",
            ErrorMessage = "Version must be a valid SemVer string.")]
        public string Version { get; init; } = default!;

        /// <summary>
        /// Identifier of the experiment run that generated this checkpoint.
        /// </summary>
        [DataMember(Order = 4)]
        [JsonPropertyName("experimentRunId")]
        public Guid? ExperimentRunId { get; init; }

        /// <summary>
        /// When the version was first registered (UTC).
        /// </summary>
        [DataMember(Order = 5)]
        [JsonPropertyName("createdAtUtc")]
        [Required]
        public DateTime CreatedAtUtc { get; init; }

        /// <summary>
        /// Username or e-mail of the author that created the version.
        /// </summary>
        [DataMember(Order = 6)]
        [JsonPropertyName("createdBy")]
        [Required, StringLength(256)]
        public string CreatedBy { get; init; } = default!;

        /// <summary>
        /// Path or URI to the model checkpoint artifact in object storage.
        /// </summary>
        [DataMember(Order = 7)]
        [JsonPropertyName("artifactUri")]
        [Required, StringLength(2048)]
        public string ArtifactUri { get; init; } = default!;

        /// <summary>
        /// True if this version has been promoted to production.
        /// </summary>
        [DataMember(Order = 8)]
        [JsonPropertyName("isProduction")]
        public bool IsProduction { get; init; }

        /// <summary>
        /// Optional timestamp of the last production deployment.
        /// </summary>
        [DataMember(Order = 9)]
        [JsonPropertyName("lastDeployedAtUtc")]
        public DateTime? LastDeployedAtUtc { get; init; }

        /// <summary>
        /// Arbitrary, immutable key-value metadata attached by the user or pipeline.
        /// </summary>
        [DataMember(Order = 10)]
        [JsonPropertyName("metadata")]
        public IReadOnlyDictionary<string, string>? Metadata { get; init; }

        /// <summary>
        /// Performance metrics captured at the time of model evaluation.
        /// Metric names SHOULD be lower-kebab-case (e.g., "top-1-accuracy").
        /// </summary>
        [DataMember(Order = 11)]
        [JsonPropertyName("metrics")]
        public IReadOnlyDictionary<string, double>? Metrics { get; init; }

        /// <summary>
        /// Tags aid in grouping and retrieval (e.g., ["stable", "latent-diffusion"]).
        /// </summary>
        [DataMember(Order = 12)]
        [JsonPropertyName("tags")]
        public IReadOnlyCollection<string>? Tags { get; init; }

        #region Validation

        /// <summary>
        /// Performs cross-field validation that cannot be expressed with attributes.
        /// </summary>
        public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
        {
            // Enforce UTC.
            if (CreatedAtUtc.Kind != DateTimeKind.Utc)
            {
                yield return new ValidationResult(
                    $"{nameof(CreatedAtUtc)} must be expressed in UTC.",
                    new[] { nameof(CreatedAtUtc) });
            }

            if (LastDeployedAtUtc.HasValue && LastDeployedAtUtc.Value.Kind != DateTimeKind.Utc)
            {
                yield return new ValidationResult(
                    $"{nameof(LastDeployedAtUtc)} must be expressed in UTC.",
                    new[] { nameof(LastDeployedAtUtc) });
            }

            // Production deployment must have a timestamp.
            if (IsProduction && !LastDeployedAtUtc.HasValue)
            {
                yield return new ValidationResult(
                    $"A production version must have {nameof(LastDeployedAtUtc)} populated.",
                    new[] { nameof(IsProduction), nameof(LastDeployedAtUtc) });
            }
        }

        #endregion

        #region Factory helpers

        /// <summary>
        /// Convenience factory used by controllers to create a DTO from the domain entity.
        /// The domain entity is not referenced here to avoid circular dependencies; 
        /// reflection-based mapping or mapster/AutoMapper is recommended in production.
        /// </summary>
        public static ModelVersionDto From(
            Guid id,
            string modelName,
            string version,
            Guid? experimentRunId,
            DateTime createdAtUtc,
            string createdBy,
            string artifactUri,
            bool isProduction,
            DateTime? lastDeployedAtUtc,
            IReadOnlyDictionary<string, string>? metadata,
            IReadOnlyDictionary<string, double>? metrics,
            IReadOnlyCollection<string>? tags)
        {
            return new ModelVersionDto
            {
                Id = id,
                ModelName = modelName,
                Version = version,
                ExperimentRunId = experimentRunId,
                CreatedAtUtc = createdAtUtc,
                CreatedBy = createdBy,
                ArtifactUri = artifactUri,
                IsProduction = isProduction,
                LastDeployedAtUtc = lastDeployedAtUtc,
                Metadata = metadata,
                Metrics = metrics,
                Tags = tags
            };
        }

        #endregion

        #region Overrides

        public override string ToString()
            => $"{ModelName} v{Version} ({Id})";

        #endregion
    }
}
```