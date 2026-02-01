```markdown
# CanvasChain Symphony — Setup Guide
_A modular blockchain-NFT orchestration suite written in Rust_

---

## 1. Prerequisites

```bash
# 🐡 Rust toolchain (latest stable + wasm32 target)
curl https://sh.rustup.rs -sSf | sh
rustup target add wasm32-unknown-unknown

# 📦 Protocol Buffers compiler
brew install protobuf       # macOS
apt-get install -y protobuf-compiler # Debian/Ubuntu

# 🐳 Docker & Docker-Compose (for quick-start orchestration)
brew install --cask docker  # macOS
apt-get install -y docker.io docker-compose # Debian/Ubuntu

# 🗝️  OpenSSL development headers (crypto back-ends & TLS)
apt-get install -y libssl-dev pkg-config
```

> **Minimum Rust version:** `1.71.0` – validated via CI.

---

## 2. Repository Layout

```text
.
├── docs/                    # You are here
├── proto/                   # *.proto files (gRPC interface)
├── services/                # 10 micro-services (each independent binary crate)
│   ├── composer/
│   ├── conductor/
│   ├── curator/
│   └── …
├── gateway/                 # API gateway (GraphQL + REST façade)
├── pallets/                 # Substrate runtime modules (WASM)
├── tooling/                 # Developer CLI & code-gen helpers
├── examples/                # End-to-end demos + integration tests
└── Cargo.toml               # Workspace manifest
```

---

## 3. One-Command Quick-Start

Spin up a fully-fledged local cluster:

```bash
make devnet
```

`make devnet` performs the following under the hood:

1. Generates gRPC bindings (`prost`).
2. Builds all Rust binaries in `release` mode.
3. Stitches services together with `docker-compose.override.yml`.
4. Boots a 4-validator Substrate network with `Proof-of-Inspiration`.
5. Exposes:
   - gRPC: `localhost:50051`
   - GraphQL: `http://localhost:8080/graphql`
   - Polkadot-JS UI: `http://localhost:8000`

Stop and remove containers:

```bash
make down     # or: docker-compose down -v
```

---

## 4. Manual Build (Non-Docker)

### 4.1 Compile All Binaries

```bash
cargo build --workspace --release
```

Artifacts land in `target/release/`.

### 4.2 Launch Core Services

In separate terminals:

```bash
# ① Blockchain node (Substrate)
./target/release/canvas-node --dev --tmp --rpc-methods=Unsafe

# ② Event Bus (NATS)
nats-server -DV

# ③ Composer Microservice
RUST_LOG=info \
COMPOSER_NODE_URL=127.0.0.1:9944 \
cargo run -p composer --release
```

Use `just` recipes (`just --list`) for shortcuts.

---

## 5. Regenerating gRPC Stubs

Whenever you modify files under `proto/`:

```bash
protoc \
  --proto_path=proto \
  --prost_out=services \
  --tonic_out=services \
  proto/**/*.proto
```

Or simply:

```bash
make proto
```

The workspace makes heavy use of [tonic-build] with Prost, mapping Protobuf well-known types to `chrono` and `uuid` seamlessly.

---

## 6. End-to-End Smoke Test

```bash
cargo test --workspace --all-features
```

Expect output similar to:

```
running 192 tests
test composer::tests::mint_flow ... ok
test defi::tests::apy_math ... ok
…
```

---

## 7. Creating & Deploying a Custom NFT Instrument

Below is a minimal factory template:

```rust
// pallets/instrument-factory/src/lib.rs
pub struct GlitchSynthFactory;

impl InstrumentFactory for GlitchSynthFactory {
    fn instantiate(config: InstrumentConfig) -> Result<InstrumentId, DispatchError> {
        let id = Self::reserve_id()?;
        <Instruments<T>>::insert(
            id,
            Instrument {
                owner: config.owner,
                curve: CurveKind::Bls12381,
                metadata: config.metadata,
            },
        );
        Self::deposit_event(Event::InstrumentCreated { id, owner: config.owner });
        Ok(id)
    }
}
```

Compile to WASM and deploy:

```bash
cargo +nightly contract build -p instrument-factory
canvas-cli wasm deploy \
  --wasm target/ink/instrument-factory.wasm \
  --rpc-url ws://127.0.0.1:9944 \
  --suri //Alice
```

---

## 8. Advanced: Swapping Cryptographic Strategies

All crypto operations are abstracted behind the `SignatureScheme` trait:

```rust
pub trait SignatureScheme {
    type Public;
    type Private;
    type Signature;
    fn sign(msg: &[u8], sk: &Self::Private) -> Self::Signature;
    fn verify(msg: &[u8], sig: &Self::Signature, pk: &Self::Public) -> bool;
}

pub enum DefaultScheme {
    Ed25519,
}

impl SignatureScheme for DefaultScheme { … }
```

Compile-time selection:

```bash
# Ed25519 (default)
cargo build --features curve-ed25519

# BLS12-381 (threshold support)
cargo build --features curve-bls12-381

# XMSS (post-quantum)
cargo build --features curve-xmss
```

---

## 9. Environment Variables

| Variable                    | Purpose                                   | Default                |
|-----------------------------|-------------------------------------------|------------------------|
| `NODE_RPC_URL`             | Rust node RPC endpoint                    | `ws://localhost:9944` |
| `COMPOSER_SEED`            | sr25519 seed phrase for composer node     | `//Alice`             |
| `EVENT_BUS_URL`            | NATS server address                       | `nats://127.0.0.1:4222`|
| `DATABASE_URL`             | Postgres connection string                | `postgres://canvas:canvas@localhost/canvas` |
| `RUST_LOG`                 | Log level (`info`, `debug`, `trace`)      | `info`                |

Load via direnv or `.env`:

```dotenv
NODE_RPC_URL=ws://127.0.0.1:9944
COMPOSER_SEED=bottom drive obey lake curtain smoke basket hold race lonely fit walk
RUST_LOG=trace
```

---

## 10. Troubleshooting

| Symptom                                | Fix |
|----------------------------------------|-----|
| `error: linking with cc failed`        | Ensure `libssl-dev` & `clang` are installed |
| gRPC returns `UNIMPLEMENTED`           | Version mismatch – regenerate proto stubs |
| `PoolTimedOut` from `sqlx`             | Increase `MAX_CONNECTIONS` or use psql ≥ 14 |
| NFT not minting, tx stuck in `Ready`   | Check that `composer` service is elected (see logs) |

---

## 11. Contribution & Code Style

1. `rustfmt --check` enforced via CI.
2. Clippy `-D warnings`.
3. Conventional Commits (`feat:`, `fix:`, `chore:`…).

Create feature branches off `develop`, then open PRs targeting `develop`.

---

## 12. Glossary

- **Proof-of-Inspiration:** Hybrid PoS + VRF consensus selecting creatives to push on-chain art updates.
- **Instrument:** A composable NFT template (e.g., synthesizer, brush stroke engine).
- **Movement:** Discrete generative art variation emitted by a composer node.
- **Royalty Stream:** Continuous, time-based payout leveraging Superfluid-like DeFi contracts.

---

Happy hacking — _unleash your inner composer!_ 🎨🎶
```