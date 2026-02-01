```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Core/Abstractions/IEventBus.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace UtilityChain.Core.Abstractions
{
    #region Event-bus Contracts

    /// <summary>
    ///     Marker interface for domain events flowing through the in-process <see cref="IEventBus" />.
    /// </summary>
    public interface IEvent { }

    /// <summary>
    ///     Marker interface for request/response style events.
    /// </summary>
    /// <typeparam name="TResult">The expected result type returned to the publisher.</typeparam>
    public interface IRequestEvent<TResult> : IEvent { }

    /// <summary>
    ///     Handles a specific <typeparamref name="TEvent" />.
    /// </summary>
    /// <typeparam name="TEvent">Event type.</typeparam>
    public interface IEventHandler<in TEvent>
        where TEvent : IEvent
    {
        /// <summary>
        ///     Processes an incoming event.
        /// </summary>
        ValueTask HandleAsync(TEvent @event, CancellationToken ct);
    }

    /// <summary>
    ///     Contract for the internal event bus that glues together every UtilityChain module.
    ///     The bus is intentionally light-weight (in-memory only) and must NEVER block
    ///     the caller thread.
    /// </summary>
    public interface IEventBus
    {
        #region Publish

        /// <summary>
        ///     Fire-and-forget publication.
        /// </summary>
        ValueTask PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
            where TEvent : class, IEvent;

        /// <summary>
        ///     Publishes a request event and awaits the response.
        /// </summary>
        /// <exception cref="TimeoutException">
        ///     Thrown when no handler returns a result before <paramref name="ct" /> is cancelled.
        /// </exception>
        ValueTask<TResult> PublishAsync<TEvent, TResult>(TEvent @event, CancellationToken ct = default)
            where TEvent : class, IRequestEvent<TResult>
            where TResult : class;

        #endregion

        #region Subscribe

        /// <summary>
        ///     Subscribes a delegate to <typeparamref name="TEvent" /> messages.
        /// </summary>
        SubscriptionToken Subscribe<TEvent>(
            Func<TEvent, CancellationToken, ValueTask> handler,
            SubscriptionOptions? options = null)
            where TEvent : class, IEvent;

        /// <summary>
        ///     Subscribes a DI-resolved event handler.
        /// </summary>
        SubscriptionToken Subscribe<TEventHandler, TEvent>(SubscriptionOptions? options = null)
            where TEventHandler : class, IEventHandler<TEvent>
            where TEvent : class, IEvent;

        /// <summary>
        ///     Removes an existing subscription.
        /// </summary>
        void Unsubscribe(in SubscriptionToken token);

        #endregion
    }

    #endregion

    #region Supporting Primitives

    /// <summary>
    ///     Represents an opaque handle that can be used to unregister an existing subscription.
    /// </summary>
    public readonly record struct SubscriptionToken(Guid Value)
    {
        public static SubscriptionToken New() => new(Guid.NewGuid());
        public bool IsEmpty => Value == Guid.Empty;
        public override string ToString() => Value.ToString("N");
    }

    /// <summary>
    ///     Configures fine-grained subscription behaviour.
    /// </summary>
    public sealed class SubscriptionOptions
    {
        /// <summary>
        ///     Gets or sets the maximum number of concurrent handler invocations
        ///     the bus will schedule for this subscription (default = <c>1</c>).
        /// </summary>
        public int MaxDegreeOfParallelism { get; init; } = 1;

        /// <summary>
        ///     Indicates whether derived event types should also be delivered
        ///     to the subscription (<c>false</c> by default).
        /// </summary>
        public bool IncludeDerivedTypes { get; init; }

        /// <summary>
        ///     Optional filter to short-circuit event delivery.
        ///     The event is delivered only when the predicate returns <c>true</c>.
        /// </summary>
        public Func<IEvent, bool>? Filter { get; init; }
    }

    #endregion

    #region In-Memory Implementation (optional)

    /// <summary>
    ///     Production-ready in-memory implementation of <see cref="IEventBus" />.
    ///     Thread-safe and allocation-friendly.
    /// </summary>
    internal sealed class InMemoryEventBus : IEventBus
    {
        private sealed record Subscription(
            Type EventType,
            Func<IEvent, CancellationToken, ValueTask> Handler,
            SubscriptionOptions Options);

        private readonly ConcurrentDictionary<SubscriptionToken, Subscription> _subscriptions = new();

        #region Publish

        public ValueTask PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
            where TEvent : class, IEvent
        {
            if (@event is null) throw new ArgumentNullException(nameof(@event));

            // Fast path – copy subscription list to avoid locking during await
            var subscribers = GetSubscribers(@event.GetType());

            return subscribers.Length == 0
                ? ValueTask.CompletedTask
                : InvokeHandlersAsync(subscribers, @event, ct);

            static async ValueTask InvokeHandlersAsync(Subscription[] subs, IEvent ev, CancellationToken token)
            {
                var tasks = new List<Task>(subs.Length);

                foreach (var sub in subs)
                {
                    if (token.IsCancellationRequested) break;

                    // Filter
                    if (sub.Options.Filter is { } filter && !filter(ev)) continue;

                    // Serial execution when MaxDegreeOfParallelism == 1
                    if (sub.Options.MaxDegreeOfParallelism <= 1)
                    {
                        await sub.Handler(ev, token).ConfigureAwait(false);
                        continue;
                    }

                    // Concurrent execution
                    tasks.Add(Task.Run(() => sub.Handler(ev, token).AsTask(), token));
                    if (tasks.Count >= sub.Options.MaxDegreeOfParallelism)
                    {
                        await Task.WhenAll(tasks).ConfigureAwait(false);
                        tasks.Clear();
                    }
                }

                if (tasks.Count > 0)
                    await Task.WhenAll(tasks).ConfigureAwait(false);
            }
        }

        public async ValueTask<TResult> PublishAsync<TEvent, TResult>(TEvent @event, CancellationToken ct = default)
            where TEvent : class, IRequestEvent<TResult>
            where TResult : class
        {
            if (@event is null) throw new ArgumentNullException(nameof(@event));

            var subscribers = GetSubscribers(typeof(TEvent));
            if (subscribers.Length == 0)
                throw new InvalidOperationException(
                    $"No handler registered for request event '{typeof(TEvent).Name}'.");

            // We expect a single (command) handler for request/response semantics.
            if (subscribers.Length > 1)
                throw new InvalidOperationException(
                    $"Multiple handlers registered for request event '{typeof(TEvent).Name}'. " +
                    "Only one handler can return a value.");

            var (handler, options) = (subscribers[0].Handler, subscribers[0].Options);

            // Respect cancellation and P-L options.
            if (options.MaxDegreeOfParallelism > 1)
            {
                return await Task
                    .Run(() => handler(@event, ct).AsTask(), ct)
                    .ConfigureAwait(false) as TResult
                    ?? throw new InvalidOperationException("Handler returned null result.");
            }

            return await handler(@event, ct).ConfigureAwait(false) as TResult
                   ?? throw new InvalidOperationException("Handler returned null result.");
        }

        #endregion

        #region Subscribe

        public SubscriptionToken Subscribe<TEvent>(
            Func<TEvent, CancellationToken, ValueTask> handler,
            SubscriptionOptions? options = null)
            where TEvent : class, IEvent
        {
            if (handler is null) throw new ArgumentNullException(nameof(handler));

            var token = SubscriptionToken.New();

            _subscriptions.TryAdd(
                token,
                new Subscription(
                    typeof(TEvent),
                    // Box to generic IEvent
                    (e, ct) => handler((TEvent)e, ct),
                    options ?? new SubscriptionOptions()));

            return token;
        }

        public SubscriptionToken Subscribe<TEventHandler, TEvent>(SubscriptionOptions? options = null)
            where TEventHandler : class, IEventHandler<TEvent>, new()
            where TEvent : class, IEvent
        {
            // Resolve via Activator; in production, plug your DI container here.
            var handlerInstance = new TEventHandler();
            return Subscribe<TEvent>(
                (e, ct) => handlerInstance.HandleAsync(e, ct),
                options);
        }

        public void Unsubscribe(in SubscriptionToken token)
        {
            _subscriptions.TryRemove(token, out _);
        }

        #endregion

        #region Helpers

        private Subscription[] GetSubscribers(Type eventType)
        {
            // Copy to array to avoid allocation during enumeration
            var list = new List<Subscription>();

            foreach (var sub in _subscriptions.Values)
            {
                if (sub.EventType == eventType ||
                    (sub.Options.IncludeDerivedTypes && sub.EventType.IsAssignableFrom(eventType)))
                {
                    list.Add(sub);
                }
            }

            return list.ToArray();
        }

        #endregion
    }

    #endregion
}
```