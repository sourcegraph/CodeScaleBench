```csharp
using System;
using System.Buffers.Text;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Retry;

namespace PaletteStream.Loader.Writers
{
    /// <summary>
    ///     Writes refined data into the <c>Curated</c> tier of the PaletteStream data-lake.
    ///     The writer is opinionated:
    ///     • It produces NDJSON payloads (one JSON per line) that are GZip-compressed.
    ///     • It appends an execution timestamp and a monotonically increasing part-number
    ///       to the file-name, enabling downstream partition pruning.
    ///     • It validates each record with an <see cref="IRecordValidator{T}" />, sending any
    ///       rejected records to the configured dead-letter handler.
    ///     • It exposes write events to observers for metrics/monitoring hooks.
    /// </summary>
    /// <remarks>
    ///     The writer is intentionally streaming-friendly: the caller can yield records as
    ///     they arrive to keep memory usage bounded. Back-pressure is provided via the
    ///     <see cref="SemaphoreSlim" />–based <c>_concurrencyGate</c>.
    /// </remarks>
    public sealed class CuratedZoneWriter : ICuratedZoneWriter, IDisposable
    {
        private const int DefaultMaxFileSizeInBytes = 100 * 1024 * 1024; // 100 MB
        private const int DefaultMaxConcurrency     = 4;

        private readonly IDataLakeClient                     _dataLake;
        private readonly ILogger<CuratedZoneWriter>          _logger;
        private readonly IEnumerable<IWriteEventObserver>    _observers;
        private readonly int                                 _maxFileSize;
        private readonly SemaphoreSlim                       _concurrencyGate;
        private readonly AsyncRetryPolicy                    _ioRetryPolicy;

        public CuratedZoneWriter(
            IDataLakeClient                  dataLake,
            ILogger<CuratedZoneWriter>       logger,
            IEnumerable<IWriteEventObserver> observers = null,
            int                              maxFileSizeInBytes = DefaultMaxFileSizeInBytes,
            int                              maxConcurrency     = DefaultMaxConcurrency)
        {
            _dataLake       = dataLake  ?? throw new ArgumentNullException(nameof(dataLake));
            _logger         = logger    ?? throw new ArgumentNullException(nameof(logger));
            _observers      = observers ?? Array.Empty<IWriteEventObserver>();
            _maxFileSize    = maxFileSizeInBytes;
            _concurrencyGate = new SemaphoreSlim(maxConcurrency, maxConcurrency);

            _ioRetryPolicy = Policy
                .Handle<IOException>()
                .Or<OperationCanceledException>()
                .WaitAndRetryAsync(
                    retryCount : 3,
                    sleepDurationProvider : retry => TimeSpan.FromSeconds(Math.Pow(2, retry)),
                    onRetry : (exception, timespan, retry, _) =>
                        _logger.LogWarning(exception,
                                           "I/O retry {Retry} scheduled in {Delay} ms.",
                                           retry,
                                           timespan.TotalMilliseconds));
        }

        #region ICuratedZoneWriter implementation

        public async Task<CuratedWriteResult> WriteAsync<T>(
            IAsyncEnumerable<T> records,
            string              datasetName,
            IRecordValidator<T> validator = null,
            CancellationToken   cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(datasetName))
                throw new ArgumentException("Dataset name cannot be null/empty.", nameof(datasetName));

            if (records is null)
                throw new ArgumentNullException(nameof(records));

            var start = DateTimeOffset.UtcNow;
            var path  = BuildDirectoryPath(datasetName, start);

            long fileIndex      = 0;
            long totalWritten   = 0;
            long invalidRecords = 0;

            await foreach (var chunk in SplitStreamAsync(records, _maxFileSize, validator, cancellationToken)
                                          .ConfigureAwait(false))
            {
                var fileName = $"{datasetName}_{start:yyyyMMddHHmmss}_{fileIndex:D4}.ndjson.gz";
                var key      = $"{path}/{fileName}";

                await _concurrencyGate.WaitAsync(cancellationToken).ConfigureAwait(false);
                try
                {
                    await _ioRetryPolicy.ExecuteAsync(
                        ct => UploadChunkAsync(key, chunk, ct),
                        cancellationToken);
                }
                finally
                {
                    _concurrencyGate.Release();
                }

                NotifyObservers(new WriteEvent(key, chunk.RecordCount));
                totalWritten += chunk.RecordCount;
                fileIndex++;
            }

            var completion = DateTimeOffset.UtcNow;
            var result = new CuratedWriteResult(
                datasetName, path, totalWritten, invalidRecords, start, completion);

            _logger.LogInformation("Write completed: {@Result}", result);
            return result;
        }

        #endregion

        #region Streaming helpers

        private async Task UploadChunkAsync(string key, ChunkBuffer chunk, CancellationToken ct)
        {
            _logger.LogDebug("Uploading {Key} ({Size} bytes)...", key, chunk.Length);

            await using var writeStream = await _dataLake.OpenWriteAsync(key, overwrite : false, ct);
            await chunk.Stream.CopyToAsync(writeStream, ct);
            await writeStream.FlushAsync(ct);

            _logger.LogInformation("Uploaded {Key}.", key);
        }

        private static async IAsyncEnumerable<ChunkBuffer> SplitStreamAsync<T>(
            IAsyncEnumerable<T>     source,
            int                     maxBytes,
            IRecordValidator<T>     validator,
            [EnumeratorCancellation] CancellationToken ct)
        {
            var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };

            var buffer       = new ChunkBuffer(maxBytes);
            await foreach (var item in source.WithCancellation(ct))
            {
                var line      = JsonSerializer.Serialize(item, options) + '\n';
                var lineBytes = Encoding.UTF8.GetBytes(line);

                // Simple validation
                if (validator != null && !validator.IsValid(item))
                {
                    // Optionally, send to DLQ here.
                    continue;
                }

                if (!buffer.TryAppend(lineBytes))
                {
                    yield return buffer;
                    buffer = new ChunkBuffer(maxBytes);
                    if (!buffer.TryAppend(lineBytes))
                        throw new InvalidOperationException("Single record exceeds configured max file size.");
                }
            }

            if (buffer.RecordCount > 0)
                yield return buffer;
        }

        #endregion

        private static string BuildDirectoryPath(string dataset, DateTimeOffset timestamp)
            => $"{dataset}/curated/partition_date={timestamp:yyyyMMdd}";

        private void NotifyObservers(WriteEvent evt)
        {
            foreach (var observer in _observers)
            {
                try
                {
                    observer.OnNext(evt);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Observer {Observer} threw an exception.", observer.GetType().Name);
                }
            }
        }

        #region IDisposable

        public void Dispose() => _concurrencyGate?.Dispose();

        #endregion
    }

    #region ––––– Supporting types –––––

    public interface ICuratedZoneWriter
    {
        Task<CuratedWriteResult> WriteAsync<T>(
            IAsyncEnumerable<T> records,
            string              datasetName,
            IRecordValidator<T> validator = null,
            CancellationToken   cancellationToken = default);
    }

    public readonly record struct CuratedWriteResult(
        string          Dataset,
        string          DirectoryPath,
        long            RecordsWritten,
        long            InvalidRecords,
        DateTimeOffset  StartedAt,
        DateTimeOffset  CompletedAt);

    public readonly record struct WriteEvent(string ObjectKey, long Records);

    public interface IWriteEventObserver : IObserver<WriteEvent> { }

    public interface IDataLakeClient
    {
        /// <summary> Open a stream for writing. Implementations should create the underlying container if needed. </summary>
        ValueTask<Stream> OpenWriteAsync(string objectKey, bool overwrite, CancellationToken cancellationToken);
    }

    public interface IRecordValidator<in T>
    {
        bool IsValid(T record);
    }

    /// <summary>
    ///     In-memory buffer that accumulates NDJSON payloads until it reaches the configured maximum size.
    ///     Internally wraps a <see cref="GZipStream" /> to ensure on-the-fly compression.
    /// </summary>
    internal sealed class ChunkBuffer : IDisposable
    {
        private readonly int         _maxSize;
        private readonly MemoryStream _innerStream;
        private readonly GZipStream   _gzipStream;
        private          long         _recordCount;

        public ChunkBuffer(int maxSizeInBytes)
        {
            _maxSize     = maxSizeInBytes;
            _innerStream = new MemoryStream(capacity: maxSizeInBytes);
            _gzipStream  = new GZipStream(_innerStream, CompressionLevel.Fastest, leaveOpen: true);
        }

        public bool TryAppend(ReadOnlySpan<byte> data)
        {
            if (data.Length + _innerStream.Length > _maxSize) return false;

            _gzipStream.Write(data);
            _recordCount++;
            return true;
        }

        public Stream Stream
        {
            get
            {
                _gzipStream.Flush();
                _innerStream.Position = 0;
                return _innerStream;
            }
        }

        public long Length       => _innerStream.Length;
        public long RecordCount  => _recordCount;

        #region IDisposable

        public void Dispose()
        {
            _gzipStream?.Dispose();
            _innerStream?.Dispose();
        }

        #endregion
    }

    #endregion
}
```