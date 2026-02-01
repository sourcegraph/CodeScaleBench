```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;

namespace PaletteStream.Shared.Events
{
    /// <summary>
    ///     High-level discriminator for the type of data event.
    ///     The value is used for routing (Kafka topics / EventBus channels) as well as
    ///     for polymorphic JSON serialization.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum DataEventType
    {
        Unknown                 = 0,
        RawDataIngested         = 10,
        DataValidationFailed    = 20,
        DataTransformApplied    = 30,
        DataQualityCheckFailed  = 40,
        DataBatchCompleted      = 50,
        PipelineError           = 60
    }

    /// <summary>
    ///     Marker interface for all events flowing inside the PaletteStream ETL Canvas.
    ///     The interface purposefully contains only the strictly required information
    ///     for inter-service contracts; behavioral helpers are offered as extension
    ///     methods on <see cref="DataEventExtensions"/>.
    /// </summary>
    public interface IDataEvent
    {
        Guid              EventId         { get; }
        Guid?             CorrelationId   { get; }
        DateTimeOffset    OccurredOnUtc   { get; }
        DataEventType     EventType       { get; }
        string            Environment     { get; }
        IReadOnlyDictionary<string, string> Tags { get; }
    }

    /// <summary>
    ///     Base implementation relied upon by all concrete events. Being a record,
    ///     value-based equality & immutability come for free.
    /// </summary>
    /// <param name="EventId">Unique identifier of the event instance.</param>
    /// <param name="CorrelationId">Identifier used to correlate a set of events.</param>
    /// <param name="OccurredOnUtc">Timestamp recorded in UTC.</param>
    /// <param name="EventType">Concrete classification of the event.</param>
    /// <param name="Environment">The logical execution environment (Dev/Staging/Prod).</param>
    /// <param name="Tags">Free-form key/value metadata for diagnostics and search.</param>
    public abstract record DataEventBase(
        Guid                                     EventId,
        Guid?                                    CorrelationId,
        DateTimeOffset                           OccurredOnUtc,
        DataEventType                            EventType,
        string                                   Environment,
        IReadOnlyDictionary<string, string>?     Tags = default)
        : IDataEvent
    {
        private static readonly IReadOnlyDictionary<string, string> _emptyTags =
            new ReadOnlyDictionary<string, string>(new Dictionary<string, string>(0));

        [JsonIgnore]
        public bool IsProduction => Environment.Equals("prod", StringComparison.OrdinalIgnoreCase);

        IReadOnlyDictionary<string, string> IDataEvent.Tags => Tags ?? _emptyTags;

        /// <summary>
        ///     Performs basic validation & throws <see cref="InvalidOperationException"/>
        ///     if the event does not satisfy contractual requirements.
        ///     Must be called by inheritors during construction or via factory methods.
        /// </summary>
        protected static void Validate(
            DataEventType       expected,
            DataEventType       actual,
            string              env,
            Guid                eventId,
            DateTimeOffset      occurred)
        {
            if (expected != actual)
                Throw(nameof(actual), $"EventType “{actual}” does not match expected “{expected}”.");

            if (eventId == Guid.Empty)
                Throw(nameof(eventId), "EventId must be a non-empty GUID.");

            if (string.IsNullOrWhiteSpace(env))
                Throw(nameof(env), "Environment must be specified.");

            if (occurred.Offset != TimeSpan.Zero)
                Throw(nameof(occurred), "OccurredOnUtc must be expressed in UTC.");

            [MethodImpl(MethodImplOptions.NoInlining)]
            static void Throw(string param, string? message) =>
                throw new InvalidOperationException($"Invalid {param}: {message}");
        }
    }

    #region Concrete Events

    public sealed record RawDataIngestedEvent : DataEventBase
    {
        public string SourceSystem         { get; init; }
        public string ObjectKey            { get; init; }
        public long   Bytes                { get; init; }
        public int    RecordCount          { get; init; }

        [JsonConstructor]
        public RawDataIngestedEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   sourceSystem,
            string                                   objectKey,
            long                                     bytes,
            int                                      recordCount,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.RawDataIngested, environment, tags)
        {
            Validate(DataEventType.RawDataIngested, EventType, environment, EventId, OccurredOnUtc);

            SourceSystem = sourceSystem ?? throw new ArgumentNullException(nameof(sourceSystem));
            ObjectKey    = objectKey    ?? throw new ArgumentNullException(nameof(objectKey));
            Bytes        = bytes >= 0   ? bytes : throw new ArgumentOutOfRangeException(nameof(bytes));
            RecordCount  = recordCount >= 0 ? recordCount : throw new ArgumentOutOfRangeException(nameof(recordCount));
        }
    }

    public sealed record DataValidationFailedEvent : DataEventBase
    {
        public string Stage                            { get; init; }
        public IReadOnlyList<string> Errors            { get; init; }

        [JsonConstructor]
        public DataValidationFailedEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   stage,
            IReadOnlyList<string>                    errors,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.DataValidationFailed, environment, tags)
        {
            Validate(DataEventType.DataValidationFailed, EventType, environment, EventId, OccurredOnUtc);

            Stage  = stage  ?? throw new ArgumentNullException(nameof(stage));
            Errors = errors ?? throw new ArgumentNullException(nameof(errors));
        }
    }

    public sealed record DataTransformAppliedEvent : DataEventBase
    {
        public string TransformerName  { get; init; }
        public TimeSpan Duration       { get; init; }
        public int OutputRecordCount   { get; init; }

        [JsonConstructor]
        public DataTransformAppliedEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   transformerName,
            TimeSpan                                 duration,
            int                                      outputRecordCount,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.DataTransformApplied, environment, tags)
        {
            Validate(DataEventType.DataTransformApplied, EventType, environment, EventId, OccurredOnUtc);

            TransformerName    = transformerName ?? throw new ArgumentNullException(nameof(transformerName));
            Duration           = duration >= TimeSpan.Zero ? duration : throw new ArgumentOutOfRangeException(nameof(duration));
            OutputRecordCount  = outputRecordCount >= 0 ? outputRecordCount : throw new ArgumentOutOfRangeException(nameof(outputRecordCount));
        }
    }

    public sealed record DataQualityCheckFailedEvent : DataEventBase
    {
        public string                 CheckName       { get; init; }
        public IReadOnlyList<long>    FailedRecordIds { get; init; }

        [JsonConstructor]
        public DataQualityCheckFailedEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   checkName,
            IReadOnlyList<long>                      failedRecordIds,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.DataQualityCheckFailed, environment, tags)
        {
            Validate(DataEventType.DataQualityCheckFailed, EventType, environment, EventId, OccurredOnUtc);

            CheckName       = checkName ?? throw new ArgumentNullException(nameof(checkName));
            FailedRecordIds = failedRecordIds ?? throw new ArgumentNullException(nameof(failedRecordIds));
        }
    }

    public sealed record DataBatchCompletedEvent : DataEventBase
    {
        public string  JobId         { get; init; }
        public TimeSpan Duration     { get; init; }
        public int     SuccessCount  { get; init; }
        public int     FailureCount  { get; init; }

        [JsonConstructor]
        public DataBatchCompletedEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   jobId,
            TimeSpan                                 duration,
            int                                      successCount,
            int                                      failureCount,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.DataBatchCompleted, environment, tags)
        {
            Validate(DataEventType.DataBatchCompleted, EventType, environment, EventId, OccurredOnUtc);

            JobId         = jobId ?? throw new ArgumentNullException(nameof(jobId));
            Duration      = duration >= TimeSpan.Zero ? duration : throw new ArgumentOutOfRangeException(nameof(duration));
            SuccessCount  = successCount >= 0 ? successCount : throw new ArgumentOutOfRangeException(nameof(successCount));
            FailureCount  = failureCount >= 0 ? failureCount : throw new ArgumentOutOfRangeException(nameof(failureCount));
        }
    }

    public sealed record PipelineErrorEvent : DataEventBase
    {
        public string         ErrorMessage  { get; init; }
        public string?        StackTrace    { get; init; }
        public ActivityTraceId TraceId      { get; init; }
        public string?        Severity      { get; init; }

        [JsonConstructor]
        public PipelineErrorEvent(
            Guid                                     eventId,
            Guid?                                    correlationId,
            DateTimeOffset                           occurredOnUtc,
            string                                   environment,
            string                                   errorMessage,
            string?                                  stackTrace,
            ActivityTraceId                          traceId,
            string?                                  severity,
            IReadOnlyDictionary<string, string>?     tags = default)
            : base(eventId, correlationId, occurredOnUtc, DataEventType.PipelineError, environment, tags)
        {
            Validate(DataEventType.PipelineError, EventType, environment, EventId, OccurredOnUtc);

            ErrorMessage = errorMessage ?? throw new ArgumentNullException(nameof(errorMessage));
            StackTrace   = stackTrace;
            TraceId      = traceId;
            Severity     = severity;
        }
    }

    #endregion

    #region Extensions & Utilities

    /// <summary>
    ///     Helper API surface that adds convenience logic without polluting
    ///     the contractual surface of <see cref="IDataEvent"/>.
    /// </summary>
    public static class DataEventExtensions
    {
        /// <summary>
        ///     Standard factory method that automatically enriches an event with
        ///     correlation & tracing information derived from the current activity.
        /// </summary>
        public static T WithTracing<T>(this T @event) where T : IDataEvent
        {
            var activity = Activity.Current;
            if (activity == null) return @event;

            var tags = @event.Tags.ToDictionary(kv => kv.Key, kv => kv.Value, StringComparer.OrdinalIgnoreCase);
            tags["trace_id"] = activity.TraceId.ToString();
            tags["span_id"]  = activity.SpanId.ToString();

            return @event switch
            {
                RawDataIngestedEvent e          => e with { Tags = tags },
                DataValidationFailedEvent e     => e with { Tags = tags },
                DataTransformAppliedEvent e     => e with { Tags = tags },
                DataQualityCheckFailedEvent e   => e with { Tags = tags },
                DataBatchCompletedEvent e       => e with { Tags = tags },
                PipelineErrorEvent e            => e with { Tags = tags },
                _                               => @event
            };
        }

        /// <summary>
        ///     Returns a deterministic routing key for event streaming systems
        ///     (Kafka Partition Key, Service Bus Session Id, …).
        /// </summary>
        public static string GetRoutingKey(this IDataEvent @event) =>
            @event.EventType switch
            {
                DataEventType.PipelineError          => "pipeline.errors",
                DataEventType.DataValidationFailed   => "quality.validation",
                DataEventType.DataQualityCheckFailed => "quality.checks",
                DataEventType.RawDataIngested        => "ingestion.raw",
                DataEventType.DataTransformApplied   => "transform.applied",
                DataEventType.DataBatchCompleted     => "batch.completed",
                _                                    => "event.unknown"
            };

        /// <summary>
        ///     Enables structured logging when using Serilog / Microsoft.Extensions.Logging.
        /// </summary>
        public static IReadOnlyDictionary<string, object?> ToLogScope(this IDataEvent @event) =>
            new Dictionary<string, object?>
            {
                ["event_id"       ] = @event.EventId,
                ["correlation_id" ] = @event.CorrelationId,
                ["event_type"     ] = @event.EventType.ToString(),
                ["occurred_utc"   ] = @event.OccurredOnUtc,
                ["environment"    ] = @event.Environment
            };
    }

    /// <summary>
    ///     Centralized, thread-safe factory for creating events.
    ///     Keeps construction logic out of business code & reduces duplication.
    /// </summary>
    public static class DataEventFactory
    {
        public static RawDataIngestedEvent CreateRawDataIngested(
            string sourceSystem,
            string objectKey,
            long   bytes,
            int    recordCount,
            string environment,
            Guid?  correlationId = null,
            IReadOnlyDictionary<string, string>? tags = null)
            => new(
                eventId:        Guid.NewGuid(),
                correlationId:  correlationId,
                occurredOnUtc:  DateTimeOffset.UtcNow,
                environment:    environment,
                sourceSystem:   sourceSystem,
                objectKey:      objectKey,
                bytes:          bytes,
                recordCount:    recordCount,
                tags:           tags);

        public static PipelineErrorEvent CreatePipelineError(
            Exception exception,
            string    environment,
            string?   severity = "critical",
            Guid?     correlationId = null,
            IReadOnlyDictionary<string, string>? tags = null)
            => new(
                eventId:        Guid.NewGuid(),
                correlationId:  correlationId,
                occurredOnUtc:  DateTimeOffset.UtcNow,
                environment:    environment,
                errorMessage:   exception.Message,
                stackTrace:     exception.ToString(),
                traceId:        Activity.Current?.TraceId ?? default,
                severity:       severity,
                tags:           tags);
    }

    #endregion
}
```