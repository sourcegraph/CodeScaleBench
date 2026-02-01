# CanvasChain Symphony – Node Service

The **Node Service** is the beating heart of CanvasChain Symphony.  
It encapsulates networking, consensus, state-replication, and provides an ergonomic Rust SDK so higher-level micro-services (composition, remixing, marketplace, etc.) can publish transactions or subscribe to real-time events without re-implementing blockchain plumbing.

---

## 🧩 Responsibilities

1. Peer-to-peer networking (libp2p over QUIC + noise)
2. Proof-of-Inspiration (PoI) leader election
3. Transaction / block propagation
4. State–machine replication (+ snapshotting)
5. gRPC façade exposing high-level APIs to the remaining micro-services
6. Event bus bridge (NATS) to fan-out new blocks & governance votes

---

## 🔖 Feature Flags

| Cargo Feature            | Description                                |
|--------------------------|--------------------------------------------|
| `in-memory-db`           | Use an ephemeral RocksDB substitute for tests |
| `bls-signatures`         | Switch from Ed25519 to BLS12-381 curve     |
| `experimental-post-quantum` | Enable Dilithium (PQ-crypto) signatures |

Activate mutually exclusive curves via:

```bash
cargo build --release --no-default-features --features bls-signatures
```

---

## 🗄️ Directory Layout

```
services/node_service
├── Cargo.toml                # Crate metadata + feature flags
├── build.rs                  # Build-time generation of protobuf & WASM
├── src/
│   ├── lib.rs                # Public SDK
│   ├── config.rs             # Strictly-typed TOML/YAML config
│   ├── grpc/
│   │   ├── mod.rs            # tonic-generated stubs (auto-generated)
│   ├── consensus/
│   │   ├── mod.rs
│   │   └── proof_of_inspiration.rs
│   ├── network/
│   ├── storage/
│   ├── event_bus/
│   └── node.rs               # Binary entry-point
└── README.md                 # You are here
```

---

## ⚙️ Configuration

`node.yaml` (default look-up paths: `$PWD`, `$HOME/.canvaschain`, `/etc/canvaschain/`)

```yaml
node_id: "node-01-mainnet"
network:
  listen_multiaddr: "/ip4/0.0.0.0/udp/30333/quic-v1"
  bootstrap_peers:
    - "/dns4/boot.canvaschain.art/udp/30333/quic-v1"
consensus:
  staking_contract: "0x92…a4"
  epoch_duration_sec: 6
storage:
  path: "/var/lib/canvaschain"
grpc:
  bind: "0.0.0.0:50051"
event_bus:
  nats_url: "nats://localhost:4222"
```

Load it with the public SDK:

```rust
use node_service::config::NodeConfig;

let cfg = NodeConfig::from_path("node.yaml")?;
println!("Node ID: {}", cfg.node_id);
```

---

## 🛰️ gRPC API

All protobuf definitions live in `proto/` and are compiled by `build.rs` using `tonic_build`.

Example service snippet (simplified):

```proto
service CanvasNode {
  rpc SubmitTransaction (SignedTransaction) returns (TxReceipt);
  rpc GetBlockByHash     (BlockHash)        returns (Block);
  rpc SubscribeEvents    (EventFilter)      returns (stream Event);
}
```

### Error Model

Errors map to canonical gRPC codes:

| gRPC Code | Meaning                                    |
|-----------|--------------------------------------------|
| `INVALID_ARGUMENT` | Input failed schema or signature validation |
| `UNAVAILABLE`      | Not currently the leader / syncing |
| `FAILED_PRECONDITION` | Consensus rejected the tx (e.g. nonce) |
| `INTERNAL`         | Unexpected panic → logged + Sentry |

---

## 🚀 Quick Start

```bash
# 1. Clone repo
git clone https://github.com/canvaschain/symphony.git
cd symphony/services/node_service

# 2. Build with default Ed25519 curve
cargo build --release

# 3. Generate keys (stored in ./keys/)
cargo run --bin keygen ed25519

# 4. Run a standalone dev-node with an in-memory DB and verbose logs
RUST_LOG=debug cargo run --features in-memory-db
```

---

## 🧑‍💻 Embedding the SDK

Use the SDK in another micro-service (e.g. composition_service):

```toml
[dependencies]
canvas_node_sdk = { path = "../services/node_service", default-features = false }
prost = "0.12"
tonic = { version = "0.10", features=["transport"] }
```

```rust
use canvas_node_sdk::grpc::canvas_node_client::CanvasNodeClient;
use tonic::transport::Channel;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut client = CanvasNodeClient::connect("http://localhost:50051").await?;

    let tx = build_artist_transaction();
    let receipt = client.submit_transaction(tx).await?.into_inner();

    println!("🎉 Mined in block {}", receipt.block_number);
    Ok(())
}
```

---

## 🏛️ Consensus in 60 Seconds

1. Epoch is fixed (#blocks = `epoch_duration_sec / slot_time_sec`)
2. VRF leader randomness is derived from last block hash + validator stake
3. Committee = top-N validators by stake (configurable)
4. Fork-choice = GHOST for liveness; blocks must include VRF proof
5. Finality via BFT overlay (HotStuff variant) after 2 rounds

See `src/consensus/proof_of_inspiration.rs` for full implementation & unit tests.

---

## 📈 Metrics & Observability

Prometheus exporter is enabled by default at `/metrics` (port 9103).

Key metrics:
• `canvas_block_height`
• `canvas_peer_count`
• `canvas_tx_pool_size`
• `canvas_leader_election_duration_seconds`

Enable Jaeger tracing:

```bash
JAEGER_ENDPOINT=http://localhost:14268/api/traces RUST_LOG=info,tower_http=debug \
    cargo run --release
```

---

## 🔒 Security Checklist

- AES-GCM sealed storage for private keys (`KeyVault`)
- All peer traffic encrypted via Noise_KK
- Strict Protobuf schema validation (`prost-types` + `schemars`)
- Comprehensive fuzzing harness: `cargo fuzz run tx_deserialize`

---

## 📝 Contributing

1. Fork & branch from `main`
2. `cargo clippy --all-targets --all-features -- -D warnings`
3. Add tests (`cargo tarpaulin --out Html`)
4. Submit PR + DCO sign-off

---

## 📜 License

Apache-2.0 © 2024 CanvasChain Contributors