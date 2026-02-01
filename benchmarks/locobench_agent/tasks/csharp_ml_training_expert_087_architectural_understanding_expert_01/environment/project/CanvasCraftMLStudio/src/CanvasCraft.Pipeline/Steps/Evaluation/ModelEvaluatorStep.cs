```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/Evaluation/ModelEvaluatorStep.cs

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Abstractions;
using CanvasCraft.Core.Events;
using CanvasCraft.ModelRegistry.Abstractions;
using CanvasCraft.Pipeline.Abstractions;
using CanvasCraft.Tracking.Abstractions;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Pipeline.Steps.Evaluation
{
    /// <summary>
    /// Pipeline step that evaluates a trained model against a hold-out evaluation dataset,
    /// logs metrics to the experiment tracker, updates the model registry and publishes
    /// a <see cref="ModelEvaluatedEvent"/> for reactive stakeholders.
    /// </summary>
    public sealed class ModelEvaluatorStep : IPipelineStep
    {
        private readonly IEnumerable<IEvaluationMetric> _metrics;
        private readonly IExperimentTracker _experimentTracker;
        private readonly IModelRegistryClient _modelRegistry;
        private readonly IEventBus _eventBus;
        private readonly ILogger<ModelEvaluatorStep> _logger;

        public string Name => "Model Evaluation";

        public ModelEvaluatorStep(
            IEnumerable<IEvaluationMetric> metrics,
            IExperimentTracker experimentTracker,
            IModelRegistryClient modelRegistry,
            IEventBus eventBus,
            ILogger<ModelEvaluatorStep> logger)
        {
            _metrics = metrics ?? throw new ArgumentNullException(nameof(metrics));
            _experimentTracker = experimentTracker ?? throw new ArgumentNullException(nameof(experimentTracker));
            _modelRegistry = modelRegistry ?? throw new ArgumentNullException(nameof(modelRegistry));
            _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <inheritdoc />
        public async Task<PipelineStepResult> ExecuteAsync(
            PipelineContext context,
            CancellationToken cancellationToken = default)
        {
            if (context == null) throw new ArgumentNullException(nameof(context));

            // Ensure we have the required artifacts on the pipeline context
            if (!context.TryGet<ITrainedModel>(PipelineContextKeys.ActiveModel, out var model) || model == null)
            {
                const string message = "Evaluation failed: no trained model found in pipeline context.";
                _logger.LogError(message);
                return PipelineStepResult.Failed(message);
            }

            if (!context.TryGet<IDataFrame>(PipelineContextKeys.EvaluationFrame, out var evaluationData) ||
                evaluationData == null || evaluationData.IsEmpty)
            {
                const string message = "Evaluation failed: no evaluation dataset found in pipeline context.";
                _logger.LogError(message);
                return PipelineStepResult.Failed(message);
            }

            try
            {
                _logger.LogInformation("⏳ Starting model evaluation of model '{ModelId}'.", model.ModelId);

                // Perform batched prediction
                IEnumerable<ModelPrediction> predictions =
                    await model.PredictBatchAsync(evaluationData, cancellationToken)
                               .ConfigureAwait(false);

                // Compute all requested metrics
                var metricResults = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
                foreach (var metric in _metrics)
                {
                    double value = metric.Calculate(predictions, evaluationData.LabelColumnName);
                    metricResults[metric.Name] = value;
                    _logger.LogInformation("• {MetricName}: {MetricValue:N4}", metric.Name, value);

                    await _experimentTracker.LogMetricAsync(
                            experimentId: context.ExperimentId,
                            metricName: metric.Name,
                            value,
                            cancellationToken)
                        .ConfigureAwait(false);
                }

                // Persist evaluation artifacts to the model registry
                await _modelRegistry.AppendEvaluationAsync(
                        model.ModelId,
                        new ModelEvaluationRecord(
                            evaluatedAtUtc: DateTime.UtcNow,
                            metrics: metricResults,
                            datasetFingerprint: evaluationData.Fingerprint),
                        cancellationToken)
                    .ConfigureAwait(false);

                // Notify observers
                var evaluationEvent = new ModelEvaluatedEvent(
                    modelId: model.ModelId,
                    metrics: metricResults,
                    experimentId: context.ExperimentId);
                await _eventBus.PublishAsync(evaluationEvent, cancellationToken).ConfigureAwait(false);

                _logger.LogInformation("✅ Model evaluation completed successfully for model '{ModelId}'.", model.ModelId);

                // Attach results to the pipeline context for downstream steps
                context.Set(PipelineContextKeys.EvaluationMetrics, metricResults);

                return PipelineStepResult.Success(
                    output: new Dictionary<string, object>
                    {
                        [PipelineContextKeys.EvaluationMetrics] = metricResults
                    });
            }
            catch (OperationCanceledException)
            {
                const string message = "Model evaluation cancelled by user.";
                _logger.LogWarning(message);
                return PipelineStepResult.Cancelled(message);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "❌ An unhandled exception occurred while evaluating the model.");
                return PipelineStepResult.Failed($"Unhandled exception during model evaluation: {ex.Message}");
            }
        }
    }

    #region Supporting abstractions (internal contracts)

    // NOTE: These are minimal interfaces required by the step. In the actual
    // solution they are defined elsewhere; they are reproduced here only to
    // make the file self-contained and compile-time safe.

    public interface IEvaluationMetric
    {
        string Name { get; }
        double Calculate(IEnumerable<ModelPrediction> predictions, string labelColumn);
    }

    public interface IExperimentTracker
    {
        Task LogMetricAsync(Guid experimentId, string metricName, double metricValue,
            CancellationToken token = default);
    }

    public interface IModelRegistryClient
    {
        Task AppendEvaluationAsync(Guid modelId, ModelEvaluationRecord record,
            CancellationToken token = default);
    }

    public interface IEventBus
    {
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken token = default) where TEvent : class;
    }

    public interface ITrainedModel
    {
        Guid ModelId { get; }
        Task<IEnumerable<ModelPrediction>> PredictBatchAsync(IDataFrame data, CancellationToken token = default);
    }

    public interface IDataFrame
    {
        bool IsEmpty { get; }
        string LabelColumnName { get; }
        string Fingerprint { get; }
    }

    public record ModelPrediction(object? PredictedLabel, double[]? Probabilities, IDictionary<string, object>? Metadata);

    public record ModelEvaluationRecord(DateTime evaluatedAtUtc, IDictionary<string, double> metrics, string datasetFingerprint);

    /// <summary>Key constants used to store/retrieve data from <see cref="PipelineContext"/>.</summary>
    public static class PipelineContextKeys
    {
        public const string ActiveModel = "pipeline.activeModel";
        public const string EvaluationFrame = "pipeline.evaluationFrame";
        public const string EvaluationMetrics = "pipeline.evaluationMetrics";
    }

    #endregion
}
```