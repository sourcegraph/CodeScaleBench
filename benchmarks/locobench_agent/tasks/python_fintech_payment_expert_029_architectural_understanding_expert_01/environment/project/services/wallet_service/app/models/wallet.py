```python
"""
crowdpay_connect.services.wallet_service.app.models.wallet

Domain / ORM model for Wallets inside CrowdPay Connect.

Highlights
----------
1. SQLAlchemy 2.0–style declarative mapping with Postgres specific
   columns (UUID + JSONB) and optimistic-locking (version_id).
2. Multi-currency support via JSONB `balances` mapping
   ISO-4217 currency code -> stringified decimal.
3. Domain methods (`deposit`, `withdraw`, `lock`, `unlock`, `close`)
   that raise rich domain exceptions so that application-layer code
   can react accordingly.
4. Event-sourcing hooks: every mutating domain method emits
   an in-memory `WalletEvent` ready to be persisted to an event store
   by the calling service layer / Saga.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as PgEnum,
    Integer,
    String,
    event,
    func,
    types,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, validates

# --- SQLAlchemy Declarative Base ------------------------------------------- #
# In a larger project this would likely live in a shared module, but keeping
# it local makes the example self-contained.
Base = declarative_base()


# --- Exceptions ------------------------------------------------------------ #
class WalletError(Exception):
    """Base error for all wallet domain exceptions."""


class InsufficientFunds(WalletError):
    """Raised when a withdrawal exceeds the wallet’s balance."""


class WalletLocked(WalletError):
    """Raised when an operation is attempted on a locked wallet."""


class InvalidCurrency(WalletError):
    """Raised when an unsupported/invalid currency is supplied."""


class WalletClosed(WalletError):
    """Raised when operations occur on a closed wallet."""


# --- Helper / Domain Constructs ------------------------------------------- #
ISO_CURRENCY_LENGTH = 3  # e.g., "USD", "EUR"


class WalletStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class WalletEventType(enum.Enum):
    BALANCE_CREDITED = "BALANCE_CREDITED"
    BALANCE_DEBITED = "BALANCE_DEBITED"
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    CLOSED = "CLOSED"


class WalletEvent:
    """
    Lightweight domain event to be raised by Wallet aggregates.

    The application-layer (command-handler / Saga) is responsible for capturing
    these objects and persisting them into the event store or publishing them
    on the message bus.
    """

    __slots__ = ("event_type", "wallet_id", "payload", "occurred_at")

    def __init__(
        self,
        event_type: WalletEventType,
        wallet_id: uuid.UUID,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.event_type = event_type
        self.wallet_id = wallet_id
        self.payload = payload or {}
        self.occurred_at = datetime.now(tz=timezone.utc)

    # representation for debugging / logging
    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<WalletEvent {self.event_type.value} wallet={self.wallet_id} "
            f"occurred_at={self.occurred_at.isoformat()}>"
        )


# --- Wallet ORM / Aggregate Root ------------------------------------------ #
class Wallet(Base):  # type: ignore[misc]
    """
    ORM entity + Domain Aggregate Root representing a multi-currency wallet.
    """

    __tablename__ = "wallets"

    # --------------------------------------------------------------------- #
    # Columns / schema
    # --------------------------------------------------------------------- #
    id: uuid.UUID = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    owner_id: uuid.UUID = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="Foreign-key to `users.id` (logical, enforced in service layer).",
    )

    balances: Dict[str, str] = Column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Mapping ISO-currency -> stringified Decimal balance.",
    )

    status: WalletStatus = Column(
        PgEnum(WalletStatus, name="wallet_status"),
        nullable=False,
        default=WalletStatus.ACTIVE,
    )

    kyc_verified: bool = Column(
        Boolean,
        nullable=False,
        default=False,
        doc="Copy of KYC-service state, cached for quick checks.",
    )

    risk_score: Decimal = Column(
        types.Numeric(precision=9, scale=4),
        nullable=False,
        default=Decimal("0.0000"),
        doc="Real-time aggregated risk assessment score.",
    )

    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    version_id: int = Column(
        Integer,
        nullable=False,
        default=0,
    )

    __table_args__ = (
        CheckConstraint("version_id >= 0", name="ck_wallet_version_non_negative"),
    )

    # --------------------------------------------------------------------- #
    # Domain / aggregate state (transient)
    # --------------------------------------------------------------------- #
    _pending_events: List[WalletEvent]

    # --------------------------------------------------------------------- #
    # Constructors / Lifecycle hooks
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        owner_id: uuid.UUID,
        initial_balances: Optional[Dict[str, Decimal]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[misc]
        self.owner_id = owner_id
        self.balances = {
            c.upper(): str(v.quantize(Decimal("0.01")))
            for c, v in (initial_balances or {}).items()
        }
        self.status = WalletStatus.ACTIVE
        self._pending_events = []

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #
    @validates("balances")
    def _validate_balances(
        self, _key: str, value: Dict[str, str]
    ) -> Dict[str, str]:
        for currency_code, amount in value.items():
            if len(currency_code) != ISO_CURRENCY_LENGTH or not currency_code.isalpha():
                raise InvalidCurrency(
                    f"Currency code '{currency_code}' is not valid ISO-4217."
                )
            # Additional numeric validation
            try:
                Decimal(amount)
            except Exception as exc:  # pragma: no cover
                raise ValueError(f"Invalid decimal amount for {currency_code}.") from exc
        return value

    # --------------------------------------------------------------------- #
    # Public API / Domain methods
    # --------------------------------------------------------------------- #
    def deposit(self, currency: str, amount: Decimal) -> None:
        """
        Credit funds into the wallet.

        Emits: WalletEventType.BALANCE_CREDITED
        """
        self._assert_mutable()
        currency = self._normalize_currency(currency)
        amount = self._normalize_amount(amount)

        current = Decimal(self.balances.get(currency, "0"))
        new_balance = current + amount
        self.balances[currency] = str(new_balance)

        self._add_event(
            WalletEventType.BALANCE_CREDITED,
            {"currency": currency, "amount": str(amount)},
        )

    def withdraw(self, currency: str, amount: Decimal) -> None:
        """
        Debit funds from the wallet, raising `InsufficientFunds` if balance
        would become negative.

        Emits: WalletEventType.BALANCE_DEBITED
        """
        self._assert_mutable()
        currency = self._normalize_currency(currency)
        amount = self._normalize_amount(amount)

        if currency not in self.balances:
            raise InsufficientFunds(f"No balance for currency {currency}.")

        current = Decimal(self.balances[currency])
        if current < amount:
            raise InsufficientFunds(
                f"Insufficient funds: balance={current} requested={amount}."
            )

        new_balance = current - amount
        self.balances[currency] = str(new_balance)

        self._add_event(
            WalletEventType.BALANCE_DEBITED,
            {"currency": currency, "amount": str(amount)},
        )

    def lock(self, reason: str) -> None:
        """
        Lock wallet due to risk/compliance reasons. Only allowed if ACTIVE.

        Emits: WalletEventType.LOCKED
        """
        if self.status == WalletStatus.CLOSED:
            raise WalletClosed("Cannot lock a closed wallet.")
        if self.status == WalletStatus.LOCKED:
            return  # idempotent

        self.status = WalletStatus.LOCKED
        self._add_event(WalletEventType.LOCKED, {"reason": reason})

    def unlock(self, reason: str) -> None:
        """
        Unlock a previously locked wallet.

        Emits: WalletEventType.UNLOCKED
        """
        if self.status == WalletStatus.CLOSED:
            raise WalletClosed("Cannot unlock a closed wallet.")
        if self.status != WalletStatus.LOCKED:
            return  # idempotent

        self.status = WalletStatus.ACTIVE
        self._add_event(WalletEventType.UNLOCKED, {"reason": reason})

    def close(self) -> None:
        """
        Permanently close a wallet. Should only be performed after settlement
        has ensured that balances are zero.

        Emits: WalletEventType.CLOSED
        """
        if self.status == WalletStatus.CLOSED:
            return  # idempotent

        if any(Decimal(v) != 0 for v in self.balances.values()):
            raise WalletError(
                "Cannot close wallet with non-zero balances; settle first."
            )

        self.status = WalletStatus.CLOSED
        self._add_event(WalletEventType.CLOSED, {})

    # --------------------------------------------------------------------- #
    # Domain utilities
    # --------------------------------------------------------------------- #
    def pull_events(self) -> List[WalletEvent]:
        """
        Return and clear the list of pending domain events.
        This is a common pattern so that the service layer can collect and
        forward events without exposing `_pending_events` directly.
        """
        events, self._pending_events = self._pending_events, []
        return events

    # JSON-serialisable snapshot (e.g., for message bus payloads)
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "owner_id": str(self.owner_id),
            "balances": self.balances,
            "status": self.status.value,
            "kyc_verified": self.kyc_verified,
            "risk_score": str(self.risk_score),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version_id": self.version_id,
        }

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #
    def _assert_mutable(self) -> None:
        if self.status == WalletStatus.LOCKED:
            raise WalletLocked("Operation not permitted on a locked wallet.")
        if self.status == WalletStatus.CLOSED:
            raise WalletClosed("Operation not permitted on a closed wallet.")

    def _add_event(
        self, event_type: WalletEventType, payload: Optional[Dict[str, Any]] = None
    ) -> None:
        self._pending_events.append(WalletEvent(event_type, self.id, payload))

    @staticmethod
    def _normalize_currency(currency: str) -> str:
        if not currency or len(currency.strip()) != ISO_CURRENCY_LENGTH:
            raise InvalidCurrency("Currency must be 3-letter ISO-4217 code.")
        return currency.strip().upper()

    @staticmethod
    def _normalize_amount(amount: Decimal) -> Decimal:
        if amount <= 0:
            raise ValueError("Amount must be positive.")
        # Round to 2 decimal places (typical for fiat currencies)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- SQLAlchemy Events / Optimistic Concurrency --------------------------- #
@event.listens_for(Session, "before_flush")
def _increment_version_before_flush(session: Session, _flush_context, _instances):
    """
    Increment `version_id` for any changed Wallet entities to enable optimistic
    concurrency control. This is executed right before the flush so the DB
    receives the incremented version which must match the where-clause in
    the UPDATE statement.
    """
    for instance in session.dirty:
        if isinstance(instance, Wallet):
            # Only if changes are pending (attrs dirty)
            if session.is_modified(instance, include_collections=False):
                instance.version_id += 1
```