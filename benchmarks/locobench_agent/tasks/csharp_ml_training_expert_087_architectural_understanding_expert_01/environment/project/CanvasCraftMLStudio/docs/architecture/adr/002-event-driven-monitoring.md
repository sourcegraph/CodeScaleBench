```markdown
<!--
File: CanvasCraftMLStudio/docs/architecture/adr/002-event-driven-monitoring.md
This Architecture Decision Record (ADR) captures why CanvasCraft ML Studio
adopted an event-driven, reactive monitoring subsystem.
-->

# 002 — Event-Driven Monitoring

* Status: **Accepted**
* Date: 2024-06-11
* Deciders: Core Platform Team  
* Supersedes: *none*  
* Tags: monitoring, observer-pattern, event-bus, mlops, csharp

---

## 1. Context  

CanvasCraft ML Studio serves creative professionals who demand instant
feedback when a model’s aesthetic *or* quantitative performance drifts.
Traditional, pull-based dashboards proved too latent for interactive
workflows. We therefore require:

* Near-real-time detection of data and model drift  
* Reactive alerting to UI canvases, Slack, and WebHooks  
* Loose coupling between producers (model training, feature store) and
  consumers (dashboards, alerting services, auto-retrain jobs)  
* A pluggable architecture that works in single-process testbeds **and**
  distributed production clusters  

These constraints map naturally to an **Event-Driven Architecture (EDA)**
implemented via the **Observer Pattern**.

---

## 2. Decision  

We will implement a lightweight, in-process **Event Bus** backed by
`System.Threading.Channels` for default deployments, with adapters that
proxy to external brokers (Kafka / Azure Event Hubs) for scale-out
environments. All monitoring signals will be published as immutable
domain events implementing `IModelEvent`. Down-stream subscribers may
react synchronously or asynchronously (e.g., stream to the dashboard,
write to the Feature Store, or trigger auto-retraining).

---

## 3. Consequences  

* + Producers/consumers remain oblivious of each other  
* + Local unit tests stay fast by using the in-memory bus  
* + Scaling to cloud brokers is a deployment concern, not a code change  
* − Requires disciplined event-schema versioning  
* − Potential complexity in distributed tracing (mitigated by
  correlation IDs baked into `IModelEvent`)  

---

## 4. Reference Implementation (C#)

```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;

namespace CanvasCraft.MLStudio.Monitoring
{
    /// <summary>
    /// Base contract for all domain events emitted by the ML Studio.
    /// </summary>
    public interface IModelEvent
    {
        DateTimeOffset OccurredOn { get; }
        Guid CorrelationId { get; }
    }

    /// <summary>
    /// Example event raised when feature or prediction drift is detected.
    /// </summary>
    public sealed record DriftDetectedEvent(
        string ModelName,
        double DriftScore,
        string DriftType,
        DateTimeOffset OccurredOn,
        Guid CorrelationId) : IModelEvent;

    /// <summary>
    /// Thread-safe, in-memory event bus using <see cref="Channel{T}"/> for high throughput.
    /// An external adapter can bridge messages to Kafka, RabbitMQ, etc.
    /// </summary>
    public class InMemoryEventBus : IEventBus, IDisposable
    {
        private readonly Channel<IModelEvent> _channel;
        private readonly ConcurrentDictionary<Type, List<Func<IModelEvent, ValueTask>>> _subscriptions;
        private readonly CancellationTokenSource _cts = new();
        private readonly Task _dispatcherTask;

        public InMemoryEventBus(int boundedCapacity = 10_000)
        {
            _channel = Channel.CreateBounded<IModelEvent>(new BoundedChannelOptions(boundedCapacity)
            {
                FullMode = BoundedChannelFullMode.Wait,
                SingleReader = true,
                SingleWriter = false
            });
            _subscriptions = new();
            _dispatcherTask = Task.Run(DispatchLoopAsync, _cts.Token);
        }

        public async ValueTask PublishAsync(IModelEvent @event, CancellationToken ct = default)
        {
            ArgumentNullException.ThrowIfNull(@event);
            ct.ThrowIfCancellationRequested();
            await _channel.Writer.WriteAsync(@event, ct).ConfigureAwait(false);
        }

