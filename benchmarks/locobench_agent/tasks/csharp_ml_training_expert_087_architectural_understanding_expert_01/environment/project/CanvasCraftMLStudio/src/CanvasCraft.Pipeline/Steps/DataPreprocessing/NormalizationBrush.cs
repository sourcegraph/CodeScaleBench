using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Analysis;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Pipeline.Steps.DataPreprocessing
{
    /// <summary>
    ///     Enumeration of supported normalization techniques.
    /// </summary>
    public enum NormalizationMethod
    {
        /// <summary>Standard score: (x - μ) / σ.</summary>
        ZScore,

        /// <summary>(x - min) / (max - min).</summary>
        MinMax,

        /// <summary>log(1 + x), commonly used for skewed data.</summary>
        Log1p
    }

    /// <summary>
    ///     Contract for all preprocessing brushes in the CanvasCraft pipeline.
    ///     A brush is a strategy that can mutate or copy the incoming <see cref="DataFrame" />.
    /// </summary>
    public interface IPreprocessingBrush
    {
        /// <summary>Name of the brush; surfaced to the experiment tracker.</summary>
        string Name { get; }

        /// <summary>Executes the preprocessing step.</summary>
        /// <param name="input">Input data frame.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>A new data frame—unless the brush is configured for in-place mutation.</returns>
        Task<DataFrame> ApplyAsync(DataFrame input, CancellationToken ct = default);
    }

    /// <summary>
    ///     Minimalistic experiment tracker interface.
    ///     The concrete implementation is provided by the Experiment-Tracking subsystem.
    /// </summary>
    public interface IExperimentTracker
    {
        void LogParameter(string stepName, string key, object value);
        void LogMetric(string stepName, string key, double value);
    }

    /// <summary>
    ///     A data-preprocessing brush that normalizes numeric columns using
    ///     one of several <see cref="NormalizationMethod">methods</see>.
    ///     Follows the Strategy pattern: interchangeable within the pipeline.
    /// </summary>
    public sealed class NormalizationBrush : IPreprocessingBrush
    {
        private readonly IEnumerable<string>? _targetColumns;
        private readonly bool _inPlace;
        private readonly bool _throwOnMissingColumn;
        private readonly ILogger<NormalizationBrush> _logger;
        private readonly IExperimentTracker? _tracker;

        public NormalizationMethod Method { get; }

        public string Name => nameof(NormalizationBrush);

        /// <summary>
        ///     Creates a new <see cref="NormalizationBrush" /> instance.
        /// </summary>
        /// <param name="method">The normalization algorithm to apply.</param>
        /// <param name="targetColumns">
        ///     Optional white-list of columns to transform.
        ///     When <c>null</c>, every numeric column is processed.
        /// </param>
        /// <param name="inPlace">
        ///     When <c>true</c> the input <see cref="DataFrame" /> is mutated; otherwise a deep copy is returned.
        /// </param>
        /// <param name="throwOnMissingColumn">
        ///     Determines whether a missing column in <paramref name="targetColumns" /> throws an exception.
        /// </param>
        /// <param name="logger">Structured logger instance.</param>
        /// <param name="tracker">Optional experiment-tracker for metadata logging.</param>
        public NormalizationBrush(
            NormalizationMethod method,
            IEnumerable<string>? targetColumns,
            bool inPlace,
            bool throwOnMissingColumn,
            ILogger<NormalizationBrush> logger,
            IExperimentTracker? tracker = null)
        {
            Method = method;
            _targetColumns = targetColumns?.ToArray();
            _inPlace = inPlace;
            _throwOnMissingColumn = throwOnMissingColumn;
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _tracker = tracker;
        }

        /// <inheritdoc />
        public async Task<DataFrame> ApplyAsync(DataFrame input, CancellationToken ct = default)
        {
            if (input == null) throw new ArgumentNullException(nameof(input));

            _logger.LogDebug("Starting {Brush} using {Method}. In-place: {InPlace}.", Name, Method, _inPlace);
            _tracker?.LogParameter(Name, "method", Method);
            _tracker?.LogParameter(Name, "in_place", _inPlace);

            // Defensive copy if the caller requested non-mutating behavior.
            var workingFrame = _inPlace ? input : input.Clone();

            // Determine target columns (fallback to all numeric columns).
            var columns = ResolveTargetColumns(workingFrame);

            // Perform transformation.
            var stats = new Dictionary<string, double[]>(capacity: columns.Count);
            await Parallel.ForEachAsync(columns, ct, (col, token) =>
            {
                try
                {
                    token.ThrowIfCancellationRequested();
                    ApplyNormalization(col, stats);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Normalization failed for column '{Column}'.", col.Name);
                    throw;
                }

                return ValueTask.CompletedTask;
            });

            // Record statistics in the experiment tracker.
            foreach (var (colName, values) in stats)
            {
                if (values.Length == 2)
                {
                    _tracker?.LogMetric(Name, $"{colName}_min", values[0]);
                    _tracker?.LogMetric(Name, $"{colName}_max", values[1]);
                }
                else if (values.Length == 3)
                {
                    _tracker?.LogMetric(Name, $"{colName}_mean", values[0]);
                    _tracker?.LogMetric(Name, $"{colName}_std", values[1]);
                    _tracker?.LogMetric(Name, $"{colName}_count", values[2]);
                }
            }

            _logger.LogInformation("{Brush} completed. {ColumnCount} columns normalized.",
                Name, columns.Count);

            return workingFrame;
        }

        #region Implementation details

        private IReadOnlyList<DataFrameColumn> ResolveTargetColumns(DataFrame frame)
        {
            if (_targetColumns == null)
            {
                return frame.Columns
                    .Where(c => c.DataType.IsNumericType())
                    .ToArray();
            }

            var columns = new List<DataFrameColumn>();
            foreach (var columnName in _targetColumns)
            {
                if (!frame.Columns.Contains(columnName))
                {
                    var message = $"Column '{columnName}' not found in DataFrame.";
                    if (_throwOnMissingColumn)
                    {
                        _logger.LogError(message);
                        throw new ArgumentException(message);
                    }

                    _logger.LogWarning(message);
                    continue;
                }

                var column = frame.Columns[columnName];
                if (!column.DataType.IsNumericType())
                {
                    _logger.LogWarning(
                        "Column '{Column}' is not numeric and will be skipped by {Brush}.",
                        columnName, Name);
                    continue;
                }

                columns.Add(column);
            }

            return columns;
        }

        private void ApplyNormalization(DataFrameColumn column, IDictionary<string, double[]> statSink)
        {
            switch (Method)
            {
                case NormalizationMethod.ZScore:
                    statSink[column.Name] = ZScoreNormalize(column);
                    break;

                case NormalizationMethod.MinMax:
                    statSink[column.Name] = MinMaxNormalize(column);
                    break;

                case NormalizationMethod.Log1p:
                    statSink[column.Name] = Log1p(column);
                    break;

                default:
                    throw new NotSupportedException(
                        $"Normalization method '{Method}' is not supported.");
            }
        }

        private static double[] ZScoreNormalize(DataFrameColumn column)
        {
            var numeric = column.ToDoubleColumn();

            var mean = numeric.Mean();
            var std = numeric.StdDev();

            if (std.Equals(0))
            {
                // Avoid division by zero; leave column untouched but warn caller.
                return new[] { mean, std, numeric.Length };
            }

            for (var i = 0; i < numeric.Length; i++)
            {
                if (numeric[i] is not double val || double.IsNaN(val)) continue;
                numeric[i] = (val - mean) / std;
            }

            return new[] { mean, std, numeric.Length };
        }

        private static double[] MinMaxNormalize(DataFrameColumn column)
        {
            var numeric = column.ToDoubleColumn();
            var min = numeric.Min();
            var max = numeric.Max();

            if (Math.Abs(max - min) < double.Epsilon)
            {
                // Degenerate distribution – set all values to 0
                for (var i = 0; i < numeric.Length; i++)
                {
                    if (numeric[i] is not double) continue;
                    numeric[i] = 0d;
                }

                return new[] { min, max };
            }

            for (var i = 0; i < numeric.Length; i++)
            {
                if (numeric[i] is not double val || double.IsNaN(val)) continue;
                numeric[i] = (val - min) / (max - min);
            }

            return new[] { min, max };
        }

        private static double[] Log1p(DataFrameColumn column)
        {
            var numeric = column.ToDoubleColumn();
            for (var i = 0; i < numeric.Length; i++)
            {
                if (numeric[i] is not double val || double.IsNaN(val)) continue;
                numeric[i] = Math.Log1p(val);
            }

            // Statistics for log1p don't add much value; still return count
            return new[] { numeric.Length };
        }

        #endregion
    }

    #region Helper extensions

    internal static class DataFrameExtensions
    {
        private static readonly HashSet<Type> NumericTypes = new()
        {
            typeof(byte), typeof(sbyte), typeof(short), typeof(ushort),
            typeof(int), typeof(uint), typeof(long), typeof(ulong),
            typeof(float), typeof(double), typeof(decimal)
        };

        /// <summary>
        ///     Checks whether the type is considered numeric for the purpose
        ///     of normalization.
        /// </summary>
        internal static bool IsNumericType(this Type type) => NumericTypes.Contains(type);

        /// <summary>
        ///     Converts a <see cref="DataFrameColumn" /> to a mutable
        ///     <see cref="PrimitiveDataFrameColumn{T}" /> of <see cref="Double" />.
        ///     This enables in-place modifications for any numeric type.
        ///     Non-numeric columns throw <see cref="InvalidOperationException" />.
        /// </summary>
        internal static PrimitiveDataFrameColumn<double> ToDoubleColumn(this DataFrameColumn column)
        {
            if (!column.DataType.IsNumericType())
                throw new InvalidOperationException(
                    $"Column '{column.Name}' is not numeric.");

            // Already double – no need to cast.
            if (column is PrimitiveDataFrameColumn<double> doubles) return doubles;

            // Fallback: clone with conversion to double.
            var converted = column.Cast<double>();
            column.DataFrame!.Columns.Remove(column);
            column.DataFrame!.Columns.Insert(column.Index, converted);
            return converted;
        }

        /// <summary>Computes the mean of a numeric column.</summary>
        internal static double Mean(this PrimitiveDataFrameColumn<double> column)
        {
            double sum = 0;
            long count = 0;

            foreach (var item in column)
            {
                if (double.IsNaN(item)) continue;
                sum += item;
                count++;
            }

            return count == 0 ? double.NaN : sum / count;
        }

        /// <summary>Standard deviation (population).</summary>
        internal static double StdDev(this PrimitiveDataFrameColumn<double> column)
        {
            var mean = column.Mean();
            if (double.IsNaN(mean)) return double.NaN;

            double sumSq = 0;
            long count = 0;

            foreach (var item in column)
            {
                if (double.IsNaN(item)) continue;
                sumSq += Math.Pow(item - mean, 2);
                count++;
            }

            return count == 0 ? double.NaN : Math.Sqrt(sumSq / count);
        }
    }

    #endregion
}

