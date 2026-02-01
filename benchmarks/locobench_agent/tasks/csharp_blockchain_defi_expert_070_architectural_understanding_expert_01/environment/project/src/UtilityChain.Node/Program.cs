```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Node/Program.cs
// Project: UtilityChain Core Suite (blockchain_defi)
// -----------------------------------------------------------------------------
// Entry-point for the UtilityChain node executable. Responsible for boot-
// strapping configuration, dependency-injection, module discovery, and the
// application host/lifetime pipeline.
// -----------------------------------------------------------------------------

#region Imports

using System.CommandLine;
using System.CommandLine.Binding;
using System.Diagnostics;
using System.Reflection;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using UtilityChain.Node.Hosting;
using UtilityChain.Node.Infrastructure;
using UtilityChain.Node.Infrastructure.Events;
using UtilityChain.Node.Modules.Abstractions;

#endregion

#pragma warning disable CA2007 // Consider calling ConfigureAwait on the awaited task
#pragma warning disable CS1591 // Missing XML comment for publicly visible type or member

try
{
    // ──────────────────────────────────────────────────────────────────────────
    // 1. Build CLI syntax and parse incoming arguments
    // ──────────────────────────────────────────────────────────────────────────
    var rootCommand = CliDefinition.BuildRootCommand();
    var cliParseResult = await rootCommand.ParseAsync(Environment.GetCommandLineArgs()[1..]);

    // If the user requested --help or parsing failed, exit early.
    if (cliParseResult.Errors.Count > 0 || cliParseResult.Directives.Contains("help"))
    {
        return;
    }

    var nodeOptions = new NodeOptionsBinder().GetBoundValue(cliParseResult);

    // ──────────────────────────────────────────────────────────────────────────
    // 2. Compose the application host
    // ──────────────────────────────────────────────────────────────────────────
    var builder = Host.CreateApplicationBuilder(new HostApplicationBuilderSettings
    {
        Args = Environment.GetCommandLineArgs(),
        ContentRootPath = nodeOptions.ContentRoot ?? Directory.GetCurrentDirectory(),
        ApplicationName = "UtilityChain.Node"
    });

    ConfigureLogging(builder, nodeOptions);
    ConfigureConfiguration(builder, nodeOptions);
    ConfigureDependencyInjection(builder, nodeOptions);

    using var host = builder.Build();

    // ──────────────────────────────────────────────────────────────────────────
    // 3. Run the host (blocking until cancellation/shutdown)
    // ──────────────────────────────────────────────────────────────────────────
    await host.RunAsync();
}
catch (Exception ex) when (LogFatal(ex))
{
    // The logging method returns false so that we never actually
    // fall into this 'catch' block flow – the method takes care of
    // logging and we simply allow the exception to bubble as ‘unhandled’.
}

#region Host Configuration

static void ConfigureConfiguration(HostApplicationBuilder builder, NodeOptions options)
{
    builder.Configuration
        .AddJsonFile("appsettings.json", optional: true, reloadOnChange: true)
        .AddEnvironmentVariables(prefix: "UTILITYCHAIN_")
        .AddCommandLine(Environment.GetCommandLineArgs())
        .AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["Node:Network"] = options.Network
        });
}

static void ConfigureLogging(HostApplicationBuilder builder, NodeOptions options)
{
    builder.Logging.ClearProviders();
    builder.Logging.AddConsole(cfg =>
    {
        cfg.TimestampFormat = "[yyyy-MM-dd HH:mm:ss] ";
        cfg.IncludeScopes   = builder.Environment.IsDevelopment();
    });
    builder.Logging.SetMinimumLevel(options.Verbose ? LogLevel.Debug : LogLevel.Information);
}

static void ConfigureDependencyInjection(HostApplicationBuilder builder, NodeOptions options)
{
    var services  = builder.Services;
    var config    = builder.Configuration;
    var logger    = builder.Logging.CreateLogger("Bootstrapper");

    // Core infrastructure
    services.AddSingleton(options);
    services.AddSingleton<IEventBus, InProcessEventBus>();
    services.AddHostedService<NodeLifetimeHostedService>();

    // Discover and load pluggable modules (staking, consensus, etc.)
    ModuleLoader.LoadModules(services, config, logger);
}

#endregion

#region Logging Helpers

static bool LogFatal(Exception ex)
{
    try
    {
        var category = typeof(Program).FullName ?? "Program";
        using var loggerFactory = LoggerFactory.Create(lb => lb.AddConsole());
        var logger = loggerFactory.CreateLogger(category);
        logger.LogCritical(ex, "Fatal exception terminated UtilityChain.Node");
    }
    catch
    {
        // Fell through – cannot log.
    }

    // Bubble the exception.
    return false;
}

#endregion

#pragma warning restore CA2007
#pragma warning restore CS1591

// ──────────────────────────────────────────────────────────────────────────────
// Below are the minimal infrastructure types kept in a single file for the
// sake of brevity. In the real codebase, these would live in dedicated files.
// ──────────────────────────────────────────────────────────────────────────────
namespace UtilityChain.Node
{
    /// <summary>
    /// Command-line options parsed from System.CommandLine.
    /// </summary>
    public sealed record NodeOptions
    {
        public bool   Verbose      { get; init; }
        public string Network      { get; init; } = "default";
        public string? ContentRoot { get; init; }
    }
}

namespace UtilityChain.Node.Infrastructure
{
    using Microsoft.Extensions.Logging;
    using System.Collections.Concurrent;

    /// <summary>
    /// Simple in-process event bus leveraging a pub/sub model.
    /// </summary>
    public sealed class InProcessEventBus : IEventBus
    {
        private readonly ConcurrentDictionary<Type, List<Delegate>> _handlers = new();

        public void Publish<TEvent>(TEvent @event)
        {
            if (_handlers.TryGetValue(typeof(TEvent), out var subscribers))
            {
                foreach (var handler in subscribers.OfType<Action<TEvent>>())
                {
                    // Fire-and-forget; the node is event-driven and
                    // handlers must handle their own exceptions.
                    Task.Run(() => handler(@event));
                }
            }
        }

        public void Subscribe<TEvent>(Action<TEvent> handler)
        {
            var subscribers = _handlers.GetOrAdd(typeof(TEvent), _ => new List<Delegate>());
            lock (subscribers)
            {
                subscribers.Add(handler);
            }
        }
    }
}

namespace UtilityChain.Node.Infrastructure.Events
{
    /// <summary>
    /// Public contract for the internal event bus.
    /// </summary>
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
        void Subscribe<TEvent>(Action<TEvent> handler);
    }
}

namespace UtilityChain.Node.Hosting
{
    using Microsoft.Extensions.Hosting;
    using Microsoft.Extensions.Logging;

    /// <summary>
    /// Background service responsible for graceful startup/shutdown hooks.
    /// </summary>
    internal sealed class NodeLifetimeHostedService : IHostedService
    {
        private readonly ILogger<NodeLifetimeHostedService> _logger;
        private readonly IHostApplicationLifetime           _lifetime;

        public NodeLifetimeHostedService(
            ILogger<NodeLifetimeHostedService> logger,
            IHostApplicationLifetime            lifetime)
        {
            _logger   = logger;
            _lifetime = lifetime;
        }

        public Task StartAsync(CancellationToken cancellationToken)
        {
            _logger.LogInformation("UtilityChain.Node started");
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken)
        {
            _logger.LogInformation("UtilityChain.Node stopped");
            return Task.CompletedTask;
        }
    }
}

namespace UtilityChain.Node.Modules.Abstractions
{
    using Microsoft.Extensions.Configuration;
    using Microsoft.Extensions.DependencyInjection;

    /// <summary>
    /// Contract that all node modules must implement in order to be discovered.
    /// </summary>
    public interface INodeModule
    {
        void Register(IServiceCollection services, IConfiguration configuration);
    }
}

namespace UtilityChain.Node.Infrastructure
{
    using Microsoft.Extensions.Configuration;
    using Microsoft.Extensions.DependencyInjection;
    using Microsoft.Extensions.Logging;
    using UtilityChain.Node.Modules.Abstractions;

    /// <summary>
    /// Responsible for discovering and wiring in pluggable node modules.
    /// </summary>
    internal static class ModuleLoader
    {
        public static void LoadModules(
            IServiceCollection services,
            IConfiguration configuration,
            ILogger logger)
        {
            // For simplicity, load all assemblies in the current directory
            // matching the convention `UtilityChain.*.dll`.
            var baseDir   = AppContext.BaseDirectory;
            var assemblies = Directory.EnumerateFiles(baseDir, "UtilityChain.*.dll")
                                      .Select(Assembly.LoadFrom)
                                      .ToArray();

            foreach (var assembly in assemblies)
            {
                var moduleTypes = assembly
                    .DefinedTypes
                    .Where(t => typeof(INodeModule).IsAssignableFrom(t) &&
                                !t.IsAbstract &&
                                !t.IsInterface)
                    .ToArray();

                foreach (var moduleType in moduleTypes)
                {
                    try
                    {
                        var module = (INodeModule)Activator.CreateInstance(moduleType)!;
                        module.Register(services, configuration);
                        logger.LogInformation("Loaded module: {Module}", moduleType.FullName);
                    }
                    catch (Exception ex)
                    {
                        logger.LogError(ex, "Failed to load module {Module}", moduleType.FullName);
                    }
                }
            }
        }
    }
}

namespace UtilityChain.Node.Infrastructure
{
    using System.CommandLine;

    /// <summary>
    /// Defines the System.CommandLine syntax for UtilityChain.Node.
    /// </summary>
    internal static class CliDefinition
    {
        public static RootCommand BuildRootCommand()
        {
            var cmd = new RootCommand("UtilityChain Core Node");

            var verboseOpt = new Option<bool>(
                aliases: new[] { "--verbose", "-v" },
                description: "Enable verbose (debug) logging");

            var networkOpt = new Option<string>(
                aliases: new[] { "--network", "-n" },
                getDefaultValue: () => "default",
                description: "Blockchain network identifier");

            var contentRootOpt = new Option<string?>(
                aliases: new[] { "--content-root", "-c" },
                description: "Override content-root directory");

            cmd.AddOption(verboseOpt);
            cmd.AddOption(networkOpt);
            cmd.AddOption(contentRootOpt);

            return cmd;
        }
    }

    internal sealed class NodeOptionsBinder : BinderBase<NodeOptions>
    {
        protected override NodeOptions GetBoundValue(BindingContext bindingContext) =>
            new()
            {
                Verbose      = bindingContext.ParseResult.GetValueForOption<bool>("--verbose"),
                Network      = bindingContext.ParseResult.GetValueForOption<string>("--network") ?? "default",
                ContentRoot  = bindingContext.ParseResult.GetValueForOption<string?>("--content-root")
            };
    }
}
```