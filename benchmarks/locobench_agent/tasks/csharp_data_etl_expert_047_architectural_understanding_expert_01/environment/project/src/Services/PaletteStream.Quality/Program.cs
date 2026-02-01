```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Quality/Program.cs

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Serilog;
using Serilog.Events;
using Serilog.Formatting.Compact;

namespace PaletteStream.Quality;

/// <summary>
/// Entry-point for the PaletteStream Quality micro-service.  This host boots a
/// generic worker that continuously validates data inside the Data Lake zones
/// (raw, refined, curated) and publishes the results to the central
/// monitoring/alerting pipeline.
/// </summary>
internal sealed class Program
{
    /// <summary>
    /// Application entry-point.
    /// </summary>
    /// <param name="args">Command-line arguments.</param>
    /// <returns>Exit code.</returns>
    public static async Task<int> Main(string[] args)
    {
        using var host = CreateHost(args);

        try
        {
            await host.StartAsync();

            // Keep running until cancellation is requested (e.g. SIGTERM)
            await host.WaitForShutdownAsync();
            return 0;
        }
        catch (Exception ex)
        {
            Log.Fatal(ex, "Unhandled exception in Quality service");
            return 1;
        }
        finally
        {
            Log.CloseAndFlush();
        }
    }

    /// <summary>
    /// Builds the <see cref="IHost"/> for the current service.
    /// </summary>
    /// <param name="args">Command-line arguments.</param>
    private static IHost CreateHost(string[] args) =>
        Host.CreateDefaultBuilder(args)
            .ConfigureAppConfiguration(cfg =>
            {
                cfg.AddJsonFile("appsettings.json", optional: true, reloadOnChange: true)
                   .AddEnvironmentVariables()
                   .AddCommandLine(args);
            })
            .UseSerilog((ctx, services, conf) =>
            {
                conf.ReadFrom.Configuration(ctx.Configuration)
                    .ReadFrom.Services(services)
                    .Enrich.FromLogContext()
                    .Enrich.WithProperty("Service", "PaletteStream.Quality")
                    .WriteTo.Console(new RenderedCompactJsonFormatter(), restrictedToMinimumLevel: LogEventLevel.Information);
            })
            .ConfigureServices((ctx, services) =>
            {
                // Configuration objects
                services.Configure<QualityCheckOptions>(ctx.Configuration.GetSection("QualityChecks"));

                // Core dependencies
                services.AddSingleton<IDataLakeClient, DataLakeClientMock>();      // Replace with real client (e.g., ADLS, S3, GCS)
                services.AddSingleton<IQualityPublisher, LogQualityPublisher>();   // Publishes check results to the event bus

                // Hosted worker
                services.AddHostedService<DataQualityWorker>();

                // Health checks
                services.AddHealthChecks()
                        .AddCheck<QualityServiceHealthCheck>("quality_service");

            })
            .Build();
}

/// <summary>
/// Holds configurable parameters that drive the quality check engine.
/// </summary>
internal sealed record QualityCheckOptions
{
    /// <summary>
    /// Milliseconds to wait between quality passes.
    /// Defaults to 30 seconds when not supplied.
    /// </summary>
    public int PollIntervalMs { get; init; } = 30_000;

    /// <summary>
    /// Set of lake zones to inspect.  If empty, all zones are inspected.
    /// </summary>
    public string[] Zones { get; init; } = Array.Empty<string>();
}

/// <summary>
/// Background worker that continuously evaluates data quality across Data Lake zones.
/// </summary>
internal sealed class DataQualityWorker : BackgroundService
{
    private readonly ILogger<DataQualityWorker> _log;
    private readonly IDataLakeClient _lakeClient;
    private readonly IQualityPublisher _publisher;
    private readonly QualityCheckOptions _opts;

    public DataQualityWorker(
        ILogger<DataQualityWorker> log,
        IDataLakeClient lakeClient,
        IQualityPublisher publisher,
        Microsoft.Extensions.Options.IOptions<QualityCheckOptions> opts)
    {
        _log = log;
        _lakeClient = lakeClient;
        _publisher = publisher;
        _opts = opts.Value;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _log.LogInformation("Quality worker starting with poll interval: {PollInterval} ms", _opts.PollIntervalMs);

        while (!stoppingToken.IsCancellationRequested)
        {
            var sw = Stopwatch.StartNew();
            try
            {
                await CheckZonesAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _log.LogError(ex, "Quality pass failed");
            }
            finally
            {
                sw.Stop();
                _log.LogDebug("Quality pass completed in {ElapsedMs} ms", sw.ElapsedMilliseconds);
            }

            // Wait for next tick unless cancelled
            try
            {
                await Task.Delay(_opts.PollIntervalMs, stoppingToken);
            }
            catch (TaskCanceledException)
            {
                // gracefully exit
            }
        }

        _log.LogInformation("Quality worker stopping.");
    }

    private async Task CheckZonesAsync(CancellationToken ct)
    {
        var zones = _opts.Zones.Length == 0
            ? await _lakeClient.ListZonesAsync(ct)
            : _opts.Zones;

        foreach (var zone in zones)
        {
            if (ct.IsCancellationRequested) break;

            _log.LogInformation("Running quality checks on {Zone}", zone);

            var datasets = await _lakeClient.ListDatasetsAsync(zone, ct);
            if (!datasets.Any())
            {
                _log.LogWarning("No datasets discovered in zone {Zone}", zone);
                continue;
            }

            var tasks = datasets.Select(ds => EvaluateDatasetAsync(zone, ds, ct));
            await Task.WhenAll(tasks);
        }
    }

    private async Task EvaluateDatasetAsync(string zone, string dataset, CancellationToken ct)
    {
        try
        {
            var stats = await _lakeClient.GetStatisticsAsync(zone, dataset, ct);

            var issues = new List<QualityIssue>();

            // Statistical validation (placeholder logic)
            if (stats.NullPercentage > 0.05)
            {
                issues.Add(new QualityIssue(QualitySeverity.Warning,
                    $"High null ratio: {stats.NullPercentage:P1}"));
            }

            if (stats.DuplicateCount > 0)
            {
                issues.Add(new QualityIssue(QualitySeverity.Critical,
                    $"Dataset contains {stats.DuplicateCount} duplicate records"));
            }

            // Publish result
            var result = new QualityCheckResult(
                Zone: zone,
                Dataset: dataset,
                TimestampUtc: DateTime.UtcNow,
                IsSuccess: issues.Count == 0,
                Issues: issues);

            await _publisher.PublishAsync(result, ct);

            if (issues.Count == 0)
            {
                _log.LogInformation("[{Zone}/{Dataset}] Quality OK", zone, dataset);
            }
            else
            {
                foreach (var issue in issues)
                {
                    _log.Log(issue.Severity == QualitySeverity.Critical ? LogLevel.Error : LogLevel.Warning,
                        "[{Zone}/{Dataset}] {Severity} – {Description}",
                        zone, dataset, issue.Severity, issue.Description);
                }
            }
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "Failed to evaluate dataset {Zone}/{Dataset}", zone, dataset);
        }
    }
}

/// <summary>
/// Lightweight abstraction over the Data Lake.
/// </summary>
internal interface IDataLakeClient
{
    Task<string[]> ListZonesAsync(CancellationToken ct);
    Task<string[]> ListDatasetsAsync(string zone, CancellationToken ct);
    Task<DataStatistics> GetStatisticsAsync(string zone, string dataset, CancellationToken ct);
}

/// <summary>
/// Stub/mock implementation for demo & unit tests.
/// Replace with concrete implementation (ADLS, S3, GCS, etc.).
/// </summary>
internal sealed class DataLakeClientMock : IDataLakeClient
{
    private static readonly string[] s_zones = { "raw", "refined", "curated" };
    private static readonly Random s_rng = new();

    public Task<string[]> ListZonesAsync(CancellationToken ct) =>
        Task.FromResult(s_zones);

    public Task<string[]> ListDatasetsAsync(string zone, CancellationToken ct)
    {
        // Simulate 5 datasets per zone
        var datasets = Enumerable.Range(1, 5)
                                 .Select(i => $"{zone}_dataset_{i}")
                                 .ToArray();
        return Task.FromResult(datasets);
    }

    public Task<DataStatistics> GetStatisticsAsync(string zone, string dataset, CancellationToken ct)
    {
        // Simulated stats
        var stats = new DataStatistics(
            RecordCount: s_rng.Next(1000, 50_000),
            NullPercentage: s_rng.NextDouble() * 0.1,
            DuplicateCount: s_rng.Next(0, 20));
        return Task.FromResult(stats);
    }
}

/// <summary>
/// Contract for communicating quality results to downstream systems
/// (monitoring dashboards, alerting pipelines, etc.).
/// </summary>
internal interface IQualityPublisher
{
    Task PublishAsync(QualityCheckResult result, CancellationToken ct);
}

/// <summary>
/// Default publisher that logs results.  Real implementation would push to Kafka,
/// SignalR, Event Hubs, etc.
/// </summary>
internal sealed class LogQualityPublisher : IQualityPublisher
{
    private readonly ILogger<LogQualityPublisher> _log;

    public LogQualityPublisher(ILogger<LogQualityPublisher> log) => _log = log;

    public Task PublishAsync(QualityCheckResult result, CancellationToken ct)
    {
        _log.LogInformation("Publishing quality result for {Zone}/{Dataset} – Success: {Success}",
            result.Zone, result.Dataset, result.IsSuccess);
        return Task.CompletedTask;
    }
}

/// <summary>
/// Data transfer object describing the outcome of a quality check.
/// </summary>
internal sealed record QualityCheckResult(
    string Zone,
    string Dataset,
    DateTime TimestampUtc,
    bool IsSuccess,
    IReadOnlyCollection<QualityIssue> Issues);

/// <summary>
/// Represents a single problem found during validation.
/// </summary>
internal sealed record QualityIssue(QualitySeverity Severity, string Description);

internal enum QualitySeverity { Info, Warning, Critical }

/// <summary>
/// Statistical overview of a dataset.
/// </summary>
internal sealed record DataStatistics(
    int RecordCount,
    double NullPercentage,
    int DuplicateCount);

/// <summary>
/// Provides liveness & readiness signals for Kubernetes / service mesh.
/// </summary>
internal sealed class QualityServiceHealthCheck : IHealthCheck
{
    private readonly IDataLakeClient _lake;

    public QualityServiceHealthCheck(IDataLakeClient lake) => _lake = lake;

    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context,
        CancellationToken cancellationToken = default)
    {
        try
        {
            // Sanity call into the lake
            var zones = await _lake.ListZonesAsync(cancellationToken);
            return zones.Length == 0
                ? HealthCheckResult.Unhealthy("No zones found")
                : HealthCheckResult.Healthy();
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy("Exception while checking Data Lake connectivity", ex);
        }
    }
}
```