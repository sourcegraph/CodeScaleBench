```markdown
# CrowdPay Connect – **User Service**

A stateless, event-driven micro-service responsible for:

* onboarding and lifecycle management of platform users;
* real-time KYC + AML verification orchestration;
* issuance and rotation of cryptographic credentials;
* publishing of domain events (UserRegistered, UserVerified, RiskScoreUpdated, …);
* serving CQRS read-models consumed by other bounded contexts.

The **User Service** is written in Python 3.11, follows security-by-design principles and is deployable as a container on Kubernetes.  
It interacts with other CrowdPay components through gRPC, an internal event bus (Kafka) and PostgreSQL for strongly-consistent write models.

---

## ✨ Key Capabilities

| Capability                 | Description                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------- |
| KYC/AML Orchestration      | Pluggable provider interface (SumSub, Stripe Identity, Onfido) + automatic fallback / retries                |
| Risk Assessment Hooks      | Publishes risk vectors that feed the platform’s unified `risk-assessment` domain micro-service               |
| Multi-Currency Readiness   | Stores user locale & preferred settlement currency for use by `settlement-engine`                            |
| Audit Trail                | Every mutating command persists an immutable audit record ‑ signed and tamper-evident (Hash-chain)           |
| Data Privacy Compliance    | GDPR + CCPA compliant data retention & Right-to-Be-Forgotten helpers                                         |
| Observability              | OpenTelemetry traces + Prometheus metrics + Structured JSON logging                                          |

---

## 🏛️ High-Level Architecture

```text
                ┌─────────────┐       RegisterUserCmd     ┌───────────────────┐
  Client / BFF  │  GraphQL /  ├──────────────────────────►│  User Service     │
                │  REST API   │                           │ (Write-Model)     │
                └─────────────┘                           └─────────┬─────────┘
                                                                    │ Persist
                                 ┌───────────────Event──────────────┘
                                 ▼
                        Kafka Topic: user.events
                                 │
         ┌───────────────────────┼──────────────────────────────────┐
         ▼                       ▼                                  ▼
┌─────────────────┐    ┌────────────────────┐              ┌────────────────────┐
│ Notification    │    │ Risk-Assessment    │              │ ComplianceService  │
│ Service         │    │ Service           │              │                    │
└─────────────────┘    └────────────────────┘              └────────────────────┘
```

* Commands mutate the **write-model** (PostgreSQL, SERIALIZABLE tx).  
* Mutations emit **domain events** to Kafka.  
* Read-models (Redis) are updated by separate **projector** workers (CQRS pattern).  
* Sagas ensure cross-service consistency, e.g. KYC verification saga might compensate by disabling a user if provider callbacks fail.

---

## ⚡ Quick Start (Development)

```bash
# 1. Clone repository
git clone git@github.com:crowdpay/connect.git
cd connect/services/user_service

# 2. Spin up local stack (PostgreSQL + Kafka + Redis + Jaeger)
docker compose -f infra/local/docker-compose.yml up -d

# 3. Create virtual environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt

# 4. Run service with autoreload
export APP_ENV=local
uvicorn user_service.main:app --reload

