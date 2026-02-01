```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Monitoring.Observers
{
    /// <summary>
    /// Observes a live stream of model–metric updates and raises an alert when the metric’s
    /// moving average fades (drops) by a configurable percentage within a sliding time-window.
    /// </summary>
    public sealed class PerformanceFadeObserver : IDisposable
    {
        private readonly IMetricStream _metricStream;
        private readonly IAlertDispatcher _alertDispatcher;
        private readonly ILogger<PerformanceFadeObserver> _logger;

        private readonly ImmutableDictionary<string, PerformanceFadeThreshold> _thresholdsByMetric;
        private readonly ConcurrentDictionary<ModelMetricKey, MetricWindow> _metricWindows;

        private readonly TimeSpan _alertSuppressionWindow;
        private readonly ConcurrentDictionary<ModelMetricKey, DateTimeOffset> _lastAlertOnMetric;

        private bool _disposed;

        /// <summary>
        /// Creates an observer that monitors model performance and raises fade alerts.
        /// </summary>
        /// <param name="metricStream">The stream providing metric-update events.</param>
        /// <param name="alertDispatcher">Alert dispatcher responsible for delivering alerts.</param>
        /// <param name="thresholds">Threshold rules defined for each metric.</param>
        /// <param name="logger">A typed logger.</param>
        /// <param name="alertSuppressionWindow">
        /// Cool-down period between successive alerts for the same model-metric combination.
        /// </param>
        /// <exception cref="ArgumentNullException">If any argument is null.</exception>
        /// <exception cref="ArgumentException">If thresholds are empty.</exception>
        public PerformanceFadeObserver(
            IMetricStream metricStream,
            IAlertDispatcher alertDispatcher,
            IEnumerable<PerformanceFadeThreshold> thresholds,
            ILogger<PerformanceFadeObserver> logger,
            TimeSpan? alertSuppressionWindow = null)
        {
            _metricStream = metricStream ?? throw new ArgumentNullException(nameof(metricStream));
            _alertDispatcher = alertDispatcher ?? throw new ArgumentNullException(nameof(alertDispatcher));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            if (thresholds is null) throw new ArgumentNullException(nameof(thresholds));
            var thresholdList = thresholds.ToImmutableList();
            if (thresholdList.Count == 0)
                throw new ArgumentException("At least one threshold must be provided.", nameof(thresholds));

            _thresholdsByMetric = thresholdList.ToImmutableDictionary(t => t.MetricName, StringComparer.OrdinalIgnoreCase);
            _metricWindows = new ConcurrentDictionary<ModelMetricKey, MetricWindow>();
            _lastAlertOnMetric = new ConcurrentDictionary<ModelMetricKey, DateTimeOffset>();

            _alertSuppressionWindow = alertSuppressionWindow ?? TimeSpan.FromMinutes(10);

            // Wire-up the subscription.
            _metricStream.MetricUpdated += OnMetricUpdated;
            _logger.LogInformation("PerformanceFadeObserver initialised with {ThresholdCount} thresholds.", _thresholdsByMetric.Count);
        }

        #region Event Handling

        private void OnMetricUpdated(object? sender, MetricUpdatedEventArgs e)
        {
            if (_disposed) return;

            if (!_thresholdsByMetric.TryGetValue(e.MetricName, out var threshold))
            {
                // No monitoring configured for this metric; ignore.
                return;
            }

            var key = new ModelMetricKey(e.ModelId, e.MetricName);

            var window = _metricWindows.GetOrAdd(
                key,
                _ => new MetricWindow(threshold.Window));

            window.Add(e.Timestamp, e.Value);

            // Only evaluate when the window is "warm".
            if (!window.IsWarm) return;

            var pastAverage = window.PastAverage;
            var recentAverage = window.RecentAverage;

            if (pastAverage <= 0) return; // Avoid div-by-zero or meaningless ratio.

            var relativeDrop = (pastAverage - recentAverage) / pastAverage;

            if (relativeDrop >= threshold.DropPercentage)
            {
                var now = DateTimeOffset.UtcNow;
                if (ShouldSuppressAlert(key, now))
                {
                    _logger.LogDebug(
                        "Alert suppressed for {ModelId}/{Metric}: drop={Drop:P1}, " +
                        "suppression window={SuppressWindow:g}.",
                        e.ModelId,
                        e.MetricName,
                        relativeDrop,
                        _alertSuppressionWindow);
                    return;
                }

                _ = DispatchFadeAlertAsync(e, pastAverage, recentAverage, relativeDrop, now);
            }
        }

        private bool ShouldSuppressAlert(ModelMetricKey key, DateTimeOffset now)
        {
            if (_lastAlertOnMetric.TryGetValue(key, out var last))
            {
                if (now - last < _alertSuppressionWindow)
                {
                    return true;
                }
            }

            // Update the time optimistically.
            _lastAlertOnMetric[key] = now;
            return false;
        }

        private async Task DispatchFadeAlertAsync(
            MetricUpdatedEventArgs currentEvent,
            double pastAvg,
            double recentAvg,
            double relativeDrop,
            DateTimeOffset timestamp)
        {
            var alert = new Alert
            (
                id: Guid.NewGuid(),
                timestamp: timestamp,
                severity: AlertSeverity.Warning,
                title: $"Performance fade detected on '{currentEvent.MetricName}'",
                description:
                    $"Model '{currentEvent.ModelId}' exhibits a {relativeDrop:P1} " +
                    $"drop in {currentEvent.MetricName} over the last {currentEvent.Timestamp - currentEvent.Timestamp.Add(-_thresholdsByMetric[currentEvent.MetricName].Window):g}. " +
                    $"Past AVG={pastAvg:F4}, Recent AVG={recentAvg:F4}."
            );

            try
            {
                await _alertDispatcher.DispatchAlertAsync(alert, CancellationToken.None).ConfigureAwait(false);
                _logger.LogWarning(
                    "Performance fade alert dispatched: {ModelId}/{Metric} drop={Drop:P1}.",
                    currentEvent.ModelId,
                    currentEvent.MetricName,
                    relativeDrop);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Failed to dispatch performance fade alert for {ModelId}/{Metric}.",
                    currentEvent.ModelId,
                    currentEvent.MetricName);
            }
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _metricStream.MetricUpdated -= OnMetricUpdated;
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion

        #region Nested Types

        /// <summary>
        /// Immutable configuration describing how to detect a fade for a specific metric.
        /// </summary>
        public sealed record PerformanceFadeThreshold(
            string MetricName,
            double DropPercentage,
            TimeSpan Window)
        {
            public PerformanceFadeThreshold
                : this(MetricName, DropPercentage, Window)
            {
                if (string.IsNullOrWhiteSpace(MetricName))
                    throw new ArgumentException("MetricName cannot be null or whitespace.", nameof(MetricName));
                if (DropPercentage <= 0 || DropPercentage >= 1)
                    throw new ArgumentOutOfRangeException(nameof(DropPercentage),
                        "DropPercentage must be between 0 and 1 (exclusive).");
                if (Window <= TimeSpan.Zero)
                    throw new ArgumentOutOfRangeException(nameof(Window),
                        "Window must be a positive TimeSpan.");
            }
        }

        private sealed class MetricWindow
        {
            private readonly TimeSpan _window;
            private readonly object _gate = new();

            private readonly Queue<MetricPoint> _points = new();
            private double _sum;

            public MetricWindow(TimeSpan window)
            {
                _window = window;
            }

            public void Add(DateTimeOffset timestamp, double value)
            {
                lock (_gate)
                {
                    _points.Enqueue(new MetricPoint(timestamp, value));
                    _sum += value;

                    // Evict old points.
                    var limit = timestamp - _window;
                    while (_points.Count > 0 && _points.Peek().Timestamp < limit)
                    {
                        var evicted = _points.Dequeue();
                        _sum -= evicted.Value;
                    }
                }
            }

            public bool IsWarm
            {
                get
                {
                    lock (_gate)
                    {
                        if (_points.Count < 4) return false; // Arbitrary minimum.
                        return _points.Last().Timestamp - _points.First().Timestamp >= _window;
                    }
                }
            }

            public double PastAverage
            {
                get
                {
                    lock (_gate)
                    {
                        if (!IsWarm) return 0d;

                        var half = _points.Count / 2;
                        return _points
                            .Take(half)
                            .Average(p => p.Value);
                    }
                }
            }

            public double RecentAverage
            {
                get
                {
                    lock (_gate)
                    {
                        if (!IsWarm) return 0d;

                        var half = _points.Count / 2;
                        return _points
                            .Skip(half)
                            .Average(p => p.Value);
                    }
                }
            }

            private readonly struct MetricPoint
            {
                public DateTimeOffset Timestamp { get; }
                public double Value { get; }

                public MetricPoint(DateTimeOffset ts, double val)
                {
                    Timestamp = ts;
                    Value = val;
                }
            }
        }

        private readonly struct ModelMetricKey : IEquatable<ModelMetricKey>
        {
            public ModelMetricKey(string modelId, string metricName)
            {
                ModelId = modelId;
                MetricName = metricName;
            }

            public string ModelId { get; }
            public string MetricName { get; }

            public bool Equals(ModelMetricKey other)
                => StringComparer.OrdinalIgnoreCase.Equals(ModelId, other.ModelId) &&
                   StringComparer.OrdinalIgnoreCase.Equals(MetricName, other.MetricName);

            public override bool Equals([NotNullWhen(true)] object? obj)
                => obj is ModelMetricKey other && Equals(other);

            public override int GetHashCode()
            {
                var hash = new HashCode();
                hash.Add(ModelId, StringComparer.OrdinalIgnoreCase);
                hash.Add(MetricName, StringComparer.OrdinalIgnoreCase);
                return hash.ToHashCode();
            }

            public void Deconstruct(out string modelId, out string metricName)
            {
                modelId = ModelId;
                metricName = MetricName;
            }
        }

        #endregion
    }

    #region Infrastructure Contracts

    /// <summary>
    /// Stream of metric updates produced by training / serving pipelines.
    /// </summary>
    public interface IMetricStream
    {
        event EventHandler<MetricUpdatedEventArgs> MetricUpdated;
    }

    /// <summary>
    /// Arguments providing metric data.
    /// </summary>
    public sealed class MetricUpdatedEventArgs : EventArgs
    {
        public MetricUpdatedEventArgs(
            string modelId,
            string metricName,
            double value,
            DateTimeOffset timestamp)
        {
            ModelId = modelId;
            MetricName = metricName;
            Value = value;
            Timestamp = timestamp;
        }

        public string ModelId { get; }
        public string MetricName { get; }
        public double Value { get; }
        public DateTimeOffset Timestamp { get; }
    }

    /// <summary>
    /// Dispatches alerts to downstream sinks (e-mail, Slack, dashboard, etc.).
    /// </summary>
    public interface IAlertDispatcher
    {
        Task DispatchAlertAsync(Alert alert, CancellationToken cancellationToken);
    }

    /// <summary>
    /// Basic alert domain object.
    /// </summary>
    public sealed record Alert(
        Guid Id,
        DateTimeOffset Timestamp,
        AlertSeverity Severity,
        string Title,
        string Description);

    public enum AlertSeverity
    {
        Info,
        Warning,
        Critical
    }

    #endregion
}
```