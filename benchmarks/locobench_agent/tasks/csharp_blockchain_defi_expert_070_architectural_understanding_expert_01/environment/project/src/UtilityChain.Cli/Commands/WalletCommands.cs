```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Cli/Commands/WalletCommands.cs
// Description: Provides `wallet` root command and sub-commands for interacting with
//              the on-chain wallet module from the command-line.
//
// ──────────────────────────────────────────────────────────────────────────────
// Copyright © UtilityChain Contributors
// SPDX-License-Identifier: Apache-2.0
// ──────────────────────────────────────────────────────────────────────────────

using System.CommandLine;
using System.CommandLine.Invocation;
using System.Globalization;
using Microsoft.Extensions.Logging;
using UtilityChain.Core.Common;
using UtilityChain.Core.Wallets;
using UtilityChain.Core.Wallets.Abstractions;

namespace UtilityChain.Cli.Commands;

/// <summary>
///     Declaratively builds the wallet sub-command hierarchy for <c>uc</c>
///     (UtilityChain CLI) and wires the commands to an <see cref="IWalletService"/>.
/// </summary>
internal static class WalletCommands
{
    /// <summary>
    ///     Builds the <c>wallet</c> root command and all its children.
    ///     The returned <see cref="Command"/> can be added directly to the root
    ///     System.CommandLine <see cref="Command"/>.
    /// </summary>
    /// <param name="walletService">
    ///     Concrete wallet service implementation resolved from the DI container.
    /// </param>
    /// <param name="logger">
    ///     Optional structured logger.
    /// </param>
    /// <returns>The fully configured wallet command tree.</returns>
    public static Command Build(IWalletService walletService, ILogger? logger = null)
    {
        ArgumentNullException.ThrowIfNull(walletService);

        var walletCmd = new Command("wallet", "Manage on-chain wallets and perform token operations.");

        // ‑-- create ───────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildCreateCommand(walletService, logger));

        // ‑-- import ───────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildImportCommand(walletService, logger));

        // ‑-- list ─────────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildListCommand(walletService));

        // ‑-- balance ──────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildBalanceCommand(walletService));

        // ‑-- send ─────────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildSendCommand(walletService, logger));

        // ‑-- stake ────────────────────────────────────────────────────────────
        walletCmd.AddCommand(BuildStakeCommand(walletService, logger));

        return walletCmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // create
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildCreateCommand(IWalletService walletService, ILogger? logger)
    {
        var nameOpt       = new Option<string>("--name",    "Logical wallet name.") { IsRequired = true };
        var passOpt       = new Option<string>("--pass",    "Passphrase (leave blank to prompt interactively).") { IsRequired = false };
        var strengthOpt   = new Option<int>("--strength",   () => 256, "Mnemonic strength (128, 192, 256).");

        var cmd = new Command("create", "Create a fresh hierarchical deterministic wallet.")
        {
            nameOpt,
            passOpt,
            strengthOpt
        };

        cmd.SetHandler(async (InvocationContext ctx) =>
        {
            var name      = ctx.ParseResult.GetValueForOption(nameOpt)!;
            var pass      = await ResolvePassphraseAsync(ctx, passOpt);
            var strength  = ctx.ParseResult.GetValueForOption(strengthOpt);

            if (strength is not (128 or 192 or 256))
            {
                ctx.Console.Error.WriteLine("Mnemonic strength must be 128, 192, or 256 bits.");
                ctx.ExitCode = -1;
                return;
            }

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ctx.GetCancellationToken());

            try
            {
                var wallet = await walletService.CreateAsync(name, pass, strength, cts.Token)
                                                .ConfigureAwait(false);

                ctx.Console.WriteLine($"[+] Wallet '{wallet.Name}' generated ({wallet.Address}).");
                ctx.Console.WriteLine($"    Mnemonic: {wallet.Mnemonic}");
                ctx.ExitCode = 0;
            }
            catch (WalletAlreadyExistsException ex)
            {
                logger?.LogWarning(ex, "Wallet '{Name}' already exists.", name);
                ctx.Console.Error.WriteLine($"[!] Wallet '{name}' already exists.");
                ctx.ExitCode = -1;
            }
            catch (Exception ex)
            {
                logger?.LogError(ex, "Failed to create wallet '{Name}'.", name);
                ctx.Console.Error.WriteLine($"[✗] Failed to create wallet: {ex.Message}");
                ctx.ExitCode = -1;
            }
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // import
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildImportCommand(IWalletService walletService, ILogger? logger)
    {
        var nameOpt      = new Option<string>("--name", "Logical wallet name.") { IsRequired = true };
        var passOpt      = new Option<string>("--pass", "Passphrase (leave blank to prompt interactively).");
        var mnemonicOpt  = new Option<string>("--mnemonic", "BIP-39 mnemonic phrase (if importing from words).");
        var privKeyOpt   = new Option<string>("--private-key", "Raw hexadecimal private key (if importing direct).");

        var cmd = new Command("import", "Import an existing wallet from mnemonic or private key.")
        {
            nameOpt,
            passOpt,
            mnemonicOpt,
            privKeyOpt
        };

        cmd.SetHandler(async (InvocationContext ctx) =>
        {
            var name     = ctx.ParseResult.GetValueForOption(nameOpt)!;
            var pass     = await ResolvePassphraseAsync(ctx, passOpt);
            var mnemonic = ctx.ParseResult.GetValueForOption(mnemonicOpt);
            var privKey  = ctx.ParseResult.GetValueForOption(privKeyOpt);

            if (string.IsNullOrWhiteSpace(mnemonic) && string.IsNullOrWhiteSpace(privKey))
            {
                ctx.Console.Error.WriteLine("[!] Either --mnemonic or --private-key must be provided.");
                ctx.ExitCode = -1;
                return;
            }

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ctx.GetCancellationToken());

            try
            {
                var wallet = await walletService.ImportAsync(name, pass, mnemonic, privKey, cts.Token)
                                                .ConfigureAwait(false);

                ctx.Console.WriteLine($"[+] Wallet '{wallet.Name}' imported ({wallet.Address}).");
                ctx.ExitCode = 0;
            }
            catch (WalletAlreadyExistsException ex)
            {
                logger?.LogWarning(ex, "Wallet '{Name}' already exists.", name);
                ctx.Console.Error.WriteLine($"[!] Wallet '{name}' already exists.");
                ctx.ExitCode = -1;
            }
            catch (FormatException ex)
            {
                logger?.LogWarning(ex, "Invalid key format during import.");
                ctx.Console.Error.WriteLine($"[✗] Invalid key format: {ex.Message}");
                ctx.ExitCode = -1;
            }
            catch (Exception ex)
            {
                logger?.LogError(ex, "Failed to import wallet '{Name}'.", name);
                ctx.Console.Error.WriteLine($"[✗] Failed to import wallet: {ex.Message}");
                ctx.ExitCode = -1;
            }
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // list
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildListCommand(IWalletService walletService)
    {
        var cmd = new Command("list", "List locally-managed wallets.");

        cmd.SetHandler((InvocationContext ctx) =>
        {
            var rows = walletService.GetAll()
                                    .Select(w => (w.Name, w.Address, w.CreatedUtc))
                                    .ToArray();

            if (rows.Length == 0)
            {
                ctx.Console.WriteLine("No wallets have been created or imported yet.");
                ctx.ExitCode = 0;
                return;
            }

            ctx.Console.WriteLine($"{"Name",-16} {"Address",-45} {"Created (UTC)"}");
            ctx.Console.WriteLine(new string('─', 80));

            foreach (var (name, address, created) in rows)
            {
                ctx.Console.WriteLine($"{name,-16} {address,-45} {created:u}");
            }

            ctx.ExitCode = 0;
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // balance
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildBalanceCommand(IWalletService walletService)
    {
        var addrOpt = new Option<string>("--address", description: "Wallet address (leave blank to use default).")
        {
            IsRequired = false
        };

        var assetOpt = new Option<string>("--asset", () => "UCOIN", "Asset symbol (default: UCOIN).");

        var cmd = new Command("balance", "Query the on-chain balance of a wallet.")
        {
            addrOpt,
            assetOpt
        };

        cmd.SetHandler(async (InvocationContext ctx) =>
        {
            var address = ctx.ParseResult.GetValueForOption(addrOpt);
            var asset   = ctx.ParseResult.GetValueForOption(assetOpt)!;

            try
            {
                address ??= walletService.GetDefault()?.Address
                    ?? throw new InvalidOperationException("No wallet address provided and no default wallet configured.");

                var balance = await walletService.GetBalanceAsync(address, asset, ctx.GetCancellationToken())
                                                 .ConfigureAwait(false);

                ctx.Console.WriteLine($"{balance.ToString("N", CultureInfo.InvariantCulture)} {asset}");
                ctx.ExitCode = 0;
            }
            catch (Exception ex)
            {
                ctx.Console.Error.WriteLine($"[✗] Unable to fetch balance: {ex.Message}");
                ctx.ExitCode = -1;
            }
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // send
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildSendCommand(IWalletService walletService, ILogger? logger)
    {
        var fromOpt   = new Option<string>("--from", "Sender wallet name or address.") { IsRequired = true };
        var toOpt     = new Option<string>("--to", "Recipient address.") { IsRequired = true };
        var amountOpt = new Option<decimal>("--amount", "Amount to transfer.") { IsRequired = true };
        var assetOpt  = new Option<string>("--asset", () => "UCOIN", "Asset symbol.");
        var feeOpt    = new Option<decimal?>("--fee", "Optional transaction fee override.");

        var cmd = new Command("send", "Send tokens from one wallet to another.")
        {
            fromOpt, toOpt, amountOpt, assetOpt, feeOpt
        };

        cmd.SetHandler(async (InvocationContext ctx) =>
        {
            var from    = ctx.ParseResult.GetValueForOption(fromOpt)!;
            var to      = ctx.ParseResult.GetValueForOption(toOpt)!;
            var amount  = ctx.ParseResult.GetValueForOption(amountOpt);
            var asset   = ctx.ParseResult.GetValueForOption(assetOpt)!;
            var fee     = ctx.ParseResult.GetValueForOption(feeOpt);

            if (amount <= 0)
            {
                ctx.Console.Error.WriteLine("[!] Amount must be greater than zero.");
                ctx.ExitCode = -1;
                return;
            }

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ctx.GetCancellationToken());

            try
            {
                var receipt = await walletService
                    .SendAsync(from, to, amount, asset, fee, cts.Token)
                    .ConfigureAwait(false);

                ctx.Console.WriteLine($"[✓] Tx accepted: {receipt.TransactionHash}");
                ctx.ExitCode = 0;
            }
            catch (InsufficientBalanceException)
            {
                ctx.Console.Error.WriteLine("[✗] Insufficient balance for this transaction.");
                ctx.ExitCode = -1;
            }
            catch (Exception ex)
            {
                logger?.LogError(ex, "Failed to send funds.");
                ctx.Console.Error.WriteLine($"[✗] Failed to send funds: {ex.Message}");
                ctx.ExitCode = -1;
            }
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // stake
    // ──────────────────────────────────────────────────────────────────────────
    private static Command BuildStakeCommand(IWalletService walletService, ILogger? logger)
    {
        var fromOpt     = new Option<string>("--from", "Wallet name or address to stake from.") { IsRequired = true };
        var amountOpt   = new Option<decimal>("--amount", "Amount to stake.") { IsRequired = true };
        var validatorOpt= new Option<string>("--validator", "Validator node ID (leave blank for self-stake).");

        var cmd = new Command("stake", "Lock tokens for staking rewards and validator selection.")
        {
            fromOpt, amountOpt, validatorOpt
        };

        cmd.SetHandler(async (InvocationContext ctx) =>
        {
            var from      = ctx.ParseResult.GetValueForOption(fromOpt)!;
            var amount    = ctx.ParseResult.GetValueForOption(amountOpt);
            var validator = ctx.ParseResult.GetValueForOption(validatorOpt);

            if (amount <= 0)
            {
                ctx.Console.Error.WriteLine("[!] Amount must be greater than zero.");
                ctx.ExitCode = -1;
                return;
            }

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ctx.GetCancellationToken());

            try
            {
                var receipt = await walletService
                    .StakeAsync(from, amount, validator, cts.Token)
                    .ConfigureAwait(false);

                ctx.Console.WriteLine($"[✓] Stake successful. Tx: {receipt.TransactionHash}");
                ctx.ExitCode = 0;
            }
            catch (Exception ex)
            {
                logger?.LogError(ex, "Stake failed.");
                ctx.Console.Error.WriteLine($"[✗] Stake failed: {ex.Message}");
                ctx.ExitCode = -1;
            }
        });

        return cmd;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Helpers
    // ──────────────────────────────────────────────────────────────────────────
    private static async Task<string?> ResolvePassphraseAsync(
        InvocationContext ctx,
        Option<string> passOpt)
    {
        var pass = ctx.ParseResult.GetValueForOption(passOpt);

        if (!string.IsNullOrWhiteSpace(pass))
            return pass;

        // Fallback to interactive prompt; console is in raw mode so masking is effective.
        ctx.Console.Out.Write("Passphrase: ");
        pass = await Task.Run(() => ReadPassword(ctx.Console), ctx.GetCancellationToken());
        ctx.Console.Out.WriteLine();

        return pass;
    }

    /// <summary>
    ///     Reads sensitive input from the console without echoing characters.
    /// </summary>
    private static string ReadPassword(IConsole console)
    {
        var pwd = new Stack<char>();

        while (true)
        {
            var keyInfo = console.ReadKey(intercept: true);
            if (keyInfo.Key is ConsoleKey.Enter)
            {
                break;
            }

            if (keyInfo.Key is ConsoleKey.Backspace && pwd.Count > 0)
            {
                pwd.Pop();
                console.Out.Write("\b \b");
            }
            else if (!char.IsControl(keyInfo.KeyChar))
            {
                pwd.Push(keyInfo.KeyChar);
                console.Out.Write('*');
            }
        }

        return new string(pwd.Reverse().ToArray());
    }
}
```