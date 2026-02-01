```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Quality.Core
{
    #region Contracts

    /// <summary>
    /// Represents a batch or micro-batch of data flowing through the ETL pipeline.
    /// </summary>
    public sealed class DataBatch
    {
        public DataBatch(Guid id, IReadOnlyDictionary<string, object> metadata)
        {
            Id = id;
            Metadata = metadata ?? throw new ArgumentNullException(nameof(metadata));
        }

        public Guid Id { get; }

        /// <summary>
        /// Free-form metadata that helps QualityChecks determine applicability.
        /// </summary>
        public IReadOnlyDictionary<string, object> Metadata { get; }
    }

    /// <summary>
    /// Marker interface for a single, executable quality check.
    /// </summary>
    public interface IQualityCheck
    {
        /// <summary>
        /// Unique identifier for the check (e.g. "null_ratio.product_id").
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Executes the quality check against <paramref name="batch"/>.
        /// </summary>
        Task<QualityCheckResult> ExecuteAsync(DataBatch batch, CancellationToken ct);
    }

    /// <summary>
    /// Publishes the outcome of a quality check run to an external sink (DB, Kafka, etc.).
    /// </summary>
    public interface IQualityResultSink
    {
        Task PersistAsync(QualityCheckResult result, CancellationToken ct);
    }

    /// <summary>
    /// Simple event bus abstraction so we do not leak concrete implementation into runner.
    /// </summary>
    public interface IEventBus
    {
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken ct);
    }

    #endregion

    #region Model

    public enum QualityCheckStatus
    {
        Passed,
        Failed,
        Skipped,
        Error
    }

    /// <summary>
    /// Result produced by a single <see cref="IQualityCheck"/>.
    /// </summary>
    public sealed class QualityCheckResult
    {
        public QualityCheckResult(
            string checkName,
            QualityCheckStatus status,
            TimeSpan duration,
            string? details = null,
            Exception? error = null)
        {
            CheckName = checkName;
            Status = status;
            Duration = duration;
            Details = details;
            Error = error;
        }

        public string CheckName { get; }
        public QualityCheckStatus Status { get; }
        public TimeSpan Duration { get; }
        public string? Details { get; }
        public Exception? Error { get; }
    }

    /// <summary>
    /// Summary for an entire quality run over a single <see cref="DataBatch"/>.
    /// </summary>
    public sealed class QualityRunSummary
    {
        public QualityRunSummary(
            Guid batchId,
            DateTimeOffset startedAt,
            DateTimeOffset finishedAt,
            IReadOnlyCollection<QualityCheckResult> results)
        {
            BatchId = batchId;
            StartedAt = startedAt;
            FinishedAt = finishedAt;
            Results = results;
        }

        public Guid BatchId { get; }
        public DateTimeOffset StartedAt { get; }
        public DateTimeOffset FinishedAt { get; }
        public IReadOnlyCollection<QualityCheckResult> Results { get; }

        public bool HasFailures => Results.Any(r => r.Status is QualityCheckStatus.Failed or QualityCheckStatus.Error);
    }

    #endregion

    /// <summary>
    /// Executes a set of registered <see cref="IQualityCheck"/>s against a <see cref="DataBatch"/>.
    /// Handles fan-out/fan-in parallelism, error capturing, logging, and event publication.
    /// </summary>
    public sealed class QualityCheckRunner
    {
        private static readonly ActivitySource ActivitySource = new("PaletteStream.Quality");

        private readonly IReadOnlyCollection<IQualityCheck> _checks;
        private readonly IQualityResultSink _resultSink;
        private readonly IEventBus _eventBus;
        private readonly ILogger<QualityCheckRunner> _logger;
        private readonly int _maxParallelism;

        public QualityCheckRunner(
            IEnumerable<IQualityCheck> checks,
            IQualityResultSink resultSink,
            IEventBus eventBus,
            ILogger<QualityCheckRunner> logger,
            int maxParallelism = 8)
        {
            _checks = checks?.ToArray() ?? throw new ArgumentNullException(nameof(checks));
            _resultSink = resultSink ?? throw new ArgumentNullException(nameof(resultSink));
            _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            _maxParallelism = Math.Max(1, maxParallelism);
        }

        /// <summary>
        /// Executes all registered quality checks against the provided <paramref name="batch"/> and
        /// persist their outcomes to the configured sink.
        /// </summary>
        public async Task<QualityRunSummary> RunAsync(DataBatch batch, CancellationToken ct = default)
        {
            if (batch == null) throw new ArgumentNullException(nameof(batch));

            using var activity = ActivitySource.StartActivity("QualityCheckRunner.Run");
            activity?.SetTag("batch.id", batch.Id);

            _logger.LogInformation("Starting quality check run for batch {BatchId} ({CheckCount} checks)",
                batch.Id, _checks.Count);

            var start = DateTimeOffset.UtcNow;
            var resultsBag = new ConcurrentBag<QualityCheckResult>();

            // Semaphore used to throttle concurrency.
            using var semaphore = new SemaphoreSlim(_maxParallelism);

            var tasks = _checks.Select(async check =>
            {
                await semaphore.WaitAsync(ct).ConfigureAwait(false);
                try
                {
                    var result = await ExecuteCheckSafeAsync(check, batch, ct).ConfigureAwait(false);
                    resultsBag.Add(result);

                    // Fire-and-forget sink write; do not block overall execution if sink is slow.
                    _ = PersistAndPublishAsync(result, ct);

                    // Expose span events for observability.
                    activity?.AddEvent(new ActivityEvent($"quality.{result.CheckName}",
                        tags: new ActivityTagsCollection
                        {
                            { "status", result.Status.ToString() },
                            { "duration_ms", result.Duration.TotalMilliseconds }
                        }));

                }
                finally
                {
                    semaphore.Release();
                }
            }).ToList();

            await Task.WhenAll(tasks).ConfigureAwait(false);

            var end = DateTimeOffset.UtcNow;
            var summary = new QualityRunSummary(batch.Id, start, end, resultsBag.ToArray());

            _logger.LogInformation("Quality check run finished for batch {BatchId} in {ElapsedMs} ms. Failures: {HasFailures}",
                batch.Id, (end - start).TotalMilliseconds, summary.HasFailures);

            activity?.SetTag("failures", summary.HasFailures);

            return summary;
        }

        #region Helpers

        private async Task PersistAndPublishAsync(QualityCheckResult result, CancellationToken ct)
        {
            try
            {
                await _resultSink.PersistAsync(result, ct).ConfigureAwait(false);

                // Broadcast result so UI dashboards/renderers can update in real-time
                await _eventBus.PublishAsync(result, ct).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Failed to persist/publish quality check result {CheckName}. " +
                    "The result will not be lost, but metrics may be inaccurate.", result.CheckName);
            }
        }

        private async Task<QualityCheckResult> ExecuteCheckSafeAsync(
            IQualityCheck check,
            DataBatch batch,
            CancellationToken ct)
        {
            var sw = Stopwatch.StartNew();
            try
            {
                var result = await check.ExecuteAsync(batch, ct).ConfigureAwait(false);
                sw.Stop();

                return new QualityCheckResult(
                    checkName: check.Name,
                    status: result.Status,
                    duration: sw.Elapsed,
                    details: result.Details);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                // Propagate cancellation
                throw;
            }
            catch (Exception ex)
            {
                sw.Stop();
                _logger.LogWarning(ex, "Quality check {CheckName} encountered an error", check.Name);

                return new QualityCheckResult(
                    checkName: check.Name,
                    status: QualityCheckStatus.Error,
                    duration: sw.Elapsed,
                    error: ex,
                    details: ex.Message);
            }
        }

        #endregion
    }

    #region Example Checks (for completeness only)

    /// <summary>
    /// A dummy check that always passes. These exemplars would normally live in their own files.
    /// </summary>
    public sealed class AlwaysGreenCheck : IQualityCheck
    {
        public string Name => "always_green";

        public Task<QualityCheckResult> ExecuteAsync(DataBatch batch, CancellationToken ct)
        {
            return Task.FromResult(new QualityCheckResult(
                checkName: Name,
                status: QualityCheckStatus.Passed,
                duration: TimeSpan.Zero,
                details: "Everything looks good!"));
        }
    }

    /// <summary>
    /// Simulates a null-percentage check on a column; fails if threshold exceeds value provided in metadata.
    /// </summary>
    public sealed class NullRatioCheck : IQualityCheck
    {
        public const string RatioKey = "null_ratio";

        public string Name => "null_ratio";

        public Task<QualityCheckResult> ExecuteAsync(DataBatch batch, CancellationToken ct)
        {
            // In real implementation, we'd inspect data frame here.
            if (!batch.Metadata.TryGetValue(RatioKey, out var ratioObj) ||
                ratioObj is not double ratio)
            {
                return Task.FromResult(new QualityCheckResult(
                    Name,
                    QualityCheckStatus.Skipped,
                    TimeSpan.Zero,
                    details: "No null ratio metadata supplied"));
            }

            var status = ratio <= 0.01 ? QualityCheckStatus.Passed : QualityCheckStatus.Failed;
            var details = $"Null ratio: {ratio:P2}";

            return Task.FromResult(new QualityCheckResult(
                Name,
                status,
                TimeSpan.Zero,
                details: details));
        }
    }

    #endregion
}
```