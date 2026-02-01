```python
"""
crowdpay_connect.services.transaction_service.app.events.saga_coordinator
========================================================================

Implements a distributed-Saga coordinator responsible for orchestrating
multi-step payments across the CrowdPay Connect platform.

Key responsibilities
--------------------
1. Define a reusable Saga abstraction that can be persisted and resumed.
2. Execute Saga steps *atomically* while guaranteeing compensating actions
   upon failure.
3. Publish domain events to the platform-wide event bus in line with the
   Event-Sourcing architecture.
4. Provide fault-tolerance via timeouts, retries, and idempotency guards.

The implementation purposefully stays framework-agnostic so that it may be
integrated with popular async messaging layers such as Kafka, NATS, or
RabbitMQ.  Replace the `EventBus` stub with your actual infrastructure-
specific adapter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# -----------------------------------------------------------------------------
# Event bus stub (replace with real implementation)
# -----------------------------------------------------------------------------


@dataclass
class Event:
    topic: str
    payload: Dict[str, str]
    timestamp: float = field(default_factory=lambda: time.time())

    def to_json(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "payload": self.payload,
                "timestamp": self.timestamp,
            }
        )


class EventBus:
    """
    Extremely simplified async pub/sub interface used by the SagaCoordinator.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = {}

    async def publish(self, event: Event) -> None:
        subscribers = self._subscribers.get(event.topic, [])
        if not subscribers:
            logger.debug("No subscribers for topic %s", event.topic)
        for cb in subscribers:
            try:
                await cb(event)
            except Exception:  # noqa: BLE001
                logger.exception("Event handler failed for topic %s", event.topic)

    def subscribe(self, topic: str, callback: Callable[[Event], Awaitable[None]]) -> None:
        self._subscribers.setdefault(topic, []).append(callback)
        logger.debug("Subscribed %s to topic %s", callback, topic)


# -----------------------------------------------------------------------------
# Saga primitives
# -----------------------------------------------------------------------------


class SagaStatus(Enum):
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()
    COMPENSATED = auto()
    TIMED_OUT = auto()


class StepStatus(Enum):
    PENDING = auto()
    SUCCESS = auto()
    FAILED = auto()
    COMPENSATED = auto()


ActionCallable = Callable[[], Awaitable[None]]
CompensationCallable = Callable[[], Awaitable[None]]


@dataclass
class SagaStep:
    """
    Represents a single unit of work.
    """

    name: str
    action: ActionCallable
    compensation: CompensationCallable
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    async def execute(self) -> None:
        logger.debug("Executing action step: %s", self.name)
        self.started_at = datetime.utcnow()
        try:
            await self.action()
            self.status = StepStatus.SUCCESS
            logger.debug("Action step succeeded: %s", self.name)
        except Exception as exc:  # noqa: BLE001
            self.status = StepStatus.FAILED
            logger.error("Action step failed: %s - %s", self.name, exc)
            raise

        self.completed_at = datetime.utcnow()

    async def compensate(self) -> None:
        logger.debug("Executing compensation step: %s", self.name)
        try:
            await self.compensation()
            self.status = StepStatus.COMPENSATED
            logger.debug("Compensation step succeeded: %s", self.name)
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "Compensation step failed irrecoverably: %s - %s", self.name, exc
            )
            raise  # escalate ‑ we cannot guarantee consistency anymore


@dataclass
class Saga:
    saga_id: str
    steps: List[SagaStep]
    status: SagaStatus = SagaStatus.PENDING
    ttl: timedelta = timedelta(minutes=5)  # overall Saga timeout
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_expired(self) -> bool:
        return datetime.utcnow() - self.created_at >= self.ttl

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.saga_id,
            "status": self.status.name,
            "steps": [
                {
                    "name": step.name,
                    "status": step.status.name,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat()
                    if step.completed_at
                    else None,
                }
                for step in self.steps
            ],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class SagaTimeoutError(Exception):
    """Raised when the Saga exceeds its allowed completion window."""


# -----------------------------------------------------------------------------
# In-memory repository for demonstration purposes
# -----------------------------------------------------------------------------


class SagaRepository:
    """
    In production this would be backed by PostgreSQL, Redis, or a document store.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Saga] = {}

    async def save(self, saga: Saga) -> None:
        saga.updated_at = datetime.utcnow()
        self._store[saga.saga_id] = saga
        logger.debug("Saga %s persisted with status %s", saga.saga_id, saga.status)

    async def get(self, saga_id: str) -> Optional[Saga]:
        return self._store.get(saga_id)

    async def delete(self, saga_id: str) -> None:
        self._store.pop(saga_id, None)


# -----------------------------------------------------------------------------
# Coordinator implementation
# -----------------------------------------------------------------------------


class SagaCoordinator:
    """
    Orchestrates multi-step payment Sagas for CrowdPay Connect.

    Example
    -------
    >>> bus = EventBus()
    >>> repo = SagaRepository()
    >>> coordinator = SagaCoordinator(bus, repo)
    >>> saga = coordinator.create_saga(
    ...     steps=[
    ...         SagaStep("debit", debit_wallet, credit_wallet),
    ...         SagaStep("credit", credit_recipient, debit_recipient),
    ...     ]
    ... )
    >>> await coordinator.execute(saga.saga_id)
    """

    BUS_TOPIC_SAGA_UPDATED = "saga.updated"

    def __init__(self, bus: EventBus, repository: SagaRepository) -> None:
        self.bus = bus
        self.repository = repository

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def create_saga(self, steps: Iterable[SagaStep], ttl_minutes: int = 5) -> Saga:
        saga_id = str(uuid.uuid4())
        saga = Saga(
            saga_id=saga_id,
            steps=list(steps),
            ttl=timedelta(minutes=ttl_minutes),
        )
        # Persist synchronously to guarantee idempotent starts
        asyncio.get_event_loop().run_until_complete(self.repository.save(saga))
        logger.info("Created new Saga: %s", saga_id)
        return saga

    async def execute(self, saga_id: str) -> Saga:
        saga = await self._load_saga_or_raise(saga_id)
        if saga.status not in {SagaStatus.PENDING, SagaStatus.IN_PROGRESS}:
            logger.warning("Saga %s already completed with status %s", saga_id, saga.status)
            return saga

        saga.status = SagaStatus.IN_PROGRESS
        await self.repository.save(saga)
        await self._publish_update(saga)

        try:
            for step in saga.steps:
                if saga.is_expired():
                    raise SagaTimeoutError(f"Saga {saga.saga_id} timed-out")

                if step.status is StepStatus.SUCCESS:
                    # Allows Saga resumption after crash
                    logger.debug("Skipping already successful step: %s", step.name)
                    continue

                await step.execute()
                await self.repository.save(saga)
                await self._publish_update(saga)

            saga.status = SagaStatus.COMPLETED
            await self.repository.save(saga)
            await self._publish_update(saga)
            logger.info("Saga %s completed successfully", saga.saga_id)
            return saga

        except Exception as exc:  # noqa: BLE001
            logger.error("Saga %s failed due to %s. Triggering compensation.", saga.saga_id, exc)
            saga.status = SagaStatus.FAILED
            await self.repository.save(saga)
            await self._publish_update(saga)

            # Attempt compensations in **reverse** order
            await self._run_compensations(saga)
            return saga

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    async def _run_compensations(self, saga: Saga) -> None:
        for step in reversed(saga.steps):
            if step.status is StepStatus.SUCCESS:
                try:
                    await step.compensate()
                except Exception:  # noqa: BLE001
                    # compensation failure is fatal — escalate & stop loop
                    saga.status = SagaStatus.COMPENSATED
                    await self.repository.save(saga)
                    await self._publish_update(saga)
                    raise
        saga.status = SagaStatus.COMPENSATED
        await self.repository.save(saga)
        await self._publish_update(saga)
        logger.info("Saga %s compensated successfully", saga.saga_id)

    async def _publish_update(self, saga: Saga) -> None:
        event = Event(
            topic=self.BUS_TOPIC_SAGA_UPDATED,
            payload=saga.to_dict(),
        )
        await self.bus.publish(event)

    async def _load_saga_or_raise(self, saga_id: str) -> Saga:
        saga = await self.repository.get(saga_id)
        if not saga:
            raise ValueError(f"Saga {saga_id} not found")
        return saga


# -----------------------------------------------------------------------------
# Example step actions (place-holders)
# -----------------------------------------------------------------------------
async def debit_wallet() -> None:
    """
    Placeholder for wallet debit service call.
    """
    await asyncio.sleep(0.1)  # simulate IO delay
    logger.debug("Debited wallet successfully")


async def credit_wallet() -> None:
    """
    Compensation for debit_wallet().
    """
    await asyncio.sleep(0.1)
    logger.debug("Credited wallet rollback successfully")


async def credit_recipient() -> None:
    await asyncio.sleep(0.1)
    logger.debug("Credited recipient successfully")


async def debit_recipient() -> None:
    await asyncio.sleep(0.1)
    logger.debug("Debited recipient compensation successfully")


# -----------------------------------------------------------------------------
# Module test (only run when executed directly)
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    async def _demo() -> None:
        # Configure root logger for demo purposes
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

        bus = EventBus()
        repo = SagaRepository()
        coordinator = SagaCoordinator(bus, repo)

        # Subscribe to Saga updates
        bus.subscribe(
            SagaCoordinator.BUS_TOPIC_SAGA_UPDATED,
            lambda e: logger.info("EVENT: %s", e.to_json()),
        )

        # Build a saga with two steps
        saga = coordinator.create_saga(
            steps=[
                SagaStep(
                    name="debit_payer",
                    action=debit_wallet,
                    compensation=credit_wallet,
                ),
                SagaStep(
                    name="credit_receiver",
                    action=credit_recipient,
                    compensation=debit_recipient,
                ),
            ]
        )

        # Execute saga
        await coordinator.execute(saga.saga_id)

    asyncio.run(_demo())
```