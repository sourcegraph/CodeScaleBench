```python
"""
crowdpay_connect/services/user_service/tests/test_reputation.py

Unit-tests for the gamified reputation engine that powers the social-trust
layer of CrowdPay Connect.  The reputation engine consumes behaviour events
emitted by the Audit-Trail/Event-Sourcing pipeline, converts them into
weighted scores, and persists a running total per user.

The tests below validate that:

1.  Positive behaviour increases reputation.
2.  Negative behaviour decreases reputation.
3.  Duplicate (idempotent) event processing is handled correctly.
4.  Persistence errors are surfaced.
5.  Concurrent processing of the same user does not corrupt state.

Where possible we rely on the concrete production implementation.  Any
external dependency (event-store, repository, etc.) is patched with an
in-memory fake to keep the test deterministic and fast.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from freezegun import freeze_time

# --------------------------------------------------------------------------- #
# Optional fallback definitions
# --------------------------------------------------------------------------- #
#
# When running inside CI the real implementation will be importable.
# During isolated unit-testing (e.g. pylint, type-checking) the stubs keep the
# file self-contained and importable without the full application tree.

try:
    # Production objects
    from crowdpay_connect.services.user_service.reputation import (
        ReputationEvent,
        ReputationService,
        ReputationStoreError,
    )
except ModuleNotFoundError:  # pragma: no cover – fallback only
    # --------------------------------------------------------------------- #
    # Fallback stubs (keep identical public interface)
    # --------------------------------------------------------------------- #
    class ReputationStoreError(RuntimeError):
        """Raised when persisting reputation to the backing store fails."""

    @dataclass(frozen=True, slots=True)
    class ReputationEvent:  # type: ignore
        user_id: uuid.UUID
        type: str
        timestamp: datetime
        metadata: Dict[str, Any]
        version: int

    class ReputationService:  # type: ignore
        """
        Minimal stub: real implementation is provided in application code.
        This stub is only used so that the test module remains importable.
        """

        # Default weights – the real implementation is more sophisticated.
        _EVENT_WEIGHTS: Dict[str, int] = {
            "UPVOTE": 3,
            "PAYMENT_COMPLETED": 5,
            "LATE_PAYMENT": -4,
            "FRAUD_FLAGGED": -50,
        }

        def __init__(self, *, repository: Any, event_store: Any) -> None:
            self._repo = repository
            self._event_store = event_store

        async def calculate_score(self, user_id: uuid.UUID) -> int:
            # Extremely simplified logic for stub-only
            current = await self._repo.get(user_id) or (0, 0)
            current_score, current_version = current
            events: List[ReputationEvent] = await self._event_store.fetch_events(
                user_id, after_version=current_version
            )
            delta = sum(self._EVENT_WEIGHTS[e.type] for e in events)
            new_score = current_score + delta
            new_version = current_version + len(events)
            await self._repo.upsert(user_id, score=new_score, version=new_version)
            return new_score


# --------------------------------------------------------------------------- #
# In-memory fakes
# --------------------------------------------------------------------------- #
class InMemoryReputationRepo:
    """
    Thread-safe(ish) in-memory implementation of the persistence gateway.  It
    intentionally provides just enough behaviour for the tests.
    """

    def __init__(self) -> None:
        self._store: Dict[uuid.UUID, SimpleNamespace] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: uuid.UUID) -> Optional[tuple[int, int]]:
        """
        Return a tuple (score, version) or None when the user does not yet
        have an entry.
        """
        return (
            (record.score, record.version) if (record := self._store.get(user_id)) else None
        )

    async def upsert(self, user_id: uuid.UUID, *, score: int, version: int) -> None:
        """
        Insert or update the record.  A naïve optimistic-locking strategy is
        used to guarantee idempotency during concurrent writes.
        """
        async with self._lock:
            current = self._store.get(user_id)
            if current and version <= current.version:
                # Stale write – ignore (idempotent behaviour)
                return
            self._store[user_id] = SimpleNamespace(score=score, version=version)


class InMemoryEventStore:
    """
    Simulates the audit/event-sourcing store.  Events are appended in-memory
    and can be fetched incrementally via *after_version* semantics.
    """

    def __init__(self) -> None:
        self._events_by_user: Dict[uuid.UUID, List[ReputationEvent]] = {}

    def append(self, *events: ReputationEvent) -> None:
        for e in events:
            self._events_by_user.setdefault(e.user_id, []).append(e)
            # Keep events ordered by version for determinism in tests.
            self._events_by_user[e.user_id].sort(key=lambda ev: ev.version)

    async def fetch_events(
        self, user_id: uuid.UUID, after_version: int = 0
    ) -> List[ReputationEvent]:
        """
        Return all events AFTER the supplied version number.
        """
        return [
            e
            for e in self._events_by_user.get(user_id, [])
            if e.version > after_version
        ]


# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="function")
def user_id() -> uuid.UUID:
    """Return a fresh random user-id per test."""
    return uuid.uuid4()


@pytest.fixture(scope="function")
def repo() -> InMemoryReputationRepo:
    """New, empty repository for every test."""
    return InMemoryReputationRepo()


@pytest.fixture(scope="function")
def event_store() -> InMemoryEventStore:
    """New, empty event-store for every test."""
    return InMemoryEventStore()


@pytest.fixture(scope="function")
def reputation_service(repo: InMemoryReputationRepo, event_store: InMemoryEventStore) -> ReputationService:  # type: ignore
    """Concrete service under test (real or stub)."""
    return ReputationService(repository=repo, event_store=event_store)  # type: ignore


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
_EVENT_SEQUENCES = {
    "positive": [
        ("UPVOTE", 3),
        ("PAYMENT_COMPLETED", 5),
        ("PAYMENT_COMPLETED", 5),
    ],
    "negative": [
        ("FRAUD_FLAGGED", -50),
    ],
}


def _make_events(
    user: uuid.UUID, sequence_name: str, *, start_version: int = 1
) -> List[ReputationEvent]:
    """
    Generate a list of ReputationEvent objects for a user out of a predefined
    sequence template.
    """
    events: List[ReputationEvent] = []
    now = datetime.utcnow()
    for offset, (etype, _) in enumerate(_EVENT_SEQUENCES[sequence_name], start=0):
        events.append(
            ReputationEvent(
                user_id=user,
                type=etype,
                metadata={},
                timestamp=now + timedelta(seconds=offset),
                version=start_version + offset,
            )
        )
    return events


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_positive_behavior_increases_reputation(
    user_id: uuid.UUID,
    reputation_service: ReputationService,  # type: ignore
    event_store: InMemoryEventStore,
) -> None:
    # Arrange
    events = _make_events(user_id, "positive")
    event_store.append(*events)

    # Act
    score = await reputation_service.calculate_score(user_id)

    # Assert
    expected_score = 3 + 5 + 5  # weights defined in default config
    assert score == expected_score, "Reputation should be the sum of weights for all events"


@pytest.mark.asyncio
async def test_duplicate_processing_is_idempotent(
    user_id: uuid.UUID,
    reputation_service: ReputationService,  # type: ignore
    event_store: InMemoryEventStore,
) -> None:
    # Arrange
    events = _make_events(user_id, "positive")
    event_store.append(*events)

    # First run
    first_score = await reputation_service.calculate_score(user_id)
    assert first_score == 13

    # Second run (no new events added) – should be idempotent
    second_score = await reputation_service.calculate_score(user_id)
    assert second_score == first_score, "Score must remain unchanged when no new events exist"


@pytest.mark.asyncio
async def test_negative_behavior_correctly_penalizes(
    user_id: uuid.UUID,
    reputation_service: ReputationService,  # type: ignore
    event_store: InMemoryEventStore,
) -> None:
    # Arrange: good behaviour first, then negative behaviour
    good_events = _make_events(user_id, "positive")
    bad_events = _make_events(user_id, "negative", start_version=len(good_events) + 1)
    event_store.append(*good_events, *bad_events)

    # Act
    final_score = await reputation_service.calculate_score(user_id)

    # Assert
    expected_score = 13 - 50
    assert final_score == expected_score
    assert final_score < 0, "Fraud flag should push the user into negative score territory"


@pytest.mark.asyncio
async def test_repository_failure_is_propagated(
    user_id: uuid.UUID,
    repo: InMemoryReputationRepo,
    event_store: InMemoryEventStore,
) -> None:
    # Arrange
    service = ReputationService(repository=repo, event_store=event_store)  # type: ignore
    event_store.append(*_make_events(user_id, "positive"))

    # Force an error on upsert
    async def _boom(*_a: Any, **_kw: Any) -> None:
        raise ReputationStoreError("database down")  # type: ignore

    repo.upsert = _boom  # type: ignore

    # Act / Assert
    with pytest.raises(ReputationStoreError):
        await service.calculate_score(user_id)


@pytest.mark.asyncio
async def test_concurrent_updates_are_consistent(
    user_id: uuid.UUID,
    reputation_service: ReputationService,  # type: ignore
    event_store: InMemoryEventStore,
    repo: InMemoryReputationRepo,
) -> None:
    # Arrange
    # Split events into two batches that will be processed concurrently
    all_events = _make_events(user_id, "positive")
    first_half, second_half = all_events[:2], all_events[2:]
    event_store.append(*first_half)

    async def _process_first_half() -> None:
        await reputation_service.calculate_score(user_id)  # processes first two events

    async def _process_second_half() -> None:
        # Append remaining events a tiny bit later to mimic real-world lag
        await asyncio.sleep(0.05)
        event_store.append(*second_half)
        await reputation_service.calculate_score(user_id)

    # Act
    await asyncio.gather(_process_first_half(), _process_second_half())

    # Assert – final score in repo must equal sum of all event weights
    final = await repo.get(user_id)
    assert final is not None
    score, version = final
    assert score == 13
    assert version == 3, "Version number should equal number of processed events"


@pytest.mark.asyncio
async def test_time_sensitive_scoring_with_freeze_time(
    user_id: uuid.UUID,
    reputation_service: ReputationService,  # type: ignore
    event_store: InMemoryEventStore,
) -> None:
    """
    Some scoring algorithms can apply decay functions or deadlines.  Demonstrate
    testing such a behaviour by freezing the clock.
    """
    events = _make_events(user_id, "positive")
    with freeze_time(datetime.utcnow() - timedelta(days=365)):
        # Create a very old late-payment event
        old_late_payment = ReputationEvent(
            user_id=user_id,
            type="LATE_PAYMENT",
            metadata={},
            timestamp=datetime.utcnow(),
            version=len(events) + 1,
        )

    # Now add a recent on-time payment
    recent_payment = ReputationEvent(
        user_id=user_id,
        type="PAYMENT_COMPLETED",
        metadata={},
        timestamp=datetime.utcnow(),
        version=len(events) + 2,
    )

    event_store.append(*events, old_late_payment, recent_payment)

    score = await reputation_service.calculate_score(user_id)

    # Expected score = 13 (positive events) -4 (late payment) +5 (recent)
    assert score == 14, "Score must include all events irrespective of age until decay is implemented"
```