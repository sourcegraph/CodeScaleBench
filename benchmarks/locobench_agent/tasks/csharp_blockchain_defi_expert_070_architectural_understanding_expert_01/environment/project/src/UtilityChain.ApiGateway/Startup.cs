```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.ApiGateway/Startup.cs

using System.Reflection;
using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.HttpLogging;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.AspNetCore.ResponseCompression;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using UtilityChain.ApiGateway.Infrastructure;
using UtilityChain.Core.Eventing;
using UtilityChain.Core.Telemetry;
using UtilityChain.Shared.Constants;

namespace UtilityChain.ApiGateway;

/// <summary>
///     ASP.NET Core startup class responsible for wiring services and middleware
///     used by the API-Gateway layer of the UtilityChain Core Suite.
/// </summary>
public sealed class Startup
{
    private readonly IConfiguration _configuration;
    private readonly IHostEnvironment _env;

    public Startup(IConfiguration configuration, IHostEnvironment env)
    {
        _configuration = configuration;
        _env           = env;
    }

    /// <summary>
    ///     Registers framework and custom services.
    /// </summary>
    public void ConfigureServices(IServiceCollection services)
    {
        // ------------------------------------------------------------
        // Infrastructure & cross-cutting concerns
        // ------------------------------------------------------------
        services.AddMemoryCache();
        services.AddHttpContextAccessor();
        services.AddHttpLogging(o =>
        {
            o.LoggingFields = HttpLoggingFields.All;
            o.RequestBodyLogLimit  = 4 * 1024; // 4 KB
            o.ResponseBodyLogLimit = 4 * 1024;
        });

        services.AddResponseCompression(o =>
        {
            o.Providers.Add<BrotliCompressionProvider>();
            o.EnableForHttps = true;
        });

        // ------------------------------------------------------------
        // CORS
        // ------------------------------------------------------------
        services.AddCors(opt =>
        {
            opt.AddPolicy(CorsPolicies.Default, builder =>
            {
                builder
                    .WithOrigins(_configuration
                        .GetSection("Cors:AllowedOrigins")
                        .Get<string[]>() ?? Array.Empty<string>())
                    .AllowAnyHeader()
                    .AllowAnyMethod()
                    .AllowCredentials();
            });
        });

        // ------------------------------------------------------------
        // Rate Limiting
        // ------------------------------------------------------------
        services.AddRateLimiter(opt =>
        {
            opt.AddPolicy(RateLimitPolicies.Fixed, context =>
                RateLimitPartition.GetSlidingWindowLimiter(
                    key: context.User?.Identity?.Name ?? context.Connection.RemoteIpAddress?.ToString() ?? "anonymous",
                    factory: _ => new SlidingWindowRateLimiterOptions
                    {
                        PermitLimit        = 100,
                        Window             = TimeSpan.FromMinutes(1),
                        SegmentsPerWindow  = 4,
                        QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                        QueueLimit         = 50
                    }));
        });

        // ------------------------------------------------------------
        // Authentication / Authorization
        // ------------------------------------------------------------
        services.Configure<JwtSettings>(_configuration.GetSection("Authentication:Jwt"));
        var jwtSettings = _configuration.GetSection("Authentication:Jwt").Get<JwtSettings>()!;

        services
            .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    RequireExpirationTime   = true,
                    ValidateIssuer          = true,
                    ValidateAudience        = true,
                    ValidateLifetime        = true,
                    ValidateIssuerSigningKey= true,
                    ValidIssuer             = jwtSettings.Issuer,
                    ValidAudience           = jwtSettings.Audience,
                    IssuerSigningKey        = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSettings.SigningKey))
                };
            });

        services.AddAuthorization(opt =>
        {
            opt.DefaultPolicy = new AuthorizationPolicyBuilder()
                .RequireAuthenticatedUser()
                .Build();

            opt.AddPolicy(AuthorizationPolicies.Administrator,
                policy => policy.RequireClaim(ClaimTypes.Role, Roles.Administrator));
        });

        // ------------------------------------------------------------
        // Controllers, API Versioning & Documentation
        // ------------------------------------------------------------
        services.AddControllers()
                .AddApplicationPart(Assembly.Load("UtilityChain.ApiGateway.Controllers"))
                .AddControllersAsServices();

        services.AddEndpointsApiExplorer();
        services.AddSwaggerGen(o =>
        {
            o.SwaggerDoc("v1", new() { Title = "UtilityChain API Gateway", Version = "v1" });
            // Provide JWT input in Swagger UI
            o.AddSecurityDefinition("Bearer", new()
            {
                Name         = "Authorization",
                In           = Microsoft.OpenApi.Models.ParameterLocation.Header,
                Type         = Microsoft.OpenApi.Models.SecuritySchemeType.Http,
                Scheme       = "bearer",
                BearerFormat = "JWT",
                Description  = "Enter 'Bearer {token}'"
            });
            o.AddSecurityRequirement(new()
            {
                {
                    new() { Reference = new() { Id = "Bearer", Type = Microsoft.OpenApi.Models.ReferenceType.SecurityScheme }},
                    Array.Empty<string>()
                }
            });
        });

        services.AddApiVersioning(opt =>
        {
            opt.AssumeDefaultVersionWhenUnspecified = true;
            opt.DefaultApiVersion = new Microsoft.AspNetCore.Mvc.ApiVersion(1, 0);
            opt.ReportApiVersions  = true;
        });

        // ------------------------------------------------------------
        // GraphQL (HotChocolate) – for flexible queryable access
        // ------------------------------------------------------------
        services
            .AddGraphQLServer()
            .AddQueryType(d => d.Name("Query"))
            .AddMutationType(d => d.Name("Mutation"))
            .AddSubscriptionType(d => d.Name("Subscription"))
            .AddInMemorySubscriptions();

        // ------------------------------------------------------------
        // Health Checks – surface liveness/readiness for orchestration
        // ------------------------------------------------------------
        services.AddHealthChecks()
                .AddCheck<BlockchainNodeHealthCheck>("blockchain_node")
                .AddSqlServer(
                    _configuration.GetConnectionString("SqlServer")!,
                    name: "sql_server",
                    tags: new[] { "db", "sql" });

        // ------------------------------------------------------------
        // Telemetry (OpenTelemetry)
        // ------------------------------------------------------------
        services.AddUtilityChainOpenTelemetry(_configuration);

        // ------------------------------------------------------------
        // Event Bus
        // ------------------------------------------------------------
        services.AddSingleton<IEventBus, InProcessEventBus>();

        // ------------------------------------------------------------
        // MediatR – cohesive in-process message dispatcher
        // ------------------------------------------------------------
        services.AddMediatR(cfg => cfg.RegisterServicesFromAssemblyContaining<Startup>());

        // ------------------------------------------------------------
        // Custom Middlewares / Filters
        // ------------------------------------------------------------
        services.AddScoped<CorrelationIdMiddleware>();
        services.AddScoped<ApiExceptionHandlingMiddleware>();
    }

    /// <summary>
    ///     Configures the HTTP pipeline.
    /// </summary>
    public void Configure(IApplicationBuilder app, IHostApplicationLifetime lifetime)
    {
        if (_env.IsDevelopment())
        {
            app.UseDeveloperExceptionPage();
            app.UseSwagger();
            app.UseSwaggerUI(o =>
            {
                o.SwaggerEndpoint("/swagger/v1/swagger.json", "UtilityChain API v1");
                o.DocExpansion(Swashbuckle.AspNetCore.SwaggerUI.DocExpansion.None);
            });
        }
        else
        {
            app.UseHsts(); // Add HSTS for production
        }

        app.UseResponseCompression();
        app.UseHttpLogging();

        // Global exception handling & correlation id
        app.UseMiddleware<CorrelationIdMiddleware>();
        app.UseMiddleware<ApiExceptionHandlingMiddleware>();

        // CORS & Security
        app.UseCors(CorsPolicies.Default);
        app.UseAuthentication();
        app.UseAuthorization();

        // Rate limiting
        app.UseRateLimiter();

        // Routing
        app.UseRouting();

        // GraphQL subscriptions (WebSockets)
        app.UseWebSockets();

        app.UseEndpoints(endpoints =>
        {
            endpoints.MapControllers();
            endpoints.MapGraphQL();
            endpoints.MapHealthChecks("/health/live", new HealthCheckOptions
            {
                Predicate = hc => hc.Tags.Contains("live")
            });
            endpoints.MapHealthChecks("/health/ready", new HealthCheckOptions
            {
                Predicate = _ => true
            });
        });

        // Log lifecycle events
        lifetime.ApplicationStarted.Register(() =>
            app.ApplicationServices.GetRequiredService<ILogger<Startup>>()
               .LogInformation("UtilityChain.ApiGateway started."));

        lifetime.ApplicationStopping.Register(() =>
            app.ApplicationServices.GetRequiredService<ILogger<Startup>>()
               .LogInformation("UtilityChain.ApiGateway stopping..."));
    }
}

/* -------------------------------------------------------------------------- */
/* --------------------- Infrastructure & Helper Components ----------------- */
/* -------------------------------------------------------------------------- */

#region Options

/// <summary>Strongly-typed JWT settings.</summary>
public sealed class JwtSettings
{
    public string Issuer     { get; init; } = default!;
    public string Audience   { get; init; } = default!;
    public string SigningKey { get; init; } = default!;
}

#endregion

#region Constants

internal static class CorsPolicies
{
    public const string Default = "Default";
}

internal static class RateLimitPolicies
{
    public const string Fixed = "FixedSliding";
}

internal static class AuthorizationPolicies
{
    public const string Administrator = "AdministratorPolicy";
}

internal static class Roles
{
    public const string Administrator = "Admin";
}

#endregion

#region Middleware

/// <summary>
///     Emits/propagates a correlation id on each request for distributed tracing.
/// </summary>
public sealed class CorrelationIdMiddleware
{
    private const string CorrelationIdHeader = "X-Correlation-Id";
    private readonly RequestDelegate _next;
    private readonly ILogger<CorrelationIdMiddleware> _logger;

    public CorrelationIdMiddleware(RequestDelegate next, ILogger<CorrelationIdMiddleware> logger)
    {
        _next   = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        if (!context.Request.Headers.TryGetValue(CorrelationIdHeader, out var correlationId))
        {
            correlationId = Guid.NewGuid().ToString("N");
            context.Request.Headers.Add(CorrelationIdHeader, correlationId);
        }

        context.Response.Headers.TryAdd(CorrelationIdHeader, correlationId);

        using (_logger.BeginScope("{CorrelationId}", correlationId.ToString()))
        {
            await _next(context);
        }
    }
}

/// <summary>
///     Converts unhandled exceptions into RFC7807 problem detail responses.
/// </summary>
public sealed class ApiExceptionHandlingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<ApiExceptionHandlingMiddleware> _logger;
    private readonly IHostEnvironment _env;

    public ApiExceptionHandlingMiddleware(RequestDelegate next, ILogger<ApiExceptionHandlingMiddleware> logger, IHostEnvironment env)
    {
        _next   = next;
        _logger = logger;
        _env    = env;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next.Invoke(context);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unhandled exception caught by middleware");

            context.Response.StatusCode  = StatusCodes.Status500InternalServerError;
            context.Response.ContentType = "application/problem+json";

            var problem = new
            {
                type   = "https://utilitychain.io/problems/unhandled-exception",
                title  = "An unexpected error occurred.",
                status = StatusCodes.Status500InternalServerError,
                detail = _env.IsDevelopment() ? ex.ToString() : null,
                traceId= context.TraceIdentifier
            };

            await context.Response.WriteAsJsonAsync(problem);
        }
    }
}

#endregion

#region HealthChecks

/// <summary>
///     Validates whether the underlying blockchain node is reachable and synchronized.
/// </summary>
public sealed class BlockchainNodeHealthCheck : IHealthCheck
{
    private readonly ILogger<BlockchainNodeHealthCheck> _logger;

    public BlockchainNodeHealthCheck(ILogger<BlockchainNodeHealthCheck> logger)
    {
        _logger = logger;
    }

    public Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context,
        CancellationToken    cancellationToken = default)
    {
        // NOTE: Replace with real connectivity check to consensus module
        var nodeIsHealthy = true; // stubbed for illustration

        if (nodeIsHealthy)
        {
            return Task.FromResult(HealthCheckResult.Healthy("Node synchronized"));
        }

        _logger.LogWarning("Blockchain node is out of sync or unreachable.");
        return Task.FromResult(HealthCheckResult.Unhealthy("Node out of sync"));
    }
}

#endregion

#region Telemetry Extensions

public static class TelemetryBootstrapExtensions
{
    /// <summary>
    /// Registers OpenTelemetry metrics, traces and logs using configuration.
    /// </summary>
    public static IServiceCollection AddUtilityChainOpenTelemetry(
        this IServiceCollection services,
        IConfiguration           configuration)
    {
        // Minimal stub – replace with full OpenTelemetry setup
        services.AddOpenTelemetry()
                .ConfigureResource(r => r.AddService("UtilityChain.ApiGateway"))
                .WithMetrics(m => m.AddAspNetCoreInstrumentation())
                .WithTracing(t => t.AddAspNetCoreInstrumentation());

        return services;
    }
}

#endregion

```