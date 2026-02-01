```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Node/Startup.cs

using System;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using UtilityChain.Core.Abstractions;
using UtilityChain.Core.Consensus;
using UtilityChain.Core.Events;
using UtilityChain.Core.Governance;
using UtilityChain.Core.Staking;
using UtilityChain.Core.Token;
using UtilityChain.Node.Infrastructure;
using UtilityChain.Node.Options;

namespace UtilityChain.Node;

/// <summary>
/// Boot-straps the UtilityChain node. 
/// This class wires up the dependency-injection container, the configuration system,
/// logging, background services, and infrastructure cross-cutting concerns
/// (event bus, state machine host, etc.).
/// </summary>
public sealed class Startup
{
    private const string DefaultConfigFileName = "nodeSettings.json";
    private readonly IConfiguration _configuration;
    private readonly IHostEnvironment _environment;
    private readonly ILogger<Startup> _logger;

    private Startup(IConfiguration configuration, IHostEnvironment environment, ILogger<Startup> logger)
    {
        _configuration  = configuration  ?? throw new ArgumentNullException(nameof(configuration));
        _environment    = environment    ?? throw new ArgumentNullException(nameof(environment));
        _logger         = logger         ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>
    /// Creates and runs a UtilityChain node host.
    /// </summary>
    /// <param name="args">Command-line arguments.</param>
    /// <returns>Exit code.</returns>
    public static async Task<int> RunAsync(string[] args)
    {
        using IHost host = BuildHost(args);
        await host.RunAsync().ConfigureAwait(false);
        return 0;
    }

    /// <summary>
    /// Builds the generic host that powers the node.
    /// </summary>
    /// <remarks>
    /// The host is configured for resiliency: critical hosted services are wrapped in
    /// the <see cref="RetryingHostedServiceDecorator"/> which will restart transient-failing
    /// services without tearing down the entire node.
    /// </remarks>
    private static IHost BuildHost(string[] args)
    {
        return Host.CreateDefaultBuilder(args)
                   .ConfigureAppConfiguration((ctx, config) =>
                   {
                       // Clear default JSON providers so that we can fully control precedence
                       config.Sources.Clear();

                       // 1) AppSettings.{ENV}.json (optional)
                       config.AddJsonFile("appSettings.json", optional: true, reloadOnChange: true)
                             .AddJsonFile($"appSettings.{ctx.HostingEnvironment.EnvironmentName}.json",
                                          optional: true,
                                          reloadOnChange: true);

                       // 2) Node settings – overrides app settings
                       var nodeSettingsPath = Path.Combine(
                           ctx.HostingEnvironment.ContentRootPath,
                           DefaultConfigFileName);
                       config.AddJsonFile(nodeSettingsPath, optional: true, reloadOnChange: true);

                       // 3) Environment variables (UtilityChain__*)
                       config.AddEnvironmentVariables("UtilityChain__");

                       // 4) Command-line args (highest precedence)
                       config.AddCommandLine(args);
                   })
                   .ConfigureServices((ctx, services) =>
                   {
                       // Bind strongly-typed options.
                       services.AddOptions<NodeOptions>()
                               .Bind(ctx.Configuration.GetSection(NodeOptions.SectionName))
                               .ValidateDataAnnotations()
                               .ValidateOnStart();

                       services.AddSingleton<IClock, SystemClock>();

                       // Infrastructure
                       services.AddSingleton<IEventBus, InMemoryEventBus>();
                       services.AddSingleton<IStateMachineHost, StateMachineHost>();

                       // Register application modules (staking, consensus, etc.)
                       services.AddConsensus(ctx.Configuration)
                               .AddStaking(ctx.Configuration)
                               .AddGovernance(ctx.Configuration)
                               .AddTokenEngine(ctx.Configuration);

                       // Hosted service responsible for orchestrating modules.
                       services.AddHostedService<NodeRuntimeCoordinator>();

                       // Decorate hosted services with retry logic except for the coordinator itself.
                       services.DecorateAllHostedServicesWith<RetryingHostedServiceDecorator>(exclude: typeof(NodeRuntimeCoordinator));
                   })
                   .ConfigureLogging((ctx, logging) =>
                   {
                       logging.ClearProviders();
                       logging.AddConsole();

                       if (ctx.HostingEnvironment.IsDevelopment())
                       {
                           logging.AddDebug();
                       }
                   })
                   .UseConsoleLifetime()
                   .Build();
    }

    #region ───── Extension Methods ────────────────────────────────────────────────────────────────

    /// <summary>
    /// Adds consensus-related services to the container.
    /// </summary>
    private static IServiceCollection AddConsensus(this IServiceCollection services, IConfiguration configuration)
    {
        var section = configuration.GetSection("Consensus");
        services.Configure<ConsensusOptions>(section);
        services.AddSingleton<IConsensusEngine, ProofOfAuthorityEngine>();
        services.AddHostedService<ConsensusHostedService>();
        return services;
    }

    /// <summary>
    /// Adds staking-related services to the container.
    /// </summary>
    private static IServiceCollection AddStaking(this IServiceCollection services, IConfiguration configuration)
    {
        var section = configuration.GetSection("Staking");
        services.Configure<StakingOptions>(section);
        services.AddSingleton<IStakingCalculator, DefaultStakingCalculator>();
        services.AddHostedService<StakingHostedService>();
        return services;
    }

    /// <summary>
    /// Adds governance services to the container.
    /// </summary>
    private static IServiceCollection AddGovernance(this IServiceCollection services, IConfiguration configuration)
    {
        var section = configuration.GetSection("Governance");
        services.Configure<GovernanceOptions>(section);
        services.AddSingleton<IGovernanceEngine, SnapshotGovernanceEngine>();
        services.AddHostedService<GovernanceHostedService>();
        return services;
    }

    /// <summary>
    /// Adds token / NFT engine services to the DI container.
    /// </summary>
    private static IServiceCollection AddTokenEngine(this IServiceCollection services, IConfiguration configuration)
    {
        var section = configuration.GetSection("TokenEngine");
        services.Configure<TokenEngineOptions>(section);
        services.AddSingleton<ITokenEngine, DefaultTokenEngine>();
        services.AddHostedService<TokenHostedService>();
        return services;
    }

    /// <summary>
    /// Decorates all registered <see cref="IHostedService"/> with <typeparamref name="TDecorator"/>
    /// except those specified by <paramref name="exclude"/>.
    /// </summary>
    private static IServiceCollection DecorateAllHostedServicesWith<TDecorator>(
        this IServiceCollection services,
        params Type[] exclude)
        where TDecorator : class, IHostedService
    {
        for (var i = 0; i < services.Count; ++i)
        {
            var descriptor = services[i];
            if (descriptor.ServiceType != typeof(IHostedService)) continue;
            if (exclude != null && Array.Exists(exclude, e => e == descriptor.ImplementationType)) continue;

            var implementationType = descriptor.ImplementationType;
            if (implementationType is null) continue; // only class-registered services are supported

            var decoratedDescriptor = ServiceDescriptor.Describe(
                serviceType: typeof(IHostedService),
                implementationFactory: provider =>
                {
                    var loggerFactory   = provider.GetRequiredService<ILoggerFactory>();
                    var originalService = (IHostedService)ActivatorUtilities.CreateInstance(provider, implementationType!);
                    return ActivatorUtilities.CreateInstance<TDecorator>(provider, originalService, loggerFactory);
                },
                lifetime: descriptor.Lifetime);

            services[i] = decoratedDescriptor;
        }

        return services;
    }

    #endregion
}

/// <summary>
/// Coordinates the lifetime of individual subsystems and ensures healthy startup / shutdown.
/// </summary>
internal sealed class NodeRuntimeCoordinator : IHostedService
{
    private readonly ILogger<NodeRuntimeCoordinator> _logger;
    private readonly IEventBus _bus;
    private readonly IHostApplicationLifetime _appLifetime;

    public NodeRuntimeCoordinator(
        ILogger<NodeRuntimeCoordinator> logger,
        IEventBus bus,
        IHostApplicationLifetime appLifetime)
    {
        _logger       = logger;
        _bus          = bus;
        _appLifetime  = appLifetime;
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("UtilityChain Node runtime coordinator starting…");

        // Example of subscribing to a critical event (Observer Pattern)
        _bus.Subscribe<NodePanicEvent>(OnNodePanic);

        _logger.LogInformation("Runtime coordinator fully started.");
        return Task.CompletedTask;
    }

    private void OnNodePanic(NodePanicEvent e)
    {
        _logger.LogCritical("Critical panic detected from {@Subsystem}. Reason: {Reason}. Initiating shutdown.",
            e.Subsystem, e.Reason);

        // Stop the host – triggers orderly shutdown.
        _appLifetime.StopApplication();
    }

    public Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("Runtime coordinator stopping…");
        _bus.Unsubscribe<NodePanicEvent>(OnNodePanic);
        return Task.CompletedTask;
    }
}

/// <summary>
/// Wraps another <see cref="IHostedService"/> and retries it when it exits unexpectedly.
/// This is an application of the proxy pattern providing resilience.
/// </summary>
internal sealed class RetryingHostedServiceDecorator : IHostedService
{
    private readonly IHostedService _inner;
    private readonly ILogger _logger;
    private readonly CancellationTokenSource _cts = new();

    public RetryingHostedServiceDecorator(IHostedService inner, ILoggerFactory loggerFactory)
    {
        _inner  = inner  ?? throw new ArgumentNullException(nameof(inner));
        _logger = loggerFactory.CreateLogger(inner.GetType().Name + "_RetryDecorator");
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        _logger.LogDebug("Starting hosted service with retry decorator: {Service}", _inner.GetType().Name);

        _ = Task.Run(() => RunWithRetryAsync(_cts.Token), CancellationToken.None);
        await Task.CompletedTask;
    }

    private async Task RunWithRetryAsync(CancellationToken cancellationToken)
    {
        const int maxAttempts = 5;
        var attempt = 0;

        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                attempt++;
                _logger.LogInformation("Attempt {Attempt} to start {Service}.", attempt, _inner.GetType().Name);

                await _inner.StartAsync(cancellationToken).ConfigureAwait(false);
                _logger.LogInformation("{Service} completed successfully.", _inner.GetType().Name);
                return; // exit loop
            }
            catch (Exception ex) when (attempt < maxAttempts)
            {
                _logger.LogWarning(ex,
                    "{Service} failed with error. Retrying in 5s ({Attempt}/{Max}).",
                    _inner.GetType().Name, attempt, maxAttempts);

                await Task.Delay(TimeSpan.FromSeconds(5), cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogCritical(ex,
                    "{Service} failed after {MaxAttempts} attempts. Giving up.",
                    _inner.GetType().Name, maxAttempts);
                throw;
            }
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogDebug("Stopping hosted service with retry decorator: {Service}", _inner.GetType().Name);

        _cts.Cancel();
        await _inner.StopAsync(cancellationToken).ConfigureAwait(false);
    }
}

/// <summary>
/// Represents an event dispatched on unrecoverable failure of a subsystem.
/// Listeners should shut down or transition to safe state.
/// </summary>
public sealed record NodePanicEvent(string Subsystem, string Reason);

/// <summary>
/// Default implementation of a monotonic clock used for deterministic time handling
/// across modules (critical for block timestamp validation).
/// </summary>
internal sealed class SystemClock : IClock
{
    public DateTimeOffset UtcNow() => DateTimeOffset.UtcNow;
}

/// <summary>
/// Provides strongly-typed configuration for the node host.
/// </summary>
public sealed class NodeOptions
{
    public const string SectionName = "Node";
    
    /// <summary> Gets/sets the unique identifier of the network (E.g. 'EnergyNet'). </summary>
    public required string NetworkId { get; init; }
    
    /// <summary> Path to data directory. </summary>
    public required string DataDir { get; init; }

    /// <summary> Indicates whether the REST / GraphQL gateway should be enabled. </summary>
    public bool EnableApi { get; init; } = true;
}
```