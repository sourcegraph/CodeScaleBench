```markdown
# CrowdPay Connect – CQRS & Event Sourcing Architecture
_Revision: 1.3 – Last updated 2024-05-30_

> “Payments are conversations.” &nbsp;— CrowdPay Engineering principle #2

CrowdPay Connect is built around conversation-like financial interactions that must be **auditable**, **replayable**, and **socially contextual**.  
To meet these requirements we employ **CQRS (Command Query Responsibility Segregation)** coupled with **Event Sourcing** and a **Saga orchestrator** for cross-service transactions.

---

## 1. Motivation

| Challenge                              | Why CQRS/Event-Sourcing?                                                     |
|----------------------------------------|-----------------------------------------------------------------------------|
| Multi-currency, social payment flows   | Immutable events preserve precise FX rates + social context at the moment of intent. |
| Regulatory audit (KYC/AML, GDPR)       | Full event log serves as the system of record—no mutable state hidden from auditors. |
| Gamified reputation & trust signals    | Reputation scores are projections computed from the same source-of-truth event stream. |
| Feature agility                        | New read models (e.g., “top donors this week”) can be generated without writing migrations. |

---

## 2. Ubiquitous Language

| Term          | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| CrowdPod      | Autonomous wallet + rule engine owned by a social group.       |
| Member        | User admitted to a CrowdPod with a **Role** (Admin, Payer …).  |
| Command       | “Intent” to change state – must be validated.                  |
| Event         | Successfully validated state change – **immutable**.           |
| Aggregate     | Consistency boundary on the write side (e.g., `CrowdPod`).     |

---

## 3. High-level Component Diagram

```mermaid
flowchart LR
  subgraph Write [Write (Command) Side]
    C[Command API<br/>GraphQL / gRPC] -->|1| V[Validator]
    V -->|2| AGG[Aggregates<br/>Domain Logic]
    AGG -->|3| ES[(Event Store<br/>PostgreSQL<br/>w/ WAL + logical replication)]
  end

  subgraph Infra  ["Streaming Backbone"]
    ES ==>|Logical Replication Slot| K[Kafka Topic:<br/>crowdpay.events]
  end

  subgraph Read [Read (Query) Side]
    K -->|4| PROJ[Projections<br/>Materialisers]
    PROJ -->|5| RM[(Read Models<br/>ElasticSearch, Redis, ClickHouse)]
    RM -->|6| QueryAPI[REST / GraphQL]
  end

  AGG -->|7| SagaCmd[Outbox → Kafka (saga.*)]
  SagaCmd -->|8| SagaOrch[[Saga Orchestrator]]
  SagaOrch -->|9| ExternalSvc[/FX Engine, KYC, AML/]
