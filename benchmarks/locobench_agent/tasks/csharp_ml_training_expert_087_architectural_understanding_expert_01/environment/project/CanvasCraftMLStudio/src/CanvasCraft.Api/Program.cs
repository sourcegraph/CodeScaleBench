```csharp
using System.Reflection;
using CanvasCraft.Api.Infrastructure;
using CanvasCraft.Core.Events;
using CanvasCraft.Core.FeatureStore;
using CanvasCraft.Core.ModelRegistry;
using CanvasCraft.Core.Pipelines;
using CanvasCraft.Infrastructure.Persistence;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Serilog;
using Serilog.Exceptions;
using Serilog.Sinks.SystemConsole.Themes;

var builder = WebApplication.CreateBuilder(args);

// ------------------------------------------------------------
// 1. Bootstrap logging (Serilog)
// ------------------------------------------------------------
Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .Enrich.WithProperty("Application", "CanvasCraft.Api")
    .Enrich.WithExceptionDetails()
    .WriteTo.Console(theme: AnsiConsoleTheme.Code)
    .CreateLogger();

builder.Host
    .UseSerilog((ctx, services, cfg) =>
        cfg.ReadFrom.Configuration(ctx.Configuration)
           .ReadFrom.Services(services)
           .Enrich.FromLogContext()
           .WriteTo.Console(theme: AnsiConsoleTheme.Code));

// ------------------------------------------------------------
// 2. Configuration & Options
// ------------------------------------------------------------
builder.Services.Configure<ApiBehaviorOptions>(options =>
{
    options.SuppressInferBindingSourcesForParameters = true;
    options.SuppressModelStateInvalidFilter          = true;
});

// ------------------------------------------------------------
// 3. Infrastructure components
// ------------------------------------------------------------

// Database (PostgreSQL for metadata, feature store, experiment tracking)
builder.Services.AddDbContext<CanvasCraftDbContext>(options =>
{
    var connectionString = builder.Configuration.GetConnectionString("CanvasCraft");
    options.UseNpgsql(connectionString,
        npgsql => npgsql.MigrationsAssembly(typeof(CanvasCraftDbContext).Assembly.FullName));
});

// Feature Store
builder.Services.AddScoped<IFeatureStore, PgFeatureStore>();

// Model Registry
builder.Services.AddScoped<IModelRegistry, PgModelRegistry>();

// Pipeline Orchestrator (Strategy + Factory pattern)
builder.Services.AddScoped<IPipelineOrchestrator, PipelineOrchestrator>();

// Domain Events (Observer pattern)
builder.Services.AddSingleton<IDomainEventDispatcher, DomainEventDispatcher>();

// Controllers & MVC
builder.Services
       .AddControllers()
       .AddJsonOptions(o => { o.JsonSerializerOptions.PropertyNamingPolicy = null; });

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new()
    {
        Version     = "v1",
        Title       = "CanvasCraft ML Studio API",
        Description = "RESTful endpoints for CanvasCraft ML Studio."
    });

    var xmlFile = $"{Assembly.GetExecutingAssembly().GetName().Name}.xml";
    var xmlPath = Path.Combine(AppContext.BaseDirectory, xmlFile);
    if (File.Exists(xmlPath))
        c.IncludeXmlComments(xmlPath);
});

// Health Checks
builder.Services.AddHealthChecks()
       .AddNpgSql(builder.Configuration.GetConnectionString("CanvasCraft")!, name: "Postgres");

// ------------------------------------------------------------
// 4. Build application
// ------------------------------------------------------------
var app = builder.Build();

// ------------------------------------------------------------
// 5. Application middleware pipeline
// ------------------------------------------------------------

app.UseSerilogRequestLogging(opts =>
{
    opts.EnrichDiagnosticContext = (ctx, http) =>
    {
        ctx.Set("CorrelationId", http.TraceIdentifier);
        ctx.Set("UserAgent", http.Request.Headers.UserAgent.ToString());
    };
});

if (app.Environment.IsDevelopment())
{
    app.UseDeveloperExceptionPage();
    app.UseSwagger();
    app.UseSwaggerUI(c => c.SwaggerEndpoint("/swagger/v1/swagger.json", "CanvasCraft.Api v1"));
}
else
{
    app.UseExceptionHandler("/error");
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseRouting();

app.UseAuthorization();

app.MapControllers();
app.MapHealthChecks("/_health", new HealthCheckOptions
{
    ResponseWriter = HealthCheckResponseWriter.WriteResponse
});

// ------------------------------------------------------------
// 6. Database initialization / migrations
// ------------------------------------------------------------
await using (var scope = app.Services.CreateAsyncScope())
{
    var dbContext = scope.ServiceProvider.GetRequiredService<CanvasCraftDbContext>();
    var logger    = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();

    try
    {
        logger.LogInformation("Applying database migrations…");
        await dbContext.Database.MigrateAsync();

        logger.LogInformation("Seeding initial data…");
        await CanvasCraftDbSeeder.SeedAsync(dbContext, logger);
    }
    catch (Exception ex)
    {
        logger.LogCritical(ex, "Database migration failed");
        throw;
    }
}

// ------------------------------------------------------------
// 7. Run the application
// ------------------------------------------------------------
try
{
    Log.Information("Starting CanvasCraft.Api…");
    await app.RunAsync();
}
catch (Exception ex) when (ex is not HostAbortedException)
{
    Log.Fatal(ex, "CanvasCraft.Api terminated unexpectedly");
}
finally
{
    Log.CloseAndFlush();
}
```
