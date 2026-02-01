```python
from __future__ import annotations

import datetime as _dt
import decimal
import enum
import uuid
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event as sa_event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    Mapped,
    Session,
    declarative_base,
    mapped_column,
    relationship,
    validates,
)

# --------------------------------------------------------------------------- #
# Infrastructure / shared kernels                                             #
# --------------------------------------------------------------------------- #

Base = declarative_base()


class TimestampMixin:
    """Adds created_at / updated_at timestamps to inheriting models."""

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_dt.datetime.utcnow
    )
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_dt.datetime.utcnow,
        onupdate=_dt.datetime.utcnow,
    )


class SoftDeleteMixin:
    """Soft-delete implementation—records remain in DB for audit purposes."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def delete(self, *, hard: bool = False, session: Session | AsyncSession) -> None:
        """Mark record as deleted (hard=true => permanent removal)."""
        if hard:
            session.delete(self)
        else:
            self.is_deleted = True


# --------------------------------------------------------------------------- #
# Money & Currency Value Object                                               #
# --------------------------------------------------------------------------- #


class Currency(str, enum.Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    NGN = "NGN"
    GHS = "GHS"
    KES = "KES"

    @classmethod
    def has_value(cls, value: str) -> bool:  # pragma: no cover
        return value in cls.__members__


class Money:
    """Lightweight money representation with fixed-point arithmetic."""

    __slots__ = ("_amount", "_currency")

    def __init__(self, amount: decimal.Decimal | float | str, currency: Currency):
        if not isinstance(currency, Currency):
            raise TypeError("currency must be an instance of Currency Enum.")
        quantized = (
            decimal.Decimal(str(amount)).quantize(decimal.Decimal("0.01"))
            if not isinstance(amount, decimal.Decimal)
            else amount.quantize(decimal.Decimal("0.01"))
        )
        if quantized < decimal.Decimal("0"):
            raise ValueError("Money cannot be negative.")
        self._amount: decimal.Decimal = quantized
        self._currency: Currency = currency

    # ------------------------------------------------------------------ #
    # Dunder helpers                                                      #
    # ------------------------------------------------------------------ #

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self._amount + other._amount, currency=self._currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        if other._amount > self._amount:
            raise ValueError("Insufficient funds.")
        return Money(self._amount - other._amount, currency=self._currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if self._currency != other._currency:
            raise ValueError("Currency mismatch.")

    # ------------------------------------------------------------------ #
    # Properties                                                         #
    # ------------------------------------------------------------------ #

    @property
    def amount(self) -> decimal.Decimal:
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    # ------------------------------------------------------------------ #
    # Serialization                                                      #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        return {"amount": str(self._amount), "currency": self._currency.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Money":
        return cls(data["amount"], Currency(data["currency"]))

    # ------------------------------------------------------------------ #
    # Representation                                                     #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return f"Money(amount={self._amount}, currency={self._currency})"


# --------------------------------------------------------------------------- #
# Domain Events (simplified for illustration)                                #
# --------------------------------------------------------------------------- #

class DomainEvent:
    """Base type for domain events."""
    occurred_on: _dt.datetime
    payload: Dict[str, Any]

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.occurred_on = _dt.datetime.utcnow()
        self.payload = payload


class PodBalanceChanged(DomainEvent):
    pass


class PodMemberAdded(DomainEvent):
    pass


# --------------------------------------------------------------------------- #
# Association Tables                                                          #
# --------------------------------------------------------------------------- #

class PodMemberRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    CONTRIBUTOR = "CONTRIBUTOR"
    VIEWER = "VIEWER"


class PodMember(Base, TimestampMixin):
    """Member–to–Pod association with role & permissions."""

    __tablename__ = "pod_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pod_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pods.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[PodMemberRole] = mapped_column(
        Enum(PodMemberRole), default=PodMemberRole.CONTRIBUTOR, nullable=False
    )
    inviter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("pod_id", "user_id", name="uq_pod_user"),
        Index("ix_pod_member_user", "user_id"),
    )

    def promote(self, new_role: PodMemberRole) -> None:
        if self.role == PodMemberRole.OWNER:
            raise ValueError("Owner role cannot be changed.")
        self.role = new_role


class PodBalance(Base, TimestampMixin):
    """Represents a Pod's liquid balance per currency."""

    __tablename__ = "pod_balances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pod_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pods.id", ondelete="CASCADE"))
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    available_amount: Mapped[decimal.Decimal] = mapped_column(
        Integer, default=0, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "pod_id",
            "currency",
            name="uq_pod_currency",
        ),
    )

    # ------------------------------------------------------------------ #
    # Domain behavior                                                    #
    # ------------------------------------------------------------------ #

    def deposit(self, money: Money) -> None:
        self._assert_currency(money)
        self.available_amount += money.amount

    def withdraw(self, money: Money) -> None:
        self._assert_currency(money)
        if money.amount > self.available_amount:
            raise ValueError("Insufficient funds.")
        self.available_amount -= money.amount

    def _assert_currency(self, money: Money) -> None:
        if self.currency != money.currency:
            raise ValueError("Currency mismatch.")


# --------------------------------------------------------------------------- #
# Pod Aggregate                                                               #
# --------------------------------------------------------------------------- #

class PodStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Pod(Base, TimestampMixin, SoftDeleteMixin):
    """CrowdPod wallet aggregate root."""

    __tablename__ = "pods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[PodStatus] = mapped_column(
        Enum(PodStatus), default=PodStatus.ACTIVE, nullable=False
    )
    base_currency: Mapped[Currency] = mapped_column(
        Enum(Currency), default=Currency.USD, nullable=False
    )
    risk_score: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="0-100 risk scale"
    )
    metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="Optimistic lock version"
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                      #
    # ------------------------------------------------------------------ #

    balances: Mapped[List[PodBalance]] = relationship(
        PodBalance,
        backref="pod",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    members: Mapped[List[PodMember]] = relationship(
        PodMember,
        backref="pod",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ------------------------------------------------------------------ #
    # Domain events / changes                                            #
    # ------------------------------------------------------------------ #

    _pending_events: List[DomainEvent]

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:  # noqa: D401
        if not value or len(value) < 3:
            raise ValueError("Pod name must be at least 3 characters.")
        return value

    # ------------------------------------------------------------------ #
    # Aggregate Root public API                                          #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        *,
        name: str,
        slug: str,
        owner_id: uuid.UUID,
        base_currency: Currency = Currency.USD,
        metadata: Dict[str, Any] | None = None,
    ) -> None:  # noqa: D401
        super().__init__(
            name=name,
            slug=slug,
            base_currency=base_currency,
            metadata=metadata or {},
        )
        self._pending_events = []
        self._bootstrap(owner_id=owner_id)

    # ------------------------------------------------------------------ #
    # Private helpers                                                    #
    # ------------------------------------------------------------------ #

    def _bootstrap(self, owner_id: uuid.UUID) -> None:
        """Create default balance & owner membership."""
        # bootstrap zero balance for base currency
        self.balances.append(PodBalance(currency=self.base_currency))
        # bootstrap owner membership
        self.members.append(
            PodMember(
                user_id=owner_id,
                role=PodMemberRole.OWNER,
                inviter_id=None,
            )
        )

    # ------------------------------------------------------------------ #
    # Membership API                                                     #
    # ------------------------------------------------------------------ #

    def add_member(
        self,
        user_id: uuid.UUID,
        inviter_id: uuid.UUID,
        role: PodMemberRole = PodMemberRole.CONTRIBUTOR,
    ) -> None:
        """Attach a new member to the Pod."""
        if any(m.user_id == user_id for m in self.members):
            raise ValueError("User already a member of this Pod.")
        self.members.append(
            PodMember(
                user_id=user_id,
                role=role,
                inviter_id=inviter_id,
            )
        )
        self._record_event(
            PodMemberAdded(
                {
                    "pod_id": str(self.id),
                    "user_id": str(user_id),
                    "role": role.value,
                    "inviter_id": str(inviter_id),
                }
            )
        )

    # ------------------------------------------------------------------ #
    # Financial API                                                      #
    # ------------------------------------------------------------------ #

    def deposit(self, money: Money) -> None:
        balance = self._get_or_create_balance(money.currency)
        balance.deposit(money)
        self._record_event(
            PodBalanceChanged(
                {
                    "pod_id": str(self.id),
                    "currency": money.currency.value,
                    "delta": str(money.amount),
                    "type": "DEPOSIT",
                }
            )
        )

    def withdraw(self, money: Money) -> None:
        balance = self._get_or_create_balance(money.currency)
        balance.withdraw(money)
        self._record_event(
            PodBalanceChanged(
                {
                    "pod_id": str(self.id),
                    "currency": money.currency.value,
                    "delta": str(-money.amount),
                    "type": "WITHDRAWAL",
                }
            )
        )

    # ------------------------------------------------------------------ #
    # Domain Internals                                                   #
    # ------------------------------------------------------------------ #

    def _get_or_create_balance(self, currency: Currency) -> PodBalance:
        for bal in self.balances:
            if bal.currency == currency:
                return bal
        # Not found -> create new with zero amount
        balance = PodBalance(currency=currency, available_amount=0)
        self.balances.append(balance)
        return balance

    def _record_event(self, event: DomainEvent) -> None:
        self._pending_events.append(event)

    def pull_events(self) -> Iterable[DomainEvent]:
        """Expose and empty the queue of pending domain events."""
        events, self._pending_events = self._pending_events, []
        return events

    # ------------------------------------------------------------------ #
    # Risk & Compliance                                                  #
    # ------------------------------------------------------------------ #

    def update_risk_score(self, new_score: int) -> None:
        if not 0 <= new_score <= 100:
            raise ValueError("Risk score must be between 0 and 100.")
        self.risk_score = new_score

    def suspend(self, reason: str) -> None:
        if self.status != PodStatus.ACTIVE:
            raise ValueError("Only active pods can be suspended.")
        self.status = PodStatus.SUSPENDED
        self.metadata.setdefault("suspension_reason", reason)

    def close(self) -> None:
        if self.status == PodStatus.CLOSED:
            raise ValueError("Pod already closed.")
        if any(b.available_amount > 0 for b in self.balances):
            raise ValueError("Cannot close pod with non-zero balance.")
        self.status = PodStatus.CLOSED

    # ------------------------------------------------------------------ #
    # Optimistic Concurrency Handling                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _versioning_listener(mapper, connection, target) -> None:  # noqa: N805
        target.version += 1


# Register optimistic lock listener.
sa_event.listen(Pod, "before_update", Pod._versioning_listener)

# --------------------------------------------------------------------------- #
# Utility functions for querying                                             #
# --------------------------------------------------------------------------- #

async def get_pod_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    include_deleted: bool = False,
) -> Optional[Pod]:
    """Retrieve a Pod aggregate by its slug."""
    stmt = (
        select(Pod)
        .where(Pod.slug == slug)
        .where(True if include_deleted else Pod.is_deleted.is_(False))
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()
```