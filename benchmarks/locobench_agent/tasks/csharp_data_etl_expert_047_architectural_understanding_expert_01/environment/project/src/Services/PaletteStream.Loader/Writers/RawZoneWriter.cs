```csharp
using System;
using System.Buffers;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Loader.Writers
{
    /// <summary>
    /// Describes the contract for writing batches of raw data to the Raw Zone of the Data Lake.
    /// </summary>
    public interface IRawZoneWriter
    {
        /// <summary>
        /// Persists a batch of <paramref name="records"/> for the specified <paramref name="sourceSystem"/> into the Raw Zone.
        /// </summary>
        /// <typeparam name="T">Type of record within the batch.</typeparam>
        /// <param name="records">Asynchronous stream of records to write.</param>
        /// <param name="sourceSystem">Identifier of the system the data originated from (Kafka topic, API, etc.).</param>
        /// <param name="cancellationToken">Token used to cancel the operation.</param>
        /// <returns>A <see cref="WriteResult"/> describing the persisted object.</returns>
        Task<WriteResult> WriteAsync<T>(
            IAsyncEnumerable<T> records,
            string sourceSystem,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Production-grade implementation responsible for persisting raw data in a
    /// newline-delimited JSON (jsonl.gz) format with date-based partitioning.
    /// </summary>
    public sealed class RawZoneWriter : IRawZoneWriter
    {
        private static readonly JsonSerializerOptions JsonSerializerOptions = new()
        {
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = false
        };

        private readonly IObjectStorageClient _storage;
        private readonly IMetadataRepository _catalog;
        private readonly ISystemClock _clock;
        private readonly ILogger<RawZoneWriter> _logger;

        public RawZoneWriter(
            IObjectStorageClient storage,
            IMetadataRepository catalog,
            ISystemClock clock,
            ILogger<RawZoneWriter> logger)
        {
            _storage = storage ?? throw new ArgumentNullException(nameof(storage));
            _catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            _clock   = clock   ?? throw new ArgumentNullException(nameof(clock));
            _logger  = logger  ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <inheritdoc />
        public async Task<WriteResult> WriteAsync<T>(
            IAsyncEnumerable<T> records,
            string sourceSystem,
            CancellationToken cancellationToken = default)
        {
            ArgumentNullException.ThrowIfNull(records);
            if (string.IsNullOrWhiteSpace(sourceSystem))
                throw new ArgumentException("Source system must be provided.", nameof(sourceSystem));

            var utcNow = _clock.UtcNow;
            // Build path: raw/{yyyy}/{MM}/{dd}/{source}/batch_{ticks}_{rand}.jsonl.gz
            var baseFolder = Path.Combine(
                "raw",
                utcNow.ToString("yyyy", CultureInfo.InvariantCulture),
                utcNow.ToString("MM", CultureInfo.InvariantCulture),
                utcNow.ToString("dd", CultureInfo.InvariantCulture),
                SanitizePathSegment(sourceSystem));

            var objectName = $"batch_{utcNow.Ticks}_{Guid.NewGuid():N}.jsonl.gz";
            var fullPath   = Path.Combine(baseFolder, objectName).Replace('\\', '/');

            _logger.LogInformation("Starting RawZone write for {SourceSystem}. Target object = {Path}", sourceSystem, fullPath);

            long recordCount = 0;
            long bytesWritten = 0;

            await using Stream objectStream = await _storage.OpenWriteAsync(fullPath, overwrite: false, cancellationToken);
            await using var gzip = new GZipStream(objectStream, CompressionLevel.Fastest, leaveOpen: false);
            await using var writer = new StreamWriter(gzip);

            // Allocate a recyclable buffer for serialized lines
            var bufferWriter = new ArrayBufferWriter<byte>(256);

            await foreach (T record in records.WithCancellation(cancellationToken))
            {
                bufferWriter.Clear();
                await JsonSerializer.SerializeAsync(bufferWriter, record, JsonSerializerOptions, cancellationToken);
                await writer.WriteLineAsync(System.Text.Encoding.UTF8.GetString(bufferWriter.WrittenSpan), cancellationToken);

                recordCount++;

                if (recordCount % 50_000 == 0) // Log progress every 50k records
                {
                    _logger.LogDebug("RawZone writer progress – {Records} records so far for {SourceSystem}", recordCount, sourceSystem);
                }
            }

            await writer.FlushAsync();
            await gzip.FlushAsync();

            bytesWritten = objectStream.CanSeek ? objectStream.Position : -1;

            var result = new WriteResult(fullPath, recordCount, bytesWritten, utcNow);
            await PersistMetadataAsync(result, sourceSystem, cancellationToken);

            _logger.LogInformation(
                "RawZone write finished for {SourceSystem}. {RecordCount} records, {Size:n0} bytes written to {Path}",
                sourceSystem,
                result.RecordCount,
                result.SizeBytes,
                result.ObjectPath);

            return result;
        }

        private async Task PersistMetadataAsync(
            WriteResult result,
            string sourceSystem,
            CancellationToken cancellationToken)
        {
            var meta = new RawObjectMetadata
            {
                ObjectPath   = result.ObjectPath,
                SourceSystem = sourceSystem,
                RecordCount  = result.RecordCount,
                SizeBytes    = result.SizeBytes,
                CreatedUtc   = result.CreatedUtc
            };

            try
            {
                await _catalog.UpsertAsync(meta, cancellationToken);
            }
            catch (Exception ex)
            {
                // Metadata is important but not critical for data durability.
                // We log the error and swallow to avoid failing the pipeline.
                _logger.LogError(ex, "Failed to persist metadata for RawZone object {Path}", result.ObjectPath);
            }
        }

        private static string SanitizePathSegment(string segment)
        {
            foreach (var c in Path.GetInvalidFileNameChars())
            {
                segment = segment.Replace(c, '_');
            }
            return segment;
        }
    }

    #region Support contracts / DTOs

    /// <summary>
    /// Simple abstraction over an object storage implementation (Azure Blob, AWS S3, Minio, etc.).
    /// </summary>
    public interface IObjectStorageClient
    {
        /// <summary>
        /// Opens a writable stream to the specified object <paramref name="path"/>.
        /// </summary>
        /// <param name="path">Destination path / key.</param>
        /// <param name="overwrite">Whether to overwrite existing object (if any).</param>
        /// <param name="cancellationToken">Token to cancel the operation.</param>
        /// <returns>Writable <see cref="Stream"/>.</returns>
        Task<Stream> OpenWriteAsync(
            string path,
            bool overwrite = false,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Abstraction for persisting metadata about objects written to the Raw Zone.
    /// </summary>
    public interface IMetadataRepository
    {
        Task UpsertAsync(RawObjectMetadata metadata, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Provides access to the current <see cref="DateTimeOffset.UtcNow"/> – greatly simplifies unit testing.
    /// </summary>
    public interface ISystemClock
    {
        DateTimeOffset UtcNow { get; }
    }

    /// <summary>
    /// Records information about a persisted Raw Zone object.
    /// </summary>
    public sealed record RawObjectMetadata
    {
        public string          ObjectPath   { get; init; } = default!;
        public string          SourceSystem { get; init; } = default!;
        public long            RecordCount  { get; init; }
        public long            SizeBytes    { get; init; }
        public DateTimeOffset  CreatedUtc   { get; init; }
    }

    /// <summary>
    /// Returned after a successful write operation to the Raw Zone.
    /// </summary>
    public sealed record WriteResult(
        string ObjectPath,
        long   RecordCount,
        long   SizeBytes,
        DateTimeOffset CreatedUtc);

    #endregion
}
```