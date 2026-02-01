```markdown
# UtilityChain Core Suite  
## Guide 03 – Wallet SDK & Desktop Wallet Integration  
*(Applies to v1.0+ / .NET 8)*

The UtilityChain Wallet SDK is a **zero-configuration**, in-process client that gives .NET
applications and plug-ins secure access to key-management, balance look-ups, and
transaction-building features exposed by the UtilityChain Core runtime.  
This guide demonstrates common wallet operations using **C# 12**.  
All snippets **compile out-of-the-box** when UtilityChain.Core is referenced.

---

## 1. Package Reference

```bash
dotnet add package UtilityChain.Core --version 1.*
```

If you are working inside the top-level `UtilityChain` solution you can reference the
project directly:

```xml
<ItemGroup>
  <ProjectReference Include="..\src\UtilityChain.Core\UtilityChain.Core.csproj" />
</ItemGroup>
```

---

## 2. Namespaces & Usings

```csharp
using System;
using System.Threading;
using System.Threading.Tasks;
using UtilityChain.Core.Wallet;
using UtilityChain.Core.Crypto;
using UtilityChain.Core.Transactions;
using UtilityChain.Core.Events;
```

---

## 3. Creating or Opening a Wallet

The wallet can run **in-memory**, **encrypted on-disk**, or be injected by the
hosted node (`UtilityChainNode`).  
Below is a quick example that covers *new wallet creation* and *encrypted import*.

```csharp
// Program.cs
public static async Task Main(string[] args)
{
    // Path where the wallet file will be stored.
    var walletPath = Environment.ExpandEnvironmentVariables(
        @"%APPDATA%\UtilityChain\wallet.dat");

    // Encryption password (never hard-code in production!)
    var securePassword = Environment.GetEnvironmentVariable("UC_WALLET_PWD")
                         ?? throw new InvalidOperationException(
                             "Environment variable UC_WALLET_PWD not set.");

    // Automatically create or open an encrypted wallet file.
    IWalletStore store = new FileWalletStore(walletPath, securePassword);

    // Wrap the store with a high-level wallet service.
    using var wallet = new WalletService(store);

    Console.WriteLine(
        $"Wallet ID: {wallet.Metadata.WalletId}\n" +
        $"Created : {wallet.Metadata.CreatedOn:O}");
}
```

> 💡 **Tip**  
> Password-based encryption uses `argon2id` for key derivation and `ChaCha20-Poly1305`
> for stream encryption. PBKDF configuration resides in *appsettings.json*.

---

## 4. Generating Accounts & Addresses

The UtilityChain wallet is **HD (Hierarchical Deterministic)** and follows the  
`ucip44` derivation scheme (`m / 44' / 6006' / account' / change / index`).

```csharp
// Generates the first account if it does not exist, or loads it otherwise.
HdAccount energyAccount = await wallet.GetOrCreateAccountAsync(
    label: "Energy Credits",
    symbol: "ECRT");

Console.WriteLine(
    $"Account #{energyAccount.Index} – {energyAccount.Label} ({energyAccount.Symbol})");

// Request a fresh external address for deposits.
BlockchainAddress depositAddress = energyAccount.DeriveAddress(AddressType.External);

Console.WriteLine($"Deposit Address: {depositAddress}");
```

---

## 5. Querying Balances

All balance look-ups are performed against the local **UTXO set** managed by the
utility-node’s consensus engine.

```csharp
// Returns confirmed + unconfirmed funds grouped by asset symbol.
BalanceSummary balance = await wallet.GetBalanceAsync(energyAccount);

Console.WriteLine(
    $"Confirmed : {balance.Confirmed} {energyAccount.Symbol}\n" +
    $"Pending   : {balance.Pending}   {energyAccount.Symbol}\n" +
    $"Total     : {balance.Total}     {energyAccount.Symbol}");
```

---

## 6. Building & Broadcasting Transactions

The `TransactionBuilder` hides signature aggregation, fee estimation, and
change-output generation. You only specify the *intent*.

```csharp
// Assume we want to send 25 ECRT to a DAO treasury address.
const decimal amountToSend = 25.0m;
const string treasury = "ucx1qtreasuryd35k4t0mk99cw6pp...";

var builder = wallet
    .NewTransaction()
    .From(energyAccount)           // source account
    .To(treasury, amountToSend)    // destination
    .WithFee(FeeStrategy.Medium)   // fee tier
    .When(DateTimeOffset.UtcNow)   // optional scheduled time (for L2 batching)
    .Build();                      // returns a signed Transaction object

// ⏩ Broadcast via the in-process node mem-pool.
BroadcastResult result = await wallet.BroadcastAsync(builder);

if (result.Success)
{
    Console.WriteLine($"Tx {result.TransactionId} accepted with fee {result.FeePaid} ECRT.");
}
else
{
    Console.WriteLine(
        $"Broadcast failed: {result.ErrorCode} – {result.Message}");
}
```

Error-handling helpers:

```csharp
wallet.TransactionRejected += (_, e) =>
{
    Console.Error.WriteLine(
        $"[REJECTED] {e.TransactionId} • Reason: {e.Reason}");
};
```

