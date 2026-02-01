```markdown
# CrowdPay Connect – KYC Service  
_Secure, event-driven Know-Your-Customer micro-service_

---

## 1  Overview
The **KYC Service** is a self-contained micro-service responsible for:

* end-to-end collection and verification of customer identity data,
* orchestration of external KYC/KYB vendors,
* real-time publishing of verification events used across the CrowdPay ecosystem,
* continuous sanction & PEP (Politically Exposed Persons) screening,
* secure storage of sensitive identity artefacts (GDPR/CCPA compliant).

The service adheres to CrowdPay’s core architectural tenets: **Security-by-Design, Event Sourcing, CQRS, and the Saga Pattern**.  
Written in Python 3.11, it exposes both **REST** and **async message** interfaces, emitting domain events onto the internal **RabbitMQ**/**Kafka** bus.

---

## 2  Key Concepts & Flow

```text
┌──────────┐      (1) POST /applications          ┌──────────────┐
│ Frontend │  ───────────────────────────────────▶ │  KYC Service │
└──────────┘                                      ├──────────────┤
                                                 (2) Persist cmd │
                                                  │ + snapshot   │
                                                  ├──────────────┤
                                                  │(3) Publish   │
                                                  │   "KYC_APPL" │─────┐
                                                  └──────────────┘     │
                                                                       ▼
                                                             ┌────────────────┐
                                                             │ Anti-Fraud Svc │
                                                             └────────────────┘
```

1. A CrowdPay application (web/mobile/backend) submits a **KYC Application** via HTTP.
2. The Command layer writes an immutable event to the event store (PostgreSQL + `wal2json`) and snapshots the current aggregate state.
3. The **KYC_CREATED** event is broadcast internally so that other bounded contexts (e.g. fraud, credit-scoring) can react independently.

If any downstream action fails (e.g. vendor downtime), the Saga orchestrator rolls back the transaction and emits a **KYC_ROLLBACK** event, ensuring global consistency.

---

## 3  Public API

### 3.1  HTTP Endpoints
| Method | Path | Description | Auth |
| ------ | ---- | ----------- | ---- |
| `POST` | `/v1/kyc/applications` | Submit new application | `Bearer` |
| `GET`  | `/v1/kyc/applications/{application_id}` | Retrieve single application | `Bearer` |
| `PATCH`| `/v1/kyc/applications/{application_id}` | Update pending application (limited) | `Bearer` |
| `GET`  | `/v1/kyc/applications` | List applications (filterable) | `Bearer` |

HTTP status codes follow [RFC 7807](https://datatracker.ietf.org/doc/html/rfc7807) (Problem Details).

### 3.2  Domain Events
All events share a common envelope complying with the [CloudEvents v1.0](https://cloudevents.io/) spec.

| Topic | Type | Payload |
| ----- | ---- | ------- |
| `kyc.events` | `KYC_CREATED`    | `KycApplicationCreated` |
| `kyc.events` | `KYC_VERIFIED`   | `KycApplicationVerified` |
| `kyc.events` | `KYC_REJECTED`   | `KycApplicationRejected` |
| `kyc.events` | `KYC_ROLLBACK`   | `KycSagaRollback` |

---

## 4  Data Contracts

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ApplicationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class ApplicantDocument(BaseModel):
    doc_type: str = Field(..., examples=["PASSPORT", "NATIONAL_ID"])
    file_id: UUID
    issued_country: str = Field(..., min_length=2, max_length=2)


class KycApplication(BaseModel):
    id: UUID
    user_id: UUID
    email: EmailStr
    created_at: datetime
    status: ApplicationStatus = ApplicationStatus.PENDING
    reason: Optional[str] = None
    documents: list[ApplicantDocument] = Field(default_factory=list)
```

These models are **shared via a pip-installable package** (`crowdpay-contracts`) to guarantee cross-service schema alignment.

---

## 5  Python Client Usage

