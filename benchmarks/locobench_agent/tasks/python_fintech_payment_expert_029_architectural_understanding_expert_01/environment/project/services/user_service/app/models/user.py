```python
"""
crowdpay_connect.services.user_service.app.models.user
======================================================

SQLAlchemy data-model and domain helpers for the User aggregate.

A User represents a human (or legal entity) that interacts with the CrowdPay
ecosystem.  In addition to the usual authentication attributes, a user owns
security-critical state such as:

    • KYC / KYB verification workflow
    • Risk-assessment scores
    • Social reputation & compliance badges
    • Multi-currency wallet preferences

The model purposefully stays free from transport/presentation concerns; that
responsibility is handled by DTOs (Pydantic models) in the `schemas` package.
"""

from __future__ import annotations

import enum
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple  # noqa: WPS235

import sqlalchemy as sa
from passlib.context import CryptContext
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (  # noqa: WPS235
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

# --------------------------------------------------------------------------- #
#  Configuration constants
# --------------------------------------------------------------------------- #

_PWD_CONTEXT = CryptContext(
    # CrowdPay enforces Argon2id company-wide, fallbacks are disabled.
    schemes=["argon2"],
    deprecated="auto",
    argon2__rounds=4,
    argon2__memory_cost=102400,
    argon2__parallelism=8,
)

# --------------------------------------------------------------------------- #
#  SQLAlchemy helpers
# --------------------------------------------------------------------------- #


class _Base(DeclarativeBase):  # pragma: no cover – base class
    """Project-level SQLAlchemy declarative base."""

    type_annotation_map = {dict[str, Any]: JSONB}


class TimestampMixin:
    """
    Adds automatic ``created_at`` / ``updated_at`` timestamp columns
    in UTC with microsecond precision.
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Implements soft-delete semantics through a nullable ``deleted_at`` column.
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
#  Domain events infrastructure (very light Outbox implementation)
# --------------------------------------------------------------------------- #


class DomainEvent:  # pragma: no cover – simplistic sketch
    """Base-class for domain events published to the outbox."""

    def __init__(self, name: str, payload: Dict[str, Any]) -> None:
        self.event_id: str = str(uuid.uuid4())
        self.occurred_on: datetime = datetime.now(timezone.utc)
        self.name = name
        self.payload = payload

    # The JSON representation is what will actually be inserted into the outbox
    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "occurred_on": self.occurred_on.isoformat(),
                "name": self.name,
                "payload": self.payload,
            },
        )


class DomainEventMixin:
    """
    Collects raised events so that the Outbox pattern can flush them in bulk.
    """

    _pending_events: List[DomainEvent]

    @property
    def pending_events(self) -> Tuple[DomainEvent, ...]:
        """Return a read-only view of pending events."""
        return tuple(self._pending_events)

    def _init_event_buffer(self) -> None:
        # SQLAlchemy may bypass __init__ when unpickling rows, use attribute set
        if "_pending_events" not in self.__dict__:
            self._pending_events = []

    def _raise_event(self, event: DomainEvent) -> None:
        self._init_event_buffer()
        self._pending_events.append(event)

    def _clear_events(self) -> None:
        self._pending_events.clear()


# --------------------------------------------------------------------------- #
#  Enumerations
# --------------------------------------------------------------------------- #


class KYCTier(enum.StrEnum):
    """KYC verification level."""

    NONE = "none"  # Unverified
    BASIC = "basic"  # Phone/email verified
    PLUS = "plus"  # Gov. ID & selfie
    PRO = "pro"  # Enhanced due-diligence


class RiskBand(enum.IntEnum):
    """Simplified risk bands derived from machine-learning scoring."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# --------------------------------------------------------------------------- #
#  Actual User model
# --------------------------------------------------------------------------- #


class User(_Base, TimestampMixin, SoftDeleteMixin, DomainEventMixin):
    """
    CrowdPay User aggregate root.

    Important business invariants enforced in code:
        • Email & username are unique (case-insensitive)
        • Password hashes use Argon2id with company-wide policy
        • KYC tier upgrades are monotonic (cannot downgrade)
        • Username can be changed **once** after registration
    """

    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email_normalized", name="uq_users_email"),
        sa.UniqueConstraint("username_normalized", name="uq_users_username"),
    )

    # Primary identifier
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
    )

    # Public profile information
    username: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    username_normalized: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(sa.String(64))

    # Contact details
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    email_normalized: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(sa.String(24))

    # Authentication
    _password_hash: Mapped[str] = mapped_column("password_hash", sa.String(256))

    # KYC / compliance
    kyc_tier: Mapped[KYCTier] = mapped_column(
        sa.Enum(KYCTier, name="kyc_tier"),
        default=KYCTier.NONE,
        nullable=False,
    )
    kyc_reference_id: Mapped[Optional[str]] = mapped_column(sa.String(64))
    risk_band: Mapped[RiskBand] = mapped_column(
        sa.Enum(RiskBand, name="risk_band"),
        default=RiskBand.LOW,
        nullable=False,
    )

    # Misc settings
    locale: Mapped[str] = mapped_column(sa.String(12), default="en_US", nullable=False)
    metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,  # noqa: WPS110 – intentional
        server_default="{}",
        nullable=False,
    )

    # Relationships (lazy-loaded)
    # Example: a user might own many CrowdPods
    crowdpods: Mapped[List["CrowdPod"]] = relationship(
        "CrowdPod",
        back_populates="owner",
        cascade="all,delete-orphan",
        lazy="selectin",
    )

    # --------------------------------------------------------------------- #
    #  Lifecycle hooks
    # --------------------------------------------------------------------- #

    def __init__(  # noqa: WPS612 – complex signature justified
        self,
        username: str,
        email: str,
        password: str,
        *,
        display_name: str | None = None,
        phone_number: str | None = None,
        locale: str = "en_US",
    ) -> None:
        self._init_event_buffer()

        self.username = username.strip()
        self.username_normalized = self.username.lower()

        self.display_name = display_name or self.username

        self.email = email.strip()
        self.email_normalized = self.email.lower()

        self.phone_number = phone_number
        self.locale = locale

        self.set_password(password)  # will hash + store

        self._raise_event(
            DomainEvent(
                name="UserRegistered",
                payload={
                    "user_id": str(self.id),
                    "email": self.email,
                    "username": self.username,
                },
            ),
        )

    # --------------------------------------------------------------------- #
    #  Authentication helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _hash_password(plain_password: str) -> str:
        return _PWD_CONTEXT.hash(plain_password)

    def set_password(self, plain_password: str) -> None:
        if not plain_password or len(plain_password) < 12:
            msg = "Password must contain at least 12 characters."
            raise ValueError(msg)

        self._password_hash = self._hash_password(plain_password)
        self._raise_event(
            DomainEvent(
                name="UserPasswordChanged",
                payload={"user_id": str(self.id)},
            ),
        )

    def verify_password(self, plain_password: str) -> bool:
        """
        Constant-time verification to mitigate timing-attacks.
        """
        ok = _PWD_CONTEXT.verify(plain_password, self._password_hash)
        # `passlib` will indicate if re-hashing is necessary
        if ok and _PWD_CONTEXT.needs_update(self._password_hash):
            # Re-hash transparently
            self._password_hash = self._hash_password(plain_password)
        return ok

    # --------------------------------------------------------------------- #
    #  Business behavior
    # --------------------------------------------------------------------- #

    def upgrade_kyc(self, new_tier: KYCTier, reference_id: str) -> None:
        """
        Promote the user to a higher KYC tier.

        Downgrades are not permitted. Attempting to downgrade will raise.
        """
        if new_tier.value <= self.kyc_tier.value:
            msg = (
                f"KYC upgrade must be higher than current tier "
                f"({self.kyc_tier} → {new_tier})."
            )
            raise ValueError(msg)

        self.kyc_tier = new_tier
        self.kyc_reference_id = reference_id
        self._raise_event(
            DomainEvent(
                name="UserKycUpgraded",
                payload={
                    "user_id": str(self.id),
                    "new_tier": new_tier,
                    "reference_id": reference_id,
                },
            ),
        )

    def flag_for_risk(self, new_band: RiskBand) -> None:
        """
        Change the user's risk band (e.g., after ML re-scoring).

        Escalating the risk band always emits an event; downgrades are allowed
        only if compliance service has approved it through an external workflow
        that adds `risk_downgrade_approved: true` to the metadata.
        """
        if new_band == self.risk_band:
            return  # no-op

        if new_band > self.risk_band:
            # Escalation
            self.risk_band = new_band
            self._raise_event(
                DomainEvent(
                    name="UserRiskEscalated",
                    payload={"user_id": str(self.id), "risk_band": int(new_band)},
                ),
            )
        else:
            # Potential downgrade
            if not self.metadata.get("risk_downgrade_approved"):
                msg = (
                    "Risk band downgrade not approved by compliance workflow; "
                    "set metadata['risk_downgrade_approved']=True to proceed."
                )
                raise PermissionError(msg)
            self.risk_band = new_band
            self._raise_event(
                DomainEvent(
                    name="UserRiskDowngraded",
                    payload={"user_id": str(self.id), "risk_band": int(new_band)},
                ),
            )

    # --------------------------------------------------------------------- #
    #  Utility helpers
    # --------------------------------------------------------------------- #

    @property
    def public_profile(self) -> Dict[str, Any]:
        """
        Serializable public profile; excludes PII & security-sensitive fields.
        """
        return {
            "id": str(self.id),
            "username": self.username,
            "display_name": self.display_name,
            "kyc_tier": self.kyc_tier.value,
            "risk_band": int(self.risk_band),
            "locale": self.locale,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            "User("
            f"id={self.id!s}, "
            f"username={self.username!r}, "
            f"email={self.email!r}, "
            f"kyc_tier={self.kyc_tier}, "
            f"risk_band={self.risk_band}"
            ")"
        )


# --------------------------------------------------------------------------- #
#  Example of related model to satisfy relationship – not fully implemented
# --------------------------------------------------------------------------- #

class CrowdPod(_Base):  # pragma: no cover – placeholder
    """
    Simplistic stub for CrowdPod aggregate to make the relationship valid.

    In real code this would live in its own module and hold substantial logic.
    """

    __tablename__ = "crowdpods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    owner: Mapped[User] = relationship("User", back_populates="crowdpods")


# --------------------------------------------------------------------------- #
#  SQLAlchemy events – audit trail injection
# --------------------------------------------------------------------------- #


def _audit_before_flush(session, flush_context, instances):  # noqa: D401
    """
    Collect domain events from all aggregates participating in the flush.

    A proper implementation would persist events into an ``outbox`` table
    within the same transaction to guarantee atomicity (a.k.a. transactional
    outbox).  Here we only demonstrate event collection.
    """
    for instance in session.new.union(session.dirty):
        if isinstance(instance, DomainEventMixin):
            for event_ in instance.pending_events:
                # `session.info.setdefault` survives commit / rollback barrier
                session.info.setdefault("outbox", []).append(event_)
            instance._clear_events()


event.listen(
    sa.orm.Session,
    "before_flush",
    _audit_before_flush,
)
```