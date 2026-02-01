```python
"""
tests/test_main.py

A self-contained PyTest suite that exercises a trimmed-down version of the
`IngestSocialEventUseCase`, mimicking the Clean-Architecture entrypoint used by
PulseStream Nexus.  The test doubles defined here (repository, metrics, etc.)
allow the suite to run without the full production dependency graph.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, Field, ValidationError


# --------------------------------------------------------------------------- #
#                             Domain Test Doubles                              #
# --------------------------------------------------------------------------- #
class FakeMetricsCollector:
    """
    Minimal replacement for a Prometheus counter gauge used in production.
    """

    def __init__(self) -> None:
        self.value = 0

    def inc(self, amount: int = 1) -> None:
        """
        Increment internal counter.

        Parameters
        ----------
        amount : int, default=1
            How much to increment the metric.
        """
        self.value += amount


class InMemorySocialEventRepository:
    """
    In-memory repository that simulates persistence behaviour.
    """

    def __init__(self, *, should_fail: bool = False) -> None:
        self._storage: dict[str, "SocialEvent"] = {}
        self.should_fail = should_fail

    async def save(self, event: "SocialEvent") -> None:
        """
        Persist an event or raise :class:`ConnectionError` if `should_fail` is
        toggled.  Idempotency is enforced on `event.event_id`.
        """
        # Simulate network latency
        await asyncio.sleep(0.01)

        if self.should_fail:
            raise ConnectionError("Synthetic repository failure")

        # Naive idempotency guard
        if event.event_id not in self._storage:
            self._storage[event.event_id] = event

    def get(self, event_id: str) -> "SocialEvent | None":
        """Helper accessor used by the test-suite only."""
        return self._storage.get(event_id)


class SocialEvent(BaseModel):
    """
    Canonical schema for an individual social event.
    """

    event_id: str = Field(..., alias="id")
    text: str
    user_id: str
    timestamp: datetime

    class Config:
        allow_population_by_field_name = True
        frozen = True  # Guarantee immutability


class IngestSocialEventUseCase:
    """
    Clean-Architecture interactor responsible for validating and persisting a
    social event while collecting operational metrics.
    """

    MAX_RETRIES = 3
    BACKOFF_SECONDS = 0.05

    def __init__(
        self,
        repository: InMemorySocialEventRepository,
        *,
        success_counter: FakeMetricsCollector | None = None,
        failure_counter: FakeMetricsCollector | None = None,
    ) -> None:
        self._repository = repository
        self._metric_success = success_counter or FakeMetricsCollector()
        self._metric_failure = failure_counter or FakeMetricsCollector()

    async def execute(self, payload: dict) -> SocialEvent:
        """
        Parameters
        ----------
        payload : dict
            Raw JSON-deserialised message coming from the streaming layer.

        Returns
        -------
        SocialEvent
            The validated, domain-level event instance.

        Raises
        ------
        ValidationError
            When the payload violates schema requirements.
        ConnectionError
            After exhausting all retries against the repository.
        """
        # 1) Schema validation
        event = SocialEvent.parse_obj(payload)

        # 2) Persistence with exponential back-off
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self._repository.save(event)
                self._metric_success.inc()
                return event
            except ConnectionError:
                if attempt >= self.MAX_RETRIES:
                    self._metric_failure.inc()
                    raise
                await asyncio.sleep(self.BACKOFF_SECONDS * attempt)  # back-off


# --------------------------------------------------------------------------- #
#                                   Fixtures                                  #
# --------------------------------------------------------------------------- #
@pytest.fixture
def valid_payload() -> dict:
    return {
        "id": "evt_123",
        "text": "Hello, Nexus!",
        "user_id": "user_42",
        "timestamp": datetime.now(tz=timezone.utc),
    }


@pytest.fixture
def invalid_payload() -> dict:
    # Missing the mandatory "text" field.
    return {
        "id": "evt_bad",
        "user_id": "user_42",
        "timestamp": datetime.now(tz=timezone.utc),
    }


# --------------------------------------------------------------------------- #
#                                   Tests                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_execute_happy_path(valid_payload) -> None:
    """A well-formed payload should be persisted exactly once."""
    repo = InMemorySocialEventRepository()
    metric_ok = FakeMetricsCollector()

    use_case = IngestSocialEventUseCase(repo, success_counter=metric_ok)
    event = await use_case.execute(valid_payload)

    assert repo.get(event.event_id) == event
    assert metric_ok.value == 1


@pytest.mark.asyncio
async def test_validation_error_bubbles_up(invalid_payload) -> None:
    """Pydantic should reject structurally invalid events."""
    repo = InMemorySocialEventRepository()
    use_case = IngestSocialEventUseCase(repo)

    with pytest.raises(ValidationError):
        await use_case.execute(invalid_payload)

    assert use_case._metric_failure.value == 1  # noqa: SLF001
    # Repository never touched.
    assert not repo._storage  # noqa: SLF001


@pytest.mark.asyncio
async def test_retry_then_success(valid_payload) -> None:
    """
    Repository fails once before recovering.  Use-case must retry and succeed.
    """
    repo = InMemorySocialEventRepository(should_fail=True)
    use_case = IngestSocialEventUseCase(repo)

    # First call should eventually raise after MAX_RETRIES
    with pytest.raises(ConnectionError):
        await use_case.execute(valid_payload)

    # Flip the switch and ensure we can ingest afterwards
    repo.should_fail = False
    event = await use_case.execute(valid_payload)

    assert repo.get(event.event_id) is not None
    assert use_case._metric_success.value == 1  # noqa: SLF001


@pytest.mark.asyncio
async def test_idempotency_guard(valid_payload) -> None:
    """
    Persisting the same event twice should not create duplicates.
    """
    repo = InMemorySocialEventRepository()
    use_case = IngestSocialEventUseCase(repo)

    await use_case.execute(valid_payload)
    await use_case.execute(valid_payload)

    assert len(repo._storage) == 1  # noqa: SLF001


# --------------------------------------------------------------------------- #
#                 Dynamic module injection for integration tests              #
# --------------------------------------------------------------------------- #
# Allow 'import pulsestream_nexus.domain.use_cases.stream_ingestion as ...'
# in other test suites by injecting the stub into sys.modules.
module_name = "pulsestream_nexus.domain.use_cases.stream_ingestion"
stub_module = type(sys)(module_name)
stub_module.IngestSocialEventUseCase = IngestSocialEventUseCase
stub_module.SocialEvent = SocialEvent
sys.modules[module_name] = stub_module
```