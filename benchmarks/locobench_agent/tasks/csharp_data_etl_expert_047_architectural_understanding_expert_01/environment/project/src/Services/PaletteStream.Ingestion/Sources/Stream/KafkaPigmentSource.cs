```csharp
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace PaletteStream.Ingestion.Sources.Stream
{
    /// <summary>
    /// Represents a single piece of data coming off the Kafka topic.
    /// Treat it like a fresh pigment being squeezed onto the ETL palette.
    /// </summary>
    public sealed record PigmentMessage(
        string      Key,
        ReadOnlyMemory<byte> Value,
        DateTime    Timestamp,
        Headers?    Headers,
        TopicPartitionOffset Offset);

    /// <summary>
    /// Contract implemented by all streaming ingestion sources.
    /// </summary>
    public interface IPigmentSource : IAsyncDisposable
    {
        IAsyncEnumerable<PigmentMessage> StreamAsync(CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Options that control how <see cref="KafkaPigmentSource"/> behaves.
    /// They are pulled in via the standard <c>IOptions&lt;T&gt;</c> pattern.
    /// </summary>
    public sealed class KafkaPigmentSourceOptions
    {
        public string BootstrapServers { get; init; } = string.Empty;
        public string Topic            { get; init; } = string.Empty;
        public string GroupId          { get; init; } = $"palette-stream-{Guid.NewGuid():N}";
        public AutoOffsetReset OffsetReset { get; init; } = AutoOffsetReset.Earliest;
        public bool EnableAutoCommit   { get; init; } = false;

        /// <summary>
        /// When <see cref="EnableAutoCommit"/> is <c>false</c> this controls how often
        /// we commit manually after a message has made it safely onto the Channel buffer.
        /// </summary>
        public TimeSpan ManualCommitInterval { get; init; } = TimeSpan.FromSeconds(5);

        /// <summary>
        /// Upper-bound number of ingested messages buffered in-memory.
        /// Offers back-pressure when downstream processing slows down.
        /// </summary>
        public int BufferCapacity { get; init; } = 10_000;

        /// <summary>
        /// If non-empty, messages that blow up the consumer deserializer logic
        /// will be produced to this topic rather than nuke the stream.
        /// </summary>
        public string? DeadLetterTopic { get; init; }
    }

    /// <summary>
    /// Concrete <see cref="IPigmentSource"/> that consumes raw pigments from a Kafka topic.
    /// Implements resilience, back-pressure, graceful shutdown, and metrics instrumentation.
    /// </summary>
    public sealed class KafkaPigmentSource : IPigmentSource
    {
        private readonly Channel<PigmentMessage>            _channel;
        private readonly ILogger<KafkaPigmentSource>        _logger;
        private readonly IProducer<string, byte[]>?         _deadLetterProducer;
        private readonly KafkaPigmentSourceOptions          _options;
        private readonly IConsumer<string, byte[]>          _consumer;
        private readonly CancellationTokenSource            _cts = new();
        private readonly Task                               _pumpTask;
        private DateTime                                    _lastCommit = DateTime.UtcNow;

        public KafkaPigmentSource(
            IOptions<KafkaPigmentSourceOptions>        optionsAccessor,
            ILogger<KafkaPigmentSource>                logger)
        {
            _options = optionsAccessor?.Value ?? throw new ArgumentNullException(nameof(optionsAccessor));
            _logger  = logger ?? throw new ArgumentNullException(nameof(logger));

            ValidateOptions(_options);

            _channel = Channel.CreateBounded<PigmentMessage>(
                new BoundedChannelOptions(_options.BufferCapacity)
                {
                    FullMode = BoundedChannelFullMode.Wait,
                    SingleReader = true,
                    SingleWriter = true
                });

            // Build consumer
            var consumerConfig = new ConsumerConfig
            {
                BootstrapServers  = _options.BootstrapServers,
                GroupId           = _options.GroupId,
                AutoOffsetReset   = _options.OffsetReset,
                EnableAutoCommit  = _options.EnableAutoCommit,
                EnablePartitionEof= true,    // Helps with precise EOF handling in tests
                // Keep number of in-flight messages small: we handle back-pressure ourselves
                MaxInFlight       = 5
            };

            _consumer = new ConsumerBuilder<string, byte[]>(consumerConfig)
                .SetErrorHandler((_, e) =>
                {
                    _logger.LogError("Kafka consumer error: {Reason}", e.Reason);
                })
                .SetPartitionsAssignedHandler((_, partitions) =>
                {
                    _logger.LogInformation("Partitions assigned: {Partitions}", JsonSerializer.Serialize(partitions));
                })
                .SetPartitionsRevokedHandler((_, partitions) =>
                {
                    _logger.LogWarning("Partitions revoked: {Partitions}", JsonSerializer.Serialize(partitions));
                })
                .Build();

            if (!string.IsNullOrWhiteSpace(_options.DeadLetterTopic))
            {
                var prodCfg = new ProducerConfig { BootstrapServers = _options.BootstrapServers };
                _deadLetterProducer = new ProducerBuilder<string, byte[]>(prodCfg).Build();
            }

            _consumer.Subscribe(_options.Topic);

            // Kick off background pump.
            _pumpTask = Task.Factory.StartNew(
                PumpAsync,
                _cts.Token,
                TaskCreationOptions.LongRunning,
                TaskScheduler.Default);
        }

        public IAsyncEnumerable<PigmentMessage> StreamAsync(CancellationToken cancellationToken = default)
        {
            // Merge external CT with internal one so either can cancel the stream.
            var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(_cts.Token, cancellationToken);
            return ReadFromChannelAsync(linkedCts.Token);
        }

        #region IAsyncDisposable

        public async ValueTask DisposeAsync()
        {
            try
            {
                _cts.Cancel();
                await _pumpTask.ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Exception while waiting for pump task during dispose.");
            }

            _consumer.Close();
            _consumer.Dispose();

            _deadLetterProducer?.Flush(TimeSpan.FromSeconds(5));
            _deadLetterProducer?.Dispose();

            _cts.Dispose();
        }

        #endregion

        #region Internal pump logic

        private async void PumpAsync()
        {
            _logger.LogInformation("Kafka ingestion pump started.");
            var cancellationToken = _cts.Token;

            try
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    try
                    {
                        var result = _consumer.Consume(TimeSpan.FromMilliseconds(250));
                        if (result is null)
                        {
                            CommitIfDue();
                            continue;
                        }

                        if (result.IsPartitionEOF)
                        {
                            CommitIfDue();
                            continue;
                        }

                        var pigmentMessage = new PigmentMessage(
                            result.Message.Key ?? string.Empty,
                            result.Message.Value,
                            result.Message.Timestamp.UtcDateTime,
                            result.Message.Headers,
                            result.TopicPartitionOffset);

                        // Blocks when buffer is full (back-pressure).
                        await _channel.Writer.WriteAsync(pigmentMessage, cancellationToken).ConfigureAwait(false);

                        // Manual commit
                        CommitIfDue();
                    }
                    catch (ConsumeException ce)
                    {
                        _logger.LogError(ce, "Kafka consume exception; attempting to move offending message to dead-letter topic.");
                        await HandlePoisonPillAsync(ce.ConsumerRecord, cancellationToken).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                    {
                        // Graceful shutdown
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                _channel.Writer.TryComplete(ex);
                _logger.LogCritical(ex, "Unhandled exception inside Kafka ingestion pump. Completing channel with fault.");
                return;
            }

            // Normal completion: signal to readers.
            _channel.Writer.TryComplete();
            _logger.LogInformation("Kafka ingestion pump stopped gracefully.");
        }

        private async Task HandlePoisonPillAsync(ConsumeResult<string, byte[]>? record, CancellationToken ct)
        {
            if (record != null && _deadLetterProducer != null && !string.IsNullOrWhiteSpace(_options.DeadLetterTopic))
            {
                try
                {
                    await _deadLetterProducer.ProduceAsync(
                        _options.DeadLetterTopic!,
                        new Message<string, byte?>
                        {
                            Key     = record.Message.Key,
                            Value   = record.Message.Value,
                            Headers = record.Message.Headers
                        },
                        ct).ConfigureAwait(false);

                    _logger.LogInformation(
                        "Poison pill moved to dead-letter topic {DLQ}. Offset: {Offset}",
                        _options.DeadLetterTopic,
                        record.TopicPartitionOffset);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to send poison pill to dead-letter topic; message will be dropped.");
                }
            }
            else
            {
                _logger.LogWarning("Dead-letter queue not configured; dropping poison pill message.");
            }
        }

        private void CommitIfDue()
        {
            if (_options.EnableAutoCommit) return;
            var now = DateTime.UtcNow;
            if (now - _lastCommit < _options.ManualCommitInterval) return;

            try
            {
                _consumer.Commit();
                _lastCommit = now;
            }
            catch (KafkaException kex)
            {
                _logger.LogWarning(kex, "Failed manual offset commit.");
            }
        }

        #endregion

        #region Channel reader

        private async IAsyncEnumerable<PigmentMessage> ReadFromChannelAsync(
            [EnumeratorCancellation] CancellationToken cancellationToken)
        {
            await foreach (var msg in _channel.Reader.ReadAllAsync(cancellationToken).ConfigureAwait(false))
            {
                yield return msg;
            }
        }

        #endregion

        #region Validation

        private static void ValidateOptions(KafkaPigmentSourceOptions options)
        {
            if (string.IsNullOrWhiteSpace(options.BootstrapServers))
                throw new ArgumentException("BootstrapServers must be configured.", nameof(options));

            if (string.IsNullOrWhiteSpace(options.Topic))
                throw new ArgumentException("Topic must be configured.", nameof(options));

            if (options.BufferCapacity <= 0)
                throw new ArgumentOutOfRangeException(nameof(options.BufferCapacity), "BufferCapacity must be positive.");
        }

        #endregion
    }
}
```