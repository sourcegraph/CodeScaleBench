```csharp
// --------------------------------------------------------------------------------------------------------------------
//  TycoonVerse: Enterprise Empire Simulator
//  File:        TycoonVerse/src/TycoonVerse.Application/Common/EventBus.cs
//  Author:      AI Generated
//  Created:     2024-06-14
//
//  Description: Thread-safe event-aggregation hub that coordinates domain and
//               application events across bounded contexts (UI, Analytics, Persistence,
//               Multiplayer, etc.).  The bus supports transient in-memory dispatching
//               for online play as well as a durable queue for “offline first”
//               scenarios—events raised while the player is disconnected are stored
//               locally and replayed once a network round-trip is available.
//
//  Architectural notes:
//      • Singleton – global access point inside the application layer
//      • Observer  – handlers subscribe to strongly-typed events
//      • Factory   – pluggable storage back-ends through IOfflineEventStore
//
//  The implementation purposefully avoids any Unity-specific constructs so that
//  it can be unit-tested headlessly and reused by dedicated servers.
// --------------------------------------------------------------------------------------------------------------------
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace TycoonVerse.Application.Common
{
    #region Contracts

    /// <summary>
    ///     Marker base-class for all domain events.
    ///     Concrete events should be implemented inside <c>TycoonVerse.Domain.Events</c>.
    /// </summary>
    public abstract record DomainEvent
    {
        /// <summary>Correlation id connecting a chain of events to a single action.</summary>
        public Guid CorrelationId { get; init; } = Guid.NewGuid();

        /// <summary>UTC timestamp when the event was raised.</summary>
        public DateTimeOffset OccurredOnUtc { get; init; } = DateTimeOffset.UtcNow;
    }

    /// <summary>Any component interested in a specific event type implements this interface.</summary>
    /// <typeparam name="TEvent">Concrete event type the handler processes.</typeparam>
    public interface IEventHandler<in TEvent> where TEvent : DomainEvent
    {
        /// <summary>Handle an event asynchronously.</summary>
        Task HandleAsync(TEvent @event, CancellationToken cancellationToken = default);
    }

    /// <summary>Public API that the rest of the app uses to interact with the event bus.</summary>
    public interface IEventBus : IAsyncDisposable
    {
        /// <summary>Publish a new event to the bus.</summary>
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken cancellationToken = default)
            where TEvent : DomainEvent;

        /// <summary>Subscribe a handler instance to a specific event type.</summary>
        void Subscribe<TEvent>(IEventHandler<TEvent> handler) where TEvent : DomainEvent;

        /// <summary>Remove an existing subscription.</summary>
        void Unsubscribe<TEvent>(IEventHandler<TEvent> handler) where TEvent : DomainEvent;

        /// <summary>Flush any queued events (e.g., after regaining network connectivity).</summary>
        Task FlushQueuedAsync(CancellationToken cancellationToken = default);
    }

    /// <summary>
    ///     Optional durability layer—implementations can persist events to SQLite, file, or encrypted
    ///     container so that gameplay remains deterministic while offline.
    /// </summary>
    public interface IOfflineEventStore : IAsyncDisposable
    {
        ValueTask EnqueueAsync(DomainEvent @event, CancellationToken cancellationToken = default);
        IAsyncEnumerable<DomainEvent> DequeueAsync(CancellationToken cancellationToken = default);
    }

    #endregion

    /// <summary>
    ///     Production-grade, strongly-typed, thread-safe event bus.
    /// </summary>
    internal sealed class EventBus : IEventBus
    {
        #region Fields

        private readonly ILogger<EventBus> _logger;
        private readonly IOfflineEventStore? _offlineStore;

        // Event handlers keyed by concrete DomainEvent type
        private readonly ConcurrentDictionary<Type, ConcurrentBag<object>> _subscriptions = new();

        // Used to guarantee Dispose/Flush is not executed concurrently
        private readonly SemaphoreSlim _lifecycleSemaphore = new(1, 1);
        private bool _disposed;

        #endregion

        #region Ctor

        public EventBus(ILogger<EventBus> logger, IOfflineEventStore? offlineStore = null)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _offlineStore = offlineStore;
        }

        #endregion

        #region IEventBus

        /// <inheritdoc />
        public void Subscribe<TEvent>(IEventHandler<TEvent> handler) where TEvent : DomainEvent
        {
            if (handler is null) throw new ArgumentNullException(nameof(handler));

            var bag = _subscriptions.GetOrAdd(typeof(TEvent), _ => new ConcurrentBag<object>());
            bag.Add(handler);

            _logger.LogDebug("Handler {Handler} subscribed to event {EventType}", handler.GetType().Name,
                typeof(TEvent).Name);
        }

        /// <inheritdoc />
        public void Unsubscribe<TEvent>(IEventHandler<TEvent> handler) where TEvent : DomainEvent
        {
            if (handler is null) throw new ArgumentNullException(nameof(handler));

            if (_subscriptions.TryGetValue(typeof(TEvent), out var bag))
            {
                // ConcurrentBag doesn't support removal, hence rebuild collection
                var newBag = new ConcurrentBag<object>(bag.Where(h => !ReferenceEquals(h, handler)));

                _subscriptions[typeof(TEvent)] = newBag;

                _logger.LogDebug("Handler {Handler} unsubscribed from event {EventType}", handler.GetType().Name,
                    typeof(TEvent).Name);
            }
        }

        /// <inheritdoc />
        public async Task PublishAsync<TEvent>(TEvent @event, CancellationToken cancellationToken = default)
            where TEvent : DomainEvent
        {
            if (@event is null) throw new ArgumentNullException(nameof(@event));

            _logger.LogTrace("Publishing event {EventType} (Correlation: {CorrelationId})",
                typeof(TEvent).Name, @event.CorrelationId);

            // Dispatch immediately to all subscribers
            var dispatchTasks = GetHandlers<TEvent>()
                .Select(h => SafeHandleAsync(h, @event, cancellationToken))
                .ToArray();

            // Always store offline, regardless of connected state, to guarantee deterministic replay
            if (_offlineStore is not null)
            {
                await _offlineStore.EnqueueAsync(@event, cancellationToken).ConfigureAwait(false);
            }

            await Task.WhenAll(dispatchTasks).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task FlushQueuedAsync(CancellationToken cancellationToken = default)
        {
            if (_offlineStore is null) return;

            await foreach (DomainEvent persistedEvent in _offlineStore.DequeueAsync(cancellationToken)
                                .ConfigureAwait(false))
            {
                _logger.LogTrace("Replaying queued event {EventType} (Correlation: {CorrelationId})",
                    persistedEvent.GetType().Name, persistedEvent.CorrelationId);

                // Dynamically invoke generic PublishAsync<TEvent>
                var method = typeof(EventBus).GetMethod(nameof(PublishAsync))!
                                             .MakeGenericMethod(persistedEvent.GetType());
                await (Task)method.Invoke(this, new object?[] { persistedEvent, cancellationToken })!;
            }
        }

        #endregion

        #region Helpers

        private IEnumerable<IEventHandler<TEvent>> GetHandlers<TEvent>() where TEvent : DomainEvent
        {
            if (_subscriptions.TryGetValue(typeof(TEvent), out var bag))
            {
                foreach (var handler in bag)
                    if (handler is IEventHandler<TEvent> typed)
                        yield return typed;
            }
        }

        private async Task SafeHandleAsync<TEvent>(
            IEventHandler<TEvent> handler,
            TEvent @event,
            CancellationToken cancellationToken)
            where TEvent : DomainEvent
        {
            try
            {
                await handler.HandleAsync(@event, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                _logger.LogWarning("Event handling was cancelled. Handler={Handler}, Event={EventType}",
                    handler.GetType().Name, typeof(TEvent).Name);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unhandled exception in event handler {Handler} for event {EventType}",
                    handler.GetType().Name, typeof(TEvent).Name);
                // Game design decision: swallow exception to prevent one faulty handler from breaking the loop.
            }
        }

        #endregion

        #region Dispose

        /// <inheritdoc />
        public async ValueTask DisposeAsync()
        {
            await _lifecycleSemaphore.WaitAsync().ConfigureAwait(false);
            try
            {
                if (_disposed) return;

                _disposed = true;

                // Flush any remaining queued events before closing
                await FlushQueuedAsync().ConfigureAwait(false);

                _lifecycleSemaphore.Dispose();
                if (_offlineStore is not null) await _offlineStore.DisposeAsync().ConfigureAwait(false);
            }
            finally
            {
                // ReSharper disable once ConditionIsAlwaysTrueOrFalseAccordingToNullableAPIContract
                if (!_disposed) _lifecycleSemaphore.Release();
            }
        }

        #endregion
    }
}
```