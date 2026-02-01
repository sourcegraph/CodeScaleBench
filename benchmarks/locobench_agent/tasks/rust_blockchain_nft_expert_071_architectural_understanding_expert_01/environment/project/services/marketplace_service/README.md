```markdown
# CanvasChain Symphony – Marketplace Service
`services/marketplace_service`

The Marketplace Service powers the primary and secondary exchange of multilayer NFTs
(“Instruments”) on CanvasChain Symphony.  It exposes a gRPC interface for listing,
bidding, buying, and royalty-settlement, publishes domain events on the mesh-bus,
and persists state changes in PostgreSQL using Diesel.  
The service is designed to be **stateless**; business state is maintained in the
database and propagated through events.  
High-throughput order-matching is achieved with an _in-memory order-book_ backed
by **MVCC snapshots** so reads never block writes.

---

## Table of Contents
1. Responsibilities & Guarantees  
2. Architecture Diagram  
3. gRPC Service Definition  
4. Event-Bus Contracts  
5. Domain Model (Rust)  
6. Database Migrations  
7. Configuration & Environment  
8. Running Locally  
9. Integration Test Example  
10. Extending / Plug-Ins  
11. Troubleshooting & FAQ  

---

## 1. Responsibilities & Guarantees
| Capability                     | SLA / Contract                                             |
|--------------------------------|------------------------------------------------------------|
| List NFT for sale              | ≤ 150 ms p95 latency                                       |
| Purchase NFT                   | Atomic ownership + fund transfer on-chain                  |
| Accept bid / auction settlement| Deterministic matching, replayable via event log           |
| Royalty stream distribution    | ≤ 30 s settlement delay, idempotent payouts                |
| Data Consistency               | Strict serializable transactions for write paths           |
| Observability                  | OpenTelemetry tracing + Prometheus metrics                 |

---

## 2. Architecture Diagram
```text
┌───────────────┐      gRPC       ┌────────────────┐
│   REST Proxy  │ ───────────────►│ MarketplaceSvc │────┐
└───────────────┘                 └────────────────┘    │
        ▲                               ▲              │
        │                               │ Diesel ORM   │
        │                               ▼              │
  Web / Mobile                  ┌────────────────┐     │
    Clients                     │  PostgreSQL     │◄───┘
                                └────────────────┘
                                       ▲
                                       │ Event(bincoded)
                                       ▼
                                 ┌───────────────┐
                                 │ Canvas Bus    │
                                 └───────────────┘
```

---

## 3. gRPC Service Definition
```proto
// proto/marketplace.proto
syntax = "proto3";
package canvas.marketplace;

service Marketplace {
  rpc ListInstrument(ListInstrumentRequest) returns (ListInstrumentResponse);
  rpc BuyInstrument(BuyInstrumentRequest)   returns (BuyInstrumentResponse);
  rpc PlaceBid(PlaceBidRequest)             returns (PlaceBidResponse);
  rpc AcceptBid(AcceptBidRequest)           returns (AcceptBidResponse);
  rpc StreamEvents(EventsRequest)           returns (stream MarketplaceEvent);
}

message ListInstrumentRequest {
  string instrument_id = 1;
  uint64 price_microunit = 2;
  uint32 expiration_secs = 3;
}

message BuyInstrumentRequest  { string listing_id = 1; string buyer_wallet = 2; }
message BuyInstrumentResponse { string tx_hash     = 1; }

