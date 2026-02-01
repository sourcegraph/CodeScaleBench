```markdown
# Architecture Decision Record 003  
**Pluggable Cryptography Strategy**

| Status | Proposed |
| ------ | -------- |
| Date   | 2024-05-05 |
| Target release | `v0.8.0` (`CanvasChain Symphony`) |
| Supersedes | — |
| Related ADRs | ADR-001 Modular Micro-services, ADR-002 Event Bus |

---

## 1. Context

CanvasChain Symphony aims to be the de-facto playground for experimental digital art on the blockchain.  
Consequently, we must:

1. Support *multiple* signature schemes—`Ed25519` for mainstream wallets, `BLS12-381` for aggregated votes, and one or more post-quantum candidates (e.g. `Dilithium`, `Falcon`) for future-proofing.
2. Allow *runtime* selection of a scheme for each micro-service (e.g. the **governance** service needs BLS while **composition** might stick with Ed25519 for speed).
3. Offer *hot-swap* capabilities so research collectives can ship cryptographic experiments without forking or recompiling the **entire** chain.
4. Maintain *deterministic* behavior across WASM smart-contracts and native nodes so that consensus is never broken.
5. Remain *auditable* and *testable*—adding new crypto must not impair formal verification or fuzzing pipelines.

## 2. Decision

We will implement a **Strategy Pattern** that surfaces an `CryptoSuite` trait across all micro-services.  
A concrete suite is loaded **at startup** according to configuration (environment variable, CLI flag, or chain parameter) and injected via dependency-injection (gRPC metadata and event bus headers propagate the chosen suite).

Key points:

* The `CryptoSuite` trait is **no-std** compatible so that the same code compiles to WASM.
* Each suite resides in its own crate (`canvas_crypto_ed25519`, `canvas_crypto_bls`, `canvas_crypto_dilithium`, …) behind a *cargo feature*.
* We provide a *registry* that maps the on-chain enum discriminator (`CryptoAlgoId`) to a boxed trait object.
* Critical operations (sign, verify, aggregate, random_seed) are **generic** over the trait, avoiding `dyn` in hot paths.
* The consensus engine restricts the active set of suites to those that produce deterministic results for VRF.  
  A governance proposal can *enable* or *disable* a suite network-wide.

### High-level module layout

```
canvaschain/
 ├─ crates/
 │   ├─ crypto_api/       # defines trait + registry
 │   ├─ crypto_ed25519/
 │   ├─ crypto_bls/
 │   └─ crypto_dilithium/
 └─ services/
     ├─ governance/
     ├─ composition/
     └─ …
```

### Rust Interface (simplified)

```rust
// crypto_api/src/lib.rs
#![no_std]

use alloc::boxed::Box;
use core::fmt::Debug;

pub type Result<T> = core::result::Result<T, CryptoError>;

#[derive(Debug)]
pub enum CryptoError {
    InvalidKey,
    InvalidSignature,
    VerificationFailed,
    UnsupportedAlgo,
}

pub trait CryptoSuite: Send + Sync + Debug + 'static {
    const ID: CryptoAlgoId;

    fn generate_keypair(&self, rng: &mut dyn RngCore) -> Result<(PublicKey, PrivateKey)>;
    fn sign(&self, privkey: &PrivateKey, msg: &[u8]) -> Result<Signature>;
    fn verify(&self, pubkey: &PublicKey, msg: &[u8], sig: &Signature) -> Result<()>;

    // Optional for schemes that support it
    fn aggregate(&self, sigs: &[Signature]) -> Result<Signature> {
        Err(CryptoError::UnsupportedAlgo)
    }
}

pub enum CryptoAlgoId {
    Ed25519,
    Bls12381,
    Dilithium5,
    // …
}

pub struct SuiteRegistry {
    inner: spin::RwLock<hashbrown::HashMap<CryptoAlgoId, Box<dyn CryptoSuite>>>,
}

impl SuiteRegistry {
    pub const fn new() -> Self { /* … */ }
    pub fn register(&self, suite: Box<dyn CryptoSuite>) { /* … */ }
    pub fn get(&self, id: CryptoAlgoId) -> Result<&dyn CryptoSuite> { /* … */ }
}
```

## 3. Consequences

### Positive

* **Extensibility**: New crypto only requires a new crate implementing `CryptoSuite` and an entry in the registry.
* **Selective compilation**: Production nodes can compile with `--no-default-features --features "ed25519 bls"` to minimize the binary’s attack surface.
* **WASM parity**: Smart-contracts rely on the same trait, guaranteeing deterministic crypto across FFI boundaries.
* **Governance control**: The registry honors an on-chain allow-list, so malicious or broken suites can be disabled without a hard-fork.

### Negative / Trade-offs

* **Runtime dispatch** adds minimal overhead (~2–5 ns) when comparing trait object lookup vs. monomorphized code.
* **Larger codebase**: Each algorithm introduces external dependencies (`blst`, `pqcrypto`). Extra scrutiny is required for audits.
* **Complex migration** if the active suite for validators changes (requires key rotation mechanics).

## 4. Alternatives considered

1. **Compile-time feature gating only**  
   Reject because it forbids late activation of new algorithms by governance.
2. **Dynamic linking to system crypto libraries**  
   Reject due to WASM determinism concerns and platform-specific quirks.
3. **One-size-fits-all (ED25519 only)**  
   Reject; stifles experimentation and future-proofing against quantum attacks.

## 5. Implementation plan

1. Land `crypto_api` crate with trait, error types, and `SuiteRegistry`.  
2. Port existing ED25519 utilities to `canvas_crypto_ed25519`; register by default.  
3. Integrate `blst` and expose `canvas_crypto_bls`.  
4. Scaffold a proof-of-concept `canvas_crypto_dilithium` (behind `experimental` feature).  
5. Update all micro-services to inject `SuiteRegistry` from their service bootstrap.  
6. Add CLI flag `--crypto-suite=[ed25519|bls|dilithium]` for node operators.  
7. Extend governance pallet to manage the on-chain allow-list.  
8. Write cross-suite property tests and differential fuzzers (via `cargo-fuzz`).  
9. Perform third-party audit before enabling `dilithium` on mainnet.

## 6. Security considerations

* Using *multiple* cryptographic primitives increases the surface area for supply-chain attacks. Each suite is audited independently.
* Each suite’s implementation must meet **constant-time** guarantees.  
  CI integrates `criterion-ct` to detect data-dependent timing.
* The registry denies loading suites compiled with *unsafe optimizations* (e.g., `-C target-cpu=native`) unless explicitly whitelisted by validators.
* Key-material memory is zeroized via `zeroize` crate to mitigate side-channel leaks.

## 7. Reference implementation

Refer to `examples/demo_pluggable_crypto.rs` for a runnable showcase.  
The demo spins up a mock governance vote that swaps from Ed25519 to BLS mid-session and re-verifies historical signatures.

```
cargo run --example demo_pluggable_crypto --features "ed25519 bls"
```

---

*Prepared by*: `@rust_blockchain_nft_expert`  
*Reviewed by*: `core-team, cryptography-guild`  
*Last updated*: 2024-05-05
```