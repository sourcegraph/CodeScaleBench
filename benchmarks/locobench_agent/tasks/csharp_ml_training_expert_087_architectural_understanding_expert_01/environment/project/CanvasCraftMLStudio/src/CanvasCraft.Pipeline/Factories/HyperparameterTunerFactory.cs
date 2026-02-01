```csharp
// -------------------------------------------------------------------------------------------------
//  CanvasCraft ML Studio
//  HyperparameterTunerFactory.cs
//
//  Copyright (c) CanvasCraft
//  All rights reserved.
// -------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.Loader;
using Microsoft.Extensions.Logging;
using CanvasCraft.ExperimentTracking;
using CanvasCraft.Pipeline.Configuration;
using CanvasCraft.Pipeline.Exceptions;
using CanvasCraft.Pipeline.HyperparameterTuning;

namespace CanvasCraft.Pipeline.Factories
{
    /// <summary>
    /// Factory responsible for instantiating <see cref="IHyperparameterTuner"/> implementations
    /// based on runtime configuration.  The factory encapsulates:
    ///
    /// • Creation of built-in tuner strategies (Grid, Random, Bayesian)
    /// • Dynamic loading of custom tuner plug-ins (Strategy Pattern)
    /// • Centralized, opinionated error handling and logging
    ///
    /// The factory is intended to be invoked by the Pipeline Orchestrator immediately before
    /// training begins, so that the selected tuner can register itself with the 
    /// <see cref="IExperimentTracker"/> and emit search progress throughout the run.
    /// </summary>
    public static class HyperparameterTunerFactory
    {
        /// <summary>
        /// Creates an <see cref="IHyperparameterTuner"/> based on the supplied <paramref name="config"/>.
        /// </summary>
        /// <param name="config">User-provided tuning configuration.</param>
        /// <param name="dataset">The dataset on which models will be trained.</param>
        /// <param name="featureStore">Feature store, used by certain tuners for 
        ///                             online feature selection.</param>
        /// <param name="experimentTracker">Experiment tracker used for metrics logging.</param>
        /// <param name="loggerFactory">Logger factory for structured logging.</param>
        /// <returns>Constructed and dependency-injected tuner.</returns>
        /// <exception cref="PipelineConfigurationException">
        /// Thrown when configuration is missing or invalid.
        /// </exception>
        public static IHyperparameterTuner CreateTuner(
            TunerConfig config,
            IDataSet dataset,
            IFeatureStore featureStore,
            IExperimentTracker experimentTracker,
            ILoggerFactory loggerFactory)
        {
            if (config == null) throw new ArgumentNullException(nameof(config));
            if (dataset == null) throw new ArgumentNullException(nameof(dataset));
            if (featureStore == null) throw new ArgumentNullException(nameof(featureStore));
            if (experimentTracker == null) throw new ArgumentNullException(nameof(experimentTracker));
            if (loggerFactory == null) throw new ArgumentNullException(nameof(loggerFactory));

            ILogger logger = loggerFactory.CreateLogger(typeof(HyperparameterTunerFactory));

            try
            {
                logger.LogInformation("Creating hyper-parameter tuner for strategy {Strategy}", config.Strategy);

                return config.Strategy switch
                {
                    HyperparameterTuningStrategy.GridSearch   => CreateGridSearchTuner(config, dataset, featureStore, experimentTracker, loggerFactory),
                    HyperparameterTuningStrategy.RandomSearch => CreateRandomSearchTuner(config, dataset, featureStore, experimentTracker, loggerFactory),
                    HyperparameterTuningStrategy.Bayesian     => CreateBayesianTuner(config, dataset, featureStore, experimentTracker, loggerFactory),
                    HyperparameterTuningStrategy.Custom       => LoadCustomTuner(config, dataset, featureStore, experimentTracker, loggerFactory, logger),
                    _ => throw new PipelineConfigurationException($"Unsupported tuning strategy '{config.Strategy}'.")
                };
            }
            catch (Exception ex) when (!ex.IsCritical())
            {
                logger.LogError(ex, "Failed to create hyper-parameter tuner.");
                throw;
            }
        }

        #region Built-in strategy factories --------------------------------------------------------

        private static IHyperparameterTuner CreateGridSearchTuner(
            TunerConfig config,
            IDataSet       dataset,
            IFeatureStore  featureStore,
            IExperimentTracker tracker,
            ILoggerFactory loggerFactory)
        {
            return new GridSearchTuner(
                searchSpace        : config.SearchSpace,
                maxTrials          : config.MaxTrials,
                dataset            : dataset,
                featureStore       : featureStore,
                tracker            : tracker,
                loggerFactory      : loggerFactory
            );
        }

        private static IHyperparameterTuner CreateRandomSearchTuner(
            TunerConfig config,
            IDataSet       dataset,
            IFeatureStore  featureStore,
            IExperimentTracker tracker,
            ILoggerFactory loggerFactory)
        {
            return new RandomSearchTuner(
                searchSpace        : config.SearchSpace,
                maxTrials          : config.MaxTrials,
                seed               : config.RandomSeed,
                dataset            : dataset,
                featureStore       : featureStore,
                tracker            : tracker,
                loggerFactory      : loggerFactory
            );
        }

        private static IHyperparameterTuner CreateBayesianTuner(
            TunerConfig config,
            IDataSet       dataset,
            IFeatureStore  featureStore,
            IExperimentTracker tracker,
            ILoggerFactory loggerFactory)
        {
            return new BayesianTuner(
                searchSpace        : config.SearchSpace,
                maxTrials          : config.MaxTrials,
                initialRandomRuns  : config.InitialRandomRuns,
                explorationRatio   : config.ExplorationRatio,
                dataset            : dataset,
                featureStore       : featureStore,
                tracker            : tracker,
                loggerFactory      : loggerFactory
            );
        }

        #endregion

        #region Custom strategy loader -------------------------------------------------------------

        /// <summary>
        /// Dynamically loads a custom tuner implementation from disk and instantiates it.  
        /// The implementation must:
        ///     • Implement <see cref="IHyperparameterTuner"/>
        ///     • Expose a public constructor matching the factory signature
        /// </summary>
        private static IHyperparameterTuner LoadCustomTuner(
            TunerConfig config,
            IDataSet       dataset,
            IFeatureStore  featureStore,
            IExperimentTracker tracker,
            ILoggerFactory loggerFactory,
            ILogger logger)
        {
            if (string.IsNullOrWhiteSpace(config.CustomTunerType))
                throw new PipelineConfigurationException("CustomTunerType must be provided for custom strategy.");

            if (string.IsNullOrWhiteSpace(config.CustomTunerAssemblyPath))
                throw new PipelineConfigurationException("CustomTunerAssemblyPath must be provided for custom strategy.");

            if (!File.Exists(config.CustomTunerAssemblyPath))
                throw new PipelineConfigurationException($"Custom tuner assembly '{config.CustomTunerAssemblyPath}' does not exist.");

            logger.LogInformation("Dynamically loading custom tuner from '{AssemblyPath}'", config.CustomTunerAssemblyPath);

            // Isolation via AssemblyLoadContext allows unloading if needed.
            var alc       = new AssemblyLoadContext($"CustomTuner_{Guid.NewGuid()}", isCollectible: true);
            var assembly  = alc.LoadFromAssemblyPath(Path.GetFullPath(config.CustomTunerAssemblyPath));
            var tunerType = assembly.GetType(config.CustomTunerType, throwOnError: true);

            if (!typeof(IHyperparameterTuner).IsAssignableFrom(tunerType))
                throw new PipelineConfigurationException($"Custom tuner '{config.CustomTunerType}' does not implement IHyperparameterTuner.");

            // The required ctor signature
            var ctor = tunerType.GetConstructor(new[]
            {
                typeof(IDictionary<string, HyperparameterSpace>),
                typeof(int),
                typeof(IDataSet),
                typeof(IFeatureStore),
                typeof(IExperimentTracker),
                typeof(ILoggerFactory)
            });

            if (ctor == null)
                throw new PipelineConfigurationException(
                    $"No public constructor found on '{config.CustomTunerType}' " +
                    "matching the required signature (searchSpace, maxTrials, dataset, featureStore, tracker, loggerFactory).");

            // Instantiate
            var instance = (IHyperparameterTuner) ctor.Invoke(new object[]
            {
                config.SearchSpace,
                config.MaxTrials,
                dataset,
                featureStore,
                tracker,
                loggerFactory
            });

            logger.LogInformation("Successfully loaded custom hyper-parameter tuner: {TunerType}", tunerType.FullName);

            return instance;
        }

        #endregion
    }
}

// -------------------------------------------------------------------------------------------------
//  Below are supporting configuration, enum, and extension types that would normally live in their
//  own files.  They are included here for completeness and to keep the snippet self-contained.
// -------------------------------------------------------------------------------------------------

namespace CanvasCraft.Pipeline.Configuration
{
    using System.Collections.Generic;
    using CanvasCraft.Pipeline.HyperparameterTuning;

    /// <summary>
    /// User-supplied configuration object consumed by <see cref="HyperparameterTunerFactory"/>.
    /// </summary>
    public sealed class TunerConfig
    {
        public HyperparameterTuningStrategy Strategy { get; init; } = HyperparameterTuningStrategy.RandomSearch;

        /// <summary>Number of trials (model trainings) to run before stopping.</summary>
        public int MaxTrials { get; init; } = 50;

        /// <summary>Random seed for reproducibility (when applicable).</summary>
        public int? RandomSeed { get; init; }

        /// <summary>Number of random runs before Bayesian inference kicks in.</summary>
        public int InitialRandomRuns { get; init; } = 10;

        /// <summary>Exploration vs exploitation ratio for Bayesian optimization.</summary>
        public double ExplorationRatio { get; init; } = 0.25;

        /// <summary>Search space definition for each hyper-parameter.</summary>
        public IDictionary<string, HyperparameterSpace> SearchSpace { get; init; } 
            = new Dictionary<string, HyperparameterSpace>();

        /// <summary>Fully qualified type name for a custom tuner (when Strategy == Custom).</summary>
        public string? CustomTunerType { get; init; }

        /// <summary>Absolute or relative path to the assembly containing the custom tuner.</summary>
        public string? CustomTunerAssemblyPath { get; init; }
    }

    /// <summary>
    /// Enumerates supported hyper-parameter tuning strategies.
    /// </summary>
    public enum HyperparameterTuningStrategy
    {
        GridSearch,
        RandomSearch,
        Bayesian,
        Custom
    }
}

namespace CanvasCraft.Pipeline.HyperparameterTuning
{
    using System;
    using System.Collections.Generic;
    using System.Threading;
    using System.Threading.Tasks;
    using CanvasCraft.ExperimentTracking;

    /// <summary>
    /// Contract for all hyper-parameter tuners.
    /// </summary>
    public interface IHyperparameterTuner : IAsyncDisposable
    {
        /// <summary>
        /// Executes the tuning job and returns the winning set of parameters.
        /// </summary>
        Task<HyperparameterTuningResult> TuneAsync(CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Represents a single hyper-parameter search space.
    /// </summary>
    public sealed record HyperparameterSpace(
        double Min,
        double Max,
        double? Step      = null,    // For discrete/linear spaces
        IReadOnlyList<string>? Choices = null); // For categorical spaces

    /// <summary>
    /// Immutable result returned by a tuner at the end of search.
    /// </summary>
    public sealed record HyperparameterTuningResult(
        IReadOnlyDictionary<string, object> Parameters,
        double Metric,
        string     BestModelArtifactPath);
}

namespace CanvasCraft.Pipeline.Exceptions
{
    using System;

    /// <summary>
    /// Exception thrown for configuration-related issues within the pipeline.
    /// </summary>
    public sealed class PipelineConfigurationException : Exception
    {
        public PipelineConfigurationException(string message) : base(message) { }

        public PipelineConfigurationException(string message, Exception inner) : base(message, inner) { }
    }
}

namespace CanvasCraft.Utilities
{
    using System;

    /// <summary>
    /// Helper extensions for <see cref="Exception"/> classification.
    /// </summary>
    internal static class ExceptionExtensions
    {
        /// <summary>
        /// Determines whether the supplied exception is critical enough that it should
        /// not be swallowed by catch-all policies.
        /// </summary>
        public static bool IsCritical(this Exception ex)
        {
            return ex is OutOfMemoryException
                   or StackOverflowException
                   or ThreadAbortException;
        }
    }
}

// -------------------------------------------------------------------------------------------------
//  External abstractions normally supplied by other CanvasCraft modules.
//  Only signatures are included here to satisfy the compiler.
// -------------------------------------------------------------------------------------------------
namespace CanvasCraft.ExperimentTracking
{
    public interface IExperimentTracker
    {
        void LogMetric(string name, double value, int step);
        void LogParameter(string name, object value);
        void SetTag(string key, string value);
    }
}

namespace CanvasCraft.Pipeline
{
    public interface IDataSet { /* ... */ }
    public interface IFeatureStore { /* ... */ }
}

namespace CanvasCraft.Pipeline.HyperparameterTuning
{
    using CanvasCraft.ExperimentTracking;
    using Microsoft.Extensions.Logging;

    // Placeholders for built-in tuner implementations
    internal sealed class GridSearchTuner : IHyperparameterTuner
    {
        public GridSearchTuner(IDictionary<string, HyperparameterSpace> searchSpace, int maxTrials,
                               CanvasCraft.Pipeline.IDataSet dataset, CanvasCraft.Pipeline.IFeatureStore featureStore,
                               IExperimentTracker tracker, ILoggerFactory loggerFactory) { /* ... */ }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        public Task<HyperparameterTuningResult> TuneAsync(System.Threading.CancellationToken cancellationToken = default)
            => Task.FromResult<HyperparameterTuningResult>(null!);
    }

    internal sealed class RandomSearchTuner : IHyperparameterTuner
    {
        public RandomSearchTuner(IDictionary<string, HyperparameterSpace> searchSpace, int maxTrials, int? seed,
                                 CanvasCraft.Pipeline.IDataSet dataset, CanvasCraft.Pipeline.IFeatureStore featureStore,
                                 IExperimentTracker tracker, ILoggerFactory loggerFactory) { /* ... */ }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        public Task<HyperparameterTuningResult> TuneAsync(System.Threading.CancellationToken cancellationToken = default)
            => Task.FromResult<HyperparameterTuningResult>(null!);
    }

    internal sealed class BayesianTuner : IHyperparameterTuner
    {
        public BayesianTuner(IDictionary<string, HyperparameterSpace> searchSpace, int maxTrials, int initialRandomRuns,
                             double explorationRatio, CanvasCraft.Pipeline.IDataSet dataset,
                             CanvasCraft.Pipeline.IFeatureStore featureStore, IExperimentTracker tracker,
                             ILoggerFactory loggerFactory) { /* ... */ }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
        public Task<HyperparameterTuningResult> TuneAsync(System.Threading.CancellationToken cancellationToken = default)
            => Task.FromResult<HyperparameterTuningResult>(null!);
    }
}
```