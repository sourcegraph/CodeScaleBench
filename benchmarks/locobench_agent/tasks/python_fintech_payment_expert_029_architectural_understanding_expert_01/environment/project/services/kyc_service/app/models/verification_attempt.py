```python
"""
crowdpay_connect.services.kyc_service.app.models.verification_attempt

Model and domain-logic for KYC verification attempts.  Each attempt is
instantiated whenever a user starts a KYC flow with a third-party provider.
The model is responsible for:

    • Persisting verification-attempt metadata
    • Controlling valid state-transitions (FSM-like)
    • Collecting domain-events for the event-sourcing pipeline
    • Providing light-weight serialization helpers

This file purposefully keeps the model self-contained so that higher-level
service-layers (command handlers / query handlers) can remain ignorant of the
underlying ORM details while still profiting from rich domain behavior.
"""

from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Boolean,
    Column,
    Enum,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import validates

# NOTE: In production this `Base` should instead be imported from the shared
# database module so that metadata is aggregated correctly.
Base = declarative_base()


# --------------------------------------------------------------------------- #
#                               Domain Events                                 #
# --------------------------------------------------------------------------- #
class _DomainEvent:
    """
    Base-class for domain events.  In production these events would be passed to
    a dedicated event-bus (Kafka, RabbitMQ, etc.) by an outbox/publisher.
    """

    __slots__ = ("occurred_at",)

    def __init__(self) -> None:
        self.occurred_at: datetime = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable representation."""
        return {
            "type": self.__class__.__name__,
            "occurred_at": self.occurred_at.isoformat(),
            **{
                k: v for k, v in self.__dict__.items() if k != "occurred_at"
            },
        }


class VerificationAttemptCreated(_DomainEvent):
    def __init__(self, attempt_id: uuid.UUID, user_id: uuid.UUID):
        super().__init__()
        self.attempt_id = str(attempt_id)
        self.user_id = str(user_id)


class VerificationAttemptSucceeded(_DomainEvent):
    def __init__(
        self,
        attempt_id: uuid.UUID,
        user_id: uuid.UUID,
        risk_score: float,
    ):
        super().__init__()
        self.attempt_id = str(attempt_id)
        self.user_id = str(user_id)
        self.risk_score = risk_score


class VerificationAttemptFailed(_DomainEvent):
    def __init__(
        self,
        attempt_id: uuid.UUID,
        user_id: uuid.UUID,
        failure_reason: str,
    ):
        super().__init__()
        self.attempt_id = str(attempt_id)
        self.user_id = str(user_id)
        self.failure_reason = failure_reason


class VerificationAttemptExpired(_DomainEvent):
    def __init__(self, attempt_id: uuid.UUID, user_id: uuid.UUID):
        super().__init__()
        self.attempt_id = str(attempt_id)
        self.user_id = str(user_id)


# --------------------------------------------------------------------------- #
#                             Enumeration Helpers                             #
# --------------------------------------------------------------------------- #
class VerificationStatus(str, enum.Enum):
    """Finite-state for KYC verification attempts."""

    PENDING = "PENDING"  # No provider callback yet
    SUCCESS = "SUCCESS"  # Completed & verified
    FAILED = "FAILED"  # Completed but rejected
    EXPIRED = "EXPIRED"  # Time-boxed attempt timed out
    FLAGGED = "FLAGGED"  # Manual review required


# --------------------------------------------------------------------------- #
#                                 ORM Model                                   #
# --------------------------------------------------------------------------- #
class VerificationAttempt(Base):
    """
    ORM-model representing a single KYC verification attempt.

    A user may perform multiple attempts—e.g. when the provider requires
    additional clarification—but for idempotency the tuple (user_id,
    provider, provider_reference) is forced unique.
    """

    __tablename__ = "kyc_verification_attempts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "provider_reference",
            name="uq_user_provider_reference",
        ),
    )

    # --------------------------------------------------------------------- #
    # Column Definitions
    # --------------------------------------------------------------------- #
    id: uuid.UUID = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: uuid.UUID = Column(String(36), nullable=False, index=True)
    provider: str = Column(String(64), nullable=False)  # e.g. "veriff", "onfido"
    provider_reference: str = Column(
        String(128),
        nullable=False,
        comment="Reference returned by provider that uniquely identifies the KYC session.",
    )
    status: VerificationStatus = Column(
        Enum(VerificationStatus, name="kyc_verification_status"),
        nullable=False,
        default=VerificationStatus.PENDING,
    )
    risk_score: Optional[float] = Column(
        Float,
        nullable=True,
        comment="0.0 => low risk, 1.0 => high risk",
    )
    failure_reason: Optional[str] = Column(Text, nullable=True)
    metadata: Dict[str, Any] = Column(
        JSON,
        nullable=False,
        default=dict,
        comment="Raw payload echoed by provider.",
    )

    created_at: datetime = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: datetime = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expires_at: datetime = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        comment="Provider may define a TTL; default to 15 minutes.",
    )

    # Optimistic locking
    version: int = Column(
        Integer,
        nullable=False,
        default=1,
    )

    # Non-persistent attribute to collect domain events during the TX
    _pending_events: List[_DomainEvent] = []

    # --------------------------------------------------------------------- #
    # Lifecycle / Validation
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        user_id: uuid.UUID,
        provider: str,
        provider_reference: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        # SQLAlchemy bypasses __init__ when hydrating from DB, so guard.
        if not hasattr(self, "_sa_instance_state"):
            # This is a brand new instance
            self.id = str(uuid.uuid4())
            self.user_id = str(user_id)
            self.provider = provider.lower()
            self.provider_reference = provider_reference
            self.status = VerificationStatus.PENDING
            self.metadata = metadata or {}
            self.expires_at = datetime.utcnow() + ttl
            self._pending_events = [
                VerificationAttemptCreated(self.id, self.user_id)
            ]

    # --------------------------------------------------------------------- #
    # Domain Methods
    # --------------------------------------------------------------------- #
    def mark_success(
        self,
        risk_score: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark the attempt as succeeded.  Raises ValueError if transition is
        illegal.
        """
        if self.status not in (VerificationStatus.PENDING, VerificationStatus.FLAGGED):
            raise ValueError(
                f"Cannot transition from {self.status} to SUCCESS for attempt={self.id}"
            )

        self.status = VerificationStatus.SUCCESS
        self.risk_score = float(risk_score)
        if metadata:
            self.metadata.update(metadata)
        self._pending_events.append(
            VerificationAttemptSucceeded(
                attempt_id=self.id,
                user_id=self.user_id,
                risk_score=self.risk_score,
            )
        )

    def mark_failed(
        self,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark attempt as failed.  Raises ValueError on illegal transition.
        """
        if self.status not in (VerificationStatus.PENDING, VerificationStatus.FLAGGED):
            raise ValueError(
                f"Cannot transition from {self.status} to FAILED for attempt={self.id}"
            )

        self.status = VerificationStatus.FAILED
        self.failure_reason = reason
        if metadata:
            self.metadata.update(metadata)
        self._pending_events.append(
            VerificationAttemptFailed(
                attempt_id=self.id,
                user_id=self.user_id,
                failure_reason=reason,
            )
        )

    def expire(self) -> None:
        """Expire an attempt when TTL is hit."""
        if self.status != VerificationStatus.PENDING:
            return  # Only PENDING can expire silently.

        self.status = VerificationStatus.EXPIRED
        self._pending_events.append(
            VerificationAttemptExpired(
                attempt_id=self.id,
                user_id=self.user_id,
            )
        )

    # --------------------------------------------------------------------- #
    # Query helpers
    # --------------------------------------------------------------------- #
    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def to_dict(self, include_metadata: bool = False) -> Dict[str, Any]:
        """Return a serialisable dict; optionally include raw provider metadata."""
        payload = {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "provider_reference": self.provider_reference,
            "status": self.status.value,
            "risk_score": self.risk_score,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat(),
            "version": self.version,
        }
        if include_metadata:
            payload["metadata"] = self.metadata
        return payload

    def pop_pending_events(self) -> List[_DomainEvent]:
        """
        Return & clear domain events accumulated during the current
        transaction/unit-of-work.  The caller is responsible for publishing the
        events atomically with DB commit to avoid dual-write hazards.
        """
        events, self._pending_events = self._pending_events, []
        return events

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #
    @validates("risk_score")
    def _validate_risk_score(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is not None and not (0.0 <= value <= 1.0):
            raise ValueError("risk_score must be between 0.0 and 1.0")
        return value

    # --------------------------------------------------------------------- #
    # Representation / Debugging
    # --------------------------------------------------------------------- #
    def __repr__(self) -> str:  # pragma: no cover
        attrs = " ".join(
            f"{k}={getattr(self, k)!r}"
            for k in ("id", "user_id", "status", "provider")
        )
        return f"<VerificationAttempt {attrs}>"


# --------------------------------------------------------------------------- #
#               SQLAlchemy event listener for optimistic locking              #
# --------------------------------------------------------------------------- #
@event.listens_for(VerificationAttempt, "before_update", propagate=True)
def _increment_version(mapper, connection, target: VerificationAttempt, **kw):
    """
    Auto-increment `version` column to facilitate optimistic locking checks
    for concurrent writers.
    """
    target.version += 1


# --------------------------------------------------------------------------- #
#                      JSON-encoding helper for API responses                 #
# --------------------------------------------------------------------------- #
class VerificationAttemptJSONEncoder(json.JSONEncoder):
    """
    Drop-in encoder so that `json.dumps(obj, cls=VerificationAttemptJSONEncoder)`
    can handle VerificationAttempt & _DomainEvent instances transparently.
    """

    def default(self, obj: Any):  # type: ignore[override]
        if isinstance(obj, VerificationAttempt):
            return obj.to_dict(include_metadata=False)
        if isinstance(obj, _DomainEvent):
            return obj.to_dict()
        return super().default(obj)
```