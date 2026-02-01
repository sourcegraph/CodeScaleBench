```csharp
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using Xunit;
using Polly;
using Polly.Retry;

namespace PaletteStream.ETL.Tests.Architecture
{
    #region Contracts ──────────────────────────────────────────────────────────
    /// <summary>
    /// Basic abstraction for a Kafka-like producer.
    /// </summary>
    /// <typeparam name="TKey">Key type.</typeparam>
    /// <typeparam name="TValue">Value type.</typeparam>
    public interface IKafkaProducer<in TKey, in TValue>
    {
        Task ProduceAsync(string topic, TKey key, TValue value, CancellationToken ct = default);
    }

    /// <summary>
    /// Represents an ETL domain event.
    /// </summary>
    public interface IDomainEvent
    {
        Guid EventId { get; }
        DateTimeOffset OccurredOn { get; }
        string EventType { get; }
    }

    /// <summary>
    /// Sink for messages that could not be published to the primary topic.
    /// </summary>
    public interface IDeadLetterSink
    {
        Task SendAsync(byte[] message, CancellationToken ct = default);
    }
    #endregion

    #region Implementation ────────────────────────────────────────────────────
    /// <summary>
    /// Publishes <see cref="IDomainEvent"/> instances to Kafka with retry +
    /// back-off and a dead-letter fallback.
    /// </summary>
    public sealed class EventPublisher
    {
        private const string DefaultTopic = "etl-domain-events";

        private readonly IKafkaProducer<string, byte[]> _producer;
        private readonly IDeadLetterSink _deadLetterSink;
        private readonly AsyncRetryPolicy _retryPolicy;

        public EventPublisher(
            IKafkaProducer<string, byte[]> producer,
            IDeadLetterSink deadLetterSink,
            int retryCount = 3)
        {
            _producer = producer ?? throw new ArgumentNullException(nameof(producer));
            _deadLetterSink = deadLetterSink ?? throw new ArgumentNullException(nameof(deadLetterSink));

            _retryPolicy = Policy
                .Handle<Exception>() // Capture any broker/transport exceptions.
                .WaitAndRetryAsync(
                    retryCount,
                    retryAttempt => TimeSpan.FromMilliseconds(Math.Pow(2, retryAttempt) * 100),
                    onRetry: (ex, ts, i, _) =>
                    {
                        // In production we'd emit a structured log entry here.
                        Console.WriteLine(
                            $"Retry {i} after {ts.TotalMilliseconds:n0} ms due to: {ex.Message}");
                    });
        }

        public async Task PublishAsync(IDomainEvent domainEvent, CancellationToken ct = default)
        {
            if (domainEvent == null) throw new ArgumentNullException(nameof(domainEvent));

            var serialized = JsonSerializer.SerializeToUtf8Bytes(domainEvent, domainEvent.GetType());

            try
            {
                await _retryPolicy.ExecuteAsync(
                    async token => await _producer.ProduceAsync(
                        DefaultTopic,
                        domainEvent.EventId.ToString("N"),
                        serialized,
                        token),
                    ct);
            }
            catch (Exception finalEx)
            {
                // Fallback to dead-letter sink.
                await _deadLetterSink.SendAsync(serialized, ct);

                // Bubble up so that calling code can still be aware something went wrong.
                throw new EventPublishException(
                    $"Failed to publish event {domainEvent.EventId}", finalEx);
            }
        }
    }

    /// <summary>
    /// Exception thrown when an event could not be published.
    /// </summary>
    public sealed class EventPublishException : Exception
    {
        public EventPublishException(string message, Exception inner)
            : base(message, inner) { }
    }
    #endregion

    #region Dummy Domain Event ────────────────────────────────────────────────
    private sealed class DataPigmentTransformedEvent : IDomainEvent
    {
        public Guid EventId { get; } = Guid.NewGuid();
        public DateTimeOffset OccurredOn { get; } = DateTimeOffset.UtcNow;
        public string EventType => nameof(DataPigmentTransformedEvent);

        public string PigmentName { get; init; } = default!;
        public string Transformation { get; init; } = default!;
        public string Operator { get; init; } = default!;
    }
    #endregion

    #region Tests ─────────────────────────────────────────────────────────────
    public class EventPublisherTests
    {
        private readonly Mock<IKafkaProducer<string, byte[]>> _producerMock =
            new(MockBehavior.Strict);

        private readonly Mock<IDeadLetterSink> _deadLetterMock =
            new(MockBehavior.Strict);

        private EventPublisher BuildSut(int retryCount = 3)
            => new(_producerMock.Object, _deadLetterMock.Object, retryCount);

        private static DataPigmentTransformedEvent CreateSampleEvent()
            => new()
            {
                PigmentName = "Cerulean",
                Transformation = "Aggregation",
                Operator = "GPU-Blend"
            };

        [Fact(DisplayName = "PublishAsync sends event to correct topic with key/value")]
        public async Task PublishAsync_SendsMessage_WhenFirstTrySucceeds()
        {
            // Arrange
            var sut = BuildSut();
            var sample = CreateSampleEvent();

            _producerMock
                .Setup(p => p.ProduceAsync(
                    It.Is<string>(t => t == "etl-domain-events"),
                    It.Is<string>(k => k == sample.EventId.ToString("N")),
                    It.IsAny<byte[]>(),
                    It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask)
                .Verifiable();

            // No calls expected to dead-letter sink.
            _deadLetterMock.VerifyNoOtherCalls();

            // Act
            await sut.PublishAsync(sample);

            // Assert
            _producerMock.Verify(); // Ensures the expected interaction occurred.
        }

        [Fact(DisplayName = "PublishAsync retries and eventually succeeds")]
        public async Task PublishAsync_RetriesAndSucceeds_BeforeExhaustingPolicy()
        {
            // Arrange
            var sut = BuildSut(retryCount: 2);
            var sample = CreateSampleEvent();
            var attempt = 0;

            _producerMock
                .Setup(p => p.ProduceAsync(
                    It.IsAny<string>(),
                    It.IsAny<string>(),
                    It.IsAny<byte[]>(),
                    It.IsAny<CancellationToken>()))
                .Returns(() =>
                {
                    attempt++;
                    // Fail first attempt only
                    if (attempt == 1) throw new TimeoutException("Simulated broker timeout");
                    return Task.CompletedTask;
                });

            // Act
            await sut.PublishAsync(sample);

            // Assert
            attempt.Should().Be(2, "one retry should have been performed");
            _deadLetterMock.VerifyNoOtherCalls();
        }

        [Fact(DisplayName = "PublishAsync pushes to dead-letter sink after all retries fail")]
        public async Task PublishAsync_GoesToDeadLetter_WhenRetriesExhausted()
        {
            // Arrange
            var sut = BuildSut(retryCount: 2);
            var sample = CreateSampleEvent();

            _producerMock
                .Setup(p => p.ProduceAsync(
                    It.IsAny<string>(),
                    It.IsAny<string>(),
                    It.IsAny<byte[]>(),
                    It.IsAny<CancellationToken>()))
                .ThrowsAsync(new InvalidOperationException("Permanent failure"));

            _deadLetterMock
                .Setup(d => d.SendAsync(
                    It.IsAny<byte[]>(),
                    It.IsAny<CancellationToken>()))
                .Returns(Task.CompletedTask)
                .Verifiable();

            // Act
            Func<Task> act = () => sut.PublishAsync(sample);

            // Assert
            await act.Should().ThrowAsync<EventPublishException>();
            _deadLetterMock.Verify();
        }
    }
    #endregion
}
```