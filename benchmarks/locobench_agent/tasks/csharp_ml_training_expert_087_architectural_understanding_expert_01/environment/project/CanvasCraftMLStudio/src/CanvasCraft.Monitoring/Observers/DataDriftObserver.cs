```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Monitoring/Observers/DataDriftObserver.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using CanvasCraft.Core.Events;
using CanvasCraft.FeatureStore;
using CanvasCraft.Monitoring.Alerts;
using CanvasCraft.Monitoring.Metrics;
using CanvasCraft.Shared;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Monitoring.Observers
{
    /// <summary>
    /// Observes incoming <see cref="DataBatchEvent"/> streams and computes data–drift statistics
    /// (currently PSI) against the baseline training distribution stored in the Feature Store.
    /// When drift crosses the configured threshold, an alert is routed to the <see cref="IAlertService"/>.
    /// All metrics—alerting or not—are shipped to the configured <see cref="IMetricSink"/>.
    /// </summary>
    public sealed class DataDriftObserver : IObserver<DataBatchEvent>, IDisposable
    {
        private readonly IFeatureStatisticsRepository _baselineRepo;
        private readonly IMetricSink _metricSink;
        private readonly IAlertService _alertService;
        private readonly DataDriftObserverOptions _options;
        private readonly ILogger<DataDriftObserver> _logger;
        private readonly IDisposable _subscription;
        private readonly SemaphoreSlim _gate = new(1, 1);

        // Cache baseline statistics for performance; keyed by feature name.
        private readonly ConcurrentDictionary<string, FeatureHistogram> _baselineCache = new();

        public DataDriftObserver(
            IObservable<DataBatchEvent> source,
            IFeatureStatisticsRepository baselineRepo,
            IMetricSink metricSink,
            IAlertService alertService,
            DataDriftObserverOptions options,
            ILogger<DataDriftObserver> logger)
        {
            _baselineRepo = baselineRepo ?? throw new ArgumentNullException(nameof(baselineRepo));
            _metricSink   = metricSink   ?? throw new ArgumentNullException(nameof(metricSink));
            _alertService = alertService ?? throw new ArgumentNullException(nameof(alertService));
            _options      = options      ?? DataDriftObserverOptions.Default;
            _logger       = logger       ?? throw new ArgumentNullException(nameof(logger));

            _subscription = (source ?? throw new ArgumentNullException(nameof(source))).Subscribe(this);

            _logger.LogInformation("DataDriftObserver initialized with AlertThreshold={Threshold:P2} BinCount={BinCount}.",
                _options.AlertThreshold, _options.BinCount);
        }

        #region IObserver<DataBatchEvent>

        public async void OnNext(DataBatchEvent batch)
        {
            if (batch == null || batch.Records.Count == 0)
            {
                _logger.LogDebug("Ignoring empty DataBatchEvent.");
                return;
            }

            try
            {
                await _gate.WaitAsync().ConfigureAwait(false);
                ProcessBatch(batch);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to process DataBatchEvent for ExperimentId={ExperimentId}.",
                    batch.ExperimentId);
            }
            finally
            {
                _gate.Release();
            }
        }

        public void OnError(Exception error)
        {
            _logger.LogError(error, "Data source signaled an error to DataDriftObserver.");
        }

        public void OnCompleted()
        {
            _logger.LogInformation("Data source completed. DataDriftObserver shutting down.");
            Dispose();
        }

        #endregion

        private void ProcessBatch(DataBatchEvent batch)
        {
            foreach (var feature in batch.Signature.Features.Where(f => f.Type == FeatureType.Numeric))
            {
                var actualHistogram = BuildHistogram(batch.Records.Select(r => r.GetNumericValue(feature.Name)));

                var baselineHistogram = _baselineCache.GetOrAdd(feature.Name, name =>
                {
                    // Fetch baseline from repository lazily
                    var baselineStats = _baselineRepo.GetHistogram(batch.TrainingRunId, name);
                    return baselineStats ?? throw new InvalidOperationException(
                        $"Baseline statistics for feature '{name}' not found.");
                });

                var psi = ComputePsi(baselineHistogram, actualHistogram);

                EmitMetrics(batch, feature.Name, psi);

                if (psi >= _options.AlertThreshold)
                {
                    RaiseAlert(batch, feature.Name, psi);
                }
            }
        }

        #region Alerting & Metrics

        private void EmitMetrics(DataBatchEvent batch, string featureName, double psi)
        {
            var tags = new MetricTags(
                ("experiment_id", batch.ExperimentId.ToString()),
                ("feature", featureName));

            _metricSink.RecordGauge("canvascraft.data_drift.psi", psi, tags);
        }

        private void RaiseAlert(DataBatchEvent batch, string featureName, double psi)
        {
            var alert = new AlertMessage(
                title: "Data drift detected",
                body: $"PSI={psi:F4} exceeded threshold for feature '{featureName}' in experiment {batch.ExperimentId}.",
                severity: AlertSeverity.Warning,
                source: nameof(DataDriftObserver));

            _alertService.Publish(alert);

            _logger.LogWarning("Data drift detected (PSI={PSI:F4}) for feature '{Feature}' in ExperimentId={ExperimentId}.",
                psi, featureName, batch.ExperimentId);
        }

        #endregion

        #region Histogram & PSI

        private FeatureHistogram BuildHistogram(IEnumerable<double> values)
        {
            var histogram = new FeatureHistogram(_options.BinCount);

            foreach (var v in values.Where(x => !double.IsNaN(x) && !double.IsInfinity(x)))
            {
                histogram.Add(v);
            }

            histogram.Seal(); // finalize bin sizes & probabilities
            return histogram;
        }

        private static double ComputePsi(FeatureHistogram expected, FeatureHistogram actual)
        {
            Guard.Against(expected.BinCount != actual.BinCount,
                $"Expected and actual histograms must have same bin count to compute PSI. " +
                $"Expected={expected.BinCount}, Actual={actual.BinCount}");

            double psi = 0.0;
            for (var i = 0; i < expected.BinCount; i++)
            {
                var expP = expected.BinProbabilities[i];
                var actP = actual.BinProbabilities[i];

                // Avoid division by zero / log(0)
                if (expP <= 0 || actP <= 0)
                {
                    // Conventional approach: ignore bins with zero probability in either distribution
                    continue;
                }

                psi += (actP - expP) * Math.Log(actP / expP);
            }
            return psi;
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            _subscription?.Dispose();
            _gate?.Dispose();
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    /// <summary>
    /// Configuration options for <see cref="DataDriftObserver"/>.
    /// </summary>
    public sealed record DataDriftObserverOptions
    {
        public double AlertThreshold { get; init; } = 0.25;     // typical PSI threshold
        public int    BinCount       { get; init; } = 10;       // default number of histogram bins

        public static DataDriftObserverOptions Default => new();
    }

    #region Helper Types

    /// <summary>
    /// Lightweight histogram that tracks bin boundaries and probabilities for PSI calculation.
    /// </summary>
    internal sealed class FeatureHistogram
    {
        private readonly List<double> _values = new();
        private readonly int _binCount;
        private bool _sealed;
        private double _min;
        private double _max;

        public int BinCount => _binCount;
        public IReadOnlyList<double> BinProbabilities => _probabilities;

        private readonly double[] _probabilities;

        public FeatureHistogram(int binCount)
        {
            if (binCount <= 0) throw new ArgumentOutOfRangeException(nameof(binCount));

            _binCount = binCount;
            _probabilities = new double[_binCount];
        }

        public void Add(double value)
        {
            if (_sealed) throw new InvalidOperationException("Cannot add value after histogram is sealed.");

            if (_values.Count == 0)
            {
                _min = _max = value;
            }
            else
            {
                if (value < _min) _min = value;
                if (value > _max) _max = value;
            }
            _values.Add(value);
        }

        public void Seal()
        {
            if (_sealed) return;

            var binWidth = (_max - _min) / _binCount;

            // Handle edge case: constant feature
            if (binWidth.Equals(0.0))
            {
                _probabilities[0] = 1.0;
                _sealed = true;
                return;
            }

            foreach (var v in _values)
            {
                var index = (int)((v - _min) / binWidth);
                if (index == _binCount) index--; // Right–inclusive correction
                _probabilities[index]++;
            }

            var total = _values.Count;
            for (var i = 0; i < _probabilities.Length; i++)
            {
                _probabilities[i] /= total;
            }

            _sealed = true;
            _values.Clear();
        }
    }

    #endregion
}
```