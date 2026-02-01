```csharp
using System;
using System.Buffers;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Dapper;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Retry;

namespace PaletteStream.Ingestion.Sources.Batch
{
    /// <summary>
    /// Hangfire-invoked worker that extracts data from a relational
    /// database source, executes optional transformations, runs
    /// quality checks and pushes the final pigments to the Data Lake.
    /// </summary>
    public sealed class DatabaseIngestionWorker
    {
        private const int DefaultBatchSize = 10_000;

        private readonly IDbConnectionFactory _connectionFactory;
        private readonly ITransformationStrategyFactory _strategyFactory;
        private readonly IEnumerable<IDataQualityCheck> _qualityChecks;
        private readonly IDataLakeWriter _lakeWriter;
        private readonly IMetricsRecorder _metrics;
        private readonly ILogger<DatabaseIngestionWorker> _logger;
        private readonly AsyncRetryPolicy _retryPolicy;

        public DatabaseIngestionWorker(
            IDbConnectionFactory connectionFactory,
            ITransformationStrategyFactory strategyFactory,
            IEnumerable<IDataQualityCheck> qualityChecks,
            IDataLakeWriter lakeWriter,
            IMetricsRecorder metrics,
            ILogger<DatabaseIngestionWorker> logger)
        {
            _connectionFactory = connectionFactory;
            _strategyFactory = strategyFactory;
            _qualityChecks = qualityChecks;
            _lakeWriter = lakeWriter;
            _metrics = metrics;
            _logger = logger;

            _retryPolicy = Policy
                .Handle<Exception>()
                .WaitAndRetryAsync(
                    retryCount: 3,
                    sleepDurationProvider: attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
                    onRetry: (exception, ts, attempt, _) =>
                    {
                        _logger.LogWarning(exception,
                            "Retry {Attempt} after {Delay} due to error pulling data from source.", attempt, ts);
                    });
        }

        /// <summary>
        /// Entry point for Hangfire job.
        /// </summary>
        public async Task ExecuteAsync(DatabaseIngestionJobDescriptor descriptor, CancellationToken ct = default)
        {
            if (descriptor is null)
                throw new ArgumentNullException(nameof(descriptor));

            var startedAt = DateTimeOffset.UtcNow;
            _logger.LogInformation("Database ingestion job started {@Descriptor}", descriptor);

            await _retryPolicy.ExecuteAsync(async token =>
            {
                await using var connection = await _connectionFactory.CreateAsync(
                    descriptor.ConnectionString, token).ConfigureAwait(false);

                // Streaming query result set
                var reader = await connection.ExecuteReaderAsync(
                    descriptor.SourceQuery,
                    param: descriptor.QueryParameters,
                    commandTimeout: descriptor.CommandTimeoutSeconds,
                    commandType: CommandType.Text);

                var strategy = _strategyFactory.Resolve(descriptor.TransformationStrategy);
                var batchBuffer = ArrayPool<IDictionary<string, object?>>
                    .Shared.Rent(DefaultBatchSize);

                try
                {
                    var rowCount = 0;
                    while (!token.IsCancellationRequested &&
                           await reader.ReadAsync(token).ConfigureAwait(false))
                    {
                        // Map row to dictionary for flexible transformations
                        var pigment = MapRow(reader);
                        pigment = await strategy.TransformAsync(pigment, token).ConfigureAwait(false);

                        batchBuffer[rowCount++] = pigment;

                        if (rowCount == DefaultBatchSize)
                        {
                            await FlushBatchAsync(batchBuffer, rowCount, descriptor, token).ConfigureAwait(false);
                            rowCount = 0;
                        }
                    }

                    if (rowCount > 0)
                        await FlushBatchAsync(batchBuffer, rowCount, descriptor, token).ConfigureAwait(false);

                    _metrics.RecordGauge("etl_ingestion_row_count", strategy.Name, reader.RecordsAffected);
                }
                finally
                {
                    ArrayPool<IDictionary<string, object?>>.Shared.Return(batchBuffer, clearArray: true);
                }
            }, ct).ConfigureAwait(false);

            _metrics.RecordTimer("etl_ingestion_duration", descriptor.DataSetName,
                DateTimeOffset.UtcNow - startedAt);
            _logger.LogInformation("Database ingestion job finished for {DataSet}", descriptor.DataSetName);
        }

        #region private helpers

        private static IDictionary<string, object?> MapRow(IDataRecord reader)
        {
            var dict = new Dictionary<string, object?>(reader.FieldCount, StringComparer.OrdinalIgnoreCase);
            for (var i = 0; i < reader.FieldCount; i++)
            {
                var val = reader.GetValue(i);
                dict[reader.GetName(i)] = val == DBNull.Value ? null : val;
            }

            return dict;
        }

        private async Task FlushBatchAsync(
            IDictionary<string, object?>[] batch,
            int count,
            DatabaseIngestionJobDescriptor descriptor,
            CancellationToken ct)
        {
            var segment = batch.AsSpan(0, count).ToArray();

            foreach (var check in _qualityChecks)
            {
                await check.AssertAsync(segment, ct).ConfigureAwait(false);
            }

            await _lakeWriter.WriteAsync(
                datasetName: descriptor.DataSetName,
                data: segment,
                format: descriptor.TargetFormat,
                ct: ct).ConfigureAwait(false);
        }

        #endregion
    }

    #region contracts

    public record DatabaseIngestionJobDescriptor(
        string ConnectionString,
        string SourceQuery,
        object? QueryParameters,
        int? CommandTimeoutSeconds,
        string DataSetName,
        string TargetFormat,
        string TransformationStrategy);

    public interface IDbConnectionFactory
    {
        ValueTask<IDbConnection> CreateAsync(string connectionString, CancellationToken ct);
    }

    public interface ITransformationStrategyFactory
    {
        ITransformationStrategy Resolve(string name);
    }

    public interface ITransformationStrategy
    {
        string Name { get; }

        ValueTask<IDictionary<string, object?>> TransformAsync(
            IDictionary<string, object?> pigment,
            CancellationToken ct = default);
    }

    public interface IDataQualityCheck
    {
        Task AssertAsync(IEnumerable<IDictionary<string, object?>> data, CancellationToken ct);
    }

    public interface IDataLakeWriter
    {
        Task WriteAsync(
            string datasetName,
            IReadOnlyCollection<IDictionary<string, object?>> data,
            string format,
            CancellationToken ct = default);
    }

    public interface IMetricsRecorder
    {
        void RecordGauge(string name, string label, long value);
        void RecordTimer(string name, string label, TimeSpan elapsed);
    }

    #endregion
}
```