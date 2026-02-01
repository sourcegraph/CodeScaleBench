```markdown
# 🎻 Royalty Service  
CanvasChain Symphony – `services/royalty_service`

The Royalty Service is a standalone **gRPC** micro-service that meters, accrues and streams
on-chain royalty revenues to NFT creators, collaborators, DAOs and liquidity stakers.
It embodies the **“Composer’s Tip Jar”** of the CanvasChain Symphony:  
every time an artwork changes hands, is remixed, or earns DeFi yield, the service
calculates the share owed to every participant and settles it in-chain – in real time,
per block.

---

## ✨ Key Responsibilities
| Responsibility                           | Pattern / Subsystem           |
|------------------------------------------|--------------------------------|
| Calculate primary-sale royalties         | Factory + Strategy             |
| Accrue secondary-market fees             | Observer (Marketplace events)  |
| Stream periodic DeFi yield               | State Machine (per NFT)        |
| Support pluggable fee curves & splits    | Strategy Pattern               |
| Emit _RoyaltySettled_ events             | Event-Driven / gRPC            |
| Expose analytics & health endpoints      | gRPC + `tokio-metrics`         |

---

## 🗺️ Directory Layout
```text
royalty_service/
├── Cargo.toml
├── README.md            ← You are here
├── src/
│   ├── bin/
│   │   └── royaltyd.rs  ← Tokio entrypoint
│   ├── domain/          ← Domain logic (DDD)
│   ├── infra/           ← DB, gRPC, Event-Bus adapters
│   └── tests/
└── proto/
    └── royalty.proto
```

---

## 📚 High-Level Flow

```mermaid
sequenceDiagram
    participant M as Marketplace Service
    participant R as Royalty Service
    participant B as Substrate Runtime
    participant U as End-User Wallet

    M->>R: SaleEvent { nft_id, price, seller, buyer }
    R->>R: Compute royalties via FeeStrategy
    alt On-chain settlement
        R->>B: royalty::settle { nft_id, splits[], total }
        B-->>R: TxReceipt { block_hash }
        R-->>M: RoyaltySettled { receipt }
        R-->>U: StreamUpdate (WebSocket)
    else Off-chain accrual
        R->>R: Accrue to internal ledger
    end
```

---

## 📜 gRPC API Reference

```proto
syntax = "proto3";

package canvaschain.royalty.v1;

option rust_module = "royalty_rs";

service RoyaltyService {
  // Returns current royalty configuration for a single NFT.
  rpc GetRoyaltyConfig(GetRoyaltyConfigRequest)
      returns (GetRoyaltyConfigResponse);

  // Updates (or creates) royalty splits; requires nft_owner signature.
  rpc UpsertRoyaltyConfig(UpsertRoyaltyConfigRequest)
      returns (UpsertRoyaltyConfigResponse);

  // Settles outstanding royalties for an NFT up to the latest finalized block.
  rpc SettleRoyalties(SettleRoyaltiesRequest)
      returns (SettleRoyaltiesResponse);

  // Server-side streaming of royalty events.
  rpc StreamRoyaltyEvents(StreamRoyaltyEventsRequest)
      returns (stream RoyaltyEvent);
}
```

proto generated with [`tonic-build`](https://docs.rs/tonic-build) in `build.rs`.

---

## 🧩 Domain Model (Rust)

```rust
/// Percentage with 2-dec fixed precision (0.01% resolution)
#[derive(Clone, Copy, Debug, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct Bps(u16); // 1 bps == 0.01%

/// Represents a single royalty split entry.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoyaltySplit {
    /// AccountId on CanvasChain (ss58 string).
    pub account: String,
    /// Fee share in basis points (0-10_000).
    pub share: Bps,
    /// Optional cliff block; before this block user receives nothing.
    pub cliff_block: Option<u32>,
}

/// Persisted configuration per NFT.
/// PK: nft_id (32-byte hash)
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoyaltyConfig {
    pub nft_id: [u8; 32],
    pub primary_splits: Vec<RoyaltySplit>,
    pub secondary_splits: Vec<RoyaltySplit>,
    /// Deterministic strategy used to compute dynamic splits.
    pub fee_strategy: FeeStrategyKind,
    /// Last block royalties were settled up to.
    pub last_settled_block: u32,
}
```

---

## ⚙️ Pluggable Fee Strategy

```rust
/// Strategy Pattern: swap at runtime without recompilation.
pub trait FeeStrategy: Send + Sync {
    /// Computes split based on sale context (primary, secondary, remix, etc.)
    fn compute_splits(
        &self,
        ctx: &SaleContext,
        cfg: &RoyaltyConfig,
    ) -> anyhow::Result<Vec<CalculatedSplit>>;
}

