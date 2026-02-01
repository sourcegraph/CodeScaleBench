```csharp
// File: PaletteStream-ETL-Canvas/docs/architecture/data-flow-and-events.md
// NOTE:  Although the physical file lives in the `docs/` folder, it intentionally
//        contains an executable, production-grade test-suite that documents – in code –
//        the expected data-flow & event contracts of the PaletteStream ETL Canvas.
//        The tests serve as living documentation and regression-safety for the
//        Pipeline / Observer interaction model.
//
// Compile-time dependencies (nuget):
//   - xunit                 (unit-test framework)
//   - FluentAssertions      (expressive assertions)
//   - Moq                   (test doubles)
//
// -----------------------------------------------------------------------------
//                     ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
//                     ┃  DATA-FLOW & EVENTS TEST SUITE ┃
//                     ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
// -----------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using Xunit;

namespace PaletteStream.ETL.Canvas.Tests.Architecture
{
    #region ‑-[ Domain Contracts (abridged) ]--

    /// <summary>
    /// A single unit of data transported through the ETL pipeline
    /// </summary>
    public sealed record DataPigment(Guid Id, IReadOnlyDictionary<string, object> Payload);

    /// <summary>
    /// Marker interface for pipeline stages.
    /// </summary>
    public interface IPipelineStage
    {
        Task<DataPigment> ProcessAsync(DataPigment pigment, CancellationToken ct = default);
    }

    /// <summary>
    /// Each stage can publish domain events via the event bus.
    /// The functional code base provides an implementation – for the tests we create a lightweight stub.
    /// </summary>
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event) where TEvent : IPipelineEvent;
        void Subscribe<TEvent>(Action<TEvent> handler) where TEvent : IPipelineEvent;
    }

    /// <summary>
    /// Root marker for all pipeline-related events.
    /// </summary>
    public interface IPipelineEvent
    {
        Guid PigmentId { get; }
        DateTimeOffset Timestamp { get; }
    }

    internal record IngestedEvent(Guid PigmentId, DateTimeOffset Timestamp)  : IPipelineEvent;
    internal record TransformedEvent(Guid PigmentId, DateTimeOffset Timestamp) : IPipelineEvent;
    internal record LoadedEvent(Guid PigmentId, DateTimeOffset Timestamp) : IPipelineEvent;
    internal record ErrorEvent(Guid PigmentId, DateTimeOffset Timestamp, string Stage, Exception Error) : IPipelineEvent;

    #endregion

    #region ‑-[ Infrastructure Test Doubles ]--

    /// <summary>
    ///  In-memory event-bus used only for tests. Thread-safe, minimalistic and deterministic.
    /// </summary>
    internal sealed class InMemoryEventBus : IEventBus
    {
        private readonly ConcurrentDictionary<Type, List<Delegate>> _subscriptions = new();

        public void Publish<TEvent>(TEvent @event) where TEvent : IPipelineEvent
        {
            if (_subscriptions.TryGetValue(typeof(TEvent), out var handlers))
            {
                // Clone to avoid concurrency issues while enumerating.
                var snapshot = handlers.ToArray();
                foreach (var handler in snapshot.Cast<Action<TEvent>>())
                {
                    handler(@event);
                }
            }
        }

        public void Subscribe<TEvent>(Action<TEvent> handler) where TEvent : IPipelineEvent
        {
            _subscriptions.AddOrUpdate(
                typeof(TEvent),
                _ => new List<Delegate> { handler },
                (_, list) =>
                {
                    list.Add(handler);
                    return list;
                });
        }
    }

    /// <summary>
    ///  Simple pipeline orchestrator that executes stages sequentially and surfaces events via IEventBus.
    /// </summary>
    internal sealed class EtlPipeline
    {
        private readonly IEnumerable<IPipelineStage> _stages;
        private readonly IEventBus _eventBus;

        public EtlPipeline(IEnumerable<IPipelineStage> stages, IEventBus eventBus)
        {
            _stages   = stages ?? throw new ArgumentNullException(nameof(stages));
            _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
        }

        public async Task<DataPigment> ExecuteAsync(DataPigment pigment, CancellationToken ct = default)
        {
            _eventBus.Publish(new IngestedEvent(pigment.Id, DateTimeOffset.UtcNow));

            var current = pigment;
            foreach (var stage in _stages)
            {
                try
                {
                    current = await stage.ProcessAsync(current, ct).ConfigureAwait(false);
                    _eventBus.Publish(new TransformedEvent(current.Id, DateTimeOffset.UtcNow));
                }
                catch (Exception ex)
                {
                    _eventBus.Publish(new ErrorEvent(current.Id, DateTimeOffset.UtcNow, stage.GetType().Name, ex));
                    throw; // let the orchestrator bubble the exception so the caller can react.
                }
            }

            _eventBus.Publish(new LoadedEvent(current.Id, DateTimeOffset.UtcNow));
            return current;
        }
    }

    #endregion

    #region ‑-[ Tests ]--

    public sealed class DataFlowAndEventContractTests
    {
        private static DataPigment GeneratePigment() =>
            new(Guid.NewGuid(), new Dictionary<string, object> { ["input"] = "raw-value" });

        [Fact(DisplayName = "Pipeline publishes Ingested, a Transformed per stage, then Loaded events in order")]
        public async Task PipelinePublishesKeyEventsInExpectedOrder()
        {
            // Arrange ----------------------------------------------------------
            var bus = new InMemoryEventBus();
            var observedEvents = new List<IPipelineEvent>();

            bus.Subscribe<IngestedEvent>(e   => observedEvents.Add(e));
            bus.Subscribe<TransformedEvent>(e => observedEvents.Add(e));
            bus.Subscribe<LoadedEvent>(e      => observedEvents.Add(e));

            // Two trivial mock stages
            var stage1 = new Mock<IPipelineStage>();
            var stage2 = new Mock<IPipelineStage>();

            stage1.Setup(s => s.ProcessAsync(It.IsAny<DataPigment>(), It.IsAny<CancellationToken>()))
                  .ReturnsAsync((DataPigment p, CancellationToken _) =>
                      p with { Payload = p.Payload.Append("stage1", "ok") });

            stage2.Setup(s => s.ProcessAsync(It.IsAny<DataPigment>(), It.IsAny<CancellationToken>()))
                  .ReturnsAsync((DataPigment p, CancellationToken _) =>
                      p with { Payload = p.Payload.Append("stage2", "ok") });

            var pipeline = new EtlPipeline(new[] { stage1.Object, stage2.Object }, bus);

            // Act --------------------------------------------------------------
            var pigment = GeneratePigment();
            await pipeline.ExecuteAsync(pigment);

            // Assert -----------------------------------------------------------
            observedEvents.Should().HaveCount(1 /*ingested*/ + 2 /*transforms*/ + 1 /*loaded*/);

            observedEvents.Select(e => e switch
            {
                IngestedEvent   => "Ingested",
                TransformedEvent=> "Transformed",
                LoadedEvent     => "Loaded",
                _               => "Unknown"
            })
            .Should()
            .ContainInOrder("Ingested", "Transformed", "Transformed", "Loaded");
        }

        [Fact(DisplayName = "Subscribers receive each event exactly once even under concurrent load")]
        public async Task EventBusDispatchesToAllSubscribersExactlyOnce()
        {
            // Arrange ----------------------------------------------------------
            var bus = new InMemoryEventBus();

            var ingestedCount  = 0;
            var transformedCount = 0;
            var loadedCount    = 0;

            bus.Subscribe<IngestedEvent>(_ => Interlocked.Increment(ref ingestedCount));
            bus.Subscribe<TransformedEvent>(_ => Interlocked.Increment(ref transformedCount));
            bus.Subscribe<LoadedEvent>(_ => Interlocked.Increment(ref loadedCount));

            var stage = new Mock<IPipelineStage>();
            stage.Setup(s => s.ProcessAsync(It.IsAny<DataPigment>(), It.IsAny<CancellationToken>()))
                 .ReturnsAsync((DataPigment p, CancellationToken _) => p);

            var pipeline = new EtlPipeline(Enumerable.Repeat(stage.Object, 3), bus);

            // Act --------------------------------------------------------------
            const int parallelRuns = 25;
            await Task.WhenAll(Enumerable.Range(0, parallelRuns)
                .Select(_ => pipeline.ExecuteAsync(GeneratePigment())));

            // Assert -----------------------------------------------------------
            ingestedCount.Should().Be(parallelRuns);
            transformedCount.Should().Be(parallelRuns * 3);
            loadedCount.Should().Be(parallelRuns);
        }

        [Fact(DisplayName = "Error in a stage raises ErrorEvent and propagates exception")]
        public async Task PipelinePublishesErrorEventWhenStageFails()
        {
            // Arrange ----------------------------------------------------------
            var bus = new InMemoryEventBus();
            var errorEvents = new ConcurrentBag<ErrorEvent>();
            bus.Subscribe<ErrorEvent>(errorEvents.Add);

            var failingStage = new Mock<IPipelineStage>();
            failingStage.Setup(s => s.ProcessAsync(It.IsAny<DataPigment>(), It.IsAny<CancellationToken>()))
                        .ThrowsAsync(new InvalidOperationException("Boom"));

            var pipeline = new EtlPipeline(new[] { failingStage.Object }, bus);

            // Act --------------------------------------------------------------
            Func<Task> act = () => pipeline.ExecuteAsync(GeneratePigment());

            // Assert -----------------------------------------------------------
            await act.Should().ThrowAsync<InvalidOperationException>()
                     .WithMessage("Boom");

            errorEvents.Should().HaveCount(1);
            var evt = errorEvents.Single();
            evt.Stage.Should().Be(failingStage.Object.GetType().Name);
            evt.Error.Should().BeOfType<InvalidOperationException>();
        }
    }

    #endregion
}

#region ‑-[ Extension Helpers ]--

internal static class DictionaryExtensions
{
    public static IReadOnlyDictionary<string, object> Append(this IReadOnlyDictionary<string, object> source,
                                                             string key,
                                                             object value)
    {
        var clone = source.ToDictionary(kvp => kvp.Key, kvp => kvp.Value);
        clone[key] = value;
        return clone;
    }
}

#endregion
```