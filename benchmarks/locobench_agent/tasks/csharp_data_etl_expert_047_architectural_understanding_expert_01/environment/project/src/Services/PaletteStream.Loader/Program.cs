```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Loader/Program.cs
// Project: PaletteStream ETL Canvas (data_etl)
//
// NOTE: This is the entry-point for the “Loader” micro-service.  It is responsible for
//  • Subscribing to stream topics (Kafka) for near-real-time loads
//  • Scheduling/Executing batch micro-loads via Hangfire
//  • Publishing operational events to the monitoring stack
//
// The service is intentionally self-contained so it can be built/run in isolation
// during CI or local development.  External dependencies are registered through DI
// and may be mocked/replaced by the test harness.

using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using Hangfire;
using Hangfire.MemoryStorage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Loader
{
    public static class Program
    {
        public static async Task<int> Main(string[] args)
        {
            IHostBuilder builder = CreateHostBuilder(args);

            try
            {
                using IHost host = builder.Build();
                host.Services.GetRequiredService<ILoggerFactory>() // touch logger to preload config
                              .CreateLogger("Bootstrap")
                              .LogInformation("PaletteStream.Loader bootstrapped in {Environment} mode.",
                                              host.Services.GetRequiredService<IHostEnvironment>().EnvironmentName);

                await host.RunAsync();
                return 0;
            }
            catch (OperationCanceledException)
            {
                return 143; // Standard Unix SIGTERM code
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[FATAL] {ex}");
                return 1;
            }
        }

        private static IHostBuilder CreateHostBuilder(string[] args) =>
            Host.CreateDefaultBuilder(args)
                .ConfigureAppConfiguration((ctx, config) =>
                {
                    config.AddEnvironmentVariables(prefix: "PS_");

                    if (ctx.HostingEnvironment.IsDevelopment())
                    {
                        // Support user-secrets during local development.
                        config.AddUserSecrets(typeof(Program).Assembly, optional: true);
                    }
                })
                .ConfigureLogging((ctx, logging) =>
                {
                    logging.ClearProviders();
                    logging.AddConsole(o =>
                    {
                        o.IncludeScopes = true;
                        o.TimestampFormat = "yyyy-MM-dd HH:mm:ss ";
                    });

                    if (ctx.HostingEnvironment.IsDevelopment())
                        logging.SetMinimumLevel(LogLevel.Debug);
                    else
                        logging.SetMinimumLevel(LogLevel.Information);
                })
                .ConfigureServices((ctx, services) =>
                {
                    IConfiguration cfg = ctx.Configuration;

                    services.Configure<KafkaOptions>(cfg.GetSection("Kafka"));
                    services.Configure<BatchOptions>(cfg.GetSection("Batch"));

                    services.AddSingleton<IKafkaConsumerFactory, KafkaConsumerFactory>();
                    services.AddSingleton<IDataLakeWriter, LocalFileDataLakeWriter>();
                    services.AddSingleton<IQualityChecker, BasicQualityChecker>();
                    services.AddSingleton<IDomainEventPublisher, ConsoleDomainEventPublisher>();

                    // Stream loader (Kafka consumer) runs as background service
                    services.AddHostedService<StreamLoaderService>();

                    // Hangfire (micro-batch jobs)
                    services.AddHangfire(c => c.UseMemoryStorage());
                    services.AddHangfireServer();
                    services.AddTransient<BatchLoaderJob>();
                    services.AddHostedService<HangfireBootstrapper>(); // schedules recurring jobs
                });
    }

    #region Options

    /// <summary>Strongly-typed configuration for Kafka connectivity.</summary>
    internal sealed class KafkaOptions
    {
        public string BootstrapServers { get; set; } = "localhost:9092";
        public string Topic            { get; set; } = "palette.pigments.raw";
        public string GroupId          { get; set; } = "palette.loader";
        public AutoOffsetReset OffsetReset { get; set; } = AutoOffsetReset.Earliest;
        public int    CommitPeriodMs   { get; set; } = 5_000;
    }

    /// <summary>Configuration for batch/ Hangfire jobs.</summary>
    internal sealed class BatchOptions
    {
        public string Cron            { get; set; } = "0 */30 * * * *"; // every 30 minutes
        public string ImportDirectory { get; set; } = "./import";
    }

    #endregion

    #region Factories / Infrastructure

    internal interface IKafkaConsumerFactory
    {
        IConsumer<Ignore, string> Create(CancellationToken cancellationToken);
    }

    internal sealed class KafkaConsumerFactory : IKafkaConsumerFactory
    {
        private readonly KafkaOptions _options;
        private readonly ILogger<KafkaConsumerFactory> _logger;

        public KafkaConsumerFactory(
            Microsoft.Extensions.Options.IOptions<KafkaOptions> opt,
            ILogger<KafkaConsumerFactory> logger)
        {
            _options = opt.Value;
            _logger  = logger;
        }

        public IConsumer<Ignore, string> Create(CancellationToken cancellationToken)
        {
            var cfg = new ConsumerConfig
            {
                BootstrapServers = _options.BootstrapServers,
                GroupId          = _options.GroupId,
                AutoOffsetReset  = _options.OffsetReset,
                EnableAutoCommit = false,
                EnablePartitionEof = true
            };

            _logger.LogInformation("Creating Kafka consumer for topic '{Topic}' on {BootstrapServers}",
                                   _options.Topic, _options.BootstrapServers);

            return new ConsumerBuilder<Ignore, string>(cfg)
                   .SetErrorHandler((_, e) => _logger.LogError("Kafka error: {Reason}", e.Reason))
                   .SetLogHandler((_, m) => _logger.LogDebug("Kafka: {Message}", m.Message))
                   .Build();
        }
    }

    internal interface IDataLakeWriter
    {
        Task WriteAsync(string payload, CancellationToken ct);
    }

    /// <summary>
    /// Very naive implementation that simply appends the payload to a local file.
    /// In production this would write to Azure/AWS data lake or S3.
    /// </summary>
    internal sealed class LocalFileDataLakeWriter : IDataLakeWriter
    {
        private static readonly string _targetDir = Path.Combine(AppContext.BaseDirectory, "lake", "raw");

        public async Task WriteAsync(string payload, CancellationToken ct)
        {
            Directory.CreateDirectory(_targetDir);
            string filePath = Path.Combine(_targetDir, $"{DateTime.UtcNow:yyyyMMdd_HHmmss_fff}.json");
            await File.WriteAllTextAsync(filePath, payload, ct);
        }
    }

    internal interface IQualityChecker
    {
        bool IsValid(string jsonPayload, out IEnumerable<string> errors);
    }

    internal sealed class BasicQualityChecker : IQualityChecker
    {
        public bool IsValid(string jsonPayload, out IEnumerable<string> errors)
        {
            var e = new List<string>();

            if (string.IsNullOrWhiteSpace(jsonPayload))
                e.Add("Payload is empty.");

            errors = e;
            return e.Count == 0;
        }
    }

    internal interface IDomainEventPublisher
    {
        Task PublishAsync(string eventName, object data, CancellationToken ct);
    }

    internal sealed class ConsoleDomainEventPublisher : IDomainEventPublisher
    {
        public Task PublishAsync(string eventName, object data, CancellationToken ct)
        {
            Console.WriteLine($"[EVENT] {eventName}: {System.Text.Json.JsonSerializer.Serialize(data)}");
            return Task.CompletedTask;
        }
    }

    #endregion

    #region Hosted Services

    /// <summary>
    /// Consumes pigment stream (Kafka) and loads messages to the Data Lake.
    /// </summary>
    internal sealed class StreamLoaderService : BackgroundService
    {
        private readonly IKafkaConsumerFactory _factory;
        private readonly IDataLakeWriter       _writer;
        private readonly IQualityChecker       _quality;
        private readonly IDomainEventPublisher _events;
        private readonly KafkaOptions          _options;
        private readonly ILogger<StreamLoaderService> _logger;

        public StreamLoaderService(
            IKafkaConsumerFactory factory,
            IDataLakeWriter writer,
            IQualityChecker quality,
            IDomainEventPublisher events,
            Microsoft.Extensions.Options.IOptions<KafkaOptions> opt,
            ILogger<StreamLoaderService> logger)
        {
            _factory  = factory;
            _writer   = writer;
            _quality  = quality;
            _events   = events;
            _options  = opt.Value;
            _logger   = logger;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            using var consumer = _factory.Create(stoppingToken);
            consumer.Subscribe(_options.Topic);

            _logger.LogInformation("Started StreamLoaderService. Subscribed to {Topic}.", _options.Topic);

            try
            {
                while (!stoppingToken.IsCancellationRequested)
                {
                    try
                    {
                        var cr = consumer.Consume(stoppingToken);

                        if (cr.IsPartitionEOF)
                            continue;

                        string payload = cr.Message.Value;
                        _logger.LogDebug("Received message at {TopicPartitionOffset}", cr.TopicPartitionOffset);

                        if (!_quality.IsValid(payload, out var errs))
                        {
                            _logger.LogWarning("Discarding invalid message: {Errors}", string.Join(", ", errs));
                            await _events.PublishAsync("loader.validationFailed",
                                new { cr.TopicPartitionOffset, Errors = errs }, stoppingToken);
                            consumer.Commit(cr);
                            continue;
                        }

                        await _writer.WriteAsync(payload, stoppingToken);

                        consumer.Commit(cr);
                        await _events.PublishAsync("loader.messageProcessed",
                            new { cr.TopicPartitionOffset }, stoppingToken);
                    }
                    catch (ConsumeException cex)
                    {
                        _logger.LogError(cex, "Kafka consume exception – pausing for 5 s.");
                        await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
                    }
                }
            }
            catch (OperationCanceledException) { /* expected on shutdown */ }
            finally
            {
                consumer.Close();
                _logger.LogInformation("StreamLoaderService stopped.");
            }
        }
    }

    /// <summary>
    /// Schedules recurring batch import jobs via Hangfire.
    /// </summary>
    internal sealed class HangfireBootstrapper : BackgroundService
    {
        private readonly IRecurringJobManager _manager;
        private readonly IServiceProvider _provider;
        private readonly BatchOptions _options;
        private readonly ILogger<HangfireBootstrapper> _logger;

        public HangfireBootstrapper(IRecurringJobManager manager,
                                    IServiceProvider provider,
                                    Microsoft.Extensions.Options.IOptions<BatchOptions> opt,
                                    ILogger<HangfireBootstrapper> logger)
        {
            _manager = manager;
            _provider = provider;
            _options = opt.Value;
            _logger = logger;
        }

        protected override Task ExecuteAsync(CancellationToken stoppingToken)
        {
            // Schedule as recurring
            _logger.LogInformation("Scheduling batch loader job with CRON '{Cron}'.", _options.Cron);

            _manager.AddOrUpdate(
                recurringJobId: "batch-loader",
                methodCall: () => BatchLoaderJob.ExecuteAsync(default),
                cronExpression: _options.Cron,
                timeZone: TimeZoneInfo.Utc);

            return Task.CompletedTask;
        }
    }

    #endregion

    #region Hangfire Job

    /// <summary>
    /// A micro-batch job that loads files from the import folder
    /// into the Data Lake, simulating a batch ETL step.
    /// </summary>
    public sealed class BatchLoaderJob
    {
        private readonly BatchOptions        _options;
        private readonly IDataLakeWriter     _writer;
        private readonly IQualityChecker     _quality;
        private readonly IDomainEventPublisher _events;
        private readonly ILogger<BatchLoaderJob> _logger;

        public BatchLoaderJob(
            Microsoft.Extensions.Options.IOptions<BatchOptions> opt,
            IDataLakeWriter writer,
            IQualityChecker quality,
            IDomainEventPublisher events,
            ILogger<BatchLoaderJob> logger)
        {
            _options = opt.Value;
            _writer  = writer;
            _quality = quality;
            _events  = events;
            _logger  = logger;
        }

        /// <summary>
        /// Hangfire entry-point (no DI on static). Uses Service Locator pattern via JobActivator.
        /// </summary>
        public static async Task ExecuteAsync(CancellationToken ct)
        {
            // Hangfire will resolve instance through DI container to run the non-static ExecuteInternalAsync.
            var job = GlobalConfiguration.Configuration
                                          .JobActivator
                                          .ActivateJob(typeof(BatchLoaderJob)) as BatchLoaderJob
                      ?? throw new InvalidOperationException("Unable to activate BatchLoaderJob.");
            await job.ExecuteInternalAsync(ct);
        }

        // Actual implementation
        private async Task ExecuteInternalAsync(CancellationToken ct)
        {
            _logger.LogInformation("BatchLoaderJob started. Scanning {ImportFolder}.", _options.ImportDirectory);

            if (!Directory.Exists(_options.ImportDirectory))
            {
                _logger.LogWarning("Import folder {ImportDirectory} does not exist.", _options.ImportDirectory);
                return;
            }

            foreach (string file in Directory.GetFiles(_options.ImportDirectory, "*.json"))
            {
                if (ct.IsCancellationRequested) break;

                string payload = await File.ReadAllTextAsync(file, ct);

                if (!_quality.IsValid(payload, out var errs))
                {
                    _logger.LogWarning("File {FileName} failed validation: {Errors}", file, string.Join(", ", errs));
                    await _events.PublishAsync("loader.batch.validationFailed",
                        new { File = file, Errors = errs }, ct);
                    continue;
                }

                await _writer.WriteAsync(payload, ct);
                await _events.PublishAsync("loader.batch.fileProcessed",
                    new { File = file }, ct);

                File.Move(file,
                          Path.Combine(Path.GetDirectoryName(file)!, "processed", Path.GetFileName(file)),
                          overwrite: true);
            }

            _logger.LogInformation("BatchLoaderJob completed.");
        }
    }

    #endregion
}
```