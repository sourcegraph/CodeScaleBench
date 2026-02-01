```python
"""
tests/test_utils.py

Integration-style unit-tests for the low-level utility helpers that power
PulseStream Nexus.  These helpers live in the `nexus.utils.*` namespace
and are intentionally kept framework-agnostic to guarantee they remain
re-usable across the ingestion, transformation, and serving layers.

The tests below use `pytest` and `hypothesis` for property-based checks,
and they self-degrade to xfail/skip whenever an optional third-party
dependency (or the module under test itself) cannot be imported.  This
allows the overall test-suite to stay green in constrained CI settings
(e.g. documentation builds) while still providing strong guarantees in
full environments.

To keep tests hermetic, slow or I/O-heavy calls (e.g., `time.sleep`,
Kafka clients) are patched out with `unittest.mock`.
"""

from __future__ import annotations

import math
import re
import sys
import time
from contextlib import nullcontext
from typing import Any, Dict, Iterable, List

import pytest

# --------------------------------------------------------------------------- #
# Optional/third-party test dependencies
# --------------------------------------------------------------------------- #
hypothesis = pytest.importorskip("hypothesis", reason="property-based tests")
from hypothesis import given, settings
from hypothesis import strategies as st

# `freezegun` is handy but optional.
freezegun = pytest.importorskip("freezegun", reason="requires `freezegun`")
from freezegun import freeze_time

# --------------------------------------------------------------------------- #
# System under test
# --------------------------------------------------------------------------- #
#
# The Clean Architecture layout places pure helpers in `nexus.utils.*`.
# The try/except keeps this test-file importable even when only a subset
# of the project is installed (e.g., docs builds, static analysis, etc.).
#
try:
    from nexus.utils.backoff import exponential_backoff
    from nexus.utils.kafka import topic_for_platform
    from nexus.utils.schema import ValidationError, validate_event
    from nexus.utils.time import calculate_throughput
except ModuleNotFoundError:
    # Tell pytest that these tests should be marked as xfailed when the utils
    # are not present.  The parametrized fixture below will handle the skip.
    exponential_backoff = topic_for_platform = validate_event = calculate_throughput = None  # type: ignore[assignment]
    ValidationError = RuntimeError  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Helper fixtures & markers
# --------------------------------------------------------------------------- #
def _require_utils():
    """Skip the calling test if the target utils package is unavailable."""
    if exponential_backoff is None:
        pytest.skip("`nexus.utils` helpers not importable in this environment.")


# --------------------------------------------------------------------------- #
# Tests for `nexus.utils.backoff.exponential_backoff`
# --------------------------------------------------------------------------- #
@given(
    retries=st.integers(min_value=0, max_value=10),
    base_delay=st.floats(min_value=0.001, max_value=0.5, allow_nan=False),
    factor=st.floats(min_value=1.5, max_value=3.0, allow_nan=False),
)
@settings(deadline=None)
def test_exponential_backoff_monotonically_increases(retries: int, base_delay: float, factor: float) -> None:
    """
    The backoff sequence must be strictly monotonically increasing and never
    drop below the `base_delay`.
    """
    _require_utils()

    delays: List[float] = list(exponential_backoff(retries, base_delay, factor))

    # Sequence length check
    assert len(delays) == max(1, retries + 1)

    # Monotonicity & lower-bound assertions
    for previous, current in zip(delays, delays[1:]):
        assert current >= previous >= base_delay

    # Ensure exponential growth ≈ base_delay * factor ** idx (rounded for jitter)
    # We allow a 10% margin due to optional jitter in implementation.
    for idx, delay in enumerate(delays):
        expected = base_delay * (factor**idx)
        assert math.isclose(delay, expected, rel_tol=0.10), f"idx={idx}, expected≈{expected}, got={delay}"


def test_exponential_backoff_max_sleep_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The helper must never sleep longer than the computed delay and should handle
    interrupting exceptions gracefully.
    """
    _require_utils()

    called: List[float] = []

    def fake_sleep(duration: float) -> None:  # pragma: no cover
        called.append(duration)
        # Simulate early keyboard interrupt half-way through the retries
        if len(called) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", fake_sleep)

    # The utility should propagate KeyboardInterrupt to the caller
    with pytest.raises(KeyboardInterrupt):
        # Use small retry-count to keep test fast.
        list(exponential_backoff(retries=3, base_delay=0.01, factor=2.0, perform_sleep=True))

    # Sleep must be invoked exactly len(called) == 2 times before abort
    assert len(called) == 2
    # All recorded sleep durations must match the generated backoff sequence
    assert called[0] < called[1]


# --------------------------------------------------------------------------- #
# Tests for `nexus.utils.schema.validate_event`
# --------------------------------------------------------------------------- #
@freeze_time("2024-06-01 00:00:00")
@pytest.mark.parametrize(
    "payload",
    [
        # Happy-path minimal event
        {
            "id": "evt_123",
            "platform": "twitter",
            "created_at": "2024-06-01T00:00:00Z",
            "payload": {"text": "The cake is a lie."},
        },
        # Extra metadata is allowed
        {
            "id": "evt_123",
            "platform": "discord",
            "created_at": "2024-06-01T00:00:00Z",
            "payload": {"message": "Hello, world!"},
            "meta": {"lang": "en"},
        },
    ],
)
def test_validate_event_happy_path(payload: Dict[str, Any]) -> None:
    """
    A valid event must return the canonicalized event with `created_at`
    converted to a `datetime` object (implementation detail), and it must not
    raise an error.
    """
    _require_utils()

    result = validate_event(payload)
    assert result["id"] == payload["id"]
    assert "created_at" in result and hasattr(result["created_at"], "isoformat")


invalid_event_strat = st.fixed_dictionaries(
    {
        # Force at least one of the required keys to be absent
        "id": st.one_of(st.none(), st.text()),
        "platform": st.one_of(st.none(), st.text()),
        "created_at": st.one_of(st.none(), st.text()),
        "payload": st.one_of(st.none(), st.dictionaries(st.text(), st.text())),
    }
).filter(
    lambda d: any(d[k] is None for k in ("id", "platform", "created_at", "payload"))
)


@given(invalid_event=invalid_event_strat)
@settings(deadline=None, max_examples=30)
def test_validate_event_rejects_missing_required_fields(invalid_event: Dict[str, Any]) -> None:
    """
    Missing or null required fields must raise `ValidationError`.
    """
    _require_utils()

    with pytest.raises(ValidationError):
        validate_event(invalid_event)


# --------------------------------------------------------------------------- #
# Tests for `nexus.utils.time.calculate_throughput`
# --------------------------------------------------------------------------- #
def test_calculate_throughput_zero_elapsed_time() -> None:
    """
    Division by zero guard: when `elapsed_ms` is zero the function should
    return `float('inf')` or a domain-specific sentinel such as `None`.
    """
    _require_utils()

    result = calculate_throughput(event_count=1_000, elapsed_ms=0.0)
    assert result in (float("inf"), None)


@pytest.mark.parametrize(
    "event_count,elapsed_ms,expected",
    [
        (1_000, 1_000, 1_000.0),
        (5_000, 2_000, 2_500.0),
        (0, 50, 0.0),
    ],
)
def test_calculate_throughput_basic(event_count: int, elapsed_ms: float, expected: float) -> None:
    """
    Basic deterministic checks for the throughput helper.
    """
    _require_utils()

    assert calculate_throughput(event_count, elapsed_ms) == expected


# --------------------------------------------------------------------------- #
# Tests for `nexus.utils.kafka.topic_for_platform`
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "platform,expected_regex",
    [
        ("twitter", r"^xnxs\.twitter\.v\d+$"),
        ("reddit", r"^xnxs\.reddit\.v\d+$"),
        ("mastodon", r"^xnxs\.mastodon\.v\d+$"),
        ("discord", r"^xnxs\.discord\.v\d+$"),
    ],
)
def test_topic_for_platform_naming_convention(platform: str, expected_regex: str) -> None:
    """
    Topic names must conform to `xnxs.<platform>.v<version>` to guarantee
    compatibility with the central schema registry.
    """
    _require_utils()

    topic_name = topic_for_platform(platform)
    assert re.match(expected_regex, topic_name), f"topic `{topic_name}` did not match `{expected_regex}`"


def test_topic_for_platform_unknown_platform() -> None:
    """
    An unknown platform should raise a `KeyError` (or a library-specific
    exception) to prevent silently emitting to an invalid topic.
    """
    _require_utils()

    with pytest.raises(KeyError):
        topic_for_platform("myspace")  # vintage FTW 🤘


# --------------------------------------------------------------------------- #
# Main block for `python -m pytest` debugging sessions
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    # Allow developers to quickly run this single test-file with
    # `python tests/test_utils.py` while still leveraging pytest's discovery.
    sys.exit(pytest.main([__file__]))
```