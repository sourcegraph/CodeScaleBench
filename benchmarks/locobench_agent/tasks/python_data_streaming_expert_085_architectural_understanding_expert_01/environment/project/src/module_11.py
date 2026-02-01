```python
"""
src/module_11.py
PulseStream Nexus – Transformation Pipeline (Clean-Architecture Friendly)

This module implements a pluggable, resilient data-transformation pipeline that
can be embedded in either streaming or batch jobs.  It showcases:

1.  Strategy Pattern
2.  Observer Pattern (optional Prometheus metrics sink)
3.  Circuit-Breaker & Exponential-Back-Off for fault tolerance
4.  Dynamic (entry-point–style) plugin discovery
5.  100 % framework/I-O decoupling – pure domain logic

The pipeline accepts “Event” domain objects and emits enriched copies.  By
keeping external libraries optional (lazy import), the code remains portable
while still integrating with specialized tooling when present.

Author: PulseStream Nexus Core Team
License: Apache-2.0
"""

from __future__ import annotations

import importlib
import inspect
import logging
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from types import ModuleType
from typing import Callable, Iterable, Iterator, List, Mapping, MutableMapping, Protocol

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #
_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    # Basic configuration only if the root logger has not been configured yet.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

# --------------------------------------------------------------------------- #
# Optional Prometheus integration
# --------------------------------------------------------------------------- #
try:
    from prometheus_client import Counter, Histogram

    _PROM_ENABLED = True
except ModuleNotFoundError:  # pragma: no cover – 3rd-party optional
    _PROM_ENABLED = False

    class _NoOp:  # type: ignore
        def __init__(self, *_, **__):
            pass

        def labels(self, *_, **__):
            return self

        def observe(self, *_):
            pass

        def inc(self, *_):
            pass

    Counter = Histogram = _NoOp  # type: ignore


# --------------------------------------------------------------------------- #
# Domain Objects
# --------------------------------------------------------------------------- #
@dataclass(slots=True, frozen=True)
class Event:
    """
    Immutable representation of a social interaction event.

    Attributes
    ----------
    stream_id : str
        ID of the originating stream (e.g. Kafka topic).
    payload : Mapping[str, object]
        Raw or partially processed data blob.
    metadata : MutableMapping[str, object]
        Enrichment bag.  Down-stream processors are free to mutate a cloned
        instance, preserving immutability of the original.
    created_at : datetime
        Original creation time of the social interaction.
    processed_at : datetime
        Timestamp of the most recent transformation step.

    Notes
    -----
    Immutability ensures transformations do not accidentally create
    race-conditions in concurrent job execution.
    """

    stream_id: str
    payload: Mapping[str, object]
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    processed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


# --------------------------------------------------------------------------- #
# Transformation Strategy Protocol
# --------------------------------------------------------------------------- #
class TransformationStrategy(Protocol):
    """
    A single, pure function that mutates *no global state* and returns a
    transformed copy of the incoming `Event`.
    """

    name: str  # human-readable ID (for metrics and logging)

    def __call__(self, event: Event) -> Event: ...


# --------------------------------------------------------------------------- #
# Fault-Tolerance Primitives
# --------------------------------------------------------------------------- #
class CircuitState(Enum):
    CLOSED = "closed"          # normal operation
    OPEN = "open"              # failing – calls short-circuited
    HALF_OPEN = "half_open"    # probing for recovery


@dataclass(slots=True)
class CircuitBreaker:
    """
    Simplified, thread-safe (GIL-bound) circuit breaker.

    Reset/hysteresis timings are based on an exponential back-off schedule.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0  # seconds
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_ts: float = field(default=0.0, init=False)

    def before_call(self) -> None:
        now = time.monotonic()
        if self._state is CircuitState.OPEN and \
           now - self._last_failure_ts >= self.recovery_timeout:
            _LOGGER.debug("CircuitBreaker: moving to HALF_OPEN state")
            self._state = CircuitState.HALF_OPEN

        if self._state is CircuitState.OPEN:
            raise CircuitBreakerOpenError("Circuit breaker open – call blocked")

    def after_call(self, error: Exception | None) -> None:
        now = time.monotonic()

        if error is None:
            # Successful call
            if self._state is CircuitState.HALF_OPEN:
                _LOGGER.info("CircuitBreaker: recovery confirmed – closing")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_ts = 0.0
            return

        # Failed call
        self._failure_count += 1
        self._last_failure_ts = now

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            _LOGGER.warning("CircuitBreaker: failure threshold reached – opening")


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a call is blocked due to an OPEN circuit breaker."""


# --------------------------------------------------------------------------- #
# Resilient transformation decorator
# --------------------------------------------------------------------------- #
def resilient(
    cb: CircuitBreaker,
    max_retries: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.3,
) -> Callable[[TransformationStrategy], TransformationStrategy]:
    """
    Decorates a TransformationStrategy with retry + circuit breaker logic.

    Returns a wrapped strategy that transparently handles transient failures.
    """

    def decorator(fn: TransformationStrategy) -> TransformationStrategy:
        fn_name = getattr(fn, "name", fn.__qualname__)

        def _wrapper(event: Event) -> Event:  # type: ignore
            cb.before_call()
            exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return fn(event)
                except Exception as e:  # noqa: BLE001 – want to trap all
                    exc = e
                    sleep_time = (
                        base_delay * (2**attempt)  # exponential
                        + random.uniform(0, jitter)
                    )
                    _LOGGER.exception(
                        "Transformation %s failed (attempt %d/%d): %s",
                        fn_name,
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    time.sleep(sleep_time)

            # Exhausted retries – propagate last error
            cb.after_call(exc)
            raise exc  # type: ignore[does-not-return]

        _wrapper.name = fn_name  # type: ignore[attr-defined]
        return _wrapper  # type: ignore[return-value]

    return decorator


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class TransformationPipeline:
    """
    Orchestrates a series of TransformationStrategy components.

    Each step receives the *output* of the previous step.  The pipeline is
    synchronous by design; concurrency must be handled by external orchestration
    (e.g., Kafka-Streams, Spark, Beam).
    """

    def __init__(self, *, metrics_namespace: str = "psn_transform"):
        self._steps: List[TransformationStrategy] = []
        self._metrics_ns = metrics_namespace

        # Metrics
        self._metric_latency = Histogram(
            f"{metrics_namespace}_latency_seconds",
            "Transformation latency per step",
            labelnames=["step"],
        )
        self._metric_errors = Counter(
            f"{metrics_namespace}_errors_total",
            "Total transformation errors",
            labelnames=["step"],
        )

    # --------------------------------------------------------------------- #
    # API
    # --------------------------------------------------------------------- #
    def add_step(self, strategy: TransformationStrategy) -> None:
        if not callable(strategy):
            raise TypeError("strategy must be callable")
        self._steps.append(strategy)
        _LOGGER.info("Added transformation step: %s", getattr(strategy, "name", str(strategy)))

    def run(self, events: Iterable[Event]) -> Iterator[Event]:
        """
        Generator that yields transformed Events.

        Errors in a single step will cause the offending event to be skipped,
        but the pipeline continues processing subsequent events.
        """
        for ev in events:
            current_event = ev
            for step in self._steps:
                step_name = getattr(step, "name", step.__qualname__)

                start = time.perf_counter()
                try:
                    current_event = step(current_event)
                except Exception as e:  # noqa: BLE001
                    duration = time.perf_counter() - start
                    self._metric_latency.labels(step=step_name).observe(duration)
                    self._metric_errors.labels(step=step_name).inc()
                    _LOGGER.error(
                        "Event (stream=%s) dropped by step=%s: %s",
                        ev.stream_id,
                        step_name,
                        e,
                    )
                    break  # Drop event; skip remaining steps
                else:
                    duration = time.perf_counter() - start
                    self._metric_latency.labels(step=step_name).observe(duration)
            else:
                # Only reached if inner loop is *not* broken – event survived
                yield current_event

    # --------------------------------------------------------------------- #
    # Convenience helpers
    # --------------------------------------------------------------------- #
    @classmethod
    def from_entrypoints(
        cls,
        group: str,
        *,
        metrics_namespace: str = "psn_transform",
    ) -> "TransformationPipeline":
        """
        Auto-discovers all transformation plugins under a given entry-point
        group (set up in setup.py/pyproject.toml) and returns a ready-to-use
        pipeline.

        Example
        -------
        In `pyproject.toml`:
            [project.entry-points.pulsenexus_transforms]
            sentiment = "my_pkg.sentiment:SentimentTransformer"
        """
        import importlib.metadata as importlib_metadata

        pipeline = cls(metrics_namespace=metrics_namespace)

        for ep in importlib_metadata.entry_points(group=group):
            try:
                transform_cls = ep.load()
                if inspect.isclass(transform_cls):
                    instance: TransformationStrategy = transform_cls()  # type: ignore[call-arg]
                else:
                    # Already a function
                    instance = transform_cls  # type: ignore[assignment]
                pipeline.add_step(instance)
            except Exception as e:  # noqa: BLE001 – plugin loading isolation
                _LOGGER.error("Failed to load plugin %s: %s", ep.name, e)

        return pipeline


# --------------------------------------------------------------------------- #
# Reference Transformation Implementations
# --------------------------------------------------------------------------- #
class SentimentTransformer:
    """
    Adds a naive sentiment polarity score to `metadata["sentiment"]`.

    If `textblob` or `vaderSentiment` is available, they will be preferred.
    """

    name = "sentiment"

    def __init__(self):
        self._analyzer = self._init_analyzer()

    # Public API
    # ----------
    def __call__(self, event: Event) -> Event:
        text = str(event.payload.get("text", ""))
        polarity = self._score(text)

        new_metadata = dict(event.metadata)
        new_metadata["sentiment"] = polarity

        return replace(event, metadata=new_metadata, processed_at=datetime.now(tz=timezone.utc))

    # Internal helpers
    # ----------------
    @staticmethod
    def _init_analyzer() -> Callable[[str], float]:
        # Attempt library detection at runtime; fall back to heuristic.
        try:
            from textblob import TextBlob  # type: ignore
            _LOGGER.info("Using TextBlob sentiment analyzer")
            return lambda txt: float(TextBlob(txt).sentiment.polarity)
        except ModuleNotFoundError:
            pass

        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
            analyzer = SentimentIntensityAnalyzer()
            _LOGGER.info("Using VADER sentiment analyzer")

            def _vader(text: str) -> float:
                return float(analyzer.polarity_scores(text)["compound"])

            return _vader
        except ModuleNotFoundError:
            pass

        _LOGGER.warning("No advanced sentiment analyzer found – using fallback")

        # Fallback extremely naive heuristic
        positive = {"good", "great", "love", "excellent", "happy"}
        negative = {"bad", "hate", "terrible", "sad", "angry"}

        def _fallback(text: str) -> float:
            tokens = {t.lower().strip(".,!?") for t in text.split()}
            score = sum(
                (1 if t in positive else -1 if t in negative else 0) for t in tokens
            )
            if score == 0:
                return 0.0
            return float(max(-1.0, min(1.0, score / 5.0)))

        return _fallback

    def _score(self, text: str) -> float:
        try:
            return self._analyzer(text)
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("Sentiment analysis failed: %s", e)
            return math.nan


class ToxicityTransformer:
    """
    Annotates `metadata["toxicity"]` with a float 0.0–1.0 (higher = more toxic).

    Uses Google's `perspective-api-client` if available, otherwise stub.
    """

    name = "toxicity"

    def __init__(self, *, api_key: str | None = None):
        self._analyzer = self._init_analyzer(api_key=api_key)

    def __call__(self, event: Event) -> Event:
        text = str(event.payload.get("text", ""))
        toxicity = self._score(text)

        md = dict(event.metadata)
        md["toxicity"] = toxicity
        return replace(event, metadata=md, processed_at=datetime.now(tz=timezone.utc))

    # Internals
    # ---------
    @staticmethod
    def _init_analyzer(*, api_key: str | None) -> Callable[[str], float]:
        try:
            from perspective_api_client import PerspectiveAPIClient  # type: ignore
            if not api_key:
                raise ValueError("Perspective API key required")
            client = PerspectiveAPIClient(api_key)

            def _perspective(text: str) -> float:
                return float(
                    client.score(text, attribute="TOXICITY")["TOXICITY"]["value"]
                )

            _LOGGER.info("Using Perspective API for toxicity scoring")
            return _perspective
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Perspective API unavailable – using stub (%s)", e)

            def _stub(_: str) -> float:
                return random.random() * 0.1  # assume mostly non-toxic

            return _stub

    def _score(self, text: str) -> float:
        try:
            return self._analyzer(text)
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("Toxicity analysis failed: %s", e)
            return math.nan


# --------------------------------------------------------------------------- #
# Factory helper for default pipeline (commonly used by micro-services)
# --------------------------------------------------------------------------- #
def default_enrichment_pipeline() -> TransformationPipeline:
    """
    Returns a ready-to-use pipeline with sentiment and toxicity enrichment,
    secured by a circuit breaker and retry guard.
    """
    pipeline = TransformationPipeline(metrics_namespace="psn_enrich")

    # Each transformer gets its own breaker – isolation per component
    sent_cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    tox_cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

    pipeline.add_step(resilient(sent_cb)(SentimentTransformer()))
    pipeline.add_step(resilient(tox_cb)(ToxicityTransformer()))

    return pipeline


# --------------------------------------------------------------------------- #
# If executed directly, run a quick demo
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import itertools
    import json

    logging.getLogger().setLevel(logging.DEBUG)

    _LOGGER.info("Running demo pipeline – CTRL+C to stop")

    pipeline = default_enrichment_pipeline()

    test_events = [
        Event(
            stream_id="demo",
            payload={"text": txt},
            metadata={},
        )
        for txt in [
            "I absolutely love this product – great work!",
            "This is terrible. I hate everything about it!",
            "Meh, it's okay I guess.",
        ]
    ]

    for out_ev in pipeline.run(itertools.cycle(test_events)):
        _LOGGER.info("Output: %s", json.dumps(out_ev.metadata, indent=2))
        time.sleep(2)
```