message MarketplaceEvent {
  oneof event {
    ListingCreated   listing_created   = 1;
    InstrumentSold   instrument_sold   = 2;
    BidPlaced        bid_placed        = 3;
    BidAccepted      bid_accepted      = 4;
    RoyaltySettled   royalty_settled   = 5;
  }
}
```

The Rust implementation is generated with `tonic-build` during `build.rs`.

---

## 4. Event-Bus Contracts
All domain events are published to the **Canvas Mesh-Bus** (NATS JetStream) under the
subject hierarchy: `marketplace.<event>`.  Payloads are CBOR-encoded for forward-compatibility.

| Subject                      | Schema (Rust Struct)                  |
|------------------------------|---------------------------------------|
| marketplace.listing.created  | `ListingCreatedV1`                    |
| marketplace.instrument.sold  | `InstrumentSoldV1`                    |
| marketplace.bid.placed       | `BidPlacedV1`                         |
| marketplace.royalty.settled  | `RoyaltySettledV1`                    |

Event versions are semver’d; newer readers **must** handle unknown fields.

---

## 5. Domain Model (Rust)
```rust
use chrono::{DateTime, Utc};
use uuid::Uuid;
use bigdecimal::BigDecimal;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum OrderType {
    FixedPrice,
    EnglishAuction,
    DutchAuction { start_price: BigDecimal, end_price: BigDecimal },
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Listing {
    pub id:           Uuid,
    pub instrument_id: Uuid,
    pub seller:       String, // bech32 wallet addr
    pub order_type:   OrderType,
    pub price:        BigDecimal,
    pub expires_at:   DateTime<Utc>,
    pub created_at:   DateTime<Utc>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Bid {
    pub id:         Uuid,
    pub listing_id: Uuid,
    pub bidder:     String,
    pub amount:     BigDecimal,
    pub placed_at:  DateTime<Utc>,
}
```
The structs above are mapped to database tables using `diesel::Queryable` &
`diesel::Insertable` (see `src/schema.rs`).

---

## 6. Database Migrations
```sql
-- migrations/2024-05-20-220000_create_listings/up.sql
CREATE TABLE listings (
    id              UUID PRIMARY KEY,
    instrument_id   UUID NOT NULL,
    seller          TEXT NOT NULL,
    order_type      JSONB NOT NULL,
    price           NUMERIC(36, 18) NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_listings_instrument ON listings(instrument_id);

-- migrations/2024-05-20-220100_create_bids/up.sql
CREATE TABLE bids (
    id           UUID PRIMARY KEY,
    listing_id   UUID REFERENCES listings(id) ON DELETE CASCADE,
    bidder       TEXT NOT NULL,
    amount       NUMERIC(36, 18) NOT NULL,
    placed_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_bids_listing ON bids(listing_id);
```

---

## 7. Configuration & Environment
| Variable                       | Default          | Description                                   |
|--------------------------------|------------------|-----------------------------------------------|
| `MARKETPLACE__PG_URL`          | postgres://...   | PostgreSQL connection URI                     |
| `MARKETPLACE__BUS_NATS_URL`    | nats://127.0.0.1 | Mesh-Bus broker URL                           |
| `MARKETPLACE__GRPC_ADDR`       | 0.0.0.0:6001     | gRPC bind address                             |
| `MARKETPLACE__SIGNING_KEY`     | (none)           | Hex-encoded secp256k1 key for on-chain txs    |
| `RUST_LOG`                     | info             | Log level (uses `tracing_subscriber`)         |

Configuration is loaded via [`config`](https://docs.rs/config) merging:
`default.toml` → `$(ENV).toml` → environment variables.

---

## 8. Running Locally
```bash
# 1. Start dependencies
docker compose -f infra/docker-compose.yml up -d postgres nats

# 2. Run database migrations
cargo install diesel_cli --no-default-features --features postgres
DATABASE_URL=postgres://canvas:canvas@localhost:5432/canvas diesel migration run

# 3. Start the service with hot-reload
cargo watch -x 'run --package marketplace_service'
```

---

## 9. Integration Test Example
```rust
#[tokio::test]
async fn it_lists_and_buys() {
    let mut client = MarketplaceClient::connect("http://[::1]:6001").await.unwrap();

    // 1. List an NFT
    let list_res = client.list_instrument(ListInstrumentRequest {
        instrument_id: Uuid::new_v4().to_string(),
        price_microunit: 1_000_000u64,
        expiration_secs: 86_400,
    }).await.unwrap().into_inner();

    // 2. Buy it
    let buy_res = client.buy_instrument(BuyInstrumentRequest {
        listing_id: list_res.listing_id,
        buyer_wallet: "wallet1p5...".into(),
    }).await.unwrap().into_inner();

    assert!(buy_res.tx_hash.starts_with("0x"));
}
```

Run with:
```bash
cargo test -p marketplace_service -- --nocapture
```

---

## 10. Extending / Plug-Ins
The Marketplace leverages the **Strategy Pattern** for _fee calculation_:

```rust
pub trait FeePolicy: Send + Sync {
    fn taker_fee(&self, price: &BigDecimal) -> BigDecimal;
    fn maker_fee(&self, price: &BigDecimal) -> BigDecimal;
}

pub struct FlatFee {
    pub bps: u32 // basis points, e.g. 25 = 0.25%
}

impl FeePolicy for FlatFee {
    fn taker_fee(&self, price: &BigDecimal) -> BigDecimal {
        price * BigDecimal::from(self.bps) / BigDecimal::from(10_000u32)
    }
    fn maker_fee(&self, price: &BigDecimal) -> BigDecimal { BigDecimal::zero() }
}
```
Drop your own policy in `src/fees/` and register via Rocket’s `Figment` or
`feature = "dynamic-fees"`.

---

## 11. Troubleshooting & FAQ
Q: _“I’m seeing `deadlock detected` errors in logs”_  
A: Ensure you are on PostgreSQL ≥ 14.2; the advisory lock upgrade reduces deadlocks
in high-concurrency auctions.

Q: _“Events are not replaying on cold start”_  
A: Verify `JetStream` stream `marketplace.*` is configured with `max_msgs=-1` and
`retention=workqueue`.

---

© 2024 CanvasChain Foundation – Licensed under Apache-2.0
```