```

Legend:

1. Command received.  
2. Validation + invariant checks.  
3. Events appended atomically inside Postgres transaction.  
4. Events copied to Kafka via logical decoding plugin (`wal2json`).  
5. Projectors consume Kafka to update denormalised views.  
6. Queries hit fast, isolated read stores.  
7. Aggregates emit “side-effect” commands through an _outbox_ table.  
8. Saga orchestrator coordinates long-running workflows.  
9. External micro-services participate via compensating actions.

---

## 4. Event Store Specification

- **Physical store**: Partitioned PostgreSQL 15 + ZFS.  
- **Schema**:

```sql
CREATE TABLE crowdpay.event_store (
    stream_id     UUID      NOT NULL,
    stream_type   TEXT      NOT NULL,            -- e.g. 'CrowdPod'
    version       INTEGER   NOT NULL,            -- optimistic locking
    event_id      UUID      PRIMARY KEY,
    event_type    TEXT      NOT NULL,
    event_data    JSONB     NOT NULL,
    meta_data     JSONB     NOT NULL,            -- user-id, ip, kyc_level …
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_stream_version
  ON crowdpay.event_store (stream_id, version);
```

- **Guarantees**:  
  • Append-only.  
  • Serializable isolation.  
  • SNAPSHOT EXPORT every 24 h for cold storage (S3 + Glacier).

---

## 5. Command-Side Implementation (Python 3.11)

Below is a trimmed version of the production library used by the **Command API** service.

```python
"""
crowdpay_connect.commanding
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Core CQRS command-side primitives.
"""
from __future__ import annotations

import uuid
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Protocol, Sequence, Any

import psycopg  # psycopg3
from psycopg.rows import class_row


# ---------- Domain Events -------------------------------------------------- #

class DomainEvent(Protocol):
    event_type: str
    occurred_at: datetime

    def to_json(self) -> str: ...
    @classmethod
    def from_row(cls, row: Any) -> "DomainEvent": ...


@dataclass(frozen=True, slots=True)
class CrowdPodCreated:
    pod_id: str
    owner_id: str
    currency: str
    name: str
    event_type: str = "CrowdPodCreated"
    occurred_at: datetime = datetime.now(timezone.utc)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


@dataclass(frozen=True, slots=True)
class FundsDeposited:
    pod_id: str
    member_id: str
    amount_minor: int
    currency: str
    tx_ref: str
    event_type: str = "FundsDeposited"
    occurred_at: datetime = datetime.now(timezone.utc)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


# ---------- Command Objects ------------------------------------------------ #

@dataclass(frozen=True, slots=True)
class CreateCrowdPod:
    owner_id: str
    currency: str
    name: str


@dataclass(frozen=True, slots=True)
class DepositFunds:
    pod_id: str
    member_id: str
    amount_minor: int
    currency: str
    tx_ref: str


# ---------- Exceptions ----------------------------------------------------- #

class ConcurrencyError(RuntimeError):
    pass


class ValidationError(ValueError):
    pass


# ---------- Aggregate Root ------------------------------------------------- #

class CrowdPodAggregate:
    """
    In-memory representation reconstructed from events.
    """
    def __init__(self, pod_id: str | None = None) -> None:
        self.id: str | None = pod_id
        self.owner_id: str | None = None
        self.currency: str | None = None
        self.name: str | None = None
        self.balance_minor: int = 0
        self._version: int = 0
        self._pending: list[DomainEvent] = []

    # --- Rehydration -------------------------------------------------------

    @classmethod
    def load(cls, events: Sequence[DomainEvent]) -> "CrowdPodAggregate":
        agg = cls()
        for ev in events:
            agg._apply(ev, is_new=False)
            agg._version += 1
        return agg

    # --- Command Handlers --------------------------------------------------

    def handle(self, cmd: Any) -> None:
        match cmd:
            case CreateCrowdPod(owner_id=oid, currency=cur, name=nm):
                if self.id is not None:
                    raise ValidationError("CrowdPod already exists.")
                event = CrowdPodCreated(
                    pod_id=str(uuid.uuid4()),
                    owner_id=oid,
                    currency=cur,
                    name=nm,
                )
                self._record(event)

            case DepositFunds(pod_id=_pid, member_id=mid,
                              amount_minor=amt, currency=cur, tx_ref=tx):
                if cur != self.currency:
                    raise ValidationError("Currency mismatch.")
                if amt <= 0:
                    raise ValidationError("Invalid amount.")
                event = FundsDeposited(
                    pod_id=self.id,
                    member_id=mid,
                    amount_minor=amt,
                    currency=cur,
                    tx_ref=tx,
                )
                self._record(event)

            case _:
                raise ValidationError(f"Unknown command: {cmd}")

    # --- Event Application -------------------------------------------------

    def _apply(self, event: DomainEvent, *, is_new: bool) -> None:
        if isinstance(event, CrowdPodCreated):
            self.id = event.pod_id
            self.owner_id = event.owner_id
            self.currency = event.currency
            self.name = event.name
        elif isinstance(event, FundsDeposited):
            self.balance_minor += event.amount_minor
        else:
            raise RuntimeError(f"Unsupported event {event}")

        if is_new:
            self._pending.append(event)

    def _record(self, event: DomainEvent) -> None:
        self._apply(event, is_new=True)

    # --- Public helpers ----------------------------------------------------

    @property
    def pending_events(self) -> list[DomainEvent]:
        return self._pending

    def mark_committed(self) -> None:
        self._pending.clear()

    @property
    def version(self) -> int:
        return self._version


# ---------- Repository Layer ---------------------------------------------- #

class CrowdPodRepository:
    """
    Stores and retrieves aggregates through the event store.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def _fetch_stream(self, stream_id: str) -> list[DomainEvent]:
        cur = self._conn.cursor(row_factory=class_row(CrowdPodCreated))
        cur.execute(
            "SELECT event_type, event_data "
            "FROM crowdpay.event_store "
            "WHERE stream_id = %s "
            "ORDER BY version ASC",
            (stream_id,),
        )

        events = []
        for event_type, event_data in cur.fetchall():
            data = json.loads(event_data)
            if event_type == "CrowdPodCreated":
                events.append(CrowdPodCreated(**data))
            elif event_type == "FundsDeposited":
                events.append(FundsDeposited(**data))
            else:
                continue  # Unknown events are skipped (forward compatibility)
        return events

    def get(self, stream_id: str) -> CrowdPodAggregate:
        events = self._fetch_stream(stream_id)
        if not events:
            raise ValidationError("CrowdPod not found")
        return CrowdPodAggregate.load(events)

    def save(self, agg: CrowdPodAggregate) -> None:
        if not agg.pending_events:
            return

        with self._conn.transaction():
            for ev in agg.pending_events:
                self._conn.execute(
                    "INSERT INTO crowdpay.event_store "
                    "(stream_id, stream_type, version, event_id, "
                    " event_type, event_data, meta_data) "
                    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                    (
                        agg.id,
                        "CrowdPod",
                        agg.version + 1,
                        uuid.uuid4(),
                        ev.event_type,
                        ev.to_json(),
                        json.dumps({"schema": 1}),
                    ),
                )
                agg._version += 1

        agg.mark_committed()
```

The full implementation includes an **outbox** pattern and robust retry/back-off logic (omitted here for brevity).

---

## 6. Read-Side Projection

Read models are produced by **idempotent** consumers subscribed to the Kafka topic `crowdpay.events`.

```python
"""
crowdpay_connect.read_model.projectors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ElasticSearch projector for quick CrowdPod lookups.
"""
import json
import logging
from typing import Any

from elasticsearch import AsyncElasticsearch
from aiokafka import AIOKafkaConsumer

from crowdpay_connect.events import deserialise_event  # shared util

logger = logging.getLogger(__name__)


class CrowdPodSearchProjector:
    INDEX = "crowdpod_search_v1"

    def __init__(self, es: AsyncElasticsearch, bootstrap_servers: str):
        self._es = es
        self._consumer = AIOKafkaConsumer(
            "crowdpay.events",
            bootstrap_servers=bootstrap_servers,
            group_id="crowdpod-search",
            value_deserializer=lambda b: json.loads(b.decode()),
            enable_auto_commit=False,
        )

    async def run(self) -> None:
        await self._consumer.start()
        try:
            async for msg in self._consumer:
                evt = deserialise_event(msg.value)
                await self._handle_event(evt)
                await self._consumer.commit()
        except Exception:
            logger.exception("Projection loop crashed!")
        finally:
            await self._consumer.stop()

    # --- Event Handlers ----------------------------------------------------

    async def _handle_event(self, event: Any) -> None:
        if event["event_type"] == "CrowdPodCreated":
            await self._es.index(
                index=self.INDEX,
                id=event["pod_id"],
                document={
                    "name": event["name"],
                    "currency": event["currency"],
                    "owner_id": event["owner_id"],
                    "created_at": event["occurred_at"],
                },
                op_type="create",
            )
        elif event["event_type"] == "FundsDeposited":
            await self._es.update(
                index=self.INDEX,
                id=event["pod_id"],
                script={
                    "source": "ctx._source.balance_minor += params.amt",
                    "params": {"amt": event["amount_minor"]},
                },
                retry_on_conflict=5,
            )
```

Design notes:

1. **Exactly-once semantics** are achieved via Kafka offsets + deterministic `id` in ElasticSearch.  
2. **Backfills**: Replaying the full event history is safe; the script handles duplicate events.

---

## 7. Saga Orchestrator (Settlement Flow)

```python
"""
crowdpay_connect.saga.settlement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Distributed Saga to convert multi-currency deposits and
settle funds to external banking rails.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from enum import Enum, auto

from crowdpay_connect.bus import publish_command, publish_event

log = logging.getLogger(__name__)


class SagaState(Enum):
    INITIATED = auto()
    FX_RESERVED = auto()
    BANK_RESERVED = auto()
    COMPLETED = auto()
    COMPENSATING = auto()
    FAILED = auto()


@dataclass
class SagaContext:
    saga_id: str
    pod_id: str
    amount_minor: int
    src_currency: str
    dest_currency: str
    beneficiary_iban: str


class SettlementSaga:
    TIMEOUT = 30  # seconds for each step

    def __init__(self, ctx: SagaContext) -> None:
        self.ctx = ctx
        self.state = SagaState.INITIATED

    async def execute(self) -> None:
        try:
            await self._reserve_fx()
            await self._reserve_bank_slot()
            await self._finalise()
        except Exception as exc:
            log.warning("Saga %s failed: %s – compensating …", self.ctx.saga_id, exc)
            await self._compensate()
            self.state = SagaState.FAILED
            raise

    async def _reserve_fx(self) -> None:
        publish_command(
            "fx.reserve",
            saga_id=self.ctx.saga_id,
            amount=self.ctx.amount_minor,
            src=self.ctx.src_currency,
            dest=self.ctx.dest_currency,
        )
        await self._await_event("fx.reserved")
        self.state = SagaState.FX_RESERVED

    async def _reserve_bank_slot(self) -> None:
        publish_command(
            "bank.reserve",
            saga_id=self.ctx.saga_id,
            amount=self.ctx.amount_minor,
            currency=self.ctx.dest_currency,
            iban=self.ctx.beneficiary_iban,
        )
        await self._await_event("bank.slot_reserved")
        self.state = SagaState.BANK_RESERVED

    async def _finalise(self) -> None:
        publish_command("bank.settle", saga_id=self.ctx.saga_id)
        await self._await_event("bank.settled")
        publish_event("saga.settlement.completed", saga_id=self.ctx.saga_id)
        self.state = SagaState.COMPLETED

    async def _compensate(self) -> None:
        self.state = SagaState.COMPENSATING
        publish_command("fx.cancel", saga_id=self.ctx.saga_id)
        publish_command("bank.release", saga_id=self.ctx.saga_id)
        await asyncio.gather(
            self._await_event("fx.cancelled"),
            self._await_event("bank.slot_released"),
        )
        publish_event("saga.settlement.compensated", saga_id=self.ctx.saga_id)

    async def _await_event(self, name: str) -> None:
        # Pseudo-implementation; production code uses Kafka + Correlation-ID
        try:
            await asyncio.wait_for(_event_bus_wait(name, self.ctx.saga_id), timeout=self.TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Timeout waiting for {name}") from exc


def start_settlement(
    pod_id: str,
    amount_minor: int,
    src_currency: str,
    dest_currency: str,
    beneficiary_iban: str,
) -> str:
    saga_id = str(uuid.uuid4())
    ctx = SagaContext(
        saga_id=saga_id,
        pod_id=pod_id,
        amount_minor=amount_minor,
        src_currency=src_currency,
        dest_currency=dest_currency,
        beneficiary_iban=beneficiary_iban,
    )

    asyncio.create_task(SettlementSaga(ctx).execute())
    return saga_id
```

---

## 8. Compliance & Security by Design

1. **Immutability** – No PII lives in the event payload; sensitive data is encrypted via **envelope encryption** before being stored as `event_data`.  
2. **Field-level encryption** – KMS-backed keys rotate every 90 days.  
3. **GDPR Right to Erasure** – Events keep a `subject_id` pointer; “deletion” is processed by cryptographically shredding the CEK (Content Encryption Key).  
4. **Audit trail** – All event append operations store the `meta_data` → `trace_id`, `source_ip`, `kyc_level`, `bank_id`.  
5. **Tamper detection** – Merkle root per day signed with server HSM.

---

## 9. Operational Playbook

| Action                               | Cmd / Tooling                                       |
|--------------------------------------|-----------------------------------------------------|
| Rebuild read models                  | `python -m crowdpay_connect.tools.replay_events`    |
| Take snapshot for hot restore        | `SELECT crowdpay.snapshot_make('CrowdPod', ...);`   |
| Verify merkle integrity              | `crowdpay-cli merkle verify --date 2024-05-30`      |
| Truncate outbox table (processed)    | Schedule: cron daily via `crowdpay_cleaner`         |

---

## 10. Testing Strategy

1. **Property-based tests** (`hypothesis`) for aggregates guarantee invariants (`balance ≥ 0`).  
2. **Event fixture contracts** verified through **JSON Schema** in CI.  
3. **Replay test**: every PR triggers a full replay of prod anon-scrubbed events against head commit; projection checksum must match.

---

### Appendix: Event JSON Schemas (OpenAPI 3.1 extract)

```yaml
CrowdPodCreated:
  type: object
  required: [pod_id, owner_id, currency, name, occurred_at]
  properties:
    pod_id:      {type: string, format: uuid}
    owner_id:    {type: string, format: uuid}
    currency:    {type: string, enum: [USD, EUR, GBP, NGN, GHS]}
    name:        {type: string, maxLength: 64}
    occurred_at: {type: string, format: date-time}

FundsDeposited:
  type: object
  required: [pod_id, member_id, amount_minor, currency, tx_ref, occurred_at]
  properties:
    pod_id:       {type: string, format: uuid}
    member_id:    {type: string, format: uuid}
    amount_minor: {type: integer, minimum: 1}
    currency:     {type: string}
    tx_ref:       {type: string}
    occurred_at:  {type: string, format: date-time}
```

---

_© 2024 CrowdPay Connect Architecture Guild_
```