        public void Subscribe<TEvent>(Func<TEvent, ValueTask> handler) where TEvent : IModelEvent
        {
            ArgumentNullException.ThrowIfNull(handler);
            var list = _subscriptions.GetOrAdd(typeof(TEvent), _ => new());
            ValueTask Wrapper(IModelEvent e) => handler((TEvent)e);
            list.Add(Wrapper);
        }

        public void Dispose()
        {
            _cts.Cancel();
            _channel.Writer.Complete();
            try { _dispatcherTask.Wait(TimeSpan.FromSeconds(5)); }
            catch (AggregateException) { /* swallow */ }
            _cts.Dispose();
        }

        // Core dispatcher: fan-out each event to its type-based subscribers.
        private async Task DispatchLoopAsync()
        {
            try
            {
                while (await _channel.Reader.WaitToReadAsync(_cts.Token).ConfigureAwait(false))
                {
                    while (_channel.Reader.TryRead(out var evt))
                    {
                        if (_subscriptions.TryGetValue(evt.GetType(), out var handlers))
                        {
                            foreach (var h in handlers)
                            {
                                _ = SafeInvokeAsync(h, evt, _cts.Token);
                            }
                        }
                    }
                }
            }
            catch (OperationCanceledException) { /* graceful shutdown */ }
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static async Task SafeInvokeAsync(
            Func<IModelEvent, ValueTask> handler,
            IModelEvent evt,
            CancellationToken ct)
        {
            try { await handler.Invoke(evt); }
            catch (Exception ex)
            {
                // TODO: emit a MonitoringExceptionEvent or log via ILogger
                Console.Error.WriteLine($"Handler failure: {ex}");
            }
        }
    }

    /// <summary>
    /// Abstraction to decouple components from the concrete bus implementation.
    /// </summary>
    public interface IEventBus
    {
        ValueTask PublishAsync(IModelEvent @event, CancellationToken ct = default);
        void Subscribe<TEvent>(Func<TEvent, ValueTask> handler) where TEvent : IModelEvent;
    }

    /// <summary>
    /// Service that watches for drift events and triggers auto-retraining.
    /// </summary>
    public sealed class AutoRetrainService
    {
        private readonly IEventBus _bus;

        public AutoRetrainService(IEventBus bus)
        {
            _bus = bus;
            _bus.Subscribe<DriftDetectedEvent>(OnDriftAsync);
        }

        private async ValueTask OnDriftAsync(DriftDetectedEvent evt)
        {
            Console.WriteLine(
                $"[AutoRetrain] {evt.ModelName} drifted ({evt.DriftType}:{evt.DriftScore:F2}). " +
                $"CorrelationId={evt.CorrelationId}");
            // TODO: enqueue retraining pipeline job via orchestrator.
            await Task.CompletedTask;
        }
    }

    /// <summary>
    /// Example usage in composition root.
    /// </summary>
    public static class MonitoringBootstrap
    {
        public static async Task DemonstrateAsync()
        {
            using var bus = new InMemoryEventBus();
            var autoretrain = new AutoRetrainService(bus);

            var driftEvent = new DriftDetectedEvent(
                ModelName: "StyleGAN-Canvas-v3",
                DriftScore: 0.42,
                DriftType: "KL Divergence",
                OccurredOn: DateTimeOffset.UtcNow,
                CorrelationId: Guid.NewGuid());

            await bus.PublishAsync(driftEvent);
            await Task.Delay(500); // Give dispatcher time to deliver
        }
    }
}
```

---

## 5. Roll-Out Plan  

1. Merge reference implementation behind a feature flag  
2. Instrument existing training jobs to publish `DriftDetectedEvent`,
   `MetricThresholdBreachedEvent`, etc.  
3. Incrementally migrate legacy polling dashboards to consume events  
4. Enable Kafka adapter in production clusters for horizontal scale  

---

## 6. Alternatives Considered  

* **Polling**: Rejected due to latency and tight coupling  
* **Direct Service Calls**: Violates Open/Closed principle as new
  consumers would require producer changes  
* **Third-party APM only**: Complementary but does not provide
  domain-specific semantics (e.g., aesthetic drift)  

---

## 7. References  

* E. Gamma et al. *Design Patterns* — Observer  
* M. Fowler — *Event Sourcing*  
* Krizhevsky, *et al.* — *Imagenet Classification with Deep Convolutional
  Neural Networks* (early drift discussion)
```