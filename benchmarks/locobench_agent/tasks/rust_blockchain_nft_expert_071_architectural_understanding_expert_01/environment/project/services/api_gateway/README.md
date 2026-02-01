# CanvasChain Symphony – API Gateway Service  
_Service Path: `services/api_gateway`_  

The **API Gateway** exposes a unified HTTP/JSON façade on top of the internal gRPC micro-services that power CanvasChain Symphony.  
It performs protocol translation, request authentication, streaming compression, tracing injection and fine-grained rate–limiting.  
This document walks through its architecture, public endpoints, deployment topology and contribution guidelines.

---

## 1. High-Level Responsibilities
* HTTP ↔ gRPC bidirectional translation (powered by `tonic` + `tower` + `axum`)
* JWT-based authentication & multi-tenant authorization (artist / curator / collector roles)
* Request fan-out & aggregation (e.g. marketplace listings + royalty stream in a single round-trip)
* Cross-service observability (OpenTelemetry traces, Prometheus metrics, structured JSON logs)
* Circuit-breaker & back-pressure for flaky downstream micro-services
* Pluggable cryptography strategy dispatch (Ed25519, BLS12-381, Kyber-1024) exposed via feature flags
* Canary deployments & zero-downtime schema migrations

---

## 2. Crate Layout
```
services/api_gateway
├── Cargo.toml
├── README.md            ← you are here
└── src
    ├── main.rs          ← bootstrap + signal handling
    ├── config.rs        ← typed configuration loader (TOML / env / CLI)
    ├── auth.rs          ← JWT verification + RBAC guard
    ├── grpc_client.rs   ← generated gRPC stubs + retry layers
    ├── router.rs        ← axum router + middleware stack
    └── telemetry.rs     ← tracing / metrics initialisation
```

---

## 3. Quick-start

```bash
# 1. Run all dependencies using the dev docker-compose file
docker compose -f ../../infra/local/docker-compose.yml up -d etcd nats postgres

# 2. Launch the gateway with the default profile
cargo run -p api_gateway --features ed25519 -- --config ./Config.dev.toml
```

### Environment Variables (override any setting in `Config.*.toml`)
| Variable                       | Default                 | Description                                   |
| ------------------------------ | ----------------------- | --------------------------------------------- |
| `CC_GW__LISTEN_ADDR`           | `0.0.0.0:8080`          | Public HTTP bind address                      |
| `CC_GW__PUBLIC_URL`            | `http://localhost:8080` | Used for HATEOAS link generation              |
| `CC_GW__JWT_PUBLIC_KEY_PATH`   | `./keys/jwt_pub.pem`    | PEM file for verifying access tokens          |
| `CC_GW__RATE_LIMIT_PER_MINUTE` | `120`                   | Global per-IP request cap                     |
| `RUST_LOG`                     | `info,api_gateway=debug`| Structured log filter                         |

---

## 4. Public API Surface

### 4.1 Authentication
```
POST /v1/auth/login     (Body: { "wallet_sig": "0x…" })
200 OK → { "access_token": "jwt", "expires_in": 900 }

GET  /v1/auth/refresh   (header: Authorization: Bearer <refresh>)
```

### 4.2 NFT Lifecycle
```
GET  /v1/nfts/:id
POST /v1/nfts           (mint)
POST /v1/nfts/:id/remix
```

### 4.3 Marketplace
```
GET  /v1/marketplace/listings                   (filters via query params)
POST /v1/marketplace/listings                  (create ask/bid)
POST /v1/marketplace/listings/:id/fulfill
```

OpenAPI spec is generated at `/openapi.json` and interactive Swagger UI is served at `/docs`.

---

## 5. Architectural Highlights

### 5.1 Robust Configuration Pattern
```rust
/// src/config.rs
use serde::Deserialize;
use std::time::Duration;

#[derive(Debug, Deserialize, Clone)]
pub struct GatewayConfig {
    pub listen_addr: String,
    pub public_url: String,
    pub jwt_public_key_path: String,
    pub rate_limit_per_minute: u32,
    #[serde(default = "default_timeout")]
    pub grpc_timeout: Duration,
}

fn default_timeout() -> Duration {
    Duration::from_secs(3)
}
```
A single, strongly-typed configuration struct is hydrated via the excellent `config` crate, merging:
`Config.<profile>.toml` ⟶ `Config.local.toml` ⟶ env variables ⟶ CLI overrides.

### 5.2 Tower Service Graph
```
                        +-------------------+
HTTP Requests ────────▶ |   Axum Router     | ──▶ gRPC clients ──▶ downstream services
                        +-------------------+
  │           TLS, compression, auth, metrics, timeout, retry, circuit-breaker
  ▼
Back-pressure, fair queueing
```

### 5.3 Cryptography Strategy Pattern
Compile-time feature flags toggle between signature schemes:
```
cargo build -F bls
cargo build -F kyber
```
`src/auth.rs` performs signature verification by dispatching on the active strategy and returns a type-erased `PublicKey` for further RBAC checks.

---

## 6. Local Development & Testing

```bash
# Run unit tests + doc tests
cargo test -p api_gateway

# Hot–reload server while editing
cargo watch -x 'run -p api_gateway --features ed25519'
```

### 6.1 gRPC Integration Tests
```rust
#[tokio::test]
async fn mint_roundtrip_ok() {
    let app = spawn_gateway().await;
    let token = login_as_artist(&app).await;
    let nft = mint_sample_nft(&app, &token).await;
    assert_eq!(nft.layers.len(), 3);
}
```

---

## 7. Observability

* **Tracing** (distributed): `tracing_subscriber` pushes spans to OTLP (Jaeger/Grafana Tempo).
* **Metrics**: `axum_prometheus` exports `/metrics` compatible with Prometheus.
* **Health Checks**: `GET /healthz` verifies downstream gRPC channels with a deadline budget.

---

## 8. Security Considerations

* All JWTs use ECDSA P-256 + SHA-256 (default) or BLS signatures (feature flag).
* Rate-limiting and circuit-breaker thresholds are adaptive (EMA of last 10 min window).
* Sensitive configs (DB passwords, API keys) are injectable via [doppler.com](https://doppler.com/) secrets manager in production.

---

## 9. Deployment Matrix

| Environment | Ingress            | TLS Termination | Secrets Backend | Image Tag |
|-------------|--------------------|-----------------|-----------------|-----------|
| Dev         | `nginx:alpine`     | self-signed     | `.env`          | `:edge`   |
| Staging     | AWS ALB            | ACM             | AWS SecretMgr   | `:rc`     |
| Production  | Cloudflare Tunnel  | CF Origin Cert  | HashiCorp Vault | `:v*`     |

**Helm charts** live at `deploy/charts/api-gateway` and integrate seamlessly with ArgoCD pipelines.

---

## 10. Contributing

1. Fork → feature branch → PR
2. Pre-push hook runs `cargo fmt`, `clippy --deny warnings`, `cargo test`
3. At least one approving review + passing CI to merge into `main`

Happy hacking! 🙏🎨🎶  

---

## 11. License
Dual-licensed under **Apache-2.0 + MIT**, the same as the Rust compiler itself.  
See `/LICENSE-APACHE` and `/LICENSE-MIT` for details.