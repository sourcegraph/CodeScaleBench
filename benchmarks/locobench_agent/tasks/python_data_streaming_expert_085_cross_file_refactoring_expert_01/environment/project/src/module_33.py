```python
"""
src/module_33.py
PulseStream Nexus – Data-Streaming Platform
-------------------------------------------

This module implements a *stream-processing orchestrator* that conforms to the
Clean-Architecture guidelines in PulseStream Nexus.  Responsibilities include:

1.   Accepting incoming social‐network events from an **async source** (e.g.
     Kafka, Kinesis, Redis Streams, etc.).
2.   Running the events through a configurable **validation & transformation**
     pipeline (Strategy Pattern).
3.   Notifying **observers** about life-cycle events and collecting metrics
     (Observer Pattern).
4.   Emitting the processed records to a downstream *async sink* with retry
     semantics and back-pressure awareness.

The code purposefully avoids concrete broker implementations so that it can be
unit-tested without external dependencies.  Replace `AsyncEventSource` /
`AsyncEventSink` with real adapters in production.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import random
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Callable,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
)

# ------------------------------------------------------------------------------
# 3rd-party (optional) dependencies
# ------------------------------------------------------------------------------

try:
    # Light dependency, safe to embed; used for /metrics endpoint scraping
    from prometheus_client import Counter, Histogram  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – Prometheus is optional
    # Provide no-op shims so that the rest of the module remains functional.
    class _NopMetric:  # pylint: disable=too-few-public-methods
        def __getattr__(self, name: str) -> "_NopMetric":  # noqa: D401
            return self

        def __call__(self, *args: Any, **kwargs: Any) -> "_NopMetric":
            return self

    Counter = Histogram = _NopMetric  # type: ignore


# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("PULSENEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d | %(message)s",
    stream=sys.stdout,
)
logger: logging.Logger = logging.getLogger("pulsestream.module_33")


# ------------------------------------------------------------------------------
# Domain Model
# ------------------------------------------------------------------------------

@dataclasses.dataclass(slots=True, frozen=True)
class SocialEvent:
    """
    An immutable, minimal representation of a social-media interaction captured
    from an upstream broker.  `payload` contains the raw post/tweet, while the
    orchestrator enriches it with additional attributes (e.g., sentiment).
    """

    event_id: str
    platform: str
    user_handle: str
    payload: str
    created_at: datetime

    # Optional enrichment fields
    sentiment: Optional[float] = None
    toxicity: Optional[float] = None
    extra: MutableMapping[str, Any] = dataclasses.field(
        default_factory=dict, hash=False, compare=False
    )

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def to_json(self) -> str:
        """Render the event to a JSON string (for downstream sinks)."""
        return json.dumps(
            dataclasses.asdict(self),
            default=str,  # datetime -> ISO-format
            sort_keys=True,
        )


# ------------------------------------------------------------------------------
# Validation Layer
# ------------------------------------------------------------------------------

class ValidationError(RuntimeError):
    """Raised when an event fails schema or business validation."""


class EventValidator(Protocol):
    """Validator plug-in interface."""

    async def __call__(self, event: SocialEvent) -> None:  # noqa: D401
        ...


class BasicSchemaValidator:
    """
    A minimal schema validator that ensures required fields are present and not
    empty.  In production we leverage *Great Expectations* or *Pydantic*, but
    this lightweight variant keeps the dependency footprint low.
    """

    __slots__ = ("_required",)

    def __init__(self, required: Iterable[str] | None = None) -> None:
        self._required: frozenset[str] = frozenset(required or {"event_id", "payload"})

    async def __call__(self, event: SocialEvent) -> None:
        for field_name in self._required:
            if not getattr(event, field_name, None):
                raise ValidationError(f"Missing required field '{field_name}'")


# ------------------------------------------------------------------------------
# Transformation Strategies
# ------------------------------------------------------------------------------

class Transformer(ABC):
    """
    Base class for all transformation strategies.  Sub-classes must implement
    the `transform` coroutine which receives *and returns* an event so that
    transformers can be chained in a functional pipeline.
    """

    __slots__ = ()

    @abstractmethod
    async def transform(self, event: SocialEvent) -> SocialEvent:  # noqa: D401
        ...


class SentimentTransformer(Transformer):
    """
    Attaches a **sentiment score** to the event.  A real implementation would
    call a fine-tuned ML model; for illustration we use a uniform random value
    in ‑1…1.
    """

    SCORE_RANGE = (-1.0, 1.0)

    async def transform(self, event: SocialEvent) -> SocialEvent:
        score = random.uniform(*self.SCORE_RANGE)  # noqa: S311 – not security-critical
        logger.debug("Sentiment score=%.3f assigned to %s", score, event.event_id)
        return dataclasses.replace(event, sentiment=score)


class ToxicityTransformer(Transformer):
    """
    Adds a *toxicity* probability (0…1).  In production we might query a REST
    model or run a transformer locally; here we replicate latency & accuracy
    trade-offs with time.sleep.
    """

    _MAX_LATENCY_SEC = 0.05

    async def transform(self, event: SocialEvent) -> SocialEvent:
        # Simulate IO/compute latency
        await asyncio.sleep(random.uniform(0, self._MAX_LATENCY_SEC))  # noqa: S311
        toxicity = random.random()  # noqa: S311 – placeholder
        logger.debug("Toxicity score=%.3f assigned to %s", toxicity, event.event_id)
        return dataclasses.replace(event, toxicity=toxicity)


# ------------------------------------------------------------------------------
# Observer Pattern (Metrics / Hooks)
# ------------------------------------------------------------------------------

class PipelineObserver(Protocol):
    """
    Receives notifications about the pipeline life-cycle.  Observers must be
    *non-blocking* – heavy work should be off-loaded to background tasks.
    """

    async def on_event_processed(self, event: SocialEvent) -> None:  # noqa: D401
        ...

    async def on_error(self, exc: BaseException, event: Optional[SocialEvent]) -> None:  # noqa: D401
        ...


class MetricsObserver(PipelineObserver):
    """
    Collects Prometheus metrics.  The observer is instantiated once and reused
    across runs.  If `prometheus_client` is not installed, counters/histograms
    resolve to no-op stubs provided earlier.
    """

    _proc_counter = Counter(
        "pulsenex_events_processed_total",
        "Number of events successfully processed",
        ["platform"],
    )
    _error_counter = Counter(
        "pulsenex_events_error_total",
        "Number of events that errored in the pipeline",
        ["platform", "exception_type"],
    )
    _latency_hist = Histogram(
        "pulsenex_event_processing_latency_seconds",
        "Event processing latency (source -> sink)",
        buckets=(0.001, 0.01, 0.1, 0.5, 1, 2, 5),
    )

    async def on_event_processed(self, event: SocialEvent) -> None:  # noqa: D401
        self._proc_counter.labels(platform=event.platform).inc()

    async def on_error(self, exc: BaseException, event: Optional[SocialEvent]) -> None:  # noqa: D401
        platform = getattr(event, "platform", "unknown")
        self._error_counter.labels(platform=platform, exception_type=type(exc).__name__).inc()


# ------------------------------------------------------------------------------
# Async Event Source / Sink – Adapters
# ------------------------------------------------------------------------------

class AsyncEventSource(Protocol):
    """
    Abstract interface for producing *raw* events.  Implementations wrap Kafka
    consumers, REST endpoints (SSE / WebSocket), or file tails.
    """

    def __aiter__(self) -> AsyncIterator[SocialEvent]:  # noqa: D401
        ...


class InMemoryEventSource:
    """
    Simplistic in-memory source used for smoke tests and sample runs.
    Produces events immediately from a list.
    """

    def __init__(self, events: Sequence[SocialEvent], *, delay: float = 0.0) -> None:
        self._events = events
        self._delay = delay

    async def __aiter__(self) -> AsyncIterator[SocialEvent]:
        for event in self._events:
            await asyncio.sleep(self._delay)
            yield event


class AsyncEventSink(Protocol):
    """Pushes transformed events down-stream (e.g., Kafka producer / DB writer)."""

    async def publish(self, event: SocialEvent) -> None:  # noqa: D401
        ...


class InMemoryEventSink:
    """Stores events in a list for later inspection (unit tests, notebooks)."""

    def __init__(self) -> None:
        self.events: List[SocialEvent] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: SocialEvent) -> None:
        async with self._lock:
            self.events.append(event)
        logger.debug("Event %s published to in-memory sink", event.event_id)


# ------------------------------------------------------------------------------
# Retry / Backoff Helpers
# ------------------------------------------------------------------------------

async def exponential_backoff_retry(
    coro_factory: Callable[[], "asyncio.Future[None]"] | Callable[[], "asyncio.coroutine[Any]"],  # type: ignore[valid-type]
    *,
    max_attempts: int = 5,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    jitter: float = 0.1,
) -> None:
    """
    Executes `coro_factory()` with exponential backoff.  The factory is invoked
    *for each attempt* so that it can capture a fresh closure (e.g., recreate a
    transient network request).  Raises the last caught exception after
    exhausting attempts.
    """

    attempt = 0
    while True:
        try:
            await coro_factory()
            return  # success
        except Exception as exc:  # noqa: BLE001
            attempt += 1
            if attempt >= max_attempts:
                logger.error("Retry exhausted after %d attempts: %s", attempt, exc)
                raise

            delay = min(base_delay * 2**(attempt - 1), max_delay)
            delay += random.uniform(0, jitter)  # noqa: S311
            logger.warning(
                "Attempt %d/%d failed (%s); retrying in %.2fs",
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


# ------------------------------------------------------------------------------
# Pipeline Orchestrator
# ------------------------------------------------------------------------------

class PipelineOrchestrator:
    """
    Glue-code that wires together the whole event-processing flow:

    Source -> validators -> transformers -> sink
             \---------------------------------/
                       observers
    """

    def __init__(
        self,
        *,
        source: AsyncEventSource,
        sink: AsyncEventSink,
        validators: Sequence[EventValidator] | None = None,
        transformers: Sequence[Transformer] | None = None,
        observers: Sequence[PipelineObserver] | None = None,
        concurrency: int = 1,
    ) -> None:
        self._source = source
        self._sink = sink
        self._validators = list(validators or (BasicSchemaValidator(),))
        self._transformers = list(transformers or (SentimentTransformer(), ToxicityTransformer()))
        self._observers = list(observers or (MetricsObserver(),))
        self._concurrency = max(1, concurrency)

        self._latency_hist = MetricsObserver._latency_hist  # Re-use singleton metric

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run_forever(self) -> None:
        """
        Consumes the async event source *indefinitely* (or until the source is
        exhausted), applying transformations, observers, and retries under
        concurrency.  Cancellation propagates gracefully.
        """
        sem = asyncio.Semaphore(self._concurrency)

        async def _worker(event: SocialEvent) -> None:
            async with sem:
                await self._process_event(event)

        tasks: List["asyncio.Task[None]"] = []

        async for event in self._source:
            # We *immediately* spawn a task to avoid blocking the iteration loop
            tasks.append(asyncio.create_task(_worker(event)))

        # Wait for all spawned tasks to finish (propagate first error)
        await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _process_event(self, event: SocialEvent) -> None:
        start_time = time.perf_counter()
        try:
            await self._validate(event)
            for transformer in self._transformers:
                event = await transformer.transform(event)
            await self._publish_with_retry(event)
            await self._notify_processed(event)
        except Exception as exc:  # noqa: BLE001
            await self._notify_error(exc, event)
        finally:
            elapsed = time.perf_counter() - start_time
            self._latency_hist.observe(elapsed)

    async def _validate(self, event: SocialEvent) -> None:
        for validator in self._validators:
            await validator(event)

    async def _publish_with_retry(self, event: SocialEvent) -> None:
        async def _coro() -> None:
            await self._sink.publish(event)

        await exponential_backoff_retry(_coro)

    # Observer helpers -------------------------------------------------
    async def _notify_processed(self, event: SocialEvent) -> None:
        for observer in self._observers:
            with contextlib.suppress(Exception):
                await observer.on_event_processed(event)

    async def _notify_error(self, exc: Exception, event: Optional[SocialEvent]) -> None:
        logger.exception("Error processing event %s: %s", getattr(event, "event_id", "?"), exc)
        for observer in self._observers:
            with contextlib.suppress(Exception):
                await observer.on_error(exc, event)


# ------------------------------------------------------------------------------
# Entry-point (for manual invocation / smoke test)
# ------------------------------------------------------------------------------

async def _demo() -> None:
    """
    Rudimentary demo that processes a handful of randomly generated events in
    memory.  Useful when running `python -m src.module_33`.
    """
    now = datetime.now(timezone.utc)
    sample_events = [
        SocialEvent(
            event_id=f"demo-{i}",
            platform=random.choice(["twitter", "reddit", "mastodon"]),  # noqa: S311
            user_handle=f"user{i}",
            payload=f"Hello world {i}",
            created_at=now,
        )
        for i in range(10)
    ]

    source = InMemoryEventSource(sample_events, delay=0.05)
    sink = InMemoryEventSink()

    orchestrator = PipelineOrchestrator(source=source, sink=sink, concurrency=4)
    await orchestrator.run_forever()

    logger.info("Processed %d events", len(sink.events))
    for ev in sink.events[:3]:
        logger.info("Sample out: %s", ev.to_json())


if __name__ == "__main__":
    try:
        asyncio.run(_demo())
    except KeyboardInterrupt:
        logger.warning("Ctrl-C received, shutting down gracefully…")
    except Exception as unexpected:  # noqa: BLE001
        logger.exception("Fatal error in demo run: %s", unexpected)
        sys.exit(1)
```