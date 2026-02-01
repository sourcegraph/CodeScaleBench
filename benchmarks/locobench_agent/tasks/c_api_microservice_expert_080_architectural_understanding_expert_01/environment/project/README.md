# MercuryMonolith Commerce Hub  
_All-in-one native (C) business services platform_

[![Build Status](https://img.shields.io/github/actions/workflow/status/acme/mercury-monolith/ci.yml?branch=main)](https://github.com/acme/mercury-monolith/actions)  
[![Coverage](https://img.shields.io/codecov/c/github/acme/mercury-monolith)](https://codecov.io/gh/acme/mercury-monolith)  
[![License](https://img.shields.io/github/license/acme/mercury-monolith)](LICENSE)  

---

MercuryMonolith Commerce Hub consolidates ordering, catalog, invoicing, customer management and analytics into **one statically linked binary**.  
While it exposes a _micro-service-shaped_ REST / GraphQL surface, every module shares the same address space, event bus and ACID-compliant data layer—delivering:

* predictable latency (<200 µs p99 internal hops)
* **single-step deployment** (copy & run)
* coherent, cross-domain transactions
* drastically reduced operational overhead

> Think of it as an **API constellation** wrapped in a single-process, native rocket.

---

## Feature highlights
* REST v1/v2 + GraphQL endpoints (auto-generated schemas / OpenAPI)
* Response caching (LRU+TTL, cache-aside)
* Token-bucket rate-limiting (per-key, sliding-window analytics)
* JWT / mTLS authentication & fine-grained authorization
* Input validation (JSONSchema / custom DSL)
* Structured logging (JSON / text; trace-id propagation)
* Prometheus metrics (histograms, counters, gauges)
* Panic-free error handling & typed error surfaces
* Hot-reloadable configuration (SIGHUP; zero downtime)
* Built-in **SQLite** for PoC / demos; **PostgreSQL** for prod

---

## Quick-start

### Prerequisites
* GCC 12+ or Clang 16+  
* `make`, `cmake` ≥3.25  
* SQLite ≥3.40 _(optional if using Postgres)_  
* PostgreSQL 15 _(optional if using SQLite)_  

```bash
# build optimized, static binary
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel

# run with default config (./config/mercury.toml)
./build/mercury-monolith
```

Out-of-box the process listens on:

| Interface | Address | Purpose                |
|-----------|---------|------------------------|
| REST      | `:8080` | JSON/HTTP API          |
| GraphQL   | `:8081` | GraphQL Playground     |
| Metrics   | `:9000` | Prometheus /metrics    |
| Admin     | `:9001` | Health/live/ready z-pages |

---

## Configuration

The binary looks for a **TOML** file at:

* `${MERCURY_CONFIG}` (env override)
* `./config/mercury.toml` (relative)
* `/etc/mercury/mercury.toml` (system default)

Excerpt:

```toml
[server]
bind_addr = "0.0.0.0"
rest_port = 8080
graphql_port = 8081

[database]
driver = "postgres"        # "sqlite" or "postgres"
dsn    = "postgres://monolith:secret@localhost:5432/monolith"

[security]
jwt_public_key  = "/etc/mercury/pub.pem"
mtls_ca_bundle  = "/etc/ssl/ca.pem"

[caching]
enabled = true
ttl_seconds = 120
capacity   = 25000

[logging]
format = "json"            # "text" or "json"
level  = "info"
```

---

## REST example

```bash
curl -X POST http://localhost:8080/v1/orders \
     -H  'Content-Type: application/json' \
     -H  "Authorization: Bearer $JWT" \
     -d '{ "customer_id": 42, "items": [ { "sku": "ABC-123", "qty": 3 } ] }'
```

Successful response:

```json
{
  "id": "ORD-20240325-0001",
  "status": "PENDING",
  "total": "27.99",
  "links": {
    "self": "/v1/orders/ORD-20240325-0001"
  }
}
```

API reference is auto-generated at:

```
GET /openapi.json
GET /docs         (ReDoc)
```

---

## GraphQL example

```graphql
mutation {
  createOrder(input: {
    customerId: 42
    lines: [{ sku: "ABC-123", quantity: 3 }]
  }) {
    id
    status
    total
  }
}
```

Play with queries at `http://localhost:8081/playground`.

---

## Internals

```
┌───────────────────┐
│  Presentation     │  REST  │  GraphQL
│  (HTTP front)     │────────┼────────┐
└────────┬──────────┘        │        │
         │        in-proc    │        │
┌────────▼───────────┐       │        │
│  API Gateway       │ ◀─────┘        │
│  (routing, auth)   │                │
└────────┬───────────┘                │
         │ event bus                 cache
┌────────▼───────────┐        ┌──────▼──────┐
│  Service Layer     │        │  LRU Cache  │
│  (orders, users…)  │        └──────┬──────┘
└────────┬───────────┘               │
         │ CQRS                      │
┌────────▼───────────┐               │
│  Repositories      │───────────────┘
│  (SQL/DTO mappers) │
└────────┬───────────┘
         │
┌────────▼───────────┐
│  Driver / DAL      │── SQLite / Postgres
└────────────────────┘
```

* Zero-copy message passing via lock-free ring buffers
* _Sozu-style_ state machine per connection; HTTP/1.1 & H/2
* Compile-time dependency injection (linker sections)

---

## Monitoring

| Metric                        | Description                       |
|-------------------------------|-----------------------------------|
| `http_requests_total`         | Counter by route / status         |
| `http_request_duration_ms`    | Histogram buckets 0.1–10 000 ms   |
| `cache_hits_total`            | Counter by region                 |
| `db_pool_in_use`              | Gauge per replica                 |
| `eventbus_backpressure_ratio` | Gauge 0.0–1.0                     |

Scrape via: `GET /metrics`

---

## Development

```bash
# run test matrix
make test

# auto-format (clang-format) & static analysis
make lint
```

### Debug build with address‐sanitizer

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Debug -DENABLE_ASAN=ON
cmake --build build --parallel
```

---

## Contributing

Bug reports, feature requests and pull requests are welcome!  
Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

---

## License

MercuryMonolith is licensed under the **Apache 2.0** License – see the [LICENSE](LICENSE) file for details.

---

© 2024 ACME Corp – Built with ＜3 and a lot of caffeine.