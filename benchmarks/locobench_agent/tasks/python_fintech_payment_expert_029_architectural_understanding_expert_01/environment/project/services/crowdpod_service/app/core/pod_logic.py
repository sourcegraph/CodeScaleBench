```python
"""
pod_logic.py
Core domain logic for CrowdPod lifecycle management inside the CrowdPay Connect
ecosystem.

This module purposefully isolates business-level operations (create a pod,
manage members, collect / disburse funds) from infrastructural concerns
(persistence, messaging, KYC, FX, etc.) by using small, swappable interfaces.
Doing so keeps the domain model testable and independent while still enabling
rich integrations through dependency injection.

Author: CrowdPay Connect Engineering
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Protocol

# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class CrowdPodError(Exception):
    """Base exception for CrowdPod domain failures."""


class PodNotFound(CrowdPodError):
    pass


class MemberNotFound(CrowdPodError):
    pass


class InsufficientBalance(CrowdPodError):
    pass


class ConcurrentModification(CrowdPodError):
    """Raised when optimistic locking detects a conflicting update."""


class RiskRejected(CrowdPodError):
    """Raised when the real-time risk engine blocks an operation."""


# --------------------------------------------------------------------------- #
# Domain model
# --------------------------------------------------------------------------- #


class PodStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class MemberRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


MONEY_QUANT = Decimal(".01")  # quantization for 2-decimal currencies


@dataclass
class PodMember:
    user_id: uuid.UUID
    role: MemberRole
    joined_at: _dt.datetime = field(default_factory=_dt.datetime.utcnow)


@dataclass
class CrowdPod:
    """Aggregate root for a CrowdPod."""
    pod_id: uuid.UUID
    name: str
    default_currency: str
    created_by: uuid.UUID
    created_at: _dt.datetime = field(default_factory=_dt.datetime.utcnow)
    status: PodStatus = PodStatus.ACTIVE
    members: Dict[uuid.UUID, PodMember] = field(default_factory=dict)
    balance: Decimal = Decimal("0.00")
    version: int = 0  # optimistic locking field

    def add_member(self, user_id: uuid.UUID, role: MemberRole) -> None:
        if user_id in self.members:
            logging.debug("User %s already member of pod %s", user_id, self.pod_id)
            return
        self.members[user_id] = PodMember(user_id=user_id, role=role)
        self._bump_version()
        logging.debug("Added member %s to pod %s with role %s", user_id, self.pod_id, role)

    def remove_member(self, user_id: uuid.UUID) -> None:
        if user_id not in self.members:
            raise MemberNotFound(f"User {user_id} not in pod {self.pod_id}")
        del self.members[user_id]
        self._bump_version()
        logging.debug("Removed member %s from pod %s", user_id, self.pod_id)

    def credit(self, amount: Decimal, currency: str) -> None:
        self._assert_active()
        if currency != self.default_currency:
            raise ValueError("Currency mismatch: pod currency %s, supplied %s", self.default_currency, currency)
        self.balance += amount
        self.balance = self.balance.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        self._bump_version()
        logging.debug("Credited %s %s to pod %s. New balance: %s", currency, amount, self.pod_id, self.balance)

    def debit(self, amount: Decimal, currency: str) -> None:
        self._assert_active()
        if currency != self.default_currency:
            raise ValueError("Currency mismatch: pod currency %s, supplied %s", self.default_currency, currency)
        if self.balance < amount:
            raise InsufficientBalance("Not enough balance in pod.")
        self.balance -= amount
        self.balance = self.balance.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        self._bump_version()
        logging.debug("Debited %s %s from pod %s. New balance: %s", currency, amount, self.pod_id, self.balance)

    def _assert_active(self) -> None:
        if self.status != PodStatus.ACTIVE:
            raise CrowdPodError("Operation allowed only on active pods.")

    def _bump_version(self) -> None:
        self.version += 1


# --------------------------------------------------------------------------- #
# Ports / Interfaces
# --------------------------------------------------------------------------- #


class PodRepository(Protocol):
    """Persistence port (interface)."""

    def get(self, pod_id: uuid.UUID) -> CrowdPod:
        ...

    def save(self, pod: CrowdPod, *, expected_version: int) -> None:
        ...

    def list_by_user(self, user_id: uuid.UUID) -> List[CrowdPod]:
        ...


class RiskEngine(Protocol):
    """Risk & compliance port (interface)."""

    def approve_transaction(
        self, *, pod_id: uuid.UUID, user_id: uuid.UUID, amount: Decimal, currency: str
    ) -> bool:
        ...


class EventBus(Protocol):
    """Event sourcing port (interface)."""

    def publish(self, topic: str, event: dict) -> None:
        ...


class FXService(Protocol):
    """Foreign-exchange conversion port (interface)."""

    def convert(
        self, amount: Decimal, from_currency: str, to_currency: str
    ) -> Decimal:
        ...


# --------------------------------------------------------------------------- #
# Infrastructure reference implementation (in-memory)
# --------------------------------------------------------------------------- #


class InMemoryPodRepository(PodRepository):
    """Thread-safe, in-memory repository (useful for unit testing)."""

    def __init__(self) -> None:
        self._store: Dict[uuid.UUID, CrowdPod] = {}
        self._lock = threading.RLock()

    def get(self, pod_id: uuid.UUID) -> CrowdPod:
        with self._lock:
            if pod_id not in self._store:
                raise PodNotFound(str(pod_id))
            return self._store[pod_id]

    def save(self, pod: CrowdPod, *, expected_version: int) -> None:
        with self._lock:
            stored = self._store.get(pod.pod_id)
            if stored and stored.version != expected_version:
                raise ConcurrentModification(
                    f"Version conflict for pod {pod.pod_id}: {stored.version} != {expected_version}"
                )
            # store a shallow copy to mimic serialization
            self._store[pod.pod_id] = CrowdPod(**pod.__dict__)
            logging.debug("Persisted pod %s (version %d)", pod.pod_id, pod.version)

    def list_by_user(self, user_id: uuid.UUID) -> List[CrowdPod]:
        with self._lock:
            return [
                pod
                for pod in self._store.values()
                if user_id in pod.members
            ]


class NoopEventBus(EventBus):
    def publish(self, topic: str, event: dict) -> None:
        logging.debug("Published event on %s: %s", topic, event)


class StaticFXService(FXService):
    """Naïve FX conversion with static rates (for demo purposes only)."""

    _RATES = {
        ("USD", "EUR"): Decimal("0.91"),
        ("EUR", "USD"): Decimal("1.10"),
    }

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        if from_currency == to_currency:
            return amount
        rate = self._RATES.get((from_currency, to_currency))
        if rate is None:
            raise ValueError(f"Unsupported currency pair {from_currency}->{to_currency}")
        return (amount * rate).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


class DummyRiskEngine(RiskEngine):
    """Approves all transactions below 10 000 for demonstration."""

    def approve_transaction(
        self, *, pod_id: uuid.UUID, user_id: uuid.UUID, amount: Decimal, currency: str
    ) -> bool:
        return amount < Decimal("10000.00")


# --------------------------------------------------------------------------- #
# Application service
# --------------------------------------------------------------------------- #


class PodService:
    """
    Orchestrates high-level CrowdPod workflows while delegating persistence,
    compliance, and messaging to their dedicated components.
    """

    def __init__(
        self,
        *,
        repo: PodRepository,
        risk_engine: RiskEngine,
        event_bus: EventBus,
        fx_service: FXService,
    ) -> None:
        self._repo = repo
        self._risk = risk_engine
        self._events = event_bus
        self._fx = fx_service
        self._logger = logging.getLogger(self.__class__.__name__)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def create_pod(
        self,
        *,
        name: str,
        owner_id: uuid.UUID,
        default_currency: str = "USD",
    ) -> uuid.UUID:
        pod_id = uuid.uuid4()
        pod = CrowdPod(
            pod_id=pod_id,
            name=name,
            default_currency=default_currency,
            created_by=owner_id,
        )
        pod.add_member(owner_id, MemberRole.ADMIN)
        self._repo.save(pod, expected_version=0)  # new pod, expect version 0
        self._events.publish(
            topic="crowdpod.created",
            event={
                "pod_id": str(pod_id),
                "name": name,
                "created_by": str(owner_id),
                "default_currency": default_currency,
                "timestamp": _dt.datetime.utcnow().isoformat(),
            },
        )
        self._logger.info("Created new CrowdPod %s (%s)", name, pod_id)
        return pod_id

    def add_member(
        self, *, pod_id: uuid.UUID, requester_id: uuid.UUID, new_member_id: uuid.UUID, role: MemberRole
    ) -> None:
        pod = self._repo.get(pod_id)
        self._assert_admin(pod, requester_id)
        expected = pod.version
        pod.add_member(new_member_id, role)
        self._repo.save(pod, expected_version=expected)
        self._events.publish(
            topic="crowdpod.member_added",
            event={
                "pod_id": str(pod_id),
                "member_id": str(new_member_id),
                "added_by": str(requester_id),
                "role": role.value,
                "timestamp": _dt.datetime.utcnow().isoformat(),
            },
        )
        self._logger.info(
            "User %s added %s as %s to pod %s", requester_id, new_member_id, role, pod_id
        )

    def contribute(
        self,
        *,
        pod_id: uuid.UUID,
        contributor_id: uuid.UUID,
        amount: Decimal,
        currency: str,
    ) -> None:
        pod = self._repo.get(pod_id)
        if contributor_id not in pod.members:
            raise MemberNotFound("User must be a member to contribute.")
        # risk check
        if not self._risk.approve_transaction(
            pod_id=pod.pod_id,
            user_id=contributor_id,
            amount=amount,
            currency=currency,
        ):
            raise RiskRejected("Contribution blocked by risk engine.")
        # FX conversion if needed
        converted = self._fx.convert(amount, currency, pod.default_currency)
        expected = pod.version
        pod.credit(converted, pod.default_currency)
        self._repo.save(pod, expected_version=expected)
        self._events.publish(
            topic="crowdpod.contribution_made",
            event={
                "pod_id": str(pod_id),
                "contributor_id": str(contributor_id),
                "amount_contributed": str(amount),
                "currency": currency,
                "amount_converted": str(converted),
                "pod_currency": pod.default_currency,
                "timestamp": _dt.datetime.utcnow().isoformat(),
            },
        )
        self._logger.info(
            "Contribution of %s %s (%s %s) made to pod %s by %s",
            amount,
            currency,
            converted,
            pod.default_currency,
            pod_id,
            contributor_id,
        )

    def disburse(
        self,
        *,
        pod_id: uuid.UUID,
        requester_id: uuid.UUID,
        beneficiary_id: uuid.UUID,
        amount: Decimal,
        currency: str,
    ) -> None:
        pod = self._repo.get(pod_id)
        self._assert_admin(pod, requester_id)

        if not self._risk.approve_transaction(
            pod_id=pod.pod_id,
            user_id=beneficiary_id,
            amount=amount,
            currency=currency,
        ):
            raise RiskRejected("Disbursement blocked by risk engine.")
        # Convert debit amount into pod default currency
        converted = self._fx.convert(amount, currency, pod.default_currency)
        expected = pod.version
        pod.debit(converted, pod.default_currency)
        self._repo.save(pod, expected_version=expected)
        # Dispatch event; settlement microservice will pick this up via CQRS
        self._events.publish(
            topic="crowdpod.disbursement_requested",
            event={
                "pod_id": str(pod_id),
                "requested_by": str(requester_id),
                "beneficiary_id": str(beneficiary_id),
                "amount_original": str(amount),
                "currency_original": currency,
                "amount_debited": str(converted),
                "pod_currency": pod.default_currency,
                "timestamp": _dt.datetime.utcnow().isoformat(),
            },
        )
        self._logger.info(
            "Disbursement of %s %s (%s %s) requested from pod %s to %s",
            amount,
            currency,
            converted,
            pod.default_currency,
            pod_id,
            beneficiary_id,
        )

    def get_pod_overview(self, *, pod_id: uuid.UUID) -> dict:
        pod = self._repo.get(pod_id)
        return {
            "pod_id": str(pod.pod_id),
            "name": pod.name,
            "created_by": str(pod.created_by),
            "status": pod.status.value,
            "balance": str(pod.balance),
            "currency": pod.default_currency,
            "member_count": len(pod.members),
        }

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _assert_admin(pod: CrowdPod, user_id: uuid.UUID) -> None:
        member = pod.members.get(user_id)
        if member is None or member.role != MemberRole.ADMIN:
            raise CrowdPodError("User must be admin to perform this action.")


# --------------------------------------------------------------------------- #
# Bootstrapping (example)
# --------------------------------------------------------------------------- #

def _bootstrap() -> PodService:  # pragma: no cover – for manual testing only
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    repo = InMemoryPodRepository()
    risk = DummyRiskEngine()
    events = NoopEventBus()
    fx = StaticFXService()

    return PodService(repo=repo, risk_engine=risk, event_bus=events, fx_service=fx)


if __name__ == "__main__":  # pragma: no cover
    service = _bootstrap()

    owner = uuid.uuid4()
    alice = uuid.uuid4()
    bob = uuid.uuid4()

    pod_id = service.create_pod(name="Summer Trip 2025", owner_id=owner)
    service.add_member(pod_id=pod_id, requester_id=owner, new_member_id=alice, role=MemberRole.MEMBER)
    service.add_member(pod_id=pod_id, requester_id=owner, new_member_id=bob, role=MemberRole.MEMBER)

    service.contribute(
        pod_id=pod_id,
        contributor_id=alice,
        amount=Decimal("150.00"),
        currency="USD",
    )
    service.disburse(
        pod_id=pod_id,
        requester_id=owner,
        beneficiary_id=bob,
        amount=Decimal("50.00"),
        currency="USD",
    )

    print(service.get_pod_overview(pod_id=pod_id))
```
