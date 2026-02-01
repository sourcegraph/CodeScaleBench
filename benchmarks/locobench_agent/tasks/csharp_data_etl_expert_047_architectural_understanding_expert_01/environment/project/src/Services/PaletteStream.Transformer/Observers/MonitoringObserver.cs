using System;
using System.Diagnostics;
using System.Threading;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Transformer.Observers
{
    /// <summary>
    /// Observes <see cref="TransformationEvent"/>s emitted from the Transformer pipeline
    /// and forwards aggregated telemetry to a metrics back-end as well as structured logs.
    /// </summary>
    /// <remarks>
    /// The observer is **thread-safe** and inexpensive; it is designed to be reused
    /// for multiple observable subscriptions within the ETL microservice.
    ///
    /// Typical usage:
    /// <code>
    ///   var observer = new MonitoringObserver(logger, metrics);
    ///   observableTransformationEvents.Subscribe(observer);
    /// </code>
    /// </remarks>
    public sealed class MonitoringObserver : IObserver<TransformationEvent>, IDisposable
    {
        private readonly ILogger<MonitoringObserver> _logger;
        private readonly IMetricsRecorder _metrics;
        private int _hasCompleted;

        public MonitoringObserver(
            ILogger<MonitoringObserver> logger,
            IMetricsRecorder metricsRecorder)
        {
            _logger  = logger  ?? throw new ArgumentNullException(nameof(logger));
            _metrics = metricsRecorder ?? throw new ArgumentNullException(nameof(metricsRecorder));
        }

        #region IObserver

        public void OnNext(TransformationEvent value)
        {
            if (value is null) return;

            // Emit structured log
            _logger.LogInformation(
                "Transformer {Transformer} processed {Input} records (Output = {Output}) in {ElapsedMs:n0} ms [Success = {Success}] {@Event}",
                value.TransformerName,
                value.InputRecords,
                value.OutputRecords,
                value.Duration.TotalMilliseconds,
                value.IsSuccess,
                value);

            // Emit metrics
            var commonTags = new[]
            {
                ("pipeline",  value.Pipeline),
                ("transformer", value.TransformerName),
                ("success", value.IsSuccess.ToString().ToLowerInvariant())
            };

            _metrics.IncrementCounter("transformations_total", 1, commonTags);

            // Record duration as histogram (seconds)
            _metrics.RecordHistogram("transformation_duration_seconds",
                value.Duration.TotalSeconds, commonTags);

            // Record throughput gauges (records / s)
            if (value.Duration > TimeSpan.Zero)
            {
                var throughputIn  = value.InputRecords  / value.Duration.TotalSeconds;
                var throughputOut = value.OutputRecords / value.Duration.TotalSeconds;

                _metrics.RecordGauge("transformation_throughput_in_records_per_second",
                    throughputIn,  commonTags);
                _metrics.RecordGauge("transformation_throughput_out_records_per_second",
                    throughputOut, commonTags);
            }

            if (!value.IsSuccess && !string.IsNullOrWhiteSpace(value.ErrorMessage))
            {
                _metrics.IncrementCounter("transformation_failures_total", 1, commonTags);
            }
        }

        public void OnError(Exception error)
        {
            _logger.LogError(error, "An error occurred in the transformation observable.");
            _metrics.IncrementCounter("transformation_observer_errors_total", 1,
                ("component", nameof(MonitoringObserver)));
        }

        public void OnCompleted()
        {
            // Ensure we only log completion once in case multiple observables share the same observer.
            if (Interlocked.Exchange(ref _hasCompleted, 1) == 0)
            {
                _logger.LogInformation("Transformation event stream completed.");
            }
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            // Currently no unmanaged resources—placeholder for future additions.
        }

        #endregion
    }

    #region Supporting ­domain primitives

    /// <summary>
    /// Domain event published after each individual Transformer completes its work.
    /// </summary>
    public sealed record TransformationEvent(
        Guid JobId,
        string Pipeline,
        string TransformerName,
        DateTimeOffset StartedAt,
        DateTimeOffset EndedAt,
        long InputRecords,
        long OutputRecords,
        bool IsSuccess,
        string? ErrorMessage = null)
    {
        public TimeSpan Duration => EndedAt - StartedAt;
    }

    /// <summary>
    /// Abstraction over a metrics backend (Prometheus, App-Insights, Datadog, etc.).
    /// Implementations should be lightweight and thread-safe.
    /// </summary>
    public interface IMetricsRecorder
    {
        /// <summary>
        /// Increments a counter metric by the specified value.
        /// </summary>
        void IncrementCounter(string name, double value = 1,
            params (string Key, string Value)[] tags);

        /// <summary>
        /// Records a gauge metric.
        /// </summary>
        void RecordGauge(string name, double value,
            params (string Key, string Value)[] tags);

        /// <summary>
        /// Records a histogram/sample.
        /// </summary>
        void RecordHistogram(string name, double value,
            params (string Key, string Value)[] tags);
    }

    #endregion
}