```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Core.Interfaces.Repositories
{
    /// <summary>
    /// A repository abstraction responsible for the persistent storage and retrieval
    /// of <see cref="Experiment"/> aggregates, their associated metrics, artifacts,
    /// and versioned snapshots.
    /// 
    /// Implementations are expected to:
    /// • Handle optimistic concurrency (e.g. ETags or row-version columns)
    /// • Respect CancellationTokens for graceful shutdowns
    /// • Throw domain-specific exceptions (e.g. ExperimentNotFoundException)
    /// • Remain side-effect free beyond persistence concerns
    /// </summary>
    public interface IExperimentRepository
    {
        #region Experiment CRUD --------------------------------------------------

        /// <summary>
        /// Persists a new experiment aggregate.
        /// </summary>
        /// <param name="experiment">The experiment to persist.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>The persisted aggregate with generated keys populated.</returns>
        Task<Experiment> CreateAsync(Experiment experiment, CancellationToken ct = default);

        /// <summary>
        /// Retrieves an experiment by its identifier.
        /// </summary>
        /// <param name="experimentId">The experiment identifier.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>The matching experiment or null.</returns>
        Task<Experiment?> GetByIdAsync(Guid experimentId, CancellationToken ct = default);

        /// <summary>
        /// Returns experiments matching a set of flexible query options.
        /// </summary>
        /// <param name="options">Filtering / paging / ordering options.</param>
        /// <param name="ct">Cancellation token.</param>
        IAsyncEnumerable<Experiment> QueryAsync(ExperimentQueryOptions options, CancellationToken ct = default);

        /// <summary>
        /// Updates an existing experiment. Implementations should raise a
        /// <see cref="ConcurrencyException"/> when optimistic concurrency fails.
        /// </summary>
        /// <param name="experiment">Experiment aggregate with changes applied.</param>
        /// <param name="ct">Cancellation token.</param>
        Task UpdateAsync(Experiment experiment, CancellationToken ct = default);

        /// <summary>
        /// Deletes an experiment and all dependent entities (metrics, snapshots, artifacts).
        /// </summary>
        /// <param name="experimentId">Identifier of the experiment to delete.</param>
        /// <param name="ct">Cancellation token.</param>
        Task DeleteAsync(Guid experimentId, CancellationToken ct = default);

        #endregion

        #region Metrics ----------------------------------------------------------

        /// <summary>
        /// Logs a single metric for a given experiment.
        /// </summary>
        /// <param name="experimentId">The parent experiment identifier.</param>
        /// <param name="metric">Metric to log.</param>
        /// <param name="ct">Cancellation token.</param>
        Task LogMetricAsync(Guid experimentId, ExperimentMetric metric, CancellationToken ct = default);

        /// <summary>
        /// Streams metrics matching a metric name prefix (wildcard search) so callers
        /// can render real-time dashboards without loading every metric into memory.
        /// </summary>
        /// <param name="experimentId">Experiment identifier.</param>
        /// <param name="metricNamePrefix">Prefix filter (e.g. "val_").</param>
        /// <param name="ct">Cancellation token.</param>
        IAsyncEnumerable<ExperimentMetric> StreamMetricsAsync(
            Guid experimentId,
            string? metricNamePrefix = null,
            CancellationToken ct = default);

        #endregion

        #region Snapshots & Versioning ------------------------------------------

        /// <summary>
        /// Persists a point-in-time snapshot of the experiment’s params,
        /// artifacts, and metadata for rollbacks or branching.
        /// </summary>
        /// <param name="experimentId">Experiment to snapshot.</param>
        /// <param name="description">Human-readable description.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>The created snapshot.</returns>
        Task<ExperimentSnapshot> CreateSnapshotAsync(
            Guid experimentId,
            string description,
            CancellationToken ct = default);

        /// <summary>
        /// Retrieves all snapshots for a given experiment.
        /// </summary>
        /// <param name="experimentId">Experiment identifier.</param>
        /// <param name="ct">Cancellation token.</param>
        IAsyncEnumerable<ExperimentSnapshot> GetSnapshotsAsync(
            Guid experimentId,
            CancellationToken ct = default);

        /// <summary>
        /// Rolls back the current state of an experiment to a specific snapshot.
        /// </summary>
        /// <param name="experimentId">Target experiment identifier.</param>
        /// <param name="snapshotId">Snapshot to restore.</param>
        /// <param name="ct">Cancellation token.</param>
        Task RollbackToSnapshotAsync(
            Guid experimentId,
            Guid snapshotId,
            CancellationToken ct = default);

        #endregion

        #region Artifact Management ---------------------------------------------

        /// <summary>
        /// Adds or updates a binary artifact (e.g., model weights, feature store parquet)
        /// associated with an experiment run.
        /// </summary>
        /// <param name="experimentId">Experiment aggregate identifier.</param>
        /// <param name="artifact">The artifact metadata + stream.</param>
        /// <param name="ct">Cancellation token.</param>
        Task UpsertArtifactAsync(
            Guid experimentId,
            ExperimentArtifact artifact,
            CancellationToken ct = default);

        /// <summary>
        /// Downloads an artifact as a read-only stream without loading the entire
        /// blob into memory. The caller is responsible for disposing the stream.
        /// </summary>
        /// <param name="experimentId">Experiment identifier.</param>
        /// <param name="artifactId">Artifact identifier.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>Tuple containing metadata and the data stream.</returns>
        Task<(ExperimentArtifact Metadata, System.IO.Stream DataStream)> DownloadArtifactAsync(
            Guid experimentId,
            Guid artifactId,
            CancellationToken ct = default);

        #endregion
    }

    #region Supporting Domain Models (simplified for interface reference) -------

    /// <summary>
    /// Aggregate root representing a single ML experiment.
    /// </summary>
    public record Experiment
    (
        Guid Id,
        string Name,
        string? Description,
        ExperimentStatus Status,
        DateTimeOffset CreatedUtc,
        DateTimeOffset UpdatedUtc,
        IReadOnlyDictionary<string, string> Parameters,
        string? TagsCsv,
        string? ConcurrencyToken // e.g., row version or ETag for optimistic locking
    );

    /// <summary>
    /// A granular metric logged during training/validation.
    /// </summary>
    public record ExperimentMetric
    (
        string Name,
        double Value,
        long Step,
        DateTimeOffset TimestampUtc
    );

    /// <summary>
    /// A frozen view of experiment state used for rollbacks and branching.
    /// </summary>
    public record ExperimentSnapshot
    (
        Guid Id,
        Guid ExperimentId,
        string Description,
        DateTimeOffset CreatedUtc,
        string BlobStoragePath
    );

    /// <summary>
    /// Artifact metadata plus helper to obtain binary content.
    /// </summary>
    public record ExperimentArtifact
    (
        Guid Id,
        string Name,
        string ContentType,
        long SizeInBytes,
        DateTimeOffset CreatedUtc,
        Func<System.IO.Stream> GetWriteStream // Defers stream creation to caller
    );

    /// <summary>
    /// Flexible query options object—extend as required.
    /// </summary>
    public record ExperimentQueryOptions
    {
        public ExperimentStatus? Status { get; init; }
        public string? Tag { get; init; }
        public int PageNumber { get; init; } = 1;
        public int PageSize { get; init; } = 50;
        public string? SortBy { get; init; }
        public bool Descending { get; init; } = false;
    }

    public enum ExperimentStatus
    {
        Draft,
        Running,
        Completed,
        Failed,
        Archived
    }

    /// <summary>
    /// Exception thrown when optimistic concurrency fails.
    /// </summary>
    public sealed class ConcurrencyException : Exception
    {
        public ConcurrencyException(string message) : base(message) { }
        public ConcurrencyException(string message, Exception inner) : base(message, inner) { }
    }

    #endregion
}
```