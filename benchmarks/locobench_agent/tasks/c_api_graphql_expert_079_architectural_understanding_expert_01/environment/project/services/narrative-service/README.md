# SynestheticCanvas · Narrative Service  
![CI](../../.github/badges/narrative-ci.svg) ![Coverage](../../.github/badges/narrative-coverage.svg) ![License](https://img.shields.io/badge/license-MIT-green)

The Narrative Service is a stand-alone C micro-service that handles every story-telling concern in SynestheticCanvas: branching plots, character arcs, time-travelled timelines, and any stateful dialog required by graphical or audio-reactive scenes.  
It ships as an **HTTP/2 + gRPC** server with a **GraphQL façade** exposed through the API-Gateway, falls back to JSON/REST, and stores its state in a _pluggable repository_ (SQLite, PostgreSQL, or an in-memory ephemeral store—switchable at runtime).

---

## ✨ Key Responsibilities

* Deliver a **branching narrative engine** with millisecond latency.  
* Offer **CQS-compliant endpoints** (`query { … }` vs `mutation { … }`).  
* Support **optimistic concurrency** via revision hashes.  
* Stream **server-sent events** (SSE) for live plot changes.  
* **Versioned GraphQL schema** (`v1`, `preview`, `experimental`).  
* Expose **metrics** to Prometheus and **traces** to OpenTelemetry.  
* Log through the central **Elastic APM** with colorized spans.  

---

## 🗄 Repository Pattern

```
┌─────────────────────┐        ┌─────────────────────┐
│  narrative_service  │        │   rest_controller   │
│   (domain layer)    │        │   graphql_resolver  │
└─────────▲───────────┘        └──────────▲──────────┘
          │                               │
          │  C→ABI (narrative_repo.h)     │
          │                               │
┌─────────┴───────────┐        ┌──────────┴──────────┐
│  sqlite_repository  │        │  postgres_repository│
│(dynamic plug-in .so)│        │  (dynamic plug-in)  │
└─────────────────────┘        └─────────────────────┘
```

`narrative_repo.h` is the canonical interface. Load a concrete repo at boot via `dlopen(3)` by setting `NARRATIVE_REPO_DRIVER=/path/to/librepo_sqlite.so`.

---

## 🧑‍💻 Quick-Start (Local)

```bash
git clone https://github.com/SynestheticCanvas/api_graphql.git
cd services/narrative-service

# Pull submodules (shared lib, 3rd-party)
git submodule update --init --recursive

# Build with Meson + Ninja
meson setup build --prefix=/usr/local \
                  -Dbuildtype=release \
                  -Db_lto=true
ninja -C build
sudo ninja -C build install

# Run migrations (PostgreSQL example)
./scripts/migrate.sh

# Start service
./bin/narrative_service --config ./config/local.toml
```

After startup, visit  
`http://localhost:8071/graphiql` to try the interactive playground.

---

## 🔌 Environment Variables

| Name                          | Default           | Description                                    |
|-------------------------------|-------------------|------------------------------------------------|
| `NARRATIVE_PORT`              | `8071`            | Service TCP port                               |
| `NARRATIVE_HOST`              | `0.0.0.0`         | Bind address                                   |
| `NARRATIVE_REPO_DRIVER`       | `librepo_mem.so`  | `.so` implementing `narrative_repo_t`          |
| `NARRATIVE_LOG_LEVEL`         | `info`            | `trace`, `debug`, `info`, `warn`, `error`      |
| `NARRATIVE_SCHEMA_VERSION`    | `v1`              | Default GraphQL schema version                 |
| `NARRATIVE_MAX_PAGE_SIZE`     | `100`             | Hard limit for pagination size                 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `""`              | OpenTelemetry collector URL                    |

---

## 🔍 GraphQL Schema (v1 excerpt)

```graphql
type Query {
  narrative(id: ID!): Narrative!
  narratives(page: PageInput): NarrativeConnection!
}

type Mutation {
  createNarrative(input: CreateNarrativeInput!): Narrative!
  branchNarrative(id: ID!, atEvent: ID!, input: BranchInput!): Narrative!
}

type Narrative {
  id: ID!
  title: String!
  revision: String!   # sha256 of state snapshot
  events: [Event!]!
}

type Event {
  id: ID!
  timestamp: Time!
  payload: JSON!
  forks: [Narrative!]!
}

input PageInput {
  first: Int = 20
  after: Cursor
}
```

---

## ➕ REST Fallback

```
POST /narratives
{
  "title": "Giraffes on Mars"
}

GET  /narratives?page[after]=gVwAAA&limit=20
```

All endpoints accept/return `application/json; charset=utf-8`.

---

## 🧪 Test & Coverage

```bash
meson test -C build --print-errorlogs
ninja -C build coverage        # Generates lcov + HTML report
```

Unit tests use **µCheck** with mocked repositories, while the **integration test suite** (`tests/it/`) spins up PostgreSQL in Docker and hits the service through HTTP.

---

## 📈 Metrics & Health

* `/healthz` – liveness (HTTP 200)  
* `/readyz` – readiness incl. repo ping  
* `/metrics` – Prometheus scrape target  
* `/debug/pprof/*` – performance profiling  

---

## 🛡 Security

1. Every mutation requires a `X-SYNESTHETIC-AUTH` JWT (RS256).  
2. Query depth & cost analyzers prevent DoS in GraphQL.  
3. OWASP-top-10 mitigations baked into shared `security_middleware.c`.  

---

## 🐳 Docker

```bash
docker build -t syn/canvas-narrative .
docker run -d --name=story \
           -p 8071:8071 \
           -e NARRATIVE_REPO_DRIVER=/repo/librepo_postgres.so \
           -e POSTGRES_URI=postgres://sc:sc@db:5432/sc \
           syn/canvas-narrative
```

---

## 👥 Contributing

PRs are welcome! Lint with `clang-format` (profile: `llvm`) and `cppcheck --enable=all`.  
For sizeable changes, open an issue first and discuss proposals.

---

## 📝 License

This component of SynestheticCanvas is released under the **MIT License**.  
See [LICENSE](../../LICENSE) for full text.

---

> “Stories are just data with a soul.” – Chris Milk