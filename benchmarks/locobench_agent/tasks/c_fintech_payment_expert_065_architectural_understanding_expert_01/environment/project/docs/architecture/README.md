```markdown
# EduPay Ledger Academy – Architecture Overview
Fintech Payment Platform for Higher-Education Institutions  
_Last updated: 2023-12-05_

---

## 1  Purpose of this Document
This README describes the **Clean-Architecture** blueprint that governs every source
file in this repository.  
It is intended for:

* Faculty who use the codebase as teaching material
* Contributors adding new tuition-payment features
* Security auditors performing PCI-DSS or FERPA reviews
* DevOps engineers deploying microservices to Kubernetes

---

## 2  High-Level View

```mermaid
graph TD
    UI[Web / Mobile / CLI] -->|REST / gRPC| APIGateway
    APIGateway --> CmdSvc[Command Service]
    APIGateway --> QuerySvc[Query Service]
    subgraph Event Bus ➀
        Kafka[(Kafka Topic::Ledger.Events)]
    end
    CmdSvc -->|Publish DomainEvent| Kafka
    Kafka -->|Project to Read Model| QuerySvc
    CmdSvc -->|Dispatch| BoundedContexts
    BoundedContexts -->|Invoke| SagaOrchestrator
    SagaOrchestrator -->|Persist| AuditTrail[(Append-Only Ledger)]
```

Legend  
➀ Event Bus is pluggable. Professors may replace **Kafka** with **NATS** or
**RabbitMQ** without touching business rules.

---

## 3  Clean Architecture Layering

| Layer (Dir) | Stability | Example Components | Compile-Time Dependency |
|-------------|-----------|--------------------|-------------------------|
| `domain` | 💎 Most stable | `payment.h`, `currency.h` | _None_ |
| `usecase` | 🏛️ Stable | `register_student.c`, `process_refund.c` | `domain` |
| `interface` | 🌐 Replaceable | `http_controller.c`, `grpc_adapter.c` | `usecase` |
| `infrastructure` | 🔌 Volatile | `postgres_repo.c`, `kafka_producer.c` | `interface` |

The arrows always point _inwards_; outer layers know inner layers, never
vice-versa.

---

## 4  Bounded Contexts

### 4.1 Admissions
* Handles enrollment fees and acceptance deposits
* Emits `AdmissionAccepted` → triggers **Financial-Aid** scholarship allocation saga

### 4.2 Bursar
* Tuition invoicing, late-fee calculations
* Maintains **Multi-Currency** tables using ISO-4217

### 4.3 Financial-Aid
* Scholarship disbursement & stipend scheduling
* Implements **Fraud Detection** heuristics (`aid_risk_score.c`)

### 4.4 Continuing-Education
* Pay-per-micro-credential flows & coupon codes
* Demonstrates **PSD2 SCA** (Strong Customer Authentication) via WebAuthn

---

## 5  Payment Processing Flow (Happy Path)

```plaintext
┌──────────────────┐
│ Student Portal   │
└────────┬─────────┘
         │ POST /tuition/pay
         ▼
┌──────────────────┐
│ API Gateway      │
└────────┬─────────┘
         │ Command: PayTuition
         ▼
┌──────────────────┐
│ Bursar.CmdSvc    │ ① Validate → ② Authorize Card (PCI-DSS) → ③ Emit Paid Event
└────────┬─────────┘
         ▼ publish
┌──────────────────┐
│ Kafka: TuitionPaid│
└────────┬─────────┘
         ▼
┌──────────────────┐
│ QuerySvc         │ ④ Update Materialized View
└──────────────────┘
```

Error cases (insufficient funds, 3-D Secure failure) are handled by the
**Saga Orchestrator** which issues compensating transactions.

---

## 6  Saga Pattern Demonstration Mode

| Failure Point | Compensating Action | Teaching Objective |
|---------------|--------------------|--------------------|
| FX conversion timeout | Revert ledger entry | Idempotent rollbacks |
| Scholarship ledger update fails | Re-credit student card | Distributed tracing |

The mode can be toggled via the compile-time flag  
```c
#define SAGA_DEMO 1
```
in `config/build_flags.h`.

---

## 7  Event Sourcing & CQRS

* **Write Model** – append-only events stored in `audit/ledger.dat`
* **Read Model** – projections in **PostgreSQL** (can swap with **SQLite** for
  classroom labs)
* Replay tool: `bin/ledger-replay --from 2022-01-01`

---

## 8  Security by Design

1. Memory-safe wrappers (`secure_mem.c`) protect against buffer overflows.
2. PCI-DSS scope is minimized by tokenizing PANs via external vault.
3. FERPA compliance: PII fields encrypted with **AES-256-GCM**; keys rotated
   through **HashiCorp Vault** every 24 h.
4. Static analysis integrated with **clang-tidy** and **CodeQL**.

---

## 9  Extensibility: Swapping a Repository

Example: Replace PostgreSQL with MongoDB in a lab.

1. Implement `mongo_payment_repo.c` conforming to
   ```c
   struct payment_repo_vtbl { ... };
   ```
2. Register the concrete type in `infra/repo_factory.c`.
3. No changes required in `usecase/process_payment.c`  
   thanks to the **Dependency Inversion** rule.

---

## 10  Development Conventions

* **C17** standard, compiled with `-Wall -Wextra -pedantic`.
* One public header per component; internal helpers stay in `*.c`.
* Unit tests with **Unity**; acceptance tests scripted in **Bats**.
* Commit messages follow Conventional Commits:
  `feat(bursar): add multi-currency rounding bugfix`.

---

## 11  Directory Tree (excerpt)

```plaintext
src/
 ├─ admissions/
 │   ├─ domain/
 │   ├─ usecase/
 │   └─ interface/
 ├─ bursar/
 │   └─ ...
 ├─ common/
 │   ├─ secure_mem.c
 │   ├─ currency.c
 │   └─ ...
docs/
 └─ architecture/
     └─ README.md  ← you are here
tests/
 ├─ unit/
 └─ integration/
```

---

## 12  Future Work

* Integrate OpenTelemetry for distributed tracing labs.
* Add Rust FFI bindings to compare memory safety.
* Implement ISO-20022 `pain.001` export for cross-border wires.

---

© 2023 EduPay Ledger Academy.  
Licensed under the MIT License – see `LICENSE` for details.
```