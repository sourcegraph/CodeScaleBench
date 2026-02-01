```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Api/Startup.cs

#nullable enable
using System.Text.Json;
using CanvasCraft.Core.ExperimentTracking;
using CanvasCraft.Core.FeatureEngineering;
using CanvasCraft.Core.FeatureStore;
using CanvasCraft.Core.HyperparameterTuning;
using CanvasCraft.Core.MLops;
using CanvasCraft.Core.ModelRegistry;
using CanvasCraft.Infrastructure.ExperimentTracking.Sql;
using CanvasCraft.Infrastructure.FeatureStore.Redis;
using CanvasCraft.Infrastructure.ModelRegistry.Postgres;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.OpenApi.Models;

namespace CanvasCraft.Api
{
    /// <summary>
    /// ASP.NET Core Startup class responsible for bootstrapping dependency–injection,
    /// middleware pipeline, and environment-specific configuration for CanvasCraft ML Studio.
    /// </summary>
    public sealed class Startup
    {
        private readonly IConfiguration _configuration;
        private readonly IWebHostEnvironment _environment;

        public Startup(IConfiguration configuration, IWebHostEnvironment environment)
        {
            _configuration = configuration;
            _environment  = environment;
        }

        /// <summary>
        /// Configures dependency–injection container.
        /// </summary>
        public void ConfigureServices(IServiceCollection services)
        {
            //----------------------------------------------------
            // ASP.NET Core & Third-party infrastructure services
            //----------------------------------------------------
            services
                .AddControllers(options =>
                {
                    // Enforce a global, uniform JSON response format.
                    options.Filters.Add(new ProducesAttribute("application/json"));
                })
                .AddJsonOptions(o =>
                {
                    o.JsonSerializerOptions.PropertyNamingPolicy      = JsonNamingPolicy.CamelCase;
                    o.JsonSerializerOptions.WriteIndented            = _environment.IsDevelopment();
                    o.JsonSerializerOptions.DefaultIgnoreCondition   = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull;
                });

            services.AddEndpointsApiExplorer();
            services.AddSwaggerGen(s =>
            {
                s.SwaggerDoc("v1", new OpenApiInfo
                {
                    Title       = "CanvasCraft ML Studio API",
                    Version     = "v1",
                    Description = "A creative ML training studio where every model is a living work of art."
                });
            });

            services.AddHealthChecks()
                    .AddCheck("self", () => HealthCheckResult.Healthy())
                    .AddRedis(_configuration.GetConnectionString("Redis")!, "redis")
                    .AddNpgSql(_configuration.GetConnectionString("Postgres")!, name: "postgres");

            //----------------------------------------------------
            // Domain-specific service registrations
            //----------------------------------------------------
            // Experiment Tracking
            services.AddScoped<IExperimentTracker, SqlExperimentTracker>();

            // Feature Store
            services.AddSingleton<IFeatureStore, RedisFeatureStore>();

            // Model Registry
            services.AddScoped<IModelRegistry, PostgresModelRegistry>();

            // Hyper-parameter tuning strategies (Strategy Pattern)
            services.AddSingleton<IHyperparameterSearchStrategy, BayesianSearchStrategy>();
            services.AddSingleton<IHyperparameterSearchStrategy, GridSearchStrategy>();

            // Feature-engineering palette factory (Factory Pattern)
            services.AddSingleton<IFeatureEngineeringPaletteFactory, FeatureEngineeringPaletteFactory>();

            // MLOps pipeline orchestrator (Pipeline Pattern)
            services.AddScoped<IMLopsPipeline, MlOpsPipeline>();

            // Observer Pattern – notify when model performance drifts
            services.AddSingleton<IModelPerformanceObserver, DriftDetectionObserver>();

            //----------------------------------------------------
            // Configuration binding
            //----------------------------------------------------
            services.Configure<StorageSettings>(_configuration.GetSection(StorageSettings.SectionName));
            services.Configure<ExperimentTrackerOptions>(_configuration.GetSection(ExperimentTrackerOptions.SectionName));
        }

        /// <summary>
        /// Configures HTTP request pipeline.
        /// </summary>
        public void Configure(IApplicationBuilder app, ILogger<Startup> logger)
        {
            // Global exception handler (must be first)
            app.UseMiddleware<ErrorHandlingMiddleware>();

            if (_environment.IsDevelopment())
            {
                app.UseDeveloperExceptionPage();
                app.UseSwagger();
                app.UseSwaggerUI(c =>
                {
                    c.SwaggerEndpoint("/swagger/v1/swagger.json", "CanvasCraft ML Studio API v1");
                    c.DisplayRequestDuration();
                });
            }

            app.UseHttpsRedirection();
            app.UseRouting();

            app.UseAuthorization();

            app.UseEndpoints(endpoints =>
            {
                endpoints.MapControllers();
                endpoints.MapHealthChecks("/healthz", new HealthCheckOptions
                {
                    ResponseWriter = WriteHealthResponse
                });
            });

            logger.LogInformation("CanvasCraft ML Studio successfully started in {Environment} mode.", _environment.EnvironmentName);
        }

        #region Helper methods / nested types

        private static Task WriteHealthResponse(HttpContext context, HealthReport report)
        {
            context.Response.ContentType = "application/json";
            var json = JsonSerializer.Serialize(new
            {
                status   = report.Status.ToString(),
                details  = report.Entries.Select(e => new
                {
                    name   = e.Key,
                    state  = e.Value.Status.ToString(),
                    error  = e.Value.Exception?.Message
                })
            });
            return context.Response.WriteAsync(json);
        }

        /// <summary>
        /// Lightweight custom exception–handling middleware that converts unhandled
        /// exceptions into ProblemDetails (RFC 7807 compliant) JSON responses.
        /// </summary>
        private sealed class ErrorHandlingMiddleware
        {
            private readonly RequestDelegate _next;
            private readonly ILogger<ErrorHandlingMiddleware> _logger;

            public ErrorHandlingMiddleware(RequestDelegate next, ILogger<ErrorHandlingMiddleware> logger)
            {
                _next   = next;
                _logger = logger;
            }

            public async Task InvokeAsync(HttpContext context)
            {
                try
                {
                    await _next(context);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unhandled exception caught by global middleware.");

                    var problem = new ProblemDetails
                    {
                        Status = StatusCodes.Status500InternalServerError,
                        Title  = "An internal server error occurred.",
                        Detail = _environment?.IsDevelopment() == true ? ex.ToString() : "Please contact support."
                    };

                    context.Response.ContentType = "application/problem+json";
                    context.Response.StatusCode  = problem.Status ?? StatusCodes.Status500InternalServerError;
                    await context.Response.WriteAsJsonAsync(problem);
                }
            }
        }

        #endregion
    }
}
```
