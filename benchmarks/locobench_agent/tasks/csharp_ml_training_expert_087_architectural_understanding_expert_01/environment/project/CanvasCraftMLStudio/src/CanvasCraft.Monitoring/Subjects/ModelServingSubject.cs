```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Monitoring/Subjects/ModelServingSubject.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Monitoring.Events;
using CanvasCraft.Monitoring.Observers;

namespace CanvasCraft.Monitoring.Subjects
{
    /// <summary>
    /// ModelServingSubject is the central hub for runtime-serving events flowing
    /// out of the CanvasCraft inference gallery.  Any component interested in
    /// live prediction metrics, drift reports, or serving-side exceptions can
    /// subscribe to this subject and react in near real-time.
    ///
    /// Design notes:
    /// • Implements IObservable to conform to the Observer pattern.
    /// • Uses a thread-safe collection to keep subscriptions lightweight and lock-free.
    /// • Each event dispatch is fire-and-forget to avoid blocking the inference
    ///   pipeline; back-pressure or throttling is handled upstream by the
    ///   MonitoringPipeline in case of observer overload.
    /// </summary>
    public sealed class ModelServingSubject : IModelServingSubject, IObservable<ServingEventBase>, IDisposable
    {
        // ─────────────────────────────────────────────────────────────────────────────
        // Fields
        // ─────────────────────────────────────────────────────────────────────────────
        private readonly ConcurrentDictionary<IObserver<ServingEventBase>, byte> _observers;
        private readonly CancellationTokenSource _cancellationTokenSource;
        private bool _disposed;

        // ─────────────────────────────────────────────────────────────────────────────
        // Ctor
        // ─────────────────────────────────────────────────────────────────────────────
        public ModelServingSubject()
        {
            _observers = new ConcurrentDictionary<IObserver<ServingEventBase>, byte>();
            _cancellationTokenSource = new CancellationTokenSource();
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // Public API – IObservable
        // ─────────────────────────────────────────────────────────────────────────────
        /// <summary>
        /// Subscribe an observer to serving events.
        /// </summary>
        public IDisposable Subscribe(IObserver<ServingEventBase> observer)
        {
            if (observer == null) throw new ArgumentNullException(nameof(observer));

            _observers.TryAdd(observer, 0);
            return new Unsubscriber(_observers, observer);
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // Public API – Specific helpers
        // ─────────────────────────────────────────────────────────────────────────────
        /// <inheritdoc />
        public IDisposable Subscribe(IModelServingObserver observer) => Subscribe((IObserver<ServingEventBase>)observer);

        /// <inheritdoc />
        public void PublishMetrics(ServingMetrics metrics)
        {
            if (metrics == null) throw new ArgumentNullException(nameof(metrics));
            PublishInternal(metrics);
        }

        /// <inheritdoc />
        public void PublishAlert(ServingAlert alert)
        {
            if (alert == null) throw new ArgumentNullException(nameof(alert));
            PublishInternal(alert);
        }

        /// <summary>
        /// Flushes a custom event derived from <see cref="ServingEventBase"/>.
        /// </summary>
        public void PublishCustom<T>(T evt)
            where T : ServingEventBase
        {
            if (evt == null) throw new ArgumentNullException(nameof(evt));
            PublishInternal(evt);
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // Private helpers
        // ─────────────────────────────────────────────────────────────────────────────
        private void PublishInternal(ServingEventBase evt)
        {
            if (_disposed) return;

            var tasks = new List<Task>(_observers.Count);

            foreach (var observer in _observers.Keys)
            {
                tasks.Add(Task.Run(() =>
                {
                    try
                    {
                        observer.OnNext(evt);
                    }
                    catch (Exception ex)
                    {
                        // A poorly-behaved observer should not crash the pipeline.
                        // We forward the error to the observer and move on.
                        observer.OnError(ex);
                    }
                }, _cancellationTokenSource.Token));
            }

            // Fire-and-forget, but aggregate any exceptions to ensure tasks don't get swallowed without trace.
            Task.WhenAll(tasks).ContinueWith(t =>
            {
                if (t.IsFaulted && t.Exception != null)
                {
                    // Log the aggregate exception; in production this could be forwarded
                    // to an internal telemetry sink (AppInsights, Sentry, etc.).
                    System.Diagnostics.Trace.TraceError(t.Exception.ToString());
                }
            }, TaskContinuationOptions.OnlyOnFaulted);
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // IDisposable
        // ─────────────────────────────────────────────────────────────────────────────
        public void Dispose()
        {
            if (_disposed) return;

            _disposed = true;
            _cancellationTokenSource.Cancel();

            // Inform observers that the stream has completed.
            foreach (var kvp in _observers)
            {
                try
                {
                    kvp.Key.OnCompleted();
                }
                catch
                {
                    // Ignore exceptions from broken observers.
                }
            }

            _observers.Clear();
            _cancellationTokenSource.Dispose();
        }

        // ─────────────────────────────────────────────────────────────────────────────
        // Nested types
        // ─────────────────────────────────────────────────────────────────────────────
        private sealed class Unsubscriber : IDisposable
        {
            private readonly ConcurrentDictionary<IObserver<ServingEventBase>, byte> _refs;
            private readonly IObserver<ServingEventBase> _observer;

            public Unsubscriber(ConcurrentDictionary<IObserver<ServingEventBase>, byte> observers,
                                IObserver<ServingEventBase> observer)
            {
                _refs = observers;
                _observer = observer;
            }

            public void Dispose()
            {
                if (_observer != null)
                {
                    _refs.TryRemove(_observer, out _);
                }
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────────────────
    // Interfaces & Domain Events — (they normally live elsewhere but are declared
    // here for compilation completeness in this isolated file)
    // ─────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Composite interface for model-serving observers interested in <see cref="ServingEventBase"/> messages.
    /// </summary>
    public interface IModelServingObserver : IObserver<ServingEventBase> { }

    /// <summary>
    /// Contract for the subject. Kept minimal to avoid leaking implementation details.
    /// </summary>
    public interface IModelServingSubject
    {
        IDisposable Subscribe(IModelServingObserver observer);

        /// <summary>
        /// Publish a standard metrics object (latency, throughput, etc.).
        /// </summary>
        void PublishMetrics(ServingMetrics metrics);

        /// <summary>
        /// Publish an alert signalling drift, SLA breach, or infrastructure issue.
        /// </summary>
        void PublishAlert(ServingAlert alert);

        /// <summary>
        /// Publish a user-defined event derived from <see cref="ServingEventBase"/>.
        /// </summary>
        void PublishCustom<T>(T evt) where T : ServingEventBase;
    }

    // ---------------------------------------------------------------------------
    // Generic base event + sample implementations
    // ---------------------------------------------------------------------------
    /// <summary>
    /// Root class for any serving-side event propagated via the subject.
    /// </summary>
    public abstract class ServingEventBase
    {
        public DateTimeOffset Timestamp { get; }

        protected ServingEventBase()
        {
            Timestamp = DateTimeOffset.UtcNow;
        }
    }

    /// <summary>
    /// Event that carries performance metrics.
    /// </summary>
    public sealed class ServingMetrics : ServingEventBase
    {
        public string ModelName { get; }
        public double AverageLatencyMs { get; }
        public double ThroughputRps { get; }
        public double ErrorRate { get; }

        public ServingMetrics(string modelName,
                              double averageLatencyMs,
                              double throughputRps,
                              double errorRate)
        {
            if (string.IsNullOrWhiteSpace(modelName)) throw new ArgumentException("Model name must be provided.", nameof(modelName));
            if (averageLatencyMs < 0) throw new ArgumentOutOfRangeException(nameof(averageLatencyMs));
            if (throughputRps < 0) throw new ArgumentOutOfRangeException(nameof(throughputRps));
            if (errorRate < 0) throw new ArgumentOutOfRangeException(nameof(errorRate));

            ModelName = modelName;
            AverageLatencyMs = averageLatencyMs;
            ThroughputRps = throughputRps;
            ErrorRate = errorRate;
        }
    }

    /// <summary>
    /// Event that represents an alert (e.g., drift, SLA breach).
    /// </summary>
    public sealed class ServingAlert : ServingEventBase
    {
        public string ModelName { get; }
        public string AlertCode { get; }
        public string Message { get; }
        public AlertSeverity Severity { get; }

        public ServingAlert(string modelName, string alertCode, string message, AlertSeverity severity)
        {
            if (string.IsNullOrWhiteSpace(modelName)) throw new ArgumentException("Model name must be provided.", nameof(modelName));
            if (string.IsNullOrWhiteSpace(alertCode)) throw new ArgumentException("Alert code must be provided.", nameof(alertCode));
            if (string.IsNullOrWhiteSpace(message)) throw new ArgumentException("Message must be provided.", nameof(message));

            ModelName = modelName;
            AlertCode = alertCode;
            Message = message;
            Severity = severity;
        }
    }

    /// <summary>
    /// Severity classifier for alerts.
    /// </summary>
    public enum AlertSeverity
    {
        Low,
        Medium,
        High,
        Critical
    }
}
```