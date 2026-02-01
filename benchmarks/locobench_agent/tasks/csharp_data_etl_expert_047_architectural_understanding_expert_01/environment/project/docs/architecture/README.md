```csharp
// File: PaletteStream-ETL-Canvas/docs/architecture/README.md (treated as test file)
//
// NOTE: The project build will treat *.md files in the `docs/` folder as embedded-unit-tests
//       through “Markdown-Test-Discovery” (custom MSBuild target).  This allows the
//       architecture documentation to stay executable and always green.
//
//       Run with: dotnet test ‑c Release

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Xunit;
using FluentAssertions;
using Moq;

namespace PaletteStream.ETL.Tests.Architecture
{
    #region Domain primitives (light-weight test doubles)

    /// <summary>
    /// Lightweight immutable “pigment” that flows through the pipeline.
    /// </summary>
    internal sealed record DataPigment(Guid Id, IDictionary<string, object> Payload);

    /// <summary>
    /// The Strategy abstraction used by the pipeline.
    /// </summary>
    internal interface ITransformationStrategy
    {
        /// <summary>Executes the transformation on a pigment.</summary>
        /// <remarks>
        /// All strategies MUST be pure and return a new instance to guarantee immutability.
        /// </remarks>
        DataPigment Execute(DataPigment pigment);
    }

    /// <summary>An observer that reacts when a pigment finishes a transformation stage.</summary>
    internal interface ITransformationObserver
    {
        void OnTransformed(DataPigment pigment, ITransformationStrategy strategy);
        void OnError(DataPigment pigment, Exception ex);
    }

    /// <summary>
    /// Exception thrown by <see cref="EtlPipeline"/> when any stage fails.
    /// </summary>
    internal sealed class PipelineException : Exception
    {
        public PipelineException(string? message, Exception? inner)
            : base(message, inner)
        { }
    }

    #endregion

    #region Concrete transformation strategies

    internal sealed class AggregationStrategy : ITransformationStrategy
    {
        public DataPigment Execute(DataPigment pigment)
        {
            var aggregated = pigment.Payload
                                    .Where(kv => kv.Value is int or double or decimal)
                                    .Sum(kv => Convert.ToDecimal(kv.Value));

            var newPayload = new Dictionary<string, object>(pigment.Payload)
            {
                ["aggregated_value"] = aggregated
            };

            return pigment with { Payload = newPayload };
        }
    }

    internal sealed class AnonymizationStrategy : ITransformationStrategy
    {
        public DataPigment Execute(DataPigment pigment)
        {
            var newPayload = pigment.Payload.ToDictionary(
                kv => kv.Key,
                kv => kv.Key.Contains("email", StringComparison.OrdinalIgnoreCase)
                        ? "***@redacted.com"
                        : kv.Value);

            return pigment with { Payload = newPayload };
        }
    }

    internal sealed class FaultyStrategy : ITransformationStrategy
    {
        public DataPigment Execute(DataPigment pigment)
            => throw new InvalidOperationException("Simulated transformer failure");
    }

    #endregion

    #region ETL Pipeline implementation

    /// <summary>
    /// Highly simplified pipeline that applies a chain of strategies
    /// and notifies any registered observer.
    /// </summary>
    internal sealed class EtlPipeline
    {
        private readonly IEnumerable<ITransformationStrategy> _strategies;
        private readonly IEnumerable<ITransformationObserver> _observers;

        public EtlPipeline(IEnumerable<ITransformationStrategy> strategies,
                           IEnumerable<ITransformationObserver>? observers = null)
        {
            _strategies = strategies ?? throw new ArgumentNullException(nameof(strategies));
            _observers = observers ?? Array.Empty<ITransformationObserver>();
        }

        public DataPigment Execute(DataPigment pigment)
        {
            DataPigment current = pigment ?? throw new ArgumentNullException(nameof(pigment));

            foreach (var strategy in _strategies)
            {
                try
                {
                    current = strategy.Execute(current);
                    NotifyTransformed(current, strategy);
                }
                catch (Exception ex)
                {
                    NotifyError(current, ex);
                    throw new PipelineException(
                        $"Pipeline halted at '{strategy.GetType().Name}'.", ex);
                }
            }

            return current;
        }

        public Task<DataPigment> ExecuteAsync(DataPigment pigment,
                                              CancellationToken token = default)
            => Task.Run(() => Execute(pigment), token); // simple async wrapper

        private void NotifyTransformed(DataPigment pigment, ITransformationStrategy strategy)
        {
            foreach (var obs in _observers)
                obs.OnTransformed(pigment, strategy);
        }

        private void NotifyError(DataPigment pigment, Exception ex)
        {
            foreach (var obs in _observers)
                obs.OnError(pigment, ex);
        }
    }

    #endregion

    public class PipelineArchitectureSpecs
    {
        [Fact(DisplayName = "Pipeline executes all strategies in order")]
        public void Pipeline_Executes_All_Strategies_In_Order()
        {
            // Arrange
            var pigment = new DataPigment(Guid.NewGuid(), new Dictionary<string, object>
            {
                ["amount_1"] = 100,
                ["amount_2"] = 150,
                ["email"]    = "artist@example.com"
            });

            var pipeline = new EtlPipeline(new ITransformationStrategy[]
            {
                new AggregationStrategy(),
                new AnonymizationStrategy()
            });

            // Act
            var result = pipeline.Execute(pigment);

            // Assert
            result.Payload.Should().ContainKey("aggregated_value")
                  .WhichValue.Should().BeOfType<decimal>();

            result.Payload["email"].Should().Be("***@redacted.com");
        }

        [Fact(DisplayName = "Observers are notified at each successful stage")]
        public void Observer_Is_Notified_On_Transformation()
        {
            // Arrange
            var pigment = new DataPigment(Guid.NewGuid(), new Dictionary<string, object>());
            var observerMock = new Mock<ITransformationObserver>();
            var strategy = new AggregationStrategy();
            var pipeline = new EtlPipeline(new[] { strategy }, new[] { observerMock.Object });

            // Act
            pipeline.Execute(pigment);

            // Assert
            observerMock.Verify(o =>
                o.OnTransformed(It.IsAny<DataPigment>(), strategy), Times.Once);
            observerMock.VerifyNoOtherCalls();
        }

        [Fact(DisplayName = "Pipeline surfaces exceptions as PipelineException and notifies observers")]
        public void Pipeline_Transforms_Error_To_PipelineException()
        {
            // Arrange
            var pigment       = new DataPigment(Guid.NewGuid(), new Dictionary<string, object>());
            var observerMock  = new Mock<ITransformationObserver>();

            var pipeline = new EtlPipeline(
                new ITransformationStrategy[] { new FaultyStrategy() },
                new[] { observerMock.Object });

            // Act
            Action act = () => pipeline.Execute(pigment);

            // Assert
            act.Should().Throw<PipelineException>()
               .WithInnerException<InvalidOperationException>();

            observerMock.Verify(o =>
                o.OnError(It.IsAny<DataPigment>(), It.IsAny<Exception>()), Times.Once);
        }

        [Fact(DisplayName = "Async execution returns a completed pigment")]
        public async Task Pipeline_Supports_Async_Execution()
        {
            // Arrange
            var pigment = new DataPigment(Guid.NewGuid(), new Dictionary<string, object>());
            var pipeline = new EtlPipeline(new[] { new AggregationStrategy() });

            // Act
            var result = await pipeline.ExecuteAsync(pigment);

            // Assert
            result.Should().NotBeNull();
        }

        [Fact(DisplayName = "Parallel pipelines produce deterministic results")]
        public async Task Parallel_Pipelines_Are_Deterministic()
        {
            // Arrange
            var pigment = new DataPigment(Guid.NewGuid(), new Dictionary<string, object>
            {
                ["amount_1"] = 10,
                ["amount_2"] = 20
            });

            var strategies = new ITransformationStrategy[]
            {
                new AggregationStrategy(),
                new AnonymizationStrategy()
            };

            var pipeline1 = new EtlPipeline(strategies);
            var pipeline2 = new EtlPipeline(strategies);

            // Act
            var tasks = new[] {
                pipeline1.ExecuteAsync(pigment),
                pipeline2.ExecuteAsync(pigment)
            };

            var results = await Task.WhenAll(tasks);

            // Assert
            results[0].Should().BeEquivalentTo(results[1]);
        }
    }
}
```