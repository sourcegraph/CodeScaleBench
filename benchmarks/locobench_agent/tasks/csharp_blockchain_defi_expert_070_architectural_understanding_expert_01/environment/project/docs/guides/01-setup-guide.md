```markdown
# UtilityChain Core Suite — Setup Guide  
_File: `docs/guides/01-setup-guide.md`_

This document walks new operators through downloading, compiling, configuring, and launching a **single-node or multi-node** UtilityChain network. It also demonstrates how to extend the default distribution with custom C# modules.

> **Audience**  
>  • DevOps or Site Reliability engineers deploying the chain in production  
>  • C#/.NET developers integrating bespoke staking calculators, consensus engines, or governance policies  
>  • Solution architects evaluating whether UtilityChain’s monolithic executable satisfies organizational requirements  

---

## 1. Prerequisites

| Requirement         | Minimum Version | Notes                                                |
| ------------------- | --------------- | ---------------------------------------------------- |
| .NET SDK            | **8.0.100**     | Verify with `dotnet --version`                      |
| Git                 | 2.40            | Needed for cloning the repository                   |
| OS                  | Windows 10 / Ubuntu 22.04 / macOS 13 | x64 or ARM64                      |
| PostgreSQL (optional) | 14             | Used for the **Indexing Service**                   |
| NTP Service         | —               | Nodes must remain in sync for consensus time-slots  |

---

## 2. Cloning the Repository

```bash
git clone https://github.com/your-org/utilitychain.git
cd utilitychain
```

> **Tip:** To contribute, fork the repository first and push to your own origin.

---

## 3. Building the Executable

The project targets `net8.0` and packs all runtime dependencies into a single self-contained binary.  
Build **Release** to enable AOT (Ahead-Of-Time) compilation and hardware-accelerated crypto.

```bash
dotnet publish src/UtilityChainCoreSuite/UtilityChainCoreSuite.csproj \
  --configuration Release \
  --runtime linux-x64      \
  -p:PublishSingleFile=true \
  -p:PublishAot=true        \
  -o ./out
```

Output on Linux:

```text
./out/utilitychain
./out/utilitychain.deps.json
./out/utilitychain.runtimeconfig.json
```

Copy the `/out` directory to each target node.

---

## 4. First-Time Node Initialization

### 4.1 Create a Working Directory

```bash
sudo mkdir -p /var/lib/utilitychain
sudo chown "$(whoami)" /var/lib/utilitychain
cd /var/lib/utilitychain
```

### 4.2 Generate the Default Configuration

```bash
/path/to/utilitychain init --network=devnet
```

This command does the following:

1. Writes `appsettings.json` and `logging.json`
2. Generates a **validator key-pair** in `keys/`
3. Creates a genesis block using the **Proof-of-Authority** consensus template  
4. Seeds a local SQLite ledger (`ledger.db`) with the genesis contents

> **Note**: Use `--overwrite` to regenerate config files. Use a secure location or HSM for production keys.

---

## 5. Configuration Deep-Dive

All settings can be tweaked via _appsettings.json_, environment variables, or CLI flags.

```jsonc
{
  "Blockchain": {
    // Length of a slot in seconds. Must match across all nodes.
    "SlotTime" : 5,

    // Identifier written in every block header
    "ChainId"  : "utilitychain-devnet"
  },

  "Consensus": {
    // Switch between "PoA", "DPoS", or any IConsensusEngine implementation
    "Engine" : "PoA",

    // Assembly-qualified type name for custom engine
    "CustomEngineType": null
  },

  "Staking": {
    // Base reward per block (in smallest currency unit)
    "BlockReward" : 5_000_000,

    // Strategy class implementing IStakingCalculator
    "CalculatorStrategy" : "Default"
  },

  "Persistence": {
    // "SQLite", "PostgreSql", or "InMemory"
    "Provider" : "SQLite",
    "ConnectionString" : "Data Source=ledger.db"
  }
}
```

You can also override a single property via environment variable:

```bash
export Blockchain__SlotTime=2
./utilitychain run
```

---

## 6. Running the Node

### 6.1 Stand-Alone

```bash
./utilitychain run --network=devnet \
                   --log-level=Information \
                   --http-port=7070 \
                   --p2p-port=30303
