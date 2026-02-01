```python
"""
module_12.py
PulseStream Nexus – Observable streaming utilities & observer implementations.

This module implements a lightweight, asyncio–powered Observable/Observer
framework that lives in the “application” layer of the Clean Architecture
stack.  It provides a convenient mechanism for reacting to real-time social
events (e.g., Kafka messages) while keeping business logic decoupled from
I/O or third-party frameworks.

Key abstractions
----------------
1. Event
   Canonical dataclass that represents an incoming social interaction.

2. ObservableStream
   Async producer/consumer wrapper that fans out events to registered
   observers and guarantees back-pressure via an internal asyncio.Queue.

3. BaseObserver (ABC)
   Contract for components interested in stream events.

4. Concrete observers
   • SentimentEnricherObserver  – attaches sentiment score
   • ToxicityFilterObserver     – drops offensive events
   • PrometheusMetricsObserver  – exposes runtime metrics

Design choices
--------------
• Strategy & Observer patterns keep transformations pluggable.
• All heavy/optional dependencies are imported lazily to avoid hard runtime
  requirements (e.g., TextBlob, Detoxify, prometheus_client, etc.).
• Fail-fast validations with Great Expectations can be injected but are
  stubbed here for brevity.
• Graceful degradation: if an enrichment library is missing, the observer
  falls back to a naïve heuristic and logs a warning rather than crashing.

Usage example
-------------
>>> async def main():
...     stream = ObservableStream("twitter_firehose")
...     stream.register(SentimentEnricherObserver())
...     stream.register(ToxicityFilterObserver())
...     stream.register(PrometheusMetricsObserver(namespace="pulse_stream"))
...
...     await stream.start()
...
...     await stream.publish(
...         Event(platform="twitter", payload={"text": "I love OSS 🤗"})
...     )
...
...     await asyncio.sleep(1)   # Let the pipeline flush
...     await stream.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol, Set

# ---------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------

logger = logging.getLogger("pulse_stream.observable")
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s :: %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------
# Data contracts
# ---------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Event:
    """
    An immutable, domain-centric representation of a social event.

    Attributes
    ----------
    id : str
        Globally unique identifier for the event (ULID/UUID).
    ts : datetime
        Timestamp when the event entered the pipeline.
    platform : str
        Source platform (twitter, reddit, mastodon, etc.).
    payload : Dict[str, Any]
        Raw payload emitted by the upstream ingestion layer.
    meta : Dict[str, Any]
        Additional metadata added by observers (sentiment, toxicity, etc.).
    """

    platform: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: datetime = field(default_factory=datetime.utcnow)
    meta: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Functional helpers
    # ------------------------------------------------------------------

    def with_meta(self, **extra: Any) -> "Event":
        """
        Return a copy of the event with additional metadata attached.
        """
        new_meta = {**self.meta, **extra}
        return Event(
            id=self.id,
            ts=self.ts,
            platform=self.platform,
            payload=self.payload,
            meta=new_meta,
        )

    def to_json(self) -> str:
        """
        Serialize the event to a JSON string (isoformat timestamps).
        """
        serializable = {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "platform": self.platform,
            "payload": self.payload,
            "meta": self.meta,
        }
        return json.dumps(serializable, ensure_ascii=False)


# ---------------------------------------------------------
# Observer protocol / exceptions
# ---------------------------------------------------------


class SkipEvent(Exception):
    """
    Raised by an observer to signal that the current event should
    be discarded and not propagated to downstream observers.
    """


class StreamObserver(Protocol):
    """
    Typing protocol that all observers must satisfy.
    """

    async def on_event(self, event: Event) -> Event | None: ...


class BaseObserver(ABC):
    """
    Base class that implements common observer plumbing.
    """

    #: Human-readable name (overridden by subclasses if desired)
    name: str = "base_observer"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} name='{self.name}'>"

    # --- Lifecycle hooks -------------------------------------------------

    async def on_startup(self) -> None:
        """
        Called once when the ObservableStream starts.
        Subclasses may override this to warm up expensive resources.
        """

    async def on_shutdown(self) -> None:
        """
        Called once during stream shutdown for cleanup.
        """

    # --- Event hook ------------------------------------------------------

    @abstractmethod
    async def on_event(self, event: Event) -> Event | None:
        """
        Called for every event.  Must return a (possibly mutated) event,
        or raise SkipEvent to drop the event.
        """


# ---------------------------------------------------------
# Observable stream
# ---------------------------------------------------------


class ObservableStream:
    """
    An asyncio-based event fan-out hub with back-pressure support.
    """

    _sentinel: object = object()

    def __init__(
        self,
        name: str,
        *,
        queue_size: int = 10_000,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._name = name
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=queue_size)
        self._observers: List[BaseObserver] = []
        self._consumer_task: Optional[asyncio.Task[None]] = None
        self._loop = loop or asyncio.get_event_loop()
        self._is_running: bool = False

    # ------------------------------------------------------------------
    # Observer registration
    # ------------------------------------------------------------------

    def register(self, observer: BaseObserver) -> None:
        """
        Add an observer.  Must be called before `start()`.
        """
        if self._is_running:
            raise RuntimeError("Cannot register observers after stream start.")
        logger.info("Registering observer: %s", observer)
        self._observers.append(observer)

    def unregister(self, observer: BaseObserver) -> None:
        """
        Remove an observer mid-flight (experimental).
        """
        with suppress(ValueError):
            self._observers.remove(observer)
            logger.info("Unregistered observer: %s", observer)

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the consumer loop and invoke observer start hooks.
        """
        if self._is_running:
            return

        logger.info("Starting ObservableStream '%s' with %d observers", self._name, len(self._observers))
        self._is_running = True
        # Kick off observer start-up hooks first
        for obs in self._observers:
            with suppress(Exception):
                await obs.on_startup()

        self._consumer_task = self._loop.create_task(self._consume())

    async def stop(self) -> None:
        """
        Signal the consumer loop to exit and drain the queue.
        """
        if not self._is_running:
            return
        logger.info("Stopping ObservableStream '%s' ...", self._name)
        await self._queue.put(self._sentinel)
        if self._consumer_task:
            await self._consumer_task
        # observer clean-up
        for obs in self._observers:
            with suppress(Exception):
                await obs.on_shutdown()
        self._is_running = False
        logger.info("ObservableStream '%s' stopped", self._name)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: Event, *, timeout: Optional[float] = None) -> None:
        """
        Publish an event into the internal queue.

        This call will respect back-pressure by default.  The caller may
        specify `timeout` to fail fast if the queue is full.
        """
        if not self._is_running:
            raise RuntimeError("Stream is not running. Call start() first.")

        try:
            await asyncio.wait_for(self._queue.put(event), timeout=timeout)
        except asyncio.TimeoutError as exc:
            logger.error("Publish timeout (%s) exceeded for event=%s", timeout, event)
            raise exc

    # ------------------------------------------------------------------
    # Internal consumer
    # ------------------------------------------------------------------

    async def _consume(self) -> None:
        """
        Background task that drains the queue and fans out events
        to registered observers.
        """
        while True:
            event = await self._queue.get()
            if event is self._sentinel:
                # drain queue before exit
                if not self._queue.empty():
                    logger.warning(
                        "Sentinel received, but %d events still in queue", self._queue.qsize()
                    )
                break

            await self._dispatch(event)
            self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        """
        Notify observers sequentially; an observer can mutate or drop the event.
        """
        current_event: Event | None = event
        for obs in self._observers:
            if current_event is None:
                break
            try:
                result = await obs.on_event(current_event)
                current_event = result
            except SkipEvent:
                logger.debug("Observer %s skipped event %s", obs, current_event.id)
                return
            except Exception as exc:
                # Swallow exceptions to keep the pipeline alive
                logger.exception("Observer %s failed processing event=%s: %s", obs, current_event.id, exc)

        if current_event is not None:
            logger.debug("Event %s processed successfully", current_event.id)


# ---------------------------------------------------------
# Concrete observers
# ---------------------------------------------------------


class SentimentEnricherObserver(BaseObserver):
    """
    Observer that computes text sentiment and attaches it to the event.

    The implementation prefers `textblob` or `vaderSentiment` if available;
    otherwise it falls back to a trivial positive/negative keyword heuristic.
    """

    name = "sentiment_enricher"

    def __init__(self, field: str = "text") -> None:
        self._field = field
        self._analyzer = None

    async def on_startup(self) -> None:
        # Lazy import to avoid hard dependency
        try:
            from textblob import TextBlob  # type: ignore
            self._analyzer = TextBlob
            logger.info("SentimentEnricherObserver using TextBlob backend")
        except ModuleNotFoundError:
            logger.warning(
                "TextBlob not installed. Falling back to naïve sentiment heuristic."
            )

    async def on_event(self, event: Event) -> Event:
        text = event.payload.get(self._field, "")
        if not text:
            raise SkipEvent()  # No text to process

        score: float
        if self._analyzer:
            # TextBlob returns polarity in range [-1.0, 1.0]
            # Blocking call is negligible for small text; wrap in thread executor if needed.
            score = float(self._analyzer(text).sentiment.polarity)
        else:
            # Naïve heuristic: positive if contains happy emoji/keywords
            positive_markers = {"love", "great", "awesome", "🤗", "❤️"}
            negative_markers = {"hate", "terrible", "awful", "💔", "😡"}
            score = 0.0
            lowered = text.lower()
            if any(w in lowered for w in positive_markers):
                score = 0.5
            elif any(w in lowered for w in negative_markers):
                score = -0.5

        enriched = event.with_meta(sentiment_score=score)
        return enriched


class ToxicityFilterObserver(BaseObserver):
    """
    Drops events deemed toxic based on Detoxify or a keyword blacklist.
    """

    name = "toxicity_filter"

    def __init__(
        self,
        *,
        threshold: float = 0.7,
        blacklist: Optional[Iterable[str]] = None,
    ) -> None:
        self._threshold = threshold
        self._blacklist: Set[str] = set(w.lower() for w in (blacklist or []))
        self._model = None

    async def on_startup(self) -> None:
        try:
            import torch  # noqa: F401
            from detoxify import Detoxify  # type: ignore

            self._model = Detoxify("original")
            logger.info("ToxicityFilterObserver using Detoxify backend")
        except ModuleNotFoundError:
            logger.warning(
                "Detoxify not installed. Falling back to keyword blacklist only."
            )

    async def _predict(self, text: str) -> float:
        if self._model:
            # Detoxify returns a dict of toxicity categories; use 'toxicity'
            preds: Dict[str, float] = self._model.predict(text)
            return float(preds.get("toxicity", 0.0))
        # Keyword heuristic
        if any(bad_word in text.lower() for bad_word in self._blacklist):
            return 1.0
        return 0.0

    async def on_event(self, event: Event) -> Event:
        text: str = event.payload.get("text", "")
        score = await self._predict(text)

        if score >= self._threshold:
            logger.info("Dropping toxic event %s (score=%.2f)", event.id, score)
            raise SkipEvent()

        return event.with_meta(toxicity_score=score)


class PrometheusMetricsObserver(BaseObserver):
    """
    Observer that exports basic stream metrics via Prometheus.
    """

    name = "prometheus_metrics"

    def __init__(self, *, namespace: str = "pulse_stream") -> None:
        self._namespace = namespace
        self._counters_created = False

    async def on_startup(self) -> None:
        try:
            from prometheus_client import Counter, CollectorRegistry, start_http_server  # type: ignore

            self._registry = CollectorRegistry()
            self._total_events = Counter(
                "events_total",
                "Total number of events processed",
                namespace=self._namespace,
                registry=self._registry,
            )
            self._start_time = Counter(
                "start_timestamp",
                "Unix time when the observer started",
                namespace=self._namespace,
                registry=self._registry,
            )
            self._start_time.inc(int(time.time()))
            # Kick off HTTP server in a background thread
            start_http_server(8000, registry=self._registry)
            self._counters_created = True
            logger.info("Prometheus metrics available at :8000/metrics")
        except ModuleNotFoundError:
            logger.warning("prometheus_client not installed. Metrics disabled.")

    async def on_event(self, event: Event) -> Event:
        if self._counters_created:
            self._total_events.inc()
        return event


# ---------------------------------------------------------
# Convenience factory for common observers
# ---------------------------------------------------------


def default_observers() -> List[BaseObserver]:
    """
    Helper that returns a sensible default observer stack used
    by most services.
    """
    return [
        SentimentEnricherObserver(),
        ToxicityFilterObserver(blacklist={"idiot", "stupid"}),
        PrometheusMetricsObserver(),
    ]


# ---------------------------------------------------------
# Test / Demo entry-point (when executed directly)
# ---------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    async def _demo() -> None:
        stream = ObservableStream("demo_stream")
        for obs in default_observers():
            stream.register(obs)

        await stream.start()

        await stream.publish(
            Event(platform="twitter", payload={"text": "I love open source ❤️"})
        )
        await stream.publish(
            Event(platform="twitter", payload={"text": "You are an idiot!"})
        )
        await stream.publish(
            Event(platform="reddit", payload={"text": "OSS is awesome 🔥"})
        )

        # Let events propagate
        await asyncio.sleep(2)
        await stream.stop()

    asyncio.run(_demo())
```