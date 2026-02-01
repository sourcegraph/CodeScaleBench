```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Ingestion/Program.cs

using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Ingestion
{
    /// <summary>
    /// Entry-point for the PaletteStream.Ingestion micro-service.
    /// Consumes raw "pigment" events from Kafka, applies a transformation
    /// pipeline, and writes the resulting artifacts to the raw data-lake zone.
    /// </summary>
    internal sealed class Program
    {
        public static async Task Main(string[] args)
        {
            var host = CreateHostBuilder(args).Build();

            // Run EF/Core or Liquibase migrations here if needed:
            await RunMigrationsAsync(host.Services);

            await host.RunAsync();
        }

        /// <summary>
        /// Builds the .NET Generic Host configuring DI, Logging and Options binding.
        /// </summary>
        private static IHostBuilder CreateHostBuilder(string[] args) =>
            Host.CreateDefaultBuilder(args)
                .ConfigureHostConfiguration(cfg =>
                {
                    cfg.AddEnvironmentVariables("PALETTESTREAM_")
                       .AddCommandLine(args);
                })
                .ConfigureAppConfiguration((context, cfg) =>
                {
                    var env = context.HostingEnvironment;
                    cfg.SetBasePath(Directory.GetCurrentDirectory())
                       .AddJsonFile("appsettings.json", optional: false, reloadOnChange: true)
                       .AddJsonFile($"appsettings.{env.EnvironmentName}.json", optional: true)
                       .AddEnvironmentVariables("PALETTESTREAM_");

                    if (args is { Length: > 0 })
                        cfg.AddCommandLine(args);
                })
                .ConfigureLogging((ctx, lb) =>
                {
                    lb.ClearProviders();
                    lb.AddConsole();
                    lb.AddDebug();
                    lb.AddConfiguration(ctx.Configuration.GetSection("Logging"));
                })
                .ConfigureServices((context, services) =>
                {
                    services.Configure<KafkaOptions>(context.Configuration.GetSection("Kafka"));
                    services.Configure<DataLakeOptions>(context.Configuration.GetSection("DataLake"));

                    services.AddSingleton<IKafkaConsumerFactory, KafkaConsumerFactory>();
                    services.AddSingleton<IDataLakeClient, DataLakeClient>();
                    services.AddSingleton<ITransformationPipeline, TransformationPipeline>();

                    services.AddHostedService<IngestionWorker>();
                    services.AddHealthChecks(); // liveness / readiness probes
                });

        /// <summary>
        /// Executes blocking migrations (e.g. DB schema) before the host starts serving traffic.
        /// </summary>
        private static async Task RunMigrationsAsync(IServiceProvider sp)
        {
            // Example: ensure that the data-lake containers / databases exist.
            var logger = sp.GetRequiredService<ILoggerFactory>()
                           .CreateLogger("Startup.Migrations");

            try
            {
                var lake = sp.GetRequiredService<IDataLakeClient>();
                await lake.EnsureContainersAsync(CancellationToken.None);
            }
            catch (Exception ex)
            {
                logger.LogCritical(ex, "Failed to perform startup migrations.");
                throw; // Crash the application; Kubernetes will restart the pod.
            }
        }
    }

    #region Hosted Service

    /// <summary>
    /// Worker responsible for streaming ingestion from Kafka into the pipeline.
    /// Lifecycle is managed by the .NET Generic Host.
    /// </summary>
    internal sealed class IngestionWorker : BackgroundService
    {
        private readonly ILogger<IngestionWorker> _logger;
        private readonly IKafkaConsumerFactory _factory;
        private readonly ITransformationPipeline _pipeline;
        private readonly IDataLakeClient _dataLake;
        private IConsumer<string, string>? _consumer;

        public IngestionWorker(
            ILogger<IngestionWorker> logger,
            IKafkaConsumerFactory factory,
            ITransformationPipeline pipeline,
            IDataLakeClient dataLake)
        {
            _logger    = logger;
            _factory   = factory;
            _pipeline  = pipeline;
            _dataLake  = dataLake;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _consumer = _factory.CreateConsumer();

            _consumer.Subscribe(_factory.Options.Topic);

            _logger.LogInformation("Kafka consumer subscribed to topic {Topic}", _factory.Options.Topic);

            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    var cr = _consumer.Consume(stoppingToken);
                    if (cr == null) continue;

                    _logger.LogDebug("Received message with key {Key} at {Offset}", cr.Message.Key, cr.TopicPartitionOffset);

                    // 1. Deserialize
                    var rawPigment = JsonSerializer.Deserialize<DataPigment>(cr.Message.Value);

                    // 2. Transform (could be CPU/GPU heavy, run asynchronously)
                    var refined = await _pipeline.ExecuteAsync(rawPigment!, stoppingToken);

                    // 3. Persist to Data Lake
                    await _dataLake.StoreAsync(refined, stoppingToken);

                    // 4. Commit offset
                    _consumer.Commit(cr);
                }
                catch (ConsumeException cex)
                {
                    // Handle deserialization errors, poison pill messages, etc.
                    _logger.LogError(cex, "Kafka consumption error, message will be skipped.");
                }
                catch (OperationCanceledException) { /* graceful shutdown */ }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unexpected error in ingestion loop; backing off for 5s.");
                    await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
                }
            }
        }

        public override void Dispose()
        {
            base.Dispose();
            _consumer?.Close();
            _consumer?.Dispose();
        }
    }

    #endregion

    #region Options

    /// <summary>
    /// Strongly-typed settings for Kafka connectivity.
    /// </summary>
    internal sealed record KafkaOptions
    {
        public string BootstrapServers { get; init; } = string.Empty;
        public string Topic            { get; init; } = string.Empty;
        public string GroupId          { get; init; } = "palette-stream-ingestion";
        public bool   EnableAutoCommit { get; init; } = false;
    }

    /// <summary>
    /// Strongly-typed settings for the Data Lake.
    /// </summary>
    internal sealed record DataLakeOptions
    {
        public string RawContainerName { get; init; } = "raw-zone";
        public string ConnectionString { get; init; } = string.Empty;
    }

    #endregion

    #region Contracts / Domain Models

    /// <summary>
    /// Raw pigment as stored in the source stream.
    /// </summary>
    internal sealed record DataPigment(
        Guid   Id,
        string Payload,
        DateTimeOffset CreatedAtUtc);

    /// <summary>
    /// Refined pigment after passing through the transformation pipeline.
    /// </summary>
    internal sealed record RefinedPigment(
        Guid Id,
        string NormalizedPayload,
        DateTimeOffset CreatedAtUtc,
        string[] TransformationTrace);

    #endregion

    #region Infrastructure: Kafka

    internal interface IKafkaConsumerFactory
    {
        IConsumer<string, string> CreateConsumer();
        KafkaOptions Options { get; }
    }

    /// <summary>
    /// Creates configured Kafka consumers with sane defaults and TLS / Sasl support.
    /// </summary>
    internal sealed class KafkaConsumerFactory : IKafkaConsumerFactory
    {
        private readonly KafkaOptions _options;
        private readonly ILogger<KafkaConsumerFactory> _logger;

        public KafkaConsumerFactory(
            IOptions<KafkaOptions> options,
            ILogger<KafkaConsumerFactory> logger)
        {
            _options = options.Value;
            _logger  = logger;
        }

        public KafkaOptions Options => _options;

        public IConsumer<string, string> CreateConsumer()
        {
            var config = new ConsumerConfig
            {
                BootstrapServers = _options.BootstrapServers,
                GroupId          = _options.GroupId,
                EnableAutoCommit = _options.EnableAutoCommit,
                AutoOffsetReset  = AutoOffsetReset.Latest,
                // Additional production settings: SSL, Sasl, retries, etc.
            };

            _logger.LogInformation("Creating Kafka consumer for servers {Servers}", _options.BootstrapServers);

            return new ConsumerBuilder<string, string>(config)
                    .SetErrorHandler((_, e) =>
                        _logger.LogWarning("Kafka error {Reason}", e.Reason))
                    .Build();
        }
    }

    #endregion

    #region Transformation Pipeline

    internal interface ITransformationPipeline
    {
        Task<RefinedPigment> ExecuteAsync(DataPigment pigment, CancellationToken ct);
    }

    /// <summary>
    /// Example implementation using the Strategy + Pipeline pattern.
    /// Real-world scenarios would load strategies via DI / reflection.
    /// </summary>
    internal sealed class TransformationPipeline : ITransformationPipeline
    {
        private readonly ILogger<TransformationPipeline> _logger;

        public TransformationPipeline(ILogger<TransformationPipeline> logger)
            => _logger = logger;

        public Task<RefinedPigment> ExecuteAsync(DataPigment pigment, CancellationToken ct)
        {
            // 1. Data quality checks
            if (string.IsNullOrWhiteSpace(pigment.Payload))
                throw new InvalidDataException("Payload must not be empty.");

            // 2. Normalization (toy example)
            var normalized = pigment.Payload.Trim().ToUpperInvariant();

            // 3. Build transformation trace for observability
            var trace = new[]
            {
                "TrimWhitespace",
                "ToUpperCase"
            };

            var refined = new RefinedPigment(
                Id: pigment.Id,
                NormalizedPayload: normalized,
                CreatedAtUtc: pigment.CreatedAtUtc,
                TransformationTrace: trace);

            _logger.LogDebug("Pigment {Id} transformed.", pigment.Id);

            return Task.FromResult(refined);
        }
    }

    #endregion

    #region Infrastructure: Data Lake

    internal interface IDataLakeClient
    {
        Task StoreAsync(RefinedPigment pigment, CancellationToken ct);
        Task EnsureContainersAsync(CancellationToken ct);
    }

    /// <summary>
    /// Simplified Azure Data Lake client stub.
    /// Replace with ADLS Gen-2 / S3 / GCS implementation as necessary.
    /// </summary>
    internal sealed class DataLakeClient : IDataLakeClient
    {
        private readonly DataLakeOptions _options;
        private readonly ILogger<DataLakeClient> _logger;
        private readonly JsonSerializerOptions _serializerOptions;

        public DataLakeClient(
            IOptions<DataLakeOptions> options,
            ILogger<DataLakeClient> logger)
        {
            _options  = options.Value;
            _logger   = logger;
            _serializerOptions = new JsonSerializerOptions
            {
                WriteIndented          = false,
                DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
            };
        }

        public Task EnsureContainersAsync(CancellationToken ct)
        {
            // NO-OP stub. In production, check if the container exists and create it.
            _logger.LogInformation("Ensuring data-lake container {Container} exists.", _options.RawContainerName);
            return Task.CompletedTask;
        }

        public async Task StoreAsync(RefinedPigment pigment, CancellationToken ct)
        {
            // This is a stub that writes to the local file system.
            // Swap with a cloud BlobContainerClient for real deployments.
            var folder = Path.Combine(AppContext.BaseDirectory, _options.RawContainerName);
            Directory.CreateDirectory(folder);

            var path = Path.Combine(folder, $"{pigment.Id:N}.json");
            await File.WriteAllTextAsync(path,
                JsonSerializer.Serialize(pigment, _serializerOptions),
                ct);

            _logger.LogDebug("Refined pigment {Id} stored to {Path}", pigment.Id, path);
        }
    }

    #endregion
}
```
