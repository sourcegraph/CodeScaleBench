```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite (blockchain_defi)
//  File:    UtilityChainCoreSuite/src/UtilityChain.Node/NodeHost.cs
//  Project: UtilityChain Core Suite
//  Author:  AI Assistant
//
//  Description:
//  The NodeHost is the root–level bootstrapper for a UtilityChain node. It
//  wraps the generic .NET host, coordinates discovery and life-cycle of
//  plug-in modules, and exposes a simple state-machine so that other internal
//  components (CLI, wallet, REST gateway, etc.) can observe node activity in
//  a strongly-typed manner.
//
//  The class purposefully keeps its public surface small; orchestration of
//  consensus, staking, or governance engines is delegated to pluggable
//  INodeModule implementations that are discovered at runtime.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Versioning;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Node;

/// <summary>
/// Defines the contract that all internal UtilityChain modules must satisfy.
/// </summary>
public interface INodeModule
{
    /// <summary>Human-readable module name (used for logs, diagnostics).</summary>
    string Name { get; }

    /// <summary>Called once when the node is starting up.</summary>
    Task StartAsync(IServiceProvider services, CancellationToken ct);

    /// <summary>Called once when the node is shutting down.</summary>
    Task StopAsync(CancellationToken ct);
}

/// <summary>
/// Ambient options for <see cref="NodeHost"/>. Usually injected from
/// configuration providers (CLI args, JSON, EnvVars, etc.).
/// </summary>
public sealed class NodeHostOptions
{
    /// <summary>The logical network name (e.g. "private-net", "staging").</summary>
    public string Network { get; init; } = "private-net";

    /// <summary>Absolute path where chain-data, logs, and cache are stored.</summary>
    public string DataDirectory { get; init; }
        = Path.Combine(AppContext.BaseDirectory, "data");

    /// <summary>Paths that are probed for additional module assemblies.</summary>
    public string[] ModuleProbingPaths { get; init; } = { "modules" };

    /// <summary>When true the embedded REST+GraphQL gateway is enabled.</summary>
    public bool EnableApi { get; init; } = true;
}

/// <summary>
/// Internal state representation for <see cref="NodeHost"/>.
/// </summary>
internal enum NodeState
{
    Created,
    Initializing,
    Running,
    Stopping,
    Stopped,
    Faulted
}

/// <summary>
/// Simple state-machine with minimal safety checks.
/// </summary>
internal sealed class NodeStateMachine
{
    private readonly object _sync = new();
    private NodeState _state = NodeState.Created;

    public NodeState Current
    {
        get { lock (_sync) return _state; }
    }

    public event Action<NodeState>? StateChanged;

    public void TransitionTo(NodeState newState)
    {
        lock (_sync)
        {
            if (!IsValidTransition(_state, newState))
                throw new InvalidOperationException(
                    $"Invalid state transition {_state} → {newState}");

            _state = newState;
        }

        StateChanged?.Invoke(newState);
    }

    private static bool IsValidTransition(NodeState from, NodeState to) =>
        (from, to) switch
        {
            (NodeState.Created, NodeState.Initializing) => true,
            (NodeState.Initializing, NodeState.Running)  => true,
            (NodeState.Running, NodeState.Stopping)      => true,
            (NodeState.Stopping, NodeState.Stopped)      => true,
            (_, NodeState.Faulted)                       => true,
            _                                             => false
        };
}

/// <summary>
/// Discovers and manages life-cycle of <see cref="INodeModule"/> instances.
/// </summary>
internal sealed class NodeModuleLoader
{
    private readonly ILogger<NodeModuleLoader> _logger;
    private readonly List<INodeModule> _modules = new();

    public NodeModuleLoader(ILogger<NodeModuleLoader> logger) => _logger = logger;

    public IReadOnlyList<INodeModule> Modules => _modules;

    public void Discover(IEnumerable<string> probingPaths)
    {
        foreach (var path in probingPaths.Where(Directory.Exists))
        {
            foreach (var file in Directory.EnumerateFiles(path, "*.dll",
                         SearchOption.TopDirectoryOnly))
            {
                try
                {
                    var asm = Assembly.LoadFrom(file);
                    foreach (var modType in asm.GetTypes()
                             .Where(t => typeof(INodeModule).IsAssignableFrom(t) &&
                                         !t.IsAbstract && !t.IsInterface))
                    {
                        if (Activator.CreateInstance(modType) is not INodeModule mod)
                            continue;

                        _modules.Add(mod);
                        _logger.LogInformation(
                            "Discovered module {Module} in {Assembly}",
                            mod.Name, Path.GetFileName(file));
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to load assembly {Assembly}", file);
                }
            }
        }
    }

    public async Task StartModulesAsync(IServiceProvider sp, CancellationToken ct)
    {
        foreach (var module in _modules)
        {
            try
            {
                _logger.LogInformation("Starting module {Module}", module.Name);
                await module.StartAsync(sp, ct).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Module {Module} failed to start", module.Name);
                throw; // Bubble up; node will fault.
            }
        }
    }

    public async Task StopModulesAsync(CancellationToken ct)
    {
        foreach (var module in _modules.AsEnumerable().Reverse())
        {
            try
            {
                _logger.LogInformation("Stopping module {Module}", module.Name);
                await module.StopAsync(ct).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Module {Module} failed to stop", module.Name);
                // Continue shutting down remaining modules.
            }
        }
    }
}

/// <summary>
/// Primary bootstrapper for UtilityChain node processes.
/// </summary>
[SupportedOSPlatform("windows10.0.19041")]
[SupportedOSPlatform("linux")]
public sealed class NodeHost : IAsyncDisposable
{
    private readonly IHost _host;
    private readonly NodeModuleLoader _moduleLoader;
    private readonly NodeStateMachine _stateMachine;
    private readonly ILogger<NodeHost> _logger;
    private readonly CancellationTokenSource _cts = new();
    private readonly TaskCompletionSource _shutdownTcs =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private NodeHost(
        IHost host,
        NodeModuleLoader moduleLoader,
        NodeStateMachine stateMachine,
        ILogger<NodeHost> logger)
    {
        _host = host;
        _moduleLoader = moduleLoader;
        _stateMachine = stateMachine;
        _logger = logger;
    }

    // ---------------------------------------------------------------------
    //  Factory
    // ---------------------------------------------------------------------

    public static async Task<NodeHost> CreateAsync(
        NodeHostOptions options,
        Action<IServiceCollection>? configureServices = null,
        CancellationToken ct = default)
    {
        var builder = Host.CreateApplicationBuilder();

        // Base configuration providers.
        builder.Configuration
               .AddEnvironmentVariables("UTILITYCHAIN_");

        builder.Logging.ClearProviders();
        builder.Logging.AddConsole();
        builder.Logging.AddDebug();

        // Core services.
        builder.Services.AddSingleton(options);
        builder.Services.AddSingleton<NodeModuleLoader>();
        builder.Services.AddSingleton<NodeStateMachine>();

        configureServices?.Invoke(builder.Services);

        var host = builder.Build();

        // Resolve singletons created above.
        var loader = host.Services.GetRequiredService<NodeModuleLoader>();
        var sm     = host.Services.GetRequiredService<NodeStateMachine>();
        var logger = host.Services.GetRequiredService<ILogger<NodeHost>>();

        var nodeHost = new NodeHost(host, loader, sm, logger);
        await nodeHost.InitializeAsync(ct).ConfigureAwait(false);

        return nodeHost;
    }

    // ---------------------------------------------------------------------
    //  Public API
    // ---------------------------------------------------------------------

    /// <summary>Blocks until the node is shut down or <paramref name="ct"/> cancels.</summary>
    public async Task RunAsync(CancellationToken ct = default)
    {
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
        Console.CancelKeyPress += OnCancelKeyPress;

        try
        {
            _stateMachine.TransitionTo(NodeState.Running);
            _logger.LogInformation("UtilityChain node started (network: {Network})",
                _host.Services.GetRequiredService<NodeHostOptions>().Network);

            await Task.WhenAny(_shutdownTcs.Task,
                               Task.Delay(Timeout.Infinite, ct))
                      .ConfigureAwait(false);
        }
        finally
        {
            await ShutdownAsync().ConfigureAwait(false);
        }
    }

    /// <summary>Signals the node to shut down gracefully.</summary>
    public void RequestStop() => _shutdownTcs.TrySetResult();

    // ---------------------------------------------------------------------
    //  Internal orchestration
    // ---------------------------------------------------------------------

    private async Task InitializeAsync(CancellationToken ct)
    {
        _stateMachine.TransitionTo(NodeState.Initializing);

        var opts = _host.Services.GetRequiredService<NodeHostOptions>();

        Directory.CreateDirectory(opts.DataDirectory);
        _logger.LogInformation("Using data directory {DataDir}", opts.DataDirectory);

        // Discover & start modules before starting the generic host so they can
        // register hosted services, background workers, etc.
        _moduleLoader.Discover(opts.ModuleProbingPaths);

        await _host.StartAsync(ct).ConfigureAwait(false);
        await _moduleLoader.StartModulesAsync(_host.Services, ct)
                           .ConfigureAwait(false);
    }

    private async Task ShutdownAsync()
    {
        if (_stateMachine.Current is NodeState.Stopping or NodeState.Stopped)
            return; // Already shutting down.

        _stateMachine.TransitionTo(NodeState.Stopping);

        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            await _moduleLoader.StopModulesAsync(timeout.Token).ConfigureAwait(false);
            await _host.StopAsync(timeout.Token).ConfigureAwait(false);

            _stateMachine.TransitionTo(NodeState.Stopped);
            _logger.LogInformation("Node shutdown complete.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error while shutting down node");
            _stateMachine.TransitionTo(NodeState.Faulted);
        }
    }

    // ---------------------------------------------------------------------
    //  Event handlers
    // ---------------------------------------------------------------------

    private void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        _logger.LogCritical((Exception)e.ExceptionObject,
            "Unhandled exception. Node will shut down.");
        _stateMachine.TransitionTo(NodeState.Faulted);
        _shutdownTcs.TrySetResult();
    }

    private void OnCancelKeyPress(object? sender, ConsoleCancelEventArgs e)
    {
        e.Cancel = true; // Prevent the process from terminating immediately.
        _logger.LogInformation("SIGINT/SIGTERM received – initiating shutdown.");
        _shutdownTcs.TrySetResult();
    }

    // ---------------------------------------------------------------------
    //  Disposal
    // ---------------------------------------------------------------------

    public async ValueTask DisposeAsync()
    {
        await ShutdownAsync().ConfigureAwait(false);
        _cts.Cancel();
        _cts.Dispose();
        _host.Dispose();
        AppDomain.CurrentDomain.UnhandledException -= OnUnhandledException;
        Console.CancelKeyPress -= OnCancelKeyPress;
        GC.SuppressFinalize(this);
    }
}
```