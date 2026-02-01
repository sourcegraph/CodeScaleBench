```csharp
using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Polly;
using Polly.Retry;
using RabbitMQ.Client;
using RabbitMQ.Client.Events;
using RabbitMQ.Client.Exceptions;

namespace CanvasCraft.Infrastructure.Services
{
    /// <summary>
    /// Represents configuration options for the RabbitMQ service.
    /// </summary>
    public sealed class RabbitMqOptions
    {
        /// <summary>
        /// The URI pointing to the RabbitMQ broker.
        /// </summary>
        public string ConnectionUri { get; init; } = default!;

        /// <summary>
        /// Default exchange used when none is explicitly provided.
        /// </summary>
        public string DefaultExchange { get; init; } = "";

        /// <summary>
        /// Number of retry attempts when publishing fails.
        /// </summary>
        public int PublishRetryCount { get; init; } = 3;

        /// <summary>
        /// Interval in seconds between retries.
        /// </summary>
        public int RetryBackoffSeconds { get; init; } = 2;

        /// <summary>
        /// Consumer prefetch count.
        /// </summary>
        public ushort PrefetchCount { get; init; } = 50;
    }

    /// <summary>
    /// Contract for RabbitMQ operations used by CanvasCraft ML Studio.
    /// </summary>
    public interface IRabbitMqService : IDisposable
    {
        Task PublishAsync<TMessage>(
            TMessage message,
            string routingKey,
            string? exchange = null,
            CancellationToken cancellationToken = default);

        Task<IDisposable> SubscribeAsync<TMessage>(
            string queue,
            Func<TMessage, Task> onMessageAsync,
            CancellationToken cancellationToken = default);

        bool IsHealthy { get; }
    }

    /// <summary>
    /// Production-grade RabbitMQ service responsible for resilient
    /// publishing and consuming of messages across the application.
    /// </summary>
    public sealed class RabbitMqService : IRabbitMqService
    {
        private readonly IConnection _connection;
        private readonly ConcurrentDictionary<string, IModel> _channels = new();
        private readonly ILogger<RabbitMqService> _logger;
        private readonly RabbitMqOptions _options;
        private readonly AsyncRetryPolicy _publishRetryPolicy;
        private readonly AsyncRetryPolicy _connectionRetryPolicy;
        private volatile bool _disposed;

        public bool IsHealthy => _connection.IsOpen && !_disposed;

        public RabbitMqService(
            IOptions<RabbitMqOptions> options,
            ILogger<RabbitMqService> logger,
            IHostApplicationLifetime lifetime)
        {
            _options = options?.Value ?? throw new ArgumentNullException(nameof(options));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            _connectionRetryPolicy = Policy
                .Handle<BrokerUnreachableException>()
                .Or<SocketException>()
                .WaitAndRetryForever(
                    retryAttempt => TimeSpan.FromSeconds(Math.Min(retryAttempt, 30)),
                    (ex, ts) =>
                    {
                        _logger.LogWarning(ex, "RabbitMQ connection attempt failed, retrying in {Delay}s", ts.TotalSeconds);
                    });

            _publishRetryPolicy = Policy
                .Handle<Exception>()
                .WaitAndRetryAsync(
                    _options.PublishRetryCount,
                    retry => TimeSpan.FromSeconds(_options.RetryBackoffSeconds),
                    (ex, ts, retry, _) =>
                    {
                        _logger.LogWarning(ex,
                            "Publish attempt {Retry}/{RetryCount} failed, retrying in {Delay}s",
                            retry, _options.PublishRetryCount, ts.TotalSeconds);
                    });

            _connection = CreateConnection();

            lifetime.ApplicationStopping.Register(OnApplicationStopping);
        }

        #region Publish

        public async Task PublishAsync<TMessage>(
            TMessage message,
            string routingKey,
            string? exchange = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();

            exchange ??= _options.DefaultExchange;

            byte[] body = Serialize(message);

            await _publishRetryPolicy.ExecuteAsync(async ct =>
            {
                using var channel = GetOrCreateChannel(exchange);
                var properties = channel.CreateBasicProperties();
                properties.Persistent = true;

                channel.BasicPublish(
                    exchange: exchange,
                    routingKey: routingKey,
                    mandatory: false,
                    basicProperties: properties,
                    body: body);

                await Task.CompletedTask; // Maintain async signature
            }, cancellationToken);
        }

        private static byte[] Serialize<TMessage>(TMessage message)
        {
            return JsonSerializer.SerializeToUtf8Bytes(
                message,
                new JsonSerializerOptions
                {
                    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                    WriteIndented = false
                });
        }

        #endregion

        #region Subscribe

        public async Task<IDisposable> SubscribeAsync<TMessage>(
            string queue,
            Func<TMessage, Task> onMessageAsync,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();

            var channel = _connection.CreateModel();
            channel.BasicQos(prefetchSize: 0, prefetchCount: _options.PrefetchCount, global: false);

            var consumer = new AsyncEventingBasicConsumer(channel);

            consumer.Received += async (_, ea) =>
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    channel.BasicNack(ea.DeliveryTag, multiple: false, requeue: true);
                    return;
                }

                try
                {
                    TMessage? message = Deserialize<TMessage>(ea.Body);

                    if (message is null)
                    {
                        _logger.LogWarning("Received null/invalid message. Nack with requeue=false");
                        channel.BasicNack(ea.DeliveryTag, false, false);
                        return;
                    }

                    await onMessageAsync(message);

                    channel.BasicAck(deliveryTag: ea.DeliveryTag, multiple: false);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unhandled exception while processing message. Nack with requeue=false");
                    channel.BasicNack(deliveryTag: ea.DeliveryTag, multiple: false, requeue: false);
                }
            };

            string consumerTag = channel.BasicConsume(
                queue: queue,
                autoAck: false,
                consumer: consumer);

            _logger.LogInformation("Subscribed to queue '{Queue}' with consumer tag '{ConsumerTag}'", queue, consumerTag);

            IDisposable subscription = new Subscription(channel, consumerTag, _logger);

            // Allow awaiting to satisfy async signature
            await Task.CompletedTask;

            return subscription;
        }

        private static TMessage? Deserialize<TMessage>(ReadOnlyMemory<byte> body)
        {
            return JsonSerializer.Deserialize<TMessage>(body.Span);
        }

        #endregion

        #region Connection / Channels

        private IConnection CreateConnection()
        {
            return _connectionRetryPolicy.Execute(() =>
            {
                var factory = new ConnectionFactory
                {
                    Uri = new Uri(_options.ConnectionUri),
                    DispatchConsumersAsync = true,
                    RequestedConnectionTimeout = TimeSpan.FromSeconds(10)
                };

                _logger.LogInformation("Attempting to connect to RabbitMQ at {Uri}", _options.ConnectionUri);
                var connection = factory.CreateConnection();
                connection.ConnectionShutdown += OnConnectionShutdown;
                return connection;
            });
        }

        private IModel GetOrCreateChannel(string exchange)
        {
            return _channels.GetOrAdd(exchange, ex =>
            {
                var channel = _connection.CreateModel();
                if (!string.IsNullOrWhiteSpace(ex))
                {
                    channel.ExchangeDeclare(exchange: ex, type: ExchangeType.Topic, durable: true, autoDelete: false);
                }

                return channel;
            });
        }

        private void OnConnectionShutdown(object? sender, ShutdownEventArgs e)
        {
            _logger.LogWarning("RabbitMQ connection shutdown: {ReplyCode}-{ReplyText}", e.ReplyCode, e.ReplyText);
        }

        #endregion

        #region Disposing

        private void OnApplicationStopping()
        {
            Dispose();
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            foreach (var channel in _channels.Values)
            {
                if (channel.IsOpen)
                    channel.Close();
                channel.Dispose();
            }

            _channels.Clear();

            if (_connection.IsOpen)
                _connection.Close();

            _connection.Dispose();
            _logger.LogInformation("RabbitMQ service disposed.");
        }

        private void EnsureNotDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(RabbitMqService));
        }

        #endregion

        #region Nested subscription disposable

        private sealed class Subscription : IDisposable
        {
            private readonly IModel _channel;
            private readonly string _consumerTag;
            private readonly ILogger _logger;
            private bool _disposed;

            public Subscription(IModel channel, string consumerTag, ILogger logger)
            {
                _channel = channel;
                _consumerTag = consumerTag;
                _logger = logger;
            }

            public void Dispose()
            {
                if (_disposed) return;
                _disposed = true;

                try
                {
                    if (_channel.IsOpen)
                        _channel.BasicCancel(_consumerTag);

                    if (_channel.IsOpen)
                        _channel.Close();

                    _channel.Dispose();
                    _logger.LogInformation("RabbitMQ consumer '{ConsumerTag}' disposed.", _consumerTag);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error disposing consumer '{ConsumerTag}'", _consumerTag);
                }
            }
        }

        #endregion
    }
}
```