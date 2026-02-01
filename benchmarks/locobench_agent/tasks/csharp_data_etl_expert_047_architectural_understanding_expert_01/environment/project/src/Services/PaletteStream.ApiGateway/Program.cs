```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.ApiGateway/Program.cs
//
// Entry-point for the PaletteStream API-Gateway.  This micro-service
// fronts the ETL micro-service mesh and provides:
//
//  • Reverse-proxy routing (YARP)                            /{service}/{**path}
//  • Observability (Serilog + OpenTelemetry)                 logs / traces / metrics
//  • Resilience   (Polly retry + circuit-breaker)
//  • Health-checks for itself AND the downstream services
//  • Start-up warm-up ping to reduce first-call latency
//
// NOTE: most configuration is externalised to appsettings.json / env-vars
// ---------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using Polly;
using Polly.Extensions.Http;
using Serilog;
using Yarp.ReverseProxy;

namespace PaletteStream.ApiGateway
{
    internal sealed class Program
    {
        private static readonly string[] DownstreamServiceNames =
        {
            "DataIngestion",
            "DataTransformation",
            "Visualization"
        };

        public static async Task Main(string[] args)
        {
            var builder = WebApplication.CreateBuilder(args);

            // ------------------------------------------------------------------
            // Logging: Serilog ➜ Console + any sinks defined in configuration.
            // ------------------------------------------------------------------
            builder.Host.UseSerilog((ctx, lc) =>
            {
                lc.ReadFrom.Configuration(ctx.Configuration)
                  .Enrich.FromLogContext()
                  .Enrich.WithProperty("Service", "ApiGateway")
                  .WriteTo.Console();
            });

            // ------------------------------------------------------------------
            // Core services.
            // ------------------------------------------------------------------
            RegisterServices(builder);

            var app = builder.Build();

            // ------------------------------------------------------------------
            // Pipeline.
            // ------------------------------------------------------------------
            app.UseSerilogRequestLogging();      // access log

            app.UseRouting();

            // Reverse proxy routing (YARP).
            app.MapReverseProxy();

            // Health probe endpoint.
            app.MapHealthChecks("/health");

            // Friendly landing page.
            app.MapGet("/", () => Results.Text(
                "PaletteStream Api-Gateway 🖌️ is running.\nVisit /health or hit proxied routes."));

            // ------------------------------------------------------------------
            // Warm-up downstream services to reduce first-hit latency.
            // ------------------------------------------------------------------
            await WarmUpAsync(app);

            await app.RunAsync();
        }

        // ----------------------------------------------------------------------
        // Service-registration helpers.
        // ----------------------------------------------------------------------
        private static void RegisterServices(WebApplicationBuilder builder)
        {
            IConfiguration config = builder.Configuration;
            IServiceCollection services = builder.Services;

            // YARP reverse-proxy (routes/clusters pulled from configuration).
            services.AddReverseProxy()
                    .LoadFromConfig(config.GetSection("ReverseProxy"));

            // Options pattern.
            services.Configure<RetryOptions>(config.GetSection(RetryOptions.SectionName));
            services.Configure<CircuitBreakerOptions>(config.GetSection(CircuitBreakerOptions.SectionName));

            // Resilient HTTP clients for each downstream micro-service.
            foreach (var svc in DownstreamServiceNames)
            {
                AddResilientHttpClient(services, svc);
            }

            // Health checks (self + downstream).
            services.AddHealthChecks()
                    .AddCheck<DownstreamAggregateHealthCheck>("downstream_services");

            // Observability – OpenTelemetry (traces + metrics) EXPORTS ➜ OTLP.
            services.AddOpenTelemetry()
                    .ConfigureResource(r => r.AddService("PaletteStream.ApiGateway"))
                    .WithTracing(t =>
                    {
                        t.AddAspNetCoreInstrumentation()
                         .AddHttpClientInstrumentation()
                         .AddOtlpExporter();      // endpoint comes from env-vars
                    })
                    .WithMetrics(m =>
                    {
                        m.AddAspNetCoreInstrumentation()
                         .AddRuntimeInstrumentation()
                         .AddHttpClientInstrumentation()
                         .AddPrometheusExporter();
                    });

            // Needed for SerilogRequestLogging
            services.AddHttpContextAccessor();
        }

        private static void AddResilientHttpClient(IServiceCollection services, string name)
        {
            services.AddHttpClient(name, (sp, client) =>
            {
                var configuration = sp.GetRequiredService<IConfiguration>();
                var baseAddress = configuration[$"Downstream:{name}:BaseAddress"];

                if (string.IsNullOrWhiteSpace(baseAddress))
                    throw new InvalidOperationException(
                        $"Missing configuration: Downstream:{name}:BaseAddress");

                client.BaseAddress = new Uri(baseAddress);
            })
            .AddPolicyHandler((sp, _) =>
            {
                var opts = sp.GetRequiredService<IOptions<RetryOptions>>().Value;
                return HttpPolicyBuilder.BuildRetryPolicy(opts);
            })
            .AddPolicyHandler((sp, _) =>
            {
                var opts = sp.GetRequiredService<IOptions<CircuitBreakerOptions>>().Value;
                return HttpPolicyBuilder.BuildCircuitBreakerPolicy(opts);
            });
        }

        // ----------------------------------------------------------------------
        // Warm-up pings to downstream /health endpoints (fire-and-forget).
        // ----------------------------------------------------------------------
        private static async Task WarmUpAsync(WebApplication app)
        {
            using var scope = app.Services.CreateScope();
            var factory = scope.ServiceProvider.GetRequiredService<IHttpClientFactory>();
            var logger  = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();

            foreach (string svc in DownstreamServiceNames)
            {
                try
                {
                    var client   = factory.CreateClient(svc);
                    var response = await client.GetAsync("health");

                    if (response.IsSuccessStatusCode)
                        logger.LogInformation("Warm-up to {Service} succeeded ({Status})",
                            svc, response.StatusCode);
                    else
                        logger.LogWarning("Warm-up to {Service} returned {Status}",
                            svc, response.StatusCode);
                }
                catch (Exception ex)
                {
                    logger.LogWarning(ex, "Warm-up to {Service} failed", svc);
                }
            }
        }
    }

    // ======================================================================
    // HEALTH-CHECK
    // Aggregate probe that fans-out to each downstream service.
    // ======================================================================
    internal sealed class DownstreamAggregateHealthCheck : IHealthCheck
    {
        private readonly IHttpClientFactory _clientFactory;
        private readonly ILogger<DownstreamAggregateHealthCheck> _log;

        public DownstreamAggregateHealthCheck(
            IHttpClientFactory clientFactory,
            ILogger<DownstreamAggregateHealthCheck> log)
        {
            _clientFactory = clientFactory;
            _log           = log;
        }

        public async Task<HealthCheckResult> CheckHealthAsync(
            HealthCheckContext context,
            CancellationToken token = default)
        {
            var unhealthy = new List<string>();

            foreach (string svc in Program.DownstreamServiceNames)
            {
                try
                {
                    var client   = _clientFactory.CreateClient(svc);
                    var response = await client.GetAsync("health", token);

                    if (!response.IsSuccessStatusCode)
                        unhealthy.Add($"{svc} ({(int)response.StatusCode})");
                }
                catch (Exception ex)
                {
                    _log.LogWarning(ex, "Health probe to {Service} failed", svc);
                    unhealthy.Add($"{svc} (exception)");
                }
            }

            return unhealthy.Count == 0
                ? HealthCheckResult.Healthy("All downstream services healthy")
                : HealthCheckResult.Unhealthy(
                    "Some downstream services are unhealthy",
                    data: new Dictionary<string, object?>
                    {
                        ["Unhealthy"] = string.Join(", ", unhealthy)
                    });
        }
    }

    // ======================================================================
    // POLLY OPTIONS & BUILDERS
    // ======================================================================
    internal record RetryOptions
    {
        public const string SectionName = "Resilience:Retry";

        public int    RetryCount               { get; init; } = 3;
        public double ExponentialBackoffFactor { get; init; } = 2;
        public int    FirstDelayMilliseconds   { get; init; } = 200;

        // e.g. [ "408", "502", "503", "504" ]
        public string[] HttpStatusCodesToRetry { get; init; } = Array.Empty<string>();
    }

    internal record CircuitBreakerOptions
    {
        public const string SectionName = "Resilience:CircuitBreaker";

        public int FailureThreshold        { get; init; } = 5;
        public int SamplingDurationSeconds { get; init; } = 30;
        public int MinimumThroughput       { get; init; } = 5;
        public int BreakDurationSeconds    { get; init; } = 15;
    }

    internal static class HttpPolicyBuilder
    {
        public static IAsyncPolicy<HttpResponseMessage> BuildRetryPolicy(RetryOptions opt)
        {
            int[] additionalCodes = opt.HttpStatusCodesToRetry?
                                        .Select(int.Parse)
                                        .ToArray() ?? Array.Empty<int>();

            // HandleTransientHttpError() handles 5xx + 408 by default.
            return HttpPolicyExtensions
                .HandleTransientHttpError()
                .OrResult(r => additionalCodes.Contains((int)r.StatusCode))
                .WaitAndRetryAsync(
                    opt.RetryCount,
                    retryAttempt =>
                    {
                        var backoff = Math.Pow(opt.ExponentialBackoffFactor, retryAttempt - 1);
                        var ms      = opt.FirstDelayMilliseconds * backoff;
                        return TimeSpan.FromMilliseconds(ms);
                    },
                    onRetry: (outcome, span, retry, ctx) =>
                    {
                        ctx.GetLogger()?.LogWarning(
                            "Retry {Retry}/{Total} for {Uri} after {Delay} due to {Status}.",
                            retry, opt.RetryCount, outcome?.Result?.RequestMessage?.RequestUri,
                            span, outcome.Exception?.Message ?? outcome.Result.StatusCode.ToString());
                    });
        }

        public static IAsyncPolicy<HttpResponseMessage> BuildCircuitBreakerPolicy(CircuitBreakerOptions opt)
        {
            return HttpPolicyExtensions
                .HandleTransientHttpError()
                .CircuitBreakerAsync(
                    failureThreshold: opt.FailureThreshold,
                    samplingDuration: TimeSpan.FromSeconds(opt.SamplingDurationSeconds),
                    minimumThroughput: opt.MinimumThroughput,
                    durationOfBreak: TimeSpan.FromSeconds(opt.BreakDurationSeconds),
                    onBreak: (outcome, ts) =>
                    {
                        Log.Logger.Warning(
                            "Circuit breaker opened for {Duration}s due to {Reason}.",
                            ts.TotalSeconds,
                            outcome.Exception?.Message ?? outcome.Result.StatusCode.ToString());
                    },
                    onReset: () => Log.Logger.Information("Circuit breaker reset."),
                    onHalfOpen: () => Log.Logger.Information("Circuit breaker half-open; testing next call."));
        }

        // Helper to get an ILogger from Polly Context (if any).
        private static ILogger? GetLogger(this Context ctx) =>
            ctx.TryGetValue("Logger", out var l) && l is ILogger logger ? logger : null;
    }
}
```