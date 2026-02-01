```csharp
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using PaletteStream.Orchestrator.Domain.Events;
using PaletteStream.Orchestrator.Domain.Exceptions;
using PaletteStream.Orchestrator.Infrastructure.Configuration;
using Polly;
using Polly.Retry;

namespace PaletteStream.Orchestrator.Infrastructure.EventPublishers
{
    /// <summary>
    ///     Publishes <see cref="PipelineEvent"/> instances to an external event-stream (Kafka).
    ///     Supports resiliency through exponential-backoff retries and deferred error handling.
    /// </summary>
    public sealed class PipelineEventPublisher : IPipelineEventPublisher, IAsyncDisposable
    {
        private readonly IProducer<string, string> _producer;
        private readonly ILogger<PipelineEventPublisher> _logger;
        private readonly string _topic;
        private readonly JsonSerializerOptions _jsonOptions;
        private readonly AsyncRetryPolicy _retryPolicy;

        public PipelineEventPublisher(
            IProducer<string, string> producer,
            IOptions<KafkaOptions> kafkaOptions,
            ILogger<PipelineEventPublisher> logger)
        {
            _producer = producer ?? throw new ArgumentNullException(nameof(producer));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            if (kafkaOptions?.Value == null)
                throw new ArgumentNullException(nameof(kafkaOptions), "KafkaOptions cannot be null.");

            _topic = kafkaOptions.Value.PipelineEventTopic;
            _jsonOptions = new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented = false
            };

            _retryPolicy = Policy
                .Handle<ProduceException<string, string>>()
                .Or<KafkaException>()
                .WaitAndRetryAsync(
                    kafkaOptions.Value.MaxRetryAttempts,
                    attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
                    OnRetry);
        }

        /// <inheritdoc />
        public async Task PublishAsync(PipelineEvent pipelineEvent, CancellationToken cancellationToken = default)
        {
            if (pipelineEvent == null) throw new ArgumentNullException(nameof(pipelineEvent));

            string messageKey = pipelineEvent.Id.ToString("N");
            string messageValue = JsonSerializer.Serialize(pipelineEvent, _jsonOptions);

            var kafkaMessage = new Message<string, string>
            {
                Key = messageKey,
                Value = messageValue,
                Timestamp = new Timestamp(pipelineEvent.Timestamp.UtcDateTime)
            };

            _logger.LogDebug(
                "Publishing pipeline event {EventType} ({EventId}) to topic {Topic}...",
                pipelineEvent.EventType, pipelineEvent.Id, _topic);

            try
            {
                await _retryPolicy.ExecuteAsync(async () =>
                {
                    // Confluent.Kafka does not support CancellationToken directly—wrapping in Task.Run
                    DeliveryResult<string, string> result = await Task
                        .Run(() => _producer.ProduceAsync(_topic, kafkaMessage), cancellationToken)
                        .ConfigureAwait(false);

                    _logger.LogInformation(
                        "Pipeline event {EventType} ({EventId}) delivered to {Partition}:{Offset}.",
                        pipelineEvent.EventType,
                        pipelineEvent.Id,
                        result.Partition.Value,
                        result.Offset.Value);
                });
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                _logger.LogWarning(
                    "Publishing of event {EventId} cancelled by caller.",
                    pipelineEvent.Id);

                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Failed to publish pipeline event {EventId} after retries.",
                    pipelineEvent.Id);

                throw new EventPublishException(
                    $"Exceeded retry attempts when publishing event {pipelineEvent.Id}.", ex);
            }
        }

        private void OnRetry(Exception exception, TimeSpan delay, int attempt, Context ctx)
        {
            _logger.LogWarning(exception,
                "Publish attempt {Attempt} failed. Retrying in {Delay}...",
                attempt, delay);
        }

        public async ValueTask DisposeAsync()
        {
            try
            {
                _producer.Flush(TimeSpan.FromSeconds(5));
                _producer.Dispose();
                await Task.CompletedTask;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error while disposing Kafka producer.");
            }
        }
    }
}
```