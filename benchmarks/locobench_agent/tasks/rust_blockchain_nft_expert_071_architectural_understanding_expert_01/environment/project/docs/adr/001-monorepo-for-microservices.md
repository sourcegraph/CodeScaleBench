# 001 – Adopt a Monorepo for Rust Microservices

Status: **Approved**  
Date: 2024-06-17  
Tags: `repository`, `dev‐experience`, `ci/cd`, `rust`, `microservices`

---

## Context

CanvasChain Symphony orchestrates ten specialized Rust microservices—`composition`, `minting`, `remixing`, `marketplace`, `royalty`, `wallet`, `governance`, `token-management`, `defi`, and `orchestrator`.  
Early prototypes lived in independent Git repositories. While this respected bounded context, it created friction:

* **Version skew**: cross-service protocol buffers, domain types and cryptographic primitives (e.g., our pluggable `CurveStrategy`) drifted, forcing tedious cherry-picks.
* **Atomic evolution**: a change to a shared crate (e.g., `canvas-chain-primitives`) required synchronized releases across repos; partial updates risked network halts.
* **CI💰**: each repo ran its own CI minutes; caching was duplicated and expensive.
* **Dev onboarding**: cloning ten repos, wiring SSH deploy keys and remembering divergent release processes slowed contributors.

Rust’s native support for [Cargo workspaces](https://doc.rust-lang.org/book/ch14-03-cargo-workspaces.html) and our need for atomic, protocol-grade versioning make a monorepo attractive.

## Decision

We will:

1. Move all Rust microservices, shared crates (`*-primitives`, `*-proto`, etc.) and infrastructure scripts into a single repository named `canvaschain-symphony`.
2. Organize code using Cargo workspaces:

```
canvaschain-symphony/
├── Cargo.toml            # root workspace manifest
├── crates/
│   ├── primitives/
│   ├── proto/
│   ├── curve-strategy/
│   └── …
└── services/
    ├── composition/
    ├── minting/
    └── …
```

3. Keep **one** `main` branch protected by mandatory checks. Feature work occurs in PRs with review from at least one other domain owner.
4. Maintain **semantic versioning per crate** using `cargo-release`. A change to `canvaschain-primitives` bumps only that crate, but CI blocks merging unless all dependants still compile.
5. Employ a top-level `Makefile.toml` (cargo-make) for common developer tasks (`make db`, `make dev-up`, etc.).
6. Leverage GitHub Actions’ shared cache: incremental build artifacts (~650 MB) are reused across microservices, cutting CI by ~55 %.
7. Use code-owners to preserve microservice boundaries:

```
# CODEOWNERS
/services/composition/ @art-algo @orchestrator
/services/marketplace/ @defi-team
/crates/primitives/ @core-protocol
```

## Consequences

### Positive

* **Atomic protocol upgrades** across services—e.g., adding a new VRF proof to `ProofOfInspiration` requires one PR, one commit hash.
* Unified **tooling and linting** (`cargo fmt`, `cargo clippy`, `cargo udeps`, `cargo deny`).
* **Consistent release pipeline**: `cargo make release` builds Docker images for all changed services with version tags derived from Git metadata.
* **Simplified local dev**: `make dev-up` spins up all services via `docker-compose`, seeded with testnet state.
* Easier **refactoring**: `cargo fix --workspace` can propagate changes instantly.

### Negative

* Repo size grows quickly (projected 2 GB in 18 months). We will enforce **Git LFS** for large fixtures (e.g., generative art sample sets).
* Potential for **cross-team merge conflicts**; mitigated by conventional commits and smaller PR scope.
* Accidental **hidden coupling**; owners must respect microservice boundaries and avoid reaching into sibling domains.

### Mitigations

* **Bazel remote cache** is on our roadmap for even faster incremental builds.
* Introduce `cargo hack` to run feature-matrix tests only on changed crates.
* Quarterly **module sociability reviews** to detect leakage in service boundaries.

---

## Cargo Workspace Manifest (excerpt)

```toml
[workspace]
members = [
    "crates/primitives",
    "crates/proto",
    "crates/curve-strategy",
    "services/composition",
    "services/minting",
    "services/remixing",
    "services/marketplace",
    "services/royalty",
    "services/wallet",
    "services/governance",
    "services/token-management",
    "services/defi",
    "services/orchestrator",
]

[workspace.dependencies]
tokio          = { version = "1.37", features = ["rt-multi-thread", "macros"] }
prost          = "0.12"
tonic          = { version = "0.11", features = ["transport"] }
tracing        = "0.1"
anyhow         = "1"
thiserror      = "1"
serde          = { version = "1", features = ["derive"] }
async-trait    = "0.1"
```

---

## Adoption Plan

1. Freeze external repos; merge them into the new `canvaschain-symphony` monorepo preserving commit history (`git subtree add`).
2. Update CI to run workspace-aware commands (`cargo test --workspace`).
3. Notify the community via Discord, update contributor docs, schedule “dev-env day” to migrate local clones.
4. Archive old repositories as read-only.

---

## References

* RFC-0396 – “Cargo Workspaces in Large Rust Projects”  
* ADR-004 – “Event Bus over gRPC”  
* Google SRE Book, Chap. 5 – “Monorepos at Scale”