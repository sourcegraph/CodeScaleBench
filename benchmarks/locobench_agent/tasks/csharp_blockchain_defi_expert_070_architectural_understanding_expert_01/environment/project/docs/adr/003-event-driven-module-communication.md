```markdown
# ADR-003: Event-Driven Module Communication
UtilityChain Core Suite  
Created: 2024-05-26  
Status: **Accepted**

---

## 1. Context
UtilityChain is delivered as a single, self-contained .NET 8 executable.  
Although a monolith, it is _modular_: **Staking**, **Consensus**, **Governance**, **Token/NFT Tooling**, and the **Smart-Contract Engine** are developed as pluggable components that must interoperate without compile-time coupling.

Key forces:

| Force | Explanation |
|-------|-------------|
| Runtime Efficiency | Blockchain nodes must achieve deterministic, micro-second latency. |
| Hot-swappability  | New consensus engines, staking algorithms, or NFT standards may be introduced without shutting down a node. |
| Isolation         | A failure in one module (e.g., a buggy smart-contract) must not crash the entire node. |
| Observability     | Administrators need fine-grained telemetry (audit, tracing, metrics) for each module. |

Traditional approaches (direct method calls, REST gRPC, message brokers) either introduce undesirable coupling or unacceptable latency.  
Therefore, an **in-process event bus** (mediator) will be the spine of module communication.

---

## 2. Decision
1. Adopt a lightweight, in-memory **Domain Event Bus** that follows the _Mediator_ and _Observer_ patterns.  
2. Events are C# records implementing the `IApplicationEvent` marker interface to ensure immutability and serialization safety.  
3. Modules interact exclusively through events and **Application Commands**; no module holds a hard reference to another.  
4. Subscriptions are registered at runtime through a **Fluent Subscription API** allowing hot-plug and graceful unloading.  
5. The bus supports:
   • Synchronous “fire-and-forget” events  
   • Asynchronous events with `Task` pipelines  
   • Cancellation tokens for long-running work  
   • Weak references to prevent memory leaks  
6. Observability is baked in via the `IEventTracer` abstraction; a default OpenTelemetry implementation ships with the core suite.  

---

## 3. Consequences
✔  Runtime coupling is reduced to the event contract; modules evolve independently.  
✔  Zero-copy, in-process dispatch keeps latency in the sub-millisecond range.  
✔  New modules may be loaded via reflection or MEF without recompilation.  
✖  Debugging becomes harder because control-flow is no longer explicit in the call-stack.  
✖  Misuse of long-running handlers can still block the thread if not awaited or scheduled correctly.  

---

## 4. Implementation Sketch (Production-Quality C#)

```csharp
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Runtime.CompilerServices;

namespace UtilityChain.Core.Eventing;

/// <summary>
/// Marker interface for immutable domain events that flow through the in-process event bus.
/// </summary>
public interface IApplicationEvent { }

/// <summary>
/// A canonical contract for consuming <typeparamref name="TEvent" /> messages.
/// Handlers should be stateless and idempotent.  
/// </summary>
public interface IEventHandler<in TEvent> where TEvent : IApplicationEvent
{
    /// <summary>Handle an application event.</summary>
    ValueTask HandleAsync(TEvent @event, CancellationToken ct);
}

/// <summary>
/// A handle that allows the subscriber to dispose/unsubscribe at runtime.
/// </summary>
public sealed class Subscription : IDisposable
{
    private readonly Action _dispose;
    private int _disposed;

    internal Subscription(Action dispose) => _dispose = dispose;

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
            _dispose();
    }
}

/// <summary>
/// Core implementation of the event bus.  It is intentionally lightweight, allocation-free for the hot-path,
/// and free of third-party dependencies so that it can operate in AOT contexts.
/// </summary>
public sealed class EventBus : IEventTracer
{
    // Handlers are stored in a thread-safe dictionary keyed by event type.
    private readonly ConcurrentDictionary<Type, ConcurrentBag<WeakReference<object>>> _handlers = new();

    // External tracer for observability; can be swapped for OpenTelemetry/Jaeger/etc.
    private readonly IEventTracer _tracer;

    public EventBus(IEventTracer? tracer = null)
    {
        _tracer = tracer ?? this; // Fallback to self-logging.
    }

    #region Publish

    /// <summary>
    /// Publish an event in a fire-and-forget manner.
    /// </summary>
    public void Publish<TEvent>(TEvent @event) where TEvent : IApplicationEvent
        => PublishAsync(@event, CancellationToken.None).GetAwaiter().GetResult();

