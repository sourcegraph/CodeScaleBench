```python
"""
crowdpay_connect.services.wallet_service.app.models.transaction_log

Domain model for immutable, append-only transaction logs that power
CrowdPay Connect’s event-sourcing layer.  Every balance mutation,
cross-pod transfer, or settlement operation produces a TransactionLog
record that is consumed by downstream micro-services (Risk, KYC,
Compliance, Ledger, Notifications, etc).

The log is deliberately denormalised and self-contained so that a single
row holds every attribute required to replay or audit a transaction,
even if related domain objects are later deleted or archived.
"""

from __future__ import annotations

import enum
import typing as _t
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    event,
    orm,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Prefer the project-wide declarative base if available.  Fall back to a local one
# so that stand-alone tooling (e.g. `pytest`, `alembic revision --autogenerate`)
# keeps working when the entire package isn't imported.
try:  # pragma: no cover
    from ..db.base import Base
except Exception:  # pylint: disable=broad-except
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()  # type: ignore  # noqa: N816


class TxType(str, enum.Enum):
    """
    High-level classification of wallet transactions.
    """

    DEBIT = "DEBIT"               # Wallet balance decreases
    CREDIT = "CREDIT"             # Wallet balance increases
    RESERVE = "RESERVE"           # Funds reserved for later capture
    RELEASE = "RELEASE"           # Release previously reserved funds
    HOLD = "HOLD"                 # Regulatory or risk hold
    REVERSAL = "REVERSAL"         # Reversal initiated (chargeback, refund)
    ADJUSTMENT = "ADJUSTMENT"     # Manual back-office balance adjustment


class TxStatus(str, enum.Enum):
    """
    Lifecycle state of a transaction.
    """

    PENDING = "PENDING"           # In flight (e.g. saga not finished)
    COMPLETED = "COMPLETED"       # Persisted on ledger, immutable
    FAILED = "FAILED"             # Hard failure – no ledger impact
    ROLLED_BACK = "ROLLED_BACK"   # Saga compensation executed successfully
    CANCELLED = "CANCELLED"       # User or system cancelled before commit


class FailureCode(str, enum.Enum):
    """
    Canonical failure reasons used to classify unsuccessful payments.
    """

    NONE = "NONE"                 # Placeholder for succeed cases
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    FRAUD_DETECTED = "FRAUD_DETECTED"
    COMPLIANCE_BLOCK = "COMPLIANCE_BLOCK"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PARTNER_ERROR = "PARTNER_ERROR"
    UNKNOWN = "UNKNOWN"


class TransactionLog(Base):  # type: ignore[misc]
    """
    Immutable append-only log entry for a wallet transaction.

    Unless explicitly wrapped in a database transaction and deleted
    before commit this row MUST NOT be updated nor deleted – it
    constitutes an audit trail.
    """

    __tablename__ = "transaction_logs"

    # Core identifiers
    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,  # quick lookup for idempotency & saga correlation
    )
    pod_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    wallet_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    initiated_by_user_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # Business attributes
    tx_type: orm.Mapped[TxType] = orm.mapped_column(
        Enum(TxType, values_callable=lambda obj: [e.value for e in obj]),  # type: ignore[arg-type]  # noqa: E501
        nullable=False,
    )
    status: orm.Mapped[TxStatus] = orm.mapped_column(
        Enum(TxStatus, values_callable=lambda obj: [e.value for e in obj]),  # type: ignore[arg-type]  # noqa: E501
        nullable=False,
        default=TxStatus.PENDING,
    )

    amount: orm.Mapped[float] = orm.mapped_column(
        Numeric(precision=18, scale=2),  # Up to 999 trillion with 2 decimals
        nullable=False,
    )
    currency: orm.Mapped[str] = orm.mapped_column(String(3), nullable=False)
    fx_rate: orm.Mapped[float | None] = orm.mapped_column(
        Numeric(precision=18, scale=8), nullable=True
    )  # Original amount × fx_rate = settlement amount

    # Compliance & risk flags
    risk_score: orm.Mapped[int | None] = orm.mapped_column(
        Numeric(precision=4, scale=0),
        nullable=True,
        doc="0-999 risk score returned by the risk engine.",
    )
    kyc_verified: orm.Mapped[bool] = orm.mapped_column(Boolean, default=False)

    failure_code: orm.Mapped[FailureCode] = orm.mapped_column(
        Enum(FailureCode, values_callable=lambda obj: [e.value for e in obj]),  # type: ignore[arg-type]  # noqa: E501
        nullable=False,
        default=FailureCode.NONE,
    )
    failure_reason: orm.Mapped[str | None] = orm.mapped_column(
        String(512), nullable=True
    )

    # Misc
    metadata: orm.Mapped[dict[str, _t.Any] | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        doc="Arbitrary immutable JSON payload (provider response, etc.)",
    )

    created_at: orm.Mapped[datetime] = orm.mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        Index(
            "idx_transaction_logs_wallet_status_created",
            "wallet_id",
            "status",
            "created_at",
        ),
        Index(
            "idx_transaction_logs_pod_status_created",
            "pod_id",
            "status",
            "created_at",
        ),
    )

    # --------------------------------------------------------------------- #
    # Domain helpers
    # --------------------------------------------------------------------- #

    def mark_completed(self, session: orm.Session) -> None:
        """
        Mark this transaction as COMPLETED if currently pending.
        Raises:
            ValueError: if the status transition is invalid.
        """
        if self.status not in {TxStatus.PENDING}:
            raise ValueError(
                f"Cannot mark transaction {self.id} as completed from {self.status}"
            )
        self.status = TxStatus.COMPLETED
        self.updated_at = datetime.now(timezone.utc)
        session.add(self)

    def mark_failed(
        self,
        session: orm.Session,
        failure_code: FailureCode = FailureCode.UNKNOWN,
        failure_reason: str | None = None,
    ) -> None:
        """
        Mark this transaction as FAILED and update failure metadata.
        """
        if self.status not in {TxStatus.PENDING}:
            raise ValueError(
                f"Cannot mark transaction {self.id} as failed from {self.status}"
            )
        self.status = TxStatus.FAILED
        self.failure_code = failure_code
        if failure_reason:
            self.failure_reason = failure_reason[:512]
        self.updated_at = datetime.now(timezone.utc)
        session.add(self)

    @property
    def is_successful(self) -> bool:
        return self.status == TxStatus.COMPLETED and self.failure_code == FailureCode.NONE  # type: ignore[comparison-overlap]  # noqa: E501

    # --------------------------------------------------------------------- #
    # SQLAlchemy event listeners
    # --------------------------------------------------------------------- #

    @staticmethod
    def _set_updated_at(mapper, connection, target) -> None:  # noqa: N805
        """
        SQLAlchemy callback to keep the updated_at column in sync on UPDATE.
        """
        target.updated_at = datetime.now(timezone.utc)

    # Hook both UPDATE and INSERT events.
    event.listen(
        __mapper__, "before_update", _set_updated_at.__func__  # type: ignore[attr-defined]  # noqa: E501
    )

    # --------------------------------------------------------------------- #
    # Convenience constructors
    # --------------------------------------------------------------------- #

    @classmethod
    def create(
        cls,
        *,
        session: orm.Session,
        transaction_id: uuid.UUID,
        pod_id: uuid.UUID,
        wallet_id: uuid.UUID,
        initiated_by_user_id: uuid.UUID | None,
        tx_type: TxType,
        amount: float,
        currency: str,
        fx_rate: float | None = None,
        metadata: dict[str, _t.Any] | None = None,
        risk_score: int | None = None,
        kyc_verified: bool = False,
    ) -> "TransactionLog":
        """
        Factory method that creates and persists a new log row, handling
        mandatory attributes, idempotency, and common integrity errors.
        """
        if amount <= 0:
            raise ValueError("Transaction amount must be positive")

        log_entry = cls(
            transaction_id=transaction_id,
            pod_id=pod_id,
            wallet_id=wallet_id,
            initiated_by_user_id=initiated_by_user_id,
            tx_type=tx_type,
            amount=amount,
            currency=currency.upper(),
            fx_rate=fx_rate,
            metadata=metadata,
            risk_score=risk_score,
            kyc_verified=kyc_verified,
        )
        session.add(log_entry)
        return log_entry

    # --------------------------------------------------------------------- #
    # Dunder methods
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:  # pragma: no cover
        protected_fields = {
            "id",
            "transaction_id",
            "wallet_id",
            "amount",
            "currency",
            "status",
        }
        attrs = (
            f"{name}={getattr(self, name)!r}" for name in protected_fields  # noqa: B023
        )
        return f"<TransactionLog({', '.join(attrs)})>"
```