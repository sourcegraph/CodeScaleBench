```python
"""
crowdpay_connect.services.wallet_service.app.core.ledger
========================================================

Core ledger domain module for CrowdPay Connect Wallet Service.

Responsibilities
----------------
1. Provide an immutable, auditable, double–entry ledger for every wallet
   (CrowdPod) in the platform.
2. Expose a **LedgerService** that upstream application layers (e.g. API
   controllers, Sagas, CQRS command handlers) can use to record financial
   movements in a safe, idempotent, multi-currency aware manner.
3. Publish domain events to the event-bus so that downstream projections
   (e.g. compliance reports, reputation score calculators) remain in sync.
4. Integrate with the global Saga coordinator to guarantee atomicity of
   distributed payment workflows.

Notes
-----
The implementation below purposefully hides infrastructure details
(database adapters, event bus client, fx-rate fetchers, etc.) behind
well-defined *protocols* so that the core domain remains persistence-
agnostic and highly testable.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum, auto
from types import TracebackType
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
    Union,
)

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Shared value objects & enums                                                #
# --------------------------------------------------------------------------- #


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class EntryStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    REVERSED = "REVERSED"
    FAILED = "FAILED"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    # Extend as needed


@dataclass(frozen=True, slots=True)
class Money:
    """
    Immutable value object representing a monetary amount in a given currency.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if self.amount < Decimal("0"):
            raise ValueError("Money amount cannot be negative")

    def __neg__(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError("Currency mismatch: %s vs %s", self.currency, other.currency)


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class LedgerError(Exception):
    """Base class for ledger-related errors."""


class DuplicateEntryError(LedgerError):
    """Raised when the client attempts to post a transaction that already exists."""


class InsufficientFundsError(LedgerError):
    """Raised when a wallet lacks enough balance for a debit operation."""


class SagaCommitError(LedgerError):
    """Raised when a distributed saga fails to commit."""


# --------------------------------------------------------------------------- #
# Protocols (Ports)                                                           #
# --------------------------------------------------------------------------- #


class AbstractEventPublisher(Protocol):
    async def publish(self, event_name: str, payload: Mapping[str, Any]) -> None: ...


class AbstractLedgerRepository(Protocol):
    """
    Persistence port. Implemented by an infrastructure adapter (e.g. SQLAlchemy).
    """

    async def fetch_entry_by_external_id(
        self, external_id: str
    ) -> Optional["LedgerEntry"]: ...

    async def save_entries(self, entries: Sequence["LedgerEntry"]) -> None: ...

    async def list_wallet_balance(self, wallet_id: uuid.UUID) -> Mapping[Currency, Money]: ...

    @contextlib.asynccontextmanager
    async def transaction(self) -> "AsyncLedgerTxn": ...

    async def mark_committed(self, entry_ids: Sequence[uuid.UUID]) -> None: ...

    async def mark_reversed(
        self, entry_ids: Sequence[uuid.UUID], reason: str, *, failed: bool = False
    ) -> None: ...


class AbstractFxRateProvider(Protocol):
    """
    Foreign exchange rate provider.
    """

    async def convert(self, money: Money, to_currency: Currency) -> Money: ...


# --------------------------------------------------------------------------- #
# Domain entities                                                              #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class LedgerEntry:
    """
    Domain entity representing a single row in the ledger.

    In a double-entry ledger, every external transfer appears as **two**
    complementary entries: a debit in the origin wallet and a credit in the
    destination wallet.
    """

    id: uuid.UUID
    wallet_id: uuid.UUID
    entry_type: EntryType
    money: Money
    external_txn_id: str  # Idempotency key for de-duplication across retries
    status: EntryStatus = field(default=EntryStatus.PENDING)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), init=False
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- Behaviors ---------------------------------------------------------- #

    def commit(self) -> None:
        if self.status is not EntryStatus.PENDING:
            raise LedgerError(f"Cannot commit entry {self.id}: status = {self.status}")
        self.status = EntryStatus.COMMITTED

    def reverse(self, reason: str, *, failed: bool = False) -> None:
        if self.status is EntryStatus.COMMITTED:
            self.status = EntryStatus.REVERSED if not failed else EntryStatus.FAILED
            self.metadata["reverse_reason"] = reason
        else:
            raise LedgerError(f"Cannot reverse entry {self.id}: status = {self.status}")


# --------------------------------------------------------------------------- #
# Auxiliary helpers                                                           #
# --------------------------------------------------------------------------- #


class AsyncLedgerTxn:
    """
    Async context manager returned by repository.transaction().
    """

    async def __aenter__(self) -> "AsyncLedgerTxn":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # In a real adapter we would commit/rollback DB here.
        return False


# --------------------------------------------------------------------------- #
# Saga coordinator (simplified)                                               #
# --------------------------------------------------------------------------- #


class SagaStep(Protocol):
    async def invoke(self) -> None: ...

    async def compensate(self) -> None: ...


class SagaCoordinator:
    """
    Extremely slim saga coordinator focusing on ledger local steps.

    Upstream "payment orchestrator" may pass additional steps (e.g. FX
    settlement, compliance reporting) to achieve global atomicity.
    """

    def __init__(self, steps: Sequence[SagaStep]) -> None:
        self._steps: List[SagaStep] = list(steps)
        self._completed: List[SagaStep] = []

    async def execute(self) -> None:
        try:
            for step in self._steps:
                await step.invoke()
                self._completed.append(step)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Saga step failed; starting compensation", exc_info=exc)
            await self._compensate()
            raise SagaCommitError("Saga aborted due to failure") from exc

    async def _compensate(self) -> None:
        for step in reversed(self._completed):
            with contextlib.suppress(Exception):
                await step.compensate()


# --------------------------------------------------------------------------- #
# Ledger service                                                              #
# --------------------------------------------------------------------------- #


class LedgerService:
    """
    Application-level facade responsible for recording double-entry
    transactions and ensuring eventual consistency through sagas and events.
    """

    def __init__(
        self,
        repo: AbstractLedgerRepository,
        publisher: AbstractEventPublisher,
        fx_provider: AbstractFxRateProvider,
    ) -> None:
        self._repo = repo
        self._publisher = publisher
        self._fx = fx_provider

    # --------------------------------------------------------------------- #
    # Public API                                                             #
    # --------------------------------------------------------------------- #

    async def transfer(
        self,
        *,
        origin_wallet_id: uuid.UUID,
        dest_wallet_id: uuid.UUID,
        amount: Decimal,
        currency: Currency,
        external_txn_id: str,
        description: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[LedgerEntry, LedgerEntry]:
        """
        Orchestrate a double-entry transfer between two wallets.

        1. Validate idempotency.
        2. Check available funds.
        3. Assemble **pending** ledger entries.
        4. Execute Saga:
           a. Persist entries atomically.
           b. Commit entries.
        5. Publish events.

        Returns
        -------
        Tuple[LedgerEntry, LedgerEntry]
            `(debit_entry, credit_entry)`
        """
        if await self._repo.fetch_entry_by_external_id(external_txn_id):
            logger.info("Duplicate external_txn_id=%s. Fast-returning.", external_txn_id)
            raise DuplicateEntryError(f"Transaction {external_txn_id} already processed")

        money = Money(Decimal(amount), currency)

        # Step 1 – ensure origin wallet has sufficient funds
        await self._assert_sufficient_balance(origin_wallet_id, money)

        # Step 2 – create *pending* ledger entries
        debit_entry = LedgerEntry(
            id=uuid.uuid4(),
            wallet_id=origin_wallet_id,
            entry_type=EntryType.DEBIT,
            money=money,
            external_txn_id=external_txn_id,
            metadata={"description": description, **(metadata or {})},
        )
        credit_entry = LedgerEntry(
            id=uuid.uuid4(),
            wallet_id=dest_wallet_id,
            entry_type=EntryType.CREDIT,
            money=money,
            external_txn_id=external_txn_id,
            metadata={"description": description, **(metadata or {})},
        )

        # Step 3 – wrap in a local saga to ensure durability + commit
        saga_steps: List[SagaStep] = [
            _PersistEntriesStep(self._repo, debit_entry, credit_entry),
            _CommitEntriesStep(self._repo, debit_entry, credit_entry),
            _PublishEventsStep(self._publisher, debit_entry, credit_entry),
        ]
        saga = SagaCoordinator(saga_steps)

        await saga.execute()
        logger.info(
            "Transfer committed: %s -> %s amount=%s %s",
            origin_wallet_id,
            dest_wallet_id,
            money.amount,
            money.currency,
        )
        return debit_entry, credit_entry

    async def get_balances(
        self, wallet_id: uuid.UUID, *, in_currency: Optional[Currency] = None
    ) -> Mapping[Currency, Money]:
        """
        Aggregate current balances per currency for a wallet. If
        `in_currency` is provided, convert all balances to that currency.
        """
        balances = await self._repo.list_wallet_balance(wallet_id)
        if in_currency is None:
            return balances

        async def _convert(m: Money) -> Money:
            if m.currency == in_currency:
                return m
            return await self._fx.convert(m, in_currency)

        tasks = [asyncio.create_task(_convert(m)) for m in balances.values()]
        converted = await asyncio.gather(*tasks)
        return {in_currency: sum((m.amount for m in converted), Decimal("0"))}

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    async def _assert_sufficient_balance(
        self, wallet_id: uuid.UUID, debit_amount: Money
    ) -> None:
        balances = await self._repo.list_wallet_balance(wallet_id)
        available = balances.get(debit_amount.currency, Money(Decimal("0"), debit_amount.currency))
        if available.amount < debit_amount.amount:
            raise InsufficientFundsError(
                f"Wallet {wallet_id} has {available.amount}, "
                f"needs {debit_amount.amount} {debit_amount.currency}"
            )
        logger.debug(
            "Sufficient funds verified for wallet %s (available=%s, requested=%s)",
            wallet_id,
            available.amount,
            debit_amount.amount,
        )


# --------------------------------------------------------------------------- #
# Saga Steps                                                                  #
# --------------------------------------------------------------------------- #


class _PersistEntriesStep:
    def __init__(self, repo: AbstractLedgerRepository, *entries: LedgerEntry):
        self._repo = repo
        self._entries = entries

    async def invoke(self) -> None:
        async with self._repo.transaction():
            await self._repo.save_entries(self._entries)
        logger.debug("Ledger entries persisted: %s", [e.id for e in self._entries])

    async def compensate(self) -> None:
        async with self._repo.transaction():
            await self._repo.mark_reversed(
                [e.id for e in self._entries],
                reason="Saga compensation before commit",
                failed=True,
            )
        logger.debug("Persist saga compensation applied to entries: %s", [e.id for e in self._entries])


class _CommitEntriesStep:
    def __init__(self, repo: AbstractLedgerRepository, *entries: LedgerEntry):
        self._repo = repo
        self._entries = entries

    async def invoke(self) -> None:
        # Local in-memory state transition
        for e in self._entries:
            e.commit()
        async with self._repo.transaction():
            await self._repo.mark_committed([e.id for e in self._entries])
        logger.debug("Ledger entries committed: %s", [e.id for e in self._entries])

    async def compensate(self) -> None:
        async with self._repo.transaction():
            await self._repo.mark_reversed(
                [e.id for e in self._entries],
                reason="Saga compensation post commit",
                failed=True,
            )
        logger.debug("Commit saga compensation executed for entries: %s", [e.id for e in self._entries])


class _PublishEventsStep:
    """
    Final saga step that broadcasts domain events. This step is intentionally
    placed last so that consumers only see COMMITTED entries.
    """

    def __init__(self, publisher: AbstractEventPublisher, *entries: LedgerEntry):
        self._publisher = publisher
        self._entries = entries
        self._published: bool = False

    async def invoke(self) -> None:
        tasks = [
            self._publisher.publish(
                "ledger.entry.committed",
                {
                    "entry_id": str(e.id),
                    "wallet_id": str(e.wallet_id),
                    "type": e.entry_type,
                    "amount": str(e.money.amount),
                    "currency": e.money.currency,
                    "external_txn_id": e.external_txn_id,
                    "timestamp": e.created_at.isoformat(),
                },
            )
            for e in self._entries
        ]
        await asyncio.gather(*tasks)
        self._published = True
        logger.debug("Ledger events published for entries: %s", [e.id for e in self._entries])

    async def compensate(self) -> None:
        if not self._published:
            return
        # Events are immutable; to compensate we emit a "reversed" event
        tasks = [
            self._publisher.publish(
                "ledger.entry.reversed",
                {"entry_id": str(e.id), "reason": "Saga compensation"},
            )
            for e in self._entries
        ]
        await asyncio.gather(*tasks)
        logger.debug("Compensation events emitted for entries: %s", [e.id for e in self._entries])
```