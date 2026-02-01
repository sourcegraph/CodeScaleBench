```csharp
using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Azure;
using Azure.Core;
using Azure.Storage.Files.DataLake;
using Azure.Storage.Files.DataLake.Models;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Retry;

namespace PaletteStream.Loader.DataLake
{
    /// <summary>
    /// Handles failed records by persisting them to an Azure Data Lake–backed
    /// Dead-Letter Queue (DLQ).  
    ///
    /// ‑ Buffers incoming messages on an in-process <see cref="Channel{T}"/>  
    /// ‑ Writes to the lake in a background task with exponential-backoff retries  
    /// ‑ Exposes health & diagnostic metrics via <see cref="DeadLetterQueueStats"/>  
    /// </summary>
    /// <remarks>
    /// The handler is designed to be a singleton within the Loader micro-service.
    /// </remarks>
    public sealed class DeadLetterQueueHandler : IDeadLetterQueueHandler, IAsyncDisposable
    {
        private const string DefaultContainerName = "dead-letter-zone";
        private const string DefaultPathFormat    = "yyyy/MM/dd/HH/";

        private readonly Channel<DeadLetterMessage> _channel;
        private readonly CancellationTokenSource    _cts         = new();
        private readonly DataLakeFileSystemClient   _fileSystem;
        private readonly AsyncRetryPolicy          _retryPolicy;
        private readonly ILogger<DeadLetterQueueHandler> _logger;

        private Task? _backgroundWriter;
        private long  _totalMessagesWritten;
        private long  _totalBytesWritten;

        public DeadLetterQueueStats Stats => new(_totalMessagesWritten, _totalBytesWritten);

        public DeadLetterQueueHandler(
            Uri dataLakeUri,
            TokenCredential credential,
            ILogger<DeadLetterQueueHandler> logger,
            int channelCapacity        = 10_000,
            string? containerName      = null,
            IAsyncPolicy? retryPolicy  = null)
        {
            if (dataLakeUri == null) throw new ArgumentNullException(nameof(dataLakeUri));
            _logger     = logger ?? throw new ArgumentNullException(nameof(logger));

            var serviceClient = new DataLakeServiceClient(dataLakeUri, credential);
            _fileSystem       = serviceClient.GetFileSystemClient(containerName ?? DefaultContainerName);
            _fileSystem.CreateIfNotExists();

            _channel     = Channel.CreateBounded<DeadLetterMessage>(new BoundedChannelOptions(channelCapacity)
            {
                FullMode   = BoundedChannelFullMode.Wait,
                SingleReader = true,   // Background writer single-threaded
                SingleWriter = false
            });

            _retryPolicy = (AsyncRetryPolicy)(retryPolicy ?? BuildDefaultRetryPolicy());

            _backgroundWriter = Task.Run(ProcessQueueAsync, _cts.Token);
        }

        #region Public API
        public ValueTask EnqueueAsync(DeadLetterMessage message, CancellationToken externalToken = default)
        {
            if (message == null) throw new ArgumentNullException(nameof(message));
            return _channel.Writer.WriteAsync(message, externalToken);
        }

        public async Task FlushAsync(CancellationToken cancellationToken = default)
        {
            _channel.Writer.Complete();    // Signal completion
            if (_backgroundWriter != null)
                await _backgroundWriter.WaitAsync(cancellationToken)
                                         .ConfigureAwait(false);
        }
        #endregion

        #region Background Writer
        private async Task ProcessQueueAsync()
        {
            try
            {
                await foreach (var message in _channel.Reader.ReadAllAsync(_cts.Token).ConfigureAwait(false))
                {
                    await _retryPolicy.ExecuteAsync(
                        async ct => await PersistAsync(message, ct).ConfigureAwait(false),
                        _cts.Token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) when (_cts.IsCancellationRequested)
            {
                // graceful shutdown
            }
            catch (Exception ex)
            {
                _logger.LogCritical(ex, "Unhandled exception in DLQ background writer – messages may be lost.");
            }
        }

        private async Task PersistAsync(DeadLetterMessage message, CancellationToken ct)
        {
            string directoryPath = message.Timestamp.ToString(DefaultPathFormat);
            string fileName      = $"{Guid.NewGuid():N}.json";

            // Ensure directory exists
            var directory = _fileSystem.GetDirectoryClient(directoryPath);
            await directory.CreateIfNotExistsAsync(cancellationToken: ct).ConfigureAwait(false);

            // Create the file
            var fileClient = directory.GetFileClient(fileName);
            await fileClient.CreateAsync(cancellationToken: ct).ConfigureAwait(false);

            // Serialize the message
            byte[] data = JsonSerializer.SerializeToUtf8Bytes(message, DeadLetterJsonContext.Default.DeadLetterMessage);

            // Upload the content
            using var ms = new MemoryStream(data);
            await fileClient.AppendAsync(content: ms, offset: 0, cancellationToken: ct).ConfigureAwait(false);
            await fileClient.FlushAsync(position: data.Length, cancellationToken: ct).ConfigureAwait(false);

            // Stats
            Interlocked.Increment(ref _totalMessagesWritten);
            Interlocked.Add(ref _totalBytesWritten, data.Length);

            _logger.LogDebug("Persisted DLQ message to {Path}/{File}", directoryPath, fileName);
        }
        #endregion

        #region Policies
        private static IAsyncPolicy BuildDefaultRetryPolicy() =>
            Policy
                .Handle<RequestFailedException>()
                .Or<IOException>()
                .WaitAndRetryAsync(
                    retryCount: 5,
                    sleepDurationProvider: attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
                    onRetry: (exception, delay, attempt, context) =>
                    {
                        var log = context["logger"] as ILogger;
                        log?.LogWarning(exception,
                            "DLQ persistence failed (attempt {Attempt}). Retrying in {Delay}.", attempt, delay);
                    })
                .WithPolicyKey("DLQ.RetryPolicy");
        #endregion

        #region Dispose Pattern
        public async ValueTask DisposeAsync()
        {
            try
            {
                _cts.Cancel();

                if (_backgroundWriter != null)
                    await _backgroundWriter.ConfigureAwait(false);

                _cts.Dispose();
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error occurred while disposing DLQ handler.");
            }
        }
        #endregion
    }

    #region Models & Interfaces
    /// <summary>
    /// Contract for writing failed records to a DLQ implementation.
    /// </summary>
    public interface IDeadLetterQueueHandler
    {
        ValueTask EnqueueAsync(DeadLetterMessage message, CancellationToken externalToken = default);
        Task FlushAsync(CancellationToken cancellationToken = default);
        DeadLetterQueueStats Stats { get; }
    }

    /// <summary>
    /// Represents a failed ETL record with rich metadata for troubleshooting.
    /// </summary>
    public sealed record DeadLetterMessage(
        string   SourceSystem,
        string   TopicOrTable,
        long     Offset,
        string?  PartitionKey,
        DateTime Timestamp,
        string   ErrorMessage,
        string   StackTrace,
        byte[]   Payload);

    /// <summary>
    /// Lightweight struct used for surfacing runtime metrics.
    /// </summary>
    public readonly struct DeadLetterQueueStats
    {
        public long TotalMessages { get; }
        public long TotalBytes    { get; }

        public DeadLetterQueueStats(long totalMessages, long totalBytes)
        {
            TotalMessages = totalMessages;
            TotalBytes    = totalBytes;
        }
    }
    #endregion

    #region System.Text.Json Source-Gen Context
    // Opt-in to source-generated serialization for performance.
    [JsonSerializable(typeof(DeadLetterMessage))]
    internal partial class DeadLetterJsonContext : JsonSerializerContext
    { }
    #endregion
}
```