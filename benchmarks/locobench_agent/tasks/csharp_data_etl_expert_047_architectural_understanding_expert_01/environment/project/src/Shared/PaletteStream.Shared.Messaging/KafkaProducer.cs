```csharp
// File: PaletteStream-ETL-Canvas/src/Shared/PaletteStream.Shared.Messaging/KafkaProducer.cs

using System;
using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Shared.Messaging
{
    /// <summary>
    /// Options required to bootstrap a Kafka producer.
    /// </summary>
    public sealed record KafkaProducerConfig
    {
        /// <summary>The Kafka bootstrap servers.</summary>
        public required string BootstrapServers { get; init; }

        /// <summary>Optional client identifier.  Defaults to the entry assembly name.</summary>
        public string ClientId { get; init; } = Assembly.GetEntryAssembly()?.GetName().Name ?? "palette-stream-producer";

        /// <summary>Number of retries before giving up on transient failures.</summary>
        public int RetryCount { get; init; } = 3;

        /// <summary>Message linger (ms) before flush to improve batching.</summary>
        public int LingerMs { get; init; } = 5;

        /// <summary>Compression codec (gzip, snappy, lz4, zstd).  Defaults to snappy.</summary>
        public CompressionType CompressionType { get; init; } = CompressionType.Snappy;
    }

    /// <summary>
    /// Abstraction for producing messages to Kafka.
    /// </summary>
    /// <typeparam name="TValue">Type of the message payload.</typeparam>
    public interface IKafkaProducer<TValue> : IAsyncDisposable
    {
        /// <summary>
        /// Produces a single message to the specified topic.
        /// </summary>
        /// <param name="topic">Kafka topic.</param>
        /// <param name="key">Partitioning key.</param>
        /// <param name="value">Message payload.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <remarks>
        /// Any failures will surface as <see cref="ProduceException{TKey, TValue}"/>.
        /// </remarks>
        ValueTask ProduceAsync(
            string topic,
            string key,
            TValue value,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Production-quality Kafka producer with JSON value serialization, structured logging,
    /// resiliency and OpenTelemetry tracing hooks.
    /// </summary>
    /// <typeparam name="TValue">Type of the message payload.</typeparam>
    public sealed class KafkaProducer<TValue> : IKafkaProducer<TValue>
    {
        private static readonly ActivitySource ActivitySource =
            new("PaletteStream.Shared.Messaging.KafkaProducer");

        private readonly IProducer<string, TValue> _producer;
        private readonly ILogger _logger;
        private readonly JsonSerializerOptions _serializerOptions;

        public KafkaProducer(
            KafkaProducerConfig config,
            ILogger<KafkaProducer<TValue>> logger)
        {
            ArgumentNullException.ThrowIfNull(config);
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _serializerOptions = new(JsonSerializerDefaults.Web)
            {
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented = false
            };

            _producer = BuildProducer(config);
            _logger.LogInformation(
                "Kafka producer for {Type} initialised with bootstrap servers {BootstrapServers}.",
                typeof(TValue).Name,
                config.BootstrapServers);
        }

        private IProducer<string, TValue> BuildProducer(KafkaProducerConfig options)
        {
            var producerConfig = new ProducerConfig
            {
                BootstrapServers = options.BootstrapServers,
                ClientId         = options.ClientId,
                Acks             = Acks.All,
                LingerMs         = options.LingerMs,
                CompressionType  = options.CompressionType,
                MessageSendMaxRetries = options.RetryCount,
                EnableIdempotence = true, // Safe-produce mode
                EnableDeliveryReports = true
            };

            return new ProducerBuilder<string, TValue>(producerConfig)
                .SetValueSerializer(new JsonAsyncSerializer<TValue>(_serializerOptions))
                .SetErrorHandler((_, e) =>
                {
                    // Centralised error handler to ensure we never silently swallow exceptions
                    _logger.LogError(
                        "Kafka producer error: {Reason} (IsFatal: {IsFatal})",
                        e.Reason,
                        e.IsFatal);
                })
                .Build();
        }

        public async ValueTask ProduceAsync(
            string topic,
            string key,
            TValue value,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(topic))
                throw new ArgumentException("Topic cannot be null or whitespace.", nameof(topic));

            // Trace the produce operation for distributed observability
            using var activity = ActivitySource.StartActivity(
                "kafka.produce",
                ActivityKind.Producer);

            var message = new Message<string, TValue>
            {
                Key   = key,
                Value = value,
            };

            // Embed trace context into Kafka headers for downstream correlation
            if (activity?.Context.TraceId != default)
            {
                var traceParent = $"00-{activity.Context.TraceId}-{activity.Context.SpanId}-01";
                message.Headers ??= new Headers();
                message.Headers.Add("traceparent", Encoding.UTF8.GetBytes(traceParent));
            }

            try
            {
                var result = await _producer
                    .ProduceAsync(topic, message, cancellationToken)
                    .ConfigureAwait(false);

                _logger.LogInformation(
                    "Message produced to {TopicPartitionOffset} (latency {LatencyMs} ms).",
                    result.TopicPartitionOffset,
                    result.Status == PersistenceStatus.Persisted
                        ? (int?)result.Timestamp.UtcDateTime.Subtract(DateTime.UtcNow).TotalMilliseconds * -1
                        : null);
            }
            catch (ProduceException<string, TValue> ex) when (!ex.Error.IsFatal)
            {
                // Non-fatal errors can be retried/requeued depending on calling context
                _logger.LogWarning(
                    ex,
                    "Non-fatal produce error to topic {Topic}: {Reason}",
                    topic,
                    ex.Error.Reason);
                throw;
            }
            catch (ProduceException<string, TValue> ex)
            {
                _logger.LogError(
                    ex,
                    "Fatal produce error to topic {Topic}: {Reason}",
                    topic,
                    ex.Error.Reason);
                throw;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                _logger.LogInformation(
                    "Produce operation to topic {Topic} was canceled.",
                    topic);
                throw;
            }
        }

        public async ValueTask DisposeAsync()
        {
            try
            {
                _logger.LogDebug("Flushing Kafka producer…");
                _producer.Flush(TimeSpan.FromSeconds(5));
                await Task.CompletedTask;
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Kafka producer flush failed.");
            }
            finally
            {
                _logger.LogDebug("Disposing Kafka producer.");
                _producer.Dispose();
            }
        }

        #region Internal JSON serializer
        private sealed class JsonAsyncSerializer<T> : IAsyncSerializer<T>
        {
            private readonly JsonSerializerOptions _options;

            public JsonAsyncSerializer(JsonSerializerOptions options) => _options = options;

            public Task<byte[]> SerializeAsync(T data, SerializationContext context)
            {
                // ReSharper disable once ConvertClosureToMethodGroup — explicit for clarity
                byte[] payload = data is null
                    ? Array.Empty<byte>()
                    : JsonSerializer.SerializeToUtf8Bytes(data, _options);

                return Task.FromResult(payload);
            }
        }
        #endregion
    }
}
```