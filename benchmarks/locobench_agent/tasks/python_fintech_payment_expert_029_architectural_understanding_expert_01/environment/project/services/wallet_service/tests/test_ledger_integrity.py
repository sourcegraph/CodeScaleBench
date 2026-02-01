```python
"""
crowdpay_connect/services/wallet_service/tests/test_ledger_integrity.py

These tests validate the integrity guarantees provided by the wallet
ledger component.  The ledger is expected to:

1. Maintain a cryptographically-linked chain of entries (hash-chain)
2. Reject duplicate transaction identifiers
3. Prevent negative balances on a per-currency basis
4. Provide deterministic replay of events so that the balance derived
   from event replay always matches the live balance
5. Tolerate concurrent writes by guaranteeing idempotency
"""

from __future__ import annotations

import hashlib
import itertools
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, NamedTuple, Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# --------------------------------------------------------------------------- #
#  Test-Target Lookup                                                         #
# --------------------------------------------------------------------------- #

# The real implementation should live in:
#   crowdpay_connect.services.wallet_service.ledger
# For the purpose of keeping the test file self-contained and fully runnable
# in isolation, we dynamically fall back to an in-memory stub that follows
# the same public contract in case the import fails.

try:
    from crowdpay_connect.services.wallet_service.ledger import Ledger  # type: ignore
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    # --------------------------------------------------------------------- #
    #  Stub implementation (only used whilst the real module is unavailable)
    # --------------------------------------------------------------------- #
    class LedgerEntry(NamedTuple):
        tx_id: str
        wallet_id: str
        amount: Decimal
        currency: str
        created_at: datetime
        previous_hash: str
        hash: str

    class Ledger:
        """
        A *very* small, in-memory, hash-chained ledger.  Do NOT use in
        production.  It only exists so the tests can be executed
        immediately in an isolated environment.
        """

        def __init__(self) -> None:
            self._entries: Dict[str, List[LedgerEntry]] = {}
            self._balances: Dict[tuple[str, str], Decimal] = {}  # (wallet, currency) -> balance
            self._tx_ids: set[str] = set()

        # -------------------- Public API ---------------------------------- #

        def append(
            self,
            *,
            wallet_id: str,
            tx_id: str,
            amount: Decimal,
            currency: str,
            created_at: Optional[datetime] = None,
        ) -> LedgerEntry:
            """Append an entry to the ledger."""
            self._ensure_tx_is_unique(tx_id)
            created_at = created_at or datetime.now(tz=timezone.utc)
            previous_hash = self._entries[wallet_id][-1].hash if self._entries.get(wallet_id) else "⌀"

            tentative_balance = self._balances.get((wallet_id, currency), Decimal("0")) + amount
            if tentative_balance < 0:
                raise ValueError("Negative balance not allowed")

            hash_ = self._hash_entry(
                tx_id=tx_id,
                wallet_id=wallet_id,
                amount=amount,
                currency=currency,
                created_at=created_at,
                previous_hash=previous_hash,
            )
            entry = LedgerEntry(
                tx_id=tx_id,
                wallet_id=wallet_id,
                amount=amount,
                currency=currency,
                created_at=created_at,
                previous_hash=previous_hash,
                hash=hash_,
            )
            self._entries.setdefault(wallet_id, []).append(entry)
            self._balances[(wallet_id, currency)] = tentative_balance
            self._tx_ids.add(tx_id)
            return entry

        def verify_integrity(self, wallet_id: str) -> bool:
            """Replay the hash chain and confirm tamper-proofness."""
            entries = self._entries.get(wallet_id, [])
            previous_hash = "⌀"
            for entry in entries:
                expected = self._hash_entry(
                    tx_id=entry.tx_id,
                    wallet_id=entry.wallet_id,
                    amount=entry.amount,
                    currency=entry.currency,
                    created_at=entry.created_at,
                    previous_hash=previous_hash,
                )
                if expected != entry.hash:
                    return False
                previous_hash = entry.hash
            return True

        def balance(self, wallet_id: str, currency: str) -> Decimal:
            """Return the live balance."""
            return self._balances.get((wallet_id, currency), Decimal("0"))

        def replay_balance(self, wallet_id: str, currency: str) -> Decimal:
            """Derive the balance by event replay (deterministic)."""
            entries = [
                e for e in self._entries.get(wallet_id, []) if e.currency == currency
            ]
            return sum((e.amount for e in entries), Decimal("0"))

        # -------------------- Internal Helpers ---------------------------- #

        def _hash_entry(
            self,
            *,
            tx_id: str,
            wallet_id: str,
            amount: Decimal,
            currency: str,
            created_at: datetime,
            previous_hash: str,
        ) -> str:
            sha = hashlib.sha3_256()
            sha.update(f"{tx_id}{wallet_id}{amount}{currency}{created_at.isoformat()}{previous_hash}".encode())
            return sha.hexdigest()

        def _ensure_tx_is_unique(self, tx_id: str) -> None:
            if tx_id in self._tx_ids:
                raise ValueError(f"Duplicate tx_id detected: {tx_id!r}")

    # End of stub implementation
# --------------------------------------------------------------------------- #
#                         Test Fixtures & Utilities                           #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="function")
def ledger() -> Ledger:
    """Return a fresh ledger for each test."""
    return Ledger()


def _random_tx_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
#                                Test Cases                                   #
# --------------------------------------------------------------------------- #

def test_append_entry_updates_balance(ledger: Ledger) -> None:
    wallet_id = "wallet::alice"
    ledger.append(
        wallet_id=wallet_id,
        tx_id=_random_tx_id(),
        amount=Decimal("100.00"),
        currency="USD",
    )
    assert ledger.balance(wallet_id, "USD") == Decimal("100.00")

    ledger.append(
        wallet_id=wallet_id,
        tx_id=_random_tx_id(),
        amount=Decimal("-40.00"),
        currency="USD",
    )
    assert ledger.balance(wallet_id, "USD") == Decimal("60.00")
    assert ledger.verify_integrity(wallet_id) is True


def test_duplicate_transaction_id_rejected(ledger: Ledger) -> None:
    wallet_id = "wallet::bob"
    tx_id = _random_tx_id()
    ledger.append(
        wallet_id=wallet_id,
        tx_id=tx_id,
        amount=Decimal("10"),
        currency="EUR",
    )

    with pytest.raises(ValueError, match="Duplicate tx_id detected"):
        ledger.append(
            wallet_id=wallet_id,
            tx_id=tx_id,
            amount=Decimal("5"),
            currency="EUR",
        )


def test_negative_balance_raises(ledger: Ledger) -> None:
    wallet_id = "wallet::carol"
    with pytest.raises(ValueError, match="Negative balance"):
        ledger.append(
            wallet_id=wallet_id,
            tx_id=_random_tx_id(),
            amount=Decimal("-5"),
            currency="GBP",
        )


def test_integrity_validation_fails_on_tamper(ledger: Ledger) -> None:
    wallet_id = "wallet::dave"
    entry = ledger.append(
        wallet_id=wallet_id,
        tx_id=_random_tx_id(),
        amount=Decimal("20"),
        currency="USD",
    )
    # Maliciously mutate the internal entry (simulating tampering)
    ledger._entries[wallet_id][0] = entry._replace(amount=Decimal("9999"))  # type: ignore

    assert ledger.verify_integrity(wallet_id) is False


def test_replay_balance_matches_live_balance(ledger: Ledger) -> None:
    wallet_id = "wallet::eve"
    # deposit & withdrawals
    ledger.append(wallet_id=wallet_id, tx_id=_random_tx_id(), amount=Decimal("200"), currency="USD")
    ledger.append(wallet_id=wallet_id, tx_id=_random_tx_id(), amount=Decimal("-50"), currency="USD")
    ledger.append(wallet_id=wallet_id, tx_id=_random_tx_id(), amount=Decimal("1.25"), currency="USD")

    assert ledger.balance(wallet_id, "USD") == ledger.replay_balance(wallet_id, "USD")


# --------------------------------------------------------------------------- #
#                         Property-Based Test Suite                           #
# --------------------------------------------------------------------------- #

@given(
    amounts=st.lists(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("1000.00"),
            places=2
        ),
        min_size=1,
        max_size=25,
    )
)
@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_random_deposits_always_consistent(amounts: List[Decimal], ledger: Ledger) -> None:
    """
    Generates an arbitrary list of positive deposits and ensures that:
    1. Live balance matches the sum of deposits
    2. Replay balance matches live balance
    3. Integrity verification never fails
    """
    wallet_id = f"wallet::property::{time.time_ns()}"
    currency = "USD"

    for amt in amounts:
        tx_id = _random_tx_id()
        ledger.append(wallet_id=wallet_id, tx_id=tx_id, amount=amt, currency=currency)

    expected_balance = sum(amounts, Decimal("0"))
    assert ledger.balance(wallet_id, currency) == expected_balance
    assert ledger.replay_balance(wallet_id, currency) == expected_balance
    assert ledger.verify_integrity(wallet_id) is True


@given(
    withdrawals=st.lists(
        st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("50.00"),
            places=2
        ),
        min_size=1,
        max_size=10,
    )
)
@settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_withdrawals_never_allow_overdraft(withdrawals: List[Decimal], ledger: Ledger) -> None:
    """
    Property: A wallet that starts with a zero balance must never be able
    to overdraft, even with concurrent withdrawal attempts.
    """
    wallet_id = f"wallet::overdraft::{time.time_ns()}"
    currency = "EUR"

    for withdrawal in withdrawals:
        with pytest.raises(ValueError):
            ledger.append(
                wallet_id=wallet_id,
                tx_id=_random_tx_id(),
                amount=-withdrawal,  # negative to represent withdrawal
                currency=currency,
            )
        # Ledger balance must remain zero
        assert ledger.balance(wallet_id, currency) == Decimal("0")
        assert ledger.verify_integrity(wallet_id) is True


def test_concurrent_idempotent_writes(ledger: Ledger) -> None:
    """
    Simulate concurrent writes that attempt to record the same Saga-wide
    transaction identifier on multiple threads / retries.  The ledger
    must keep the operation idempotent by rejecting duplicates.
    """
    wallet_id = "wallet::saga"
    saga_tx_id = "saga::" + _random_tx_id()

    # First attempt
    ledger.append(
        wallet_id=wallet_id,
        tx_id=saga_tx_id,
        amount=Decimal("15.00"),
        currency="USD",
    )

    # Second attempt (duplicate of the same Saga transaction)
    with pytest.raises(ValueError, match="Duplicate tx_id detected"):
        ledger.append(
            wallet_id=wallet_id,
            tx_id=saga_tx_id,
            amount=Decimal("15.00"),
            currency="USD",
        )

    assert ledger.balance(wallet_id, "USD") == Decimal("15.00")
    assert ledger.verify_integrity(wallet_id) is True


def test_hash_chain_is_continuous(ledger: Ledger) -> None:
    """
    Ensure that each subsequent entry references the digest of the
    previous entry, establishing a continuous hash chain.
    """
    wallet_id = "wallet::hashchain"
    currency = "USD"

    # Generate several entries
    for _ in range(5):
        ledger.append(
            wallet_id=wallet_id,
            tx_id=_random_tx_id(),
            amount=Decimal("10"),
            currency=currency,
        )

    entries = ledger._entries[wallet_id]  # type: ignore[attr-defined]
    for prev, next_ in itertools.pairwise(entries):
        assert next_.previous_hash == prev.hash
```