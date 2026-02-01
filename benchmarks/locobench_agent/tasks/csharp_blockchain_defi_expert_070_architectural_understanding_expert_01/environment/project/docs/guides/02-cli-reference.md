```markdown
# UtilityChain Core Suite – Command-Line Reference
> Version `v1.4.0` (built on .NET 8)\
> Last updated 2024-04-30

The `uc` ( **U**tility**C**hain ) command-line interface ships with every
UtilityChain Core Suite distribution.  
It exposes the same public surface used by the REST/GraphQL gateway and the
desktop wallet, making it ideal for scripting, CI/CD pipelines, and advanced
node administration.

```
# Bootstrap a private network
uc init --network energynet --validators 4 --force

# Generate a cold-storage key and delegate 500 UTX to a validator
uc key gen --out ./cold.json
uc stake delegate --from ./cold.json --amount 500

# Compile & deploy a smart contract
uc contract build ./EnergyCredits.csproj
uc contract deploy ./bin/Release/EnergyCredits.ucwasm
```

---

## 1. Installation

```
dotnet tool install --global UtilityChain.Core
# or:
choco install utilitychain
# or:
brew tap utilitychain/core && brew install uc
```

The `uc` executable is **self-contained**; no runtime is required on the host
machine aside from the glibc/libc variant of your operating system.

---

## 2. CLI Conventions

Syntax legend:

```
uc [<GLOBAL-OPTIONS>] <COMMAND> [<SUBCOMMAND>] [<OPTIONS>] [<ARGS>]
```

• Flags may be placed **before or after** the command (`uc -v stake delegate`).  
• Short form flags may be **stacked** (`-vn=mainnet` → `--verbose --network`).  
• Environment variables prefixed with `UC_` override the CLI (`UC_NETWORK`).  
• A **double dash** stops option parsing (`uc tx submit -- --raw-json`).  

---

### 2.1 Global Options

| Option                                | Description                                                      |
|---------------------------------------|------------------------------------------------------------------|
| `-h`, `--help`                        | Show context-sensitive help.                                     |
| `--version`                           | Print build, commit hash, and semantic version.                  |
| `-v`, `--verbosity <level>`           | `quiet`, `minimal`, `normal` (default), `detailed`, `diagnostic` |
| `-n`, `--network <id>`                | `mainnet`, `testnet`, or a custom chain identifier.              |
| `-c`, `--config <path>`               | Path to a `.yml`/`.json` config file (default `%APPDATA%/uc`).   |
| `--json`                              | Emit machine-readable JSON instead of ANSI text.                 |

Examples:

```
uc --network testnet stake list --json
uc -v detailed node start
```

---

## 3. Command Reference

The table below lists high-level commands. Click the command name to jump to
its dedicated section.

| Command        | Purpose                                        |
|----------------|------------------------------------------------|
| [`init`](#31-init)           | Bootstrap a fresh chain / workspace. |
| [`key`](#32-key)             | Key and keystore management.         |
| [`wallet`](#33-wallet)       | Multi-asset wallet operations.       |
| [`stake`](#34-stake)         | Delegated staking and validator ops. |
| [`governance`](#35-governance)| Propose, vote, enact policy changes. |
| [`contract`](#36-contract)   | WASM smart contract toolchain.       |
| [`token`](#37-token)         | Fungible & asset-backed token suite. |
| [`nft`](#38-nft)             | Non-fungible token utilities.        |
| [`node`](#39-node)           | Start, stop, and inspect node daemon.|
| [`chain`](#310-chain)        | Query ledger, submit raw tx, export. |
| [`config`](#311-config)      | Modify host configuration.           |

---

### 3.1 `init`

Bootstrap a new UtilityChain data-directory or a full private network.

```
uc init [OPTIONS]
```

| Option                 | Description                                      |
|------------------------|--------------------------------------------------|
| `--network <id>`       | Override the chain identifier.                   |
| `--validators <count>` | Generate & fund `<count>` genesis validators.    |
| `--force`              | Overwrite existing directory without prompt.     |
| `--template <name>`    | `minimal`, `energynet`, `carbon-credit`, etc.    |

Example:

```
uc init --network energynet --validators 4 --template energynet --force
```

---

### 3.2 `key`

Generate, import, export, list, and rotate cryptographic keys.

Sub-commands:

```
uc key gen         # Create an encrypted key-file
uc key import      # Import mnemonic or raw seed
uc key export      # Export to JSON / PKCS#8 / PEM
uc key list        # Enumerate keys in the keystore
uc key rotate      # Derive & swap a new child key
```

Key generation example:

```
uc key gen \
  --out ./founder.json \
  --algo secp256k1 \
  --mnemonic \
  --passphrase "correct horse battery staple"
```

---

### 3.3 `wallet`

High-level asset management.

• `uc wallet balance` — Show multi-currency balance  
• `uc wallet send` — Transfer tokens (with offline signing)  
• `uc wallet history` — List inbound/outbound transactions  

```
uc wallet send \
  --from ./founder.json \
  --to util1q529u... \
  --symbol UTX \
  --amount 250.5 \
  --memo "Seed funding" \
  --fee auto
