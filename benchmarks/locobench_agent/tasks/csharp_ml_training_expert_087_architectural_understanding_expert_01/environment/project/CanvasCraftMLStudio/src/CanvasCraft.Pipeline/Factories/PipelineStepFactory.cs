```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Factories/PipelineStepFactory.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json.Linq;

namespace CanvasCraft.Pipeline.Factories
{
    /// <summary>
    /// Responsible for creating concrete instances of <see cref="IPipelineStep" />
    /// based on a pipeline definition. The factory relies on the DI container
    /// and run-time reflection to materialize the appropriate step class so that
    /// callers do not need to reference concrete implementations directly.
    ///
    /// The factory is thread-safe and can be reused across pipeline executions.
    /// </summary>
    public sealed class PipelineStepFactory : IPipelineStepFactory, IDisposable
    {
        private readonly IServiceProvider _serviceProvider;
        private readonly ILogger<PipelineStepFactory> _logger;
        private readonly ConcurrentDictionary<string, Func<PipelineStepContext, IPipelineStep>> _customCreators;
        private bool _disposed;

        public PipelineStepFactory(IServiceProvider serviceProvider,
                                   ILogger<PipelineStepFactory> logger)
        {
            _serviceProvider  = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
            _logger           = logger          ?? throw new ArgumentNullException(nameof(logger));
            _customCreators   = new ConcurrentDictionary<string, Func<PipelineStepContext, IPipelineStep>>(StringComparer.OrdinalIgnoreCase);
        }

        /// <inheritdoc />
        public IEnumerable<IPipelineStep> CreateSteps(PipelineDefinition definition, CancellationToken ct = default)
        {
            if (definition is null)
                throw new ArgumentNullException(nameof(definition));

            if (definition.StepDefinitions.Count == 0)
            {
                _logger.LogWarning("Pipeline definition \"{PipelineName}\" contains no steps.", definition.Name);
                return Enumerable.Empty<IPipelineStep>();
            }

            var steps = new List<IPipelineStep>(definition.StepDefinitions.Count);

            foreach (var stepDef in definition.StepDefinitions.OrderBy(sd => sd.Order))
            {
                ct.ThrowIfCancellationRequested();
                steps.Add(CreateStep(stepDef));
            }

            return steps;
        }

        /// <inheritdoc />
        public IPipelineStep CreateStep(StepDefinition stepDefinition)
        {
            if (stepDefinition is null)
                throw new ArgumentNullException(nameof(stepDefinition));

            // First check if a user-supplied creator has been registered.
            if (_customCreators.TryGetValue(stepDefinition.Type, out var creator))
            {
                _logger.LogDebug("Creating pipeline step \"{StepName}\" using a custom creator.", stepDefinition.Type);
                return creator(new PipelineStepContext(stepDefinition, _serviceProvider));
            }

            // Fallback to DI/Reflection discovery.
            var stepInstance = ResolveViaServiceProvider(stepDefinition)
                               ?? ResolveViaReflection(stepDefinition);

            _logger.LogInformation("Created pipeline step \"{StepName}\" (ConcreteType: {ConcreteType}).",
                                   stepDefinition.Type,
                                   stepInstance.GetType().Name);

            return stepInstance;
        }

        /// <summary>
        /// Registers a custom step creator delegate that is invoked when
        /// a <see cref="StepDefinition.Type"/> matches <paramref name="typeKey"/>.
        /// </summary>
        /// <param name="typeKey">Step type identifier (case-insensitive).</param>
        /// <param name="creator">Factory delegate.</param>
        public void RegisterCustomCreator(string typeKey, Func<PipelineStepContext, IPipelineStep> creator)
        {
            if (string.IsNullOrWhiteSpace(typeKey))
                throw new ArgumentException("Type key cannot be null or whitespace.", nameof(typeKey));
            if (creator is null)
                throw new ArgumentNullException(nameof(creator));

            if (!_customCreators.TryAdd(typeKey.Trim(), creator))
                throw new InvalidOperationException($"A custom creator for type '{typeKey}' has already been registered.");

            _logger.LogDebug("Custom creator registered for pipeline step type \"{TypeKey}\".", typeKey);
        }

        #region Private helpers

        private IPipelineStep ResolveViaServiceProvider(StepDefinition stepDefinition)
        {
            // Allow users to register concrete steps in DI and simply resolve by name.
            var matching = _serviceProvider
                .GetServices<IPipelineStep>()
                .FirstOrDefault(s => s.Name.Equals(stepDefinition.Type, StringComparison.OrdinalIgnoreCase));

            if (matching != null)
            {
                ConfigureStepInstance(matching, stepDefinition);
            }

            return matching;
        }

        private IPipelineStep ResolveViaReflection(StepDefinition stepDefinition)
        {
            // Convention: step types live in the CanvasCraft.Pipeline.Steps namespace
            // and end with "Step" (e.g., "DataIngestionStep").
            var expectedClrName = stepDefinition.Type.EndsWith("Step", StringComparison.OrdinalIgnoreCase)
                                    ? stepDefinition.Type
                                    : $"{stepDefinition.Type}Step";

            var candidateType = AppDomain.CurrentDomain
                                        .GetAssemblies()
                                        .SelectMany(a =>
                                        {
                                            try { return a.GetTypes(); }
                                            catch (ReflectionTypeLoadException ex) { return ex.Types.Where(t => t != null)!; }
                                        })
                                        .FirstOrDefault(t => typeof(IPipelineStep).IsAssignableFrom(t)
                                                             && t.Name.Equals(expectedClrName, StringComparison.OrdinalIgnoreCase)
                                                             && !t.IsAbstract);

            if (candidateType == null)
                throw new UnknownPipelineStepException(stepDefinition.Type);

            var stepInstance = ActivatorUtilities.CreateInstance(_serviceProvider, candidateType) as IPipelineStep
                               ?? throw new InvalidOperationException($"Unable to create instance of step type '{candidateType.FullName}'.");

            ConfigureStepInstance(stepInstance, stepDefinition);

            return stepInstance;
        }

        private static void ConfigureStepInstance(IPipelineStep instance, StepDefinition stepDefinition)
        {
            // Allow steps to receive raw configuration parameters via IConfigurablePipelineStep.
            if (instance is IConfigurablePipelineStep configurable)
            {
                configurable.Configure(stepDefinition.Parameters);
            }
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            (_serviceProvider as IDisposable)?.Dispose();
            _customCreators.Clear();
        }

        #endregion
    }

    #region Interfaces & POCOs (internal placeholders)

    // NOTE: In real production these would reside in their own files/namespaces.
    // They are included here solely to keep the example self-contained.

    public interface IPipelineStep
    {
        string Name { get; }
        Task ExecuteAsync(CancellationToken ct = default);
    }

    public interface IConfigurablePipelineStep : IPipelineStep
    {
        /// <summary>
        /// Accepts raw config parameters from the pipeline definition (e.g., JSON).
        /// </summary>
        /// <param name="parameters">The step-specific parameters.</param>
        void Configure(JObject parameters);
    }

    public interface IPipelineStepFactory
    {
        IEnumerable<IPipelineStep> CreateSteps(PipelineDefinition definition, CancellationToken ct = default);
        IPipelineStep CreateStep(StepDefinition stepDefinition);
    }

    /// <summary>
    /// Run-time context supplied to custom creators.
    /// </summary>
    public readonly struct PipelineStepContext
    {
        public PipelineStepContext(StepDefinition definition, IServiceProvider sp)
        {
            Definition      = definition;
            ServiceProvider = sp;
        }

        public StepDefinition Definition { get; }
        public IServiceProvider ServiceProvider { get; }
    }

    public sealed class PipelineDefinition
    {
        public string Name { get; init; } = "UnnamedPipeline";
        public IList<StepDefinition> StepDefinitions { get; init; } = new List<StepDefinition>();
    }

    public sealed class StepDefinition
    {
        /// <summary>
        /// Logical name of the step (e.g., "DataIngestion", "FeatureEngineering").
        /// </summary>
        public string Type { get; init; } = default!;

        /// <summary>
        /// Execution order within the pipeline.
        /// </summary>
        public int Order { get; init; }

        /// <summary>
        /// Arbitrary parameters that the step expects.
        /// </summary>
        public JObject Parameters { get; init; } = new JObject();
    }

    /// <summary>
    /// Thrown when a pipeline step cannot be resolved.
    /// </summary>
    public sealed class UnknownPipelineStepException : Exception
    {
        public UnknownPipelineStepException(string stepType)
            : base($"Unable to locate a pipeline step of type '{stepType}'. " +
                   "Ensure it is registered in the DI container, " +
                   "added as a custom creator, or follows the naming convention.")
        { }
    }

    #endregion
}
```