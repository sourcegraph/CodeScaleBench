```python
"""
crowdpay_connect/services/transaction_service/app/models/saga_state.py

Model definition and supporting helpers for persisting and manipulating the
state of long-running, distributed Saga transactions executed by the
Transaction Service.  The Saga pattern ensures that each multi-step payment
workflow either completes atomically across micro-services or gets rolled
back via compensating actions.

The SagaState model keeps track of where the workflow currently is, which
step (child-command) is being executed, and whether the overall process has
completed, failed, or is compensating.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum as SqlEnum,
    Integer,
    LargeBinary,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.types import TypeDecorator

# In a full project this Base would be imported from a common db module.
Base = declarative_base()
logger = logging.getLogger(__name__)


@unique
class SagaPhase(str, Enum):
    """
    High-level lifecycle phases for a distributed Saga.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            SagaPhase.COMPLETED,
            SagaPhase.ROLLED_BACK,
            SagaPhase.FAILED,
        }


class _JSONEncodedDict(TypeDecorator):
    """
    Stores Python dicts natively in Postgres JSONB or as TEXT fallback for
    other engines, and transparently (de)serialises them.
    """

    impl = JSON

    cache_ok = True  # SQLAlchemy 1.4+ optimisation hint

    def process_bind_param(self, value: Dict[str, Any] | None, dialect):  # noqa: N802
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("SagaState.data must be a dict.")
        return value

    def process_result_value(  # noqa: N802
        self,
        value: Dict[str, Any] | None,
        dialect,
    ):
        return value or {}


class OptimisticLockError(RuntimeError):
    """Raised when an update is attempted with a stale version number."""

    pass


class SagaState(Base):
    """
    SQLAlchemy model representing the persisted state of a Saga instance.
    """

    __tablename__ = "saga_states"
    __table_args__ = {"schema": "transaction_service"}  # optional schema

    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    # Human-friendly identifier, e.g., "crowdpod_settlement"
    saga_name: str = Column(String(255), nullable=False, index=True)
    # Correlates this saga across micro-services
    correlation_id: uuid.UUID = Column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
    )

    phase: SagaPhase = Column(
        SqlEnum(SagaPhase, name="saga_phase"),
        nullable=False,
        default=SagaPhase.NOT_STARTED,
    )

    current_step: int = Column(Integer, nullable=False, default=0)
    total_steps: int = Column(Integer, nullable=False)
    # Arbitrary contextual data shared across steps
    data: Dict[str, Any] = Column(_JSONEncodedDict, default=dict, nullable=False)

    # Captures unrecoverable error messages (if any)
    error_message: Optional[str] = Column(Text, nullable=True)

    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        index=True,
    )
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
        onupdate=lambda: datetime.now(tz=timezone.utc),
    )

    # Optimistic-locking version column
    version: int = Column(Integer, nullable=False, default=1)

    # --------------------------------------------------------------------- #
    # Factory helpers
    # --------------------------------------------------------------------- #

    @classmethod
    def bootstrap(
        cls,
        *,
        saga_name: str,
        correlation_id: uuid.UUID | None = None,
        total_steps: int,
        initial_data: Dict[str, Any] | None = None,
    ) -> "SagaState":
        """
        Instantiate a new saga record in NOT_STARTED phase.
        """
        correlation_id = correlation_id or uuid.uuid4()
        logger.debug(
            "Bootstrapping new SagaState '%s' (correlation_id=%s)",
            saga_name,
            correlation_id,
        )
        return cls(
            saga_name=saga_name,
            correlation_id=correlation_id,
            total_steps=total_steps,
            data=initial_data or {},
        )

    # --------------------------------------------------------------------- #
    # Business-logic manipulation helpers
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """
        Transition the saga into IN_PROGRESS, if possible.
        """
        self._ensure_phase(expected=SagaPhase.NOT_STARTED)
        self.phase = SagaPhase.IN_PROGRESS
        self.current_step = 1
        logger.info("Saga '%s' started (step %s/%s)", self.id, self.current_step, self.total_steps)

    def advance_step(self, data_patch: Dict[str, Any] | None = None) -> None:
        """
        Marks the current step as completed and advances to the next one.
        Mutates optional internal saga data using the provided patch.
        """
        self._ensure_phase(expected=SagaPhase.IN_PROGRESS)
        if self.current_step >= self.total_steps:
            raise ValueError(
                f"Saga '{self.id}' is already on the last step ({self.current_step}).",
            )
        self.current_step += 1
        logger.debug("Saga '%s' advanced to step %s", self.id, self.current_step)
        if data_patch:
            logger.debug("Patching Saga data with %s", data_patch)
            self.data.update(data_patch)

        if self.current_step == self.total_steps:
            self.complete()

    def complete(self) -> None:
        """
        Finish the saga successfully.
        """
        self._ensure_phase(expected=SagaPhase.IN_PROGRESS)
        self.phase = SagaPhase.COMPLETED
        logger.info("Saga '%s' completed successfully.", self.id)

    # ------------------------------------------------------------------ #
    # Failure handling
    # ------------------------------------------------------------------ #

    def fail(self, reason: str, compensate: bool = False) -> None:
        """
        Registers a failure.  If `compensate=True` the saga enters COMPENSATING
        and will later be rolled back; otherwise it's FAILED (terminal).
        """
        if self.phase.is_terminal:
            logger.warning(
                "Attempted to fail saga '%s' but it is already terminal (%s)",
                self.id,
                self.phase,
            )
            return

        self.error_message = reason
        self.phase = SagaPhase.COMPENSATING if compensate else SagaPhase.FAILED
        logger.error(
            "Saga '%s' transitioned to %s due to: %s",
            self.id,
            self.phase.value,
            reason,
        )

    def rollback(self) -> None:
        """
        Mark the saga as fully rolled back after successful compensation tasks.
        """
        self._ensure_phase(expected=SagaPhase.COMPENSATING)
        self.phase = SagaPhase.ROLLED_BACK
        logger.info("Saga '%s' has been rolled back.", self.id)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ensure_phase(self, *, expected: SagaPhase) -> None:
        """
        Raises a ValueError if the saga isn't currently in the expected phase.
        """
        if self.phase != expected:
            raise ValueError(
                f"Saga '{self.id}' must be in phase {expected}, "
                f"but is {self.phase}.",
            )

    # ------------------------------------------------------------------ #
    # Optimistic locking / versioning
    # ------------------------------------------------------------------ #

    def increment_version(self) -> None:
        """
        Increments the version number prior to flushing to the DB, enabling
        optimistic concurrency control.
        """
        logger.debug(
            "Incrementing version of Saga '%s' from %s to %s",
            self.id,
            self.version,
            self.version + 1,
        )
        self.version += 1


# --------------------------------------------------------------------- #
# SQLAlchemy event listeners
# --------------------------------------------------------------------- #

@event.listens_for(SagaState, "before_update", propagate=True)
def _receive_before_update(mapper, connection, target: SagaState):  # noqa: D401
    """
    SQLAlchemy event hook that fires before an UPDATE statement.  It validates
    the version column to implement application-level optimistic locking and
    bumps the version number afterwards.
    """
    # Retrieve current version persisted in the database
    table = SagaState.__table__
    current_version: int | None = connection.execute(
        table.select()
        .with_only_columns(table.c.version)
        .where(table.c.id == target.id)
    ).scalar()

    if current_version is None:
        raise StaleDataError(
            f"Saga '{target.id}' disappeared from the database whilst updating.",
        )

    if current_version != target.version:
        raise OptimisticLockError(
            f"Saga '{target.id}' has been modified concurrently "
            f"(db_version={current_version}, entity_version={target.version}).",
        )

    # All good – increment the in-memory version so it gets stored by UPDATE
    target.increment_version()
```