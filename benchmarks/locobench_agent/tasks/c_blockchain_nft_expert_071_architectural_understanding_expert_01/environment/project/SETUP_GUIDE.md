```markdown
# HoloCanvas Setup Guide  
**A step-by-step manual for compiling, testing, and operating the complete on-chain micro-gallery stack**

---

## 1. Repository Layout

```
HoloCanvas/
├── build/                  # CMake/Ninja out-of-source build tree
├── cmake/                  # Shared CMake helper modules
├── docs/                   # Additional architecture notes
├── external/               # Git sub-modules (OpenSSL, protobuf-c, etc.)
├── services/
│   ├── Cryptograph/        # Signatures, hashing, Merkle proofs
│   ├── LedgerCore/         # UTXO ledger + roll-up verifier
│   ├── Mint-Factory/       # Factory Pattern: NFT mint pipeline
│   ├── Gallery-Gateway/    # HTTP/gRPC API gateway
│   ├── DeFi-Garden/        # Staking, liquidity pools
│   ├── Oracle-Bridge/      # Off-chain sensor/oracle bridge
│   ├── Wallet-Proxy/       # Client-side transaction abstraction
│   └── Governance-Hall/    # DAO governance module
└── tools/
    ├── holoctl/            # CLI management tool (Go)
    └── scripts/            # CI helpers, code-gen, benchmarks
```

---

## 2. Prerequisites

| Component            | Version (min) | Notes                                   |
|----------------------|---------------|-----------------------------------------|
| GCC / Clang          | 12 / 15       | `-std=c2x` features used                |
| CMake                | 3.25          | Presets + Object libraries              |
| Ninja                | 1.11          | Faster multi-service builds             |
| OpenSSL              | 3.x           | ECC curve support (secp256k1, ed25519)  |
| libsodium            | 1.0.19        | Optional: accelerated crypto            |
| protobuf-c           | 1.5           | gRPC C stubs                            |
| librdkafka           | 2.3           | Event-driven mesh messaging             |
| Kafka                | 3.6           | Local dev cluster via Docker            |
| PostgreSQL           | 15            | Metadata & governance state             |
| Redis                | 7.x           | Ephemeral caches/queues                 |
| Docker / Podman      | 24.x          | Local orchestration                     |
| Python               | 3.11          | Code-gen, test harness, CLI wrappers    |

MacOS users: Install via Homebrew (`brew bundle --file=./tools/Brewfile`).

---

## 3. Quick-start (TL;DR)

The fastest way to play with a **local devnet**:

```bash
git clone --recurse-submodules https://github.com/holocanvas/blockchain_nft.git
cd blockchain_nft

# Spin up infra + all microservices
make devnet-up             # ⏱ ~30 s (depends on network)

# Verify health
./tools/scripts/check.sh   # Probes gRPC ports and Kafka topics
```

After containers are ready, open http://localhost:8080 to view the **Gallery-Gateway** Swagger UI.

---

## 4. Building From Source

### 4.1 Configure Toolchain

```bash
export CC=clang
export CXX=clang++
export HOLOCANVAS_BUILD_TYPE=Debug   # or RelWithDebInfo / Release
```

### 4.2 Generate Build Tree

```bash
cmake --preset=ninja-multi
# Preset defined in CMakePresets.json:
# {
#   "name": "ninja-multi",
#   "generator": "Ninja Multi-Config",
#   "binaryDir": "build",
#   "cacheVariables": {
#     "CMAKE_C_STANDARD": "23",
#     "BUILD_SHARED_LIBS": "ON",
#     "USE_LTO": "ON"
#   }
# }
```

### 4.3 Incremental Compilation

```bash
cmake --build build --config Debug -j$(nproc)
```

The root CMakeLists.txt creates a **super-build** that exports each service as an `IMPORTED` target, ensuring IDEs (VSCode, CLion) support cross-navigation.

---

## 5. Running Unit & Integration Tests

```bash
# Unit tests (CTest + GoogleTest)
ctest --test-dir build -L unit

# Property-based fuzzers (libFuzzer + honggfuzz)
make fuzz TARGET=Cryptograph

