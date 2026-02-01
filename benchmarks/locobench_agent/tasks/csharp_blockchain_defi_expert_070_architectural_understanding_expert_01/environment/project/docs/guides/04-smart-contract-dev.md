# UtilityChain Core Suite &mdash; Smart-Contract Development Guide
_Revision: 1.2 – compatible with UtilityChain Core Suite 0.8.x_

---

## Table of Contents
1. Introduction  
2. Prerequisites  
3. Project Structure  
4. Creating a Contract  
5. Compiling & Packaging  
6. Deploying to the Chain  
7. Interacting via CLI / SDK  
8. Unit-Testing Contracts  
9. Debugging & Tracing  
10. Security Checklist  

---

## 1. Introduction
UtilityChain smart-contracts are authored in **C# 12** and executed by an **in-process WASM host** that is tightly coupled to the monolithic node. Developers write contracts against the `UtilityChain.Contracts` SDK, compile them into WebAssembly or IL, and deploy the artifacts through the built-in gRPC/GraphQL gateways or the command-line interface `uc`.

> NOTE  
> Contracts are sandboxed and deterministic—only the APIs exposed by `UtilityChain.Contracts` are available. Any attempt to reflect, spawn threads, or perform non-deterministic operations will fail at verification time.

---

## 2. Prerequisites
```bash
dotnet --version        # >= 8.0
uc --version            # shipped with node binary
wasmtime --version      # only if you require native debugging
```

---

## 3. Project Structure
The `uc util new-contract` template scaffolds the following layout:

```text
EnergyCredit/
 ├── EnergyCredit.csproj      // SDK style project
 ├── Contracts/
 │   └── EnergyCreditToken.cs // Your main contract
 ├── test/
 │   └── EnergyCreditTests.cs // xUnit test project
 └── README.md
```

`UtilityChain.Contracts` is referenced automatically and brings the following namespaces:

```csharp
using UtilityChain.Contracts;
using UtilityChain.Contracts.Runtime;
using UtilityChain.Contracts.Storage;
using UtilityChain.Contracts.Cryptography;
```

---

## 4. Creating a Contract

Below is a fully-featured sample implementing a **credit-based ERC-20-like** token with mint/burn, pausing, and role-based access control.

