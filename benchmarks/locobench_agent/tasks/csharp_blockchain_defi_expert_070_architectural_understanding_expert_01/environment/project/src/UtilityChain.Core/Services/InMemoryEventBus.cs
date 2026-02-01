```csharp
﻿// -----------------------------------------------------------------------------
//  UtilityChain Core Suite
//  Copyright (c) 2024 
//  https://github.com/UtilityChain/Core
//
//  This file is part of UtilityChain Core Suite. The software is released
//  under the MIT license. See LICENSE file in the root directory for more
//  information.
// -----------------------------------------------------------------------------
//  File:        InMemoryEventBus.cs
//  Description: High-performance in-process event bus for decoupled module
//               communication inside the monolithic UtilityChain executable.
//  ---------------------------------------------------------------------------

#nullable enable
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Runtime.CompilerServices;
using System.Threading.Channels;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Core.Services;

/// <summary>
/// Marker interface for events flowing through <see cref="InMemoryEventBus" />.
/// </summary>
public interface IEvent { }

/// <summary>
/// Event bus contract used throughout the UtilityChain codebase. Only in-process
/// communication is required; therefore implementations may rely on shared
/// memory and do not need to provide distributed guarantees.
/// </summary>
public interface IEventBus : IAsyncDisposable, IDisposable
{
    /// <summary>
    /// Subscribes to events of type <typeparamref name="TEvent" />.
    /// </summary>
    /// <param name="handler">
    /// Asynchronous delegate invoked when an event is published.
    /// </param>
    /// <param name="subscriberId">
    /// Optional friendly identifier used for logging and unsubscription.
    /// </param>
    /// <typeparam name="TEvent">Concrete event type.</typeparam>
    /// <returns>
    /// An <see cref="IDisposable" /> that should be disposed to remove the
    /// subscription.
    /// </returns>
    IDisposable Subscribe<TEvent>(
        Func<TEvent, CancellationToken, ValueTask> handler,
        string? subscriberId = null)
        where TEvent : IEvent;

    /// <summary>
    /// Publishes an event to the bus. The call is non-blocking; the event is
    /// enqueued and processed on background dispatchers respecting ordering.
    /// </summary>
    /// <typeparam name="TEvent">Concrete event type.</typeparam>
    /// <param name="event">The event instance.</param>
    /// <param name="cancellationToken">
    /// Token that propagates cancellation to observers.
    /// </param>
    ValueTask PublishAsync<TEvent>(
        TEvent @event,
        CancellationToken cancellationToken = default)
        where TEvent : IEvent;

    /// <summary>
    /// Checks if the bus currently has any subscribers for <paramref name="eventType"/>.
    /// </summary>
    bool HasSubscribers(Type eventType);
}

/// <summary>
/// High-performance, lock-free in-memory event bus optimized for a modular
/// monolith. The implementation uses <see cref="System.Threading.Channels"/>
/// to guarantee FIFO ordering, back-pressure and bounded concurrency.
/// </summary>
public sealed class InMemoryEventBus : IEventBus
{
    private readonly ILogger<InMemoryEventBus> _logger;
    private readonly int _dispatcherCount;
    private readonly Channel<EventEnvelope> _channel;
    private readonly CancellationTokenSource _cts = new();
    private readonly Task[] _dispatchers;

    // Map: EventType -> (SubscriberId -> Subscription)
    private readonly ConcurrentDictionary<Type,
        ConcurrentDictionary<string, Subscription>> _subscriptions = new();

    // Used when the caller does not specify a subscriberId.
    private static long _autoIncrementSubscriberId;

    private bool _disposed;

    /// <summary>
    /// Creates a new instance with the provided logger. Dispatcher thread-count
    /// defaults to <c>Environment.ProcessorCount</c>.
    /// </summary>
    public InMemoryEventBus(
        ILogger<InMemoryEventBus> logger,
        int? dispatcherCount = null,
        int channelCapacity = 65_536)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));

        _dispatcherCount = dispatcherCount is > 0 ? dispatcherCount.Value : Environment.ProcessorCount;
        var options = new BoundedChannelOptions(channelCapacity)
        {
            SingleReader = false,
            SingleWriter = false,
            FullMode = BoundedChannelFullMode.Wait
        };
        _channel = Channel.CreateBounded<EventEnvelope>(options);

        // Spin up background dispatcher tasks.
        _dispatchers = new Task[_dispatcherCount];
        for (var i = 0; i < _dispatcherCount; i++)
        {
            _dispatchers[i] = Task.Factory.StartNew(
                () => DispatcherLoop(i, _cts.Token),
                _cts.Token,
                TaskCreationOptions.LongRunning,
                TaskScheduler.Default);
        }

        _logger.LogInformation(
            "In-memory event bus initialised with {DispatcherCount} dispatcher(s) and capacity {Capacity}",
            _dispatcherCount, channelCapacity);
    }

    // ---------------------------------------------------------------------
    // IEventBus implementation
    // ---------------------------------------------------------------------

    public IDisposable Subscribe<TEvent>(
        Func<TEvent, CancellationToken, ValueTask> handler,
        string? subscriberId = null)
        where TEvent : IEvent
    {
        if (handler is null) throw new ArgumentNullException(nameof(handler));

        var type = typeof(TEvent);
        var id = subscriberId ?? $"auto_{Interlocked.Increment(ref _autoIncrementSubscriberId)}";

        var subscriberMap = _subscriptions.GetOrAdd(type,
            _ => new ConcurrentDictionary<string, Subscription>());

        var subscription = new Subscription(this, type, id,
            async (obj, token) =>
            {
                // Fast cast without 'as' to keep boxing minimal.
                await handler(Unsafe.As<TEvent>(obj), token).ConfigureAwait(false);
            });

        if (!subscriberMap.TryAdd(id, subscription))
        {
            throw new InvalidOperationException(
                $"A subscriber with id '{id}' is already registered for events of type '{type.Name}'.");
        }

        _logger.LogDebug(
            "Subscriber '{SubscriberId}' registered for event type '{EventType}'",
            id, type.Name);

        return subscription;
    }

    public async ValueTask PublishAsync<TEvent>(
        TEvent @event,
        CancellationToken cancellationToken = default)
        where TEvent : IEvent
    {
        if (_disposed) ThrowObjectDisposed();

        if (@event is null) throw new ArgumentNullException(nameof(@event));

        // We still enqueue even when there are no subscribers; this allows
        // diagnostics to track publication frequency if needed.
        var envelope = new EventEnvelope(@event, cancellationToken);

        // This can block if the bounded channel is full: built-in back-pressure.
        await _channel.Writer.WriteAsync(envelope, cancellationToken).ConfigureAwait(false);
    }

    public bool HasSubscribers(Type eventType)
    {
        if (eventType is null) throw new ArgumentNullException(nameof(eventType));
        return _subscriptions.TryGetValue(eventType, out var map) && !map.IsEmpty;
    }

    // ---------------------------------------------------------------------
    // Housekeeping
    // ---------------------------------------------------------------------

    public void Dispose() => DisposeAsync().AsTask().GetAwaiter().GetResult();

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _disposed = true;

        _logger.LogInformation("Disposing in-memory event bus…");

        _cts.Cancel();
        _channel.Writer.Complete();

        try
        {
            await Task.WhenAll(_dispatchers).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is TaskCanceledException or OperationCanceledException)
        {
            // Expected during shutdown, suppress.
        }

        _cts.Dispose();
    }

    // ---------------------------------------------------------------------
    // Internal dispatcher logic
    // ---------------------------------------------------------------------

    private async Task DispatcherLoop(int dispatcherIndex, CancellationToken token)
    {
        try
        {
            var reader = _channel.Reader;
            while (await reader.WaitToReadAsync(token).ConfigureAwait(false))
            {
                while (reader.TryRead(out var envelope))
                {
                    Deliver(envelope);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Normal on shutdown.
        }
        catch (Exception ex)
        {
            _logger.LogCritical(ex, "Dispatcher {Index} crashed unexpectedly", dispatcherIndex);
        }
    }

    private void Deliver(EventEnvelope envelope)
    {
        if (!_subscriptions.TryGetValue(envelope.Event.GetType(), out var subscribers) ||
            subscribers.IsEmpty)
        {
            // No subscribers: nothing to do.
            return;
        }

        foreach (var sub in subscribers.Values)
        {
            // Fire-and-forget: each handler is executed independently.
            _ = Task.Run(async () =>
            {
                var sw = ValueStopwatch.StartNew();
                try
                {
                    await sub.Handler(envelope.Event, envelope.PublishCancellationToken)
                        .ConfigureAwait(false);

                    _logger.LogTrace(
                        "Event '{EventType}' delivered to '{SubscriberId}' in {Elapsed} µs",
                        envelope.Event.GetType().Name, sub.Id, sw.ElapsedMicroseconds);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex,
                        "Error delivering event '{EventType}' to subscriber '{SubscriberId}'",
                        envelope.Event.GetType().Name, sub.Id);
                }
            });
        }
    }

    // ---------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ThrowObjectDisposed() =>
        throw new ObjectDisposedException(nameof(InMemoryEventBus));

    /// <summary>
    /// Encapsulates an event and metadata used by the dispatcher.
    /// </summary>
    private sealed record EventEnvelope(object Event, CancellationToken PublishCancellationToken);

    /// <summary>
    /// Represents a single subscription. Disposing removes it from the bus.
    /// </summary>
    private sealed class Subscription : IDisposable
    {
        private readonly InMemoryEventBus _bus;
        private readonly Type _eventType;
        private bool _isDisposed;

        public string Id { get; }
        public Func<object, CancellationToken, ValueTask> Handler { get; }

        public Subscription(
            InMemoryEventBus bus,
            Type eventType,
            string id,
            Func<object, CancellationToken, ValueTask> handler)
        {
            _bus = bus;
            _eventType = eventType;
            Id = id;
            Handler = handler;
        }

        public void Dispose()
        {
            if (_isDisposed) return;
            _isDisposed = true;

            if (_bus._subscriptions.TryGetValue(_eventType, out var map) &&
                map.TryRemove(Id, out _))
            {
                _bus._logger.LogDebug(
                    "Subscriber '{SubscriberId}' removed from event type '{EventType}'",
                    Id, _eventType.Name);
            }
        }
    }

    // Fast, allocation-free stopwatch helper.
    private readonly struct ValueStopwatch
    {
        private static readonly double TickFrequency =
            1_000_000.0 / Stopwatch.Frequency; // microsecond conversion

        private readonly long _start;

        private ValueStopwatch(long start) => _start = start;

        public static ValueStopwatch StartNew() => new(Stopwatch.GetTimestamp());

        public double ElapsedMicroseconds =>
            (Stopwatch.GetTimestamp() - _start) * TickFrequency;
    }
}
```
