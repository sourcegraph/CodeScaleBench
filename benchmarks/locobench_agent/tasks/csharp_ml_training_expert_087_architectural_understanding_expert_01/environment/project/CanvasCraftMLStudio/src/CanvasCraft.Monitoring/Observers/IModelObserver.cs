```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Monitoring.Observers
{
    /// <summary>
    /// Describes the semantic nature of a monitoring signal emitted by the Model Monitor.
    /// </summary>
    public enum MonitorSignal
    {
        /// <summary>
        /// The training or inference run for the model has started.
        /// </summary>
        ModelRunStarted,

        /// <summary>
        /// A new metric snapshot (e.g., loss, accuracy) is available.
        /// </summary>
        MetricUpdate,

        /// <summary>
        /// Data or concept drift has been detected beyond a configured threshold.
        /// </summary>
        DriftDetected,

        /// <summary>
        /// The model run has finished successfully.
        /// </summary>
        ModelRunCompleted,

        /// <summary>
        /// An unrecoverable error occurred in the pipeline.
        /// </summary>
        PipelineError,

        /// <summary>
        /// Custom/user-defined signal.
        /// </summary>
        Custom
    }

    /// <summary>
    /// Immutable, serializable event payload describing an update emitted by the
    /// model-monitoring pipeline.  Instances are intended to be lightweight and
    /// suitable for transport across process or network boundaries.
    /// </summary>
    public sealed record ModelMonitorEvent
    (
        Guid ModelId,
        MonitorSignal Signal,
        DateTimeOffset Timestamp,
        IReadOnlyDictionary<string, object>? Payload = null,
        string? CorrelationId = null
    );

    /// <summary>
    /// Observer abstraction for components that wish to listen to <see cref="ModelMonitorEvent"/>
    /// streams.  Follows the standard <c>IObserver{T}</c> contract and augments it with async
    /// support, subscription lifecycle metadata, as well as structured identification that can
    /// be leveraged by DI containers, message buses, or distributed tracing frameworks.
    /// </summary>
    public interface IModelObserver : IObserver<ModelMonitorEvent>, IDisposable
    {
        /// <summary>
        /// Human-readable identifier of this observer (e.g., "TrainingDashboardSink").
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Stable identifier for correlation across distributed systems.
        /// </summary>
        Guid ObserverId { get; }

        /// <summary>
        /// Indicates whether the observer is currently subscribed to an event source.
        /// </summary>
        bool IsSubscribed { get; }

        /// <summary>
        /// Optional event-level filter.  If the method returns <c>false</c>, the event
        /// is ignored and <see cref="IObserver{T}.OnNext"/> will not be invoked.
        /// Implementers should keep the logic lightweight because it is executed
        /// in-line with the publisher’s publish loop.
        /// </summary>
        /// <param name="monitorEvent">Candidate event.</param>
        /// <returns><c>true</c> if the event should be processed; otherwise <c>false</c>.</returns>
        bool ShouldProcess(in ModelMonitorEvent monitorEvent);

        /// <summary>
        /// Asynchronous counterpart to <see cref="IObserver{T}.OnNext"/> that enables
        /// non-blocking event processing (e.g., remote logging, database persistence,
        /// UI rendering).  Implementers should honor the supplied
        /// <paramref name="cancellationToken"/>.
        /// </summary>
        /// <param name="monitorEvent">The event being consumed.</param>
        /// <param name="cancellationToken">Token to cancel the async operation.</param>
        /// <exception cref="OperationCanceledException">Thrown if the operation is cancelled.</exception>
        Task ReceiveAsync(ModelMonitorEvent monitorEvent, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Common extension methods for <see cref="IModelObserver"/> implementers.
    /// </summary>
    public static class ModelObserverExtensions
    {
        /// <summary>
        /// Safely notifies the observer of an event without propagating exceptions back
        /// to the publisher.  Any exceptions thrown by the observer are routed to
        /// <see cref="IObserver{T}.OnError"/>.
        /// </summary>
        /// <param name="observer">The target observer.</param>
        /// <param name="monitorEvent">Event to deliver.</param>
        /// <remarks>
        /// This helper enables publishers to implement a <i>fire-and-forget</i> model while still
        /// respecting the Rx contract.
        /// </remarks>
        public static void SafeOnNext(this IModelObserver observer, ModelMonitorEvent monitorEvent)
        {
            if (observer == null)
                throw new ArgumentNullException(nameof(observer));

            if (!observer.ShouldProcess(in monitorEvent))
                return;

            try
            {
                observer.OnNext(monitorEvent);
            }
            catch (Exception ex)
            {
                observer.OnError(ex);
            }
        }

        /// <summary>
        /// Asynchronously notifies an observer, eating any exceptions and piping them
        /// through the error channel to keep the publisher clean.
        /// </summary>
        public static async Task SafeReceiveAsync(
            this IModelObserver observer,
            ModelMonitorEvent monitorEvent,
            CancellationToken cancellationToken = default)
        {
            if (observer == null)
                throw new ArgumentNullException(nameof(observer));

            if (!observer.ShouldProcess(in monitorEvent))
                return;

            try
            {
                await observer.ReceiveAsync(monitorEvent, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex) when (!ex.IsCritical())
            {
                observer.OnError(ex);
            }
        }

        /// <summary>
        /// Determines whether an exception is considered fatal for the application domain.
        /// </summary>
        private static bool IsCritical(this Exception ex)
        {
            return ex is OutOfMemoryException or StackOverflowException or AccessViolationException;
        }
    }
}
```