```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/Training/ModelTrainerStep.cs

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace CanvasCraft.Pipeline.Steps.Training
{
    /// <summary>
    /// Pipeline step responsible for training a model and registering the resulting artefacts.
    /// Utilises Strategy + Factory patterns to delegate training logic to technology-specific trainers.
    /// </summary>
    public sealed class ModelTrainerStep : IPipelineStep
    {
        private readonly ILogger _logger;

        public ModelTrainerStep(ILogger<ModelTrainerStep>? logger = null)
        {
            _logger = logger ?? NullLogger<ModelTrainerStep>.Instance;
        }

        public string Name => nameof(ModelTrainerStep);

        public async Task ExecuteAsync(PipelineContext context, CancellationToken cancellationToken = default)
        {
            if (context == null) throw new ArgumentNullException(nameof(context));
            if (context.TrainingConfig == null) throw new InvalidOperationException("TrainingConfig was not provided.");
            if (context.Data == null) throw new InvalidOperationException("Dataset was not provided.");

            var experimentTracker = context.ExperimentTracker 
                                   ?? throw new InvalidOperationException("ExperimentTracker was not provided.");
            var modelRegistry     = context.ModelRegistry
                                   ?? throw new InvalidOperationException("ModelRegistry was not provided.");

            using var run = experimentTracker.StartRun(Name);

            try
            {
                _logger.LogInformation("Training step '{StepName}' started.", Name);
                run.LogParameters(context.TrainingConfig.ToDictionary());
                run.LogTaggedArtifact("dataset", context.Data.Path);

                // Select and execute concrete strategy
                var trainer    = ModelTrainerStrategyFactory.Create(context.TrainingConfig, _logger);
                var stopwatch  = Stopwatch.StartNew();
                var trainResult = await trainer.TrainAsync(context.Data, context.TrainingConfig, cancellationToken);
                stopwatch.Stop();

                // Log metrics & timings
                run.LogMetrics(trainResult.Metrics);
                run.LogMetric("training_time_ms", stopwatch.ElapsedMilliseconds);

                // Register the model in the central registry
                var modelVersion = await modelRegistry.RegisterAsync(
                    trainResult.ArtifactPath, trainResult.Metrics, cancellationToken);

                // Pass artefacts downstream
                context.Items["ModelVersionId"] = modelVersion.Id;
                context.Items["Metrics"]        = trainResult.Metrics;

                _logger.LogInformation("Training succeeded. ModelVersion={ModelVersionId}", modelVersion.Id);
                run.SetStatus(ExperimentRunStatus.Success);
            }
            catch (OperationCanceledException)
            {
                _logger.LogWarning("Training was cancelled.");
                run.SetStatus(ExperimentRunStatus.Failed, "Cancelled");
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Training failed with error.");
                run.SetStatus(ExperimentRunStatus.Failed, ex.Message);
                throw;
            }
        }
    }

    #region ---- Strategy Pattern Implementation --------------------------------------------------

    internal static class ModelTrainerStrategyFactory
    {
        public static IModelTrainerStrategy Create(TrainingConfig cfg, ILogger parentLogger)
            => cfg.ModelType switch
            {
                ModelType.Vision  => new VisionTrainerStrategy(parentLogger),
                ModelType.Audio   => new AudioTrainerStrategy(parentLogger),
                ModelType.Tabular => new TabularTrainerStrategy(parentLogger),
                _ => throw new NotSupportedException($"Unknown ModelType '{cfg.ModelType}'.")
            };
    }

    internal interface IModelTrainerStrategy
    {
        Task<TrainingResult> TrainAsync(Dataset dataset,
                                        TrainingConfig config,
                                        CancellationToken cancellationToken = default);
    }

    internal abstract class BaseTrainerStrategy : IModelTrainerStrategy
    {
        protected readonly ILogger Logger;

        protected BaseTrainerStrategy(ILogger? logger)
        {
            Logger = logger ?? NullLogger.Instance;
        }

        public abstract Task<TrainingResult> TrainAsync(Dataset dataset,
                                                        TrainingConfig config,
                                                        CancellationToken cancellationToken = default);

        protected static IDictionary<string, double> GenerateRandomMetrics()
        {
            var rnd = new Random(Guid.NewGuid().GetHashCode());
            return new Dictionary<string, double>
            {
                ["accuracy"] = Math.Round(rnd.NextDouble() * 0.25 + 0.70, 4), // 0.70 – 0.95
                ["loss"]     = Math.Round(rnd.NextDouble() * 0.50, 4),
                ["f1"]       = Math.Round(rnd.NextDouble() * 0.25 + 0.65, 4)
            };
        }

        protected static async Task<string> PersistStubModelAsync(string prefix,
                                                                  CancellationToken token)
        {
            var path = Path.Combine(Path.GetTempPath(), $"{prefix}_{Guid.NewGuid():N}.bin");
            await File.WriteAllTextAsync(path, "binary model blob", token);
            return path;
        }
    }

    /// <summary>Trainer for computer-vision models.</summary>
    internal sealed class VisionTrainerStrategy : BaseTrainerStrategy
    {
        public VisionTrainerStrategy(ILogger? logger = null) : base(logger) { }

        public override async Task<TrainingResult> TrainAsync(Dataset dataset,
                                                              TrainingConfig config,
                                                              CancellationToken cancellationToken = default)
        {
            Logger.LogInformation("Vision training: {Samples} images, {Epochs} epochs",
                                  dataset.SampleCount, config.Epochs);

            for (var epoch = 1; epoch <= config.Epochs; epoch++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                await Task.Delay(250, cancellationToken); // Simulate GPU work
                Logger.LogDebug("Vision epoch {Epoch}/{Total} completed.", epoch, config.Epochs);
            }

            var metrics = GenerateRandomMetrics();
            var path    = await PersistStubModelAsync("vision", cancellationToken);
            return new TrainingResult(Guid.NewGuid(), metrics, path);
        }
    }

    /// <summary>Trainer for audio-classification models.</summary>
    internal sealed class AudioTrainerStrategy : BaseTrainerStrategy
    {
        public AudioTrainerStrategy(ILogger? logger = null) : base(logger) { }

        public override async Task<TrainingResult> TrainAsync(Dataset dataset,
                                                              TrainingConfig config,
                                                              CancellationToken cancellationToken = default)
        {
            Logger.LogInformation("Audio training: {Samples} clips, hop={Hop}", dataset.SampleCount,
                                  config.HyperParameters.TryGetValue("hop_length", out var hop) ? hop : "n/a");

            for (var epoch = 1; epoch <= config.Epochs; epoch++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                await Task.Delay(200, cancellationToken); // Simulate training
                Logger.LogDebug("Audio epoch {Epoch}/{Total}", epoch, config.Epochs);
            }

            var metrics = GenerateRandomMetrics();
            var path    = await PersistStubModelAsync("audio", cancellationToken);
            return new TrainingResult(Guid.NewGuid(), metrics, path);
        }
    }

    /// <summary>Trainer for tabular dataset models (e.g., gradient boosting).</summary>
    internal sealed class TabularTrainerStrategy : BaseTrainerStrategy
    {
        public TabularTrainerStrategy(ILogger? logger = null) : base(logger) { }

        public override async Task<TrainingResult> TrainAsync(Dataset dataset,
                                                              TrainingConfig config,
                                                              CancellationToken cancellationToken = default)
        {
            Logger.LogInformation("Tabular training with LR={LR} and {Trees} trees",
                                  config.LearningRate, 
                                  config.HyperParameters.TryGetValue("n_trees", out var trees) ? trees : "n/a");

            // Simulate CPU-bound work
            await Task.Delay(TimeSpan.FromMilliseconds(400 * config.Epochs), cancellationToken);

            var metrics = GenerateRandomMetrics();
            var path    = await PersistStubModelAsync("tabular", cancellationToken);
            return new TrainingResult(Guid.NewGuid(), metrics, path);
        }
    }

    #endregion

    #region ---- Supporting Domain Contracts ------------------------------------------------------

    public interface IPipelineStep
    {
        string Name { get; }

        Task ExecuteAsync(PipelineContext context, CancellationToken cancellationToken = default);
    }

    /// <summary>Shared context handed from one pipeline step to the next.</summary>
    public sealed class PipelineContext
    {
        public required TrainingConfig        TrainingConfig  { get; init; }
        public required Dataset               Data            { get; init; }
        public required IExperimentTracker    ExperimentTracker { get; init; }
        public required IModelRegistry        ModelRegistry     { get; init; }
        public required ILogger               Logger            { get; init; }
        public IDictionary<string, object>    Items { get; } = new Dictionary<string, object>();
    }

    public record TrainingConfig
    {
        public required ModelType                              ModelType       { get; init; }
        public int                                             Epochs          { get; init; } = 10;
        public double                                          LearningRate    { get; init; } = 1e-3;
        public IDictionary<string, string>                     HyperParameters { get; init; } = new Dictionary<string, string>();

        public IDictionary<string, object> ToDictionary()
        {
            var dict = new Dictionary<string, object>(HyperParameters.Count + 3)
            {
                ["model_type"]    = ModelType.ToString(),
                ["epochs"]        = Epochs,
                ["learning_rate"] = LearningRate
            };

            foreach (var (k, v) in HyperParameters)
                dict[$"hp_{k}"] = v;

            return dict;
        }
    }

    public enum ModelType
    {
        Vision,
        Audio,
        Tabular
    }

    public sealed class Dataset
    {
        public required string Path         { get; init; }
        public int             SampleCount  { get; init; }
    }

    public record TrainingResult(Guid ModelVersionId,
                                 IDictionary<string, double> Metrics,
                                 string ArtifactPath);

    public interface IExperimentTracker
    {
        IExperimentRun StartRun(string runName);
        IExperimentRun CurrentRun { get; }
    }

    public interface IExperimentRun : IDisposable
    {
        void LogParameters(IDictionary<string, object> parameters);
        void LogMetric(string name, double value);
        void LogMetrics(IDictionary<string, double> metrics);
        void LogTaggedArtifact(string tag, string path);
        void SetStatus(ExperimentRunStatus status, string? message = null);
    }

    public enum ExperimentRunStatus
    {
        Running,
        Success,
        Failed
    }

    public interface IModelRegistry
    {
        Task<ModelVersion> RegisterAsync(string artifactPath,
                                         IDictionary<string, double> metrics,
                                         CancellationToken cancellationToken = default);
    }

    public record ModelVersion(Guid Id, string ArtifactPath, DateTime RegisteredAt);

    #endregion
}
```