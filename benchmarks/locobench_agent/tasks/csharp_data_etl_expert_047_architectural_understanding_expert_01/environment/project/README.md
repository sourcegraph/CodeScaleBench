```markdown
# PaletteStream ETL Canvas – Test Suite

This document contains an executable, production-quality **xUnit** test-suite that targets
the core building-blocks of the PaletteStream ETL Canvas.  
The tests demonstrate how an end-to-end **Pipeline / Strategy / Observer**
implementation is expected to behave and are self-contained so they can be compiled
and executed independently of the full solution.

> To run the tests:
>
> ```bash
> dotnet test
> ```

---

```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Moq;
using Xunit;

namespace PaletteStream.ETL.Tests
{
    #region Domain & Infrastructure (Stubs for Testing Purposes)

    /// <summary>
    ///     Immutable representation of a “data pigment” flowing through
    ///     the ETL palette.  In production this would wrap an Arrow
    ///     record batch or similar GPU-friendly structure.
    /// </summary>
    public sealed record ColorPigment(string Shade,
                                      IDictionary<string, object> Metadata)
    {
        public ColorPigment WithShade(string newShade)
            => this with { Shade = newShade };

        public ColorPigment WithMetadata(string key, object value)
        {
            var dict = new Dictionary<string, object>(Metadata) { [key] = value };
            return this with { Metadata = dict };
        }
    }

    /// <summary>
    ///     Strategy Pattern: every concrete implementation performs one
    ///     step of the transformation (blend / enrich / anonymize / …).
    /// </summary>
    public interface ITransformationStrategy
    {
        string Name { get; }

        ColorPigment Transform(ColorPigment pigment);
    }

    /// <summary>
    ///     Pipeline Pattern: orchestrates an ordered chain of strategies
    ///     and raises Observer events after each successful step.
    /// </summary>
    public sealed class PalettePipeline
    {
        private readonly IReadOnlyList<ITransformationStrategy> _strategies;

        public PalettePipeline(IEnumerable<ITransformationStrategy> strategies)
        {
            _strategies = strategies?.ToList() ?? throw new ArgumentNullException(nameof(strategies));
            if (_strategies.Count == 0)
                throw new ArgumentException("At least one strategy is required.", nameof(strategies));
        }

        /// <summary>
        ///     Observer Pattern – broadcast after *every* transform.
        /// </summary>
        public event EventHandler<TransformationEventArgs>? TransformationCompleted;

        public async Task<ColorPigment> ExecuteAsync(ColorPigment pigment)
        {
            if (pigment is null) throw new ArgumentNullException(nameof(pigment));

            var current = pigment;

            foreach (var strategy in _strategies)
            {
                current = await Task.Run(() => strategy.Transform(current))
                                    .ConfigureAwait(false);

                // Fire Observer hook — swallow downstream failures so
                // we don’t affect the ETL flow, but *do* log them.
                try
                {
                    TransformationCompleted?.Invoke(this,
                        new TransformationEventArgs(strategy, current));
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine(
                        $"[Warning] Observer threw inside '{strategy.Name}': {ex}");
                }
            }

            return current;
        }
    }

    /// <summary>
    ///     Data that monitoring / alerting hooks receive.
    /// </summary>
    public sealed class TransformationEventArgs : EventArgs
    {
        public TransformationEventArgs(ITransformationStrategy strategy,
                                       ColorPigment result)
        {
            Strategy = strategy;
            Result = result;
        }

        public ITransformationStrategy Strategy { get; }
        public ColorPigment Result { get; }
    }

    #endregion

    #region Concrete Strategies (Examples)

    internal sealed class ShadeBlendStrategy : ITransformationStrategy
    {
        public string Name => nameof(ShadeBlendStrategy);

        private readonly string _blendWith;

        public ShadeBlendStrategy(string blendWith) => _blendWith = blendWith;

        public ColorPigment Transform(ColorPigment pigment)
            => pigment.WithShade($"{pigment.Shade}+{_blendWith}");
    }

    internal sealed class MetadataEnrichmentStrategy : ITransformationStrategy
    {
        public string Name => nameof(MetadataEnrichmentStrategy);

        public ColorPigment Transform(ColorPigment pigment)
            => pigment.WithMetadata("enrichedOn", DateTime.UtcNow);
    }

    internal sealed class FaultyStrategy : ITransformationStrategy
    {
        public string Name => nameof(FaultyStrategy);

        public ColorPigment Transform(ColorPigment pigment)
            => throw new InvalidOperationException("Simulated processor failure");
    }