```

The console log should end with:

```text
[Node] ▶ State=Listening; P2P=0.0.0.0:30303; HTTP=0.0.0.0:7070
```

### 6.2 Systemd Service (Linux)

```ini
# /etc/systemd/system/utilitychain.service
[Unit]
Description=UtilityChain Core Suite Node
After=network.target

[Service]
ExecStart=/usr/local/bin/utilitychain run --network=mainnet
WorkingDirectory=/var/lib/utilitychain
Restart=on-failure
User=blockchain

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable utilitychain
sudo systemctl start utilitychain
sudo journalctl -u utilitychain -f
```

---

## 7. Connecting Multiple Peers

Each node maintains a `peers.json` file:

```json
[
  { "host": "10.0.1.5", "port": 30303, "publicKey": "0x03efa..." },
  { "host": "10.0.1.6", "port": 30303, "publicKey": "0x02ab1..." }
]
```

Add static peers on **Node A**:

```bash
./utilitychain peer add 10.0.1.6:30303 0x02ab1...
./utilitychain peer list
```

The **Event-Driven** P2P stack uses the _Observer Pattern_ to broadcast state changes:

```csharp
public sealed class PeerConnectedEvent : IClusterEvent
{
    public required PeerInfo Peer { get; init; }
}

_cluster.EventBus.Publish(new PeerConnectedEvent { Peer = info });
```

---

## 8. Developer Extensions

### 8.1 Custom Staking Calculator

Implement `IStakingCalculator` in a class library that targets `net8.0`.

```csharp
namespace Acme.Coins.Staking;

/// <summary>
/// Example calculator awarding quadratic interest for long-term delegators.
/// </summary>
public sealed class QuadraticStakingCalculator : IStakingCalculator
{
    public decimal CalculateReward(
        ulong stakedBlocks,
        decimal currentStake,
        CancellationToken ct = default)
    {
        // Reward = stake × √blocks
        var sqrt = Math.Sqrt(Convert.ToDouble(stakedBlocks));
        return currentStake * (decimal)sqrt * 0.000_1m;
    }
}
```

Build the DLL and drop it into the `plugins/` folder:

```bash
dotnet publish -c Release -o ../../node/plugins
```

Update the config:

```jsonc
"Staking": {
  "CalculatorStrategy": "Acme.Coins.Staking.QuadraticStakingCalculator, Acme.Coins.Staking"
}
```

Restart the node; the **Strategy Pattern** hot-loads your calculator at runtime.

### 8.2 Custom Consensus Engine

1. Implement `IConsensusEngine` using the **State Machine** APIs  
2. Register the assembly in `appsettings.json → Consensus → CustomEngineType`  
3. Restart all nodes with identical binaries to avoid consensus forks  

```csharp
[Export(typeof(IConsensusEngine))]
public sealed class RandomBeaconBftEngine : ConsensusEngineBase
{
    protected override ValueTask<StateChange> ProcessBlockAsync(
        LedgerState state,
        Block incoming,
        CancellationToken ct)
    {
        // Custom Byzantine-Fault-Tolerant rules
        return new(StateChange.Accept);
    }
}
```

---

## 9. REST / GraphQL Gateway

Once the node is running, the embedded gateway is reachable at:

```
GET http://127.0.0.1:7070/api/v1/chain/height
```

Sample response:

```json
{ "height": 1824 }
```

GraphQL Playground:

```
http://127.0.0.1:7070/graphql
```

Query example:

```graphql
query {
  blocks(last: 10) {
    index
    hash
    proposer
  }
}
```

---

## 10. Troubleshooting

| Symptom                               | Possible Cause                               | Fix                                                   |
| ------------------------------------- | -------------------------------------------- | ----------------------------------------------------- |
| `Slot drift exceeds tolerance`        | System clock skew                            | Enable NTP daemon, restart node                       |
| `Failed to load plugin assembly`      | Version mismatch / missing dependency        | Recompile plugin against matching UtilityChain SDK    |
| HTTP 503 on GraphQL endpoint          | Gateway not started yet                      | Wait for `NodeReady` event or check `--http-port`     |
| Node shuts down with `ConsensusFork`  | Differing codebase among validators          | Redeploy identical executable to all consensus nodes  |

---

## 11. Next Steps

• Follow the [Smart-Contract Quick Start](./02-smart-contract-guide.md)  
• Explore the [Desktop Wallet](https://github.com/your-org/utilitychain-wallet)  
• Join our Discord for community support  

---

Copyright © **UtilityChain Core Suite**.  
Licensed under the **MIT License**.
```