# Multi-service integration suite (docker-compose)
make integration-up   # bring up infra
pytest tests/it       # Python gRPC clients
```

Coverage reports are emitted into `build/coverage/` (HTML + Cobertura).

---

## 6. Environment Variables

| Var                       | Default              | Description                              |
|---------------------------|----------------------|------------------------------------------|
| HOLO_NET_ID               | `devnet`            | Chain/network identifier                 |
| HOLO_KAFKA_BROKERS        | `localhost:9092`     | Kafka bootstrap list                     |
| HOLO_DB_URL               | `postgres://...`     | Postgres DSN                             |
| HOLO_REDIS_URL            | `redis://localhost`  | Ephemeral cache                          |
| HOLO_GENESIS_FILE         | `config/dev.genesis` | Genesis JSON used by LedgerCore          |
| HOLO_LOG_LEVEL            | `info`               | `trace,debug,info,warn,error`            |
| HOLO_WALLET_SEED          | _none_               | 32-byte master key (test accounts)       |
| HOLO_FEATURE_FLAGS        | empty                | Comma-sep list of RFC/Lab features       |

Create a local `.env` to override; Docker Compose automatically injects it.

---

## 7. Database Bootstrapping

```bash
psql -f services/LedgerCore/migrations/schema.sql "$HOLO_DB_URL"

# Seed devnet accounts & NFTs
./services/LedgerCore/bin/ledgercore --seed config/seeds/draft_nfts.json
```

`migrations/` use **sqitch** for idempotent versioning; CI pipelines enforce a forward-only migration rule.

---

## 8. Local Devnet via Docker Compose

```bash
make devnet-up          # = docker compose up -d --build
make devnet-logs        # Stream aggregated logs
make devnet-down        # Clean shutdown + volume prune
```

`docker-compose.yaml` builds each service’s OCI image via multi-stage (alpine-based) Dockerfiles. CPU architecture is auto-detected (`linux/arm64` on Apple Silicon).

---

## 9. Production Deployment (Kubernetes)

All deployment manifests live in `deploy/k8s/` and follow **GitOps** conventions (Kustomize overlays).

```shell
kubectl kustomize deploy/k8s/overlays/prod | kubectl apply -f -
```

Secrets (TLS keys, database passwords) are sourced from **Vault** via the CSI driver.

---

## 10. Code Quality & Conventions

1. `clang-format` enforces the project style (`.clang-format` file).
2. `clang-tidy` runs with a strict profile (`modernize-*`, `hicpp-*`, `cert-*`).
3. Pre-commit hooks (`pre-commit.com`) verify:
   - SPDX license headers
   - No TODOs referencing expired RFC tickets
   - Markdown spell-check
   - Large binary blobs.

CI (GitHub Actions + BuildKite) blocks merges on any violation.

---

## 11. Upgrading the Consensus Engine

The consensus engine lives behind a **Strategy Pattern** interface:

```c
// services/LedgerCore/include/consensus/engine.h
typedef enum {
    HOLO_CONS_ENGINE_NPOS,   // Default: Nominal PoS
    HOLO_CONS_ENGINE_DA,     // Delegated Artistry
    HOLO_CONS_ENGINE_POW_S,  // Experimental: Shader PoW
} holo_consensus_kind_e;

typedef struct {
    holo_consensus_kind_e kind;
    void *impl;             // Opaque impl pointer
} holo_consensus_engine_t;

/* Dynamically loads the selected engine (.so) at runtime */
int holo_consensus_init(holo_consensus_engine_t *out,
                        holo_consensus_kind_e kind);
```

To swap engines:

```bash
cmake -DHOLO_CONS_ENGINE=HOLO_CONS_ENGINE_DA -S . -B build
make -C build
```

---

## 12. Troubleshooting

| Symptom                               | Possible Cause                           | Fix                                       |
|---------------------------------------|------------------------------------------|-------------------------------------------|
| `dial tcp 127.0.0.1:9092: connect…`   | Kafka init race                          | `make devnet-logs` ⇒ wait for `kafka ready` |
| `SSL: CERTIFICATE_VERIFY_FAILED`      | Outdated root store (macOS)              | `brew install --cask certifi`             |
| `ledgercore: genesis mismatch`        | Network ID changed w/o DB reset          | `make devnet-down` then `rm -rf .volumes` |

---

## 13. Contributing

1. Fork + branch naming: `feat/<module>-<ticket>`, `fix/…`.
2. All public APIs must have:
   - RFC doc in `docs/rfc/`.
   - Unit tests (`>90 %` coverage).
   - Benchmarks if perf-critical.
3. Open a PR and link the **Linear.app** ticket.

---

## 14. Related Reading

- `docs/ARCHITECTURE.md` – Deep dive into micro-service contracts.
- `docs/RFC/0010_dynamically_evolving_nfts.md`
- ERC-721 & ERC-1155 specs (background context).

---

Happy hacking!  
If you get stuck hop into our Discord `#dev-holo` or open an issue.

```
