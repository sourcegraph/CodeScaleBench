```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Collections.Concurrent;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Transformer.Transformers.Implementations
{
    #region Contracts & Models

    /// <summary>
    /// Strategy contract implemented by all transformation algorithms.
    /// </summary>
    public interface ITransformationStrategy
    {
        /// <summary>
        /// Executes the transformation on the provided <see cref="DataBatch"/>.
        /// </summary>
        /// <param name="input">Batch that will be transformed.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>A brand-new <see cref="DataBatch"/> with the transformation applied.</returns>
        Task<DataBatch> TransformAsync(DataBatch input, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Defines the aggregation configuration consumed by <see cref="AggregateDataStrategy"/>.
    /// </summary>
    public sealed record AggregateConfig
    {
        /// <summary>
        /// Fields that will be used as key in the Group-By clause.
        /// </summary>
        public IReadOnlyCollection<string> GroupByFields { get; init; } = Array.Empty<string>();

        /// <summary>
        /// Collection of aggregate definitions that will be executed on each group.
        /// </summary>
        public IReadOnlyCollection<AggregateDefinition> Aggregates { get; init; } = Array.Empty<AggregateDefinition>();

        /// <summary>
        /// Whether to keep the original grouping keys in the output payload.
        /// </summary>
        public bool KeepGroupKeys { get; init; } = true;

        /// <summary>
        /// Throw if any of the configured fields is not present in the incoming record.
        /// </summary>
        public bool StrictSchema { get; init; } = false;
    }

    /// <summary>
    /// Describes a single aggregate operation (e.g., SUM of "Amount" → "TotalAmount").
    /// </summary>
    public sealed record AggregateDefinition
    {
        public required string SourceField { get; init; }
        public required string OutputField { get; init; }
        public required AggregateOperation Operation { get; init; }
    }

    /// <summary>
    /// Supported aggregate operations.
    /// </summary>
    public enum AggregateOperation
    {
        Sum,
        Average,
        Min,
        Max,
        Count
    }

    /// <summary>
    /// Plain old data wrapper around a collection of records.
    /// Internally the record is represented as an immutable dictionary.
    /// </summary>
    public sealed class DataBatch
    {
        public DataBatch(IEnumerable<DataRecord> records, string? batchId = null)
        {
            Records = new ReadOnlyCollection<DataRecord>((records ?? Enumerable.Empty<DataRecord>()).ToList());
            BatchId = batchId ?? Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
        }

        public IReadOnlyCollection<DataRecord> Records { get; }

        public string BatchId { get; }

        public static readonly DataBatch Empty = new([]);

        public override string ToString() => $"BatchId = {BatchId} | Records = {Records.Count}";
    }

    /// <summary>
    /// Wrapper around an immutable dictionary representing a single row of data.
    /// </summary>
    public sealed class DataRecord
    {
        private readonly IReadOnlyDictionary<string, object?> _fields;

        public DataRecord(IDictionary<string, object?> fields)
            => _fields = new ReadOnlyDictionary<string, object?>(fields);

        public object? this[string key] => _fields.TryGetValue(key, out var value) ? value : null;

        public IReadOnlyDictionary<string, object?> Fields => _fields;

        public DataRecord WithField(string key, object? value)
        {
            var dict = new Dictionary<string, object?>(_fields) { [key] = value };
            return new DataRecord(dict);
        }

        public override string ToString() => string.Join(" | ", _fields.Select(kv => $"{kv.Key}={kv.Value}"));
    }

    /// <summary>
    /// Observer used by transformers to broadcast metrics/alerts without coupling.
    /// The implementation is provided by the hosting micro-service.
    /// </summary>
    public interface ITransformationObserver
    {
        void TransformationStarted(string batchId, string strategyName);
        void TransformationCompleted(string batchId, string strategyName, int outputRecords);
        void TransformationFailed(string batchId, string strategyName, Exception ex);
    }

    #endregion

    /// <summary>
    /// Aggregates numeric and statistical values over a batch of incoming records.
    /// Implements the Strategy pattern so that it can be hot-swapped at runtime.
    /// </summary>
    public sealed class AggregateDataStrategy : ITransformationStrategy
    {
        private readonly AggregateConfig _config;
        private readonly ILogger<AggregateDataStrategy> _logger;
        private readonly ITransformationObserver? _observer;

        public AggregateDataStrategy(
            AggregateConfig config,
            ILogger<AggregateDataStrategy> logger,
            ITransformationObserver? observer = null)
        {
            _config  = config  ?? throw new ArgumentNullException(nameof(config));
            _logger  = logger  ?? throw new ArgumentNullException(nameof(logger));
            _observer = observer; // optional
        }

        public async Task<DataBatch> TransformAsync(DataBatch input, CancellationToken cancellationToken = default)
        {
            if (input == null) throw new ArgumentNullException(nameof(input));

            _observer?.TransformationStarted(input.BatchId, nameof(AggregateDataStrategy));
            _logger.LogDebug("Aggregation started for BatchId={BatchId} (Records={RecordCount})",
                             input.BatchId, input.Records.Count);

            try
            {
                var aggregatedRecords = await Task.Run(
                    () => TransformInternal(input, cancellationToken),
                    cancellationToken).ConfigureAwait(false);

                var outputBatch = new DataBatch(aggregatedRecords, input.BatchId);

                _logger.LogInformation("Aggregation completed for BatchId={BatchId}. Output Records = {OutputCount}",
                                       input.BatchId, outputBatch.Records.Count);

                _observer?.TransformationCompleted(input.BatchId, nameof(AggregateDataStrategy), outputBatch.Records.Count);

                return outputBatch;
            }
            catch (Exception ex) when (!ex.IsFatal())
            {
                _logger.LogError(ex, "Aggregation failed for BatchId={BatchId}", input.BatchId);
                _observer?.TransformationFailed(input.BatchId, nameof(AggregateDataStrategy), ex);
                throw;
            }
        }

        #region Internal Implementation

        private IEnumerable<DataRecord> TransformInternal(DataBatch input, CancellationToken cancellationToken)
        {
            if (!_config.GroupByFields.Any())
            {
                _logger.LogWarning("AggregateDataStrategy executed with no GroupByFields. " +
                                   "Entire batch will be treated as a single group.");
            }

            // 1. Validate schema if StrictSchema is enabled
            if (_config.StrictSchema)
            {
                ValidateSchema(input);
            }

            // 2. Perform grouping
            var grouped = input.Records
                               .GroupBy(record => BuildGroupKey(record, _config.GroupByFields))
                               .ToList(); // materialise to avoid multiple enumeration

            _logger.LogDebug("Created {GroupCount} groups using fields [{Fields}]",
                             grouped.Count, string.Join(",", _config.GroupByFields));

            // 3. Aggregate each group in parallel using PLINQ
            var aggregated = grouped
                .AsParallel()
                .WithCancellation(cancellationToken)
                .Select(group => AggregateGroup(group.Key, group))
                .ToList();

            return aggregated;
        }

        private static string BuildGroupKey(DataRecord record, IEnumerable<string> fields)
        {
            return string.Join("||", fields.Select(f => record[f]?.ToString() ?? string.Empty));
        }

        private DataRecord AggregateGroup(string groupKey, IEnumerable<DataRecord> groupRecords)
        {
            var firstRecord = groupRecords.First();

            var outputFields = new Dictionary<string, object?>();
            if (_config.KeepGroupKeys)
            {
                foreach (var keyField in _config.GroupByFields)
                    outputFields[keyField] = firstRecord[keyField];
            }

            foreach (var aggregate in _config.Aggregates)
            {
                outputFields[aggregate.OutputField] =
                    ExecuteAggregateOperation(aggregate.Operation, groupRecords, aggregate.SourceField);
            }

            _logger.LogTrace("Aggregated group {GroupKey}. Output: {Data}", groupKey,
                             string.Join(", ", outputFields.Select(kv => $"{kv.Key}:{kv.Value}")));

            return new DataRecord(outputFields);
        }

        private static object ExecuteAggregateOperation(
            AggregateOperation op,
            IEnumerable<DataRecord> records,
            string sourceField)
        {
            IEnumerable<double?> values() => records.Select(r => ToNullableDouble(r[sourceField]));

            return op switch
            {
                AggregateOperation.Sum     => values().Sum() ?? 0d,
                AggregateOperation.Average => values().Average() ?? 0d,
                AggregateOperation.Min     => values().Where(v => v.HasValue).Min() ?? 0d,
                AggregateOperation.Max     => values().Where(v => v.HasValue).Max() ?? 0d,
                AggregateOperation.Count   => records.LongCount(),
                _                          => throw new ArgumentOutOfRangeException(nameof(op), op, "Unknown aggregate op")
            };
        }

        private static double? ToNullableDouble(object? value)
        {
            if (value == null || value is DBNull) return null;

            return value switch
            {
                double d      => d,
                float f       => f,
                decimal dcm   => (double)dcm,
                int i         => i,
                long l        => l,
                short s       => s,
                uint ui       => ui,
                ulong ul      => ul,
                string str    => double.TryParse(str, NumberStyles.Any, CultureInfo.InvariantCulture, out var dv) ? dv : null,
                _             => null
            };
        }

        private void ValidateSchema(DataBatch input)
        {
            var requiredFields = _config.GroupByFields
                                        .Concat(_config.Aggregates.Select(a => a.SourceField))
                                        .ToHashSet(StringComparer.OrdinalIgnoreCase);

            foreach (var record in input.Records)
            {
                var missing = requiredFields
                    .Where(field => !record.Fields.ContainsKey(field))
                    .ToList();

                if (missing.Count <= 0) continue;

                var msg = $"Record missing required fields [{string.Join(",", missing)}].";
                _logger.LogError(msg + " Record={Record}", record);
                throw new InvalidOperationException(msg);
            }
        }

        #endregion
    }

    #region Helper Extensions

    internal static class ExceptionExtensions
    {
        /// <summary>
        /// Determines whether the exception is fatal/unrecoverable.
        /// </summary>
        internal static bool IsFatal(this Exception ex)
        {
            return ex is StackOverflowException
                or OutOfMemoryException
                or ThreadAbortException
                or AccessViolationException
                or AppDomainUnloadedException
                or BadImageFormatException;
        }
    }

    #endregion
}
```