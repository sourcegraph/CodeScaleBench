using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;

namespace PaletteStream.Shared.Messaging
{
    /// <summary>
    /// Abstraction over a Kafka producer used throughout the PaletteStream platform.
    /// Implementations hide the concrete <see cref="IProducer{TKey,TValue}"/> from calling
    /// code and add higher-level functionality such as automatic retry, metrics emission,
    /// distributed tracing, and dead-letter handling.
    /// </summary>
    /// <typeparam name="TKey">The message key type.</typeparam>
    /// <typeparam name="TValue">The message value type.</typeparam>
    public interface IKafkaProducer<in TKey, in TValue>
    {
        /// <summary>
        /// Gets a unique identifier for this producer instance.  Useful for correlating logs
        /// and traces across distributed components.
        /// </summary>
        Guid InstanceId { get; }

        /// <summary>
        /// Publishes a single message to the specified Kafka topic asynchronously.
        /// </summary>
        /// <param name="topic">The Kafka topic.</param>
        /// <param name="key">The key to partition the message by.</param>
        /// <param name="value">The payload (value) of the message.</param>
        /// <param name="headers">
        /// Optional headers to attach to the message (e.g. correlation-id, trace-id, schema-version).
        /// </param>
        /// <param name="cancellationToken">Propagates notification that the operation should be cancelled.</param>
        /// <returns>
        /// A <see cref="DeliveryResult{TKey,TValue}"/> containing
        /// metadata about where the record was written.
        /// </returns>
        Task<DeliveryResult<TKey, TValue>> ProduceAsync(
            string topic,
            TKey key,
            TValue value,
            Headers? headers = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Publishes a batch of messages to Kafka.  Implementations should prefer
        /// using the underlying producer’s <c>ProduceAsync</c> in parallel (or
        /// <c>Produce</c> followed by <c>Flush</c>) while honoring ordering
        /// guarantees per key, where required.
        /// </summary>
        /// <param name="topic">The Kafka topic to which the batch should be published.</param>
        /// <param name="messages">The collection of messages to publish.</param>
        /// <param name="cancellationToken">Token that signals if the caller wishes to cancel the operation.</param>
        Task ProduceBatchAsync(
            string topic,
            IEnumerable<Message<TKey, TValue>> messages,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Flushes any outstanding messages held by the producer.  This should be called
        /// before application shutdown to guarantee at-least-once delivery semantics.
        /// </summary>
        /// <param name="timeout">
        /// The maximum amount of time to block.  If <see langword="null"/>, the producer’s
        /// default timeout is used.
        /// </param>
        void Flush(TimeSpan? timeout = null);

        /// <summary>
        /// Retrieves a JSON-serialized statistics string produced by the underlying
        /// librdkafka client, if enabled via the <c>statistics.interval.ms</c> setting.
        /// </summary>
        /// <returns>The statistics JSON string, or an empty string if unavailable.</returns>
        string GetStatistics();

        /// <summary>
        /// Event raised for every delivery report returned by the broker.  Consumers
        /// may attach handlers to push metrics, emit logs, or implement custom retries.
        /// </summary>
        event Action<DeliveryReport<TKey, TValue>>? MessageDelivered;
    }
}