```csharp
// File: Contracts/EnergyCreditToken.cs
using System.Numerics;
using UtilityChain.Contracts;
using UtilityChain.Contracts.Attributes;
using UtilityChain.Contracts.Runtime;
using UtilityChain.Contracts.Storage;

namespace EnergyCredit;

/// <summary>
/// EnergyCreditToken implements a pausable, mintable ERC-20-like asset.
/// </summary>
[Contract("energy.credit.v1", Author = "UtilityChain Labs", Description = "Tradable on/off-chain energy credits.")]
[SupportsInterface("IERC20", "IPausable", "IRoleBasedAccess")]
public sealed partial class EnergyCreditToken : SmartContract
{
    /* ----------------------------------------------------------------------
     *                           Storage Schema
     * --------------------------------------------------------------------*/
    private readonly Mapping<UInt160, BigInteger> _balances = new(nameof(_balances));
    private readonly Mapping<UInt160, Mapping<UInt160, BigInteger>> _allowances = new(nameof(_allowances));

    private readonly Persistent<BigInteger> _totalSupply = new(nameof(_totalSupply));
    private readonly Persistent<bool> _paused = new(nameof(_paused));

    /* ----------------------------------------------------------------------
     *                            Constants
     * --------------------------------------------------------------------*/
    public const string ADMIN_ROLE = "ADMIN";
    public const string PAUSER_ROLE = "PAUSER";
    public const string MINTER_ROLE = "MINTER";

    /* ----------------------------------------------------------------------
     *                       Contract Initialization
     * --------------------------------------------------------------------*/
    [Initializer]
    public void Init(UInt160 admin)
    {
        Require(!IsInitialized, "Already initialized.");
        Roles.GrantRole(ADMIN_ROLE, admin);
        Roles.GrantRole(PAUSER_ROLE, admin);
        Roles.GrantRole(MINTER_ROLE, admin);
    }

    /* ----------------------------------------------------------------------
     *                        Public Read Methods
     * --------------------------------------------------------------------*/
    public BigInteger TotalSupply() => _totalSupply.Value;

    public BigInteger BalanceOf(UInt160 owner) => _balances[owner];

    public BigInteger Allowance(UInt160 owner, UInt160 spender) => _allowances[owner][spender];

    public bool IsPaused() => _paused.Value;

    /* ----------------------------------------------------------------------
     *                        Token Mutations
     * --------------------------------------------------------------------*/
    [Event("Transfer", typeof(UInt160), typeof(UInt160), typeof(BigInteger))]
    private static partial void OnTransfer(UInt160 from, UInt160 to, BigInteger amount);

    [Event("Approval", typeof(UInt160), typeof(UInt160), typeof(BigInteger))]
    private static partial void OnApproval(UInt160 owner, UInt160 spender, BigInteger amount);

    public void Transfer(UInt160 to, BigInteger amount)
    {
        EnsureNotPaused();
        _transfer(Message.Sender, to, amount);
    }

    public void Approve(UInt160 spender, BigInteger amount)
    {
        EnsureNotPaused();
        _allowances[Message.Sender][spender] = amount;
        OnApproval(Message.Sender, spender, amount);
    }

    public void TransferFrom(UInt160 owner, UInt160 to, BigInteger amount)
    {
        EnsureNotPaused();
        var current = _allowances[owner][Message.Sender];
        Require(current >= amount, "Allowance exceeded.");

        _allowances[owner][Message.Sender] = current - amount;
        _transfer(owner, to, amount);
    }

    /* ----------------------------------------------------------------------
     *                          Mint / Burn
     * --------------------------------------------------------------------*/
    public void Mint(UInt160 to, BigInteger amount)
    {
        RequireRole(MINTER_ROLE);
        Require(amount > 0, "Invalid mint amount.");

        _totalSupply.Value += amount;
        _balances[to] += amount;

        OnTransfer(UInt160.Zero, to, amount);
    }

    public void Burn(UInt160 from, BigInteger amount)
    {
        RequireRole(MINTER_ROLE);
        Require(amount > 0, "Invalid burn amount.");
        Require(_balances[from] >= amount, "Insufficient balance.");

        _balances[from] -= amount;
        _totalSupply.Value -= amount;

        OnTransfer(from, UInt160.Zero, amount);
    }

    /* ----------------------------------------------------------------------
     *                          Pause Control
     * --------------------------------------------------------------------*/
    public void Pause()
    {
        RequireRole(PAUSER_ROLE);
        _paused.Value = true;
    }

    public void Unpause()
    {
        RequireRole(PAUSER_ROLE);
        _paused.Value = false;
    }

    /* ----------------------------------------------------------------------
     *                         Internal Helpers
     * --------------------------------------------------------------------*/
    private void _transfer(UInt160 from, UInt160 to, BigInteger amount)
    {
        Require(amount > 0, "Invalid transfer amount.");
        Require(_balances[from] >= amount, "Insufficient balance.");

        _balances[from] -= amount;
        _balances[to] += amount;

        OnTransfer(from, to, amount);
    }

    private void EnsureNotPaused() => Require(!_paused.Value, "Contract paused.");
}
```

### Key Points
1. `[Initializer]` runs once when the contract is deployed.  
2. `Roles.GrantRole` leverages the **built-in RBAC** engine.  
3. `Persistent<T>` and `Mapping<TKey, TValue>` wrap trie storage with type-safety.  
4. `OnTransfer` / `OnApproval` are compile-time generated event emitters.

---

## 5. Compiling & Packaging
Use the CLI to compile contracts into a determinstic WASM payload that is ready for deployment.

