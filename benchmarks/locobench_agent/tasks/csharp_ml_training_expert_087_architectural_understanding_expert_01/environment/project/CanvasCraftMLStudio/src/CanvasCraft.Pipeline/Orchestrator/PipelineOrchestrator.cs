```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Orchestrator/PipelineOrchestrator.cs

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using CanvasCraft.Pipeline.Events;
using CanvasCraft.Pipeline.Factories;
using CanvasCraft.Pipeline.Steps;
using CanvasCraft.Pipeline.Tracking;
using CanvasCraft.Pipeline.Registry;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Pipeline.Orchestrator
{
    /// <summary>
    /// Coordinates end-to-end execution of an ML pipeline in CanvasCraft ML Studio.
    /// Applies the Pipeline, Strategy, Factory, and Observer patterns to allow
    /// dynamic, runtime-composable experiments.
    /// </summary>
    public sealed class PipelineOrchestrator : IPipelineOrchestrator, IAsyncDisposable
    {
        private readonly IPreprocessingBrushFactory _brushFactory;
        private readonly IFeaturePaletteFactory _paletteFactory;
        private readonly IHyperparameterTuningWheelFactory _tuningWheelFactory;
        private readonly ITrainerFactory _trainerFactory;
        private readonly IEvaluatorFactory _evaluatorFactory;
        private readonly IExperimentTracker _tracker;
        private readonly IModelRegistry _modelRegistry;
        private readonly IEventBus _eventBus;
        private readonly ILogger<PipelineOrchestrator> _logger;
        private readonly Channel<PipelineEvent> _eventChannel;

        public PipelineOrchestrator(
            IPreprocessingBrushFactory brushFactory,
            IFeaturePaletteFactory paletteFactory,
            IHyperparameterTuningWheelFactory tuningWheelFactory,
            ITrainerFactory trainerFactory,
            IEvaluatorFactory evaluatorFactory,
            IExperimentTracker tracker,
            IModelRegistry modelRegistry,
            IEventBus eventBus,
            ILogger<PipelineOrchestrator> logger)
        {
            _brushFactory      = brushFactory      ?? throw new ArgumentNullException(nameof(brushFactory));
            _paletteFactory    = paletteFactory    ?? throw new ArgumentNullException(nameof(paletteFactory));
            _tuningWheelFactory= tuningWheelFactory?? throw new ArgumentNullException(nameof(tuningWheelFactory));
            _trainerFactory    = trainerFactory    ?? throw new ArgumentNullException(nameof(trainerFactory));
            _evaluatorFactory  = evaluatorFactory  ?? throw new ArgumentNullException(nameof(evaluatorFactory));
            _tracker           = tracker           ?? throw new ArgumentNullException(nameof(tracker));
            _modelRegistry     = modelRegistry     ?? throw new ArgumentNullException(nameof(modelRegistry));
            _eventBus          = eventBus          ?? throw new ArgumentNullException(nameof(eventBus));
            _logger            = logger            ?? throw new ArgumentNullException(nameof(logger));

            // Internal channel used to decouple pipeline-step progress from the event bus.
            _eventChannel      = Channel.CreateUnbounded<PipelineEvent>();
            _ = PumpEventsToBusAsync(_eventChannel.Reader, _eventBus, CancellationToken.None);
        }

        /// <inheritdoc />
        public async Task<PipelineResult> RunAsync(PipelineRequest request, CancellationToken cancellationToken = default)
        {
            if (request == null) throw new ArgumentNullException(nameof(request));

            var stopwatch = Stopwatch.StartNew();
            var experimentId = Guid.NewGuid();
            await _tracker.MarkExperimentStartedAsync(experimentId, request, cancellationToken);

            try
            {
                _logger.LogInformation("Experiment {ExperimentId} started with dataset '{DatasetUri}'", experimentId, request.DatasetUri);

                // 1. Pre-processing (Brush)
                var brush = _brushFactory.Create(request.PreprocessingBrushName);
                await PublishAsync(new PipelineProgressEvent(experimentId, "PreprocessingStarted"));
                var preprocessed = await brush.ExecuteAsync(request.DatasetUri, cancellationToken);
                await PublishAsync(new PipelineProgressEvent(experimentId, "PreprocessingCompleted"));

                // 2. Feature Engineering (Palette)
                var palette = _paletteFactory.Create(request.FeaturePaletteName);
                await PublishAsync(new PipelineProgressEvent(experimentId, "FeatureEngineeringStarted"));
                var featureSet = await palette.ExecuteAsync(preprocessed, cancellationToken);
                await PublishAsync(new PipelineProgressEvent(experimentId, "FeatureEngineeringCompleted"));

                // 3. Hyperparameter Tuning (Wheel)
                var tuner = _tuningWheelFactory.Create(request.TuningWheelName);
                await PublishAsync(new PipelineProgressEvent(experimentId, "HyperparameterTuningStarted"));
                var tunedParams = await tuner.ExecuteAsync(featureSet, request.Algorithm, cancellationToken);
                await PublishAsync(new PipelineProgressEvent(experimentId, "HyperparameterTuningCompleted"));

                // 4. Model Training
                var trainer = _trainerFactory.Create(request.Algorithm);
                await PublishAsync(new PipelineProgressEvent(experimentId, "ModelTrainingStarted"));
                var trainedModel = await trainer.ExecuteAsync(featureSet, tunedParams, cancellationToken);
                await PublishAsync(new PipelineProgressEvent(experimentId, "ModelTrainingCompleted"));

                // 5. Evaluation
                var evaluator = _evaluatorFactory.Create(request.EvaluationMetric);
                await PublishAsync(new PipelineProgressEvent(experimentId, "ModelEvaluationStarted"));
                var evaluationResult = await evaluator.ExecuteAsync(trainedModel, featureSet, cancellationToken);
                await PublishAsync(new PipelineProgressEvent(experimentId, "ModelEvaluationCompleted"));

                // 6. Registry & Finalize
                await _modelRegistry.RegisterAsync(experimentId, trainedModel, evaluationResult, cancellationToken);
                await _tracker.MarkExperimentCompletedAsync(experimentId, evaluationResult, stopwatch.Elapsed, cancellationToken);

                _logger.LogInformation("Experiment {ExperimentId} completed in {Elapsed}", experimentId, stopwatch.Elapsed);

                return new PipelineResult(
                    ExperimentId: experimentId,
                    ModelId: trainedModel.Id,
                    Evaluation: evaluationResult,
                    Duration: stopwatch.Elapsed);
            }
            catch (OperationCanceledException)
            {
                await _tracker.MarkExperimentCanceledAsync(experimentId, stopwatch.Elapsed, cancellationToken);
                _logger.LogWarning("Experiment {ExperimentId} canceled after {Elapsed}", experimentId, stopwatch.Elapsed);
                throw;
            }
            catch (Exception ex)
            {
                await _tracker.MarkExperimentFailedAsync(experimentId, ex, stopwatch.Elapsed, cancellationToken);
                _logger.LogError(ex, "Experiment {ExperimentId} failed after {Elapsed}", experimentId, stopwatch.Elapsed);
                throw;
            }
        }

        /// <summary>
        /// Publishes a pipeline event to the internal channel.
        /// </summary>
        private async Task PublishAsync(PipelineEvent pipelineEvent)
        {
            await _eventChannel.Writer.WriteAsync(pipelineEvent);
        }

        /// <summary>
        /// Drains events from an internal channel to the shared event bus.
        /// </summary>
        private static async Task PumpEventsToBusAsync(ChannelReader<PipelineEvent> reader, IEventBus bus, CancellationToken token)
        {
            await foreach (var evt in reader.ReadAllAsync(token))
            {
                await bus.PublishAsync(evt, token);
            }
        }

        public async ValueTask DisposeAsync()
        {
            _eventChannel.Writer.TryComplete();
            // Give ongoing publishing some time to finish.
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await PumpEventsToBusAsync(_eventChannel.Reader, _eventBus, cts.Token)
                  .ContinueWith(_ => { }, TaskScheduler.Default);
        }
    }

    #region Contracts

    public interface IPipelineOrchestrator
    {
        Task<PipelineResult> RunAsync(PipelineRequest request, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Encapsulates information required to run a pipeline.
    /// </summary>
    /// <param name="DatasetUri">Path/URI to input data.</param>
    /// <param name="Algorithm">Algorithm name (e.g., "StableDiffusion", "GAN").</param>
    /// <param name="PreprocessingBrushName">Identifier for preprocessing strategy.</param>
    /// <param name="FeaturePaletteName">Identifier for feature engineering strategy.</param>
    /// <param name="TuningWheelName">Identifier for hyperparameter tuning strategy.</param>
    /// <param name="EvaluationMetric">Primary evaluation metric.</param>
    public sealed record PipelineRequest(
        Uri DatasetUri,
        string Algorithm,
        string PreprocessingBrushName,
        string FeaturePaletteName,
        string TuningWheelName,
        string EvaluationMetric);

    /// <summary>
    /// Result of a completed pipeline run.
    /// </summary>
    public sealed record PipelineResult(
        Guid ExperimentId,
        Guid ModelId,
        EvaluationResult Evaluation,
        TimeSpan Duration);

    #endregion
}

```