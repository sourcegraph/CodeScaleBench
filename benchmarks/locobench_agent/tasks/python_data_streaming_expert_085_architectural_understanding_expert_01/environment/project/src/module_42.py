```python
"""
PulseStream Nexus – Module 42
--------------------------------------------------------------------
Virality scoring and observer notification utilities for social-event
streams.  This module lives in the (pure) domain layer – it contains
no direct framework nor I/O code, making it reusable from both the
Kafka micro-services (real-time) and Spark/Beam jobs (batch).

Key concepts
============

1. ViralityStrategy (Strategy Pattern)
   -----------------------------------
   Multiple scoring algorithms can be registered and swapped at run-
   time.  The default strategy implements an exponential time-decay
   model that rewards rapid engagement bursts.

2. ViralitySubject / ViralityObserver (Observer Pattern)
   -----------------------------------------------------
   ‑ A Subject calculates virality scores and broadcasts high-score
     events to subscribed observers (logging, metrics, alerting).

3. Thread-safe design
   ------------------
   Although the module itself is I/O-free, it must be safe to call
   from multiple consumer threads inside a streaming worker.

4. Clean-architecture compliance
   ------------------------------
   Interfaces (Protocols) are defined in this file; concrete adap-
   ters for DB writes, REST calls, etc. should reside elsewhere.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, MutableMapping, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
logger = logging.getLogger("pulse.nexus.module42")
logger.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Prometheus integration (optional, keeps domain independence)
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Histogram = None  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Domain model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SocialEvent:
    """
    Minimal immutable representation of a raw or enriched social-network
    event.  Downstream layers may extend this via type-composition.
    """

    event_id: str
    author_id: str
    created_at: datetime
    likes: int = 0
    replies: int = 0
    reposts: int = 0
    quotes: int = 0

    @property
    def epoch_seconds(self) -> float:
        """Unix timestamp (seconds) – avoids repeated datetime→epoch conversions."""
        return self.created_at.replace(tzinfo=timezone.utc).timestamp()


# --------------------------------------------------------------------------- #
# Strategy interface and registry
# --------------------------------------------------------------------------- #
@runtime_checkable
class ViralityStrategy(Protocol):
    """Interface for pluggable virality-scoring algorithms."""

    def score(self, event: SocialEvent, **context) -> float:  # noqa: D401 – imperative style
        ...


_STRATEGY_REGISTRY: MutableMapping[str, ViralityStrategy] = {}


def register_strategy(name: str, strategy: ViralityStrategy, *, override: bool = False) -> None:
    """
    Register a new virality strategy under a human-friendly key.

    Args:
        name: Public identifier (snake_case recommended).
        strategy: Concrete implementation.
        override: Replace existing entry if present.

    Raises:
        ValueError: If the name already exists and override=False.
    """
    if not override and name in _STRATEGY_REGISTRY:
        raise ValueError(f"Strategy '{name}' is already registered.")
    _STRATEGY_REGISTRY[name] = strategy
    logger.debug("Registered virality strategy '%s' -> %s", name, strategy.__class__.__name__)


def get_strategy(name: str) -> ViralityStrategy:
    """Lookup a previously-registered strategy."""
    try:
        return _STRATEGY_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Strategy '{name}' is not registered.") from exc


# --------------------------------------------------------------------------- #
# Built-in strategies
# --------------------------------------------------------------------------- #
class ExponentialTimeDecay(ViralityStrategy):
    """
    Virality = Σ(weight[action] * count) * exp(-λ * Δt)

    where:
        Δt      – seconds since event creation.
        λ       – decay constant (higher = faster decay).
    """

    # Tunable coefficients – domain experts can adjust via config
    ACTION_WEIGHTS: Dict[str, float] = {
        "likes": 1.0,
        "replies": 2.0,
        "reposts": 3.0,
        "quotes": 2.5,
    }

    def __init__(self, half_life_seconds: float = 3600) -> None:
        if half_life_seconds <= 0:
            raise ValueError("half_life_seconds must be > 0")
        self._lambda = math.log(2) / half_life_seconds

    def score(self, event: SocialEvent, **context) -> float:  # noqa: D401
        age_seconds = max(time.time() - event.epoch_seconds, 0.0)
        engagement = sum(
            getattr(event, action) * weight
            for action, weight in self.ACTION_WEIGHTS.items()
        )
        decay_factor = math.exp(-self._lambda * age_seconds)
        virality = engagement * decay_factor
        logger.debug(
            "ExponentialTimeDecay score for %s: engagement=%s decay=%.4f => %.3f",
            event.event_id,
            engagement,
            decay_factor,
            virality,
        )
        return virality


class SimpleCountStrategy(ViralityStrategy):
    """
    Baseline model: sum of all engagement metrics (no decay).
    """

    def score(self, event: SocialEvent, **context) -> float:  # noqa: D401
        engagement = event.likes + event.replies + event.reposts + event.quotes
        logger.debug("SimpleCount score for %s: %s", event.event_id, engagement)
        return float(engagement)


# Register defaults on import
register_strategy("exp_time_decay", ExponentialTimeDecay())
register_strategy("simple_count", SimpleCountStrategy())

# --------------------------------------------------------------------------- #
# Observer interfaces
# --------------------------------------------------------------------------- #
@runtime_checkable
class ViralityObserver(Protocol):
    """Boundary-layer interface for downstream notification adapters."""

    def notify(self, event: SocialEvent, score: float) -> None:  # noqa: D401 – imperative style
        ...


# --------------------------------------------------------------------------- #
# Subject – thread-safe
# --------------------------------------------------------------------------- #
class ViralitySubject:
    """
    Thread-safe orchestrator that computes scores using a chosen strategy
    and notifies observers when a score exceeds a configurable threshold.
    """

    _histogram: Histogram | None = None

    def __init__(
        self,
        strategy_name: str = "exp_time_decay",
        high_score_threshold: float = 50.0,
        *,
        enable_metrics: bool = True,
        prometheus_namespace: str = "pulsestream",
    ) -> None:
        self._strategy = get_strategy(strategy_name)
        self._high_score_threshold = high_score_threshold
        self._observers: List[ViralityObserver] = []
        self._lock = threading.RLock()

        if enable_metrics and Histogram is not None:
            self._histogram = Histogram(
                name="virality_score",
                documentation="Distribution of computed virality scores",
                namespace=prometheus_namespace,
                unit="score",
                buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, float("inf")),
            )
        logger.debug(
            "ViralitySubject initialized with strategy=%s threshold=%.2f",
            strategy_name,
            high_score_threshold,
        )

    # ----------------------- Observer management ----------------------- #
    def attach(self, observer: ViralityObserver) -> None:
        with self._lock:
            self._observers.append(observer)
            logger.debug("Attached observer: %s", observer.__class__.__name__)

    def detach(self, observer: ViralityObserver) -> None:
        with self._lock:
            self._observers.remove(observer)
            logger.debug("Detached observer: %s", observer.__class__.__name__)

    # ----------------------- Core scoring API -------------------------- #
    def process_event(self, event: SocialEvent, **context) -> float:
        """
        Calculate virality score and dispatch notifications if threshold
        is crossed.

        Returns:
            The computed score.
        """
        score = self._strategy.score(event, **context)

        if self._histogram:
            self._histogram.observe(score)

        if score >= self._high_score_threshold:
            self._notify(event, score)
        return score

    # ----------------------- Internal helpers -------------------------- #
    def _notify(self, event: SocialEvent, score: float) -> None:
        with self._lock:
            observers_snapshot = list(self._observers)
        logger.debug(
            "Notifying %d observers: event=%s score=%.3f",
            len(observers_snapshot),
            event.event_id,
            score,
        )
        for observer in observers_snapshot:
            try:
                observer.notify(event, score)
            except Exception:  # pragma: no cover
                logger.exception(
                    "Observer %s raised while handling event %s",
                    observer.__class__.__name__,
                    event.event_id,
                )


# --------------------------------------------------------------------------- #
# Built-in observers
# --------------------------------------------------------------------------- #
class LoggingObserver(ViralityObserver):
    """Simple observer that logs high-virality events."""

    def notify(self, event: SocialEvent, score: float) -> None:  # noqa: D401
        logger.info(
            "High-virality event detected: id=%s author=%s score=%.2f",
            event.event_id,
            event.author_id,
            score,
        )


class SlidingWindowObserver(ViralityObserver):
    """
    Maintains a recent sliding window of high-score events, useful for
    quick analytics or dashboards.

    Note:
        This does NOT expose thread-safe iteration; external readers must
        acquire their own copy via `snapshot()` to avoid race conditions.
    """

    def __init__(self, window_size: int = 100) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self._window: Deque[tuple[SocialEvent, float]] = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def notify(self, event: SocialEvent, score: float) -> None:  # noqa: D401
        with self._lock:
            self._window.append((event, score))
            logger.debug(
                "SlidingWindowObserver cached event %s (window=%d/%d)",
                event.event_id,
                len(self._window),
                self._window.maxlen,
            )

    def snapshot(self) -> List[tuple[SocialEvent, float]]:
        with self._lock:
            return list(self._window)


class MetricsObserver(ViralityObserver):
    """
    Emits a Prometheus histogram for high-virality events only.

    Using the subject's global histogram for *all* scores is usually
    preferred, but this class offers per-observer customization.
    """

    def __init__(
        self,
        *,
        enable: bool = True,
        prometheus_namespace: str = "pulsestream",
        histogram_name: str = "high_virality_score",
    ) -> None:
        self._enabled = enable and Histogram is not None
        if self._enabled:
            self._histogram = Histogram(
                name=histogram_name,
                documentation="Distribution of high virality scores",
                namespace=prometheus_namespace,
                unit="score",
                buckets=(50, 100, 200, 400, 800, float("inf")),
            )
        else:
            self._histogram = None

    def notify(self, event: SocialEvent, score: float) -> None:  # noqa: D401
        if self._enabled and self._histogram:
            self._histogram.observe(score)


# --------------------------------------------------------------------------- #
# Convenience factory – encourages single shared subject per worker process
# --------------------------------------------------------------------------- #
_default_subject: ViralitySubject | None = None
_default_lock = threading.Lock()


def get_default_subject() -> ViralitySubject:
    """
    Obtain (and lazily instantiate) the process-wide ViralitySubject.

    Using a singleton ensures global histogram metrics are not
    duplicated per component, which would skew Prometheus statistics.
    """
    global _default_subject
    with _default_lock:
        if _default_subject is None:
            _default_subject = ViralitySubject()
            _default_subject.attach(LoggingObserver())
            _default_subject.attach(SlidingWindowObserver())
            _default_subject.attach(MetricsObserver())
        return _default_subject


# --------------------------------------------------------------------------- #
# Self-test (can be executed with `python -m src.module_42`)
# --------------------------------------------------------------------------- #
def _demo() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    subject = get_default_subject()

    # Fabricate events with increasing engagement
    now = datetime.now(tz=timezone.utc)
    for i in range(1, 10):
        ev = SocialEvent(
            event_id=f"EVT{i}",
            author_id=f"USR{i%3}",
            created_at=now,
            likes=i * 5,
            replies=i * 2,
            reposts=i * 3,
            quotes=i,
        )
        time.sleep(0.2)  # simulate stream pacing
        score = subject.process_event(ev)
        print(f"Event {ev.event_id} => {score:.2f}")

    # Show sliding-window content
    window_observer = next(
        o for o in subject._observers if isinstance(o, SlidingWindowObserver)
    )
    print("\nHigh-virality window snapshot:")
    for e, s in window_observer.snapshot():
        print(f" • {e.event_id} score={s:.2f}")


if __name__ == "__main__":  # pragma: no cover
    _demo()
```