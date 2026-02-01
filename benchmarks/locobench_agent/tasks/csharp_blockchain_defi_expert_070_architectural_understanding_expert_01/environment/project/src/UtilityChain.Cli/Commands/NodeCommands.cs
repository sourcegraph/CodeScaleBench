using System;
using System.CommandLine;
using System.CommandLine.Invocation;
using System.IO;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Cli.Commands
{
    /// <summary>
    /// Provides the top-level <c>node</c> command and its sub-commands for
    /// interacting with the local UtilityChain node daemon.
    /// </summary>
    internal static class NodeCommands
    {
        /// <summary>
        /// Adds the <c>node</c> command hierarchy to the supplied root command.
        /// </summary>
        /// <param name="root">The application root command.</param>
        /// <param name="services">The application service provider.</param>
        /// <exception cref="ArgumentNullException"/>
        public static void Register(Command root, IServiceProvider services)
        {
            if (root == null) throw new ArgumentNullException(nameof(root));
            if (services == null) throw new ArgumentNullException(nameof(services));

            // `node` root
            var node = new Command("node", "Operate a UtilityChain node instance.");

            node.AddCommand(BuildStart(services));
            node.AddCommand(BuildStop(services));
            node.AddCommand(BuildStatus(services));
            node.AddCommand(BuildConfigure(services));

            root.AddCommand(node);
        }

        #region start

        private static Command BuildStart(IServiceProvider services)
        {
            var cmd = new Command("start", "Start the node daemon.")
            {
                // Optional configuration file
                new Option<FileInfo?>(
                    aliases: new[] { "-c", "--config-file" },
                    description: "Path to a JSON/YAML file that overrides default configuration."),

                // Node role enum
                new Option<string>(
                    aliases: new[] { "-r", "--role" },
                    getDefaultValue: () => "validator",
                    description: "Node role: validator | full | archive"),

                // Network identifier
                new Option<string>(
                    aliases: new[] { "-n", "--network" },
                    getDefaultValue: () => "local",
                    description: "Network to join: mainnet | testnet | local"),

                // Force flag
                new Option<bool>(
                    aliases: new[] { "-f", "--force" },
                    description: "Start even if another instance claims the same data directory.")
            };

            cmd.SetHandler(async (FileInfo? cfg, string role, string network, bool force, InvocationContext ctx) =>
            {
                var log = services.GetRequiredService<ILoggerFactory>()
                                  .CreateLogger("cli.node.start");
                var lifecycle = services.GetRequiredService<INodeLifecycleManager>();
                var token = ctx.GetCancellationToken();

                try
                {
                    var opts = new NodeOptions(RoleFrom(role), network, cfg?.FullName, force);

                    log.LogInformation("Starting node — Network={Network}, Role={Role}, Config={Cfg}, Force={Force}",
                        opts.Network, opts.Role, opts.ConfigurationPath ?? "<default>", opts.Force);

                    await lifecycle.StartAsync(opts, token).ConfigureAwait(false);
                    log.LogInformation("Node start completed successfully.");
                    ctx.ExitCode = 0;
                }
                catch (Exception ex)
                {
                    log.LogError(ex, "Node failed to start.");
                    ctx.ExitCode = 1;
                }
            },
            cmd.Options[0], // cfg
            cmd.Options[1], // role
            cmd.Options[2], // network
            cmd.Options[3]  // force
            );

            return cmd;
        }

        #endregion

        #region stop

        private static Command BuildStop(IServiceProvider services)
        {
            var cmd = new Command("stop", "Stop the node daemon.")
            {
                new Option<bool>(
                    aliases: new[] { "-g", "--graceful" },
                    getDefaultValue: () => true,
                    description: "Perform graceful shutdown (default).")
            };

            cmd.SetHandler(async (bool graceful, InvocationContext ctx) =>
            {
                var log = services.GetRequiredService<ILoggerFactory>()
                                  .CreateLogger("cli.node.stop");
                var lifecycle = services.GetRequiredService<INodeLifecycleManager>();
                var token = ctx.GetCancellationToken();

                try
                {
                    log.LogInformation("Stopping node. Graceful={Graceful}", graceful);
                    await lifecycle.StopAsync(token).ConfigureAwait(false);
                    log.LogInformation("Node stopped.");
                    ctx.ExitCode = 0;
                }
                catch (Exception ex)
                {
                    log.LogError(ex, "Node stop failed.");
                    ctx.ExitCode = 1;
                }
            }, cmd.Options[0]);

            return cmd;
        }

        #endregion

        #region status

        private static Command BuildStatus(IServiceProvider services)
        {
            var cmd = new Command("status", "Show current node status.")
            {
                new Option<bool>(
                    aliases: new[] { "-j", "--json" },
                    description: "Output response as JSON.")
            };

            cmd.SetHandler(async (bool json, InvocationContext ctx) =>
            {
                var log = services.GetRequiredService<ILoggerFactory>()
                                  .CreateLogger("cli.node.status");
                var lifecycle = services.GetRequiredService<INodeLifecycleManager>();
                var token = ctx.GetCancellationToken();

                try
                {
                    var status = await lifecycle.GetStatusAsync(token).ConfigureAwait(false);

                    if (json)
                    {
                        Console.WriteLine(JsonSerializer.Serialize(
                            status,
                            new JsonSerializerOptions { WriteIndented = true }));
                    }
                    else
                    {
                        Console.WriteLine($"State   : {status.State}");
                        Console.WriteLine($"Uptime  : {status.Uptime}");
                        Console.WriteLine($"Height  : {status.BlockHeight}");
                        Console.WriteLine($"Peers   : {status.ConnectedPeers}");
                        Console.WriteLine($"Role    : {status.Role}");
                    }

                    ctx.ExitCode = 0;
                }
                catch (Exception ex)
                {
                    log.LogError(ex, "Failed to fetch status.");
                    ctx.ExitCode = 1;
                }
            }, cmd.Options[0]);

            return cmd;
        }

        #endregion

        #region configure

        private static Command BuildConfigure(IServiceProvider services)
        {
            var cmd = new Command("configure", "Update node runtime configuration.")
            {
                new Argument<string>("key", "Configuration key (e.g. consensus.blockInterval)"),
                new Argument<string>("value", "New value as string (will be type-coerced)"),
                new Option<bool>(
                    aliases: new[] { "-a", "--apply" },
                    description: "Apply changes immediately (may restart node).")
            };

            cmd.SetHandler(async (string key, string value, bool apply, InvocationContext ctx) =>
            {
                var log = services.GetRequiredService<ILoggerFactory>()
                                  .CreateLogger("cli.node.configure");
                var lifecycle = services.GetRequiredService<INodeLifecycleManager>();
                var token = ctx.GetCancellationToken();

                try
                {
                    log.LogInformation("Mutating configuration '{Key}' = '{Value}' (Apply={Apply})", key, value, apply);

                    var mutation = new NodeConfigurationMutation(key, value, apply);
                    await lifecycle.UpdateConfigAsync(mutation, token).ConfigureAwait(false);

                    Console.WriteLine($"Configuration '{key}' successfully updated.");
                    ctx.ExitCode = 0;
                }
                catch (Exception ex)
                {
                    log.LogError(ex, "Configuration update failed.");
                    ctx.ExitCode = 1;
                }
            },
            cmd.Arguments[0],  // key
            cmd.Arguments[1],  // value
            cmd.Options[0]);   // apply

            return cmd;
        }

        #endregion

        #region helpers

        private static NodeRole RoleFrom(string raw)
        {
            if (Enum.TryParse<NodeRole>(raw, true, out var role))
                return role;

            throw new CommandException($"Invalid node role '{raw}'. Allowed: validator | full | archive");
        }

        #endregion
    }

    #region supporting abstractions (stripped-down stubs)

    // NOTE: These stubs keep the file self-contained. In production they
    // would be sourced from UtilityChain.Core.* packages.

    internal enum NodeRole { Validator, Full, Archive }

    internal sealed record NodeOptions(
        NodeRole Role,
        string Network,
        string? ConfigurationPath,
        bool Force);

    internal sealed record NodeStatus(
        string State,
        TimeSpan Uptime,
        long BlockHeight,
        int ConnectedPeers,
        NodeRole Role);

    internal sealed record NodeConfigurationMutation(
        string Key,
        string Value,
        bool ApplyImmediately);

    internal interface INodeLifecycleManager
    {
        Task StartAsync(NodeOptions options, CancellationToken ct);
        Task StopAsync(CancellationToken ct);
        Task<NodeStatus> GetStatusAsync(CancellationToken ct);
        Task UpdateConfigAsync(NodeConfigurationMutation mutation, CancellationToken ct);
    }

    /// <summary>
    /// Command-level error that results in a non-zero exit code.
    /// </summary>
    internal sealed class CommandException : Exception
    {
        public CommandException(string message) : base(message) { }
    }

    #endregion
}