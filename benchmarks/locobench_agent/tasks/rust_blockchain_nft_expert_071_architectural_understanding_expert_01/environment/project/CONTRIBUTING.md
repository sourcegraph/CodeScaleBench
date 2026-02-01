```markdown
# Contributing to **CanvasChain Symphony**

First off, thank you 💜 for taking the time to contribute.  
CanvasChain Symphony is a community–driven Rust project and every pull-request,
issue, and suggestion makes the ecosystem stronger for digital artists all
around the globe.

This document describes the preferred workflow for contributing code,
documentation, tests, or ideas. **Please read it carefully before opening a
pull-request.**

---

## Table of Contents
1. Getting Started
2. Repository Layout
3. Branching & Versioning
4. Coding Guidelines
5. Testing & QA
6. gRPC / Protobuf Workflow
7. Commit Message Convention
8. Continuous Integration
9. Security Policy
10. Community Guidelines & Code of Conduct
11. FAQ

---

## 1 Getting Started

### 1.1 Prerequisites

| Tool            | Minimum Version | Notes                                            |
| --------------- | --------------- | ------------------------------------------------ |
| Rust Toolchain  | **1.74**        | Follow _rust-lang.org/tools/install_ for setup.  |
| Cargo           | Bundled         | Use `+stable` unless otherwise stated.           |
| `cargo-make`    | 0.37            | Task runner (`cargo install cargo-make`).        |
| `protoc`        | 3.20            | Needed for gRPC code generation.                 |
| `buf` (optional)| 1.26            | Protobuf linting / breaking-change detection.    |
| `just` (optional)| 1.15           | Command runner; alternative to `cargo-make`.     |

```bash
rustup override set stable          # pin toolchain
cargo install cargo-make --locked   # task runner
cargo install cargo-nextest --locked # faster test harness
```

---

### 1.2 Bootstrapping Your Environment

```bash
# Clone the monorepo
git clone https://github.com/CanvasChain/symphony.git
cd symphony

# Fetch submodules (e.g. UI, docs, examples)
git submodule update --init --recursive

# Prepare dev containers (optional)
cargo make dev-container-build
```

`cargo make` provides helpful tasks for most workflows:

```bash
cargo make help      # list tasks
cargo make start     # run all microservices locally
cargo make lint      # run rustfmt + clippy
cargo make e2e       # spin up an ephemeral test-net and execute integration tests
```

---

## 2 Repository Layout

```
.
├── crates/                  # Rust workspaces
│   ├── chain/               # Substrate-based L1
│   ├── nft-engine/          # NFT state-machine library
│   ├── composer/            # Proof-of-Inspiration node
│   └── ...
├── services/                # gRPC microservices
│   ├── composition/
│   ├── minting/
│   ├── marketplace/
│   └── ...
├── proto/                   # .proto files
├── docs/                    # Book & RFCs
└── tools/                   # Dev-ops scripts
```

Each **microservice** lives in `services/<name>` and is published as its own
Crate (`service-<name>`). Shared libraries go under `crates/`.

---

## 3 Branching & Versioning

We follow **GitHub Flow** with long-lived `main` and optional release branches.

```text
main ──┬─► v0.4.x (release branch)
       │
       ├── feature/trait-evolution-hashmap
       ├── bugfix/marketplace-fee-rounding
       └── chore/update-clippy
```

1. Fork the repo and create a **topic branch** from `main`.
2. Rebase onto `main` frequently to reduce merge friction.
3. Submit a PR targeting `main` (unless patching an active release branch).

Semantic Versioning (SemVer) applies to all published crates.

---

## 4 Coding Guidelines

### 4.1 Rust Style

* `rustfmt` and `clippy` must pass _with `--all-targets --all-features -- -D warnings`_
  before a PR is eligible for review.
* Favor **explicitness** over magic. Excessive `unsafe` will be rejected unless
  absolutely necessary **and** accompanied by thorough safety comments.
* Prefer **composability** (small, reusable traits) to inheritance-like enums.

### 4.2 Recommended Patterns

* **Factory Pattern** for spawning new smart-contract templates.
* **Strategy Pattern** to plug additional crypto curves (Ed25519 ⇨ BLS).
* **Observer Pattern** drives real-time ownership dashboards.
* **State Machine Pattern** governs NFT layer evolution.

### 4.3 Error Handling

Use `thiserror` for domain errors, and `anyhow` **only** at application
boundaries (CLI, HTTP, gRPC). Example:

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum MintingError {
    #[error("insufficient balance; required {required}, available {available}")]
    InsufficientBalance { required: u128, available: u128 },

    #[error("invalid metadata URI")]
    InvalidMetadata(#[from] url::ParseError),

    #[error(transparent)]
    Storage(#[from] sled::Error),
}
```

---

## 5 Testing & QA

| Layer               | Tooling                 | Command                                |
| ------------------- | ----------------------- | -------------------------------------- |
| Unit tests          | `cargo nextest`         | `cargo make test`                      |
| Integration tests   | `cucumber-rs`           | `cargo make e2e`                       |
| Property testing    | `proptest`              | `cargo nextest --features fuzz`        |
| Benchmarking        | `criterion`             | `cargo make bench`                     |
| Static analysis     | `clippy`, `rust-analyzer`| `cargo make lint`                      |

CI runs all of the above on push and PR.

---

## 6 gRPC / Protobuf Workflow

1. Edit or add `.proto` files in `proto/`.  
   When changing existing services, bump the minor version and update service
   namespace, e.g. `canvaschain.marketplace.v1beta2`.
2. Run `buf breaking --against main` to ensure compatibility.
3. Generate Rust stubs:

```bash
cargo make proto-gen
```

The generated code is **checked in** to keep downstream crates vendorable.

---

## 7 Commit Message Convention

We use **Conventional Commits** + scoped types:

```
<type>(<scope>): <subject>
<BLANK LINE>
<body>
<BLANK LINE>
<footer>
```

Examples:

```
feat(composer): support post-quantum Dilithium signatures

fix(marketplace): correct fee rounding for large u256 values, closes #512
```

---

## 8 Continuous Integration

* GitHub Actions files live in `.github/workflows/`.
* Required jobs: `lint`, `test`, `e2e`, `cargo-deny`.
* PRs are auto-labeled (`📦 crate`, `🛠 infra`, `📚 docs`) via `labeler.yml`.

---

## 9 Security Policy

To report a vulnerability, please **do not open a GitHub issue**.  
Instead, email `security@canvaschain.org` with a detailed description and
reproduction steps. We follow responsible disclosure and aim to reply within 48 h.

---

## 10 Community Guidelines & Code of Conduct

We adhere to the **Rust Code of Conduct**. In short:

* Be respectful and inclusive.
* Harassment, discrimination, or trolling will not be tolerated.
* Issues & PRs should stay on topic.

---

## 11 FAQ

**Q:** _My build fails with nightly-only features._  
**A:** Ensure you have not opted into optional crates that require nightly. You
can build the full workspace with stable.

**Q:** _How do I spin up a local test-net?_  
**A:** `cargo make start` launches `substrate-node` + all microservices with
Docker Compose.

**Q:** _Can I contribute an ERC-721 bridge?_  
**A:** Absolutely! Open a feature request issue first so we can coordinate on
design and avoid duplicate work.

---

Happy hacking,
_The CanvasChain Symphony Maintainers_ 🎨⚡️
```