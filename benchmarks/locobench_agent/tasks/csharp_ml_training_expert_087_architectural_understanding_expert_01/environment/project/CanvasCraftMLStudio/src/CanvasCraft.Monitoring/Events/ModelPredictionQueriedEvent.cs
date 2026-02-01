```csharp
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CanvasCraft.Monitoring.Events
{
    /// <summary>
    /// Minimal contract that every monitoring event raised by the
    /// CanvasCraft ML Studio platform must fulfill.
    /// </summary>
    public interface IMonitoringEvent
    {
        /// <summary>Unique identifier for the event instance.</summary>
        Guid EventId { get; }

        /// <summary>UTC timestamp indicating when the event occurred.</summary>
        DateTimeOffset Timestamp { get; }
    }

    /// <summary>
    /// Event that is raised every time an on-line or batch prediction
    /// produced by a model is queried by a consumer (e.g. front-end, REST API,
    /// background job, or another service).
    ///
    /// Capturing this event allows downstream observers to:
    ///  • Track serving latency and throughput
    ///  • Detect concept or performance drift
    ///  • Attribute usage to individual stakeholders for billing or analytics
    ///  • Reinforce datasets with user feedback (active learning)
    /// </summary>
    public sealed class ModelPredictionQueriedEvent : IMonitoringEvent
    {
        private const int MaxSummaryLength = 512;

        /// <inheritdoc />
        public Guid EventId { get; }

        /// <inheritdoc />
        public DateTimeOffset Timestamp { get; }

        /// <summary>Logical identifier of the model (immutable across versions).</summary>
        public string ModelId { get; }

        /// <summary>Semantic version (or SHA/branch) that uniquely identifies the model artifact used for the prediction.</summary>
        public string ModelVersion { get; }

        /// <summary>Identifier of the prediction request / row within the prediction batch.</summary>
        public string PredictionId { get; }

        /// <summary>Optional identifier of the principal that issued the prediction request.</summary>
        public string? UserId { get; }

        /// <summary>Total latency in milliseconds experienced while serving the prediction.</summary>
        public double LatencyInMs { get; }

        /// <summary>
        /// Hash or checksum of the input payload, used to correlate inputs
        /// stored in the Feature Store without persisting raw data on the event itself.
        /// </summary>
        public string InputSignatureHash { get; }

        /// <summary>
        /// Optional, truncated summary of the prediction output useful for quick inspection.
        /// Large outputs should be stored externally and referenced via <see cref="PredictionId"/>.
        /// </summary>
        public string? OutputSummary { get; }

        /// <summary>
        /// Free-form bag of key/value attributes to enrich the event with
        /// additional metadata (e.g. geo, device, AB test group).
        /// </summary>
        public IReadOnlyDictionary<string, object>? CustomMetadata { get; }

        /// <summary>
        /// Activity / correlation identifier used to stitch logs, traces and events together.
        /// </summary>
        public string? CorrelationId { get; }

        /// <summary>
        /// Creates a new instance of <see cref="ModelPredictionQueriedEvent"/>.
        /// </summary>
        /// <exception cref="ArgumentException">
        /// Thrown when required arguments are null, empty, or whitespace.
        /// </exception>
        public ModelPredictionQueriedEvent(
            string modelId,
            string modelVersion,
            string predictionId,
            double latencyInMs,
            string inputSignatureHash,
            string? outputSummary = null,
            string? userId = null,
            IReadOnlyDictionary<string, object>? customMetadata = null,
            string? correlationId = null,
            DateTimeOffset? timestampUtc = null,
            Guid? eventId = null)
        {
            // Defensive programming / argument validation
            if (string.IsNullOrWhiteSpace(modelId))
                throw new ArgumentException("Model id must be provided.", nameof(modelId));

            if (string.IsNullOrWhiteSpace(modelVersion))
                throw new ArgumentException("Model version must be provided.", nameof(modelVersion));

            if (string.IsNullOrWhiteSpace(predictionId))
                throw new ArgumentException("Prediction id must be provided.", nameof(predictionId));

            if (string.IsNullOrWhiteSpace(inputSignatureHash))
                throw new ArgumentException("Input signature hash must be provided.", nameof(inputSignatureHash));

            if (latencyInMs < 0)
                throw new ArgumentOutOfRangeException(nameof(latencyInMs), "Latency cannot be negative.");

            if (outputSummary?.Length > MaxSummaryLength)
                outputSummary = outputSummary[..MaxSummaryLength] + "…"; // truncate with ellipsis

            ModelId         = modelId.Trim();
            ModelVersion    = modelVersion.Trim();
            PredictionId    = predictionId.Trim();
            LatencyInMs     = latencyInMs;
            InputSignatureHash = inputSignatureHash.Trim();
            OutputSummary   = outputSummary;
            UserId          = userId?.Trim();
            CustomMetadata  = customMetadata;
            CorrelationId   = correlationId ?? Activity.Current?.Id;
            Timestamp       = timestampUtc ?? DateTimeOffset.UtcNow;
            EventId         = eventId ?? Guid.NewGuid();
        }

        /// <summary>
        /// Serialises the event to JSON using System.Text.Json with reasonable defaults.
        /// This is convenient when persisting to an event store or emitting to logs.
        /// </summary>
        public string ToJson(JsonSerializerOptions? options = null)
        {
            options ??= new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented        = false,
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
            };

            return JsonSerializer.Serialize(this, options);
        }

        /// <summary>
        /// Returns a concise, single-line representation helpful for diagnostic logging.
        /// </summary>
        public override string ToString()
        {
            var sb = new StringBuilder()
                     .Append($"[PredictionQueried] ")
                     .Append($"{ModelId}@{ModelVersion} ")
                     .Append($"prediction={PredictionId} ")
                     .Append($"latency={LatencyInMs:n2}ms");

            if (!string.IsNullOrWhiteSpace(UserId))
                sb.Append($" user={UserId}");

            if (!string.IsNullOrWhiteSpace(CorrelationId))
                sb.Append($" corr={CorrelationId}");

            return sb.ToString();
        }
    }
}
```