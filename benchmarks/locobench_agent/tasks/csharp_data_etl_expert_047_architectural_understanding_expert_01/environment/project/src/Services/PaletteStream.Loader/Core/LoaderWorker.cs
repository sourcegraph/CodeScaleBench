```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace PaletteStream.Loader.Core
{
    /// <summary>
    /// A long-running worker that dequeues raw “pigments” from an <see cref="IIngestionQueue"/>,
    /// selects the correct <see cref="ILoaderStrategy"/> on the fly (strategy-pattern),
    /// and persists the processed payload to the Data Lake canvas.
    /// 
    /// The worker is designed for high-throughput scenarios.  It maintains an internal
    /// bounded channel to enable back-pressure and leverages a configurable degree of
    /// parallelism to efficiently saturate available CPU / IO resources.
    /// </summary>
    public sealed class LoaderWorker : BackgroundService
    {
        private readonly IIngestionQueue _ingestionQueue;
        private readonly IServiceProvider _serviceProvider;
        private readonly ILogger<LoaderWorker> _logger;
        private readonly LoaderOptions _options;
        private readonly Channel<PigmentMessage> _channel;
        private readonly ILoadMetricsCollector _metrics;

        public LoaderWorker(
            IIngestionQueue ingestionQueue,
            IServiceProvider serviceProvider,
            IOptions<LoaderOptions> options,
            ILoadMetricsCollector metrics,
            ILogger<LoaderWorker> logger)
        {
            _ingestionQueue = ingestionQueue ?? throw new ArgumentNullException(nameof(ingestionQueue));
            _serviceProvider = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _options = options?.Value ?? throw new ArgumentNullException(nameof(options));
            _metrics = metrics ?? throw new ArgumentNullException(nameof(metrics));

            _channel = Channel.CreateBounded<PigmentMessage>(new BoundedChannelOptions(_options.ChannelCapacity)
            {
                SingleReader = false,
                SingleWriter = true,
                FullMode = BoundedChannelFullMode.Wait
            });
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _logger.LogInformation("LoaderWorker started with {Parallelism} parallelism.", _options.MaxDegreeOfParallelism);

            // Fire-and-forget pump from queue -> channel.
            _ = Task.Run(() => PumpQueueAsync(stoppingToken), stoppingToken);

            // Spin up consumer tasks
            var consumers = new List<Task>();
            for (var i = 0; i < _options.MaxDegreeOfParallelism; i++)
            {
                consumers.Add(Task.Run(() => ConsumeChannelAsync(i, stoppingToken), stoppingToken));
            }

            await Task.WhenAll(consumers);
        }

        #region Producer

        private async Task PumpQueueAsync(CancellationToken ct)
        {
            try
            {
                while (!ct.IsCancellationRequested)
                {
                    var msg = await _ingestionQueue.DequeueAsync(ct).ConfigureAwait(false);
                    await _channel.Writer.WriteAsync(msg, ct).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException)
            {
                // Expected on shutdown.
            }
            catch (Exception ex)
            {
                _logger.LogCritical(ex, "[Pump] Fatal error while reading from ingestion queue.");
            }
            finally
            {
                _channel.Writer.TryComplete();
            }
        }

        #endregion

        #region Consumer

        private async Task ConsumeChannelAsync(int workerId, CancellationToken ct)
        {
            await foreach (var msg in _channel.Reader.ReadAllAsync(ct).ConfigureAwait(false))
            {
                var sw = Stopwatch.StartNew();
                try
                {
                    using var scope = _serviceProvider.CreateScope();
                    var strategyFactory = scope.ServiceProvider.GetRequiredService<ILoaderStrategyFactory>();
                    var strategy = strategyFactory.GetStrategy(msg.Format);

                    _logger.LogDebug("[{Worker}] Loading pigment {PigmentId} via {Strategy}.", workerId, msg.Id, strategy.GetType().Name);

                    await strategy.LoadAsync(msg, ct).ConfigureAwait(false);

                    _metrics.RecordSuccess(msg.SourceSystem, sw.Elapsed);
                    _logger.LogInformation("[{Worker}] Successfully loaded pigment {PigmentId} in {Elapsed}.",
                        workerId, msg.Id, sw.Elapsed);
                }
                catch (OperationCanceledException)
                {
                    // Graceful shutdown or individual timeout.
                    _metrics.RecordCancellation(msg.SourceSystem);
                    _logger.LogWarning("[{Worker}] Loading pigment {PigmentId} cancelled.", workerId, msg.Id);
                }
                catch (Exception ex)
                {
                    _metrics.RecordFailure(msg.SourceSystem, ex);
                    _logger.LogError(ex, "[{Worker}] Failed to load pigment {PigmentId}.", workerId, msg.Id);

                    if (_options.RetryFailedMessages)
                    {
                        // Push to dead-letter or retry queue depending on policy.
                        await _ingestionQueue.RequeueAsync(msg, ct).ConfigureAwait(false);
                    }
                }
            }
        }

        #endregion
    }

    #region Options & Models

    /// <summary>
    /// Configurable settings for <see cref="LoaderWorker"/>.
    /// </summary>
    public sealed class LoaderOptions
    {
        /// <summary>
        /// Max concurrent loader tasks.
        /// </summary>
        public int MaxDegreeOfParallelism { get; set; } = Environment.ProcessorCount;

        /// <summary>
        /// Back-pressure capacity of the internal buffer.
        /// </summary>
        public int ChannelCapacity { get; set; } = 10_000;

        /// <summary>
        /// Whether failed pigments should be re-queued for retry.
        /// </summary>
        public bool RetryFailedMessages { get; set; } = true;
    }

    /// <summary>
    /// Represents a unit of raw data flowing through the Loader service.
    /// </summary>
    public sealed record PigmentMessage
    (
        Guid Id,
        string SourceSystem,
        string Format,
        ReadOnlyMemory<byte> Payload,
        DateTimeOffset EnqueuedAt
    );

    #endregion

    #region Contracts

    /// <summary>
    /// Abstraction over any upstream ingestion mechanism (Kafka, S3, REST, etc.).
    /// </summary>
    public interface IIngestionQueue
    {
        Task<PigmentMessage> DequeueAsync(CancellationToken ct);
        Task RequeueAsync(PigmentMessage message, CancellationToken ct);
    }

    /// <summary>
    /// Factory that chooses the correct loader strategy for the given pigment format.
    /// </summary>
    public interface ILoaderStrategyFactory
    {
        ILoaderStrategy GetStrategy(string format);
    }

    /// <summary>
    /// Strategy interface for loading pigments into the Data Lake.
    /// </summary>
    public interface ILoaderStrategy
    {
        Task LoadAsync(PigmentMessage message, CancellationToken ct);
    }

    /// <summary>
    /// Collects metrics for monitoring and alerting dashboards.
    /// </summary>
    public interface ILoadMetricsCollector
    {
        void RecordSuccess(string sourceSystem, TimeSpan elapsed);
        void RecordFailure(string sourceSystem, Exception ex);
        void RecordCancellation(string sourceSystem);
    }

    #endregion
}
```