```python
"""
crowdpay_connect/services/transaction_service/tests/test_payment_saga_rollback.py

Integration-style unit tests for the PaymentSaga rollback logic.  The “real”
PaymentSaga, EventBus, and domain-level step classes live in
crowdpay_connect.services.transaction_service.*  – here we create lightweight
test doubles so that the tests remain hermetic and can run without the rest of
the CrowdPay Connect stack being importable.

A NOTE FOR MAINTAINERS:
------------------------------------------------------------------
When the true service-layer objects are available these stubs can be removed
and the imports at the very bottom of the file can be uncommented to make the
tests exercise production code instead of test doubles.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import TracebackType
from typing import Callable, List, MutableMapping, Sequence, Type

import pytest

###############################################################################
# Test doubles – drop-in replacements for the real service implementations.
###############################################################################


class StepFailedException(Exception):
    """Raised by a step when it cannot be completed successfully."""


class EventBus:
    """
    Extremely small in-memory replacement for the production message bus.
    The real bus could be Kafka, NATS, RabbitMQ, etc.
    """

    def __init__(self) -> None:
        self._events: List[tuple[str, dict]] = []

    # --------------------------------------------------------------------- #
    # API used by the Saga orchestrator
    # --------------------------------------------------------------------- #
    def publish(self, event_type: str, **payload) -> None:  # noqa: D401 (imperative mood)
        """
        Publish an event.  In production this would be an asynchronous, durable
        operation.  For the purposes of a test we simply capture it in memory.
        """
        self._events.append((event_type, payload))

    # --------------------------------------------------------------------- #
    # Helper utilities for assertions in test cases
    # --------------------------------------------------------------------- #
    def all(self) -> Sequence[tuple[str, dict]]:
        return tuple(self._events)

    def filter(self, event_type: str) -> Sequence[tuple[str, dict]]:
        """
        Return all events that match a particular type.
        This keeps test assertions tidy.
        """
        return tuple(evt for evt in self._events if evt[0] == event_type)


@dataclass(slots=True)
class TransactionStep:
    """
    A very lightweight representation of a Saga step with injectable execute and
    compensate callables.
    """

    name: str
    _execute: Callable[[], None]
    _compensate: Callable[[], None]

    # ------------------------------------------------------------------ #
    # API consumed by the orchestrator
    # ------------------------------------------------------------------ #
    def execute(self) -> None:
        self._execute()

    def compensate(self) -> None:
        self._compensate()

    # ------------------------------------------------------------------ #
    # String representation is handy when debugging a failed test run.
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:  # noqa: D401 (imperative mood)
        return f"<TransactionStep {self.name!r}>"


class PaymentSaga:
    """
    Simple forward/compensate Saga coordinator that guarantees atomicity across
    multiple TransactionSteps.
    """

    STATUS_PENDING = "PENDING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_ROLLED_BACK = "ROLLED_BACK"

    def __init__(self, steps: Sequence[TransactionStep], bus: EventBus) -> None:
        self._steps: list[TransactionStep] = list(steps)
        self._bus: EventBus = bus
        self._completed: list[TransactionStep] = []
        self._status: str = self.STATUS_PENDING
        self._lock = threading.RLock()  # protects concurrent access

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def status(self) -> str:
        return self._status

    def execute(self) -> None:
        """
        Execute the saga in forward direction.  If any step fails a rollback
        sequence will be initiated automatically in reverse order.
        """
        with self._lock:
            if self._status != self.STATUS_PENDING:
                raise RuntimeError(f"Cannot execute saga in state '{self._status}'")

            try:
                for step in self._steps:
                    step.execute()
                    self._completed.append(step)

                self._status = self.STATUS_COMPLETED
                self._bus.publish("SAGA_COMPLETED")

            except StepFailedException as exc:
                self._rollback(reason=str(exc))
                raise

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _rollback(self, *, reason: str) -> None:
        """Rollback previously executed steps (in reverse order)."""
        for step in reversed(self._completed):
            try:
                step.compensate()
            except Exception as exc:  # pragma: no cover – compensation must not stop rollback
                self._bus.publish(
                    "SAGA_COMPENSATION_FAILED",
                    step=step.name,
                    error=str(exc),
                )
        self._status = self.STATUS_ROLLED_BACK
        self._bus.publish("SAGA_ROLLED_BACK", reason=reason)


###############################################################################
#                                  Fixtures                                   #
###############################################################################


@pytest.fixture()
def in_memory_accounts() -> MutableMapping[str, int]:
    """
    Provide a fresh set of account balances per test case to ensure isolation.
    Monetary values are expressed in minor units (e.g. cents) for accuracy.
    """
    return {"payer": 1_000_00, "crowdpod": 0}  # 1 000.00 units


@pytest.fixture()
def event_bus() -> EventBus:
    """Return a new in-memory EventBus instance for each test."""
    return EventBus()


###############################################################################
#                               Test helpers                                  #
###############################################################################


def _transfer(
    *,
    src: str,
    dst: str,
    amount: int,
    accounts: MutableMapping[str, int],
) -> None:
    """Primitive utility that moves money between two in-memory ledgers."""
    if accounts[src] < amount:
        raise StepFailedException("insufficient funds")
    accounts[src] -= amount
    accounts[dst] += amount


###############################################################################
#                               Test cases                                    #
###############################################################################


def test_payment_saga_rollback_restores_balances(in_memory_accounts, event_bus) -> None:
    """
    Given a Saga that fails mid-flight,
    When the Saga executes,
    Then the ledger returns to its original state
    And a 'SAGA_ROLLED_BACK' event is emitted.
    """
    accounts = in_memory_accounts.copy()
    original_balances = accounts.copy()
    amount = 250_00  # 250.00 units

    compensation_order: list[str] = []

    # ---------------------------------------------------------- #
    # Step implementations used by the Saga under test
    # ---------------------------------------------------------- #
    def debit_payer() -> None:
        _transfer(src="payer", dst="crowdpod", amount=amount, accounts=accounts)

    def debit_payer_comp() -> None:
        compensation_order.append("debit_payer")
        _transfer(src="crowdpod", dst="payer", amount=amount, accounts=accounts)

    def credit_wallet() -> None:
        # In a real system this might be an inter-service call to the wallet
        # microservice.  For testing we touch the same in-memory ledger.
        pass  # nothing to do – funds already credited by first step

    def credit_wallet_comp() -> None:
        compensation_order.append("credit_wallet")
        # No-op in this artificial scenario.

    def convert_currency() -> None:
        # Simulate a downstream failure – e.g. FX service unavailable.
        raise StepFailedException("FX rate provider timeout")

    # No compensation necessary because the step never succeeded.
    def convert_currency_comp() -> None:  # pragma: no cover
        raise AssertionError("Compensate should not be called for failed step")

    steps: Sequence[TransactionStep] = (
        TransactionStep("debit_payer", debit_payer, debit_payer_comp),
        TransactionStep("credit_wallet", credit_wallet, credit_wallet_comp),
        TransactionStep("convert_currency", convert_currency, convert_currency_comp),
    )

    saga = PaymentSaga(steps, bus=event_bus)

    # ------------------------------------------------------------------ #
    # Execute & verify Saga failure
    # ------------------------------------------------------------------ #
    with pytest.raises(StepFailedException):
        saga.execute()

    # ------------------------------------------------------------------ #
    # Assertions
    # ------------------------------------------------------------------ #
    # Ledger balances must be the same as before the Saga started.
    assert accounts == original_balances

    # Compensation must occur in *reverse* order (LIFO) relative to execution.
    assert compensation_order == ["credit_wallet", "debit_payer"]

    # The Saga should end in a rolled-back state and issue one rollback event.
    assert saga.status == PaymentSaga.STATUS_ROLLED_BACK
    rollback_events = event_bus.filter("SAGA_ROLLED_BACK")
    assert len(rollback_events) == 1
    assert rollback_events[0][1]["reason"] == "FX rate provider timeout"


def test_concurrent_sagas_isolated_rollback(in_memory_accounts, event_bus) -> None:
    """
    Ensure that when two Sagas run concurrently a failure in one does *not*
    contaminate the balances manipulated by the other.
    """

    # Scenario: Saga-A will fail and roll back, Saga-B will complete.
    # Both operate on distinct wallets so they must not interfere.
    accounts = in_memory_accounts  # shared across threads

    # ------------------------------- #
    # Build Saga-A (will fail)
    # ------------------------------- #
    saga_a_steps = (
        TransactionStep(
            "A.debit_payer",
            lambda: _transfer(
                src="payer",
                dst="crowdpod",
                amount=100_00,
                accounts=accounts,
            ),
            lambda: _transfer(
                src="crowdpod",
                dst="payer",
                amount=100_00,
                accounts=accounts,
            ),
        ),
        TransactionStep(
            "A.fail_step",
            lambda: (_ for _ in ()).throw(StepFailedException("downstream error")),
            lambda: None,
        ),
    )
    saga_a = PaymentSaga(saga_a_steps, bus=event_bus)

    # ------------------------------- #
    # Build Saga-B (will succeed)
    # ------------------------------- #
    saga_b_steps = (
        TransactionStep(
            "B.debit_payer",
            lambda: _transfer(
                src="payer",
                dst="crowdpod",
                amount=200_00,
                accounts=accounts,
            ),
            lambda: _transfer(
                src="crowdpod",
                dst="payer",
                amount=200_00,
                accounts=accounts,
            ),
        ),
    )
    saga_b = PaymentSaga(saga_b_steps, bus=event_bus)

    # ------------------------------- #
    # Run each Saga in its own thread
    # ------------------------------- #
    def _run(saga: PaymentSaga) -> None:
        try:
            saga.execute()
        except StepFailedException:
            pass  # expected for Saga-A

    threads = [threading.Thread(target=_run, args=(s,)) for s in (saga_a, saga_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
        assert not t.is_alive(), "thread hung during test execution"

    # ------------------------------- #
    # Final ledger assertions
    # ------------------------------- #
    # Expected outcome:
    #   Saga-A rolled back completely (net zero effect)
    #   Saga-B transferred 200.00 units from payer -> crowdpod
    assert accounts["payer"] == 1_000_00 - 200_00
    assert accounts["crowdpod"] == 200_00

    # Saga states and bus notifications
    assert saga_a.status == PaymentSaga.STATUS_ROLLED_BACK
    assert saga_b.status == PaymentSaga.STATUS_COMPLETED
    assert len(event_bus.filter("SAGA_ROLLED_BACK")) >= 1
    assert len(event_bus.filter("SAGA_COMPLETED")) >= 1


###############################################################################
# Uncomment when the production implementations are available in sys.path.
###############################################################################
#
# from crowdpay_connect.services.transaction_service.payment_saga import (
#     PaymentSaga,
#     StepFailedException,
# )
# from crowdpay_connect.services.transaction_service.event_bus import EventBus
#
# IMPORTANT:
#  - Remove the test doubles at the top of the file
#  - Adjust fixtures to use the real DI container or in-memory adapters.
###############################################################################
```