```

---

### 3.4 `stake`

Delegate stake, claim rewards, and manage validator nodes.

| Sub-command            | Highlights                                                   |
|------------------------|--------------------------------------------------------------|
| `list`                 | Show validator set, commission, uptime, total stake.        |
| `delegate`             | Delegate tokens to a validator public key.                  |
| `withdraw`             | Claim staking rewards to wallet.                            |
| `validator register`   | Register as a new validator candidate (requires bond).      |
| `validator edit`       | Update metadata & commission rate.                          |

Delegation example:

```
uc stake delegate --from wallet.json --validator 03ab… --amount 500 --lock 21d
```

---

### 3.5 `governance`

Submit, vote, and tally proposals.

```
uc governance propose text \
  --title "Increase block gas limit" \
  --description ./gas-limit.md \
  --deposit 1000
```

Vote:

```
uc governance vote --proposal 42 --option yes --from council.json
```

---

### 3.6 `contract`

Compile, test, audit, and deploy WASM/IL smart contracts.

| Sub-command | Action                                            |
|-------------|---------------------------------------------------|
| `build`     | MSBuild wrapper producing deterministic WASM.     |
| `deploy`    | Broadcast a new contract to the chain.            |
| `call`      | Execute a read-only method locally.               |
| `invoke`    | Submit a state-changing transaction.              |
| `test`      | Run unit & gas-metered integration tests.         |
| `verify`    | Compare on-chain bytecode to local build.         |

Deploy example:

```
uc contract build ./EnergyCredits.csproj -c Release
uc contract deploy ./bin/Release/EnergyCredits.ucwasm \
  --from treasurer.json \
  --gas-limit 4_000_000 \
  --init-json ./init-params.json
```

---

### 3.7 `token`

Manage fungible (ERC-20-like) tokens.

```
uc token create \
  --symbol ECO \
  --name "Energy Credit" \
  --decimals 2 \
  --max-supply 10_000_000 \
  --owner treasury.json
```

---

### 3.8 `nft`

Mint, transfer, and query NFT collections.

```
uc nft mint \
  --collection solar \
  --recipient util1... \
  --metadata ./solar-panel-124.json
```

---

### 3.9 `node`

Control the local node daemon.

```
uc node start   # foreground
uc node stop
uc node status
uc node logs --tail 100 --follow
```

---

### 3.10 `chain`

Low-level ledger tooling.

| Sub-command | Description                          |
|-------------|--------------------------------------|
| `height`    | Print current block height.          |
| `info`      | Chain ID, consensus, epoch length.   |
| `block`     | Fetch a block by height/hash.        |
| `tx`        | Submit or query transactions.        |
| `export`    | Snapshot chain DB to `.tar.zst`.     |
| `import`    | Restore from snapshot.               |

---

### 3.11 `config`

Read or mutate the host/runtime configuration.

```
uc config set consensus.blockTimeMs 1500
uc config get api.http.port
uc config diff --against defaults
```

---

## 4. Environment Variables

| Variable            | Purpose                                 |
|---------------------|-----------------------------------------|
| `UC_NETWORK`        | Default network (mainnet/testnet/etc).  |
| `UC_CONFIG`         | Path to fallback config file.           |
| `UC_LOG_LEVEL`      | Override logging verbosity.             |
| `UC_NO_UPDATE`      | Disable update-checker on startup.      |

---

## 5. Exit Codes

| Code | Meaning                 |
|------|-------------------------|
| `0`  | Success.                |
| `1`  | General or unknown error|
| `2`  | Invalid arguments.      |
| `3`  | Network / RPC failure.   |
| `4`  | Unauthorized / auth fail|
| `5`  | Cryptographic error.    |

---

## 6. Programmatic Usage (C#)

The CLI internally proxies to the same API you can reference from .NET
applications. The snippet below demonstrates how to obtain the current
validator set without launching a subprocess:

```csharp
using UtilityChain.Core;
using UtilityChain.Core.Ledger;
using UtilityChain.Core.Rpc;
using var host = new UtilityChainHost(
    configPath: Environment.GetEnvironmentVariable("UC_CONFIG"));

IValidatorProvider provider = host.GetService<IValidatorProvider>();
var validators = await provider.GetActiveValidatorsAsync();

Console.WriteLine($"Active validators: {validators.Count}");
foreach (var v in validators)
{
    Console.WriteLine($"{v.Moniker} – {v.Stake} UTX");
}
```

---

## 7. Autocompletion

Generate a shell completion script:

```
uc completion bash   > /etc/bash_completion.d/uc
uc completion zsh    > "${fpath[1]}/_uc"
uc completion powershell | Out-String | Invoke-Expression
```

---

## 8. Troubleshooting

| Symptom                          | Resolution                                              |
|----------------------------------|---------------------------------------------------------|
| `uc: command not found`          | Ensure `$HOME/.dotnet/tools` is on your `$PATH`.        |
| Stuck at *“Connecting to peers”* | Verify ports `26656`/`26657` are open and routable.      |
| `ERR128: Invalid mnemonic`       | Check word list spelling & correct passphrase.          |
| `Consensus halted at height X`   | Inspect `uc node logs` and remove corrupt WAL if safe.  |

---

## 9. Changelog Highlights

• **v1.4.0** — NFT royal­ties, PoS slashing, dynamic fee market  
• **v1.3.2** — GraphQL API, batch contract invocations  
• **v1.2.0** — WASM debugging, cold-staking support

---

© 2024 UtilityChain Foundation — Licensed under Apache 2.0
```