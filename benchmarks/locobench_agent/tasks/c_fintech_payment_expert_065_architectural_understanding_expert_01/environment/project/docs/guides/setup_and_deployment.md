```markdown
# EduPay Ledger Academy  
**Guide: Setup & Deployment**  
status: Stable • last-reviewed: 2024-05-02 • min‐platform: POSIX (Linux/macOS)

---

## 1 . Prerequisites

| Component                   | Tested Version | Notes                                               |
|-----------------------------|----------------|-----------------------------------------------------|
| GCC / Clang                 | ≥ 12.2 / 15.0 | `-std=c17`, LTO, and UBSan are enabled by default   |
| CMake                       | ≥ 3.25        | Cross-compilation & presets                         |
| Make / Ninja                | ≥ 4.4 / 1.11  | Either generator is supported                       |
| PostgreSQL                  | 15.x          | Event-store (CQRS), idempotent SQL migrations       |
| Redis                       | 7.x           | Idempotency-Key cache & distributed locks           |
| NATS.io                     | 2.9.x         | Audit-Trail event bus & Saga orchestrations         |
| Docker & Docker Compose     | ≥ 24.0        | Local polyglot stack                                |
| Kubernetes (kubectl, helm)  | ≥ 1.28        | Production deployment                               |
| OpenSSL                     | 3.x           | TLS 1.3 & HSM off-loading                           |
| Git                         | ≥ 2.40        | Git submodules enabled                              |

```bash
# Debian / Ubuntu quick-install
sudo apt update && sudo apt install -y \
    build-essential cmake ninja-build clang lld \
    libpq-dev libssl-dev libnats-dev redis-server \
    postgresql postgresql-contrib git
```

---

## 2 . Clone Repository & Submodules

```bash
git clone --recursive https://github.com/edupay/ledger-academy.git
cd ledger-academy
```

The `--recursive` flag is mandatory:  
* `/third_party/cJSON` – minimal JSON for embedded usage  
* `/docs/datasets` – synthetic FERPA-compliant fixtures  

---

## 3 . Local Build (Debug)

```bash
cmake --preset dev .
cmake --build . --target all --parallel $(nproc)
ctest --output-on-failure
```

Presets are defined in `CMakePresets.json`:

```jsonc
{
  "configurePresets": [
    {
      "name": "dev",
      "generator": "Ninja",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug",
        "EDUPAY_ENABLE_SANITIZERS": "ON",
        "EDUPAY_ENABLE_COVERAGE": "ON"
      }
    }
  ]
}
```

### 3.1 Sanitizers

During `Debug` builds the following flags are auto-enabled:

```
-fsanitize=address,undefined,leak -fsanitize-trap=all
```

Crash traces map back to source with DWARF v5 symbols.

---

## 4 . Run Services Locally (Docker Compose)

```bash
docker compose -f ops/docker/docker-compose.yml \
    --project-name edupay up -d
```

Included services:

* `pg-db`       → PostgreSQL 15 with timescaledb
* `nats`        → NATS JetStream for event sourcing
* `redis`       → Ephemeral cache / lock service
* `otel-collector` & `grafana` → Observability stack

Once started, run migrations:

```bash
./build/bin/edupay_migrate \
  --db "postgres://admin:edup4y@127.0.0.1:5432/edupay?sslmode=disable"
```

---

## 5 . Environment Variables (`.env`)

```dotenv
# Database
EDUPAY_DB_URL=postgres://admin:edup4y@pg-db:5432/edupay?sslmode=disable

# NATS
EDUPAY_NATS_URL=nats://nats:4222

# Redis
EDUPAY_REDIS_URL=redis://redis:6379/0

# TLS certificates (development only)
EDUPAY_TLS_CERT=ops/certs/localhost.crt
EDUPAY_TLS_KEY =ops/certs/localhost.key

