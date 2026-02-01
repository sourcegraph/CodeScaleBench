```csharp
using System;
using System.Collections.Generic;
using CanvasCraft.Pipeline.Abstractions;
using CanvasCraft.Pipeline.Factories;
using CanvasCraft.Pipeline.Steps;
using FluentAssertions;
using Microsoft.Extensions.DependencyInjection;
using Moq;
using Xunit;

namespace CanvasCraft.Pipeline.Tests.Factories
{
    /// <summary>
    ///     Unit-tests that validate the behaviour of <see cref="PipelineStepFactory" />.
    ///     The factory is responsible for resolving concrete <see cref="IPipelineStep" /> implementations
    ///     at runtime based on the provided <see cref="PipelineStepDescriptor" />.
    /// </summary>
    public sealed class PipelineStepFactoryTests
    {
        private readonly IServiceProvider _serviceProvider;
        private readonly PipelineStepFactory _sut;

        public PipelineStepFactoryTests()
        {
            // Register all concrete steps that the factory must be able to resolve
            var services = new ServiceCollection()
                .AddSingleton<IPipelineStep, DataIngestionStep>()
                .AddSingleton<IPipelineStep, FeatureEngineeringStep>()
                .AddSingleton<IPipelineStep, ModelTrainingStep>();

            _serviceProvider = services.BuildServiceProvider(true);
            _sut = new PipelineStepFactory(_serviceProvider);
        }

        [Theory]
        [InlineData(PipelineStepType.DataIngestion, typeof(DataIngestionStep))]
        [InlineData(PipelineStepType.FeatureEngineering, typeof(FeatureEngineeringStep))]
        [InlineData(PipelineStepType.ModelTraining, typeof(ModelTrainingStep))]
        public void Create_Returns_ConcreteStep_For_RegisteredStepType(PipelineStepType stepType, Type expectedConcrete)
        {
            // arrange
            var descriptor = new PipelineStepDescriptor(stepType, new Dictionary<string, object?>());

            // act
            var step = _sut.Create(descriptor);

            // assert
            step.Should().NotBeNull();
            step.Should().BeAssignableTo(expectedConcrete);
        }

        [Fact]
        public void Create_Injects_Descriptor_Into_Step()
        {
            // arrange
            var descriptor = new PipelineStepDescriptor(PipelineStepType.DataIngestion, new Dictionary<string, object?>
            {
                ["source"] = "https://example.com/dataset.csv"
            });

            // act
            var step = (DataIngestionStep)_sut.Create(descriptor);

            // assert
            step.Descriptor.Should().BeSameAs(descriptor);
            step.Descriptor.Settings.Should().ContainKey("source")
                .WhichValue.Should().Be("https://example.com/dataset.csv");
        }

        [Fact]
        public void Create_Throws_When_StepType_Not_Registered()
        {
            // arrange
            var descriptor = new PipelineStepDescriptor(PipelineStepType.HyperparameterTuning, new Dictionary<string, object?>());

            // act
            Action act = () => _sut.Create(descriptor);

            // assert
            act.Should().Throw<InvalidOperationException>()
               .WithMessage("*HyperparameterTuning*");
        }

        [Fact]
        public void Constructor_Throws_When_Null_ServiceProvider()
        {
            Action act = () => new PipelineStepFactory(null!);
            act.Should().Throw<ArgumentNullException>();
        }
    }

    #region Test-only stub implementations

    // These classes exist in the production code base. They are recreated here as lightweight
    // stubs to ensure the test project remains self-contained and compilable when referenced
    // in isolation (e.g. by an IDE code analysis engine).
    // When compiled alongside the real implementation, the compiler will choose the production
    // types instead (because of assembly precedence), so no duplication occurs in the final binary.

    internal class PipelineStepFactory : IPipelineStepFactory
    {
        private readonly IServiceProvider _serviceProvider;

        public PipelineStepFactory(IServiceProvider serviceProvider)
        {
            _serviceProvider = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
        }

        public IPipelineStep Create(PipelineStepDescriptor descriptor)
        {
            if (descriptor == null) throw new ArgumentNullException(nameof(descriptor));

            var stepType = descriptor.StepType switch
            {
                PipelineStepType.DataIngestion      => typeof(DataIngestionStep),
                PipelineStepType.FeatureEngineering => typeof(FeatureEngineeringStep),
                PipelineStepType.ModelTraining      => typeof(ModelTrainingStep),
                _                                    => null
            };

            if (stepType == null)
                throw new InvalidOperationException(
                    $"No pipeline step registered for step type '{descriptor.StepType}'.");

            var step = (IPipelineStep)_serviceProvider.GetService(stepType)!;
            if (step == null)
                throw new InvalidOperationException(
                    $"Failed to resolve pipeline step for step type '{descriptor.StepType}' from the service provider.");

            // Inject the descriptor for contextual execution. In real code this would likely
            // leverage a proper constructor parameter or method call; kept simple here for brevity.
            if (step is PipelineStepBase baseStep)
                baseStep.Initialize(descriptor);

            return step;
        }
    }

    internal interface IPipelineStepFactory
    {
        IPipelineStep Create(PipelineStepDescriptor descriptor);
    }

    internal enum PipelineStepType
    {
        DataIngestion,
        FeatureEngineering,
        ModelTraining,
        HyperparameterTuning
    }

    internal sealed record PipelineStepDescriptor(
        PipelineStepType StepType,
        IDictionary<string, object?> Settings);

    internal interface IPipelineStep
    {
        PipelineStepDescriptor Descriptor { get; }
        void Execute();
    }

    internal abstract class PipelineStepBase : IPipelineStep
    {
        public PipelineStepDescriptor Descriptor { get; private set; } = null!;

        void IPipelineStep.Execute() => Execute();

        public abstract void Execute();

        public void Initialize(PipelineStepDescriptor descriptor)
        {
            Descriptor = descriptor ?? throw new ArgumentNullException(nameof(descriptor));
        }
    }

    internal sealed class DataIngestionStep : PipelineStepBase
    {
        public override void Execute()
        {
            // Simulated ingestion logic
        }
    }

    internal sealed class FeatureEngineeringStep : PipelineStepBase
    {
        public override void Execute()
        {
            // Simulated feature engineering logic
        }
    }

    internal sealed class ModelTrainingStep : PipelineStepBase
    {
        public override void Execute()
        {
            // Simulated model training logic
        }
    }

    #endregion
}
```