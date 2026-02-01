# CanvasChain Symphony – Minting Service

> Location: `services/minting_service/`  
> Language: Rust (2021 edition)  
> Transport: gRPC over **TONIC** + **NATS** event bus  
> Runtime: `tokio` multi-threaded  
> Safety: `#![forbid(unsafe_code)]` – *no exceptions*  

---

## Table of Contents
1. Overview
2. Responsibilities
3. High-Level Architecture
4. Public gRPC API
5. Event Bus Channels
6. Build & Run
7. Configuration
8. Code Walk-Through
9. Error Semantics
10. Observability
11. Extending the Service
12. Security Considerations
13. License

---

## 1   Overview
The **Minting Service** orchestrates turning creative artifacts into on-chain, multilayer NFTs.  
It provides:

* Streaming & batch minting endpoints
* Pluggable cryptographic curves (Strategy Pattern)
* Proxy contracts for gas-optimized NFT spawning
* Event sourcing for auditability
* Integration hooks for DeFi staking rewards

The service is fully stateless; blockchain interactions are delegated to a **Wallet Adapter** module, while persistence is achieved via append-only **EventStore** snapshots in `PostgreSQL` (for rollups) and **IPFS/Arweave** for content addressable storage.

---

## 2   Responsibilities
• Validate mint requests (editions, royalties, metadata)  
• Generate deterministic metadata hashes using VRF seed (Proof-of-Inspiration)  
• Deploy **ERC-721**/**ERC-1155** compliant proxy contracts via Factory pattern  
• Emit `nft.minted` events for downstream services (marketplace, royalty-stream)  
• Throttle minting rate per composer node to prevent congestion  

---

## 3   High-Level Architecture

```text
┌────────────┐      gRPC       ┌─────────────────┐    NATS     ┌─────────────┐
│  Composer   │ ─────────────► │  Minting Service │───────────►│ Event Bus   │
│  Node       │                │   (this repo)   │            │ (JetStream) │
└────────────┘                 └─────────────────┘            └────┬────────┘
      ▲                                ▲                              │
      │ VRF seed / stake               │                              │
      │                                │ Wallet Tx / audit events     ▼
┌────────────┐                   ┌────────────┐                ┌────────────┐
│  Wallet    │◄──────────────────│  Ethereum  │◄───────────────│  Indexer   │
│  Adapter   │ JSON-RPC / EIP-155│  /EVM L2   │  block events  │  Service   │
└────────────┘                   └────────────┘                └────────────┘
```

---

## 4   Public gRPC API

`proto/minting/v1/minting.proto`

```proto
service MintingService {
    rpc Mint (MintRequest) returns (MintResponse);
    rpc MintStream (stream MintRequest) returns (stream MintResponse);
    rpc Health (HealthCheckRequest) returns (HealthCheckResponse);
}
```

Key messages:

* `MintRequest`
  * `artist_id`, `asset_uri`, `supply`, `royalty_bps`, `signature`
* `MintResponse`
  * `token_id`, `tx_hash`, `status`

See [`proto/`](../../proto/) for the full schema.

---

## 5   Event Bus Channels

| Subject                | Direction | Payload                             |
| ---------------------- | --------- | ----------------------------------- |
| `nft.minted`           | publish   | `MintedEvent` (JSON)                |
| `nft.mint.failed`      | publish   | `MintFailedEvent`                   |
| `governance.vrf.seed`  | subscribe | `VrfSeedEvent`                      |
| `wallet.tx.confirmed`  | subscribe | `TxConfirmedEvent`                  |

---

## 6   Build & Run

### Prerequisites
* Rust 1.71+ (`rustup toolchain install stable`)
* `protobuf` ≥ 3.21
* `docker` & `docker-compose` (for local chain / Postgres / NATS)

```bash
# Generate code
cargo xtask proto

# Run the service
cargo run -p minting_service -- --config ./Config.toml
```

> TIP – Use `cargo make dev` for a hot-reloading workflow.

---

## 7   Configuration (`Config.toml`)

```toml
[grpc]
listen_addr = "0.0.0.0:9002"
max_concurrent_streams = 128

[event_bus]
nats_url = "nats://localhost:4222"

[ethereum]
rpc_endpoint = "http://localhost:8545"
factory_address = "0xFactoryProxy..."
chain_id = 31337

[postgres]
dsn = "postgres://canvas:canvas@localhost:5432/canvas_nft"

[crypto]
curve = "ed25519" # ed25519 | bls12_381 | dilithium
```

Env vars can override any key using the form `CANVAS_MINTING__GRPC__LISTEN_ADDR`.

---

## 8   Code Walk-Through

```rust
//! cmd/minting_service/main.rs
#![forbid(unsafe_code)]
use minting_service::{config::Config, server::MintingServer};
use anyhow::Result;
use tracing::{info, error};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialise logging
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .init();

    // Load configuration
    let cfg = Config::from_env()?;
    info!(?cfg, "Launching Minting Service");

    // Run gRPC server
    if let Err(e) = MintingServer::run(cfg).await {
        error!(error = %e, "MintingService terminated with error");
        std::process::exit(1);
    }
    Ok(())
}
```

Highlights:

* `Strategy Pattern` – `crypto::Signer` trait with curve-specific back-ends (Ed25519/BLS/…)
* `Proxy Pattern` – contract factory `Factory<x>::deploy_proxy(…)`
* `Event Driven` – `EventPublisher` & `EventSubscriber` interfaces over `async_nats`
* `State Machine` – `MintJobState` (Queued → PendingTx → Confirmed | Failed)

---

## 9   Error Semantics

| gRPC code | Meaning                        | Retry |
| --------- | ----------------------------- | ----- |
| `INVALID_ARGUMENT` | Bad input (metadata URI missing, royalty > 100%) | No |
| `UNAUTHENTICATED`  | Invalid artist signature / expired nonce         | No |
| `RESOURCE_EXHAUSTED` | Rate limit exceeded (composer node)          | Yes, after `Retry-After` header |
| `INTERNAL`         | Unexpected error, check `error_id`              | Maybe |

A structured error (`ErrorBody`) is serialized in `details`.

---

## 10   Observability

* **Metrics** – `OpenTelemetry` exporter (`/metrics` Prometheus scrape)  
* **Tracing** – Distributed `trace_id` propagated via gRPC metadata  
* **Health** – `/livez` & `/readyz` HTTP endpoints (serve on `:9003`)  
* **Structured Logs** – JSON by default, switch to pretty with `RUST_LOG_STYLE=pretty`

---

## 11   Extending the Service

* Add new crypto curves by implementing `crypto::Signer` + registering in `crypto::registry`.
* Support new NFT standards (e.g., ERC-3525) via the `contract::factory` module.
* Custom throttling strategies can be injected using the `RateLimiter` trait.

---

## 12   Security Considerations

* Re-entrancy guarded via **OpenZeppelin** templates
* Nonce replay protection for mint signatures
* `supply` and `royalty_bps` sanity checks
* All secrets loaded via `HashiCorp Vault` in prod

---

## 13   License
`Apache-2.0` – see [LICENSE](../../LICENSE)  

*Art fuels technology – forge responsibly.*