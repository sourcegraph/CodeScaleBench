using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using Microsoft.Data.Analysis;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Pipeline.Steps.DataPreprocessing
{
    /// <summary>
    /// Represents a data–pre-processing “brush” that scales or standardises numeric
    /// columns in a <see cref="DataFrame"/> before model-training.
    /// 
    /// The brush is designed to be plugged into the Pipeline Pattern and selected
    /// at runtime via the Strategy / Factory patterns that the CanvasCraft MLOps
    /// runtime provides.
    /// </summary>
    public sealed class ScalingBrush : IDataPreprocessingBrush
    {
        private readonly ScalingBrushOptions _options;
        private readonly ILogger<ScalingBrush> _logger;
        private readonly IFeatureStore _featureStore;
        private readonly IExperimentTracker _experimentTracker;

        public ScalingBrush(
            ScalingBrushOptions options,
            ILogger<ScalingBrush> logger,
            IFeatureStore featureStore,
            IExperimentTracker experimentTracker)
        {
            _options            = options        ?? throw new ArgumentNullException(nameof(options));
            _logger             = logger         ?? throw new ArgumentNullException(nameof(logger));
            _featureStore       = featureStore   ?? throw new ArgumentNullException(nameof(featureStore));
            _experimentTracker  = experimentTracker ?? throw new ArgumentNullException(nameof(experimentTracker));
        }

        /// <summary>
        /// Applies the configured scaling transformation to the input <see cref="DataFrame"/>.
        /// </summary>
        /// <param name="input">The raw input dataset.</param>
        /// <param name="context">An experiment-run context carrying correlation + cancellation tokens.</param>
        /// <returns>The transformed frame.</returns>
        /// <exception cref="ArgumentNullException"></exception>
        /// <exception cref="InvalidOperationException"></exception>
        public DataFrame Transform(DataFrame input, ExperimentRunContext context)
        {
            if (input == null) throw new ArgumentNullException(nameof(input));
            context?.ThrowIfCancellationRequested();

            IReadOnlyList<DataFrameColumn> candidateColumns =
                ResolveTargetColumns(input, _options.TargetColumns);

            if (!candidateColumns.Any())
            {
                const string msg = "ScalingBrush encountered no numeric columns to operate on.";
                _logger.LogWarning(msg);
                throw new InvalidOperationException(msg);
            }

            var statisticsBag = new Dictionary<string, ColumnScalingStatistics>();

            foreach (var col in candidateColumns)
            {
                context?.ThrowIfCancellationRequested();
                _logger.LogDebug("Scaling column: {ColumnName}", col.Name);

                ColumnScalingStatistics stats = ComputeStatistics(col, _options.Strategy);
                DataFrameColumn scaled = ApplyScaling(col, stats, _options);

                // Replace column in the frame (DataFrame clones the column if name already exists)
                input.Columns.Remove(col);
                input.Columns.Insert(col.Index, scaled);

                statisticsBag[col.Name] = stats;
            }

            if (_options.PersistStatistics)
            {
                PersistAndLog(statisticsBag, context?.CancellationToken ?? CancellationToken.None);
            }

            _logger.LogInformation("ScalingBrush completed transformation on {ColumnCount} columns.", statisticsBag.Count);
            return input;
        }

        #region Helpers

        private IReadOnlyList<DataFrameColumn> ResolveTargetColumns(DataFrame frame, IReadOnlyList<string>? targets)
        {
            IEnumerable<DataFrameColumn> columns =
                targets is { Count: > 0 }
                    ? targets.Select(name => frame.Columns[name])
                    : frame.Columns.Where(IsNumericColumn);

            return columns.ToArray();
        }

        private static bool IsNumericColumn(DataFrameColumn column)
        {
            // PrimitiveDataFrameColumn<T> exposes DataType at runtime
            return column.DataType == typeof(float)  ||
                   column.DataType == typeof(double) ||
                   column.DataType == typeof(decimal)||
                   column.DataType == typeof(int)    ||
                   column.DataType == typeof(long);
        }

        private static ColumnScalingStatistics ComputeStatistics(DataFrameColumn column, ScalingStrategy strategy)
        {
            double[] data = column switch
            {
                PrimitiveDataFrameColumn<double> d => d.ToArray(),
                PrimitiveDataFrameColumn<float>  f => f.ToArray().Select(Convert.ToDouble).ToArray(),
                PrimitiveDataFrameColumn<int>    i => i.ToArray().Select(Convert.ToDouble).ToArray(),
                PrimitiveDataFrameColumn<long>   l => l.ToArray().Select(Convert.ToDouble).ToArray(),
                PrimitiveDataFrameColumn<decimal> m => m.ToArray().Select(Convert.ToDouble).ToArray(),
                _ => throw new NotSupportedException(
                    $"Column '{column.Name}' of type {column.DataType} is not supported for scaling.")
            };

            // Ignore NaN/Null records for statistics; downstream transformation will keep them as-is.
            double[] clean = data.Where(d => !double.IsNaN(d)).ToArray();
            if (clean.Length == 0)
                return new ColumnScalingStatistics(0, 1, 0, 0, 1);

            double min  = clean.Min();
            double max  = clean.Max();
            double mean = clean.Average();
            double std  = Math.Sqrt(clean.Sum(x => Math.Pow(x - mean, 2)) / clean.Length);

            Array.Sort(clean);
            double median = clean[clean.Length / 2];
            double q1     = clean[(int)(0.25 * clean.Length)];
            double q3     = clean[(int)(0.75 * clean.Length)];
            double iqr    = q3 - q1;

            return strategy switch
            {
                ScalingStrategy.Standard => new ColumnScalingStatistics(mean, std, min, max, 0),
                ScalingStrategy.MinMax   => new ColumnScalingStatistics(mean, std, min, max, 0),
                ScalingStrategy.MaxAbs   => new ColumnScalingStatistics(mean, std, min, max, 0),
                ScalingStrategy.Robust   => new ColumnScalingStatistics(median, iqr, min, max, 0),
                _ => throw new ArgumentOutOfRangeException(nameof(strategy), strategy, null)
            };
        }

        private static DataFrameColumn ApplyScaling(DataFrameColumn source,
                                                    ColumnScalingStatistics stats,
                                                    ScalingBrushOptions opts)
        {
            // Create new column with same name to preserve order.
            PrimitiveDataFrameColumn<double> scaled = new(source.Name, source.Length);

            for (int i = 0; i < source.Length; i++)
            {
                if (source.IsValid(i))
                {
                    double raw = Convert.ToDouble(source[i], CultureInfo.InvariantCulture);
                    double transformed = opts.Strategy switch
                    {
                        ScalingStrategy.Standard => Standardize(raw, stats.Mean, stats.Std),
                        ScalingStrategy.MinMax   => MinMaxScale(raw, stats.Min, stats.Max, opts.MinValue, opts.MaxValue),
                        ScalingStrategy.MaxAbs   => MaxAbsScale(raw, stats.Max),
                        ScalingStrategy.Robust   => RobustScale(raw, stats.Median, stats.Iqr),
                        _                        => raw
                    };
                    scaled[i] = transformed;
                }
                else
                {
                    scaled[i] = double.NaN;  // Preserve null semantics
                }
            }

            return scaled;
        }

        private void PersistAndLog(
            IReadOnlyDictionary<string, ColumnScalingStatistics> statisticsBag,
            CancellationToken cancellationToken)
        {
            // Persist statistics to Feature Store for reproducibility.
            foreach ((string column, ColumnScalingStatistics stats) in statisticsBag)
            {
                cancellationToken.ThrowIfCancellationRequested();
                
                _featureStore.PutFeatureStatistics(
                    column,
                    new NumericFeatureStats
                    {
                        Mean    = stats.Mean,
                        Std     = stats.Std,
                        Min     = stats.Min,
                        Max     = stats.Max,
                        Median  = stats.Median,
                        Iqr     = stats.Iqr
                    });

                _logger.LogDebug("Persisted scaling stats for column {ColumnName}", column);
            }

            // Log as experiment artifact.
            _experimentTracker.LogArtifact(
                "scaling_statistics.json",
                statisticsBag.ToDictionary(kvp => kvp.Key, kvp => kvp.Value),
                new Dictionary<string, object?>
                {
                    ["strategy"] = _options.Strategy.ToString(),
                    ["columns"]  = statisticsBag.Keys.ToArray()
                });
        }

        #endregion

        #region Static scaling functions

        private static double Standardize(double value, double mean, double std)
            => std == 0 ? 0 : (value - mean) / std;

        private static double MinMaxScale(double value, double min, double max, double targetMin, double targetMax)
            => max == min ? 0 : ((value - min) / (max - min)) * (targetMax - targetMin) + targetMin;

        private static double MaxAbsScale(double value, double maxAbs)
            => maxAbs == 0 ? 0 : value / Math.Abs(maxAbs);

        private static double RobustScale(double value, double median, double iqr)
            => iqr == 0 ? 0 : (value - median) / iqr;

        #endregion
    }

    #region Options / Stats POCOs

    /// <summary>
    /// Configuration record for <see cref="ScalingBrush"/>.
    /// </summary>
    public sealed record ScalingBrushOptions
    {
        /// <summary>Choice of scaling strategy. Default is <see cref="ScalingStrategy.Standard"/>.</summary>
        public ScalingStrategy Strategy { get; init; } = ScalingStrategy.Standard;

        /// <summary>
        /// Minimum value for Min-Max scaling (ignored for other strategies).
        /// </summary>
        public double MinValue { get; init; } = 0.0;

        /// <summary>
        /// Maximum value for Min-Max scaling (ignored for other strategies).
        /// </summary>
        public double MaxValue { get; init; } = 1.0;

        /// <summary>
        /// Explicit list of columns to scale; null or empty means “all numeric columns”.
        /// </summary>
        public IReadOnlyList<string>? TargetColumns { get; init; }

        /// <summary>
        /// When true, the brush persists scaling statistics to the Feature Store
        /// and logs them as experiment artifacts.
        /// </summary>
        public bool PersistStatistics { get; init; } = true;
    }

    /// <summary>
    /// Supported scaling strategies.
    /// </summary>
    public enum ScalingStrategy
    {
        Standard,   // Z-score
        MinMax,     // (x - min) / (max - min)
        MaxAbs,     // x / abs(max)
        Robust      // (x - median) / IQR
    }

    /// <summary>
    /// Captures summary statistics required to scale a single column.
    /// </summary>
    public readonly struct ColumnScalingStatistics
    {
        public ColumnScalingStatistics(double mean, double std, double min, double max, double median)
        {
            Mean   = mean;
            Std    = std;
            Min    = min;
            Max    = max;
            Median = median;
            Iqr    = std; // For compatibility; this constructor covers strategies that don't use IQR.
        }

        public ColumnScalingStatistics(double median, double iqr, double min, double max, byte _)
        {
            Mean   = 0;
            Std    = 0;
            Min    = min;
            Max    = max;
            Median = median;
            Iqr    = iqr;
        }

        public double Mean   { get; }
        public double Std    { get; }
        public double Min    { get; }
        public double Max    { get; }
        public double Median { get; }
        public double Iqr    { get; }
    }

    /// <summary>
    /// POCO sent to the Feature Store.
    /// </summary>
    public sealed class NumericFeatureStats
    {
        public double Mean   { get; init; }
        public double Std    { get; init; }
        public double Min    { get; init; }
        public double Max    { get; init; }
        public double Median { get; init; }
        public double Iqr    { get; init; }
    }

    #endregion

    #region Interfaces used by the brush (simplified for brevity)

    /// <summary>
    /// Contract for pipeline brushes.
    /// </summary>
    public interface IDataPreprocessingBrush
    {
        DataFrame Transform(DataFrame input, ExperimentRunContext context);
    }

    /// <summary>
    /// Represents a running experiment; carries tokens and context information.
    /// </summary>
    public sealed class ExperimentRunContext
    {
        public ExperimentRunContext(Guid runId, CancellationToken cancellationToken = default)
        {
            RunId             = runId;
            CancellationToken = cancellationToken;
        }

        public Guid RunId { get; }
        public CancellationToken CancellationToken { get; }

        public void ThrowIfCancellationRequested() => CancellationToken.ThrowIfCancellationRequested();
    }

    /// <summary>Contract to persist feature statistics.</summary>
    public interface IFeatureStore
    {
        void PutFeatureStatistics(string featureName, NumericFeatureStats stats);
    }

    /// <summary>Experiment/ML-flow style tracker.</summary>
    public interface IExperimentTracker
    {
        void LogArtifact(string name, object artifact, IDictionary<string, object?>? metadata = null);
    }

    #endregion
}