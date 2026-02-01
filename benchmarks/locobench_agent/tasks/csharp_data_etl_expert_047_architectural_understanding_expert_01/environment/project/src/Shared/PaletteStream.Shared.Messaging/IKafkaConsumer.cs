```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;

namespace PaletteStream.Shared.Messaging
{
    /// <summary>
    /// Abstraction layer around a Kafka consumer (Confluent.Kafka).
    /// Exposes a minimal but production-ready surface that:
    ///  •   Works for both streaming and micro-batch (poll-based) scenarios
    ///  •   Can be mocked or substituted in unit / integration testing
    ///  •   Provides strongly-typed events for observability & diagnostics
    /// </summary>
    /// <typeparam name="TKey">Ser-desed message key type.</typeparam>
    /// <typeparam name="TValue">Ser-desed message value type.</typeparam>
    public interface IKafkaConsumer<TKey, TValue> : IDisposable
    {
        #region Observability

        /// <summary>
        /// Raised every time a message is successfully consumed and deserialized.
        /// NOTE:
        ///   •  The event is fired on the thread that executed the <c>Consume</c> / poll loop.
        ///   •  Heavy logic in handlers may block the consumer-loop if not carefully scheduled.
        /// </summary>
        event EventHandler<KafkaMessageReceivedEventArgs<TKey, TValue>>? MessageReceived;

        /// <summary>
        /// Raised when the underlying consumer emits an error (fatal or non-fatal).
        /// </summary>
        event EventHandler<KafkaConsumerErrorEventArgs>? Error;

        /// <summary>
        /// Raised when the underlying consumer emits a log message.
        /// </summary>
        event EventHandler<KafkaConsumerLogEventArgs>? Log;

        #endregion

        #region Subscription / Assignment

        /// <summary>
        /// Subscribes the consumer to a single topic.
        /// </summary>
        /// <param name="topic">Kafka topic name.</param>
        void Subscribe(string topic);

        /// <summary>
        /// Subscribes the consumer to a list of topics (common in multi-tenant pipelines).
        /// </summary>
        /// <param name="topics">Collection of topic names.</param>
        void Subscribe(IEnumerable<string> topics);

        /// <summary>
        /// Directly assigns the consumer to a specific set of partitions / offsets.
        /// Useful for stateful re-processing and replay scenarios.
        /// </summary>
        /// <param name="partitions">Partitions with offsets.</param>
        void Assign(IEnumerable<TopicPartitionOffset> partitions);

        /// <summary>
        /// Unsubscribes from the currently subscribed topics (leaves the consumer group).
        /// </summary>
        void Unsubscribe();

        #endregion

        #region Consumption (imperative)

        /// <summary>
        /// Synchronously poll Kafka for a single message.
        /// </summary>
        /// <param name="timeout">
        /// The maximum time to wait; <see cref="ConsumeResult{TKey,TValue}"/> may be null when timed-out.
        /// </param>
        /// <param name="cancellationToken">Token to abort the underlying blocking call.</param>
        /// <returns>A consume result or <c>null</c> if the call timed-out.</returns>
        ConsumeResult<TKey, TValue>? Consume(
            TimeSpan timeout,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Commit the offset for a previously consumed record.
        /// </summary>
        /// <param name="result">The result returned by <c>Consume</c>.</param>
        void Commit(ConsumeResult<TKey, TValue> result);

        /// <summary>
        /// Asynchronous variant of <see cref="Commit(ConsumeResult{TKey, TValue})"/>.
        /// </summary>
        /// <param name="result">The result returned by <c>Consume</c>.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        Task CommitAsync(
            ConsumeResult<TKey, TValue> result,
            CancellationToken cancellationToken = default);

        #endregion

        #region Consumption (continuous)

        /// <summary>
        /// Starts an asynchronous, long-running loop that continuously consumes
        /// messages until <paramref name="cancellationToken" /> is cancelled.
        ///
        /// Typical pattern:
        /// <code>
        /// await consumer.RunAsync(
        ///     result => transformer.ProcessAsync(result, ct), ct);
        /// </code>
        /// All exceptions thrown by <paramref name="handler" /> are bubbled up
        /// as <see cref="KafkaMessageHandlingException"/> to allow the caller
        /// to decide on restart / backoff strategies.
        /// </summary>
        /// <param name="handler">User-provided delegate that processes each message.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        Task RunAsync(
            Func<ConsumeResult<TKey, TValue>, Task> handler,
            CancellationToken cancellationToken = default);

        #endregion
    }

    #region Event-arg DTOs

    /// <summary>
    /// Arguments for <see cref="IKafkaConsumer{TKey, TValue}.MessageReceived"/> event.
    /// </summary>
    public sealed class KafkaMessageReceivedEventArgs<TKey, TValue> : EventArgs
    {
        public KafkaMessageReceivedEventArgs(ConsumeResult<TKey, TValue> result) =>
            Result = result;

        /// <summary>
        /// Gets the raw consume result containing the key, value, topic, partition, offset, etc.
        /// </summary>
        public ConsumeResult<TKey, TValue> Result { get; }
    }

    /// <summary>
    /// Arguments for <see cref="IKafkaConsumer{TKey, TValue}.Error"/> event.
    /// Wraps <see cref="Confluent.Kafka.Error"/> making it easier to test /
    /// serialize to OpenTelemetry / Serilog sinks.
    /// </summary>
    public sealed class KafkaConsumerErrorEventArgs : EventArgs
    {
        public KafkaConsumerErrorEventArgs(Error error, bool isFatal) =>
            (Error, IsFatal) = (error, isFatal);

        public Error Error { get; }
        public bool IsFatal { get; }
    }

    /// <summary>
    /// Arguments for <see cref="IKafkaConsumer{TKey, TValue}.Log"/> event.
    /// </summary>
    public sealed class KafkaConsumerLogEventArgs : EventArgs
    {
        public KafkaConsumerLogEventArgs(LogMessage message) => Message = message;

        public LogMessage Message { get; }
    }

    #endregion

    #region Exception helpers

    /// <summary>
    /// Exception thrown when the user-supplied message handler fails.
    /// The original exception is preserved in <see cref="InnerException"/>.
    /// </summary>
    public sealed class KafkaMessageHandlingException : Exception
    {
        public KafkaMessageHandlingException(
            string topic,
            Partition partition,
            Offset offset,
            Exception inner)
            : base(
                $"An exception occurred while handling message at " +
                $"{topic}[{partition}]@{offset}. See inner exception for details.",
                inner) =>
            (Topic, Partition, Offset) = (topic, partition, offset);

        public string Topic { get; }
        public Partition Partition { get; }
        public Offset Offset { get; }
    }

    #endregion
}
```