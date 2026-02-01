```python
"""
crowdpay_connect/services/transaction_service/app/repositories/saga_repository.py

Repository abstraction for reading/writing Saga state to the database.
Implements the Saga Pattern’s persistence concern for the Transaction Service.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import (
    Column,
    DateTime,
    Enum as PgEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

__all__ = ["SagaRepository", "SagaError", "SagaNotFoundError"]

logger = logging.getLogger(__name__)
Base = declarative_base()

###############################################################################
# ORM models
###############################################################################


class SagaStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


class SagaStepStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SagaORM(Base):
    """
    Top-level Saga instance.
    """

    __tablename__ = "sagas"
    __table_args__ = (UniqueConstraint("reference_id", "saga_type", name="uq_saga_reference_type"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    saga_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[SagaStatus] = mapped_column(
        PgEnum(SagaStatus, name="saga_status"), default=SagaStatus.PENDING, nullable=False
    )
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.utcnow(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.utcnow(),
        onupdate=lambda: dt.datetime.utcnow(),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    steps: Mapped[List["SagaStepORM"]] = relationship(
        "SagaStepORM",
        back_populates="saga",
        cascade="all, delete-orphan",
        order_by="SagaStepORM.order",
        lazy="selectin",
    )


class SagaStepORM(Base):
    """
    Individual step in a Saga instance.
    """

    __tablename__ = "saga_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    saga_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("sagas.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SagaStepStatus] = mapped_column(
        PgEnum(SagaStepStatus, name="saga_step_status"),
        default=SagaStepStatus.PENDING,
        nullable=False,
    )
    output: Mapped[Dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.utcnow(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.utcnow(),
        onupdate=lambda: dt.datetime.utcnow(),
        nullable=False,
    )
    saga: Mapped["SagaORM"] = relationship("SagaORM", back_populates="steps")


###############################################################################
# Exceptions
###############################################################################


class SagaError(RuntimeError):
    """Base class for saga repository exceptions."""


class SagaNotFoundError(SagaError):
    """Saga instance could not be found."""


class SagaVersionConflictError(SagaError):
    """
    Saga concurrent modification error—optimistic locking version mismatch.
    """


###############################################################################
# Repository
###############################################################################


class SagaRepository:
    """
    Repository providing CRUD operations for Saga instances.
    Intended to be injected as a dependency from FastAPI/DI container.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    # --------------------------------------------------------------------- #
    # Saga operations
    # --------------------------------------------------------------------- #

    async def create_saga(
        self,
        *,
        reference_id: str,
        saga_type: str,
        steps: Sequence[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SagaORM:
        """
        Create a new Saga instance and its initial steps.

        :param reference_id: External reference for idempotency (e.g., tx id).
        :param saga_type: Name of the Saga orchestrator (e.g., SETTLEMENT_SAGA).
        :param steps: Ordered collection of step names.
        :param metadata: Optional arbitrary JSON metadata.
        """
        logger.debug("Creating saga (ref=%s, type=%s)", reference_id, saga_type)
        saga = SagaORM(reference_id=reference_id, saga_type=saga_type, metadata=metadata)
        saga.steps = [
            SagaStepORM(name=name, order=idx, status=SagaStepStatus.PENDING) for idx, name in enumerate(steps)
        ]
        self._session.add(saga)

        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            logger.error("Failed to create saga %s - %s", reference_id, exc)
            raise SagaError("Saga creation failed") from exc

        logger.info("Saga created [%s]", saga.id)
        return saga

    async def get_saga(self, saga_id: uuid.UUID, *, for_update: bool = False) -> SagaORM:
        """
        Fetch Saga by ID.

        :param saga_id: Saga UUID.
        :param for_update: Whether to place a SELECT ... FOR UPDATE lock.
        :raises SagaNotFoundError: If saga is missing.
        """
        stmt = select(SagaORM).where(SagaORM.id == saga_id)
        if for_update:
            stmt = stmt.with_for_update()

        logger.debug("Fetching saga %s (lock=%s)", saga_id, for_update)
        result = await self._session.execute(stmt)
        saga = result.scalar_one_or_none()

        if saga is None:
            raise SagaNotFoundError(f"Saga {saga_id} not found")

        return saga

    async def update_saga_status(
        self,
        saga_id: uuid.UUID,
        *,
        status: SagaStatus,
        expected_version: Optional[int] = None,
    ) -> SagaORM:
        """
        Atomically update Saga status (optimistic locking via version column).

        :param saga_id: Saga UUID.
        :param status: New status.
        :param expected_version: If supplied, will ensure version match.
        :raises SagaVersionConflictError: If optimistic lock fails.
        """
        logger.debug(
            "Updating saga %s status to %s (expected_version=%s)",
            saga_id,
            status,
            expected_version,
        )

        stmt = (
            update(SagaORM)
            .where(SagaORM.id == saga_id)
            .values(
                status=status,
                updated_at=dt.datetime.utcnow(),
                version=SagaORM.version + 1,
            )
            .returning(SagaORM)
        )

        if expected_version is not None:
            stmt = stmt.where(SagaORM.version == expected_version)

        result = await self._session.execute(stmt)
        saga: SagaORM | None = result.scalar_one_or_none()

        if saga is None:
            await self._session.rollback()
            raise SagaVersionConflictError(
                f"Optimistic lock failed for saga {saga_id} "
                f"(expected_version={expected_version})"
            )

        await self._session.commit()
        logger.info("Saga %s status updated to %s", saga_id, status)
        return saga

    # --------------------------------------------------------------------- #
    # Step operations
    # --------------------------------------------------------------------- #

    async def mark_step_completed(
        self,
        saga_id: uuid.UUID,
        step_name: str,
        *,
        output: Optional[Dict[str, Any]] = None,
    ) -> SagaStepORM:
        """
        Update the step's status to COMPLETED.
        """
        logger.debug("Marking step '%s' completed for saga %s", step_name, saga_id)
        stmt = (
            update(SagaStepORM)
            .where(
                SagaStepORM.saga_id == saga_id,
                SagaStepORM.name == step_name,
                SagaStepORM.status == SagaStepStatus.PENDING,
            )
            .values(
                status=SagaStepStatus.COMPLETED,
                output=output,
                updated_at=dt.datetime.utcnow(),
            )
            .returning(SagaStepORM)
        )
        result = await self._session.execute(stmt)
        step: SagaStepORM | None = result.scalar_one_or_none()

        if step is None:
            await self._session.rollback()
            logger.warning("Step '%s' not found or already processed (saga=%s)", step_name, saga_id)
            raise SagaNotFoundError(f"Step {step_name} not found for saga {saga_id}")

        await self._session.commit()
        logger.info("Step '%s' completed (saga=%s)", step_name, saga_id)
        return step

    async def mark_step_failed(
        self,
        saga_id: uuid.UUID,
        step_name: str,
        *,
        reason: str,
        output: Optional[Dict[str, Any]] = None,
    ) -> SagaStepORM:
        """
        Mark the given step as FAILED.
        """
        logger.debug("Marking step '%s' failed for saga %s: %s", step_name, saga_id, reason)
        stmt = (
            update(SagaStepORM)
            .where(
                SagaStepORM.saga_id == saga_id,
                SagaStepORM.name == step_name,
                SagaStepORM.status.in_(
                    [SagaStepStatus.PENDING, SagaStepStatus.COMPLETED]
                ),  # allow update unless already failed
            )
            .values(
                status=SagaStepStatus.FAILED,
                output={**(output or {}), "reason": reason},
                updated_at=dt.datetime.utcnow(),
            )
            .returning(SagaStepORM)
        )
        result = await self._session.execute(stmt)
        step: SagaStepORM | None = result.scalar_one_or_none()

        if step is None:
            await self._session.rollback()
            raise SagaNotFoundError(f"Step {step_name} not found for saga {saga_id}")

        await self._session.commit()
        logger.error("Step '%s' FAILED (saga=%s): %s", step_name, saga_id, reason)
        return step

    async def list_pending_steps(self, saga_id: uuid.UUID) -> List[SagaStepORM]:
        """
        Return steps that are not completed/compensated/failed yet.
        """
        stmt = select(SagaStepORM).where(
            SagaStepORM.saga_id == saga_id,
            SagaStepORM.status == SagaStepStatus.PENDING,
        ).order_by(SagaStepORM.order)

        result = await self._session.execute(stmt)
        steps = result.scalars().all()
        return list(steps)

    # --------------------------------------------------------------------- #
    # Convenience helpers
    # --------------------------------------------------------------------- #

    async def compensate_saga(self, saga_id: uuid.UUID, *, reason: str) -> None:
        """
        Mark all COMPLETED steps in reverse order for compensation, then set
        saga status to COMPENSATED.

        This operation is executed transactionally.
        """
        logger.warning("Compensating saga %s due to: %s", saga_id, reason)
        saga = await self.get_saga(saga_id, for_update=True)

        # 1. Mark steps
        for step in reversed(saga.steps):
            if step.status == SagaStepStatus.COMPLETED:
                logger.debug("Compensating step '%s' (saga=%s)", step.name, saga_id)
                step.status = SagaStepStatus.COMPENSATED
                step.output = {**(step.output or {}), "compensation_reason": reason}

        saga.status = SagaStatus.COMPENSATED

        await self._session.commit()
        logger.info("Saga %s compensated", saga_id)

    async def delete_old_sagas(self, *, older_than_days: int = 30, limit: int = 500) -> int:
        """
        House-keeping utility. Remove sagas that ended > X days ago.

        Returns number of rows deleted.
        """
        dead_line = dt.datetime.utcnow() - dt.timedelta(days=older_than_days)
        logger.debug("Pruning sagas completed before %s", dead_line.isoformat())

        stmt_select = select(SagaORM.id).where(
            SagaORM.updated_at < dead_line,
            SagaORM.status.in_([SagaStatus.COMPLETED, SagaStatus.COMPENSATED, SagaStatus.FAILED]),
        ).limit(limit)

        result = await self._session.execute(stmt_select)
        ids = [row.id for row in result.fetchall()]

        if not ids:
            return 0

        logger.info("Deleting %d old sagas", len(ids))
        await self._session.execute(
            update(SagaStepORM).where(SagaStepORM.saga_id.in_(ids)).execution_options(synchronize_session=False)
        )
        await self._session.execute(
            update(SagaORM).where(SagaORM.id.in_(ids)).execution_options(synchronize_session=False)
        )
        await self._session.commit()
        return len(ids)

    # --------------------------------------------------------------------- #
    # Utilities
    # --------------------------------------------------------------------- #

    async def refresh(self, saga: SagaORM) -> None:
        """
        Ensure the given Saga ORM instance is fresh from DB.
        """
        await self._session.refresh(saga)

    async def close(self) -> None:
        """
        Close underlying session gracefully.
        """
        if self._session and not self._session.closed:
            await self._session.close()

###############################################################################
# Async context manager sugar
###############################################################################


class _SagaRepositoryContext:
    """
    Convenience async context manager for short-lived repository use:

    async with saga_repository(session_factory) as repo:
        ...
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._repo: Optional[SagaRepository] = None

    async def __aenter__(self) -> SagaRepository:
        session: AsyncSession = await self._session_factory()
        self._repo = SagaRepository(session)
        return self._repo

    async def __aexit__(self, exc_type, exc, tb):
        if self._repo:
            if exc:
                await self._repo._session.rollback()
            await self._repo.close()


def saga_repository(session_factory) -> _SagaRepositoryContext:
    """
    Factory returning an async context manager.

    Usage:
        async with saga_repository(session_factory) as repo:
            await repo.create_saga(...)
    """
    return _SagaRepositoryContext(session_factory)
```