```csharp
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Text.Json;
using System.Text.Json.Serialization;
using CanvasCraft.Domain.Experiments; // Domain assembly (for mapping)

namespace CanvasCraft.Api.DTOs
{
    /// <summary>
    /// Enumerates the legal lifecycle states of an experiment run.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum ExperimentStatus
    {
        Pending = 0,
        Running = 1,
        Completed = 2,
        Failed = 3,
        Cancelled = 4
    }

    /// <summary>
    /// DTO that surfaces a single experiment execution log to API consumers.
    /// </summary>
    public sealed record ExperimentLogDto
    {
        [Required]
        [JsonPropertyName("experimentId")]
        public Guid ExperimentId { get; init; }

        [Required]
        [MaxLength(256)]
        [JsonPropertyName("experimentName")]
        public string ExperimentName { get; init; } = string.Empty;

        [Required]
        [MaxLength(64)]
        [JsonPropertyName("modelVersion")]
        public string ModelVersion { get; init; } = string.Empty;

        [Required]
        [JsonPropertyName("status")]
        public ExperimentStatus Status { get; init; }

        [Required]
        [JsonPropertyName("startedAtUtc")]
        public DateTimeOffset StartedAtUtc { get; init; }

        [JsonPropertyName("completedAtUtc")]
        public DateTimeOffset? CompletedAtUtc { get; init; }

        /// <summary>
        /// Total runtime once the experiment completes. Null until CompletedAtUtc is set.
        /// </summary>
        [JsonPropertyName("duration")]
        [JsonConverter(typeof(TimeSpanSecondsJsonConverter))]
        public TimeSpan? Duration =>
            CompletedAtUtc.HasValue ? CompletedAtUtc - StartedAtUtc : null;

        /// <summary>
        /// Hyper-parameter grid used for the run, expressed as arbitrary key/value pairs.
        /// JSON serialises heterogenous value types (e.g. string, double, bool).
        /// </summary>
        [JsonPropertyName("hyperParameters")]
        public IReadOnlyDictionary<string, object> HyperParameters { get; init; } =
            new Dictionary<string, object>();

        /// <summary>
        /// Captured metrics (loss, accuracy, F1, etc.).
        /// </summary>
        [JsonPropertyName("metrics")]
        public IReadOnlyDictionary<string, double> Metrics { get; init; } =
            new Dictionary<string, double>();

        /// <summary>
        /// Username or e-mail of the creator that kicked off the run.
        /// </summary>
        [Required]
        [MaxLength(128)]
        [JsonPropertyName("createdBy")]
        public string CreatedBy { get; init; } = string.Empty;

        /// <summary>
        /// User-defined labels that help group related experiments.
        /// </summary>
        [JsonPropertyName("tags")]
        public IReadOnlyCollection<string> Tags { get; init; } = Array.Empty<string>();

        /// <summary>
        /// Convenience flag that quickly answers whether the run completed successfully.
        /// Presents a domain-friendly field for API callers.
        /// </summary>
        [JsonPropertyName("isSuccessful")]
        public bool IsSuccessful => Status == ExperimentStatus.Completed;

        #region Mapping helpers

        /// <summary>
        /// Maps a domain experiment entity to its outward-facing DTO.
        /// </summary>
        /// <param name="experiment">Domain experiment.</param>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="experiment"/> is null.</exception>
        public static ExperimentLogDto FromDomain(ExperimentLog experiment)
        {
            if (experiment is null)
                throw new ArgumentNullException(nameof(experiment));

            return new ExperimentLogDto
            {
                ExperimentId    = experiment.Id,
                ExperimentName  = experiment.Name,
                ModelVersion    = experiment.ModelVersion,
                Status          = Enum.TryParse<ExperimentStatus>(experiment.Status, true, out var s)
                                    ? s
                                    : ExperimentStatus.Pending,
                StartedAtUtc    = experiment.StartedAtUtc,
                CompletedAtUtc  = experiment.CompletedAtUtc,
                HyperParameters = experiment.HyperParameters,
                Metrics         = experiment.Metrics,
                CreatedBy       = experiment.CreatedBy,
                Tags            = experiment.Tags
            };
        }

        #endregion
    }

    #region Json converters

    /// <summary>
    /// Serialises a nullable <see cref="TimeSpan"/> as seconds with sub-second precision to keep JSON payloads short.
    /// E.g. 00:01:30.500 -> 90.5
    /// </summary>
    internal sealed class TimeSpanSecondsJsonConverter : JsonConverter<TimeSpan?>
    {
        public override TimeSpan? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            if (reader.TokenType is JsonTokenType.Null)
                return null;

            if (reader.TokenType is not JsonTokenType.Number)
                throw new JsonException("Expected numeric seconds for TimeSpan.");

            var seconds = reader.GetDouble();
            return TimeSpan.FromSeconds(seconds);
        }

        public override void Write(Utf8JsonWriter writer, TimeSpan? value, JsonSerializerOptions options)
        {
            if (value is null)
            {
                writer.WriteNullValue();
                return;
            }

            var seconds = value.Value.TotalSeconds;
            writer.WriteNumberValue(seconds);
        }
    }

    #endregion
}
```