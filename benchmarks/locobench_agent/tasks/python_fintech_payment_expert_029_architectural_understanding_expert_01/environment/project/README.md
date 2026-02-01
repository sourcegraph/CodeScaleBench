```markdown
# CrowdPay Connect

Social-first, component-based payment orchestration for the next generation of community finance.

![CrowdPay Connect Banner](docs/assets/crowdpay_banner.png)

[![CI](https://github.com/<your-org>/crowdpay_connect/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-org>/crowdpay_connect/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CrowdPay Connect enables friends, families, fan-clubs and community groups to create **dynamic payment circles**—called **CrowdPods**—where funds can be pooled, split, lent, or donated in *multiple currencies* with transparent compliance, real-time risk controls, and gamified reputation mechanics.

---

## ✨ Key Features

| Category            | Highlights                                                                                                   |
|---------------------|---------------------------------------------------------------------------------------------------------------|
| Multi-Currency      | Seamless conversion and settlement in 140+ fiat and digital currencies.                                       |
| Secure by Design    | End-to-end encryption, zero-trust micro-service mesh, and automated KYC/KYB flows.                            |
| Social Layer        | Follow Pods, up-vote trusted payers, earn compliance badges, and view audit-safe reputation scores.           |
| Saga Orchestration  | Distributed workflows guarantee atomic settlement or full rollback across cross-border rails.                 |
| Event Sourcing      | All domain events are append-only and tamper-proof, powering real-time notifications and analytics.           |
| Audit Trail         | Immutable ledger entries allow turnkey compliance reporting (SOX, GDPR, PCI-DSS, PSD2).                      |
| Developer-Friendly  | Python 3.10+, fully-typed APIs, async-first SDK, and GraphQL/REST gateways.                                   |

---

## :rocket: Quick Start (Docker Compose)

```bash
git clone https://github.com/<your-org>/crowdpay_connect.git
cd crowdpay_connect

# Copy environment template & set secrets
cp .env.example .env
${EDITOR:-vi} .env

# Build & run local stack
docker-compose -f deploy/local/docker-compose.yml up --build
```

The stack boots the following core services:

- `gateway-api`: GraphQL + REST façade (FastAPI)
- `auth-service`: OAuth2 + JWT provider
- `pod-service`: CrowdPod domain aggregate (CQRS/ES)
- `ledger-service`: double-entry ledger & settlement sagas
- `risk-service`: real-time risk engine (streaming Flink)
- `notification-service`: event-driven WebSocket & push gateway
- `postgres`, `redis`, `kafka`, `minio` (S3-compatible object store)

Once healthy, visit **http://localhost:8080/docs** for interactive API docs.

---

## 🐍 Usage Example (Python SDK)

```python
from crowdpay_connect import CrowdPayClient
from crowdpay_connect.models import Currency

client = CrowdPayClient(
    api_base="https://sandbox.api.crowdpay.io",
    api_key="sk_test_51H...",
)

# 1. Create a CrowdPod
pod = client.pods.create(
    name="EuroTrip 2025",
    default_currency=Currency.EUR,
    members=["alice@example.com", "bob@example.com"],
)
print(pod.id)  # -> cpod_2f32...

# 2. Pledge funds
client.pods.pledge_funds(
    pod_id=pod.id,
    amount=250_00,           # €2.50 in minor units
    source="card_1J4K...",
)

# 3. Split a bill
client.pods.split_bill(
    pod_id=pod.id,
    amount=1_200_00,         # €12.00
    strategy="equal",
    memo="Lunch @ Lisboa",
)

# 4. Withdraw to bank account once trip is done
client.pods.initiate_settlement(
    pod_id=pod.id,
    target_iban="DE89370400440532013000",
)
```

---

## ⚙️ Configuration

Environment variables are loaded via [`pydantic.BaseSettings`](./crowdpay_connect/core/config.py).

| Variable                    | Description                                                                  | Default      |
|-----------------------------|------------------------------------------------------------------------------|--------------|
| `CROWD_PAY_ENV`            | `local`, `staging`, `production`                                             | `local`      |
| `DATABASE__URL`            | Postgres connection string (`asyncpg`)                                        | `postgres://`|
| `REDIS__URL`               | Redis endpoint for rate-limiting & caching                                    | `redis://`   |
| `KAFKA__BOOTSTRAP_SERVERS` | Kafka brokers for event bus                                                  | `localhost:9092` |
| `S3__ENDPOINT_URL`         | MinIO/S3 bucket for receipt uploads                                          | —            |
| `AUTH__JWT_SECRET`         | Private key or secret for signing JWT access tokens                          | —            |

---

## 🏗️ Project Architecture

```
                                 ┌───────────────────────────┐
                                 │       API Gateway        │
                                 └───────▲────────▲─────────┘
                                         │        │
                    ┌────────────────────┘        └───────────────────┐
                    │                                                 │
            ┌───────┴────────┐                               ┌────────┴────────┐
            │  Auth Service  │                               │  Notification   │
            └───────▲────────┘                               └────────▲────────┘
                    │                                                         ▲
                    │                                                         │
┌───────────────────┴───────────┐        Saga Events           ┌──────────────┴─────────────┐
│         Pod Service           │───────────────┬────────────►│      Risk Service          │
└───────────────────▲───────────┘               │             └──────────────▲─────────────┘
                    │                           │                             │
                    │                       ┌───┴───┐                    ┌────┴────┐
                    │                       │Ledger │◄───────────────────│Currency  │
                    │                       └───────┘   FX Rates        │  Router  │
                    │                                                       └────────┘
```

1. **CQRS/ES**: Each write emits an immutable domain event (PostgreSQL + Kafka). Reads are projected to optimized views.
2. **Sagas**: Long-running, cross-service workflows (e.g., multi-currency settlement) are coordinated via the `ledger-service`.
3. **Security by Design**: Every HTTP/gRPC call carries a short-lived JWT. Mutual TLS secures inter-service mesh.
4. **Observability**: OpenTelemetry traces, Prometheus metrics, and Grafana dashboards out-of-the-box.

---

## 🛡️ Security & Compliance

- **PCI-DSS v4.0**: Cardholder data is vaulted with an external tokenization provider.
- **PSD2 / SCA**: Strong Customer Authentication flows via WebAuthn/FIDO2.
- **GDPR**: Right-to-erasure and data portability baked into aggregates.
- **Audit Logging**: SHA-256 hashed logs streamed to immutable storage (AWS QLDB by default).

---

## 🧪 Testing

```bash
# Lint + typecheck
pre-commit run --all-files

# Unit tests
pytest -q

# Contract tests (pact)
pytest tests/contracts
```

CI pipeline enforces 90%+ coverage with mutation testing (**Mutmut**).

---

## 📦 Packaging & Release

We follow **Semantic Versioning**. Tags are published to:

- PyPI: `pip install crowdpay-connect`
- Docker Hub: `crowdpay/connect:<version>`

Release artifacts are signed via **Sigstore** and verified in CI.

---

## 🤝 Contributing

1. Fork the repo and create your branch: `git checkout -b feat/my-feature`
2. Commit your changes: `git commit -m 'feat: add my feature'`
3. Push and open a PR – follow the _Conventional Commits_ style guide.
4. Ensure all status checks pass and at least one maintainer reviews your PR.

We abide by the [Contributor Covenant](CODE_OF_CONDUCT.md).

---

## 📝 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

### © 2024 CrowdPay Connect
*Making money social, transparent, and fun again.*
```