# Feature flags
EDUPAY_FEATURE_SAGA_DEMO=true
EDUPAY_FEATURE_FRAUD_HEURISTICS=true
```

All variables are parsed via `src/common/config/env.c`.  
Missing critical variables cause a **hard fail** (`exit(EXIT_INVALID_ENV)`).

---

## 6 . Database Migrations

Migrations live in `ops/sql/*.sql` and follow semantic filenames:

```
0001_init_event_store.up.sql
0001_init_event_store.down.sql
```

The migration CLI:

```bash
./build/bin/edupay_migrate --help
```

Under the hood the tool uses a stripped-down version of `libpq` with  
transaction-per-migration guarantees (either all or none applied).

---

## 7 . Running the Platform

```bash
./build/bin/edupay_gateway \
    --config ./configs/gateway.dev.yaml
```

Excerpt from `gateway.dev.yaml`:

```yaml
server:
  bind_addr: "0.0.0.0:8443"
  max_conns: 4096
security:
  tls:
    cert_file: "ops/certs/localhost.crt"
    key_file:  "ops/certs/localhost.key"
features:
  saga_pattern_demo: true
  multi_currency:    true
```

Press `Ctrl-C` and Gateway performs a **zero-data-loss** shutdown:

1. Drains NATS subscriptions  
2. Finishes in-flight SQL transactions  
3. Flushes Redis lock table  

---

## 8 . Saga Pattern Simulation

1. Start platform in *demo* mode (`EDUPAY_FEATURE_SAGA_DEMO=true`).
2. Kill the `fees` microservice:  

   ```bash
   docker compose exec fees svcctl stop
   ```
3. Observe compensation transactions in the **UI Dashboard**.

Developers can tune chaos frequency:

```bash
export EDUPAY_SAGA_CHAOS_CHANCE=0.15   # 15 % random outage
```

---

## 9 . Container Image (Production)

Multi-stage Dockerfile:

```Dockerfile
# --- Build stage ----------------------------------------------------------
FROM ghcr.io/cross-rs/x86_64-unknown-linux-gnu:stable AS builder
WORKDIR /src
COPY . .
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -G Ninja \
 && cmake --build build --target edupay_gateway --parallel 8 \
 && strip build/bin/edupay_gateway

# --- Runtime stage --------------------------------------------------------
FROM gcr.io/distroless/cc-debian12
COPY --from=builder /src/build/bin/edupay_gateway /usr/local/bin/
ENTRYPOINT ["edupay_gateway"]
```

Build & push:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/edupay/ledger-academy:$(git rev-parse --short HEAD) \
  --push .
```

---

## 10 . Kubernetes Deployment (Helm)

```bash
helm upgrade --install edupay ops/helm \
  --namespace edupay --create-namespace \
  --set image.tag=$(git rev-parse --short HEAD)
```

Key resources:

* `Deployment/edupay-gateway`  (2 replicas, HPA enabled)  
* `StatefulSet/edupay-postgres` (WAL-enabled, PVC)  
* `PodDisruptionBudget` to ensure **> 50 %** availability  

---

## 11 . Observability

Components auto-export OpenTelemetry spans:

```bash
kubectl port-forward svc/grafana 3000:80
# Login: admin / edup4y
```

Critical RED metrics:

| Metric                   | SLI Goal |
|--------------------------|----------|
| `gateway_latency_p99`    | < 120 ms |
| `payment_success_ratio`  | ≥ 99.3 % |
| `fraud_false_negative`   | 0        |

---

## 12 . CI Pipeline (GitHub Actions)

`.github/workflows/ci.yml` handles:

1. Static analysis (`clang-tidy`, `cppcheck`, `semgrep`)  
2. Unit + integration tests  
3. SCA (`oss-fuzz`) & SBOM generation  
4. Container build & automatic CVE scans (Trivy)  

---

## 13 . Troubleshooting

| Symptom                           | Suggestion                                            |
|-----------------------------------|-------------------------------------------------------|
| `ECONNRESET` during NATS publish  | Check NATS JetStream limits/quotas.                   |
| Seg-fault in `pqResultCreate`     | Verify SSL root CA; mismatched `libpq` versions.      |
| Stuck migration                   | Drop `schema_migrations` advisory lock (pg_advisory). |

---

## 14 . Uninstall

```bash
docker compose down -v        # removes volumes
rm -rf build/                 # cleans cmake artefacts
dropdb edupay                  # if using local Postgres
```

---

© 2024 EduPay Ledger Academy • MIT License
```