```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Transformer/Transformers/Gpu/GpuDataFrameProcessor.cs

using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Analysis;
using Microsoft.Extensions.Logging;

#if FEATURE_COMPUTE_SHARP
using ComputeSharp;
using ComputeSharp.__Internals; // AutoConstructor attribute
#endif

namespace PaletteStream.Transformer.Transformers.Gpu
{
    /// <summary>
    /// Contract for components that can post–process a <see cref="DataFrame"/> leveraging
    /// GPU acceleration when available.
    /// </summary>
    public interface IGpuDataFrameProcessor
    {
        /// <summary>
        /// Calculates numeric statistics for every numeric column in the supplied <see cref="DataFrame"/>.
        /// </summary>
        /// <param name="frame">Data to process.</param>
        /// <param name="token">Cancellation token.</param>
        /// <returns>A collection of <see cref="ColumnStatistics"/> objects.</returns>
        Task<IReadOnlyList<ColumnStatistics>> ComputeStatisticsAsync(DataFrame frame, CancellationToken token = default);
    }

    /// <summary>
    /// Default implementation of <see cref="IGpuDataFrameProcessor"/> that uses <c>ComputeSharp</c> when a suitable
    /// GPU device is detected, and gracefully falls back to CPU/Vectorized LINQ otherwise.
    /// </summary>
    public sealed class GpuDataFrameProcessor : IGpuDataFrameProcessor
    {
        private readonly ILogger<GpuDataFrameProcessor> _logger;

        // Threshold to decide when to use the GPU path (number of rows).
        private const long MIN_ROWS_FOR_GPU = 100_000;

        public GpuDataFrameProcessor(ILogger<GpuDataFrameProcessor> logger)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region IGpuDataFrameProcessor

        /// <inheritdoc />
        public async Task<IReadOnlyList<ColumnStatistics>> ComputeStatisticsAsync(
            DataFrame frame,
            CancellationToken token = default)
        {
            if (frame is null) throw new ArgumentNullException(nameof(frame));
            if (frame.Rows.Count == 0) return Array.Empty<ColumnStatistics>();

            // Run IO-bound validation asynchronously.
            await ValidateFrameAsync(frame, token).ConfigureAwait(false);

            var sw = Stopwatch.StartNew();
            IReadOnlyList<ColumnStatistics> result =
                ShouldUseGpu(frame)
                    ? await ComputeOnGpuAsync(frame, token).ConfigureAwait(false)
                    : await ComputeOnCpuAsync(frame, token).ConfigureAwait(false);

            _logger.LogInformation(
                "Computed statistics for {ColumnCount} columns ({RowCount} rows) in {ElapsedMilliseconds}ms using {Path}.",
                result.Count,
                frame.Rows.Count,
                sw.ElapsedMilliseconds,
                ShouldUseGpu(frame) ? "GPU" : "CPU");

            return result;
        }

        #endregion

        #region GPU PATH

#if FEATURE_COMPUTE_SHARP
        /// <summary>
        /// Compute shader that calculates min, max and sum (for mean) in parallel.
        /// </summary>
        /// <typeparam name="T">Numeric type (must be unmanaged).</typeparam>
        [AutoConstructor]
        internal readonly partial struct MinMaxSumShader<T> : IComputeShader
            where T : unmanaged, INumber<T>
        {
            // Injected by AutoConstructor
            private readonly ReadOnlyBuffer<T> _input;

            // Output buffers
            private readonly ReadWriteBuffer<T> _minOut;
            private readonly ReadWriteBuffer<T> _maxOut;
            private readonly ReadWriteBuffer<double> _sumOut;

            /// <inheritdoc/>
            public void Execute()
            {
                var id = ThreadIds.X;

                var value = _input[id];

                // Atomic min/max reductions
                AtomicMin(ref _minOut[0], value);
                AtomicMax(ref _maxOut[0], value);

                // Sum in double for accuracy
                AtomicAdd(ref _sumOut[0], double.CreateChecked(value));
            }
        }
#endif

        private async Task<IReadOnlyList<ColumnStatistics>> ComputeOnGpuAsync(
            DataFrame frame,
            CancellationToken token)
        {
#if FEATURE_COMPUTE_SHARP
            if (!GraphicsDevice.EnumerateDevices().Any(d => d.IsSupported))
            {
                _logger.LogWarning("No compatible GPU found – falling back to CPU.");
                return await ComputeOnCpuAsync(frame, token).ConfigureAwait(false);
            }

            var device = GraphicsDevice.GetDefault();
            var results = new ConcurrentBag<ColumnStatistics>();

            var tasks = GetNumericColumns(frame)
                .Select(col => Task.Run(() =>
                {
                    var count = col.Length;
                    if (count == 0) return;

                    using ReadOnlyBuffer<double> input = device.AllocateReadOnly(col.ToDoubleArray());
                    using ReadWriteBuffer<double> minOut = device.AllocateReadWrite<double>(1);
                    using ReadWriteBuffer<double> maxOut = device.AllocateReadWrite<double>(1);
                    using ReadWriteBuffer<double> sumOut = device.AllocateReadWrite<double>(1);

                    // Initialize min/max with first value
                    minOut[0] = double.PositiveInfinity;
                    maxOut[0] = double.NegativeInfinity;
                    sumOut[0] = 0d;

                    device.For(count, new MinMaxSumShader<double>(input, minOut, maxOut, sumOut));

                    // Device -> CPU sync
                    device.Synchronize();

                    double min = minOut[0];
                    double max = maxOut[0];
                    double mean = sumOut[0] / count;

                    results.Add(new ColumnStatistics(col.Name, min, max, mean));
                }, token));

            await Task.WhenAll(tasks).ConfigureAwait(false);
            return results.OrderBy(r => r.ColumnName).ToArray();
#else
            // ComputeSharp not compiled in
            _logger.LogWarning("GPU path requested but ComputeSharp is not enabled. Falling back to CPU.");
            return await ComputeOnCpuAsync(frame, token).ConfigureAwait(false);
#endif
        }

        #endregion

        #region CPU PATH

        private static async Task<IReadOnlyList<ColumnStatistics>> ComputeOnCpuAsync(
            DataFrame frame,
            CancellationToken token)
        {
            // Use parallel LINQ for large workloads
            var numericColumns = GetNumericColumns(frame);

            var results = await Task
                .Run(() =>
                {
                    return numericColumns
                        .AsParallel()
                        .WithCancellation(token)
                        .Select(col =>
                        {
                            var vector = col.ToDoubleArray();
                            double min = vector.Min();
                            double max = vector.Max();
                            double mean = vector.Average();
                            return new ColumnStatistics(col.Name, min, max, mean);
                        })
                        .ToArray();
                }, token)
                .ConfigureAwait(false);

            return results;
        }

        #endregion

        #region Helpers

        private static IEnumerable<PrimitiveDataFrameColumn<double>> GetNumericColumns(DataFrame frame)
        {
            // At present we normalise all numerics to double for simplicity.
            foreach (var column in frame.Columns)
            {
                if (column.DataType == typeof(double))
                {
                    yield return (PrimitiveDataFrameColumn<double>)column;
                }
                else if (column.DataType == typeof(float)    ||
                         column.DataType == typeof(int)      ||
                         column.DataType == typeof(long)     ||
                         column.DataType == typeof(short)    ||
                         column.DataType == typeof(byte)     ||
                         column.DataType == typeof(decimal))
                {
                    // Convert to double column on the fly
                    yield return column.Clone(numberFormat: null).Cast<double>();
                }
            }
        }

        private static bool ShouldUseGpu(DataFrame frame)
        {
#if FEATURE_COMPUTE_SHARP
            // Heuristic: big enough + has GPU
            return frame.Rows.Count >= MIN_ROWS_FOR_GPU &&
                   GraphicsDevice.EnumerateDevices().Any(d => d.IsSupported);
#else
            return false;
#endif
        }

        private static Task ValidateFrameAsync(DataFrame frame, CancellationToken token)
        {
            // Example validation: check for NaNs or Infinities → could plug into data_quality_checks feature
            foreach (var column in frame.Columns.Where(c => c.DataType == typeof(double)))
            {
                var dblColumn = (PrimitiveDataFrameColumn<double>)column;
                if (dblColumn.Any(v => double.IsNaN(v) || double.IsInfinity(v)))
                {
                    throw new InvalidOperationException(
                        $"Column '{column.Name}' contains NaN or Infinity values which are not supported by the processor.");
                }
            }

            return Task.CompletedTask;
        }

        #endregion
    }

    /// <summary>
    /// Simple POCO holding statistics for a DataFrame column.
    /// </summary>
    public sealed record ColumnStatistics(string ColumnName, double Min, double Max, double Mean);

    internal static class DataFrameColumnExtensions
    {
        /// <summary>
        /// Materialises the <see cref="PrimitiveDataFrameColumn{T}"/> into a contiguous <see cref="double"/> array
        /// to facilitate vectorised or GPU processing.
        /// </summary>
        public static double[] ToDoubleArray(this DataFrameColumn column)
        {
            var doubleArr = ArrayPool<double>.Shared.Rent(column.Length);
            try
            {
                for (var i = 0; i < column.Length; i++)
                {
                    doubleArr[i] = Convert.ToDouble(column[i]);
                }

                var finalArr = new double[column.Length];
                Array.Copy(doubleArr, finalArr, column.Length);
                return finalArr;
            }
            finally
            {
                ArrayPool<double>.Shared.Return(doubleArr);
            }
        }
    }
}
```