```bash
cd EnergyCredit
uc util build --release              # emits bin/EnergyCredit.wasm
```

Artifacts:
```text
bin/
 ├── EnergyCredit.wasm               # sandboxed contract byte-code
 └── EnergyCredit.manifest.json      # interfaces, abi, and metadata
```

---

## 6. Deploying to the Chain

### 6.1 CLI
```bash
uc tx deploy \
    --wasm bin/EnergyCredit.wasm \
    --manifest bin/EnergyCredit.manifest.json \
    --sender 0xA1B2... \
    --gas 5_000_000
```

### 6.2 GraphQL
```graphql
mutation DeployContract($input: DeployContractInput!) {
  deployContract(input: $input) {
    txId
    contractHash
  }
}
```

The contract address (UInt160) is deterministic: `Hash(wasm + manifest + salt)`.

---

## 7. Interacting via CLI / SDK

### CLI Example
```bash
# Mint 100 credits to Bob
uc tx call \
   --contract 0xABCD... \
   --method Mint \
   --params "[\"0xB0B...\", \"100\"]" \
   --sender 0xA1B2...
```

### .NET SDK Example
```csharp
var chain = new UtilityChainClient("http://localhost:5155");

var tx = await chain
    .Contracts["0xABCD..."]
    .PrepareCall("Transfer")
    .WithParameters(new UInt160("0xB0B..."), BigInteger.Parse("10"))
    .WithSender(wallet)
    .SendAsync();

Console.WriteLine($"Tx sent: {tx.TxHash}");
```

---

## 8. Unit-Testing Contracts

Contracts are tested using **xUnit** and the `UtilityChain.TestKit` harness which spins up an **in-memory consensus sandbox**.

```csharp
// File: test/EnergyCreditTests.cs
using System.Numerics;
using UtilityChain.TestKit;
using Xunit;

public class EnergyCreditTests : ContractTestBase
{
    private readonly UInt160 _owner = TestAccounts.Genesis.Address;
    private readonly UInt160 _alice = TestAccounts.Alice.Address;

    [Fact]
    public void Mint_Increases_TotalSupply_And_Balance()
    {
        // Arrange
        var contract = Deploy<EnergyCreditToken>(_owner);

        // Act
        contract.Mint(_alice, 100);

        // Assert
        Assert.Equal(100, contract.TotalSupply());
        Assert.Equal(100, contract.BalanceOf(_alice));
    }

    [Fact]
    public void Transfer_Throws_If_Paused()
    {
        var contract = Deploy<EnergyCreditToken>(_owner);

        contract.Pause();

        var ex = Assert.Throws<ContractException>(() =>
            contract.Transfer(_alice, 1));

        Assert.Equal("Contract paused.", ex.Message);
    }
}
```

`ContractTestBase` resets state before each test and provides deterministic execution.

---

## 9. Debugging & Tracing

1. Start node with verbose tracing:
   ```bash
   uc node start --log-level debug --trace-contracts
   ```
2. Attach a debugger to the WASM runtime (optional):
   ```bash
   wasmtime run --debug bin/EnergyCredit.wasm
   ```
3. Use the Contract Explorer in **UtilityChain Wallet** for real-time logs/events.

---

## 10. Security Checklist
- [ ] Validate all external inputs with `Require`.  
- [ ] Leverage RBAC (`Roles.*`) for sensitive operations.  
- [ ] Emit events for state-changing operations.  
- [ ] Avoid floating point arithmetic—use `BigInteger`.  
- [ ] Run `uc audit contract` before deployment.  
- [ ] Document upgrade/migration path if `@Upgradable`.

---

## Further Reading
* docs/api/UtilityChain.Contracts.md  
* guides/05-governance-hooks.md  
* RFC-19: Deterministic Data Layout  

Happy building! For issues, visit **github.com/utilitychain/utilitychain-core-suite**.