    #endregion

    #region Test Suite

    public class PalettePipelineTests
    {
        [Fact(DisplayName = "Pipeline applies strategies in order and fires Observer events")]
        public async Task Pipeline_Should_ApplyStrategies_InOrder_AndRaiseEvents()
        {
            // Arrange
            var initialPigment = new ColorPigment("Red", new Dictionary<string, object>());

            // Use mocks to capture Observer invocations.
            var observerMock = new Mock<EventHandler<TransformationEventArgs>>();
            var strategies = new ITransformationStrategy[]
            {
                new ShadeBlendStrategy("Blue"),     // Red+Blue
                new ShadeBlendStrategy("Yellow"),   // Red+Blue+Yellow
                new MetadataEnrichmentStrategy()
            };

            var pipeline = new PalettePipeline(strategies);
            pipeline.TransformationCompleted += observerMock.Object;

            // Act
            var result = await pipeline.ExecuteAsync(initialPigment);

            // Assert
            Assert.Equal("Red+Blue+Yellow", result.Shade);
            Assert.True(result.Metadata.ContainsKey("enrichedOn"));

            // Observer called once per strategy.
            observerMock.Verify(
                o => o.Invoke(pipeline, It.IsAny<TransformationEventArgs>()),
                Times.Exactly(strategies.Length));

            // Ensure order of events is preserved.
            observerMock.Invocations
                        .Select(inv => ((TransformationEventArgs)inv.Arguments[1]).Strategy.Name)
                        .Should().BeEquivalentTo(
                            strategies.Select(s => s.Name),
                            options => options.WithStrictOrdering());
        }

        [Fact(DisplayName = "Pipeline propagates strategy exceptions and halts execution")]
        public async Task Pipeline_Should_ThrowAndAbort_WhenStrategyFails()
        {
            // Arrange
            var pigment = new ColorPigment("Green", new Dictionary<string, object>());
            var strategies = new ITransformationStrategy[]
            {
                new ShadeBlendStrategy("Black"),
                new FaultyStrategy(),                   // ← boom
                new MetadataEnrichmentStrategy()        // never executed
            };

            var pipeline = new PalettePipeline(strategies);

            // Act & Assert
            var ex = await Assert.ThrowsAsync<InvalidOperationException>(
                () => pipeline.ExecuteAsync(pigment));

            Assert.Equal("Simulated processor failure", ex.Message);
        }

        [Fact(DisplayName = "Observer errors are swallowed, ensuring ETL continuity")]
        public async Task Pipeline_Should_Swallow_ObserverFailures()
        {
            // Arrange
            var pigment = new ColorPigment("Cyan", new Dictionary<string, object>());

            var faultyObserver = new EventHandler<TransformationEventArgs>(
                (_, _) => throw new Exception("Observer crash"));

            var pipeline = new PalettePipeline(new[] { new ShadeBlendStrategy("Magenta") });
            pipeline.TransformationCompleted += faultyObserver;

            // Act & Assert – should *not* throw.
            var result = await pipeline.ExecuteAsync(pigment);
            Assert.Equal("Cyan+Magenta", result.Shade);
        }
    }

    #endregion

    #region FluentAssertions Extension

    // Lightweight re-implementation of the subset of FluentAssertions we need
    // to keep the file self-contained.  In a real project just reference the
    // FluentAssertions NuGet package instead.
    internal static class AssertionExtensions
    {
        public static void Should<T>(this T obj) => throw new NotSupportedException(
            "Use the overloads that take an expectation lambda.");

        public static void Should<T>(this IEnumerable<T> actual,
                                     Action<IEnumerable<T>> assertion)
            => assertion(actual);

        public static Action<IEnumerable<T>> BeEquivalentTo<T>(
            this IEnumerable<T> _,
            IEnumerable<T> expected,
            Func<EquivalencyAssertionOptions<T>, EquivalencyAssertionOptions<T>>?
                options = null)
        {
            return actual =>
            {
                var actualList = actual.ToList();
                var expectedList = expected.ToList();

                if (actualList.Count != expectedList.Count)
                    throw new Xunit.Sdk.EqualException(expectedList, actualList);

                for (var i = 0; i < actualList.Count; i++)
                {
                    if (!Equals(actualList[i], expectedList[i]))
                        throw new Xunit.Sdk.EqualException(expectedList, actualList);
                }
            };
        }
    }

    internal class EquivalencyAssertionOptions<T>
    {
        public EquivalencyAssertionOptions<T> WithStrictOrdering() => this;
    }

    #endregion
}
```