```python
"""
Example: Asynchronously create and poll a KYC application
"""
import asyncio
import os
from uuid import uuid4

import httpx
from crowdpy_auth import CrowdPayAuth  # Internal shared lib

API_BASE = os.getenv("KYC_API_URL", "http://localhost:8180/v1")


async def submit_kyc_session(token: str) -> str:
    async with httpx.AsyncClient(auth=CrowdPayAuth(token=token)) as client:
        resp = await client.post(
            f"{API_BASE}/kyc/applications",
            json={
                "user_id": str(uuid4()),
                "email": "alice@example.com",
                "documents": [
                    {
                        "doc_type": "PASSPORT",
                        "file_id": str(uuid4()),
                        "issued_country": "US",
                    }
                ],
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["id"]  # Application ID


async def wait_for_verification(app_id: str, token: str, timeout: int = 90) -> None:
    async with httpx.AsyncClient(auth=CrowdPayAuth(token=token)) as client:
        for _ in range(timeout // 3):
            resp = await client.get(f"{API_BASE}/kyc/applications/{app_id}")
            resp.raise_for_status()
            data = resp.json()
            print(f"[poll] status={data['status']}")
            if data["status"] in {"VERIFIED", "REJECTED"}:
                return
            await asyncio.sleep(3)
        raise TimeoutError("KYC verification timed out")


async def main() -> None:
    app_id = await submit_kyc_session(token=os.environ["ACCESS_TOKEN"])
    await wait_for_verification(app_id, os.environ["ACCESS_TOKEN"])
    print(f"KYC flow completed for application {app_id}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6  Configuration

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `KYC_DB_DSN` | `postgresql://crowdpay:<pwd>@db:5432/kyc` | PostgreSQL connection URI |
| `KYC_EVENT_BROKER_URL` | `amqp://guest:guest@rabbitmq:5672/` | AMQP broker URI |
| `KYC_JWT_PUBLIC_KEY_URL` | — | JWKS endpoint for token validation |
| `KYC_VENDOR_API_KEY` | — | Credentials for external KYC provider |
| `KYC_MAX_RETRIES` | `3` | Max vendor retries before rejection |

All sensitive variables **must** be injected at runtime—never committed.

---

## 7  Running Locally

```bash
# Clone sub-repo and spin up dependencies
git clone https://github.com/crowdpay/connect.git && cd connect/services/kyc_service
cp .env.sample .env                 # <-- fill missing secrets
docker compose up ‑d                # Postgres, RabbitMQ, MinIO
# Run migrations & service (hot-reload)
poetry install
poetry run alembic upgrade head
poetry run uvicorn kyc_service.api.main:app --reload --port 8180
```

Navigate to `http://localhost:8180/docs` for interactive OpenAPI.

---

## 8  Testing

```bash
poetry run pytest --cov=kyc_service --cov-report=term-missing
```

Unit, integration, and contract tests are executed in CI (GitHub Actions) across Python 3.11 & 3.12.

---

## 9  Security & Compliance

* **PII encryption at rest** (AES-256 GCM via `libsodium`).
* **Field-level access control** enforced by JWT & OPA policies.
* Automated **GDPR data-deletion workflow** triggers upon account closure.
* Yearly **penetration tests** and dependency vulnerability scanning (Snyk).

---

## 10  Extending the Service

1. Add new external vendor adapter under `kyc_service/vendors/`.
2. Register adapter in `kyc_service.settings.AvailableVendors`.
3. Provide corresponding Pydantic model & unit tests.
4. Ensure Saga compensation logic (rollback) is covered.

---

## 11  FAQ

> **Q:** How long does verification take?  
> **A:** Average 40 seconds (95-th percentile) using our default vendor stack.

> **Q:** Where are documents stored?  
> **A:** Encrypted in S3-compatible object store (MinIO > 4.0) behind VPC endpoints.

> **Q:** Which regulatory frameworks are supported?  
> **A:** Currently FINCEN (US), FCA (UK) and MAS (SG). Region-specific policies can be toggled per tenant.

---

_© 2024 CrowdPay Connect — All rights reserved._
```