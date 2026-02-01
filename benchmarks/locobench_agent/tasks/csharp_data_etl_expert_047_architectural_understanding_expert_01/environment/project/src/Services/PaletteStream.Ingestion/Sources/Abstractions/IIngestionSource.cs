```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace PaletteStream.Ingestion.Sources.Abstractions
{
    /// <summary>
    /// Represents a generic data ingestion source.  Implementations may wrap message queues
    /// (Kafka, Event Hubs), file systems, object stores, REST endpoints, or any other medium
    /// from which data needs to be pulled or subscribed to.
    /// </summary>
    /// <typeparam name="TRaw">The raw domain model that is emitted by the source.</typeparam>
    public interface IIngestionSource<TRaw> : IAsyncDisposable
    {
        #region Events

        /// <summary>
        /// Raised every time a batch of raw records has been read from the underlying source.
        /// Consumers are expected to subscribe and push the payload further down the pipeline.
        /// </summary>
        event Func<IReadOnlyCollection<TRaw>, IngestionContext, Task> OnDataAsync;

        /// <summary>
        /// Raised when a non-recoverable error occurs.  The error will also be reported through
        /// the monitoring subsystem, but attaching to this event allows the pipeline to
        /// implement compensating strategies (e.g., re-queue, dead-letter).
        /// </summary>
        event Func<Exception, IngestionContext, Task> OnErrorAsync;

        /// <summary>
        /// Raised when the source transitions to a healthy state after a previous failure.
        /// </summary>
        event Func<IngestionContext, Task> OnRecoveredAsync;

        #endregion

        #region Lifecycle

        /// <summary>
        /// Initializes the source, performing connection handshakes and allocating resources.
        /// </summary>
        /// <param name="options">
        /// Arbitrary key–value pairs that allow the same implementation to be configured for
        /// multiple runtimes (e.g., topic name, file pattern, API key).
        /// </param>
        /// <param name="cancellationToken">Token used to propagate initialization cancellation.</param>
        /// <exception cref="IngestionSourceException">
        /// Thrown when initialization fails and the source cannot recover automatically.
        /// </exception>
        Task InitializeAsync(
            IngestionSourceOptions options,
            CancellationToken          cancellationToken = default);

        /// <summary>
        /// Starts the continuous ingestion loop.  For bounded sources (CSV, Parquet, …), the
        /// method returns once the data has been fully read.  For unbounded sources (Kafka,
        /// sockets, …), the method does not return until <paramref name="cancellationToken"/>
        /// is triggered.
        /// 
        /// Any runtime exceptions must be surfaced through <see cref="OnErrorAsync"/> and not
        /// thrown; doing so would crash the host service.
        /// </summary>
        Task RunAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Attempts to gracefully halt ingestion, flushing any in-memory buffers and releasing
        /// ephemeral resources.  This method should be idempotent.
        /// </summary>
        /// <param name="cancellationToken"></param>
        Task StopAsync(CancellationToken cancellationToken = default);

        #endregion

        #region Diagnostics & Observability

        /// <summary>
        /// Performs a lightweight health check.  The call must never block for an extended
        /// period of time; network or I/O-bound operations should be avoided to ensure the
        /// method can be called frequently by monitoring probes.
        /// </summary>
        /// <returns>true if the source is healthy; otherwise, false.</returns>
        bool IsHealthy();

        /// <summary>
        /// Gets a snapshot of ingestion statistics that can be surfaced to dashboards or used
        /// by autoscaling algorithms.
        /// </summary>
        IngestionStatistics Snapshot();

        #endregion
    }

    /// <summary>
    /// A strongly-typed bag of runtime settings supplied to <see cref="IIngestionSource{TRaw}.InitializeAsync"/>.
    /// </summary>
    public sealed record IngestionSourceOptions
    {
        public required string SourceName     { get; init; }
        public required string Environment    { get; init; }
        public IDictionary<string, string>    Properties { get; init; } = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// An immutable snapshot of ingestion metrics.  Metric names follow an Inflector-style
    /// naming convention so that they map seamlessly to Prometheus or OpenTelemetry metrics.
    /// </summary>
    public readonly record struct IngestionStatistics(
        long RecordsRead,
        long BatchesRead,
        long BytesRead,
        DateTimeOffset? LastMessageTimestampUtc,
        DateTimeOffset SnapshotTimestampUtc);

    /// <summary>
    /// Encapsulates contextual information that travels alongside every callback.  This
    /// enables advanced observability without polluting method signatures across the codebase.
    /// </summary>
    public sealed record IngestionContext
    {
        public required string          SourceName  { get; init; }
        public required Guid            RunId       { get; init; }
        public required DateTimeOffset  OccurredAtUtc { get; init; }
        public IngestionStatistics      Statistics  { get; init; }
        public IReadOnlyDictionary<string, object?>? Metadata { get; init; }
    }

    /// <summary>
    /// The canonical exception type for ingestion-layer errors.  By using a dedicated type,
    /// we can consistently distinguish between source-related errors and pipeline processing
    /// errors further downstream.
    /// </summary>
    public sealed class IngestionSourceException : Exception
    {
        public IngestionSourceException(string message) : base(message) { }
        public IngestionSourceException(string message, Exception innerException) : base(message, innerException) { }
    }
}
```