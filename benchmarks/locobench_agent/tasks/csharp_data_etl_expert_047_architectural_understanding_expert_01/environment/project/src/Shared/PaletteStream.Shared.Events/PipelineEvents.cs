```csharp
// -----------------------------------------------------------------------------
// PaletteStream ETL Canvas
// Shared.Events :: PipelineEvents.cs
//
// A shared event-model abstraction used by both batch and stream processing
// engines to broadcast domain events across the PaletteStream ETL microservice
// mesh.  These events are consumed by observability/monitoring services,
// alerting pipelines, data-quality dashboards, and compensating-transaction
// workflows.
// -----------------------------------------------------------------------------

using System;
using System.Diagnostics.CodeAnalysis;
using System.Runtime.Serialization;
using System.Text.Json.Serialization;

namespace PaletteStream.Shared.Events
{
    /// <summary>
    /// Contract implemented by all PaletteStream pipeline domain events.
    /// </summary>
    public interface IPipelineEvent
    {
        /// <summary>Uniquely identifies this event instance.</summary>
        Guid EventId { get; }

        /// <summary>Point in time (UTC) when the event was raised.</summary>
        DateTimeOffset Timestamp { get; }

        /// <summary>Identifier of the logical pipeline instance this event belongs to.</summary>
        string PipelineInstanceId { get; }

        /// <summary>Human-readable name of the pipeline (e.g. "CustomerOrdersDaily").</summary>
        string PipelineName { get; }
    }

    /// <summary>
    /// Common base-type for all pipeline events.  Provides shared metadata
    /// and factory helpers.
    /// </summary>
    [DataContract]
    public abstract record PipelineEvent : IPipelineEvent
    {
        protected PipelineEvent(string pipelineInstanceId, string pipelineName)
        {
            EventId           = Guid.NewGuid();
            Timestamp         = DateTimeOffset.UtcNow;
            PipelineInstanceId = pipelineInstanceId ?? throw new ArgumentNullException(nameof(pipelineInstanceId));
            PipelineName      = pipelineName        ?? throw new ArgumentNullException(nameof(pipelineName));
        }

        [DataMember(Order = 1)]
        public Guid EventId { get; init; }

        [DataMember(Order = 2)]
        public DateTimeOffset Timestamp { get; init; }

        [DataMember(Order = 3)]
        public string PipelineInstanceId { get; init; }

        [DataMember(Order = 4)]
        public string PipelineName { get; init; }

        /// <summary>
        /// Correlation identifier used to tie a group of events together
        /// (e.g. all events that occurred during one ingestion batch).
        /// </summary>
        [DataMember(Order = 5)]
        public Guid? CorrelationId { get; init; }

        /// <summary>Additional event-specific metadata (opaque to the platform).</summary>
        [DataMember(Order = 6)]
        public MetadataDictionary? Metadata { get; init; }

        /// <summary>
        /// User-friendly pretty print, useful for log statements.
        /// </summary>
        public override string ToString()
            => $"{GetType().Name}({PipelineName}/{PipelineInstanceId}) @ {Timestamp:u} (EventId: {EventId})";
    }

    /// <summary>
    /// Fired once when a pipeline run is created.
    /// </summary>
    [DataContract]
    public sealed record PipelineStartedEvent : PipelineEvent
    {
        public PipelineStartedEvent(
            string pipelineInstanceId,
            string pipelineName,
            string initiatedBy,
            string? branch = null)
            : base(pipelineInstanceId, pipelineName)
        {
            InitiatedBy = initiatedBy;
            Branch      = branch;
        }

        /// <summary>User or system that triggered the pipeline.</summary>
        [DataMember(Order = 1)]
        public string InitiatedBy { get; init; }

        /// <summary>Git/CI branch or environment (if applicable).</summary>
        [DataMember(Order = 2)]
        public string? Branch { get; init; }
    }

    /// <summary>
    /// Fired after each step within a pipeline completes successfully.
    /// </summary>
    [DataContract]
    public sealed record PipelineStepCompletedEvent : PipelineEvent
    {
        public PipelineStepCompletedEvent(
            string pipelineInstanceId,
            string pipelineName,
            string stepName,
            TimeSpan duration,
            long? processedRecords = null,
            SeverityLevel severity = SeverityLevel.Info)
            : base(pipelineInstanceId, pipelineName)
        {
            StepName         = stepName;
            Duration         = duration;
            ProcessedRecords = processedRecords;
            Severity         = severity;
        }

        /// <summary>Name of the completed step (e.g. "NormalizeAddresses").</summary>
        [DataMember(Order = 1)]
        public string StepName { get; init; }

        /// <summary>How long the step took to execute.</summary>
        [DataMember(Order = 2)]
        public TimeSpan Duration { get; init; }

        /// <summary>Total records processed (null when not applicable).</summary>
        [DataMember(Order = 3)]
        public long? ProcessedRecords { get; init; }

        /// <summary>
        /// Severity level computed from any data-quality checks performed
        /// during the step.
        /// </summary>
        [DataMember(Order = 4)]
        public SeverityLevel Severity { get; init; }
    }

    /// <summary>
    /// Fired when a pipeline or step fails irrecoverably.
    /// </summary>
    [DataContract]
    public sealed record PipelineFailedEvent : PipelineEvent
    {
        public PipelineFailedEvent(
            string pipelineInstanceId,
            string pipelineName,
            string failingComponent,
            string errorMessage,
            string? stackTrace = null,
            bool   isRecoverable = false)
            : base(pipelineInstanceId, pipelineName)
        {
            FailingComponent = failingComponent;
            ErrorMessage     = errorMessage;
            StackTrace       = stackTrace;
            IsRecoverable    = isRecoverable;
        }

        /// <summary>Component where the failure occurred.</summary>
        [DataMember(Order = 1)]
        public string FailingComponent { get; init; }

        /// <summary>Root cause error message.</summary>
        [DataMember(Order = 2)]
        public string ErrorMessage { get; init; }

        /// <summary>Detailed stack trace (optional for brevity).</summary>
        [DataMember(Order = 3)]
        public string? StackTrace { get; init; }

        /// <summary>
        /// Indicates whether the orchestrator can attempt an automated recovery.
        /// </summary>
        [DataMember(Order = 4)]
        public bool IsRecoverable { get; init; }
    }

    /// <summary>
    /// Fired periodically by long-running pipelines to emit a heartbeat signal,
    /// useful for liveness detection in orchestrators and dashboards.
    /// </summary>
    [DataContract]
    public sealed record PipelineHeartbeatEvent : PipelineEvent
    {
        public PipelineHeartbeatEvent(
            string pipelineInstanceId,
            string pipelineName,
            double progressPercentage,
            string currentStage)
            : base(pipelineInstanceId, pipelineName)
        {
            ProgressPercentage = progressPercentage;
            CurrentStage       = currentStage;
        }

        /// <summary>Estimated progress (0-100).</summary>
        [DataMember(Order = 1)]
        public double ProgressPercentage { get; init; }

        /// <summary>Friendly name of the current stage (e.g. "LoadingRefinedZone").</summary>
        [DataMember(Order = 2)]
        public string CurrentStage { get; init; }
    }

    /// <summary>
    /// Fired once when the pipeline finishes all its steps successfully.
    /// </summary>
    [DataContract]
    public sealed record PipelineCompletedEvent : PipelineEvent
    {
        public PipelineCompletedEvent(
            string pipelineInstanceId,
            string pipelineName,
            TimeSpan totalDuration,
            bool    succeededWithWarnings = false)
            : base(pipelineInstanceId, pipelineName)
        {
            TotalDuration          = totalDuration;
            SucceededWithWarnings  = succeededWithWarnings;
        }

        /// <summary>Total pipeline runtime.</summary>
        [DataMember(Order = 1)]
        public TimeSpan TotalDuration { get; init; }

        /// <summary>
        /// True when pipeline completed but one or more steps recorded
        /// non-blocking warnings.
        /// </summary>
        [DataMember(Order = 2)]
        public bool SucceededWithWarnings { get; init; }
    }

    // ---------------------------------------------------------------------
    // Supporting Types
    // ---------------------------------------------------------------------

    /// <summary>
    /// Map of arbitrary string -> string metadata values attached to events
    /// (e.g. DAG version, git SHA, dataset id...)
    /// </summary>
    [SuppressMessage("Design", "CA1032:Implement standard exception constructors")]
    public sealed class MetadataDictionary : System.Collections.Generic.Dictionary<string, string>
    {
        public MetadataDictionary() : base(StringComparer.OrdinalIgnoreCase) { }

        public MetadataDictionary(int capacity) : base(capacity, StringComparer.OrdinalIgnoreCase) { }
    }

    /// <summary>Severity level used by data-quality and monitoring checks.</summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum SeverityLevel
    {
        Info = 0,
        Warning = 1,
        Error = 2,
        Critical = 3
    }
}
```