    /// <summary>
    /// Publish an event asynchronously.  Handlers are awaited _concurrently_.
    /// </summary>
    public async ValueTask PublishAsync<TEvent>(
        TEvent @event,
        CancellationToken ct = default) where TEvent : IApplicationEvent
    {
        if (_handlers.TryGetValue(typeof(TEvent), out var list))
        {
            var tasks = new List<ValueTask>(list.Count);
            foreach (var weak in list)
            {
                if (weak.TryGetTarget(out var target) &&
                    target is IEventHandler<TEvent> handler)
                {
                    tasks.Add(InvokeHandler(handler, @event, ct));
                }
            }
            await ValueTask.WhenAll(tasks);
        }
        else
        {
            _tracer.TraceNoHandler(@event);
        }
    }

    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    private async ValueTask InvokeHandler<TEvent>(
        IEventHandler<TEvent> handler,
        TEvent @event,
        CancellationToken ct) where TEvent : IApplicationEvent
    {
        var sw = Stopwatch.StartNew();
        try
        {
            await handler.HandleAsync(@event, ct).ConfigureAwait(false);
            _tracer.TraceSuccess(@event, handler, sw.Elapsed);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _tracer.TraceCancelled(@event, handler, sw.Elapsed);
            throw;
        }
        catch (Exception ex)
        {
            _tracer.TraceFailure(@event, handler, sw.Elapsed, ex);
            throw;
        }
    }

    #endregion

    #region Subscribe

    /// <summary>
    /// Subscribe an <see cref="IEventHandler{TEvent}" /> instance to the bus.
    /// Returns a <see cref="Subscription" /> that can be disposed to unsubscribe.
    /// </summary>
    public Subscription Subscribe<TEvent>(IEventHandler<TEvent> handler)
        where TEvent : IApplicationEvent
    {
        var bag = _handlers.GetOrAdd(typeof(TEvent), _ => new ConcurrentBag<WeakReference<object>>());
        var weak = new WeakReference<object>(handler);
        bag.Add(weak);

        return new Subscription(() => RemoveHandler(typeof(TEvent), weak));
    }

    private void RemoveHandler(Type type, WeakReference<object> weak)
    {
        if (_handlers.TryGetValue(type, out var list))
        {
            // ConcurrentBag does not support removal; rebuild without the disposed handler.
            var newBag = new ConcurrentBag<WeakReference<object>>(list.Where(wr => wr != weak));
            _handlers[type] = newBag;
        }
    }

    #endregion

    #region Self-Trace (No-op)

    void IEventTracer.TraceNoHandler(IApplicationEvent ev) { }
    void IEventTracer.TraceSuccess(IApplicationEvent ev, object handler, TimeSpan dur) { }
    void IEventTracer.TraceCancelled(IApplicationEvent ev, object handler, TimeSpan dur) { }
    void IEventTracer.TraceFailure(IApplicationEvent ev, object handler, TimeSpan dur, Exception ex) { }

    #endregion
}

/// <summary>
/// Defines tracing callbacks for diagnostics.  Implementations should be side-effect-free.
/// </summary>
public interface IEventTracer
{
    void TraceNoHandler(IApplicationEvent ev);
    void TraceSuccess(IApplicationEvent ev, object handler, TimeSpan dur);
    void TraceCancelled(IApplicationEvent ev, object handler, TimeSpan dur);
    void TraceFailure(IApplicationEvent ev, object handler, TimeSpan dur, Exception ex);
}
```

### Usage Example

```csharp
// 1. Create a concrete event
public sealed record TokensMinted(Guid TokenId, decimal Amount, Address Owner) : IApplicationEvent;

// 2. Implement a handler that reacts to the event
public sealed class LedgerProjection : IEventHandler<TokensMinted>
{
    private readonly ILedgerRepository _repo;
    public LedgerProjection(ILedgerRepository repo) => _repo = repo;

    public async ValueTask HandleAsync(TokensMinted e, CancellationToken ct)
    {
        var entry = new LedgerEntry(e.TokenId, e.Owner, e.Amount, LedgerOp.Mint);
        await _repo.AddAsync(entry, ct);
    }
}

// 3. Wire up in the composition root
var bus = new EventBus(new OpenTelemetryTracer());
var projection = new LedgerProjection(repo);
using var sub = bus.Subscribe(projection);

// 4. Somewhere in the Token module…
await bus.PublishAsync(new TokensMinted(tokenId, 250, caller.Address), ct);
```

---

## 5. Future Work
• Integrate a deterministic, priority-aware scheduler so that consensus-critical events pre-empt UI telemetry.  
• Provide Roslyn source generators for boiler-plate handler registration.  
• Investigate out-of-process fallbacks (e.g., NATS, Kafka) for horizontally scaled, multi-process deployments.

---
© 2024 UtilityChain Contributors – Released under the MIT License
```