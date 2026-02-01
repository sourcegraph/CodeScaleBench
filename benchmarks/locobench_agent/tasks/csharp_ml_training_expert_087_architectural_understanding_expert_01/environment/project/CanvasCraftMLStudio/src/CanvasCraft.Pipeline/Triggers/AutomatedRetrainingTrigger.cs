```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Logging;
using CanvasCraft.Core.ModelMonitoring;
using CanvasCraft.Core.ModelRegistry;
using CanvasCraft.Core.Orchestration;
using CanvasCraft.Core.Tracing;
using CanvasCraft.Core.Utils;

namespace CanvasCraft.Pipeline.Triggers
{
    /// <summary>
    ///     Subscribes to <see cref="IModelMonitor" /> events (e.g. data / concept drift, performance decay) and
    ///     automatically kicks off a retraining pipeline when thresholds are violated.
    ///
    ///     The class implements <see cref="IObserver{T}" /> so that it can be chained into the wider
    ///     Observer/Reactive-streams that power the CanvasCraft runtime.
    /// </summary>
    public sealed class AutomatedRetrainingTrigger : IObserver<ModelDriftReport>, IDisposable
    {
        private readonly CancellationTokenSource _cts             = new();
        private readonly IEventLogger            _logger;
        private readonly IModelTrainingOrchestrator _orchestrator;
        private readonly IExperimentTracker      _tracker;
        private readonly IModelRegistry          _registry;

        // Debounce protection – avoid flooding if several monitors publish concurrently.
        private readonly TimeSpan _debounceWindow;
        private readonly ConcurrentQueue<ModelDriftReport> _inboundQueue = new();
        private readonly PeriodicTimer _pollTimer;

        // Async-exclusive to guarantee single active retraining job.
        private readonly AsyncLock _retrainLock = new();

        private bool _disposed;

        public AutomatedRetrainingTrigger(
            IModelMonitor                monitor,
            IModelTrainingOrchestrator   orchestrator,
            IExperimentTracker           tracker,
            IModelRegistry               registry,
            IEventLogger                 logger,
            TimeSpan?                    debounceWindow = null,
            TimeSpan?                    pollInterval   = null)
        {
            _orchestrator   = orchestrator  ?? throw new ArgumentNullException(nameof(orchestrator));
            _tracker        = tracker       ?? throw new ArgumentNullException(nameof(tracker));
            _registry       = registry      ?? throw new ArgumentNullException(nameof(registry));
            _logger         = logger        ?? throw new ArgumentNullException(nameof(logger));
            _debounceWindow = debounceWindow ?? TimeSpan.FromSeconds(30);
            _pollTimer      = new PeriodicTimer(pollInterval ?? TimeSpan.FromSeconds(5));

            // Subscribe to the monitor stream.
            monitor.Subscribe(this);
            _ = Task.Run(ProcessInboundQueueAsync, _cts.Token);
        }

        #region Observer implementation

        public void OnNext(ModelDriftReport value)
        {
            _inboundQueue.Enqueue(value);
        }

        public void OnCompleted()
        {
            _logger.Info("[RetrainingTrigger] Monitor stream completed.");
        }

        public void OnError(Exception error)
        {
            _logger.Error(error, "[RetrainingTrigger] Monitor stream faulted.");
        }

        #endregion

        #region Queue Processing

        private async Task ProcessInboundQueueAsync()
        {
            var driftBuffer = new List<ModelDriftReport>();

            try
            {
                while (await _pollTimer.WaitForNextTickAsync(_cts.Token))
                {
                    driftBuffer.Clear();

                    // Drain queue fast.
                    while (_inboundQueue.TryDequeue(out var report))
                    {
                        driftBuffer.Add(report);
                    }

                    if (driftBuffer.Count == 0)
                        continue;

                    // Collapse into a single aggregate report.
                    var aggregate = ModelDriftReport.Aggregate(driftBuffer);
                    if (!aggregate.ShouldRetrain)
                    {
                        _logger.Debug("[RetrainingTrigger] Drift detected but below thresholds. Ignoring.");
                        continue;
                    }

                    // Guard against rapid-fire triggers using a timestamped throttle.
                    var lastRetrainTime = await _tracker.GetLastRetrainTimestampAsync(aggregate.ModelId, _cts.Token);
                    if (lastRetrainTime.HasValue &&
                        DateTimeOffset.UtcNow - lastRetrainTime.Value < _debounceWindow)
                    {
                        _logger.Info(
                            "[RetrainingTrigger] Retrain already triggered recently for model {ModelId}. Skipping.",
                            aggregate.ModelId);
                        continue;
                    }

                    await TriggerRetrainingAsync(aggregate);
                }
            }
            catch (OperationCanceledException)
            {
                // Normal shutdown.
            }
            catch (Exception ex)
            {
                _logger.Error(ex, "[RetrainingTrigger] Unhandled error in queue processor.");
            }
        }

        private async Task TriggerRetrainingAsync(ModelDriftReport report)
        {
            using var retrainGuard = await _retrainLock.TryAcquireAsync(_cts.Token);
            if (!retrainGuard.Acquired)
            {
                _logger.Info("[RetrainingTrigger] Retrain already in progress. Skipping new trigger.");
                return;
            }

            var retrainCtx = BuildContext(report);

            try
            {
                _logger.Info(
                    "[RetrainingTrigger] Starting automated retraining for model {ModelId}, drift={DriftScore:P2}",
                    report.ModelId,
                    report.DriftScore);

                var experimentId = await _tracker.StartExperimentAsync(retrainCtx, _cts.Token);

                var result = await _orchestrator.RetrainAsync(retrainCtx, _cts.Token);

                await _tracker.CompleteExperimentAsync(experimentId, result, _cts.Token);
                await _registry.RegisterNewModelAsync(result.ModelArtifact, _cts.Token);

                _logger.Info(
                    "[RetrainingTrigger] Completed retraining for model {ModelId}. New version: {Version}",
                    report.ModelId,
                    result.ModelArtifact.Version);
            }
            catch (Exception ex)
            {
                _logger.Error(ex,
                    "[RetrainingTrigger] Automated retraining failed for model {ModelId}",
                    report.ModelId);

                await _tracker.FailExperimentAsync(retrainCtx.ExperimentId, ex, CancellationToken.None);
            }
        }

        private RetrainingContext BuildContext(ModelDriftReport report)
        {
            return new RetrainingContext(
                report.ModelId,
                report.DatasetId,
                report.DriftScore,
                triggerType: RetrainingTriggerType.Automated,
                triggeredAt: DateTimeOffset.UtcNow);
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            _cts.Cancel();
            _pollTimer.Dispose();
            _cts.Dispose();
        }

        #endregion
    }

    #region Supporting types (would normally live in separate source files)

    /// <summary>
    /// Represents a model drift or decay report emitted by <see cref="IModelMonitor" />.
    /// </summary>
    public sealed record ModelDriftReport(
        string ModelId,
        string DatasetId,
        double DriftScore,
        DateTimeOffset ObservedAt,
        IReadOnlyDictionary<string, double> Metrics)
    {
        public bool ShouldRetrain => DriftScore >= 0.1; // Example threshold.

        public static ModelDriftReport Aggregate(IEnumerable<ModelDriftReport> reports)
        {
            var list = reports.ToList();

            return new ModelDriftReport(
                list.First().ModelId,
                list.First().DatasetId,
                list.Max(r => r.DriftScore),
                list.Max(r => r.ObservedAt),
                list.SelectMany(r => r.Metrics).GroupBy(kv => kv.Key)
                    .ToDictionary(g => g.Key, g => g.Average(kv => kv.Value)));
        }
    }

    /// <summary>
    /// Represents the context required for retraining.
    /// </summary>
    public sealed record RetrainingContext(
        string           ModelId,
        string           DatasetId,
        double           DriftScore,
        RetrainingTriggerType TriggerType,
        DateTimeOffset   TriggeredAt,
        Guid?            ExperimentId = null);

    public enum RetrainingTriggerType
    {
        Automated,
        Manual,
        Scheduled
    }

    public interface IModelMonitor : IObservable<ModelDriftReport> { }

    public interface IModelTrainingOrchestrator
    {
        Task<ModelTrainingResult> RetrainAsync(RetrainingContext context, CancellationToken token);
    }

    public interface IExperimentTracker
    {
        Task<Guid> StartExperimentAsync(RetrainingContext context, CancellationToken token);
        Task CompleteExperimentAsync(Guid experimentId, ModelTrainingResult result, CancellationToken token);
        Task FailExperimentAsync(Guid experimentId, Exception error, CancellationToken token);
        Task<DateTimeOffset?> GetLastRetrainTimestampAsync(string modelId, CancellationToken token);
    }

    public interface IModelRegistry
    {
        Task RegisterNewModelAsync(ModelArtifact artifact, CancellationToken token);
    }

    public sealed record ModelTrainingResult(ModelArtifact ModelArtifact, IDictionary<string, double> Metrics);

    public sealed record ModelArtifact(string ModelId, string Version, Uri StorageUri);

    #endregion
}
```