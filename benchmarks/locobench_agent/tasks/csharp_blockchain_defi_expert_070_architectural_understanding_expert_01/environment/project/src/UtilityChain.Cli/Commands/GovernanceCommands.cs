```csharp
// ---------------------------------------------------------------------------------------------------------------------
// File: UtilityChainCoreSuite/src/UtilityChain.Cli/Commands/GovernanceCommands.cs
// Description: CLI commands for interacting with the on-chain governance module.
// ---------------------------------------------------------------------------------------------------------------------

using System;
using System.CommandLine;
using System.CommandLine.NamingConventionBinder;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using UtilityChain.Abstractions.Governance;   // IGovernanceService, ProposalType, VoteChoice, etc.
using UtilityChain.Common;                    // IConsoleWriter, Result<T>
using UtilityChain.Domain.Governance.Models;  // Proposal, VoteReceipt

namespace UtilityChain.Cli.Commands;

/// <summary>
///     Registers Governance-related sub-commands.
/// </summary>
public static class GovernanceCommands
{
    /// <summary>
    ///     Builds the <c>governance</c> root command and all its descendants.
    /// </summary>
    /// <param name="services">Application-level service provider.</param>
    /// <returns>A composed <see cref="Command" /> tree.</returns>
    public static Command Build(IServiceProvider services)
    {
        if (services == null) throw new ArgumentNullException(nameof(services));

        var console            = services.GetRequiredService<IConsoleWriter>();
        var governanceService  = services.GetRequiredService<IGovernanceService>();

        var governanceCommand = new Command(
            name: "governance",
            description: "Interact with the on-chain governance subsystem.")
        {
            BuildCreateProposal(console, governanceService),
            BuildListProposals(console, governanceService),
            BuildVote(console, governanceService),
            BuildTally(console, governanceService)
        };

        governanceCommand.SetHandler(
            () => console.Info("Use --help to see available governance commands."));

        return governanceCommand;
    }

    // -------------------------------------------------------------------------------------------------------------
    // Sub-Command: create-proposal
    // -------------------------------------------------------------------------------------------------------------
    private static Command BuildCreateProposal(
        IConsoleWriter console,
        IGovernanceService governance)
    {
        var typeOpt = new Option<ProposalType>(
            aliases: new[] { "--type", "-t" },
            description: "Type of proposal (e.g., Treasury, Parameter, Text).")
        { IsRequired = true };

        var titleArg = new Argument<string>(
            name: "title",
            description: "Concise, human-readable title for the proposal.");

        var fileOpt = new Option<FileInfo>(
            aliases: new[] { "--file", "-f" },
            description: "Path to a markdown file containing the proposal body.");

        var command = new Command(
            name: "create-proposal",
            description: "Submit a proposal to on-chain governance.")
        {
            typeOpt,
            titleArg,
            fileOpt
        };

        command.AddAlias("new");

        command.Handler = CommandHandler.Create<ProposalType, string, FileInfo, CancellationToken>(
            async (type, title, file, ct) =>
            {
                try
                {
                    var body = file != null
                        ? await File.ReadAllTextAsync(file.FullName, ct).ConfigureAwait(false)
                        : string.Empty;

                    var result = await governance
                        .CreateProposalAsync(type, title, body, ct)
                        .ConfigureAwait(false);

                    if (result.IsSuccess)
                        console.Success($"Proposal {result.Value.Id} created ✓");
                    else
                        console.Error(result.ErrorMessage);
                }
                catch (Exception ex)
                {
                    console.Fatal($"Failed to create proposal: {ex.Message}", ex);
                }
            });

        return command;
    }

    // -------------------------------------------------------------------------------------------------------------
    // Sub-Command: list-proposals
    // -------------------------------------------------------------------------------------------------------------
    private static Command BuildListProposals(
        IConsoleWriter console,
        IGovernanceService governance)
    {
        var stateOpt = new Option<GovernanceState?>(
            aliases: new[] { "--state", "-s" },
            description: "Filter proposals by current state (Draft, Voting, Queued, Executed, Rejected).");

        var command = new Command(
            name: "list-proposals",
            description: "Display existing proposals with optional filtering.")
        {
            stateOpt
        };

        command.AddAlias("ls");

        command.Handler = CommandHandler.Create<GovernanceState?, CancellationToken>(
            async (state, ct) =>
            {
                try
                {
                    var filter = new ProposalQuery { State = state };
                    var proposals = await governance
                        .QueryProposalsAsync(filter, ct)
                        .ConfigureAwait(false);

                    if (proposals.Count == 0)
                    {
                        console.Info("No proposals found.");
                        return;
                    }

                    foreach (var p in proposals)
                    {
                        console.WriteLine(
                            $"[{p.State,-8}] #{p.Id,-4}  {p.Type,-10}  " +
                            $"{p.Title} (Created {p.CreatedAt:yyyy-MM-dd})");
                    }
                }
                catch (Exception ex)
                {
                    console.Fatal($"Unable to fetch proposals: {ex.Message}", ex);
                }
            });

        return command;
    }

    // -------------------------------------------------------------------------------------------------------------
    // Sub-Command: vote
    // -------------------------------------------------------------------------------------------------------------
    private static Command BuildVote(
        IConsoleWriter console,
        IGovernanceService governance)
    {
        var proposalIdArg = new Argument<ulong>(
            name: "proposal-id",
            description: "Unique identifier of the proposal to vote on.");

        var choiceOpt = new Option<VoteChoice>(
            aliases: new[] { "--choice", "-c" },
            description: "Your voting choice (Yes, No, Abstain).")
        { IsRequired = true };

        var weightOpt = new Option<decimal>(
            aliases: new[] { "--weight", "-w" },
            description: "Amount of voting power to commit. Omit for full balance.",
            getDefaultValue: () => 0M);

        var command = new Command(
            name: "vote",
            description: "Cast a vote for a given proposal.")
        {
            proposalIdArg,
            choiceOpt,
            weightOpt
        };

        command.Handler = CommandHandler.Create<ulong, VoteChoice, decimal, CancellationToken>(
            async (proposalId, choice, weight, ct) =>
            {
                try
                {
                    Result<VoteReceipt> result = await governance
                        .VoteAsync(proposalId, choice, weight, ct)
                        .ConfigureAwait(false);

                    if (result.IsSuccess)
                    {
                        console.Success(
                            $"Vote recorded ✓   Proposal #{proposalId} " +
                            $"Choice: {choice} Weight: {result.Value.Weight:N2}");
                    }
                    else
                    {
                        console.Error(result.ErrorMessage);
                    }
                }
                catch (Exception ex)
                {
                    console.Fatal($"Voting failed: {ex.Message}", ex);
                }
            });

        return command;
    }

    // -------------------------------------------------------------------------------------------------------------
    // Sub-Command: tally
    // -------------------------------------------------------------------------------------------------------------
    private static Command BuildTally(
        IConsoleWriter console,
        IGovernanceService governance)
    {
        var proposalIdArg = new Argument<ulong>(
            name: "proposal-id",
            description: "Identifier of the proposal to tally.");

        var command = new Command(
            name: "tally",
            description: "Display live or final tally results for a proposal.")
        {
            proposalIdArg
        };

        command.Handler = CommandHandler.Create<ulong, CancellationToken>(
            async (proposalId, ct) =>
            {
                try
                {
                    var tally = await governance
                        .GetTallyAsync(proposalId, ct)
                        .ConfigureAwait(false);

                    if (!tally.IsSuccess)
                    {
                        console.Error(tally.ErrorMessage);
                        return;
                    }

                    var t = tally.Value;
                    console.WriteLine($"Tally for Proposal #{proposalId}");
                    console.WriteLine($"Yes:     {t.YesWeight:N2}");
                    console.WriteLine($"No:      {t.NoWeight:N2}");
                    console.WriteLine($"Abstain: {t.AbstainWeight:N2}");
                    console.WriteLine($"Quorum:  {t.Quorum:N2} ({t.Status})");
                }
                catch (Exception ex)
                {
                    console.Fatal($"Unable to fetch tally: {ex.Message}", ex);
                }
            });

        return command;
    }
}
```