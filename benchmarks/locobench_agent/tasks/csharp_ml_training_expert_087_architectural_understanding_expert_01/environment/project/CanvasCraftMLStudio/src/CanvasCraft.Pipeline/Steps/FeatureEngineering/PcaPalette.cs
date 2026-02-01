```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/FeatureEngineering/PcaPalette.cs

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using CanvasCraft.Common;
using CanvasCraft.ExperimentTracking;
using MathNet.Numerics.LinearAlgebra;
using MathNet.Numerics.LinearAlgebra.Double;

namespace CanvasCraft.Pipeline.Steps.FeatureEngineering
{
    /// <summary>
    /// Principal-Component-Analysis “palette” that can be plugged into the CanvasCraft
    /// MLOps pipeline at feature-engineering time.  The palette learns a
    /// transformation (Fit) and then applies it to input data (Transform),
    /// replacing or appending PCA components to the feature matrix.
    /// </summary>
    public sealed class PcaPalette : IFeatureEngineeringStep, IDisposable
    {
        private readonly PcaPaletteOptions _options;
        private Vector<double>? _meanVector;
        private Matrix<double>? _components; // Columns = principal axes (eigenvectors)
        private Vector<double>? _explainedVariance;
        private bool _isFitted;

        public string Name => nameof(PcaPalette);

        public PcaPalette(PcaPaletteOptions options)
        {
            _options = options ?? throw new ArgumentNullException(nameof(options));
        }

        #region IFeatureEngineeringStep

        public void Fit(IPipelineContext context)
        {
            if (context == null) throw new ArgumentNullException(nameof(context));
            var frame = context.Data;

            string[] selectedColumns = SelectColumns(frame);
            var data = DenseMatrix.OfArray(frame.ToNumericMatrix(selectedColumns));

            if (data.RowCount == 0 || data.ColumnCount == 0)
                throw new InvalidOperationException("Input data for PCA contains no numeric values.");

            // Center the data
            _meanVector = data.ColumnSums() / data.RowCount;
            Center(data, _meanVector);

            // Compute covariance
            var covariance = (data.TransposeThisAndMultiply(data)) / (data.RowCount - 1);

            // Eigen decomposition
            var evd = covariance.Evd(Symmetricity.Symmetric);
            var eigenValues = evd.EigenValues.Real();
            var eigenVectors = evd.EigenVectors;

            // Sort descending by eigenvalue
            var sorted = eigenValues
                         .Select((val, idx) => (val, idx))
                         .OrderByDescending(t => t.val)
                         .ToList();

            var orderedValues = DenseVector.OfEnumerable(sorted.Select(s => s.val));
            var orderedVectors = DenseMatrix.Build.Dense(
                eigenVectors.RowCount,
                eigenVectors.ColumnCount,
                (i, j) => eigenVectors[i, sorted[j].idx]);

            // Decide how many components to keep
            int k = DetermineComponentCount(orderedValues);
            _components = orderedVectors.SubMatrix(0, orderedVectors.RowCount, 0, k);
            _explainedVariance = orderedValues.SubVector(0, k);

            _isFitted = true;

            LogFitMetrics(context, orderedValues, k);
        }

        public void Transform(IPipelineContext context)
        {
            EnsureFitted();
            if (context == null) throw new ArgumentNullException(nameof(context));

            var frame = context.Data;
            string[] selectedColumns = SelectColumns(frame);
            var data = DenseMatrix.OfArray(frame.ToNumericMatrix(selectedColumns));

            // Apply mean centering
            Center(data, _meanVector!);

            // Projection
            var transformed = data * _components!;

            // Persist back to data frame
            AppendComponents(frame, transformed);
            if (_options.ReplaceOriginalColumns)
            {
                frame.RemoveColumns(selectedColumns);
            }
        }

        public void FitTransform(IPipelineContext context)
        {
            Fit(context);
            Transform(context);
        }

        #endregion

        #region Disposal

        public void Dispose()
        {
            _components = null;
            _meanVector = null;
            _explainedVariance = null;
        }

        #endregion

        #region Helper logic

        private static void Center(Matrix<double> m, Vector<double> mean)
        {
            for (int i = 0; i < m.RowCount; i++)
            {
                for (int j = 0; j < m.ColumnCount; j++)
                {
                    m[i, j] -= mean[j];
                }
            }
        }

        private int DetermineComponentCount(Vector<double> eigenValues)
        {
            if (_options.ComponentsCount.HasValue)
                return Math.Min(_options.ComponentsCount.Value, eigenValues.Count);

            double total = eigenValues.Sum();
            double cumulative = 0.0;
            for (int i = 0; i < eigenValues.Count; i++)
            {
                cumulative += eigenValues[i];
                if (cumulative / total >= _options.VarianceThreshold)
                    return i + 1;
            }

            return eigenValues.Count;
        }

        private static void AppendComponents(IDataFrame frame, Matrix<double> transformed)
        {
            for (int j = 0; j < transformed.ColumnCount; j++)
            {
                var col = new double[transformed.RowCount];
                for (int i = 0; i < transformed.RowCount; i++)
                    col[i] = transformed[i, j];

                frame.AddColumn($"pca_{j + 1}", col);
            }
        }

        private void LogFitMetrics(IPipelineContext context, Vector<double> orderedValues, int k)
        {
            double total = orderedValues.Sum();
            double retained = orderedValues.SubVector(0, k).Sum();
            double ratio = retained / total;

            context.Logger?.Info($"[PCA] Retained {k} components explaining {ratio:P2} variance.");

            context.ExperimentTracker?.LogMetric(new ExperimentMetric
            {
                Step = Name,
                MetricName = "pca_explained_variance_ratio",
                Value = ratio,
                Tags = new Dictionary<string, string>
                {
                    { "components", k.ToString() },
                    { "variance_threshold", _options.VarianceThreshold.ToString("0.##") }
                }
            });
        }

        private string[] SelectColumns(IDataFrame frame)
        {
            IEnumerable<string> columns = _options.IncludeColumns?.Any() == true
                ? _options.IncludeColumns
                : frame.Columns;

            if (_options.ExcludeColumns?.Any() == true)
                columns = columns.Except(_options.ExcludeColumns);

            return columns.ToArray();
        }

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private void EnsureFitted()
        {
            if (!_isFitted)
                throw new InvalidOperationException("PcaPalette must be fitted before calling Transform.");
        }

        #endregion
    }

    #region Options class

    public sealed class PcaPaletteOptions
    {
        /// <summary>
        /// Desired cumulative variance ratio to retain.
        /// Ignored if <see cref="ComponentsCount"/> is provided.
        /// </summary>
        public double VarianceThreshold { get; init; } = 0.95;

        /// <summary>
        /// Optional explicit number of components to keep.
        /// </summary>
        public int? ComponentsCount { get; init; }

        /// <summary>
        /// Column names that must be included in the PCA transform.
        /// If null or empty, all numeric columns are considered.
        /// </summary>
        public string[]? IncludeColumns { get; init; }

        /// <summary>
        /// Column names to explicitly exclude from the PCA transform.
        /// </summary>
        public string[]? ExcludeColumns { get; init; }

        /// <summary>
        /// Replace the original feature columns with PCA components.
        /// </summary>
        public bool ReplaceOriginalColumns { get; init; } = false;
    }

    #endregion

    #region Interfaces & stubs

    // The following minimal interfaces represent other CanvasCraft subsystems.
    // They are intentionally lightweight so this file can compile in isolation;
    // in the real codebase, they are supplied by dedicated assemblies.

    public interface IFeatureEngineeringStep
    {
        string Name { get; }
        void Fit(IPipelineContext context);
        void Transform(IPipelineContext context);
        void FitTransform(IPipelineContext context);
    }

    public interface IPipelineContext
    {
        IDataFrame Data { get; }
        IDictionary<string, object> Artifacts { get; }
        ILogger? Logger { get; }
        IExperimentTracker? ExperimentTracker { get; }
    }

    public interface IDataFrame
    {
        IEnumerable<string> Columns { get; }
        int RowCount { get; }

        /// <summary>
        /// Extracts a 2-D numeric array for the specified columns.
        /// All rows are returned.
        /// </summary>
        double[,] ToNumericMatrix(IEnumerable<string> columns);

        /// <summary>
        /// Adds a new column or replaces an existing column.
        /// </summary>
        void AddColumn(string name, double[] values);

        /// <summary>
        /// Removes columns from the frame.
        /// </summary>
        void RemoveColumns(IEnumerable<string> names);
    }

    public interface ILogger
    {
        void Info(string message);
        void Warn(string message);
        void Error(string message, Exception ex);
    }

    public interface IExperimentTracker
    {
        void LogMetric(ExperimentMetric metric);
    }

    public sealed class ExperimentMetric
    {
        public string Step { get; init; } = string.Empty;
        public string MetricName { get; init; } = string.Empty;
        public double Value { get; init; }
        public IDictionary<string, string>? Tags { get; init; }
    }

    #endregion
}
```