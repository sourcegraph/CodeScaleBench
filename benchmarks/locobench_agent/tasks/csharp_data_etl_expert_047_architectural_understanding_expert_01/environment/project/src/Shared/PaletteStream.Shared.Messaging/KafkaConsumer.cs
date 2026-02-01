```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright>
//   © PaletteStream ETL Canvas. All rights reserved.
// </copyright>
// <summary>
//   KafkaConsumer.cs
//   A resilient, production-grade Kafka consumer used throughout the PaletteStream ETL Canvas solution.
//   The consumer supports:
//     ‑ Manual or automatic offset commits
//     ‑ Pluggable deserialization
//     ‑ Circuit-breaker style back-off on failures
//     ‑ Structured logging & metric hooks
//     ‑ Graceful shutdown with cooperative cancellation
// </summary>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Shared.Messaging
{
    /// <summary>
    /// Contract for deserializing an incoming Kafka message payload into a CLR object.
    /// </summary>
    /// <typeparam name="TKey">Kafka message key.</typeparam>
    /// <typeparam name="TValue">Kafka message value.</typeparam>
    public interface IMessageDeserializer<TKey, TValue>
    {
        TValue Deserialize(ConsumeResult<TKey, byte[]> result);
    }

    /// <summary>
    /// Marker interface for background consumers so that they can be registered as hosted services
    /// or supervised by a service orchestrator.
    /// </summary>
    public interface IKafkaConsumer : IAsyncDisposable
    {
        Task StartAsync(CancellationToken ct = default);
        Task StopAsync(CancellationToken ct = default);
    }

    /// <summary>
    /// A resilient Kafka consumer that encapsulates polling, error handling,
    /// deserialization and commit logic.
    /// </summary>
    public sealed class KafkaConsumer<TKey, TValue> : IKafkaConsumer
    {
        private readonly IConsumer<TKey, byte[]> _innerConsumer;
        private readonly IMessageDeserializer<TKey, TValue> _deserializer;
        private readonly Func<TValue, Task> _handler;
        private readonly ILogger<KafkaConsumer<TKey, TValue>> _logger;
        private readonly IEnumerable<string> _topics;
        private readonly bool _enableAutoCommit;
        private readonly TimeSpan _pollTimeout = TimeSpan.FromMilliseconds(250);
        private readonly BackoffStrategy _backoff = new();
        private readonly CancellationTokenSource _internalCts = new();

        private Task? _processingTask;

        /// <summary>
        /// Initializes a new instance of the <see cref="KafkaConsumer{TKey,TValue}"/> class.
        /// </summary>
        /// <param name="topics">The topics to subscribe to.</param>
        /// <param name="consumer">Underlying Confluent consumer.</param>
        /// <param name="deserializer">Deserializer implementation.</param>
        /// <param name="handler">Delegate that processes messages.</param>
        /// <param name="logger">Structured logger.</param>
        /// <param name="enableAutoCommit">Indicates whether offsets are auto-committed.</param>
        /// <exception cref="ArgumentNullException">Thrown when any dependency is null.</exception>
        public KafkaConsumer(
            IEnumerable<string> topics,
            IConsumer<TKey, byte[]> consumer,
            IMessageDeserializer<TKey, TValue> deserializer,
            Func<TValue, Task> handler,
            ILogger<KafkaConsumer<TKey, TValue>> logger,
            bool enableAutoCommit = false)
        {
            _topics = topics ?? throw new ArgumentNullException(nameof(topics));
            _innerConsumer = consumer ?? throw new ArgumentNullException(nameof(consumer));
            _deserializer = deserializer ?? throw new ArgumentNullException(nameof(deserializer));
            _handler = handler ?? throw new ArgumentNullException(nameof(handler));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _enableAutoCommit = enableAutoCommit;
        }

        #region IKafkaConsumer

        public Task StartAsync(CancellationToken ct = default)
        {
            // Guard against multiple starts.
            if (_processingTask != null)
            {
                throw new InvalidOperationException("Consumer already started.");
            }

            _logger.LogInformation("Starting Kafka consumer for topics: {Topics}", string.Join(", ", _topics));
            _innerConsumer.Subscribe(_topics);

            var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, _internalCts.Token);
            _processingTask = Task.Run(() => ConsumeLoopAsync(linked.Token), linked.Token);

            return _processingTask.IsCompleted ? _processingTask : Task.CompletedTask;
        }

        public async Task StopAsync(CancellationToken ct = default)
        {
            if (_processingTask == null)
            {
                _logger.LogWarning("Stop requested but consumer was never started.");
                return;
            }

            _internalCts.Cancel();

            // Allow configured timeout for graceful drain.
            if (_enableAutoCommit)
            {
                _logger.LogDebug("Committing offsets before shutdown.");
                SafeCommit();
            }

            try
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeout.CancelAfter(TimeSpan.FromSeconds(30));
                await Task.WhenAny(_processingTask, Task.Delay(Timeout.Infinite, timeout.Token));
            }
            catch (OperationCanceledException)
            {
                _logger.LogWarning("Forced shutdown due to timeout.");
            }
            finally
            {
                _innerConsumer.Close();
                _innerConsumer.Dispose();
                _logger.LogInformation("Kafka consumer shutdown completed.");
            }
        }

        public async ValueTask DisposeAsync()
        {
            await StopAsync();
        }

        #endregion

        #region Core Loop

        private async Task ConsumeLoopAsync(CancellationToken ct)
        {
            var sw = Stopwatch.StartNew();
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    var consumeResult = _innerConsumer.Consume(_pollTimeout);
                    if (consumeResult == null) continue; // No message

                    // Reset backoff counter on successful poll.
                    _backoff.Reset();

                    TValue payload;
                    try
                    {
                        payload = _deserializer.Deserialize(consumeResult);
                    }
                    catch (Exception ex)
                    {
                        HandleDeserializationError(consumeResult, ex);
                        continue; // skip to next message
                    }

                    // Process the message using the provided delegate.
                    await _handler(payload);

                    if (!_enableAutoCommit)
                    {
                        SafeCommit(consumeResult);
                    }
                }
                catch (ConsumeException ce)
                {
                    _logger.LogError(ce, "Fatal error in Consume: {@Error}", ce.Error);
                    await BackoffAsync(ct);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested)
                {
                    // Graceful shutdown requested.
                    _logger.LogInformation("Consumer cancellation requested; stopping.");
                    break;
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unhandled exception in Kafka consumer loop.");
                    await BackoffAsync(ct);
                }
            }

            sw.Stop();
            _logger.LogInformation("Consumer loop exited after {Elapsed:g}.", sw.Elapsed);
        }

        #endregion

        #region Helper Methods

        private void HandleDeserializationError(ConsumeResult<TKey, byte[]> result, Exception ex)
        {
            // In production this may route the bad payload to a dead-letter queue.
            _logger.LogError(ex,
                "Failed to deserialize message from topic {Topic} at {Partition}:{Offset}. Skipping.",
                result.Topic, result.Partition, result.Offset);
        }

        private void SafeCommit(ConsumeResult<TKey, byte[]>? result = null)
        {
            try
            {
                if (result == null)
                {
                    _innerConsumer.Commit();
                }
                else
                {
                    _innerConsumer.Commit(result);
                }
            }
            catch (KafkaException ke)
            {
                _logger.LogWarning(ke, "Failed to commit offsets: {Reason}", ke.Error.Reason);
            }
        }

        private async Task BackoffAsync(CancellationToken ct)
        {
            var delay = _backoff.Next();
            _logger.LogWarning("Backing off for {Delay} after error.", delay);
            try
            {
                await Task.Delay(delay, ct);
            }
            catch (OperationCanceledException)
            {
                // Swallow since shutdown requested.
            }
        }

        #endregion

        #region Nested Backoff Strategy

        /// <summary>
        /// Very small, self-contained exponential backoff implementation with jitter.
        /// </summary>
        private sealed class BackoffStrategy
        {
            private const int MaxExponent = 6; // 2^6 * Base = 64 * 250ms ≈ 16s
            private readonly Random _rng = new();
            private readonly TimeSpan _baseDelay = TimeSpan.FromMilliseconds(250);
            private int _failureCount;

            public TimeSpan Next()
            {
                var exponent = Math.Min(_failureCount++, MaxExponent);
                var delay = TimeSpan.FromMilliseconds(_baseDelay.TotalMilliseconds * Math.Pow(2, exponent));

                // Add jitter (+/- 15%).
                var jitterPercentage = _rng.NextDouble() * 0.3 - 0.15;
                var jitter = TimeSpan.FromMilliseconds(delay.TotalMilliseconds * jitterPercentage);
                return delay + jitter;
            }

            public void Reset() => _failureCount = 0;
        }

        #endregion
    }
}
```