# 5. Tail logs
docker compose logs -f user_service
```

---

## 🛠️ Environment Variables

| Variable                        | Required | Default           | Description                                                    |
| ------------------------------- | -------- | ----------------- | -------------------------------------------------------------- |
| `APP_ENV`                       | no       | `local`           | Execution environment (`local`, `staging`, `prod`)             |
| `DATABASE_DSN`                  | yes      | —                 | PostgreSQL DSN                                                 |
| `REDIS_URL`                     | yes      | —                 | Redis connection string                                        |
| `KAFKA_BOOTSTRAP`               | yes      | —                 | Kafka brokers (comma-sep)                                      |
| `KYC_PROVIDER`                  | yes      | `sumsub`          | Which KYC adapter to load                                      |
| `JWT_PRIVATE_KEY_PATH`          | yes      | `./keys/app.key`  | PEM file used for signing user JWTs                            |
| `JWT_PUBLIC_KEY_PATH`           | yes      | `./keys/app.pub`  | PEM file used for verifying JWTs                               |
| `SENTRY_DSN`                    | no       | —                 | Enable crash reporting                                         |

Secrets should be stored in **HashiCorp Vault** (prod) or docker secrets (staging).

---

## 🌐 API Surface

### 1. gRPC – `user.proto`

```protobuf
service UserService {
  rpc RegisterUser (RegisterUserRequest) returns (UserResponse);
  rpc GetUserById  (GetUserRequest)     returns (UserResponse);
  rpc VerifyUser   (VerifyUserRequest)  returns (UserResponse);
  rpc ListUsers    (ListUsersRequest)   returns (stream UserResponse);
}
```

### 2. HTTP REST

```http
POST /v1/users
GET  /v1/users/{id}
PATCH /v1/users/{id}/verify
GET  /v1/users?cursor=<opaque>&limit=50
```

All responses conform to JSON:API spec  
Request/response examples live in `docs/swagger.yaml` (OpenAPI 3.1).

---

## 🔐 Security Notes

1. All endpoints require **mTLS** inside service mesh (Linkerd).  
2. Sensitive PII encryption at rest using AES-256-GCM keys managed via AWS KMS.  
3. JWTs signed with `ES256` using rotated, short-lived keys.  
4. Rate-limiting & IP reputation handled upstream by **API-Gateway**.

---

## 🚦 Testing Strategy

* Unit tests – pytest + `pytest-mocker` (≥ 90 % coverage gate enforced in CI).  
* Contract tests – Pact files committed to `contracts/`.  
* Integration tests – Docker Compose spins real services; run via `make test-integration`.  
* Load tests – Locust scenarios maintained in `load/`.

CI pipeline (`.github/workflows/ci.yml`) runs all stages and blocks PR merge if any fail.

---

## 🪵 Observability

Metric                    | Description                         | Prometheus Label Set
------------------------- | ----------------------------------- | --------------------
`user_commands_total`     | counter for accepted commands       | `command_name`, `status`
`kyc_latency_seconds`     | histogram of KYC provider latency   | `provider`
`user_events_in_flight`   | gauge of unprocessed events         | `event_type`

Traces are exported through OTLP to **Jaeger** => **Grafana** dashboards.

---

## ▶️ Sequence Diagram – `RegisterUser`

```text
Client  ->  UserService         : POST /users
UserService  ->  Postgres       : INSERT users (transaction)
UserService  ->  Kafka          : Publish UserRegistered
Kafka  ->  KYCService           : UserRegistered(event)
KYCService  ->  KYCProvider     : /verify (REST)
KYCProvider ->  KYCService      : callback (webhook)
KYCService  ->  Kafka           : UserVerified
UserService (Read Model) listens to UserVerified & updates projection
```

---

## 👷‍♂️ Development Guidelines

1. Keep write-models **pure**, do not leak FastAPI or gRPC types.  
2. Each domain event MUST be versioned (`v1`, `v2` …) and backward compatible.  
3. SQL migrations via **Alembic**. Revertible & idempotent.  
4. Avoid cross-service calls from controllers; delegate to **Application Layer**.  
5. External API integrations must implement **Retry with Jitter** + **Circuit Breaker** (see `infra/resilience.py`).  

---

## 🗂️ Project Layout (excerpt)

```text
user_service/
├── application/
│   ├── commands.py          # DTOs and validation
│   ├── handlers.py          # Command handlers
│   └── events.py            # Domain events
├── domain/
│   ├── entities.py          # User aggregate root
│   ├── value_objects.py
│   └── services.py          # Domain services (e.g., RiskScorePolicy)
├── infrastructure/
│   ├── persistence/
│   │   ├── repositories.py  # Postgres implementation
│   │   └── models.py        # SQLAlchemy models
│   ├── messaging/
│   │   └── kafka_producer.py
│   └── kyc/
│       ├── base.py
│       ├── sumsub_adapter.py
│       └── stripe_adapter.py
├── presentation/
│   ├── grpc/
│   └── http/
├── tests/
│   └── …
└── main.py                  # FastAPI app + DI container
```

---

## 🚀 Deployment

* Container image built by `Dockerfile` → `ghcr.io/crowdpay/user-service:<sha>`.  
* Helm chart located in `deploy/chart/`. Roll-out strategy is **Canary + Analysis** via Argo Rollouts.  
* Secrets mounted as `Kubernetes Secrets` backed by Sealed Secrets CRD.  
* Horizontal Pod Autoscaler driven by `cpu`, `memory`, and custom `user_commands_total` QPS.

---

## 📜 License

`CrowdPay Connect` © 2023-2024 CrowdPay Technologies, Inc.  
This project is proprietary; redistribution or reverse engineering is strictly prohibited without prior written consent.

---
```