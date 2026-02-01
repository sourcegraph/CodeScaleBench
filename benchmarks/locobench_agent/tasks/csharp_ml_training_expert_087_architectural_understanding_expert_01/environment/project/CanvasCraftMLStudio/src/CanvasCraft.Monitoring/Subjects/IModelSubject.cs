using System;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Monitoring.Events;
using CanvasCraft.Monitoring.Observers;
using CanvasCraft.Registry.Models;

namespace CanvasCraft.Monitoring.Subjects
{
    /// <summary>
    /// Represents a concrete publisher in the Observer pattern responsible for emitting
    /// monitoring-related events tied to a single machine-learning model instance.
    ///
    /// The interface extends <see cref="IObservable{T}"/> so that consumers can leverage
    /// the System.Reactive ecosystem (e.g., LINQ-to-Events, Rx.NET) without forcing an
    /// implementation to depend on any specific reactive library.
    ///
    /// Implementations MUST be thread-safe; monitoring events often originate from
    /// background training jobs, RESTful inference endpoints, and UI-driven dashboards
    /// concurrently.
    /// </summary>
    /// <typeparam name="TEvent">
    /// The concrete event payload type derived from <see cref="ModelEventBase"/> that the
    /// subject will publish.
    /// </typeparam>
    public interface IModelSubject<out TEvent> : IObservable<TEvent> where TEvent : ModelEventBase
    {
        /// <summary>
        /// Gets a descriptor that uniquely identifies the model (and optionally its
        /// version or training run) within the CanvasCraft Model Registry.
        /// </summary>
        ModelDescriptor Descriptor { get; }

        /// <summary>
        /// Publishes the specified event to all current observers.
        /// Implementations must:
        ///   1. Be safe for concurrent calls.
        ///   2. Ensure that a single misbehaving observer cannot disrupt notifications
        ///      to other observers (error isolation).
        ///   3. Deliver events in the order they were published per observer.
        /// </summary>
        /// <param name="evt">The event payload to broadcast.</param>
        /// <param name="cancellationToken">
        /// Optional token that allows the caller to cancel the publish operation before
        /// completion (e.g., during shutdown).
        /// </param>
        Task PublishAsync(TEvent evt, CancellationToken cancellationToken = default);
    }
}