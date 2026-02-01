# CanvasChain Symphony 🎼🖼️  

Modular, **artist-friendly** blockchain & NFT platform powered by Rust, gRPC and an event-driven micro-service mesh.

[![CI](https://github.com/your-org/canvaschain/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/canvaschain/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## ✨ Why CanvasChain?

Digital art keeps evolving—so should the chain it lives on. CanvasChain Symphony lets creators compose evolving, multi-layer NFTs that react to collectors, governance votes, DeFi staking and real-world events. Each **movement** of the symphony is a standalone Rust micro-service you can fork, extend or swap out.

* Proof-of-Inspiration (PoI) consensus blends PoS staking with VRF randomness to pick a “composer node.”
* Factory & Proxy patterns spawn user-defined NFT instruments with upgradeable logic.
* Event-driven gRPC mesh keeps services decoupled yet reactive.
* Strategy pattern supports pluggable crypto curves (Ed25519, BLS12-381, SPHINCS+, …).
* Observer + State Machine render live ownership & trait evolution.

---

## 🌐 High-Level Architecture

```text
 ┌─────────────────────────────────────────────────────────┐
 │                  Proof-of-Inspiration                  │
 │  (Validator Set + VRF randomness selects Composer)     │
 └──────┬───────────────┬───────────────┬───────────────┬─┘
        │               │               │               │
┌───────▼───────┐ ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
│ Composition   │ │ Minting   │   │ Remixing  │   │ Marketplace│
│ Service       │ │ Service   │   │ Service   │   │ Service    │
└───────────────┘ └───────────┘   └───────────┘   └───────────┘
        ▲               │               │               ▼
        │               │               │       ┌──────────────┐
        └───────────────┴───────────────┴──────▶│ Event Bus    │
                                                └─────▲────────┘
                                                      │
                                             ┌────────┴──────────┐
                                             │ Wallet Gateway    │
                                             └───────────────────┘
```

*RabbitMQ* (or NATS) is the default event bus, but the interface allows Kafka or Redis Streams.

---

## 🛠️ Micro-services

| Service           | Crate | Description                                                   | Port |
|-------------------|-------|---------------------------------------------------------------|------|
| `composer-core`   | `composer_core` | PoI consensus, block authoring, VRF beacon             | 7000 |
| `nft-factory`     | `nft_factory`   | Factory + Proxy pattern for upgradeable NFT contracts  | 7001 |
| `minting`         | `minting_srv`   | Mints initial NFT layers, IPFS pinning                | 7002 |
| `remixing`        | `remixing_srv`  | In-place NFT evolution & dynamic trait algorithms     | 7003 |
| `marketplace`     | `market_srv`    | Order-book & AMM hybrid marketplace                   | 7004 |
| `royalty-stream`  | `royalty_srv`   | Real-time royalty splits using Superfluid + gStream   | 7005 |
| `wallet-gateway`  | `wallet_gate`   | gRPC ↔️ JSON-RPC bridge for client wallets             | 7006 |
| `governance`      | `gov_srv`       | On-chain governance, quadratic voting, CIP upgrades    | 7007 |
| `defi-orchestra`  | `defi_orch`     | Staking, farming, yield routing for art tokens        | 7008 |
| `observatory`     | `observer_srv`  | Observer + State Machine for live rendering           | 7009 |

---

## 🚀 Quick Start

### 1. Clone & bootstrap

```bash
git clone https://github.com/your-org/canvaschain.git
cd canvaschain
cargo xtask bootstrap           # installs toolchains & pre-commit hooks
```

### 2. Start the stack (Docker)

```bash
docker compose up -d          # starts all 10 services + RabbitMQ + Postgres + IPFS
```

Logs are streamed using [`cargo-watch`](https://github.com/passcod/cargo-watch):

```bash
cargo xtask tail composer-core
```

### 3. Mint your first Canvas NFT

```bash
curl -X POST \
     -H "Content-Type: application/json" \
     -d '{"artist":"0xDEAD…BEEF","layers":[{"type":"svg","data":"<svg>…"}]}' \
     http://localhost:7002/v1/mint
```

The response includes the NFT CID, token-ID and real-time `ws://…/events` stream URL.

---

## 🧩 Example Rust Client

```rust
use tonic::transport::Channel;
use nft_factory::proto::{
    factory_client::FactoryClient,
    CreateInstrumentRequest,
    Curve,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // gRPC client with TLS
    let mut client = FactoryClient::connect("https://localhost:7001").await?;

    // Request a new upgradeable ERC-721 proxy with Ed25519 curve
    let req = tonic::Request::new(
        CreateInstrumentRequest {
            name:          "Glitchy Symphony #1".into(),
            symbol:        "GLTCH".into(),
            curve:         Curve::Ed25519.into(),
            royalty_bp:    500,      // 5%
            max_supply:    10_000,
            owner_address: "0xDEAD…BEEF".into(),
        }
    );

    let resp = client.create_instrument(req).await?;
    println!("Instrument deployed at: {}", resp.get_ref().proxy_address);
    Ok(())
}
```

See `examples/` for more end-to-end flows (mint, remix, list, bid).

---

## ⚙️ Configuration

Environment variables (or `.env`):

```text
CANVAS_NET_ID=1337
POSTGRES_URL=postgres://canvas:canvas@db:5432/canvas
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/%2f
IPFS_API=http://ipfs:5001
```

Each service also reads its own `[service].toml` for fine-tuning.

---

## 🏗️ Building From Source

```bash
cargo build --workspace --release
```

Features:

```bash
# enable post-quantum curves
cargo build -p composer_core --features pqc
```

Run tests:

```bash
cargo test --workspace  --all-features
```

Code coverage (`cargo-llvm-cov`):

```bash
cargo llvm-cov --workspace --html
```

---

## 🔒 Security Notes

1. Smart contracts are formally verified using `sea` & `prusti`.
2. Multi-sig governor keys recommended for production.
3. Audit reports live in `/audits/`.
4. Responsible disclosure: security@your-org.com.

---

## 👥 Contributing

1. Fork & create feature branch
2. Run `cargo fmt && cargo clippy --all-targets -- -D warnings`
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/)
4. Pull Request → automatic CI, integration tests, spellcheck

All contributors must sign the **Contributor License Agreement (CLA)**.

---

## 🗺️ Roadmap

- [x] Proof-of-Inspiration consensus MVP
- [x] Upgradeable NFT Factory
- [ ] zk-SNARK layer for anonymous bids
- [ ] Live generative audio channels
- [ ] Mobile Flutter wallet

---

## 📜 License

Apache 2.0 © 2023-present CanvasChain Symphony Contributors  
Third-party dependencies remain under their respective licenses.

---

_“Code is the canvas, randomness the muse.”_