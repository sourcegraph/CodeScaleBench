# CanvasChain Symphony – Wallet Service

The Wallet Service is a self-contained microservice that manages cryptographic identities, signing operations, and on-chain asset tracking for CanvasChain Symphony.  
It exposes a gRPC API, publishes domain events to the cluster event-bus, and follows the Strategy pattern to swap cryptographic curves (Ed25519, BLS12-381, Kyber) at runtime without downtime.

---

## Features
- Hierarchical Deterministic (HD) key-derivation (BIP-44-like)  
- Curve-agnostic signing (`Ed25519`, `BLS12_381`, `Kyber1024`)  
- Multi-sig & social-recovery vaults  
- Watch-only observers for galleries & DAO treasuries  
- Encrypted keystore (Argon2id, ChaCha20-Poly1305)  
- Event sourcing & snapshotting for fast recovery  
- gRPC API with JWT or mTLS auth  
- Outgoing WebHook for real-time UX updates  
- Prometheus metrics & OpenTelemetry tracing  

---

## Directory Layout
```
wallet_service/
├── Cargo.toml
├── README.md          ← you are here
├── proto/             ← gRPC definitions
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── lib.rs
│   ├── crypto/
│   │   ├── mod.rs
│   │   ├── ed25519.rs
│   │   ├── bls.rs
│   │   └── kyber.rs
│   ├── grpc/
│   │   ├── mod.rs
│   │   └── service.rs
│   ├── handlers/
│   │   ├── commands.rs
│   │   └── queries.rs
│   └── storage/
│       ├── mod.rs
│       └── rocksdb.rs
└── tests/
    └── integration.rs
```

---

## gRPC Service Definition (excerpt)

```proto
syntax = "proto3";

package wallet.v1;

service WalletService {
  rpc CreateWallet (CreateWalletRequest) returns (CreateWalletResponse);
  rpc ImportWallet (ImportWalletRequest) returns (ImportWalletResponse);
  rpc SignTransaction (SignTxRequest) returns (SignTxResponse);
  rpc GetBalance (GetBalanceRequest) returns (GetBalanceResponse);
  rpc StreamEvents (EventsRequest) returns (stream WalletEvent);
}

message CreateWalletRequest {
  bytes entropy = 1;                 // optional, 16–64 bytes
  Curve curve  = 2;                  // ED25519 by default
}

enum Curve {
  CURVE_ED25519   = 0;
  CURVE_BLS12_381 = 1;
  CURVE_KYBER1024 = 2;
}

message CreateWalletResponse {
  string wallet_id = 1;
  bytes  public_key = 2;
  bytes  address = 3;
}
```

The full `.proto` file lives in `proto/` and is compiled using `tonic-build` during `cargo build`.

---

## Running Locally

```bash
# 1. Launch RocksDB & migrate schemas
cargo run --bin wallet_service migrate

# 2. Start the service with the default Ed25519 curve
cargo run --bin wallet_service
```

Default configuration is loaded from `wallet.yaml` (see sample below) and can be overridden via environment variables prefixed with `WALLET_`.

### Configuration (`wallet.yaml`)

```yaml
server:
  bind_addr: "0.0.0.0:6002"
  tls:
    cert_path: "./certs/server.pem"
    key_path: "./certs/server.key"

storage:
  rocksdb_path: "./data/rocksdb"

security:
  jwt_secret: "${WALLET_JWT_SECRET}"
  keystore_password: "${WALLET_KEYSTORE_PASSWORD}"

curve: "Ed25519"       # or BLS12_381 / Kyber1024

metrics:
  prometheus: "0.0.0.0:9102"
  otlp_endpoint: "http://localhost:4317"
```

---

## Sample Client (Rust)

```rust
use wallet_proto::wallet::v1::wallet_service_client::WalletServiceClient;
use wallet_proto::wallet::v1::{CreateWalletRequest, Curve};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut client = WalletServiceClient::connect("http://127.0.0.1:6002").await?;

    let request = tonic::Request::new(CreateWalletRequest {
        entropy: rand::random::<[u8; 32]>().to_vec(),
        curve: Curve::CurveEd25519.into(),
    });

    let response = client.create_wallet(request).await?.into_inner();
    println!("New wallet: {}", response.wallet_id);

    Ok(())
}
```

---

## Event Bus Topics

| Topic                           | Payload                                   |
|---------------------------------|-------------------------------------------|
| `wallet.created`                | `WalletCreated { wallet_id, curve }`      |
| `wallet.balance.updated`        | `BalanceUpdated { wallet_id, delta }`     |
| `wallet.tx.signed`              | `TxSigned { wallet_id, tx_hash }`         |
| `wallet.keystore.locked`        | `KeystoreLocked { wallet_id }`            |

Messages are published via NATS and conform to the cluster-wide JSON Schema registry.

---

## Metrics & Instrumentation

- `wallet_created_total{curve="Ed25519"}`  
- `wallet_keystore_unlock_seconds_bucket`  
- `wallet_sign_tx_failed_total{error="InvalidNonce"}`  

OpenTelemetry spans are propagated over gRPC trace context for fully-distributed tracing across the Symphony.

---

## Security Considerations

1. Keystores encrypted with `Argon2id` (3 passes, 64 MiB memory) + `ChaCha20-Poly1305`.
2. In-memory private keys are zeroized on drop (`zeroize` crate).
3. mTLS between microservices (`rustls`, `ring`).
4. Automated fuzzing via `cargo-fuzz` on signing parsers.
5. Compile-time `deny(unsafe_code)` gate with regular CI checks.

---

## Testing

```bash
# Unit tests
cargo test -p wallet_service --lib -- --nocapture

# gRPC contract tests (requires server running)
cargo test -p wallet_service --test integration

# Lint & formatting
cargo clippy --all-targets --all-features
cargo fmt -- --check
```

---

## CLI Cheatsheet

```bash
# Create a new Ed25519 wallet
wallet-cli create

# Import from mnemonic
wallet-cli import --mnemonic "fold media graceful..."
                 --curve BLS12_381

# Sign a transaction JSON file
wallet-cli sign ./txs/auction_bid.json --wallet-id 0xa415

# Watch-only DAO treasury
wallet-cli watch 0xdeadbeef...cafebabe
```

---

## Roadmap

- Ledger / YubiHSM hardware-wallet bridge
- Threshold-BLS signature aggregation
- MPC wallet for collaborative collectives
- Post-quantum default curve once NIST finalizes

---

## Contributing

1. Fork & clone
2. `make setup` (installs git hooks and pre-commit)
3. Follow the conventional commit guidelines
4. Run `cargo test && cargo clippy`
5. Submit a PR with a detailed description

---

© CanvasChain Labs – released under Apache 2.0.