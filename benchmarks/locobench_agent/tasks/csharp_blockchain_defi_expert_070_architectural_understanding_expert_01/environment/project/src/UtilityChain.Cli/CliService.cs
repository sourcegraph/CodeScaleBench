```csharp
// -------------------------------------------------------------------------------------------------
// File:     UtilityChainCoreSuite/src/UtilityChain.Cli/CliService.cs
// Project:  UtilityChain Core Suite (blockchain_defi)
// Author:   UtilityChain Team
// License:  MIT
// -------------------------------------------------------------------------------------------------
// Description:
//     Central command–line entry point that wires together command routing, dependency injection,
//     telemetry, cancellation support, and dynamic module discovery.  Command implementations
//     live in feature assemblies (staking, governance, etc.) and are exposed to this service
//     through the `ICliModule` observer contract.  The class is intentionally asynchronous and
//     highly–resilient so that node operators can run long-lived tasks (e.g., staking loops,
//     block validation) without blocking the main thread.
// -------------------------------------------------------------------------------------------------

#nullable enable

using System.CommandLine;
using System.CommandLine.Builder;
using System.CommandLine.Parsing;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Cli;

/// <summary>
/// Primary façade responsible for parsing CLI arguments, bootstrapping the host, and delegating
/// to feature-specific modules that contribute <see cref="Command"/> objects through DI.
/// </summary>
public sealed class CliService : IAsyncDisposable
{
    private readonly string[] _args;
    private readonly CancellationTokenSource _cts            = new();
    private readonly IHost                    _host;
    private readonly ILogger<CliService>      _logger;
    private readonly ParseResult              _parseResult;

    private bool _disposed;

    /// <summary>
    /// Initializes and configures the overarching <see cref="IHost"/> as well as the
    /// <see cref="System.CommandLine"/> pipeline.
    /// </summary>
    /// <param name="args">Raw command-line arguments.</param>
    /// <exception cref="ArgumentNullException">Thrown when <paramref name="args"/> is null.</exception>
    public CliService(string[] args)
    {
        _args = args ?? throw new ArgumentNullException(nameof(args));

        // Build the generic host that will live for the lifetime of the CLI execution.
        _host = Host.CreateDefaultBuilder(args)
                    .ConfigureAppConfiguration(static (_, config) =>
                    {
                        // Additional configuration providers (e.g., secrets, consul) can be added here.
                        config.AddEnvironmentVariables(prefix: "UTILITYCHAIN_");
                    })
                    .ConfigureLogging(static (_, logging) =>
                    {
                        logging.ClearProviders();
                        logging.AddSimpleConsole(options =>
                        {
                            options.SingleLine = true;
                            options.TimestampFormat = "[HH:mm:ss] ";
                        });
                    })
                    .ConfigureServices(ConfigureServices)
                    .Build();

        _logger = _host.Services.GetRequiredService<ILogger<CliService>>();

        // Build the System.CommandLine parse result.
        var builder = BuildCommandLineBuilder(_host.Services)
                     .UseDefaults()
                     .UseExceptionHandler(OnUnhandledException);

        var parser = builder.Build();
        _parseResult = parser.Parse(_args);
    }

    /// <summary>
    /// Executes the CLI and returns the resulting exit code.
    /// </summary>
    public async Task<int> RunAsync()
    {
        PrintBanner();

        Console.CancelKeyPress += HandleConsoleCancel;

        try
        {
            _logger.LogInformation("Starting UtilityChain CLI with command: {CommandLine}", string.Join(' ', _args));

            var exitCode = await _parseResult.InvokeAsync(_cts.Token);

            _logger.LogInformation("Exiting UtilityChain CLI with code {ExitCode}", exitCode);
            return exitCode;
        }
        // Catch is intentionally broad— business logic errors should be handled by the
        // command handler itself, and _UseExceptionHandler in the pipeline surfaces those nicely.
        catch (Exception ex)
        {
            _logger.LogCritical(ex, "Unhandled exception reached the top-level.");
            return 1;
        }
    }

    // --------------------------------------------------------------------------------------------
    // Dependency-Injection Registration
    // --------------------------------------------------------------------------------------------

    private static void ConfigureServices(HostBuilderContext ctx, IServiceCollection services)
    {
        // Register core services common to all CLI modules.
        services.AddSingleton<ITelemetrySink, ConsoleTelemetrySink>();

        // Discover and register ICliModule implementations across loaded assemblies.
        foreach (var moduleType in AppDomain.CurrentDomain
                                            .GetAssemblies()
                                            .SelectMany(a =>
                                            {
                                                // We skip dynamically-generated assemblies that can throw.
                                                try      { return a.GetTypes(); }
                                                catch    { return Array.Empty<Type>(); }
                                            })
                                            .Where(t => t is { IsClass: true, IsAbstract: false } &&
                                                        typeof(ICliModule).IsAssignableFrom(t)))
        {
            services.AddSingleton(typeof(ICliModule), moduleType);
        }
    }

    // --------------------------------------------------------------------------------------------
    // Command-line Configuration
    // --------------------------------------------------------------------------------------------

    private static CommandLineBuilder BuildCommandLineBuilder(IServiceProvider services)
    {
        var root = new RootCommand("UtilityChain Core Suite – All-in-one blockchain utility toolkit");

        // Wire-in dynamic modules.
        IEnumerable<ICliModule> modules = services.GetServices<ICliModule>();
        foreach (var module in modules)
        {
            var cmd = module.BuildCommand();
            root.AddCommand(cmd);
        }

        // Built-in command to list all loaded modules
        root.AddCommand(new Command("modules", "List all loaded CLI modules")
        {
            Handler = CommandHandler.Create(() =>
            {
                Console.WriteLine("Loaded CLI modules:");
                foreach (var m in modules)
                {
                    Console.WriteLine($" • {m.GetType().Name}");
                }
            })
        });

        return new CommandLineBuilder(root);
    }

    // --------------------------------------------------------------------------------------------
    // Unhandled Exception Pipeline
    // --------------------------------------------------------------------------------------------

    private void OnUnhandledException(Exception ex, InvocationContext ctx)
    {
        _logger.LogError(ex, "A fatal error occurred.");
        ctx.ExitCode = 1;
    }

    // --------------------------------------------------------------------------------------------
    // Console Cancellation Handler
    // --------------------------------------------------------------------------------------------

    private void HandleConsoleCancel(object? sender, ConsoleCancelEventArgs e)
    {
        _logger.LogWarning("CTRL-C detected. Attempting graceful shutdown…");
        _cts.Cancel();
        e.Cancel = true; // Suppress default abrupt termination.
    }

    // --------------------------------------------------------------------------------------------
    // Fancy ASCII Art Banner (because developers love eye-candy)
    // --------------------------------------------------------------------------------------------

    private void PrintBanner()
    {
        const string banner =
            """
             _   _ _   _ _   _ _ _ _   _ _______   _____ _   _  _____ 
            | | | | | | | \ | | | \ \ / /  ___\ \ / / _ \ | | |/  ___|
            | |_| | | | |  \| | | |\ V /| |__  \ V / /_\ \| | | \ `--. 
            |  _  | | | | . ` | | | \ / |  __| /   |  _  || | |  `--. \
            | | | | |_| | |\  | | | | | | |___/ /^\ \ | | || |_| /\__/ /
            \_| |_/\___/\_| \_/_|_| |_| \____/\/   \_\_| |_/\___/\____/ 
            """;

        var version = typeof(CliService).Assembly.GetName().Version?.ToString() ?? "dev";
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine(banner);
        Console.ResetColor();
        Console.WriteLine($"UtilityChain Core Suite v{version}");
        Console.WriteLine();
    }

    // --------------------------------------------------------------------------------------------
    // IDisposable / IAsyncDisposable Implementation
    // --------------------------------------------------------------------------------------------

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;

        _disposed = true;

        try
        {
            _cts.Cancel();
            _cts.Dispose();

            await _host.StopAsync(TimeSpan.FromSeconds(10));
            _host.Dispose();
        }
        catch (Exception ex)
        {
            // Avoid throwing from a Dispose(); just log.
            _logger.LogError(ex, "Error during disposal of CliService.");
        }
    }
}

// =================================================================================================
// Supporting Contracts
// =================================================================================================

/// <summary>
/// Contract that feature assemblies implement to plug-in new commands to the CLI.  A module can
/// contribute arbitrarily nested sub-commands, options, and argument validations.
/// </summary>
public interface ICliModule
{
    /// <summary>
    /// Builds and returns the root command for this module.
    /// </summary>
    Command BuildCommand();
}

/// <summary>
/// Simplified telemetry sink for demonstration purposes.  In a production node this could write
/// to Application Insights, Prometheus, or another observability backend.
/// </summary>
public interface ITelemetrySink
{
    void TrackEvent(string eventName, IReadOnlyDictionary<string, object?>? properties = null);
    void TrackError(Exception ex, IReadOnlyDictionary<string, object?>? properties = null);
}

/// <summary>
/// Default no-frills telemetry sink that writes structured data to the console.
/// </summary>
public sealed class ConsoleTelemetrySink : ITelemetrySink
{
    public void TrackEvent(string eventName, IReadOnlyDictionary<string, object?>? properties = null)
    {
        Console.WriteLine($"[Telemetry] Event: {eventName} {Serialize(properties)}");
    }

    public void TrackError(Exception ex, IReadOnlyDictionary<string, object?>? properties = null)
    {
        Console.Error.WriteLine($"[Telemetry] Error: {ex.GetType().Name}: {ex.Message} {Serialize(properties)}");
    }

    private static string Serialize(IReadOnlyDictionary<string, object?>? dict)
        => dict is null ? string.Empty
                        : string.Join(", ", dict.Select(kvp => $"{kvp.Key}={kvp.Value ?? "<null>"}"));
}
```