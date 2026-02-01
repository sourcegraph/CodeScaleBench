```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Transformer/Program.cs
// Project: PaletteStream ETL Canvas (data_etl)
// Description: Entry-point and bootstrapper for the Transformer micro-service.  Responsible for
//              wiring-up the host, dependency-injection container, background workers, and the
//              Strategy/Observer plumbing that powers real-time stream transformations.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Transformer
{
    internal static class Program
    {
        public static async Task Main(string[] args)
        {
            // Build and run the .NET Generic Host
            IHost host = Host.CreateDefaultBuilder(args)
                .ConfigureHostConfiguration(cfg =>
                {
                    // Enable docker/k8s friendly env-var overrides (e.g. "Kafka__BootstrapServers")
                    cfg.AddEnvironmentVariables(prefix: "PALETTESTREAM__");
                    if (args != null) cfg.AddCommandLine(args);
                })
                .ConfigureAppConfiguration((ctx, builder) =>
                {
                    // Load additional configuration sources if present
                    builder.AddJsonFile("appsettings.Local.json", optional: true)
                           .AddEnvironmentVariables();
                })
                .ConfigureLogging((ctx, logging) =>
                {
                    logging.ClearProviders();
                    logging.AddConsole()
                           .AddDebug();
                })
                .ConfigureServices((ctx, services) =>
                {
                    // ------------ Options & Settings ------------
                    services.Configure<KafkaOptions>(ctx.Configuration.GetSection("Kafka"));

                    // ------------ Strategy Pattern registrations ------------
                    services.AddSingleton<ITransformationStrategy, AggregationStrategy>();
                    services.AddSingleton<ITransformationStrategy, EnrichmentStrategy>();
                    services.AddSingleton<ITransformationStrategy, AnonymizationStrategy>();

                    // ------------ Observer Pattern registrations ------------
                    services.AddSingleton<ITransformationObserver, LoggingObserver>();
                    services.AddSingleton<ITransformationObserver, MetricsObserver>();

                    // ------------ Core Transformer Engine ------------
                    services.AddSingleton<ITransformerEngine, TransformerEngine>();

                    // ------------ I/O (Kafka) ------------
                    // In real production code this would be backed by Confluent.Kafka Consumer/Producer.
                    services.AddSingleton<IStreamClient, InMemoryStreamClient>();

                    // ------------ Background Worker ------------
                    services.AddHostedService<StreamTransformerService>();
                })
                .Build();

            await host.RunAsync();
        }
    }

    #region --- Options ---------------------------------------------------------------------------------------------

    public sealed record KafkaOptions
    {
        public string BootstrapServers { get; init; } = "localhost:9092";
        public string InputTopic { get; init; } = "palette.raw";
        public string OutputTopic { get; init; } = "palette.refined";
        public string ConsumerGroupId { get; init; } = "palette.transformer";
        public bool   EnableAutoCommit { get; init; } = true;
    }

    #endregion

    #region --- Background Worker ------------------------------------------------------------------------------------

    /// <summary>
    ///    Continuously consumes messages from an input topic, applies configured transformations,
    ///    and publishes the results downstream.  Fault-tolerant and back-pressure aware.
    /// </summary>
    internal sealed class StreamTransformerService : BackgroundService
    {
        private readonly ILogger<StreamTransformerService> _logger;
        private readonly IStreamClient                     _stream;
        private readonly ITransformerEngine                _engine;

        public StreamTransformerService(
            ILogger<StreamTransformerService> logger,
            IStreamClient stream,
            ITransformerEngine engine)
        {
            _logger  = logger;
            _stream  = stream;
            _engine  = engine;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _logger.LogInformation("🎨 PaletteStream Transformer started.");

            await foreach (var raw in _stream.ConsumeAsync(stoppingToken))
            {
                try
                {
                    TransformationContext ctx = new(raw.Payload, raw.Metadata);

                    // Execute the transformation pipeline
                    TransformationResult result = await _engine.TransformAsync(ctx, stoppingToken);

                    await _stream.ProduceAsync(result.Payload, result.Metadata, stoppingToken);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Errored while processing message {@Message}", raw);
                    // In production, failed messages would be routed to a dead-letter topic.
                }
            }
        }
    }

    #endregion

    #region --- Transformer Engine -----------------------------------------------------------------------------------

    /// <summary>
    ///    Coordinates the execution of a chain of transformation strategies and notifies observers
    ///    about transformation lifecycle events.
    /// </summary>
    internal interface ITransformerEngine
    {
        Task<TransformationResult> TransformAsync(
            TransformationContext context,
            CancellationToken      token = default);
    }

    internal sealed class TransformerEngine : ITransformerEngine
    {
        private readonly IEnumerable<ITransformationStrategy> _strategies;
        private readonly IEnumerable<ITransformationObserver> _observers;
        private readonly ILogger<TransformerEngine>           _logger;

        public TransformerEngine(
            IEnumerable<ITransformationStrategy> strategies,
            IEnumerable<ITransformationObserver> observers,
            ILogger<TransformerEngine> logger)
        {
            _strategies = strategies;
            _observers  = observers;
            _logger     = logger;
        }

        public async Task<TransformationResult> TransformAsync(
            TransformationContext context,
            CancellationToken token = default)
        {
            _logger.LogDebug("Starting transformation for CorrelationId={CorrelationId}", context.Metadata.CorrelationId);
            foreach (ITransformationObserver observer in _observers) observer.OnBeforeTransform(context);

            TransformationPayload currentPayload = context.Payload;

            foreach (ITransformationStrategy strategy in _strategies)
            {
                token.ThrowIfCancellationRequested();
                currentPayload = await strategy.ApplyAsync(currentPayload, token);
            }

            var result = new TransformationResult(currentPayload, context.Metadata with { ProcessedUtc = DateTimeOffset.UtcNow });

            foreach (ITransformationObserver observer in _observers) observer.OnAfterTransform(result);
            _logger.LogDebug("Completed transformation for CorrelationId={CorrelationId}", context.Metadata.CorrelationId);

            return result;
        }
    }

    #endregion

    #region --- Strategy Pattern -------------------------------------------------------------------------------------

    internal interface ITransformationStrategy
    {
        string Name { get; }

        Task<TransformationPayload> ApplyAsync(
            TransformationPayload payload,
            CancellationToken      token = default);
    }

    /// <summary>
    ///    Example strategy that performs simple aggregation (e.g., totals numeric fields).
    /// </summary>
    internal sealed class AggregationStrategy : ITransformationStrategy
    {
        public string Name => "Aggregation";

        public Task<TransformationPayload> ApplyAsync(TransformationPayload payload, CancellationToken token = default)
        {
            // Example: count number of properties
            int propertyCount = payload.Content.Count;
            payload.Content["propertyCount"] = propertyCount;

            return Task.FromResult(payload);
        }
    }

    /// <summary>
    ///    Example strategy that enriches the payload with derived data.
    /// </summary>
    internal sealed class EnrichmentStrategy : ITransformationStrategy
    {
        public string Name => "Enrichment";

        public Task<TransformationPayload> ApplyAsync(TransformationPayload payload, CancellationToken token = default)
        {
            payload.Content["enrichedUtc"] = DateTimeOffset.UtcNow;
            return Task.FromResult(payload);
        }
    }

    /// <summary>
    ///    Example strategy that anonymizes PII-like fields.
    /// </summary>
    internal sealed class AnonymizationStrategy : ITransformationStrategy
    {
        public string Name => "Anonymization";

        public Task<TransformationPayload> ApplyAsync(TransformationPayload payload, CancellationToken token = default)
        {
            if (payload.Content.TryGetValue("email", out var emailRaw) && emailRaw is string email)
            {
                string hash = Convert.ToBase64String(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(email)));
                payload.Content["email_hash"] = hash;
                payload.Content.Remove("email");
            }

            return Task.FromResult(payload);
        }
    }

    #endregion

    #region --- Observer Pattern -------------------------------------------------------------------------------------

    internal interface ITransformationObserver
    {
        void OnBeforeTransform(TransformationContext context);
        void OnAfterTransform(TransformationResult   result);
    }

    /// <summary>
    ///    Observer that simply logs transformation events.
    /// </summary>
    internal sealed class LoggingObserver : ITransformationObserver
    {
        private readonly ILogger<LoggingObserver> _logger;

        public LoggingObserver(ILogger<LoggingObserver> logger) => _logger = logger;

        public void OnBeforeTransform(TransformationContext context) =>
            _logger.LogInformation("➡️  Starting transform for CorrelationId={CorrelationId}", context.Metadata.CorrelationId);

        public void OnAfterTransform(TransformationResult result) =>
            _logger.LogInformation("✅ Finished transform for CorrelationId={CorrelationId}", result.Metadata.CorrelationId);
    }

    /// <summary>
    ///    Observer that publishes simple in-memory metrics (count, latency).
    /// </summary>
    internal sealed class MetricsObserver : ITransformationObserver
    {
        private static readonly ConcurrentDictionary<string, long> _counters = new();

        public void OnBeforeTransform(TransformationContext context) { /* no-op */ }

        public void OnAfterTransform(TransformationResult result)
        {
            _counters.AddOrUpdate("transform.count", 1, (_, v) => v + 1);
            // Real implementation would push to Prometheus / OpenTelemetry.
        }
    }

    #endregion

    #region --- DTOs & Models ----------------------------------------------------------------------------------------

    public sealed record TransformationMetadata(
        Guid   CorrelationId,
        string SourceTopic,
        long   Offset,
        DateTimeOffset IngestedUtc,
        DateTimeOffset? ProcessedUtc = null);

    public sealed record TransformationPayload(IDictionary<string, object> Content)
    {
        public override string ToString() => JsonSerializer.Serialize(Content);
    }

    public sealed record TransformationContext(
        TransformationPayload  Payload,
        TransformationMetadata Metadata);

    public sealed record TransformationResult(
        TransformationPayload  Payload,
        TransformationMetadata Metadata);

    #endregion

    #region --- Stream Abstractions ----------------------------------------------------------------------------------

    /// <summary>
    ///    Represents a simple Kafka-like message abstraction used by the service.
    /// </summary>
    public sealed record StreamMessage(
        TransformationPayload  Payload,
        TransformationMetadata Metadata);

    /// <summary>
    ///    Minimal abstraction over a streaming platform (Kafka, Pulsar, etc.).
    /// </summary>
    internal interface IStreamClient
    {
        IAsyncEnumerable<StreamMessage> ConsumeAsync(CancellationToken token = default);
        Task ProduceAsync(TransformationPayload payload, TransformationMetadata metadata, CancellationToken token = default);
    }

    /// <summary>
    ///    An in-memory implementation used for local development and unit testing.
    /// </summary>
    internal sealed class InMemoryStreamClient : IStreamClient
    {
        private readonly Channel<StreamMessage> _channel = Channel.CreateUnbounded<StreamMessage>();
        private readonly ILogger<InMemoryStreamClient> _logger;

        public InMemoryStreamClient(ILogger<InMemoryStreamClient> logger)
        {
            _logger = logger;
            // Seed the channel with some mock data so that developers see immediate action.
            _ = SeedAsync();
        }

        public async IAsyncEnumerable<StreamMessage> ConsumeAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken token = default)
        {
            while (await _channel.Reader.WaitToReadAsync(token))
            {
                while (_channel.Reader.TryRead(out StreamMessage? msg))
                {
                    yield return msg;
                }
            }
        }

        public async Task ProduceAsync(TransformationPayload payload, TransformationMetadata metadata, CancellationToken token = default)
        {
            var output = new StreamMessage(payload, metadata);
            await _channel.Writer.WriteAsync(output, token);
            _logger.LogDebug("📤 Published transformed message {CorrelationId}", metadata.CorrelationId);
        }

        private async Task SeedAsync()
        {
            for (int i = 0; i < 5; i++)
            {
                var payload = new TransformationPayload(new Dictionary<string, object>
                {
                    ["email"] = $"user{i}@example.com",
                    ["value"] = i
                });

                var metadata = new TransformationMetadata(
                    CorrelationId: Guid.NewGuid(),
                    SourceTopic: "seed",
                    Offset: i,
                    IngestedUtc: DateTimeOffset.UtcNow);

                await _channel.Writer.WriteAsync(new StreamMessage(payload, metadata));
            }
        }
    }

    #endregion
}
```