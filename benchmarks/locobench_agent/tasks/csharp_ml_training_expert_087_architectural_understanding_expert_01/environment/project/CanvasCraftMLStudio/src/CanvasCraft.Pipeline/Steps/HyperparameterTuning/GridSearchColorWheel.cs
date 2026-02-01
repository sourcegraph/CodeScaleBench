```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/HyperparameterTuning/GridSearchColorWheel.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.ML;
using Microsoft.ML.Data;

namespace CanvasCraft.Pipeline.Steps.HyperparameterTuning
{
    #region Contracts & Utilities

    /// <summary>
    /// Simple abstraction over whatever experiment tracking system the studio uses.
    /// Replacing this interface allows us to integrate with MLflow, Azure ML, Weights & Biases, etc.
    /// </summary>
    public interface IExperimentTracker
    {
        Task LogMetricAsync(string experimentName,
                            string runId,
                            string metricName,
                            double metricValue,
                            CancellationToken ct = default);

        Task LogArtifactAsync(string experimentName,
                              string runId,
                              string artifactPath,
                              CancellationToken ct = default);
    }

    /// <summary>
    /// Simple abstraction over the studio’s model registry.
    /// </summary>
    public interface IModelRegistry
    {
        Task RegisterAsync(string modelName,
                           ITransformer model,
                           DataViewSchema inputSchema,
                           IReadOnlyDictionary<string, object> metadata,
                           CancellationToken ct = default);
    }

    /// <summary>
    /// Represents a single hyper-parameter and the discrete set of values
    /// that should be explored during the grid-search.
    /// </summary>
    /// <param name="Name">Unique name of the hyper-parameter.</param>
    /// <param name="Values">Concrete values to try.</param>
    public record HyperparameterSpec(string Name, IEnumerable<object> Values);

    /// <summary>
    /// Concrete set of hyper-parameter selections (one value per parameter).
    /// </summary>
    public record HyperparameterSet(IReadOnlyDictionary<string, object> Values)
    {
        public override string ToString() =>
            string.Join(", ", Values.Select(kv => $"{kv.Key}={kv.Value}", CultureInfo.InvariantCulture));
    }

    /// <summary>
    /// Helper DTO encapsulating one evaluation run.
    /// </summary>
    internal sealed record EvaluationResult(HyperparameterSet Hyperparameters,
                                            double Score,
                                            bool HigherIsBetter);

    #endregion

    /// <summary>
    /// Grid-search tuner (a.k.a. “color wheel”) that systematically sweeps a hyper-parameter grid,
    /// trains models, and tracks experiment metrics.  Uses ML.NET for training/evaluation but can be
    /// adapted to any backend by swapping the estimator factory delegate.
    /// </summary>
    public sealed class GridSearchColorWheel
    {
        private readonly MLContext _ml;
        private readonly ILogger<GridSearchColorWheel> _logger;
        private readonly IExperimentTracker _tracker;
        private readonly IModelRegistry _registry;

        /// <summary>
        /// Initializes a new instance of the <see cref="GridSearchColorWheel"/> class.
        /// </summary>
        public GridSearchColorWheel(MLContext mlContext,
                                    ILogger<GridSearchColorWheel> logger,
                                    IExperimentTracker tracker,
                                    IModelRegistry registry)
        {
            _ml       = mlContext  ?? throw new ArgumentNullException(nameof(mlContext));
            _logger   = logger     ?? throw new ArgumentNullException(nameof(logger));
            _tracker  = tracker    ?? throw new ArgumentNullException(nameof(tracker));
            _registry = registry   ?? throw new ArgumentNullException(nameof(registry));
        }

        /// <summary>
        /// Executes a synchronous grid-search over the supplied hyper-parameter space.  The caller
        /// provides an <paramref name="estimatorFactory"/> that converts a concrete hyper-parameter
        /// set into an ML.NET <see cref="IEstimator{ITransformer}"/>.
        /// </summary>
        /// <remarks>
        /// The method is task-based and cancellation-aware so it can be orchestrated by the larger
        /// MVC/MLOps pipeline without blocking threads.
        /// </remarks>
        /// <param name="trainData">The training dataset.</param>
        /// <param name="estimatorFactory">
        /// User-supplied factory that builds an ML.NET estimator from a
        /// <see cref="HyperparameterSet"/>.
        /// </param>
        /// <param name="experimentName">Name of the high-level experiment (used by the tracker).</param>
        /// <param name="hyperparameterSpace">Grid definition.</param>
        /// <param name="labelColumn">Name of the label column.</param>
        /// <param name="cvFolds">Number of cross-validation folds.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>The best model trained on the full dataset.</returns>
        public async Task<ITransformer> ExecuteAsync(
            IDataView trainData,
            Func<HyperparameterSet, IEstimator<ITransformer>> estimatorFactory,
            string experimentName,
            IEnumerable<HyperparameterSpec> hyperparameterSpace,
            string labelColumn,
            int cvFolds = 5,
            CancellationToken ct = default)
        {
            if (trainData            is null) throw new ArgumentNullException(nameof(trainData));
            if (estimatorFactory     is null) throw new ArgumentNullException(nameof(estimatorFactory));
            if (hyperparameterSpace  is null) throw new ArgumentNullException(nameof(hyperparameterSpace));
            if (string.IsNullOrWhiteSpace(labelColumn)) throw new ArgumentException("Label column cannot be null/empty.", nameof(labelColumn));

            _logger.LogInformation("🎨 Starting grid-search color wheel: {Experiment}", experimentName);

            var parameterGrid  = ExpandHyperparameterSpace(hyperparameterSpace).ToList();
            var results        = new ConcurrentBag<EvaluationResult>();

            _logger.LogInformation("🖌️  Exploring {Count} hyper-parameter combinations…", parameterGrid.Count);

            // Degree of parallelism deliberately capped so the outer orchestrator can scale instances.
            var parallelOptions = new ParallelOptions
            {
                CancellationToken = ct,
                MaxDegreeOfParallelism = Math.Max(Environment.ProcessorCount - 1, 1)
            };

            await Task.Run(() =>
            {
                Parallel.ForEach(parameterGrid, parallelOptions, parameterSet =>
                {
                    ct.ThrowIfCancellationRequested();

                    string runId = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);

                    try
                    {
                        var estimator = estimatorFactory(parameterSet);
                        double score  = CrossValidateAndScore(trainData, estimator, labelColumn, cvFolds, out bool higherIsBetter);

                        _logger.LogInformation("🎯 [{Run}] {Params} → Score={Score:F4}",
                                               runId, parameterSet, score);

                        results.Add(new EvaluationResult(parameterSet, score, higherIsBetter));

                        // Fire-and-forget tracker logging (don’t await inside parallel loop).
                        _ = _tracker.LogMetricAsync(experimentName, runId, "Score", score, ct);
                        _ = _tracker.LogArtifactAsync(experimentName, runId, parameterSet.ToString(), ct);
                    }
                    catch (OperationCanceledException) { /* re-thrown below */ }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, "❌ Failure during grid-search run for {Params}", parameterSet);
                    }
                });
            }, ct);

            ct.ThrowIfCancellationRequested();

            // Pick the best result respecting the metric direction.
            EvaluationResult? best = results
                .OrderByDescending(r => r.HigherIsBetter ? r.Score : -r.Score)
                .FirstOrDefault();

            if (best is null)
                throw new InvalidOperationException("No successful grid-search runs were completed.");

            _logger.LogInformation("✅ Best parameters: {Params}", best.Hyperparameters);

            // Train final model on full dataset
            var bestEstimator = estimatorFactory(best.Hyperparameters);
            ITransformer finalModel = bestEstimator.Fit(trainData);

            // Register model with metadata
            await _registry.RegisterAsync(
                modelName: $"{experimentName}_Best",
                model: finalModel,
                inputSchema: trainData.Schema,
                metadata: best.Hyperparameters.Values.ToDictionary(kv => kv.Key, kv => kv.Value),
                ct);

            return finalModel;
        }

        #region Internal helpers

        /// <summary>
        /// Generates the Cartesian product of the supplied hyper-parameter grid definitions.
        /// </summary>
        private static IEnumerable<HyperparameterSet> ExpandHyperparameterSpace(IEnumerable<HyperparameterSpec> specs)
        {
            IReadOnlyList<HyperparameterSpec> specList = specs.ToList();
            if (specList.Count == 0) yield break;

            IEnumerable<HyperparameterSet> seed = new[]
            {
                new HyperparameterSet(new Dictionary<string, object>())
            };

            foreach (var spec in specList)
            {
                seed = from combo in seed
                       from value in spec.Values
                       select new HyperparameterSet(
                           new Dictionary<string, object>(combo.Values)
                           {
                               [spec.Name] = value
                           });
            }

            foreach (var combination in seed)
                yield return combination;
        }

        /// <summary>
        /// Performs k-fold cross-validation to obtain a single evaluation metric for a given estimator.
        /// Automatically detects the problem type (binary/multi classification or regression) by
        /// inspecting the label column type.
        /// </summary>
        private double CrossValidateAndScore(IDataView data,
                                             IEstimator<ITransformer> estimator,
                                             string labelColumn,
                                             int cvFolds,
                                             out bool higherIsBetter)
        {
            var labelType = data.Schema[labelColumn].Type;

            if (labelType is BooleanDataViewType)
            {
                var cv = _ml.BinaryClassification.CrossValidate(data, estimator, numberOfFolds: cvFolds, labelColumnName: labelColumn);
                higherIsBetter = true;
                return cv.Select(r => r.Metrics.Accuracy).Average();
            }

            if (labelType is KeyDataViewType)
            {
                var cv = _ml.MulticlassClassification.CrossValidate(data, estimator, numberOfFolds: cvFolds, labelColumnName: labelColumn);
                higherIsBetter = true;
                return cv.Select(r => r.Metrics.MacroAccuracy).Average();
            }

            if (labelType is NumberDataViewType)
            {
                var cv = _ml.Regression.CrossValidate(data, estimator, numberOfFolds: cvFolds, labelColumnName: labelColumn);
                higherIsBetter = false; // Lower RMSE is better
                return cv.Select(r => r.Metrics.RootMeanSquaredError).Average();
            }

            throw new NotSupportedException($"Unsupported label column type: {labelType}");
        }

        #endregion
    }
}
```