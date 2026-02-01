```markdown
# LedgerLink Nexus – API Microservice

LedgerLink Nexus is a Rust-powered, enterprise-grade API microservice that delivers **ultra-reliable**, **versioned** REST and GraphQL endpoints for multi-tenant B2B reconciliation platforms.  
It synchronises invoices, payments and audit trails across ERP, CRM and banking systems while enforcing financial-grade SLAs and audit readiness.

---

## ✨ Key Features

- **MVVM-inspired service layout** – Clear separation between external payloads (*Views*), validated DTOs (*View-Models*) and core domain *Models*.
- **REST _and_ GraphQL** – Version-negotiated REST endpoints live side-by-side with a fully-typed GraphQL schema.
- **Command / Query Separation** – Deterministic business flows split between commands (mutations) and queries (read-only).
- **Repository Pattern** – Postgres (Diesel) and Redis repositories isolated behind domain traits; supports easy swapping/mocking.
- **Tenant-Aware Auth** – JWT/OAuth2 tokens enriched with tenant and role claims ferry through a central API Gateway.
- **Response Caching** – Multi-layer caching (Redis, HTTP cache-control headers, immutable GraphQL fragments).
- **Observability** – OpenTelemetry spans, structured JSON logs, Prometheus metrics and Sentry error envelopes.
- **Production-ready** – Docker-compose stack, migrations, smoke tests, DevOps manifests.

---

## 🏗️ Architecture (High Level)

```text
┌─────────────┐   REST / GraphQL   ┌───────────────┐
│  Clients    │◀──────────────────▶│ API Gateway   │  ↘ rate-limit, authN/Z
└─────────────┘                    └───────────────┘
                                         │
                                         ▼
                        ┌───────────────────────────────────┐
                        │         LedgerLink Nexus          │
                        │-----------------------------------│
                        │  View (payload)                   │
                        │      ▼                            │
                        │  View-Model (DTO + Validation)    │
                        │      ▼                            │
                        │  Service Layer (Cmd/Query)        │
                        │      ▼                            │
                        │  Repository (Pg / Redis)          │
                        │      ▼                            │
                        │  Domain Model (Ledger, Invoice)   │
                        └───────────────────────────────────┘
                                         │
              ┌───────────────────────────┴────────────────────────┐
              ▼                                                    ▼
          PostgreSQL                                           Redis
   (audit-ready TX journal)                         (cache, idempotency keys)
```

---

## 🚀 Quick Start

### 1. Prerequisites

- Rust **1.73+** (stable)
- `docker` + `docker compose`
- `make` (optional but convenient)

### 2. Clone & Launch

```bash
git clone https://github.com/acme-fintech/ledgerlink-nexus.git
cd ledgerlink-nexus

# Spin up Postgres + Redis
docker compose up -d db redis

# Run migrations
cargo install sqlx-cli --no-default-features --features postgres
sqlx migrate run

# Start the service
cargo run --release
```

Service boot logs resemble:

```text
2023-10-27T12:11:07Z  INFO ledgerlink_nexus::bootstrap: Listening on 0.0.0.0:8080 (REST v1)
2023-10-27T12:11:07Z  INFO ledgerlink_nexus::bootstrap: Listening on 0.0.0.0:8081 (/graphql)
```

Navigate to `http://localhost:8081/graphql/playground` for GraphQL IDE.

---

## ⚡ Quick Glance: Code Snippet

Below is a trimmed excerpt showing how the MVVM tier wires together inside a query endpoint:

```rust
use axum::{extract::State, Json};
use crate::{
    dto::ledger::{LedgerEntryQueryVm, LedgerEntryView},
    service::ledger::LedgerQueryService,
    error::ApiError,
};

/// GET /v1/ledger
pub async fn list_ledger_entries(
    State(state): State<AppState>,
    query_vm: LedgerEntryQueryVm, // automatic validator via `serde_with` + `validator`
) -> Result<Json<Paginated<LedgerEntryView>>, ApiError> {
    let service = LedgerQueryService::new(&state.pg_pool, &state.redis);
    let entries = service
        .paginate(query_vm.into())
        .await?; // Transparent error conversion into ApiError

    Ok(Json(entries.into()))
}
```

`LedgerEntryQueryVm` performs field-level validation, default pagination and attaches cache hints (ETag, max-age).  
`LedgerQueryService` orchestrates read-only flows by composing repositories – no business logic leaks into the handler.

---

## 🔌 Example GraphQL Query

```graphql
query CashFlowForecast($tenant: UUID!, $currency: ISO4217!) {
  forecast(tenantId: $tenant, currency: $currency, horizonDays: 90) {
    date
    inflow
    outflow
    net
  }
}
```

Curl-style execution:

```bash
curl -X POST http://localhost:8081/graphql \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "query": "query { forecast(tenantId:\"c23d...\", currency:USD, horizonDays:30){date net} }"
}
EOF
```

---

## 🗄️ Configuration

LedgerLink Nexus is configured through **environment variables** (12-factor):

| Variable                      | Description                                 | Default           |
| ----------------------------- | ------------------------------------------- | ----------------- |
| `DATABASE_URL`                | Postgres connection string                  | `postgres://...`  |
| `REDIS_URL`                   | Redis connection string                     | `redis://...`     |
| `LLN_BIND_ADDR`               | Listener address (REST)                     | `0.0.0.0:8080`    |
| `LLN_GRAPHQL_ADDR`            | Listener address (GraphQL)                  | `0.0.0.0:8081`    |
| `LLN_JWT_ISSUER`              | JWT expected issuer                         | `ledgerlink`      |
| `LLN_JWT_AUDIENCE`            | JWT expected audience                       | `nexus`           |
| `RUST_LOG`                    | Log filter expression                       | `info,sqlx=warn`  |

`.env.sample` ships with sensible defaults.

---

## 🧪 Running Tests

```bash
# Unit & integration suites (uses testcontainers)
cargo test

# Cargo-nextest parallel runner
cargo nextest run

# Check linting, formatting, security advisories
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo audit
```

---

## 📂 Project Layout (excerpt)

```text
.
├── api                # REST + GraphQL handlers
├── dto                # View-Models (serde, validator)
├── domain             # Core business models
├── service            # Command / Query orchestrators
├── repository         # Postgres + Redis impls
├── gateway            # HTTP entry-points, middleware, auth, version negotiation
├── config             # Layered settings loader
├── migrations         # sqlx migrations
└── README.md
```

---

## 🔒 Security Policy

If you discover a vulnerability, **please do not open an issue**.  
Instead, email `security@acme-fintech.io` and we will coordinate a private disclosure.

---

## 🤝 Contributing

1. Fork the repo & create your feature branch (`git checkout -b feat/amazing`).
2. Commit your changes (`git commit -m 'feat: add amazing'`).
3. Run the checks (`make ci`).
4. Push to the branch (`git push origin feat/amazing`) and open a PR.

All code is reviewed with **rustfmt**, **clippy** and **semantic PR titles** enforced by CI.

---

## 📜 License

LedgerLink Nexus is licensed under **Apache-2.0** – see [`LICENSE`](./LICENSE) for details.

---

> Financial data deserves **type-safety and rock-solid guarantees** – choose Rust, choose LedgerLink Nexus.
```