---

## 7. Subscribing to Wallet Events

The wallet emits domain events through `IEventBus` (Observer Pattern).  
You can subscribe to receive **new payment notifications**, **status changes**, or
**incoming token/NFT transfers**.

```csharp
private static void ConfigureEvents(WalletService wallet)
{
    IEventBus bus = wallet.EventBus;

    bus.Subscribe<IncomingPaymentEvent>(e =>
    {
        Console.WriteLine(
            $"📥  +{e.Amount} {e.Symbol} from {e.FromAddress} " +
            $"(Tx: {e.TransactionId})");
    });

    bus.Subscribe<TransactionConfirmedEvent>(e =>
    {
        Console.WriteLine(
            $"✅  Tx {e.TransactionId} confirmed in block {e.BlockHeight}");
    });
}
```

All subscriptions are **weakly referenced**; you do not need to unsubscribe when
using delegates or lambdas from short-lived objects.

---

## 8. Handling Errors & Exceptions

Every public API surface is annotated with `<exception>` XML comments.  
Major categories:

• `WalletLockedException` – Store locked or wrong password  
• `InsufficientFundsException` – Balance too low for requested spend  
• `FeeEstimationException` – Node unable to provide a fee quote  
• `BroadcastException` – Transaction rejected by mem-pool validation  

```csharp
try
{
    await wallet.UnlockAsync("wrong-password!");
}
catch (WalletLockedException ex) when (ex.ErrorCode == WalletError.BadPassword)
{
    Console.Error.WriteLine("🔒  Incorrect password.");
}
```

---

## 9. Best Practices Checklist

- **Encrypt** wallets at rest and **never** persist raw private keys.  
- **Unlock** wallets for the shortest possible time window (`using` block).  
- **Derive** a fresh address for each inbound payment (privacy & accounting).  
- **Validate** recipients and amounts in the UI **before** building transactions.  
- **Backup** the encrypted wallet file + mnemonic in a different physical location.  

---

## 10. Full Example – Minimal CLI

The following program combines the snippets above into a minimal, one-file CLI
that can create a wallet (if missing), display balances, and send payments.

```csharp
// WalletCli.csproj  (sdk: Microsoft.NET.Sdk / TargetFramework: net8.0)

/*
   dotnet run --                                         \
       --pwd "StrongPassword!"                           \
       --to  ucx1qa0x4c5l2ahyx4q...                      \
       --amount 10                                       \
       --label "Staking Rewards"                         \
       --symbol ECRT
*/

using System.CommandLine;
using UtilityChain.Core.Wallet;
using UtilityChain.Core.Transactions;

var pwdOption    = new Option<string>("--pwd",    "Wallet encryption password") { IsRequired = true };
var toOption     = new Option<string>("--to",     "Recipient address");
var amountOption = new Option<decimal>("--amount","Amount to send");
var labelOption  = new Option<string>("--label",  () => "Default");
var symbolOption = new Option<string>("--symbol", () => "ECRT");

var root = new RootCommand("UtilityChain Wallet CLI")
{
    pwdOption, toOption, amountOption, labelOption, symbolOption
};

root.SetHandler(async ctx =>
{
    var pwd    = ctx.ParseResult.GetValueForOption(pwdOption)!;
    var to     = ctx.ParseResult.GetValueForOption(toOption);
    var amount = ctx.ParseResult.GetValueForOption(amountOption);
    var label  = ctx.ParseResult.GetValueForOption(labelOption)!;
    var symbol = ctx.ParseResult.GetValueForOption(symbolOption)!;

    var walletPath = Environment.ExpandEnvironmentVariables(
        @"%APPDATA%\UtilityChain\wallet.dat");

    using var wallet = new WalletService(new FileWalletStore(walletPath, pwd));
    await wallet.UnlockAsync(pwd);

    HdAccount account = await wallet.GetOrCreateAccountAsync(label, symbol);

    if (to is null || amount == 0)
    {
        var bal = await wallet.GetBalanceAsync(account);
        Console.WriteLine($"Balance: {bal.Total} {symbol}");
        return;
    }

    try
    {
        var tx = wallet.NewTransaction()
                       .From(account)
                       .To(to, amount)
                       .WithFee(FeeStrategy.Medium)
                       .Build();

        var result = await wallet.BroadcastAsync(tx);

        Console.WriteLine(result.Success
            ? $"Sent! Tx {result.TransactionId}"
            : $"Failed: {result.Message}");
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.Message);
    }
});

return await root.InvokeAsync(args);
```

Compile & run:

```bash
dotnet run --project WalletCli.csproj -- --pwd "StrongPassword!"
```

---

## 11. Next Steps

1. Integrate the Wallet SDK with the **GraphQL Gateway** to expose balances over HTTP.  
2. Explore the **Smart-Contract IDE template** to sign and deploy contracts directly from the wallet.  
3. Read *Guide 04 – Staking & Governance* for details on delegating funds to validators.  

---

© UtilityChain 2024 – Released under the Apache 2.0 license.
```