```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Text.Json.Serialization;

namespace PaletteStream.Shared.Events
{
    /// <summary>
    /// Marker interface for all quality–related integration events that travel across the micro-service fabric.
    /// Helps message routers, sagas and dead-letter handlers quickly identify
    /// data-quality traffic.
    /// </summary>
    public interface IQualityEvent
    {
        /// <summary>Globally unique identifier for this event instance.</summary>
        Guid EventId { get; }

        /// <summary>Logical correlation identifier linking all events that belong to the same
        /// pipeline execution context (e.g., an ETL run or a streaming session).</summary>
        string CorrelationId { get; }

        /// <summary>Timestamp in UTC — set at the publisher edge.</summary>
        DateTimeOffset OccurredUtc { get; }

        /// <summary>The identifier of the ETL pipeline that emitted this event.</summary>
        string PipelineId { get; }
    }

    /// <summary>
    /// Indicates how severe a data-quality finding is. Consumers map these values to their own
    /// alerting thresholds (email, PagerDuty, etc.).
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum DataQualitySeverity
    {
        Info = 0,
        Warning = 1,
        Critical = 2
    }

    /// <summary>
    /// Base class for domain-specific details about a quality issue.  Each concrete check
    /// (e.g., SchemaDriftIssueDetails, NullRatioIssueDetails) derives from this type.
    /// </summary>
    public abstract record IssueDetails
    {
        /// <summary>Human-readable message describing the issue.</summary>
        public string Message { get; init; } = default!;
    }

    /// <summary>
    /// Raised when a data-quality check detects a new issue that has not been seen before
    /// or whose severity changed since the last run.
    /// </summary>
    public sealed record DataQualityIssueRaisedEvent : IQualityEvent
    {
        [JsonConstructor]
        public DataQualityIssueRaisedEvent(
            Guid eventId,
            string correlationId,
            DateTimeOffset occurredUtc,
            string pipelineId,
            string dataset,
            string checkName,
            DataQualitySeverity severity,
            IssueDetails details,
            IReadOnlyDictionary<string, string>? metadata = null)
        {
            EventId = eventId != Guid.Empty ? eventId : throw new ArgumentException("EventId cannot be an empty GUID.", nameof(eventId));
            CorrelationId = string.IsNullOrWhiteSpace(correlationId) ? throw new ArgumentException("CorrelationId is required.", nameof(correlationId)) : correlationId;
            OccurredUtc = occurredUtc;
            PipelineId = string.IsNullOrWhiteSpace(pipelineId) ? throw new ArgumentException("PipelineId is required.", nameof(pipelineId)) : pipelineId;
            Dataset = string.IsNullOrWhiteSpace(dataset) ? throw new ArgumentException("Dataset is required.", nameof(dataset)) : dataset;
            CheckName = string.IsNullOrWhiteSpace(checkName) ? throw new ArgumentException("CheckName is required.", nameof(checkName)) : checkName;
            Severity = severity;
            Details = details ?? throw new ArgumentNullException(nameof(details));
            Metadata = metadata is null ? EmptyMetadata : new ReadOnlyDictionary<string, string>(metadata);
        }

        public Guid EventId { get; }
        public string CorrelationId { get; }
        public DateTimeOffset OccurredUtc { get; }
        public string PipelineId { get; }
        public string Dataset { get; }
        public string CheckName { get; }
        public DataQualitySeverity Severity { get; }
        public IssueDetails Details { get; }
        public IReadOnlyDictionary<string, string> Metadata { get; }

        private static readonly IReadOnlyDictionary<string, string> EmptyMetadata =
            new ReadOnlyDictionary<string, string>(new Dictionary<string, string>());

        /// <summary>
        /// Factory helper that fills common parameters and validates required fields.
        /// Typically used by pipeline processors.
        /// </summary>
        public static DataQualityIssueRaisedEvent Create(
            string pipelineId,
            string correlationId,
            string dataset,
            string checkName,
            DataQualitySeverity severity,
            IssueDetails details,
            IReadOnlyDictionary<string, string>? metadata = null) =>
            new(
                Guid.NewGuid(),
                correlationId,
                DateTimeOffset.UtcNow,
                pipelineId,
                dataset,
                checkName,
                severity,
                details,
                metadata);
    }

    /// <summary>
    /// Raised when an outstanding data-quality issue has been resolved.
    /// Invoked by the same check that previously raised the issue once
    /// the condition is cleared.
    /// </summary>
    public sealed record DataQualityIssueResolvedEvent : IQualityEvent
    {
        [JsonConstructor]
        public DataQualityIssueResolvedEvent(
            Guid eventId,
            string correlationId,
            DateTimeOffset occurredUtc,
            string pipelineId,
            string dataset,
            string checkName,
            IReadOnlyDictionary<string, string>? metadata = null)
        {
            EventId = eventId != Guid.Empty ? eventId : throw new ArgumentException("EventId cannot be an empty GUID.", nameof(eventId));
            CorrelationId = string.IsNullOrWhiteSpace(correlationId) ? throw new ArgumentException("CorrelationId is required.", nameof(correlationId)) : correlationId;
            OccurredUtc = occurredUtc;
            PipelineId = string.IsNullOrWhiteSpace(pipelineId) ? throw new ArgumentException("PipelineId is required.", nameof(pipelineId)) : pipelineId;
            Dataset = string.IsNullOrWhiteSpace(dataset) ? throw new ArgumentException("Dataset is required.", nameof(dataset)) : dataset;
            CheckName = string.IsNullOrWhiteSpace(checkName) ? throw new ArgumentException("CheckName is required.", nameof(checkName)) : checkName;
            Metadata = metadata is null ? EmptyMetadata : new ReadOnlyDictionary<string, string>(metadata);
        }

        public Guid EventId { get; }
        public string CorrelationId { get; }
        public DateTimeOffset OccurredUtc { get; }
        public string PipelineId { get; }
        public string Dataset { get; }
        public string CheckName { get; }
        public IReadOnlyDictionary<string, string> Metadata { get; }

        private static readonly IReadOnlyDictionary<string, string> EmptyMetadata =
            new ReadOnlyDictionary<string, string>(new Dictionary<string, string>());

        public static DataQualityIssueResolvedEvent Create(
            string pipelineId,
            string correlationId,
            string dataset,
            string checkName,
            IReadOnlyDictionary<string, string>? metadata = null) =>
            new(
                Guid.NewGuid(),
                correlationId,
                DateTimeOffset.UtcNow,
                pipelineId,
                dataset,
                checkName,
                metadata);
    }

    /// <summary>
    /// Periodic snapshot of data-quality metrics (null ratios, uniqueness counts, etc.)
    /// used by dashboards and anomaly detectors.
    /// </summary>
    public sealed record DataQualityMetricsEvent : IQualityEvent
    {
        [JsonConstructor]
        public DataQualityMetricsEvent(
            Guid eventId,
            string correlationId,
            DateTimeOffset occurredUtc,
            string pipelineId,
            string dataset,
            IReadOnlyDictionary<string, decimal> metrics,
            IReadOnlyDictionary<string, string>? metadata = null)
        {
            if (metrics is null || metrics.Count == 0)
                throw new ArgumentException("Metrics cannot be null or empty.", nameof(metrics));

            EventId = eventId;
            CorrelationId = correlationId;
            OccurredUtc = occurredUtc;
            PipelineId = pipelineId;
            Dataset = dataset;
            Metrics = new ReadOnlyDictionary<string, decimal>(metrics);
            Metadata = metadata is null ? EmptyMetadata : new ReadOnlyDictionary<string, string>(metadata);
        }

        public Guid EventId { get; }
        public string CorrelationId { get; }
        public DateTimeOffset OccurredUtc { get; }
        public string PipelineId { get; }
        public string Dataset { get; }
        public IReadOnlyDictionary<string, decimal> Metrics { get; }
        public IReadOnlyDictionary<string, string> Metadata { get; }

        private static readonly IReadOnlyDictionary<string, string> EmptyMetadata =
            new ReadOnlyDictionary<string, string>(new Dictionary<string, string>());

        public static DataQualityMetricsEvent Create(
            string pipelineId,
            string correlationId,
            string dataset,
            IReadOnlyDictionary<string, decimal> metrics,
            IReadOnlyDictionary<string, string>? metadata = null) =>
            new(
                Guid.NewGuid(),
                correlationId,
                DateTimeOffset.UtcNow,
                pipelineId,
                dataset,
                metrics,
                metadata);
    }
}
```