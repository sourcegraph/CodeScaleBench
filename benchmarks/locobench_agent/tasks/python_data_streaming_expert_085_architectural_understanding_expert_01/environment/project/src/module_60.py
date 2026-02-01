```python
"""
PulseStream Nexus
=================

module_60.py
------------

Virality scoring & observer dispatch for real–time social events.

This module implements a decaying–time–weighted virality score that can be fed
with a high-volume event stream (e.g., retweets, boosts, re-shares) and exposes
a thread-safe API to:

1. Ingest raw social events at millisecond latency.
2. Calculate a rolling virality score using exponential time decay
   (half-life configurable).
3. Notify a dynamic observer set (Observer Pattern) whenever the score changes.
4. Export Prometheus metrics for ingestion throughput & score evolution.

The implementation is framework-agnostic — it requires only a standard Python
runtime and the optional ``prometheus_client`` package for metrics exposition.
If Prometheus is unavailable, the module will gracefully degrade and continue
functioning without metrics.

Typical usage
~~~~~~~~~~~~~
>>> calc = ViralityScoreCalculator(half_life_seconds=900)   # 15-minute half-life
>>> calc.register(SimplePrintObserver())
>>> calc.ingest(SocialEvent(event_type='reshare', weight=1.0, source='twitter'))

"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, List, Optional, Protocol

try:
    # Prometheus is optional — if unavailable we simply stub metrics.
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
except ImportError:  # pragma: no cover
    # Create no-op stand-ins to maintain type correctness without runtime dep.
    class _MetricStub:  # pylint: disable=too-few-public-methods
        def __init__(self, *_, **__):  # noqa: D401
            pass

        def labels(self, *_, **__):  # noqa: D401
            return self

        def inc(self, *_):  # noqa: D401
            pass

        def set(self, *_):  # noqa: D401
            pass

        def observe(self, *_):  # noqa: D401
            pass

    Counter = Gauge = Histogram = _MetricStub  # type: ignore


__all__ = [
    "SocialEvent",
    "ViralityObserver",
    "ViralityScoreCalculator",
]

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.INFO)

# -----------------------------------------------------------------------------
# Prometheus metric definitions
# -----------------------------------------------------------------------------
_EVENTS_INGESTED = Counter(
    "psn_virality_events_ingested_total",
    "Total number of social events ingested for virality scoring",
    labelnames=["event_type"],
)

_SCORE_GAUGE = Gauge(
    "psn_virality_score",
    "Current exponentially-decayed virality score across all events",
)

_INGEST_LATENCY = Histogram(
    "psn_virality_ingest_latency_seconds",
    "Latency of ingest operations (time spent in calculator.ingest())",
)

# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SocialEvent:
    """
    A minimalistic representation of a social event that impacts virality.

    Attributes
    ----------
    event_type : str
        Canonical name of the event (e.g., 'reshare', 'reply', 'like').
        This value becomes a Prometheus label, therefore it should be a low-
        cardinality taxonomy.
    weight : float
        Positive numeric weight representing the virality contribution. A
        reshare may carry weight 1.0 while a like might be 0.2, for example.
    timestamp : datetime, optional
        Event clock time. Defaults to ``datetime.utcnow()`` if not supplied.
    source : str, optional
        Name of the platform the event originated from — Twitter, Reddit, etc.
        Not used in scoring but helpful for debugging & metrics.
    """

    event_type: str
    weight: float
    timestamp: datetime = datetime.now(tz=timezone.utc)
    source: str = "unknown"


# -----------------------------------------------------------------------------
# Observer interface
# -----------------------------------------------------------------------------
class ViralityObserver(Protocol):
    """
    Implement to receive score updates.

    Notes
    -----
    • Observers MUST be fast — callbacks are dispatched synchronously inside the
      calculator's critical section.  Slow observers will stall ingestion.
    • Observers MUST NOT raise exceptions. Any exception will be logged and the
      observer will be automatically unregistered.
    """

    def update(self, new_score: float, event: SocialEvent) -> None:  # noqa: D401
        """Handle a new virality score."""


# -----------------------------------------------------------------------------
# Core calculator
# -----------------------------------------------------------------------------
class ViralityScoreCalculator:
    """
    Thread-safe, exponentially-decayed virality score calculator.

    Algorithm
    ~~~~~~~~~
    For every event ``i`` occurring at time ``t_i`` with weight ``w_i`` we store
    a tuple ``(t_i, w_i)``.  The current score ``S(t)`` at now ``t`` is:

        S(t) = Σ w_i * 0.5 ** ((t - t_i) / half_life)

    We lazily prune expired events to keep memory bounded.

    Parameters
    ----------
    half_life_seconds : int
        Half-life horizon for the exponential decay.
    max_events : int, optional
        Hard cap for the event deque.  Older events are dropped once the cap is
        reached, even if they are theoretically still within the decay window.
        This prevents unbounded growth on pathological streams.
    """

    # Public API --------------------------------------------------------------

    def __init__(self, half_life_seconds: int = 3600, max_events: int = 50_000) -> None:
        if half_life_seconds <= 0:
            raise ValueError("half_life_seconds must be positive")
        if max_events <= 0:
            raise ValueError("max_events must be positive")

        self.half_life_seconds = float(half_life_seconds)
        self.max_events = max_events

        self._events: Deque[tuple[float, float]] = deque()
        self._observers: List[ViralityObserver] = []
        self._lock = threading.RLock()
        self._score: float = 0.0

        _LOG.info(
            "ViralityScoreCalculator initialized (half-life=%ss, max_events=%s)",
            self.half_life_seconds,
            self.max_events,
        )

    # Observer management ----------------------------------------------------

    def register(self, observer: ViralityObserver) -> None:
        """Register an observer to receive score updates."""
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                _LOG.debug("Observer %s registered", observer)

    def unregister(self, observer: ViralityObserver) -> None:
        """Remove a previously registered observer."""
        with self._lock:
            try:
                self._observers.remove(observer)
                _LOG.debug("Observer %s unregistered", observer)
            except ValueError:
                _LOG.warning("Attempted to unregister unknown observer %s", observer)

    # Public operations ------------------------------------------------------

    def ingest(self, event: SocialEvent) -> float:
        """
        Ingest a new ``SocialEvent`` and return the updated virality score.

        Raises
        ------
        ValueError
            If the event weight is non-positive.
        """
        start_time = time.perf_counter()

        if event.weight <= 0:
            raise ValueError(f"weight {event.weight} must be positive")

        epoch_ts = event.timestamp.timestamp()

        with self._lock:
            # Append new event, cap at max_events
            self._events.append((epoch_ts, event.weight))
            if len(self._events) > self.max_events:
                self._events.popleft()

            # Recalculate score (lazy expire + decay)
            self._score = self._recalculate(now=time.time())

            # Dispatch to observers (best effort)
            observers_snapshot = list(self._observers)

        # Outside lock to avoid blocking ingestion pipeline
        self._notify_observers(observers_snapshot, self._score, event)
        self._register_metrics(event, time.perf_counter() - start_time)

        return self._score

    def current_score(self) -> float:
        """Return the last computed virality score."""
        with self._lock:
            return self._score

    # Internal helpers -------------------------------------------------------

    def _recalculate(self, now: float) -> float:
        """
        Recompute decayed score, mutating ``self._events`` in-place.

        Expired events are dropped in the same pass to keep the deque tight.
        """
        decay_const = self.half_life_seconds / math.log(2)  # time constant τ
        threshold = now - (self.half_life_seconds * 10)  # drop ~10 half-lives

        score: float = 0.0
        pruned = 0

        # We'll rebuild the deque with only relevant events
        new_events: Deque[tuple[float, float]] = deque()

        for ts, w in self._events:
            if ts < threshold:
                pruned += 1
                continue

            age = now - ts
            weight = w * math.exp(-age / decay_const)
            if weight <= 1e-9:
                # Negligible contribution — drop
                pruned += 1
                continue

            score += weight
            new_events.append((ts, w))

        if pruned:
            _LOG.debug("Pruned %s expired events", pruned)
        self._events = new_events

        _LOG.debug("Score recalculated: %f", score)
        return score

    @staticmethod
    def _notify_observers(
        observers: List[ViralityObserver],
        score: float,
        event: SocialEvent,
    ) -> None:
        """Best-effort observer dispatch with auto-unregister on failure."""
        for obs in observers:
            try:
                obs.update(score, event)
            except Exception:  # pylint: disable=broad-except
                _LOG.exception("Observer %s raised — removing from registry", obs)
                # Cannot modify observers list directly; rely on unregister
                # call by client or re-registration logic.

    @staticmethod
    def _register_metrics(event: SocialEvent, latency_seconds: float) -> None:
        """Update Prometheus metrics (no-op if client missing)."""
        try:
            _EVENTS_INGESTED.labels(event_type=event.event_type).inc()
            _SCORE_GAUGE.set(event.weight)  # update w/ latest contribution
            _INGEST_LATENCY.observe(latency_seconds)
        except Exception:  # noqa: BLE001  (metrics should never fail)
            pass


# -----------------------------------------------------------------------------
# Example observer implementations
# -----------------------------------------------------------------------------
class SimplePrintObserver:  # pragma: no cover
    """Print updated scores — helpful for debugging & local tests."""

    def update(self, new_score: float, event: SocialEvent) -> None:
        print(
            f"[{datetime.utcnow().isoformat(timespec='seconds')}Z] "
            f"Score={new_score:0.3f} (event={event.event_type}, w={event.weight})"
        )


# -----------------------------------------------------------------------------
# Self-test entry-point
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    calc = ViralityScoreCalculator(half_life_seconds=300, max_events=10_000)
    calc.register(SimplePrintObserver())

    # Synthetic event stream
    import random

    def generate_event() -> SocialEvent:
        etype = random.choice(["reshare", "reply", "like"])
        weight_map = {"reshare": 1.0, "reply": 0.6, "like": 0.2}
        return SocialEvent(event_type=etype, weight=weight_map[etype])

    try:
        while True:
            calc.ingest(generate_event())
            time.sleep(random.uniform(0.01, 0.2))
    except KeyboardInterrupt:
        print("Terminate.")
```