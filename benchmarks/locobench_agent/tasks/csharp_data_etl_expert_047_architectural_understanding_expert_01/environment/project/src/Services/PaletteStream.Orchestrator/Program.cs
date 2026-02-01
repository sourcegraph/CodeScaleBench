```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Orchestrator/Program.cs

#nullable enable
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Hangfire;
using Hangfire.MemoryStorage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Orchestrator
{
    /// <summary>
    /// Entry-point for the PaletteStream Orchestrator service.
    /// Bootstraps dependency-injection, config, logging, Hangfire, and streaming coordinators.
    /// </summary>
    public sealed class Program
    {
        public static async Task Main(string[] args)
        {
            IHost host = Host.CreateDefaultBuilder(args)
                .ConfigureAppConfiguration((ctx, cfg) =>
                {
                    cfg.AddJsonFile("appsettings.json", optional: true)
                       .AddEnvironmentVariables()
                       .AddCommandLine(args);
                })
                .ConfigureLogging((ctx, logging) =>
                {
                    logging.ClearProviders();
                    logging.AddConsole();
                    logging.AddDebug();
                })
                .ConfigureServices((ctx, services) =>
                {
                    // Hangfire (micro-batch scheduler)
                    services.AddHangfire(config =>
                    {
                        config.UseMemoryStorage(); // production: swap with persistent storage (e.g., PostgreSQL, Redis)
                    });
                    services.AddHangfireServer();

                    // Pipeline registry & orchestration services
                    services.AddSingleton<IPipelineRegistry, PipelineRegistry>();
                    services.AddSingleton<IEventBus, EventBus>();
                    services.AddSingleton<IDataQualityService, DataQualityService>();

                    // Coordinators
                    services.AddHostedService<BatchJobScheduler>();
                    services.AddHostedService<StreamingJobCoordinator>();
                })
                .UseConsoleLifetime()
                .Build();

            await host.RunAsync();
        }
    }

    #region Service Contracts

    /// <summary>
    /// Publishes domain events to observers (monitoring, alerting, etc.).
    /// </summary>
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
        IDisposable Subscribe<TEvent>(Action<TEvent> handler);
    }

    /// <summary>
    /// Holds runtime ETL pipelines and exposes CRUD operations.
    /// </summary>
    public interface IPipelineRegistry
    {
        void Register(string pipelineId, Func<CancellationToken, Task> pipeline);
        bool TryGet(string pipelineId, out Func<CancellationToken, Task>? pipeline);
        IEnumerable<string> List();
    }

    /// <summary>
    /// Performs pre/post-execution data validation and quality checks.
    /// </summary>
    public interface IDataQualityService
    {
        Task ValidateAsync(string pipelineId, CancellationToken token = default);
    }

    #endregion

    #region Infrastructure Implementations

    internal sealed class EventBus : IEventBus
    {
        // For simplicity, naive in-process pub/sub implementation.
        private readonly ConcurrentDictionary<Type, List<Delegate>> _handlers = new();

        public void Publish<TEvent>(TEvent @event)
        {
            if (_handlers.TryGetValue(typeof(TEvent), out var delegates))
            {
                foreach (var del in delegates!.OfType<Action<TEvent>>())
                {
                    try
                    {
                        del(@event);
                    }
                    catch
                    {
                        // swallow to avoid bringing down publisher; consider logging
                    }
                }
            }
        }

        public IDisposable Subscribe<TEvent>(Action<TEvent> handler)
        {
            var handlers = _handlers.GetOrAdd(typeof(TEvent), _ => new List<Delegate>());
            lock (handlers)
            {
                handlers.Add(handler);
            }

            return new Unsubscriber(() =>
            {
                lock (handlers)
                {
                    handlers.Remove(handler);
                }
            });
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly Action _dispose;
            private bool _disposed;

            public Unsubscriber(Action dispose) => _dispose = dispose;

            public void Dispose()
            {
                if (!_disposed)
                {
                    _disposed = true;
                    _dispose();
                }
            }
        }
    }

    internal sealed class PipelineRegistry : IPipelineRegistry
    {
        private readonly ConcurrentDictionary<string, Func<CancellationToken, Task>> _pipelines = new();

        public void Register(string pipelineId, Func<CancellationToken, Task> pipeline) =>
            _pipelines[pipelineId] = pipeline;

        public bool TryGet(string pipelineId, out Func<CancellationToken, Task>? pipeline) =>
            _pipelines.TryGetValue(pipelineId, out pipeline);

        public IEnumerable<string> List() => _pipelines.Keys;
    }

    internal sealed class DataQualityService : IDataQualityService
    {
        private readonly ILogger<DataQualityService> _logger;
        private readonly IEventBus _events;

        public DataQualityService(ILogger<DataQualityService> logger, IEventBus events)
        {
            _logger = logger;
            _events = events;
        }

        public async Task ValidateAsync(string pipelineId, CancellationToken token = default)
        {
            // Simulate heavy validation work.
            _logger.LogInformation("Running data-quality checks for pipeline {PipelineId}", pipelineId);
            await Task.Delay(TimeSpan.FromSeconds(1), token);

            // notify observers
            _events.Publish(new DataQualityPassedEvent(pipelineId));
        }

        public readonly record struct DataQualityPassedEvent(string PipelineId);
    }

    #endregion

    #region Hosted Services

    /// <summary>
    /// Orchestrates batch pipelines using Hangfire jobs.
    /// </summary>
    internal sealed class BatchJobScheduler : BackgroundService
    {
        private readonly ILogger<BatchJobScheduler> _logger;
        private readonly IPipelineRegistry _registry;
        private readonly IDataQualityService _quality;

        public BatchJobScheduler(
            ILogger<BatchJobScheduler> logger,
            IPipelineRegistry registry,
            IDataQualityService quality)
        {
            _logger = logger;
            _registry = registry;
            _quality = quality;
        }

        protected override Task ExecuteAsync(CancellationToken stoppingToken)
        {
            // Kick-off a recurring demo job every minute.
            RecurringJob.AddOrUpdate(
                "demo-pipeline",
                () => ExecutePipelineAsync("demo-pipeline", CancellationToken.None),
                Cron.Minutely);

            // Register a dummy pipeline
            _registry.Register("demo-pipeline", token =>
            {
                _logger.LogInformation("Running demo pipeline (batch)...");
                return Task.Delay(TimeSpan.FromSeconds(2), token);
            });

            _logger.LogInformation("BatchJobScheduler started");
            return Task.CompletedTask;
        }

        // Hangfire background method must be public & static-friendly
        public async Task ExecutePipelineAsync(string pipelineId, CancellationToken token)
        {
            if (!_registry.TryGet(pipelineId, out var pipeline))
            {
                _logger.LogWarning("Pipeline {PipelineId} not found, skipping.", pipelineId);
                return;
            }

            try
            {
                _logger.LogInformation("Starting pipeline {PipelineId}", pipelineId);
                await _quality.ValidateAsync(pipelineId, token);
                await pipeline!(token);
                _logger.LogInformation("Completed pipeline {PipelineId}", pipelineId);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error while executing pipeline {PipelineId}", pipelineId);
                // TODO: push to dead-letter or compensating transaction manager.
            }
        }
    }

    /// <summary>
    /// Coordinates Kafka streaming pipelines.
    /// </summary>
    internal sealed class StreamingJobCoordinator : BackgroundService
    {
        private const string Topic = "palettestream.ingest";
        private readonly ILogger<StreamingJobCoordinator> _logger;
        private readonly IPipelineRegistry _registry;
        private readonly IConfiguration _config;
        private readonly IDataQualityService _quality;

        public StreamingJobCoordinator(
            ILogger<StreamingJobCoordinator> logger,
            IPipelineRegistry registry,
            IConfiguration config,
            IDataQualityService quality)
        {
            _logger = logger;
            _registry = registry;
            _config = config;
            _quality = quality;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            var kafkaConfig = new ConsumerConfig
            {
                BootstrapServers = _config.GetValue<string>("Kafka:BootstrapServers", "localhost:9092"),
                GroupId = "palettestream.orchestrator",
                AutoOffsetReset = AutoOffsetReset.Earliest
            };

            using var consumer = new ConsumerBuilder<Ignore, string>(kafkaConfig).Build();
            consumer.Subscribe(Topic);

            _registry.Register("stream-echo", async token =>
            {
                // placeholder pipeline that echoes messages to console
                _logger.LogInformation("Echo stream pipeline activated");
                await Task.Delay(500, token);
            });

            _logger.LogInformation("Kafka consumer started on topic {Topic}", Topic);

            try
            {
                while (!stoppingToken.IsCancellationRequested)
                {
                    try
                    {
                        var cr = consumer.Consume(stoppingToken);
                        await HandleMessageAsync(cr.Message.Value, stoppingToken);
                    }
                    catch (ConsumeException ex)
                    {
                        _logger.LogError(ex, "Kafka consume error: {Reason}", ex.Error.Reason);
                    }
                }
            }
            catch (OperationCanceledException)
            {
                _logger.LogInformation("StreamingJobCoordinator is stopping due to cancellation.");
            }
            finally
            {
                consumer.Close();
            }
        }

        private async Task HandleMessageAsync(string payload, CancellationToken token)
        {
            const string pipelineId = "stream-echo";
            if (!_registry.TryGet(pipelineId, out var pipeline))
            {
                _logger.LogWarning("Streaming pipeline {PipelineId} not registered. Dropping message.", pipelineId);
                return;
            }

            _logger.LogDebug("Received streaming payload: {Payload}", payload);

            try
            {
                await _quality.ValidateAsync(pipelineId, token);
                await pipeline!(token);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Exception in streaming pipeline {PipelineId}. Payload: {Payload}", pipelineId, payload);
                // TODO: push to dead-letter topic.
            }
        }
    }

    #endregion
}
```