pub enum FeeStrategyKind {
    Fixed,                // naive BPS splits
    BondingCurve,         // dynamic % based on supply
    TimeDecaying,         // royalties fade out over time
    CommunityWeighted,    // governance decides weights
    Custom(String),       // loaded from Wasm blob
}
```

Strategies live under `src/domain/strategy`.  
`BondingCurve` is default, using a cubic curve to incentivize early supporters.

---

## 🛢️ Persistence

| Component     | Tech                                    | Notes                                   |
|---------------|-----------------------------------------|-----------------------------------------|
| Ledger store  | PostgreSQL (`sqlx`)                     | ACID rows per NFT per account per block |
| Cache         | `redis`                                 | Hot in-memory balances / config         |
| Snapshotting  | Substrate Off-chain Workers             | On-chain idempotent checkpointing       |

Postgres schema snippet:

```sql
CREATE TABLE royalty_ledger (
    id            BIGSERIAL PRIMARY KEY,
    nft_id        BYTEA        NOT NULL,
    account       TEXT         NOT NULL,
    amount        NUMERIC(78)  NOT NULL, -- 10^18 precision
    settled_block INTEGER      NOT NULL,
    UNIQUE (nft_id, account, settled_block)
);
```

`sqlx migrate run` applies migrations at startup.

---

## 🚀 Running Locally

```bash
# 1. launch postgres & redis
docker compose up -d db cache

# 2. compile and run
cargo run -p royalty_service --bin royaltyd
```

Set environment variables (see `.env.example`):

```dotenv
DATABASE_URL=postgres://canvas:canvas@localhost:5432/royalty
REDIS_URL=redis://127.0.0.1/
CANVAS_NODE_WS=ws://127.0.0.1:9944
JWT_PUBLIC_KEY_PATH=./keys/jwt.pub
```

---

## 🔐 Security Considerations
1. **Re-entrancy**: on-chain payout is executed via Substrate’s
   `pallet_balances::transfer` which is non-reentrant.
2. **Signature spoofing**: `UpsertRoyaltyConfig` verifies signatures off-chain
   using the pluggable crypto Strategy (Ed25519/BLS/post-quantum).
3. **Rate limiting**: gRPC endpoints are protected by `tower::limit::RateLimit`.
4. **Data integrity**: every payout is traced with
   [`opentelemetry`](https://crates.io/crates/opentelemetry) spans, hashed and
   published to the Event Bus (`NATS`) for auditability.

---

## 🧪 Testing Matrix

| Test Type            | Tooling                  | CI Stage |
|----------------------|--------------------------|----------|
| Unit                 | `cargo test`             | ✅       |
| Property-based       | `proptest`               | ✅       |
| Integration (gRPC)   | `cucumber-rust`          | ✅       |
| DB Migrations        | `sqlx` offline checks    | ✅       |
| Fuzz (fee strategies)| `cargo fuzz`             | nightly  |

Run all with:

```bash
just test-all     # requires `just` command runner
```

---

## 📈 Observability

* **Metrics**: Prom-compatible via `opentelemetry-prometheus`.
  * `royalty_settlements_total`
  * `royalty_backlog_gauge`
* **Tracing**: Distributed traces with Jaeger.
* **Health**: `grpc.health.v1.Health/Check` + `/livez` & `/readyz` HTTP probes.

---

## 🤝 Contributing

1. Fork & clone repo  
2. `make dev-up` – spins up local stack  
3. Write code & tests  
4. Run `pre-commit run --all-files`  
5. PRs must pass all CI workflows and get 2 approvals

See `CONTRIBUTING.md` for coding style & commit message convention.

---

## 📄 License

CanvasChain Symphony is dual-licensed under
`Apache-2.0` and `MIT`. You may choose either license
when using or distributing the code.

> _Made with 🤍 by generative minds._

```