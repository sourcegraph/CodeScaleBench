```markdown
# CrowdPay Connect • Transaction Service

Transactional micro–service responsible for **orchestrating, persisting and
settling every monetary movement** inside a CrowdPod.  
Implements **CQRS + Event-Sourcing**, participates in **distributed Sagas** and
enforces **Security-by-Design** principles (KYC, fraud-detection,
rate-limiting, audit-trail).

---

## 1. Responsibilities

1. **Command Side** – accepts _Transfer_, _Top-Up_, _Withdrawal_ or _FX Swap_
   commands, validates them against:
   • risk‐engine, • KYC state, • account limits, • FX quotation TTL.
2. **Event Store** – append-only stream (`postgresql` → `wal2json` logical
   slot) storing immutable `TransactionEvent`s.
3. **Query Side** – pre-computed projections kept in `read_model.transactions`
   for low-latency reads / reporting.
4. **Saga Coordination** – publishes domain events to the message broker
   (`NATS JetStream`) and listens for compensation commands in case of failure
   (e.g. failed FX settlement, AML hit).
5. **Compliance Trail** – ships signed hash of every event to the `audit-vault`
   micro-service for tamper-proof archiving.

---

## 2. Service APIs

| Method                            | Transport | Auth        | Description                              |
|----------------------------------|-----------|-------------|------------------------------------------|
| POST /v1/transactions            | REST      | JWT + mTLS  | Initiate a new transaction command       |
| GET  /v1/transactions/{id}       | REST      | JWT + mTLS  | Fetch aggregate / projections            |
| gRPC `TransactionService.Create` | gRPC      | mutual TLS  | Low-latency ingestion for internal calls |

> NOTE  
> Public SDKs wrap these endpoints and transparently handle retries,
> idempotency keys, and saga correlation IDs.

---

## 3. Quick-Start (local)

```bash
# 1. Clone mono-repo
git clone git@github.com:crowdpay/connect.git
cd connect/services/transaction_service

# 2. Bootstrap Docker stack
make infra-up     # postgres, nats, jaeger, redis, audit-vault
make migrate      # executes Alembic migrations
make seed-secrets # generates self-signed certs for mTLS
make dev          # reloads on code changes
```

Environment variables (see `.env.example`):

```
DATABASE_URL=postgresql+asyncpg://user:pwd@localhost:5432/transactions
MESSAGE_BROKER_URL=nats://localhost:4222
JWT_PUBLIC_KEY_PATH=/secrets/jwks.json
SENTRY_DSN=
FX_QUOTE_SERVICE_URL=http://fx:8000
```

---

## 4. Folder Structure

```
transaction_service/
├── adapters/          # IO / Framework glue code
│   ├── http/          # FastAPI routers & DTOs
│   ├── grpc/          # gRPC generated stubs
│   └── messaging/     # NATS JetStream publisher / consumer
├── application/       # CQRS command & query handlers
├── domain/            # Pure business logic, aggregates & value objects
├── infra/             # DB models, migrations, observability, cache
└── tests/             # pytest with Hypothesis property-based tests
```

---

## 5. Code Samples

### 5.1 Creating a Transaction (Python SDK)

```python
from crowdpay_connect.sdk import CrowdPayClient
from crowdpay_connect.sdk.models import (
    Money,
    TransactionCommand,
    TransactionType,
)

client = CrowdPayClient(
    base_url="https://api.crowdpay.io",
    api_key="cp_live_xxx",                # automatically exchanged for JWT
    tls_cert="/path/to/client-cert.pem",
    tls_key="/path/to/client-key.pem",
)

cmd = TransactionCommand(
    pod_id="pod_abcd1234",
    type=TransactionType.TRANSFER,
    amount=Money(currency="EUR", value="250.00"),
    beneficiary_wallet_id="wallet_xyz",
    description="Weekend trip booking",
    idempotency_key="b54e26a1-90fc-4dc6-95b2-7c9f3d2f24ab",
)

tx = client.transactions.create(cmd)
print(tx.status)     # -> PENDING
```

### 5.2 Subscribing to Events (internal service)

```python
import asyncio
from crowdpay_connect.event_bus import EventBus
from crowdpay_connect.events import TransactionSettled, TransactionFailed

async def handle_settled(evt: TransactionSettled) -> None:
    print(f"[✓] Transaction {evt.transaction_id} settled in ledger.")

async def handle_failed(evt: TransactionFailed) -> None:
    print(f"[✗] Transaction {evt.transaction_id} rolled back: {evt.reason}")

bus = EventBus("nats://nats:4222")

bus.subscribe(TransactionSettled, handle_settled)
bus.subscribe(TransactionFailed, handle_failed)

asyncio.run(bus.run_forever())
```

### 5.3 Compensation Workflow (Saga)

```python
from transaction_service.application.commands import CompensateFxLeg
from transaction_service.domain.saga import saga_manager

async def compensate_failed_fx(tx_id: str, reason: str) -> None:
    cmd = CompensateFxLeg(transaction_id=tx_id, failure_reason=reason)
    await saga_manager.handle(cmd)
```

---

## 6. Error Codes

| Code | HTTP | Meaning                                                        |
|------|------|----------------------------------------------------------------|
| T001 | 422  | Validation failed (limits, KYC, sanctions)                     |
| T002 | 409  | Duplicate idempotency key                                      |
| T003 | 503  | Upstream dependency unavailable (FX, Risk Engine, Ledger)      |
| T004 | 402  | Insufficient funds after pre-authorization                     |
| T005 | 500  | Unexpected server error – error reference broadcast to Sentry  |

All errors embed a `trace_id` header for correlation across micro-services.

---

## 7. Testing & Quality Gates

• **Unit / Integration tests** → `pytest -q` (95 %+ coverage enforced)  
• **Static Analysis** → `ruff` + `mypy --strict` + `bandit -r .`  
• **Load tests** → `k6` scripts in `infra/load/` targeting 1 k TPS, <50 ms p95  
• **Chaos / Saga fault-injection** → `litmuschaos` experiments: randomly abort
  FX legs and verify compensation.

CI pipeline hosted on **GitHub Actions**; all gates must pass before merge.

---

## 8. Observability

Metric / Trace            | Tool   | Example
--------------------------|--------|--------------------------------------------
Latency (ms), TPS         | Prometheus + Grafana | `transaction_processing_latency_p95`
Distributed Traces        | Jaeger | view saga spans across services
Audit Trail Verification  | Audit-Vault | merkle root per 10 000 events
Error Percent / SLO       | Sentry | alert at 1 % 5-min error rate

---

## 9. Security Considerations

• mTLS mutual authentication between micro-services  
• **OPA** side-cars evaluate ABAC policies on impersonation and circle roles  
• Event payloads **field-level encrypted** for PII (`ChaCha20-Poly1305`)  
• Periodic **CST** (Continuous Security Testing) scan → `trivy` & `semgrep`  
• One-time secrets loaded via **HashiCorp Vault** with short-lived leases

---

## 10. Roadmap

1. Add lattice-based **confidential computing** enclave for AML model execution  
2. Integrate **ISO-20022** messaging for bank settlements  
3. Roll-out **WebAuthn** transactional signing (FIDO2) for high-value flows

---

<div align="center">

Made with 💜 by the CrowdPay Connect Core Payments Team  
_“Trust by Design, at Social Scale.”_

</div>
```