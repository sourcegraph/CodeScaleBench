```csharp
// -------------------------------------------------------------------------------------------------
//  CanvasCraft ML Studio
//  Program.cs
//
//  Entry point of the CanvasCraft.WebApp ASP-NET Core MVC application.  Responsible for
//  • Configuring dependency-injection containers
//  • Bootstrapping application-level infrastructure (logging, configuration, telemetry, etc.)
//  • Wiring middleware pipeline and HTTP endpoints
//
//  Author:   CanvasCraft Team
//  License:  MIT
// -------------------------------------------------------------------------------------------------

using System.Reflection;
using CanvasCraft.Core.Configuration;
using CanvasCraft.Core.Observability;
using CanvasCraft.Core.Pipeline;
using CanvasCraft.Core.Services;
using CanvasCraft.Infrastructure.Data;
using CanvasCraft.Infrastructure.HttpClients;
using CanvasCraft.WebApp.Background;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Serilog;

Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(GetBootstrapConfiguration())
    .Enrich.FromLogContext()
    .Enrich.WithProperty("Application", "CanvasCraft.WebApp")
    .CreateBootstrapLogger();

try
{
    Log.Information("🚀 Starting CanvasCraft.WebApp host");

    var builder = WebApplication.CreateBuilder(args);

    // Replace default logging with Serilog.
    builder.Host.UseSerilog((ctx, services, cfg) =>
    {
        cfg.ReadFrom.Configuration(ctx.Configuration)
           .ReadFrom.Services(services)
           .Enrich.FromLogContext()
           .Enrich.WithMachineName()
           .Enrich.WithEnvironmentName()
           .WriteTo.Console()
           .WriteTo.File("logs/canvascraft-.log",
                         rollingInterval: RollingInterval.Day,
                         retainedFileCountLimit: 14);
    });

    // Load optional user secrets in development.
    if (builder.Environment.IsDevelopment())
    {
        builder.Configuration.AddUserSecrets(Assembly.GetExecutingAssembly(), optional: true);
    }

    // Strongly-typed options pattern.
    builder.Services.Configure<FeatureStoreOptions>(
        builder.Configuration.GetSection(nameof(FeatureStoreOptions)));
    builder.Services.Configure<RegistryOptions>(
        builder.Configuration.GetSection(nameof(RegistryOptions)));

    // DbContext for Identity + application data.
    builder.Services.AddDbContext<AppDbContext>(options =>
        options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection"),
            sql => sql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));

    builder.Services.AddDefaultIdentity<IdentityUser>(options =>
        {
            options.SignIn.RequireConfirmedAccount = true;
        })
        .AddEntityFrameworkStores<AppDbContext>();

    // Add MVC controllers + Razor Pages.
    builder.Services.AddControllersWithViews();
    builder.Services.AddRazorPages();

    // OpenTelemetry / distributed tracing.
    builder.Services.AddCanvasCraftOpenTelemetry(builder.Configuration);

    // Health checks.
    builder.Services
        .AddHealthChecks()
        .AddDbContextCheck<AppDbContext>("PostgreSQL")
        .AddCheck<FeatureStoreHealthCheck>("FeatureStore");

    // HttpClient(s) for downstream micro-services.
    builder.Services.AddCanvasCraftHttpClients(builder.Configuration);

    // Domain services + factory/strategy registrations.
    builder.Services.AddCanvasCraftDomainServices();

    // Background hosted service for the MLOps pipeline.
    builder.Services.AddHostedService<PipelineOrchestratorBackgroundService>();

    var app = builder.Build();

    // Perform automatic database migrations in Development & Staging.
    if (app.Environment.IsDevelopment() || app.Environment.IsStaging())
    {
        await using var scope = app.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        await db.Database.MigrateAsync();
    }

    // Middleware pipeline ----------------------------------------------------
    if (!app.Environment.IsDevelopment())
    {
        app.UseExceptionHandler("/Home/Error");
        app.UseHsts();
    }

    app.UseSerilogRequestLogging(); // Request logging.

    app.UseHttpsRedirection();
    app.UseStaticFiles();

    app.UseRouting();

    app.UseAuthentication();
    app.UseAuthorization();

    // Map endpoints ----------------------------------------------------------
    app.MapControllerRoute(
        name: "default",
        pattern: "{controller=Home}/{action=Index}/{id?}");
    app.MapRazorPages();
    app.MapHealthChecks("/health", new HealthCheckOptions
    {
        ResponseWriter = HealthCheckUiResponseWriter.WriteResponse
    });

    Log.Information("✅ CanvasCraft.WebApp started successfully");
    await app.RunAsync();
}
catch (Exception ex)
{
    // Serilog will flush on dispose.
    Log.Fatal(ex, "💥 CanvasCraft.WebApp terminated unexpectedly");
}
finally
{
    Log.CloseAndFlush();
}

// -------------------------------------------------------------------------------------------------
//  Local helpers
// -------------------------------------------------------------------------------------------------
static IConfiguration GetBootstrapConfiguration()
{
    return new ConfigurationBuilder()
        .AddJsonFile("appsettings.json", optional: false, reloadOnChange: true)
        .AddJsonFile($"appsettings.{Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT")}.json",
            optional: true)
        .AddEnvironmentVariables()
        .Build();
}
```